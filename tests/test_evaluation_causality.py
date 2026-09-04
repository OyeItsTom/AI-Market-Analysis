"""Causality of outcome evaluation, and adversarial attack on the harness."""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.evaluation import (
    EvaluatedOutcome,
    OutcomeSpec,
    OutcomeStatus,
    evaluate_observations,
)
from src.strategies.research import ResearchState
from tests.conftest import UTC, make_observations
from tests.evaluation_lookahead import (
    assert_evaluation_causal,
    assert_evaluation_deterministic,
    assert_outcome_ignores_bars_after_horizon,
    assert_outcome_survives_truncation,
    perturb_after,
)

BULLISH = ResearchState.BULLISH


@pytest.fixture
def series():
    """Non-monotonic, so global extrema do not sit permanently in the prefix."""
    closes = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.2 for i in range(20)]
    bars = [
        MarketBar("X", datetime(2024, 1, 1, tzinfo=UTC) + Interval.DAY_1.max_duration * i,
                  c * 0.98, c * 1.05, c * 0.95, c, 1_000.0 + i, "1d", "t")
        for i, c in enumerate(closes)
    ]
    return BarSeries.from_bars(bars, basis=PriceBasis.RAW)


def runner(spec=None):
    """The whole pipeline as one callable: bars in, outcome records out."""
    spec = spec or OutcomeSpec(horizon_bars=3)

    def run(s):
        return evaluate_observations(
            make_observations(s, [BULLISH] * len(s)), s, spec
        )

    return run


class TestEvaluationIsCausal:
    @pytest.mark.parametrize("horizon", [1, 2, 3, 5])
    def test_bars_after_the_horizon_cannot_change_an_outcome(self, horizon, series):
        assert_outcome_ignores_bars_after_horizon(
            runner(OutcomeSpec(horizon_bars=horizon)), series, label=f"h={horizon}"
        )

    @pytest.mark.parametrize("horizon", [1, 2, 3, 5])
    def test_truncating_after_the_future_bar_changes_nothing(self, horizon, series):
        assert_outcome_survives_truncation(
            runner(OutcomeSpec(horizon_bars=horizon)), series, label=f"h={horizon}"
        )

    def test_both_properties_together(self, series):
        assert_evaluation_causal(runner(), series, label="forward_return")

    def test_evaluation_is_deterministic(self, series):
        assert_evaluation_deterministic(runner(), series)

    def test_it_does_not_mutate_the_series(self, series):
        before = series.values("close")
        runner()(series)
        assert series.values("close") == before

    def test_mutating_the_observation_container_afterwards_changes_nothing(self, series):
        observations = list(make_observations(series, [BULLISH] * len(series)))
        outcomes = evaluate_observations(observations, series, OutcomeSpec())
        observations.clear()
        assert len(outcomes) == len(series)

    def test_an_observation_is_immutable_so_it_cannot_be_rewritten(self, series):
        observation = make_observations(series, [BULLISH] * len(series))[0]
        with pytest.raises((AttributeError, TypeError)):
            observation.state = ResearchState.BEARISH  # type: ignore[misc]


