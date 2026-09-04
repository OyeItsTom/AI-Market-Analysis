"""Evaluation: reference selection, horizon indexing, status and alignment.

Fixtures use deliberately unmistakable prices — bar *n* has open ``n*100`` and
close ``n*100 + 50`` — so an off-by-one is visible in the number itself rather
than hidden behind a plausible return.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.evaluation import (
    EvaluationError,
    OutcomeSpec,
    OutcomeStatus,
    PriceField,
    evaluate_observations,
)
from src.strategies.research import ResearchState
from tests.conftest import UTC, make_observations

BULLISH = ResearchState.BULLISH


def marked_series(count=6, *, symbol="X", interval="1d", basis=PriceBasis.RAW,
                  start=None, step=None):
    """Bar n (1-based): open = n*100, close = n*100 + 50."""
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    step = step or Interval.parse(interval).max_duration
    bars = [
        MarketBar(
            symbol=symbol,
            timestamp=start + step * index,
            open=(index + 1) * 100.0,
            high=(index + 1) * 100.0 + 90.0,
            low=(index + 1) * 100.0 - 10.0,
            close=(index + 1) * 100.0 + 50.0,
            volume=1_000.0,
            interval=interval,
            source="t",
        )
        for index in range(count)
    ]
    return BarSeries.from_bars(bars, basis=basis)


def evaluate(series, states=None, spec=None):
    states = states or [BULLISH] * len(series)
    return evaluate_observations(
        make_observations(series, states), series, spec or OutcomeSpec()
    )


class TestReferenceConvention:
    """Reference = OPEN of bar i+1. Never bar i."""

    def test_reference_is_the_next_bar_open(self):
        series = marked_series()
        outcome = evaluate(series)[0]
        assert outcome.reference_timestamp == series.timestamps[1]
        assert outcome.reference_price == 200.0  # bar 2 open, not bar 1's 100.0

    def test_the_observation_bar_open_is_never_the_reference(self):
        """Same-bar leakage: bar i's open predates the information that
        produced the observation from bar i's completed data."""
        series = marked_series()
        outcome = evaluate(series)[0]
        assert outcome.reference_price != series[0].open
        assert outcome.reference_timestamp != outcome.observation_timestamp

    def test_the_observation_bar_close_is_never_the_reference(self):
        series = marked_series()
        assert evaluate(series)[0].reference_price != series[0].close

    def test_the_final_observation_has_no_reference_bar(self):
        outcomes = evaluate(marked_series())
        assert outcomes[-1].status is OutcomeStatus.NO_REFERENCE_BAR
        assert outcomes[-1].reference_timestamp is None
        assert outcomes[-1].outcome_value is None


class TestHorizonIndexing:
    """future_index = reference_index + horizon_bars - 1."""

    @pytest.mark.parametrize(
        ("horizon", "future_bar_number", "expected_return"),
        [
            # reference is always bar 2 open = 200.0
            (1, 2, 250.0 / 200.0 - 1.0),
            (2, 3, 350.0 / 200.0 - 1.0),
            (3, 4, 450.0 / 200.0 - 1.0),
            (4, 5, 550.0 / 200.0 - 1.0),
        ],
    )
    def test_hand_computed_horizons(self, horizon, future_bar_number, expected_return):
        series = marked_series()
        outcome = evaluate(series, spec=OutcomeSpec(horizon_bars=horizon))[0]
        assert outcome.reference_price == 200.0
        assert outcome.future_timestamp == series.timestamps[future_bar_number - 1]
        assert outcome.future_price == future_bar_number * 100.0 + 50.0
        assert outcome.outcome_value == pytest.approx(expected_return)

    def test_horizon_one_ends_on_the_reference_bar_itself(self):
        outcome = evaluate(marked_series(), spec=OutcomeSpec(horizon_bars=1))[0]
        assert outcome.reference_timestamp == outcome.future_timestamp

    def test_horizon_two_ends_one_bar_after_the_reference(self):
        series = marked_series()
        outcome = evaluate(series, spec=OutcomeSpec(horizon_bars=2))[0]
        assert outcome.future_timestamp == series.timestamps[2]

    def test_the_future_field_is_configurable_and_used(self):
        series = marked_series()
        outcome = evaluate(
            series, spec=OutcomeSpec(horizon_bars=2, future_field=PriceField.OPEN)
        )[0]
        assert outcome.future_price == 300.0  # bar 3 OPEN, not its close


