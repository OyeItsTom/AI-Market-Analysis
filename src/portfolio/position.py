"""The immutable paper position record.

A :class:`PaperPosition` records hypothetical **exposure** in a symbol. It has
no price, no quantity, no market value and no result:

* **no price** — Phase 5 has no price semantics at all. Phase 4's
  ``NEXT_BAR_OPEN`` is an *evaluation* convention and must not silently become
  a paper entry price; the two answer different questions.
* **no cash, no P&L** — a close records that exposure ended, not what it
  earned. Adding an entry and an exit price would put a cost-free, unlabelled
  return one subtraction away.

State machine: ``OPEN -> CLOSED``. Nothing else. Order-lifecycle states such
as PENDING/FILLED/CANCELLED belong to execution systems, and including them is
how a paper domain drifts into looking like one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .intent import (
    IntentError,
    ResearchProvenance,
    require_aware_timestamp,
    require_identifier,
    require_notional,
    require_symbol,
)


class PositionError(ValueError):
    """Raised when a paper position would be structurally invalid."""


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class PaperPosition:
    """One hypothetical long exposure. Immutable.

    ``closed_at`` is the caller-supplied timestamp of the closing intent, and
    must not precede ``opened_at``. Opening research provenance, if any, is
    preserved through a close and never rewritten.
    """

    position_id: str
    symbol: str
    notional: Decimal
    opened_at: datetime
    status: PositionStatus = PositionStatus.OPEN
    closed_at: datetime | None = None
    research_provenance: ResearchProvenance | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        try:
            set_(self, "position_id", require_identifier(self.position_id, "position_id"))
            set_(self, "symbol", require_symbol(self.symbol))
            set_(self, "notional", require_notional(self.notional))
            set_(self, "opened_at", require_aware_timestamp(self.opened_at, "opened_at"))
        except IntentError as exc:
            raise PositionError(str(exc)) from None

        set_(self, "status", PositionStatus(self.status))

        if self.status is PositionStatus.OPEN:
            if self.closed_at is not None:
                raise PositionError(
                    "an OPEN position must not carry closed_at; the record would describe "
                    "a close that its own status says never happened"
                )
        else:
            if self.closed_at is None:
                raise PositionError("a CLOSED position must carry closed_at")
            try:
                set_(self, "closed_at", require_aware_timestamp(self.closed_at, "closed_at"))
            except IntentError as exc:
                raise PositionError(str(exc)) from None
            if self.closed_at < self.opened_at:
                raise PositionError(
                    f"closed_at {self.closed_at.isoformat()} precedes opened_at "
                    f"{self.opened_at.isoformat()}; a position cannot close before it opened"
                )

        if self.research_provenance is not None and not isinstance(
            self.research_provenance, ResearchProvenance
        ):
            raise PositionError(
                "research_provenance must be a ResearchProvenance or None, got "
                f"{type(self.research_provenance).__name__}"
            )

    @property
    def is_open(self) -> bool:
        return self.status is PositionStatus.OPEN

    @property
    def open_notional(self) -> Decimal:
        """Notional contributing to current exposure. Zero once closed."""
        return self.notional if self.is_open else Decimal(0)

    def closed(self, closed_at: datetime) -> "PaperPosition":
        """Return a CLOSED copy. The receiver is never modified.

        Everything about the opening is retained -- id, symbol, notional,
        opened_at and provenance -- because a close records that exposure
        ended, not that the position became a different one.
        """
        if not self.is_open:
            raise PositionError(
                f"position {self.position_id!r} is already {self.status.value}; "
                "closing it twice would double-count the reduction in exposure"
            )
        return replace(self, status=PositionStatus.CLOSED, closed_at=closed_at)

    def describe(self) -> str:
        when = "" if self.closed_at is None else f" closed {self.closed_at.isoformat()}"
        return (
            f"{self.position_id} {self.symbol} notional={self.notional} "
            f"[{self.status.value}] opened {self.opened_at.isoformat()}{when}"
        )


__all__ = ["PaperPosition", "PositionStatus", "PositionError"]
