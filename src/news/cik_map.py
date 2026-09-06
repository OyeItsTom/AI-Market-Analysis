"""The SEC's ticker-to-registrant map, cached locally.

Which symbols Phase 8 supports is decided by this map: a symbol EDGAR can
resolve to a CIK is in scope, and one it cannot is reported as
``UNSUPPORTED`` rather than silently returning nothing, which would imply
coverage that does not exist.

Lifecycle
---------
The map is fetched once and persisted with the metadata needed to refresh it
cheaply and to say how old it is. Later refreshes send ``If-Modified-Since``;
the SEC returns ``304`` when nothing changed, so keeping the map current costs
one small conditional request rather than a 200 KB download. If the network is
unavailable and a stored map exists, the stored map is used -- a news refresh
should not fail because a mapping file could not be re-checked.

What this map is not
--------------------
It is **today's** mapping. It is not evidence that a ticker mapped to the same
registrant at any past date: tickers are reassigned, companies rename, and this
file carries no history. Every association records the map's ``Last-Modified``
so a later reader can see which vintage was used, and ``docs/news.md`` states
plainly that historical ticker identity is not reconstructible in V1. Treating
the current map as historical truth is the one misuse this module cannot
prevent by construction, so it is documented instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .models import NewsError, require_aware, require_symbol

#: Repository root, i.e. the parent of ``src/`` -- mirrors ``src.data.storage``.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NEWS_ROOT = REPO_ROOT / "data" / "news"

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

#: Bumped if the stored envelope's shape changes.
CIK_MAP_SCHEMA_VERSION = 1


class CikMapError(NewsError):
    """Raised when the ticker map cannot be read, parsed or refreshed."""


@dataclass(frozen=True)
class CikMap:
    """A resolved ticker-to-CIK mapping plus the provenance of this copy."""

    entries: Mapping[str, str]
    retrieved_at: datetime
    last_modified: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "entries", dict(self.entries))
        set_(self, "last_modified", str(self.last_modified or "").strip())

    def resolve(self, symbol: str) -> str | None:
        """CIK for ``symbol``, or ``None`` when the SEC does not list it.

        ``None`` means "this registrant is not in the SEC's map", which the
        caller reports as UNSUPPORTED. It never means "no news".
        """
        return self.entries.get(require_symbol(symbol))

    def supports(self, symbol: str) -> bool:
        return self.resolve(symbol) is not None

    @property
    def size(self) -> int:
        return len(self.entries)

    def describe(self) -> str:
        vintage = self.last_modified or "unknown vintage"
        return f"{self.size:,} SEC registrants (source last modified: {vintage})"


def parse_company_tickers(payload: object) -> dict[str, str]:
    """Turn the SEC's ``company_tickers.json`` into ``{TICKER: zero-padded CIK}``.

    The published shape is ``{"0": {"cik_str": 320193, "ticker": "AAPL", ...}}``.
    Malformed entries are skipped rather than aborting the map: one bad row must
    not cost every other registrant.
    """
    if not isinstance(payload, dict):
        raise CikMapError(
            f"company_tickers payload must be a JSON object, got {type(payload).__name__}"
        )
    entries: dict[str, str] = {}
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        if isinstance(cik, bool) or not isinstance(cik, int) or cik <= 0:
            continue
        try:
            entries[require_symbol(ticker)] = f"{cik:010d}"
        except NewsError:
            continue
    if not entries:
        raise CikMapError("company_tickers payload contained no usable registrants")
    return entries


@dataclass(frozen=True)
class CikMapFetch:
    """What a conditional fetch returned."""

    #: ``None`` means the server said 304 and the stored copy is still current.
    payload: object | None
    last_modified: str = ""
    not_modified: bool = False


#: ``(url, last_modified) -> CikMapFetch``. Injected everywhere so no test
#: reaches the network, exactly as the Phase 1 provider injects ``download_fn``.
CikMapFetchFn = Callable[[str, str], CikMapFetch]


class CikMapStore:
    """Reads and writes the cached map under ``data/news/sec/``."""

    def __init__(self, root: str | Path = DEFAULT_NEWS_ROOT) -> None:
        self._root = Path(root)

    @property
    def path(self) -> Path:
        return self._root / "sec" / "company_tickers.json"

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> CikMap | None:
        """The stored map, or ``None`` if there is not a usable one.

        A corrupt cache file returns ``None`` rather than raising: this is a
        rebuildable cache of a public file, not the auditable record store, so
        re-fetching is the right repair. It is the one place in Phase 8 where
        discarding unreadable bytes is correct, and it is limited to this file.
        """
        if not self.exists():
            return None
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if envelope.get("schema_version") != CIK_MAP_SCHEMA_VERSION:
                return None
            return CikMap(
                entries=envelope["entries"],
                retrieved_at=datetime.fromisoformat(envelope["retrieved_at"]),
                last_modified=envelope.get("last_modified", ""),
            )
        except Exception:
            return None

    def write(self, cik_map: CikMap) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": CIK_MAP_SCHEMA_VERSION,
            "retrieved_at": cik_map.retrieved_at.isoformat(),
            "last_modified": cik_map.last_modified,
            "entries": dict(cik_map.entries),
        }
        self.path.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        return self.path


def load_cik_map(
    store: CikMapStore,
    fetch_fn: CikMapFetchFn,
    *,
    now: Callable[[], datetime],
    refresh: bool = True,
) -> CikMap:
    """Return a usable map, refreshing it conditionally when asked.

    Order of preference, and the reasoning for each step:

    1. no stored map -> fetch (there is nothing else to use);
    2. stored map and ``refresh`` -> conditional fetch; ``304`` or a network
       failure keeps the stored copy, because a stale mapping is far better
       than no news at all;
    3. ``refresh=False`` -> use the stored map untouched, so an ordinary news
       request costs the SEC nothing.
    """
    stored = store.read()

    if stored is not None and not refresh:
        return stored

    try:
        fetched = fetch_fn(CIK_MAP_URL, stored.last_modified if stored else "")
    except Exception as exc:
        if stored is not None:
            return stored
        raise CikMapError(f"could not fetch the SEC ticker map: {exc}") from exc

    if fetched.not_modified or fetched.payload is None:
        if stored is not None:
            return stored
        raise CikMapError(
            "the SEC reported the ticker map unmodified, but no local copy exists"
        )

    try:
        entries = parse_company_tickers(fetched.payload)
    except CikMapError:
        # A malformed remote payload must never cost us a working local map:
        # the cache is still valid, and replacing it would turn one bad
        # response into a lasting outage.
        if stored is not None:
            return stored
        raise

    fresh = CikMap(entries=entries, retrieved_at=now(), last_modified=fetched.last_modified)
    store.write(fresh)
    return fresh


__all__ = [
    "CIK_MAP_URL",
    "CIK_MAP_SCHEMA_VERSION",
    "DEFAULT_NEWS_ROOT",
    "REPO_ROOT",
    "CikMapError",
    "CikMap",
    "CikMapFetch",
    "CikMapFetchFn",
    "CikMapStore",
    "parse_company_tickers",
    "load_cik_map",
]