class TestHarnessCatchesCheats:
    """The harness is worth only what it catches.

    Each cheat below replaces the production evaluator with one that reads
    something it must not. Their categories are reported honestly: some are
    caught, some are structurally impossible in production, and one is
    genuinely causal and correctly passes.
    """

    def _cheat(self, series, pick):
        """An evaluator whose outcome value comes from `pick(series, index)`."""

        def run(s):
            observations = make_observations(s, [BULLISH] * len(s))
            spec = OutcomeSpec(horizon_bars=2)
            honest = evaluate_observations(observations, s, spec)
            out = []
            for index, record in enumerate(honest):
                if record.status is not OutcomeStatus.EVALUATED:
                    out.append(record)
                    continue
                value = pick(s, index)
                out.append(
                    EvaluatedOutcome(
                        hypothesis_id=record.hypothesis_id,
                        hypothesis_version=record.hypothesis_version,
                        hypothesis_fingerprint=record.hypothesis_fingerprint,
                        symbol=record.symbol, interval=record.interval, basis=record.basis,
                        observation_timestamp=record.observation_timestamp,
                        observation_state=record.observation_state,
                        spec_fingerprint=record.spec_fingerprint,
                        horizon_bars=record.horizon_bars,
                        status=OutcomeStatus.EVALUATED,
                        reference_timestamp=record.reference_timestamp,
                        future_timestamp=record.future_timestamp,
                        reference_price=record.reference_price,
                        future_price=record.future_price,
                        outcome_value=value,
                    )
                )
            return tuple(out)

        return run

    def _assert_caught(self, series, pick):
        with pytest.raises(AssertionError):
            assert_evaluation_causal(self._cheat(series, pick), series)

    def test_final_dataset_value_is_caught(self, series):
        self._assert_caught(series, lambda s, i: s[-1].close / 1000.0)

    def test_global_future_maximum_is_caught(self, series):
        self._assert_caught(series, lambda s, i: max(s.values("close")) / 1000.0)

    def test_global_future_minimum_is_caught(self, series):
        self._assert_caught(series, lambda s, i: min(s.values("close")) / 1000.0)

    def test_dataset_length_is_caught(self, series):
        self._assert_caught(series, lambda s, i: float(len(s)) / 1000.0)

    def test_existence_of_extra_future_rows_is_caught(self, series):
        self._assert_caught(series, lambda s, i: 0.1 if i + 5 < len(s) else -0.1)

    def test_tail_parity_is_caught(self, series):
        self._assert_caught(series, lambda s, i: 0.1 if (len(s) - i) % 2 == 0 else -0.1)

    def test_value_only_when_the_tail_increases_is_caught(self, series):
        self._assert_caught(
            series, lambda s, i: 0.1 if s[-1].close > s[0].close else -0.1
        )

    def test_value_only_when_the_tail_decreases_is_caught(self, series):
        self._assert_caught(
            series, lambda s, i: 0.1 if s[-1].close < s[0].close else -0.1
        )

    def test_an_index_dependent_evaluator_is_genuinely_causal_and_passes(self, series):
        """Category 3: not a cheat.

        A bar's index depends only on how many bars precede it, so it uses no
        future information. Truncation preserves earlier indices and
        perturbation does not move them. The harness is right to pass it --
        and production cannot do it anyway, because the evaluator receives no
        index-dependent freedom.
        """
        assert_evaluation_causal(self._cheat(series, lambda s, i: 0.01 * (i % 3)), series)

    def test_the_honest_evaluator_is_not_falsely_accused(self, series):
        assert_evaluation_causal(runner(), series)

    def test_the_perturbation_really_changes_the_tail(self, series):
        perturbed = perturb_after(series, 10)
        assert perturbed.values("close")[:11] == series.values("close")[:11]
        assert perturbed.values("close")[11:] != series.values("close")[11:]

    def test_the_perturbation_moves_the_tail_in_both_directions(self, series):
        perturbed = perturb_after(series, 5)
        tail = perturbed.values("close")[6:]
        head = series.values("close")[:6]
        assert max(tail) > max(head)
        assert min(tail) < min(head)


