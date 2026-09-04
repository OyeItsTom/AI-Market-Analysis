"""Research vocabulary: states, reason codes and the observation record.

Terminology, deliberately
-------------------------
This layer classifies *evidence*.  It does not recommend, order, or predict.

``BULLISH`` means "this deterministic hypothesis classifies the supplied
evidence as bullish-leaning".  It does **not** mean "buy", "this will rise", or
"this is a profitable signal".  Phase 3 contains no measurement of what
happened next -- that is Phase 4's question, under a separately defined
evaluation protocol.

The vocabulary is deliberately not ``BUY``/``SELL``.  Naming the fundamental
abstraction after an order type invites every later layer to treat a
classification as an instruction, and makes it awkward to express "the
evidence is genuinely uninformative here".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from src.data.models import Interval
from src.data.series import PriceBasis

from .spec import HypothesisSpec


class ResearchState(str, Enum):
    """How a hypothesis classifies the evidence at one point in time.

    ``INSUFFICIENT_DATA`` is reserved for *legitimately* unavailable evidence:
    an indicator still in warm-up. It is never used to absorb a structural
    problem -- a symbol mismatch, an interval mismatch, a wrong price basis or
    missing required evidence all raise instead. Hiding a bug behind a
    plausible-looking state is how a corrupted study survives review.
    """

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    INSUFFICIENT_DATA = "insufficient_data"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_directional(self) -> bool:
        return self in (ResearchState.BULLISH, ResearchState.BEARISH)


class ReasonCode(str, Enum):
    """Deterministic, machine-testable explanations.

    A closed vocabulary rather than free text: reason codes are asserted on in
    tests, counted in later analysis, and compared across versions. Prose --
    and certainly anything model-generated -- cannot serve any of those uses.
    """

    # Warm-up / availability
    WARMUP_INCOMPLETE = "warmup_incomplete"

    # Trend
    FAST_ABOVE_SLOW = "fast_above_slow"
    FAST_BELOW_SLOW = "fast_below_slow"
    FAST_EQUALS_SLOW = "fast_equals_slow"
    TREND_MARGIN_BELOW_THRESHOLD = "trend_margin_below_threshold"

    # Momentum
    MOMENTUM_ELEVATED = "momentum_elevated"
    MOMENTUM_DEPRESSED = "momentum_depressed"
    MOMENTUM_MIDRANGE = "momentum_midrange"

    # Transitions (require lookback >= 1)
    CROSSED_ABOVE = "crossed_above"
    CROSSED_BELOW = "crossed_below"
    RELATIONSHIP_UNCHANGED = "relationship_unchanged"

    # Combination outcomes
    MOMENTUM_CONFIRMS_TREND = "momentum_confirms_trend"
    MOMENTUM_CONTRADICTS_TREND = "momentum_contradicts_trend"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ResearchObservation:
    """One hypothesis' classification of the evidence at one bar. Immutable.

    Carries everything needed to audit the classification later without
    re-running anything: which hypothesis and version produced it, its
    fingerprint (so a re-parameterised hypothesis cannot be confused with the
    original), what the evidence actually was, and when the classification
    could logically have been made.

    Timing
    ------
    ``timestamp`` is the **bar open time** of the bar the evidence describes
    (a Phase 1 invariant). ``evaluable_from`` is the earliest instant the
    classification could logically be made -- ``timestamp + interval``, because
    the evidence depends on that bar's completed OHLCV.

    ``evaluable_from`` is a **bound, not a measurement**. It inherits Phase 2's
    limitation exactly: no exchange calendar, no provider-latency model. It is
    later than the true session close for session-based intervals, and earlier
    than real data arrival for a delayed feed. It must not be read as "the
    classification was actionable at this instant".
    """

    hypothesis_id: str
    version: int
    fingerprint: str
    symbol: str
    interval: Interval
    basis: PriceBasis
    timestamp: datetime
    state: ResearchState
    evidence: Mapping[str, float | None]
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "state", ResearchState(self.state))
        set_(self, "reason_codes", tuple(ReasonCode(code) for code in self.reason_codes))
        # A read-only view: an observation is a record, not a scratchpad.
        set_(self, "evidence", MappingProxyType(dict(self.evidence)))

        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("observation timestamp must be timezone-aware")
        if not self.reason_codes:
            raise ValueError(
                f"{self.hypothesis_id}: every observation must carry at least one reason "
                "code; an unexplained classification is not auditable"
            )

    @property
    def evaluable_from(self) -> datetime:
        """Earliest instant this classification could logically be made.

        See the class docstring: a bound, not provider-arrival time.
        """
        return self.timestamp + self.interval.max_duration

    @property
    def label(self) -> str:
        return f"{self.hypothesis_id}@v{self.version}#{self.fingerprint}"

    def describe(self) -> str:
        codes = ",".join(code.value for code in self.reason_codes)
        return (
            f"{self.label} {self.symbol} {self.interval.value} [{self.basis.value}] "
            f"{self.timestamp.isoformat()} -> {self.state.value} ({codes})"
        )

    @classmethod
    def build(
        cls,
        spec: HypothesisSpec,
        *,
        symbol: str,
        interval: Interval,
        basis: PriceBasis,
        timestamp: datetime,
        state: ResearchState,
        evidence: Mapping[str, float | None],
        reason_codes: Sequence[ReasonCode],
    ) -> "ResearchObservation":
        """Build an observation, taking identity from ``spec``."""
        return cls(
            hypothesis_id=spec.hypothesis_id,
            version=spec.version,
            fingerprint=spec.fingerprint,
            symbol=symbol,
            interval=interval,
            basis=basis,
            timestamp=timestamp,
            state=state,
            evidence=evidence,
            reason_codes=tuple(reason_codes),
        )


__all__ = ["ResearchState", "ReasonCode", "ResearchObservation"]
