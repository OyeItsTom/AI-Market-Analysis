"""Moving-average trend features.

Conventions are stated explicitly because implementations differ.
"""

from __future__ import annotations

from src.data.series import BarSeries

from .base import FeatureSeries, require_period, require_series


def sma(series: BarSeries, period: int, *, field: str = "close") -> FeatureSeries:
    """Simple moving average over the trailing ``period`` observations.

    ``value[i] = mean(price[i-period+1] .. price[i])``, inclusive of bar ``i``.

    First defined value is at index ``period - 1``; every earlier index is
    ``None``. The window is never shortened to produce an early value.
    """
    series = require_series(series)
    period = require_period(period)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    window_sum = 0.0
    for index, price in enumerate(prices):
        window_sum += price
        if index >= period:
            window_sum -= prices[index - period]
        if index >= period - 1:
            values[index] = window_sum / period

    return FeatureSeries.aligned_to(
        series, name="sma", params={"period": period, "field": field}, values=values
    )


def ema(series: BarSeries, period: int, *, field: str = "close") -> FeatureSeries:
    """Exponential moving average.

    Convention (stated because EMA initialisation varies between libraries):

    * smoothing factor ``alpha = 2 / (period + 1)``
    * **seeded** with the simple average of the first ``period`` observations,
      placed at index ``period - 1``
    * thereafter ``ema[i] = alpha * price[i] + (1 - alpha) * ema[i-1]``

    Seeding from an SMA rather than from ``price[0]`` means the early values do
    not carry the outsized weight of a single arbitrary observation. The seed
    uses only observations at or before its own index, so the recursion never
    sees the future.

    First defined value is at index ``period - 1``.
    """
    series = require_series(series)
    period = require_period(period)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    if len(prices) < period:
        return FeatureSeries.aligned_to(
            series, name="ema", params={"period": period, "field": field}, values=values
        )

    alpha = 2.0 / (period + 1.0)
    current = sum(prices[:period]) / period
    values[period - 1] = current
    for index in range(period, len(prices)):
        current = alpha * prices[index] + (1.0 - alpha) * current
        values[index] = current

    return FeatureSeries.aligned_to(
        series, name="ema", params={"period": period, "field": field}, values=values
    )


__all__ = ["sma", "ema"]
