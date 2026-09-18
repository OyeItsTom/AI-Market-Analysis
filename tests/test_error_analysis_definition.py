"""Phase 13A: the frozen Error Analysis v1 definition, pinned literally."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.research import ERROR_ANALYSIS_V1, ErrorAnalysisDefinition, ErrorAnalysisError
from src.research import error_analysis as module
from src.research.definition import BASELINE_STUDY_V1
from tests.error_analysis_fixtures import build_texts, definition_for

UTC = timezone.utc

LOCKED_FINGERPRINT = "9081b83bc75ffff8f14d4c3f1f42463d0a15efa6bb93216fe7daa9f737e64e1c"


class TestIdentity:
    def test_study_identity(self):
        assert (module.STUDY_ID, module.STUDY_VERSION, module.STUDY_SCHEMA_VERSION) == ("error_analysis", 1, 1)
        assert ERROR_ANALYSIS_V1.label == "error_analysis_v1"

    def test_source_identity_is_baseline_study_v1(self):
        d = ERROR_ANALYSIS_V1
        assert (d.source_study_id, d.source_study_version) == ("baseline_study", 1)
        assert d.source_study_fingerprint == BASELINE_STUDY_V1.fingerprint == (
            "1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261"
        )
        assert d.source_methodology_sha == "5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31"
        assert d.source_result_sha == "3625e10656b6d11b40479a09d2c467e190480b2e"

    def test_source_hashes_are_the_frozen_live_run(self):
        assert dict(ERROR_ANALYSIS_V1.source_hashes) == {
            "manifest.json": "d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf",
            "summary.csv": "cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee",
            "observations.csv": "c2be1f66f10d7dc31debfaac76d67c850664166a65d1585bdd3769d0a228af76",
        }

    def test_source_window(self):
        assert ERROR_ANALYSIS_V1.source_observation_start == datetime(2015, 1, 1, tzinfo=UTC)
        assert ERROR_ANALYSIS_V1.source_observation_end == datetime(2025, 1, 1, tzinfo=UTC)

    def test_universe_hypotheses_horizons_match_the_source(self):
        assert ERROR_ANALYSIS_V1.symbols == BASELINE_STUDY_V1.symbols == ("SPY", "QQQ", "IWM", "TLT", "GLD")
        assert ERROR_ANALYSIS_V1.hypotheses == tuple(
            (s.hypothesis_id, s.version, s.fingerprint) for s in BASELINE_STUDY_V1.hypothesis_specs
        )
        assert ERROR_ANALYSIS_V1.horizons == BASELINE_STUDY_V1.horizons == (1, 5, 20)

    def test_segments_exactly(self):
        assert ERROR_ANALYSIS_V1.segments == (
            ("2015-2016", datetime(2015, 1, 1, tzinfo=UTC), datetime(2017, 1, 1, tzinfo=UTC)),
            ("2017-2018", datetime(2017, 1, 1, tzinfo=UTC), datetime(2019, 1, 1, tzinfo=UTC)),
            ("2019-2020", datetime(2019, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC)),
            ("2021-2022", datetime(2021, 1, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC)),
            ("2023-2024", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        )

    def test_asset_classes_exactly(self):
        assert dict(ERROR_ANALYSIS_V1.asset_classes) == {
            "SPY": "equity", "QQQ": "equity", "IWM": "equity", "TLT": "treasury", "GLD": "gold",
        }

    def test_diagnostics_row_types_and_metrics(self):
        assert ERROR_ANALYSIS_V1.diagnostics == (
            "D1_episode_structure", "D2_gate_decomposition", "D3_temporal_segmentation",
            "D4_class_signs", "D5_crossover_events", "D6_semantic_contract",
        )
        assert ERROR_ANALYSIS_V1.row_types == (
            "episode_summary", "episode_start", "gate_crosstab", "gate_partition",
            "segment_state", "segment_matched", "class_signs", "crossover_event",
        )
        assert ERROR_ANALYSIS_V1.metric_names == (
            "sample_count", "mean_forward_return", "median_forward_return", "min_forward_return",
            "max_forward_return", "positive_count", "negative_count", "zero_count", "episode_count",
        )
        for forbidden in ("hit", "sharpe", "alpha", "p_value", "accuracy", "win"):
            assert not any(forbidden in m for m in ERROR_ANALYSIS_V1.metric_names)

    def test_decision_aids_are_descriptive_constants(self):
        assert ERROR_ANALYSIS_V1.decision_aid_segment_majority == 4
        assert ERROR_ANALYSIS_V1.decision_aid_episode_share == 0.25
        assert "not statistical tests" in ERROR_ANALYSIS_V1.canonical_payload()["decision_aids"]["kind"]

    def test_the_fingerprint_is_pinned_and_stable(self):
        assert ERROR_ANALYSIS_V1.fingerprint == LOCKED_FINGERPRINT
        assert replace(ERROR_ANALYSIS_V1).fingerprint == LOCKED_FINGERPRINT

    def test_fingerprint_excludes_runtime_inputs(self):
        payload = ERROR_ANALYSIS_V1.canonical_payload()
        text = str(payload)
        for absent in ("generated_at", "git_commit", "out_root", "output"):
            assert absent not in text

    @pytest.mark.parametrize(
        "override",
        [
            {"study_version": 2},
            {"study_schema_version": 2},
            {"source_study_fingerprint": "0" * 64},
            {"source_methodology_sha": "0" * 40},
            {"source_result_sha": "0" * 40},
            {"source_hashes": {**ERROR_ANALYSIS_V1.source_hashes, "summary.csv": "0" * 64}},
            {"symbols": ("SPY", "QQQ", "IWM", "TLT")},
            {"symbols": ("GLD", "TLT", "IWM", "QQQ", "SPY")},
            {"horizons": (1, 5, 10)},
            {"segments": (
                ("s1", datetime(2015, 1, 1, tzinfo=UTC), datetime(2016, 1, 1, tzinfo=UTC)),
                ("s2", datetime(2016, 1, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC)),
                ("s3", datetime(2018, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC)),
                ("s4", datetime(2020, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC)),
                ("s5", datetime(2022, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
            )},
            {"asset_classes": {**ERROR_ANALYSIS_V1.asset_classes, "GLD": "commodity"}},
            {"diagnostics": ERROR_ANALYSIS_V1.diagnostics[:5]},
            {"metric_names": ERROR_ANALYSIS_V1.metric_names + ("hit_rate",)},
            {"row_types": ERROR_ANALYSIS_V1.row_types[:7]},
            {"decision_aid_segment_majority": 3},
            {"decision_aid_episode_share": 0.5},
        ],
        ids=lambda o: next(iter(o)),
    )
    def test_any_locked_choice_changes_the_fingerprint(self, override):
        assert replace(ERROR_ANALYSIS_V1, **override).fingerprint != LOCKED_FINGERPRINT


class TestValidation:
    def test_synthetic_definition_is_valid(self):
        texts = build_texts()
        d = definition_for(texts)
        assert d.symbols == ("SPY", "TLT") and d.fingerprint != LOCKED_FINGERPRINT

    def test_segments_must_cover_the_window_contiguously(self):
        gap = (
            ("a", datetime(2015, 1, 1, tzinfo=UTC), datetime(2019, 1, 1, tzinfo=UTC)),
            ("b", datetime(2020, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        )
        with pytest.raises(ErrorAnalysisError, match="contiguous"):
            replace(ERROR_ANALYSIS_V1, segments=gap)
        short = (("a", datetime(2015, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),)
        with pytest.raises(ErrorAnalysisError, match="cover"):
            replace(ERROR_ANALYSIS_V1, segments=short)

    def test_segment_of_uses_half_open_utc_bounds(self):
        d = ERROR_ANALYSIS_V1
        assert d.segment_of(datetime(2016, 12, 31, 23, 59, tzinfo=UTC)) == "2015-2016"
        assert d.segment_of(datetime(2017, 1, 1, tzinfo=UTC)) == "2017-2018"
        assert d.segment_of(datetime(2024, 12, 31, 5, tzinfo=UTC)) == "2023-2024"
        with pytest.raises(ErrorAnalysisError):
            d.segment_of(datetime(2025, 1, 1, tzinfo=UTC))

    def test_class_map_must_cover_every_symbol(self):
        with pytest.raises(ErrorAnalysisError, match="asset_classes"):
            replace(ERROR_ANALYSIS_V1, asset_classes={"SPY": "equity"})

    def test_required_hypotheses(self):
        with pytest.raises(ErrorAnalysisError, match="must include"):
            replace(ERROR_ANALYSIS_V1, hypotheses=ERROR_ANALYSIS_V1.hypotheses[:2])

    def test_hashes_must_be_complete_and_hex(self):
        with pytest.raises(ErrorAnalysisError, match="exactly"):
            replace(ERROR_ANALYSIS_V1, source_hashes={"manifest.json": "0" * 64})
        with pytest.raises(ErrorAnalysisError, match="64 hex"):
            replace(ERROR_ANALYSIS_V1, source_hashes={**ERROR_ANALYSIS_V1.source_hashes, "summary.csv": "zz"})

    def test_the_definition_is_frozen(self):
        with pytest.raises(Exception):
            ERROR_ANALYSIS_V1.symbols = ("SPY",)  # type: ignore[misc]
        assert isinstance(ERROR_ANALYSIS_V1, ErrorAnalysisDefinition)
