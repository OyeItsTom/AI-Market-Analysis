"""Corporate actions and the raw -> adjusted transformation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.data.adjustment import (
    AdjustmentData,
    AdjustmentError,
    adjust,
    factors_from_adjusted_close,
)
from src.data.corporate_actions import ActionType, CorporateAction, CorporateActionError
from src.data.series import BarSeries, PriceBasis
from tests.conftest import UTC, make_series

DAY = timedelta(days=1)


def raw_series(closes=(400.0, 408.0, 102.0)):
    return make_series(list(closes), symbol="AAPL", source="yfinance", basis=PriceBasis.RAW)


def factors_for(series, mapping):
    return AdjustmentData(
        symbol=series.symbol,
        source=series.source,
        interval=series.interval,
        produces_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
        factors={ts: mapping[i] for i, ts in enumerate(series.timestamps)},
    )


class TestCorporateAction:
    def test_a_split_records_its_ratio(self):
        action = CorporateAction("aapl", datetime(2020, 8, 31, tzinfo=UTC), "split", 4.0, "yfinance")
        assert action.symbol == "AAPL"
        assert action.action_type is ActionType.SPLIT
        assert action.value == 4.0

    @pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
    def test_malformed_values_are_rejected(self, value):
        with pytest.raises(CorporateActionError):
            CorporateAction("AAPL", datetime(2020, 8, 31, tzinfo=UTC), "split", value, "yf")

    def test_a_naive_effective_time_is_rejected(self):
        with pytest.raises(CorporateActionError, match="timezone-aware"):
            CorporateAction("AAPL", datetime(2020, 8, 31), "split", 4.0, "yf")

    def test_effective_time_is_normalised_to_utc(self):
        eastern = datetime(2020, 8, 31, 9, 30, tzinfo=timezone_eastern())
        action = CorporateAction("AAPL", eastern, "cash_dividend", 0.22, "yf")
        assert action.effective_time.utcoffset().total_seconds() == 0

    def test_an_unknown_action_type_is_rejected(self):
        with pytest.raises(ValueError):
            CorporateAction("AAPL", datetime(2020, 8, 31, tzinfo=UTC), "merger", 1.0, "yf")

    def test_empty_symbol_or_source_is_rejected(self):
        with pytest.raises(CorporateActionError):
            CorporateAction("  ", datetime(2020, 8, 31, tzinfo=UTC), "split", 4.0, "yf")
        with pytest.raises(CorporateActionError):
            CorporateAction("AAPL", datetime(2020, 8, 31, tzinfo=UTC), "split", 4.0, "  ")


def timezone_eastern():
    from datetime import timezone

    return timezone(timedelta(hours=-4))


class TestAdjustmentData:
    def test_it_rejects_a_raw_target_basis(self):
        with pytest.raises(AdjustmentError, match="derived basis"):
            AdjustmentData("AAPL", "yfinance", "1d", PriceBasis.RAW)

    @pytest.mark.parametrize("factor", [0.0, -1.0, float("nan"), float("inf")])
    def test_malformed_factors_are_rejected(self, factor):
        series = raw_series()
        with pytest.raises(AdjustmentError):
            AdjustmentData(
                "AAPL", "yfinance", "1d",
                PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
                {series.timestamps[0]: factor},
            )

    def test_a_naive_factor_timestamp_is_rejected(self):
        with pytest.raises(AdjustmentError, match="timezone-aware"):
            AdjustmentData(
                "AAPL", "yfinance", "1d",
                PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
                {datetime(2024, 1, 2): 1.0},
            )

    def test_actions_for_another_symbol_are_rejected(self):
        other = CorporateAction("MSFT", datetime(2024, 1, 2, tzinfo=UTC), "split", 2.0, "yfinance")
        with pytest.raises(AdjustmentError, match="does not belong"):
            AdjustmentData(
                "AAPL", "yfinance", "1d",
                PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED, {}, (other,),
            )

    def test_actions_from_another_source_are_rejected(self):
        other = CorporateAction("AAPL", datetime(2024, 1, 2, tzinfo=UTC), "split", 2.0, "alpaca")
        with pytest.raises(AdjustmentError, match="does not belong"):
            AdjustmentData(
                "AAPL", "yfinance", "1d",
                PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED, {}, (other,),
            )


class TestAdjust:
    def test_a_split_stops_looking_like_a_catastrophic_loss(self):
        # 4-for-1 split before the last bar: raw shows -75%, adjusted shows ~0%.
        raw = raw_series((400.0, 408.0, 102.0))
        assert raw[2].close / raw[1].close - 1 == pytest.approx(-0.75)

        adjusted = adjust(raw, factors_for(raw, [0.25, 0.25, 1.0]))
        assert adjusted.values("close") == (100.0, 102.0, 102.0)
        assert adjusted[2].close / adjusted[1].close - 1 == pytest.approx(0.0)

    def test_the_raw_series_is_not_modified(self):
        raw = raw_series()
        before = raw.values("close")
        adjust(raw, factors_for(raw, [0.25, 0.25, 1.0]))
        assert raw.values("close") == before
        assert raw.basis is PriceBasis.RAW

    def test_all_four_prices_are_scaled_by_the_same_factor(self):
        raw = make_series([100.0], opens=[90.0], highs=[110.0], lows=[80.0],
                          symbol="AAPL", source="yfinance")
        adjusted = adjust(raw, factors_for(raw, [0.5]))
        assert (adjusted[0].open, adjusted[0].high, adjusted[0].low, adjusted[0].close) == (
            45.0, 55.0, 40.0, 50.0,
        )

    def test_volume_is_never_adjusted(self):
        raw = make_series([100.0, 200.0], volumes=[1_000.0, 2_000.0],
                          symbol="AAPL", source="yfinance")
        adjusted = adjust(raw, factors_for(raw, [0.25, 1.0]))
        assert adjusted.values("volume") == (1_000.0, 2_000.0)

    def test_the_result_declares_its_derived_basis(self):
        raw = raw_series()
        adjusted = adjust(raw, factors_for(raw, [1.0, 1.0, 1.0]))
        assert adjusted.basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
        assert adjusted.basis.is_derived

    def test_provenance_records_how_it_was_derived(self):
        raw = raw_series()
        adjusted = adjust(raw, factors_for(raw, [1.0, 1.0, 1.0]))
        assert "derived from raw" in adjusted.provenance
        assert "volume left unadjusted" in adjusted.provenance

    def test_it_is_deterministic(self):
        raw = raw_series()
        data = factors_for(raw, [0.25, 0.25, 1.0])
        assert adjust(raw, data).values("close") == adjust(raw, data).values("close")

    def test_double_adjustment_is_refused(self):
        raw = raw_series()
        data = factors_for(raw, [0.25, 0.25, 1.0])
        adjusted = adjust(raw, data)
        with pytest.raises(AdjustmentError, match="already"):
            adjust(adjusted, data)

    def test_a_missing_factor_refuses_the_whole_series(self):
        raw = raw_series()
        partial = AdjustmentData(
            "AAPL", "yfinance", "1d",
            PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
            {raw.timestamps[0]: 0.25},  # bars 1 and 2 have no factor
        )
        with pytest.raises(AdjustmentError, match="no adjustment factor"):
            adjust(raw, partial)

    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [("symbol", "MSFT", "symbol"), ("source", "alpaca", "source"), ("interval", "1h", "interval")],
    )
    def test_mismatched_metadata_is_refused(self, field, value, expected):
        raw = raw_series()
        kwargs = {"symbol": "AAPL", "source": "yfinance", "interval": "1d"}
        kwargs[field] = value
        data = AdjustmentData(
            produces_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
            factors={ts: 1.0 for ts in raw.timestamps},
            **kwargs,
        )
        with pytest.raises(AdjustmentError, match=expected):
            adjust(raw, data)

    def test_a_non_series_input_is_refused(self):
        raw = raw_series()
        with pytest.raises(AdjustmentError, match="BarSeries"):
            adjust(list(raw.bars), factors_for(raw, [1.0, 1.0, 1.0]))


class TestFactorDerivation:
    def test_ratio_of_adjusted_to_raw_close(self):
        stamps = [datetime(2024, 1, day, tzinfo=UTC) for day in (2, 3)]
        factors = factors_from_adjusted_close(
            [(stamps[0], 400.0), (stamps[1], 408.0)],
            [(stamps[0], 100.0), (stamps[1], 102.0)],
        )
        assert factors == {stamps[0]: 0.25, stamps[1]: 0.25}

    def test_a_zero_raw_close_is_refused_not_infinite(self):
        stamp = datetime(2024, 1, 2, tzinfo=UTC)
        with pytest.raises(AdjustmentError, match="undefined"):
            factors_from_adjusted_close([(stamp, 0.0)], [(stamp, 100.0)])

    def test_mismatched_timestamps_are_refused(self):
        a = datetime(2024, 1, 2, tzinfo=UTC)
        b = datetime(2024, 1, 3, tzinfo=UTC)
        with pytest.raises(AdjustmentError, match="different timestamps"):
            factors_from_adjusted_close([(a, 100.0)], [(b, 100.0)])

    def test_a_missing_adjusted_close_yields_a_nan_free_refusal(self):
        stamp = datetime(2024, 1, 2, tzinfo=UTC)
        with pytest.raises(AdjustmentError):
            factors_from_adjusted_close([(stamp, 100.0)], [(stamp, float("nan"))])
