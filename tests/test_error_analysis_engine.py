"""Phase 13A engine: input contract, Phase R cross-check, episodes, gate, segments, classes,
crossover events, decision aids and determinism -- on the synthetic fixture only."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.research import ErrorAnalysisError, run_error_analysis
from src.research.error_analysis import (
    CROSSOVER_ID,
    MOMENTUM_ID,
    PARTITION_OPPOSITE,
    PARTITION_REMOVED,
    PARTITION_RETAINED,
    ROW_CLASS_SIGNS,
    ROW_CROSSOVER_EVENT,
    ROW_EPISODE_START,
    ROW_EPISODE_SUMMARY,
    ROW_GATE_CROSSTAB,
    ROW_GATE_PARTITION,
    ROW_SEGMENT_MATCHED,
    ROW_SEGMENT_STATE,
    ROW_TYPES,
    SOURCE_MANIFEST,
    SOURCE_OBSERVATIONS,
    SOURCE_SUMMARY,
    TREND_ID,
    parse_observations,
    reconstruct_episodes,
    verify_source_bytes,
)
from tests.error_analysis_fixtures import (
    CONTRA_DOWN,
    CONTRA_UP,
    MID,
    OBS_COLUMNS,
    SYMBOLS,
    build_manifest,
    build_rows,
    build_summary_rows,
    build_texts,
    definition_for,
    fixture_dates,
    parse_csv,
)
from src.research.render import SUMMARY_COLUMNS, render_csv

UTC = timezone.utc


@pytest.fixture(scope="module")
def texts():
    return build_texts()


@pytest.fixture(scope="module")
def definition(texts):
    return definition_for(texts)


@pytest.fixture(scope="module")
def result(definition, texts):
    return run_error_analysis(definition, texts)


def rows_of(result, row_type, **match):
    return [d for d in result.diagnostics if d.row_type == row_type
            and all(getattr(d, k) == v for k, v in match.items())]


def mutate(texts, name, old, new):
    assert old in texts[name]
    out = dict(texts)
    out[name] = texts[name].replace(old, new, 1)
    return out


# -- input integrity ------------------------------------------------------------------------


class TestInputIntegrity:
    def test_accepts_the_exact_fixture(self, result, texts):
        assert result.observation_rows == len(parse_csv(texts[SOURCE_OBSERVATIONS]))
        assert result.source_rows_checked > 0

    @pytest.mark.parametrize("name", [SOURCE_MANIFEST, SOURCE_SUMMARY, SOURCE_OBSERVATIONS])
    def test_one_byte_change_is_refused(self, texts, definition, name):
        altered = dict(texts)
        altered[name] = texts[name][:-1] + ("X" if texts[name][-1] != "X" else "Y")
        with pytest.raises(ErrorAnalysisError, match="does not match the pinned source hash"):
            run_error_analysis(definition, altered)

    def test_missing_or_extra_artifact_is_refused(self, texts, definition):
        with pytest.raises(ErrorAnalysisError, match="exactly"):
            verify_source_bytes(definition, {k: v for k, v in texts.items() if k != SOURCE_SUMMARY})
        with pytest.raises(ErrorAnalysisError, match="exactly"):
            verify_source_bytes(definition, {**texts, "extra.txt": ""})

    def test_wrong_source_fingerprint_is_refused(self, texts, definition):
        wrong = replace(definition, source_study_fingerprint="0" * 64)
        with pytest.raises(ErrorAnalysisError, match="study_fingerprint"):
            run_error_analysis(wrong, texts)

    def test_wrong_methodology_sha_is_refused(self, texts, definition):
        wrong = replace(definition, source_methodology_sha="0" * 40)
        with pytest.raises(ErrorAnalysisError, match="git_commit"):
            run_error_analysis(wrong, texts)

    def test_wrong_universe_or_hypothesis_identity_is_refused(self, texts):
        manifest = build_manifest(universe=["SPY", "GLD"])
        altered = build_texts(manifest=manifest)
        with pytest.raises(ErrorAnalysisError, match="universe"):
            run_error_analysis(definition_for(altered), altered)
        manifest = build_manifest()
        manifest["hypotheses"][0]["fingerprint"] = "0" * 16
        altered = build_texts(manifest=manifest)
        with pytest.raises(ErrorAnalysisError, match="hypotheses"):
            run_error_analysis(definition_for(altered), altered)

    def test_future_timestamp_is_refused_not_filtered(self):
        rows = build_rows()
        future = dict(rows[0])
        future["timestamp"] = "2025-01-01T00:00:00+00:00"
        altered = build_texts(rows=rows + [future], summary_rows=build_summary_rows(rows))
        with pytest.raises(ErrorAnalysisError, match="on or after the frozen observation end"):
            run_error_analysis(definition_for(altered), altered)

    def test_pre_window_timestamp_is_refused(self):
        rows = build_rows()
        early = dict(rows[0])
        early["timestamp"] = "2014-12-31T00:00:00+00:00"
        altered = build_texts(rows=rows + [early], summary_rows=build_summary_rows(rows))
        with pytest.raises(ErrorAnalysisError, match="precedes"):
            run_error_analysis(definition_for(altered), altered)

    def test_altered_summary_statistic_is_refused(self, texts):
        summary = parse_csv(texts[SOURCE_SUMMARY])
        target = next(r for r in summary if r["row_type"] == "state" and r["sample_count"] != "0")
        target["mean_forward_return"] = repr(float(target["mean_forward_return"]) + 0.001)
        altered = dict(texts, **{SOURCE_SUMMARY: render_csv(SUMMARY_COLUMNS, summary)})
        with pytest.raises(ErrorAnalysisError, match="recomputes to"):
            run_error_analysis(definition_for(altered), altered)

    def test_corrupted_reason_signature_is_refused_by_the_cross_check(self, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        victim = next(r for r in rows if r["hypothesis_id"] == MOMENTUM_ID and r["reason_codes"] == MID)
        victim["reason_codes"] = "made_up_reason"
        altered = build_texts(rows=rows, summary_rows=parse_csv(texts[SOURCE_SUMMARY]))
        with pytest.raises(ErrorAnalysisError):
            run_error_analysis(definition_for(altered), altered)

    def test_omitted_common_timestamp_is_refused(self, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        rows = [r for r in rows if not (r["hypothesis_id"] == MOMENTUM_ID and r["symbol"] == "SPY"
                                        and r["timestamp"].startswith("2019-01-02"))]
        altered = build_texts(rows=rows, summary_rows=build_summary_rows(rows))
        with pytest.raises(ErrorAnalysisError, match="do not share the same timestamps"):
            run_error_analysis(definition_for(altered), altered)

    def test_unknown_column_layout_is_refused(self, texts, definition):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        for r in rows:
            r["hit_rate"] = "0.5"
        altered = dict(texts, **{SOURCE_OBSERVATIONS: render_csv(OBS_COLUMNS + ("hit_rate",), rows)})
        with pytest.raises(ErrorAnalysisError):
            run_error_analysis(definition_for(altered), altered)


# -- Phase R cross-check ----------------------------------------------------------------------


class TestPhaseRCrossCheck:
    def test_every_non_coverage_summary_row_is_checked(self, result, texts):
        summary = parse_csv(texts[SOURCE_SUMMARY])
        assert result.source_rows_checked == sum(1 for r in summary if r["row_type"] != "coverage")

    def test_a_fixture_with_ineligible_and_insufficient_rows_still_cross_checks(self):
        rows = build_rows(insufficient_first=2, short_tail=3)
        texts = build_texts(rows=rows, summary_rows=build_summary_rows(rows))
        result = run_error_analysis(definition_for(texts), texts)
        assert any(d.state == "insufficient_data" for d in result.diagnostics if d.row_type == ROW_EPISODE_SUMMARY)
        starts = [d for d in result.diagnostics if d.row_type == ROW_EPISODE_START and d.horizon_bars == 20]
        assert all(d.count <= d.episode_count for d in starts)


# -- episodes ---------------------------------------------------------------------------------


class TestEpisodes:
    def test_hand_built_sequence(self):
        rows = build_rows(symbols=("SPY",))
        dates = fixture_dates()
        texts = build_texts(rows=rows, symbols=("SPY",))
        d = definition_for(texts, symbols=("SPY",))
        episodes = [e for e in reconstruct_episodes(d, parse_observations(d, texts["observations.csv"]))
                    if e.hypothesis_id == TREND_ID]
        # Trend pattern for SPY: cycle 0-4 bullish, 5-8 bearish, 9-11 neutral, in position order.
        assert [e.state for e in episodes[:3]] == ["bullish", "bearish", "neutral"]
        assert [e.length for e in episodes[:3]] == [5, 4, 3]
        assert episodes[0].start_timestamp == dates[0] and episodes[0].end_timestamp == dates[4]
        # The first episode spans a weekend (a gap of more than one calendar day)
        # and is still one episode: adjacency is by position, not by date.
        gaps = [(b - a).days for a, b in zip(dates[:5], dates[1:5])]
        assert max(gaps) >= 3 and min(gaps) == 1
        assert sum(e.length for e in episodes) == len(dates)
        assert [e.episode_index for e in episodes] == list(range(len(episodes)))

    def test_reason_change_inside_neutral_does_not_split(self):
        rows = build_rows(symbols=("SPY",))
        texts = build_texts(rows=rows, symbols=("SPY",))
        d = definition_for(texts, symbols=("SPY",))
        episodes = [e for e in reconstruct_episodes(d, parse_observations(d, texts["observations.csv"]))
                    if e.hypothesis_id == MOMENTUM_ID]
        # Momentum cycle 3 (CONTRA_UP) and 4 (MID) are consecutive NEUTRAL bars -> one episode.
        neutral = [e for e in episodes if e.state == "neutral"]
        assert any(e.length >= 2 and e.reason_signature == CONTRA_UP for e in neutral)

    def test_single_bar_episodes_and_summary_shares(self, result):
        cross = rows_of(result, ROW_EPISODE_SUMMARY, hypothesis_id=CROSSOVER_ID, symbol="SPY", state="bullish")[0]
        assert cross.length_min == cross.length_max == 1 and cross.episode_count == cross.count
        for d in rows_of(result, ROW_EPISODE_SUMMARY):
            assert 0 < d.share_largest_episode <= d.share_three_largest <= 1.0
            assert d.length_min <= d.length_median <= d.length_max

    def test_episode_start_view_uses_start_bar_returns_only(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        for d in rows_of(result, ROW_EPISODE_START, symbol="SPY", hypothesis_id=TREND_ID, state="bearish"):
            starts = [e for e in result.episodes if e.symbol == "SPY" and e.hypothesis_id == TREND_ID
                      and e.state == "bearish"]
            values = [next(r for r in rows if r["symbol"] == "SPY" and r["hypothesis_id"] == TREND_ID
                           and r["timestamp"] == e.start_timestamp.isoformat())[f"return_h{d.horizon_bars}"]
                      for e in starts]
            values = [float(v) for v in values if v != ""]
            assert d.count == len(values) and d.sampling_view == "episode_start"
            assert d.stats.mean_forward_return == statistics.fmean(values)


# -- gate decomposition --------------------------------------------------------------------------


class TestGate:
    def test_crosstab_is_complete_and_totals_match(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        for symbol in SYMBOLS:
            cells = rows_of(result, ROW_GATE_CROSSTAB, symbol=symbol)
            assert len(cells) == 16
            assert sum(c.count for c in cells) == sum(1 for r in rows if r["symbol"] == symbol
                                                      and r["hypothesis_id"] == TREND_ID)
            # The dead-band sliver (trend neutral, momentum bullish) is present and counted.
            assert next(c for c in cells if c.state == "neutral" and c.momentum_state == "bullish").count > 0

    def test_partitions_account_for_every_directional_bar(self, result):
        for symbol in SYMBOLS:
            for direction in ("bullish", "bearish"):
                for h in (1, 5, 20):
                    parts = {(d.partition, d.reason_signature): d for d in
                             rows_of(result, ROW_GATE_PARTITION, symbol=symbol, state=direction, horizon_bars=h)}
                    retained = parts[(PARTITION_RETAINED, "")]
                    removed = parts[(PARTITION_REMOVED, "")]
                    opposite = parts[(PARTITION_OPPOSITE, "")]
                    parent = rows_of(result, ROW_GATE_CROSSTAB, symbol=symbol, state=direction)
                    assert retained.count + removed.count + opposite.count == sum(c.count for c in parent)
                    signatures = [d for (p, s), d in parts.items() if p == PARTITION_REMOVED and s]
                    assert sum(d.count for d in signatures) == removed.count
                    assert {d.reason_signature for d in signatures} <= {MID, CONTRA_UP, CONTRA_DOWN}
                    assert opposite.count == 0 and opposite.stats.mean_forward_return is None

    def test_partition_deltas_are_against_the_parent_trend_state(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        trend = [r for r in rows if r["symbol"] == "SPY" and r["hypothesis_id"] == TREND_ID and r["state"] == "bullish"]
        parent_mean = statistics.fmean(float(r["return_h5"]) for r in trend)
        parent_median = statistics.median(float(r["return_h5"]) for r in trend)
        retained = rows_of(result, ROW_GATE_PARTITION, symbol="SPY", state="bullish", horizon_bars=5,
                           partition=PARTITION_RETAINED)[0]
        assert retained.delta_reference == "parent_trend_state"
        assert retained.mean_delta == retained.stats.mean_forward_return - parent_mean
        assert retained.median_delta == retained.stats.median_forward_return - parent_median

    def test_opposite_momentum_is_reported_not_assumed_impossible(self, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        victim = next(r for r in rows if r["symbol"] == "SPY" and r["hypothesis_id"] == MOMENTUM_ID
                      and r["state"] == "bullish")
        victim["state"] = "bearish"
        victim["reason_codes"] = "fast_below_slow,momentum_depressed,momentum_confirms_trend"
        altered = build_texts(rows=rows, summary_rows=build_summary_rows(rows))
        result = run_error_analysis(definition_for(altered), altered)
        opposite = rows_of(result, ROW_GATE_PARTITION, symbol="SPY", state="bullish", horizon_bars=1,
                           partition=PARTITION_OPPOSITE)[0]
        assert opposite.count == 1


# -- segments -----------------------------------------------------------------------------------


class TestSegments:
    def test_boundaries_by_timestamp(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        stamps = sorted({r["timestamp"] for r in rows})
        assert "2016-12-30T00:00:00+00:00" in stamps and "2017-01-02T00:00:00+00:00" in stamps
        assert "2024-12-31T00:00:00+00:00" in stamps and not any(s >= "2025-01-01" for s in stamps)
        counts = Counter()
        for d in rows_of(result, ROW_SEGMENT_MATCHED, symbol="SPY", hypothesis_id=TREND_ID, horizon_bars=1):
            counts[d.segment] = d.count
        assert counts == {"2015-2016": 12, "2017-2018": 12, "2019-2020": 12, "2021-2022": 12, "2023-2024": 12}

    def test_segment_counts_recombine_and_medians_do_not_pretend_to(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        for symbol in SYMBOLS:
            for state in ("bullish", "bearish", "neutral"):
                cells = rows_of(result, ROW_SEGMENT_STATE, symbol=symbol, hypothesis_id=TREND_ID,
                                state=state, horizon_bars=5)
                full = [float(r["return_h5"]) for r in rows if r["symbol"] == symbol
                        and r["hypothesis_id"] == TREND_ID and r["state"] == state]
                assert sum(c.count for c in cells) == len(full)
                # Means recombine through the raw observations (weighted), never through medians.
                weighted = sum(c.stats.mean_forward_return * c.count for c in cells if c.count) / len(full)
                assert weighted == pytest.approx(statistics.fmean(full))
                assert sum(c.episode_count for c in cells) >= 1

    def test_segment_deltas_use_the_segment_matched_row(self, result):
        for cell in rows_of(result, ROW_SEGMENT_STATE, symbol="TLT", hypothesis_id=MOMENTUM_ID, horizon_bars=20):
            matched = rows_of(result, ROW_SEGMENT_MATCHED, symbol="TLT", hypothesis_id=MOMENTUM_ID,
                              horizon_bars=20, segment=cell.segment)[0]
            if cell.count:
                assert cell.mean_delta == cell.stats.mean_forward_return - matched.stats.mean_forward_return
                assert cell.delta_reference == "segment_matched_unconditional"
            else:
                assert cell.mean_delta is None


# -- classes, crossover, aids -------------------------------------------------------------------------


class TestClassesCrossoverAids:
    def test_class_rows_are_metadata_not_pooled(self, result):
        per_symbol = [d for d in rows_of(result, ROW_CLASS_SIGNS) if d.symbol]
        per_class = [d for d in rows_of(result, ROW_CLASS_SIGNS) if not d.symbol]
        assert {d.asset_class for d in per_symbol} == {"equity", "treasury"}
        assert all(d.stats is None for d in per_class)  # no pooled return statistics
        assert all(len(d.mean_delta_sign) == d.count for d in per_class)

    def test_class_signs_match_phase_r_deltas(self, result, texts):
        summary = parse_csv(texts[SOURCE_SUMMARY])
        for d in [d for d in rows_of(result, ROW_CLASS_SIGNS) if d.symbol]:
            row = next(r for r in summary if r["row_type"] == "state" and r["symbol"] == d.symbol
                       and r["hypothesis_id"] == d.hypothesis_id and r["state"] == d.state
                       and r["horizon_bars"] == str(d.horizon_bars))
            expected = "" if row["mean_delta_vs_matched_unconditional"] == "" else float(row["mean_delta_vs_matched_unconditional"])
            assert d.mean_delta == (None if expected == "" else expected)

    def test_crossover_events_and_distances(self, result, texts):
        rows = parse_csv(texts[SOURCE_OBSERVATIONS])
        events = rows_of(result, ROW_CROSSOVER_EVENT, symbol="SPY")
        expected = [r for r in rows if r["symbol"] == "SPY" and r["hypothesis_id"] == CROSSOVER_ID
                    and r["state"] in ("bullish", "bearish")]
        assert [e.timestamp.isoformat() for e in events] == [r["timestamp"] for r in expected]
        assert events[0].bars_since_previous_cross is None
        # Crossings sit at cycle positions 0 and 5 of a 12-bar cycle: distances alternate 5, 7.
        positions = [i for i, r in enumerate(sorted((r for r in rows if r["symbol"] == "SPY"
                                                      and r["hypothesis_id"] == CROSSOVER_ID),
                                                     key=lambda r: r["timestamp"]))
                     if r["state"] in ("bullish", "bearish")]
        assert [e.bars_since_previous_cross for e in events[1:]] == [b - a for a, b in zip(positions, positions[1:])]
        assert set(e.bars_since_previous_cross for e in events[1:]) == {5, 7}
        for e, r in zip(events, expected):
            assert [hv.outcome_value for hv in e.returns] == [float(r[f"return_h{h}"]) for h in (1, 5, 20)]

    def test_decision_aids_cover_every_symbol_and_carry_no_verdict(self, result):
        kinds = Counter(a.aid for a in result.decision_aids)
        assert kinds["segment_sign_agreement"] == 2 * len(SYMBOLS) * 2 * 3
        assert kinds["episode_concentration"] == 2 * len(SYMBOLS) * 2
        assert kinds["gate_partition_signs"] == len(SYMBOLS) * 2 * 3
        for a in result.decision_aids:
            assert not any(k in a.detail for k in ("pass", "fail", "verdict", "robust", "significant"))

    def test_row_types_are_the_locked_vocabulary(self, result):
        assert {d.row_type for d in result.diagnostics} == set(ROW_TYPES)


# -- determinism ----------------------------------------------------------------------------------


def test_the_engine_is_deterministic(definition, texts, result):
    again = run_error_analysis(definition, texts)
    assert again == result