class TestForwardReturnArithmetic:
    def test_it_is_an_arithmetic_fraction_not_a_percentage(self):
        series = marked_series(count=3)
        # reference bar 2 open = 200, horizon 1 -> bar 2 close = 250 -> +0.25
        outcome = evaluate(series)[0]
        assert outcome.outcome_value == pytest.approx(0.25)
        assert outcome.outcome_value != pytest.approx(25.0)

    def test_a_hand_computed_positive_return(self):
        bars = [
            MarketBar("X", datetime(2024, 1, d, tzinfo=UTC), o, o + 20, o - 20, c,
                      1_000.0, "1d", "t")
            for d, o, c in ((1, 50.0, 55.0), (2, 100.0, 110.0), (3, 90.0, 95.0))
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        outcome = evaluate(series)[0]
        assert outcome.reference_price == 100.0
        assert outcome.future_price == 110.0
        assert outcome.outcome_value == pytest.approx(0.10)

    def test_a_hand_computed_negative_return(self):
        bars = [
            MarketBar("X", datetime(2024, 1, d, tzinfo=UTC), o, o + 20, o - 20, c,
                      1_000.0, "1d", "t")
            for d, o, c in ((1, 50.0, 55.0), (2, 100.0, 90.0), (3, 90.0, 95.0))
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        assert evaluate(series)[0].outcome_value == pytest.approx(-0.10)

    def test_a_hand_computed_zero_return(self):
        bars = [
            MarketBar("X", datetime(2024, 1, d, tzinfo=UTC), 100.0, 120.0, 80.0, c,
                      1_000.0, "1d", "t")
            for d, c in ((1, 105.0), (2, 100.0), (3, 100.0))
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        outcome = evaluate(series)[0]
        assert outcome.outcome_value == 0.0
        assert outcome.status is OutcomeStatus.EVALUATED  # zero is a result, not a gap


class TestStatuses:
    def test_insufficient_future_data_when_the_horizon_overruns(self):
        series = marked_series(count=4)
        outcomes = evaluate(series, spec=OutcomeSpec(horizon_bars=3))
        # obs 0 -> future index 3 (exists). obs 1 -> future index 4 (does not).
        assert outcomes[0].status is OutcomeStatus.EVALUATED
        assert outcomes[1].status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA

    def test_insufficient_future_data_is_not_a_zero_return(self):
        outcomes = evaluate(marked_series(count=4), spec=OutcomeSpec(horizon_bars=3))
        insufficient = [o for o in outcomes if o.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA]
        assert insufficient
        assert all(o.outcome_value is None for o in insufficient)

    def test_insufficient_future_still_records_the_reference_it_found(self):
        outcomes = evaluate(marked_series(count=4), spec=OutcomeSpec(horizon_bars=3))
        insufficient = next(
            o for o in outcomes if o.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        )
        assert insufficient.reference_timestamp is not None
        assert insufficient.future_timestamp is None

    def test_no_reference_bar_is_distinct_from_insufficient_future(self):
        outcomes = evaluate(marked_series(count=4), spec=OutcomeSpec(horizon_bars=3))
        assert outcomes[-1].status is OutcomeStatus.NO_REFERENCE_BAR
        assert outcomes[-2].status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA

    def test_every_observation_produces_exactly_one_record(self):
        series = marked_series(count=6)
        outcomes = evaluate(series, spec=OutcomeSpec(horizon_bars=4))
        assert len(outcomes) == len(series)
        assert [o.observation_timestamp for o in outcomes] == list(series.timestamps)

    def test_an_insufficient_data_observation_is_ineligible_not_dropped(self):
        series = marked_series()
        states = [ResearchState.INSUFFICIENT_DATA] * 2 + [BULLISH] * 4
        outcomes = evaluate(series, states)
        assert outcomes[0].status is OutcomeStatus.INELIGIBLE_OBSERVATION
        assert outcomes[0].outcome_value is None
        assert len(outcomes) == len(series)


class TestAlignment:
    def _observations(self, series, **overrides):
        from src.strategies.research import ReasonCode, ResearchObservation

        fields = dict(
            hypothesis_id="h", version=1, fingerprint="fp",
            symbol=series.symbol, interval=series.interval, basis=series.basis,
            timestamp=series.timestamps[0], state=BULLISH, evidence={},
            reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
        )
        fields.update(overrides)
        return (ResearchObservation(**fields),)

    def test_symbol_mismatch_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="symbol"):
            evaluate_observations(self._observations(series, symbol="OTHER"), series, OutcomeSpec())

    def test_interval_mismatch_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="interval"):
            evaluate_observations(self._observations(series, interval="1h"), series, OutcomeSpec())

    def test_basis_mismatch_between_observation_and_series_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="basis"):
            evaluate_observations(
                self._observations(series, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
                series, OutcomeSpec(),
            )

    def test_basis_mismatch_against_the_spec_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="requires"):
            evaluate_observations(
                make_observations(series, [BULLISH] * len(series)), series,
                OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
            )

    def test_evaluation_never_converts_the_basis(self):
        adjusted = marked_series(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        with pytest.raises(EvaluationError, match="data layer"):
            evaluate_observations(
                make_observations(adjusted, [BULLISH] * len(adjusted)), adjusted,
                OutcomeSpec(required_basis=PriceBasis.RAW),
            )

    def test_a_matching_adjusted_basis_is_accepted(self):
        adjusted = marked_series(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        outcomes = evaluate_observations(
            make_observations(adjusted, [BULLISH] * len(adjusted)), adjusted,
            OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
        )
        assert outcomes[0].status is OutcomeStatus.EVALUATED

    def test_an_observation_timestamp_not_in_the_series_raises(self):
        series = marked_series()
        stray = series.timestamps[0] + timedelta(hours=7)  # between bars
        with pytest.raises(EvaluationError, match="does not correspond"):
            evaluate_observations(self._observations(series, timestamp=stray), series, OutcomeSpec())

    def test_it_does_not_match_the_nearest_timestamp(self):
        series = marked_series()
        near = series.timestamps[1] - timedelta(seconds=1)
        with pytest.raises(EvaluationError):
            evaluate_observations(self._observations(series, timestamp=near), series, OutcomeSpec())

    def test_a_non_series_input_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="BarSeries"):
            evaluate_observations(self._observations(series), list(series.bars), OutcomeSpec())

    def test_duplicate_observation_timestamps_are_refused(self):
        """A repeat would be counted twice in every metric denominator."""
        series = marked_series()
        observations = make_observations(series, [BULLISH] * len(series))
        with pytest.raises(EvaluationError, match="repeats the timestamp"):
            evaluate_observations(observations + (observations[0],), series, OutcomeSpec())

    def test_observations_may_be_supplied_out_of_order(self):
        # Each record is independently correct; ordering is the caller's.
        series = marked_series()
        observations = make_observations(series, [BULLISH] * len(series))
        outcomes = evaluate_observations(tuple(reversed(observations)), series, OutcomeSpec())
        assert [o.observation_timestamp for o in outcomes] == [
            o.timestamp for o in reversed(observations)
        ]

    def test_a_non_observation_input_raises(self):
        series = marked_series()
        with pytest.raises(EvaluationError, match="ResearchObservation"):
            evaluate_observations(("not an observation",), series, OutcomeSpec())


class TestFixedDurationSpacingGuard:
    """Bars closer together than a fixed-duration interval allows are malformed."""

    def _hourly(self, minutes_apart):
        bars = [
            MarketBar("X", datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes_apart) * i,
                      100.0, 120.0, 80.0, 110.0, 1_000.0, "1h", "t")
            for i in range(4)
        ]
        return BarSeries.from_bars(bars, basis=PriceBasis.RAW)

    def test_overlapping_intraday_bars_are_rejected(self):
        series = self._hourly(30)  # "1h" bars 30 minutes apart
        with pytest.raises(EvaluationError, match="before the observation bar's period ends"):
            evaluate(series)

    def test_correctly_spaced_intraday_bars_pass(self):
        assert evaluate(self._hourly(60))[0].status is OutcomeStatus.EVALUATED

    def test_wider_intraday_spacing_passes(self):
        # A gap is legitimate; only closer-than-interval spacing is malformed.
        assert evaluate(self._hourly(180))[0].status is OutcomeStatus.EVALUATED

    def test_the_guard_is_not_applied_to_calendar_intervals(self):
        """1wk/1mo spacing legitimately varies; max_duration is an upper bound.

        A February monthly bar is 29 days before March, less than the 31-day
        max_duration. Applying the guard here would reject valid data.
        """
        bars = [
            MarketBar("X", datetime(2024, m, 1, tzinfo=UTC), 100.0, 120.0, 80.0, 110.0,
                      1_000.0, "1mo", "t")
            for m in (1, 2, 3, 4)
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        assert evaluate(series)[0].status is OutcomeStatus.EVALUATED

    def test_daily_bars_across_a_dst_shift_are_not_rejected(self):
        # Session-local midnight changes UTC offset at a DST transition, so
        # consecutive daily bars can be 23h apart in UTC.
        stamps = [
            datetime(2024, 3, 8, 5, tzinfo=UTC),
            datetime(2024, 3, 9, 4, tzinfo=UTC),  # 23 hours later
            datetime(2024, 3, 10, 4, tzinfo=UTC),
        ]
        bars = [
            MarketBar("X", ts, 100.0, 120.0, 80.0, 110.0, 1_000.0, "1d", "t")
            for ts in stamps
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        assert evaluate(series)[0].status is OutcomeStatus.EVALUATED


class TestEvaluableFromIsNotUsed:
    """Regression for the architecture review's R-2 finding."""

    def test_monthly_reference_is_the_next_bar_not_the_evaluable_from_bar(self):
        bars = [
            MarketBar("X", datetime(2024, m, 1, tzinfo=UTC), m * 100.0, m * 100.0 + 90,
                      m * 100.0 - 10, m * 100.0 + 50, 1_000.0, "1mo", "t")
            for m in (1, 2, 3, 4)
        ]
        series = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        observations = make_observations(series, [BULLISH] * len(series))

        february = observations[1]
        # evaluable_from = 1 Feb + 31 days = 3 March, which is AFTER the March bar.
        assert february.evaluable_from > series.timestamps[2]

        outcome = evaluate_observations(observations, series, OutcomeSpec())[1]
        # Correct: the March bar. Using evaluable_from would have skipped to April.
        assert outcome.reference_timestamp == series.timestamps[2]
        assert outcome.reference_price == 300.0
        assert outcome.reference_timestamp != series.timestamps[3]
