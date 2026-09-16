"""Phase R: the frozen Baseline Study v1 definition, pinned literally.

Every value here is a research decision made before the first real bar was
fetched. A test failing in this module means the methodology changed; the
correct response is a new study version, never an updated expectation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.application import ENSEMBLE, WARMUP_BARS
from src.application.outcomes import OUTCOME_SPECS
from src.application.snapshot import BASIS as APPLICATION_BASIS
from src.data.models import Interval
from src.data.series import PriceBasis
from src.evaluation import OutcomeSpec, PriceField, ReferenceConvention
from src.research import (
    BASELINE_STUDY_V1,
    BENCHMARK_POLICY,
    METRIC_POLICY,
    STUDY_ID,
    STUDY_SCHEMA_VERSION,
    STUDY_VERSION,
    StudyDefinition,
    StudyDefinitionError,
)
from src.research import definition as module
from src.strategies import MomentumInTrendContext, TrendAlignment, TrendCrossover

UTC = timezone.utc

#: The three current hypotheses, exactly as they were when the study was frozen.
LOCKED_HYPOTHESES = (
    ("trend_alignment", 1, "650add07184f8440"),
    ("momentum_in_trend_context", 1, "6589cb8021b76574"),
    ("trend_crossover", 1, "f1126ca778e6f7ce"),
)

#: The Phase 12 outcome specifications the study reuses, by fingerprint.
LOCKED_OUTCOME_SPECS = (
    (1, "83e9dabf9b4e27de"),
    (5, "b586481caf972d58"),
    (20, "a040ca488aa3f51f"),
)

#: The definition's own identity. Changes only with the methodology.
LOCKED_STUDY_FINGERPRINT = "1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261"


def small_definition(**overrides) -> StudyDefinition:
    """A valid short-window definition for engine tests; overrides for validation tests."""
    fields = dict(
        study_id="engine_test",
        study_version=1,
        study_schema_version=1,
        symbols=("AAA", "BBB"),
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        fetch_start=datetime(2024, 1, 1, tzinfo=UTC),
        observation_start=datetime(2024, 3, 1, tzinfo=UTC),
        observation_end=datetime(2024, 6, 1, tzinfo=UTC),
        outcome_data_end=datetime(2024, 7, 1, tzinfo=UTC),
        hypotheses=(TrendAlignment, MomentumInTrendContext, TrendCrossover),
        outcome_specs=tuple(OutcomeSpec(horizon_bars=h) for h in (1, 5, 20)),
        minimum_warmup_bars=51,
    )
    fields.update(overrides)
    return StudyDefinition(**fields)


# -- identity --------------------------------------------------------------------------------


class TestStudyIdentity:
    def test_id_version_and_schema(self):
        assert STUDY_ID == "baseline_study"
        assert STUDY_VERSION == 1
        assert STUDY_SCHEMA_VERSION == 1
        assert BASELINE_STUDY_V1.study_id == STUDY_ID
        assert BASELINE_STUDY_V1.study_version == STUDY_VERSION
        assert BASELINE_STUDY_V1.study_schema_version == STUDY_SCHEMA_VERSION
        assert BASELINE_STUDY_V1.label == "baseline_study_v1"

    def test_policies(self):
        assert METRIC_POLICY == "descriptive_v1"
        assert BENCHMARK_POLICY == "matched_unconditional_v1"
        assert BASELINE_STUDY_V1.metric_policy == METRIC_POLICY
        assert BASELINE_STUDY_V1.benchmark_policy == BENCHMARK_POLICY

    def test_the_study_fingerprint_is_pinned(self):
        assert BASELINE_STUDY_V1.fingerprint == LOCKED_STUDY_FINGERPRINT
        assert len(BASELINE_STUDY_V1.fingerprint) == 64

    def test_the_fingerprint_is_stable_across_instances(self):
        again = replace(BASELINE_STUDY_V1)
        assert again.fingerprint == BASELINE_STUDY_V1.fingerprint
        assert again.canonical_payload() == BASELINE_STUDY_V1.canonical_payload()

    def test_the_canonical_payload_covers_the_whole_methodology(self):
        payload = BASELINE_STUDY_V1.canonical_payload()
        assert set(payload) == {
            "scheme", "scheme_version", "study_id", "study_version", "study_schema_version",
            "symbols", "interval", "basis", "fetch_start", "observation_start",
            "observation_end", "outcome_data_end", "minimum_warmup_bars", "hypotheses",
            "outcome_specs", "metric_policy", "metrics", "deltas", "benchmark_policy",
        }
        assert payload["metrics"] == list(module.METRIC_NAMES)
        assert payload["deltas"] == list(module.DELTA_NAMES)
        assert [(h["hypothesis_id"], h["version"], h["fingerprint"]) for h in payload["hypotheses"]] == list(LOCKED_HYPOTHESES)
        assert [(s["horizon_bars"], s["fingerprint"]) for s in payload["outcome_specs"]] == list(LOCKED_OUTCOME_SPECS)

    @pytest.mark.parametrize(
        "override",
        [
            {"symbols": ("SPY", "QQQ", "IWM", "TLT")},
            {"symbols": ("GLD", "TLT", "IWM", "QQQ", "SPY")},
            {"observation_end": datetime(2024, 12, 31, tzinfo=UTC)},
            {"outcome_data_end": datetime(2025, 4, 1, tzinfo=UTC)},
            {"fetch_start": datetime(2014, 8, 1, tzinfo=UTC)},
            {"hypotheses": (TrendAlignment, MomentumInTrendContext)},
            {"outcome_specs": tuple(OutcomeSpec(horizon_bars=h) for h in (1, 5, 10))},
            {"minimum_warmup_bars": 60},
            {"metric_policy": "descriptive_v2"},
            {"benchmark_policy": "all_timestamps_v1"},
            {"study_version": 2},
        ],
        ids=lambda o: next(iter(o)),
    )
    def test_any_methodology_change_changes_the_fingerprint(self, override):
        changed = replace(BASELINE_STUDY_V1, **override)
        assert changed.fingerprint != LOCKED_STUDY_FINGERPRINT


# -- the locked research decisions --------------------------------------------------------------


class TestLockedDecisions:
    def test_universe_exactly_in_order(self):
        assert BASELINE_STUDY_V1.symbols == ("SPY", "QQQ", "IWM", "TLT", "GLD")
        assert module.UNIVERSE == BASELINE_STUDY_V1.symbols

    def test_windows(self):
        assert BASELINE_STUDY_V1.fetch_start == datetime(2014, 9, 1, tzinfo=UTC)
        assert BASELINE_STUDY_V1.observation_start == datetime(2015, 1, 1, tzinfo=UTC)
        assert BASELINE_STUDY_V1.observation_end == datetime(2025, 1, 1, tzinfo=UTC)
        assert BASELINE_STUDY_V1.outcome_data_end == datetime(2025, 3, 1, tzinfo=UTC)

    def test_interval_and_basis(self):
        assert BASELINE_STUDY_V1.interval is Interval.DAY_1
        assert BASELINE_STUDY_V1.basis is PriceBasis.RAW
        assert BASELINE_STUDY_V1.basis is APPLICATION_BASIS

    def test_minimum_warmup_matches_the_application_floor(self):
        assert BASELINE_STUDY_V1.minimum_warmup_bars == 51 == WARMUP_BARS

    def test_hypotheses_are_the_current_ensemble_unchanged(self):
        assert BASELINE_STUDY_V1.hypotheses == ENSEMBLE
        assert BASELINE_STUDY_V1.hypotheses == (
            TrendAlignment, MomentumInTrendContext, TrendCrossover,
        )
        identities = tuple(
            (spec.hypothesis_id, spec.version, spec.fingerprint)
            for spec in BASELINE_STUDY_V1.hypothesis_specs
        )
        assert identities == LOCKED_HYPOTHESES

    def test_no_conflicted_state_exists(self):
        from src.strategies import ResearchState

        assert {state.value for state in ResearchState} == {
            "bullish", "bearish", "neutral", "insufficient_data",
        }

    def test_horizons_and_outcome_specs_match_phase_twelve(self):
        assert BASELINE_STUDY_V1.horizons == (1, 5, 20)
        study = tuple((s.horizon_bars, s.fingerprint) for s in BASELINE_STUDY_V1.outcome_specs)
        tracked = tuple((s.horizon_bars, s.fingerprint) for s in OUTCOME_SPECS)
        assert study == tracked == LOCKED_OUTCOME_SPECS
        for spec in BASELINE_STUDY_V1.outcome_specs:
            assert spec.required_basis is PriceBasis.RAW
            assert spec.reference is ReferenceConvention.NEXT_BAR_OPEN
            assert spec.future_field is PriceField.CLOSE
        assert tuple(s.canonical_form for s in BASELINE_STUDY_V1.outcome_specs) == tuple(
            s.canonical_form for s in OUTCOME_SPECS
        )

    def test_the_locked_metric_set(self):
        assert module.METRIC_NAMES == (
            "sample_count", "mean_forward_return", "median_forward_return",
            "min_forward_return", "max_forward_return", "positive_count", "negative_count",
            "zero_count", "episode_count",
        )
        assert module.DELTA_NAMES == (
            "mean_delta_vs_matched_unconditional", "median_delta_vs_matched_unconditional",
        )
        for forbidden in ("hit_rate", "positive_return_rate", "sharpe", "sortino", "cagr",
                          "drawdown", "profit", "alpha", "accuracy", "win_rate", "p_value"):
            assert not any(forbidden in name for name in module.METRIC_NAMES + module.DELTA_NAMES)


# -- validation ---------------------------------------------------------------------------------


class TestValidation:
    def test_small_definition_is_valid(self):
        definition = small_definition()
        assert definition.symbols == ("AAA", "BBB")
        assert definition.horizons == (1, 5, 20)

    def test_symbols_are_normalised_and_unique(self):
        assert small_definition(symbols=(" aaa ", "bbb")).symbols == ("AAA", "BBB")
        with pytest.raises(StudyDefinitionError):
            small_definition(symbols=("AAA", "aaa"))
        with pytest.raises(StudyDefinitionError):
            small_definition(symbols=())
        with pytest.raises(StudyDefinitionError):
            small_definition(symbols=("AAA", " "))

    @pytest.mark.parametrize(
        "override",
        [
            {"fetch_start": datetime(2024, 3, 1, tzinfo=UTC)},
            {"observation_start": datetime(2024, 6, 1, tzinfo=UTC)},
            {"observation_end": datetime(2024, 7, 2, tzinfo=UTC)},
            {"outcome_data_end": datetime(2024, 5, 1, tzinfo=UTC)},
        ],
    )
    def test_windows_must_be_ordered(self, override):
        with pytest.raises(StudyDefinitionError, match="windows must satisfy"):
            small_definition(**override)

    def test_windows_must_be_timezone_aware(self):
        with pytest.raises(StudyDefinitionError, match="timezone-aware"):
            small_definition(fetch_start=datetime(2024, 1, 1))

    def test_hypotheses_must_be_hypothesis_classes(self):
        with pytest.raises(StudyDefinitionError):
            small_definition(hypotheses=(TrendAlignment(),))
        with pytest.raises(StudyDefinitionError):
            small_definition(hypotheses=())
        with pytest.raises(StudyDefinitionError, match="unique"):
            small_definition(hypotheses=(TrendAlignment, TrendAlignment))

    def test_outcome_specs_must_share_the_study_basis_and_be_unique(self):
        with pytest.raises(StudyDefinitionError, match="basis"):
            small_definition(outcome_specs=(OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),))
        with pytest.raises(StudyDefinitionError, match="unique"):
            small_definition(outcome_specs=(OutcomeSpec(horizon_bars=5), OutcomeSpec(horizon_bars=5)))
        with pytest.raises(StudyDefinitionError):
            small_definition(outcome_specs=())

    @pytest.mark.parametrize("name", ["study_version", "study_schema_version", "minimum_warmup_bars"])
    def test_counts_must_be_positive_ints(self, name):
        with pytest.raises(StudyDefinitionError):
            small_definition(**{name: 0})
        with pytest.raises(StudyDefinitionError):
            small_definition(**{name: True})

    def test_the_definition_is_frozen(self):
        with pytest.raises(Exception):
            BASELINE_STUDY_V1.symbols = ("SPY",)  # type: ignore[misc]
