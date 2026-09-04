"""Shared fixtures/helpers for the market-data tests.

Nothing here touches the network: every provider test injects a fake fetch
function, so the suite runs offline and deterministically.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval, MarketBar

UTC = timezone.utc


def make_bar(
    *,
    symbol: str = "AAPL",
    timestamp: datetime | None = None,
    open: float = 100.0,
    high: float = 110.0,
    low: float = 95.0,
    close: float = 105.0,
    volume: float = 1_000.0,
    interval: Interval | str = Interval.DAY_1,
    source: str = "test",
) -> MarketBar:
    """Build a valid bar; override any field to make it invalid on purpose."""
    return MarketBar(
        symbol=symbol,
        timestamp=timestamp or datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        interval=interval,
        source=source,
    )


def corrupt_bar(bar: MarketBar, **overrides) -> MarketBar:
    """Build a MarketBar-shaped object that bypasses ``__post_init__``.

    Needed to test the validation layer against states the constructor
    refuses to create (NaN, infinity, naive timestamps) -- data that can still
    reach us from a corrupted cache file or a mis-written adapter.
    """
    clone = object.__new__(MarketBar)
    for field in fields(MarketBar):
        value = overrides.get(field.name, getattr(bar, field.name))
        object.__setattr__(clone, field.name, value)
    return clone


@pytest.fixture
def bar() -> MarketBar:
    return make_bar()


@pytest.fixture
def bars() -> list[MarketBar]:
    """Three consecutive, valid daily bars."""
    start = datetime(2024, 1, 2, tzinfo=UTC)
    return [
        make_bar(timestamp=start + timedelta(days=offset), close=105.0 + offset)
        for offset in range(3)
    ]
