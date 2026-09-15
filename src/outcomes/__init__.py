"""Outcome tracking: what happened after a deterministic research claim.

Phase 4 (``src.evaluation``) *measures* forward outcomes and forgets them.
This package *tracks* them: it records what a research snapshot claimed at
the moment it claimed it, and defines the immutable record a completed
Phase 4 measurement of that claim must take. Identity is deterministic and
process-independent, so the same claim and the same measurement have the
same key on every machine, forever.

    ResearchObservation / ResearchAssessment  ->  TrackedArtifact
    TrackedArtifact + Phase 4 measurement     ->  OutcomeRecord

:func:`evaluate_artifact` performs that second step: given an artifact, a
series of settled bars, an outcome specification and an explicit evaluation
clock, it asks Phase 4 to measure the market point and returns either one
:class:`OutcomeRecord` or a deterministic reason there is none.

Nothing here predicts, recommends, scores, trades, or reads a clock, a file
or a network. A forward return is a property of the market, not of a
strategy, and **historical outcomes do not establish future profitability.**
"""

from .identity import (
    OutcomeTrackingError,
    assessment_artifact_key,
    bar_fingerprint,
    bars_fingerprint,
    observation_artifact_key,
    outcome_key,
)
from .models import (
    EVALUATION_VERSION,
    SUPPORTED_EVALUATION_VERSIONS,
    ArtifactKind,
    ArtifactOrigin,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
    TrackedArtifact,
)
from .tracking import RefusalReason, TrackingResult, TrackingStatus, evaluate_artifact

__all__ = [
    "ArtifactKind",
    "ArtifactOrigin",
    "TrackedArtifact",
    "ObservationArtifact",
    "AssessmentArtifact",
    "OutcomeRecord",
    "OutcomeTrackingError",
    "EVALUATION_VERSION",
    "SUPPORTED_EVALUATION_VERSIONS",
    "observation_artifact_key",
    "assessment_artifact_key",
    "outcome_key",
    "bar_fingerprint",
    "bars_fingerprint",
    "TrackingStatus",
    "RefusalReason",
    "TrackingResult",
    "evaluate_artifact",
]
