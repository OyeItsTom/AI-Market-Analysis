"""Volume features.

Volume caveat under adjustment
------------------------------
An adjusted price series carries the **original reported volume** (see
``src/data/adjustment.py``): nothing rescales share counts, because inventing
them would be fabrication. Consequences:

* adjusted price x reported volume is **not** historical traded notional;
* a raw-volume series spanning a split has a mechanical step in it, exactly as
  the raw price series does, and these features will show that step.

Any feature needing price-volume economic consistency must handle this itself.
"""

from __future__ import annotations

from src.data.series import BarSeries

from .base import FeatureSeries, require_period, require_series


def average_volume(series: BarSeries, period: int) -> FeatureSeries:
    """Simple moving average of volume over the trailing ``period`` bars.

    First defined value is at index ``period - 1``.
    """
    series = require_series(series)
    period = require_period(period)
    volumes = series.values("volume")

    values: list[float | None] = [None] * len(volumes)
    window_sum = 0.0
    for index, volume in enumerate(volumes):
        window_sum += volume
        if index >= period:
            window_sum -= volumes[index - period]
        if index >= period - 1:
            values[index] = window_sum / period

    return FeatureSeries.aligned_to(
        series, name="average_volume", params={"period": period}, values=values
    )


def relative_volume(series: BarSeries, period: int) -> FeatureSeries:
    """Volume relative to its trailing average: ``volume[i] / average_volume[i]``.

    The average **includes bar ``i``** (it is the same window as
    :func:`average_volume`), so this uses no future information.

    When the trailing average is zero the ratio is undefined and the value is
    ``None`` -- not zero, not one. A stretch of zero-volume bars is a real
    condition (halts, illiquid instruments) and must not be papered over.

    First defined value is at index ``period - 1``.
    """
    series = require_series(series)
    period = require_period(period)
    volumes = series.values("volume")
    averages = average_volume(series, period).values

    values: list[float | None] = [None] * len(volumes)
    for index, average in enumerate(averages):
        if average is None or average == 0:
            continue
        values[index] = volumes[index] / average

    return FeatureSeries.aligned_to(
        series, name="relative_volume", params={"period": period}, values=values
    )


__all__ = ["average_volume", "relative_volume"]
