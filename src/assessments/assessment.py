"""The assessment record: states, evidence accounting, reasons, and the result.

A :class:`ResearchAssessment` is what one :class:`~src.assessments.policy.AssessmentPolicy`
concluded from an aligned set of research observations.  It is a *classification
of combined evidence* and nothing else.

What these states are not
-------------------------
``BULLISH`` means "the ensemble's sufficient evidence points bullish under
``directional_presence_v1``".  It does **not** mean buy, hold, a prediction, a
probability, a confidence, a strength, or independent confirmation.  There is
deliberately no score and no confidence field: a number derived from a handful
of hypotheses -- two of which, in this repository, are trend-family and share
inputs -- would manufacture precision the research cannot support.  The
:class:`AssessmentCounts` are descriptive accounting, not a measure of
conviction: ``bullish=3`` is three classifications, not three independent
confirmations and not three times the confidence.

``CONFLICTED`` is not ``NEUTRAL``
---------------------------------
``NEUTRAL`` means the sufficient evidence points nowhere.  ``CONFLICTED`` means
sufficient evidence *disagrees* -- some hypothesis said bullish while another
said bearish.  Collapsing the two would erase exactly the situation a human most
needs to look at, so they are separate states.

Why a separate state enum
-------------------------
:class:`AssessmentState` is deliberately not :class:`~src.strategies.research.ResearchState`.
Phase 3 has no ``CONFLICTED`` -- ``MomentumInTrendContext`` is forced to report
an internal contradiction as ``NEUTRAL`` for want of the word -- and adding one
there would change Phase 3's meaning.  A separate enum also means a later
evaluator can tell a single hypothesis' classification from a combined one by
type rather than by convention, and ``CONFLICTED`` cannot leak backwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Sequence

from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ResearchState


class AssessmentError(ValueError):
    """Raised when assessment input or an assessment record is malformed.

    Structural problems raise; they never become a state. An assessment that
    reported a symbol mismatch as ``INSUFFICIENT_DATA`` would look like a
    legitimate research outcome, which is how a corrupted study survives
    review. This mirrors Phase 3's rule for ``INSUFFICIENT_DATA``.
    """


class AssessmentState(str, Enum):
    """How a policy classifies the combined evidence at one market point."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"
    INSUFFICIENT_DATA = "insufficient_data"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_directional(self) -> bool:
        return self in (AssessmentState.BULLISH, AssessmentState.BEARISH)


class AssessmentReasonCode(str, Enum):
    """Deterministic, machine-testable explanations of one assessment.

    Every member is reachable under the locked ``directional_presence_v1``
    semantics, and every member states a *fact about the counts* rather than a
    judgement about them. There is deliberately no ``MAJORITY_BULLISH``: under
    this rule ``BULLISH + NEUTRAL`` is a directional finding among abstentions,
    not a majority, and a code claiming otherwise would be false.
    """

    #: "Unanimous" is scoped to the **sufficient** inputs -- those that actually
    #: classified. ``BULLISH + BULLISH + INSUFFICIENT_DATA`` is
    #: ``UNANIMOUS_BULLISH``, because the hypothesis that did not classify cast
    #: no vote to disagree with. The exclusion is never hidden: that case also
    #: carries ``INSUFFICIENT_INPUTS_EXCLUDED``, and ``counts.insufficient``
    #: records it. Read the two codes together.
    UNANIMOUS_BULLISH = "unanimous_bullish"
    UNANIMOUS_BEARISH = "unanimous_bearish"
    UNANIMOUS_NEUTRAL = "unanimous_neutral"
    DIRECTIONAL_BULLISH_WITH_NEUTRAL = "directional_bullish_with_neutral"
    DIRECTIONAL_BEARISH_WITH_NEUTRAL = "directional_bearish_with_neutral"
    CONFLICTING_DIRECTIONAL_EVIDENCE = "conflicting_directional_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INSUFFICIENT_INPUTS_EXCLUDED = "insufficient_inputs_excluded"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Canonical reason-code order. Fixed so a dashboard renders reasons in one
