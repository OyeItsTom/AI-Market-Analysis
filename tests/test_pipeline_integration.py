"""End-to-end check of the Phase 1 pipeline, entirely offline.

provider -> normalization -> validation -> storage -> read back
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

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
