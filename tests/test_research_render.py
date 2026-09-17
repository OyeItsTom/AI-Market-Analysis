"""Phase R renderers: fixed columns, exact round-trips, raw/summary consistency,
manifest identity, and a report that states facts only."""

from __future__ import annotations

import csv
import io
import json
import statistics
from datetime import datetime

import pytest

from src.research import (
    ARTIFACT_OBSERVATIONS,
    ARTIFACT_REPORT,
    ARTIFACT_SUMMARY,
    LIMITATIONS,
    OBSERVATION_COLUMNS,
    OVERLAP_CAVEAT,
    RETROSPECTIVE_CAVEAT,
    ROW_COVERAGE,
    ROW_MATCHED_UNCONDITIONAL,
    ROW_NEUTRAL_REASON,
    ROW_STATE,
    SUMMARY_COLUMNS,
    manifest_payload,
    observation_columns,
    observation_rows,
    render_csv,
    render_manifest,
    render_report,
    run_study,
    summary_rows,
)
from src.research.definition import DELTA_NAMES, METRIC_NAMES
from src.research.render import format_float, format_timestamp
from tests.research_fixtures import UTC, series_for
from tests.test_research_definition import small_definition

GIT = "0123456789abcdef0123456789abcdef01234567"
RETRIEVED = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
GENERATED = datetime(2026, 9, 20, 12, 5, tzinfo=UTC)


@pytest.fixture(scope="module")
def definition():
    return small_definition()


@pytest.fixture(scope="module")
def result(definition):
    return run_study(definition, series_for(definition))


@pytest.fixture(scope="module")
def summary_csv(result):
    return render_csv(SUMMARY_COLUMNS, summary_rows(result))


@pytest.fixture(scope="module")
def observations_csv(result, definition):
    return render_csv(observation_columns(definition.outcome_specs), observation_rows(result))


@pytest.fixture(scope="module")
def manifest(result):
    return manifest_payload(
        result,
        git_commit=GIT,
        source="synthetic",
        retrieved_at=RETRIEVED,
        generated_at=GENERATED,
        bars_fingerprints={"AAA": "a" * 64, "BBB": "b" * 64},
        summary_sha256="1" * 64,
        observations_sha256="2" * 64,
        report_sha256="3" * 64,
    )


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


# -- columns -----------------------------------------------------------------------------------


class TestColumns:
    def test_summary_columns_are_fixed(self):
        assert SUMMARY_COLUMNS[:9] == (
            "row_type", "hypothesis_id", "hypothesis_version", "hypothesis_fingerprint",
            "symbol", "horizon_bars", "spec_fingerprint", "state", "reason_signature",
        )
        assert SUMMARY_COLUMNS[9:20] == METRIC_NAMES + DELTA_NAMES
        assert "directional_hit_rate" not in SUMMARY_COLUMNS
        assert "positive_return_rate" not in SUMMARY_COLUMNS
        assert len(set(SUMMARY_COLUMNS)) == len(SUMMARY_COLUMNS)

    def test_observation_columns_are_fixed(self):
        assert OBSERVATION_COLUMNS == (
            "symbol", "timestamp", "hypothesis_id", "hypothesis_version",
            "hypothesis_fingerprint", "state", "reason_codes",
            "status_h1", "return_h1", "reference_timestamp_h1", "future_timestamp_h1",
            "status_h5", "return_h5", "reference_timestamp_h5", "future_timestamp_h5",
            "status_h20", "return_h20", "reference_timestamp_h20", "future_timestamp_h20",
        )

    def test_the_csv_header_is_exactly_the_columns(self, summary_csv, observations_csv):
        assert summary_csv.splitlines()[0] == ",".join(SUMMARY_COLUMNS)
        assert observations_csv.splitlines()[0] == ",".join(OBSERVATION_COLUMNS)
        assert "\r" not in summary_csv and "\r" not in observations_csv

    def test_no_trading_label_in_any_column(self):
        for column in SUMMARY_COLUMNS + OBSERVATION_COLUMNS:
            assert not any(word in column for word in ("buy", "sell", "long", "short", "trade", "signal"))


# -- summary.csv --------------------------------------------------------------------------------


