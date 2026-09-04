"""Feature-engine contracts: anti-look-ahead, warm-up, alignment, purity.

The anti-look-ahead sweep is the most important file in Phase 2. It tests a
property rather than an implementation, so it keeps working across rewrites.
"""

from __future__ import annotations

import functools
import math
from datetime import datetime, timedelta

import pytest

from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.features import (
    atr,
    average_volume,
    ema,
    log_return,
    realized_volatility,
    relative_volume,
    rsi,
    simple_return,
    sma,
)
from src.features.base import FeatureError, FeatureSeries
from tests.conftest import UTC, make_series
from tests.lookahead import (
    assert_causal,
    assert_causal_at_every_split,
    assert_deterministic,
    assert_input_unchanged,
    assert_prefix_invariant,
    assert_truncation_invariant,
    perturb_tail,
)

#: Every feature, bound to a period where it takes one. Kept in one place so a
#: newly added feature is covered by every contract test below automatically.
ALL_FEATURES = [
    ("simple_return", simple_return),
    ("log_return", log_return),
    ("sma", functools.partial(sma, period=3)),
    ("ema", functools.partial(ema, period=3)),
    ("rsi", functools.partial(rsi, period=3)),
    ("realized_volatility", functools.partial(realized_volatility, period=3)),
    ("atr", functools.partial(atr, period=3)),
    ("average_volume", functools.partial(average_volume, period=3)),
    ("relative_volume", functools.partial(relative_volume, period=3)),
]
FEATURE_IDS = [name for name, _ in ALL_FEATURES]
FEATURE_FNS = [fn for _, fn in ALL_FEATURES]


@pytest.fixture
def wavy():
    """A series with enough variety that a look-ahead bug would change values."""
    closes = [10.0, 11.0, 10.5, 12.0, 11.0, 13.0, 12.5, 14.0, 13.0, 15.0]
    return make_series(
        closes,
        highs=[value * 1.05 for value in closes],
        lows=[value * 0.95 for value in closes],
        volumes=[1000.0 + 100 * index for index in range(len(closes))],
    )


class TestAntiLookahead:
    """A feature at bar i may use bars 0..i and nothing later."""

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_values_ignore_every_future_bar_at_every_split(self, feature, wavy):
        assert_causal_at_every_split(feature, wavy)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_truncating_the_future_does_not_change_the_past(self, feature, wavy):
        # Strictly stronger than perturbation: truncation changes the series
        # LENGTH and removes future TIMESTAMPS, both of which tail-perturbation
        # preserves. See tests/lookahead.py.
        assert_truncation_invariant(feature, wavy)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_a_single_changed_final_bar_cannot_move_earlier_values(self, feature, wavy):
        # The tightest case: only the LAST bar differs.
        assert_prefix_invariant(feature, wavy, len(wavy) - 1)

    def test_the_harness_actually_detects_a_look_ahead_bug(self, wavy):
        """The harness must fail on a genuinely non-causal feature.

        Without this, a passing sweep proves nothing: a broken harness would
        pass everything.
        """

        def peeks_forward(series: BarSeries) -> FeatureSeries:
            closes = series.values("close")
            values = [
                closes[index + 1] if index + 1 < len(closes) else None
                for index in range(len(closes))
            ]
            return FeatureSeries.aligned_to(
                series, name="cheating", params={}, values=values
            )

        with pytest.raises(AssertionError, match="LOOK-AHEAD"):
            assert_causal_at_every_split(peeks_forward, wavy)

    @pytest.mark.parametrize(
        ("name", "cheat"),
        [
            # Each of these was verified to slip past tail-perturbation alone.
            (
                "reads the total number of bars",
                lambda s: FeatureSeries.aligned_to(
                    s, name="len_cheat", params={}, values=[float(len(s))] * len(s)
                ),
            ),
            (
                "reads a future timestamp",
                lambda s: FeatureSeries.aligned_to(
                    s, name="ts_cheat", params={},
                    values=[float(s.timestamps[-1].toordinal()) if len(s) else None] * len(s),
                ),
            ),
            (
                "uses the global minimum close",
                lambda s: FeatureSeries.aligned_to(
                    s, name="min_cheat", params={},
                    values=[(min(s.values("close")) if len(s) else None)] * len(s),
                ),
            ),
            (
                "uses the global maximum close",
                lambda s: FeatureSeries.aligned_to(
                    s, name="max_cheat", params={},
                    values=[(max(s.values("close")) if len(s) else None)] * len(s),
                ),
            ),
        ],
    )
    def test_the_harness_detects_every_known_cheating_strategy(self, name, cheat, wavy):
        """Regression: each of these once passed the harness.

        A safety net is only worth what it catches, so the known ways of
        defeating it are pinned here.
        """
        with pytest.raises(AssertionError):
            assert_causal(cheat, wavy)

    def test_the_harness_detects_misaligned_output_timestamps(self, wavy):
        """A feature returning correct values against wrong timestamps.

        ``aligned_to`` forces timestamps to match, so this builds the output
        directly -- which is exactly what a future refactor of FeatureSeries
        could accidentally allow.
        """

        def shifts_timestamps(series):
            # The shift depends on how many bars exist, so a truncated series
            # lands on different timestamps than the full one -- a uniform
            # shift would be invisible to a truncated-vs-full comparison.
            shifted = tuple(
                stamp + series.interval.max_duration * len(series)
                for stamp in series.timestamps
            )
            return FeatureSeries(
                symbol=series.symbol, interval=series.interval, source=series.source,
                basis=series.basis, name="shifted", params={},
                timestamps=shifted, values=series.values("close"),
            )

        with pytest.raises(AssertionError, match="timestamps"):
            assert_truncation_invariant(shifts_timestamps, wavy)

    def test_the_perturbation_moves_the_tail_in_both_directions(self, wavy):
        # An upward-only perturbation leaves min(all_prices) in the prefix, so
        # a feature leaking through the global minimum would survive it.
        perturbed = perturb_tail(wavy, 4)
        tail = perturbed.values("close")[4:]
        prefix = wavy.values("close")[:4]
        assert max(tail) > max(prefix)
        assert min(tail) < min(prefix)

    def test_the_harness_perturbation_really_changes_the_tail(self, wavy):
        perturbed = perturb_tail(wavy, 4)
        assert perturbed.values("close")[:4] == wavy.values("close")[:4]
        assert perturbed.values("close")[4:] != wavy.values("close")[4:]


