"""Metrics: hand-computed verification and anti-selection-bias.

Expected values are computed independently in the tests, never by calling the
production aggregation.
"""

from __future__ import annotations

import statistics
from datetime import datetime

import pytest

from src.data.models import Interval
from src.data.series import PriceBasis
from src.evaluation import (
    EvaluatedOutcome,
    OutcomeError,
    OutcomeStatus,
    StateMetrics,
    summarize,
)
from src.strategies.research import ResearchState
from tests.conftest import UTC

BULLISH, BEARISH = ResearchState.BULLISH, ResearchState.BEARISH
NEUTRAL, NODATA = ResearchState.NEUTRAL, ResearchState.INSUFFICIENT_DATA


def outcome(state, value, *, status=None, day=1, spec="spec0", horizon=1):
    """Build one EvaluatedOutcome directly, so metrics are tested in isolation."""
    status = status or (
        OutcomeStatus.EVALUATED if value is not None else OutcomeStatus.INSUFFICIENT_FUTURE_DATA
    )
    stamp = datetime(2024, 1, day, tzinfo=UTC)
    extra = {}
    if status is OutcomeStatus.EVALUATED:
        extra = dict(
            reference_timestamp=stamp, future_timestamp=stamp,
            reference_price=100.0, future_price=100.0 * (1 + value),
            outcome_value=value,
        )
    return EvaluatedOutcome(
        hypothesis_id="h", hypothesis_version=1, hypothesis_fingerprint="fp",
        symbol="X", interval=Interval.DAY_1, basis=PriceBasis.RAW,
        observation_timestamp=stamp, observation_state=state,
        spec_fingerprint=spec, horizon_bars=horizon, status=status, **extra,
    )


class TestHandComputedMetrics:
    def test_mean_median_and_positive_rate(self):
        values = [0.10, -0.10, 0.0, 0.20]
        summary = summarize([outcome(BULLISH, v, day=i + 1) for i, v in enumerate(values)])
        assert summary.bullish.count == 4
        assert summary.bullish.mean_forward_return == pytest.approx(0.05)  # 0.20/4
        assert summary.bullish.median_forward_return == pytest.approx(0.05)  # (0.0+0.10)/2
        assert summary.bullish.positive_return_rate == pytest.approx(0.5)  # 2 of 4

    def test_a_single_positive_observation(self):
        summary = summarize([outcome(BULLISH, 0.10)])
        assert summary.bullish.mean_forward_return == pytest.approx(0.10)
        assert summary.bullish.median_forward_return == pytest.approx(0.10)
        assert summary.bullish.positive_return_rate == 1.0
        assert summary.bullish.directional_hit_rate == 1.0

    def test_a_single_negative_observation(self):
        summary = summarize([outcome(BEARISH, -0.10)])
        assert summary.bearish.mean_forward_return == pytest.approx(-0.10)
        assert summary.bearish.directional_hit_rate == 1.0  # bearish + negative = hit

    def test_exactly_zero_is_a_miss_for_both_directions(self):
        bullish = summarize([outcome(BULLISH, 0.0)])
        bearish = summarize([outcome(BEARISH, 0.0)])
        assert bullish.bullish.directional_hit_rate == 0.0
        assert bearish.bearish.directional_hit_rate == 0.0

    def test_zero_returns_are_counted_not_discarded(self):
        summary = summarize([outcome(BULLISH, 0.0, day=1), outcome(BULLISH, 0.10, day=2)])
        assert summary.bullish.count == 2
        assert summary.bullish.mean_forward_return == pytest.approx(0.05)

    def test_all_bullish(self):
        values = [0.01, 0.02, -0.03]
        summary = summarize([outcome(BULLISH, v, day=i + 1) for i, v in enumerate(values)])
        assert summary.bullish.count == 3
        assert summary.bearish.count == 0
        assert summary.bullish.directional_hit_rate == pytest.approx(2 / 3)

    def test_all_bearish(self):
        values = [-0.01, -0.02, 0.03]
        summary = summarize([outcome(BEARISH, v, day=i + 1) for i, v in enumerate(values)])
        assert summary.bearish.directional_hit_rate == pytest.approx(2 / 3)
        assert summary.bearish.positive_return_rate == pytest.approx(1 / 3)

    def test_all_neutral_has_no_hit_rate(self):
        summary = summarize([outcome(NEUTRAL, 0.05, day=i + 1) for i in range(3)])
        assert summary.neutral.count == 3
        assert summary.neutral.mean_forward_return == pytest.approx(0.05)
        assert summary.neutral.directional_hit_rate is None

    def test_mixed_states_are_partitioned_correctly(self):
        outcomes = [
            outcome(BULLISH, 0.10, day=1), outcome(BULLISH, -0.02, day=2),
            outcome(BEARISH, -0.05, day=3), outcome(NEUTRAL, 0.01, day=4),
        ]
        summary = summarize(outcomes)
        assert (summary.bullish.count, summary.bearish.count, summary.neutral.count) == (2, 1, 1)
        assert summary.bullish.mean_forward_return == pytest.approx(0.04)
        assert summary.bearish.mean_forward_return == pytest.approx(-0.05)
        assert summary.all_evaluated.mean_forward_return == pytest.approx(
            statistics.fmean([0.10, -0.02, -0.05, 0.01])
        )

    def test_extreme_but_finite_values(self):
        summary = summarize([outcome(BULLISH, 1e9, day=1), outcome(BULLISH, -0.999, day=2)])
        assert summary.bullish.mean_forward_return == pytest.approx((1e9 - 0.999) / 2)