class TestNumericSafety:
    """Verify Phase 1's guarantees rather than assuming them."""

    @pytest.mark.parametrize("bad", [0.0, -5.0])
    def test_non_positive_prices_cannot_reach_a_series(self, bad):
        from src.data.series import SeriesError

        bars = [
            MarketBar("X", datetime(2024, 1, d, tzinfo=UTC), 100.0, 120.0, 80.0, 100.0,
                      1_000.0, "1d", "t")
            for d in (1, 2)
        ]
        broken = MarketBar("X", datetime(2024, 1, 3, tzinfo=UTC), bad if bad > 0 else 100.0,
                           120.0, 80.0, 100.0, 1_000.0, "1d", "t") if bad > 0 else None
        with pytest.raises((SeriesError, ValueError)):
            import dataclasses
            bars.append(dataclasses.replace(bars[0], open=bad, low=bad,
                                            timestamp=datetime(2024, 1, 3, tzinfo=UTC)))
            BarSeries.from_bars(bars, basis=PriceBasis.RAW)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_prices_cannot_reach_a_bar(self, bad):
        with pytest.raises(ValueError, match="finite"):
            MarketBar("X", datetime(2024, 1, 1, tzinfo=UTC), 100.0, 120.0, 80.0, bad,
                      1_000.0, "1d", "t")

    def test_every_evaluated_outcome_is_finite(self, series):
        for outcome in runner()(series):
            if outcome.status is OutcomeStatus.EVALUATED:
                assert math.isfinite(outcome.outcome_value)

    def test_an_evaluated_record_cannot_be_built_without_a_value(self):
        from src.evaluation import OutcomeError

        with pytest.raises(OutcomeError, match="must carry"):
            EvaluatedOutcome(
                hypothesis_id="h", hypothesis_version=1, hypothesis_fingerprint="fp",
                symbol="X", interval=Interval.DAY_1, basis=PriceBasis.RAW,
                observation_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                observation_state=BULLISH, spec_fingerprint="s", horizon_bars=1,
                status=OutcomeStatus.EVALUATED,
            )

    def test_an_unavailable_record_cannot_carry_a_value(self):
        from src.evaluation import OutcomeError

        with pytest.raises(OutcomeError, match="not a zero result"):
            EvaluatedOutcome(
                hypothesis_id="h", hypothesis_version=1, hypothesis_fingerprint="fp",
                symbol="X", interval=Interval.DAY_1, basis=PriceBasis.RAW,
                observation_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                observation_state=BULLISH, spec_fingerprint="s", horizon_bars=1,
                status=OutcomeStatus.NO_REFERENCE_BAR, outcome_value=0.0,
            )

    def test_an_evaluated_record_rejects_a_non_finite_value(self):
        from src.evaluation import OutcomeError

        stamp = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(OutcomeError, match="finite"):
            EvaluatedOutcome(
                hypothesis_id="h", hypothesis_version=1, hypothesis_fingerprint="fp",
                symbol="X", interval=Interval.DAY_1, basis=PriceBasis.RAW,
                observation_timestamp=stamp, observation_state=BULLISH,
                spec_fingerprint="s", horizon_bars=1, status=OutcomeStatus.EVALUATED,
                reference_timestamp=stamp, future_timestamp=stamp,
                reference_price=100.0, future_price=100.0, outcome_value=float("inf"),
            )


class TestRecordInvariants:
    """A record must not describe bars its own status says were never reached."""

    def _base(self):
        return dict(
            hypothesis_id="h", hypothesis_version=1, hypothesis_fingerprint="fp",
            symbol="X", interval=Interval.DAY_1, basis=PriceBasis.RAW,
            observation_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            observation_state=BULLISH, spec_fingerprint="s", horizon_bars=1,
        )

    @pytest.mark.parametrize(
        ("status", "extra"),
        [
            (OutcomeStatus.NO_REFERENCE_BAR, {"reference_price": 100.0}),
            (OutcomeStatus.NO_REFERENCE_BAR, {"reference_timestamp": datetime(2024, 1, 2, tzinfo=UTC)}),
            (OutcomeStatus.NO_REFERENCE_BAR, {"future_price": 110.0}),
            (OutcomeStatus.INELIGIBLE_OBSERVATION, {"reference_price": 100.0}),
            (OutcomeStatus.INELIGIBLE_OBSERVATION, {"future_timestamp": datetime(2024, 1, 2, tzinfo=UTC)}),
            (OutcomeStatus.INSUFFICIENT_FUTURE_DATA, {"future_price": 110.0}),
            (OutcomeStatus.INSUFFICIENT_FUTURE_DATA, {"future_timestamp": datetime(2024, 1, 2, tzinfo=UTC)}),
        ],
    )
    def test_contradictory_records_cannot_be_constructed(self, status, extra):
        from src.evaluation import OutcomeError

        with pytest.raises(OutcomeError, match="never reached"):
            EvaluatedOutcome(**self._base(), status=status, **extra)

    def test_insufficient_future_may_keep_the_reference_bar_it_found(self):
        """It legitimately found a reference; it just could not reach the horizon."""
        record = EvaluatedOutcome(
            **self._base(), status=OutcomeStatus.INSUFFICIENT_FUTURE_DATA,
            reference_timestamp=datetime(2024, 1, 2, tzinfo=UTC), reference_price=100.0,
        )
        assert record.reference_price == 100.0
        assert record.future_price is None

    def test_the_evaluator_produces_only_consistent_records(self, series):
        for horizon in (1, 3, 8):
            for record in runner(OutcomeSpec(horizon_bars=horizon))(series):
                if record.status is OutcomeStatus.NO_REFERENCE_BAR:
                    assert record.reference_timestamp is None
                elif record.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA:
                    assert record.reference_timestamp is not None
                    assert record.future_timestamp is None