class TestSummary:
    def test_row_types_and_counts(self, summary_csv, result, definition):
        rows = parse_csv(summary_csv)
        types = [row["row_type"] for row in rows]
        coverage = len(result.coverage) * len(definition.horizons)
        assert types[:coverage] == [ROW_COVERAGE] * coverage
        assert set(types[coverage:]) <= {ROW_STATE, ROW_MATCHED_UNCONDITIONAL, ROW_NEUTRAL_REASON}
        assert len(rows) == coverage + len(result.groups)

    def test_coverage_rows_carry_only_coverage_cells(self, summary_csv):
        for row in parse_csv(summary_csv):
            if row["row_type"] != ROW_COVERAGE:
                continue
            assert row["sample_count"] == "" and row["mean_forward_return"] == ""
            assert row["state"] == "" and row["reason_signature"] == ""
            for column in ("total_observations", "bullish_count", "bearish_count", "neutral_count",
                           "insufficient_data_count", "evaluated", "insufficient_future_data",
                           "no_reference_bar", "ineligible", "bars_fetched", "warmup_bars",
                           "observation_bars", "outcome_buffer_bars"):
                assert row[column].isdigit(), column
            assert (int(row["evaluated"]) + int(row["insufficient_future_data"])
                    + int(row["no_reference_bar"]) + int(row["ineligible"])
                    == int(row["total_observations"]))

    def test_result_rows_carry_only_result_cells(self, summary_csv):
        for row in parse_csv(summary_csv):
            if row["row_type"] == ROW_COVERAGE:
                continue
            assert row["total_observations"] == "" and row["bars_fetched"] == ""
            assert row["sample_count"].isdigit()
            if row["row_type"] == ROW_MATCHED_UNCONDITIONAL:
                assert row["state"] == "all"
                assert row["mean_delta_vs_matched_unconditional"] == ""
            if row["row_type"] == ROW_NEUTRAL_REASON:
                assert row["state"] == "neutral" and row["reason_signature"]

    def test_no_cross_symbol_row(self, summary_csv, definition):
        for row in parse_csv(summary_csv):
            assert row["symbol"] in definition.symbols


# -- observations.csv ---------------------------------------------------------------------------


class TestObservations:
    def test_one_row_per_symbol_bar_hypothesis(self, observations_csv, result):
        rows = parse_csv(observations_csv)
        assert len(rows) == len(result.observations)
        keys = [(r["symbol"], r["timestamp"], r["hypothesis_id"]) for r in rows]
        assert len(set(keys)) == len(keys)

    def test_floats_round_trip_exactly(self, observations_csv, result):
        rows = parse_csv(observations_csv)
        for row, source in zip(rows, result.observations):
            for outcome in source.outcomes:
                cell = row[f"return_h{outcome.horizon_bars}"]
                if outcome.outcome_value is None:
                    assert cell == ""
                else:
                    assert float(cell) == outcome.outcome_value
                assert row[f"status_h{outcome.horizon_bars}"] == outcome.status.value

    def test_timestamps_are_utc_iso(self, observations_csv):
        for row in parse_csv(observations_csv)[:5]:
            assert row["timestamp"].endswith("+00:00")
            datetime.fromisoformat(row["timestamp"])


class TestRawSummaryConsistency:
    def test_every_state_row_is_reproducible_from_observations(self, summary_csv, observations_csv):
        """Recompute each result row from the raw export with independent code."""
        raw = parse_csv(observations_csv)
        for row in parse_csv(summary_csv):
            if row["row_type"] == ROW_COVERAGE:
                continue
            horizon = row["horizon_bars"]
            members = [
                r for r in raw
                if r["symbol"] == row["symbol"] and r["hypothesis_id"] == row["hypothesis_id"]
                and r[f"status_h{horizon}"] == "evaluated"
                and (row["row_type"] == ROW_MATCHED_UNCONDITIONAL or r["state"] == row["state"])
                and (row["row_type"] != ROW_NEUTRAL_REASON or r["reason_codes"] == row["reason_signature"])
            ]
            values = [float(r[f"return_h{horizon}"]) for r in members]
            assert int(row["sample_count"]) == len(values)
            if not values:
                assert row["mean_forward_return"] == "" and row["min_forward_return"] == ""
                assert row["episode_count"] == "0"
                continue
            assert float(row["mean_forward_return"]) == statistics.fmean(values)
            assert float(row["median_forward_return"]) == statistics.median(values)
            assert float(row["min_forward_return"]) == min(values)
            assert float(row["max_forward_return"]) == max(values)
            assert int(row["positive_count"]) == sum(1 for v in values if v > 0)
            assert int(row["negative_count"]) == sum(1 for v in values if v < 0)
            assert int(row["zero_count"]) == sum(1 for v in values if v == 0)
            assert row["first_evaluated_timestamp"] == min(r["timestamp"] for r in members)
            assert row["last_evaluated_timestamp"] == max(r["timestamp"] for r in members)

    def test_deltas_are_reproducible_from_the_matched_row(self, summary_csv):
        rows = parse_csv(summary_csv)
        matched = {
            (r["hypothesis_id"], r["symbol"], r["horizon_bars"]): r
            for r in rows if r["row_type"] == ROW_MATCHED_UNCONDITIONAL
        }
        for row in rows:
            if row["row_type"] in (ROW_COVERAGE, ROW_MATCHED_UNCONDITIONAL) or row["sample_count"] == "0":
                continue
            reference = matched[(row["hypothesis_id"], row["symbol"], row["horizon_bars"])]
            assert float(row["mean_delta_vs_matched_unconditional"]) == (
                float(row["mean_forward_return"]) - float(reference["mean_forward_return"])
            )
            assert float(row["median_delta_vs_matched_unconditional"]) == (
                float(row["median_forward_return"]) - float(reference["median_forward_return"])
            )

    def test_the_matched_timestamps_are_the_union_of_state_timestamps(self, observations_csv):
        """No second benchmark sample: evaluated rows, state ignored, is the benchmark."""
        raw = parse_csv(observations_csv)
        for horizon in ("1", "5", "20"):
            for symbol in ("AAA", "BBB"):
                for hypothesis in {r["hypothesis_id"] for r in raw}:
                    evaluated = [r for r in raw if r["symbol"] == symbol and r["hypothesis_id"] == hypothesis
                                 and r[f"status_h{horizon}"] == "evaluated"]
                    union = set()
                    for state in ("bullish", "bearish", "neutral"):
                        union |= {r["timestamp"] for r in evaluated if r["state"] == state}
                    assert union == {r["timestamp"] for r in evaluated}


