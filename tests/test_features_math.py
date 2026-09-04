"""Mathematical correctness against HAND-COMPUTED fixtures.

Expected values here are derived by hand from the documented conventions, not
by running another copy of the same code. Where a published reference exists
(Wilder's RSI example) it is discussed in the relevant test.
"""

from __future__ import annotations

import math

import pytest

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
from tests.conftest import make_series

TOL = 1e-12  # exact arithmetic on small integers; loosened only where stated


class TestSimpleReturn:
    def test_hand_computed(self):
        # 100 -> 110 is +10%; 110 -> 99 is -10%.
        values = simple_return(make_series([100.0, 110.0, 99.0])).values
        assert values[0] is None
        assert values[1] == pytest.approx(0.10, abs=TOL)
        assert values[2] == pytest.approx(-0.10, abs=TOL)

    def test_constant_prices_give_zero(self):
        values = simple_return(make_series([5.0] * 4)).values
        assert values[1:] == (0.0, 0.0, 0.0)

    def test_first_bar_has_no_return(self):
        assert simple_return(make_series([1.0])).values == (None,)


class TestLogReturn:
    def test_hand_computed(self):
        # ln(2) for a doubling, -ln(2) for a halving.
        values = log_return(make_series([1.0, 2.0, 1.0])).values
        assert values[1] == pytest.approx(math.log(2), abs=TOL)
        assert values[2] == pytest.approx(-math.log(2), abs=TOL)

    def test_log_returns_are_additive_where_simple_returns_are_not(self):
        series = make_series([100.0, 110.0, 121.0])
        logs = [value for value in log_return(series).values if value is not None]
        assert sum(logs) == pytest.approx(math.log(1.21), abs=1e-12)


class TestSMA:
    def test_hand_computed(self):
        # windows: (1,2,3)->2, (2,3,4)->3, (3,4,5)->4
        assert sma(make_series([1.0, 2.0, 3.0, 4.0, 5.0]), 3).values == (None, None, 2.0, 3.0, 4.0)

    def test_period_one_is_the_price_itself(self):
        assert sma(make_series([3.0, 7.0]), 1).values == (3.0, 7.0)

    def test_constant_prices_give_the_constant(self):
        assert sma(make_series([4.0] * 5), 3).values[2:] == (4.0, 4.0, 4.0)

    def test_the_window_is_never_shortened_to_produce_an_early_value(self):
        assert sma(make_series([1.0, 2.0]), 5).values == (None, None)

    def test_rolling_sum_does_not_drift_on_large_values(self):
        # Guards the incremental add/subtract implementation.
        large = [1e12 + index for index in range(6)]
        assert sma(make_series(large), 3).values[-1] == pytest.approx(
            sum(large[3:6]) / 3, rel=1e-15
        )


class TestEMA:
    def test_hand_computed(self):
        # period 3 -> alpha = 0.5; seed = mean(1,2,3) = 2.0 at index 2
        # idx3 = 0.5*4 + 0.5*2 = 3.0 ; idx4 = 0.5*5 + 0.5*3 = 4.0
        assert ema(make_series([1.0, 2.0, 3.0, 4.0, 5.0]), 3).values == (None, None, 2.0, 3.0, 4.0)

    def test_seed_is_the_simple_average_not_the_first_price(self):
        # If it seeded from price[0]=1.0 the value at index 2 would be 2.25.
        assert ema(make_series([1.0, 2.0, 3.0]), 3).values[2] == 2.0

    def test_constant_prices_stay_constant(self):
        assert ema(make_series([7.0] * 6), 3).values[2:] == (7.0, 7.0, 7.0, 7.0)

    def test_too_short_a_series_is_all_warm_up(self):
        assert ema(make_series([1.0, 2.0]), 3).values == (None, None)


class TestRSI:
    def test_hand_computed_small_case(self):
        # closes 10, 11, 10, 12 with period 2. changes: +1, -1, +2
        #   seed at idx2: avg_gain=(1+0)/2=0.5  avg_loss=(0+1)/2=0.5  RS=1  -> 50
        #   idx3: avg_gain=(0.5*1+2)/2=1.25  avg_loss=(0.5*1+0)/2=0.25  RS=5 -> 100-100/6
        values = rsi(make_series([10.0, 11.0, 10.0, 12.0]), 2).values
        assert values[:2] == (None, None)
        assert values[2] == pytest.approx(50.0, abs=TOL)
        assert values[3] == pytest.approx(100.0 - 100.0 / 6.0, abs=1e-10)

    def test_monotonic_rise_pins_at_100(self):
        assert rsi(make_series([float(index) for index in range(1, 8)]), 3).values[-1] == 100.0

    def test_monotonic_fall_pins_at_0(self):
        assert rsi(make_series([float(index) for index in range(9, 2, -1)]), 3).values[-1] == 0.0

    def test_flat_prices_give_the_documented_neutral_value(self):
        # RSI is genuinely undefined (0/0) here; 50.0 is our documented choice.
        assert rsi(make_series([5.0] * 8), 3).values[-1] == 50.0

    def test_first_value_needs_period_changes(self):
        # period changes require period+1 closes, so the first index is `period`.
        assert rsi(make_series([1.0, 2.0, 3.0]), 2).ready_from == 2
        assert rsi(make_series([1.0, 2.0]), 2).ready_from is None

    def test_wilder_smoothing_is_not_a_standard_ema(self):
        # Wilder uses alpha = 1/p. A 2/(p+1) EMA would give a different number;
        # this pins the convention documented in src/features/momentum.py.
        values = rsi(make_series([10.0, 11.0, 10.0, 12.0, 11.0]), 2).values
        # idx4: gain=0 loss=1 -> avg_gain=(1.25*1+0)/2=0.625, avg_loss=(0.25*1+1)/2=0.625
        assert values[4] == pytest.approx(50.0, abs=1e-10)

    def test_against_wilders_published_example_within_documented_tolerance(self):
        """Wilder's canonical dataset.

        The widely reproduced table shows 70.53 for the first value. Our exact
        arithmetic on the published (2dp) closes gives 70.4641: the table's own
        displayed averages (0.2382/0.0993) are not reproducible from its
        displayed closes (which give 0.2386/0.1000), so the difference is in
        the reference data, not the formula. We therefore assert only a loose
        agreement and rely on the exact hand-computed cases above.
        """
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
                  46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        assert rsi(make_series(closes), 14).values[14] == pytest.approx(70.5, abs=0.1)


