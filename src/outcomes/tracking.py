"""Evaluate one tracked artifact against settled bars: Phase 4 measures, Phase 12 records.

    TrackedArtifact + BarSeries + OutcomeSpec + evaluated_at  ->  TrackingResult

A :class:`TrackingResult` is either exactly one trusted
:class:`~src.outcomes.models.OutcomeRecord` (``EVALUATED``) or a
deterministic statement of why there is none: the future bars are not yet
in the series (``PENDING``), the artifact carries no classification to
measure (``INELIGIBLE``), or the supplied bars are not the bars the artifact
was derived from (``REFUSED``). Nothing is partially constructed and nothing
is guessed.

Division of authority
---------------------
Phase 4 (:func:`src.evaluation.measure_forward`) is the only thing that
reads prices. It owns symbol/interval/basis alignment, exact timestamp
matching, the reference convention, the horizon arithmetic and the forward
return; this module never re-derives any of them. This module owns what
Phase 4 cannot know: whether the *provider* is the one the claim was made
from, whether the claimed bar has been *revised* since, which exact bars
the completed measurement rested on, and the shape of the resulting record.

Settledness is not inferred here
--------------------------------
Every timestamp in a :class:`~src.data.series.BarSeries` is a bar **open**.
``evaluated_at > future_timestamp`` therefore says only that the future bar
had *opened* before the measurement clock -- it says nothing about whether
that bar had closed and its OHLCV was final. This module does not compute
settlement from interval arithmetic either: a bar's true close is an
exchange-calendar fact this system does not have. It operates on a series
the caller declares to contain **settled bars only**, which is the fetch
layer's guarantee (``include_unsettled=False``) and, from 12D on, the
application's responsibility to honour. The one clock check kept here is
the necessary bound :class:`~src.outcomes.models.OutcomeRecord` already
enforces, not a proof.

Purity
------
Everything is caller-supplied: the artifact, the bars, the specification
and the evaluation clock. Nothing here reads a clock, a file, an
environment variable or a network, and neither the artifact nor the series
is mutated -- both are frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.data.models import MarketBar
from src.data.series import BarSeries
from src.evaluation import EvaluationError, ForwardMeasurement, OutcomeSpec, measure_forward

from .identity import OutcomeTrackingError, bar_fingerprint, bars_fingerprint, require_aware
from .models import EVALUATION_VERSION, OutcomeRecord, TrackedArtifact


class TrackingStatus(str, Enum):
    """What :func:`evaluate_artifact` concluded.

    Exactly one of these per call. ``EVALUATED`` is the only status that
    carries an :class:`~src.outcomes.models.OutcomeRecord`; every other one
    carries none, and none of them is a zero result.
    """

    #: A complete measurement; ``TrackingResult.outcome`` is the record.
    EVALUATED = "evaluated"

    #: The bars needed to complete the horizon are not in the series yet.
    #: Phase 4's own finding (``NO_REFERENCE_BAR`` or
    #: ``INSUFFICIENT_FUTURE_DATA``) is kept on the result unchanged.
    PENDING = "pending"

    #: The artifact's state is ``INSUFFICIENT_DATA``; there is nothing to
    #: measure and Phase 4 was not consulted.
    INELIGIBLE = "ineligible"

    #: The series is not the data this artifact was derived from. The
    #: :class:`RefusalReason` says why. No measurement is trusted.
    REFUSED = "refused"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class RefusalReason(str, Enum):
    """Why a series was refused for an artifact. Deliberately small.

    Structural misuse -- wrong type, wrong symbol, wrong interval, wrong
    basis, a timestamp that is not a bar -- is a caller error and raises,
    exactly as Phase 4 raises for an observation. A refusal is reserved for
    data that is *structurally* aligned and still not the artifact's data.

    A series that lacks the claimed bar altogether is deliberately **not** a
    refusal and not pending: Phase 4 treats a timestamp that is not a bar as
    a structural error, and 12B inherits that. The caller owns supplying a
    series that covers the claimed bar; a provider that has *dropped* the bar
    is a data-quality event to surface, not a state to record.
    """

    #: ``artifact.source != series.source``. Checked before anything is
    #: measured and independently of bar content: numerically identical
    #: bars from a different provider are a different evidential basis, not
    #: automatically the same one.
    SOURCE_MISMATCH = "source_mismatch"

    #: The bar the artifact was derived from no longer has the content it
    #: had at registration (``bar_fingerprint`` differs). The claim rested
    #: on numbers that have since changed; measuring it against the revised
    #: history would attach an outcome to a claim nobody made.
    SOURCE_BAR_REVISED = "source_bar_revised"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class TrackingResult:
    """The outcome of one :func:`evaluate_artifact` call. Immutable.

    Field presence is pinned to the status so the record cannot claim more
    than it found: an ``EVALUATED`` result has an outcome and the Phase 4
    measurement it came from; a ``PENDING`` result has the measurement
    (whose own status says which bar was missing) and no outcome; an
    ``INELIGIBLE`` result has neither; a ``REFUSED`` result has a reason and
    neither. Nothing else is representable.
    """

    artifact: TrackedArtifact
    spec: OutcomeSpec
    evaluated_at: datetime
    status: TrackingStatus
    outcome: OutcomeRecord | None = None
    measurement: ForwardMeasurement | None = None
    refusal: RefusalReason | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if not isinstance(self.artifact, TrackedArtifact):
            raise OutcomeTrackingError(
                f"artifact must be a TrackedArtifact, got {type(self.artifact).__name__}"
            )
        if not isinstance(self.spec, OutcomeSpec):
            raise OutcomeTrackingError(f"spec must be an OutcomeSpec, got {type(self.spec).__name__}")
        set_(self, "evaluated_at", require_aware(self.evaluated_at, "evaluated_at"))
        try:
            set_(self, "status", TrackingStatus(self.status))
        except ValueError:
            raise OutcomeTrackingError(f"unknown tracking status {self.status!r}") from None
        if self.refusal is not None:
            try:
                set_(self, "refusal", RefusalReason(self.refusal))
            except ValueError:
                raise OutcomeTrackingError(f"unknown refusal reason {self.refusal!r}") from None

        has_outcome = self.outcome is not None
        has_measurement = self.measurement is not None
        has_refusal = self.refusal is not None
        expected = {
            TrackingStatus.EVALUATED: (True, True, False),
            TrackingStatus.PENDING: (False, True, False),
            TrackingStatus.INELIGIBLE: (False, False, False),
            TrackingStatus.REFUSED: (False, False, True),
        }[self.status]
        if (has_outcome, has_measurement, has_refusal) != expected:
            raise OutcomeTrackingError(
                f"a {self.status.value!r} result must carry outcome={expected[0]}, "
                f"measurement={expected[1]}, refusal={expected[2]}; got "
                f"outcome={has_outcome}, measurement={has_measurement}, refusal={has_refusal}"
            )
        # A result is a record with a clock, whatever its status: a claim
        # cannot be looked at before it was recorded. OutcomeRecord enforces
        # the same rule for the evaluated case; it is stated here so that a
        # PENDING, INELIGIBLE or REFUSED result cannot carry an impossible
        # clock either.
        if self.evaluated_at < self.artifact.recorded_at:
            raise OutcomeTrackingError(
                f"evaluated_at {self.evaluated_at.isoformat()} precedes recorded_at "
                f"{self.artifact.recorded_at.isoformat()}; a claim cannot be measured before "
                "it was recorded"
            )
        if has_outcome:
            if not isinstance(self.outcome, OutcomeRecord):
                raise OutcomeTrackingError(
                    f"outcome must be an OutcomeRecord, got {type(self.outcome).__name__}"
                )
            if self.outcome.artifact != self.artifact:
                raise OutcomeTrackingError("the outcome does not embed this result's artifact")
            # The record and the result describe one measurement: same
            # clock, same specification. A result must not relabel its record.
            if self.outcome.evaluated_at != self.evaluated_at:
                raise OutcomeTrackingError(
                    f"the outcome was evaluated at {self.outcome.evaluated_at.isoformat()}, "
                    f"not at this result's {self.evaluated_at.isoformat()}"
                )
            if (self.outcome.spec_fingerprint, self.outcome.horizon_bars) != (
                self.spec.fingerprint, self.spec.horizon_bars
            ):
                raise OutcomeTrackingError(
                    f"the outcome was measured under spec#{self.outcome.spec_fingerprint} "
                    f"h={self.outcome.horizon_bars}, not this result's {self.spec.label}"
                )
        if has_measurement:
            if not isinstance(self.measurement, ForwardMeasurement):
                raise OutcomeTrackingError(
                    f"measurement must be a ForwardMeasurement, got "
                    f"{type(self.measurement).__name__}"
                )
            # The measurement's own status must agree with ours: an EVALUATED
            # result rests on an EVALUATED measurement, a PENDING one on an
            # incomplete measurement.
            if self.measurement.is_evaluated != (self.status is TrackingStatus.EVALUATED):
                raise OutcomeTrackingError(
                    f"a {self.status.value!r} result cannot rest on a "
                    f"{self.measurement.status.value!r} measurement"
                )

    @property
    def is_evaluated(self) -> bool:
        return self.status is TrackingStatus.EVALUATED

    def describe(self) -> str:
        detail = ""
        if self.outcome is not None:
            detail = f" {self.outcome.forward_return:+.6f}"
        elif self.measurement is not None:
            detail = f" ({self.measurement.status.value})"
        elif self.refusal is not None:
            detail = f" ({self.refusal.value})"
        return (
            f"{self.artifact.kind.value} {self.artifact.label} {self.artifact.symbol} "
            f"{self.artifact.interval.value} [{self.artifact.basis.value}] "
            f"{self.artifact.timestamp.isoformat()} h={self.spec.horizon_bars} "
            f"-> {self.status.value}{detail} evaluated={self.evaluated_at.isoformat()}"
        )


def evaluate_artifact(
    artifact: TrackedArtifact,
    series: BarSeries,
    spec: OutcomeSpec,
    *,
    evaluated_at: datetime,
) -> TrackingResult:
    """Measure what the market did after ``artifact``'s bar, if it can be known.

    Order of decision, each step deterministic and none reading anything
    the caller did not supply:

    1. **Inputs.** Types are checked and ``evaluated_at`` must be
       timezone-aware. Every further clock rule belongs to the records:
       :class:`TrackingResult` refuses a clock before the artifact's
       ``recorded_at`` for every status, and
       :class:`~src.outcomes.models.OutcomeRecord` refuses one at or before
       the future bar's open.
    2. **Eligibility.** ``INSUFFICIENT_DATA`` carries nothing to measure:
       ``INELIGIBLE``, decided from the artifact alone, no series work.
    3. **Source.** ``artifact.source`` must equal ``series.source``, or the
       result is ``REFUSED`` (``SOURCE_MISMATCH``). This is a provenance
       check and is separate from any comparison of bar content.
    4. **Phase 4.** :func:`~src.evaluation.measure_forward` validates the
       market point against the series (symbol, interval, basis, exact
       timestamp; an ``EvaluationError`` is re-raised as
       :class:`~src.outcomes.identity.OutcomeTrackingError` with the cause
       attached) and measures it.
    5. **Revision.** The series' bar at ``artifact.timestamp`` -- which
       Phase 4 has just proven exists -- is fingerprinted and compared with
       ``artifact.observation_bar_fingerprint``. A difference is ``REFUSED``
       (``SOURCE_BAR_REVISED``) and the measurement is discarded unread:
       revision outranks pending, because the claim's premise is gone
       whether or not the future has arrived.
    6. **Completion.** A ``NO_REFERENCE_BAR`` or ``INSUFFICIENT_FUTURE_DATA``
       measurement is ``PENDING``, Phase 4's finding kept on the result. An
       ``EVALUATED`` measurement becomes exactly one
       :class:`~src.outcomes.models.OutcomeRecord`, whose own invariants
       (evaluation clock after the future bar's open, future bar after the
       artifact's data cutoff, horizon shape, price consistency) are the
       last word; a violation raises rather than degrading to a status.

    ``consumed_bars_fingerprint`` has **causal horizon window** semantics:
    the order-sensitive fingerprint of the bars from the reference bar
    through the future bar inclusive -- exactly ``spec.horizon_bars`` of
    them. Phase 4's arithmetic reads *values* from only the first (open) and
    last (``spec.future_field``) of those bars; the bars between are counted,
    and their existence and order are what make the last one the future bar.
    The window is fingerprinted whole because the outcome is defined over
    that ordered stretch of market history: an insertion, removal or
    revision anywhere inside it changes what this record was measured over,
    even where the number happens to survive. It excludes the claimed bar
    (already fingerprinted as ``observation_bar_fingerprint``) and every bar
    before or after the window, so a revision outside the window is
    invisible, as it should be. It is **not** "the bars whose values entered
    the arithmetic"; that would be only the two ends.

    Raises
    ------
    OutcomeTrackingError
        Malformed input, a wrong clock, a series that does not structurally
        describe the artifact (symbol, interval, basis, or a timestamp that
        is not a bar -- Phase 4's error is the cause), or a completed
        measurement that :class:`~src.outcomes.models.OutcomeRecord` refuses.
    """
    if not isinstance(artifact, TrackedArtifact):
        raise OutcomeTrackingError(
            f"artifact must be a TrackedArtifact, got {type(artifact).__name__}"
        )
    if not isinstance(series, BarSeries):
        raise OutcomeTrackingError(f"series must be a BarSeries, got {type(series).__name__}")
    if not isinstance(spec, OutcomeSpec):
        raise OutcomeTrackingError(f"spec must be an OutcomeSpec, got {type(spec).__name__}")
    evaluated_at = require_aware(evaluated_at, "evaluated_at")
    # Every other clock rule lives on the records themselves: TrackingResult
    # refuses a clock before the artifact was recorded (for any status), and
    # OutcomeRecord refuses one at or before the future bar's open. Nothing
    # is checked twice, and nothing is checked here that a record would accept.

    def result(status: TrackingStatus, **fields) -> TrackingResult:
        return TrackingResult(
            artifact=artifact, spec=spec, evaluated_at=evaluated_at, status=status, **fields
        )

    if not artifact.is_evaluable:
        return result(TrackingStatus.INELIGIBLE)

    if artifact.source != series.source:
        return result(TrackingStatus.REFUSED, refusal=RefusalReason.SOURCE_MISMATCH)

    try:
        measurement = measure_forward(
            series,
            spec,
            symbol=artifact.symbol,
            interval=artifact.interval,
            basis=artifact.basis,
            timestamp=artifact.timestamp,
        )
    except EvaluationError as exc:
        raise OutcomeTrackingError(f"series does not describe the artifact: {exc}") from exc

    # Phase 4 has established that artifact.timestamp is exactly one bar of
    # this series; this is retrieval of that bar, not a second matching rule.
    observed = _bars_within(series, artifact.timestamp, artifact.timestamp)[0]
    if bar_fingerprint(observed) != artifact.observation_bar_fingerprint:
        return result(TrackingStatus.REFUSED, refusal=RefusalReason.SOURCE_BAR_REVISED)

    if not measurement.is_evaluated:
        return result(TrackingStatus.PENDING, measurement=measurement)

    window = _bars_within(series, measurement.reference_timestamp, measurement.future_timestamp)
    if len(window) != spec.horizon_bars:  # pragma: no cover - Phase 4 invariant
        raise OutcomeTrackingError(
            f"the horizon window holds {len(window)} bars, expected {spec.horizon_bars}"
        )

    outcome = OutcomeRecord(
        artifact=artifact,
        spec_fingerprint=spec.fingerprint,
        horizon_bars=spec.horizon_bars,
        evaluation_version=EVALUATION_VERSION,
        evaluated_at=evaluated_at,
        consumed_bars_fingerprint=bars_fingerprint(window),
        reference_timestamp=measurement.reference_timestamp,
        reference_price=measurement.reference_price,
        future_timestamp=measurement.future_timestamp,
        future_price=measurement.future_price,
        forward_return=measurement.outcome_value,
    )
    return result(TrackingStatus.EVALUATED, outcome=outcome, measurement=measurement)


def _bars_within(series: BarSeries, start: datetime, end: datetime) -> tuple[MarketBar, ...]:
    """The series' bars with ``start <= timestamp <= end``, in series order.

    A ``BarSeries`` has unique, strictly increasing timestamps, so this is an
    exact, deterministic slice by the bounds Phase 4 reported -- nothing is
    approximated, and no bar outside the bounds is included.
    """
    return tuple(bar for bar in series if start <= bar.timestamp <= end)


__all__ = [
    "TrackingStatus",
    "RefusalReason",
    "TrackingResult",
    "evaluate_artifact",
]