#: sequence and a test can pin it. Ordering is enforced in
#: :meth:`ResearchAssessment.__post_init__`, not only where reasons are
#: derived, so it holds for a directly constructed record too.
_REASON_ORDER: tuple[AssessmentReasonCode, ...] = (
    AssessmentReasonCode.UNANIMOUS_BULLISH,
    AssessmentReasonCode.UNANIMOUS_BEARISH,
    AssessmentReasonCode.UNANIMOUS_NEUTRAL,
    AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL,
    AssessmentReasonCode.DIRECTIONAL_BEARISH_WITH_NEUTRAL,
    AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,
    AssessmentReasonCode.INSUFFICIENT_EVIDENCE,
    AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
)


def _require_tally(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise AssessmentError(f"{label} must be an int, got bool")
    if not isinstance(value, int):
        raise AssessmentError(f"{label} must be an int, got {type(value).__name__}")
    if value < 0:
        raise AssessmentError(f"{label} must be >= 0, got {value}")
    return value


#: Length and alphabet of an :class:`~src.assessments.policy.AssessmentPolicy`
#: fingerprint: SHA-256 rendered as the first 16 lowercase hex characters.
_FINGERPRINT_LENGTH = 16
_HEX_DIGITS = frozenset("0123456789abcdef")


def _require_policy_fingerprint(value: object) -> str:
    """Exactly the shape :attr:`AssessmentPolicy.fingerprint` produces.

    Requiring a non-empty string is not enough. An assessment carrying
    ``"hello world"`` or an uppercase digest names a policy that no
    ``AssessmentPolicy`` in this system could ever have produced, so it can
    never be matched back to one -- an assessment that is not auditable while
    looking as though it is. The record refuses states its own producer cannot
    reach; this is one of them.
    """
    if not isinstance(value, str):
        raise AssessmentError(
            f"policy_fingerprint must be a str, got {type(value).__name__}"
        )
    if len(value) != _FINGERPRINT_LENGTH or not set(value) <= _HEX_DIGITS:
        raise AssessmentError(
            f"policy_fingerprint must be {_FINGERPRINT_LENGTH} lowercase hex "
            f"characters as produced by AssessmentPolicy.fingerprint, got {value!r}; "
            "an assessment that names a policy no policy could produce is not "
            "auditable"
        )
    return value


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise AssessmentError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise AssessmentError(f"{label} must be timezone-aware; naive timestamps are ambiguous")
    return value


@dataclass(frozen=True)
class AssessmentInput:
    """One contributing hypothesis: who it was, and what it said.

    Identity plus state, and nothing else. The raw evidence mapping stays on
    the :class:`~src.strategies.research.ResearchObservation` the caller
    already holds; copying a subset here would create a second copy that can
    drift from the first. A consumer wanting reason codes or feature values
    joins on the identity triple.
    """

    hypothesis_id: str
    version: int
    fingerprint: str
    state: ResearchState

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id.strip():
            raise AssessmentError("hypothesis_id must be a non-empty, non-blank str")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise AssessmentError("fingerprint must be a non-empty, non-blank str")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise AssessmentError(
                f"version must be an int, got {type(self.version).__name__}"
            )
        if self.version < 1:
            raise AssessmentError(f"version must be >= 1, got {self.version}")
        try:
            set_(self, "state", ResearchState(self.state))
        except ValueError:
            raise AssessmentError(f"unknown research state {self.state!r}") from None

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.hypothesis_id, self.version, self.fingerprint)

    @property
    def label(self) -> str:
        return f"{self.hypothesis_id}@v{self.version}#{self.fingerprint}"


