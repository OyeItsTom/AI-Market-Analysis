"""Phase 12E: deterministic descriptive aggregation over one ledger partition.

``summarize_outcomes`` reads one partition through the reader port and
returns coverage groups (every registered artifact, per requested spec) and
completed metric groups (sign counts and plain statistics of stored forward
returns, per evaluation version). These tests pin what is separated, what
is counted, what is refused, and that the output never depends on the order
the reader happened to return records in.

Nothing here reaches a network, reads a clock, or touches the repository's
``data/outcomes``; the real-ledger tests run under ``tmp_path``.
"""

from __future__ import annotations

import dataclasses
import random
import statistics
from datetime import timedelta

import pytest

import src.outcomes.models as models_module
from src.assessments.assessment import AssessmentState
from src.data.series import PriceBasis
from src.evaluation import OutcomeSpec, PriceField
from src.outcomes import (
    EVALUATION_VERSION,
    MIN_SUMMARY_SAMPLES,
    OVERLAP_CAVEAT,
    ArtifactKind,
    JsonlOutcomeLedger,
    LedgerPartition,
    OutcomeCoverageGroup,
    OutcomeMetricGroup,
    OutcomeRecord,
    OutcomeSummary,
    OutcomeSummaryError,
    ProducerKey,
    bars_fingerprint,
    evaluate_artifact,
    summarize_outcomes,
)
from src.outcomes.summary import CoverageGroupKey, MetricGroupKey
from src.strategies.research import ReasonCode, ResearchState
from tests.test_outcomes_tracking import (
    LATER,
    assessment_artifact,
    observation_artifact,
    series,
)

H1 = OutcomeSpec(horizon_bars=1)
H3 = OutcomeSpec(horizon_bars=3)
#: Same horizon as H1, different semantics, different fingerprint.
H1_OPEN = OutcomeSpec(horizon_bars=1, future_field=PriceField.OPEN)
SPECS = (H1, H3)

S = series(40)
PARTITION = LedgerPartition(symbol=S.symbol, interval=S.interval, basis=S.basis)


# -- fixtures ------------------------------------------------------------------------


class FakeReader:
    """Hands back whatever it was given, and counts how often it was asked."""

    def __init__(self, artifacts=(), outcomes=()):
        self.artifacts = list(artifacts)
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def iter_artifacts(self, partition):
        self.calls.append("iter_artifacts")
        return iter(list(self.artifacts))

    def iter_outcomes(self, partition):
        self.calls.append("iter_outcomes")
        return iter(list(self.outcomes))

    def get_artifact(self, partition, key):  # pragma: no cover - never called
        raise AssertionError("summary must not call get_artifact")

    def get_outcome(self, partition, key):  # pragma: no cover - never called
        raise AssertionError("summary must not call get_outcome")

    def contains_artifact(self, partition, key):  # pragma: no cover - never called
        raise AssertionError("summary must not call contains_artifact")

    def contains_outcome(self, partition, key):  # pragma: no cover - never called
        raise AssertionError("summary must not call contains_outcome")


def obs(index, **over):
    return observation_artifact(S, index, **over)


def asmt(index, **over):
    return assessment_artifact(S, index, **over)


def outcome(artifact, spec=H1, *, future_price=101.0, version=EVALUATION_VERSION, s=S,
            forward_return=None):
    """A completed record for ``artifact`` under ``spec`` with a chosen future
    price against a reference of 100.0, so the stored forward return is exactly
    ``future_price / 100.0 - 1`` (or an explicitly supplied equal value)."""
    position = s.timestamps.index(artifact.timestamp)
    reference = s[position + 1]
    future = s[position + spec.horizon_bars]
    reference_price = 100.0
    return OutcomeRecord(
        artifact=artifact,
        spec_fingerprint=spec.fingerprint,
        horizon_bars=spec.horizon_bars,
        evaluation_version=version,
        evaluated_at=LATER,
        consumed_bars_fingerprint=bars_fingerprint(
            s.bars[position + 1: position + 1 + spec.horizon_bars]),
        reference_timestamp=reference.timestamp,
        reference_price=reference_price,
        future_timestamp=future.timestamp,
        future_price=future_price,
        forward_return=(future_price / reference_price - 1.0
                        if forward_return is None else forward_return),
    )


def summarize(artifacts, outcomes=(), specs=SPECS, partition=PARTITION):
    return summarize_outcomes(FakeReader(artifacts, outcomes), partition, specs)


