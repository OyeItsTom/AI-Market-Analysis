"""Phase 10 Stage E orchestration: many symbols, one snapshot, no interpretation.

The scanner's job is to reuse the existing single-symbol pipeline and record
what came back. So most of these tests are about what it must *not* do: skip a
symbol, retry one, abort on a failure, turn a research shortage into an
execution failure, or hide a programming bug inside a result row.

Symbol fixtures are chosen adversarially -- names whose alphabetical order runs
against the expected outcome -- because a fixture that sorts the way the
assertion expects can pass while the logic is broken.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.scanner import (
    SCANNER_INTERVALS,
    MarketScanner,
    ScanProgress,
    ScanRequestError,
    ranked_rows,
    research_policy_fingerprint,
)
from src.application.snapshot import (
    BASIS,
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    build_snapshot,
)
from src.assessments.assessment import AssessmentState
from src.data.models import Interval
from src.scanner.models import (
    EligibilityStatus,
    ScanErrorCode,
    ScanStatus,
    StructuralCategory,
)
from src.scanner.universe import build_universe
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
AS_OF = date(2026, 9, 6)

#: Deliberately anti-alphabetical: normalization sorts these to
#: (AAA, MMM, ZZZ), so a test that depended on input order would fail.
SYMBOLS = ["ZZZ", "AAA", "MMM"]


def universe(symbols=None, universe_id="demo"):
    definition, _ = build_universe(
        universe_id=universe_id,
        display_name="Demo universe",
        symbols=list(symbols if symbols is not None else SYMBOLS),
        source_kind="local_static",
        source_reference="illustrative research-demo membership",
        as_of=AS_OF,
    )
    return definition


class Builder:
    """Records every call and replays a per-symbol script."""

    def __init__(self, script=None, default_bars=300):
        self.script = script or {}
        self.default_bars = default_bars
        self.calls: list[str] = []

    def __call__(self, provider, symbol, interval, *, now):
        self.calls.append(symbol)
        action = self.script.get(symbol, self.default_bars)
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            return action(symbol, interval, now)
        return build_snapshot(RecordingProvider(action), symbol, interval, now=now)


def scanner(builder=None, now=None):
    return MarketScanner(
        RecordingProvider(300),
        build=builder or Builder(),
        now=now or (lambda: T0),
    )


# -- serial order and one call per symbol --------------------------------


def test_symbols_are_scanned_in_normalized_order():
    """Not input order: the universe sorts, and the scan follows the universe."""
    builder = Builder()
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert builder.calls == ["AAA", "MMM", "ZZZ"]
    assert builder.calls != SYMBOLS


def test_build_is_called_exactly_once_per_symbol():
    builder = Builder()
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert len(builder.calls) == len(set(builder.calls)) == 3


def test_no_symbol_is_skipped():
    builder = Builder()
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert {r.symbol for r in snapshot.results} == {"AAA", "MMM", "ZZZ"}
    assert len(snapshot.results) == 3


def test_the_injected_builder_is_actually_used():
    """Otherwise the tests would silently exercise the real network path."""
    builder = Builder()
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert builder.calls, "the injected builder was never called"


def test_a_failure_is_not_retried():
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "market data", "down")})
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert builder.calls.count("MMM") == 1


# -- partial failure -----------------------------------------------------


def test_one_failure_does_not_abort_its_siblings():
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "market data", "down")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert builder.calls == ["AAA", "MMM", "ZZZ"], "the scan stopped early"
    assert len(snapshot.results) == 3
    assert snapshot.status is ScanStatus.PARTIAL
    by_symbol = {r.symbol: r for r in snapshot.results}
    assert by_symbol["MMM"].error_code is ScanErrorCode.PROVIDER_UNAVAILABLE
    assert by_symbol["AAA"].eligibility is EligibilityStatus.ELIGIBLE
    assert by_symbol["ZZZ"].eligibility is EligibilityStatus.ELIGIBLE


def test_partial_failure_counters_are_consistent():
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "market data", "down")})
    counters = scanner(builder).scan(universe(), Interval.DAY_1).counters
    assert counters.symbols_total == 3
    assert counters.symbols_completed == 3
    assert counters.symbols_failed == 1
    assert counters.symbols_eligible == 2
    assert counters.rows_ordered == 2
    assert counters.provider_failures == 1
    assert counters.is_consistent


# -- all failed ----------------------------------------------------------


def test_every_symbol_failing_reports_all_failed():
    builder = Builder({s: ApplicationError(FailureKind.PROVIDER, "market data", "down")
                       for s in ("AAA", "MMM", "ZZZ")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.ALL_FAILED
    assert len(snapshot.results) == 3
    assert snapshot.counters.symbols_failed == 3
    assert snapshot.counters.provider_failures == 3
    assert snapshot.counters.symbols_eligible == 0
    assert all(r.eligibility is None for r in snapshot.results)


def test_provider_failures_are_a_subset_of_failures():
    builder = Builder({
        "AAA": ApplicationError(FailureKind.PROVIDER, "market data", "down"),
        "MMM": ApplicationError(FailureKind.DATA_QUALITY, "market data", "bad bars"),
        "ZZZ": ApplicationError(FailureKind.DOMAIN, "market data", "wrong symbol"),
    })
    counters = scanner(builder).scan(universe(), Interval.DAY_1).counters
    assert counters.symbols_failed == 3
    assert counters.provider_failures == 1


# -- research insufficiency is NOT operational failure -------------------


def test_a_scan_of_entirely_unassessable_symbols_still_succeeded():
    """The critical case: nothing went wrong, the symbols just had little to say."""
    builder = Builder(default_bars=0)
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.ALL_OK
    assert snapshot.counters.symbols_failed == 0
    assert snapshot.counters.symbols_no_data == 3
    assert all(r.eligibility is EligibilityStatus.NO_DATA for r in snapshot.results)


def test_insufficient_evidence_is_also_a_successful_scan():
    builder = Builder(default_bars=5)
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.ALL_OK
    assert snapshot.counters.symbols_insufficient_evidence == 3
    assert snapshot.counters.symbols_failed == 0
    for result in snapshot.results:
        assert result.eligibility is EligibilityStatus.INSUFFICIENT_EVIDENCE
        assert result.state is AssessmentState.INSUFFICIENT_DATA
        assert result.category is StructuralCategory.NOT_ASSESSABLE


def test_a_mix_of_non_error_outcomes_is_all_ok():
    builder = Builder({"AAA": 300, "MMM": 0, "ZZZ": 5})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.ALL_OK
    assert snapshot.counters.symbols_eligible == 1
    assert snapshot.counters.symbols_no_data == 1
    assert snapshot.counters.symbols_insufficient_evidence == 1


# -- unexpected exceptions ----------------------------------------------


def test_an_unexpected_symbol_exception_is_contained():
    builder = Builder({"MMM": RuntimeError("something nobody predicted")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    by_symbol = {r.symbol: r for r in snapshot.results}
    assert by_symbol["MMM"].error_code is ScanErrorCode.UNEXPECTED
    assert "RuntimeError" in by_symbol["MMM"].error_detail
    assert by_symbol["AAA"].eligibility is EligibilityStatus.ELIGIBLE
    assert len(snapshot.results) == 3


@pytest.mark.parametrize(
    "kind, expected",
    [
        (FailureKind.PROVIDER, ScanErrorCode.PROVIDER_UNAVAILABLE),
        (FailureKind.DATA_QUALITY, ScanErrorCode.DATA_QUALITY),
        (FailureKind.DOMAIN, ScanErrorCode.SYMBOL_MISMATCH),
        (FailureKind.REQUEST, ScanErrorCode.REQUEST_INVALID),
        (FailureKind.UNEXPECTED, ScanErrorCode.UNEXPECTED),
    ],
)
def test_every_failure_kind_maps_through_the_scanner_taxonomy(kind, expected):
    builder = Builder({"AAA": ApplicationError(kind, "market data", "boom")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert {r.symbol: r for r in snapshot.results}["AAA"].error_code is expected


def test_error_detail_is_bounded_and_carries_no_traceback():
    from src.scanner.models import MAX_ERROR_DETAIL_CHARS

    builder = Builder({"AAA": ApplicationError(FailureKind.PROVIDER, "s", "x" * 5000)})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    detail = {r.symbol: r for r in snapshot.results}["AAA"].error_detail
    assert len(detail) == MAX_ERROR_DETAIL_CHARS
    assert "Traceback" not in detail


# -- global failures stay loud -------------------------------------------


@pytest.mark.parametrize("interval", [Interval.WEEK_1, Interval.MONTH_1, "1h", "5m"])
def test_an_unsupported_interval_is_refused_before_any_work(interval):
    builder = Builder()
    with pytest.raises(ScanRequestError):
        scanner(builder).scan(universe(), interval)
    assert builder.calls == [], "a provider call was made for a refused request"


def test_the_supported_interval_is_daily_only():
    assert SCANNER_INTERVALS == (Interval.DAY_1,)
    assert scanner().scan(universe(), Interval.DAY_1).interval is Interval.DAY_1


def test_a_non_universe_argument_is_refused():
    with pytest.raises(ScanRequestError):
        scanner().scan("demo", Interval.DAY_1)


def test_a_callback_failure_fails_the_scan_rather_than_hiding():
    """A broken callback is an application bug, not a market condition.

    Swallowing it would let a UI defect masquerade as a clean scan.
    """
    def broken(progress):
        raise ValueError("callback is broken")

    with pytest.raises(ValueError, match="callback is broken"):
        scanner().scan(universe(), Interval.DAY_1, progress=broken)


def test_an_invariant_failure_is_not_disguised_as_a_symbol_error(monkeypatch):
    """A bug in the scanner's own summarising must propagate, not become a row."""
    import src.application.scanner as module

    def broken(state, reason_codes=()):
        raise AssertionError("scanner invariant broken")

    monkeypatch.setattr(module, "status_for", broken)
    with pytest.raises(AssertionError, match="invariant"):
        scanner().scan(universe(), Interval.DAY_1)