# -- manifest -----------------------------------------------------------------------------------


class TestManifest:
    REQUIRED = {
        "study_id", "study_version", "study_schema_version", "study_fingerprint",
        "study_definition", "git_commit", "source", "interval", "basis", "universe",
        "fetch_start", "observation_start", "observation_end", "outcome_data_end",
        "window_semantics", "hypotheses", "outcome_specs", "evaluation_conventions",
        "metric_policy", "metrics", "deltas", "benchmark_policy", "benchmark_definition",
        "symbols", "retrieved_at", "generated_at", "artifacts", "overlap_caveat",
        "retrospective_caveat", "limitations",
    }

    def test_required_keys(self, manifest):
        assert self.REQUIRED <= set(manifest)

    def test_identity_and_windows(self, manifest, definition):
        assert manifest["study_fingerprint"] == definition.fingerprint
        assert manifest["git_commit"] == GIT
        assert manifest["universe"] == ["AAA", "BBB"]
        assert manifest["observation_end"] == format_timestamp(definition.observation_end)
        assert manifest["window_semantics"]["untouched_future_begins"] == format_timestamp(definition.outcome_data_end)
        assert "never classified" in manifest["window_semantics"]["outcome_buffer"]

    def test_per_symbol_block(self, manifest, result):
        assert [s["symbol"] for s in manifest["symbols"]] == ["AAA", "BBB"]
        block = manifest["symbols"][0]
        assert block["bars_fingerprint"] == "a" * 64
        assert block["bars_count"] == result.symbols[0].bars_fetched
        assert block["warmup_bars"] == result.symbols[0].warmup_bars
        assert block["observation_bars"] == result.symbols[0].observation_bars
        assert block["outcome_buffer_bars"] == result.symbols[0].outcome_buffer_bars
        assert block["max_abs_single_bar_close_return"] == result.symbols[0].max_abs_single_bar_close_return
        assert block["first_timestamp"] == format_timestamp(result.symbols[0].first_timestamp)

    def test_hypotheses_specs_and_conventions(self, manifest):
        assert [h["hypothesis_id"] for h in manifest["hypotheses"]] == [
            "trend_alignment", "momentum_in_trend_context", "trend_crossover",
        ]
        assert [s["horizon_bars"] for s in manifest["outcome_specs"]] == [1, 5, 20]
        assert manifest["evaluation_conventions"]["reference"] == "next_bar_open"
        assert manifest["evaluation_conventions"]["future_field"] == "close"

    def test_artifact_hashes_and_tracking_policy(self, manifest):
        artifacts = manifest["artifacts"]
        assert artifacts[ARTIFACT_SUMMARY] == {"sha256": "1" * 64, "git_tracked": True}
        assert artifacts[ARTIFACT_OBSERVATIONS]["sha256"] == "2" * 64
        assert artifacts[ARTIFACT_OBSERVATIONS]["git_tracked"] is False
        assert "excluded from Git" in artifacts[ARTIFACT_OBSERVATIONS]["note"]
        assert artifacts[ARTIFACT_REPORT] == {"sha256": "3" * 64, "git_tracked": True}
        assert "manifest.json" not in artifacts  # a file cannot carry its own hash

    def test_the_report_hash_is_optional_and_the_report_never_prints_it(self, result, manifest):
        preliminary = manifest_payload(
            result, git_commit=GIT, source="synthetic", retrieved_at=RETRIEVED,
            generated_at=GENERATED, bars_fingerprints={"AAA": "a" * 64, "BBB": "b" * 64},
            summary_sha256="1" * 64, observations_sha256="2" * 64,
        )
        assert preliminary["artifacts"][ARTIFACT_REPORT]["sha256"] is None
        differing = {k for k in manifest if manifest[k] != preliminary[k]}
        assert differing == {"artifacts"}
        assert render_report(result, preliminary) == render_report(result, manifest)
        assert "3" * 64 not in render_report(result, manifest)

    def test_caveats(self, manifest):
        assert manifest["overlap_caveat"] == OVERLAP_CAVEAT
        assert manifest["retrospective_caveat"] == RETROSPECTIVE_CAVEAT
        assert manifest["limitations"] == list(LIMITATIONS)

    def test_missing_fingerprint_is_refused(self, result):
        with pytest.raises(ValueError, match="missing"):
            manifest_payload(result, git_commit=GIT, source="s", retrieved_at=RETRIEVED,
                             generated_at=GENERATED, bars_fingerprints={"AAA": "a"},
                             summary_sha256="1", observations_sha256="2")

    def test_rendering_is_deterministic_sorted_ascii_json(self, manifest):
        text = render_manifest(manifest)
        assert text == render_manifest(dict(reversed(list(manifest.items()))))
        assert text.endswith("\n")
        assert text.isascii()
        parsed = json.loads(text)
        assert list(parsed) == sorted(parsed)
        assert parsed == json.loads(json.dumps(manifest))

    def test_only_timestamps_differ_between_clocks(self, result, manifest):
        later = manifest_payload(
            result, git_commit=GIT, source="synthetic",
            retrieved_at=RETRIEVED.replace(year=2027), generated_at=GENERATED.replace(year=2027),
            bars_fingerprints={"AAA": "a" * 64, "BBB": "b" * 64},
            summary_sha256="1" * 64, observations_sha256="2" * 64, report_sha256="3" * 64,
        )
        differing = {key for key in manifest if manifest[key] != later[key]}
        assert differing == {"retrieved_at", "generated_at"}