def coverage(summary, spec, producer, state, source="yfinance"):
    key = CoverageGroupKey(spec_fingerprint=spec.fingerprint, producer=producer,
                           state=state, source=source)
    matches = [g for g in summary.coverage_groups if g.key == key]
    assert len(matches) == 1, [g.key for g in summary.coverage_groups]
    return matches[0]


def metric(summary, spec, producer, state, source="yfinance", version=EVALUATION_VERSION):
    key = MetricGroupKey(
        coverage=CoverageGroupKey(spec_fingerprint=spec.fingerprint, producer=producer,
                                  state=state, source=source),
        evaluation_version=version,
    )
    matches = [g for g in summary.metric_groups if g.key == key]
    assert len(matches) == 1, [g.key for g in summary.metric_groups]
    return matches[0]


TREND = ProducerKey(kind=ArtifactKind.OBSERVATION, hypothesis_id="trend_alignment",
                    hypothesis_version=1, hypothesis_fingerprint="0011223344556677")
POLICY = ProducerKey(kind=ArtifactKind.ASSESSMENT, policy_fingerprint="fedcba9876543210")


# -- the basic aggregation ------------------------------------------------------------


class TestBasicAggregation:
    RETURNS = (98.0, 100.0, 101.0, 103.0)   # -0.02, 0.00, +0.01, +0.03

    def build(self):
        artifacts = [obs(i) for i in range(4)]
        outcomes = [outcome(a, H1, future_price=p) for a, p in zip(artifacts, self.RETURNS)]
        return artifacts, outcomes

    def test_counts_and_descriptive_values_are_exact(self):
        artifacts, outcomes = self.build()
        summary = summarize(artifacts, outcomes)
        group = metric(summary, H1, TREND, ResearchState.BULLISH)
        returns = [o.forward_return for o in outcomes]
        assert group.sample_count == 4
        assert (group.negative_count, group.zero_count, group.positive_count) == (1, 1, 2)
        assert group.mean_forward_return == statistics.fmean(returns)
        assert group.median_forward_return == statistics.median(returns)
        assert group.min_forward_return == min(returns) == returns[0]
        assert group.max_forward_return == max(returns) == returns[3]
        assert group.sample_floor_met is False
        assert group.horizon_bars == 1

    def test_the_returns_are_read_as_stored_never_recomputed(self):
        artifacts, outcomes = self.build()
        summary = summarize(artifacts, outcomes)
        group = metric(summary, H1, TREND, ResearchState.BULLISH)
        assert group.min_forward_return == outcomes[0].forward_return
        assert group.max_forward_return == outcomes[3].forward_return

    def test_coverage_for_the_same_group(self):
        artifacts, outcomes = self.build()
        summary = summarize(artifacts, outcomes)
        group = coverage(summary, H1, TREND, ResearchState.BULLISH)
        assert (group.artifacts_registered, group.artifacts_evaluable, group.artifacts_completed) == (4, 4, 4)
        assert group.raw_coverage_fraction == group.evaluable_coverage_fraction == 1.0
        assert group.first_artifact_timestamp == artifacts[0].timestamp
        assert group.last_artifact_timestamp == artifacts[3].timestamp
        # The other requested spec has the same registered claims and nothing completed.
        other = coverage(summary, H3, TREND, ResearchState.BULLISH)
        assert (other.artifacts_registered, other.artifacts_completed) == (4, 0)
        assert other.raw_coverage_fraction == 0.0
        assert summary.metric_groups_for(other.key) == ()

    def test_operational_totals_are_derived(self):
        artifacts, outcomes = self.build()
        summary = summarize(artifacts, outcomes)
        assert summary.artifacts_registered == 4          # each artifact counted once
        assert summary.outcomes_completed == 4
        assert summary.specs == SPECS
        assert summary.partition == PARTITION

    def test_the_reader_is_asked_exactly_once_for_each_iterator(self):
        artifacts, outcomes = self.build()
        reader = FakeReader(artifacts, outcomes)
        summarize_outcomes(reader, PARTITION, SPECS)
        assert reader.calls == ["iter_artifacts", "iter_outcomes"]


# -- separation ------------------------------------------------------------------------


