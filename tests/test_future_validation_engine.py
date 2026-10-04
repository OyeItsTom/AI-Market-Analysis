"""FUTURE_VALIDATION_V1 pure engine: stop rule, population, Phase R benchmark reuse, categories.

Synthetic, offline, in memory. The Phase R equivalence tests run the frozen
Phase R engine and this engine over one synthetic study and require
identical numbers.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.evaluation import OutcomeSpec, OutcomeStatus
from src.research import run_study
from src.research.future_validation import (
    CATEGORY_CONSISTENT,
    CATEGORY_INCONCLUSIVE,
    CATEGORY_INVALID,
    CATEGORY_MIXED,
    CATEGORY_REVERSED,
    FUTURE_VALIDATION_V1,
    FutureValidationDefinitionError,
    RetrospectiveReference,
)
from src.research.future_validation_engine import (
    ClaimStamp,
    FutureValidationError,
    LevelOneEvidence,
    LevelThreeEvidence,
    Measurement,
    Observation,
    OutcomeStamp,
    add_calendar_months,
    build_result,
    canonical_bytes,
    classify,
    cutoffs,
    decode_canonical,
    describe_cell,
    episode_start_values,
    evaluate_stop_rule,
    evidence_through,
    magnitude_ratio,
    matured_claim_counts,
    months_elapsed,
    primary_result,
    render_report,
    secondary_results,
    StopRuleEvaluation,
)
from src.strategies import MomentumInTrendContext, TrendAlignment, TrendCrossover
from tests.future_validation_fixtures import (  # noqa: F401 - autouse firewall
    ACTIVATED_AT,
    LEAK,
    MOMENTUM,
    TREND,
    Book,
    episodes,
    future_validation_firewall,
    session,
)
from tests.research_fixtures import synthetic_series
from tests.test_research_definition import small_definition as small_study

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
V1 = FUTURE_VALIDATION_V1
REF = {r.symbol: r for r in V1.references}
MICRO = timedelta(microseconds=1)


# -- calendar months --------------------------------------------------------------------------


class TestCalendarMonths:
    def test_month_end_clamps_to_the_last_day(self):
        assert add_calendar_months(datetime(2026, 1, 31, 12, tzinfo=UTC), 1) == \
            datetime(2026, 2, 28, 12, tzinfo=UTC)
        assert add_calendar_months(datetime(2026, 8, 31, tzinfo=UTC), 1) == \
            datetime(2026, 9, 30, tzinfo=UTC)
        assert add_calendar_months(datetime(2026, 12, 31, tzinfo=UTC), 2) == \
            datetime(2027, 2, 28, tzinfo=UTC)

    def test_leap_years(self):
        assert add_calendar_months(datetime(2027, 1, 31, tzinfo=UTC), 13) == \
            datetime(2028, 2, 29, tzinfo=UTC)
        assert add_calendar_months(datetime(2028, 2, 29, 9, tzinfo=UTC), 48) == \
            datetime(2032, 2, 29, 9, tzinfo=UTC)
        assert add_calendar_months(datetime(2028, 2, 29, 9, tzinfo=UTC), 72) == \
            datetime(2034, 2, 28, 9, tzinfo=UTC)
        assert add_calendar_months(datetime(2028, 2, 29, tzinfo=UTC), 12) == \
            datetime(2029, 2, 28, tzinfo=UTC)

    def test_not_an_approximation_of_thirty_days(self):
        start = datetime(2026, 10, 5, 19, tzinfo=UTC)
        assert add_calendar_months(start, 48) != start + timedelta(days=48 * 30)
        assert add_calendar_months(start, 48) == datetime(2030, 10, 5, 19, tzinfo=UTC)

    def test_dst_is_irrelevant_because_the_rule_is_in_utc(self):
        for local in (datetime(2026, 3, 8, 3, 30, tzinfo=NY), datetime(2026, 11, 1, 1, 30,
                                                                          tzinfo=NY),
                      datetime(2026, 7, 1, 23, 59, tzinfo=NY)):
            assert add_calendar_months(local, 48) == \
                add_calendar_months(local.astimezone(UTC), 48)
            assert add_calendar_months(local, 48).tzinfo is UTC

    def test_naive_and_negative_inputs_are_refused(self):
        with pytest.raises(FutureValidationError):
            add_calendar_months(datetime(2026, 1, 1), 1)
        with pytest.raises(FutureValidationError):
            add_calendar_months(datetime(2026, 1, 1, tzinfo=UTC), -1)

    @pytest.mark.parametrize("months", [48, 72])
    def test_exact_boundary_and_one_microsecond_before(self, months):
        due = add_calendar_months(ACTIVATED_AT, months)
        assert months_elapsed(ACTIVATED_AT, due, months)
        assert not months_elapsed(ACTIVATED_AT, due - MICRO, months)

    def test_forty_seven_months_and_twenty_nine_or_thirty_days_is_not_e1(self):
        activated = datetime(2026, 1, 31, 10, tzinfo=UTC)
        due = add_calendar_months(activated, 48)  # 2030-01-31T10:00Z
        forty_seven = add_calendar_months(activated, 47)  # 2029-12-31T10:00Z
        for days in (29, 30):
            assert forty_seven + timedelta(days=days) < due
            assert not months_elapsed(activated, forty_seven + timedelta(days=days), 48)
        assert months_elapsed(activated, due, 48)


# -- stop rule ----------------------------------------------------------------------------------


def stop(evidence, counts):
    """The stop rule with ``evidence`` as the evidence clock (there is no host clock)."""
    return evaluate_stop_rule(V1, activated_at=ACTIVATED_AT, evidence_through=evidence,
                              matured_counts=counts)


E1 = add_calendar_months(ACTIVATED_AT, 48)
F = add_calendar_months(ACTIVATED_AT, 72)
FULL = {"SPY": 750, "QQQ": 750, "IWM": 750}


class TestStopRule:
    def test_frozen_parameters(self):
        assert (V1.stop_rule_minimum_calendar_months, V1.stop_rule_minimum_matured_claims,
                V1.forced_unlock_calendar_months) == (48, 750, 72)

    def test_48_months_and_e2_is_unlockable(self):
        result = stop(E1, FULL)
        assert (result.e1_met, result.e2_met, result.f_met, result.unlockable) == (
            True, True, False, True)
        assert result.basis == "E1_and_E2"

    def test_one_microsecond_before_48_months_is_not(self):
        assert not stop(E1 - MICRO, FULL).unlockable

    @pytest.mark.parametrize("symbol", ["SPY", "QQQ", "IWM"])
    def test_one_symbol_at_749_fails_e2(self, symbol):
        counts = dict(FULL, **{symbol: 749})
        result = stop(E1, counts)
        assert result.e1_met and not result.e2_met and not result.unlockable

    def test_749_and_750_boundaries(self):
        assert not stop(E1, {"SPY": 749, "QQQ": 749, "IWM": 749}).e2_met
        assert stop(E1, FULL).e2_met
        assert stop(E1, {"SPY": 751, "QQQ": 900, "IWM": 750}).e2_met

    def test_secondary_symbols_do_not_count_toward_e2(self):
        result = stop(E1, {"SPY": 750, "QQQ": 750, "IWM": 0, "TLT": 10_000, "GLD": 10_000})
        assert not result.e2_met
        assert dict(result.e2_counts) == {"SPY": 750, "QQQ": 750, "IWM": 0}

    def test_48_months_without_e2_is_not_unlockable(self):
        assert not stop(E1 + timedelta(days=400), {"SPY": 0, "QQQ": 0, "IWM": 0}).unlockable

    def test_exact_72_months_forces_unlock_with_low_counts(self):
        result = stop(F, {"SPY": 3, "QQQ": 0, "IWM": 0})
        assert result.f_met and result.unlockable and result.basis == "F_forced_unlock"
        assert not stop(F - MICRO, {"SPY": 3, "QQQ": 0, "IWM": 0}).unlockable

    def test_e2_alone_before_48_months_is_not_unlockable(self):
        result = stop(E1 - timedelta(days=1), {s: 5000 for s in FULL})
        assert result.e2_met and not result.unlockable

    def test_payload_is_level_one(self):
        payload = stop(E1, FULL).to_payload()
        assert set(payload) == {"activated_at", "basis", "e1_due", "e1_met", "e2_counts",
                                "e2_met", "e2_minimum", "evidence_through", "f_met", "forced_due",
                                "unlockable"}

    def test_matured_counts_from_level_one(self):
        book = Book()
        for symbol in ("SPY", "QQQ", "IWM"):
            for index in range(750):
                book.trend(symbol, index, "bullish" if index % 2 else "bearish", 0.001)
        book.trend("IWM", 750, value=None)  # unmatured: not counted
        counts = matured_claim_counts(V1, book.level_one())
        assert {s: counts[s] for s in FULL} == FULL
        assert stop(E1, counts).unlockable
        book.excluded_artifacts.add(book.claims[0].key)  # one SPY claim degraded
        assert not stop(E1, matured_claim_counts(V1, book.level_one())).e2_met


class TestStopRuleIsBlind:
    def test_level_one_types_have_no_research_field(self):
        forbidden = {"state", "reason_codes", "forward_return", "reference_price",
                     "future_price", "value", "mean", "median", "price"}
        for kind in (ClaimStamp, OutcomeStamp, LevelOneEvidence):
            assert not {f.name for f in fields(kind)} & forbidden, kind.__name__

    def test_stop_rule_functions_take_level_one_only(self):
        for function in (matured_claim_counts, cutoffs):
            hints = inspect.signature(function).parameters
            assert list(hints) == ["definition", "evidence"]
            assert "LevelOneEvidence" in str(hints["evidence"].annotation)
        assert set(inspect.signature(evaluate_stop_rule).parameters) == {
            "definition", "activated_at", "evidence_through", "matured_counts"}
        assert list(inspect.signature(evidence_through).parameters) == ["evidence"]

    def test_level_one_ignores_states_entirely(self):
        bullish, bearish = Book(), Book()
        for index in range(30):
            bullish.trend("SPY", index, "bullish", 0.05)
            bearish.trend("SPY", index, "bearish", -0.05)
        assert matured_claim_counts(V1, bullish.level_one()) == \
            matured_claim_counts(V1, bearish.level_one())
        assert cutoffs(V1, bullish.level_one()) == cutoffs(V1, bearish.level_one())
        assert evidence_through(bullish.level_one()) == evidence_through(bearish.level_one())


# -- the evidence clock --------------------------------------------------------------------------


def at_bar(settled: datetime) -> datetime:
    """The bar timestamp whose settlement (timestamp + one daily period) is ``settled``."""
    return settled - timedelta(days=1)


def book_through(settled: datetime, *, matured: int = 750) -> Book:
    """Evidence whose latest legitimate bar settles exactly at ``settled``."""
    book = Book()
    for symbol in ("SPY", "QQQ", "IWM"):
        for index in range(matured):
            book.trend(symbol, index, "bullish", 0.001)
    book.trend("SPY", 0, value=None, timestamp=at_bar(settled))
    return book


def gate_like(book: Book) -> "StopRuleEvaluation":
    level_one = book.level_one()
    return evaluate_stop_rule(V1, activated_at=ACTIVATED_AT,
                              evidence_through=evidence_through(level_one),
                              matured_counts=matured_claim_counts(V1, level_one))


class TestEvidenceClock:
    """E1 and F run on frozen evidence. No host clock exists in the computation."""

    def test_evidence_through_is_the_latest_settled_legitimate_claim(self):
        book = Book()
        book.trend("SPY", 0)
        book.trend("TLT", 3, value=None)  # any symbol, any state, matured or not
        book.assessment("GLD", 4)  # any producer
        assert evidence_through(book.level_one()) == session(4) + timedelta(days=1)

    def test_excluded_and_reserved_claims_do_not_advance_it(self):
        book = Book()
        book.trend("SPY", 0)
        book.trend("SPY", 9, value=None, excluded=True)  # degraded: excluded
        book.trend("SPY", 0, value=None, timestamp=datetime(2025, 3, 3, 5, tzinfo=UTC))
        assert evidence_through(book.level_one()) == session(0) + timedelta(days=1)
        assert evidence_through(Book().level_one()) is None

    def test_no_evidence_means_no_threshold(self):
        result = stop(None, FULL)
        assert not (result.e1_met or result.f_met or result.unlockable)

    def test_a_evidence_47_months_is_not_unlockable(self):
        assert not gate_like(book_through(add_calendar_months(ACTIVATED_AT, 47))).unlockable

    def test_b_evidence_exactly_48_months_without_e2_is_not_unlockable(self):
        result = gate_like(book_through(E1, matured=0))
        assert result.e1_met and not result.e2_met and not result.unlockable

    def test_c_evidence_48_months_with_e2_is_unlockable(self):
        result = gate_like(book_through(E1))
        assert result.unlockable and result.basis == "E1_and_E2"
        assert result.evidence_through == E1

    def test_d_evidence_exactly_72_months_forces_unlock(self):
        result = gate_like(book_through(F, matured=0))
        assert result.f_met and result.unlockable and result.basis == "F_forced_unlock"

    def test_f_one_microsecond_before_72_months_is_not_f(self):
        assert not gate_like(book_through(F - MICRO, matured=0)).f_met

    def test_g_exactly_72_months_is_f(self):
        assert gate_like(book_through(F, matured=0)).f_met

    def test_h_a_collection_that_stops_at_60_months_never_reaches_f(self):
        result = gate_like(book_through(add_calendar_months(ACTIVATED_AT, 60), matured=10))
        assert not result.f_met and not result.unlockable
        assert result.forced_due == F  # the due date is reported; it is never reached

    def test_evidence_clock_is_not_the_cutoff(self):
        book = Book()
        for index in range(5):
            book.trend("SPY", index)
        book.trend("SPY", 30, value=None)  # later, unmatured: advances the clock only
        level_one = book.level_one()
        assert cutoffs(V1, level_one)["SPY"] == session(4)
        assert evidence_through(level_one) == session(30) + timedelta(days=1)


# -- cutoff --------------------------------------------------------------------------------------


class TestCutoff:
    def test_cutoff_is_the_latest_matured_primary_claim(self):
        book = Book()
        for index in range(10):
            book.trend("SPY", index, value=0.01 if index < 7 else None)
        book.add("SPY", 9, identity=MOMENTUM, returns={20: 0.5})  # other hypothesis: ignored
        assert cutoffs(V1, book.level_one())["SPY"] == session(6)
        assert cutoffs(V1, book.level_one())["QQQ"] is None

    def test_an_excluded_latest_claim_does_not_move_the_cutoff(self):
        book = Book()
        for index in range(5):
            book.trend("SPY", index)
        book.trend("SPY", 5, value=LEAK, excluded=True)
        assert cutoffs(V1, book.level_one())["SPY"] == session(4)

    def test_an_excluded_outcome_does_not_count_as_matured(self):
        book = Book()
        book.trend("SPY", 0)
        book.trend("SPY", 1, value=LEAK, excluded_outcomes=True)
        assert cutoffs(V1, book.level_one())["SPY"] == session(0)
        assert matured_claim_counts(V1, book.level_one())["SPY"] == 1

    def test_later_data_cannot_change_the_result(self):
        book = Book()
        episodes(book, "SPY", 0, "BBNBBNBB")
        unlock = unlock_for(book)
        before = build_result(V1, book.level_three(), unlock=unlock, unlock_sha256="0" * 64)
        # later, unmatured claims (pending at h20) with h5 values: after C_s, outside v1
        for index in range(8, 15):
            book.trend("SPY", index, "bearish", None, returns={5: LEAK})
        after = build_result(V1, book.level_three(), unlock=unlock, unlock_sha256="0" * 64)
        assert canonical_bytes(after) == canonical_bytes(before)


# -- the Phase R cell -----------------------------------------------------------------------------


def unlock_for(book: Book, *, valid_cutoffs=None):
    recorded = cutoffs(V1, book.level_one()) if valid_cutoffs is None else valid_cutoffs
    return {
        "activated_at": ACTIVATED_AT.astimezone(UTC).isoformat(),
        "host_recorded_at": "2030-10-06T16:00:00+00:00",
        "cutoffs": {s: (None if v is None else v.isoformat()) for s, v in recorded.items()},
        "stop_rule": {"basis": "E1_and_E2",
                      "evidence_through": "2030-10-06T04:00:00+00:00"},
        "provenance": {"status": "ok"},
        "snapshot": {"identity": "f" * 64},
    }


def primary(book: Book, symbol: str = "SPY", **kwargs):
    return primary_result(V1, book.level_three(), symbol,
                          cutoffs(V1, book.level_one())[symbol], **kwargs)


class TestAdequacyAndEpisodes:
    def test_minimum_is_eight_bullish_episodes(self):
        assert V1.minimum_bullish_episodes == 8

    @pytest.mark.parametrize("count,adequate", [(7, False), (8, True), (9, True)])
    def test_seven_eight_nine(self, count, adequate):
        book = Book()
        episodes(book, "SPY", 0, "BN" * count)
        result = primary(book)
        assert result.cell.episode_count == count
        assert result.adequate is adequate
        if not adequate:
            assert result.category == CATEGORY_INCONCLUSIVE

    def test_no_bearish_minimum(self):
        book = Book()
        episodes(book, "SPY", 0, "BN" * 8)
        result = primary(book)
        assert result.adequate and result.category != CATEGORY_INCONCLUSIVE
        rows = secondary_results(V1, book.level_three(), cutoffs(V1, book.level_one()))
        bearish = [r for r in rows["B_trend_alignment_bearish"]["rows"]
                   if r["symbol"] == "SPY" and r["horizon_bars"] == 20]
        assert bearish[0]["episode_count"] == 0

    def test_consecutive_sessions_are_one_episode_across_a_weekend(self):
        book = Book()
        episodes(book, "SPY", 0, "BBBBBBBBBB")  # Mon..Fri, Mon..Fri: weekends are not sessions
        assert primary(book).cell.episode_count == 1

    def test_a_known_missed_session_splits_an_episode(self):
        book = Book()
        episodes(book, "SPY", 0, "BBMBB")
        assert primary(book).cell.episode_count == 2
        book = Book()
        episodes(book, "SPY", 0, "BBBBB")
        assert primary(book).cell.episode_count == 1

    def test_a_session_with_only_another_producers_claim_splits(self):
        book = Book()
        episodes(book, "SPY", 0, "BBABB")
        assert primary(book).cell.episode_count == 2

    def test_degraded_claims_split_and_never_contribute(self):
        book = Book()
        episodes(book, "SPY", 0, "BBXBB")
        result = primary(book)
        assert result.cell.episode_count == 2
        assert result.cell.stats.sample_count == 4
        assert result.cell.matched.sample_count == 4
        assert LEAK not in (result.cell.stats.max_forward_return,
                            result.cell.matched.max_forward_return)

    def test_an_unmatured_claim_splits(self):
        book = Book()
        episodes(book, "SPY", 0, "BBUBBB")
        assert primary(book).cell.episode_count == 2

    def test_reserved_interval_claims_are_never_eligible(self):
        book = Book()
        # bars before activation (2025-03-03 and the activation day's previous Friday)
        book.trend("SPY", 0, value=LEAK, timestamp=datetime(2025, 3, 3, 5, tzinfo=UTC))
        book.trend("SPY", 0, value=LEAK, timestamp=session(0) - timedelta(days=3))
        episodes(book, "SPY", 0, "BNBNBNBNBNBNBNBN")
        result = primary(book)
        assert result.cell.stats.sample_count == 8
        assert LEAK not in (result.cell.stats.max_forward_return,
                            result.cell.matched.max_forward_return)
        assert matured_claim_counts(V1, book.level_one())["SPY"] == 16
        coverage = [r for r in secondary_results(V1, book.level_three(), cutoffs(
            V1, book.level_one()))["G_coverage"]["rows"] if r["symbol"] == "SPY"][0]
        assert coverage["claims_reserved_interval_excluded"] == 2

    def test_a_bar_settling_exactly_at_activation_is_reserved(self):
        book = Book(activated_at=session(1))  # the bar of session 0 settles exactly then
        book.trend("SPY", 0, value=LEAK)
        book.trend("SPY", 1, value=0.01)
        assert matured_claim_counts(V1, book.level_one())["SPY"] == 1


# -- categories ---------------------------------------------------------------------------------


def classified(mean, median, ref_mean=-0.003, ref_median=-0.0015, valid=True, adequate=True):
    return classify(valid=valid, adequate=adequate, mean_delta=mean, median_delta=median,
                    reference_mean_delta=ref_mean, reference_median_delta=ref_median)


class TestCategories:
    def test_both_same_sign_is_consistent(self):
        assert classified(-0.001, -0.002) == CATEGORY_CONSISTENT
        assert classified(0.001, 0.002, 0.003, 0.001) == CATEGORY_CONSISTENT

    def test_both_opposite_is_reversed(self):
        assert classified(0.001, 0.002) == CATEGORY_REVERSED

    def test_disagreement_is_mixed(self):
        assert classified(-0.001, 0.002) == CATEGORY_MIXED
        assert classified(0.001, -0.002) == CATEGORY_MIXED

    def test_either_zero_is_mixed(self):
        assert classified(0.0, -0.002) == CATEGORY_MIXED
        assert classified(-0.001, 0.0) == CATEGORY_MIXED
        assert classified(0.0, 0.0) == CATEGORY_MIXED
        assert classified(None, -0.002) == CATEGORY_MIXED

    def test_order_invalid_then_inconclusive(self):
        assert classified(-0.001, -0.002, valid=False, adequate=False) == CATEGORY_INVALID
        assert classified(-0.001, -0.002, valid=False) == CATEGORY_INVALID
        assert classified(-0.001, -0.002, adequate=False) == CATEGORY_INCONCLUSIVE

    def test_no_magnitude_cutoff(self):
        # a delta 1e-12 the size of the reference is still directionally consistent,
        # and one 1000x larger is still consistent
        assert classified(-0.003e-12, -0.0015e-12) == CATEGORY_CONSISTENT
        assert classified(-3.0, -1.5) == CATEGORY_CONSISTENT
        assert classified(-0.0015, -0.00075) == CATEGORY_CONSISTENT  # exactly half

    def test_classify_has_exactly_six_inputs(self):
        assert list(inspect.signature(classify).parameters) == [
            "valid", "adequate", "mean_delta", "median_delta", "reference_mean_delta",
            "reference_median_delta"]

    def test_categories_through_the_primary_cell(self):
        # matched mean/median are lowered by bearish values below the bullish ones:
        book = Book()
        for k in range(8):
            book.trend("SPY", 3 * k, "bullish", 0.01)
            book.trend("SPY", 3 * k + 1, "bearish", 0.03)
            book.trend("SPY", 3 * k + 2, "neutral", 0.02)
        result = primary(book)
        assert result.cell.mean_delta < 0 and result.cell.median_delta < 0
        assert result.category == CATEGORY_CONSISTENT  # all references are negative
        reversed_book = Book()
        for k in range(8):
            reversed_book.trend("SPY", 3 * k, "bullish", 0.03)
            reversed_book.trend("SPY", 3 * k + 1, "bearish", 0.01)
            reversed_book.trend("SPY", 3 * k + 2, "neutral", 0.02)
        assert primary(reversed_book).category == CATEGORY_REVERSED

    def test_all_bullish_gives_zero_deltas_and_mixed(self):
        book = Book()
        episodes(book, "SPY", 0, "BN" * 8, bull=0.01, other=0.01)
        assert primary(book).category == CATEGORY_MIXED

    def test_measurement_defect_makes_the_symbol_invalid(self):
        book = Book()
        episodes(book, "SPY", 0, "BN" * 8)
        book.trend("SPY", 16, "bullish", 0.01, reference_offset=timedelta(0))  # lookahead
        result = primary(book)
        assert result.category == CATEGORY_INVALID and result.integrity_findings


class TestMagnitudeRatios:
    def test_positive_negative_zero_and_near_zero(self):
        assert magnitude_ratio(-0.0015, -0.003) == 0.5
        assert magnitude_ratio(0.006, -0.003) == 2.0
        assert magnitude_ratio(0.0, -0.003) == 0.0
        assert magnitude_ratio(-1e-300, -0.003) == pytest.approx(1e-300 / 0.003)
        assert magnitude_ratio(None, -0.003) is None

    def test_a_zero_reference_fails_loudly(self):
        with pytest.raises(FutureValidationError):
            magnitude_ratio(0.1, 0.0)
        reference = V1.references[0]
        with pytest.raises(FutureValidationDefinitionError):
            replace(reference, mean_delta=0.0, bullish_mean=reference.matched_mean)
        with pytest.raises(FutureValidationDefinitionError):
            replace(reference, median_delta=0.0, bullish_median=reference.matched_median)

    def test_ratios_cannot_affect_the_category(self):
        # identical signs, wildly different magnitudes: one category
        categories = set()
        for scale in (1e-9, 0.5, 1.0, 2.0, 1e6):
            categories.add(classified(-0.003 * scale, -0.0015 * scale))
        assert categories == {CATEGORY_CONSISTENT}


# -- isolation ----------------------------------------------------------------------------------


def full_book(*, perturb_secondary: bool) -> Book:
    book = Book()
    for symbol in ("SPY", "QQQ", "IWM", "TLT", "GLD"):
        for k in range(9):
            book.trend(symbol, 3 * k, "bullish", 0.01, returns={
                20: 0.01, 5: LEAK if perturb_secondary else 0.002})
            book.trend(symbol, 3 * k + 1, "bearish", 0.03, returns={
                20: 0.03, 5: -LEAK if perturb_secondary else 0.001})
            book.trend(symbol, 3 * k + 2, "neutral", 0.02)
            value = LEAK if perturb_secondary else 0.004
            book.add(symbol, 3 * k, "bearish" if perturb_secondary else "bullish",
                     identity=MOMENTUM, returns={20: value, 5: value})
    if perturb_secondary:  # TLT/GLD primary-cell evidence flips completely
        for symbol in ("TLT", "GLD"):
            for claim in [c for c in book.observations if c.symbol == symbol]:
                book.observations.remove(claim)
                book.observations.append(replace(claim, state="bearish"))
    return book


class TestSecondaryIsolation:
    def test_changing_every_secondary_input_leaves_every_primary_row_unchanged(self):
        base, perturbed = full_book(perturb_secondary=False), full_book(perturb_secondary=True)
        before = build_result(V1, base.level_three(), unlock=unlock_for(base),
                              unlock_sha256="0" * 64)
        after = build_result(V1, perturbed.level_three(), unlock=unlock_for(perturbed),
                             unlock_sha256="0" * 64)
        assert before["primary"] == after["primary"]
        assert before["categories"] == after["categories"]
        assert before["secondary"] != after["secondary"]

    def test_primary_code_never_calls_secondary_code(self):
        source = inspect.getsource(primary_result) + inspect.getsource(classify)
        for name in ("secondary", "episode_start_values", "momentum", "TLT", "GLD", "h5"):
            assert name not in source

    def test_there_is_no_overall_result(self):
        book = full_book(perturb_secondary=False)
        result = build_result(V1, book.level_three(), unlock=unlock_for(book),
                              unlock_sha256="0" * 64)
        text = json.dumps(result).lower()
        for forbidden in ("overall", "k_of_3", "majority", "\"validated\"", "pooled_",
                          "combined_score", "vote"):
            assert forbidden not in text
        assert [s for s, _ in result["categories"]] == ["SPY", "QQQ", "IWM"]
        assert set(result) >= {"categories", "primary", "secondary"}


# -- degraded evidence never leaks ----------------------------------------------------------------


class TestDegradedExclusion:
    def test_excluded_keys_reach_no_statistic_anywhere(self):
        book = Book()
        for symbol in ("SPY", "QQQ", "IWM", "TLT", "GLD"):
            for k in range(10):
                book.trend(symbol, 4 * k, "bullish", 0.01)
                book.trend(symbol, 4 * k + 1, "bullish", LEAK, excluded=True,
                           returns={20: LEAK, 5: LEAK})
                book.trend(symbol, 4 * k + 2, "bearish", 0.02)
                book.add(symbol, 4 * k + 3, "bullish", identity=MOMENTUM,
                         returns={20: LEAK, 5: LEAK}, excluded=True)
        result = build_result(V1, book.level_three(), unlock=unlock_for(book),
                              unlock_sha256="0" * 64)
        text = canonical_bytes(result).decode()
        assert str(LEAK) not in text and "1234.5" not in text
        for row in result["primary"]:
            assert row["bullish_observation_count"] == 10
            assert row["matched_unconditional_count"] == 20
            assert row["bullish_episode_count"] == 10  # each excluded claim splits

    def test_degraded_outcome_of_a_valid_claim_is_excluded(self):
        book = Book()
        book.trend("SPY", 0, "bullish", LEAK, excluded_outcomes=True)
        episodes(book, "SPY", 1, "BN" * 8)
        result = primary(book)
        assert result.cell.stats.sample_count == 8
        assert LEAK not in (result.cell.stats.max_forward_return,)


# -- Phase R equivalence -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def phase_r():
    definition = small_study(symbols=("AAA",))
    result = run_study(definition, {"AAA": synthetic_series(definition, "AAA")})
    return definition, result


class TestMatchedUnconditionalEquivalence:
    """The prospective benchmark is the Phase R matched_unconditional_v1, number for number."""

    @pytest.mark.parametrize("hypothesis", ["trend_alignment", "momentum_in_trend_context",
                                            "trend_crossover"])
    @pytest.mark.parametrize("horizon", [1, 5, 20])
    def test_every_state_group_and_matched_row_is_identical(self, phase_r, hypothesis, horizon):
        definition, result = phase_r
        rows = [r for r in result.observations if r.hypothesis_id == hypothesis]
        sequence = []
        for row in rows:
            outcome = next(o for o in row.outcomes if o.horizon_bars == horizon)
            sequence.append((row.state.value, outcome.outcome_value
                             if outcome.status is OutcomeStatus.EVALUATED else None))
        groups = [g for g in result.groups if g.hypothesis_id == hypothesis
                  and g.horizon_bars == horizon]
        matched = next(g for g in groups if g.row_type == "matched_unconditional")
        compared = 0
        for state in ("bullish", "bearish", "neutral"):
            group = next(g for g in groups if g.row_type == "state" and g.state == state)
            cell = describe_cell(sequence, state)
            assert cell.stats == group.stats
            assert cell.episode_count == group.episode_count
            assert cell.mean_delta == group.mean_delta_vs_matched_unconditional
            assert cell.median_delta == group.median_delta_vs_matched_unconditional
            assert cell.matched == matched.stats
            assert cell.matched_episode_count == matched.episode_count
            compared += group.stats.sample_count
        assert compared == matched.stats.sample_count

    def test_the_full_primary_pipeline_reproduces_phase_r_at_h20(self, phase_r):
        definition, result = phase_r
        rows = [r for r in result.observations if r.hypothesis_id == "trend_alignment"]
        first = rows[0].timestamp
        activated = first - timedelta(hours=12)
        observations, measurements, claims, outcomes = [], [], [], []
        spec = V1.spec_fingerprint(20)
        for row in rows:
            key = f"AAA|{row.timestamp.isoformat()}"
            observations.append(Observation(key, "AAA", row.timestamp, TREND.hypothesis_id,
                                            TREND.version, TREND.fingerprint, row.state.value))
            claims.append(ClaimStamp(key, "AAA", row.timestamp, TREND.hypothesis_id,
                                     TREND.version, TREND.fingerprint))
            outcome = next(o for o in row.outcomes if o.horizon_bars == 20)
            assert outcome.spec_fingerprint == spec
            if outcome.status is OutcomeStatus.EVALUATED:
                measurements.append(Measurement(
                    key + "|20", key, 20, spec, 1, outcome.outcome_value,
                    outcome.reference_timestamp, outcome.future_timestamp))
                outcomes.append(OutcomeStamp(key + "|20", key, "AAA", 20, spec, 1))
        reference = replace(V1.references[0], symbol="AAA")
        aaa = replace(V1, primary_symbols=("AAA",), secondary_symbols=(),
                      references=(reference,))
        level_one = LevelOneEvidence(activated_at=activated, claims=tuple(claims),
                                     outcomes=tuple(outcomes))
        evidence = LevelThreeEvidence(level_one, tuple(observations), tuple(measurements))
        cell = primary_result(aaa, evidence, "AAA", cutoffs(aaa, level_one)["AAA"]).cell
        group = next(g for g in result.groups if g.hypothesis_id == "trend_alignment"
                     and g.horizon_bars == 20 and g.row_type == "state" and g.state == "bullish")
        matched = next(g for g in result.groups if g.hypothesis_id == "trend_alignment"
                       and g.horizon_bars == 20 and g.row_type == "matched_unconditional")
        assert cell.stats == group.stats and cell.matched == matched.stats
        assert cell.episode_count == group.episode_count
        assert (cell.mean_delta, cell.median_delta) == (
            group.mean_delta_vs_matched_unconditional,
            group.median_delta_vs_matched_unconditional)

    def test_the_equivalence_study_uses_the_frozen_hypotheses_and_specs(self, phase_r):
        definition, _ = phase_r
        assert definition.hypotheses == (TrendAlignment, MomentumInTrendContext, TrendCrossover)
        assert TrendAlignment().spec.fingerprint == TREND.fingerprint
        assert MomentumInTrendContext().spec.fingerprint == MOMENTUM.fingerprint
        specs = {h: OutcomeSpec(horizon_bars=h).fingerprint for h in (5, 20)}
        assert specs == dict(V1.outcome_spec_fingerprints)


# -- result and report ---------------------------------------------------------------------------


class TestResultAndReport:
    def book(self):
        return full_book(perturb_secondary=False)

    def test_result_is_deterministic_and_canonical(self):
        book = self.book()
        one = canonical_bytes(build_result(V1, book.level_three(), unlock=unlock_for(book),
                                           unlock_sha256="0" * 64))
        two = canonical_bytes(build_result(V1, book.level_three(), unlock=unlock_for(book),
                                           unlock_sha256="0" * 64))
        assert one == two
        assert canonical_bytes(decode_canonical(one, "result")) == one

    def test_cutoffs_must_match_the_unlock(self):
        book = self.book()
        wrong = dict(cutoffs(V1, book.level_one()), SPY=session(0))
        with pytest.raises(FutureValidationError):
            build_result(V1, book.level_three(), unlock=unlock_for(book, valid_cutoffs=wrong),
                         unlock_sha256="0" * 64)

    def test_report_carries_every_disclosure_and_no_forbidden_language(self):
        import re

        book = self.book()
        result = build_result(V1, book.level_three(), unlock=unlock_for(book),
                              unlock_sha256="0" * 64)
        report = render_report(result)
        for disclosure in V1.disclosures:
            assert disclosure in report
        lowered = (report + canonical_bytes(result).decode()).lower()
        for word in ("validated", "proven", "profitable", "profit", "edge", "works",
                     "successful", "buy", "sell", "trade", "trading", "recommend"):
            assert not re.search(rf"\b{word}\b", lowered), word
        assert "overlap" in lowered and "correlated" in lowered
        assert "not three independent confirmations" in lowered
        assert "no inferential significance claim" in lowered
        assert "serially dependent" in lowered

    def test_report_is_a_pure_function_of_the_result(self):
        book = self.book()
        result = build_result(V1, book.level_three(), unlock=unlock_for(book),
                              unlock_sha256="0" * 64)
        assert render_report(result) == render_report(json.loads(canonical_bytes(result)))

    def test_episode_start_view(self):
        sequence = [("bullish", 1.0), ("bullish", 2.0), (None, None), ("bullish", 3.0),
                    ("bearish", 4.0), ("bullish", None), ("bullish", 5.0)]
        assert episode_start_values(sequence, "bullish") == [1.0, 3.0, 5.0]

    def test_calendar_year_breakdown_splits_by_bar_year(self):
        book = Book()
        index = 0
        while session(index).year < 2027:
            book.trend("SPY", index, "bullish" if index % 2 else "neutral", 0.01)
            index += 1
        for extra in range(index, index + 4):
            book.trend("SPY", extra, "bullish", 0.02)
        rows = secondary_results(V1, book.level_three(), cutoffs(V1, book.level_one()))
        years = [r["scope"] for r in rows["D_primary_by_calendar_year"]["rows"]
                 if r["symbol"] == "SPY"]
        assert years == ["2026", "2027"]