class TestOrderingContract:
    """Output follows caller order; summaries are permutation-invariant."""

    def test_output_follows_caller_order_and_is_not_sorted(self, series):
        from src.evaluation import evaluate_observations

        observations = make_observations(series, [BULLISH] * len(series))
        permuted = (observations[2], observations[0], observations[1]) + observations[3:]
        outcomes = evaluate_observations(permuted, series, OutcomeSpec())
        assert [o.observation_timestamp for o in outcomes] == [
            o.timestamp for o in permuted
        ]

    def test_each_record_is_correct_regardless_of_input_order(self, series):
        from src.evaluation import evaluate_observations

        observations = make_observations(series, [BULLISH] * len(series))
        spec = OutcomeSpec(horizon_bars=2)
        in_order = {
            o.observation_timestamp: o.outcome_value
            for o in evaluate_observations(observations, series, spec)
        }
        reversed_order = {
            o.observation_timestamp: o.outcome_value
            for o in evaluate_observations(tuple(reversed(observations)), series, spec)
        }
        assert in_order == reversed_order

    def test_the_summary_is_permutation_invariant(self, series):
        from src.evaluation import evaluate_observations, summarize

        observations = make_observations(series, [BULLISH] * len(series))
        spec = OutcomeSpec(horizon_bars=2)
        a = summarize(evaluate_observations(observations, series, spec))
        b = summarize(evaluate_observations(tuple(reversed(observations)), series, spec))
        assert a.total_observations == b.total_observations
        assert a.all_evaluated.mean_forward_return == b.all_evaluated.mean_forward_return
        assert a.bullish.directional_hit_rate == b.bullish.directional_hit_rate


class TestProvenanceIsPreservedNotAuthenticated:
    """The documented trust model, pinned so it cannot be silently overstated."""

    def test_an_arbitrary_fingerprint_is_copied_verbatim(self, series):
        from src.evaluation import evaluate_observations
        from src.strategies.research import ReasonCode, ResearchObservation

        forged = (
            ResearchObservation(
                hypothesis_id="momentum_v1", version=1, fingerprint="0000000000000000",
                symbol=series.symbol, interval=series.interval, basis=series.basis,
                timestamp=series.timestamps[0], state=BULLISH, evidence={},
                reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
            ),
        )
        record = evaluate_observations(forged, series, OutcomeSpec())[0]
        assert record.hypothesis_fingerprint == "0000000000000000"

    def test_the_trust_boundary_is_documented(self):
        from src.evaluation.outcome import EvaluatedOutcome as Record

        doc = (Record.__doc__ or "").lower()
        assert "preserved, not authenticated" in doc

    def test_structure_is_still_validated(self, series):
        """Structural claims ARE checked, even though provenance is not."""
        from src.evaluation import EvaluationError, evaluate_observations
        from src.strategies.research import ReasonCode, ResearchObservation

        wrong_symbol = (
            ResearchObservation(
                hypothesis_id="h", version=1, fingerprint="fp",
                symbol="OTHER", interval=series.interval, basis=series.basis,
                timestamp=series.timestamps[0], state=BULLISH, evidence={},
                reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
            ),
        )
        with pytest.raises(EvaluationError, match="symbol"):
            evaluate_observations(wrong_symbol, series, OutcomeSpec())


class TestProvenance:
    def test_the_record_carries_the_producing_hypothesis(self, series):
        outcome = runner()(series)[0]
        assert outcome.hypothesis_id == "test_hypothesis"
        assert outcome.hypothesis_version == 1
        assert outcome.hypothesis_fingerprint == "0123456789abcdef"
        assert outcome.label == "test_hypothesis@v1#0123456789abcdef"

    def test_the_record_carries_the_outcome_specification(self, series):
        spec = OutcomeSpec(horizon_bars=3)
        outcome = runner(spec)(series)[0]
        assert outcome.spec_fingerprint == spec.fingerprint
        assert outcome.horizon_bars == 3

    def test_changing_the_horizon_changes_the_recorded_spec(self, series):
        a = runner(OutcomeSpec(horizon_bars=2))(series)[0]
        b = runner(OutcomeSpec(horizon_bars=5))(series)[0]
        assert a.spec_fingerprint != b.spec_fingerprint

    def test_the_record_is_immutable(self, series):
        outcome = runner()(series)[0]
        with pytest.raises((AttributeError, TypeError)):
            outcome.outcome_value = 99.0  # type: ignore[misc]

    def test_the_record_carries_symbol_interval_and_basis(self, series):
        outcome = runner()(series)[0]
        assert (outcome.symbol, outcome.interval, outcome.basis) == (
            "X", Interval.DAY_1, PriceBasis.RAW,
        )
