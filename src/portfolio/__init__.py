"""Paper position and risk domain — PAPER ONLY, no execution.

Models hypothetical exposure recorded by an explicit human decision:

    explicit PaperIntent -> structural validation -> RiskPolicy -> RiskDecision
                                                                -> new PaperPortfolio

**A research classification never enters this flow.** This package imports
nothing from ``src.strategies`` or ``src.evaluation``, so ``ResearchState`` is
not in scope and no code here can turn ``BULLISH`` into an action. "Bullish
research and no paper position" is the ordinary state, not a special case.

Deliberately absent, and not oversights:

* no broker, order, execution, account or balance of any kind
* no price — Phase 5 has no price semantics; Phase 4's ``NEXT_BAR_OPEN`` is an
  evaluation convention and is not reused here
* no cash, no P&L, no costs, no slippage, no performance of any kind
* no ``OPEN_SHORT`` — long-only, and a short is not representable
* no persistence, no network, no clock, no randomness

See ``docs/paper_risk_engine.md`` and
``docs/adr/0003-paper-position-risk-engine.md``.
"""

from .intent import (
    CloseIntent,
    IntentError,
    OpenLongIntent,
    PaperAction,
    PaperIntent,
    ResearchProvenance,
)
from .policy import (
    PolicyError,
    RiskDecision,
    RiskOutcome,
    RiskPolicy,
    RiskReasonCode,
    canonical_decimal,
)
from .portfolio import PaperPortfolio, PortfolioError
from .position import PaperPosition, PositionError, PositionStatus

__all__ = [
    "PaperAction",
    "PaperIntent",
    "OpenLongIntent",
    "CloseIntent",
    "ResearchProvenance",
    "IntentError",
    "RiskPolicy",
    "RiskDecision",
    "RiskOutcome",
    "RiskReasonCode",
    "PolicyError",
    "canonical_decimal",
    "PaperPosition",
    "PositionStatus",
    "PositionError",
    "PaperPortfolio",
    "PortfolioError",
]
