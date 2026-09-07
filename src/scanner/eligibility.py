"""Whether a symbol could be researched, and why not when it could not.

Eligibility is read off the assessment the existing pipeline already produced.
It is never re-derived from bar counts, and that is not a stylistic preference:
measuring the real ``build_snapshot`` shows a 50-bar series already yields a
``BULLISH`` assessment, because ``MINIMUM_SUFFICIENT_OBSERVATIONS`` is two and
two hypotheses classify while the third is still warming up. A rule such as
``bar_count < WARMUP_BARS`` would therefore discard symbols that were perfectly
assessable -- the exact defect this module is written to avoid.

The failure mapping is keyed on the *name* of a failure kind rather than on an
imported enum, so this module stays a leaf: no domain package may depend on the
application layer, and importing the error type would invert that direction. The
orchestrator hands in an error; this module only has to recognise its kind.

Nothing here decides whether a symbol is *interesting*. It decides whether there
is anything to look at.
"""

from __future__ import annotations

from src.assessments.assessment import AssessmentState

from .models import EligibilityStatus, ScanErrorCode

#: One scan error code per failure kind the application layer can actually
#: distinguish, keyed by the kind's value. Timeouts and unknown symbols are
#: absent because that layer reports both as ``provider``; separating them would
#: mean classifying on exception text, which changes whenever a message does.
ERROR_FOR_KIND: dict[str, ScanErrorCode] = {
    "provider": ScanErrorCode.PROVIDER_UNAVAILABLE,
    "data_quality": ScanErrorCode.DATA_QUALITY,
    "domain": ScanErrorCode.SYMBOL_MISMATCH,
    "request": ScanErrorCode.REQUEST_INVALID,
    "unexpected": ScanErrorCode.UNEXPECTED,
}


def eligibility_for(snapshot: object) -> EligibilityStatus:
    """Classify a returned research snapshot.

    Three real outcomes, measured against the live contract:

    * ``assessment is None`` -- the provider returned no bars at all.
    * ``state is INSUFFICIENT_DATA`` -- bars existed, but fewer than the policy's
      minimum number of hypotheses classified.
    * anything else -- a usable finding, whatever its direction.
    """
    assessment = getattr(snapshot, "assessment", None)
    if assessment is None:
        return EligibilityStatus.NO_DATA
    if assessment.state is AssessmentState.INSUFFICIENT_DATA:
        return EligibilityStatus.INSUFFICIENT_EVIDENCE
    return EligibilityStatus.ELIGIBLE


def error_for(error: object) -> ScanErrorCode:
    """Map a classified failure to a stable scan error code.

    Accepts anything carrying a ``kind``; an unrecognised kind degrades to
    ``UNEXPECTED`` rather than raising, so a failure kind added later cannot
    take a whole scan down.
    """
    kind = getattr(error, "kind", None)
    name = getattr(kind, "value", kind)
    if not isinstance(name, str):
        return ScanErrorCode.UNEXPECTED
    return ERROR_FOR_KIND.get(name, ScanErrorCode.UNEXPECTED)


__all__ = ["ERROR_FOR_KIND", "eligibility_for", "error_for"]
