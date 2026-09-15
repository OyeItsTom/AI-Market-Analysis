"""Outcome tracking on the explicit refresh: register what was claimed, record what followed.

    ResearchSnapshot  ->  current artifacts  ->  ledger.register_artifact
    ledger artifacts  ->  evaluate_artifact  ->  ledger.append_outcome

This module **orchestrates**; it measures nothing, hashes nothing and writes
nothing itself. Phase 12A owns the records and their identity, Phase 12B
(:func:`~src.outcomes.evaluate_artifact`) owns every measurement through
Phase 4, and Phase 12C (an :class:`~src.outcomes.OutcomeLedger`) owns
durability. What is left for this layer is sequencing and the dashboard's own
policy: which horizons are tracked, which snapshot point is registered, and
what one refresh reports back.

One refresh, one series, one clock
----------------------------------
:func:`refresh_outcomes` receives a completed :class:`ResearchSnapshot` and
uses the series *inside* it. That series is the one settled series
(``include_unsettled=False``, see :func:`~src.application.snapshot.build_snapshot`)
the snapshot's observations and assessment were computed from, and the
snapshot is the only object that can vouch for that; accepting a second series
beside it would create the mismatch this design exists to make impossible.
There is no fetch here, no retry and no second provider call.

``now`` is the caller's single clock reading for the refresh. It is the
``recorded_at`` of every artifact registered on this refresh and the
``evaluated_at`` of every outcome completed on it. The dashboard passes the
snapshot's own ``built_at``, so a refresh reads a clock exactly once.

Prospective only: the tail rule
-------------------------------
A snapshot classifies one bar -- the last settled bar of its series -- and
that is the only point registered. Every observation and the assessment must
carry that bar's timestamp; anything else is a retrospective claim and is
refused outright rather than stored beside prospective ones. Nothing is
backfilled and nothing is replayed.

Re-registration is not a contradiction
--------------------------------------
Two refreshes on one day see the same settled bars and produce the same
claims, differing only in the clock. An artifact's ``recorded_at`` is the
clock of its *registration*, and registration happens once: the ledger is
append-only and never rewrites a line. So when the ledger already holds the
key of a claim this refresh derived, the claim is offered with the **held**
registration clock rather than this refresh's -- and then the ledger, and
only the ledger, decides: ``DUPLICATE`` when the claim is the one it holds,
``CONFLICT`` when any other field differs. This layer aligns one field it
knows to be the ledger's; it compares nothing and never pre-empts a verdict.

Nothing pending is stored, and nothing is a transaction
-------------------------------------------------------
``PENDING``, ``INELIGIBLE``, ``REFUSED`` and ``OUT_OF_WINDOW`` are derived on
every refresh from the ledger and the series, and reported. Only artifacts
and completed :class:`~src.outcomes.OutcomeRecord` values are durable, and a
ledger that cannot be read (:class:`~src.outcomes.LedgerCorruption`) is
never repaired, skipped or replaced here; it propagates.

A refresh is a sequence of independent appends, not a transaction. If it
raises part-way, every artifact and outcome appended before the failure is
already durable and stays so; nothing is rolled back, because there is
nothing wrong with those records. The next refresh reads the ledger again,
finds them ``DUPLICATE`` or ``PRESENT``, and carries on from there -- that
idempotency, not atomicity, is what makes a partial refresh safe.

This is operational bookkeeping. Counts of what was written and what is
still waiting are reported; hit rates, mean returns and any comparison across
states are a later stage's question and are deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.evaluation import OutcomeSpec
from src.outcomes import (
    EVALUATION_VERSION,
    ArtifactKind,
    ArtifactOrigin,
    AssessmentArtifact,
    JsonlOutcomeLedger,
    LedgerPartition,
    ObservationArtifact,
    OutcomeLedger,
    OutcomeTrackingError,
    RefusalReason,
    TrackedArtifact,
    TrackingStatus,
    WriteStatus,
    bar_fingerprint,
    evaluate_artifact,
    outcome_key,
)

from .snapshot import BASIS, ResearchSnapshot

#: Forward horizons the dashboard tracks, in bars of the refreshed series.
#: The Phase 12 architecture decision; declared once, here, and passed
#: explicitly -- nothing downstream assumes a horizon.
OUTCOME_HORIZONS: tuple[int, ...] = (1, 5, 20)

#: The outcome specifications those horizons name, on the basis the dashboard
#: researches. Fingerprints are the specifications' own.
OUTCOME_SPECS: tuple[OutcomeSpec, ...] = tuple(
    OutcomeSpec(horizon_bars=horizon, required_basis=BASIS) for horizon in OUTCOME_HORIZONS
)

#: Where the local ledger lives when nothing is injected: the repository's
#: ``data/outcomes``, resolved from this file like every other local data
#: root in the project, never from the working directory. The store itself
#: has no default root; choosing one is this layer's job.
DEFAULT_OUTCOMES_ROOT: Path = Path(__file__).resolve().parents[2] / "data" / "outcomes"


def build_outcome_ledger(root: str | Path | None = None) -> JsonlOutcomeLedger:
    """The concrete ledger the dashboard tracks into.

    Constructed here rather than in the UI so :mod:`src.dashboard` never
    names a store, a file or a path. Construction touches nothing: the first
    read or write is the first time the directory is consulted.
    """
    return JsonlOutcomeLedger(DEFAULT_OUTCOMES_ROOT if root is None else root)


class OutcomeRefreshError(OutcomeTrackingError):
    """The refresh could not be carried out as a coherent whole.

    Raised for a malformed request (bad specifications, a naive clock), a
    snapshot that does not describe its own series, a claim that is not the
    series' tail, and a ledger ``CONFLICT`` on either write. The cause, where
    there is one, is chained; the message names no path.
    """


class OutcomeItemStatus(str, Enum):
    """What this refresh concluded about one (artifact, specification) pair."""

    #: An outcome was already durable before this refresh; nothing was measured.
    PRESENT = "present"

    #: Measured on this refresh and appended to the ledger.
    WRITTEN = "written"

    #: Phase 12B: the bars that complete the horizon are not in the series yet.
    PENDING = "pending"

    #: Phase 12B: the artifact carries no classification to measure.
    INELIGIBLE = "ineligible"

    #: Phase 12B: the series is not this artifact's data (``refusal`` says why).
    REFUSED = "refused"

    #: The refreshed series begins after the artifact's bar, so this refresh
    #: cannot say anything about it. Decided here, before Phase 4 is asked:
    #: the fetch window is finite, and a claim older than it is not a data
    #: fault. A bar *inside* the window that is missing remains a hard error.
    OUT_OF_WINDOW = "out_of_window"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ArtifactRegistration:
    """One current claim and what registering it did. Immutable."""

    artifact_key: str
    kind: ArtifactKind
    label: str
    status: WriteStatus

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "kind", ArtifactKind(self.kind))
        set_(self, "status", WriteStatus(self.status))
        if self.status is WriteStatus.CONFLICT:
            raise OutcomeRefreshError(
                "a registration conflict is a failure, not a result; it is raised"
            )


@dataclass(frozen=True)
class OutcomeItem:
    """One tracked artifact under one specification, as concluded. Immutable."""

    artifact_key: str
    kind: ArtifactKind
    label: str
    timestamp: datetime
    spec_fingerprint: str
    horizon_bars: int
    status: OutcomeItemStatus
    refusal: RefusalReason | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "kind", ArtifactKind(self.kind))
        set_(self, "status", OutcomeItemStatus(self.status))
        if self.refusal is not None:
            set_(self, "refusal", RefusalReason(self.refusal))
        if (self.refusal is not None) != (self.status is OutcomeItemStatus.REFUSED):
            raise OutcomeRefreshError(
                f"a {self.status.value!r} item must carry a refusal reason exactly when "
                "it is refused"
            )


@dataclass(frozen=True)
class OutcomeRefreshResult:
    """What one outcome refresh did, for the caller. Immutable.

    Per-item records in a deterministic order -- registrations in snapshot
    order, items in ledger append order crossed with the caller's
    specification order -- and counts derived from them, so a count can never
    disagree with the items it summarises. No performance figure of any kind.
    """

    symbol: str
    interval: Interval
    basis: PriceBasis
    now: datetime
    registrations: tuple[ArtifactRegistration, ...]
    items: tuple[OutcomeItem, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "now", _require_aware(self.now, "now"))
        set_(self, "registrations", tuple(self.registrations))
        set_(self, "items", tuple(self.items))
        for entry in self.registrations:
            if not isinstance(entry, ArtifactRegistration):
                raise OutcomeRefreshError(
                    f"registrations must be ArtifactRegistration, got {type(entry).__name__}"
                )
        for entry in self.items:
            if not isinstance(entry, OutcomeItem):
                raise OutcomeRefreshError(
                    f"items must be OutcomeItem, got {type(entry).__name__}"
                )

    # -- counts, all derived ------------------------------------------------------

    def _count(self, status: OutcomeItemStatus) -> int:
        return sum(1 for item in self.items if item.status is status)

    @property
    def artifacts_considered(self) -> int:
        return len(self.registrations)

    @property
    def artifacts_written(self) -> int:
        return sum(1 for entry in self.registrations if entry.status is WriteStatus.WRITTEN)

    @property
    def artifact_duplicates(self) -> int:
        return sum(1 for entry in self.registrations if entry.status is WriteStatus.DUPLICATE)

    @property
    def artifacts_tracked(self) -> int:
        """Distinct ledger artifacts this refresh looked at."""
        return len({item.artifact_key for item in self.items})

    @property
    def outcomes_already_present(self) -> int:
        return self._count(OutcomeItemStatus.PRESENT)

    @property
    def outcomes_written(self) -> int:
        return self._count(OutcomeItemStatus.WRITTEN)

    @property
    def pending(self) -> int:
        return self._count(OutcomeItemStatus.PENDING)

    @property
    def ineligible(self) -> int:
        return self._count(OutcomeItemStatus.INELIGIBLE)

    @property
    def refused(self) -> int:
        return self._count(OutcomeItemStatus.REFUSED)

    @property
    def out_of_window(self) -> int:
        return self._count(OutcomeItemStatus.OUT_OF_WINDOW)

    # -- for the caller -------------------------------------------------------------

    def describes(self, snapshot: ResearchSnapshot) -> bool:
        """Whether this result came from exactly this snapshot's refresh."""
        return (
            isinstance(snapshot, ResearchSnapshot)
            and self.symbol == snapshot.symbol
            and self.interval is snapshot.interval
            and self.basis is snapshot.basis
            and self.now == snapshot.built_at
        )

    @property
    def summary(self) -> str:
        """One plain sentence of operational counts. Nothing is scored."""
        parts = [
            f"{self.artifacts_considered} claim{'s' if self.artifacts_considered != 1 else ''} "
            f"registered ({self.artifacts_written} new)",
            f"{self.outcomes_written} new outcome{'s' if self.outcomes_written != 1 else ''}",
            f"{self.pending} pending",
        ]
        if self.ineligible:
            parts.append(f"{self.ineligible} not evaluable")
        if self.refused:
            parts.append(f"{self.refused} refused")
        if self.out_of_window:
            parts.append(f"{self.out_of_window} outside the fetched history")
        return "Outcome tracking: " + ", ".join(parts) + "."