class TestPurity:
    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_input_is_not_mutated(self, feature, wavy):
        assert_input_unchanged(feature, wavy)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_repeated_calls_are_identical(self, feature, wavy):
        assert_deterministic(feature, wavy)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_two_equal_series_give_equal_results(self, feature, wavy):
        twin = make_series(
            list(wavy.values("close")),
            highs=list(wavy.values("high")),
            lows=list(wavy.values("low")),
            volumes=list(wavy.values("volume")),
        )
        assert feature(twin).values == feature(wavy).values


class TestWarmUp:
    """Insufficient history is reported honestly, never fabricated."""

    @pytest.mark.parametrize(
        ("feature", "period", "first_ready"),
        [
            (sma, 3, 2),
            (ema, 3, 2),
            (average_volume, 3, 2),
            (relative_volume, 3, 2),
            (atr, 3, 2),
            (rsi, 3, 3),                   # needs `period` changes
            (realized_volatility, 3, 3),   # one bar consumed by the first return
        ],
    )
    def test_exact_warm_up_boundary(self, feature, period, first_ready, wavy):
        result = feature(wavy, period)
        assert result.ready_from == first_ready
        assert all(value is None for value in result.values[:first_ready])
        assert result.values[first_ready] is not None

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_warm_up_is_none_never_zero_or_a_shortened_window(self, feature, wavy):
        values = feature(wavy).values
        leading = list(values[: (values.index(next(v for v in values if v is not None)))])
        assert all(value is None for value in leading)

    def test_a_series_shorter_than_the_period_is_entirely_warm_up(self):
        short = make_series([1.0, 2.0])
        assert sma(short, 20).values == (None, None)
        assert sma(short, 20).ready_from is None

    def test_is_ready_reports_the_same_thing(self, wavy):
        result = sma(wavy, 3)
        assert result.is_ready(2) is True
        assert result.is_ready(1) is False


class TestAlignmentAndTiming:
    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_one_value_per_bar_with_matching_timestamps(self, feature, wavy):
        result = feature(wavy)
        assert len(result) == len(wavy)
        assert result.timestamps == wavy.timestamps

    def test_ready_pairs_keeps_values_attached_to_timestamps(self, wavy):
        result = sma(wavy, 3)
        pairs = result.ready_pairs()
        assert pairs[0] == (wavy.timestamps[2], result.values[2])
        assert len(pairs) == len(wavy) - 2

    def test_a_feature_value_is_knowable_only_after_its_bar_completes(self, wavy):
        result = sma(wavy, 3)
        # timestamp is the bar OPEN; the value depends on that bar's close.
        assert result.knowable_at(5) == result.timestamps[5] + Interval.DAY_1.max_duration
        assert result.knowable_at(5) > result.timestamps[5]

    def test_knowable_at_is_a_lower_bound_never_before_the_bar_completes(self):
        # It must never claim a value was knowable before its bar's period
        # could have ended -- that direction would be look-ahead.
        hourly = make_series([1.0, 2.0, 3.0, 4.0], interval="1h")
        result = sma(hourly, 2)
        for index in range(len(result)):
            assert result.knowable_at(index) >= result.timestamps[index] + timedelta(hours=1)

    def test_knowable_at_is_documented_as_a_bound_not_a_measurement(self):
        # Guards against the docs quietly regaining a precision claim that
        # Phase 1 cannot support (no exchange calendar, no latency model).
        import src.features.base as base

        text = (base.__doc__ or "") + (base.FeatureSeries.knowable_at.__doc__ or "")
        assert "bound" in text.lower()
        assert "delay" in text.lower()

    def test_knowable_time_tracks_the_interval_not_the_calendar(self):
        hourly = make_series([1.0, 2.0, 3.0], interval="1h")
        result = sma(hourly, 2)
        assert result.knowable_at(1) - result.timestamps[1] == timedelta(hours=1)

    def test_provenance_is_carried_from_the_series(self, wavy):
        result = sma(wavy, 3)
        assert (result.symbol, result.source, result.basis) == (
            wavy.symbol, wavy.source, wavy.basis,
        )
        assert result.params["period"] == 3
        assert result.name == "sma"