@dataclass(frozen=True)
class AssessmentCounts:
    """Integer evidence accounting. Four primitives; the rest is derived.

    ``sufficient`` and ``total`` are computed rather than stored: a stored
    total is a conservation invariant waiting to disagree with the numbers it
    summarises.

    Integers, deliberately -- not ``float`` and not ``Decimal``. Every quantity
    here is a count of classifications. Phase 5's lesson was to choose the type
    that matches the quantity, not to reach for ``Decimal`` by habit. Anyone
    wanting a fraction can form one from these and will see the denominator,
    which ``0.67`` would hide.
    """

    bullish: int
    bearish: int
    neutral: int
    insufficient: int

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        for field in ("bullish", "bearish", "neutral", "insufficient"):
            set_(self, field, _require_tally(getattr(self, field), field))

    @property
    def sufficient(self) -> int:
        """Observations that classified: bullish, bearish **or neutral**.

        ``NEUTRAL`` is sufficient but not directional -- the hypothesis
        classified, it just did not point anywhere. Conflating "classified as
        neutral" with "could not classify" would make a legitimate all-neutral
        ensemble unreachable, which is why the policy minimum counts these and
        not :attr:`directional`.
        """
        return self.bullish + self.bearish + self.neutral

    @property
    def directional(self) -> int:
        """Observations that classified *and* pointed somewhere.

        Reported for context. It is deliberately **not** what the policy
        minimum is measured against; see :attr:`sufficient`.
        """
        return self.bullish + self.bearish

    @property
    def total(self) -> int:
        return self.sufficient + self.insufficient

    def describe(self) -> str:
        return (
            f"bullish={self.bullish} bearish={self.bearish} neutral={self.neutral} "
            f"insufficient={self.insufficient} (sufficient={self.sufficient} "
            f"total={self.total})"
        )