# -- the refresh -------------------------------------------------------------------------


def refresh_outcomes(
    snapshot: ResearchSnapshot,
    specs: Sequence[OutcomeSpec],
    ledger: OutcomeLedger,
    *,
    now: datetime,
) -> OutcomeRefreshResult:
    """Register the snapshot's claims, then complete every outcome the series allows.

    In order, and none of it reading anything the caller did not supply:

    1. **Request.** ``specs`` is non-empty, each an :class:`OutcomeSpec` on the
       snapshot's basis, no two with one fingerprint; ``now`` is aware.
    2. **Coherence.** The snapshot's symbol, interval, basis and source are
       its series'. Its observations and assessment all describe the series'
       last bar (the tail rule); a claim about any other bar is refused.
    3. **Register.** One :class:`~src.outcomes.ObservationArtifact` per
       observation and one :class:`~src.outcomes.AssessmentArtifact` for the
       assessment, audit fields from the series and ``now``. A claim whose
       key the ledger already holds is offered with the held registration
       clock (see the module docstring). Every claim is offered, and the
       ledger's verdict is the result: ``WRITTEN`` or ``DUPLICATE`` is
       recorded, ``CONFLICT`` raises.
    4. **Evaluate.** Every artifact the ledger holds for this partition, under
       every specification, in that order. A pair whose outcome key is
       already held is ``PRESENT`` and is not re-measured. An evaluable
       artifact whose bar precedes the series' first is ``OUT_OF_WINDOW``.
       Everything else goes through :func:`~src.outcomes.evaluate_artifact`;
       an ``EVALUATED`` result is appended (``WRITTEN``; a ``DUPLICATE``
       verdict is ``PRESENT``; ``CONFLICT`` raises), and the other statuses
       are reported as they are.

    Not a transaction: a failure part-way leaves earlier appends durable
    (see the module docstring); the next refresh is idempotent over them.

    Raises
    ------
    OutcomeRefreshError
        Steps 1-2, or a ledger ``CONFLICT``.
    OutcomeTrackingError
        Anything Phase 12B or the ledger refuses: an artifact whose bar the
        series should hold and does not, a clock before a registration, a
        ledger whose bytes cannot be read. Never caught here.
    """
    if not isinstance(snapshot, ResearchSnapshot):
        raise OutcomeRefreshError(
            f"snapshot must be a ResearchSnapshot, got {type(snapshot).__name__}"
        )
    now = _require_aware(now, "now")
    specs = _require_specs(specs, snapshot.basis)
    series = _require_coherent(snapshot)
    partition = LedgerPartition(symbol=snapshot.symbol, interval=snapshot.interval,
                                basis=snapshot.basis)

    current = _current_artifacts(snapshot, series, now)

    # One read of the partition's artifacts; the ledger stays the authority
    # for every write.
    held: dict[str, TrackedArtifact] = {
        artifact.artifact_key: artifact for artifact in ledger.iter_artifacts(partition)
    }
    registrations: list[ArtifactRegistration] = []
    for artifact in current:
        key = artifact.artifact_key
        existing = held.get(key)
        if existing is not None:
            # A re-sighting of a held key: the registration clock is the
            # ledger's, from the moment it first held the claim. With that one
            # field aligned, the ledger's verdict decides -- DUPLICATE for the
            # same claim, CONFLICT for a different one. Nothing is compared here.
            artifact = replace(artifact, recorded_at=existing.recorded_at)
        verdict = ledger.register_artifact(artifact)
        if verdict.status is WriteStatus.CONFLICT:
            raise OutcomeRefreshError(
                f"the ledger already holds a different claim under artifact "
                f"{key} ({artifact.kind.value} {artifact.label}): {verdict.detail}"
            )
        # DUPLICATE means the held record *is* this claim; track the held one.
        held[key] = artifact if existing is None else existing
        registrations.append(
            ArtifactRegistration(artifact_key=key, kind=artifact.kind,
                                 label=artifact.label, status=verdict.status)
        )

    present = {outcome.outcome_key for outcome in ledger.iter_outcomes(partition)}
    first_open = series[0].timestamp if len(series) else None

    items: list[OutcomeItem] = []
    for artifact in held.values():
        for spec in specs:
            key = outcome_key(artifact_key=artifact.artifact_key,
                              spec_fingerprint=spec.fingerprint,
                              evaluation_version=EVALUATION_VERSION)
            refusal: RefusalReason | None = None
            if key in present:
                status = OutcomeItemStatus.PRESENT
            elif artifact.is_evaluable and (first_open is None or artifact.timestamp < first_open):
                # Ineligibility is the artifact's own and needs no bars, so it
                # is left to Phase 12B below; only an evaluable claim can be
                # out of the fetched window.
                status = OutcomeItemStatus.OUT_OF_WINDOW
            else:
                tracked = evaluate_artifact(artifact, series, spec, evaluated_at=now)
                if tracked.status is TrackingStatus.EVALUATED:
                    verdict = ledger.append_outcome(tracked.outcome)
                    if verdict.status is WriteStatus.CONFLICT:
                        raise OutcomeRefreshError(
                            f"the ledger already holds a different outcome under "
                            f"{key} ({artifact.kind.value} {artifact.label} "
                            f"{spec.label}): {verdict.detail}"
                        )
                    status = (
                        OutcomeItemStatus.WRITTEN
                        if verdict.status is WriteStatus.WRITTEN
                        else OutcomeItemStatus.PRESENT
                    )
                    present.add(key)
                elif tracked.status is TrackingStatus.PENDING:
                    status = OutcomeItemStatus.PENDING
                elif tracked.status is TrackingStatus.INELIGIBLE:
                    status = OutcomeItemStatus.INELIGIBLE
                else:
                    status = OutcomeItemStatus.REFUSED
                    refusal = tracked.refusal
            items.append(
                OutcomeItem(
                    artifact_key=artifact.artifact_key, kind=artifact.kind,
                    label=artifact.label, timestamp=artifact.timestamp,
                    spec_fingerprint=spec.fingerprint, horizon_bars=spec.horizon_bars,
                    status=status, refusal=refusal,
                )
            )

    return OutcomeRefreshResult(
        symbol=snapshot.symbol, interval=snapshot.interval, basis=snapshot.basis, now=now,
        registrations=tuple(registrations), items=tuple(items),
    )