# -- timing --------------------------------------------------------------


def test_each_symbol_keeps_its_own_data_cutoff():
    """A scan spanning minutes never observed one simultaneous market state."""
    times = iter([
        T0,                                   # scan start
        T0 + timedelta(minutes=1),            # AAA
        T0 + timedelta(minutes=2),            # MMM
        T0 + timedelta(minutes=3),            # ZZZ
        T0 + timedelta(minutes=4),            # scan completion
    ])
    clock = lambda: next(times)

    def build(provider, symbol, interval, *, now):
        return build_snapshot(RecordingProvider(300), symbol, interval, now=now)

    snapshot = MarketScanner(RecordingProvider(300), build=build, now=clock).scan(
        universe(), Interval.DAY_1
    )
    cutoffs = [r.data_cutoff for r in snapshot.results]
    assert len(set(cutoffs)) == 3, "per-symbol cutoffs were collapsed into one"
    assert snapshot.scan_started_at == T0
    assert snapshot.scan_completed_at > snapshot.scan_started_at


def test_the_snapshot_has_no_global_market_cutoff():
    from dataclasses import fields

    from src.scanner.models import MarketScanSnapshot

    names = {f.name for f in fields(MarketScanSnapshot)}
    assert "market_cutoff" not in names
    assert "data_cutoff" not in names


