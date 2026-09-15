"""What a ledger of tracked artifacts and outcomes must do -- and no more.

Two protocols, one value, one result type and a small error family. Nothing
here touches a filesystem, a clock, a network or an environment variable:
this module says what persistence *means* for Phase 12 so that an adapter
(:mod:`src.outcomes.store`) can implement it and later stages can depend on
the meaning rather than on the adapter.

Ledger, not repository
----------------------
An :class:`OutcomeLedger` is append-only in spirit as well as in
implementation. It has two write operations, both idempotent by *key*:
registering an artifact and appending an outcome. Neither can update,
delete, overwrite or re-order anything, and a second write under an
existing key returns a :class:`WriteStatus` -- ``DUPLICATE`` when the
record is byte-for-byte the one already held, ``CONFLICT`` when it is not
-- rather than silently storing a second truth. There is no method that
anticipates analytics; aggregation is a later stage that will *read*.

Reader, for consumers that must never write
-------------------------------------------
:class:`OutcomeReader` is the read-only subset. A future consumer that
receives a reader receives immutable records and no way to add, alter or
remove one. The ledger protocol extends it, so any ledger is also a reader.

Partitions
----------
Every artifact and every outcome belongs to exactly one market context:
``(symbol, interval, basis)``. That triple is part of every artifact key,
so two records with different triples can never share a key, and an
adapter may lay records out by it. A :class:`LedgerPartition` names one
such context. Writes derive it from the record they are given -- a record
cannot be written into the wrong partition -- and reads take it explicitly.

Errors
------
Ordinary write outcomes are statuses, not exceptions. Exceptions are for
what the caller cannot proceed past: a store whose bytes do not describe
the records it claims to hold (:class:`LedgerCorruption`), a stored line
written under rules this build does not know (:class:`UnsupportedSchemaError`),
an outcome for an artifact the ledger has never seen
(:class:`UnregisteredArtifactError`), and an outcome embedding an artifact
that differs from the one registered under the same key
(:class:`ArtifactMismatchError`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Protocol

from src.data.models import Interval
from src.data.series import PriceBasis

from .identity import OutcomeTrackingError, require_key, require_text
from .models import OutcomeRecord, TrackedArtifact


# -- errors ---------------------------------------------------------------------------


class LedgerError(OutcomeTrackingError):
    """Base of every error a ledger raises. Statuses cover the ordinary cases."""


class LedgerCorruption(LedgerError):
    """The stored bytes do not describe the records they claim to hold.

    Raised on read, never silently absorbed, and nothing on disk is touched:
    the bad bytes stay as evidence. Located precisely enough to inspect by
    hand. ``byte_offset`` is the offset of the *line's first byte* within
    the file; ``line_number`` is 1-based.
    """

    def __init__(self, *, path: str, line_number: int, byte_offset: int, reason: str) -> None:
        self.path = str(path)
        self.line_number = int(line_number)
        self.byte_offset = int(byte_offset)
        self.reason = str(reason)
        super().__init__(
            f"{self.path}:{self.line_number} (byte {self.byte_offset}): {self.reason}"
        )


class UnsupportedSchemaError(LedgerCorruption):
    """A stored line declares a schema version this build does not know.

    Fatal rather than best-effort: a later writer may have changed what a
    field *means*, and reading it under today's rules would produce confident
    nonsense. There is no forward guessing and no automatic migration.
    """


class UnregisteredArtifactError(LedgerError):
    """An outcome was offered for an artifact the ledger has never registered.

    Outcomes embed their artifact, so the line would be self-contained; it
    is refused anyway, because a ledger in which an outcome exists for a
    claim that was never registered as made is not a ledger of what was
    claimed. Registration is explicit and is never performed implicitly.
    """

    def __init__(self, *, artifact_key: str, outcome_key: str) -> None:
        self.artifact_key = artifact_key
        self.outcome_key = outcome_key
        super().__init__(
            f"outcome {outcome_key} embeds artifact {artifact_key}, which is not "
            "registered in this ledger; register the artifact first"
        )


class ArtifactMismatchError(LedgerError):
    """An outcome embeds an artifact whose key is registered but whose content
    is not what was registered under that key.

    The key names the *producer* (market point plus hypothesis or policy);
    the content includes the claim and the audit facts. Two contents under
    one key are two truths, and the ledger records neither of them twice.
    """

    def __init__(self, *, artifact_key: str, outcome_key: str, detail: str) -> None:
        self.artifact_key = artifact_key
        self.outcome_key = outcome_key
        self.detail = detail
        super().__init__(
            f"outcome {outcome_key} embeds artifact {artifact_key} with content that "
            f"differs from the registered artifact ({detail}); nothing was written"
        )


# -- write result ---------------------------------------------------------------------


class WriteStatus(str, Enum):
    """What one write did. Exactly one per write, and none is an error."""

    #: A new key; exactly one record was appended.
    WRITTEN = "written"

    #: The key was already held with exactly this record; nothing was written.
    DUPLICATE = "duplicate"

    #: The key was already held with a *different* record; nothing was
    #: written. The ledger keeps the record it had. Which of the two is
    #: right is not the ledger's question.
    CONFLICT = "conflict"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class WriteResult:
    """The status of one write and the key it concerned.

    ``detail`` is empty for ``WRITTEN`` and ``DUPLICATE``; for ``CONFLICT``
    it names the fields that differ, for a person reading a log.
    """

    status: WriteStatus
    key: str
    detail: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        try:
            set_(self, "status", WriteStatus(self.status))
        except ValueError:
            raise OutcomeTrackingError(f"unknown write status {self.status!r}") from None
        set_(self, "key", require_key(self.key, "key"))
        if not isinstance(self.detail, str):
            raise OutcomeTrackingError(f"detail must be a str, got {type(self.detail).__name__}")

    @property
    def written(self) -> bool:
        return self.status is WriteStatus.WRITTEN


# -- partition --------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerPartition:
    """One market context: the ``(symbol, interval, basis)`` a record belongs to.

    Basis is part of it deliberately. A raw and an adjusted claim about the
    same bar are different artifacts with different keys, and they are kept
    apart on disk so that a reader asking for one basis can never be handed
    the other by accident.

    Symbol is taken verbatim. It is identity, and identity is never
    normalised, trimmed or re-cased here; an adapter that cannot represent a
    symbol as a location refuses it rather than rewriting it.
    """

    symbol: str
    interval: Interval
    basis: PriceBasis

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "symbol", require_text(self.symbol, "symbol"))
        try:
            set_(self, "interval", Interval.parse(self.interval))
        except (ValueError, TypeError) as exc:
            raise OutcomeTrackingError(f"interval: {exc}") from None
        try:
            set_(self, "basis", PriceBasis(self.basis))
        except ValueError:
            raise OutcomeTrackingError(f"unknown price basis {self.basis!r}") from None

    @classmethod
    def of_artifact(cls, artifact: TrackedArtifact) -> "LedgerPartition":
        if not isinstance(artifact, TrackedArtifact):
            raise OutcomeTrackingError(
                f"expected a TrackedArtifact, got {type(artifact).__name__}"
            )
        return cls(symbol=artifact.symbol, interval=artifact.interval, basis=artifact.basis)

    @classmethod
    def of_outcome(cls, outcome: OutcomeRecord) -> "LedgerPartition":
        if not isinstance(outcome, OutcomeRecord):
            raise OutcomeTrackingError(f"expected an OutcomeRecord, got {type(outcome).__name__}")
        return cls.of_artifact(outcome.artifact)

    def contains(self, artifact: TrackedArtifact) -> bool:
        """Whether ``artifact`` belongs here: exact symbol, interval and basis."""
        return (
            artifact.symbol == self.symbol
            and artifact.interval is self.interval
            and artifact.basis is self.basis
        )

    @property
    def label(self) -> str:
        return f"{self.symbol}/{self.interval.value}/{self.basis.value}"


# -- protocols ------------------------------------------------------------------------


class OutcomeReader(Protocol):
    """Read-only access to one ledger. Every record returned is immutable.

    Structural, and deliberately not ``runtime_checkable`` (the project's
    convention for protocols): an ``isinstance`` check would assert only
    that six names exist. The tests assert the adapter's real signatures.

    Every read is scoped to a :class:`LedgerPartition`. Reads of a partition
    the ledger has never written are empty, and a read never creates
    anything. Iteration order is the ledger's append order.
    """

    def iter_artifacts(self, partition: LedgerPartition) -> Iterator[TrackedArtifact]:
        """Every registered artifact in ``partition``, in append order."""

    def iter_outcomes(self, partition: LedgerPartition) -> Iterator[OutcomeRecord]:
        """Every appended outcome in ``partition``, in append order."""

    def get_artifact(self, partition: LedgerPartition, key: str) -> TrackedArtifact | None:
        """The artifact registered under ``key``, or ``None``."""

    def get_outcome(self, partition: LedgerPartition, key: str) -> OutcomeRecord | None:
        """The outcome appended under ``key``, or ``None``."""

    def contains_artifact(self, partition: LedgerPartition, key: str) -> bool:
        """Whether an artifact is registered under ``key``."""

    def contains_outcome(self, partition: LedgerPartition, key: str) -> bool:
        """Whether an outcome is appended under ``key``."""


class OutcomeLedger(OutcomeReader, Protocol):
    """A reader that can also append. Two writes, both idempotent by key.

    Neither write takes a partition: it is derived from the record, so a
    record cannot land in a partition it does not belong to. Neither write
    ever performs the other -- appending an outcome does not register its
    embedded artifact. The caller (the 12D application service) sequences
    them, and the ledger refuses an outcome whose artifact it has not seen.

    The two writes are two separate durable facts. There is no transaction
    spanning them.
    """

    def register_artifact(self, artifact: TrackedArtifact) -> WriteResult:
        """Append ``artifact`` unless its key is already held.

        ``WRITTEN`` for a new key; ``DUPLICATE`` when the held record is
        exactly this one; ``CONFLICT`` when the held record differs (same
        producer, same bar, a different claim or different audit facts). A
        conflict writes nothing and keeps the record already held.
        """

    def append_outcome(self, outcome: OutcomeRecord) -> WriteResult:
        """Append ``outcome`` unless its key is already held.

        Only a complete :class:`~src.outcomes.models.OutcomeRecord` can be
        appended: pending, ineligible and refused evaluations are not
        outcomes and have no line. The embedded artifact must already be
        registered with exactly the embedded content
        (:class:`UnregisteredArtifactError`, :class:`ArtifactMismatchError`
        otherwise). Statuses as for :meth:`register_artifact`.
        """


__all__ = [
    "LedgerError",
    "LedgerCorruption",
    "UnsupportedSchemaError",
    "UnregisteredArtifactError",
    "ArtifactMismatchError",
    "WriteStatus",
    "WriteResult",
    "LedgerPartition",
    "OutcomeReader",
    "OutcomeLedger",
]
