"""Deterministic synthetic bars for the Phase R engine tests. Offline only."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.research import StudyDefinition

UTC = timezone.utc


def synthetic_bars(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    phase: float = 0.0,
    source: str = "synthetic",
    interval: Interval = Interval.DAY_1,
    period_bars: int = 9,
) -> list[MarketBar]:
    """One bar per calendar day in ``[start, end)``: a slow sine on a drift.

    The sine crosses its own moving averages several times per quarter, so
    every hypothesis emits every state; ``phase`` makes symbols differ.
    """
    bars: list[MarketBar] = []
    step = interval.max_duration
    timestamp, index = start, 0
    while timestamp < end:
        close = 100.0 + 10.0 * math.sin(index / period_bars + phase) + 0.05 * index
        open_ = close - 0.2 + 0.1 * math.cos(index / 5 + phase)
        bars.append(
            MarketBar(
                symbol=symbol,
                timestamp=timestamp,
                open=open_,
                high=max(open_, close) + 1.0,
                low=min(open_, close) - 1.0,
                close=close,
                volume=1_000.0 + index,
                interval=interval,
                source=source,
            )
        )
        timestamp += step
        index += 1
    return bars


def synthetic_series(definition: StudyDefinition, symbol: str, *, phase: float | None = None,
                     end: datetime | None = None, source: str = "synthetic") -> BarSeries:
    """A series covering the definition's full fetch window for ``symbol``."""
    if phase is None:
        phase = 0.7 * definition.symbols.index(symbol)
    bars = synthetic_bars(
        symbol,
        definition.fetch_start,
        definition.outcome_data_end if end is None else end,
        phase=phase,
        source=source,
        interval=definition.interval,
    )
    return BarSeries.from_bars(bars, basis=PriceBasis(definition.basis))


def series_for(definition: StudyDefinition, **kwargs) -> dict[str, BarSeries]:
    return {symbol: synthetic_series(definition, symbol, **kwargs) for symbol in definition.symbols}


__all__ = ["UTC", "synthetic_bars", "synthetic_series", "series_for", "timedelta"]
