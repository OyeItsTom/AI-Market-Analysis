"""Tests for the yfinance adapter.

Every test injects a fake ``download_fn``; nothing here touches the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.data.models import Interval
from src.data.normalization import NormalizationError
from src.data.provider import ProviderUnavailableError
from src.data.providers.yahoo import YahooFinanceProvider
from src.data.series import PriceBasis
from tests.conftest import UTC

EASTERN = timezone(timedelta(hours=-5))
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 31, tzinfo=UTC)


def frame(index=None, rows=None, columns=("Open", "High", "Low", "Close", "Volume")):
    """Build a yfinance-shaped price-history DataFrame."""
    if index is None:
        index = pd.DatetimeIndex(
            [datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC)]
        )
    if rows is None:
        rows = [[100.0, 110.0, 95.0, 105.0, 1_000], [105.0, 115.0, 104.0, 112.0, 2_000]]
    return pd.DataFrame(rows, index=index, columns=list(columns))


def provider_returning(payload, **kwargs):
    calls: list[tuple] = []

    def fake_download(symbol, start, end, yf_interval):
        calls.append((symbol, start, end, yf_interval))
        return payload

    return YahooFinanceProvider(download_fn=fake_download, **kwargs), calls


class TestNormalization:
    def test_dataframe_becomes_market_bars(self):
        provider, _ = provider_returning(frame())
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert len(bars) == 2
        first = bars[0]
        assert first.symbol == "AAPL"
        assert first.source == "yfinance"
        assert first.interval is Interval.DAY_1
        assert (first.open, first.high, first.low, first.close, first.volume) == (
            100.0, 110.0, 95.0, 105.0, 1_000.0,
        )
        assert first.timestamp == datetime(2024, 1, 2, tzinfo=UTC)

    def test_lowercase_columns_are_accepted(self):
        provider, _ = provider_returning(frame(columns=("open", "high", "low", "close", "volume")))
        assert len(provider.get_bars("AAPL", START, END, "1d")) == 2

    def test_extra_vendor_columns_are_ignored(self):
        payload = frame()
        payload["Dividends"] = 0.0
        payload["Stock Splits"] = 0.0
        provider, _ = provider_returning(payload)
        assert len(provider.get_bars("AAPL", START, END, "1d")) == 2

    def test_multiindex_columns_from_yf_download_are_flattened(self):
        payload = frame()
        payload.columns = pd.MultiIndex.from_product([payload.columns, ["AAPL"]])
        provider, _ = provider_returning(payload)
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert [bar.close for bar in bars] == [105.0, 112.0]

    def test_non_utc_index_is_converted_to_utc(self):
        index = pd.DatetimeIndex(
            [datetime(2024, 1, 2, 9, 30, tzinfo=EASTERN), datetime(2024, 1, 3, 9, 30, tzinfo=EASTERN)]
        )
        provider, _ = provider_returning(frame(index=index))
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert bars[0].timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        assert bars[0].timestamp.tzinfo is timezone.utc

    def test_our_interval_is_translated_for_the_vendor(self):
        provider, calls = provider_returning(frame())
        provider.get_bars("aapl", START, END, Interval.HOUR_1)
        assert calls[0][0] == "AAPL"
        assert calls[0][3] == "1h"


class TestEmptyAndBadResponses:
    def test_empty_dataframe_returns_no_bars(self):
        provider, _ = provider_returning(pd.DataFrame())
        assert provider.get_bars("AAPL", START, END, "1d") == []

    def test_none_response_returns_no_bars(self):
        provider, _ = provider_returning(None)
        assert provider.get_bars("AAPL", START, END, "1d") == []

    def test_missing_ohlcv_column_raises(self):
        provider, _ = provider_returning(
            frame(rows=[[100.0, 110.0, 95.0, 105.0]] * 2, columns=("Open", "High", "Low", "Close"))
        )
        with pytest.raises(ProviderUnavailableError, match="volume"):
            provider.get_bars("AAPL", START, END, "1d")

    def test_unexpected_response_type_raises(self):
        provider, _ = provider_returning("<html>rate limited</html>")
        with pytest.raises(ProviderUnavailableError):
            provider.get_bars("AAPL", START, END, "1d")


class TestColumnCollisions:
    """Two columns normalizing to one field must fail, not be picked between."""

    def _collide(self, extra_name):
        payload = frame()
        payload[extra_name] = 1.23
        return payload

    @pytest.mark.parametrize("extra_name", ["close", "CLOSE", " Close "])
    def test_case_colliding_columns_are_refused(self, extra_name):
        provider, _ = provider_returning(self._collide(extra_name))
        with pytest.raises(ProviderUnavailableError, match="more than one 'close' column"):
            provider.get_bars("AAPL", START, END, "1d")

    def test_the_error_names_both_offending_columns(self):
        provider, _ = provider_returning(self._collide("close"))
        with pytest.raises(ProviderUnavailableError) as excinfo:
            provider.get_bars("AAPL", START, END, "1d")
        assert "'Close'" in str(excinfo.value) and "'close'" in str(excinfo.value)

    def test_a_collision_is_not_silently_resolved_to_either_value(self):
        # Both candidate values are plausible; validation would not catch the
        # wrong choice, so the adapter must refuse rather than guess.
        payload = frame()
        payload["close"] = 105.5  # as plausible as the real 105.0
        provider, _ = provider_returning(payload)
        with pytest.raises(ProviderUnavailableError):
            provider.get_bars("AAPL", START, END, "1d")


class TestTimestampConvention:
    def test_the_vendor_index_is_carried_through_as_bar_open_time(self):
        # yfinance indexes rows by bar open time, which is our canonical
        # convention, so it must pass through unshifted.
        index = pd.DatetimeIndex(
            [datetime(2024, 1, 2, 14, 30, tzinfo=UTC), datetime(2024, 1, 2, 15, 30, tzinfo=UTC)]
        )
        provider, _ = provider_returning(frame(index=index))
        bars = provider.get_bars("AAPL", START, END, "1h")
        assert [bar.timestamp for bar in bars] == list(index.to_pydatetime())

    def test_settlement_uses_the_open_time_plus_the_interval(self):
        index = pd.DatetimeIndex([datetime(2024, 1, 2, 15, 0, tzinfo=UTC)])
        rows = [[100.0, 110.0, 95.0, 105.0, 1_000]]
        provider, _ = provider_returning(frame(index=index, rows=rows))
        provider._now = lambda: datetime(2024, 1, 2, 15, 59, tzinfo=UTC)
        assert provider.get_bars("AAPL", START, END, "1h") == []
        provider._now = lambda: datetime(2024, 1, 2, 16, 0, tzinfo=UTC)
        assert len(provider.get_bars("AAPL", START, END, "1h")) == 1


class TestUnsettledBars:
    def test_the_forming_session_bar_is_withheld_by_default(self):
        index = pd.DatetimeIndex(
            [datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC)]
        )
        provider, _ = provider_returning(frame(index=index))
        provider._now = lambda: datetime(2024, 1, 3, 17, 0, tzinfo=UTC)  # mid-session
        bars = provider.get_bars("AAPL", START, datetime(2024, 1, 3, 17, 0, tzinfo=UTC), "1d")
        assert [bar.timestamp.day for bar in bars] == [2]

    def test_it_is_available_on_request(self):
        index = pd.DatetimeIndex(
            [datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC)]
        )
        provider, _ = provider_returning(frame(index=index))
        provider._now = lambda: datetime(2024, 1, 3, 17, 0, tzinfo=UTC)
        bars = provider.get_bars(
            "AAPL", START, datetime(2024, 1, 3, 17, 0, tzinfo=UTC), "1d", include_unsettled=True
        )
        assert [bar.timestamp.day for bar in bars] == [2, 3]


class TestAdjustmentDataCapture:
    """Corporate actions and adjustment factors come from the SAME response."""

    def _full_frame(self):
        index = pd.DatetimeIndex([datetime(2024, 1, day, tzinfo=UTC) for day in (2, 3, 4)])
        return pd.DataFrame(
            {
                "Open": [400.0, 404.0, 101.0],
                "High": [410.0, 412.0, 103.0],
                "Low": [396.0, 400.0, 100.0],
                "Close": [400.0, 408.0, 102.0],
                "Adj Close": [100.0, 102.0, 102.0],
                "Volume": [1_000.0, 1_100.0, 4_400.0],
                "Dividends": [0.0, 0.5, 0.0],
                "Stock Splits": [0.0, 0.0, 4.0],
            },
            index=index,
        )

    def test_only_one_request_is_made(self):
        provider, calls = provider_returning(self._full_frame())
        provider.get_adjustment_data("AAPL", START, END, "1d")
        assert len(calls) == 1

    def test_factors_are_adjusted_close_over_close(self):
        provider, _ = provider_returning(self._full_frame())
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert data.factors[datetime(2024, 1, 2, tzinfo=UTC)] == pytest.approx(0.25)
        assert data.factors[datetime(2024, 1, 4, tzinfo=UTC)] == pytest.approx(1.0)

    def test_the_basis_names_both_splits_and_dividends(self):
        provider, _ = provider_returning(self._full_frame())
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert data.produces_basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED

    def test_splits_and_dividends_are_captured_as_records(self):
        provider, _ = provider_returning(self._full_frame())
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        kinds = {(a.action_type.value, a.value) for a in data.actions}
        assert ("split", 4.0) in kinds
        assert ("cash_dividend", 0.5) in kinds

    def test_zero_action_values_are_not_recorded_as_events(self):
        provider, _ = provider_returning(self._full_frame())
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert len(data.actions) == 2  # not one per row

    def test_a_missing_adj_close_column_yields_no_factors_rather_than_guesses(self):
        frame_without = self._full_frame().drop(columns=["Adj Close"])
        provider, _ = provider_returning(frame_without)
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert data.factors == {}

    def test_a_nan_adj_close_is_skipped_not_defaulted_to_one(self):
        frame = self._full_frame()
        frame.loc[frame.index[1], "Adj Close"] = float("nan")
        provider, _ = provider_returning(frame)
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert datetime(2024, 1, 3, tzinfo=UTC) not in data.factors
        assert len(data.factors) == 2

    def test_a_zero_close_does_not_produce_an_infinite_factor(self):
        frame = self._full_frame()
        frame.loc[frame.index[0], "Close"] = 0.0
        provider, _ = provider_returning(frame)
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert datetime(2024, 1, 2, tzinfo=UTC) not in data.factors

    def test_an_empty_response_yields_empty_adjustment_data(self):
        provider, _ = provider_returning(pd.DataFrame())
        data = provider.get_adjustment_data("AAPL", START, END, "1d")
        assert data.factors == {} and data.actions == ()

    def test_the_raw_bar_path_is_unaffected_by_the_extra_columns(self):
        # MarketBar keeps its Phase 1 meaning: raw OHLC, no action fields.
        provider, _ = provider_returning(self._full_frame())
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert [bar.close for bar in bars] == [400.0, 408.0, 102.0]  # RAW, not adjusted
        assert not hasattr(bars[0], "dividends")
        assert not hasattr(bars[0], "basis")


class TestPriceAdjustment:
    def test_the_adapter_requests_raw_unadjusted_prices(self):
        # V4: the documented methodology must match the code. If this changes,
        # the corporate-action caveats in the docstring must change with it.
        import inspect

        from src.data.providers import yahoo

        source = inspect.getsource(yahoo._default_download)
        assert "auto_adjust=False" in source          # raw OHLC preserved
        assert "actions=True" in source               # actions captured, not discarded
        assert "unadjusted" in (yahoo.YahooFinanceProvider.__doc__ or "").lower()

    def test_adj_close_is_not_consumed(self):
        payload = frame()
        payload["Adj Close"] = 42.0  # present in the vendor response, ignored by us
        provider, _ = provider_returning(payload)
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert [bar.close for bar in bars] == [105.0, 112.0]


class TestTimezoneHandling:
    def _naive_frame(self):
        return frame(index=pd.DatetimeIndex([datetime(2024, 1, 2), datetime(2024, 1, 3)]))

    def test_naive_index_is_refused_rather_than_guessed(self):
        provider, _ = provider_returning(self._naive_frame())
        with pytest.raises(NormalizationError, match="timezone-naive"):
            provider.get_bars("AAPL", START, END, "1d")

    def test_naive_index_is_localized_when_configured_explicitly(self):
        provider, _ = provider_returning(self._naive_frame(), assume_timezone=EASTERN)
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert bars[0].timestamp == datetime(2024, 1, 2, 5, 0, tzinfo=UTC)


class TestMissingData:
    def _frame_with_nan(self):
        return frame(rows=[[100.0, 110.0, 95.0, 105.0, 1_000], [None, None, None, None, None]])

    def test_nan_rows_raise_by_default(self):
        provider, _ = provider_returning(self._frame_with_nan())
        with pytest.raises(NormalizationError):
            provider.get_bars("AAPL", START, END, "1d")

    def test_nan_rows_can_be_dropped_never_filled(self):
        provider, _ = provider_returning(self._frame_with_nan(), skip_incomplete_rows=True)
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert len(bars) == 1
        assert bars[0].close == 105.0


class TestWindowClipping:
    def test_bars_outside_the_requested_window_are_dropped(self):
        index = pd.DatetimeIndex(
            [
                datetime(2023, 12, 29, tzinfo=UTC),  # before start
                datetime(2024, 1, 2, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),  # after end
            ]
        )
        rows = [[100.0, 110.0, 95.0, 105.0, 1_000]] * 3
        provider, _ = provider_returning(frame(index=index, rows=rows))
        bars = provider.get_bars("AAPL", START, END, "1d")
        assert [bar.timestamp for bar in bars] == [datetime(2024, 1, 2, tzinfo=UTC)]


class TestProviderMetadata:
    def test_declares_its_name_and_supported_intervals(self):
        provider = YahooFinanceProvider()
        assert provider.name == "yfinance"
        assert Interval.DAY_1 in provider.supported_intervals

    def test_the_adapter_maps_our_interval_onto_the_vendor_vocabulary(self):
        provider, calls = provider_returning(frame())
        provider.get_bars("AAPL", START, END, Interval.MINUTE_15)
        assert calls[0][3] == "15m"
