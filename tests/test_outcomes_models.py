"""Phase 12A: the tracked-artifact and outcome-record models.

A tracked artifact is *what was claimed* at registration; an outcome record
is *what the market did afterwards*, attached to that claim. Both are frozen
and defend their own invariants, because a public record that can be built
directly must not be constructible into a state its producer could never
reach.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.assessments import (
    AssessmentCounts,
    AssessmentInput,
    AssessmentReasonCode,
    AssessmentState,
    ResearchAssessment,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.outcomes import (
    EVALUATION_VERSION,
    SUPPORTED_EVALUATION_VERSIONS,
    ArtifactKind,
    ArtifactOrigin,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
    OutcomeTrackingError,
    TrackedArtifact,
    outcome_key,
)
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState

UTC = timezone.utc
T0 = datetime(2024, 1, 5, tzinfo=UTC)          # the claimed bar's open
CUTOFF = T0                                     # latest settled bar open
RECORDED = T0 + timedelta(days=1, hours=2)      # registration clock
EVALUATED_AT = RECORDED + timedelta(days=30)

FP64 = "a" * 64
FP64_B = "b" * 64
SPEC_FP = "0123456789abcdef"
POLICY_FP = "fedcba9876543210"


def observation(**overrides) -> ResearchObservation:
    fields = dict(
        hypothesis_id="trend_alignment",
        version=1,
        fingerprint="0011223344556677",
        symbol="AAPL",
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        timestamp=T0,
        state=ResearchState.BULLISH,
        evidence={"sma(period=20)": 1.0},
        reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
    )
    fields.update(overrides)
    return ResearchObservation(**fields)


def assessment(**overrides) -> ResearchAssessment:
    inputs = (
        AssessmentInput("trend_alignment", 1, "0011223344556677", ResearchState.BULLISH),
        AssessmentInput("trend_crossover", 2, "8899aabbccddeeff", ResearchState.NEUTRAL),
    )
    fields = dict(
        policy_fingerprint=POLICY_FP,
        symbol="AAPL",
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        timestamp=T0,
        assessment_as_of=T0 + timedelta(days=1),
        state=AssessmentState.BULLISH,
        inputs=inputs,
        counts=AssessmentCounts(bullish=1, bearish=0, neutral=1, insufficient=0),
        reason_codes=(AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL,),
    )
    fields.update(overrides)
    return ResearchAssessment(**fields)


def obs_artifact(**overrides) -> ObservationArtifact:
    fields = dict(
        symbol="AAPL",
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        timestamp=T0,
        state=ResearchState.BULLISH,
        reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
        source="yfinance",
        data_cutoff=CUTOFF,
        recorded_at=RECORDED,
        observation_bar_fingerprint=FP64,
        origin=ArtifactOrigin.SNAPSHOT,
        hypothesis_id="trend_alignment",
        hypothesis_version=1,
        hypothesis_fingerprint="0011223344556677",
    )
    fields.update(overrides)
    return ObservationArtifact(**fields)


def asmt_artifact(**overrides) -> AssessmentArtifact:
    fields = dict(
        symbol="AAPL",
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        timestamp=T0,
        state=AssessmentState.BULLISH,
        reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,),
        source="yfinance",
        data_cutoff=CUTOFF,
        recorded_at=RECORDED,
        observation_bar_fingerprint=FP64,
        origin=ArtifactOrigin.SNAPSHOT,
        policy_fingerprint=POLICY_FP,
    )
    fields.update(overrides)
    return AssessmentArtifact(**fields)


def record(artifact=None, **overrides) -> OutcomeRecord:
    fields = dict(
        artifact=artifact if artifact is not None else obs_artifact(),
        spec_fingerprint=SPEC_FP,
        horizon_bars=5,
        evaluation_version=EVALUATION_VERSION,
        evaluated_at=EVALUATED_AT,
        consumed_bars_fingerprint=FP64_B,
        reference_timestamp=T0 + timedelta(days=1),
        reference_price=100.0,
        future_timestamp=T0 + timedelta(days=7),
        future_price=105.0,
        forward_return=105.0 / 100.0 - 1.0,
    )
    fields.update(overrides)
    return OutcomeRecord(**fields)


# -- enums -------------------------------------------------------------------


class TestEnums:
    def test_exactly_two_artifact_kinds(self):
        assert {kind.value for kind in ArtifactKind} == {"observation", "assessment"}

    def test_the_only_origin_is_snapshot(self):
        """Replay/backfill is not a Phase 12 concept. Extensibility is through
        the enum, never through accepting an unknown string."""
        assert [origin.value for origin in ArtifactOrigin] == ["snapshot"]
        with pytest.raises(ValueError):
            ArtifactOrigin("replay")

    def test_evaluation_version_is_supported(self):
        assert EVALUATION_VERSION == 1
        assert EVALUATION_VERSION in SUPPORTED_EVALUATION_VERSIONS
        assert isinstance(SUPPORTED_EVALUATION_VERSIONS, frozenset)


# -- tracked artifacts --------------------------------------------------------


class TestTrackedArtifactBase:
    def test_the_base_is_not_constructible(self):
        """An artifact without a kind has no identity payload."""
        with pytest.raises(OutcomeTrackingError, match="kind"):
            TrackedArtifact(
                symbol="AAPL", interval="1d", basis="raw", timestamp=T0,
                state=ResearchState.BULLISH, reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
                source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
                observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
            )

    def test_subtypes_are_tracked_artifacts(self):
        assert isinstance(obs_artifact(), TrackedArtifact)
        assert isinstance(asmt_artifact(), TrackedArtifact)

    def test_frozen(self):
        for artifact in (obs_artifact(), asmt_artifact()):
            with pytest.raises(dataclasses.FrozenInstanceError):
                artifact.state = ResearchState.BEARISH  # type: ignore[misc]
            with pytest.raises(dataclasses.FrozenInstanceError):
                artifact.symbol = "MSFT"  # type: ignore[misc]

    def test_kind_is_fixed_per_subtype(self):
        assert obs_artifact().kind is ArtifactKind.OBSERVATION
        assert asmt_artifact().kind is ArtifactKind.ASSESSMENT
        assert ObservationArtifact.kind is ArtifactKind.OBSERVATION
        assert AssessmentArtifact.kind is ArtifactKind.ASSESSMENT

    def test_reason_codes_are_a_tuple_even_from_a_list(self):
        artifact = obs_artifact(reason_codes=[ReasonCode.FAST_ABOVE_SLOW])
        assert artifact.reason_codes == (ReasonCode.FAST_ABOVE_SLOW,)
        assert isinstance(artifact.reason_codes, tuple)

    def test_interval_and_basis_are_parsed_from_strings(self):
        artifact = obs_artifact(interval="1wk", basis="raw")
        assert artifact.interval is Interval.WEEK_1
        assert artifact.basis is PriceBasis.RAW

    def test_hashable_and_equal_by_value(self):
        assert obs_artifact() == obs_artifact()
        assert hash(obs_artifact()) == hash(obs_artifact())
        assert asmt_artifact() == asmt_artifact()
        assert obs_artifact() != asmt_artifact()


class TestTrackedArtifactRejections:
    @pytest.mark.parametrize("field", ["symbol", "source"])
    @pytest.mark.parametrize("bad", ["", "   ", None, 7])
    def test_blank_or_non_text_identity_text_rejected(self, field, bad):
        with pytest.raises(OutcomeTrackingError, match=field):
            obs_artifact(**{field: bad})

    @pytest.mark.parametrize("field", ["timestamp", "data_cutoff", "recorded_at"])
    def test_naive_timestamps_rejected(self, field):
        with pytest.raises(OutcomeTrackingError, match="timezone-aware"):
            obs_artifact(**{field: datetime(2024, 1, 5)})

    @pytest.mark.parametrize("field", ["timestamp", "data_cutoff", "recorded_at"])
    def test_non_datetime_timestamps_rejected(self, field):
        with pytest.raises(OutcomeTrackingError, match=field):
            obs_artifact(**{field: "2024-01-05T00:00:00+00:00"})

    def test_a_claim_about_a_bar_after_the_cutoff_is_impossible(self):
        """``data_cutoff`` is the latest settled bar open the producer saw. A
        claim about a bar it had not seen is not a claim it could have made."""
        with pytest.raises(OutcomeTrackingError, match="data_cutoff"):
            obs_artifact(timestamp=CUTOFF + timedelta(days=1))

    def test_a_bar_before_the_cutoff_is_allowed_by_the_record(self):
        """The tail rule (timestamp == data_cutoff) is a registration policy,
        not a property of the record; it belongs to the application layer."""
        artifact = obs_artifact(timestamp=CUTOFF - timedelta(days=3))
        assert artifact.timestamp < artifact.data_cutoff

    def test_recording_before_the_cutoff_bar_opened_is_impossible(self):
        with pytest.raises(OutcomeTrackingError, match="recorded_at"):
            obs_artifact(recorded_at=CUTOFF - timedelta(seconds=1))

    def test_recording_at_the_cutoff_instant_is_allowed(self):
        assert obs_artifact(recorded_at=CUTOFF).recorded_at == CUTOFF

    @pytest.mark.parametrize("bad", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, 12, None])
    def test_bar_fingerprint_must_be_64_lowercase_hex(self, bad):
        with pytest.raises(OutcomeTrackingError, match="observation_bar_fingerprint"):
            obs_artifact(observation_bar_fingerprint=bad)

    @pytest.mark.parametrize("bad", ["snapshot ", "replay", "", None, 1])
    def test_origin_must_be_an_artifact_origin(self, bad):
        with pytest.raises(OutcomeTrackingError, match="origin"):
            obs_artifact(origin=bad)

    def test_origin_accepts_the_enum_value_string(self):
        assert obs_artifact(origin="snapshot").origin is ArtifactOrigin.SNAPSHOT

    def test_empty_reason_codes_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="reason"):
            obs_artifact(reason_codes=())

    def test_reason_codes_as_a_string_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="reason"):
            obs_artifact(reason_codes="fast_above_slow")

    @pytest.mark.parametrize("bad", ["2d", "", None])
    def test_unknown_interval_rejected(self, bad):
        with pytest.raises(OutcomeTrackingError, match="interval"):
            obs_artifact(interval=bad)

    def test_unknown_basis_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="basis"):
            obs_artifact(basis="adjusted_for_fun")


class TestObservationArtifact:
    def test_state_is_a_research_state(self):
        artifact = obs_artifact(state="bearish")
        assert artifact.state is ResearchState.BEARISH
        assert type(artifact.state) is ResearchState

    def test_assessment_state_instances_are_rejected_even_when_the_value_matches(self):
        """``AssessmentState.BULLISH`` and ``ResearchState.BULLISH`` share a
        value but not a meaning; a silent conversion would hide a type slip."""
        with pytest.raises(OutcomeTrackingError, match="ResearchState"):
            obs_artifact(state=AssessmentState.BULLISH)

    def test_conflicted_is_not_observation_vocabulary(self):
        with pytest.raises(OutcomeTrackingError, match="state"):
            obs_artifact(state="conflicted")

    def test_reason_codes_are_research_reason_codes(self):
        artifact = obs_artifact(reason_codes=("fast_above_slow",))
        assert artifact.reason_codes == (ReasonCode.FAST_ABOVE_SLOW,)
        with pytest.raises(OutcomeTrackingError, match="reason"):
            obs_artifact(reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,))

    @pytest.mark.parametrize("bad", ["", "  ", None, 3])
    def test_hypothesis_id_must_be_text(self, bad):
        with pytest.raises(OutcomeTrackingError, match="hypothesis_id"):
            obs_artifact(hypothesis_id=bad)

    @pytest.mark.parametrize("bad", [0, -1, True, 1.0, "1", None])
    def test_hypothesis_version_must_be_a_positive_int(self, bad):
        with pytest.raises(OutcomeTrackingError, match="hypothesis_version"):
            obs_artifact(hypothesis_version=bad)

    @pytest.mark.parametrize("bad", ["", "  ", None, 3])
    def test_hypothesis_fingerprint_must_be_text(self, bad):
        with pytest.raises(OutcomeTrackingError, match="hypothesis_fingerprint"):
            obs_artifact(hypothesis_fingerprint=bad)

    def test_insufficient_data_is_representable_but_not_evaluable(self):
        artifact = obs_artifact(
            state=ResearchState.INSUFFICIENT_DATA,
            reason_codes=(ReasonCode.WARMUP_INCOMPLETE,),
        )
        assert artifact.is_evaluable is False
        assert obs_artifact().is_evaluable is True

    def test_label_and_describe_carry_identity(self):
        artifact = obs_artifact()
        assert artifact.label == "trend_alignment@v1#0011223344556677"
        text = artifact.describe()
        for needle in ("observation", "AAPL", "1d", "raw", T0.isoformat(),
                       "bullish", "trend_alignment@v1#0011223344556677"):
            assert needle in text


class TestAssessmentArtifact:
    def test_state_is_an_assessment_state(self):
        artifact = asmt_artifact(state="conflicted",
                                 reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,))
        assert artifact.state is AssessmentState.CONFLICTED
        assert type(artifact.state) is AssessmentState

    def test_research_state_instances_are_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="AssessmentState"):
            asmt_artifact(state=ResearchState.BULLISH)

    def test_reason_codes_are_assessment_reason_codes(self):
        with pytest.raises(OutcomeTrackingError, match="reason"):
            asmt_artifact(reason_codes=(ReasonCode.FAST_ABOVE_SLOW,))

    @pytest.mark.parametrize("bad", ["", "abc", "A" * 16, "g" * 16, "a" * 15, "a" * 17, None, 1])
    def test_policy_fingerprint_must_match_the_policy_format(self, bad):
        """Exactly what ``AssessmentPolicy.fingerprint`` produces: 16 lowercase
        hex characters -- the same rule ``ResearchAssessment`` enforces."""
        with pytest.raises(OutcomeTrackingError, match="policy_fingerprint"):
            asmt_artifact(policy_fingerprint=bad)

    def test_conflicted_and_neutral_are_evaluable_but_insufficient_is_not(self):
        conflicted = asmt_artifact(
            state=AssessmentState.CONFLICTED,
            reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,),
        )
        neutral = asmt_artifact(
            state=AssessmentState.NEUTRAL,
            reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,),
        )
        insufficient = asmt_artifact(
            state=AssessmentState.INSUFFICIENT_DATA,
            reason_codes=(AssessmentReasonCode.INSUFFICIENT_EVIDENCE,),
        )
        assert conflicted.is_evaluable and neutral.is_evaluable
        assert not insufficient.is_evaluable

    def test_label_and_describe_carry_identity(self):
        artifact = asmt_artifact()
        assert artifact.label == f"policy#{POLICY_FP}"
        text = artifact.describe()
        for needle in ("assessment", "AAPL", "bullish", f"policy#{POLICY_FP}"):
            assert needle in text


# -- builders ------------------------------------------------------------------


class TestBuilders:
    def test_from_observation_copies_identity_and_claim(self):
        source = observation()
        artifact = ObservationArtifact.from_observation(
            source, source="yfinance", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        assert artifact.hypothesis_id == source.hypothesis_id
        assert artifact.hypothesis_version == source.version
        assert artifact.hypothesis_fingerprint == source.fingerprint
        assert artifact.symbol == source.symbol
        assert artifact.interval is source.interval
        assert artifact.basis is source.basis
        assert artifact.timestamp == source.timestamp
        assert artifact.state is source.state
        assert artifact.reason_codes == source.reason_codes
        assert artifact.source == "yfinance"
        assert artifact.data_cutoff == CUTOFF
        assert artifact.recorded_at == RECORDED
        assert artifact.observation_bar_fingerprint == FP64
        assert artifact.origin is ArtifactOrigin.SNAPSHOT

    def test_from_observation_does_not_mutate_the_observation(self):
        source = observation()
        before = (source.hypothesis_id, source.version, source.fingerprint, source.symbol,
                  source.interval, source.basis, source.timestamp, source.state,
                  dict(source.evidence), source.reason_codes)
        ObservationArtifact.from_observation(
            source, source="yfinance", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        after = (source.hypothesis_id, source.version, source.fingerprint, source.symbol,
                 source.interval, source.basis, source.timestamp, source.state,
                 dict(source.evidence), source.reason_codes)
        assert before == after

    def test_from_observation_requires_an_observation(self):
        with pytest.raises(OutcomeTrackingError, match="ResearchObservation"):
            ObservationArtifact.from_observation(
                assessment(), source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
                observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
            )

    def test_from_observation_carries_insufficient_data_as_is(self):
        source = observation(state=ResearchState.INSUFFICIENT_DATA,
                             reason_codes=(ReasonCode.WARMUP_INCOMPLETE,))
        artifact = ObservationArtifact.from_observation(
            source, source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        assert artifact.state is ResearchState.INSUFFICIENT_DATA
        assert not artifact.is_evaluable

    def test_from_assessment_copies_identity_and_claim(self):
        source = assessment()
        artifact = AssessmentArtifact.from_assessment(
            source, source="yfinance", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        assert artifact.policy_fingerprint == source.policy_fingerprint
        assert artifact.symbol == source.symbol
        assert artifact.interval is source.interval
        assert artifact.basis is source.basis
        assert artifact.timestamp == source.timestamp
        assert artifact.state is source.state
        assert artifact.reason_codes == source.reason_codes
        assert artifact.source == "yfinance"

    def test_from_assessment_does_not_carry_the_assessment_clock(self):
        """``assessment_as_of`` is a clock reading, not a claim; the registration
        clock is ``recorded_at`` and is supplied by the caller."""
        source = assessment()
        artifact = AssessmentArtifact.from_assessment(
            source, source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        assert not hasattr(artifact, "assessment_as_of")
        assert artifact.recorded_at == RECORDED

    def test_from_assessment_does_not_mutate_the_assessment(self):
        source = assessment()
        before = (source.policy_fingerprint, source.symbol, source.interval, source.basis,
                  source.timestamp, source.assessment_as_of, source.state, source.inputs,
                  source.counts, source.reason_codes)
        AssessmentArtifact.from_assessment(
            source, source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
            observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        )
        after = (source.policy_fingerprint, source.symbol, source.interval, source.basis,
                 source.timestamp, source.assessment_as_of, source.state, source.inputs,
                 source.counts, source.reason_codes)
        assert before == after

    def test_from_assessment_requires_an_assessment(self):
        with pytest.raises(OutcomeTrackingError, match="ResearchAssessment"):
            AssessmentArtifact.from_assessment(
                observation(), source="t", data_cutoff=CUTOFF, recorded_at=RECORDED,
                observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
            )

    def test_builders_take_no_defaults_for_audit_fields(self):
        """Every audit value is caller-supplied: no clock is read here and no
        origin is assumed."""
        with pytest.raises(TypeError):
            ObservationArtifact.from_observation(observation(), source="t")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            AssessmentArtifact.from_assessment(assessment(), source="t")  # type: ignore[call-arg]


# -- outcome records -------------------------------------------------------------


class TestOutcomeRecord:
    def test_valid_observation_outcome(self):
        rec = record()
        assert rec.artifact == obs_artifact()
        assert rec.forward_return == pytest.approx(0.05)
        assert rec.evaluation_version == EVALUATION_VERSION

    def test_valid_assessment_outcome(self):
        rec = record(asmt_artifact())
        assert rec.artifact.kind is ArtifactKind.ASSESSMENT

    def test_frozen(self):
        rec = record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            rec.forward_return = 0.0  # type: ignore[misc]

    def test_audit_fields_are_read_through_the_artifact(self):
        """Design A: the record embeds the artifact it measured, so the
        provenance can never drift from the claim and a record can never be
        orphaned from its artifact."""
        rec = record()
        assert rec.artifact_key == rec.artifact.artifact_key
        assert rec.data_cutoff == rec.artifact.data_cutoff
        assert rec.recorded_at == rec.artifact.recorded_at
        assert rec.observation_bar_fingerprint == rec.artifact.observation_bar_fingerprint

    def test_outcome_key_is_derived_not_stored(self):
        rec = record()
        assert rec.outcome_key == outcome_key(
            artifact_key=rec.artifact.artifact_key,
            spec_fingerprint=SPEC_FP,
            evaluation_version=EVALUATION_VERSION,
        )
        assert "outcome_key" not in {f.name for f in dataclasses.fields(rec)}
        assert "artifact_key" not in {f.name for f in dataclasses.fields(rec)}

    def test_artifact_must_be_a_tracked_artifact(self):
        with pytest.raises(OutcomeTrackingError, match="TrackedArtifact"):
            record(artifact=observation())

    def test_an_ineligible_artifact_can_never_have_an_outcome(self):
        insufficient = obs_artifact(
            state=ResearchState.INSUFFICIENT_DATA,
            reason_codes=(ReasonCode.WARMUP_INCOMPLETE,),
        )
        with pytest.raises(OutcomeTrackingError, match="INSUFFICIENT_DATA|evaluable"):
            record(insufficient)
        insufficient_assessment = asmt_artifact(
            state=AssessmentState.INSUFFICIENT_DATA,
            reason_codes=(AssessmentReasonCode.INSUFFICIENT_EVIDENCE,),
        )
        with pytest.raises(OutcomeTrackingError, match="INSUFFICIENT_DATA|evaluable"):
            record(insufficient_assessment)

    def test_neutral_and_conflicted_outcomes_are_representable(self):
        """A forward return is a fact about the market; it is recorded for a
        NEUTRAL or CONFLICTED claim too. Whether it is *scored* is not this
        record's business."""
        record(asmt_artifact(state="neutral",
                             reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,)))
        record(asmt_artifact(state="conflicted",
                             reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,)))
        record(obs_artifact(state="neutral", reason_codes=(ReasonCode.MOMENTUM_MIDRANGE,)))

    @pytest.mark.parametrize("bad", ["", "abc", "A" * 16, "a" * 15, "a" * 64, None, 5])
    def test_spec_fingerprint_must_match_the_outcome_spec_format(self, bad):
        """16 lowercase hex: exactly what ``OutcomeSpec.fingerprint`` yields."""
        with pytest.raises(OutcomeTrackingError, match="spec_fingerprint"):
            record(spec_fingerprint=bad)

    @pytest.mark.parametrize("bad", [0, -1, True, 2.0, "5", None])
    def test_horizon_bars_must_be_a_positive_int(self, bad):
        with pytest.raises(OutcomeTrackingError, match="horizon_bars"):
            record(horizon_bars=bad)

    @pytest.mark.parametrize("bad", [0, 2, 99, -1, True, "1", 1.0, None])
    def test_unsupported_evaluation_version_rejected(self, bad):
        with pytest.raises(OutcomeTrackingError, match="evaluation_version"):
            record(evaluation_version=bad)

    @pytest.mark.parametrize("bad", ["", "A" * 64, "a" * 63, "g" * 64, None, 1])
    def test_consumed_bars_fingerprint_must_be_64_lowercase_hex(self, bad):
        with pytest.raises(OutcomeTrackingError, match="consumed_bars_fingerprint"):
            record(consumed_bars_fingerprint=bad)

    @pytest.mark.parametrize("field", ["evaluated_at", "reference_timestamp", "future_timestamp"])
    def test_naive_timestamps_rejected(self, field):
        with pytest.raises(OutcomeTrackingError, match="timezone-aware"):
            record(**{field: datetime(2024, 2, 1)})

    def test_evaluated_before_recorded_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="evaluated_at"):
            record(evaluated_at=RECORDED - timedelta(seconds=1))

    def test_evaluated_at_the_recording_instant_is_allowed(self):
        """``evaluated_at >= recorded_at`` admits equality. The record cannot
        know bar durations, so it cannot tell whether a same-instant
        evaluation was actually reachable; that is the caller's knowledge
        (settled bars only), and the record does not pretend to have it."""
        rec = record(horizon_bars=1, reference_timestamp=T0 + timedelta(days=1),
                     future_timestamp=T0 + timedelta(days=1), evaluated_at=RECORDED)
        assert rec.evaluated_at == RECORDED == rec.recorded_at

    def test_reference_must_be_strictly_after_the_claimed_bar(self):
        """Phase 4 NEXT_BAR_OPEN: the reference is bar i+1, never bar i."""
        with pytest.raises(OutcomeTrackingError, match="reference_timestamp"):
            record(reference_timestamp=T0)
        with pytest.raises(OutcomeTrackingError, match="reference_timestamp"):
            record(reference_timestamp=T0 - timedelta(days=1))

    def test_future_must_not_precede_the_reference(self):
        with pytest.raises(OutcomeTrackingError, match="future_timestamp"):
            record(reference_timestamp=T0 + timedelta(days=2),
                   future_timestamp=T0 + timedelta(days=1))

    def test_a_one_bar_horizon_has_future_equal_to_reference(self):
        """``horizon_bars=1`` ends on the reference bar itself (ADR 0002 §3)."""
        rec = record(horizon_bars=1, reference_timestamp=T0 + timedelta(days=1),
                     future_timestamp=T0 + timedelta(days=1))
        assert rec.future_timestamp == rec.reference_timestamp

    def test_a_one_bar_horizon_cannot_end_on_a_later_bar(self):
        with pytest.raises(OutcomeTrackingError, match="horizon_bars=1"):
            record(horizon_bars=1, reference_timestamp=T0 + timedelta(days=1),
                   future_timestamp=T0 + timedelta(days=2))

    def test_a_multi_bar_horizon_cannot_end_on_the_reference_bar(self):
        with pytest.raises(OutcomeTrackingError, match="horizon_bars=5"):
            record(horizon_bars=5, reference_timestamp=T0 + timedelta(days=1),
                   future_timestamp=T0 + timedelta(days=1))

    def test_evaluation_cannot_precede_the_future_bars_open(self):
        """A settled bar is read after it opened; a clock at or before the
        future bar's open describes a measurement that could not have
        happened."""
        with pytest.raises(OutcomeTrackingError, match="evaluated_at"):
            record(evaluated_at=T0 + timedelta(days=7))      # == future_timestamp
        with pytest.raises(OutcomeTrackingError, match="evaluated_at"):
            record(evaluated_at=T0 + timedelta(days=6))
        assert record(evaluated_at=T0 + timedelta(days=7, seconds=1)).evaluated_at

    def test_future_bar_must_postdate_the_data_cutoff(self):
        """The prospective invariant: the bar that closes the measurement did
        not exist in the data when the claim was recorded."""
        cutoff_later = obs_artifact(timestamp=T0 - timedelta(days=10),
                                    data_cutoff=T0 + timedelta(days=7),
                                    recorded_at=T0 + timedelta(days=8))
        with pytest.raises(OutcomeTrackingError, match="data_cutoff"):
            record(cutoff_later, reference_timestamp=T0 - timedelta(days=9),
                   future_timestamp=T0 + timedelta(days=7),
                   evaluated_at=T0 + timedelta(days=30))

    def test_future_bar_one_step_after_the_cutoff_is_prospective(self):
        rec = record(reference_timestamp=CUTOFF + timedelta(days=1),
                     future_timestamp=CUTOFF + timedelta(days=1), horizon_bars=1)
        assert rec.future_timestamp > rec.data_cutoff

    @pytest.mark.parametrize("field", ["reference_price", "future_price"])
    @pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf, True, "100", None])
    def test_prices_must_be_finite_and_positive(self, field, bad):
        with pytest.raises(OutcomeTrackingError, match=field):
            record(**{field: bad, "forward_return": 0.0})

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "0.05", None, True])
    def test_forward_return_must_be_a_finite_number(self, bad):
        with pytest.raises(OutcomeTrackingError, match="forward_return"):
            record(forward_return=bad)

    def test_forward_return_must_agree_with_its_own_prices(self):
        """A record claiming +5% beside prices that say -5% is self-contradictory.
        The arithmetic is Phase 4's definition (``future / reference - 1``),
        checked here for consistency, not redefined."""
        with pytest.raises(OutcomeTrackingError, match="forward_return"):
            record(reference_price=100.0, future_price=95.0, forward_return=0.05)

    def test_prices_are_stored_as_floats(self):
        rec = record(reference_price=100, future_price=105, forward_return=105 / 100 - 1)
        assert isinstance(rec.reference_price, float)
        assert isinstance(rec.future_price, float)
        assert isinstance(rec.forward_return, float)

    def test_negative_and_zero_returns_are_valid_facts(self):
        down = record(reference_price=100.0, future_price=90.0, forward_return=90.0 / 100.0 - 1.0)
        flat = record(reference_price=100.0, future_price=100.0, forward_return=0.0)
        assert down.forward_return == pytest.approx(-0.10)
        assert flat.forward_return == 0.0

    def test_describe_is_informative(self):
        text = record().describe()
        for needle in ("trend_alignment@v1", "AAPL", "h=5", "+0.05"):
            assert needle in text
