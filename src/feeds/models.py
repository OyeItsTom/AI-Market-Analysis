"""Records for public RSS/Atom feeds: what a feed said, and how well we know it.

This package deliberately shares **no types** with the Phase 8 news layer. Several of
the concepts look alike, but the ones Phase 9 needs differ in ways that matter:
feeds need a ``SOURCE_UPDATED`` availability basis that news has no use for, and
a ``NOT_MODIFIED`` outcome that news never encounters. Importing the news
vocabulary and then editing it to fit would change working Phase 8 behaviour for
Phase 9's convenience; importing only the parts that happen to match would be
coupling by coincidence. So the small enums are duplicated on purpose, and the
cost of that duplication is accepted in exchange for Phase 8 staying untouched.

Nothing here interprets anything: no sentiment, no relevance, no importance, no
truth. A feed record says a configured source published something, and stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# -- limits, locked before implementation --------------------------------

MAX_SOURCE_ID = 64
MAX_FEED_ITEM_ID = 512
MAX_URL = 2_000
MAX_TITLE = 500
MAX_PUBLISHER = 200

#: Said out loud rather than left blank. Most feeds name no author, and an empty
#: byline in the panel would read as an oversight instead of a known absence.
UNKNOWN_PUBLISHER = "unknown publisher"
MAX_DISPLAY_NAME = 200
MAX_EXCERPT = 2_000
MAX_SYMBOLS_PER_SOURCE = 20
MAX_ENTRIES = 100
MAX_CONFIG_BYTES = 256 * 1024
MAX_SOURCES = 50
MAX_BODY_BYTES = 2 * 1024 * 1024


class FeedError(ValueError):
    """Raised when a feed record or configuration is structurally invalid."""


class FeedFormat(str, Enum):
    """The two dialects this phase parses. Nothing else is attempted."""

    RSS = "rss"
    ATOM = "atom"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class DeclaredTrustClass(str, Enum):
    """How authoritative the **user says** a feed is.

    "Declared" is the operative word. Nothing in this system verifies that a URL
    is really operated by the regulator or company it claims to be -- a user can
    point ``OFFICIAL_FEED`` at any address at all. The value therefore travels
    with :class:`TrustBasis`, and the interface renders both together so nobody
    can read a configuration choice as a verification result.
    """

    OFFICIAL_FEED = "official_feed"
    PUBLISHER_FEED = "publisher_feed"
    COMMUNITY_FEED = "community_feed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def label(self) -> str:
        """Wording that never implies the system checked anything."""
        return {
            DeclaredTrustClass.OFFICIAL_FEED: "Official feed (configured by you)",
            DeclaredTrustClass.PUBLISHER_FEED: "Publisher feed (configured)",
            DeclaredTrustClass.COMMUNITY_FEED: "Community feed — unverified",
        }[self]


class TrustBasis(str, Enum):
    """Where a trust class came from. V1 has exactly one honest answer."""

    USER_CONFIGURED = "user_configured"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class SymbolAssociation(str, Enum):
    """Why a record is attached to a symbol.

    One member, because only one is truthful here: the feed was *configured* for
    this symbol. That is a fact about the configuration, not about the article.
    A feed configured for AAPL will happily carry a story about something else,
    so nothing is ever claimed to be "about" a company.
    """

    CONFIGURED_SYMBOL = "configured_symbol"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def label_template(self) -> str:
        return "From a feed configured for {symbol}"


class AvailabilityBasis(str, Enum):
    """Why we believe an item was available from ``available_from``."""

    #: The source states when it published (RSS ``pubDate``, Atom ``published``).
    SOURCE_PUBLISHED = "source_published"

    #: Atom requires ``updated`` but makes ``published`` optional, and real
    #: feeds routinely omit it -- every entry in the SEC's own Atom feed does.
    #: Calling that update time a publication time would be an overclaim, so it
    #: gets its own basis rather than being folded into the one above.
    SOURCE_UPDATED = "source_updated"

    #: No usable source timing; availability is bounded above by our retrieval.
    SYSTEM_OBSERVED = "system_observed"

    #: Nothing defensible is known. Excluded from strict causal queries.
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_source_asserted(self) -> bool:
        return self in (
            AvailabilityBasis.SOURCE_PUBLISHED,
            AvailabilityBasis.SOURCE_UPDATED,
        )


class QueryMode(str, Enum):
    """Which question a query asks."""

    #: "What carried a source timestamp at or before T?" Reportorial.
    SOURCE_TIME = "source_time"

    #: "What can we defensibly say was available by T?"
    STRICT_CAUSAL = "strict_causal"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class TrustMode(str, Enum):
    """How much a strict causal query takes on trust."""

    #: Believe the source's own timestamp.
    SOURCE_ASSERTED = "source_asserted"

    #: Believe only our own observation; a backfilled item is invisible until
    #: the moment this system actually retrieved it.
    SYSTEM_OBSERVED = "system_observed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# -- helpers -------------------------------------------------------------


def require_aware(value: object, label: str) -> datetime:
    """A timezone-aware datetime, normalized to UTC. Naive input is refused."""
    if not isinstance(value, datetime):
        raise FeedError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeedError(
            f"{label} must be timezone-aware; a naive timestamp would be a guess"
        )
    return value.astimezone(timezone.utc)


def require_text(value: object, label: str, *, maximum: int) -> str:
    """Non-empty text within bounds. Over-length is refused, never trimmed.

    Identity and display fields are validated here; only ``excerpt`` is
    truncatable, and that happens explicitly at its own call site.
    """
    if not isinstance(value, str):
        raise FeedError(f"{label} must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise FeedError(f"{label} must not be empty")
    if len(text) > maximum:
        raise FeedError(f"{label} exceeds {maximum} characters ({len(text)})")
    if any(ord(character) < 32 and character != "\t" for character in text):
        raise FeedError(f"{label} contains control characters")
    return text


def require_source_id(value: object) -> str:
    """A stable, path-safe slug chosen by the user."""
    text = require_text(value, "source_id", maximum=MAX_SOURCE_ID).lower()
    if not all(character.isalnum() or character in "_-" for character in text):
        raise FeedError(
            f"source_id {value!r} may contain only lowercase letters, digits, "
            "underscore and hyphen"
        )
    return text


def require_symbol(value: object) -> str:
    text = require_text(value, "symbol", maximum=32).upper()
    if not all(character.isalnum() or character in ".-" for character in text):
        raise FeedError(f"symbol {value!r} contains unsupported characters")
    return text


# -- records -------------------------------------------------------------


@dataclass(frozen=True)
class FeedItem:
    """One entry from a configured feed, as that feed described it. Immutable.

    Stores a title, whatever short text the feed itself supplied, and a link.
    Never the full article: the link is for the reader to follow, and this
    application never follows it.
    """

    source_id: str
    feed_item_id: str
    declared_trust_class: DeclaredTrustClass
    trust_basis: TrustBasis
    title: str
    canonical_url: str
    retrieved_at: datetime
    availability_basis: AvailabilityBasis
    config_fingerprint: str
    publisher: str = ""
    excerpt: str = ""
    source_published_at: datetime | None = None
    source_edited_at: datetime | None = None
    available_from: datetime | None = None
    revision: int = 1
    content_hash: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source_id", require_source_id(self.source_id))
        set_(self, "feed_item_id",
             require_text(self.feed_item_id, "feed_item_id", maximum=MAX_FEED_ITEM_ID))
        set_(self, "declared_trust_class", DeclaredTrustClass(self.declared_trust_class))
        set_(self, "trust_basis", TrustBasis(self.trust_basis))
        set_(self, "title", require_text(self.title, "title", maximum=MAX_TITLE))
        set_(self, "canonical_url",
             require_text(self.canonical_url, "canonical_url", maximum=MAX_URL))
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "availability_basis", AvailabilityBasis(self.availability_basis))
        set_(self, "config_fingerprint",
             require_text(self.config_fingerprint, "config_fingerprint", maximum=128))
        if self.publisher:
            set_(self, "publisher",
                 require_text(self.publisher, "publisher", maximum=MAX_PUBLISHER))
        else:
            # Many feeds name no author. The absence is stated rather than left
            # as an empty string or a None for the UI to render as "None".
            set_(self, "publisher", UNKNOWN_PUBLISHER)
        if self.excerpt:
            if len(self.excerpt) > MAX_EXCERPT:
                raise FeedError("excerpt must be truncated before construction")
            set_(self, "excerpt", self.excerpt.strip())
        for name in ("source_published_at", "source_edited_at", "available_from"):
            value = getattr(self, name)
            if value is not None:
                set_(self, name, require_aware(value, name))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise FeedError("revision must be an int")
        if self.revision < 1:
            raise FeedError(f"revision must be >= 1, got {self.revision}")
        _check_availability(self.availability_basis, self.available_from)
        _check_basis_matches_timestamps(self)

    @property
    def item_key(self) -> tuple[str, str]:
        """Document identity: one item per source, however many symbols."""
        return (self.source_id, self.feed_item_id)

    @property
    def source_time(self) -> datetime | None:
        """The source's own timestamp, whichever kind it supplied."""
        return self.source_published_at or self.source_edited_at


