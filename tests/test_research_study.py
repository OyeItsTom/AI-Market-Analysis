"""Phase R engine: windows, accounting, matched benchmark, groups, metrics."""

from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.evaluation import OutcomeStatus, StateMetrics, evaluate_observations, summarize
from src.research import (
    OVERLAP_CAVEAT,
    RETROSPECTIVE_CAVEAT,
    ROW_MATCHED_UNCONDITIONAL,
    ROW_NEUTRAL_REASON,
    ROW_STATE,
    STATE_ALL,
    DescriptiveStats,
    StudyError,
    count_episodes,
    max_abs_single_bar_close_return,
    partition_series,
    run_study,
)
from src.strategies import ResearchState, build_evidence
from tests.conftest import make_series
from tests.research_fixtures import UTC, series_for, synthetic_bars, synthetic_series
from tests.test_research_definition import small_definition


@pytest.fixture(scope="module")
def definition():
    return small_definition()


@pytest.fixture(scope="module")
def result(definition):
    return run_study(definition, series_for(definition))


def groups_for(result, *, hypothesis_id, symbol, horizon, row_type=None):
    return [
        g for g in result.groups
        if g.hypothesis_id == hypothesis_id and g.symbol == symbol and g.horizon_bars == horizon
        and (row_type is None or g.row_type == row_type)
    ]


# -- descriptive helpers ---------------------------------------------------------------------


class TestDescriptiveStats:
    def test_empty_is_none_not_zero(self):
        stats = DescriptiveStats.over([])
        assert stats.sample_count == 0
        assert stats.mean_forward_return is None
        assert stats.median_forward_return is None
        assert stats.min_forward_return is None
        assert stats.max_forward_return is None
        assert (stats.positive_count, stats.negative_count, stats.zero_count) == (0, 0, 0)

    def test_hand_computed_values(self):
        stats = DescriptiveStats.over([0.02, -0.01, 0.0, 0.03, -0.04])
        assert stats.sample_count == 5
        assert stats.mean_forward_return == pytest.approx(0.0)
        assert stats.median_forward_return == 0.0
        assert stats.min_forward_return == -0.04
        assert stats.max_forward_return == 0.03
        assert (stats.positive_count, stats.negative_count, stats.zero_count) == (2, 2, 1)

    def test_mean_and_median_agree_with_phase_four(self):
        values = [0.011, -0.002, 0.0, 0.0045, -0.03, 0.02, 0.0007]
        ours = DescriptiveStats.over(values)
        theirs = StateMetrics.over(values)
        assert ours.mean_forward_return == theirs.mean_forward_return
        assert ours.median_forward_return == theirs.median_forward_return
        assert ours.sample_count == theirs.count
        assert ours.mean_forward_return == statistics.fmean(values)

    def test_sign_counts_must_partition_the_sample(self):
        with pytest.raises(StudyError):
            DescriptiveStats(3, 0.0, 0.0, 0.0, 0.0, 1, 1, 0)


class TestEpisodes:
    @pytest.mark.parametrize(
        "membership, expected",
        [
            ([], 0),
            ([False, False], 0),
            ([True], 1),
            ([True, True, True], 1),
            ([True, False, True], 2),
            ([False, True, True, False, True, False, False, True, True, True], 3),
            ([True, False, False, True], 2),
        ],
    )
    def test_hand_built_sequences(self, membership, expected):
        assert count_episodes(membership) == expected

    def test_adjacency_is_by_observation_position_not_calendar(self):
        """A weekend gap between successive bars does not split an episode."""
        # Observation positions 0..3 whatever their calendar dates: one run.
        assert count_episodes([True, True, True, True]) == 1
        # And a missing position (a False) splits it regardless of dates.
        assert count_episodes([True, True, False, True]) == 2

    def test_bullish_episodes_in_a_real_run(self, result, definition):
        """Recount from the observation rows: consecutive same-state rows form one run."""
        for coverage in result.coverage:
            rows = [
                o for o in result.observations
                if o.symbol == coverage.symbol and o.hypothesis_id == coverage.hypothesis_id
            ]
            for horizon in definition.horizons:
                for state in ("bullish", "bearish", "neutral"):
                    membership = [
                        o.state.value == state
                        and next(h for h in o.outcomes if h.horizon_bars == horizon).status
                        is OutcomeStatus.EVALUATED
                        for o in rows
                    ]
                    expected = count_episodes(membership)
                    group = next(
                        g for g in groups_for(result, hypothesis_id=coverage.hypothesis_id,
                                              symbol=coverage.symbol, horizon=horizon,
                                              row_type=ROW_STATE)
                        if g.state == state
                    )
                    assert group.episode_count == expected
                    assert group.episode_count <= group.stats.sample_count


