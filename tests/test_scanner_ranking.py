"""Phase 10 structural categories and ordering.

The category rules are pinned against the **real** assessment engine, not
against prose: every test below drives ``assess`` with concrete hypothesis
states and checks what actually comes back. The mapping must be total, because
an unmapped combination would surface as a crash during a scan.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

from src.application.snapshot import build_ensemble, build_policy
from src.assessments import assess
from src.assessments.assessment import (
    AssessmentCounts,
    AssessmentReasonCode,
    AssessmentState,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.scanner.models import (
    CATEGORY_ORDER,
    EligibilityStatus,
    ScanErrorCode,
    StructuralCategory,
    SymbolScanResult,
)
from src.scanner.ranking import category_for, order_results, ordered_rows, rank_key
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
ANY_REASON = list(ReasonCode)[0]

HYPOTHESES = build_ensemble()
POLICY = build_policy(HYPOTHESES)


def assessment_for(states):
    """Run the real assessment engine over one combination of hypothesis states."""
    observations = tuple(
        ResearchObservation(
            hypothesis_id=hypothesis.hypothesis_id,
            version=hypothesis.version,
            fingerprint=hypothesis.fingerprint,
            symbol="AAPL",
            interval=Interval.DAY_1,
            basis=PriceBasis.RAW,
            timestamp=T0,
            state=state,
            evidence={},
            reason_codes=(ANY_REASON,),
        )
        for hypothesis, state in zip(HYPOTHESES, states)
    )
    return assess(observations, POLICY)


ALL_COMBINATIONS = list(
    product(
        [ResearchState.BULLISH, ResearchState.BEARISH,
         ResearchState.NEUTRAL, ResearchState.INSUFFICIENT_DATA],
        repeat=len(HYPOTHESES),
    )
)


def result(**overrides) -> SymbolScanResult:
    fields = dict(
        symbol="AAPL",
        eligibility=EligibilityStatus.ELIGIBLE,
        category=StructuralCategory.UNANIMOUS_DIRECTIONAL,
        data_cutoff=T0,
        state=AssessmentState.BULLISH,
        counts=AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0),
        reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,),
        bar_count=300,
        latest_bar_open=T0 - timedelta(days=1),
    )
    fields.update(overrides)
    return SymbolScanResult(**fields)


# -- the mapping is total over the real engine ---------------------------


def test_every_reachable_assessment_maps_to_exactly_one_category():
    """No combination the engine can produce may be unmapped."""
    for states in ALL_COMBINATIONS:
        assessment = assessment_for(states)
        category = category_for(assessment.state, assessment.reason_codes)
        assert category in CATEGORY_ORDER, (states, assessment.state)


def test_the_mapping_is_deterministic():
    for states in ALL_COMBINATIONS[:16]:
        assessment = assessment_for(states)
        first = category_for(assessment.state, assessment.reason_codes)
        second = category_for(assessment.state, assessment.reason_codes)
        assert first is second


@pytest.mark.parametrize(
    "states, expected",
    [
        ((ResearchState.BULLISH,) * 3, StructuralCategory.UNANIMOUS_DIRECTIONAL),
        ((ResearchState.BEARISH,) * 3, StructuralCategory.UNANIMOUS_DIRECTIONAL),
        ((ResearchState.BULLISH, ResearchState.BULLISH, ResearchState.NEUTRAL),
         StructuralCategory.DIRECTIONAL_WITH_NEUTRAL),
        ((ResearchState.BEARISH, ResearchState.BEARISH, ResearchState.NEUTRAL),
         StructuralCategory.DIRECTIONAL_WITH_NEUTRAL),
        ((ResearchState.BULLISH, ResearchState.BEARISH, ResearchState.BULLISH),
         StructuralCategory.CONFLICTED),
        ((ResearchState.NEUTRAL,) * 3, StructuralCategory.NEUTRAL),
        ((ResearchState.BULLISH, ResearchState.INSUFFICIENT_DATA,
          ResearchState.INSUFFICIENT_DATA), StructuralCategory.NOT_ASSESSABLE),
    ],
)
def test_representative_combinations_map_as_locked(states, expected):
    assessment = assessment_for(states)
    assert category_for(assessment.state, assessment.reason_codes) is expected


# -- the modifier must never select a category ---------------------------


def test_insufficient_inputs_excluded_coexists_with_every_category():
    """It is a modifier, and the engine really does emit it alongside all states.

    A rule that took "the first reason code" would mis-categorise every one of
    these, which is why this is pinned explicitly.
    """
    seen: dict[StructuralCategory, AssessmentState] = {}
    for states in ALL_COMBINATIONS:
        assessment = assessment_for(states)
        if AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED not in assessment.reason_codes:
            continue
        seen[category_for(assessment.state, assessment.reason_codes)] = assessment.state
    # Every category is reachable *while* the modifier is present.
    assert set(seen) == set(CATEGORY_ORDER), seen


def test_the_modifier_alone_never_produces_a_directional_category():
    assert category_for(
        AssessmentState.BULLISH,
        (AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,),
    ) is StructuralCategory.DIRECTIONAL_WITH_NEUTRAL


def test_reason_code_position_does_not_matter():
    """Identity, not order: the unanimous code may appear anywhere."""
    codes = (
        AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
        AssessmentReasonCode.UNANIMOUS_BULLISH,
    )
    assert category_for(AssessmentState.BULLISH, codes) is (
        StructuralCategory.UNANIMOUS_DIRECTIONAL
    )


def test_an_absent_assessment_is_not_assessable():
    assert category_for(None, ()) is StructuralCategory.NOT_ASSESSABLE


# -- ordering ------------------------------------------------------------


def test_category_order_is_the_locked_sequence():
    assert [c.value for c in CATEGORY_ORDER] == [
        "unanimous_directional", "directional_with_neutral",
        "conflicted", "neutral", "not_assessable",
    ]


def test_conflicted_sorts_above_neutral():
    """Disagreement is more informative to inspect than agreed-on nothing."""
    conflicted = result(symbol="CON", category=StructuralCategory.CONFLICTED,
                        state=AssessmentState.CONFLICTED,
                        reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,))
    neutral = result(symbol="NEU", category=StructuralCategory.NEUTRAL,
                     state=AssessmentState.NEUTRAL,
                     reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,))
    assert [r.symbol for r in order_results([neutral, conflicted])] == ["CON", "NEU"]


def _one_per_category():
    """One result per assessable category, with symbols deliberately named in
    the *reverse* of category order.

    The naming matters: if symbols ascended alongside categories, the symbol
    tie-break alone would reproduce the expected order and the test would pass
    even with category ranking removed entirely.
    """
    states = {
        StructuralCategory.CONFLICTED: AssessmentState.CONFLICTED,
        StructuralCategory.NEUTRAL: AssessmentState.NEUTRAL,
    }
    total = len(CATEGORY_ORDER) - 1
    return [
        result(symbol=f"S{total - index}", category=category,
               state=states.get(category, AssessmentState.BULLISH),
               reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,))
        for index, category in enumerate(CATEGORY_ORDER[:-1])
    ]


def test_ordering_follows_the_locked_category_sequence():
    made = _one_per_category()
    assert [r.symbol for r in made] == ["S4", "S3", "S2", "S1"]
    ordered = order_results(list(reversed(made)))
    assert [r.category for r in ordered] == list(CATEGORY_ORDER[:-1])
    # And the symbols really do run counter to the tie-break, so only category
    # ranking can have produced that order.
    assert [r.symbol for r in ordered] == ["S4", "S3", "S2", "S1"]


def test_category_dominates_every_other_rank_component():
    """A weaker category with more evidence and fresher data still sorts below.

    This is what makes the ordering lexicographic rather than a score: no amount
    of classifying count or freshness can promote a NEUTRAL above a
    UNANIMOUS_DIRECTIONAL.
    """
    strong_evidence_neutral = result(
        symbol="AAA", category=StructuralCategory.NEUTRAL,
        state=AssessmentState.NEUTRAL,
        counts=AssessmentCounts(bullish=0, bearish=0, neutral=3, insufficient=0),
        reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,),
        latest_bar_open=T0,
    )
    weak_unanimous = result(
        symbol="ZZZ", category=StructuralCategory.UNANIMOUS_DIRECTIONAL,
        counts=AssessmentCounts(bullish=2, bearish=0, neutral=0, insufficient=1),
        latest_bar_open=T0 - timedelta(days=30),
    )
    ordered = order_results([strong_evidence_neutral, weak_unanimous])
    assert [r.symbol for r in ordered] == ["ZZZ", "AAA"]


def test_the_rank_key_is_lexicographic_not_a_single_number():
    """A composite score would collapse the key to one comparable value."""
    key = rank_key(result())
    assert isinstance(key, tuple)
    assert len(key) == 4
    assert isinstance(key[0], int), "category rank must lead the key"
    assert all(not isinstance(part, float) or part == int(part) for part in key[:2])


def test_ordering_is_stable_across_runs():
    made = [result(symbol=s) for s in ("MSFT", "AAPL", "GOOGL")]
    assert order_results(made) == order_results(list(reversed(made)))


# -- direction neutrality ------------------------------------------------


def test_bullish_and_bearish_receive_identical_rank_keys():
    """Direction must not appear anywhere in the comparator."""
    bullish = result(symbol="AAA", state=AssessmentState.BULLISH,
                     counts=AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0),
                     reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,))
    bearish = result(symbol="AAA", state=AssessmentState.BEARISH,
                     counts=AssessmentCounts(bullish=0, bearish=3, neutral=0, insufficient=0),
                     reason_codes=(AssessmentReasonCode.UNANIMOUS_BEARISH,))
    assert rank_key(bullish) == rank_key(bearish)


def test_inverting_every_direction_leaves_the_order_unchanged():
    """The invariant a mutant privileging bullish must fail."""
    def make(symbol, state, codes):
        counts = (AssessmentCounts(bullish=2, bearish=0, neutral=1, insufficient=0)
                  if state is AssessmentState.BULLISH
                  else AssessmentCounts(bullish=0, bearish=2, neutral=1, insufficient=0))
        return result(symbol=symbol, state=state, counts=counts, reason_codes=codes,
                      category=StructuralCategory.DIRECTIONAL_WITH_NEUTRAL)

    up = [make("AAA", AssessmentState.BULLISH,
               (AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL,)),
          make("BBB", AssessmentState.BEARISH,
               (AssessmentReasonCode.DIRECTIONAL_BEARISH_WITH_NEUTRAL,))]
    down = [make("AAA", AssessmentState.BEARISH,
                 (AssessmentReasonCode.DIRECTIONAL_BEARISH_WITH_NEUTRAL,)),
            make("BBB", AssessmentState.BULLISH,
                 (AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL,))]
    assert [r.symbol for r in order_results(up)] == [r.symbol for r in order_results(down)]


def test_no_rank_key_component_encodes_direction():
    bullish = result(state=AssessmentState.BULLISH,
                     counts=AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0))
    bearish = result(state=AssessmentState.BEARISH,
                     counts=AssessmentCounts(bullish=0, bearish=3, neutral=0, insufficient=0),
                     reason_codes=(AssessmentReasonCode.UNANIMOUS_BEARISH,))
    for a, b in zip(rank_key(bullish), rank_key(bearish)):
        assert a == b


# -- tie-breaks ----------------------------------------------------------


def test_more_classifying_hypotheses_sorts_first():
    three = result(symbol="AAA",
                   counts=AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0))
    two = result(symbol="AAB",
                 counts=AssessmentCounts(bullish=2, bearish=0, neutral=0, insufficient=1))
    assert [r.symbol for r in order_results([two, three])] == ["AAA", "AAB"]


def test_fresher_data_sorts_first_when_evidence_is_equal():
    older = result(symbol="AAA", latest_bar_open=T0 - timedelta(days=10))
    newer = result(symbol="AAB", latest_bar_open=T0 - timedelta(days=1))
    assert [r.symbol for r in order_results([older, newer])] == ["AAB", "AAA"]


def test_symbol_breaks_a_full_tie_deterministically():
    made = [result(symbol=s) for s in ("MSFT", "AAPL")]
    assert [r.symbol for r in order_results(made)] == ["AAPL", "MSFT"]


def test_a_missing_timestamp_sorts_last_without_raising():
    """NOT_ASSESSABLE rows carry no bar time; the comparator must not compare
    a datetime with None."""
    known = result(symbol="AAA", latest_bar_open=T0 - timedelta(days=5))
    unknown = result(symbol="AAB", latest_bar_open=None)
    ordered = order_results([unknown, known])
    assert [r.symbol for r in ordered] == ["AAA", "AAB"]


def test_all_missing_timestamps_still_order_deterministically():
    made = [result(symbol=s, latest_bar_open=None) for s in ("MSFT", "AAPL", "GOOGL")]
    assert [r.symbol for r in order_results(made)] == ["AAPL", "GOOGL", "MSFT"]


# -- ordered rows --------------------------------------------------------


def test_ordered_rows_contains_only_assessable_results():
    eligible = result(symbol="AAA")
    failed = SymbolScanResult(symbol="BBB", eligibility=None,
                              category=StructuralCategory.NOT_ASSESSABLE,
                              data_cutoff=T0, error_code=ScanErrorCode.PROVIDER_UNAVAILABLE)
    rows = ordered_rows([eligible, failed])
    assert [r.symbol for r in rows] == ["AAA"]


def test_order_results_drops_nothing():
    eligible = result(symbol="AAA")
    failed = SymbolScanResult(symbol="BBB", eligibility=None,
                              category=StructuralCategory.NOT_ASSESSABLE,
                              data_cutoff=T0, error_code=ScanErrorCode.UNEXPECTED)
    assert len(order_results([eligible, failed])) == 2


# -- no score ------------------------------------------------------------


def test_ranking_exposes_no_numeric_quality_measure():
    import src.scanner.ranking as ranking

    surface = {name for name in dir(ranking) if not name.startswith("_")}
    for forbidden in ("score", "confidence", "probability", "rating", "conviction",
                      "weight", "strength"):
        assert not [n for n in surface if forbidden in n.lower()], forbidden


# -- adversarial tie-break hierarchy -------------------------------------


def _row(symbol, category, classifying, days_old, state=AssessmentState.BULLISH):
    counts = AssessmentCounts(
        bullish=classifying, bearish=0, neutral=0, insufficient=3 - classifying
    )
    if category is StructuralCategory.NEUTRAL:
        state = AssessmentState.NEUTRAL
        counts = AssessmentCounts(bullish=0, bearish=0, neutral=classifying,
                                  insufficient=3 - classifying)
    elif category is StructuralCategory.CONFLICTED:
        state = AssessmentState.CONFLICTED
    return result(
        symbol=symbol, category=category, state=state, counts=counts,
        reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,),
        latest_bar_open=T0 - timedelta(days=days_old),
    )


def test_category_dominates_evidence_count_and_freshness():
    """Fixtures are deliberately anti-correlated: the weaker category has more
    evidence, fresher data *and* an alphabetically earlier symbol."""
    neutral_best_on_everything_else = _row(
        "AAA", StructuralCategory.NEUTRAL, classifying=3, days_old=0
    )
    unanimous_worst_on_everything_else = _row(
        "ZZZ", StructuralCategory.UNANIMOUS_DIRECTIONAL, classifying=1, days_old=999
    )
    ordered = order_results(
        [neutral_best_on_everything_else, unanimous_worst_on_everything_else]
    )
    assert [r.symbol for r in ordered] == ["ZZZ", "AAA"]


def test_evidence_count_dominates_freshness_and_symbol():
    """Same category. The row with more evidence is stale and sorts late
    alphabetically, so only the evidence rule can put it first."""
    more_evidence = _row("ZZZ", StructuralCategory.UNANIMOUS_DIRECTIONAL,
                         classifying=3, days_old=999)
    less_evidence = _row("AAA", StructuralCategory.UNANIMOUS_DIRECTIONAL,
                         classifying=1, days_old=0)
    assert [r.symbol for r in order_results([less_evidence, more_evidence])] == ["ZZZ", "AAA"]


def test_freshness_dominates_symbol():
    """Same category and evidence. The fresher row sorts later alphabetically."""
    fresher = _row("ZZZ", StructuralCategory.UNANIMOUS_DIRECTIONAL,
                   classifying=3, days_old=0)
    staler = _row("AAA", StructuralCategory.UNANIMOUS_DIRECTIONAL,
                  classifying=3, days_old=30)
    assert [r.symbol for r in order_results([staler, fresher])] == ["ZZZ", "AAA"]


def test_symbol_gives_a_total_order_when_all_else_ties():
    rows = [_row(s, StructuralCategory.UNANIMOUS_DIRECTIONAL, classifying=3, days_old=1)
            for s in ("MSFT", "AAPL", "ZZZZ", "GOOGL")]
    assert [r.symbol for r in order_results(rows)] == ["AAPL", "GOOGL", "MSFT", "ZZZZ"]


def test_the_full_hierarchy_holds_at_once():
    """One fixture per rule, each anti-correlated with the next."""
    rows = [
        _row("ZZZ", StructuralCategory.UNANIMOUS_DIRECTIONAL, classifying=1, days_old=900),
        _row("AAA", StructuralCategory.DIRECTIONAL_WITH_NEUTRAL, classifying=3, days_old=0),
        _row("BBB", StructuralCategory.CONFLICTED, classifying=3, days_old=0),
        _row("CCC", StructuralCategory.NEUTRAL, classifying=3, days_old=0),
    ]
    assert [r.symbol for r in order_results(list(reversed(rows)))] == [
        "ZZZ", "AAA", "BBB", "CCC"
    ]


def test_rank_key_is_total_over_every_legal_result_shape():
    """Every legal form must be comparable with every other, without raising."""
    shapes = [
        result(symbol="AAA"),
        result(symbol="BBB", latest_bar_open=None),
        SymbolScanResult(symbol="CCC", eligibility=EligibilityStatus.NO_DATA,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0),
        SymbolScanResult(symbol="DDD",
                         eligibility=EligibilityStatus.INSUFFICIENT_EVIDENCE,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
                         state=AssessmentState.INSUFFICIENT_DATA, bar_count=5),
        SymbolScanResult(symbol="EEE", eligibility=None,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
                         error_code=ScanErrorCode.UNEXPECTED),
    ]
    keys = [rank_key(shape) for shape in shapes]
    for left in keys:
        for right in keys:
            assert (left < right) or (left >= right)   # comparable, never raises
    assert len(order_results(shapes)) == len(shapes)
    assert order_results(shapes) == order_results(list(reversed(shapes)))
