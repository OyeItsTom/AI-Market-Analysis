"""Outcome evaluation: what happened after a research observation.

Answers *"given a research observation, what happened afterwards under a
precisely defined outcome contract?"* -- and nothing else. There is no
simulated position, no transaction cost, no equity curve and no profitability
claim anywhere in this package; a forward return is a property of the market,
not of a strategy.

    ResearchObservation  ->  OutcomeSpec  ->  EvaluatedOutcome  ->  EvaluationSummary

See ``docs/research_evaluation.md`` and
``docs/adr/0002-outcome-evaluation-conventions.md``.

**Historical evaluation does not establish future profitability.**
"""

from .evaluate import EvaluationError, evaluate_observations
from .metrics import EvaluationSummary, StateMetrics, summarize
from .outcome import (
    EvaluatedOutcome,
    OutcomeError,
    OutcomeSpec,
    OutcomeStatus,
    OutcomeType,
    PriceField,
    ReferenceConvention,
)

__all__ = [
    "OutcomeSpec",
    "OutcomeType",
    "ReferenceConvention",
    "PriceField",
    "OutcomeStatus",
    "EvaluatedOutcome",
    "OutcomeError",
    "evaluate_observations",
    "EvaluationError",
    "summarize",
    "EvaluationSummary",
    "StateMetrics",
]