class TestUndefinedMetrics:
    def test_absent_states_are_none_not_zero(self):
        summary = summarize([outcome(BULLISH, 0.10)])
        assert summary.bearish.count == 0
        assert summary.bearish.mean_forward_return is None
        assert summary.bearish.median_forward_return is None
        assert summary.bearish.positive_return_rate is None
        assert summary.bearish.directional_hit_rate is None

    def test_no_evaluated_observations_at_all(self):
        summary = summarize([outcome(BULLISH, None, day=1), outcome(BEARISH, None, day=2)])
        assert summary.evaluated_observations == 0
        assert summary.all_evaluated.mean_forward_return is None
        assert summary.unconditional_mean_forward_return is None

    def test_neutral_never_gets_a_hit_rate_even_when_populated(self):
        summary = summarize([outcome(NEUTRAL, 0.10, day=1), outcome(NEUTRAL, -0.10, day=2)])
        assert summary.neutral.count == 2
        assert summary.neutral.directional_hit_rate is None

    def test_state_metrics_over_an_empty_group(self):
        metrics = StateMetrics.over([])
        assert (metrics.count, metrics.mean_forward_return) == (0, None)


class TestAccounting:
    def test_every_category_is_reported(self):
        outcomes = [
            outcome(BULLISH, 0.10, day=1),
            outcome(BEARISH, None, status=OutcomeStatus.INSUFFICIENT_FUTURE_DATA, day=2),
            outcome(NEUTRAL, None, status=OutcomeStatus.NO_REFERENCE_BAR, day=3),
            outcome(NODATA, None, status=OutcomeStatus.INELIGIBLE_OBSERVATION, day=4),
        ]
        summary = summarize(outcomes)
        assert summary.total_observations == 4
        assert summary.evaluated_observations == 1
        assert summary.insufficient_future_data == 1
        assert summary.no_reference_bar == 1
        assert summary.ineligible_observations == 1
        assert summary.eligible_observations == 3

    def test_accounting_always_balances(self):
        outcomes = [
            outcome(BULLISH, 0.1, day=1),
            outcome(BEARISH, None, status=OutcomeStatus.NO_REFERENCE_BAR, day=2),
            outcome(NODATA, None, status=OutcomeStatus.INELIGIBLE_OBSERVATION, day=3),
        ]
        summary = summarize(outcomes)
        assert (
            summary.evaluated_observations
            + summary.insufficient_future_data
            + summary.no_reference_bar
            + summary.ineligible_observations
            == summary.total_observations
        )

    def test_counts_by_state_include_insufficient_data_observations(self):
        summary = summarize([
            outcome(BULLISH, 0.1, day=1),
            outcome(NODATA, None, status=OutcomeStatus.INELIGIBLE_OBSERVATION, day=2),
        ])
        assert summary.observations_by_state[NODATA] == 1
        assert summary.observations_by_state[BULLISH] == 1

    def test_an_empty_outcome_list_is_refused(self):
        with pytest.raises(OutcomeError, match="nothing to account for"):
            summarize([])

    def test_outcomes_from_different_specs_cannot_be_mixed(self):
        with pytest.raises(OutcomeError, match="different evaluations"):
            summarize([outcome(BULLISH, 0.1, day=1, spec="a"),
                       outcome(BULLISH, 0.1, day=2, spec="b")])