# -- report -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report(result, manifest):
    return render_report(result, manifest)


class TestReport:
    FORBIDDEN = (
        "profitable", "profitability", "predictive", "edge", "strategy works", "buy signal",
        "sell signal", "beats the market", "statistically significant", "significance",
        "hit rate", "win rate", "accuracy", "alpha", "sharpe", "p-value", "confidence interval",
    )

    def test_sections_in_order(self, report):
        headings = [line for line in report.splitlines() if line.startswith("## ")]
        assert headings == [
            "## Study definition", "## Reproducibility", "## Universe and period",
            "## Hypotheses", "## Evaluation protocol", "## Coverage",
            "## Results by hypothesis", "## NEUTRAL reason-code breakdown", "## Limitations",
        ]
        assert report.startswith("# Phase R — engine_test v1")

    def test_facts_are_present(self, report, definition, manifest):
        assert definition.fingerprint in report
        assert GIT in report
        assert "a" * 64 in report
        for spec in definition.hypothesis_specs:
            assert spec.fingerprint in report and spec.canonical_form in report
        assert "excluded from Git" in report
        assert OVERLAP_CAVEAT in report
        assert RETROSPECTIVE_CAVEAT in report
        for limitation in LIMITATIONS:
            assert limitation in report

    def test_every_result_group_is_tabulated(self, report, result):
        table_rows = [line for line in report.splitlines() if line.startswith("| AAA") or line.startswith("| BBB")]
        primary = [g for g in result.groups if g.row_type in (ROW_STATE, ROW_MATCHED_UNCONDITIONAL)]
        assert len(table_rows) >= len(primary)
        neutral = [line for line in report.splitlines() if "momentum_midrange" in line]
        assert neutral

    def test_no_interpretation_or_forbidden_claim(self, report):
        # The limitations section and the fixed caveats name some of these
        # words only to deny them; everything else must not mention them.
        body = report.split("## Limitations")[0].replace(OVERLAP_CAVEAT, "").lower()
        for phrase in self.FORBIDDEN:
            assert phrase not in body, phrase
        lowered = report.lower()
        for word in ("we conclude", "suggests that", "this shows", "evidence of", "outperform"):
            assert word not in lowered

    def test_no_hit_rate_field_leaks(self, report, summary_csv, observations_csv):
        for text in (report, summary_csv, observations_csv):
            assert "directional_hit_rate" not in text
            assert "positive_return_rate" not in text


class TestFormatting:
    def test_float_and_timestamp_cells(self):
        assert format_float(None) == ""
        assert format_float(0.1 + 0.2) == "0.30000000000000004"
        assert float(format_float(1e-7)) == 1e-7
        assert format_timestamp(None) == ""
        assert format_timestamp(datetime(2024, 1, 2, tzinfo=UTC)) == "2024-01-02T00:00:00+00:00"

    def test_render_csv_refuses_unknown_columns(self):
        with pytest.raises(ValueError):
            render_csv(("a",), [{"a": "1", "b": "2"}])
