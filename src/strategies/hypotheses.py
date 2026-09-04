"""Example research hypotheses.

These exist to prove the framework works. They are **not** proposed trading
rules, they were not selected or tuned by looking at outcomes, and Phase 3
measures nothing about what happened after any classification.

Parameters are conventional, test-friendly values (20/50 moving averages,
14-period RSI) chosen because they are recognisable and easy to reason about
in tests. **No parameter search was performed**, and none should be until a
controlled research protocol exists -- picking parameters by historical
outcome is how a study fits its own noise.

On volatility regimes
---------------------
A third example classifying volatility regime was considered and deliberately
not built. :class:`~src.strategies.research.ResearchState` is a directional
vocabulary (bullish / bearish / neutral); "high volatility" is not a direction,
and forcing it into that vocabulary would either overload NEUTRAL to mean two
different things or invent a bullish/bearish reading that volatility does not
carry. A regime classification needs its own state vocabulary, which is a
design decision worth making deliberately rather than as a side effect of
wanting a third example.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .base import ResearchHypothesis
from .research import ReasonCode, ResearchState
from .spec import FeatureSpec


class TrendAlignment(ResearchHypothesis):
    """Classifies the relationship between a fast and a slow moving average.

    Deliberately a *level* comparison, not a crossover: a crossover needs the
    previous bar, and the framework hands a hypothesis only the current bar's
    evidence. That restriction is what makes look-ahead structurally impossible
    (see :mod:`.base`); supporting history is deferred until something needs it.

    Classification, with ``margin`` as a dead-band expressed as a fraction of
    the slow average:

    * fast exceeds slow by more than the margin -> ``BULLISH``
    * fast is below slow by more than the margin -> ``BEARISH``
    * otherwise -> ``NEUTRAL``

    The dead-band exists so that two averages sitting on top of each other are
    reported as what they are -- no separation -- rather than flipping between
    directional states on floating-point noise.
    """

    hypothesis_id = "trend_alignment"
    version = 1
    display_name = "Fast/slow moving-average alignment"

    FAST = FeatureSpec("sma", {"period": 20, "field": "close"})
    SLOW = FeatureSpec("sma", {"period": 50, "field": "close"})
    required_features = (FAST, SLOW)

    #: Fractional dead-band around equality. Not tuned; a small round number.
    #: Declared, so it reaches the fingerprint: a different dead-band is a
    #: different research definition.
    parameters = {"margin": 0.001}

    def _classify(
        self, values: Mapping[str, float]
    ) -> tuple[ResearchState, Sequence[ReasonCode]]:
        margin = self.parameter("margin")
        fast = values[self.FAST.key]
        slow = values[self.SLOW.key]

        if slow == 0:
            # Cannot form a relative margin against zero. Validated series have
            # positive prices, so this is unreachable for real data; it is
            # handled rather than left to produce a ZeroDivisionError.
            return ResearchState.NEUTRAL, (ReasonCode.FAST_EQUALS_SLOW,)

        separation = (fast - slow) / abs(slow)

        if separation > margin:
            return ResearchState.BULLISH, (ReasonCode.FAST_ABOVE_SLOW,)
        if separation < -margin:
            return ResearchState.BEARISH, (ReasonCode.FAST_BELOW_SLOW,)
        if fast == slow:
            return ResearchState.NEUTRAL, (ReasonCode.FAST_EQUALS_SLOW,)
        return ResearchState.NEUTRAL, (
            ReasonCode.TREND_MARGIN_BELOW_THRESHOLD,
        )


class MomentumInTrendContext(ResearchHypothesis):
    """Classifies momentum *read against* prevailing trend.

    Deliberately not "RSI below 30 means buy". That rule treats one number as a
    recommendation, ignores context, and is the kind of thing this framework
    exists to avoid encoding as a primitive.

    Instead the hypothesis asks a research question with two pieces of
    evidence: does momentum agree with the trend, or contradict it?

    * trend up and momentum elevated -> ``BULLISH`` (momentum confirms trend)
    * trend down and momentum depressed -> ``BEARISH`` (momentum confirms trend)
    * trend and momentum disagree -> ``NEUTRAL``, flagged as contradicting;
      the evidence is genuinely mixed and saying so is more honest than
      picking a side
    * momentum mid-range -> ``NEUTRAL``

    Note ``NEUTRAL`` here can mean "conflicting" or "unremarkable"; the reason
    codes distinguish them, which is exactly why reason codes exist.
    """

    hypothesis_id = "momentum_in_trend_context"
    version = 1
    display_name = "Momentum read against prevailing trend"

    MOMENTUM = FeatureSpec("rsi", {"period": 14, "field": "close"})
    FAST = FeatureSpec("sma", {"period": 20, "field": "close"})
    SLOW = FeatureSpec("sma", {"period": 50, "field": "close"})
    required_features = (MOMENTUM, FAST, SLOW)

    #: Conventional RSI bands. Not tuned. Declared so they reach the
    #: fingerprint -- moving a band changes how the hypothesis classifies.
    parameters = {"upper_band": 55.0, "lower_band": 45.0}

    def _classify(
        self, values: Mapping[str, float]
    ) -> tuple[ResearchState, Sequence[ReasonCode]]:
        upper_band = self.parameter("upper_band")
        lower_band = self.parameter("lower_band")
        momentum = values[self.MOMENTUM.key]
        fast = values[self.FAST.key]
        slow = values[self.SLOW.key]

        trend_up = fast > slow
        trend_down = fast < slow

        if momentum > upper_band:
            momentum_code = ReasonCode.MOMENTUM_ELEVATED
        elif momentum < lower_band:
            momentum_code = ReasonCode.MOMENTUM_DEPRESSED
        else:
            momentum_code = ReasonCode.MOMENTUM_MIDRANGE

        if momentum_code is ReasonCode.MOMENTUM_MIDRANGE:
            return ResearchState.NEUTRAL, (momentum_code,)

        if trend_up and momentum_code is ReasonCode.MOMENTUM_ELEVATED:
            return ResearchState.BULLISH, (
                ReasonCode.FAST_ABOVE_SLOW,
                momentum_code,
                ReasonCode.MOMENTUM_CONFIRMS_TREND,
            )
        if trend_down and momentum_code is ReasonCode.MOMENTUM_DEPRESSED:
            return ResearchState.BEARISH, (
                ReasonCode.FAST_BELOW_SLOW,
                momentum_code,
                ReasonCode.MOMENTUM_CONFIRMS_TREND,
            )

        trend_code = (
            ReasonCode.FAST_ABOVE_SLOW
            if trend_up
            else ReasonCode.FAST_BELOW_SLOW
            if trend_down
            else ReasonCode.FAST_EQUALS_SLOW
        )
        return ResearchState.NEUTRAL, (
            trend_code,
            momentum_code,
            ReasonCode.MOMENTUM_CONTRADICTS_TREND,
        )


class TrendCrossover(ResearchHypothesis):
    """Classifies a *transition* in the fast/slow moving-average relationship.

    Exists to prove the causal-window abstraction: unlike the two
    point-in-time hypotheses above, this one genuinely needs the previous bar,
    which it declares as ``lookback = 1`` and reads through
    ``window.past(spec, 1)``.

    * fast was at-or-below slow, and is now above -> ``BULLISH``, crossed above
    * fast was at-or-above slow, and is now below -> ``BEARISH``, crossed below
    * no change in the relationship -> ``NEUTRAL``

    A crossover classifier is an architectural fixture. It is **not** a
    profitability claim, not a trading recommendation, and its parameters were
    not selected by looking at outcomes.

    Note this is a strictly causal transition: it compares bar ``T`` with bar
    ``T-1``, never with ``T+1``. At the first bar of a dataset there is no
    previous bar, so the framework reports ``INSUFFICIENT_DATA`` -- a genuine
    shortage of history, not a fault.
    """

    hypothesis_id = "trend_crossover"
    version = 1
    display_name = "Fast/slow moving-average crossover"

    FAST = FeatureSpec("sma", {"period": 20, "field": "close"})
    SLOW = FeatureSpec("sma", {"period": 50, "field": "close"})
    required_features = (FAST, SLOW)
    lookback = 1

    def _classify(self, values):
        now_fast = values.past(self.FAST, 0)
        now_slow = values.past(self.SLOW, 0)
        was_fast = values.past(self.FAST, 1)
        was_slow = values.past(self.SLOW, 1)

        was_above = was_fast > was_slow
        is_above = now_fast > now_slow

        if is_above and not was_above:
            return ResearchState.BULLISH, (
                ReasonCode.CROSSED_ABOVE,
                ReasonCode.FAST_ABOVE_SLOW,
            )
        if was_above and not is_above:
            return ResearchState.BEARISH, (
                ReasonCode.CROSSED_BELOW,
                ReasonCode.FAST_BELOW_SLOW,
            )
        return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)


__all__ = ["TrendAlignment", "MomentumInTrendContext", "TrendCrossover"]