class TestSeparation:
    def test_producers_sharing_one_market_return_are_never_pooled(self):
        a = obs(0)
        b = obs(0, hypothesis_id="trend_crossover", hypothesis_fingerprint="8899aabbccddeeff")
        c = asmt(0)
        outcomes = [outcome(x, H1, future_price=102.0) for x in (a, b, c)]
        summary = summarize([a, b, c], outcomes, specs=(H1,))
        assert len(summary.coverage_groups) == 3
        assert len(summary.metric_groups) == 3
        for group in summary.metric_groups:
            assert group.sample_count == 1
        producers = {g.key.producer for g in summary.metric_groups}
        assert producers == {TREND, ProducerKey.of_artifact(b), POLICY}

    def test_states_are_separate(self):
        bull = obs(0, state=ResearchState.BULLISH)
        bear = obs(1, state=ResearchState.BEARISH)
        summary = summarize([bull, bear], [outcome(bull), outcome(bear)], specs=(H1,))
        assert {g.key.state for g in summary.metric_groups} == {
            ResearchState.BULLISH, ResearchState.BEARISH}
        assert all(g.sample_count == 1 for g in summary.metric_groups)

    def test_observation_and_assessment_bullish_are_different_groups(self):
        o, a = obs(0), asmt(0)
        summary = summarize([o, a], [outcome(o), outcome(a)], specs=(H1,))
        states = [(g.key.producer.kind, type(g.key.state)) for g in summary.metric_groups]
        assert sorted(states, key=str) == sorted(
            [(ArtifactKind.OBSERVATION, ResearchState), (ArtifactKind.ASSESSMENT, AssessmentState)],
            key=str)

    def test_specs_are_separate_even_at_one_horizon(self):
        a = obs(0)
        summary = summarize([a], [outcome(a, H1), outcome(a, H1_OPEN)], specs=(H1, H1_OPEN))
        assert [g.key.spec_fingerprint for g in summary.metric_groups] == [
            H1.fingerprint, H1_OPEN.fingerprint]
        assert all(g.horizon_bars == 1 and g.sample_count == 1 for g in summary.metric_groups)

    def test_a_different_horizon_is_a_different_spec(self):
        a = obs(0)
        summary = summarize([a], [outcome(a, H1), outcome(a, H3)])
        assert [(g.key.spec_fingerprint, g.horizon_bars) for g in summary.metric_groups] == [
            (H1.fingerprint, 1), (H3.fingerprint, 3)]

    def test_evaluation_versions_are_separate_metric_groups(self, monkeypatch):
        monkeypatch.setattr(models_module, "SUPPORTED_EVALUATION_VERSIONS", frozenset({1, 2}))
        a, b = obs(0), obs(1)
        outcomes = [outcome(a, version=1), outcome(b, version=2), outcome(a, version=2)]
        summary = summarize([a, b], outcomes, specs=(H1,))
        versions = [(g.key.evaluation_version, g.sample_count) for g in summary.metric_groups]
        assert versions == [(1, 1), (2, 2)]
        # One coverage group, no version. Completion counts *artifacts* with an
        # outcome, so a second version never pushes coverage past 1.
        group = coverage(summary, H1, TREND, ResearchState.BULLISH)
        assert (group.artifacts_registered, group.artifacts_completed) == (2, 2)
        assert group.raw_coverage_fraction == 1.0
        assert summary.metric_groups_for(group.key) == summary.metric_groups
        # Each version carries its own coverage against the same denominators.
        v1, v2 = summary.metric_groups
        assert (v1.artifacts_registered, v1.sample_count, v1.raw_coverage_fraction) == (2, 1, 0.5)
        assert (v2.artifacts_registered, v2.sample_count, v2.raw_coverage_fraction) == (2, 2, 1.0)
        assert summary.outcomes_completed == 3           # records, every version

    def test_a_partial_reevaluation_never_borrows_the_old_versions_coverage(self, monkeypatch):
        """10 evaluable claims, 10 measured under v1, 2 re-measured under v2:
        the coverage group says 10/10 have *some* outcome, v1 says 10/10,
        and v2 says 2/10 -- a reader of the v2 group cannot mistake it for
        a complete sample."""
        monkeypatch.setattr(models_module, "SUPPORTED_EVALUATION_VERSIONS", frozenset({1, 2}))
        artifacts = [obs(i) for i in range(10)]
        outcomes = [outcome(a, version=1) for a in artifacts]
        outcomes += [outcome(a, version=2, future_price=99.0) for a in artifacts[3:5]]
        summary = summarize(artifacts, outcomes, specs=(H1,))
        cov = coverage(summary, H1, TREND, ResearchState.BULLISH)
        assert (cov.artifacts_registered, cov.artifacts_evaluable, cov.artifacts_completed) == (10, 10, 10)
        assert cov.raw_coverage_fraction == 1.0
        v1 = metric(summary, H1, TREND, ResearchState.BULLISH, version=1)
        v2 = metric(summary, H1, TREND, ResearchState.BULLISH, version=2)
        assert (v1.sample_count, v1.raw_coverage_fraction, v1.evaluable_coverage_fraction) == (10, 1.0, 1.0)
        assert (v2.sample_count, v2.raw_coverage_fraction, v2.evaluable_coverage_fraction) == (2, 0.2, 0.2)
        assert v2.sample_floor_met is False
        # The span of each metric group is the span of *its* measured artifacts.
        assert (cov.first_artifact_timestamp, cov.last_artifact_timestamp) == (
            artifacts[0].timestamp, artifacts[9].timestamp)
        assert (v1.first_artifact_timestamp, v1.last_artifact_timestamp) == (
            artifacts[0].timestamp, artifacts[9].timestamp)
        assert (v2.first_artifact_timestamp, v2.last_artifact_timestamp) == (
            artifacts[3].timestamp, artifacts[4].timestamp)
        assert summary.outcomes_completed == 12 and summary.artifacts_registered == 10

    def test_sources_are_separate(self):
        a = obs(0)
        b = obs(1, source="other")
        summary = summarize([a, b], [outcome(a), outcome(b)], specs=(H1,))
        assert [g.key.source for g in summary.metric_groups] == ["other", "yfinance"]
        assert [g.key.source for g in summary.coverage_groups] == ["other", "yfinance"]
        assert all(g.sample_count == 1 for g in summary.metric_groups)

    def test_there_is_no_figure_across_groups(self):
        for cls in (OutcomeSummary, OutcomeMetricGroup, OutcomeCoverageGroup):
            names = {f.name for f in dataclasses.fields(cls)} | {
                n for n in dir(cls) if not n.startswith("_")}
            for word in ("rate", "score", "rank", "best", "overall", "accuracy", "sharpe",
                         "alpha", "beta", "confidence", "pvalue", "significan", "win", "hit"):
                assert not any(word in n.lower() for n in names), (cls.__name__, word)


