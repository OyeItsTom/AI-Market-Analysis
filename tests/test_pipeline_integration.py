"""End-to-end check of the Phase 1 pipeline, entirely offline.

provider -> normalization -> validation -> storage -> read back
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.data import CsvBarStore, Interval, SeriesKey
from src.data.providers.yahoo import YahooFinanceProvider
from tests.conftest import UTC

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 31, tzinfo=UTC)


def fake_yfinance_response(symbol, start, end, yf_interval):
    index = pd.DatetimeIndex(
        [datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC)]
    )
    rows = [
        [187.15, 188.44, 183.89, 185.64, 82_488_700],
        [184.22, 185.88, 183.43, 184.25, 58_414_500],
        [182.15, 183.09, 180.88, 181.91, 71_983_600],
    ]
    return pd.DataFrame(rows, index=index, columns=["Open", "High", "Low", "Close", "Volume"])


def test_fetch_store_and_reload_a_series(tmp_path):
    provider = YahooFinanceProvider(download_fn=fake_yfinance_response)
    store = CsvBarStore(root=tmp_path / "raw")

    bars = provider.get_bars("aapl", START, END, "1d")
    assert len(bars) == 3
    assert {bar.source for bar in bars} == {"yfinance"}

    path = store.write(bars)
    assert path.is_file()

    key = SeriesKey("AAPL", Interval.DAY_1, "yfinance")
    assert store.read(key) == bars
    assert store.list_series() == [key]


def test_a_second_fetch_of_the_same_window_is_idempotent(tmp_path):
    provider = YahooFinanceProvider(download_fn=fake_yfinance_response)
    store = CsvBarStore(root=tmp_path / "raw")

    bars = provider.get_bars("AAPL", START, END, "1d")
    store.write(bars)
    store.merge(provider.get_bars("AAPL", START, END, "1d"))

    assert store.read(SeriesKey("AAPL", Interval.DAY_1, "yfinance")) == bars


def test_downstream_code_never_sees_vendor_types(tmp_path):
    provider = YahooFinanceProvider(download_fn=fake_yfinance_response)
    bars = provider.get_bars("AAPL", START, END, "1d")
    # No DataFrames, Timestamps or vendor column names escape the adapter.
    assert all(type(bar).__name__ == "MarketBar" for bar in bars)
    assert all(type(bar.timestamp).__name__ == "datetime" for bar in bars)
    assert all(isinstance(bar.close, float) for bar in bars)


# --------------------------------------------------------------------------
# Phase 2: raw -> adjusted -> features, end to end, offline
# --------------------------------------------------------------------------


def split_response(symbol, start, end, yf_interval):
    """A 4-for-1 split between the 3rd and 4th bar, with a dividend."""
    index = pd.DatetimeIndex([datetime(2024, 1, day, tzinfo=UTC) for day in (2, 3, 4, 5)])
    return pd.DataFrame(
        {
            "Open": [400.0, 404.0, 408.0, 101.0],
            "High": [410.0, 412.0, 416.0, 103.0],
            "Low": [396.0, 400.0, 404.0, 100.0],
            "Close": [400.0, 408.0, 412.0, 103.0],
            "Adj Close": [100.0, 102.0, 103.0, 103.0],
            "Volume": [1_000.0, 1_100.0, 1_200.0, 4_800.0],
            "Dividends": [0.0, 0.0, 0.25, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0, 4.0],
        },
        index=index,
    )


def _provider():
    from src.data.providers.yahoo import YahooFinanceProvider

    provider = YahooFinanceProvider(download_fn=split_response)
    provider._now = lambda: datetime(2024, 2, 1, tzinfo=UTC)
    return provider


def test_raw_returns_show_the_split_artefact_and_adjusted_ones_do_not():
    from src.data.adjustment import adjust
    from src.data.series import BarSeries, PriceBasis
    from src.features import simple_return

    provider = _provider()
    window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 31, tzinfo=UTC))

    raw = BarSeries.from_bars(provider.get_bars("AAPL", *window, "1d"), basis=PriceBasis.RAW)
    raw_returns = simple_return(raw).values
    assert raw_returns[3] == pytest.approx(-0.75, abs=0.01)  # the mechanical artefact

    adjusted = adjust(raw, provider.get_adjustment_data("AAPL", *window, "1d"))
    adjusted_returns = simple_return(adjusted).values
    assert adjusted_returns[3] == pytest.approx(0.0, abs=1e-9)  # economic reality

    # The raw series is untouched and still available as the source of record.
    assert raw.values("close") == (400.0, 408.0, 412.0, 103.0)
    assert raw.basis is PriceBasis.RAW


def test_features_carry_the_price_basis_so_a_mix_is_detectable():
    from src.data.adjustment import adjust
    from src.data.series import BarSeries, PriceBasis
    from src.features import sma

    provider = _provider()
    window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 31, tzinfo=UTC))
    raw = BarSeries.from_bars(provider.get_bars("AAPL", *window, "1d"), basis=PriceBasis.RAW)
    adjusted = adjust(raw, provider.get_adjustment_data("AAPL", *window, "1d"))

    assert sma(raw, 2).basis is PriceBasis.RAW
    assert sma(adjusted, 2).basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED


def test_volume_is_identical_in_raw_and_adjusted_series():
    from src.data.adjustment import adjust
    from src.data.series import BarSeries, PriceBasis

    provider = _provider()
    window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 31, tzinfo=UTC))
    raw = BarSeries.from_bars(provider.get_bars("AAPL", *window, "1d"), basis=PriceBasis.RAW)
    adjusted = adjust(raw, provider.get_adjustment_data("AAPL", *window, "1d"))
    assert adjusted.values("volume") == raw.values("volume")