class TestRealizedVolatility:
    def test_constant_prices_give_zero(self):
        assert realized_volatility(make_series([10.0] * 6), 3).values[-1] == pytest.approx(0.0)

    def test_hand_computed_sample_standard_deviation(self):
        # closes 1,2,4,8 -> log returns all ln2. sd of identical values = 0.
        assert realized_volatility(make_series([1.0, 2.0, 4.0, 8.0]), 3).values[3] == pytest.approx(
            0.0, abs=1e-12
        )

    def test_uses_sample_ddof_one(self):
        # returns: ln2, -ln2  -> mean 0, sample sd = sqrt(2*ln2^2/1) = ln2*sqrt(2)
        value = realized_volatility(make_series([1.0, 2.0, 1.0]), 2).values[2]
        assert value == pytest.approx(math.log(2) * math.sqrt(2), abs=1e-12)

    def test_period_below_two_is_rejected(self):
        from src.features.base import FeatureError

        with pytest.raises(FeatureError, match=">= 2"):
            realized_volatility(make_series([1.0, 2.0, 3.0]), 1)

    def test_result_is_not_annualised(self):
        # A 2x daily move must not be silently scaled by sqrt(252).
        value = realized_volatility(make_series([1.0, 2.0, 1.0]), 2).values[2]
        assert value < 1.5


class TestATR:
    def test_hand_computed(self):
        # H=[10,11,12] L=[8,9,10] C=[9,10,11]
        # TR0 = 10-8 = 2 (no previous close)
        # TR1 = max(11-9, |11-9|, |9-9|) = 2 ; TR2 = max(2, 2, 0) = 2
        # ATR(3) at idx2 = mean(2,2,2) = 2
        series = make_series([9.0, 10.0, 11.0], highs=[10.0, 11.0, 12.0], lows=[8.0, 9.0, 10.0])
        assert atr(series, 3).values == (None, None, 2.0)

    def test_true_range_captures_a_gap_beyond_the_bars_own_span(self):
        # Bar 1 spans 20..21 but the previous close was 10: TR must be 11, not 1.
        series = make_series([10.0, 20.5], opens=[10.0, 20.0], highs=[10.0, 21.0], lows=[10.0, 20.0])
        assert atr(series, 2).values[1] == pytest.approx((0.0 + 11.0) / 2)

    def test_wilder_smoothing_after_the_seed(self):
        # TRs all 2 for three bars, then a bar with TR 6:
        # ATR3 = 2 ; ATR4 = (2*(3-1) + 6)/3 = 10/3
        series = make_series(
            [9.0, 10.0, 11.0, 14.0],
            highs=[10.0, 11.0, 12.0, 16.0],
            lows=[8.0, 9.0, 10.0, 10.0],
        )
        values = atr(series, 3).values
        assert values[2] == pytest.approx(2.0)
        assert values[3] == pytest.approx((2.0 * 2 + max(6.0, 5.0, 1.0)) / 3)

    def test_zero_range_bars_give_zero(self):
        assert atr(make_series([5.0] * 4), 2).values[-1] == 0.0


class TestVolume:
    def test_average_volume_hand_computed(self):
        series = make_series([1.0] * 4, volumes=[10.0, 20.0, 30.0, 40.0])
        assert average_volume(series, 2).values == (None, 15.0, 25.0, 35.0)

    def test_relative_volume_hand_computed(self):
        # window (10,20) -> avg 15 ; 20/15 = 4/3
        series = make_series([1.0] * 3, volumes=[10.0, 20.0, 30.0])
        values = relative_volume(series, 2).values
        assert values[1] == pytest.approx(20.0 / 15.0)
        assert values[2] == pytest.approx(30.0 / 25.0)

    def test_zero_average_volume_is_undefined_not_zero_or_one(self):
        series = make_series([1.0] * 3, volumes=[0.0, 0.0, 0.0])
        assert relative_volume(series, 2).values == (None, None, None)

    def test_a_single_zero_volume_bar_still_yields_a_ratio(self):
        series = make_series([1.0] * 3, volumes=[0.0, 10.0, 10.0])
        assert relative_volume(series, 2).values[1] == pytest.approx(10.0 / 5.0)
