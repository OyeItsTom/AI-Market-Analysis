"""Research assessment — combined research classification, not a trade signal.

Combines aligned Phase 3 research observations into one immutable, auditable
record:

    ResearchObservation(s) -> AssessmentPolicy -> ResearchAssessment

A :class:`ResearchAssessment` says what an exact ensemble of hypotheses
collectively classified at one market point. It is **not** a signal, a
recommendation, a prediction, a probability, a confidence, a measure of
strength, or an instruction of any kind.

**No paper action can arise from this package.** It imports nothing from
``src.portfolio``, and ``src.portfolio`` imports nothing from here, so
``PaperIntent`` and ``PaperAction`` are not in scope in either direction and no
code can turn ``BULLISH`` into ``OPEN_LONG``. A human reads an assessment and
decides independently; "bullish assessment and no paper position" is the
ordinary state, not a special case.

Deliberately absent, and not oversights:

* no score, no confidence, no probability — evidence is reported as integer
  counts, which say what they are
* no weights — and no historical-performance input of any kind, so no outcome
  can leak backwards into a classification (``src.evaluation`` is not imported)
* no clock, no randomness, no network, no persistence, no LLM
* no ``BUY``/``SELL``/``HOLD`` — naming the abstraction after an order type
  invites every later layer to treat a classification as an instruction

Hypothesis agreement is **not** independent confirmation: two of this
repository's three hypotheses are trend-family and share inputs, so
``bullish=3`` is three classifications, not three independent votes.

See ``docs/research_assessment.md`` and
``docs/adr/0004-research-assessment.md``.
"""

from .aggregate import assess
from .assessment import (
    AssessmentCounts,
    AssessmentError,
    AssessmentInput,
    AssessmentReasonCode,
    AssessmentState,
    ResearchAssessment,
)
from .policy import (
    AssessmentAggregationRule,
    AssessmentPolicy,
    HypothesisIdentity,
    PolicyError,
)

__all__ = [
    "assess",
    "AssessmentPolicy",
    "AssessmentAggregationRule",
    "HypothesisIdentity",
    "PolicyError",
    "ResearchAssessment",
    "AssessmentState",
    "AssessmentReasonCode",
    "AssessmentInput",
    "AssessmentCounts",
    "AssessmentError",
]
