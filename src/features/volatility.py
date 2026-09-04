"""Volatility features.

Two conventions are stated precisely below because both vary between
implementations.
"""

from __future__ import annotations

import math

from src.data.series import BarSeries

from .base import FeatureSeries, require_period, require_series


def realized_volatility(
    series: BarSeries, period: int, *, field: str = "close"
) -> FeatureSeries:
    """Rolling standard deviation of logarithmic returns.

    Convention:

    * returns are **logarithmic**: ``r[i] = ln(p[i] / p[i-1])``, defined for
      ``i >= 1``
    * the statistic is the **sample** standard deviation (``ddof = 1``, i.e.
      divide by ``period - 1``), so ``period`` must be at least 2
    * the window covers the trailing ``period`` returns ending at bar ``i``
    * the result is **NOT annualised** -- it is the standard deviation per bar.
      Multiply by ``sqrt(bars per year)` yourself if you want an annual figure;
      doing it here would require assuming a trading calendar, which this
      system does not have (see ``src/data/sessions.py``).

    First defined value is at index ``period`` (one bar is consumed producing
    the first return, then ``period`` returns are needed).
    """
    series = require_series(series)
    period = require_period(period, minimum=2)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    if len(prices) <= period:
        return FeatureSeries.aligned_to(
            series,
            name="realized_volatility",
            params={"period": period, "field": field},
            values=values,
        )

    returns: list[float | None] = [None] * len(prices)
    for index in range(1, len(prices)):
        previous, current = prices[index - 1], prices[index]
        returns[index] = None if previous <= 0 or current <= 0 else math.log(current / previous)

    for index in range(period, len(prices)):
        window = returns[index - period + 1 : index + 1]
        if any(value is None for value in window):
            continue  # an undefined return leaves the whole window undefined
        mean = sum(window) / period  # type: ignore[arg-type]
        variance = sum((value - mean) ** 2 for value in window) / (period - 1)  # type: ignore[operator]
        values[index] = math.sqrt(variance)

    return FeatureSeries.aligned_to(
        series,
        name="realized_volatility",
        params={"period": period, "field": field},
        values=values,
    )


def atr(series: BarSeries, period: int = 14) -> FeatureSeries:
    """Average True Range, Wilder-smoothed.

    ATR CONVENTION — stated precisely
    ---------------------------------
    **True Range.** For ``i >= 1``::

        TR[i] = max( high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i]  - close[i-1]) )

    For ``i == 0`` there is no previous close, so ``TR[0] = high[0] - low[0]``.
    The two gap terms are omitted rather than guessed; this is Wilder's
    treatment and it is why the first value is not comparable with later ones.

    **Initial ATR** at index ``period - 1`` is the *simple* mean of
    ``TR[0] .. TR[period-1]``.

    **Smoothing** for ``i >= period`` uses Wilder's recursion (``alpha = 1/p``,
    not ``2/(p+1)``)::

        ATR[i] = (ATR[i-1] * (period - 1) + TR[i]) / period

    First defined value is at index ``period - 1``.
    """
    series = require_series(series)
    period = require_period(period)

    highs = series.values("high")
    lows = series.values("low")
    closes = series.values("close")

    values: list[float | None] = [None] * len(highs)
    if len(highs) < period:
        return FeatureSeries.aligned_to(
            series, name="atr", params={"period": period}, values=values
        )

    true_ranges = [0.0] * len(highs)
    true_ranges[0] = highs[0] - lows[0]
    for index in range(1, len(highs)):
        previous_close = closes[index - 1]
        true_ranges[index] = max(
            highs[index] - lows[index],
            abs(highs[index] - previous_close),
            abs(lows[index] - previous_close),
        )

    current = sum(true_ranges[:period]) / period
    values[period - 1] = current
    for index in range(period, len(highs)):
        current = (current * (period - 1) + true_ranges[index]) / period
        values[index] = current

    return FeatureSeries.aligned_to(
        series, name="atr", params={"period": period}, values=values
    )


__all__ = ["realized_volatility", "atr"]
