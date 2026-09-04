"""Corporate-action records, kept separate from price bars.

A corporate action is not a property of a bar, so it is not a field on
:class:`~src.data.models.MarketBar`.  It is its own observation: a split or a
cash dividend with an effective date, attributable to a source.

Kept deliberately small.  Two action types are represented because two are
what the Yahoo path actually supplies; the shape extends to more without
rework, but no speculative framework is built here.

Precision note
--------------
Yahoo reports actions against a *date* (the bar they are attached to), not a
precise instant, and gives no announcement time, no ex/record/pay-date
distinction, and no currency for dividends.  This module therefore stores the
bar timestamp it arrived on and nothing more.  Inventing an ex-date or a
settlement time we were not given would be fabricated precision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ActionType(str, Enum):
    """The kinds of corporate action this system represents."""

    #: Share split. ``value`` is the split ratio: 4.0 means 4-for-1, i.e. one
    #: old share became four. A reverse split is a ratio below 1.0.
    SPLIT = "split"

    #: Cash dividend. ``value`` is the amount per share, in the instrument's
    #: quote currency (which the source does not tell us -- see module note).
    CASH_DIVIDEND = "cash_dividend"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class CorporateActionError(ValueError):
    """Raised when a corporate-action record is malformed."""


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """One corporate action as reported by a source.

    Attributes
    ----------
    symbol:
        Instrument the action applies to, upper-cased.
    effective_time:
        The bar timestamp the source attached the action to, in UTC. This is
        as precise as the source is; it is **not** an announcement or
        settlement time.
    action_type:
        See :class:`ActionType`.
    value:
        Split ratio, or dividend amount per share. Must be finite and
        strictly positive: a zero or negative split ratio is meaningless, and
        a source reporting one is reporting a fault, not an event.
    source:
        Provider the record came from, for provenance.
    """

    symbol: str
    effective_time: datetime
    action_type: ActionType
    value: float
    source: str

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise CorporateActionError("symbol must not be empty")
        set_(self, "symbol", symbol)

        source = str(self.source).strip()
        if not source:
            raise CorporateActionError("source must not be empty")
        set_(self, "source", source)

        set_(self, "action_type", ActionType(self.action_type))

        if not isinstance(self.effective_time, datetime):
            raise CorporateActionError(
                f"effective_time must be a datetime, got {type(self.effective_time).__name__}"
            )
        if self.effective_time.tzinfo is None or self.effective_time.utcoffset() is None:
            raise CorporateActionError(
                "effective_time must be timezone-aware; naive timestamps are ambiguous"
            )
        set_(self, "effective_time", self.effective_time.astimezone(timezone.utc))

        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise CorporateActionError(
                f"value must be a real number, got {type(self.value).__name__}"
            )
        value = float(self.value)
        if not math.isfinite(value):
            raise CorporateActionError(f"value must be finite, got {self.value!r}")
        if value <= 0:
            raise CorporateActionError(
                f"{self.action_type} value must be > 0, got {value}; a non-positive "
                "split ratio or dividend is a source fault, not an event"
            )
        set_(self, "value", value)


__all__ = ["ActionType", "CorporateAction", "CorporateActionError"]