class TestRawDiagnostic:
    def test_hand_computed(self):
        series = make_series([100.0, 110.0, 99.0, 99.0])
        # 110/100-1 = 0.10; 99/110-1 = -0.1; 99/99-1 = 0
        assert max_abs_single_bar_close_return(series) == pytest.approx(0.1)

    def test_a_split_like_jump_is_visible_not_removed(self, definition):
        bars = synthetic_bars("AAA", definition.fetch_start, definition.outcome_data_end)
        index = 100
        halved = [
            b if i < index else replace(b, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2)
            for i, b in enumerate(bars)
        ]
        series = BarSeries.from_bars(halved, basis=PriceBasis.RAW)
        assert max_abs_single_bar_close_return(series) > 0.45
        # The run still counts every bar and every observation; nothing was
        # excluded, re-weighted or trimmed because of the jump.
        clean = run_study(definition, {"AAA": synthetic_series(definition, "AAA"),
                                       "BBB": synthetic_series(definition, "BBB")})
        result = run_study(definition, {"AAA": series, "BBB": synthetic_series(definition, "BBB")})
        assert result.symbols[0].max_abs_single_bar_close_return > 0.45
        assert result.symbols[0].bars_fetched == len(bars)
        assert result.symbols[0].observation_bars == clean.symbols[0].observation_bars
        for jumped, reference in zip(result.coverage, clean.coverage):
            assert jumped.total_observations == reference.total_observations
            assert [h.total for h in jumped.horizons] == [h.total for h in reference.horizons]
        assert len(result.observations) == len(clean.observations)

    def test_single_bar_is_none(self):
        assert max_abs_single_bar_close_return(make_series([100.0])) is None


# -- windows ------------------------------------------------------------------------------------


class TestWindows:
    def test_partition_is_exact_and_half_open(self, definition):
        series = synthetic_series(definition, "AAA")
        partition = partition_series(definition, series)
        stamps = series.timestamps
        assert partition.warmup_bars == sum(1 for t in stamps if t < definition.observation_start)
        assert partition.observation_bars == sum(
            1 for t in stamps if definition.observation_start <= t < definition.observation_end
        )
        assert partition.outcome_buffer_bars == sum(1 for t in stamps if t >= definition.observation_end)
        assert (partition.warmup_bars + partition.observation_bars + partition.outcome_buffer_bars
                == partition.bars_fetched == len(series))
        # The boundary bars themselves.
        assert stamps[partition.observation_start_index] == definition.observation_start
        assert stamps[partition.observation_stop_index - 1] == definition.observation_end - timedelta(days=1)
        assert stamps[partition.observation_stop_index] == definition.observation_end

    def test_too_little_warmup_fails_loudly(self, definition):
        late = synthetic_bars("AAA", definition.observation_start - timedelta(days=50),
                              definition.outcome_data_end)
        with pytest.raises(StudyError, match="only 50 bars precede"):
            partition_series(definition, BarSeries.from_bars(late, basis=PriceBasis.RAW))
        # Exactly the floor is accepted.
        enough = synthetic_bars("AAA", definition.observation_start - timedelta(days=51),
                                definition.outcome_data_end)
        assert partition_series(definition, BarSeries.from_bars(enough, basis=PriceBasis.RAW)).warmup_bars == 51

    def test_bars_outside_the_fetch_window_are_refused_not_trimmed(self, definition):
        early = synthetic_bars("AAA", definition.fetch_start - timedelta(days=1), definition.outcome_data_end)
        with pytest.raises(StudyError, match="outside the requested window"):
            partition_series(definition, BarSeries.from_bars(early, basis=PriceBasis.RAW))
        late = synthetic_bars("AAA", definition.fetch_start, definition.outcome_data_end + timedelta(days=1))
        with pytest.raises(StudyError, match="outside the requested window"):
            partition_series(definition, BarSeries.from_bars(late, basis=PriceBasis.RAW))

    def test_no_observation_bar_is_refused(self, definition):
        only_warmup = synthetic_bars("AAA", definition.fetch_start, definition.observation_start)
        with pytest.raises(StudyError, match="no bar falls in the observation window"):
            partition_series(definition, BarSeries.from_bars(only_warmup, basis=PriceBasis.RAW))

    def test_wrong_symbol_interval_or_basis_is_refused(self, definition):
        with pytest.raises(StudyError, match="not in the study universe"):
            partition_series(definition, synthetic_series(replace(definition, symbols=("ZZZ",)), "ZZZ"))
        weekly = BarSeries.from_bars(
            synthetic_bars("AAA", definition.fetch_start, definition.outcome_data_end,
                           interval=Interval.WEEK_1),
            basis=PriceBasis.RAW,
        )
        with pytest.raises(StudyError, match="interval"):
            partition_series(definition, weekly)
        adjusted = synthetic_series(definition, "AAA").with_bars(
            synthetic_series(definition, "AAA").bars, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
        )
        with pytest.raises(StudyError, match="basis"):
            partition_series(definition, adjusted)

    def test_an_empty_series_is_refused(self, definition):
        empty = BarSeries.from_bars((), basis=PriceBasis.RAW, symbol="AAA", interval="1d", source="synthetic")
        with pytest.raises(StudyError, match="no bars"):
            partition_series(definition, empty)


