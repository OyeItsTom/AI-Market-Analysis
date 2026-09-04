"""Bar-to-bar return features.

Both features compare a bar's close with the previous bar's close, so index 0
has no value: there is no earlier bar, and using a later one would be
look-ahead.

Price-basis warning: a return computed on a ``RAW`` series spans corporate
actions mechanically -- a 4-for-1 split shows as roughly -75%. Compute returns
on a ``SPLIT_AND_DIVIDEND_ADJUSTED`` series when you want the economic
outcome. The feature does not decide this for you; it records the basis it was
given so the mistake is at least visible.
"""

from __future__ import annotations

import math

from src.data.series import BarSeries

from .base import FeatureSeries, require_series


def simple_return(series: BarSeries, *, field: str = "close") -> FeatureSeries:
    """Arithmetic return: ``value[i] = price[i] / price[i-1] - 1``.

    ``values[0]`` is ``None``. A zero previous price yields ``None`` rather
    than an infinity (validated series cannot contain one, but a derived
    series is not re-validated for this specific case).
    """
    series = require_series(series)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    for index in range(1, len(prices)):
        previous = prices[index - 1]
        values[index] = None if previous == 0 else prices[index] / previous - 1.0

    return FeatureSeries.aligned_to(
        series, name="simple_return", params={"field": field}, values=values
    )


def log_return(series: BarSeries, *, field: str = "close") -> FeatureSeries:
    """Logarithmic return: ``value[i] = ln(price[i] / price[i-1])``.

    ``values[0]`` is ``None``. Non-positive prices make the logarithm
    undefined and yield ``None``.
    """
    series = require_series(series)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    for index in range(1, len(prices)):
        previous, current = prices[index - 1], prices[index]
        values[index] = (
            None if previous <= 0 or current <= 0 else math.log(current / previous)
        )

    return FeatureSeries.aligned_to(
        series, name="log_return", params={"field": field}, values=values
    )


__all__ = ["simple_return", "log_return"]
