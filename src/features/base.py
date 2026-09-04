"""Feature output representation and shared guards.

A feature is a deterministic, provider-independent calculation over a
validated :class:`~src.data.series.BarSeries`.

What a feature function must never do
-------------------------------------
* mutate its input
* fetch data or touch a provider
* read the wall clock
* use global mutable state
* look at any bar after the one it is producing a value for
* sort, deduplicate, or repair its input
* fill, interpolate, or invent a value

Timing: bar open time vs. knowable time
---------------------------------------
``MarketBar.timestamp`` is the bar's **open** time (a Phase 1 invariant).  A
feature value aligned to that timestamp is derived from the bar's close, high,
low or volume, none of which are known until the bar has **finished**.

So a feature value at timestamp ``T`` was *not* available at ``T``.
:meth:`FeatureSeries.knowable_at` returns ``T + interval``: the earliest
instant at which the value could possibly be known.  Any future strategy or
backtester must act at or after that instant, never at the timestamp itself --
treating the two as the same thing is look-ahead bias, and the alignment of
the output array makes that mistake easy if the distinction is not stated.

**It is a bound, not a measurement.** Phase 1 carries no exchange calendar and
no provider-latency model, so the true instant cannot be computed. Two
consequences, in opposite directions:

* For a session-based interval the bound is **late**: a daily bar's session
  closes hours before ``T + 1 day``, and ``1wk``/``1mo`` use
  ``Interval.max_duration``, an upper bound. Acting on the bound is safe here.
* For **data availability** the bound is **optimistic**: it models when the
  bar *completed*, not when the provider published it. yfinance intraday data
  is delayed, so an hourly value is not actually retrievable at ``T + 1h``.

Do not treat ``knowable_at`` as a guarantee that the data existed. It is the
earliest instant the value *could* have been known, and a backtester that
needs realistic execution timing must add its own latency assumption on top.

Warm-up
-------
One representation, used everywhere: **``None``**.

A value is ``None`` exactly when the indicator does not yet have enough
history to be defined (``SMA(20)`` at bar 5), or when the calculation is
genuinely undefined at that point (relative volume against zero average
volume).  ``None`` is used rather than ``NaN`` because it cannot be silently
propagated through arithmetic -- it raises instead, which is the desired
outcome for a value that does not exist.

Nothing is ever back-filled, seeded from the future, or quietly computed over
a shorter window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis


class FeatureError(ValueError):
    """Raised when a feature cannot be computed as requested."""


@dataclass(frozen=True)
class FeatureSeries:
    """Feature values aligned one-to-one with the bars they came from.

    ``timestamps[i]`` is the open time of the bar that produced ``values[i]``.
    The two tuples always have the same length, so positional drift is not
    possible; filtering is done with :meth:`ready_pairs`, which keeps
    timestamps attached to values rather than returning a bare list that a
    caller could re-index against the wrong bars.

    Provenance (``symbol``, ``interval``, ``source``, ``basis``) is carried
    from the originating series so a feature can never be silently compared
    against one computed from a different instrument or a different price
    basis.
    """

    symbol: str
    interval: Interval
    source: str
    basis: PriceBasis
    name: str
    params: Mapping[str, Any]
    timestamps: tuple[datetime, ...]
    values: tuple[float | None, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "timestamps", tuple(self.timestamps))
        set_(self, "values", tuple(self.values))
        set_(self, "params", MappingProxyType(dict(self.params)))
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))

        if len(self.timestamps) != len(self.values):
            raise FeatureError(
                f"{self.name}: {len(self.timestamps)} timestamps but {len(self.values)} "
                "values; feature output must align one-to-one with its bars"
            )
        if not str(self.name).strip():
            raise FeatureError("feature name must not be empty")

    # -- construction ----------------------------------------------------

    @classmethod
    def aligned_to(
        cls,
        series: BarSeries,
        *,
        name: str,
        params: Mapping[str, Any],
        values: Sequence[float | None],
    ) -> "FeatureSeries":
        """Build a feature series aligned to ``series``, inheriting its provenance."""
        if len(values) != len(series):
            raise FeatureError(
                f"{name}: produced {len(values)} values for {len(series)} bars; "
                "a feature must produce exactly one value per bar"
            )
        return cls(
            symbol=series.symbol,
            interval=series.interval,
            source=series.source,
            basis=series.basis,
            name=name,
            params=params,
            timestamps=series.timestamps,
            values=tuple(values),
        )

    # -- access ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[tuple[datetime, float | None]]:
        return iter(zip(self.timestamps, self.values))

    def __getitem__(self, index: int) -> tuple[datetime, float | None]:
        return self.timestamps[index], self.values[index]

    def is_ready(self, index: int) -> bool:
        """``True`` if the value at ``index`` is defined (past warm-up)."""
        return self.values[index] is not None

    @property
    def ready_from(self) -> int | None:
        """Index of the first defined value, or ``None`` if there is none."""
        for index, value in enumerate(self.values):
            if value is not None:
                return index
        return None

    def ready_pairs(self) -> tuple[tuple[datetime, float], ...]:
        """Defined ``(timestamp, value)`` pairs only, still paired."""
        return tuple(
            (timestamp, value)
            for timestamp, value in zip(self.timestamps, self.values)
            if value is not None
        )

    def knowable_at(self, index: int) -> datetime:
        """Earliest instant at which the value at ``index`` could be known.

        The bar's open time plus one interval: the value depends on the bar's
        close/high/low/volume, which are not known until the bar completes.
        This is not the same as ``timestamps[index]``.

        A **lower bound**, not a measurement. It ignores provider publication
        delay, and for session-based intervals it is later than the true
        session close. See the module docstring before relying on it for
        execution timing.
        """
        return self.timestamps[index] + self.interval.max_duration

    def describe(self) -> str:
        params = ", ".join(f"{key}={value!r}" for key, value in sorted(self.params.items()))
        ready = self.ready_from
        return (
            f"{self.name}({params}) on {self.symbol} {self.interval.value} "
            f"[{self.basis.value}] from {self.source}: {len(self)} values, "
            f"ready from index {ready if ready is not None else 'never'}"
        )


# --------------------------------------------------------------------------
# Shared guards
# --------------------------------------------------------------------------


def require_series(series: object) -> BarSeries:
    """Reject anything that is not a validated :class:`BarSeries`.

    Features refuse bare ``list[MarketBar]`` deliberately: a list carries no
    guarantee of a single symbol, interval, source or price basis, and a
    feature computed across a mix of those is silently meaningless.
    """
    if not isinstance(series, BarSeries):
        raise FeatureError(
            f"expected a BarSeries, got {type(series).__name__}; features require the "
            "validated series type, not a bare list of bars (it guarantees one symbol, "
            "one interval, one source and one price basis)"
        )
    return series


def require_period(period: object, *, minimum: int = 1, name: str = "period") -> int:
    """Reject non-integer or too-small look-back windows."""
    if isinstance(period, bool) or not isinstance(period, int):
        raise FeatureError(f"{name} must be an int, got {type(period).__name__}")
    if period < minimum:
        raise FeatureError(f"{name} must be >= {minimum}, got {period}")
    return period


__all__ = [
    "FeatureSeries",
    "FeatureError",
    "require_series",
    "require_period",
]
