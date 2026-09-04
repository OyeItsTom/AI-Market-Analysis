"""The market-data provider abstraction.

Why this exists
---------------
Strategies, backtests, risk and signal code must never import a vendor SDK.
If they did, swapping Yahoo for Alpaca (or adding a second venue, or replaying
a stored dataset) would mean rewriting everything downstream, and every module
would have to know about that vendor's column names, timezone quirks and
error types.

Instead every data source implements :class:`MarketDataProvider` and returns
:class:`~src.data.models.MarketBar` objects.  The vendor's schema stops at the
adapter boundary.

Contract enforced here
----------------------
:meth:`MarketDataProvider.get_bars` is a *template method*: it checks the
request arguments, delegates to the subclass hook :meth:`_fetch_bars`,
validates whatever came back, and drops trailing bars whose period has not
provably ended.  A provider therefore cannot return malformed, inconsistent
or half-formed data without an exception being raised or the bar being
withheld, no matter how careless the adapter is.

Settled vs. unsettled bars
--------------------------
A vendor will happily hand you the bar for the session that is still open.
It has the same shape as a finished bar, but its ``close`` is a mid-session
snapshot that will keep changing.  Backtesting on finished bars and then
running live on that half-formed bar is a classic source of
backtest/live divergence.

Completeness is **not** stored on :class:`~src.data.models.MarketBar`.  It is
not a property of the record -- it is a property of the record *relative to
the current time*: a bar written to cache as unsettled becomes settled a
minute later, so persisting a boolean would be persisting a value that is
false by the time it is read back.  Instead the provider decides, at request
time, using the one thing that is knowable: the bar's period is over when
``timestamp + interval`` has passed.  Because timestamps are bar *open*
times (a system invariant, see :mod:`src.data.models`), that arithmetic is
well defined for every provider.

Nothing is ever asserted to be final that cannot be proven final: for the
calendar intervals whose length varies (``1wk``, ``1mo``) the upper bound is
used, so a settled bar may occasionally be withheld for a little longer, but
an unsettled bar is never presented as finished.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Sequence

from .models import Interval, MarketBar
from .validation import validate_bars


class ProviderError(RuntimeError):
    """Base class for provider-level failures."""


class ProviderUnavailableError(ProviderError):
    """The upstream data source could not be reached or refused the request."""


class ProviderConfigurationError(ProviderError):
    """The provider is not usable as configured (missing SDK, missing credentials)."""


class MarketDataProvider(ABC):
    """Abstract source of normalized historical OHLCV bars."""

    #: Short identifier written into ``MarketBar.source`` for provenance.
    name: str = "unknown"

    #: Intervals this provider claims to support.  ``None`` means "all of
    #: :class:`Interval`"; subclasses should narrow it when they know better.
    supported_intervals: frozenset[Interval] | None = None

    # -- public API ------------------------------------------------------

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: Interval | str = Interval.DAY_1,
        *,
        include_unsettled: bool = False,
    ) -> list[MarketBar]:
        """Return validated bars for ``symbol`` in ``[start, end]``.

        Parameters
        ----------
        symbol:
            Ticker symbol; case-insensitive, normalized to upper case.
        start, end:
            Timezone-aware datetimes.  Naive datetimes are rejected rather
            than assumed to be UTC or local time.
        interval:
            Bar size (see :class:`~src.data.models.Interval`).
        include_unsettled:
            By default (``False``) trailing bars whose period has not provably
            ended are withheld, so the result contains only completed bars --
            this is what historical research and backtesting must use.  Pass
            ``True`` to also receive the in-progress bar, accepting that its
            values are a moving snapshot rather than a settled result.

        Returns
        -------
        list[MarketBar]
            Chronologically ordered bars.  An **empty list** is a valid
            result meaning "the source has no data for this window"; it is
            not an error.

        Raises
        ------
        ValueError
            The request itself is malformed.
        ProviderError
            The upstream source failed.
        ~src.data.validation.ValidationError
            The upstream source returned data that failed validation.
        """
        symbol = self._normalize_symbol(symbol)
        interval = Interval.parse(interval)
        self._check_window(start, end)

        if self.supported_intervals is not None and interval not in self.supported_intervals:
            supported = ", ".join(sorted(i.value for i in self.supported_intervals))
            raise ValueError(
                f"{self.name} does not support interval {interval.value!r}; supported: {supported}"
            )

        bars = self._fetch_bars(symbol, start, end, interval)
        validated = validate_bars(
            list(bars),
            expected_symbol=symbol,
            expected_interval=interval,
            require_sorted=True,
        )
        if include_unsettled:
            return validated
        return self._settled_only(validated, interval)

    # -- completeness ----------------------------------------------------

    def _now(self) -> datetime:
        """Current UTC instant.  Overridden in tests to pin the clock."""
        return datetime.now(timezone.utc)

    def _settled_only(self, bars: list[MarketBar], interval: Interval) -> list[MarketBar]:
        """Drop the trailing bars whose period has not provably ended.

        Bars are chronologically ordered (validation guarantees it), so the
        unsettled ones are always a suffix.  This is implemented as a suffix
        trim rather than a filter so that it can never punch a hole in the
        middle of a series.
        """
        now = self._now()
        cut = len(bars)
        for index in range(len(bars) - 1, -1, -1):
            if bars[index].timestamp + interval.max_duration <= now:
                break
            cut = index
        return bars[:cut]

    # -- subclass hook ---------------------------------------------------

    @abstractmethod
    def _fetch_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: Interval,
    ) -> Sequence[MarketBar]:
        """Fetch and normalize bars from the underlying source.

        Implementations receive already-checked arguments (upper-cased symbol,
        timezone-aware window, parsed interval) and must return
        :class:`MarketBar` objects tagged with ``source=self.name``.  They
        must not invent, interpolate or forward-fill missing data.
        """

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        if not isinstance(symbol, str):
            raise TypeError(f"symbol must be a str, got {type(symbol).__name__}")
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be empty")
        return normalized

    @staticmethod
    def _check_window(start: datetime, end: datetime) -> None:
        for label, value in (("start", start), ("end", end)):
            if not isinstance(value, datetime):
                raise TypeError(f"{label} must be a datetime, got {type(value).__name__}")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    f"{label} must be timezone-aware; naive datetimes are ambiguous "
                    "and are rejected rather than guessed"
                )
        if start > end:
            raise ValueError(f"start {start.isoformat()} must not be after end {end.isoformat()}")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"


__all__ = [
    "MarketDataProvider",
    "ProviderError",
    "ProviderUnavailableError",
    "ProviderConfigurationError",
]
