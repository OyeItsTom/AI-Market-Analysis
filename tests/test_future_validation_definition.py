"""FUTURE_VALIDATION_V1: the frozen pre-registration, its fingerprint and its sources.

The fingerprint is rebuilt here independently of the ``fingerprint``
property; the retrospective references are re-derived from the tracked Phase
R ``summary.csv`` (whose bytes are pinned); the methodology document is held
to the live definition.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import fields, replace
from pathlib import Path

import pytest

from src.evaluation import OutcomeSpec
from src.prospective import COLLECTION_V1, PROVENANCE_V1
from src.research import BASELINE_STUDY_V1, BENCHMARK_POLICY
from src.research.future_validation import (
    CATEGORIES,
    FUTURE_VALIDATION_V1,
    FUTURE_VALIDATION_V1_FINGERPRINT,
    REFERENCE_SOURCE,
    FutureValidationDefinitionError,
)
from src.strategies import MomentumInTrendContext, TrendAlignment
from tests.future_validation_fixtures import future_validation_firewall  # noqa: F401

REPO = Path(__file__).resolve().parent.parent
V1 = FUTURE_VALIDATION_V1
METHODOLOGY = REPO / "docs" / "research" / "future_validation_v1.md"
ADR = REPO / "docs" / "adr" / "0014-future-validation-v1.md"

#: The pinned identity, written out in the test as well.
LOCKED = "79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab"
#: Superseded in the M2A blocker repair (host-clock stop rule; stale coverage text).
SUPERSEDED = "0b113f89387871f4f17c401fee1e71f7bdc7d330015f718328b5d6ea7a17f377"


class TestFingerprint:
    def test_rebuilt_independently(self):
        text = json.dumps(V1.canonical_form(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
        rebuilt = hashlib.sha256(text.encode("ascii")).hexdigest()
        assert rebuilt == FUTURE_VALIDATION_V1_FINGERPRINT == V1.fingerprint == LOCKED
        assert len(LOCKED) == 64
        assert SUPERSEDED not in (LOCKED, V1.fingerprint)

    def test_canonical_json_is_ascii_sorted_and_compact(self):
        text = V1.canonical_json()
        assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=True)
        text.encode("ascii")

    def test_no_machine_path_activation_time_or_future_data(self):
        text = V1.canonical_json()
        for forbidden in ("/Users", "data/prospective", "activated_at\":\"", "2026-10",
                          "\\\\", "C:"):
            assert forbidden not in text

    @pytest.mark.parametrize("name", [f.name for f in fields(V1)])
    def test_every_field_is_covered(self, name):
        value = getattr(V1, name)
        if isinstance(value, str):
            changed = replace(V1, **{name: value + "x"})
        elif name == "primary_horizon_bars":
            changed = replace(V1, primary_horizon_bars=5)
        elif isinstance(value, int):
            changed = replace(V1, **{name: value + 1})
        elif name == "categories":  # fixed: any change is refused outright
            with pytest.raises(FutureValidationDefinitionError):
                replace(V1, categories=value[:-1])
            assert "categories" in V1.canonical_form()
            return
        elif name == "references":
            changed = replace(V1, references=(replace(V1.references[0], bullish_sample_count=1),
                                              *V1.references[1:]))
        elif name == "primary_symbols":
            changed = replace(V1, primary_symbols=("SPY", "IWM", "QQQ"),
                              references=(V1.references[0], V1.references[2],
                                          V1.references[1]))
        elif name in ("outcome_spec_fingerprints",):
            changed = replace(V1, outcome_spec_fingerprints=((5, "x" * 16), (20, "a040ca488aa3f51f")))
        elif isinstance(value, tuple):
            changed = replace(V1, **{name: value[:-1] if len(value) > 1 else value + value})
        else:
            changed = replace(V1, **{name: replace(value, **{
                fields(value)[0].name: getattr(value, fields(value)[0].name) + "x"})})
        assert changed.fingerprint != V1.fingerprint, name


class TestFrozenQuestion:
    def test_primary_cell(self):
        assert V1.validation_id == "future_validation_v1"
        assert (V1.primary_hypothesis.hypothesis_id, V1.primary_hypothesis.version,
                V1.primary_hypothesis.fingerprint) == ("trend_alignment", 1, "650add07184f8440")
        assert (V1.primary_state, V1.primary_horizon_bars, V1.basis, V1.interval) == (
            "bullish", 20, "raw", "1d")
        assert V1.primary_symbols == ("SPY", "QQQ", "IWM")
        assert V1.secondary_symbols == ("TLT", "GLD")
        assert V1.primary_statistical_view == "observation_level"
        assert V1.spec_fingerprint(20) == "a040ca488aa3f51f" == \
            OutcomeSpec(horizon_bars=20).fingerprint
        assert V1.spec_fingerprint(5) == OutcomeSpec(horizon_bars=5).fingerprint

    def test_identities_match_the_live_code(self):
        assert V1.collection_fingerprint == COLLECTION_V1.fingerprint == \
            "af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8"
        assert V1.provenance_policy_fingerprint == PROVENANCE_V1.fingerprint == \
            "ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117"
        assert V1.provenance_policy_id == PROVENANCE_V1.policy_id
        assert TrendAlignment().spec.fingerprint == V1.primary_hypothesis.fingerprint
        assert MomentumInTrendContext().spec.fingerprint == \
            V1.secondary_hypotheses[0].fingerprint
        assert V1.collection_id == COLLECTION_V1.collection_id

    def test_stop_rule_adequacy_and_categories(self):
        assert (V1.stop_rule_minimum_calendar_months, V1.stop_rule_minimum_matured_claims,
                V1.forced_unlock_calendar_months, V1.minimum_bullish_episodes) == (48, 750, 72, 8)
        assert V1.categories == CATEGORIES == (
            "invalid", "inconclusive_insufficient_sample", "directionally_consistent",
            "directionally_reversed", "mixed")
        assert [name for name, _ in V1.category_rules] == list(CATEGORIES)
        assert "BEARISH minimum" in V1.adequacy_rule or "no BEARISH minimum" in V1.adequacy_rule

    def test_scope(self):
        assert V1.benchmark_policy == BENCHMARK_POLICY == "matched_unconditional_v1"
        analyses = {a.analysis_id for a in V1.secondary_analyses}
        assert analyses == {"A_primary_cell_h5", "B_trend_alignment_bearish",
                            "C_primary_episode_start", "D_primary_by_calendar_year",
                            "E_momentum_in_trend_context", "F_trend_alignment_tlt_gld",
                            "G_coverage"}
        for analysis in V1.secondary_analyses:
            assert "trend_crossover" not in analysis.hypothesis_ids
            assert 1 not in analysis.horizons
        scope = " ".join(V1.out_of_scope)
        for item in ("trend_crossover", "horizon 1", "NEUTRAL", "depressed-RSI", "adjusted",
                     "pooled", "hit rate", "Sharpe", "p-values", "confidence intervals",
                     "2025-03-01"):
            assert item in scope
        assert V1.reserved_interval_start == "2025-03-01"
        assert V1.reserved_interval_start == COLLECTION_V1.holdout_start.isoformat()
        assert V1.early_termination_rule.startswith("none in v1")
        assert V1.overall_verdict_rule.startswith("none")

    def test_construction_refuses_malformed_definitions(self):
        with pytest.raises(FutureValidationDefinitionError):
            replace(V1, references=V1.references[:2])
        with pytest.raises(FutureValidationDefinitionError):
            replace(V1, forced_unlock_calendar_months=47)
        with pytest.raises(FutureValidationDefinitionError):
            replace(V1, categories=CATEGORIES[::-1])
        with pytest.raises(FutureValidationDefinitionError):
            replace(V1, secondary_symbols=("SPY",))
        with pytest.raises(FutureValidationDefinitionError):
            replace(V1.references[0], mean_delta=V1.references[0].mean_delta * 2)


class TestEvidenceClockContract:
    """B1 repair: E1 and F are frozen on the evidence clock, never the host clock."""

    def test_the_rules_name_the_evidence_clock(self):
        assert "evidence_through" in V1.calendar_month_rule
        assert "evaluation instant" not in V1.calendar_month_rule
        assert "evidence_through is at least 48 calendar months" in V1.stop_rule
        assert "evidence_through is at least 72 calendar months" in V1.stop_rule
        assert "never authoritative" in V1.evidence_clock_rule
        assert "distinct from the cutoffs C_s" in V1.evidence_clock_rule
        assert "never the host wall clock" in V1.stop_rule_blindness_rule

    def test_a_stopped_collection_never_opens_and_needs_a_new_registration(self):
        rule = V1.early_termination_rule
        assert rule.startswith("none in v1")
        assert "never opened" in rule
        assert "separately pre-registered amendment or new validation version" in rule
        assert "forced unlock" not in rule  # no fallback opening path


class TestCoverageContract:
    """B2 repair: the frozen G_coverage text describes exactly what is emitted."""

    def test_the_text_promises_nothing_after_the_cutoff(self):
        coverage = next(a for a in V1.secondary_analyses if a.analysis_id == "G_coverage")
        assert "after the cutoff" not in coverage.description
        assert "at or before the cutoff only" in coverage.description
        assert "refresh counts" not in coverage.description  # N4: no post-C_s run counts

    def test_the_emitted_coverage_keys_are_exactly_the_described_ones(self):
        from tests.future_validation_fixtures import Book
        from src.research.future_validation_engine import cutoffs, secondary_results

        book = Book()
        book.trend("SPY", 0)
        row = secondary_results(V1, book.level_three(), cutoffs(V1, book.level_one())
                                )["G_coverage"]["rows"][0]
        assert set(row) == {
            "symbol", "cutoff", "missed_sessions_at_or_before_cutoff",
            "claims_in_population_at_or_before_cutoff", "claims_matured_h20",
            "claims_unmatured_h20_at_or_before_cutoff",
            "claims_degraded_excluded_at_or_before_cutoff", "claims_insufficient_history",
            "claims_reserved_interval_excluded"}


class TestRetrospectiveReferences:
    def rows(self):
        path = REPO / REFERENCE_SOURCE.summary_path
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def test_source_bytes_are_pinned(self):
        summary = (REPO / REFERENCE_SOURCE.summary_path).read_bytes()
        manifest = (REPO / REFERENCE_SOURCE.manifest_path).read_bytes()
        assert hashlib.sha256(summary).hexdigest() == REFERENCE_SOURCE.summary_sha256
        assert hashlib.sha256(manifest).hexdigest() == REFERENCE_SOURCE.manifest_sha256
        recorded = json.loads(manifest)
        assert recorded["study_fingerprint"] == REFERENCE_SOURCE.study_fingerprint == \
            BASELINE_STUDY_V1.fingerprint
        assert recorded["git_commit"] == REFERENCE_SOURCE.methodology_git_commit
        assert recorded["benchmark_policy"] == REFERENCE_SOURCE.benchmark_policy
        assert recorded["artifacts"]["summary.csv"]["sha256"] == REFERENCE_SOURCE.summary_sha256
        assert re.fullmatch(r"[0-9a-f]{40}", REFERENCE_SOURCE.result_git_commit)

    @pytest.mark.parametrize("symbol", ["SPY", "QQQ", "IWM"])
    def test_references_are_the_exact_summary_values(self, symbol):
        rows = [r for r in self.rows() if r["hypothesis_id"] == "trend_alignment"
                and r["symbol"] == symbol and r["horizon_bars"] == "20"]
        state = next(r for r in rows if r["row_type"] == "state" and r["state"] == "bullish")
        matched = next(r for r in rows if r["row_type"] == "matched_unconditional")
        assert state["spec_fingerprint"] == V1.spec_fingerprint(20)
        reference = V1.reference(symbol)
        assert reference.bullish_sample_count == int(state["sample_count"])
        assert reference.bullish_episode_count == int(state["episode_count"])
        assert reference.bullish_mean == float(state["mean_forward_return"])
        assert reference.bullish_median == float(state["median_forward_return"])
        assert reference.matched_sample_count == int(matched["sample_count"])
        assert reference.matched_mean == float(matched["mean_forward_return"])
        assert reference.matched_median == float(matched["median_forward_return"])
        assert reference.mean_delta == float(state["mean_delta_vs_matched_unconditional"])
        assert reference.median_delta == float(state["median_delta_vs_matched_unconditional"])
        # the literals are exact round-trips of the CSV text
        assert repr(reference.mean_delta) == state["mean_delta_vs_matched_unconditional"]
        assert repr(reference.median_delta) == state["median_delta_vs_matched_unconditional"]

    def test_every_reference_delta_is_non_zero(self):
        for reference in V1.references:
            assert reference.mean_delta != 0 and reference.median_delta != 0


# -- no 0.5x rule, no k-of-3 vote ---------------------------------------------------------------

SOURCES = [REPO / "src" / "research" / "future_validation.py",
           REPO / "src" / "research" / "future_validation_engine.py",
           REPO / "src" / "application" / "future_validation.py",
           REPO / "src" / "cli" / "future_validation.py",
           REPO / "src" / "future_validation" / "store.py",
           REPO / "src" / "future_validation" / "__init__.py"]
DOCS = [METHODOLOGY, ADR]
VOTE = re.compile(r"k[- _]of[- _]3|\b2 of 3\b|two of three|majority|overall[_ ]validat|"
                  r"overall[_ ]pass|overall[_ ]fail|validated\s*=\s*true|combined score",
                  re.IGNORECASE)
HALF = re.compile(r"\b0\.5\b|\b50 ?%|\bhalf\b|0\.5x", re.IGNORECASE)
NEGATION = re.compile(r"\b(no|not|never|without|nor|none|rejected|instead of|neither)\b",
                      re.IGNORECASE)


class TestNoThresholdNoVote:
    @pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
    def test_sources_contain_no_magnitude_threshold_or_vote(self, path):
        text = path.read_text()
        assert not HALF.search(text), path.name
        assert not VOTE.search(text), path.name

    @pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
    def test_documents_mention_them_only_to_reject_them(self, path):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if HALF.search(line) or VOTE.search(line):
                assert NEGATION.search(line), f"{path.name}:{number}: {line}"


# -- the methodology document matches the live definition ----------------------------------------


class TestMethodologyDocument:
    def text(self):
        return METHODOLOGY.read_text()

    def test_it_states_the_live_fingerprint_and_identities(self):
        text = self.text()
        assert V1.fingerprint in text
        assert V1.collection_fingerprint in text
        assert V1.provenance_policy_fingerprint in text
        assert REFERENCE_SOURCE.summary_sha256 in text
        assert REFERENCE_SOURCE.study_fingerprint in text
        assert REFERENCE_SOURCE.methodology_git_commit in text
        assert REFERENCE_SOURCE.result_git_commit in text

    def test_it_states_every_frozen_number_and_reference(self):
        text = self.text()
        for item in ("48 calendar months", "750", "72 calendar months", "8 BULLISH episodes",
                     "h20", "trend_alignment", "650add07184f8440", "a040ca488aa3f51f",
                     "matched_unconditional_v1", "2025-03-01"):
            assert item in text, item
        for reference in V1.references:
            for value in (reference.mean_delta, reference.median_delta, reference.bullish_mean,
                          reference.bullish_median, reference.matched_mean,
                          reference.matched_median):
                assert repr(value) in text, (reference.symbol, value)

    def test_it_names_every_category_analysis_and_out_of_scope_item(self):
        text = self.text()
        for category in CATEGORIES:
            assert category in text
        for analysis in V1.secondary_analyses:
            assert analysis.analysis_id in text
        for item in V1.out_of_scope:
            assert item in text, item
        for disclosure in V1.disclosures:
            assert disclosure in text

    def test_the_adr_records_the_decision(self):
        text = ADR.read_text()
        assert "FUTURE_VALIDATION_V1" in text and V1.fingerprint in text