class TestAntiSelectionBias:
    """Filtering any category would make the reported result look better."""

    def test_negative_returns_are_not_removed(self):
        # Dropping the losses would turn a negative mean into a positive one.
        outcomes = [outcome(BULLISH, 0.10, day=1)] + [
            outcome(BULLISH, -0.20, day=i + 2) for i in range(3)
        ]
        summary = summarize(outcomes)
        assert summary.bullish.count == 4
        assert summary.bullish.mean_forward_return < 0
        assert summary.bullish.mean_forward_return == pytest.approx((0.10 - 0.60) / 4)

    def test_bearish_observations_are_not_removed(self):
        outcomes = [outcome(BULLISH, 0.10, day=1), outcome(BEARISH, -0.50, day=2)]
        summary = summarize(outcomes)
        assert summary.total_observations == 2
        assert summary.bearish.count == 1
        assert summary.all_evaluated.mean_forward_return == pytest.approx(-0.20)

    def test_neutral_observations_are_not_removed_from_totals(self):
        outcomes = [outcome(BULLISH, 0.10, day=1)] + [
            outcome(NEUTRAL, -0.30, day=i + 2) for i in range(2)
        ]
        summary = summarize(outcomes)
        assert summary.total_observations == 3
        assert summary.neutral.count == 2
        assert summary.all_evaluated.mean_forward_return < 0

    def test_insufficient_future_outcomes_stay_visible(self):
        """End-of-sample survivorship must be reportable."""
        outcomes = [outcome(BULLISH, 0.10, day=1)] + [
            outcome(BULLISH, None, status=OutcomeStatus.INSUFFICIENT_FUTURE_DATA, day=i + 2)
            for i in range(5)
        ]
        summary = summarize(outcomes)
        assert summary.total_observations == 6
        assert summary.insufficient_future_data == 5
        assert summary.evaluated_observations == 1  # only 1 of 6 actually measured

    def test_no_reference_outcomes_stay_visible(self):
        outcomes = [outcome(BULLISH, 0.10, day=1),
                    outcome(BULLISH, None, status=OutcomeStatus.NO_REFERENCE_BAR, day=2)]
        assert summarize(outcomes).no_reference_bar == 1

    def test_ineligible_observations_stay_in_the_total(self):
        outcomes = [outcome(BULLISH, 0.10, day=1)] + [
            outcome(NODATA, None, status=OutcomeStatus.INELIGIBLE_OBSERVATION, day=i + 2)
            for i in range(9)
        ]
        summary = summarize(outcomes)
        assert summary.total_observations == 10
        assert summary.ineligible_observations == 9
        assert summary.eligible_observations == 1


class TestBenchmark:
    def test_the_benchmark_is_the_same_evaluated_sample(self):
        outcomes = [outcome(BULLISH, 0.10, day=1), outcome(BEARISH, -0.30, day=2)]
        summary = summarize(outcomes)
        assert summary.unconditional_mean_forward_return == pytest.approx(-0.10)
        assert summary.unconditional_mean_forward_return == summary.all_evaluated.mean_forward_return

    def test_zero_returns_are_included_in_the_benchmark_sample(self):
        """Regression: filtering zeros would shrink the reference sample.

        Dropping flat outcomes from the unconditional mean silently changes
        which sample a state-conditioned mean is being compared against.
        """
        outcomes = [
            outcome(BULLISH, 0.30, day=1),
            outcome(BEARISH, 0.0, day=2),
            outcome(NEUTRAL, 0.0, day=3),
        ]
        summary = summarize(outcomes)
        assert summary.all_evaluated.count == 3
        assert summary.unconditional_mean_forward_return == pytest.approx(0.10)  # 0.30/3

    def test_negative_returns_are_included_in_the_benchmark_sample(self):
        outcomes = [outcome(BULLISH, 0.30, day=1), outcome(BEARISH, -0.60, day=2)]
        summary = summarize(outcomes)
        assert summary.all_evaluated.count == 2
        assert summary.unconditional_mean_forward_return == pytest.approx(-0.15)

    def test_the_benchmark_sample_equals_the_evaluated_count(self):
        outcomes = [
            outcome(BULLISH, 0.10, day=1), outcome(BEARISH, 0.0, day=2),
            outcome(NEUTRAL, -0.10, day=3),
            outcome(BULLISH, None, status=OutcomeStatus.NO_REFERENCE_BAR, day=4),
        ]
        summary = summarize(outcomes)
        assert summary.all_evaluated.count == summary.evaluated_observations == 3

    def test_a_state_can_beat_or_lose_to_the_benchmark(self):
        outcomes = [outcome(BULLISH, 0.10, day=1), outcome(BEARISH, -0.30, day=2)]
        summary = summarize(outcomes)
        assert summary.bullish.mean_forward_return > summary.unconditional_mean_forward_return


class TestImmutability:
    def test_the_summary_is_frozen(self):
        summary = summarize([outcome(BULLISH, 0.1)])
        with pytest.raises((AttributeError, TypeError)):
            summary.total_observations = 99  # type: ignore[misc]

    def test_the_state_counts_mapping_is_read_only(self):
        summary = summarize([outcome(BULLISH, 0.1)])
        with pytest.raises(TypeError):
            summary.observations_by_state[BULLISH] = 99  # type: ignore[index]

    def test_mutating_the_input_list_afterwards_does_not_change_the_summary(self):
        outcomes = [outcome(BULLISH, 0.10, day=1)]
        summary = summarize(outcomes)
        outcomes.append(outcome(BULLISH, -0.99, day=2))
        assert summary.total_observations == 1
        assert summary.bullish.mean_forward_return == pytest.approx(0.10)

    def test_state_metrics_are_frozen(self):
        metrics = summarize([outcome(BULLISH, 0.1)]).bullish
        with pytest.raises((AttributeError, TypeError)):
            metrics.count = 99  # type: ignore[misc]