# -- steps --------------------------------------------------------------------------------


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise OutcomeRefreshError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OutcomeRefreshError(f"{label} must be timezone-aware")
    return value


def _require_specs(specs: object, basis: PriceBasis) -> tuple[OutcomeSpec, ...]:
    """Explicit, non-empty, unique, on the snapshot's basis, caller's order kept."""
    if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
        raise OutcomeRefreshError(
            f"specs must be a sequence of OutcomeSpec, got {type(specs).__name__}"
        )
    checked = tuple(specs)
    if not checked:
        raise OutcomeRefreshError("specs must not be empty; tracking needs a horizon to track")
    seen: set[str] = set()
    for spec in checked:
        if not isinstance(spec, OutcomeSpec):
            raise OutcomeRefreshError(
                f"every spec must be an OutcomeSpec, got {type(spec).__name__}"
            )
        if spec.required_basis is not basis:
            raise OutcomeRefreshError(
                f"spec {spec.label} requires {spec.required_basis.value!r} prices but the "
                f"snapshot is {basis.value!r}; no basis is converted here"
            )
        if spec.fingerprint in seen:
            raise OutcomeRefreshError(f"duplicate outcome specification {spec.label}")
        seen.add(spec.fingerprint)
    return checked


def _require_coherent(snapshot: ResearchSnapshot) -> BarSeries:
    """The snapshot must describe its own series, and claim only its tail."""
    series = snapshot.series
    if not isinstance(series, BarSeries):
        raise OutcomeRefreshError(
            f"snapshot.series must be a BarSeries, got {type(series).__name__}"
        )
    for name, snapshot_value, series_value in (
        ("symbol", snapshot.symbol, series.symbol),
        ("interval", snapshot.interval, series.interval),
        ("basis", snapshot.basis, series.basis),
        ("source", snapshot.source, series.source),
    ):
        if snapshot_value != series_value:
            raise OutcomeRefreshError(
                f"snapshot {name} {snapshot_value!r} does not match its series' "
                f"{series_value!r}; the snapshot does not describe its own data"
            )

    claims = [(o.label, o.timestamp) for o in snapshot.observations]
    if snapshot.assessment is not None:
        claims.append((f"policy#{snapshot.assessment.policy_fingerprint}",
                       snapshot.assessment.timestamp))
    if claims and not len(series):
        raise OutcomeRefreshError("the snapshot carries claims but its series has no bars")
    for label, timestamp in claims:
        if timestamp != series[-1].timestamp:
            raise OutcomeRefreshError(
                f"{label} describes bar {timestamp.isoformat()}, not the series' last "
                f"settled bar {series[-1].timestamp.isoformat()}; only the current "
                "research point is registered, never a retrospective one"
            )
    return series


