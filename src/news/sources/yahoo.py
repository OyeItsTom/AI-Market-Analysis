"""Yahoo aggregated news -- the secondary tier.

Two measured facts drive every decision in this module.

**The payload carries no ticker field.** A story is associated with a symbol
only because that symbol was the one queried, so every link is recorded as
:attr:`SymbolAssociation.QUERIED_SYMBOL`. This is not caution for its own sake:
querying ``AAPL`` returns stories primarily about other companies, and one
article was observed being returned for ``AAPL``, ``AMZN`` and ``TSLA`` at once.
The dashboard therefore says *"returned for AAPL"*, never *"about AAPL"*.

**The "press releases" tab is not the company's press releases.** Sampling it
across three symbols returned only third-party wire copy mentioning the company
-- market-research notices and other firms' announcements. It is therefore not
fetched, and nothing from Yahoo is ever classed
:attr:`SourceClass.OFFICIAL_FILING`. Official means a regulator accepted it.

Identity
--------
The provider item id is used when present and the record is **refused** when it
is not. A fallback key derived from the headline or URL would merge a wire story
with its syndication and fork a document when a publisher fixed a typo, so no
such fallback exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from ..identity import news_content_hash
from ..models import (
    MAX_HEADLINE,
    MAX_IDENTIFIER,
    MAX_SUMMARY,
    AvailabilityBasis,
    EventType,
    NewsError,
    NewsItem,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
    require_symbol,
)
from ..source import FetchedRecord, ItemOutcome, SourceError, SourceOutcome
from ..validation import safe_text, validate_source_timestamp, validate_url

SOURCE_NAME = "yahoo"

#: Only the general news tab. See the module docstring for why "press releases"
#: is deliberately not requested.
NEWS_TAB = "news"

#: ``(symbol, count) -> list of raw provider items``. Injected so no test needs
#: the network or the yfinance package.
YahooFetchFn = Callable[[str, int], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class YahooNewsSource:
    """Normalizes Yahoo's aggregated news into :class:`NewsItem` records."""

    fetch_fn: YahooFetchFn
    name: str = SOURCE_NAME
    source_class: SourceClass = SourceClass.SECONDARY_NEWS
    max_items: int = 20

    def fetch_for_symbol(
        self, symbol: str, *, now: datetime
    ) -> tuple[FetchedRecord, ...]:
        symbol = require_symbol(symbol)
        try:
            raw_items = self.fetch_fn(symbol, self.max_items)
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(
                SourceOutcome.FAILED, f"Yahoo news request failed: {type(exc).__name__}"
            ) from exc

        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            raise SourceError(SourceOutcome.FAILED, "Yahoo returned an unusable payload")

        records: list[FetchedRecord] = []
        for raw in raw_items:
            record = self._normalize(raw, symbol=symbol, now=now)
            # One malformed story never costs the others.
            if record is not None:
                records.append(record)
        return tuple(records)

    def _normalize(
        self, raw: object, *, symbol: str, now: datetime
    ) -> FetchedRecord | None:
        if not isinstance(raw, Mapping):
            return None
        content = raw.get("content")
        content = content if isinstance(content, Mapping) else {}

        item_id = safe_text(raw.get("id") or content.get("id"), maximum=MAX_IDENTIFIER)
        if not item_id:
            # IDENTITY_UNSAFE: no provider identifier, and none is manufactured.
            return None

        headline = safe_text(content.get("title") or raw.get("title"), maximum=MAX_HEADLINE)
        if not headline:
            return None

        url = _first_url(content, raw)
        if url is None:
            return None
        try:
            canonical_url = validate_url(url, label="canonical_url")
        except NewsError:
            return None

        publisher = safe_text(
            (content.get("provider") or {}).get("displayName")
            if isinstance(content.get("provider"), Mapping)
            else raw.get("publisher"),
            maximum=MAX_IDENTIFIER,
            default="unknown publisher",
        )
        summary = safe_text(
            content.get("summary") or content.get("description"), maximum=MAX_SUMMARY
        )

        published = _parse_instant(content.get("pubDate") or content.get("displayTime"))
        try:
            published = validate_source_timestamp(published, now=now, label="pubDate")
        except NewsError:
            return None

        if published is not None:
            available_from, basis = published, AvailabilityBasis.SOURCE_PUBLISHED
        else:
            # No claimed publication time. We do not invent one from our own
            # clock; we record only that we had it by now.
            available_from, basis = now, AvailabilityBasis.SYSTEM_OBSERVED

        try:
            item = NewsItem(
                source=self.name,
                source_item_id=item_id,
                source_class=SourceClass.SECONDARY_NEWS,
                publisher=publisher,
                headline=headline,
                canonical_url=canonical_url,
                retrieved_at=now,
                availability_basis=basis,
                summary=summary,
                source_published_at=published,
                available_from=available_from,
                event_type=EventType.UNKNOWN,
                content_hash=news_content_hash(
                    headline=headline,
                    summary=summary,
                    canonical_url=canonical_url,
                    publisher=publisher,
                    source_published_at=published,
                ),
            )
        except NewsError:
            return None

        link = SymbolLink(
            source=self.name,
            source_item_id=item_id,
            symbol=symbol,
            # The payload names no ticker. This is the strongest true claim.
            association=SymbolAssociation.QUERIED_SYMBOL,
            retrieved_at=now,
            queried_symbol=symbol,
        )
        return FetchedRecord(item, (link,))


def _first_url(content: Mapping[str, Any], raw: Mapping[str, Any]) -> str | None:
    """Prefer the canonical URL, fall back to the click-through, else nothing."""
    for holder in (content.get("canonicalUrl"), content.get("clickThroughUrl")):
        if isinstance(holder, Mapping):
            candidate = holder.get("url")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    candidate = raw.get("link")
    return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None


def _parse_instant(value: object) -> datetime | None:
    """Parse ``2026-09-05T19:40:00Z`` or an epoch-second integer."""
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return None if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def default_fetch_fn(symbol: str, count: int) -> Sequence[Mapping[str, Any]]:
    """Real Yahoo fetch. Imported lazily so tests never load yfinance."""
    import yfinance

    return yfinance.Ticker(symbol).get_news(count=count, tab=NEWS_TAB)


__all__ = [
    "SOURCE_NAME",
    "NEWS_TAB",
    "YahooFetchFn",
    "YahooNewsSource",
    "default_fetch_fn",
]
