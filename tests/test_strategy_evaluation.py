"""Evidence alignment, evaluation, error handling and observation semantics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.data.models import Interval
from src.data.series import PriceBasis
from src.features import rsi, sma
from src.strategies import (
    EvidenceError,
    EvidenceSet,
    FeatureSpec,
    HypothesisError,
    MomentumInTrendContext,
    ReasonCode,
    ResearchHypothesis,
    ResearchObservation,
    ResearchState,
    TrendAlignment,
    build_evidence,
)
from tests.conftest import UTC, make_series

FAST = FeatureSpec("sma", {"period": 3, "field": "close"})
SLOW = FeatureSpec("sma", {"period": 5, "field": "close"})


def rising(n=30, start=10.0, step=0.5):
    return make_series([start + step * i for i in range(n)])


def falling(n=30, start=40.0, step=0.5):
    return make_series([start - step * i for i in range(n)])


class Demo(ResearchHypothesis):
    """Minimal hypothesis over two SMAs, for framework tests."""

    hypothesis_id = "demo_trend"
    version = 1
    display_name = "Demo trend"
    required_features = (FAST, SLOW)

    def _classify(self, values):
        fast, slow = values[FAST.key], values[SLOW.key]
        if fast > slow:
            return ResearchState.BULLISH, (ReasonCode.FAST_ABOVE_SLOW,)
        if fast < slow:
            return ResearchState.BEARISH, (ReasonCode.FAST_BELOW_SLOW,)
        return ResearchState.NEUTRAL, (ReasonCode.FAST_EQUALS_SLOW,)


class TestEvidenceAlignment:
    def test_aligned_evidence_is_accepted(self):
        evidence = build_evidence(rising(), [FAST, SLOW])
        assert len(evidence) == 30
        assert set(evidence.keys()) == {FAST.key, SLOW.key}

    def test_timestamp_mismatch_is_rejected(self):
        """RSI at T combined with SMA at T+1 produces a wrong number silently."""
        series = rising()
        shifted = series.prefix(len(series) - 1)
        with pytest.raises(EvidenceError, match="not aligned"):
            EvidenceSet.from_features([sma(series, 3), sma(shifted, 5)])

    def test_symbol_mismatch_is_rejected(self):
        with pytest.raises(EvidenceError, match="symbol"):
            EvidenceSet.from_features(
                [sma(rising(), 3), sma(make_series([10.0] * 30, symbol="OTHER"), 5)]
            )

    def test_interval_mismatch_is_rejected(self):
        with pytest.raises(EvidenceError, match="interval"):
            EvidenceSet.from_features(
                [sma(rising(), 3), sma(make_series([10.0] * 30, interval="1h"), 5)]
            )

    def test_price_basis_mismatch_is_rejected(self):
        adjusted = make_series([10.0] * 30, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        with pytest.raises(EvidenceError, match="basis"):
            EvidenceSet.from_features([sma(rising(), 3), sma(adjusted, 5)])

    def test_duplicate_features_are_rejected(self):
        series = rising()
        with pytest.raises(EvidenceError, match="duplicate"):
            EvidenceSet.from_features([sma(series, 3), sma(series, 3)])

    def test_an_empty_evidence_set_is_rejected(self):
        with pytest.raises(EvidenceError):
            EvidenceSet.from_features([])

    def test_unknown_feature_names_are_rejected(self):
        with pytest.raises(EvidenceError, match="unknown feature"):
            build_evidence(rising(), [FeatureSpec("macd", {"period": 12})])

    def test_wrong_parameter_names_are_rejected(self):
        with pytest.raises(EvidenceError, match="unknown parameter"):
            build_evidence(rising(), [FeatureSpec("sma", {"window": 3})])


class TestEvaluation:
    def test_a_rising_series_classifies_bullish_once_warm(self):
        observations = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))
        ready = [o for o in observations if o.state is not ResearchState.INSUFFICIENT_DATA]
        assert ready and all(o.state is ResearchState.BULLISH for o in ready)

    def test_a_falling_series_classifies_bearish_once_warm(self):
        observations = Demo().evaluate(build_evidence(falling(), [FAST, SLOW]))
        ready = [o for o in observations if o.state is not ResearchState.INSUFFICIENT_DATA]
        assert ready and all(o.state is ResearchState.BEARISH for o in ready)

    def test_a_flat_series_classifies_neutral(self):
        observations = Demo().evaluate(build_evidence(make_series([10.0] * 30), [FAST, SLOW]))
        ready = [o for o in observations if o.state is not ResearchState.INSUFFICIENT_DATA]
        assert ready and all(o.state is ResearchState.NEUTRAL for o in ready)

    def test_one_observation_per_bar_aligned_to_its_timestamp(self):
        evidence = build_evidence(rising(), [FAST, SLOW])
        observations = Demo().evaluate(evidence)
        assert len(observations) == len(evidence)
        assert tuple(o.timestamp for o in observations) == evidence.timestamps

    def test_evaluate_at_matches_the_full_run(self):
        evidence = build_evidence(rising(), [FAST, SLOW])
        hypothesis = Demo()
        full = hypothesis.evaluate(evidence)
        assert hypothesis.evaluate_at(evidence, 10).state is full[10].state

    def test_evaluate_at_rejects_an_out_of_range_index(self):
        evidence = build_evidence(rising(), [FAST, SLOW])
        with pytest.raises(HypothesisError, match="out of range"):
            Demo().evaluate_at(evidence, 999)

    def test_evaluation_is_deterministic(self):
        evidence = build_evidence(rising(), [FAST, SLOW])
        first = Demo().evaluate(evidence)
        second = Demo().evaluate(evidence)
        assert [o.state for o in first] == [o.state for o in second]
        assert [o.reason_codes for o in first] == [o.reason_codes for o in second]
        assert [dict(o.evidence) for o in first] == [dict(o.evidence) for o in second]


class TestWarmUpVersusError:
    """INSUFFICIENT_DATA is for warm-up only; structure problems raise."""

    def test_warm_up_yields_insufficient_data(self):
        observations = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))
        # SLOW is sma(5): first four bars cannot be defined.
        assert all(o.state is ResearchState.INSUFFICIENT_DATA for o in observations[:4])
        assert observations[4].state is not ResearchState.INSUFFICIENT_DATA

    def test_warm_up_carries_a_deterministic_reason_code(self):
        observations = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert observations[0].reason_codes == (ReasonCode.WARMUP_INCOMPLETE,)

    def test_warm_up_evidence_is_recorded_as_none_not_zero(self):
        observations = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert observations[0].evidence[SLOW.key] is None

    def test_missing_required_evidence_raises(self):
        with pytest.raises(HypothesisError, match="missing required feature"):
            Demo().evaluate(build_evidence(rising(), [FAST]))

    def test_substitute_evidence_is_not_accepted(self):
        """sma(4) is not a stand-in for sma(5)."""
        wrong = build_evidence(rising(), [FAST, FeatureSpec("sma", {"period": 4})])
        with pytest.raises(HypothesisError, match="missing required feature"):
            Demo().evaluate(wrong)

    def test_a_non_evidence_object_raises(self):
        with pytest.raises(HypothesisError, match="EvidenceSet"):
            Demo().evaluate([1, 2, 3])

    def test_a_hypothesis_cannot_return_insufficient_data_itself(self):
        class Sneaky(Demo):
            hypothesis_id = "sneaky"
            def _classify(self, values):
                return ResearchState.INSUFFICIENT_DATA, (ReasonCode.FAST_ABOVE_SLOW,)

        with pytest.raises(HypothesisError, match="reserved for warm-up"):
            Sneaky().evaluate(build_evidence(rising(), [FAST, SLOW]))

    def test_a_hypothesis_must_give_a_reason(self):
        class Mute(Demo):
            hypothesis_id = "mute"
            def _classify(self, values):
                return ResearchState.NEUTRAL, ()

        with pytest.raises(HypothesisError, match="no reason codes"):
            Mute().evaluate(build_evidence(rising(), [FAST, SLOW]))


class TestPriceBasisPolicy:
    class NeedsAdjusted(Demo):
        hypothesis_id = "needs_adjusted"
        required_basis = PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED

    def test_a_hypothesis_requiring_adjusted_rejects_raw_evidence(self):
        with pytest.raises(HypothesisError, match="requires"):
            self.NeedsAdjusted().evaluate(build_evidence(rising(), [FAST, SLOW]))

    def test_it_does_not_silently_convert_the_basis(self):
        with pytest.raises(HypothesisError, match="data layer"):
            self.NeedsAdjusted().evaluate(build_evidence(rising(), [FAST, SLOW]))

    def test_it_accepts_evidence_on_the_required_basis(self):
        adjusted = make_series(
            [10.0 + i for i in range(30)], basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
        )
        observations = self.NeedsAdjusted().evaluate(build_evidence(adjusted, [FAST, SLOW]))
        assert observations[-1].basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED

    def test_a_basis_agnostic_hypothesis_accepts_either(self):
        for basis in (PriceBasis.RAW, PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED):
            series = make_series([10.0 + i for i in range(30)], basis=basis)
            assert Demo().evaluate(build_evidence(series, [FAST, SLOW]))

    def test_the_observation_records_the_basis_it_used(self):
        observations = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert observations[-1].basis is PriceBasis.RAW


class TestObservationRecord:
    def _observation(self):
        return Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))[-1]

    def test_it_is_immutable(self):
        observation = self._observation()
        with pytest.raises((AttributeError, TypeError)):
            observation.state = ResearchState.BEARISH  # type: ignore[misc]

    def test_its_evidence_mapping_is_read_only(self):
        observation = self._observation()
        with pytest.raises(TypeError):
            observation.evidence[FAST.key] = 1.0  # type: ignore[index]

    def test_it_records_the_producing_version_and_fingerprint(self):
        observation = self._observation()
        hypothesis = Demo()
        assert observation.version == hypothesis.spec.version
        assert observation.fingerprint == hypothesis.fingerprint
        assert observation.label == hypothesis.label

    def test_it_records_the_evidence_actually_used(self):
        observation = self._observation()
        assert set(observation.evidence) == {FAST.key, SLOW.key}

    def test_a_naive_timestamp_is_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            ResearchObservation(
                "demo", 1, "abc", "TEST", Interval.DAY_1, PriceBasis.RAW,
                datetime(2024, 1, 1), ResearchState.NEUTRAL, {}, (ReasonCode.FAST_EQUALS_SLOW,),
            )

    def test_an_observation_without_a_reason_is_rejected(self):
        with pytest.raises(ValueError, match="reason code"):
            ResearchObservation(
                "demo", 1, "abc", "TEST", Interval.DAY_1, PriceBasis.RAW,
                datetime(2024, 1, 1, tzinfo=UTC), ResearchState.NEUTRAL, {}, (),
            )


class TestTimingSemantics:
    def test_an_observation_is_evaluable_only_after_its_bar_completes(self):
        observation = Demo().evaluate(build_evidence(rising(), [FAST, SLOW]))[-1]
        assert observation.evaluable_from == observation.timestamp + Interval.DAY_1.max_duration
        assert observation.evaluable_from > observation.timestamp

    def test_it_tracks_the_interval_not_the_calendar(self):
        hourly = make_series([10.0 + i for i in range(30)], interval="1h")
        observation = Demo().evaluate(build_evidence(hourly, [FAST, SLOW]))[-1]
        assert observation.evaluable_from - observation.timestamp == timedelta(hours=1)

    def test_the_bound_is_documented_as_a_bound(self):
        # Guards against the record quietly claiming provider-arrival precision
        # that Phase 1/2 cannot supply.
        text = (ResearchObservation.__doc__ or "").lower()
        assert "bound" in text and "not a measurement" in text


class TestShippedHypotheses:
    def _trending(self):
        return make_series([10.0 + i * 0.4 for i in range(80)])

    def test_trend_alignment_runs_end_to_end(self):
        hypothesis = TrendAlignment()
        observations = hypothesis.evaluate(
            build_evidence(self._trending(), hypothesis.spec.required_features)
        )
        assert len(observations) == 80
        assert any(o.state is ResearchState.BULLISH for o in observations)

    def test_trend_alignment_uses_a_dead_band(self):
        flat = make_series([10.0] * 80)
        hypothesis = TrendAlignment()
        observations = hypothesis.evaluate(
            build_evidence(flat, hypothesis.spec.required_features)
        )
        ready = [o for o in observations if o.state is not ResearchState.INSUFFICIENT_DATA]
        assert ready and all(o.state is ResearchState.NEUTRAL for o in ready)

    def test_momentum_in_trend_context_reports_confirmation(self):
        hypothesis = MomentumInTrendContext()
        observations = hypothesis.evaluate(
            build_evidence(self._trending(), hypothesis.spec.required_features)
        )
        ready = [o for o in observations if o.state is ResearchState.BULLISH]
        assert ready
        assert ReasonCode.MOMENTUM_CONFIRMS_TREND in ready[-1].reason_codes

    def test_reason_codes_are_deterministic_across_runs(self):
        hypothesis = MomentumInTrendContext()
        evidence = build_evidence(self._trending(), hypothesis.spec.required_features)
        assert [o.reason_codes for o in hypothesis.evaluate(evidence)] == [
            o.reason_codes for o in hypothesis.evaluate(evidence)
        ]

    def test_states_are_drawn_only_from_the_declared_vocabulary(self):
        hypothesis = MomentumInTrendContext()
        observations = hypothesis.evaluate(
            build_evidence(self._trending(), hypothesis.spec.required_features)
        )
        assert {o.state for o in observations} <= set(ResearchState)
