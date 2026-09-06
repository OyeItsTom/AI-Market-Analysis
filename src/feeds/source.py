"""How one feed refresh went, and what happened to each entry.

Phase 9 defines its own outcome vocabulary rather than importing Phase 8's.
Two members force the split: ``NOT_MODIFIED``, which has no meaning for a news
API that never sends conditional requests, and ``TRUNCATED``, which exists
because a feed document can legitimately carry more entries than one refresh
will process. Adding either to Phase 8's enum would change working behaviour
for this phase's convenience.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from enum import Enum

from .models import FeedError


class SourceOutcome(str, Enum):
    """How one configured feed's refresh ended."""

    #: Entries were returned and processed.
    SUCCESS = "success"

    #: The feed answered and contained no entries. Not an error.
    NO_ITEMS = "no_items"

    #: The source says its representation is unchanged. Distinct from NO_ITEMS:
    #: "nothing new was sent" and "there is nothing" are different facts.
    NOT_MODIFIED = "not_modified"

    #: More entries than the per-refresh bound; the rest were not processed.
    TRUNCATED = "truncated"

    #: The source asked us to slow down.
    RATE_LIMITED = "rate_limited"

    #: The document was not RSS or Atom, or contradicted its configured type.
    UNSUPPORTED_SOURCE_FORMAT = "unsupported_source_format"

    #: The body passed the byte ceiling, measured after decompression.
    PAYLOAD_TOO_LARGE = "payload_too_large"

    #: The host, or the address actually connected to, is not permitted.
    UNSAFE_ENDPOINT = "unsafe_endpoint"

    #: The durable store for this source is damaged. Ingestion is refused.
    STORAGE_CORRUPTION = "storage_corruption"

    #: Transport state was unusable and was rebuilt; ingestion still ran.
    CHECKPOINT_WARNING = "checkpoint_warning"

    #: The source is present in configuration but switched off.
    UNCONFIGURED = "unconfigured"

    #: Could not be reached, or answered with something unusable.
    FAILED = "failed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_healthy(self) -> bool:
        """Whether the source did its job -- including having nothing new."""
        return self in (
            SourceOutcome.SUCCESS,
            SourceOutcome.NO_ITEMS,
            SourceOutcome.NOT_MODIFIED,
            SourceOutcome.TRUNCATED,
            SourceOutcome.CHECKPOINT_WARNING,
        )


class ItemOutcome(str, Enum):
    """What happened to one entry inside a document."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REVISION = "revision"
    REJECTED = "rejected"

    #: Same provider id, but the canonical host changed: the id now refers to
    #: something else, and appending would rewrite an unrelated item's history.
    ID_REUSE_CONFLICT = "id_reuse_conflict"

    #: No usable provider id. Refused rather than given a manufactured key.
    IDENTITY_UNSAFE = "identity_unsafe"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_stored(self) -> bool:
        return self in (ItemOutcome.ACCEPTED, ItemOutcome.REVISION)


class SourceError(FeedError):
    """A source could not complete a refresh, carrying its outcome."""

    def __init__(self, outcome: SourceOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


@dataclass(frozen=True)
class IngestionCounters:
    """What one refresh did. Local counters, never telemetry."""

    entries_seen: int = 0
    entries_processed: int = 0
    entries_truncated: int = 0
    accepted: int = 0
    duplicate: int = 0
    revision: int = 0
    rejected: int = 0
    errors: int = 0
    #: New (item, symbol, config) links. Counted separately because an item can
    #: be an unchanged DUPLICATE while still being associated with a symbol for
    #: the first time -- reporting only the item outcome would say "nothing
    #: changed" when something did.
    associations: int = 0

    _NAME_FOR = {
        "accepted": "accepted",
        "duplicate": "duplicate",
        "revision": "revision",
        "rejected": "rejected",
        "id_reuse_conflict": "errors",
        "identity_unsafe": "errors",
    }

    def plus(self, outcome: ItemOutcome) -> "IngestionCounters":
        name = self._NAME_FOR[ItemOutcome(outcome).value]
        return self._replace(**{name: getattr(self, name) + 1})

    def with_association(self) -> "IngestionCounters":
        return self._replace(associations=self.associations + 1)

    def with_entries(self, *, seen: int, processed: int, truncated: int) -> "IngestionCounters":
        return self._replace(
            entries_seen=seen, entries_processed=processed, entries_truncated=truncated
        )

    def _replace(self, **changes) -> "IngestionCounters":
        current = {f.name: getattr(self, f.name) for f in dataclass_fields(self)}
        current.update(changes)
        return IngestionCounters(**current)

    @property
    def stored(self) -> int:
        return self.accepted + self.revision

    def describe(self) -> str:
        return (
            f"seen={self.entries_seen} processed={self.entries_processed} "
            f"truncated={self.entries_truncated} accepted={self.accepted} "
            f"duplicate={self.duplicate} revision={self.revision} "
            f"rejected={self.rejected} associations={self.associations} "
            f"errors={self.errors}"
        )


@dataclass(frozen=True)
class SourceResult:
    """One configured feed's contribution to a refresh."""

    source_id: str
    outcome: SourceOutcome
    counters: IngestionCounters = field(default_factory=IngestionCounters)
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", SourceOutcome(self.outcome))

    @property
    def is_healthy(self) -> bool:
        return self.outcome.is_healthy


__all__ = [
    "SourceOutcome",
    "ItemOutcome",
    "SourceError",
    "IngestionCounters",
    "SourceResult",
]
