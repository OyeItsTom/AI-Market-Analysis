"""FUTURE_VALIDATION_V1: the frozen pre-registration of the prospective validation (M2).

This module is the research question and nothing else. It holds no
computation, reads nothing and knows no location: every decision the
validation depends on is a field of :class:`FutureValidationDefinition`, and
:data:`FUTURE_VALIDATION_V1_FINGERPRINT` pins the SHA-256 of its canonical
JSON. The pure engine (``future_validation_engine.py``) and the operational
runner apply this definition; neither may widen it, and no command-line
option can change any field. A different question is a different version.

The question
------------
For each of SPY, QQQ and IWM **separately**: after prospective activation,
for legitimate Prospective Collection v1 ``trend_alignment`` BULLISH claims,
how does the 20-bar RAW forward return compare with the matched-unconditional
benchmark under exactly the Phase R ``matched_unconditional_v1`` semantics --
and how does that prospective comparison sit beside the frozen Phase R
retrospective reference?

Each primary symbol receives its own category. There is no pooled statistic,
no vote across symbols and no overall verdict: the three equity ETFs are
correlated and are not three independent replications.

Why literals
------------
The retrospective references are exact float literals derived once from the
tracked Phase R ``summary.csv`` (whose SHA-256 is pinned beside them); a test
re-derives them from that file. Nothing here re-reads the file at run time, so
no later change to it can silently alter the definition. The collection and
provenance fingerprints are likewise declared, not derived: the runner checks
them against the live code and refuses on any difference.

See ``docs/research/future_validation_v1.md`` and
``docs/adr/0014-future-validation-v1.md``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class FutureValidationDefinitionError(ValueError):
    """Raised when a validation definition is malformed."""


VALIDATION_ID: str = "future_validation_v1"
SCHEMA_VERSION: int = 1
#: Version of the deterministic runner contract (unlock, snapshot, result).
RUNNER_VERSION: int = 1

UNLOCK_SCHEMA: str = "future_validation_unlock_v1"
RESULT_SCHEMA: str = "future_validation_result_v1"

# -- categories ----------------------------------------------------------------------------------

CATEGORY_INVALID: str = "invalid"
CATEGORY_INCONCLUSIVE: str = "inconclusive_insufficient_sample"
CATEGORY_CONSISTENT: str = "directionally_consistent"
CATEGORY_REVERSED: str = "directionally_reversed"
CATEGORY_MIXED: str = "mixed"

#: Every per-symbol category, in the order they are evaluated.
CATEGORIES: tuple[str, ...] = (
    CATEGORY_INVALID,
    CATEGORY_INCONCLUSIVE,
    CATEGORY_CONSISTENT,
    CATEGORY_REVERSED,
    CATEGORY_MIXED,
)

CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    (CATEGORY_INVALID,
     "evaluated first: the symbol's evidence failed an identity, provenance or "
     "measurement-integrity condition"),
    (CATEGORY_INCONCLUSIVE,
     "evaluated second: fewer than minimum_bullish_episodes BULLISH episodes with matured, "
     "provenance-eligible h20 observations at or before the symbol's cutoff"),
    (CATEGORY_CONSISTENT,
     "prospective mean delta and prospective median delta are both non-zero and each has "
     "the same sign as the corresponding frozen retrospective reference delta"),
    (CATEGORY_REVERSED,
     "prospective mean delta and prospective median delta are both non-zero and each has "
     "the opposite sign to the corresponding frozen retrospective reference delta"),
    (CATEGORY_MIXED,
     "every other adequate case: mean and median disagree, either delta is exactly zero, "
     "or one is consistent and the other reversed"),
)

# -- identities ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HypothesisIdentity:
    hypothesis_id: str
    version: int
    fingerprint: str

    def canonical_form(self) -> dict[str, Any]:
        return {"fingerprint": self.fingerprint, "hypothesis_id": self.hypothesis_id,
                "version": self.version}


@dataclass(frozen=True)
class ReferenceSource:
    """Where the retrospective references come from, pinned to exact bytes and commits."""

    study_id: str
    study_version: int
    study_fingerprint: str
    methodology_git_commit: str
    result_git_commit: str
    summary_path: str
    summary_sha256: str
    manifest_path: str
    manifest_sha256: str
    benchmark_policy: str

    def canonical_form(self) -> dict[str, Any]:
        return {
            "benchmark_policy": self.benchmark_policy,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "methodology_git_commit": self.methodology_git_commit,
            "result_git_commit": self.result_git_commit,
            "study_fingerprint": self.study_fingerprint,
            "study_id": self.study_id,
            "study_version": self.study_version,
            "summary_path": self.summary_path,
            "summary_sha256": self.summary_sha256,
        }


def _require_nonzero_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float):
        raise FutureValidationDefinitionError(f"{label} must be a float, got {value!r}")
    if value != value or value in (float("inf"), float("-inf")):
        raise FutureValidationDefinitionError(f"{label} must be finite")
    if value == 0.0:
        raise FutureValidationDefinitionError(
            f"{label} is exactly zero; a zero retrospective reference has no sign to compare "
            "with and cannot be a ratio denominator"
        )
    return value


@dataclass(frozen=True)
class RetrospectiveReference:
    """The frozen Phase R primary cell for one symbol (trend_alignment, BULLISH, h20, raw)."""

    symbol: str
    bullish_sample_count: int
    bullish_episode_count: int
    bullish_mean: float
    bullish_median: float
    matched_sample_count: int
    matched_mean: float
    matched_median: float
    mean_delta: float
    median_delta: float

    def __post_init__(self) -> None:
        _require_nonzero_float(self.mean_delta, f"{self.symbol} reference mean_delta")
        _require_nonzero_float(self.median_delta, f"{self.symbol} reference median_delta")
        for name in ("bullish_mean", "bullish_median", "matched_mean", "matched_median"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float):
                raise FutureValidationDefinitionError(f"{self.symbol} {name} must be a float")
        # The deltas are exactly the Phase R subtraction; anything else is a copying error.
        if self.bullish_mean - self.matched_mean != self.mean_delta \
                or self.bullish_median - self.matched_median != self.median_delta:
            raise FutureValidationDefinitionError(
                f"{self.symbol}: reference deltas are not the exact Phase R subtractions"
            )

    def canonical_form(self) -> dict[str, Any]:
        return {
            "bullish_episode_count": self.bullish_episode_count,
            "bullish_mean": self.bullish_mean,
            "bullish_median": self.bullish_median,
            "bullish_sample_count": self.bullish_sample_count,
            "matched_mean": self.matched_mean,
            "matched_median": self.matched_median,
            "matched_sample_count": self.matched_sample_count,
            "mean_delta": self.mean_delta,
            "median_delta": self.median_delta,
            "symbol": self.symbol,
        }


@dataclass(frozen=True)
class SecondaryAnalysis:
    """One descriptive-only analysis. It can never change a primary category."""

    analysis_id: str
    hypothesis_ids: tuple[str, ...]
    states: tuple[str, ...]
    horizons: tuple[int, ...]
    symbols: tuple[str, ...]
    view: str
    description: str

    def canonical_form(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "description": self.description,
            "horizons": list(self.horizons),
            "hypothesis_ids": list(self.hypothesis_ids),
            "states": list(self.states),
            "symbols": list(self.symbols),
            "view": self.view,
        }


# -- the definition ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FutureValidationDefinition:
    """One complete, immutable validation definition. Every field is fingerprinted."""

    validation_id: str
    schema_version: int
    runner_version: int
    question: str
    collection_id: str
    collection_fingerprint: str
    provenance_policy_id: str
    provenance_policy_fingerprint: str
    interval: str
    basis: str
    evaluation_version: int
    primary_hypothesis: HypothesisIdentity
    primary_state: str
    primary_horizon_bars: int
    primary_symbols: tuple[str, ...]
    secondary_symbols: tuple[str, ...]
    secondary_hypotheses: tuple[HypothesisIdentity, ...]
    outcome_spec_fingerprints: tuple[tuple[int, str], ...]
    primary_statistical_view: str
    population_rule: str
    benchmark_policy: str
    benchmark_rule: str
    reference_source: ReferenceSource
    references: tuple[RetrospectiveReference, ...]
    primary_metrics: tuple[str, ...]
    descriptive_ratios: tuple[str, ...]
    magnitude_ratio_rule: str
    categories: tuple[str, ...]
    category_rules: tuple[tuple[str, str], ...]
    overall_verdict_rule: str
    stop_rule_minimum_calendar_months: int
    stop_rule_minimum_matured_claims: int
    forced_unlock_calendar_months: int
    evidence_clock_rule: str
    calendar_month_rule: str
    stop_rule: str
    stop_rule_blindness_rule: str
    cutoff_rule: str
    minimum_bullish_episodes: int
    adequacy_rule: str
    episode_rule: str
    degraded_evidence_rule: str
    provenance_rule: str
    reserved_interval_start: str
    reserved_interval_rule: str
    secondary_analyses: tuple[SecondaryAnalysis, ...]
    secondary_isolation_rule: str
    out_of_scope: tuple[str, ...]
    invalidity_conditions: tuple[str, ...]
    non_invalidating_conditions: tuple[str, ...]
    early_termination_rule: str
    one_open_rule: str
    snapshot_rule: str
    unlock_schema: str
    result_schema: str
    disclosures: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.primary_symbols:
            raise FutureValidationDefinitionError("primary_symbols must not be empty")
        universe = self.primary_symbols + self.secondary_symbols
        if len(set(universe)) != len(universe):
            raise FutureValidationDefinitionError("a symbol may appear only once")
        if tuple(ref.symbol for ref in self.references) != self.primary_symbols:
            raise FutureValidationDefinitionError(
                "exactly one retrospective reference per primary symbol, in order"
            )
        horizons = dict(self.outcome_spec_fingerprints)
        if self.primary_horizon_bars not in horizons:
            raise FutureValidationDefinitionError("the primary horizon needs a spec fingerprint")
        for analysis in self.secondary_analyses:
            for horizon in analysis.horizons:
                if horizon not in horizons:
                    raise FutureValidationDefinitionError(
                        f"{analysis.analysis_id}: horizon {horizon} has no spec fingerprint")
        if self.categories != CATEGORIES:
            raise FutureValidationDefinitionError("categories are fixed")
        for name in ("stop_rule_minimum_calendar_months", "stop_rule_minimum_matured_claims",
                     "forced_unlock_calendar_months", "minimum_bullish_episodes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise FutureValidationDefinitionError(f"{name} must be a non-negative int")
        if self.forced_unlock_calendar_months < self.stop_rule_minimum_calendar_months:
            raise FutureValidationDefinitionError("forced unlock cannot precede the stop rule")

    # -- derived views (not part of the canonical form) ------------------------------------

    @property
    def symbols(self) -> tuple[str, ...]:
        """Every symbol the validation describes: primary first, then secondary."""
        return self.primary_symbols + self.secondary_symbols

    def spec_fingerprint(self, horizon_bars: int) -> str:
        return dict(self.outcome_spec_fingerprints)[horizon_bars]

    def reference(self, symbol: str) -> RetrospectiveReference:
        for reference in self.references:
            if reference.symbol == symbol:
                return reference
        raise KeyError(symbol)

    def hypothesis(self, hypothesis_id: str) -> HypothesisIdentity:
        for identity in (self.primary_hypothesis, *self.secondary_hypotheses):
            if identity.hypothesis_id == hypothesis_id:
                return identity
        raise KeyError(hypothesis_id)

    # -- identity --------------------------------------------------------------------------

    def canonical_form(self) -> dict[str, Any]:
        return {
            "adequacy_rule": self.adequacy_rule,
            "basis": self.basis,
            "benchmark_policy": self.benchmark_policy,
            "benchmark_rule": self.benchmark_rule,
            "calendar_month_rule": self.calendar_month_rule,
            "categories": list(self.categories),
            "category_rules": [[name, rule] for name, rule in self.category_rules],
            "collection_fingerprint": self.collection_fingerprint,
            "collection_id": self.collection_id,
            "cutoff_rule": self.cutoff_rule,
            "degraded_evidence_rule": self.degraded_evidence_rule,
            "descriptive_ratios": list(self.descriptive_ratios),
            "disclosures": list(self.disclosures),
            "early_termination_rule": self.early_termination_rule,
            "episode_rule": self.episode_rule,
            "evaluation_version": self.evaluation_version,
            "evidence_clock_rule": self.evidence_clock_rule,
            "forced_unlock_calendar_months": self.forced_unlock_calendar_months,
            "interval": self.interval,
            "invalidity_conditions": list(self.invalidity_conditions),
            "magnitude_ratio_rule": self.magnitude_ratio_rule,
            "minimum_bullish_episodes": self.minimum_bullish_episodes,
            "non_invalidating_conditions": list(self.non_invalidating_conditions),
            "one_open_rule": self.one_open_rule,
            "out_of_scope": list(self.out_of_scope),
            "outcome_spec_fingerprints": [[h, fp] for h, fp in self.outcome_spec_fingerprints],
            "overall_verdict_rule": self.overall_verdict_rule,
            "population_rule": self.population_rule,
            "primary_horizon_bars": self.primary_horizon_bars,
            "primary_hypothesis": self.primary_hypothesis.canonical_form(),
            "primary_metrics": list(self.primary_metrics),
            "primary_state": self.primary_state,
            "primary_statistical_view": self.primary_statistical_view,
            "primary_symbols": list(self.primary_symbols),
            "provenance_policy_fingerprint": self.provenance_policy_fingerprint,
            "provenance_policy_id": self.provenance_policy_id,
            "provenance_rule": self.provenance_rule,
            "question": self.question,
            "reference_source": self.reference_source.canonical_form(),
            "references": [reference.canonical_form() for reference in self.references],
            "reserved_interval_rule": self.reserved_interval_rule,
            "reserved_interval_start": self.reserved_interval_start,
            "result_schema": self.result_schema,
            "runner_version": self.runner_version,
            "schema_version": self.schema_version,
            "secondary_analyses": [a.canonical_form() for a in self.secondary_analyses],
            "secondary_hypotheses": [h.canonical_form() for h in self.secondary_hypotheses],
            "secondary_isolation_rule": self.secondary_isolation_rule,
            "secondary_symbols": list(self.secondary_symbols),
            "snapshot_rule": self.snapshot_rule,
            "stop_rule": self.stop_rule,
            "stop_rule_blindness_rule": self.stop_rule_blindness_rule,
            "stop_rule_minimum_calendar_months": self.stop_rule_minimum_calendar_months,
            "stop_rule_minimum_matured_claims": self.stop_rule_minimum_matured_claims,
            "unlock_schema": self.unlock_schema,
            "validation_id": self.validation_id,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_form(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @property
    def fingerprint(self) -> str:
        """Full SHA-256 of the canonical JSON."""
        return hashlib.sha256(self.canonical_json().encode("ascii")).hexdigest()


# -- the frozen values ---------------------------------------------------------------------------

PRIMARY_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
SECONDARY_SYMBOLS: tuple[str, ...] = ("TLT", "GLD")

TREND_ALIGNMENT = HypothesisIdentity("trend_alignment", 1, "650add07184f8440")
MOMENTUM_IN_TREND_CONTEXT = HypothesisIdentity("momentum_in_trend_context", 1, "6589cb8021b76574")

#: Raw forward-return specs of Prospective Collection v1 (horizon -> spec fingerprint).
OUTCOME_SPEC_FINGERPRINTS: tuple[tuple[int, str], ...] = (
    (5, "b586481caf972d58"),
    (20, "a040ca488aa3f51f"),
)

REFERENCE_SOURCE = ReferenceSource(
    study_id="baseline_study",
    study_version=1,
    study_fingerprint="1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261",
    methodology_git_commit="5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31",
    result_git_commit="3625e10656b6d11b40479a09d2c467e190480b2e",
    summary_path="docs/research/baseline_study_v1/summary.csv",
    summary_sha256="cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee",
    manifest_path="docs/research/baseline_study_v1/manifest.json",
    manifest_sha256="d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf",
    benchmark_policy="matched_unconditional_v1",
)

#: Exact Phase R values (summary.csv rows: state/bullish and matched_unconditional/all,
#: trend_alignment, horizon 20, spec a040ca488aa3f51f).
REFERENCES: tuple[RetrospectiveReference, ...] = (
    RetrospectiveReference(
        symbol="SPY",
        bullish_sample_count=1709, bullish_episode_count=26,
        bullish_mean=0.00618879428271334, bullish_median=0.013607798752205635,
        matched_sample_count=2516,
        matched_mean=0.009315311305321278, matched_median=0.015199267558811735,
        mean_delta=-0.0031265170226079386, median_delta=-0.0015914688066061,
    ),
    RetrospectiveReference(
        symbol="QQQ",
        bullish_sample_count=1732, bullish_episode_count=27,
        bullish_mean=0.009176130346056625, bullish_median=0.016815690415374895,
        matched_sample_count=2516,
        matched_mean=0.014004018405437404, matched_median=0.019558389789087194,
        mean_delta=-0.004827888059380779, median_delta=-0.0027426993737122984,
    ),
    RetrospectiveReference(
        symbol="IWM",
        bullish_sample_count=1580, bullish_episode_count=32,
        bullish_mean=0.002112656389286471, bullish_median=0.006034942929120213,
        matched_sample_count=2516,
        matched_mean=0.00656092928863241, matched_median=0.009627624744022567,
        mean_delta=-0.0044482728993459385, median_delta=-0.0035926818149023543,
    ),
)

PRIMARY_METRICS: tuple[str, ...] = (
    "bullish_observation_count",
    "bullish_episode_count",
    "bullish_mean_h20",
    "bullish_median_h20",
    "matched_unconditional_count",
    "matched_unconditional_mean_h20",
    "matched_unconditional_median_h20",
    "mean_delta",
    "median_delta",
)

DESCRIPTIVE_RATIOS: tuple[str, ...] = (
    "abs_mean_delta_ratio_vs_reference",
    "abs_median_delta_ratio_vs_reference",
)

SECONDARY_ANALYSES: tuple[SecondaryAnalysis, ...] = (
    SecondaryAnalysis(
        "A_primary_cell_h5", ("trend_alignment",), ("bullish",), (5,), PRIMARY_SYMBOLS,
        "observation_level",
        "the primary cell (trend_alignment BULLISH vs matched unconditional) at horizon 5"),
    SecondaryAnalysis(
        "B_trend_alignment_bearish", ("trend_alignment",), ("bearish",), (5, 20),
        PRIMARY_SYMBOLS, "observation_level",
        "trend_alignment BEARISH vs matched unconditional at horizons 5 and 20"),
    SecondaryAnalysis(
        "C_primary_episode_start", ("trend_alignment",), ("bullish",), (20,), PRIMARY_SYMBOLS,
        "episode_start",
        "the h20 values at the first observation of each primary BULLISH episode"),
    SecondaryAnalysis(
        "D_primary_by_calendar_year", ("trend_alignment",), ("bullish",), (20,),
        PRIMARY_SYMBOLS, "observation_level_by_utc_calendar_year_of_bar",
        "the primary cell restricted to each calendar year of the bar timestamp"),
    SecondaryAnalysis(
        "E_momentum_in_trend_context", ("momentum_in_trend_context",), ("bullish", "bearish"),
        (5, 20), PRIMARY_SYMBOLS, "observation_level",
        "momentum_in_trend_context BULLISH and BEARISH vs its own matched unconditional"),
    SecondaryAnalysis(
        "F_trend_alignment_tlt_gld", ("trend_alignment",), ("bullish", "bearish"), (20,),
        SECONDARY_SYMBOLS, "observation_level",
        "trend_alignment on TLT and GLD, per symbol, descriptive only"),
    SecondaryAnalysis(
        "G_coverage", ("trend_alignment",), (), (20,), PRIMARY_SYMBOLS + SECONDARY_SYMBOLS,
        "coverage_accounting",
        "per symbol, at or before the cutoff only: missed sessions, population claims, "
        "matured h20 claims, unmatured claims (pending, refused, revised or outside the "
        "fetched history; indistinguishable per claim), degraded/excluded claims and "
        "insufficient-history claims; plus the count of reserved-interval claims excluded"),
)

OUT_OF_SCOPE: tuple[str, ...] = (
    "trend_crossover (sparse transition states)",
    "assessment-policy artifacts as validation targets",
    "horizon 1",
    "NEUTRAL subgroups and reason-signature groups",
    "the depressed-RSI question",
    "the adjusted price basis",
    "pooled cross-symbol statistics",
    "a pooled asset-class statistic",
    "hit rate",
    "Sharpe or any risk-adjusted ratio",
    "p-values",
    "confidence intervals",
    "any trading, position or profit framing",
    "the reserved interval from 2025-03-01 to activated_at",
)

INVALIDITY_CONDITIONS: tuple[str, ...] = (
    "prospective provenance invalid",
    "COLLECTION_V1 fingerprint mismatch (manifest or live code)",
    "PROVENANCE_V1 fingerprint mismatch",
    "FUTURE_VALIDATION_V1 fingerprint mismatch",
    "activation manifest corruption",
    "required ledger or run-log corruption",
    "required historical records missing (a frozen input prefix changed, shrank or vanished)",
    "M2 definition or runner identity mismatch once activation binding exists",
    "a material lookahead or measurement defect discovered in the evidence",
    "unsupported evidence contamination that cannot be excluded safely",
)

NON_INVALIDATING_CONDITIONS: tuple[str, ...] = (
    "missed sessions",
    "provider refusal",
    "bar revisions",
    "degraded evidence that was excluded",
    "low sample",
    "operational early termination of collection",
)

DISCLOSURES: tuple[str, ...] = (
    "h20 forward windows of adjacent observations overlap heavily (up to 19 of 20 bars).",
    "Observations within one episode are serially dependent; the observation count is not "
    "a count of independent trials.",
    "SPY, QQQ and IWM are correlated equity ETFs; the three symbol results are not three "
    "independent confirmations.",
    "No inferential significance claim is made: no p-value, confidence interval or test.",
    "This is a research comparison of forward returns only. It says nothing about any "
    "position, order, cost or achievable return of any market participant.",
)

FUTURE_VALIDATION_V1: FutureValidationDefinition = FutureValidationDefinition(
    validation_id=VALIDATION_ID,
    schema_version=SCHEMA_VERSION,
    runner_version=RUNNER_VERSION,
    question=(
        "For each of SPY, QQQ and IWM separately: after prospective activation, for "
        "legitimate Prospective Collection v1 trend_alignment BULLISH claims, how does the "
        "20-bar RAW forward return compare with the matched-unconditional benchmark under "
        "exactly the Phase R matched_unconditional_v1 semantics, and how does that "
        "prospective comparison compare descriptively with the frozen Phase R retrospective "
        "reference?"
    ),
    collection_id="prospective_collection_v1",
    collection_fingerprint="af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8",
    provenance_policy_id="prospective_provenance_v1",
    provenance_policy_fingerprint=(
        "ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117"),
    interval="1d",
    basis="raw",
    evaluation_version=1,
    primary_hypothesis=TREND_ALIGNMENT,
    primary_state="bullish",
    primary_horizon_bars=20,
    primary_symbols=PRIMARY_SYMBOLS,
    secondary_symbols=SECONDARY_SYMBOLS,
    secondary_hypotheses=(MOMENTUM_IN_TREND_CONTEXT,),
    outcome_spec_fingerprints=OUTCOME_SPEC_FINGERPRINTS,
    primary_statistical_view="observation_level",
    population_rule=(
        "per symbol: observation artifacts of the named hypothesis (id, version and "
        "fingerprint exact) in the Prospective Collection v1 ledger, read from the frozen "
        "input snapshot, whose bar settles strictly after activated_at, whose key is not "
        "excluded by the provenance report, and whose bar timestamp is at or before the "
        "symbol's cutoff C_s; an observation contributes a value at horizon h only through a "
        "non-excluded outcome record with the horizon's spec fingerprint and evaluation "
        "version 1"),
    benchmark_policy="matched_unconditional_v1",
    benchmark_rule=(
        "matched unconditional: all matured forward returns at exactly the population "
        "observations of the same hypothesis, symbol and horizon, state ignored (Phase R "
        "all_evaluated); mean via statistics.fmean and median via statistics.median over "
        "values in bar order; delta = state statistic minus matched statistic; computed with "
        "the Phase R DescriptiveStats and count_episodes code"),
    reference_source=REFERENCE_SOURCE,
    references=REFERENCES,
    primary_metrics=PRIMARY_METRICS,
    descriptive_ratios=DESCRIPTIVE_RATIOS,
    magnitude_ratio_rule=(
        "abs(prospective delta) / abs(frozen reference delta), separately for mean and "
        "median; null when the prospective delta is undefined; descriptive only and never an "
        "input to any category; no magnitude threshold exists"),
    categories=CATEGORIES,
    category_rules=CATEGORY_RULES,
    overall_verdict_rule=(
        "none: each primary symbol has its own category; there is no pooled, averaged, "
        "voted or combined result across symbols"),
    stop_rule_minimum_calendar_months=48,
    stop_rule_minimum_matured_claims=750,
    forced_unlock_calendar_months=72,
    evidence_clock_rule=(
        "evidence_through is the settlement time (bar timestamp plus one daily bar period) "
        "of the latest claim bar, any symbol and any producer, in the frozen input snapshot "
        "whose key the provenance report does not exclude and whose bar settles strictly "
        "after activated_at; none when there is no such claim; it is Level-1 evidence time "
        "and is distinct from the cutoffs C_s; the host wall clock is never authoritative "
        "for E1, F, unlockability, cutoffs, adequacy, categories, populations or results "
        "and is recorded only as unlock metadata"),
    calendar_month_rule=(
        "activated_at converted to UTC; adding n calendar months adds n to the month, "
        "carrying into the year, keeps the time of day, and clamps the day to the last day "
        "of the target month; a threshold is met when evidence_through is at or after that "
        "boundary; with no evidence_through no threshold is met"),
    stop_rule=(
        "unlockable when (E1: evidence_through is at least 48 calendar months after "
        "activated_at AND E2: for EACH primary symbol at least 750 population "
        "trend_alignment claims carry a matured h20 outcome) OR (F: evidence_through is at "
        "least 72 calendar months after activated_at); under F the adequacy rule alone "
        "decides conclusiveness"),
    stop_rule_blindness_rule=(
        "the stop rule and status read only Level-1 metadata: clocks, identities, "
        "fingerprints, artifact and outcome keys, bar timestamps, horizons, spec "
        "fingerprints and provenance status (the evidence clock from claim keys and bar "
        "timestamps alone); never a state, reason code, price, return, sign or aggregate, "
        "and never the host wall clock; BULLISH episode adequacy is not part of the stop "
        "rule"),
    cutoff_rule=(
        "per symbol, C_s is the latest bar timestamp of a population trend_alignment claim "
        "with a matured h20 outcome in the frozen input snapshot (null when none); every "
        "analysis of the symbol, primary and secondary, uses only claims at or before C_s; "
        "later data never alters the v1 result"),
    minimum_bullish_episodes=8,
    adequacy_rule=(
        "after unlock, a primary symbol is adequate when its primary population has at "
        "least 8 BULLISH episodes with matured h20 observations; no BEARISH minimum and no "
        "unconditional-sample minimum apply"),
    episode_rule=(
        "per symbol, the session sequence is the sorted union of every registered claim bar "
        "timestamp (any producer) and every known missed tail from the run log, at or before "
        "C_s and after activation; an episode is a maximal run of consecutive positions that "
        "are population observations in the state with a matured value at the horizon "
        "(Phase R count_episodes membership); a missed session, an excluded or unmatured "
        "claim, or a position without the hypothesis' claim is a non-member and splits; a "
        "weekend or holiday with no bar does not split"),
    degraded_evidence_rule=(
        "every artifact and outcome key the provenance report excludes is removed before "
        "any count, cutoff, population, benchmark, episode, primary or secondary statistic; "
        "an excluded claim position is a non-member of every episode"),
    provenance_rule=(
        "the PROVENANCE_V1 policy must be the live policy; status ok proceeds; status "
        "degraded proceeds only with every excluded key removed; status invalid refuses; "
        "status unknown refuses until provenance can be determined"),
    reserved_interval_start="2025-03-01",
    reserved_interval_rule=(
        "bars from 2025-03-01 up to activated_at (any bar that settles at or before "
        "activated_at) are permanently outside FUTURE_VALIDATION_V1 and never combined with "
        "prospective claims; a separate pre-registered retrospective study may examine them"),
    secondary_analyses=SECONDARY_ANALYSES,
    secondary_isolation_rule=(
        "a primary category is a function only of validity, adequacy, the primary mean and "
        "median deltas and the frozen reference delta signs; no secondary result is an input"),
    out_of_scope=OUT_OF_SCOPE,
    invalidity_conditions=INVALIDITY_CONDITIONS,
    non_invalidating_conditions=NON_INVALIDATING_CONDITIONS,
    early_termination_rule=(
        "none in v1: no operator, host-clock or result-driven early opening exists; if "
        "collection ends permanently before evidence_through reaches 72 calendar months "
        "(and E1 with E2 was never met), FUTURE_VALIDATION_V1 is never opened; analysing such "
        "a terminated collection requires a separately pre-registered amendment or new "
        "validation version"),
    one_open_rule=(
        "status (Level 1) -> explicit run -> write-once unlock -> deterministic computation "
        "-> write-once result; artifacts live under the definition's own fingerprint; a "
        "second unlock or result is never created; a run after an unlock without a result "
        "may only complete that same unlock from its frozen snapshot; a run after a result "
        "never replaces it and refuses unless the result names the unlock by SHA-256 and is "
        "byte-identical to the result re-derived from that unlock's recorded prefixes"),
    snapshot_rule=(
        "the activation manifest, the run log and every ledger file are read under the "
        "collection root's shared lock and frozen by length and SHA-256 in the unlock; "
        "the analysis uses exactly those bytes; completion after a crash re-reads only the "
        "recorded prefixes and refuses if any prefix changed, shrank or vanished"),
    unlock_schema=UNLOCK_SCHEMA,
    result_schema=RESULT_SCHEMA,
    disclosures=DISCLOSURES,
)

#: The pinned identity of FUTURE_VALIDATION_V1. A test rebuilds it independently.
FUTURE_VALIDATION_V1_FINGERPRINT: str = (
    "79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab"
)


__all__ = [
    "FutureValidationDefinitionError",
    "VALIDATION_ID",
    "SCHEMA_VERSION",
    "RUNNER_VERSION",
    "UNLOCK_SCHEMA",
    "RESULT_SCHEMA",
    "CATEGORY_INVALID",
    "CATEGORY_INCONCLUSIVE",
    "CATEGORY_CONSISTENT",
    "CATEGORY_REVERSED",
    "CATEGORY_MIXED",
    "CATEGORIES",
    "CATEGORY_RULES",
    "HypothesisIdentity",
    "ReferenceSource",
    "RetrospectiveReference",
    "SecondaryAnalysis",
    "FutureValidationDefinition",
    "PRIMARY_SYMBOLS",
    "SECONDARY_SYMBOLS",
    "TREND_ALIGNMENT",
    "MOMENTUM_IN_TREND_CONTEXT",
    "OUTCOME_SPEC_FINGERPRINTS",
    "REFERENCE_SOURCE",
    "REFERENCES",
    "PRIMARY_METRICS",
    "DESCRIPTIVE_RATIOS",
    "SECONDARY_ANALYSES",
    "OUT_OF_SCOPE",
    "INVALIDITY_CONDITIONS",
    "NON_INVALIDATING_CONDITIONS",
    "DISCLOSURES",
    "FUTURE_VALIDATION_V1",
    "FUTURE_VALIDATION_V1_FINGERPRINT",
]
