"""External-information records: what a source said, and how well we know it.

Two record types, deliberately not one. An SEC filing and a news article are
different kinds of thing: a filing has a registrant, a form code and an
acceptance instant; an article has a publisher and a claimed publication time.
Forcing them into one shape would mean inventing fields for whichever record
did not have them, and an invented field is indistinguishable from a real one
once it is stored.

Nothing here interprets anything. There is no sentiment, no relevance, no
importance and no direction: Phase 8 records what a source published, and a
human (or a later phase) decides what it means.

Timing, which is the whole difficulty
-------------------------------------
Four different instants are kept apart because collapsing them is how a
research system quietly starts using information before it existed:

``source_event_time``
    An instant the source asserts about the record's own lifecycle -- EDGAR's
    ``acceptanceDateTime``. It proves the SEC accepted a filing. It does **not**
    prove the filing was publicly disseminated at that moment.

``source_published_at``
    The instant a source claims it published -- Yahoo's ``pubDate``.

``retrieved_at``
    When *this system* fetched the record. Never a substitute for either of the
    above, however tempting it is that we always know it.

``available_from`` + :class:`AvailabilityBasis`
    The earliest instant we are willing to claim, and **why**. The basis is
    stored beside the value so a later reader can tell a source's assertion
    from our own observation, and can refuse to trust the former if it wants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class NewsError(ValueError):
    """Raised when an external-information record is structurally invalid."""


class SourceClass(str, Enum):
    """How authoritative a record's origin is.

    Deliberately two members. A third, vaguer tier would invite classifying a
    syndicated blog post as "semi-official", which is exactly the judgement
    this enum exists to avoid making.
    """

    #: A filing accepted by a regulator. The registrant is identified by the
    #: regulator itself, so the symbol association is a source fact.
    OFFICIAL_FILING = "official_filing"

    #: Reportage. Someone wrote about a company; nobody official said it.
    SECONDARY_NEWS = "secondary_news"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_official(self) -> bool:
        return self is SourceClass.OFFICIAL_FILING


class SymbolAssociation(str, Enum):
    """*Why* a record is attached to a symbol -- not merely that it is.

    This distinction is load-bearing rather than decorative. The Yahoo news
    payload carries **no ticker field at all**: a story is associated with a
    symbol only because that symbol was the one queried, and querying ``AAPL``
    demonstrably returns stories primarily about other companies. Recording
    that as :attr:`VERIFIED_SOURCE` would be a false claim about provenance.
    """

    #: The source itself identified the company (SEC maps a CIK to a ticker).
    VERIFIED_SOURCE = "verified_source"

    #: The record came back when this symbol was queried, and nothing stronger
    #: is known. Render as "returned for AAPL", never "about AAPL".
    QUERIED_SYMBOL = "queried_symbol"

    #: Reserved. Never produced in V1: no matcher exists, because a substring
    #: or company-name matcher would manufacture exactly the false confidence
    #: the other two members exist to prevent.
    INFERRED = "inferred"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class AvailabilityBasis(str, Enum):
    """Why we believe a record was available from ``available_from``."""

    #: A source-asserted lifecycle instant (EDGAR acceptance). Strong, but an
    #: assertion about acceptance rather than proof of dissemination.
    SOURCE_EVENT = "source_event"

    #: The source claims it published then.
    SOURCE_PUBLISHED = "source_published"

    #: No source timing at all; availability is bounded above by our retrieval.
    SYSTEM_OBSERVED = "system_observed"

    #: Nothing defensible is known. Excluded from strict causal queries rather
    #: than given a guessed value.
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_source_asserted(self) -> bool:
        return self in (AvailabilityBasis.SOURCE_EVENT, AvailabilityBasis.SOURCE_PUBLISHED)


class EventType(str, Enum):
    """What kind of event a record describes, **when the source says so**.

    ``FILING`` is used for EDGAR records, whose real taxonomy is the official
    ``form`` code (``8-K``, ``10-Q``) and ``items`` list carried on
    :class:`OfficialFiling`. Everything else is ``UNKNOWN``: without an
    official code there is no classification here, because a keyword matcher
    would be guesswork wearing a taxonomy's clothes.
    """

    FILING = "filing"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# -- helpers -------------------------------------------------------------

#: Upper bounds on stored text. Not tuning: an unbounded headline from an
#: untrusted source is a denial-of-service and a storage hazard.
MAX_HEADLINE = 1_000
MAX_SUMMARY = 5_000
MAX_URL = 2_000
MAX_IDENTIFIER = 256


def require_aware(value: object, label: str) -> datetime:
    """A timezone-aware datetime, normalized to UTC.

    Naive datetimes are rejected rather than assumed to be UTC: the same
    invariant Phase 1 enforces on :class:`~src.data.models.MarketBar`, for the
    same reason -- a guessed timezone is a silent hours-wide error.
    """
    if not isinstance(value, datetime):
        raise NewsError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise NewsError(
            f"{label} must be timezone-aware; a naive timestamp would be a guess"
        )
    return value.astimezone(timezone.utc)


def require_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise NewsError(f"{label} must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise NewsError(f"{label} must not be empty")
    if len(text) > maximum:
        raise NewsError(f"{label} exceeds {maximum} characters ({len(text)})")
    if any(ord(character) < 32 and character not in "\t" for character in text):
        raise NewsError(f"{label} contains control characters")
    return text


def _optional_text(value: object, label: str, *, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise NewsError(f"{label} must be a str or None")
    text = value.strip()
    if not text:
        return ""
    return require_text(text, label, maximum=maximum)


def require_symbol(value: object) -> str:
    symbol = require_text(value, "symbol", maximum=32).upper()
    if not all(character.isalnum() or character in ".-" for character in symbol):
        raise NewsError(f"symbol {value!r} contains unsupported characters")
    return symbol


# -- records -------------------------------------------------------------


@dataclass(frozen=True)
class NewsItem:
    """One reported article, as a source described it. Immutable.

    Carries no body: see ``docs/news.md``. Only the headline, whatever summary
    the provider itself supplied, and a link back to the source are stored, so
    this system never becomes a mirror of someone else's copyrighted article.
    """

    source: str
    source_item_id: str
    source_class: SourceClass
    publisher: str
    headline: str
    canonical_url: str
    retrieved_at: datetime
    availability_basis: AvailabilityBasis
    summary: str = ""
    source_published_at: datetime | None = None
    available_from: datetime | None = None
    event_type: EventType = EventType.UNKNOWN
    revision: int = 1
    content_hash: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source", require_text(self.source, "source", maximum=MAX_IDENTIFIER))
        set_(self, "source_item_id",
             require_text(self.source_item_id, "source_item_id", maximum=MAX_IDENTIFIER))
        set_(self, "source_class", SourceClass(self.source_class))
        set_(self, "publisher", _optional_text(self.publisher, "publisher", maximum=MAX_IDENTIFIER)
             or "unknown publisher")
        set_(self, "headline", require_text(self.headline, "headline", maximum=MAX_HEADLINE))
        set_(self, "summary", _optional_text(self.summary, "summary", maximum=MAX_SUMMARY))
        set_(self, "canonical_url",
             require_text(self.canonical_url, "canonical_url", maximum=MAX_URL))
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "availability_basis", AvailabilityBasis(self.availability_basis))
        set_(self, "event_type", EventType(self.event_type))
        if self.source_published_at is not None:
            set_(self, "source_published_at",
                 require_aware(self.source_published_at, "source_published_at"))
        if self.available_from is not None:
            set_(self, "available_from", require_aware(self.available_from, "available_from"))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise NewsError("revision must be an int")
        if self.revision < 1:
            raise NewsError(f"revision must be >= 1, got {self.revision}")
        _check_availability(self.availability_basis, self.available_from)

    @property
    def item_key(self) -> tuple[str, str]:
        """Global document identity: one document, however many symbols it was
        returned for."""
        return (self.source, self.source_item_id)

    @property
    def source_time(self) -> datetime | None:
        """The source's own timestamp, whichever kind it supplied."""
        return self.source_published_at


