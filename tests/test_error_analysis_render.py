"""Phase 13A renderers: fixed columns, row-type vocabulary, manifest lineage and hash model,
factual report, determinism."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.research import run_error_analysis
from src.research.error_analysis import ROW_TYPES, SOURCE_ARTIFACT_NAMES
from src.research.error_analysis_render import (
    ARTIFACT_DIAGNOSTICS,
    ARTIFACT_EPISODES,
    ARTIFACT_NAMES,
    ARTIFACT_REPORT,
    DIAGNOSTIC_COLUMNS,
    EPISODE_COLUMNS,
    LIMITATIONS,
    SEMANTIC_CONTRACT,
    diagnostic_columns,
    episode_columns,
    manifest_payload,
    render_diagnostics_csv,
    render_episodes_csv,
    render_manifest,
    render_report,
)
from tests.error_analysis_fixtures import build_texts, definition_for, parse_csv

UTC = timezone.utc
GIT = "0123456789abcdef0123456789abcdef01234567"
WHEN = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def texts():
    return build_texts()


@pytest.fixture(scope="module")
def result(texts):
    return run_error_analysis(definition_for(texts), texts)


@pytest.fixture(scope="module")
def manifest(result):
    return manifest_payload(result, git_commit=GIT, generated_at=WHEN, diagnostics_sha256="1" * 64,
                            episodes_sha256="2" * 64, report_sha256="3" * 64)


class TestColumns:
    def test_artifact_names(self):
        assert ARTIFACT_NAMES == ("manifest.json", "diagnostics.csv", "episodes.csv", "report.md")

    def test_diagnostic_columns_are_fixed(self):
        assert DIAGNOSTIC_COLUMNS == diagnostic_columns((1, 5, 20))
        assert DIAGNOSTIC_COLUMNS[0] == "row_type"
        assert DIAGNOSTIC_COLUMNS[-6:] == ("status_h1", "return_h1", "status_h5", "return_h5",
                                            "status_h20", "return_h20")
        for forbidden in ("hit_rate", "positive_return_rate", "sharpe", "alpha", "p_value"):
            assert forbidden not in DIAGNOSTIC_COLUMNS
        assert len(set(DIAGNOSTIC_COLUMNS)) == len(DIAGNOSTIC_COLUMNS)

    def test_episode_columns_are_fixed(self):
        assert EPISODE_COLUMNS == episode_columns((1, 5, 20))
        assert EPISODE_COLUMNS[:10] == (
            "hypothesis_id", "hypothesis_version", "hypothesis_fingerprint", "symbol", "state",
            "reason_signature", "episode_index", "start_timestamp", "end_timestamp", "length",
        )

    def test_csv_headers_and_row_types(self, result):
        diagnostics = render_diagnostics_csv(result)
        episodes = render_episodes_csv(result)
        assert diagnostics.splitlines()[0] == ",".join(DIAGNOSTIC_COLUMNS)
        assert episodes.splitlines()[0] == ",".join(EPISODE_COLUMNS)
        rows = parse_csv(diagnostics)
        assert {r["row_type"] for r in rows} == set(ROW_TYPES)
        assert len(rows) == len(result.diagnostics)
        assert len(parse_csv(episodes)) == len(result.episodes)
        assert "\r" not in diagnostics and "\r" not in episodes

    def test_episode_rows_round_trip(self, result):
        rows = parse_csv(render_episodes_csv(result))
        for row, e in zip(rows, result.episodes):
            assert int(row["length"]) == e.length and row["state"] == e.state
            for hv in e.start_outcomes:
                assert row[f"start_status_h{hv.horizon_bars}"] == hv.status
                if hv.outcome_value is not None:
                    assert float(row[f"start_return_h{hv.horizon_bars}"]) == hv.outcome_value


class TestManifest:
    def test_lineage_and_identity(self, manifest, result):
        d = result.definition
        assert manifest["study_id"] == "error_analysis" and manifest["study_version"] == 1
        assert manifest["study_fingerprint"] == d.fingerprint
        assert manifest["git_commit"] == GIT and manifest["generated_at"] == WHEN.isoformat()
        source = manifest["source"]
        assert source["artifact_sha256"] == {n: d.source_hashes[n] for n in SOURCE_ARTIFACT_NAMES}
        assert source["study_fingerprint"] == d.source_study_fingerprint
        assert source["methodology_sha"] == d.source_methodology_sha
        assert source["result_sha"] == d.source_result_sha
        assert source["observation_rows"] == result.observation_rows
        assert source["summary_rows_cross_checked"] == result.source_rows_checked
        assert manifest["network"].startswith("none")
        assert "2025-03-01" in manifest["future_data"]

    def test_hash_model_is_non_circular(self, manifest):
        artifacts = manifest["artifacts"]
        assert set(artifacts) == {ARTIFACT_DIAGNOSTICS, ARTIFACT_EPISODES, ARTIFACT_REPORT}
        assert artifacts[ARTIFACT_REPORT]["sha256"] == "3" * 64
        assert all(a["git_tracked"] is True for a in artifacts.values())

    def test_decision_aids_are_labelled_not_verdicts(self, manifest):
        aids = manifest["decision_aids"]
        assert "not statistical tests" in aids["kind"]
        assert aids["entries"] and all("verdict" not in e and "pass" not in e for e in aids["entries"])

    def test_manifest_rendering_is_sorted_ascii_and_deterministic(self, manifest):
        text = render_manifest(manifest)
        assert text == render_manifest(dict(reversed(list(manifest.items()))))
        assert text.isascii() and text.endswith("\n")
        assert list(json.loads(text)) == sorted(json.loads(text))

    def test_naive_clock_is_refused(self, result):
        with pytest.raises(ValueError):
            manifest_payload(result, git_commit=GIT, generated_at=datetime(2026, 1, 1),
                             diagnostics_sha256="1" * 64, episodes_sha256="2" * 64)


@pytest.fixture(scope="module")
def report(result, manifest):
    return render_report(result, manifest)


class TestReport:
    FORBIDDEN = ("profitable", "predictive edge", "significant", "winning", "successful",
                 "buy signal", "sell signal", "recommend", "best ", "outperform", "robust")

    def test_sections(self, report):
        headings = [l for l in report.splitlines() if l.startswith("## ")]
        assert headings == [
            "## Identity and lineage", "## D6 — Semantic contract", "## D1 — Episode structure",
            "## D2 — Gate decomposition on common timestamps (trend_alignment × momentum_in_trend_context)",
            "## D3 — Predeclared temporal segments",
            "## D4 — Asset-class sign annotation (metadata only; nothing pooled)",
            "## D5 — Crossover events", "## Predeclared descriptive decision aids", "## Limitations",
        ]

    def test_facts_present(self, report, result):
        d = result.definition
        assert d.fingerprint in report and GIT in report
        for n in SOURCE_ARTIFACT_NAMES:
            assert d.source_hashes[n] in report
        for s in SEMANTIC_CONTRACT:
            assert s in report
        for l in LIMITATIONS:
            assert l in report
        assert "2025-03-01 onward not read" in report

    def test_no_conclusion_vocabulary(self, report):
        body = report.split("## Limitations")[0].lower()
        for s in SEMANTIC_CONTRACT:
            body = body.replace(s.lower(), "")
        body = body.replace("robustness proofs", "")
        for phrase in self.FORBIDDEN:
            assert phrase not in body, phrase
        for word in ("we conclude", "suggests that", "this shows", "the hypothesis predicted"):
            assert word not in body

    def test_decision_aids_are_labelled(self, report):
        section = report.split("## Predeclared descriptive decision aids")[1]
        assert "not statistical tests" in section
        assert "nothing is selected by them" in section


def test_all_renderings_are_deterministic(result, manifest):
    assert render_diagnostics_csv(result) == render_diagnostics_csv(result)
    assert render_episodes_csv(result) == render_episodes_csv(result)
    assert render_report(result, manifest) == render_report(result, manifest)
