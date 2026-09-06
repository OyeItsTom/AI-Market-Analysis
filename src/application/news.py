"""Orchestration for the news layer: refresh, persist, query, snapshot.

    symbol -> CIK resolution -> each source independently -> store -> NewsSnapshot

Two independence rules shape this module, and both exist because a refresh
touches two unrelated services.

**Sources are independent.** EDGAR failing must not discard Yahoo's records, and
Yahoo failing must not discard EDGAR's. Each source is fetched, normalized and
persisted on its own, and the refresh reports a per-source outcome. A refresh
where one source worked is reported as ``PARTIAL`` -- never as success, because
telling someone their news is up to date when half of it is missing is the kind
of quiet lie this project is built to avoid.

**Items are independent.** Inside one response, each record is normalized,
validated, classified and stored on its own. A malformed story is rejected and
its siblings are kept. There is no whole-batch validation step, because
tolerating individual failures and claiming batch atomicity cannot both be true.

This module imports no UI framework, and it never touches research or paper
state: a :class:`NewsSnapshot` is deliberately a separate object from a
``ResearchSnapshot``, so nothing here can make a headline look like an input to
an assessment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.news.cik_map import CikMap, CikMapStore, DEFAULT_NEWS_ROOT
from src.news.config import UNCONFIGURED_MESSAGE, SecContact, read_sec_contact
from src.news.models import (
    AvailabilityBasis,
    Document,
    NewsError,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
    require_symbol,
)
from src.news.source import (
    FetchedRecord,
    IngestionCounters,
    ItemOutcome,
    SourceError,
    SourceOutcome,
    SourceResult,
)
from src.news.sources.edgar import SOURCE_NAME as EDGAR_SOURCE
from src.news.sources.yahoo import SOURCE_NAME as YAHOO_SOURCE
from src.news.store import (
    CorruptionKind,
    CorruptLine,
    NewsStore,
    NewsStoreCorruption,
    OnCorruption,
    StorageError,
    StoreIntegrityReport,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RefreshStatus(str, Enum):
    """How a whole refresh went, once every source has reported."""

    #: Every source answered, including any that simply had nothing.
    ALL_OK = "all_ok"

    #: At least one source answered and at least one did not.
    PARTIAL = "partial"

    #: No source answered.
    ALL_FAILED = "all_failed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class QueryMode(str, Enum):
    """Which question a query is asking."""

    #: "What carried a source timestamp at or before T?" Reportorial: it
    #: repeats what sources said without claiming anyone could have seen it.
    SOURCE_TIME = "source_time"

    #: "What can we defensibly say was available by T?" See :class:`TrustMode`.
    STRICT_CAUSAL = "strict_causal"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class TrustMode(str, Enum):
    """How much a strict causal query is willing to take on trust."""

    #: Believe the source's own timestamp. The ordinary research setting: an
    #: EDGAR acceptance instant or a publisher's stated publication time.
    SOURCE_ASSERTED = "source_asserted"

    #: Believe nothing but our own observation. A backfilled record becomes
    #: visible only from when this system actually retrieved it, which makes
    #: history sparse -- that is the honest cost of assuming no source trust.
    SYSTEM_OBSERVED = "system_observed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class SymbolNotSupported(NewsError):
    """Raised when no configured source can cover a symbol."""


@dataclass(frozen=True)
class NewsSnapshot:
    """One coherent view of what is known about a symbol's external information.

    Deliberately separate from ``ResearchSnapshot``. Merging them would imply
    that Phase 3-6 research consumes news, which it does not and must not: no
    field here reaches a hypothesis, an assessment or a paper action.
    """

    symbol: str
    built_at: datetime
    documents: tuple[Document, ...]
    links: tuple[SymbolLink, ...]
    source_results: tuple[SourceResult, ...]
    status: RefreshStatus
    integrity: StoreIntegrityReport | None = None
    cik_map_last_modified: str = ""

    def __post_init__(self) -> None:
        if self.built_at.tzinfo is None or self.built_at.utcoffset() is None:
            raise NewsError("built_at must be timezone-aware")
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "links", tuple(self.links))
        object.__setattr__(self, "source_results", tuple(self.source_results))

    @property
    def official(self) -> tuple[Document, ...]:
        return tuple(d for d in self.documents if d.source_class.is_official)

    @property
    def secondary(self) -> tuple[Document, ...]:
        return tuple(d for d in self.documents if not d.source_class.is_official)

    @property
    def counters(self) -> IngestionCounters:
        """Every source's counters summed.

        Built by summing each declared field rather than naming them one by
        one, so a counter added later cannot be silently dropped from the
        total -- which is exactly what happened to ``associations``.
        """
        from dataclasses import fields as _fields

        totals = {field.name: 0 for field in _fields(IngestionCounters)}
        for result in self.source_results:
            for name in totals:
                totals[name] += getattr(result.counters, name)
        return IngestionCounters(**totals)

    def association_for(self, document: Document) -> SymbolAssociation | None:
        for link in self.links:
            if (link.source, link.source_item_id) == document.item_key:
                return link.association
        return None

    @property
    def has_integrity_warning(self) -> bool:
        return self.integrity is not None and not self.integrity.is_clean


# -- ordering and causal filtering ---------------------------------------


def _sort_key(document: Document) -> tuple[float, str, str]:
    """Newest first, ties broken deterministically by identity.

    ``source_class`` is deliberately absent. Grouping official filings above
    news would reorder time itself, putting a week-old 8-K above this morning's
    story purely because it is official. Class is a filter and a label; it is
    never allowed to distort chronology.
    """
    when = document.available_from or document.retrieved_at
    return (-when.timestamp(), document.source, document.source_item_id)


def _visible_at(
    document: Document, *, as_of: datetime, mode: QueryMode, trust: TrustMode
) -> bool:
    """Whether ``document`` may be shown for a point in time."""
    if mode is QueryMode.SOURCE_TIME:
        source_time = document.source_time
        return source_time is not None and source_time <= as_of

    # STRICT_CAUSAL from here.
    if document.availability_basis is AvailabilityBasis.UNKNOWN:
        # Nothing defensible is known, so it is excluded rather than guessed in.
        return False
    if document.available_from is None:
        return False
    if trust is TrustMode.SYSTEM_OBSERVED:
        # Take the later of what the source claims and when we actually saw it:
        # a filing accepted in 2024 but fetched in 2026 was not knowable to
        # *this system* before 2026.
        return max(document.available_from, document.retrieved_at) <= as_of
    return document.available_from <= as_of


def order_documents(documents: Sequence[Document]) -> tuple[Document, ...]:
    return tuple(sorted(documents, key=_sort_key))


def filter_documents(
    documents: Sequence[Document],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    source_class: SourceClass | None = None,
    as_of: datetime | None = None,
    mode: QueryMode = QueryMode.STRICT_CAUSAL,
    trust: TrustMode = TrustMode.SOURCE_ASSERTED,
) -> tuple[Document, ...]:
    """Apply class, window and causal filters, then order chronologically."""
    selected = []
    for document in documents:
        if source_class is not None and document.source_class is not source_class:
            continue
        when = document.available_from or document.retrieved_at
        if start is not None and when < start:
            continue
        if end is not None and when > end:
            continue
        if as_of is not None and not _visible_at(
            document, as_of=as_of, mode=mode, trust=trust
        ):
            continue
        selected.append(document)
    return order_documents(selected)


# -- the service ---------------------------------------------------------


class NewsService:
    """Manual-refresh orchestration over the configured sources.

    Sources are supplied as ``{name: source}``. The dashboard never builds one
    itself, and nothing here starts a thread, a timer or a scheduler: a refresh
    happens because a human asked for it.
    """

    def __init__(
        self,
        sources: Mapping[str, object],
        store: NewsStore,
        *,
        cik_map: CikMap | None = None,
        now: Clock = _utc_now,
        unconfigured: Mapping[str, str] | None = None,
    ) -> None:
        self._sources = dict(sources)
        self._store = store
        self._cik_map = cik_map
        self._now = now
        self._unconfigured = dict(unconfigured or {})

    # -- refresh ---------------------------------------------------------

    def refresh(self, symbol: str) -> NewsSnapshot:
        """Fetch every source for ``symbol``, persist, and build a snapshot.

        Raises only when the request itself is unusable (an empty symbol, or a
        symbol no configured source covers). A source failing is an outcome,
        not an exception: it is recorded and reported.
        """
        symbol = require_symbol(symbol)
        built_at = self._now()

        results: list[SourceResult] = []
        for name in sorted(self._sources) + sorted(self._unconfigured):
            if name in self._unconfigured:
                results.append(
                    SourceResult(name, SourceOutcome.UNCONFIGURED,
                                 detail=self._unconfigured[name])
                )
                continue
            results.append(self._refresh_one(name, self._sources[name], symbol, built_at))

        if results and all(r.outcome is SourceOutcome.UNSUPPORTED for r in results):
            raise SymbolNotSupported(
                f"No configured source covers {symbol}. Phase 8 supports symbols the "
                "SEC ticker map can resolve; this is a coverage limit, not an "
                "absence of news."
            )

        documents, links, integrity = self._load(symbol)
        return NewsSnapshot(
            symbol=symbol,
            built_at=built_at,
            documents=documents,
            links=links,
            source_results=tuple(results),
            status=_overall_status(results),
            integrity=integrity,
            cik_map_last_modified=self._cik_map.last_modified if self._cik_map else "",
        )

    def _refresh_one(
        self, name: str, source: object, symbol: str, now: datetime
    ) -> SourceResult:
        """One source's whole refresh, isolated from every other source."""
        try:
            records = source.fetch_for_symbol(symbol, now=now)
        except SourceError as exc:
            return SourceResult(name, exc.outcome, detail=exc.message)
        except Exception as exc:  # a source must not take the refresh down
            return SourceResult(
                name, SourceOutcome.FAILED, detail=f"{type(exc).__name__}: {exc}"
            )

        counters = IngestionCounters().with_fetched(len(records))
        if not records:
            return SourceResult(name, SourceOutcome.NO_ITEMS, counters)

        for record in records:
            # Each record independently; one failure never voids its siblings.
            try:
                result = self._store.write_document(record.document)
                counters = counters.plus(result.outcome)
                # Links are written for a duplicate too: the document is
                # unchanged, but "it also came back for this symbol" is a new
                # fact. Only a conflicted or unusable record contributes none.
                if result.outcome is not ItemOutcome.ID_REUSE_CONFLICT:
                    for link in record.links:
                        if self._store.write_link(link):
                            # A new association is a real change even when the
                            # document itself was a duplicate.
                            counters = counters.with_association()
            except Exception:
                counters = counters.plus(ItemOutcome.REJECTED)
        return SourceResult(name, SourceOutcome.SUCCESS, counters)

    # -- query -----------------------------------------------------------

    def _load(
        self, symbol: str
    ) -> tuple[tuple[Document, ...], tuple[SymbolLink, ...], StoreIntegrityReport | None]:
        """Read every source's store, tolerating (and reporting) corruption."""
        documents: list[Document] = []
        links: list[SymbolLink] = []
        corrupt: list = []
        names = set(self._sources) | set(self._unconfigured)
        for name in sorted(names):
            # A stored row this build cannot decode -- a future schema_version,
            # say -- is an integrity problem to report, not a reason to fail a
            # refresh and lose the sources that are perfectly readable.
            try:
                stored, report = self._store.latest_documents(
                    name, on_corruption=OnCorruption.REPORT
                )
                corrupt.extend(report.corrupt_lines)
            except StorageError as exc:
                corrupt.append(_unreadable(self._store.documents_path(name), exc))
                stored = ()
            try:
                stored_links, link_report = self._store.read_links(
                    name, on_corruption=OnCorruption.REPORT
                )
                corrupt.extend(link_report.corrupt_lines)
            except StorageError as exc:
                corrupt.append(_unreadable(self._store.associations_path(name), exc))
                stored_links = ()

            wanted = {
                (link.source, link.source_item_id)
                for link in stored_links
                if link.symbol == symbol
            }
            links.extend(link for link in stored_links if link.symbol == symbol)
            documents.extend(item for item in stored if item.item_key in wanted)

        integrity = StoreIntegrityReport(tuple(corrupt)) if corrupt else None
        return order_documents(documents), tuple(links), integrity

    def documents_for_symbol(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        source_class: SourceClass | None = None,
        as_of: datetime | None = None,
        mode: QueryMode = QueryMode.STRICT_CAUSAL,
        trust: TrustMode = TrustMode.SOURCE_ASSERTED,
    ) -> tuple[Document, ...]:
        documents, _, _ = self._load(require_symbol(symbol))
        return filter_documents(
            documents, start=start, end=end, source_class=source_class,
            as_of=as_of, mode=mode, trust=trust,
        )

    def official_filings(self, symbol: str, **kwargs) -> tuple[Document, ...]:
        return self.documents_for_symbol(
            symbol, source_class=SourceClass.OFFICIAL_FILING, **kwargs
        )

    def latest_documents(self, symbol: str, *, limit: int = 20) -> tuple[Document, ...]:
        return self.documents_for_symbol(symbol)[:limit]


