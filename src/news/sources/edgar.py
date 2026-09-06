"""SEC EDGAR filings -- the official tier.

EDGAR is the only source in Phase 8 whose symbol association is a **source
fact**: the SEC itself maps a registrant's CIK to a ticker, so a filing returned
for ``AAPL`` genuinely is Apple's filing. That is why filings are the primary
tier and news is not.

Timing, stated exactly
----------------------
``acceptanceDateTime`` is the instant EDGAR **accepted** the document. It is
recorded as :attr:`AvailabilityBasis.SOURCE_EVENT` and is never described as
proven public dissemination: acceptance and dissemination are close in practice
but the source guarantees only the former, and a research system must not
upgrade an assertion into a proof. ``filingDate`` is a different fact again -- a
calendar date, rolled to the next business day for filings accepted after the
cut-off -- so both are kept.

Access discipline
-----------------
The SEC asks for a contact header and publishes a 10 requests/second ceiling.
This adapter targets roughly 2/s, times out at 30 seconds, retries at most twice
with bounded backoff, and stops immediately on ``403``/``429`` rather than
retrying into a block. The filing **body is never fetched** -- only the
submissions index -- and the document URL is *constructed* from trusted
identifiers rather than taken from a payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from ..cik_map import CikMap
from ..config import SecContact
from ..identity import filing_content_hash
from ..models import (
    AvailabilityBasis,
    EventType,
    NewsError,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
    require_symbol,
)
from ..source import FetchedRecord, SourceError, SourceOutcome
from ..validation import safe_text, validate_source_timestamp, validate_url

SOURCE_NAME = "edgar"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

#: Conservative: the published ceiling is 10/s, and nothing here needs speed.
REQUESTS_PER_SECOND = 2.0
TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

#: ``(url, user_agent) -> parsed JSON``. Injected so tests never touch the
#: network -- the same seam Phase 1 uses for market data.
EdgarFetchFn = Callable[[str, str], Any]


@dataclass(frozen=True)
class EdgarFilingsSource:
    """Fetches a registrant's recent filings from the EDGAR submissions index."""

    fetch_fn: EdgarFetchFn
    cik_map: CikMap
    contact: SecContact
    name: str = SOURCE_NAME
    source_class: SourceClass = SourceClass.OFFICIAL_FILING
    max_items: int = 40

    def fetch_for_symbol(
        self, symbol: str, *, now: datetime
    ) -> tuple[FetchedRecord, ...]:
        symbol = require_symbol(symbol)
        cik = self.cik_map.resolve(symbol)
        if cik is None:
            raise SourceError(
                SourceOutcome.UNSUPPORTED,
                f"{symbol} is not in the SEC ticker map, so EDGAR has no filings for "
                "it. This is a coverage limit, not an absence of news.",
            )

        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            payload = self.fetch_fn(url, self.contact.user_agent)
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(
                SourceOutcome.FAILED, f"EDGAR request failed: {type(exc).__name__}"
            ) from exc

        rows = _recent_rows(payload)
        if not rows:
            return ()

        records: list[FetchedRecord] = []
        for row in rows[: self.max_items]:
            record = self._normalize(row, symbol=symbol, cik=cik, now=now)
            # A malformed filing is dropped on its own; its siblings are fine.
            if record is not None:
                records.append(record)
        return tuple(records)

    def _normalize(
        self, row: Mapping[str, Any], *, symbol: str, cik: str, now: datetime
    ) -> FetchedRecord | None:
        try:
            accession = safe_text(row.get("accessionNumber"), maximum=64)
            form = safe_text(row.get("form"), maximum=64)
            if not accession or not form:
                return None

            acceptance = _parse_edgar_instant(row.get("acceptanceDateTime"))
            acceptance = validate_source_timestamp(
                acceptance, now=now, label="acceptanceDateTime"
            )

            filing_date = safe_text(row.get("filingDate"), maximum=32)
            report_date = safe_text(row.get("reportDate"), maximum=32)
            primary = safe_text(row.get("primaryDocument"), maximum=256)
            items = tuple(
                part.strip()
                for part in safe_text(row.get("items"), maximum=256).split(",")
                if part.strip()
            )

            numeric_cik = str(int(cik))
            bare_accession = accession.replace("-", "")
            # Constructed from identifiers we trust, never taken from a payload
            # URL: a link we build cannot be pointed somewhere else by a source.
            document_url = (
                ARCHIVE_URL.format(cik=numeric_cik, accession=bare_accession,
                                   document=primary)
                if primary
                else FILING_INDEX_URL.format(cik=numeric_cik, accession=bare_accession)
            )
            document_url = validate_url(document_url, label="primary_document_url")
            index_url = validate_url(
                FILING_INDEX_URL.format(cik=numeric_cik, accession=bare_accession),
                label="canonical_url",
            )

            if acceptance is not None:
                available_from, basis = acceptance, AvailabilityBasis.SOURCE_EVENT
            else:
                # No acceptance instant: we know only that we have it now.
                available_from, basis = now, AvailabilityBasis.SYSTEM_OBSERVED

            headline = f"{form} filed by {self.cik_map_title(symbol)}".strip()
            filing = OfficialFiling(
                source=self.name,
                source_item_id=accession,
                source_class=SourceClass.OFFICIAL_FILING,
                cik=cik,
                form=form,
                headline=headline,
                canonical_url=index_url,
                primary_document_url=document_url,
                retrieved_at=now,
                availability_basis=basis,
                filing_date=filing_date,
                report_date=report_date,
                items=items,
                source_event_time=acceptance,
                available_from=available_from,
                event_type=EventType.FILING,
                content_hash=filing_content_hash(
                    cik=cik,
                    form=form,
                    items=items,
                    filing_date=filing_date,
                    report_date=report_date,
                    primary_document_url=document_url,
                    source_event_time=acceptance,
                ),
            )
        except NewsError:
            return None
        except Exception:
            return None

        link = SymbolLink(
            source=self.name,
            source_item_id=filing.source_item_id,
            symbol=symbol,
            # The SEC maps this CIK to this ticker: a source fact, not a guess.
            association=SymbolAssociation.VERIFIED_SOURCE,
            retrieved_at=now,
            queried_symbol=symbol,
            cik_map_last_modified=self.cik_map.last_modified,
        )
        return FetchedRecord(filing, (link,))

    def cik_map_title(self, symbol: str) -> str:
        """Only the symbol: the submissions index names the registrant, but a
        headline is not the place to restate it from a different source."""
        return symbol


