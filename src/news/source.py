"""The news-source contract, and the vocabulary for how a fetch went.

Two sources with genuinely different query models sit behind this module, so it
deliberately does **not** define one ``get_news(symbol, start, end)`` that both
must pretend to implement. EDGAR is queried by registrant and returns filings;
Yahoo is queried by symbol and returns however many recent stories it feels
like. Forcing them behind one signature would mean one of them lying about what
it can do.

What *is* shared is the vocabulary of outcomes, because the application layer
has to report honestly on a refresh where one source worked and the other did
not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence

from .models import Document, NewsError, SymbolLink


class SourceOutcome(str, Enum):
    """How one source's fetch ended. Several of these are entirely normal."""

    #: Records were returned.
    SUCCESS = "success"

    #: The source answered, and had nothing for this symbol. Not an error.
    NO_ITEMS = "no_items"

    #: This source cannot cover this symbol (e.g. no SEC registration).
    UNSUPPORTED = "unsupported"

    #: The source needs local configuration that is absent. Not a crash, and
    #: not the other source's problem.
    UNCONFIGURED = "unconfigured"

    #: The source asked us to slow down. Respected, never retried around.
    RATE_LIMITED = "rate_limited"

    #: The source could not be reached, or answered with something unusable.
    FAILED = "failed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_healthy(self) -> bool:
        """``True`` when the source did its job, including having no news."""
        return self in (SourceOutcome.SUCCESS, SourceOutcome.NO_ITEMS)


class ItemOutcome(str, Enum):
    """What happened to one record inside a response."""

    #: New document, stored.
    ACCEPTED = "accepted"

    #: Identical content already stored. Normal, and not written again.
    DUPLICATE = "duplicate"

    #: Same identifier, changed content. Appended as a new revision.
    REVISION = "revision"

    #: Structurally unusable. Rejected without affecting its siblings.
    REJECTED = "rejected"

    #: Same identifier, but a field that may never change has changed. The
    #: identifier has been reused for a different thing; storing it as a
    #: revision would silently rewrite an unrelated document's history.
    ID_REUSE_CONFLICT = "id_reuse_conflict"

    #: No provider identifier. Refused rather than given a manufactured key.
    IDENTITY_UNSAFE = "identity_unsafe"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_stored(self) -> bool:
        return self in (ItemOutcome.ACCEPTED, ItemOutcome.REVISION)


class SourceError(NewsError):
    """A source could not complete a fetch."""

    def __init__(self, outcome: SourceOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


@dataclass(frozen=True)
class IngestionCounters:
    """What one source's refresh did. Local counters, not telemetry."""

    fetched: int = 0
    accepted: int = 0
    duplicate: int = 0
    revision: int = 0
    rejected: int = 0
    errors: int = 0
    #: New (document, symbol) links recorded. Counted separately because a
    #: document can be an unchanged DUPLICATE while still being associated
    #: with a symbol for the first time -- reporting only the document outcome
    #: would say "nothing changed" when something did.
    associations: int = 0

    def plus(self, outcome: ItemOutcome) -> "IngestionCounters":
        mapping = {
            ItemOutcome.ACCEPTED: "accepted",
            ItemOutcome.DUPLICATE: "duplicate",
            ItemOutcome.REVISION: "revision",
            ItemOutcome.REJECTED: "rejected",
            ItemOutcome.ID_REUSE_CONFLICT: "errors",
            ItemOutcome.IDENTITY_UNSAFE: "errors",
        }
        name = mapping[ItemOutcome(outcome)]
        return IngestionCounters(**{**vars(self), name: getattr(self, name) + 1})

    def with_fetched(self, count: int) -> "IngestionCounters":
        return IngestionCounters(**{**vars(self), "fetched": count})

    def with_association(self) -> "IngestionCounters":
        return IngestionCounters(**{**vars(self), "associations": self.associations + 1})

    @property
    def stored(self) -> int:
        return self.accepted + self.revision

    def describe(self) -> str:
        return (
            f"fetched={self.fetched} accepted={self.accepted} duplicate={self.duplicate} "
            f"revision={self.revision} rejected={self.rejected} "
            f"associations={self.associations} errors={self.errors}"
        )


@dataclass(frozen=True)
class SourceResult:
    """One source's contribution to a refresh, success or not."""

    source: str
    outcome: SourceOutcome
    counters: IngestionCounters = field(default_factory=IngestionCounters)
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", SourceOutcome(self.outcome))

    @property
    def is_healthy(self) -> bool:
        return self.outcome.is_healthy


@dataclass(frozen=True)
class FetchedRecord:
    """One normalized record plus the symbol links its fetch justifies."""

    document: Document
    links: tuple[SymbolLink, ...]


class NewsSource(Protocol):
    """What the application layer needs from any source.

    Intentionally minimal: a name, a class of authority, and a way to fetch for
    one symbol. Anything a particular source needs beyond that (a CIK map, a
    contact header) is its own business and is configured at construction.
    """

    name: str

    def fetch_for_symbol(self, symbol: str, *, now) -> tuple[FetchedRecord, ...]:
        """Return normalized records for ``symbol``.

        Raises :class:`SourceError` carrying a :class:`SourceOutcome` when the
        source as a whole could not answer. Individual malformed records are
        the source's own business to drop; they must never take their siblings
        with them.
        """
        ...


__all__ = [
    "SourceOutcome",
    "ItemOutcome",
    "SourceError",
    "IngestionCounters",
    "SourceResult",
    "FetchedRecord",
    "NewsSource",
]
