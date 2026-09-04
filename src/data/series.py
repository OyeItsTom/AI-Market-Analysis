"""``BarSeries`` -- the safe unit of market data for research code.

Phase 1 established :class:`~src.data.models.MarketBar` as the canonical
record.  A bare ``list[MarketBar]`` is not a safe research input, though: it
can silently mix symbols, intervals, providers, or -- once adjusted series
exist -- price bases.  Every one of those produces plausible-looking numbers
rather than an error.

``BarSeries`` is the boundary that makes those mistakes impossible.  It is a
frozen container that guarantees, at construction:

* exactly one symbol
* exactly one interval
* exactly one source (provider)
* exactly one :class:`PriceBasis`
* timestamps unique and strictly increasing
* every bar individually valid

Feature calculations consume ``BarSeries``, never a loose list.

Price basis
-----------
See ``docs/adr/0001-price-basis-and-corporate-actions.md``.  In short: raw
OHLCV is the source of record and is never overwritten; an adjusted series is
*derived*, explicitly labelled, and never silently comparable with a raw one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, Iterator, Sequence

from .models import Interval, MarketBar
from .validation import ValidationError, validate_bars


class PriceBasis(str, Enum):
    """What the OHLC values in a series mean.

    Two series with different bases must never be compared, concatenated or
    fed to the same calculation: the numbers are denominated differently.

    ``RAW``
        Prices as actually traded and reported, unadjusted.  This is the
        source of record and the only basis that is ever stored as primary
        data.  A stock split appears in a raw series as a large mechanical
        price change, because that is what happened to the quoted price.

    ``SPLIT_AND_DIVIDEND_ADJUSTED``
        Prices scaled by a historical adjustment factor that removes the
        mechanical effect of **both** share splits **and** cash dividends, so
        that a return computed across a corporate action reflects the economic
        outcome of holding the security rather than an artefact of share
        arithmetic.  Commonly called a "total return" basis.

        The name is deliberately explicit.  For the Yahoo path this basis is
        derived from ``Adj Close / Close``, and that factor was verified
        against the installed yfinance implementation to encode dividends as
        well as splits -- see the ADR.  Calling it ``SPLIT_ADJUSTED`` would
        misdescribe the transformation.

    A split-only basis is *derivable* from the corporate-action records we now
    capture, but is deliberately not defined here until something needs it:
    an unimplemented enum member is an invitation to mislabel data.
    """

    RAW = "raw"
    SPLIT_AND_DIVIDEND_ADJUSTED = "split_and_dividend_adjusted"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_derived(self) -> bool:
        """``True`` for a basis that is computed from raw data, not observed."""
        return self is not PriceBasis.RAW


class SeriesError(ValueError):
    """Raised when a group of bars cannot form a coherent series."""


@dataclass(frozen=True)
class BarSeries:
    """A validated, homogeneous, immutable run of bars for one instrument.

    Construct with :meth:`from_bars`, which infers the metadata from the bars
    themselves and then verifies it.  The direct constructor is available for
    callers that want to assert the metadata explicitly.

    ``bars`` is stored as a tuple, so a series cannot be mutated, appended to,
    or reordered in place after it has been validated.
    """

    symbol: str
    interval: Interval
    source: str
    basis: PriceBasis
    bars: tuple[MarketBar, ...] = field(default=())

    #: Free-text note describing how a derived series was produced. Empty for
    #: raw series. Never parsed -- it exists so a researcher reading a series
    #: can see where its numbers came from.
    provenance: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "symbol", str(self.symbol).strip().upper())
        set_(self, "source", str(self.source).strip())
        set_(self, "bars", tuple(self.bars))

        if not self.symbol:
            raise SeriesError("series symbol must not be empty")
        if not self.source:
            raise SeriesError("series source must not be empty")

        try:
            validate_bars(
                list(self.bars),
                expected_symbol=self.symbol,
                expected_interval=self.interval,
                expected_source=self.source,
                require_sorted=True,
            )
        except ValidationError as exc:
            raise SeriesError(
                f"cannot build a {self.symbol} {self.interval.value} series from these bars: {exc}"
            ) from exc

    # -- construction ----------------------------------------------------

    @classmethod
    def from_bars(
        cls,
        bars: Iterable[MarketBar],
        *,
        basis: PriceBasis | str,
        provenance: str = "",
        symbol: str | None = None,
        interval: Interval | str | None = None,
        source: str | None = None,
    ) -> "BarSeries":
        """Build a series, inferring metadata from ``bars`` where not given.

        An empty iterable requires ``symbol``, ``interval`` and ``source`` to
        be supplied: there is nothing to infer them from, and guessing would
        produce a series that claims to be about an instrument it has never
        seen.
        """
        bars = tuple(bars)
        if not bars:
            if symbol is None or interval is None or source is None:
                raise SeriesError(
                    "an empty series needs explicit symbol, interval and source; "
                    "they cannot be inferred from no bars"
                )
        else:
            first = bars[0]
            if not isinstance(first, MarketBar):
                raise SeriesError(f"expected MarketBar, got {type(first).__name__}")
            symbol = first.symbol if symbol is None else symbol
            interval = first.interval if interval is None else interval
            source = first.source if source is None else source

        return cls(
            symbol=symbol,
            interval=interval,
            source=source,
            basis=PriceBasis(basis),
            bars=bars,
            provenance=provenance,
        )

    def with_bars(
        self,
        bars: Iterable[MarketBar],
        *,
        basis: PriceBasis | str | None = None,
        provenance: str | None = None,
    ) -> "BarSeries":
        """Return a NEW series with different bars, keeping the metadata.

        Used by transformations. The receiver is never modified.
        """
        return BarSeries(
            symbol=self.symbol,
            interval=self.interval,
            source=self.source,
            basis=self.basis if basis is None else PriceBasis(basis),
            bars=tuple(bars),
            provenance=self.provenance if provenance is None else provenance,
        )

    # -- read-only access ------------------------------------------------

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self) -> Iterator[MarketBar]:
        return iter(self.bars)

    def __getitem__(self, index: int) -> MarketBar:
        return self.bars[index]

    @property
    def timestamps(self) -> tuple[datetime, ...]:
        return tuple(bar.timestamp for bar in self.bars)

    def values(self, field_name: str) -> tuple[float, ...]:
        """Extract one OHLCV column, in order.

        ``field_name`` must be one of open/high/low/close/volume; anything
        else raises rather than returning an attribute that merely happens to
        exist on the dataclass.
        """
        if field_name not in PRICE_FIELDS and field_name != "volume":
            allowed = ", ".join((*PRICE_FIELDS, "volume"))
            raise SeriesError(f"unknown field {field_name!r}; expected one of: {allowed}")
        return tuple(getattr(bar, field_name) for bar in self.bars)

    def prefix(self, count: int) -> "BarSeries":
        """Return the first ``count`` bars as a new series (test/analysis aid)."""
        if count < 0:
            raise SeriesError("prefix count must not be negative")
        return self.with_bars(self.bars[:count])

    # -- compatibility ---------------------------------------------------

    def require_compatible(self, other: "BarSeries") -> None:
        """Raise unless ``other`` describes the same instrument on the same basis.

        Guards any operation that combines two series. Price basis is included
        deliberately: a raw and an adjusted series for the same symbol are
        *not* interchangeable, and combining them silently is one of the
        failure modes this module exists to prevent.
        """
        mismatches = [
            f"{label} {mine!r} != {theirs!r}"
            for label, mine, theirs in (
                ("symbol", self.symbol, other.symbol),
                ("interval", self.interval.value, other.interval.value),
                ("source", self.source, other.source),
                ("basis", self.basis.value, other.basis.value),
            )
            if mine != theirs
        ]
        if mismatches:
            raise SeriesError(f"incompatible series: {'; '.join(mismatches)}")

    def describe(self) -> str:
        """One-line human summary, used in error messages and provenance."""
        span = (
            f"{self.bars[0].timestamp.isoformat()}..{self.bars[-1].timestamp.isoformat()}"
            if self.bars
            else "empty"
        )
        return (
            f"{self.symbol} {self.interval.value} [{self.basis.value}] "
            f"from {self.source} ({len(self.bars)} bars, {span})"
        )


PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close")

__all__ = ["BarSeries", "PriceBasis", "SeriesError", "PRICE_FIELDS"]