def _current_artifacts(
    snapshot: ResearchSnapshot, series: BarSeries, now: datetime
) -> tuple[TrackedArtifact, ...]:
    """The snapshot's claims as artifacts: observations in snapshot order, then
    the assessment. Audit fields come from the series' tail and ``now``."""
    if not len(series):
        return ()
    tail = series[-1]
    audit: Mapping[str, object] = dict(
        source=series.source,
        data_cutoff=tail.timestamp,
        recorded_at=now,
        observation_bar_fingerprint=bar_fingerprint(tail),
        origin=ArtifactOrigin.SNAPSHOT,
    )
    artifacts: list[TrackedArtifact] = [
        ObservationArtifact.from_observation(observation, **audit)
        for observation in snapshot.observations
    ]
    if snapshot.assessment is not None:
        artifacts.append(AssessmentArtifact.from_assessment(snapshot.assessment, **audit))
    return tuple(artifacts)


__all__ = [
    "OUTCOME_HORIZONS",
    "OUTCOME_SPECS",
    "DEFAULT_OUTCOMES_ROOT",
    "build_outcome_ledger",
    "OutcomeRefreshError",
    "OutcomeItemStatus",
    "ArtifactRegistration",
    "OutcomeItem",
    "OutcomeRefreshResult",
    "refresh_outcomes",
]