def _unreadable(path, exc: Exception) -> CorruptLine:
    """Describe a file this build cannot decode as an integrity finding."""
    return CorruptLine(
        path=str(path),
        line_number=0,
        byte_offset=0,
        kind=CorruptionKind.CORRUPT_INTERIOR,
        detail=f"{type(exc).__name__}: {exc}"[:200],
    )


def _overall_status(results: Sequence[SourceResult]) -> RefreshStatus:
    if not results:
        return RefreshStatus.ALL_FAILED
    healthy = [result for result in results if result.is_healthy]
    if len(healthy) == len(results):
        return RefreshStatus.ALL_OK
    if healthy:
        return RefreshStatus.PARTIAL
    return RefreshStatus.ALL_FAILED


def build_service(
    *,
    store_root: str | Path = DEFAULT_NEWS_ROOT,
    edgar_fetch_fn=None,
    yahoo_fetch_fn=None,
    cik_map: CikMap | None = None,
    environ: Mapping[str, str] | None = None,
    now: Clock = _utc_now,
    refresh_cik_map: bool = True,
) -> NewsService:
    """Assemble the service the dashboard uses.

    EDGAR is included only when a contact address is configured *and* a ticker
    map is available; otherwise it is registered as ``UNCONFIGURED`` so the
    interface can say which source is switched off and why, while Yahoo carries
    on working.
    """
    from src.news.sources.edgar import EdgarFilingsSource
    from src.news.sources.yahoo import YahooNewsSource, default_fetch_fn

    store = NewsStore(store_root)
    sources: dict[str, object] = {}
    unconfigured: dict[str, str] = {}

    contact = read_sec_contact(dict(environ) if environ is not None else None)
    edgar_fetch = edgar_fetch_fn or _default_edgar_fetch
    if cik_map is None and contact is not None:
        # Explicit refresh only: read the cached map, and fetch it just once if
        # there is none. Construction itself never reaches the network.
        try:
            cik_map = load_cik_map(
                CikMapStore(store_root),
                lambda url, last_modified: _fetch_cik_map(edgar_fetch, contact, url,
                                                          last_modified),
                now=now,
                refresh=refresh_cik_map,
            )
        except Exception:
            cik_map = None

    if contact is None:
        unconfigured[EDGAR_SOURCE] = UNCONFIGURED_MESSAGE
    elif cik_map is None:
        unconfigured[EDGAR_SOURCE] = (
            "EDGAR filings are switched off because the SEC ticker map could not "
            "be loaded. It is fetched once on the first news refresh."
        )
    else:
        sources[EDGAR_SOURCE] = EdgarFilingsSource(
            fetch_fn=edgar_fetch, cik_map=cik_map, contact=contact,
        )

    sources[YAHOO_SOURCE] = YahooNewsSource(
        fetch_fn=yahoo_fetch_fn or default_fetch_fn
    )
    return NewsService(sources, store, cik_map=cik_map, now=now, unconfigured=unconfigured)


def _default_edgar_fetch(url: str, user_agent: str):
    """The real EDGAR fetch, imported lazily so tests never load it."""
    from src.news.sources.edgar import default_fetch_fn

    return default_fetch_fn(url, user_agent)


def _fetch_cik_map(fetch, contact, url: str, last_modified: str):
    """Adapt the EDGAR fetch signature to the CIK map's conditional protocol.

    The SEC's ticker file is a plain document rather than a conditional API in
    this client, so a successful fetch is always treated as fresh content.
    """
    from src.news.cik_map import CikMapFetch

    return CikMapFetch(payload=fetch(url, contact.user_agent), last_modified=last_modified)


__all__ = [
    "RefreshStatus",
    "QueryMode",
    "TrustMode",
    "NewsSnapshot",
    "NewsService",
    "SymbolNotSupported",
    "build_service",
    "order_documents",
    "filter_documents",
]