def _check_availability(basis: AvailabilityBasis, available_from: datetime | None) -> None:
    if basis is AvailabilityBasis.UNKNOWN and available_from is not None:
        raise FeedError(
            "availability_basis UNKNOWN must not carry an available_from; an "
            "unknown availability is not a time"
        )
    if basis is not AvailabilityBasis.UNKNOWN and available_from is None:
        raise FeedError(f"availability_basis {basis.value!r} requires an available_from")


def _check_basis_matches_timestamps(item: "FeedItem") -> None:
    """The basis must be backed by the timestamp it names.

    Without this an adapter could label an entry ``SOURCE_PUBLISHED`` while
    carrying only an update time -- precisely the overclaim the separate
    ``SOURCE_UPDATED`` member exists to prevent.
    """
    if item.availability_basis is AvailabilityBasis.SOURCE_PUBLISHED:
        if item.source_published_at is None:
            raise FeedError("SOURCE_PUBLISHED requires source_published_at")
    if item.availability_basis is AvailabilityBasis.SOURCE_UPDATED:
        if item.source_edited_at is None:
            raise FeedError("SOURCE_UPDATED requires source_edited_at")
        if item.source_published_at is not None:
            raise FeedError(
                "SOURCE_UPDATED is for entries with no stated publication time; "
                "one with a published time is SOURCE_PUBLISHED"
            )


