"""Phase 10 scanner records: immutability, vocabulary and refused contradictions.

Most of these tests are about records the scanner must be unable to construct.
A result claiming ELIGIBLE with no assessment, or carrying both an error and a
finding, would be a statement that cannot be true -- and every consumer would
have to defend against it forever.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone

import pytest

from src.assessments.assessment import (
    AssessmentCounts,
    AssessmentReasonCode,
    AssessmentState,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.scanner.models import (
    ASSESSABLE_CATEGORIES,
    CATEGORY_ORDER,
    MAX_ERROR_DETAIL_CHARS,
    MAX_SYMBOLS_PER_UNIVERSE,
    MAX_UNIVERSE_CONFIG_BYTES,
    MAX_UNIVERSES,
    EligibilityStatus,
    MarketScanSnapshot,
    ScanCounters,
    ScanErrorCode,
    ScannerError,
    ScanStatus,
    StructuralCategory,
    SymbolScanResult,
    UniverseConfiguration,
    UniverseDefinition,
    UniverseLoadReport,
    UniverseSourceKind,
    require_universe_id,
    status_for,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
AS_OF = date(2026, 9, 6)
FP = "a" * 64


def eligible(**overrides) -> SymbolScanResult:
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


def failed(**overrides) -> SymbolScanResult:
    fields = dict(
        symbol="BBB", eligibility=None, category=StructuralCategory.NOT_ASSESSABLE,
        data_cutoff=T0, error_code=ScanErrorCode.PROVIDER_UNAVAILABLE,
        error_detail="provider down",
    )
    fields.update(overrides)
    return SymbolScanResult(**fields)


def universe(**overrides) -> UniverseDefinition:
    fields = dict(
        universe_id="demo", display_name="Demo", symbols=("AAPL", "MSFT"),
        source_kind=UniverseSourceKind.LOCAL_STATIC,
        source_reference="illustrative", as_of=AS_OF, fingerprint=FP,
    )
    fields.update(overrides)
    return UniverseDefinition(**fields)


def snapshot(**overrides) -> MarketScanSnapshot:
    """A coherent snapshot. Status and counters are derived from the results,
    because the record refuses to contradict itself."""
    results = tuple(overrides.pop("results", (eligible(),)))
    fields = dict(
        universe_id="demo", universe_fingerprint=FP, universe_display_name="Demo",
        universe_as_of=AS_OF, interval=Interval.DAY_1, basis=PriceBasis.RAW,
        policy_fingerprint="p" * 16, warmup_bars=51, minimum_sufficient_observations=2,
        scan_started_at=T0, scan_completed_at=T0 + timedelta(seconds=30),
        results=results,
        counters=ScanCounters.from_results(results, symbols_total=len(results)),
        status=status_for(results) if results else ScanStatus.ALL_OK,
    )
    fields.update(overrides)
    return MarketScanSnapshot(**fields)


# -- vocabulary ----------------------------------------------------------


def test_scan_status_has_exactly_three_members():
    """NOTHING_CONFIGURED is absent: a snapshot describes a scan that ran."""
    assert {s.value for s in ScanStatus} == {"all_ok", "partial", "all_failed"}


def test_eligibility_has_exactly_three_members():
    assert {e.value for e in EligibilityStatus} == {
        "eligible", "no_data", "insufficient_evidence"
    }


def test_no_removed_eligibility_member_reappears():
    names = {e.name for e in EligibilityStatus}
    for gone in ("INSUFFICIENT_HISTORY", "STALE_DATA", "UNSUPPORTED"):
        assert gone not in names


def test_structural_categories_are_the_locked_five():
    assert {c.value for c in StructuralCategory} == {
        "unanimous_directional", "directional_with_neutral",
        "conflicted", "neutral", "not_assessable",
    }


def test_error_codes_match_distinguishable_failure_kinds():
    from src.application.errors import FailureKind

    assert {c.value for c in ScanErrorCode} == {
        "provider_unavailable", "data_quality", "symbol_mismatch",
        "request_invalid", "unexpected",
    }
    assert len(list(ScanErrorCode)) == len(list(FailureKind))
    for absent in ("PROVIDER_TIMEOUT", "SYMBOL_NOT_FOUND"):
        assert absent not in {c.name for c in ScanErrorCode}


def test_source_kinds_claim_no_verification():
    assert {k.value for k in UniverseSourceKind} == {"local_static", "user_defined"}
    for forbidden in ("verified", "official", "index"):
        assert not [k for k in UniverseSourceKind if forbidden in k.value]


def test_no_enum_member_uses_investment_language():
    for enum in (EligibilityStatus, StructuralCategory, ScanStatus,
                 ScanErrorCode, UniverseSourceKind):
        for member in enum:
            text = f"{member.name} {member.value}".lower()
            for forbidden in ("buy", "sell", "strong", "best", "top", "pick",
                              "score", "confidence", "probability", "rating",
                              "conviction", "target"):
                assert forbidden not in text, f"{enum.__name__}.{member.name}"


def test_limits_are_the_locked_values():
    assert MAX_SYMBOLS_PER_UNIVERSE == 100
    assert MAX_UNIVERSES == 50
    assert MAX_UNIVERSE_CONFIG_BYTES == 256 * 1024
    assert MAX_ERROR_DETAIL_CHARS == 300


# -- immutability --------------------------------------------------------


@pytest.mark.parametrize("record", [eligible(), universe(), snapshot(), ScanCounters()])
def test_records_are_frozen(record):
    with pytest.raises(FrozenInstanceError):
        record.symbol = "changed"


def test_nested_collections_are_tuples():
    assert isinstance(snapshot().results, tuple)
    assert isinstance(universe().symbols, tuple)
    assert isinstance(eligible().reason_codes, tuple)


def test_a_list_passed_in_cannot_be_mutated_through_the_record():
    supplied = [eligible()]
    built = snapshot(results=supplied)
    supplied.append(eligible(symbol="MSFT"))
    assert len(built.results) == 1


# -- SymbolScanResult invariants -----------------------------------------


def test_eligible_requires_state_and_counts():
    with pytest.raises(ScannerError):
        eligible(state=None)
    with pytest.raises(ScannerError):
        eligible(counts=None)


def test_eligible_requires_a_reason_code():
    with pytest.raises(ScannerError):
        eligible(reason_codes=())


def test_eligible_cannot_carry_the_insufficient_state():
    with pytest.raises(ScannerError):
        eligible(state=AssessmentState.INSUFFICIENT_DATA)


def test_eligible_cannot_be_not_assessable():
    with pytest.raises(ScannerError):
        eligible(category=StructuralCategory.NOT_ASSESSABLE)


def test_a_failure_carries_no_determined_eligibility():
    """Eligibility was never answered: the attempt failed before it could be."""
    assert failed().eligibility is None
    with pytest.raises(ScannerError):
        failed(eligibility=EligibilityStatus.NO_DATA)


def test_a_failure_carries_no_assessment():
    with pytest.raises(ScannerError):
        failed(state=AssessmentState.BULLISH)
    with pytest.raises(ScannerError):
        failed(reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,))
    with pytest.raises(ScannerError):
        failed(bar_count=10)


def test_a_non_failure_must_carry_an_eligibility():
    with pytest.raises(ScannerError):
        SymbolScanResult(symbol="X", eligibility=None,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0)


def test_insufficient_evidence_requires_the_insufficient_state():
    ok = SymbolScanResult(
        symbol="X", eligibility=EligibilityStatus.INSUFFICIENT_EVIDENCE,
        category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
        state=AssessmentState.INSUFFICIENT_DATA, bar_count=10,
    )
    assert ok.eligibility is EligibilityStatus.INSUFFICIENT_EVIDENCE
    with pytest.raises(ScannerError):
        SymbolScanResult(symbol="X", eligibility=EligibilityStatus.INSUFFICIENT_EVIDENCE,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
                         state=AssessmentState.BULLISH)


def test_no_data_reports_no_bars_and_no_assessment():
    ok = SymbolScanResult(symbol="X", eligibility=EligibilityStatus.NO_DATA,
                          category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0)
    assert ok.bar_count == 0
    with pytest.raises(ScannerError):
        SymbolScanResult(symbol="X", eligibility=EligibilityStatus.NO_DATA,
                         category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
                         bar_count=5)


def test_data_cutoff_must_be_timezone_aware():
    with pytest.raises(ScannerError):
        eligible(data_cutoff=datetime(2026, 9, 6, 12, 0))


def test_latest_bar_open_must_be_timezone_aware_when_present():
    with pytest.raises(ScannerError):
        eligible(latest_bar_open=datetime(2026, 9, 6))


def test_error_detail_is_truncated_not_rejected():
    record = failed(error_detail="x" * 5000)
    assert len(record.error_detail) == MAX_ERROR_DETAIL_CHARS


def test_classifying_count_excludes_abstentions():
    record = eligible(counts=AssessmentCounts(bullish=1, bearish=1, neutral=1, insufficient=3))
    assert record.classifying_count == 3


def test_classifying_count_is_zero_without_counts():
    assert failed().classifying_count == 0


# -- counters ------------------------------------------------------------


def test_counter_invariants_hold_for_a_consistent_scan():
    counters = ScanCounters(
        symbols_total=10, symbols_attempted=10, symbols_completed=10,
        symbols_eligible=6, symbols_no_data=1, symbols_insufficient_evidence=1,
        symbols_failed=2, rows_ordered=6, provider_failures=2,
    )
    assert counters.terminal_total == 10
    assert counters.is_consistent


@pytest.mark.parametrize(
    "change",
    [
        {"symbols_completed": 9},            # buckets do not sum
        {"provider_failures": 5},            # more provider failures than failures
        {"rows_ordered": 5},                 # rows disagree with eligible
        {"symbols_attempted": 11},           # attempted exceeds total
    ],
)
def test_inconsistent_counters_are_detectable(change):
    fields = dict(
        symbols_total=10, symbols_attempted=10, symbols_completed=10,
        symbols_eligible=6, symbols_no_data=1, symbols_insufficient_evidence=1,
        symbols_failed=2, rows_ordered=6, provider_failures=2,
    )
    fields.update(change)
    assert not ScanCounters(**fields).is_consistent


def test_counters_reject_negative_and_boolean_values():
    with pytest.raises(ScannerError):
        ScanCounters(symbols_total=-1)
    with pytest.raises(ScannerError):
        ScanCounters(symbols_total=True)


# -- scan status ---------------------------------------------------------


def test_status_is_decided_only_by_operational_errors():
    insufficient = SymbolScanResult(
        symbol="X", eligibility=EligibilityStatus.INSUFFICIENT_EVIDENCE,
        category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
        state=AssessmentState.INSUFFICIENT_DATA, bar_count=5,
    )
    no_data = SymbolScanResult(symbol="Y", eligibility=EligibilityStatus.NO_DATA,
                               category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0)
    assert status_for((eligible(),)) is ScanStatus.ALL_OK
    assert status_for((eligible(), insufficient)) is ScanStatus.ALL_OK
    assert status_for((insufficient, no_data)) is ScanStatus.ALL_OK
    assert status_for((eligible(), failed())) is ScanStatus.PARTIAL
    assert status_for((no_data, failed())) is ScanStatus.PARTIAL
    assert status_for((failed(), failed(symbol="CCC"))) is ScanStatus.ALL_FAILED


def test_a_completed_scan_has_at_least_one_result():
    with pytest.raises(ScannerError):
        status_for(())


# -- snapshot ------------------------------------------------------------


def test_snapshot_rejects_a_completion_before_its_start():
    with pytest.raises(ScannerError):
        snapshot(scan_completed_at=T0 - timedelta(seconds=1))


def test_snapshot_allows_equal_start_and_completion():
    assert snapshot(scan_completed_at=T0).duration_seconds == 0


def test_snapshot_requires_aware_timestamps():
    with pytest.raises(ScannerError):
        snapshot(scan_started_at=datetime(2026, 9, 6, 12, 0))


def test_snapshot_requires_a_full_fingerprint():
    with pytest.raises(ScannerError):
        snapshot(universe_fingerprint="abc")


def test_a_symbol_may_appear_only_once():
    duplicated = (eligible(), eligible())
    with pytest.raises(ScannerError, match="at most once"):
        MarketScanSnapshot(
            universe_id="demo", universe_fingerprint=FP, universe_display_name="Demo",
            universe_as_of=AS_OF, interval=Interval.DAY_1, basis=PriceBasis.RAW,
            policy_fingerprint="p" * 16, warmup_bars=51,
            minimum_sufficient_observations=2, scan_started_at=T0,
            scan_completed_at=T0 + timedelta(seconds=30), results=duplicated,
            counters=ScanCounters.from_results(duplicated, symbols_total=2),
            status=status_for(duplicated),
        )


def test_snapshot_carries_no_global_market_cutoff():
    from dataclasses import fields as dataclass_fields

    names = {f.name for f in dataclass_fields(MarketScanSnapshot)}
    for forbidden in ("market_cutoff", "data_cutoff", "as_of_market"):
        assert forbidden not in names
    # Each result carries its own instead.
    assert snapshot().results[0].data_cutoff == T0


def test_snapshot_retains_no_series_or_research_snapshot():
    from dataclasses import fields as dataclass_fields

    names = {f.name for f in dataclass_fields(MarketScanSnapshot)}
    names |= {f.name for f in dataclass_fields(SymbolScanResult)}
    for forbidden in ("series", "bars", "snapshot", "features", "observations"):
        assert forbidden not in names


def test_failures_property_lists_only_operational_failures():
    built = snapshot(results=(eligible(), failed()))
    assert built.status is ScanStatus.PARTIAL
    assert [r.symbol for r in built.failures] == ["BBB"]


# -- a snapshot may not contradict itself --------------------------------


@pytest.mark.parametrize(
    "results, claimed",
    [
        ((eligible(), failed()), ScanStatus.ALL_OK),
        ((eligible(), failed()), ScanStatus.ALL_FAILED),
        ((eligible(),), ScanStatus.PARTIAL),
        ((eligible(),), ScanStatus.ALL_FAILED),
        ((failed(),), ScanStatus.ALL_OK),
    ],
)
def test_a_status_contradicting_the_results_is_refused(results, claimed):
    """Status is derived, not asserted: a helper a caller may forget to call is
    not an invariant."""
    with pytest.raises(ScannerError, match="contradicts"):
        snapshot(results=results, status=claimed)


def test_counters_contradicting_the_results_are_refused():
    with pytest.raises(ScannerError, match="disagree"):
        snapshot(results=(eligible(),),
                 counters=ScanCounters(symbols_total=999, symbols_attempted=999,
                                       symbols_completed=999, symbols_eligible=999,
                                       rows_ordered=999))


def test_symbols_total_may_not_be_fewer_than_completed():
    results = (eligible(), failed())
    with pytest.raises(ScannerError):
        snapshot(results=results,
                 counters=ScanCounters.from_results(results, symbols_total=1))


def test_counters_from_results_counts_every_bucket():
    insufficient = SymbolScanResult(
        symbol="CCC", eligibility=EligibilityStatus.INSUFFICIENT_EVIDENCE,
        category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0,
        state=AssessmentState.INSUFFICIENT_DATA, bar_count=5,
    )
    no_data = SymbolScanResult(symbol="DDD", eligibility=EligibilityStatus.NO_DATA,
                               category=StructuralCategory.NOT_ASSESSABLE, data_cutoff=T0)
    results = (eligible(), failed(), insufficient, no_data)
    counters = ScanCounters.from_results(results, symbols_total=10)
    assert counters.symbols_total == 10
    assert counters.symbols_completed == 4
    assert counters.symbols_eligible == 1
    assert counters.symbols_failed == 1
    assert counters.symbols_insufficient_evidence == 1
    assert counters.symbols_no_data == 1
    assert counters.rows_ordered == 1
    assert counters.provider_failures == 1
    assert counters.is_consistent
    assert counters.terminal_total == 4


def test_a_failure_is_not_counted_as_no_data():
    """The two are separate buckets; conflating them would double-count."""
    counters = ScanCounters.from_results((failed(),), symbols_total=1)
    assert counters.symbols_failed == 1
    assert counters.symbols_no_data == 0


# -- universe records ----------------------------------------------------


def test_universe_requires_sorted_deduplicated_symbols():
    with pytest.raises(ScannerError):
        universe(symbols=("MSFT", "AAPL"))
    with pytest.raises(ScannerError):
        universe(symbols=("AAPL", "AAPL"))


def test_universe_requires_at_least_one_symbol():
    with pytest.raises(ScannerError):
        universe(symbols=())


def test_universe_enforces_the_symbol_ceiling():
    with pytest.raises(ScannerError):
        universe(symbols=tuple(sorted(f"S{n:03d}" for n in range(MAX_SYMBOLS_PER_UNIVERSE + 1))))


def test_universe_as_of_must_be_a_date_not_a_datetime():
    with pytest.raises(ScannerError):
        universe(as_of=datetime(2026, 9, 6, tzinfo=UTC))


def test_universe_id_is_a_bounded_slug():
    assert require_universe_id(" Demo-1 ") == "demo-1"
    for bad in ("", "a/b", "a\\b", "../etc", "a b", "a\x00b", "x" * 200, 1, None):
        with pytest.raises(ScannerError):
            require_universe_id(bad)


def test_configuration_refuses_duplicate_universe_ids():
    with pytest.raises(ScannerError):
        UniverseConfiguration(universes=(universe(), universe()))


def test_configuration_enforces_the_universe_ceiling():
    many = tuple(universe(universe_id=f"u{n}") for n in range(MAX_UNIVERSES + 1))
    with pytest.raises(ScannerError):
        UniverseConfiguration(universes=many)


def test_configuration_embeds_its_load_report():
    from dataclasses import fields as dataclass_fields

    assert "load_report" in {f.name for f in dataclass_fields(UniverseConfiguration)}
    assert isinstance(UniverseConfiguration().load_report, UniverseLoadReport)


def test_an_empty_configuration_is_a_state_not_an_error():
    config = UniverseConfiguration()
    assert config.is_empty
    assert config.enabled == ()
