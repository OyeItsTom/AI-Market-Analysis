"""The immutable paper portfolio and its application semantics.

``portfolio.apply(intent, policy)`` returns ``(new_portfolio, decision)``.  The
receiver is **never** modified, which is what makes "a rejection changed
nothing" provable by comparing two values rather than by reading the code.

Three outcomes, kept strictly apart
-----------------------------------
* **structurally invalid** — raises. Nothing is returned, nothing changed.
* **policy rejected** — returns ``(self, REJECTED)``. The portfolio is the
  *same value*, and the intent id is **not** recorded as processed.
* **approved** — returns a new portfolio, and the intent id is recorded so it
  cannot be applied twice.

Retry semantics
---------------
A rejected intent is deliberately *not* marked processed, so the same
conceptual intent can be reconsidered after the portfolio or policy changes —
a human closing something and retrying is the expected workflow. An approved
intent is marked processed, so a duplicate submission raises and a retry can
never silently double exposure.

The limitation: nothing authenticates an intent id against its *content*. Two
different intents reusing one id are indistinguishable here; that belongs to a
persistence layer, which Phase 5 does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .intent import CloseIntent, IntentError, OpenLongIntent, PaperIntent, require_identifier
from .policy import RiskDecision, RiskPolicy, _EXACT
from .position import PaperPosition, PositionError, PositionStatus


class PortfolioError(ValueError):
    """Raised when an operation would put the portfolio in an invalid state."""


@dataclass(frozen=True)
class PaperPortfolio:
    """An immutable snapshot of hypothetical exposure.

    Closed positions are **retained**: deleting them would erase the audit
    trail and make the history unreconstructable. They contribute exactly zero
    to open exposure.

    Exposure and open count are computed properties rather than stored totals,
    so they cannot drift out of agreement with the positions they summarise.
    """

    positions: tuple[PaperPosition, ...] = ()
    processed_intent_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "positions", tuple(self.positions))
        set_(self, "processed_intent_ids", tuple(self.processed_intent_ids))

        for position in self.positions:
            if not isinstance(position, PaperPosition):
                raise PortfolioError(
                    f"positions must contain PaperPosition, got {type(position).__name__}"
                )

        ids = [position.position_id for position in self.positions]
        duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
        if duplicates:
            raise PortfolioError(
                f"duplicate position id(s) {duplicates}; ids identify a position for the "
                "life of the portfolio and are never recycled, including after a close"
            )

        for recorded in self.processed_intent_ids:
            # apply() validates ids through the intent, but a portfolio built
            # directly must not be able to hold an id no valid intent could
            # have produced.
            try:
                require_identifier(recorded, "processed intent id")
            except IntentError as exc:
                raise PortfolioError(str(exc)) from None

        intent_ids = list(self.processed_intent_ids)
        duplicate_intents = sorted({i for i in intent_ids if intent_ids.count(i) > 1})
        if duplicate_intents:
            raise PortfolioError(f"duplicate processed intent id(s) {duplicate_intents}")

    # -- derived state ---------------------------------------------------

    @property
    def open_positions(self) -> tuple[PaperPosition, ...]:
        return tuple(position for position in self.positions if position.is_open)

    @property
    def closed_positions(self) -> tuple[PaperPosition, ...]:
        return tuple(position for position in self.positions if not position.is_open)

    @property
    def total_open_notional(self) -> Decimal:
        """Sum of OPEN position notionals. Decimal end to end.

        Computed, never stored: a cached total is a conservation invariant
        waiting to be violated.

        Summed under the engine's pinned context (see :data:`_EXACT`), so a
        caller who has narrowed the global ``decimal`` precision cannot round
        this total down and understate exposure.
        """
        with localcontext(_EXACT):
            return sum((position.notional for position in self.open_positions), Decimal(0))

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)

    @property
    def open_symbols(self) -> tuple[str, ...]:
        return tuple(position.symbol for position in self.open_positions)

    def position(self, position_id: str) -> PaperPosition | None:
        for candidate in self.positions:
            if candidate.position_id == position_id:
                return candidate
        return None

    # -- application -----------------------------------------------------

    def apply(
        self, intent: PaperIntent, policy: RiskPolicy
    ) -> tuple["PaperPortfolio", RiskDecision]:
        """Apply ``intent`` under ``policy``. Returns a new portfolio and a decision.

        Raises
        ------
        PortfolioError
            The intent is structurally impossible against this portfolio:
            a duplicate intent id, a recycled position id, an unknown or
            already-closed close target, or a close before its open.
        """
        if not isinstance(intent, PaperIntent):
            raise PortfolioError(
                f"expected a PaperIntent, got {type(intent).__name__}; paper actions "
                "originate only from an explicit intent"
            )
        if not isinstance(policy, RiskPolicy):
            raise PortfolioError(f"expected a RiskPolicy, got {type(policy).__name__}")

        # An approved intent is recorded as processed, so replaying one is a
        # structural error rather than a second application.
        if intent.intent_id in self.processed_intent_ids:
            raise PortfolioError(
                f"intent {intent.intent_id!r} has already been applied; replaying an "
                "approved intent would double the exposure it created"
            )

        if isinstance(intent, OpenLongIntent):
            return self._apply_open_long(intent, policy)
        if isinstance(intent, CloseIntent):
            return self._apply_close(intent, policy)
        raise PortfolioError(  # pragma: no cover - unreachable while two intents exist
            f"unsupported intent type {type(intent).__name__}"
        )

    def _apply_open_long(
        self, intent: OpenLongIntent, policy: RiskPolicy
    ) -> tuple["PaperPortfolio", RiskDecision]:
        # Structural checks first: a recycled id is corruption, not a policy
        # matter, and must never be reported as a risk rejection.
        if self.position(intent.position_id) is not None:
            raise PortfolioError(
                f"position id {intent.position_id!r} is already used in this portfolio; "
                "ids are never recycled, including after a close"
            )

        decision = policy.evaluate_open(
            intent_id=intent.intent_id,
            notional=intent.notional,
            symbol=intent.symbol,
            current_total_open=self.total_open_notional,
            current_open_count=self.open_position_count,
            open_symbols=self.open_symbols,
        )
        if not decision.approved:
            # Same value back, and the intent id is NOT recorded: the caller
            # may retry this intent once circumstances change.
            return self, decision

        position = PaperPosition(
            position_id=intent.position_id,
            symbol=intent.symbol,
            notional=intent.notional,
            opened_at=intent.intent_created_at,
            research_provenance=intent.research_provenance,
        )
        return (
            PaperPortfolio(
                positions=self.positions + (position,),
                processed_intent_ids=self.processed_intent_ids + (intent.intent_id,),
            ),
            decision,
        )

    def _apply_close(
        self, intent: CloseIntent, policy: RiskPolicy
    ) -> tuple["PaperPortfolio", RiskDecision]:
        target = self.position(intent.target_position_id)
        if target is None:
            raise PortfolioError(
                f"close targets unknown position {intent.target_position_id!r}"
            )
        if not target.is_open:
            raise PortfolioError(
                f"position {target.position_id!r} is already closed; closing it again "
                "would reduce exposure that is no longer there"
            )
        if intent.intent_created_at < target.opened_at:
            raise PortfolioError(
                f"close at {intent.intent_created_at.isoformat()} precedes the position's "
                f"opened_at {target.opened_at.isoformat()}"
            )

        # Closing reduces exposure, so opening limits do not apply.
        decision = policy.evaluate_close(intent_id=intent.intent_id)

        try:
            closed = target.closed(intent.intent_created_at)
        except PositionError as exc:  # pragma: no cover - guarded above
            raise PortfolioError(str(exc)) from None

        positions = tuple(
            closed if position.position_id == target.position_id else position
            for position in self.positions
        )
        return (
            PaperPortfolio(
                positions=positions,
                processed_intent_ids=self.processed_intent_ids + (intent.intent_id,),
            ),
            decision,
        )

    def describe(self) -> str:
        return (
            f"paper portfolio: {self.open_position_count} open "
            f"({len(self.closed_positions)} closed), "
            f"open notional {self.total_open_notional}, "
            f"{len(self.processed_intent_ids)} intents applied"
        )


__all__ = ["PaperPortfolio", "PortfolioError", "PositionStatus"]