def test_scan_times_are_timezone_aware():
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    assert snapshot.scan_started_at.tzinfo is not None
    assert snapshot.scan_completed_at.tzinfo is not None


def test_a_naive_clock_is_refused():
    naive = MarketScanner(RecordingProvider(300), build=Builder(),
                          now=lambda: datetime(2026, 9, 6, 12, 0))
    with pytest.raises(ScanRequestError):
        naive.scan(universe(), Interval.DAY_1)


# -- summaries only ------------------------------------------------------


def test_no_research_snapshot_or_series_is_retained():
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    for result in snapshot.results:
        for attribute in ("series", "bars", "features", "observations", "snapshot"):
            assert not hasattr(result, attribute), attribute


def test_latest_bar_open_is_present_for_bars_and_absent_without_them():
    builder = Builder({"AAA": 300, "MMM": 0, "ZZZ": 300})
    by_symbol = {r.symbol: r for r in
                 scanner(builder).scan(universe(), Interval.DAY_1).results}
    assert by_symbol["AAA"].latest_bar_open is not None
    assert by_symbol["MMM"].latest_bar_open is None
    assert by_symbol["MMM"].bar_count == 0


# -- policy metadata -----------------------------------------------------


def test_scan_metadata_matches_what_build_snapshot_actually_used():
    """The contract test: compare against a *real* research snapshot.

    Asserting ``snapshot.warmup_bars == WARMUP_BARS`` would be a tautology --
    both sides come from the same import, so it proves the scanner copied a
    constant, not that the constant still describes the research the scan ran.
    Building one snapshot through the real path and comparing catches drift in
    the ensemble, the warm-up or the policy, because all three change what
    ``build_snapshot`` reports.
    """
    reference = build_snapshot(RecordingProvider(300), "AAA", Interval.DAY_1, now=lambda: T0)
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    assert snapshot.policy_fingerprint == reference.policy_fingerprint
    assert snapshot.warmup_bars == reference.warmup_bars
    assert snapshot.basis is reference.basis
    assert snapshot.interval is reference.interval


