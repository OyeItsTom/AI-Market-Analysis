"""Tracked research artifacts and the immutable outcome record.

Two records, deliberately separate:

* a :class:`TrackedArtifact` is **what was claimed** -- one hypothesis'
  observation or one policy's assessment of one bar, copied verbatim from
  the Phase 3/6 record at the moment it was registered, together with the
  audit facts of that moment (which provider, which data cutoff, which bar
  content, which clock reading);
* an :class:`OutcomeRecord` is **what the market did afterwards** -- Phase 4's
  forward measurement of that bar under one outcome specification, attached
  to the artifact it measures.

Nothing here measures anything. Phase 4 (``src.evaluation``) is the only
authority on forward returns; this module only defines the shape a completed
measurement must have to be stored, and refuses shapes Phase 4 could never
have produced. Nothing here reads a clock, a file, a network or an
environment variable: every timestamp and fingerprint is caller-supplied.

Identity vs claim
-----------------
An artifact's key (see :mod:`src.outcomes.identity`) is the *producer*
identity -- market point plus hypothesis triple or policy fingerprint. The
``state`` is the claim that producer made and is **not** in the key. That is
what lets a later ledger detect "same producer, same bar, different claim" as
a conflict rather than silently storing two truths.

Kinds as types
--------------
Observation and assessment artifacts are separate frozen subtypes rather
than one record with nullable fields. A record that *could* carry a policy
fingerprint beside a hypothesis id would need an invariant forbidding it;
a type that cannot express the combination needs none. Both share the
common fields and the :class:`TrackedArtifact` base, so a ledger can hold
either behind one name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar, Sequence

from src.assessments.assessment import (
    AssessmentReasonCode,
    AssessmentState,
    ResearchAssessment,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState

from .identity import (
    OutcomeTrackingError,
    assessment_artifact_key,
    observation_artifact_key,
    outcome_key,
    require_aware,
    require_key,
    require_positive_int,
    require_spec_fingerprint,
    require_text,
)

#: Identifies the Phase 12 measurement/interpretation implementation under
#: which a persisted outcome was produced. It is part of the outcome key, so
#: a change in how outcomes are derived from Phase 4 -- or in what an outcome
#: record means -- produces new records beside the old, never over them.
#:
#: This does **not** version Phase 4 itself: the outcome *contract* (horizon,
#: reference convention, price field, basis) is already identified by
#: ``OutcomeSpec.fingerprint``, which every record also carries.
EVALUATION_VERSION: int = 1

#: Versions this build can construct or interpret. A record declaring any
#: other version is refused rather than read under today's rules.
SUPPORTED_EVALUATION_VERSIONS: frozenset[int] = frozenset({EVALUATION_VERSION})


class ArtifactKind(str, Enum):
    """Which Phase produced the claim."""

    OBSERVATION = "observation"
    ASSESSMENT = "assessment"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ArtifactOrigin(str, Enum):
    """How the artifact came to be registered.

    Phase 12 registers only what a research snapshot actually claimed. A
    retrospective replay of a hypothesis over stored history would be a
    different origin with different evidential weight; it is not represented
    here, and extensibility is through this enum, never through accepting an
    unknown string.
    """

    SNAPSHOT = "snapshot"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def _require_enum(value: object, enum: type[Enum], label: str, *, not_this: type[Enum]) -> Enum:
    """Coerce ``value`` to ``enum``, refusing a member of the *other* state
    vocabulary even when its value happens to match.

    ``AssessmentState.BULLISH`` and ``ResearchState.BULLISH`` share a value and
    not a meaning; the ``str`` mix-in would let one convert into the other
    silently, hiding a type slip that a reader of the ledger could never see.
    """
    if isinstance(value, not_this):
        raise OutcomeTrackingError(
            f"{label} must be a {enum.__name__}, got {not_this.__name__}.{value.name}"
        )
    try:
        return enum(value)
    except ValueError:
        raise OutcomeTrackingError(f"unknown {label} {value!r} for {enum.__name__}") from None


def _require_reason_codes(
    codes: object, enum: type[Enum], label: str, *, not_this: type[Enum]
) -> tuple[Enum, ...]:
    if isinstance(codes, (str, bytes)) or not isinstance(codes, Sequence):
        raise OutcomeTrackingError(
            f"{label} must be a sequence of {enum.__name__}, got {type(codes).__name__}"
        )
    coerced = tuple(_require_enum(code, enum, label, not_this=not_this) for code in codes)
    if not coerced:
        raise OutcomeTrackingError(
            f"{label} must not be empty; an unexplained claim is not auditable"
        )
    return coerced


@dataclass(frozen=True)
class TrackedArtifact:
    """What one producer claimed about one bar, plus the facts of registration.

    Not constructible directly: a claim has a kind, and the kind is the
    subtype. See :class:`ObservationArtifact` and :class:`AssessmentArtifact`.

    Common fields
    -------------
    ``timestamp`` is the **open** of the bar the claim describes (a Phase 1
    invariant). ``data_cutoff`` is the open of the latest settled bar the
    producer had when it made the claim; it bounds the claim from above --
    a producer cannot classify a bar it has not seen. ``recorded_at`` is the
    registration clock, supplied by the caller, and cannot precede the cutoff
    bar's open. ``observation_bar_fingerprint`` is the content of bar
    ``timestamp`` at registration, so a later revision of that bar is
    detectable. ``source`` names the provider whose bars produced the claim.

    What the ordering checks are, and are not
    -----------------------------------------
    ``timestamp <= data_cutoff`` and ``recorded_at >= data_cutoff`` compare
    bar **open** times with a clock reading. They refuse records that
    describe an impossible sequence; they are *not* a proof that the cutoff
    bar was settled when the claim was made. Settledness is the fetch
    layer's guarantee (``include_unsettled=False``) and the registering
    caller's responsibility, and this record does not pretend to hold it.
    """

    kind: ClassVar[ArtifactKind]

    symbol: str
    interval: Interval
    basis: PriceBasis
    timestamp: datetime
    state: ResearchState | AssessmentState
    reason_codes: tuple[ReasonCode, ...] | tuple[AssessmentReasonCode, ...]
    source: str
    data_cutoff: datetime
    recorded_at: datetime
    observation_bar_fingerprint: str
    origin: ArtifactOrigin

    def __post_init__(self) -> None:
        if type(self) is TrackedArtifact:
            raise OutcomeTrackingError(
                "TrackedArtifact has no kind; construct an ObservationArtifact or an "
                "AssessmentArtifact"
            )
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

        set_(self, "timestamp", require_aware(self.timestamp, "timestamp"))
        set_(self, "data_cutoff", require_aware(self.data_cutoff, "data_cutoff"))
        set_(self, "recorded_at", require_aware(self.recorded_at, "recorded_at"))
        if self.timestamp > self.data_cutoff:
            raise OutcomeTrackingError(
                f"timestamp {self.timestamp.isoformat()} is after data_cutoff "
                f"{self.data_cutoff.isoformat()}; a producer cannot classify a bar it "
                "has not seen"
            )
        if self.recorded_at < self.data_cutoff:
            raise OutcomeTrackingError(
                f"recorded_at {self.recorded_at.isoformat()} precedes the data_cutoff bar's "
                f"open {self.data_cutoff.isoformat()}; a claim cannot be recorded before "
                "the bar it rests on opened"
            )

        set_(self, "source", require_text(self.source, "source"))
        set_(
            self,
            "observation_bar_fingerprint",
            require_key(self.observation_bar_fingerprint, "observation_bar_fingerprint"),
        )
        try:
            set_(self, "origin", ArtifactOrigin(self.origin))
        except ValueError:
            raise OutcomeTrackingError(f"unknown origin {self.origin!r}") from None

        self._validate_claim()

    def _validate_claim(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- identity ---------------------------------------------------------------

    @property
    def artifact_key(self) -> str:
        """Derived from the producer identity fields, never stored, so it
        cannot disagree with the record it names."""
        raise NotImplementedError  # pragma: no cover - overridden

    @property
    def is_evaluable(self) -> bool:
        """``INSUFFICIENT_DATA`` carries no classification to measure. Every
        other state -- including NEUTRAL and CONFLICTED -- describes a claim
        whose forward market behaviour is a fact worth recording. Each
        vocabulary is named explicitly; nothing here compares across them."""
        return self.state not in (
            ResearchState.INSUFFICIENT_DATA,
            AssessmentState.INSUFFICIENT_DATA,
        )

    @property
    def label(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def describe(self) -> str:
        codes = ",".join(code.value for code in self.reason_codes)
        return (
            f"{self.kind.value} {self.label} {self.symbol} {self.interval.value} "
            f"[{self.basis.value}] {self.timestamp.isoformat()} -> {self.state.value} "
            f"({codes}) source={self.source} cutoff={self.data_cutoff.isoformat()} "
            f"recorded={self.recorded_at.isoformat()} origin={self.origin.value}"
        )


@dataclass(frozen=True)
class ObservationArtifact(TrackedArtifact):
    """One hypothesis' :class:`~src.strategies.research.ResearchObservation`,
    as claimed. State vocabulary is :class:`ResearchState`."""

    kind: ClassVar[ArtifactKind] = ArtifactKind.OBSERVATION

    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str

    def _validate_claim(self) -> None:
        set_ = object.__setattr__
        set_(self, "state", _require_enum(self.state, ResearchState, "state",
                                          not_this=AssessmentState))
        set_(self, "reason_codes", _require_reason_codes(
            self.reason_codes, ReasonCode, "reason_codes", not_this=AssessmentReasonCode))
        set_(self, "hypothesis_id", require_text(self.hypothesis_id, "hypothesis_id"))
        set_(self, "hypothesis_version",
             require_positive_int(self.hypothesis_version, "hypothesis_version"))
        # Phase 3 and Phase 6 require a non-blank fingerprint and no more;
        # the same rule applies here so a real observation always registers.
        set_(self, "hypothesis_fingerprint",
             require_text(self.hypothesis_fingerprint, "hypothesis_fingerprint"))

    @property
    def artifact_key(self) -> str:
        return observation_artifact_key(
            symbol=self.symbol,
            interval=self.interval,
            basis=self.basis,
            timestamp=self.timestamp,
            hypothesis_id=self.hypothesis_id,
            hypothesis_version=self.hypothesis_version,
            hypothesis_fingerprint=self.hypothesis_fingerprint,
        )

    @property
    def label(self) -> str:
        return f"{self.hypothesis_id}@v{self.hypothesis_version}#{self.hypothesis_fingerprint}"

    @classmethod
    def from_observation(
        cls,
        observation: ResearchObservation,
        *,
        source: str,
        data_cutoff: datetime,
        recorded_at: datetime,
        observation_bar_fingerprint: str,
        origin: ArtifactOrigin,
    ) -> "ObservationArtifact":
        """Copy the observation's identity and claim verbatim.

        Nothing is recomputed and the observation is not touched: the
        artifact is a record of what Phase 3 said, not a second opinion.
        """
        if not isinstance(observation, ResearchObservation):
            raise OutcomeTrackingError(
                f"expected a ResearchObservation, got {type(observation).__name__}"
            )
        return cls(
            symbol=observation.symbol,
            interval=observation.interval,
            basis=observation.basis,
            timestamp=observation.timestamp,
            state=observation.state,
            reason_codes=observation.reason_codes,
            source=source,
            data_cutoff=data_cutoff,
            recorded_at=recorded_at,
            observation_bar_fingerprint=observation_bar_fingerprint,
            origin=origin,
            hypothesis_id=observation.hypothesis_id,
            hypothesis_version=observation.version,
            hypothesis_fingerprint=observation.fingerprint,
        )


@dataclass(frozen=True)
class AssessmentArtifact(TrackedArtifact):
    """One policy's :class:`~src.assessments.assessment.ResearchAssessment`,
    as claimed. State vocabulary is :class:`AssessmentState`, so CONFLICTED
    survives as itself."""

    kind: ClassVar[ArtifactKind] = ArtifactKind.ASSESSMENT

    policy_fingerprint: str

    def _validate_claim(self) -> None:
        set_ = object.__setattr__
        set_(self, "state", _require_enum(self.state, AssessmentState, "state",
                                          not_this=ResearchState))
        set_(self, "reason_codes", _require_reason_codes(
            self.reason_codes, AssessmentReasonCode, "reason_codes", not_this=ReasonCode))
        # Exactly the shape ``AssessmentPolicy.fingerprint`` produces and
        # ``ResearchAssessment`` already enforces.
        set_(self, "policy_fingerprint",
             require_spec_fingerprint(self.policy_fingerprint, "policy_fingerprint"))

    @property
    def artifact_key(self) -> str:
        return assessment_artifact_key(
            symbol=self.symbol,
            interval=self.interval,
            basis=self.basis,
            timestamp=self.timestamp,
            policy_fingerprint=self.policy_fingerprint,
        )

    @property
    def label(self) -> str:
        return f"policy#{self.policy_fingerprint}"

    @classmethod
    def from_assessment(
        cls,
        assessment: ResearchAssessment,
        *,
        source: str,
        data_cutoff: datetime,
        recorded_at: datetime,
        observation_bar_fingerprint: str,
        origin: ArtifactOrigin,
    ) -> "AssessmentArtifact":
        """Copy the assessment's identity and claim verbatim.

        ``assessment_as_of`` is not carried: it is the producer's clock
        reading, and the registration clock is ``recorded_at``. The inputs
        and counts are not carried either -- the policy fingerprint names the
        ensemble, and each input is registered as its own observation
        artifact.
        """
        if not isinstance(assessment, ResearchAssessment):
            raise OutcomeTrackingError(
                f"expected a ResearchAssessment, got {type(assessment).__name__}"
            )
        return cls(
            symbol=assessment.symbol,
            interval=assessment.interval,
            basis=assessment.basis,
            timestamp=assessment.timestamp,
            state=assessment.state,
            reason_codes=assessment.reason_codes,
            source=source,
            data_cutoff=data_cutoff,
            recorded_at=recorded_at,
            observation_bar_fingerprint=observation_bar_fingerprint,
            origin=origin,
            policy_fingerprint=assessment.policy_fingerprint,
        )


def _require_price(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OutcomeTrackingError(f"{label} must be a real number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        # A validated series cannot contain a non-positive price, and Phase 4
        # raises on a zero reference; a record carrying one was not produced
        # by the pipeline this record claims to summarise.
        raise OutcomeTrackingError(f"{label} must be a finite positive number, got {value!r}")
    return number


@dataclass(frozen=True)
class OutcomeRecord:
    """One completed forward measurement of one tracked artifact. Immutable.

    Embeds the artifact it measured (design A) rather than referencing it by
    key with a copied subset of its fields. The key is then *derived* from
    the embedded artifact and can never disagree with it; a record can never
    be orphaned from the claim it measures; and a read-only consumer (Phase
    11B) receives the complete claim with every audit field intact. The cost
    is a few hundred bytes of repetition per stored line, which is cheap at
    this project's scale and is the store's problem, not the model's.

    Measurement facts are Phase 4's, stored as produced: the reference is the
    open of the bar after the claimed one, the future is the chosen price of
    the horizon's last bar, and ``forward_return`` is
    ``future_price / reference_price - 1``. This record checks that a value
    is *consistent* with its own prices; it does not compute one.

    ``horizon_bars`` is carried beside ``spec_fingerprint`` for the same
    reason Phase 4's own record carries both: a specification cannot be
    reconstructed from its fingerprint, and a reader grouping by horizon
    should not need a lookup table.
    """

    artifact: TrackedArtifact
    spec_fingerprint: str
    horizon_bars: int
    evaluation_version: int
    evaluated_at: datetime
    consumed_bars_fingerprint: str
    reference_timestamp: datetime
    reference_price: float
    future_timestamp: datetime
    future_price: float
    forward_return: float

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        if not isinstance(self.artifact, TrackedArtifact):
            raise OutcomeTrackingError(
                f"artifact must be a TrackedArtifact, got {type(self.artifact).__name__}"
            )
        if not self.artifact.is_evaluable:
            raise OutcomeTrackingError(
                f"an artifact in state {self.artifact.state.value!r} is not evaluable "
                "(INSUFFICIENT_DATA carries no classification); it can never have an outcome"
            )

        set_(self, "spec_fingerprint",
             require_spec_fingerprint(self.spec_fingerprint, "spec_fingerprint"))
        set_(self, "horizon_bars", require_positive_int(self.horizon_bars, "horizon_bars"))
        if (
            isinstance(self.evaluation_version, bool)
            or not isinstance(self.evaluation_version, int)
            or self.evaluation_version not in SUPPORTED_EVALUATION_VERSIONS
        ):
            raise OutcomeTrackingError(
                f"evaluation_version {self.evaluation_version!r} is not supported by this "
                f"build (supported: {sorted(SUPPORTED_EVALUATION_VERSIONS)})"
            )
        set_(self, "consumed_bars_fingerprint",
             require_key(self.consumed_bars_fingerprint, "consumed_bars_fingerprint"))

        set_(self, "evaluated_at", require_aware(self.evaluated_at, "evaluated_at"))
        set_(self, "reference_timestamp",
             require_aware(self.reference_timestamp, "reference_timestamp"))
        set_(self, "future_timestamp", require_aware(self.future_timestamp, "future_timestamp"))

        artifact = self.artifact
        if self.evaluated_at < artifact.recorded_at:
            raise OutcomeTrackingError(
                f"evaluated_at {self.evaluated_at.isoformat()} precedes recorded_at "
                f"{artifact.recorded_at.isoformat()}; a claim cannot be measured before it "
                "was recorded"
            )
        # Phase 4 NEXT_BAR_OPEN: the reference is bar i+1, strictly after the
        # claimed bar. Nothing here assumes how much later -- bars are counted,
        # not dated, and gaps are legitimate.
        if self.reference_timestamp <= artifact.timestamp:
            raise OutcomeTrackingError(
                f"reference_timestamp {self.reference_timestamp.isoformat()} does not follow "
                f"the claimed bar {artifact.timestamp.isoformat()}; the reference is the next "
                "bar's open, never the observation bar"
            )
        if self.future_timestamp < self.reference_timestamp:
            raise OutcomeTrackingError(
                f"future_timestamp {self.future_timestamp.isoformat()} precedes "
                f"reference_timestamp {self.reference_timestamp.isoformat()}"
            )
        # Phase 4 counts the reference bar as bar one of the horizon
        # (``future_index = reference_index + horizon_bars - 1``), and a series
        # has strictly increasing timestamps. So a one-bar horizon ends on the
        # reference bar itself, and a longer one ends strictly after it. Bar
        # *count*, not duration: nothing here assumes how far apart bars are.
        same_bar = self.future_timestamp == self.reference_timestamp
        if self.horizon_bars == 1 and not same_bar:
            raise OutcomeTrackingError(
                f"horizon_bars=1 ends on the reference bar, but future_timestamp "
                f"{self.future_timestamp.isoformat()} differs from reference_timestamp "
                f"{self.reference_timestamp.isoformat()}"
            )
        if self.horizon_bars > 1 and same_bar:
            raise OutcomeTrackingError(
                f"horizon_bars={self.horizon_bars} ends after the reference bar, but "
                f"future_timestamp equals reference_timestamp "
                f"{self.reference_timestamp.isoformat()}"
            )
        # A settled bar cannot be read before it opens, so the measurement
        # clock must postdate the last bar it consumed. This is a *necessary*
        # condition that refuses an impossible record; it is not a proof the
        # future bar was settled -- the record does not know bar durations.
        # Settledness is the evaluator's guarantee (it reads settled series).
        if self.evaluated_at <= self.future_timestamp:
            raise OutcomeTrackingError(
                f"evaluated_at {self.evaluated_at.isoformat()} is not after the future bar's "
                f"open {self.future_timestamp.isoformat()}; the bar could not have been "
                "settled when it was read"
            )
        # The prospective invariant: the bar that closes the measurement did
        # not exist in the data when the claim was recorded.
        if self.future_timestamp <= artifact.data_cutoff:
            raise OutcomeTrackingError(
                f"future_timestamp {self.future_timestamp.isoformat()} is not after the "
                f"artifact's data_cutoff {artifact.data_cutoff.isoformat()}; the outcome "
                "would have been knowable when the claim was recorded"
            )

        set_(self, "reference_price", _require_price(self.reference_price, "reference_price"))
        set_(self, "future_price", _require_price(self.future_price, "future_price"))

        if isinstance(self.forward_return, bool) or not isinstance(
            self.forward_return, (int, float)
        ):
            raise OutcomeTrackingError(
                f"forward_return must be a real number, got {type(self.forward_return).__name__}"
            )
        forward_return = float(self.forward_return)
        if not math.isfinite(forward_return):
            raise OutcomeTrackingError(
                f"forward_return must be a finite number, got {self.forward_return!r}"
            )
        # Exact binary equality, deliberately. Phase 4 computes this same
        # expression on these same floats, and IEEE division is correctly
        # rounded everywhere, so a genuine record always agrees. A store must
        # round-trip floats exactly (JSON's shortest-repr form does; a
        # rounded or formatted decimal would not) -- that is the contract
        # this check places on persistence, and it is the right one.
        expected = self.future_price / self.reference_price - 1.0
        if forward_return != expected:
            raise OutcomeTrackingError(
                f"forward_return {forward_return!r} does not agree with its own prices "
                f"({self.future_price!r} / {self.reference_price!r} - 1 = {expected!r}); "
                "the record contradicts itself"
            )
        set_(self, "forward_return", forward_return)

    # -- identity and audit, read through the artifact -----------------------------

    @property
    def artifact_key(self) -> str:
        return self.artifact.artifact_key

    @property
    def outcome_key(self) -> str:
        return outcome_key(
            artifact_key=self.artifact.artifact_key,
            spec_fingerprint=self.spec_fingerprint,
            evaluation_version=self.evaluation_version,
        )

    @property
    def data_cutoff(self) -> datetime:
        return self.artifact.data_cutoff

    @property
    def recorded_at(self) -> datetime:
        return self.artifact.recorded_at

    @property
    def observation_bar_fingerprint(self) -> str:
        return self.artifact.observation_bar_fingerprint

    def describe(self) -> str:
        return (
            f"{self.artifact.kind.value} {self.artifact.label} {self.artifact.symbol} "
            f"{self.artifact.interval.value} [{self.artifact.basis.value}] "
            f"{self.artifact.timestamp.isoformat()} {self.artifact.state.value} "
            f"h={self.horizon_bars} spec#{self.spec_fingerprint} v{self.evaluation_version} "
            f"-> {self.forward_return:+.6f} "
            f"({self.reference_timestamp.isoformat()} {self.reference_price!r} -> "
            f"{self.future_timestamp.isoformat()} {self.future_price!r}) "
            f"evaluated={self.evaluated_at.isoformat()}"
        )


__all__ = [
    "EVALUATION_VERSION",
    "SUPPORTED_EVALUATION_VERSIONS",
    "ArtifactKind",
    "ArtifactOrigin",
    "TrackedArtifact",
    "ObservationArtifact",
    "AssessmentArtifact",
    "OutcomeRecord",
    "OutcomeTrackingError",
]
