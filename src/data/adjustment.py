"""Explicit, pure adjustment of a raw price series.

    RAW BarSeries  +  AdjustmentData  --[ adjust() ]-->  derived BarSeries

Design rules (see ``docs/adr/0001-price-basis-and-corporate-actions.md``):

* **Raw is the source of record.** ``adjust`` never modifies its input; it
  returns a new series. Raw bars are never overwritten on disk.
* **Pure.** No network, no clock, no global state. The same inputs always
  produce the same output.
* **Total, not partial.** Every bar must have a factor. A series adjusted for
  only some of its bars would splice two price bases together inside one
  series -- the exact defect this layer exists to prevent -- so a missing
  factor is an error, never a silent 1.0.
* **Not idempotent by design.** Adjusting an already-adjusted series raises.
  Double adjustment is silent corruption: the numbers stay plausible.
* **Volume is never touched.** See the caveat on :func:`adjust`.

Point-in-time warning
---------------------
An adjusted series is **not** point-in-time safe. The factor attached to a
bar in 2019 depends on every split and dividend that has happened *since*,
including ones that had not occurred at that date. An adjusted series is a
present-day restatement of history, useful for computing economically
comparable returns, and wrong for answering "what would a screen have shown
on that date". A backtest that assumes the latter from an adjusted series is
using future information. This is documented, not solved, in Phase 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence

from .corporate_actions import CorporateAction
from .models import Interval, MarketBar
from .series import BarSeries, PriceBasis


class AdjustmentError(ValueError):
    """Raised when an adjustment cannot be performed safely."""


@dataclass(frozen=True)
class AdjustmentData:
    """Everything a provider knows about adjusting one series.

    ``factors`` maps a bar's timestamp to the multiplier applied to its OHLC
    prices. For the Yahoo path the factor is ``Adj Close / Close``, which was
    verified against the installed yfinance implementation to encode dividends
    as well as splits -- hence ``produces_basis`` of
    ``SPLIT_AND_DIVIDEND_ADJUSTED``.

    ``actions`` carries the underlying corporate-action records. They are not
    required to apply the factors; they are retained so the adjustment is
    auditable and so a different basis can be derived later without refetching.
    """

    symbol: str
    source: str
    interval: Interval
    produces_basis: PriceBasis
    factors: Mapping[datetime, float] = field(default_factory=dict)
    actions: tuple[CorporateAction, ...] = ()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "symbol", str(self.symbol).strip().upper())
        set_(self, "source", str(self.source).strip())
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "produces_basis", PriceBasis(self.produces_basis))
        set_(self, "actions", tuple(self.actions))

        if self.produces_basis is PriceBasis.RAW:
            raise AdjustmentError(
                "produces_basis must be a derived basis; adjusting to RAW is meaningless"
            )

        normalized: dict[datetime, float] = {}
        for timestamp, factor in dict(self.factors).items():
            if not isinstance(timestamp, datetime):
                raise AdjustmentError(
                    f"factor key must be a datetime, got {type(timestamp).__name__}"
                )
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise AdjustmentError(f"factor timestamp {timestamp!r} must be timezone-aware")
            normalized[timestamp.astimezone(timezone.utc)] = _check_factor(factor, timestamp)
        set_(self, "factors", normalized)

        for action in self.actions:
            if action.symbol != self.symbol:
                raise AdjustmentError(
                    f"corporate action for {action.symbol!r} does not belong to {self.symbol!r}"
                )
            if action.source != self.source:
                raise AdjustmentError(
                    f"corporate action from {action.source!r} does not belong to a "
                    f"{self.source!r} adjustment set"
                )


def _check_factor(factor: object, timestamp: datetime) -> float:
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise AdjustmentError(
            f"adjustment factor at {timestamp.isoformat()} must be a real number, "
            f"got {type(factor).__name__}"
        )
    value = float(factor)
    if not math.isfinite(value):
        raise AdjustmentError(
            f"adjustment factor at {timestamp.isoformat()} is not finite ({factor!r}); "
            "a NaN factor usually means the source reported no adjusted close"
        )
    if value <= 0:
        raise AdjustmentError(
            f"adjustment factor at {timestamp.isoformat()} must be > 0, got {value}"
        )
    return value


def adjust(series: BarSeries, data: AdjustmentData) -> BarSeries:
    """Return a NEW series with OHLC scaled by ``data``'s factors.

    ``series`` is not modified.

    Volume is deliberately carried across **unchanged**. Yahoo does not adjust
    volume either, and manufacturing a share count nobody reported would be
    exactly the kind of silent invention this codebase forbids. The
    consequence, which callers must respect:

        adjusted price x reported volume is NOT historical traded notional.

    Any feature that needs price-volume economic consistency must handle this
    itself; the data layer will not paper over it.

    Raises
    ------
    AdjustmentError
        The series is already adjusted, the metadata does not match, or a bar
        has no factor.
    """
    if not isinstance(series, BarSeries):
        raise AdjustmentError(f"expected a BarSeries, got {type(series).__name__}")

    if series.basis is not PriceBasis.RAW:
        raise AdjustmentError(
            f"refusing to adjust a series that is already {series.basis.value!r}; "
            "adjusting twice silently corrupts prices while leaving them plausible. "
            "Adjust the raw series instead."
        )
    if data.produces_basis is PriceBasis.RAW:  # pragma: no cover - blocked in AdjustmentData
        raise AdjustmentError("adjustment must produce a derived basis")

    mismatches = [
        f"{label} {mine!r} != {theirs!r}"
        for label, mine, theirs in (
            ("symbol", series.symbol, data.symbol),
            ("source", series.source, data.source),
            ("interval", series.interval.value, data.interval.value),
        )
        if mine != theirs
    ]
    if mismatches:
        raise AdjustmentError(
            f"adjustment data does not belong to this series: {'; '.join(mismatches)}"
        )

    missing = [bar.timestamp for bar in series if bar.timestamp not in data.factors]
    if missing:
        shown = ", ".join(timestamp.isoformat() for timestamp in missing[:3])
        raise AdjustmentError(
            f"no adjustment factor for {len(missing)} of {len(series)} bars (e.g. {shown}); "
            "a partially adjusted series would mix two price bases, so this is refused "
            "rather than defaulting the gaps to 1.0"
        )

    adjusted: list[MarketBar] = []
    for bar in series:
        factor = data.factors[bar.timestamp]
        adjusted.append(
            MarketBar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=bar.open * factor,
                high=bar.high * factor,
                low=bar.low * factor,
                close=bar.close * factor,
                volume=bar.volume,  # deliberately unscaled -- see docstring
                interval=bar.interval,
                source=bar.source,
            )
        )

    provenance = (
        f"derived from raw {series.symbol} {series.interval.value} ({series.source}) "
        f"by adjustment.adjust() using {len(data.factors)} factors and "
        f"{len(data.actions)} corporate action(s); volume left unadjusted"
    )
    return series.with_bars(adjusted, basis=data.produces_basis, provenance=provenance)


def factors_from_adjusted_close(
    raw_closes: Sequence[tuple[datetime, float]],
    adjusted_closes: Sequence[tuple[datetime, float]],
) -> dict[datetime, float]:
    """Derive per-bar factors as ``adjusted_close / raw_close``.

    Both sequences must cover the same timestamps. A zero or non-finite raw
    close makes the ratio undefined and raises rather than producing an
    infinity that would silently destroy a price series.
    """
    raw = {timestamp: close for timestamp, close in raw_closes}
    adjusted = {timestamp: close for timestamp, close in adjusted_closes}

    only_raw = sorted(raw.keys() - adjusted.keys())
    only_adjusted = sorted(adjusted.keys() - raw.keys())
    if only_raw or only_adjusted:
        raise AdjustmentError(
            f"raw and adjusted closes cover different timestamps "
            f"({len(only_raw)} raw-only, {len(only_adjusted)} adjusted-only); "
            "cannot derive factors"
        )

    factors: dict[datetime, float] = {}
    for timestamp, close in raw.items():
        if not math.isfinite(close) or close == 0:
            raise AdjustmentError(
                f"raw close at {timestamp.isoformat()} is {close!r}; "
                "the adjustment ratio is undefined"
            )
        factors[timestamp] = _check_factor(adjusted[timestamp] / close, timestamp)
    return factors


__all__ = [
    "AdjustmentData",
    "AdjustmentError",
    "adjust",
    "factors_from_adjusted_close",
]
