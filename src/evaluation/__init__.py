"""Outcome evaluation: what happened after a research observation.

Answers *"given a research observation, what happened afterwards under a
precisely defined outcome contract?"* -- and nothing else. There is no
simulated position, no transaction cost, no equity curve and no profitability
claim anywhere in this package; a forward return is a property of the market,
not of a strategy.

    ResearchObservation  ->  OutcomeSpec  ->  EvaluatedOutcome  ->  EvaluationSummary
    market point         ->  OutcomeSpec  ->  ForwardMeasurement

A *market point* is ``(symbol, interval, basis, timestamp)``;
:func:`measure_forward` measures one without any producer attached, through
the same code path :func:`evaluate_observations` uses.

See ``docs/research_evaluation.md`` and
``docs/adr/0002-outcome-evaluation-conventions.md``.

**Historical evaluation does not establish future profitability.**
"""

from .evaluate import EvaluationError, evaluate_observations, measure_forward
from .metrics import EvaluationSummary, StateMetrics, summarize
from .outcome import (
    EvaluatedOutcome,
    ForwardMeasurement,
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
    "measure_forward",
    "ForwardMeasurement",
    "EvaluationError",
    "summarize",
    "EvaluationSummary",
    "StateMetrics",
]