@dataclass(frozen=True)
class ResearchAssessment:
    """One policy's classification of aligned research evidence. Immutable.

    Carries what is needed to audit the result without re-running anything:
    which policy produced it, which market point it describes, when the
    classification could logically have been made, what each hypothesis said,
    the evidence tally, and closed reason codes.

    Defends its own intrinsic invariants (see :meth:`__post_init__`) rather
    than trusting its producer, because a public immutable record that can be
    constructed directly must not be constructible into a state it could never
    legitimately reach.

    One invariant is **not** intrinsic and remains a producer guarantee: that
    ``INSUFFICIENT_DATA`` reflects ``sufficient < policy.minimum_sufficient_observations``.
    The record stores the policy *fingerprint*, not the minimum, so it cannot
    check that alone. Duplicating policy fields here to close that one gap
    would create a second source of truth for them, which is the worse trade.
    """

    policy_fingerprint: str
    symbol: str
    interval: Interval
    basis: PriceBasis
    timestamp: datetime
    assessment_as_of: datetime
    state: AssessmentState
    inputs: tuple[AssessmentInput, ...]
    counts: AssessmentCounts
    reason_codes: tuple[AssessmentReasonCode, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        set_(self, "policy_fingerprint", _require_policy_fingerprint(self.policy_fingerprint))
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise AssessmentError("symbol must be a non-empty, non-blank str")

        try:
            set_(self, "interval", Interval.parse(self.interval))
        except ValueError as exc:
            raise AssessmentError(str(exc)) from None
        try:
            set_(self, "basis", PriceBasis(self.basis))
        except ValueError:
            raise AssessmentError(f"unknown price basis {self.basis!r}") from None
        try:
            set_(self, "state", AssessmentState(self.state))
        except ValueError:
            raise AssessmentError(f"unknown assessment state {self.state!r}") from None

        set_(self, "timestamp", _require_aware(self.timestamp, "timestamp"))
        set_(self, "assessment_as_of", _require_aware(self.assessment_as_of, "assessment_as_of"))
        if self.assessment_as_of < self.timestamp:
            raise AssessmentError(
                f"assessment_as_of {self.assessment_as_of.isoformat()} precedes the bar "
                f"timestamp {self.timestamp.isoformat()}; a classification cannot exist "
                "before the bar it describes opened"
            )

        # -- inputs: defensive copy, canonical order, unique identities --------
        if isinstance(self.inputs, (str, bytes)) or not isinstance(self.inputs, Sequence):
            raise AssessmentError(
                f"inputs must be a sequence of AssessmentInput, got "
                f"{type(self.inputs).__name__}"
            )
        supplied = tuple(self.inputs)
        for entry in supplied:
            if not isinstance(entry, AssessmentInput):
                raise AssessmentError(
                    f"every input must be an AssessmentInput, got {type(entry).__name__}"
                )
        if not supplied:
            raise AssessmentError(
                "inputs must not be empty; an assessment with no contributing "
                "hypothesis has nothing to audit"
            )
        seen: set[tuple[str, int, str]] = set()
        for entry in supplied:
            if entry.sort_key in seen:
                raise AssessmentError(
                    f"duplicate hypothesis identity among inputs: {entry.label}"
                )
            seen.add(entry.sort_key)
        set_(self, "inputs", tuple(sorted(supplied, key=lambda item: item.sort_key)))

        if not isinstance(self.counts, AssessmentCounts):
            raise AssessmentError(
                f"counts must be an AssessmentCounts, got {type(self.counts).__name__}"
            )

        # -- counts must be the tally of inputs, not an independent claim ------
        tally = {state: 0 for state in ResearchState}
        for entry in self.inputs:
            tally[entry.state] += 1
        expected = AssessmentCounts(
            bullish=tally[ResearchState.BULLISH],
            bearish=tally[ResearchState.BEARISH],
            neutral=tally[ResearchState.NEUTRAL],
            insufficient=tally[ResearchState.INSUFFICIENT_DATA],
        )
        if self.counts != expected:
            raise AssessmentError(
                f"counts do not tally the inputs: counts say {self.counts.describe()} "
                f"but the inputs are {expected.describe()}"
            )
        if self.counts.total != len(self.inputs):
            raise AssessmentError(
                f"counts total {self.counts.total} != {len(self.inputs)} inputs"
            )

        # -- reason codes: closed, non-empty, deduplicated, canonical ---------
        if isinstance(self.reason_codes, (str, bytes)) or not isinstance(
            self.reason_codes, Sequence
        ):
            raise AssessmentError(
                f"reason_codes must be a sequence, got {type(self.reason_codes).__name__}"
            )
        try:
            present = {AssessmentReasonCode(code) for code in self.reason_codes}
        except ValueError as exc:
            raise AssessmentError(str(exc)) from None
        if not present:
            raise AssessmentError(
                "every assessment must carry at least one reason code; an unexplained "
                "classification is not auditable"
            )
        set_(self, "reason_codes", tuple(code for code in _REASON_ORDER if code in present))

        self._require_state_consistency()

    def _require_state_consistency(self) -> None:
        """Intrinsic state/count agreement -- what the record can prove alone.

        ``INSUFFICIENT_DATA`` is intentionally unchecked here: whether it was
        correct depends on the policy minimum, which this record does not hold.
        See the class docstring.
        """
        bullish, bearish, neutral = (
            self.counts.bullish,
            self.counts.bearish,
            self.counts.neutral,
        )
        state = self.state

        if state is AssessmentState.CONFLICTED and not (bullish > 0 and bearish > 0):
            raise AssessmentError(
                f"CONFLICTED requires both bullish and bearish evidence, got "
                f"{self.counts.describe()}"
            )
        if state is AssessmentState.BULLISH and not (bullish > 0 and bearish == 0):
            raise AssessmentError(
                f"BULLISH requires bullish evidence and no bearish evidence, got "
                f"{self.counts.describe()}"
            )
        if state is AssessmentState.BEARISH and not (bearish > 0 and bullish == 0):
            raise AssessmentError(
                f"BEARISH requires bearish evidence and no bullish evidence, got "
                f"{self.counts.describe()}"
            )
        if state is AssessmentState.NEUTRAL and not (
            bullish == 0 and bearish == 0 and neutral > 0
        ):
            raise AssessmentError(
                f"NEUTRAL requires neutral evidence and no directional evidence, got "
                f"{self.counts.describe()}"
            )

    @property
    def label(self) -> str:
        return f"{self.symbol} {self.interval.value} [{self.basis.value}] -> {self.state.value}"

    def describe(self) -> str:
        codes = ",".join(code.value for code in self.reason_codes)
        return (
            f"{self.label} {self.timestamp.isoformat()} "
            f"as_of={self.assessment_as_of.isoformat()} "
            f"({self.counts.describe()}) [{codes}] policy#{self.policy_fingerprint}"
        )


__all__ = [
    "AssessmentState",
    "AssessmentReasonCode",
    "AssessmentInput",
    "AssessmentCounts",
    "ResearchAssessment",
    "AssessmentError",
]