@dataclass(frozen=True)
class OfficialFiling:
    """One filing accepted by the SEC. Immutable.

    ``acceptance_time`` is the instant EDGAR accepted the document. It is
    recorded as a **bound**, not as proof of public dissemination -- the same
    discipline Phase 3 applies to ``evaluable_from``. ``filing_date`` is a
    calendar date and is not the same fact: EDGAR rolls filings accepted after
    its cut-off onto the next business day.

    The document body is never stored; ``primary_document_url`` is built from
    trusted identifiers so no URL out of a payload has to be believed.
    """

    source: str
    source_item_id: str
    source_class: SourceClass
    cik: str
    form: str
    headline: str
    canonical_url: str
    primary_document_url: str
    retrieved_at: datetime
    availability_basis: AvailabilityBasis
    filing_date: str = ""
    report_date: str = ""
    items: tuple[str, ...] = ()
    source_event_time: datetime | None = None
    available_from: datetime | None = None
    event_type: EventType = EventType.FILING
    revision: int = 1
    content_hash: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source", require_text(self.source, "source", maximum=MAX_IDENTIFIER))
        set_(self, "source_item_id",
             require_text(self.source_item_id, "source_item_id", maximum=MAX_IDENTIFIER))
        set_(self, "source_class", SourceClass(self.source_class))
        if not self.source_class.is_official:
            raise NewsError(
                "an OfficialFiling must carry SourceClass.OFFICIAL_FILING; a record "
                "that is not from a regulator must not be presented as one"
            )
        set_(self, "cik", require_text(self.cik, "cik", maximum=32))
        set_(self, "form", require_text(self.form, "form", maximum=64))
        set_(self, "headline", require_text(self.headline, "headline", maximum=MAX_HEADLINE))
        set_(self, "canonical_url",
             require_text(self.canonical_url, "canonical_url", maximum=MAX_URL))
        set_(self, "primary_document_url",
             require_text(self.primary_document_url, "primary_document_url", maximum=MAX_URL))
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "availability_basis", AvailabilityBasis(self.availability_basis))
        set_(self, "event_type", EventType(self.event_type))
        set_(self, "filing_date", _optional_text(self.filing_date, "filing_date", maximum=32))
        set_(self, "report_date", _optional_text(self.report_date, "report_date", maximum=32))
        set_(self, "items", tuple(
            require_text(item, "item", maximum=64) for item in self.items
        ))
        if self.source_event_time is not None:
            set_(self, "source_event_time",
                 require_aware(self.source_event_time, "source_event_time"))
        if self.available_from is not None:
            set_(self, "available_from", require_aware(self.available_from, "available_from"))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise NewsError("revision must be an int")
        if self.revision < 1:
            raise NewsError(f"revision must be >= 1, got {self.revision}")
        _check_availability(self.availability_basis, self.available_from)

    @property
    def item_key(self) -> tuple[str, str]:
        return (self.source, self.source_item_id)

    @property
    def source_time(self) -> datetime | None:
        return self.source_event_time

    @property
    def publisher(self) -> str:
        """Filings have a regulator, not a publisher."""
        return "U.S. Securities and Exchange Commission"

    @property
    def summary(self) -> str:
        """Official codes only -- never a generated description."""
        return f"Form {self.form}" + (f" (items {', '.join(self.items)})" if self.items else "")