def test_the_minimum_sufficient_observations_reported_is_the_one_in_force():
    """Changing the policy's minimum changes the fingerprint, so the two are
    pinned together rather than each copied independently."""
    reference = build_snapshot(RecordingProvider(300), "AAA", Interval.DAY_1, now=lambda: T0)
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    assert snapshot.minimum_sufficient_observations == MINIMUM_SUFFICIENT_OBSERVATIONS
    # ...and the fingerprint that embeds it agrees with the real research path.
    assert snapshot.policy_fingerprint == reference.policy_fingerprint


def test_policy_metadata_comes_from_the_research_configuration():
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    assert snapshot.policy_fingerprint == research_policy_fingerprint()
    assert snapshot.warmup_bars == WARMUP_BARS
    assert snapshot.minimum_sufficient_observations == MINIMUM_SUFFICIENT_OBSERVATIONS
    assert snapshot.basis is BASIS


def test_policy_metadata_survives_a_scan_with_no_successful_symbol():
    """It must not depend on whichever symbol happened to succeed first.

    Compared against a real research snapshot built separately, so an all-failed
    scan is held to the same contract as a successful one.
    """
    reference = build_snapshot(RecordingProvider(300), "AAA", Interval.DAY_1, now=lambda: T0)
    builder = Builder({s: ApplicationError(FailureKind.PROVIDER, "s", "down")
                       for s in ("AAA", "MMM", "ZZZ")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.ALL_FAILED
    assert snapshot.policy_fingerprint == reference.policy_fingerprint
    assert snapshot.warmup_bars == reference.warmup_bars
    assert snapshot.basis is reference.basis


def test_the_policy_fingerprint_is_the_real_one():
    from src.application.snapshot import build_ensemble, build_policy

    assert research_policy_fingerprint() == build_policy(build_ensemble()).fingerprint
    assert len(research_policy_fingerprint()) > 0


# -- ordering ------------------------------------------------------------


def test_results_are_stored_in_universe_order():
    """Execution history stays transparent; presentation order is derived."""
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    assert [r.symbol for r in snapshot.results] == list(universe().symbols)


def test_ranked_rows_are_derived_and_exclude_unassessable_results():
    builder = Builder({"AAA": 0, "MMM": 300, "ZZZ": 300})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    rows = ranked_rows(snapshot)
    assert {r.symbol for r in rows} == {"MMM", "ZZZ"}
    assert [r.symbol for r in snapshot.results] == ["AAA", "MMM", "ZZZ"]


def test_ordering_never_depends_on_direction():
    """Ranking is structural; the scanner must not reorder by market direction."""
    snapshot = scanner().scan(universe(), Interval.DAY_1)
    for result in ranked_rows(snapshot):
        assert result.state in (AssessmentState.BULLISH, AssessmentState.BEARISH,
                                AssessmentState.NEUTRAL, AssessmentState.CONFLICTED)


# -- progress ------------------------------------------------------------


def test_progress_is_reported_once_per_completed_symbol():
    events: list[ScanProgress] = []
    scanner().scan(universe(), Interval.DAY_1, progress=events.append)
    assert [e.symbol for e in events] == ["AAA", "MMM", "ZZZ"]
    assert [e.completed for e in events] == [1, 2, 3]
    assert all(e.total == 3 for e in events)


def test_progress_reports_a_running_failure_count():
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "down")})
    events: list[ScanProgress] = []
    scanner(builder).scan(universe(), Interval.DAY_1, progress=events.append)
    assert [e.failures for e in events] == [0, 1, 1]


def test_progress_is_optional():
    assert scanner().scan(universe(), Interval.DAY_1).status is ScanStatus.ALL_OK


def test_no_progress_is_reported_for_a_refused_request():
    events: list[ScanProgress] = []
    with pytest.raises(ScanRequestError):
        scanner().scan(universe(), Interval.WEEK_1, progress=events.append)
    assert events == []


def test_progress_is_not_stored_in_the_snapshot():
    from dataclasses import fields

    from src.scanner.models import MarketScanSnapshot

    names = {f.name for f in fields(MarketScanSnapshot)}
    assert "progress" not in names
    assert not [n for n in names if "progress" in n]


