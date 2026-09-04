"""Momentum features.

RSI CONVENTION — Wilder (1978), stated precisely
================================================
RSI implementations disagree, so this is the exact definition used here. Another
engineer should be able to reproduce these numbers from this text alone.

Given closes ``c[0..n-1]`` and a period ``p`` (default 14):

1. **Changes.** For ``i >= 1``: ``d[i] = c[i] - c[i-1]``.
   ``gain[i] = max(d[i], 0)``, ``loss[i] = max(-d[i], 0)``. Losses are
   positive magnitudes.

2. **Seed** at index ``p`` (which needs ``p`` changes, i.e. ``p + 1`` closes)::

       avg_gain[p] = (gain[1] + ... + gain[p]) / p
       avg_loss[p] = (loss[1] + ... + loss[p]) / p

   A *simple* mean, as in Wilder's original. Some libraries seed differently.

3. **Wilder smoothing** for ``i > p`` (a modified EMA with ``alpha = 1/p``,
   NOT ``2/(p+1)``)::

       avg_gain[i] = (avg_gain[i-1] * (p - 1) + gain[i]) / p
       avg_loss[i] = (avg_loss[i-1] * (p - 1) + loss[i]) / p

4. **Index** ``RS = avg_gain / avg_loss``, ``RSI = 100 - 100 / (1 + RS)``,
   equivalently ``100 * avg_gain / (avg_gain + avg_loss)``.

Degenerate cases, chosen explicitly:

* ``avg_loss == 0`` and ``avg_gain > 0`` -> **100.0** (no downward pressure).
* ``avg_gain == 0`` and ``avg_loss > 0`` -> **0.0**.
* ``avg_gain == 0`` and ``avg_loss == 0`` (perfectly flat prices) -> **50.0**.
  RSI is genuinely undefined here (0/0); 50 is our documented choice for "no
  directional pressure in either direction". Other libraries return 100 or
  NaN. We do not claim equivalence with any of them.

First defined value is at index ``p``. Everything earlier is ``None``.
"""

from __future__ import annotations

from src.data.series import BarSeries

from .base import FeatureSeries, require_period, require_series


def rsi(series: BarSeries, period: int = 14, *, field: str = "close") -> FeatureSeries:
    """Wilder-style Relative Strength Index. See the module docstring."""
    series = require_series(series)
    period = require_period(period)
    prices = series.values(field)

    values: list[float | None] = [None] * len(prices)
    if len(prices) <= period:
        return FeatureSeries.aligned_to(
            series, name="rsi", params={"period": period, "field": field}, values=values
        )

    gains = [0.0] * len(prices)
    losses = [0.0] * len(prices)
    for index in range(1, len(prices)):
        change = prices[index] - prices[index - 1]
        gains[index] = max(change, 0.0)
        losses[index] = max(-change, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    values[period] = _rsi_from(avg_gain, avg_loss)

    for index in range(period + 1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        values[index] = _rsi_from(avg_gain, avg_loss)

    return FeatureSeries.aligned_to(
        series, name="rsi", params={"period": period, "field": field}, values=values
    )


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    """RSI from smoothed averages, with the documented degenerate cases."""
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    if avg_gain == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


__all__ = ["rsi"]