def _check_availability(basis: AvailabilityBasis, available_from: datetime | None) -> None:
    """A basis that claims a source asserted something needs the instant it
    asserted; ``UNKNOWN`` must not carry one."""
    if basis is AvailabilityBasis.UNKNOWN and available_from is not None:
        raise NewsError(
            "availability_basis UNKNOWN must not carry an available_from; an "
            "unknown availability is not a time"
        )
    if basis is not AvailabilityBasis.UNKNOWN and available_from is None:
        raise NewsError(f"availability_basis {basis.value!r} requires an available_from")


@dataclass(frozen=True)
class SymbolLink:
    """That a document was associated with a symbol, and on what authority.

    Stored apart from the document because association is *query-specific*
    while a document is not: one Yahoo article is routinely returned for
    several symbols, and storing a copy per symbol would make "deduplicated"
    a false claim.
    """

    source: str
    source_item_id: str
    symbol: str
    association: SymbolAssociation
    retrieved_at: datetime
    queried_symbol: str = ""
    cik_map_last_modified: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source", require_text(self.source, "source", maximum=MAX_IDENTIFIER))
        set_(self, "source_item_id",
             require_text(self.source_item_id, "source_item_id", maximum=MAX_IDENTIFIER))
        set_(self, "symbol", require_symbol(self.symbol))
        set_(self, "association", SymbolAssociation(self.association))
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "queried_symbol",
             require_symbol(self.queried_symbol) if self.queried_symbol else self.symbol)
        set_(self, "cik_map_last_modified",
             _optional_text(self.cik_map_last_modified, "cik_map_last_modified", maximum=128))
        if self.association is SymbolAssociation.INFERRED:
            raise NewsError(
                "INFERRED association is not produced in V1: no matcher exists, and "
                "a guessed company link must not be storable as if it were evidence"
            )

    @property
    def link_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.source_item_id, self.symbol, self.association.value)


#: Either kind of stored document.
Document = NewsItem | OfficialFiling


__all__ = [
    "NewsError",
    "SourceClass",
    "SymbolAssociation",
    "AvailabilityBasis",
    "EventType",
    "NewsItem",
    "OfficialFiling",
    "SymbolLink",
    "Document",
    "require_aware",
    "require_text",
    "require_symbol",
    "MAX_HEADLINE",
    "MAX_SUMMARY",
    "MAX_URL",
    "MAX_IDENTIFIER",
]