# -- atomicity -----------------------------------------------------------


def test_a_snapshot_is_returned_only_once_the_loop_finishes():
    """Nothing is published half-built: progress sees no snapshot at all."""
    seen: list[object] = []

    def watcher(progress):
        seen.append(progress)

    snapshot = scanner().scan(universe(), Interval.DAY_1, progress=watcher)
    assert all(isinstance(item, ScanProgress) for item in seen)
    assert len(snapshot.results) == 3


# -- the catch boundary: our bugs stay loud ------------------------------


@pytest.mark.parametrize("helper", ["category_for", "eligibility_for"])
def test_a_bug_in_the_scanners_own_mapping_is_not_a_symbol_error(monkeypatch, helper):
    """Summarising is the scanner's logic, so a fault there must propagate.

    Caught, it would turn a programming defect into an ``UNEXPECTED`` row and a
    whole scan could report ALL_FAILED while the market was perfectly fine.
    """
    import src.application.scanner as module

    def broken(*args, **kwargs):
        raise AssertionError("scanner mapping is broken")

    monkeypatch.setattr(module, helper, broken)
    with pytest.raises(AssertionError, match="scanner mapping"):
        scanner().scan(universe(), Interval.DAY_1)


def test_a_result_invariant_violation_propagates(monkeypatch):
    """A SymbolScanResult that cannot be constructed is our bug, not the market's."""
    import src.application.scanner as module

    class Rejecting:
        def __init__(self, *args, **kwargs):
            raise AssertionError("result invariant violated")

    monkeypatch.setattr(module, "SymbolScanResult", Rejecting)
    with pytest.raises(AssertionError, match="invariant"):
        scanner().scan(universe(), Interval.DAY_1)


def test_a_genuine_provider_failure_is_still_contained():
    """The narrowed catch must not have broken per-symbol isolation."""
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "market data", "down")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert snapshot.status is ScanStatus.PARTIAL
    assert len(snapshot.results) == 3


def test_a_generic_builder_exception_is_still_contained():
    builder = Builder({"MMM": RuntimeError("provider library blew up")})
    snapshot = scanner(builder).scan(universe(), Interval.DAY_1)
    assert {r.symbol: r for r in snapshot.results}["MMM"].error_code is ScanErrorCode.UNEXPECTED
    assert len(snapshot.results) == 3


# -- failed-symbol cutoff semantics --------------------------------------


def test_a_failed_symbol_records_the_attempt_time_not_a_market_cutoff():
    """No market data was obtained, so none is claimed.

    ``error_code`` being set is what tells a reader the timestamp is an attempt
    time: an errored result carries no bars, no assessment and no eligibility.
    """
    builder = Builder({"AAA": ApplicationError(FailureKind.PROVIDER, "s", "down")})
    result = {r.symbol: r for r in
              scanner(builder).scan(universe(), Interval.DAY_1).results}["AAA"]
    assert result.error_code is not None
    assert result.bar_count == 0
    assert result.latest_bar_open is None
    assert result.eligibility is None
    assert result.data_cutoff.tzinfo is not None


def test_a_successful_cutoff_is_the_snapshots_own_build_time():
    """Not the scan start, not the scan end, not the latest bar."""
    built_at = T0 + timedelta(hours=3)

    def build(provider, symbol, interval, *, now):
        return build_snapshot(RecordingProvider(300), symbol, interval,
                              now=lambda: built_at)

    snapshot = MarketScanner(RecordingProvider(300), build=build, now=lambda: T0).scan(
        universe(), Interval.DAY_1
    )
    for result in snapshot.results:
        assert result.data_cutoff == built_at
        assert result.data_cutoff != snapshot.scan_started_at
        assert result.data_cutoff != result.latest_bar_open


# -- reuse and isolation -------------------------------------------------


def test_the_same_scanner_can_be_reused_without_state_leaking():
    instance = scanner()
    first = instance.scan(universe(), Interval.DAY_1)
    second = instance.scan(universe(), Interval.DAY_1)
    assert len(first.results) == len(second.results) == 3
    assert first.counters.symbols_failed == second.counters.symbols_failed == 0
    assert sorted(vars(instance)) == ["_build", "_now", "_provider"]


def test_a_failed_scan_does_not_poison_the_next_one():
    builder = Builder({"MMM": ApplicationError(FailureKind.PROVIDER, "s", "down")})
    instance = scanner(builder)
    assert instance.scan(universe(), Interval.DAY_1).counters.symbols_failed == 1
    builder.script = {}
    assert instance.scan(universe(), Interval.DAY_1).counters.symbols_failed == 0


