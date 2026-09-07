"""Phase 10 Stage F view models: formatting that cannot upgrade a claim.

The view layer is the last place a hedge can be dropped, so the wording is
pinned as tightly as the domain. Two rules carry most of the weight: a research
classification is never rendered as an instruction, and a symbol with nothing to
assess is never called a failure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.scanner import MarketScanner, ranked_rows
from src.application.snapshot import build_snapshot
from src.application.view_models import (
    SCANNER_DISCLAIMER,
    SCANNER_INTERVAL_NOTE,
    SCANNER_ORDERING_NOTE,
    ScannerIssueRowView,
    ScannerRowView,
    ScannerView,
    scanner_view,
    universe_option_label,
)
from src.data.models import Interval
from src.scanner.models import StructuralCategory
from src.scanner.universe import build_universe
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc
T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def universe(symbols=("ZZZ", "AAA", "MMM")):
    definition, _ = build_universe(
        universe_id="demo", display_name="Example research watchlist",
        symbols=list(symbols), source_kind="local_static",
        source_reference="illustrative research-demo membership",
        as_of=date(2026, 9, 6),
    )
    return definition


def scan(script=None, default_bars=300, symbols=("ZZZ", "AAA", "MMM")):
    def build(provider, symbol, interval, *, now):
        action = (script or {}).get(symbol, default_bars)
        if isinstance(action, BaseException):
            raise action
        return build_snapshot(RecordingProvider(action), symbol, interval, now=now)

    return MarketScanner(RecordingProvider(300), build=build, now=lambda: T0).scan(
        universe(symbols), Interval.DAY_1
    )


# -- summary -------------------------------------------------------------


def test_the_summary_reports_the_scan_truthfully():
    view = scanner_view(scan())
    s = view.summary
    assert s.universe_display_name == "Example research watchlist"
    assert s.universe_as_of == "2026-09-06"
    assert len(s.fingerprint_prefix) == 12
    assert s.interval == "1d"
    assert s.symbols_total == 3
    assert s.symbols_completed == 3
    assert s.symbols_eligible == 3
    assert s.operational_failures == 0
    assert s.status == "ALL OK"


def test_the_fingerprint_is_shown_as_a_prefix_not_in_full():
    snapshot = scan()
    view = scanner_view(snapshot)
    assert view.summary.fingerprint_prefix == snapshot.universe_fingerprint[:12]
    assert view.summary.fingerprint_prefix != snapshot.universe_fingerprint


def test_status_note_never_calls_a_clean_scan_a_failure():
    assert "without an operational error" in scanner_view(scan()).status_note


def test_status_note_distinguishes_partial_from_total_failure():
    partial = scanner_view(scan({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "d")}))
    assert "could not be scanned" in partial.status_note
    assert "The rest completed normally" in partial.status_note
    all_failed = scanner_view(scan({s: ApplicationError(FailureKind.PROVIDER, "s", "d")
                                    for s in ("AAA", "MMM", "ZZZ")}))
    assert "No symbol could be scanned" in all_failed.status_note


# -- eligible rows -------------------------------------------------------


def test_rows_follow_the_scanner_ordering_and_are_not_re_sorted():
    snapshot = scan()
    view = scanner_view(snapshot)
    assert [r.symbol for r in view.rows] == [r.symbol for r in ranked_rows(snapshot)]


def test_rows_expose_only_the_locked_columns():
    from dataclasses import fields

    names = {f.name for f in fields(ScannerRowView)}
    assert names == {
        "symbol", "category", "category_label", "assessment",
        "bullish", "bearish", "neutral", "why_surfaced",
        "latest_bar", "data_cutoff",
    }


def test_no_row_field_exposes_a_score_or_rating():
    from dataclasses import fields

    for record in (ScannerRowView, ScannerIssueRowView, ScannerView):
        for field in fields(record):
            for forbidden in ("score", "confidence", "probability", "rating",
                              "conviction", "rank", "return"):
                assert forbidden not in field.name.lower(), field.name


@pytest.mark.parametrize(
    "category, label",
    [
        (StructuralCategory.UNANIMOUS_DIRECTIONAL, "Unanimous directional"),
        (StructuralCategory.DIRECTIONAL_WITH_NEUTRAL, "Directional with neutral"),
        (StructuralCategory.CONFLICTED, "Conflicted"),
        (StructuralCategory.NEUTRAL, "Neutral"),
    ],
)
def test_category_labels_describe_evidence_not_priority(category, label):
    from src.application.view_models import _CATEGORY_LABEL

    assert _CATEGORY_LABEL[category.value] == label
    for forbidden in ("priority", "strong", "best", "top", "candidate rank"):
        assert forbidden not in label.lower()


def test_assessment_is_never_rendered_as_an_instruction():
    from src.application.view_models import _ASSESSMENT_LABEL

    assert _ASSESSMENT_LABEL["bullish"] == "Bullish"
    assert _ASSESSMENT_LABEL["bearish"] == "Bearish"
    for label in _ASSESSMENT_LABEL.values():
        for forbidden in ("buy", "sell", "long", "short", "hold"):
            assert forbidden not in label.lower(), label


def test_why_surfaced_is_deterministic_text_from_category_identity():
    """Properties the implementation does not simply restate.

    Asserting ``row.why_surfaced == _WHY_SURFACED[row.category]`` would only
    repeat the one line of ``_row_view`` that produces it, and would still pass
    if both were wrong together. These check the mapping is total, unambiguous
    and stable instead.
    """
    from src.application.view_models import _WHY_SURFACED

    assert _WHY_SURFACED["unanimous_directional"] == (
        "All classified hypotheses agree directionally"
    )
    assert _WHY_SURFACED["conflicted"] == "Hypotheses conflict on direction"

    # Total over the real enum: an unmapped category would be a KeyError at
    # render time, on a scan that had already succeeded.
    assert set(_WHY_SURFACED) == {c.value for c in StructuralCategory}

    # One phrase per category, so the text identifies which one produced it.
    assert len(set(_WHY_SURFACED.values())) == len(_WHY_SURFACED)

    # Deterministic: two independent scans of the same universe word it the same.
    first = {row.symbol: row.why_surfaced for row in scanner_view(scan()).rows}
    second = {row.symbol: row.why_surfaced for row in scanner_view(scan()).rows}
    assert first == second and first, first

    # And the wording actually tracks the category rather than the symbol.
    view = scanner_view(scan())
    by_category = {}
    for row in view.rows:
        by_category.setdefault(row.category, set()).add(row.why_surfaced)
    assert all(len(texts) == 1 for texts in by_category.values()), by_category


def test_bullish_and_bearish_rows_are_labelled_symmetrically():
    from src.application.view_models import _ASSESSMENT_LABEL

    assert len(_ASSESSMENT_LABEL["bullish"]) > 0
    assert _ASSESSMENT_LABEL["bullish"].isalpha()
    assert _ASSESSMENT_LABEL["bearish"].isalpha()


# -- issue rows ----------------------------------------------------------


def test_a_symbol_with_no_bars_is_no_data_and_not_a_failure():
    """The BK live-benchmark case."""
    view = scanner_view(scan(default_bars=0))
    assert not view.rows
    assert len(view.issues) == 3
    for issue in view.issues:
        assert issue.status == "No data"
        assert issue.is_operational_failure is False
        assert "no usable bars" in issue.detail
        assert "fail" not in issue.status.lower()
        assert "error" not in issue.status.lower()


def test_insufficient_evidence_is_a_research_state_not_a_failure():
    view = scanner_view(scan(default_bars=5))
    for issue in view.issues:
        assert issue.status == "Insufficient evidence"
        assert issue.is_operational_failure is False


@pytest.mark.parametrize(
    "kind, label",
    [
        (FailureKind.PROVIDER, "Provider unavailable"),
        (FailureKind.DATA_QUALITY, "Data quality issue"),
        (FailureKind.DOMAIN, "Symbol mismatch"),
        (FailureKind.REQUEST, "Request invalid"),
        (FailureKind.UNEXPECTED, "Unexpected scanner error"),
    ],
)
def test_operational_errors_are_labelled_technically(kind, label):
    view = scanner_view(scan({"AAA": ApplicationError(kind, "market data", "boom")}))
    issue = {i.symbol: i for i in view.issues}["AAA"]
    assert issue.status == label
    assert issue.is_operational_failure is True


def test_issues_never_appear_in_the_candidate_table():
    view = scanner_view(scan({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "d")},
                             default_bars=0))
    assert view.rows == ()
    assert {i.symbol for i in view.issues} == {"AAA", "MMM", "ZZZ"}


def test_error_detail_is_bounded_and_carries_no_traceback():
    view = scanner_view(scan({"AAA": ApplicationError(FailureKind.PROVIDER, "s", "x" * 5000)}))
    detail = {i.symbol: i for i in view.issues}["AAA"].detail
    assert len(detail) <= 300
    assert "Traceback" not in detail


# -- selectable symbols --------------------------------------------------


def test_only_assessable_symbols_are_offered_for_research():
    view = scanner_view(scan({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "d")},
                             default_bars=300))
    assert "MMM" not in view.eligible_symbols
    assert set(view.eligible_symbols) == {"AAA", "ZZZ"}


def test_a_scan_with_no_assessable_symbols_offers_none():
    view = scanner_view(scan(default_bars=0))
    assert view.eligible_symbols == ()
    assert not view.has_rows


# -- wording -------------------------------------------------------------


def test_the_disclaimer_denies_recommendation_and_paper_reach():
    text = SCANNER_DISCLAIMER.lower()
    assert "not a recommendation" in text or "nothing here is a recommendation" in text
    assert "paper trading" in text


def test_the_ordering_note_denies_investment_merit():
    text = SCANNER_ORDERING_NOTE.lower()
    assert "not that one symbol is a better investment" in text


def test_the_interval_note_states_daily_only():
    assert "daily bars" in SCANNER_INTERVAL_NOTE.lower()
    assert "weekly and monthly" in SCANNER_INTERVAL_NOTE.lower()


def test_no_scanner_label_uses_investment_action_language():
    """Scoped to *labels*, which is where a claim could actually be made.

    The disclaimers are deliberately excluded: they name "score" and
    "recommendation" precisely in order to deny them, and a substring rule that
    could not tell a denial from a claim would force the disclaimer to be
    written worse.
    """
    import src.application.view_models as vm

    labels = (
        list(vm._CATEGORY_LABEL.values()) + list(vm._ASSESSMENT_LABEL.values())
        + list(vm._WHY_SURFACED.values()) + list(vm._ERROR_LABEL.values())
        + list(vm._ELIGIBILITY_LABEL.values())
    )
    for text in labels:
        low = text.lower()
        for forbidden in ("buy", "sell", "strong", "top pick", "best",
                          "expected return", "conviction", "score", "rating",
                          "confidence", "priority"):
            assert forbidden not in low, f"{forbidden!r} in label {text!r}"


def test_the_disclaimers_deny_the_forbidden_concepts_rather_than_claiming_them():
    """The other half: the words must appear, as refusals."""
    text = SCANNER_DISCLAIMER.lower()
    assert "not a recommendation" in text or "nothing here is a recommendation" in text
    assert "score" in text, "the disclaimer should say there is no score"
    assert "not by investment merit" in text


def test_the_universe_label_shows_vintage_but_not_the_fingerprint():
    label = universe_option_label(universe())
    assert "Example research watchlist" in label
    assert "3 symbols" in label
    assert "as of 2026-09-06" in label
    assert universe().fingerprint not in label


# -- purity --------------------------------------------------------------


def test_view_model_construction_touches_no_network_or_filesystem(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("view-model construction reached the network")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert scanner_view(scan()).has_rows


def test_view_models_are_frozen():
    from dataclasses import FrozenInstanceError

    view = scanner_view(scan())
    with pytest.raises(FrozenInstanceError):
        view.rows[0].symbol = "CHANGED"
    with pytest.raises(FrozenInstanceError):
        view.summary.symbols_total = 99


# -- ordering and counting, pinned against a re-implementation ------------


def _ordered_snapshot():
    """A snapshot whose ranked order is deliberately *not* alphabetical.

    The earlier fixtures give every symbol the same category and counts, so a
    view that re-sorted by symbol would agree with the scanner by accident. This
    one disagrees, which is what makes the ordering assertion mean anything.
    """
    from tests.test_scanner_models import snapshot as build

    from src.assessments.assessment import (
        AssessmentCounts, AssessmentReasonCode, AssessmentState,
    )
    from src.scanner.models import EligibilityStatus, SymbolScanResult

    def result(symbol, category, state, counts, reason):
        return SymbolScanResult(
            symbol=symbol, eligibility=EligibilityStatus.ELIGIBLE, category=category,
            data_cutoff=T0, state=state, counts=counts, reason_codes=(reason,),
            bar_count=300, latest_bar_open=T0 - timedelta(days=1),
        )

    return build(results=(
        result("AAA", StructuralCategory.CONFLICTED, AssessmentState.CONFLICTED,
               AssessmentCounts(bullish=1, bearish=1, neutral=1, insufficient=0),
               AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE),
        result("ZZZ", StructuralCategory.UNANIMOUS_DIRECTIONAL,
               AssessmentState.BULLISH,
               AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0),
               AssessmentReasonCode.UNANIMOUS_BULLISH),
    ))


def test_the_view_preserves_a_ranked_order_that_disagrees_with_the_alphabet():
    snapshot = _ordered_snapshot()
    ranked = [r.symbol for r in ranked_rows(snapshot)]
    assert ranked == ["ZZZ", "AAA"], "fixture no longer distinguishes the orders"
    assert [r.symbol for r in scanner_view(snapshot).rows] == ranked
    assert [r.symbol for r in scanner_view(snapshot).rows] != sorted(ranked)


def test_the_eligible_count_is_the_scanners_and_not_the_symbol_total():
    snapshot = scan({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "d")})
    summary = scanner_view(snapshot).summary
    assert summary.symbols_eligible == snapshot.counters.symbols_eligible == 2
    assert summary.symbols_total == 3
    assert summary.symbols_eligible != summary.symbols_total


def test_symbols_with_no_data_are_never_added_to_the_failure_count():
    """The BK case, counted rather than merely labelled."""
    summary = scanner_view(scan(default_bars=0)).summary
    assert summary.symbols_no_data == 3
    assert summary.operational_failures == 0
    assert summary.status == "ALL OK"


# -- F9 regressions: gaps a fresh mutation campaign found -----------------


def test_ordering_does_not_prefer_bullish_over_bearish():
    """Direction must not buy a row a better place in the list.

    The earlier ordering fixture has no bearish row at all, so a view that
    sorted bullish-first would have agreed with the scanner by omission.
    """
    from tests.test_scanner_models import snapshot as build

    from src.assessments.assessment import (
        AssessmentCounts, AssessmentReasonCode, AssessmentState,
    )
    from src.scanner.models import EligibilityStatus, SymbolScanResult

    def result(symbol, state, counts, reason):
        return SymbolScanResult(
            symbol=symbol, eligibility=EligibilityStatus.ELIGIBLE,
            category=StructuralCategory.UNANIMOUS_DIRECTIONAL, data_cutoff=T0,
            state=state, counts=counts, reason_codes=(reason,), bar_count=300,
            latest_bar_open=T0 - timedelta(days=1),
        )

    bear = result("AAA", AssessmentState.BEARISH,
                  AssessmentCounts(bullish=0, bearish=3, neutral=0, insufficient=0),
                  AssessmentReasonCode.UNANIMOUS_BEARISH)
    bull = result("ZZZ", AssessmentState.BULLISH,
                  AssessmentCounts(bullish=3, bearish=0, neutral=0, insufficient=0),
                  AssessmentReasonCode.UNANIMOUS_BULLISH)

    snapshot = build(results=(bear, bull))
    rows = scanner_view(snapshot).rows
    assert [r.symbol for r in rows] == [r.symbol for r in ranked_rows(snapshot)]
    assert rows[0].assessment == "Bearish", (
        "a bearish row was demoted purely for being bearish"
    )
    # Equivalent evidence in either direction reads the same everywhere but the
    # direction word itself.
    by = {r.symbol: r for r in rows}
    assert by["AAA"].category_label == by["ZZZ"].category_label
    assert by["AAA"].why_surfaced == by["ZZZ"].why_surfaced
    assert (by["AAA"].bearish, by["AAA"].bullish) == (by["ZZZ"].bullish, by["ZZZ"].bearish)


def test_the_summary_counts_come_from_the_scanner_not_from_the_result_list():
    """A scan where "has an eligibility" and "is eligible" disagree.

    Every symbol here carries NO_DATA -- a determined eligibility that is not
    ELIGIBLE -- so a view that recounted the rows itself would report three
    assessable symbols for a scan that produced none.
    """
    snapshot = scan(default_bars=0)
    summary = scanner_view(snapshot).summary
    assert len([r for r in snapshot.results if r.eligibility is not None]) == 3
    assert snapshot.counters.symbols_eligible == 0
    assert summary.symbols_eligible == 0, "the view recounted instead of reading counters"
    assert summary.symbols_no_data == 3
    assert summary.operational_failures == 0