def _recent_rows(payload: object) -> list[dict[str, Any]]:
    """Turn EDGAR's column-oriented ``filings.recent`` into row dicts."""
    if not isinstance(payload, Mapping):
        raise SourceError(SourceOutcome.FAILED, "EDGAR response was not a JSON object")
    filings = payload.get("filings")
    if not isinstance(filings, Mapping):
        return []
    recent = filings.get("recent")
    if not isinstance(recent, Mapping):
        return []
    forms = recent.get("form")
    if not isinstance(forms, Sequence) or isinstance(forms, (str, bytes)):
        return []
    count = len(forms)
    columns = {
        key: value
        for key, value in recent.items()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        and len(value) == count
    }
    return [{key: value[index] for key, value in columns.items()} for index in range(count)]


#: The only hosts this client will contact. A URL that does not start with one
#: of these is refused before any socket is opened, so a value that somehow
#: reached the fetcher from a payload cannot become a request.
ALLOWED_URL_PREFIXES = (
    "https://data.sec.gov/",
    "https://www.sec.gov/",
)


def default_fetch_fn(
    url: str,
    user_agent: str,
    *,
    opener=None,
    sleep=None,
    now=None,
) -> Any:
    """Fetch one SEC JSON document under the documented access policy.

    This is where :data:`REQUESTS_PER_SECOND`, :data:`TIMEOUT_SECONDS` and
    :data:`MAX_RETRIES` are actually applied -- the adapter above only decides
    *what* to ask for.

    * the URL must be one of :data:`ALLOWED_URL_PREFIXES`; anything else raises
      before a connection is attempted
    * requests are paced to :data:`REQUESTS_PER_SECOND`
    * ``403``/``429`` stop immediately -- the SEC is telling us to back off, and
      retrying into a block is how a client gets banned
    * every other failure is retried at most :data:`MAX_RETRIES` times with
      bounded exponential backoff

    ``opener``, ``sleep`` and ``now`` are injected so the policy itself is
    testable without a network or real delays.
    """
    import gzip
    import json as _json
    import time
    import urllib.error
    import urllib.request

    if not isinstance(url, str) or not url.startswith(ALLOWED_URL_PREFIXES):
        raise SourceError(
            SourceOutcome.FAILED,
            "refusing to fetch a URL outside the configured SEC endpoints",
        )

    sleep = sleep or time.sleep
    now = now or time.monotonic
    open_url = opener or urllib.request.urlopen

    _throttle(now, sleep)

    delay = 1.0
    last: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        request = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"}
        )
        try:
            with open_url(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return _json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise SourceError(
                    SourceOutcome.RATE_LIMITED,
                    f"the SEC refused the request ({exc.code}); not retrying",
                ) from exc
            last = exc
        except Exception as exc:
            last = exc
        if attempt < MAX_RETRIES:
            sleep(delay)
            delay *= 2
    raise SourceError(
        SourceOutcome.FAILED,
        f"EDGAR request failed after {MAX_RETRIES + 1} attempts: "
        f"{type(last).__name__ if last else 'unknown'}",
    )


#: Monotonic instant of the last request, so pacing survives across calls.
_LAST_REQUEST: list[float] = [0.0]


def _throttle(now, sleep) -> None:
    """Keep requests at or below :data:`REQUESTS_PER_SECOND`."""
    minimum_gap = 1.0 / REQUESTS_PER_SECOND
    elapsed = now() - _LAST_REQUEST[0]
    if 0 <= elapsed < minimum_gap:
        sleep(minimum_gap - elapsed)
    _LAST_REQUEST[0] = now()


def _parse_edgar_instant(value: object) -> datetime | None:
    """Parse EDGAR's ``2026-09-03T22:30:44.000Z`` form.

    Returns ``None`` for anything unparseable rather than substituting a
    different clock; the caller then records SYSTEM_OBSERVED honestly.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


__all__ = [
    "SOURCE_NAME",
    "ALLOWED_URL_PREFIXES",
    "default_fetch_fn",
    "SUBMISSIONS_URL",
    "ARCHIVE_URL",
    "FILING_INDEX_URL",
    "REQUESTS_PER_SECOND",
    "TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "EdgarFetchFn",
    "EdgarFilingsSource",
]