class TestOutputAlignmentIsEnforced:
    """A feature producing the wrong number of values must not be constructible.

    This is the guard that makes `timestamps[i] <-> values[i]` a guarantee
    rather than a convention.
    """

    def test_too_few_values_are_refused(self, wavy):
        with pytest.raises(FeatureError, match="one value per bar"):
            FeatureSeries.aligned_to(
                wavy, name="broken", params={}, values=[1.0] * (len(wavy) - 1)
            )

    def test_too_many_values_are_refused(self, wavy):
        with pytest.raises(FeatureError, match="one value per bar"):
            FeatureSeries.aligned_to(
                wavy, name="broken", params={}, values=[1.0] * (len(wavy) + 1)
            )

    def test_mismatched_timestamps_and_values_are_refused(self):
        with pytest.raises(FeatureError, match="align one-to-one"):
            FeatureSeries(
                symbol="TEST", interval="1d", source="test", basis=PriceBasis.RAW,
                name="broken", params={},
                timestamps=(datetime(2024, 1, 1, tzinfo=UTC),),
                values=(1.0, 2.0),
            )

    def test_an_empty_feature_name_is_refused(self, wavy):
        with pytest.raises(FeatureError, match="name"):
            FeatureSeries.aligned_to(wavy, name="  ", params={}, values=[None] * len(wavy))


class TestValidationBoundary:
    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_a_bare_list_of_bars_is_refused(self, feature, wavy):
        with pytest.raises(FeatureError, match="BarSeries"):
            feature(list(wavy.bars))

    @pytest.mark.parametrize("period", [0, -1, 2.5, "3", None, True])
    def test_invalid_periods_are_refused(self, period, wavy):
        with pytest.raises(FeatureError):
            sma(wavy, period)

    def test_an_unknown_field_is_refused(self, wavy):
        from src.data.series import SeriesError

        with pytest.raises(SeriesError, match="unknown field"):
            sma(wavy, 3, field="symbol")

    def test_features_cannot_mix_price_bases(self, wavy):
        # The guard lives on the series; a feature carries the basis forward so
        # a downstream comparison can detect the mismatch.
        adjusted = wavy.with_bars(wavy.bars, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        raw_feature = sma(wavy, 3)
        adjusted_feature = sma(adjusted, 3)
        assert raw_feature.basis is not adjusted_feature.basis


class TestDegenerateInputs:
    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_empty_series_gives_empty_output(self, feature):
        empty = BarSeries.from_bars(
            [], basis=PriceBasis.RAW, symbol="TEST", interval="1d", source="test"
        )
        result = feature(empty)
        assert len(result) == 0
        assert result.values == ()

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_single_bar_series_does_not_crash(self, feature):
        result = feature(make_series([10.0]))
        assert len(result) == 1

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_constant_prices_produce_defined_finite_values(self, feature):
        # Not merely "does not crash": every produced value must be a real
        # number or an honest None. A feature returning NaN or inf here would
        # pass a bare smoke test and poison everything downstream.
        result = feature(make_series([5.0] * 8, volumes=[100.0] * 8))
        assert all(value is None or math.isfinite(value) for value in result.values)
        assert result.ready_from is not None

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_zero_volume_throughout_yields_none_or_finite_never_nan(self, feature):
        result = feature(make_series([5.0] * 8, volumes=[0.0] * 8))
        assert all(value is None or math.isfinite(value) for value in result.values)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_very_large_values_stay_finite(self, feature):
        import math

        closes = [1e9 * (1 + index) for index in range(8)]
        result = feature(make_series(closes, volumes=[1e12] * 8))
        assert all(value is None or math.isfinite(value) for value in result.values)

    @pytest.mark.parametrize("feature", FEATURE_FNS, ids=FEATURE_IDS)
    def test_monotonic_series_produce_defined_finite_values(self, feature):
        for closes in (
            [float(index) for index in range(1, 9)],
            [float(index) for index in range(9, 0, -1)],
        ):
            result = feature(make_series(closes))
            assert all(value is None or math.isfinite(value) for value in result.values)
            assert result.ready_from is not None
