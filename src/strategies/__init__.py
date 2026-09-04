"""Research hypothesis framework.

Expresses deterministic market-research hypotheses that a later evaluation
system can test. This package contains **no** trading logic: no orders, no
positions, no profit measurement, no recommendations.

A :class:`~src.strategies.research.ResearchState` is a classification of
evidence, not an instruction and not a prediction. Phase 3 answers "what did
hypothesis X classify at each valid evidence point?" -- it does not, and cannot,
say what happened afterwards.

Dependency direction (enforced by construction, see :mod:`.base`)::

    MarketBar -> BarSeries -> feature engine -> research hypothesis

A hypothesis never reaches a provider, the network, the bars, or any bar other
than the one it is classifying.
"""

from .base import HypothesisError, ResearchHypothesis
from .evidence import (
    EvidenceError,
    EvidenceSet,
    EvidenceWindow,
    build_evidence,
    resolve_feature_spec,
)
from .hypotheses import MomentumInTrendContext, TrendAlignment, TrendCrossover
from .research import ReasonCode, ResearchObservation, ResearchState
from .spec import FeatureSpec, HypothesisSpec, SpecError

__all__ = [
    "ResearchHypothesis",
    "HypothesisError",
    "EvidenceSet",
    "EvidenceWindow",
    "EvidenceError",
    "build_evidence",
    "resolve_feature_spec",
    "FeatureSpec",
    "HypothesisSpec",
    "SpecError",
    "ResearchState",
    "ReasonCode",
    "ResearchObservation",
    "TrendAlignment",
    "MomentumInTrendContext",
    "TrendCrossover",
]
