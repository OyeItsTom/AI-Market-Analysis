"""Session-gap contract.  Exchange-aware detection is DEFERRED.

The problem
-----------
Phase 1 validation catches duplicate and out-of-order timestamps but cannot
tell a *missing trading session* from a weekend or a holiday.  Both look the
same in the data: two consecutive bars more than one interval apart.

Answering it properly needs an exchange calendar -- which exchange a symbol
trades on, that exchange's holidays, its half-days, and its session hours.
**None of that exists in the current data model.**  ``MarketBar`` knows a
symbol string and a source; it does not know a venue.

What this module deliberately does NOT do
-----------------------------------------
* infer an exchange from a ticker string (``"AAPL"`` does not imply XNAS; the
  same ticker trades on different venues with different calendars)
* assume weekdays are trading days, or weekends are not
* treat a weekend or holiday as missing data
* add an exchange-calendar dependency
* forward-fill, interpolate or invent a bar

Any of those would manufacture a confident answer from information we do not
have, and a wrong "missing session" verdict is worse than an honest "unknown".

What it does provide
--------------------
The contract a real calendar will implement, an honest default that answers
``UNKNOWN`` for everything, and gap *observation* that is clearly separated
from gap *classification*.  Observation is factual (these two bars are more
than one interval apart); classification is what needs a calendar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .models import Interval
from .series import BarSeries


class SessionStatus(str, Enum):
    """Why a period contains no bar."""

    #: A session the exchange held, for which we have no data. Real missing
    #: data: a fetch failure, a provider gap, a filtered bar.
    EXPECTED_SESSION_MISSING = "expected_session_missing"

    #: The exchange was closed. Not missing data; nothing to explain.
    NON_TRADING_DAY = "non_trading_day"

    #: No calendar was available to decide. The honest default -- never
    #: interpret this as either of the above.
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ObservedGap:
    """A factual observation: consecutive bars more than one interval apart.

    ``status`` is whatever the supplied calendar could determine. With the
    default calendar it is always ``UNKNOWN``, which means "this needs a
    calendar", not "this is a problem".
    """

    symbol: str
    interval: Interval
    after: datetime
    before: datetime
    missing_intervals: int
    status: SessionStatus = SessionStatus.UNKNOWN

    @property
    def duration(self) -> timedelta:
        return self.before - self.after

    def __str__(self) -> str:
        return (
            f"{self.symbol} {self.interval.value}: {self.missing_intervals} interval(s) "
            f"absent between {self.after.isoformat()} and {self.before.isoformat()} "
            f"[{self.status.value}]"
        )


class TradingCalendar(ABC):
    """Classifies a gap between two bars. Implement this to add calendar awareness."""

    #: Human-readable identity of the calendar, recorded in reports.
    name: str = "abstract"

    @abstractmethod
    def classify(
        self,
        symbol: str,
        interval: Interval,
        after: datetime,
        before: datetime,
    ) -> SessionStatus:
        """Say whether the period between two bars should have contained data."""


class UnknownTradingCalendar(TradingCalendar):
    """The default: declines to guess.

    Returns ``UNKNOWN`` for every gap. This is not a placeholder to be quietly
    tolerated -- it is the correct answer given that the system holds no venue
    metadata. Replacing it requires exchange information the data model does
    not yet carry.
    """

    name = "unknown (no exchange calendar configured)"

    def classify(
        self,
        symbol: str,
        interval: Interval,
        after: datetime,
        before: datetime,
    ) -> SessionStatus:
        return SessionStatus.UNKNOWN


@dataclass(frozen=True)
class GapReport:
    """The result of scanning a series for gaps."""

    symbol: str
    interval: Interval
    calendar: str
    bar_count: int
    gaps: tuple[ObservedGap, ...]

    @property
    def has_unclassified_gaps(self) -> bool:
        """``True`` if any gap could not be classified.

        Research code should treat this as "the completeness of this series is
        unverified", never as "this series is complete".
        """
        return any(gap.status is SessionStatus.UNKNOWN for gap in self.gaps)

    @property
    def missing_sessions(self) -> tuple[ObservedGap, ...]:
        """Gaps a calendar positively identified as missing sessions."""
        return tuple(
            gap for gap in self.gaps if gap.status is SessionStatus.EXPECTED_SESSION_MISSING
        )

    def summary(self) -> str:
        return (
            f"{self.symbol} {self.interval.value}: {self.bar_count} bars, "
            f"{len(self.gaps)} observed gap(s), "
            f"{len(self.missing_sessions)} confirmed missing session(s), "
            f"calendar={self.calendar}"
        )


def find_gaps(series: BarSeries, calendar: TradingCalendar | None = None) -> GapReport:
    """Observe gaps in ``series`` and classify them with ``calendar``.

    A gap is recorded whenever consecutive bars are more than one interval
    apart. With the default :class:`UnknownTradingCalendar` this includes every
    weekend and holiday -- which is precisely why each gap carries a
    ``status`` and why ``UNKNOWN`` must not be read as "missing data".

    Nothing is filled, inserted or repaired. This function only reports.
    """
    calendar = calendar or UnknownTradingCalendar()
    step = series.interval.max_duration

    gaps: list[ObservedGap] = []
    for previous, current in zip(series.bars, series.bars[1:]):
        elapsed = current.timestamp - previous.timestamp
        if elapsed <= step:
            continue
        gaps.append(
            ObservedGap(
                symbol=series.symbol,
                interval=series.interval,
                after=previous.timestamp,
                before=current.timestamp,
                # Whole intervals that could have sat in the gap. Uses
                # max_duration, so for calendar intervals this is a lower
                # bound, not an exact count.
                missing_intervals=max(int(elapsed / step) - 1, 1),
                status=calendar.classify(
                    series.symbol, series.interval, previous.timestamp, current.timestamp
                ),
            )
        )

    return GapReport(
        symbol=series.symbol,
        interval=series.interval,
        calendar=calendar.name,
        bar_count=len(series),
        gaps=tuple(gaps),
    )


__all__ = [
    "SessionStatus",
    "ObservedGap",
    "TradingCalendar",
    "UnknownTradingCalendar",
    "GapReport",
    "find_gaps",
]
