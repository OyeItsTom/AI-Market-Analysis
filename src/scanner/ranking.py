"""Ordering research candidates by the shape of their evidence.

There is no score. Phase 6 states plainly that a handful of integer
classifications cannot yield a confidence, and a weighted composite over four
small counts would manufacture exactly the pseudo-precision it refuses. Ordering
is lexicographic over an enum and integers, and every step of it is explicable
in a sentence.

Ordering answers *which research cases are structurally interesting to inspect*.
It does not answer which security is a better investment, and no caller may
present it as though it did.

Two rules are load-bearing and easy to get wrong:

**A modifier is not a category.** ``INSUFFICIENT_INPUTS_EXCLUDED`` appears
alongside bullish, bearish, conflicted, neutral *and* insufficient results --
exhaustive enumeration of all 64 hypothesis-state combinations confirms it. Any
rule that took "the first reason code" would mis-categorise roughly a third of
real assessments.

**Direction is never a preference.** ``BULLISH`` and ``BEARISH`` produce
identical categories and identical sort keys. Direction appears nowhere in the
comparator, so a bearish case can never sort below an otherwise identical
bullish one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from src.assessments.assessment import AssessmentReasonCode, AssessmentState

from .models import CATEGORY_ORDER, StructuralCategory, SymbolScanResult

#: Reason codes that mean "every input that classified agreed on a direction".
_UNANIMOUS_DIRECTIONAL = frozenset(
    {AssessmentReasonCode.UNANIMOUS_BULLISH, AssessmentReasonCode.UNANIMOUS_BEARISH}
)

_CATEGORY_RANK = {category: index for index, category in enumerate(CATEGORY_ORDER)}

#: Sorts after every real timestamp without ever comparing datetime to None.
_NO_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


def category_for(
    state: AssessmentState | None,
    reason_codes: Sequence[AssessmentReasonCode] = (),
) -> StructuralCategory:
    """The evidence structure behind one assessment.

    Decided from the state plus one membership test on reason-code *identity* --
    never by matching text, never by position in the tuple. The mapping is total
    over every combination the assessment engine can produce.
    """
    if state is None or state is AssessmentState.INSUFFICIENT_DATA:
        return StructuralCategory.NOT_ASSESSABLE
    if state is AssessmentState.CONFLICTED:
        return StructuralCategory.CONFLICTED
    if state is AssessmentState.NEUTRAL:
        return StructuralCategory.NEUTRAL
    # BULLISH or BEARISH: unanimity is what separates the two directional
    # categories. INSUFFICIENT_INPUTS_EXCLUDED may also be present and is
    # deliberately ignored -- it says a hypothesis abstained, not how the rest
    # of the evidence stood.
    if any(code in _UNANIMOUS_DIRECTIONAL for code in reason_codes):
        return StructuralCategory.UNANIMOUS_DIRECTIONAL
    return StructuralCategory.DIRECTIONAL_WITH_NEUTRAL


def rank_key(result: SymbolScanResult) -> tuple:
    """Deterministic sort key. Direction is deliberately absent.

    1. category, in research-inspection order
    2. classifying-hypothesis count, descending -- more evidence to read first
    3. latest bar, descending -- fresher data first; missing sorts last
    4. symbol, ascending -- the final tie-break, so two runs over identical
       data produce identical order
    """
    when = result.latest_bar_open or _NO_TIMESTAMP
    return (
        _CATEGORY_RANK[result.category],
        -result.classifying_count,
        -when.timestamp(),
        result.symbol,
    )


def order_results(results: Sequence[SymbolScanResult]) -> tuple[SymbolScanResult, ...]:
    """Every result, ordered. Nothing is dropped."""
    return tuple(sorted(results, key=rank_key))


def ordered_rows(results: Sequence[SymbolScanResult]) -> tuple[SymbolScanResult, ...]:
    """Only the assessable rows, ordered -- what the research table shows."""
    return order_results([result for result in results if result.is_eligible])


__all__ = ["category_for", "rank_key", "order_results", "ordered_rows"]