# -- the run ------------------------------------------------------------------------------------


class TestRunStudy:
    def test_the_universe_must_be_supplied_exactly(self, definition):
        series = series_for(definition)
        with pytest.raises(StudyError, match="every symbol, and only those"):
            run_study(definition, {"AAA": series["AAA"]})
        extra = dict(series)
        extra["CCC"] = synthetic_series(replace(definition, symbols=("CCC",)), "CCC")
        with pytest.raises(StudyError, match="every symbol, and only those"):
            run_study(definition, extra)

    def test_every_hypothesis_symbol_pair_is_covered_once(self, result, definition):
        keys = [(c.hypothesis_id, c.symbol) for c in result.coverage]
        assert keys == [
            (spec.hypothesis_id, symbol)
            for symbol in definition.symbols
            for spec in definition.hypothesis_specs
        ]

    def test_total_observations_equal_the_observation_window(self, result):
        symbols = {s.symbol: s for s in result.symbols}
        for coverage in result.coverage:
            assert coverage.total_observations == symbols[coverage.symbol].observation_bars
            rows = [o for o in result.observations
                    if o.symbol == coverage.symbol and o.hypothesis_id == coverage.hypothesis_id]
            assert len(rows) == coverage.total_observations

    def test_no_observation_from_warmup_or_buffer(self, result, definition):
        for row in result.observations:
            assert definition.observation_start <= row.timestamp < definition.observation_end
        for coverage in result.coverage:
            assert coverage.first_observation_timestamp == definition.observation_start
            assert coverage.last_observation_timestamp == definition.observation_end - timedelta(days=1)

    def test_coverage_accounting_balances_for_every_horizon(self, result):
        for coverage in result.coverage:
            assert (coverage.bullish_count + coverage.bearish_count + coverage.neutral_count
                    + coverage.insufficient_data_count == coverage.total_observations)
            for horizon in coverage.horizons:
                assert (horizon.evaluated + horizon.insufficient_future_data
                        + horizon.no_reference_bar + horizon.ineligible
                        == coverage.total_observations)

    def test_with_enough_warmup_nothing_is_insufficient(self, result):
        for coverage in result.coverage:
            assert coverage.insufficient_data_count == 0
            for horizon in coverage.horizons:
                assert horizon.ineligible == 0

    def test_every_state_is_exercised_by_the_fixture(self, result):
        """The synthetic data must make every hypothesis emit every state, or
        the tests below would pass vacuously."""
        for hypothesis_id in {c.hypothesis_id for c in result.coverage}:
            rows = [c for c in result.coverage if c.hypothesis_id == hypothesis_id]
            assert sum(c.bullish_count for c in rows) > 0
            assert sum(c.bearish_count for c in rows) > 0
            assert sum(c.neutral_count for c in rows) > 0

    def test_group_order_and_row_types(self, result, definition):
        for coverage in result.coverage:
            for horizon in definition.horizons:
                groups = groups_for(result, hypothesis_id=coverage.hypothesis_id,
                                    symbol=coverage.symbol, horizon=horizon)
                assert [g.row_type for g in groups[:4]] == [
                    ROW_MATCHED_UNCONDITIONAL, ROW_STATE, ROW_STATE, ROW_STATE,
                ]
                assert [g.state for g in groups[:4]] == [STATE_ALL, "bullish", "bearish", "neutral"]
                assert all(g.row_type == ROW_NEUTRAL_REASON for g in groups[4:])
                assert [g.reason_signature for g in groups[4:]] == sorted(
                    g.reason_signature for g in groups[4:]
                )
                assert groups[0].mean_delta_vs_matched_unconditional is None
                assert groups[0].median_delta_vs_matched_unconditional is None

    def test_the_matched_row_is_phase_four_all_evaluated(self, result, definition):
        """Recompute Phase 4's summary independently and compare."""
        series = series_for(definition)
        for coverage in result.coverage:
            hypothesis = next(h for h in definition.hypotheses
                              if h.hypothesis_id == coverage.hypothesis_id)()
            evidence = build_evidence(series[coverage.symbol], hypothesis.spec.required_features)
            observations = [
                o for o in hypothesis.evaluate(evidence)
                if definition.observation_start <= o.timestamp < definition.observation_end
            ]
            for spec in definition.outcome_specs:
                summary = summarize(evaluate_observations(observations, series[coverage.symbol], spec))
                matched = groups_for(result, hypothesis_id=coverage.hypothesis_id,
                                     symbol=coverage.symbol, horizon=spec.horizon_bars,
                                     row_type=ROW_MATCHED_UNCONDITIONAL)[0]
                assert matched.stats.sample_count == summary.all_evaluated.count == summary.evaluated_observations
                assert matched.stats.mean_forward_return == summary.unconditional_mean_forward_return
                assert matched.stats.median_forward_return == summary.all_evaluated.median_forward_return
                for state in ResearchState.BULLISH, ResearchState.BEARISH, ResearchState.NEUTRAL:
                    group = next(g for g in groups_for(result, hypothesis_id=coverage.hypothesis_id,
                                                       symbol=coverage.symbol, horizon=spec.horizon_bars,
                                                       row_type=ROW_STATE) if g.state == state.value)
                    theirs = getattr(summary, state.value)
                    assert group.stats.sample_count == theirs.count
                    assert group.stats.mean_forward_return == theirs.mean_forward_return
                    assert group.stats.median_forward_return == theirs.median_forward_return

    def test_state_groups_partition_the_matched_sample_by_timestamp(self, result, definition):
        for coverage in result.coverage:
            rows = [o for o in result.observations
                    if o.symbol == coverage.symbol and o.hypothesis_id == coverage.hypothesis_id]
            for horizon in definition.horizons:
                evaluated = {
                    o.timestamp: o.state.value for o in rows
                    if next(h for h in o.outcomes if h.horizon_bars == horizon).status
                    is OutcomeStatus.EVALUATED
                }
                groups = groups_for(result, hypothesis_id=coverage.hypothesis_id,
                                    symbol=coverage.symbol, horizon=horizon)
                matched, states = groups[0], groups[1:4]
                assert matched.stats.sample_count == len(evaluated)
                assert sum(g.stats.sample_count for g in states) == len(evaluated)
                for group in states:
                    assert group.stats.sample_count == sum(
                        1 for state in evaluated.values() if state == group.state
                    )
                    members = [t for t, state in evaluated.items() if state == group.state]
                    assert group.first_evaluated_timestamp == (min(members) if members else None)
                    assert group.last_evaluated_timestamp == (max(members) if members else None)
                assert matched.first_evaluated_timestamp == min(evaluated)
                assert matched.last_evaluated_timestamp == max(evaluated)

    def test_deltas_are_plain_subtraction(self, result):
        by_key = {}
        for g in result.groups:
            by_key.setdefault((g.hypothesis_id, g.symbol, g.horizon_bars), []).append(g)
        for groups in by_key.values():
            matched = groups[0]
            for group in groups[1:]:
                if group.stats.sample_count == 0:
                    assert group.mean_delta_vs_matched_unconditional is None
                    assert group.median_delta_vs_matched_unconditional is None
                    continue
                assert group.mean_delta_vs_matched_unconditional == (
                    group.stats.mean_forward_return - matched.stats.mean_forward_return
                )
                assert group.median_delta_vs_matched_unconditional == (
                    group.stats.median_forward_return - matched.stats.median_forward_return
                )

    def test_neutral_reason_rows_partition_the_neutral_group(self, result):
        by_key = {}
        for g in result.groups:
            by_key.setdefault((g.hypothesis_id, g.symbol, g.horizon_bars), []).append(g)
        for groups in by_key.values():
            neutral = groups[3]
            reasons = groups[4:]
            assert neutral.state == "neutral"
            assert sum(g.stats.sample_count for g in reasons) == neutral.stats.sample_count
            assert all(g.state == "neutral" and g.reason_signature for g in reasons)
            assert len({g.reason_signature for g in reasons}) == len(reasons)

    def test_momentum_neutral_is_split_by_contradiction(self, result):
        signatures = {
            g.reason_signature for g in result.groups
            if g.row_type == ROW_NEUTRAL_REASON and g.hypothesis_id == "momentum_in_trend_context"
        }
        assert "momentum_midrange" in signatures
        assert any("momentum_contradicts_trend" in s for s in signatures)

    def test_observation_rows_carry_phase_four_records_verbatim(self, result, definition):
        series = series_for(definition)
        for coverage in result.coverage:
            hypothesis = next(h for h in definition.hypotheses
                              if h.hypothesis_id == coverage.hypothesis_id)()
            evidence = build_evidence(series[coverage.symbol], hypothesis.spec.required_features)
            observations = [
                o for o in hypothesis.evaluate(evidence)
                if definition.observation_start <= o.timestamp < definition.observation_end
            ]
            rows = [o for o in result.observations
                    if o.symbol == coverage.symbol and o.hypothesis_id == coverage.hypothesis_id]
            assert [r.timestamp for r in rows] == [o.timestamp for o in observations]
            assert [r.state for r in rows] == [o.state for o in observations]
            assert [r.reason_codes for r in rows] == [
                tuple(c.value for c in o.reason_codes) for o in observations
            ]
            for spec in definition.outcome_specs:
                outcomes = evaluate_observations(observations, series[coverage.symbol], spec)
                for row, outcome in zip(rows, outcomes):
                    ours = next(h for h in row.outcomes if h.horizon_bars == spec.horizon_bars)
                    assert ours.status is outcome.status
                    assert ours.outcome_value == outcome.outcome_value
                    assert ours.reference_timestamp == outcome.reference_timestamp
                    assert ours.future_timestamp == outcome.future_timestamp
                    assert ours.spec_fingerprint == spec.fingerprint

    def test_ineligible_observations_inside_the_window_are_accounted_for(self, definition):
        """A definition that permits a short warm-up puts INSUFFICIENT_DATA
        observations inside the window; they are counted as ineligible for
        every horizon, never dropped."""
        thin = replace(definition, minimum_warmup_bars=1,
                       fetch_start=definition.observation_start - timedelta(days=10))
        result = run_study(thin, series_for(thin))
        for coverage in result.coverage:
            assert coverage.insufficient_data_count > 0
            for horizon in coverage.horizons:
                assert horizon.ineligible == coverage.insufficient_data_count
                assert (horizon.evaluated + horizon.insufficient_future_data
                        + horizon.no_reference_bar + horizon.ineligible
                        == coverage.total_observations == result.symbols[0].observation_bars)
        rows = [o for o in result.observations if o.state is ResearchState.INSUFFICIENT_DATA]
        assert rows and all(
            h.status is OutcomeStatus.INELIGIBLE_OBSERVATION and h.outcome_value is None
            for o in rows for h in o.outcomes
        )

    def test_a_short_buffer_reports_statuses_rather_than_dropping(self, definition):
        """With no outcome buffer the last observations lack future bars."""
        cut = replace(definition, outcome_data_end=definition.observation_end)
        result = run_study(cut, series_for(cut))
        for coverage in result.coverage:
            assert coverage.total_observations == result.symbols[0].observation_bars
            for horizon in coverage.horizons:
                assert horizon.no_reference_bar == 1
                assert horizon.insufficient_future_data == horizon.horizon_bars - 1
                assert horizon.evaluated == coverage.total_observations - horizon.horizon_bars
        assert all(s.outcome_buffer_bars == 0 for s in result.symbols)

    def test_the_run_is_deterministic(self, definition, result):
        again = run_study(definition, series_for(definition))
        assert again == result

    def test_caveats_travel_with_the_result(self, result):
        assert result.overlap_caveat == OVERLAP_CAVEAT
        assert result.retrospective_caveat == RETROSPECTIVE_CAVEAT
        assert "not a number of independent statistical trials" in OVERLAP_CAVEAT
        assert "19 of 20" in OVERLAP_CAVEAT
        assert "retrieval time" in RETROSPECTIVE_CAVEAT

    def test_nothing_in_the_result_is_a_hit_rate(self, result):
        for group in result.groups:
            names = set(vars(group)) | set(vars(group.stats))
            assert not names & {"directional_hit_rate", "positive_return_rate", "hit_rate",
                                "accuracy", "win_rate", "sharpe", "alpha"}