@dataclass(frozen=True)
class SymbolLink:
    """That an item was associated with a symbol, under a specific config.

    Stored apart from the item because association is a *configuration*
    observation: it is made at retrieval time under one ``config_fingerprint``,
    and adding a symbol to a feed later must not rewrite what older records
    meant.
    """

    source_id: str
    feed_item_id: str
    symbol: str
    association: SymbolAssociation
    retrieved_at: datetime
    config_fingerprint: str
    declared_trust_class: DeclaredTrustClass = DeclaredTrustClass.COMMUNITY_FEED

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source_id", require_source_id(self.source_id))
        set_(self, "feed_item_id",
             require_text(self.feed_item_id, "feed_item_id", maximum=MAX_FEED_ITEM_ID))
        set_(self, "symbol", require_symbol(self.symbol))
        set_(self, "association", SymbolAssociation(self.association))
        set_(self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at"))
        set_(self, "config_fingerprint",
             require_text(self.config_fingerprint, "config_fingerprint", maximum=128))
        set_(self, "declared_trust_class", DeclaredTrustClass(self.declared_trust_class))

    @property
    def link_key(self) -> tuple[str, str, str, str]:
        """An association is per item, symbol **and** configuration vintage."""
        return (self.source_id, self.feed_item_id, self.symbol, self.config_fingerprint)


__all__ = [
    "FeedError",
    "FeedFormat",
    "DeclaredTrustClass",
    "TrustBasis",
    "SymbolAssociation",
    "AvailabilityBasis",
    "QueryMode",
    "TrustMode",
    "FeedItem",
    "SymbolLink",
    "require_aware",
    "require_text",
    "require_source_id",
    "require_symbol",
    "MAX_SOURCE_ID",
    "MAX_FEED_ITEM_ID",
    "MAX_URL",
    "MAX_TITLE",
    "MAX_PUBLISHER",
    "UNKNOWN_PUBLISHER",
    "MAX_DISPLAY_NAME",
    "MAX_EXCERPT",
    "MAX_SYMBOLS_PER_SOURCE",
    "MAX_ENTRIES",
    "MAX_CONFIG_BYTES",
    "MAX_SOURCES",
    "MAX_BODY_BYTES",
]