# -- coverage ----------------------------------------------------------------------------


class TestCoverage:
    def test_a_registered_claim_with_no_outcome_still_has_a_group(self):
        a = obs(0)
        summary = summarize([a], [], specs=(H1,))
        group = coverage(summary, H1, TREND, ResearchState.BULLISH)
        assert (group.artifacts_registered, group.artifacts_evaluable, group.artifacts_completed) == (1, 1, 0)
        assert group.raw_coverage_fraction == 0.0
        assert group.evaluable_coverage_fraction == 0.0
        assert summary.metric_groups == ()          # no version to fabricate

    def test_an_ineligible_artifact_is_registered_but_not_evaluable(self):
        a = obs(0, state=ResearchState.INSUFFICIENT_DATA,
                reason_codes=(ReasonCode.WARMUP_INCOMPLETE,))
        summary = summarize([a], [], specs=(H1,))
        group = coverage(summary, H1, TREND, ResearchState.INSUFFICIENT_DATA)
        assert (group.artifacts_registered, group.artifacts_evaluable, group.artifacts_completed) == (1, 0, 0)
        assert group.raw_coverage_fraction == 0.0
        assert group.evaluable_coverage_fraction is None      # no denominator, never NaN

    def test_partial_coverage(self):
        artifacts = [obs(i) for i in range(10)]
        outcomes = [outcome(a) for a in artifacts[:6]]
        group = coverage(summarize(artifacts, outcomes, specs=(H1,)), H1, TREND, ResearchState.BULLISH)
        assert (group.artifacts_registered, group.artifacts_evaluable, group.artifacts_completed) == (10, 10, 6)
        assert group.raw_coverage_fraction == 0.6
        assert group.evaluable_coverage_fraction == 0.6

    def test_mixed_ineligible_coverage_is_honest_about_both_denominators(self):
        evaluable = [obs(i) for i in range(8)]
        ineligible = [obs(i, state=ResearchState.INSUFFICIENT_DATA,
                          reason_codes=(ReasonCode.WARMUP_INCOMPLETE,)) for i in (8, 9)]
        outcomes = [outcome(a) for a in evaluable[:6]]
        summary = summarize(evaluable + ineligible, outcomes, specs=(H1,))
        bull = coverage(summary, H1, TREND, ResearchState.BULLISH)
        insufficient = coverage(summary, H1, TREND, ResearchState.INSUFFICIENT_DATA)
        registered = bull.artifacts_registered + insufficient.artifacts_registered
        evaluable_count = bull.artifacts_evaluable + insufficient.artifacts_evaluable
        completed = bull.artifacts_completed + insufficient.artifacts_completed
        assert (registered, evaluable_count, completed) == (10, 8, 6)
        assert completed / registered == 0.6
        assert completed / evaluable_count == 0.75
        assert bull.evaluable_coverage_fraction == 0.75
        assert insufficient.evaluable_coverage_fraction is None
        assert summary.artifacts_registered == 10 and summary.outcomes_completed == 6

    def test_coverage_never_infers_why_an_outcome_is_missing(self):
        names = {f.name for f in dataclasses.fields(OutcomeCoverageGroup)} | set(dir(OutcomeCoverageGroup))
        for word in ("pending", "refused", "out_of_window", "reason"):
            assert not any(word in n.lower() for n in names), word


