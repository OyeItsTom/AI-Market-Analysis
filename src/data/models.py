"""Core market-data models used throughout the application.

This module defines the *canonical* representation of market data for the
whole system: :class:`MarketBar`.

Everything downstream of the data layer (features, strategies, backtesting,
risk, signals, paper trading) is expected to consume :class:`MarketBar`
objects and nothing else.  Vendor-specific schemas (yfinance DataFrames,
Alpaca JSON payloads, ...) must be normalized into this type inside a
provider adapter and must never leak past it.

Validation split
----------------
``MarketBar`` enforces only *structural* invariants -- the things that must
hold for the object to be a meaningful value at all:

* required text fields are non-empty
* numeric fields are real, finite numbers
* the timestamp is timezone-aware

Financial/semantic rules (OHLC relationships, sign rules, sequence ordering,
duplicate timestamps, ...) live in :mod:`src.data.validation` so that they
can be applied deliberately, reported in bulk, and reasoned about
independently of object construction.

System invariant: TIMESTAMP MEANS BAR OPEN TIME
-----------------------------------------------
``MarketBar.timestamp`` is the **start of the bar's period**, in UTC — the
instant the bar opened, never the instant it closed.  The bar therefore covers
the half-open interval ``[timestamp, timestamp + interval)``.

This is a system-wide invariant that **every provider adapter must honour**.
An adapter whose vendor stamps bars at close time must subtract the interval
before constructing a ``MarketBar``.

It matters because the convention is invisible in the data.  If one provider
stamped bars at open and another at close, the two series would merge,
validate and store without a single complaint, while a strategy reading "the
bar at time T" would be handed information from after T for one of them —
look-ahead bias, introduced silently by a data-layer detail.

Open time is chosen over close time because it is the only convention under
which a bar's timestamp is knowable *before* the bar's data is: a strategy
acting on the bar at T acts strictly after T, and completeness becomes a
separate, explicit question (see ``MarketDataProvider.get_bars``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping


class Interval(str, Enum):
    """Supported bar intervals.

    ``str`` subclass so that the value serializes naturally (CSV, JSON) and
    compares equal to its plain-string form (``Interval.DAY == "1d"``).
    """

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1wk"
    MONTH_1 = "1mo"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def max_duration(self) -> timedelta:
        """An **upper bound** on how long a bar of this interval can cover.

        Deliberately an upper bound rather than an exact length: ``1wk`` and
        ``1mo`` have no fixed duration, and this value is used to prove that a
        bar's period has definitely ended (see
        :meth:`~src.data.provider.MarketDataProvider.get_bars`).  Over-
        estimating can only delay treating a bar as settled; under-estimating
        would let an in-progress bar be mistaken for a finished one, which is
        the failure we are preventing.
        """
        return _MAX_DURATIONS[self]

    @classmethod
    def parse(cls, value: "Interval | str") -> "Interval":
        """Return the :class:`Interval` for ``value``.

        Raises ``ValueError`` for unknown intervals rather than inventing a
        new one, so a typo such as ``"1day"`` fails loudly at the edge of the
        system instead of silently splitting a dataset in two.
        """
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError(f"interval must be an Interval or str, got {type(value).__name__}")
        try:
            return cls(value.strip())
        except ValueError:
            supported = ", ".join(i.value for i in cls)
            raise ValueError(
                f"unsupported interval {value!r}; supported intervals: {supported}"
            ) from None


#: Upper bound on each interval's period length.  Calendar intervals get the
#: longest they can be (a month is at most 31 days), so "settled" is never
#: claimed early.
_MAX_DURATIONS: dict[Interval, timedelta] = {
    Interval.MINUTE_1: timedelta(minutes=1),
    Interval.MINUTE_5: timedelta(minutes=5),
    Interval.MINUTE_15: timedelta(minutes=15),
    Interval.MINUTE_30: timedelta(minutes=30),
    Interval.HOUR_1: timedelta(hours=1),
    Interval.DAY_1: timedelta(days=1),
    Interval.WEEK_1: timedelta(days=7),
    Interval.MONTH_1: timedelta(days=31),
}


def _require_finite(name: str, value: Any) -> float:
    """Coerce ``value`` to ``float`` and reject NaN/inf and non-numerics."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _to_plain_utc_datetime(value: datetime) -> datetime:
    """Return ``value`` in UTC as an exact :class:`datetime`, not a subclass.

    ``pandas.Timestamp`` (and similar vendor types) subclass ``datetime``, so
    they would otherwise travel all the way downstream and reintroduce the
    vendor dependency this layer exists to remove.  Rebuilding the value keeps
    the canonical model free of vendor types.  Sub-microsecond precision is
    dropped -- a documented, deterministic downcast; bar timestamps do not
    need nanosecond resolution.
    """
    value = value.astimezone(timezone.utc)
    if type(value) is datetime:
        return value
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=timezone.utc,
    )


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class MarketBar:
    """A normalized OHLCV market-data bar.

    Attributes
    ----------
    symbol:
        Ticker symbol, upper-cased and stripped (e.g. ``"AAPL"``).
    timestamp:
        **Bar open time** — the start of the period this bar covers, i.e. the
        bar spans ``[timestamp, timestamp + interval)``.  Must be
        timezone-aware; stored normalized to UTC.  See the module docstring:
        this convention is a system invariant, not a per-provider choice.
    open, high, low, close:
        Prices for the bar, as finite floats.
    volume:
        Traded volume for the bar, as a finite float (float rather than int so
        fractional-quantity instruments are representable).
    interval:
        Bar size, see :class:`Interval`.
    source:
        Identifier of the provider the bar came from (e.g. ``"yfinance"``).
        Kept for provenance/auditing -- two bars from different sources are
        not interchangeable evidence.

    Deterministic normalization applied at construction (and documented
    because it changes the input):

    * ``symbol`` is stripped and upper-cased
    * ``timestamp`` is converted to UTC (never *assigned* a timezone) and
      rebuilt as a plain ``datetime`` so vendor subclasses such as
      ``pandas.Timestamp`` cannot leak downstream
    * ``interval`` strings are parsed into :class:`Interval`
    """

    symbol: str
    timestamp: datetime

    open: float
    high: float
    low: float
    close: float
    volume: float

    interval: Interval
    source: str

    def __post_init__(self) -> None:
        # frozen dataclass: normalized values are written via object.__setattr__
        set_ = object.__setattr__

        set_(self, "symbol", _require_text("symbol", self.symbol).upper())
        set_(self, "source", _require_text("source", self.source))
        set_(self, "interval", Interval.parse(self.interval))

        if not isinstance(self.timestamp, datetime):
            raise TypeError(
                f"timestamp must be a datetime, got {type(self.timestamp).__name__}"
            )
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError(
                "timestamp must be timezone-aware; naive timestamps are ambiguous "
                "across exchanges and are rejected rather than guessed"
            )
        set_(self, "timestamp", _to_plain_utc_datetime(self.timestamp))

        for field_name in ("open", "high", "low", "close", "volume"):
            set_(self, field_name, _require_finite(field_name, getattr(self, field_name)))

    # -- convenience -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON/CSV-friendly mapping of this bar."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "interval": self.interval.value,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketBar":
        """Rebuild a bar from :meth:`to_dict` output (or an equivalent mapping)."""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return cls(
            symbol=data["symbol"],
            timestamp=timestamp,
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data["volume"]),
            interval=data["interval"],
            source=data["source"],
        )

    def with_source(self, source: str) -> "MarketBar":
        """Return a copy of this bar tagged with a different ``source``."""
        return replace(self, source=source)


__all__ = ["Interval", "MarketBar"]
