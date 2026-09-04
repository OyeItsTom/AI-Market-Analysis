"""Validation layer for normalized market data.

Design rules
------------
1. **Reject, do not repair.**  Corrupted financial data is not silently
   "fixed".  A bar whose ``high`` is below its ``close`` is evidence that
   something upstream is wrong; quietly rewriting it would hide a data bug
   behind a plausible-looking backtest.  The only transformations this
   codebase performs are deterministic and documented (see
   :class:`~src.data.models.MarketBar`: symbol upper-casing, UTC conversion,
   interval parsing).
2. **Report everything, then fail.**  ``check_*`` functions return *all*
   issues found so a data problem can be inspected in one pass;
   ``validate_*`` functions raise on the first non-empty issue list.
3. **Structural vs. semantic.**  ``MarketBar`` already guarantees finite
   numbers, non-empty text and timezone-aware timestamps.  This module
   re-checks the numeric invariants defensively (cheap, and it keeps this
   module a complete authority) and adds the financial rules that a
   constructor should not be opinionated about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from enum import Enum
from typing import Iterable, Sequence

from .models import Interval, MarketBar


class IssueCode(str, Enum):
    """Stable identifiers for validation failures (safe to assert on)."""

    EMPTY_SYMBOL = "empty_symbol"
    NAIVE_TIMESTAMP = "naive_timestamp"
    NON_FINITE_VALUE = "non_finite_value"
    NON_POSITIVE_PRICE = "non_positive_price"
    NEGATIVE_VOLUME = "negative_volume"
    HIGH_BELOW_LOW = "high_below_low"
    HIGH_BELOW_OPEN = "high_below_open"
    HIGH_BELOW_CLOSE = "high_below_close"
    LOW_ABOVE_OPEN = "low_above_open"
    LOW_ABOVE_CLOSE = "low_above_close"
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"
    UNORDERED_TIMESTAMP = "unordered_timestamp"
    SYMBOL_MISMATCH = "symbol_mismatch"
    INTERVAL_MISMATCH = "interval_mismatch"
    SOURCE_MISMATCH = "source_mismatch"
    WRONG_TYPE = "wrong_type"


@dataclass(frozen=True)
class ValidationIssue:
    """A single problem found in a bar or a sequence of bars."""

    code: IssueCode
    message: str
    index: int | None = None

    def __str__(self) -> str:
        where = "" if self.index is None else f"[bar {self.index}] "
        return f"{where}{self.code.value}: {self.message}"


class ValidationError(ValueError):
    """Raised when market data fails validation.

    Carries the full list of :class:`ValidationIssue` objects in ``.issues``
    so callers can log or classify failures instead of parsing a string.
    """

    def __init__(self, issues: Sequence[ValidationIssue], context: str = "market data"):
        self.issues = list(issues)
        detail = "; ".join(str(issue) for issue in self.issues)
        super().__init__(f"{context} failed validation: {detail}")


# --------------------------------------------------------------------------
# Single-bar validation
# --------------------------------------------------------------------------

_PRICE_FIELDS = ("open", "high", "low", "close")


def check_bar(bar: MarketBar, *, index: int | None = None) -> list[ValidationIssue]:
    """Return every validation issue found in ``bar`` (empty list == valid)."""
    issues: list[ValidationIssue] = []

    def add(code: IssueCode, message: str) -> None:
        issues.append(ValidationIssue(code=code, message=message, index=index))

    if not isinstance(bar, MarketBar):
        add(IssueCode.WRONG_TYPE, f"expected MarketBar, got {type(bar).__name__}")
        return issues

    if not isinstance(bar.symbol, str) or not bar.symbol.strip():
        add(IssueCode.EMPTY_SYMBOL, "symbol is empty")

    tzinfo = getattr(bar.timestamp, "tzinfo", None)
    if tzinfo is None or bar.timestamp.utcoffset() is None:
        add(IssueCode.NAIVE_TIMESTAMP, f"timestamp {bar.timestamp!r} is timezone-naive")

    # Numeric sanity first: comparisons against NaN are meaningless, so if any
    # value is non-finite we report that and skip the relational checks.
    non_finite = False
    for name in (*_PRICE_FIELDS, "volume"):
        value = getattr(bar, name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            add(IssueCode.NON_FINITE_VALUE, f"{name} is not a finite number ({value!r})")
            non_finite = True
    if non_finite:
        return issues

    for name in _PRICE_FIELDS:
        value = float(getattr(bar, name))
        if value <= 0:
            add(
                IssueCode.NON_POSITIVE_PRICE,
                f"{name} must be > 0 for a traded instrument, got {value}",
            )

    if float(bar.volume) < 0:
        add(IssueCode.NEGATIVE_VOLUME, f"volume must be >= 0, got {bar.volume}")

    if bar.high < bar.low:
        add(IssueCode.HIGH_BELOW_LOW, f"high {bar.high} < low {bar.low}")
    if bar.high < bar.open:
        add(IssueCode.HIGH_BELOW_OPEN, f"high {bar.high} < open {bar.open}")
    if bar.high < bar.close:
        add(IssueCode.HIGH_BELOW_CLOSE, f"high {bar.high} < close {bar.close}")
    if bar.low > bar.open:
        add(IssueCode.LOW_ABOVE_OPEN, f"low {bar.low} > open {bar.open}")
    if bar.low > bar.close:
        add(IssueCode.LOW_ABOVE_CLOSE, f"low {bar.low} > close {bar.close}")

    return issues


def is_valid_bar(bar: MarketBar) -> bool:
    """``True`` if ``bar`` passes every single-bar rule."""
    return not check_bar(bar)


def validate_bar(bar: MarketBar) -> MarketBar:
    """Return ``bar`` unchanged, or raise :class:`ValidationError`."""
    issues = check_bar(bar)
    if issues:
        raise ValidationError(issues, context=f"bar {getattr(bar, 'symbol', '?')!r}")
    return bar


# --------------------------------------------------------------------------
# Sequence validation
# --------------------------------------------------------------------------


def check_bars(
    bars: Iterable[MarketBar],
    *,
    expected_symbol: str | None = None,
    expected_interval: Interval | str | None = None,
    expected_source: str | None = None,
    require_sorted: bool = True,
) -> list[ValidationIssue]:
    """Validate a series of bars, per bar and as a sequence.

    Sequence-level rules:

    * every bar shares the same symbol (and matches ``expected_symbol``)
    * every bar shares the same interval (and matches ``expected_interval``)
    * every bar shares the same source (and matches ``expected_source``)
    * timestamps are unique
    * timestamps are strictly increasing when ``require_sorted`` is set

    An empty sequence is *valid*: "no data for this window" is a legitimate
    answer from a provider and is handled by the caller, not by an exception.
    """
    issues: list[ValidationIssue] = []
    bars = list(bars)
    if not bars:
        return issues

    if expected_symbol is not None:
        expected_symbol = expected_symbol.strip().upper()
    if expected_interval is not None:
        expected_interval = Interval.parse(expected_interval)
    if expected_source is not None:
        expected_source = expected_source.strip()

    reference_symbol = expected_symbol
    reference_interval = expected_interval
    reference_source = expected_source
    seen_timestamps: dict[object, int] = {}
    previous_timestamp = None

    for index, bar in enumerate(bars):
        bar_issues = check_bar(bar, index=index)
        issues.extend(bar_issues)
        bar_codes = {issue.code for issue in bar_issues}
        if IssueCode.WRONG_TYPE in bar_codes:
            continue

        if reference_symbol is None:
            reference_symbol = bar.symbol
        elif bar.symbol != reference_symbol:
            issues.append(
                ValidationIssue(
                    IssueCode.SYMBOL_MISMATCH,
                    f"expected symbol {reference_symbol!r}, got {bar.symbol!r}",
                    index=index,
                )
            )

        if reference_interval is None:
            reference_interval = bar.interval
        elif bar.interval != reference_interval:
            issues.append(
                ValidationIssue(
                    IssueCode.INTERVAL_MISMATCH,
                    f"expected interval {reference_interval.value!r}, got {bar.interval.value!r}",
                    index=index,
                )
            )

        # Provenance: bars from two providers are not interchangeable evidence,
        # so a series must not silently mix them. Enforced here (not only in
        # storage) because feature calculations consume series, not files.
        if reference_source is None:
            reference_source = bar.source
        elif bar.source != reference_source:
            issues.append(
                ValidationIssue(
                    IssueCode.SOURCE_MISMATCH,
                    f"expected source {reference_source!r}, got {bar.source!r}",
                    index=index,
                )
            )

        # A bar already reported as naive takes no part in the timestamp checks
        # and does not become the baseline for the bars that follow. Ordering
        # and duplication are unknowable for it, and both ways of handling it
        # here are wrong: comparing it against an aware timestamp raises
        # TypeError (replacing this function's structured report with an
        # unrelated crash), while calling .astimezone() on it silently assumes
        # the machine's local timezone -- a guess this layer must never make.
        if IssueCode.NAIVE_TIMESTAMP in bar_codes:
            continue

        # Safe now: only aware timestamps reach this line, so astimezone() is a
        # genuine conversion rather than an assumption. Comparing in UTC means
        # equivalent instants in different zones are recognised as duplicates.
        key = bar.timestamp.astimezone(timezone.utc)
        if key in seen_timestamps:
            issues.append(
                ValidationIssue(
                    IssueCode.DUPLICATE_TIMESTAMP,
                    f"timestamp {key.isoformat()} already used by bar {seen_timestamps[key]}",
                    index=index,
                )
            )
        else:
            seen_timestamps[key] = index

        if require_sorted and previous_timestamp is not None and key < previous_timestamp:
            issues.append(
                ValidationIssue(
                    IssueCode.UNORDERED_TIMESTAMP,
                    f"timestamp {key.isoformat()} precedes previous bar "
                    f"{previous_timestamp.isoformat()}",
                    index=index,
                )
            )
        previous_timestamp = key

    return issues


def validate_bars(
    bars: Iterable[MarketBar],
    *,
    expected_symbol: str | None = None,
    expected_interval: Interval | str | None = None,
    expected_source: str | None = None,
    require_sorted: bool = True,
) -> list[MarketBar]:
    """Return the bars as a list, or raise :class:`ValidationError`."""
    bars = list(bars)
    issues = check_bars(
        bars,
        expected_symbol=expected_symbol,
        expected_interval=expected_interval,
        expected_source=expected_source,
        require_sorted=require_sorted,
    )
    if issues:
        # getattr, not attribute access: the sequence may contain the very
        # object that was rejected for not being a MarketBar.
        symbol = expected_symbol or (getattr(bars[0], "symbol", None) if bars else None)
        context = f"bar series {symbol or '?'!r}"
        raise ValidationError(issues, context=context)
    return bars


__all__ = [
    "IssueCode",
    "ValidationIssue",
    "ValidationError",
    "check_bar",
    "is_valid_bar",
    "validate_bar",
    "check_bars",
    "validate_bars",
]