# -- reader defence ----------------------------------------------------------------------


class TestReaderDefence:
    def test_duplicate_artifact_raises(self):
        a = obs(0)
        with pytest.raises(OutcomeSummaryError, match="twice"):
            summarize([a, a])

    def test_duplicate_outcome_raises(self):
        a = obs(0)
        o = outcome(a)
        with pytest.raises(OutcomeSummaryError, match="twice"):
            summarize([a], [o, o])

    def test_orphan_outcome_raises(self):
        a, b = obs(0), obs(1)
        with pytest.raises(OutcomeSummaryError, match="did not return"):
            summarize([a], [outcome(b)])

    def test_embedded_artifact_that_differs_from_the_registered_one_raises(self):
        registered = obs(0)
        embedded = dataclasses.replace(registered, recorded_at=registered.recorded_at + timedelta(hours=1))
        assert embedded.artifact_key == registered.artifact_key
        with pytest.raises(OutcomeSummaryError, match="differs from the registered"):
            summarize([registered], [outcome(embedded)])

    @pytest.mark.parametrize("foreign", [
        series(8, symbol="MSFT"), series(8, interval="1wk"), series(8, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
    ], ids=["symbol", "interval", "basis"])
    def test_a_foreign_artifact_raises(self, foreign):
        with pytest.raises(OutcomeSummaryError, match="belongs to"):
            summarize([observation_artifact(foreign, 0)], [], specs=(H1,))

    @pytest.mark.parametrize("foreign", [
        series(8, symbol="MSFT"), series(8, interval="1wk"), series(8, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
    ], ids=["symbol", "interval", "basis"])
    def test_a_foreign_outcome_raises(self, foreign):
        a = observation_artifact(foreign, 0)
        with pytest.raises(OutcomeSummaryError, match="belongs to"):
            summarize([obs(0)], [outcome(a, s=foreign)], specs=(H1,))

    def test_a_non_artifact_record_raises(self):
        with pytest.raises(OutcomeSummaryError, match="not a TrackedArtifact"):
            summarize(["not an artifact"])

    def test_a_non_outcome_record_raises(self):
        with pytest.raises(OutcomeSummaryError, match="not an OutcomeRecord"):
            summarize([obs(0)], ["not an outcome"])

    def test_a_horizon_contradiction_under_a_requested_spec_raises(self):
        a = obs(0)
        wrong = dataclasses.replace(outcome(a, H3), spec_fingerprint=H1.fingerprint)
        assert wrong.horizon_bars == 3
        with pytest.raises(OutcomeSummaryError, match="horizon"):
            summarize([a], [wrong], specs=(H1,))


# -- request validation ------------------------------------------------------------------


class TestRequest:
    @pytest.mark.parametrize("specs, message", [
        ((), "must not be empty"),
        ("h1", "sequence"),
        ((H1, "x"), "OutcomeSpec"),
        ((H1, H1), "duplicate"),
        ((OutcomeSpec(horizon_bars=1, required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),), "requires"),
    ], ids=["empty", "string", "type", "duplicate", "basis"])
    def test_bad_specs_are_refused(self, specs, message):
        with pytest.raises(OutcomeSummaryError, match=message):
            summarize([obs(0)], [], specs=specs)

    def test_a_bad_partition_is_refused(self):
        with pytest.raises(OutcomeSummaryError, match="LedgerPartition"):
            summarize_outcomes(FakeReader(), "AAPL/1d/raw", SPECS)

    def test_caller_spec_order_is_kept(self):
        summary = summarize([obs(0)], [], specs=(H3, H1))
        assert summary.specs == (H3, H1)
        assert [g.key.spec_fingerprint for g in summary.coverage_groups] == [
            H3.fingerprint, H1.fingerprint]

    def test_unrequested_durable_specs_are_ignored_entirely(self):
        a = obs(0)
        with_both = summarize([a], [outcome(a, H1), outcome(a, H3)], specs=(H1,))
        only_h1 = summarize([a], [outcome(a, H1)], specs=(H1,))
        assert with_both == only_h1
        assert {g.key.spec_fingerprint for g in with_both.coverage_groups} == {H1.fingerprint}
        assert coverage(with_both, H1, TREND, ResearchState.BULLISH).artifacts_completed == 1

    def test_an_unrequested_spec_is_still_checked_for_reader_integrity(self):
        a = obs(0)
        stray = outcome(a, H3)
        with pytest.raises(OutcomeSummaryError, match="twice"):
            summarize([a], [stray, stray], specs=(H1,))


# -- determinism -------------------------------------------------------------------------


class TestDeterminism:
    def build(self):
        artifacts = [obs(i) for i in range(6)]
        artifacts += [obs(i, state=ResearchState.BEARISH) for i in range(6, 9)]
        artifacts += [obs(i, hypothesis_id="trend_crossover",
                          hypothesis_fingerprint="8899aabbccddeeff") for i in range(9, 12)]
        artifacts += [asmt(i) for i in range(12, 15)]
        artifacts += [obs(i, source="other") for i in range(15, 18)]
        outcomes = [outcome(a, H1, future_price=100.0 + (i % 5) - 2.0)
                    for i, a in enumerate(artifacts) if i % 2 == 0]
        outcomes += [outcome(a, H3, future_price=99.0) for a in artifacts[:4]]
        return artifacts, outcomes

    def test_shuffled_input_yields_the_same_summary(self):
        artifacts, outcomes = self.build()
        reference = summarize(artifacts, outcomes)
        for seed in range(5):
            rng = random.Random(seed)
            shuffled_artifacts = list(artifacts); rng.shuffle(shuffled_artifacts)
            shuffled_outcomes = list(outcomes); rng.shuffle(shuffled_outcomes)
            assert summarize(shuffled_artifacts, shuffled_outcomes) == reference
        reversed_summary = summarize(list(reversed(artifacts)), list(reversed(outcomes)))
        assert reversed_summary == reference

    def test_groups_are_ordered_by_spec_kind_producer_state_source_version(self):
        artifacts, outcomes = self.build()
        summary = summarize(artifacts, outcomes)
        keys = [(summary.specs.index(next(s for s in summary.specs
                                           if s.fingerprint == g.key.spec_fingerprint)),
                 g.key.sort_key) for g in summary.coverage_groups]
        assert keys == sorted(keys)
        metric_keys = [(summary.specs.index(next(s for s in summary.specs
                                                  if s.fingerprint == g.key.spec_fingerprint)),
                        g.key.sort_key) for g in summary.metric_groups]
        assert metric_keys == sorted(metric_keys)
        # Observations precede assessments within a spec.
        kinds = [g.key.producer.kind for g in summary.coverage_groups
                 if g.key.spec_fingerprint == H1.fingerprint]
        assert kinds == sorted(kinds, key=lambda k: 0 if k is ArtifactKind.OBSERVATION else 1)


# -- thresholds and floats ---------------------------------------------------------------


class TestThresholdsAndFloats:
    @pytest.mark.parametrize("count, sufficient", [(19, False), (20, True)])
    def test_the_descriptive_sample_floor_flag(self, count, sufficient):
        artifacts = [obs(i) for i in range(count)]
        outcomes = [outcome(a, future_price=101.0) for a in artifacts]
        group = metric(summarize(artifacts, outcomes, specs=(H1,)), H1, TREND, ResearchState.BULLISH)
        assert group.sample_count == count
        assert group.sample_floor_met is sufficient
        assert group.mean_forward_return == outcomes[0].forward_return
        assert MIN_SUMMARY_SAMPLES == 20

    def test_negative_zero_is_a_zero(self):
        a, b = obs(0), obs(1)
        plus = outcome(a, future_price=100.0)                        # 0.0
        minus = outcome(b, future_price=100.0, forward_return=-0.0)  # -0.0, accepted as equal
        assert str(minus.forward_return) == "-0.0"
        group = metric(summarize([a, b], [plus, minus], specs=(H1,)), H1, TREND, ResearchState.BULLISH)
        assert (group.zero_count, group.negative_count, group.positive_count) == (2, 0, 0)
        assert group.mean_forward_return == 0.0

    def test_values_are_raw_finite_floats(self):
        artifacts = [obs(i) for i in range(3)]
        outcomes = [outcome(a, future_price=p) for a, p in zip(artifacts, (97.0, 100.5, 104.25))]
        group = metric(summarize(artifacts, outcomes, specs=(H1,)), H1, TREND, ResearchState.BULLISH)
        for value in (group.mean_forward_return, group.median_forward_return,
                      group.min_forward_return, group.max_forward_return):
            assert isinstance(value, float) and value == value and abs(value) != float("inf")


# -- empty and models --------------------------------------------------------------------


class TestEmptyAndModels:
    def test_an_empty_partition_is_a_valid_empty_summary(self):
        summary = summarize([], [])
        assert summary.partition == PARTITION
        assert summary.specs == SPECS
        assert summary.coverage_groups == () and summary.metric_groups == ()
        assert summary.artifacts_registered == 0 and summary.outcomes_completed == 0

    def test_the_overlap_caveat_travels_with_the_type(self):
        summary = summarize([], [])
        assert summary.overlap_caveat == OVERLAP_CAVEAT == OutcomeSummary.overlap_caveat
        assert "overlapping forward windows" in OVERLAP_CAVEAT
        assert "not independent statistical trials" in OVERLAP_CAVEAT

    def test_results_are_immutable(self):
        a = obs(0)
        summary = summarize([a], [outcome(a)], specs=(H1,))
        for target in (summary, summary.coverage_groups[0], summary.metric_groups[0],
                       summary.metric_groups[0].key, TREND):
            with pytest.raises(dataclasses.FrozenInstanceError):
                target.horizon_bars = 99  # type: ignore[misc]

    def test_producer_keys_are_structured_and_kind_checked(self):
        assert ProducerKey.of_artifact(obs(0)) == TREND
        assert ProducerKey.of_artifact(asmt(0)) == POLICY
        with pytest.raises(OutcomeSummaryError):
            ProducerKey(kind=ArtifactKind.OBSERVATION, policy_fingerprint="fedcba9876543210")
        with pytest.raises(OutcomeSummaryError):
            ProducerKey(kind=ArtifactKind.ASSESSMENT, hypothesis_id="x", hypothesis_version=1,
                        hypothesis_fingerprint="y")
        assert TREND.label == "trend_alignment@v1#0011223344556677"
        assert POLICY.label == "policy#fedcba9876543210"

    def test_a_state_from_the_wrong_vocabulary_is_refused_in_a_key(self):
        with pytest.raises(OutcomeSummaryError, match="ResearchState"):
            CoverageGroupKey(spec_fingerprint=H1.fingerprint, producer=TREND,
                             state=AssessmentState.BULLISH, source="yfinance")
        with pytest.raises(OutcomeSummaryError, match="AssessmentState"):
            CoverageGroupKey(spec_fingerprint=H1.fingerprint, producer=POLICY,
                             state=ResearchState.BULLISH, source="yfinance")
        with pytest.raises(OutcomeSummaryError, match="CoverageGroupKey"):
            MetricGroupKey(coverage="not a key", evaluation_version=1)
        with pytest.raises(OutcomeSummaryError, match="evaluation_version"):
            MetricGroupKey(coverage=CoverageGroupKey(spec_fingerprint=H1.fingerprint,
                                                     producer=TREND, state=ResearchState.BULLISH,
                                                     source="yfinance"), evaluation_version=0)

    def test_group_invariants_are_enforced(self):
        a = obs(0)
        summary = summarize([a], [outcome(a)], specs=(H1,))
        cov, met = summary.coverage_groups[0], summary.metric_groups[0]
        with pytest.raises(OutcomeSummaryError, match="exceed"):
            dataclasses.replace(cov, artifacts_completed=2)
        with pytest.raises(OutcomeSummaryError, match="exceed"):
            dataclasses.replace(cov, artifacts_evaluable=2)
        with pytest.raises(OutcomeSummaryError, match="exceed"):
            dataclasses.replace(met, artifacts_evaluable=0)
        with pytest.raises(OutcomeSummaryError, match="account"):
            dataclasses.replace(met, positive_count=2)
        with pytest.raises(OutcomeSummaryError, match="finite"):
            dataclasses.replace(met, mean_forward_return=float("nan"))
        with pytest.raises(OutcomeSummaryError, match="completed outcomes"):
            dataclasses.replace(met, sample_count=0, positive_count=0)

    def test_metric_groups_for_a_coverage_key(self):
        a = obs(0)
        summary = summarize([a], [outcome(a)], specs=(H1,))
        cov = summary.coverage_groups[0]
        assert summary.metric_groups_for(cov.key) == (summary.metric_groups[0],)
        with pytest.raises(OutcomeSummaryError):
            summary.metric_groups_for("not a key")


# -- the real ledger: 12C -> 12E ----------------------------------------------------------


class TestRealLedger:
    def test_a_ledger_written_by_the_store_summarizes_exactly(self, tmp_path):
        writer = JsonlOutcomeLedger(tmp_path / "outcomes")
        artifacts = [obs(i) for i in range(5)] + [asmt(i) for i in range(5)]
        for artifact in artifacts:
            assert writer.register_artifact(artifact).written
        written = []
        for artifact in artifacts:
            for spec in SPECS:
                tracked = evaluate_artifact(artifact, S, spec, evaluated_at=LATER)
                assert tracked.is_evaluated
                assert writer.append_outcome(tracked.outcome).written
                written.append(tracked.outcome)

        reader = JsonlOutcomeLedger(tmp_path / "outcomes")     # a fresh instance
        summary = summarize_outcomes(reader, PARTITION, SPECS)

        assert summary.artifacts_registered == 10 and summary.outcomes_completed == 20
        assert [(g.key.spec_fingerprint, g.key.producer, g.key.state) for g in summary.coverage_groups] == [
            (H1.fingerprint, TREND, ResearchState.BULLISH),
            (H1.fingerprint, POLICY, AssessmentState.BULLISH),
            (H3.fingerprint, TREND, ResearchState.BULLISH),
            (H3.fingerprint, POLICY, AssessmentState.BULLISH),
        ]
        for group in summary.coverage_groups:
            assert (group.artifacts_registered, group.artifacts_evaluable, group.artifacts_completed) == (5, 5, 5)
            assert group.raw_coverage_fraction == 1.0
        assert len(summary.metric_groups) == 4
        for group in summary.metric_groups:
            expected = [o.forward_return for o in written
                        if o.spec_fingerprint == group.key.spec_fingerprint
                        and ProducerKey.of_artifact(o.artifact) == group.key.producer]
            assert group.sample_count == 5
            assert group.mean_forward_return == statistics.fmean(expected)
            assert group.median_forward_return == statistics.median(expected)
            assert group.key.evaluation_version == EVALUATION_VERSION
            assert group.sample_floor_met is False
        # Phase 4's numbers, read back through the store, are the ones summarised.
        trend_h1 = metric(summary, H1, TREND, ResearchState.BULLISH)
        assert trend_h1.min_forward_return == min(
            o.forward_return for o in written[:10:2])

    def test_an_empty_store_root_is_an_empty_summary(self, tmp_path):
        reader = JsonlOutcomeLedger(tmp_path / "never-written")
        summary = summarize_outcomes(reader, PARTITION, SPECS)
        assert summary.coverage_groups == () and summary.metric_groups == ()
        assert not (tmp_path / "never-written").exists()


# -- the orchestration: 12D -> 12E --------------------------------------------------------


class TestThroughRefresh:
    def test_two_refreshes_then_a_summary(self, tmp_path):
        from src.application.outcomes import build_outcome_ledger
        from tests.test_application_outcomes import SPECS as REFRESH_SPECS, at, refresh, snapshot
        from tests.test_application_outcomes import partition_of

        ledger = build_outcome_ledger(tmp_path / "outcomes")
        first = snapshot(80, now=at(0))
        refresh(first, ledger)
        second = snapshot(82, now=at(2))
        result = refresh(second, ledger)
        assert result.outcomes_written == 4

        summary = summarize_outcomes(ledger, partition_of(second), REFRESH_SPECS)
        h1, h3 = REFRESH_SPECS
        assert summary.artifacts_registered == 8
        assert summary.outcomes_completed == 4
        by_spec = {}
        for group in summary.coverage_groups:
            totals = by_spec.setdefault(group.key.spec_fingerprint, [0, 0])
            totals[0] += group.artifacts_registered
            totals[1] += group.artifacts_completed
        assert by_spec == {h1.fingerprint: [8, 4], h3.fingerprint: [8, 0]}
        # A third refresh on the same bars registers nothing new and measures
        # nothing twice: the summary is unchanged, so repetition cannot inflate n.
        refresh(snapshot(82, now=at(3)), ledger)
        assert summarize_outcomes(ledger, partition_of(second), REFRESH_SPECS) == summary
        assert {g.key.spec_fingerprint for g in summary.metric_groups} == {h1.fingerprint}
        assert sum(g.sample_count for g in summary.metric_groups) == 4
        assert all(g.horizon_bars == 1 and g.key.evaluation_version == EVALUATION_VERSION
                   for g in summary.metric_groups)
        # Every producer of the snapshot has its own group; nothing is pooled.
        producers = {g.key.producer for g in summary.metric_groups}
        assert len(producers) == 4
        assert {p.kind for p in producers} == {ArtifactKind.OBSERVATION, ArtifactKind.ASSESSMENT}
