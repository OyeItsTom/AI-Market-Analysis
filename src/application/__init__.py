"""Application layer: orchestration between the dashboard and the domain.

    dashboard  ->  application  ->  Phase 1-6 domain

This package sequences existing public APIs and owns the dashboard's own
configuration -- supported intervals, history windows, the fixed ensemble, the
assessment policy, and paper session state. It contains **no research rules**:
every state, count and reason code it passes on was produced by a domain
module.

It imports no UI framework, so everything here is testable headlessly. And
:mod:`src.application.paper` imports nothing from :mod:`src.assessments`, so
the module that mutates paper state cannot see a research assessment at all --
there is no code path from ``BULLISH`` to ``OPEN_LONG``.
"""

from .errors import ApplicationError, FailureKind, FailureReport, classify
from .paper import (
    DEFAULT_RISK_POLICY,
    PaperSession,
    PendingIntentIds,
    build_provenance,
    parse_notional,
)
from .snapshot import (
    BASIS,
    ENSEMBLE,
    HISTORY_LABELS,
    HISTORY_WINDOWS,
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    SUPPORTED_INTERVALS,
    WARMUP_BARS,
    ResearchSnapshot,
    build_ensemble,
    default_provider,
    display_names,
    build_policy,
    build_snapshot,
    deduplicate_specs,
    history_window,
)

__all__ = [
    "ApplicationError",
    "FailureKind",
    "FailureReport",
    "classify",
    "ResearchSnapshot",
    "build_snapshot",
    "build_ensemble",
    "default_provider",
    "display_names",
    "build_policy",
    "deduplicate_specs",
    "history_window",
    "SUPPORTED_INTERVALS",
    "HISTORY_WINDOWS",
    "HISTORY_LABELS",
    "WARMUP_BARS",
    "ENSEMBLE",
    "MINIMUM_SUFFICIENT_OBSERVATIONS",
    "BASIS",
    "PaperSession",
    "PendingIntentIds",
    "DEFAULT_RISK_POLICY",
    "parse_notional",
    "build_provenance",
]
