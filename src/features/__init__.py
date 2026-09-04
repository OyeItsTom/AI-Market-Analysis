"""Feature engine: deterministic calculations over validated market data.

Every feature is a pure function of a :class:`~src.data.series.BarSeries` and
returns a :class:`~src.features.base.FeatureSeries` aligned one-to-one with
the input bars.

Read ``src/features/base.py`` before using these: it defines the warm-up
representation (``None``), the alignment guarantee, and the distinction
between a bar's open time and the time its feature value became knowable.

No feature here produces a trading signal, a recommendation, or a prediction.
They are inputs to research, nothing more.
"""

from .base import FeatureError, FeatureSeries
from .momentum import rsi
from .returns import log_return, simple_return
from .trend import ema, sma
from .volatility import atr, realized_volatility
from .volume import average_volume, relative_volume

__all__ = [
    "FeatureSeries",
    "FeatureError",
    "simple_return",
    "log_return",
    "sma",
    "ema",
    "rsi",
    "realized_volatility",
    "atr",
    "average_volume",
    "relative_volume",
]