def test_the_provider_is_reused_not_reconstructed():
    seen: list[int] = []

    def build(provider, symbol, interval, *, now):
        seen.append(id(provider))
        return build_snapshot(RecordingProvider(300), symbol, interval, now=now)

    provider = RecordingProvider(300)
    MarketScanner(provider, build=build, now=lambda: T0).scan(universe(), Interval.DAY_1)
    assert set(seen) == {id(provider)}


# -- callback safety -----------------------------------------------------


def test_progress_carries_only_frozen_primitives():
    from dataclasses import FrozenInstanceError

    events: list[ScanProgress] = []
    scanner().scan(universe(), Interval.DAY_1, progress=events.append)
    event = events[0]
    with pytest.raises(FrozenInstanceError):
        event.completed = 99
    for forbidden in ("results", "provider", "scanner", "snapshot", "universe"):
        assert not hasattr(event, forbidden), forbidden


def test_a_callback_abort_publishes_no_snapshot_and_stops_the_scan():
    """Precisely: no MarketScanSnapshot is returned. Earlier progress events
    were already observed by the callback, which is unavoidable and harmless --
    the scanner itself publishes nothing."""
    builder = Builder()

    def failing(progress):
        if progress.completed == 2:
            raise ValueError("callback broke")

    with pytest.raises(ValueError, match="callback broke"):
        scanner(builder).scan(universe(), Interval.DAY_1, progress=failing)
    assert builder.calls == ["AAA", "MMM"], "the third symbol was still processed"


def test_a_clock_running_backwards_is_refused():
    times = iter([T0 + timedelta(hours=1)] + [T0] * 20)
    instance = MarketScanner(RecordingProvider(300), build=Builder(),
                             now=lambda: next(times))
    with pytest.raises(Exception):
        instance.scan(universe(), Interval.DAY_1)


# -- every real interval ------------------------------------------------


@pytest.mark.parametrize("interval", [i for i in Interval if i is not Interval.DAY_1])
def test_every_unsupported_interval_is_refused_without_a_build(interval):
    """Enumerated from the real enum, not a hand-picked pair."""
    builder = Builder()
    with pytest.raises(ScanRequestError):
        scanner(builder).scan(universe(), interval)
    assert builder.calls == []


def test_a_generic_exception_is_not_retried_either():
    """The ApplicationError path and the generic path both need pinning.

    ``test_a_failure_is_not_retried`` only exercises the ApplicationError
    branch, so a retry added to the generic handler would go unnoticed.
    """
    builder = Builder({"MMM": RuntimeError("provider library blew up")})
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert builder.calls == ["AAA", "MMM", "ZZZ"]
    assert builder.calls.count("MMM") == 1


def test_the_total_build_count_equals_the_symbol_count_even_with_failures():
    builder = Builder({
        "AAA": RuntimeError("boom"),
        "MMM": ApplicationError(FailureKind.PROVIDER, "s", "down"),
    })
    scanner(builder).scan(universe(), Interval.DAY_1)
    assert len(builder.calls) == 3


def test_no_result_secretly_retains_a_research_object():
    """Checked on the objects a result actually holds, not on field names.

    A snapshot smuggled onto a result under any attribute would keep a whole
    BarSeries alive per symbol -- the memory bound this summary exists to give.
    """
    from src.application.snapshot import ResearchSnapshot
    from src.data.series import BarSeries

    snapshot = scanner().scan(universe(), Interval.DAY_1)
    forbidden = (ResearchSnapshot, BarSeries)
    for result in snapshot.results:
        held = list(vars(result).values()) if hasattr(result, "__dict__") else []
        for value in held:
            assert not isinstance(value, forbidden), (
                f"{result.symbol} retains a {type(value).__name__}"
            )
        for name in dir(result):
            if name.startswith("__"):
                continue
            assert not isinstance(getattr(result, name, None), forbidden), name


def test_the_snapshot_itself_retains_no_research_objects():
    from src.application.snapshot import ResearchSnapshot
    from src.data.series import BarSeries

    snapshot = scanner().scan(universe(), Interval.DAY_1)
    for name in dir(snapshot):
        if name.startswith("__"):
            continue
        value = getattr(snapshot, name, None)
        assert not isinstance(value, (ResearchSnapshot, BarSeries)), name
