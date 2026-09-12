"""Phase 11A Stage A: the reasoning records refuse what they cannot describe.

These tests are about construction, not behaviour. A record that accepts a naive
timestamp, a NaN, a duplicate citation or an unknown schema version would push
the problem downstream to whoever renders it.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.reasoning.models import (
    EVIDENCE_SCHEMA_VERSION,
    MAX_CLAIMS,
    MAX_EVIDENCE_IDS_PER_CLAIM,
    MAX_OBSERVATION_EVIDENCE_ITEMS,
    MAX_PACKET_OBSERVATIONS,
    MAX_REASON_CODES,
    MAX_REASONING_TEXT_CHARS,
    EvidencePacket,
    PacketCounts,
    PacketObservation,
    ProviderReasoningResponse,
    ReasoningClaim,
    ReasoningError,
    ReasoningFailureCode,
    ReasoningKind,
    ReasoningRequest,
    ReasoningSnapshot,
    ReasoningSummary,
    ReasoningUsageMetadata,
    canonical_bytes,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 7, 12, tzinfo=UTC)


def observation(**overrides) -> PacketObservation:
    fields = {
        "hypothesis_id": "trend_alignment",
        "version": 1,
        "hypothesis_fingerprint": "650add07184f8440",
        "state": "bullish",
        "reason_codes": ("fast_above_slow",),
        "timestamp": T0 - timedelta(days=1),
        "evidence": {"sma(field='close',period=20)": 209.5},
    }
    fields.update(overrides)
    return PacketObservation(**fields)


def packet(**overrides) -> EvidencePacket:
    fields = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "symbol": "AAPL",
        "interval": "1d",
        "basis": "raw",
        "data_cutoff": T0,
        "policy_fingerprint": "a829b9bde41c3332",
        "warmup_bars": 51,
        "minimum_sufficient_observations": 2,
        "assessment_state": "bullish",
        "counts": PacketCounts(bullish=2, bearish=0, neutral=1, insufficient=0),
        "assessment_reason_codes": ("directional_bullish_with_neutral",),
        "observations": (observation(),),
        "generated_at": T0,
        "omitted_counts": {},
    }
    fields.update(overrides)
    return EvidencePacket(**fields)


def usage() -> ReasoningUsageMetadata:
    return ReasoningUsageMetadata(
        provider="fake", model="fake-1", input_tokens=10, output_tokens=5,
        latency_ms=12, attempt_count=1,
    )


# -- vocabulary ----------------------------------------------------------


def test_there_is_exactly_one_reasoning_kind():
    """Stage A ships one job. A speculative second member would need a prompt."""
    assert [member.name for member in ReasoningKind] == ["EXPLAIN_RESEARCH"]
    assert ReasoningKind.EXPLAIN_RESEARCH.value == "explain_research"


def test_a_claim_carries_no_model_authored_type():
    """The model must not label its own prose.

    A claim typed "supporting" that actually contradicts renders under a heading
    its own citations disagree with, and no deterministic check can catch it.
    Grouping is derived from the cited observations instead, so the label has
    nowhere to be wrong.
    """
    import src.reasoning.models as models

    assert not hasattr(models, "ClaimType")
    assert {f.name for f in dataclasses.fields(ReasoningClaim)} == {
        "text", "evidence_ids",
    }


def test_failure_codes_are_exactly_these_and_split_operational_from_content():
    assert [member.name for member in ReasoningFailureCode] == [
        "PROVIDER_UNAVAILABLE", "RATE_LIMITED", "AUTHENTICATION_FAILED",
        "REQUEST_INVALID", "OUTPUT_SCHEMA_FAILED", "GROUNDING_FAILED",
        "BOUNDARY_VIOLATION", "UNEXPECTED",
    ]
    operational = {c for c in ReasoningFailureCode if c.is_operational}
    content = set(ReasoningFailureCode) - operational
    assert content == {
        ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
        ReasoningFailureCode.GROUNDING_FAILED,
        ReasoningFailureCode.BOUNDARY_VIOLATION,
    }


def test_no_model_exposes_a_score_or_recommendation_field():
    """The shape, not the prompt, is what makes advice unrepresentable."""
    forbidden = (
        "score", "confidence", "probability", "recommendation", "rating",
        "target", "conviction", "signal", "action", "allocation", "expected_return",
    )
    for model in (EvidencePacket, PacketObservation, PacketCounts, ReasoningClaim,
                  ReasoningSummary, ReasoningSnapshot, ReasoningRequest,
                  ReasoningUsageMetadata):
        names = {f.name for f in dataclasses.fields(model)}
        for word in forbidden:
            offenders = [name for name in names if word in name]
            assert not offenders, f"{model.__name__} exposes {offenders}"


# -- immutability --------------------------------------------------------


@pytest.mark.parametrize("model", [
    PacketCounts, PacketObservation, EvidencePacket, ReasoningClaim,
    ReasoningRequest, ReasoningUsageMetadata, ProviderReasoningResponse,
    ReasoningSnapshot,
    ReasoningSummary,
])
def test_every_stage_a_model_is_frozen(model):
    assert model.__dataclass_params__.frozen, model.__name__


def test_a_packet_cannot_be_mutated_after_construction():
    built = packet()
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.symbol = "MSFT"
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.observations = ()


def test_evidence_and_omitted_counts_are_read_only_views():
    """A caller must not be able to edit content after a digest was taken."""
    built = packet(omitted_counts={"observations": 2})
    with pytest.raises(TypeError):
        built.omitted_counts["observations"] = 99
    with pytest.raises(TypeError):
        built.observations[0].evidence["sma(field='close',period=20)"] = 1.0


def test_a_mutable_input_mapping_is_copied_not_referenced():
    supplied = {"sma(field='close',period=20)": 1.0}
    built = observation(evidence=supplied)
    supplied["injected"] = 2.0
    assert "injected" not in built.evidence


# -- timestamps ----------------------------------------------------------


@pytest.mark.parametrize("field_name", ["data_cutoff", "generated_at"])
def test_a_naive_packet_datetime_is_refused(field_name):
    with pytest.raises(ReasoningError, match="timezone-aware"):
        packet(**{field_name: datetime(2026, 9, 7, 12)})


def test_a_naive_observation_timestamp_is_refused():
    with pytest.raises(ReasoningError, match="timezone-aware"):
        observation(timestamp=datetime(2026, 9, 6, 12))


def test_a_non_utc_timestamp_is_normalized_rather_than_refused():
    other = timezone(timedelta(hours=5))
    built = observation(timestamp=datetime(2026, 9, 6, 17, tzinfo=other))
    assert built.timestamp.utcoffset() == timedelta(0)


# -- schema version ------------------------------------------------------


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_an_unknown_schema_version_is_refused(version):
    with pytest.raises(ReasoningError, match="schema_version"):
        packet(schema_version=version)


# -- assessment presence -------------------------------------------------


def test_an_absent_assessment_is_represented_as_absence():
    built = packet(assessment_state=None, counts=None, assessment_reason_codes=())
    assert built.assessment_state is None
    assert built.counts is None
    assert built.has_assessment is False


def test_a_half_present_assessment_is_refused():
    with pytest.raises(ReasoningError, match="absent entirely"):
        packet(counts=None)
    with pytest.raises(ReasoningError, match="absent entirely"):
        packet(assessment_state=None, assessment_reason_codes=())


def test_reason_codes_without_an_assessment_are_refused():
    with pytest.raises(ReasoningError, match="none to describe"):
        packet(assessment_state=None, counts=None,
               assessment_reason_codes=("unanimous_bullish",))


# -- numbers -------------------------------------------------------------


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_evidence_value_is_refused(value):
    with pytest.raises(ReasoningError, match="finite"):
        observation(evidence={"sma(field='close',period=20)": value})


def test_a_missing_evidence_value_is_preserved_as_none():
    """``None`` means the hypothesis had no value during warm-up. That is data."""
    built = observation(evidence={"sma(field='close',period=20)": None})
    assert built.evidence["sma(field='close',period=20)"] is None


def test_counts_refuse_negatives_and_booleans():
    with pytest.raises(ReasoningError):
        PacketCounts(bullish=-1, bearish=0, neutral=0, insufficient=0)
    with pytest.raises(ReasoningError):
        PacketCounts(bullish=True, bearish=0, neutral=0, insufficient=0)


# -- identity and caps ---------------------------------------------------


def test_duplicate_evidence_ids_within_a_packet_are_refused():
    with pytest.raises(ReasoningError, match="unique"):
        packet(observations=(observation(), observation()))


def test_an_observation_id_cannot_contradict_its_own_identity():
    """Derived, not stored: there is no argument through which an id could be
    made to disagree with the hypothesis it names."""
    built = observation(hypothesis_id="trend_alignment", version=2,
                        hypothesis_fingerprint="abc123")
    assert built.evidence_id == "obs:trend_alignment:v2:abc123"
    assert "evidence_id" not in {f.name for f in dataclasses.fields(PacketObservation)}
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.evidence_id = "obs:something:v1:else"


def test_a_claim_may_not_cite_the_same_evidence_twice():
    with pytest.raises(ReasoningError, match="same evidence twice"):
        ReasoningClaim(text="x", evidence_ids=("a", "a"))


def test_too_many_observations_are_refused():
    many = tuple(
        observation(hypothesis_id=f"h{i}") for i in range(MAX_PACKET_OBSERVATIONS + 1)
    )
    with pytest.raises(ReasoningError, match="at most"):
        packet(observations=many)


def test_too_much_evidence_on_one_observation_is_refused():
    values = {f"feature_{i}": float(i) for i in range(MAX_OBSERVATION_EVIDENCE_ITEMS + 1)}
    with pytest.raises(ReasoningError, match="at most"):
        observation(evidence=values)


def test_too_many_reason_codes_are_refused():
    with pytest.raises(ReasoningError, match="more than"):
        observation(reason_codes=tuple(f"code_{i}" for i in range(MAX_REASON_CODES + 1)))


def test_text_fields_are_bounded():
    with pytest.raises(ReasoningError, match="exceeds"):
        ReasoningClaim(text="x" * (MAX_REASONING_TEXT_CHARS + 1),
                       evidence_ids=("fact:a",))
    with pytest.raises(ReasoningError, match="exceeds"):
        packet(symbol="A" * 33)


def test_empty_and_control_character_text_is_refused():
    with pytest.raises(ReasoningError, match="must not be empty"):
        packet(symbol="   ")
    with pytest.raises(ReasoningError, match="control characters"):
        packet(symbol="AA\x00PL")


def test_a_claim_may_not_cite_more_than_the_cap():
    with pytest.raises(ReasoningError, match="more than"):
        ReasoningClaim(
            text="x",
            evidence_ids=tuple(f"id-{i}" for i in range(MAX_EVIDENCE_IDS_PER_CLAIM + 1)),
        )


# -- packet-level invariants ---------------------------------------------


def test_an_observation_after_the_cutoff_is_refused():
    """The causal invariant, enforced where the packet is assembled."""
    with pytest.raises(ReasoningError, match="after the data cutoff"):
        packet(observations=(observation(timestamp=T0 + timedelta(seconds=1)),))


def test_an_observation_exactly_at_the_cutoff_is_allowed():
    assert packet(observations=(observation(timestamp=T0),)).observations


def test_evidence_ids_cover_facts_observations_and_data():
    ids = packet().evidence_ids
    assert "fact:assessment-state" in ids
    assert "fact:assessment-counts" in ids
    assert "fact:policy:a829b9bde41c3332" in ids
    assert "fact:reason:directional_bullish_with_neutral" in ids
    assert "obs:trend_alignment:v1:650add07184f8440" in ids
    assert (
        "obs:trend_alignment:v1:650add07184f8440#sma(field='close',period=20)" in ids
    )


def test_a_packet_without_an_assessment_offers_no_assessment_ids():
    ids = packet(assessment_state=None, counts=None,
                 assessment_reason_codes=()).evidence_ids
    assert "fact:assessment-state" not in ids
    assert "fact:assessment-counts" not in ids
    assert any(i.startswith("obs:") for i in ids)


def test_observations_must_be_packet_observations():
    with pytest.raises(ReasoningError, match="PacketObservation"):
        packet(observations=("not-an-observation",))


# -- request and snapshot ------------------------------------------------


def test_a_request_carries_the_identity_a_later_phase_will_compare():
    request = ReasoningRequest(
        reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, packet=packet(),
        prompt_id="explain_research", prompt_version=1, prompt_fingerprint="abc123",
        output_schema_version=1, provider="fake", model="fake-1", created_at=T0,
    )
    assert request.reasoning_kind is ReasoningKind.EXPLAIN_RESEARCH
    assert request.prompt_version == 1


def test_a_request_refuses_anything_that_is_not_a_packet():
    with pytest.raises(ReasoningError, match="EvidencePacket"):
        ReasoningRequest(
            reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, packet={"symbol": "AAPL"},
            prompt_id="p", prompt_version=1, prompt_fingerprint="f",
            output_schema_version=1, provider="fake", model="m", created_at=T0,
        )


def test_provider_output_is_a_different_type_from_trusted_state():
    """Validation converts one into the other; nothing else can."""
    response = ProviderReasoningResponse(payload={"summary": "x"}, usage=usage())
    assert not isinstance(response, ReasoningSnapshot)
    with pytest.raises(TypeError):
        response.payload["summary"] = "y"


def test_a_snapshot_reports_every_id_it_relies_on():
    snapshot = ReasoningSnapshot(
        reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, symbol="AAPL", data_cutoff=T0,
        evidence_fingerprint="e" * 16, reasoning_fingerprint="r" * 16,
        prompt_id="explain_research", prompt_version=1, output_schema_version=1,
        summary=ReasoningSummary(text="Two hypotheses classified bullish.",
                                 evidence_ids=("fact:a",)),
        claims=(ReasoningClaim(text="c1", evidence_ids=("obs:x",)),),
        uncertainties=("The ensemble is still warming up.",),
        usage=usage(), generated_at=T0,
    )
    assert snapshot.cited_evidence_ids == frozenset({"fact:a", "obs:x"})


def test_a_snapshot_refuses_more_claims_than_the_cap():
    claim = ReasoningClaim(text="c", evidence_ids=("fact:a",))
    with pytest.raises(ReasoningError, match="at most"):
        ReasoningSnapshot(
            reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, symbol="AAPL",
            data_cutoff=T0, evidence_fingerprint="e", reasoning_fingerprint="r",
            prompt_id="p", prompt_version=1, output_schema_version=1,
            summary=ReasoningSummary(text="s", evidence_ids=("fact:a",)),
            claims=tuple(claim for _ in range(MAX_CLAIMS + 1)),
            uncertainties=(), usage=usage(), generated_at=T0,
        )


# -- canonical bytes -----------------------------------------------------


def test_canonical_bytes_match_the_established_repository_rules():
    """Byte-for-byte the scanner's rules, re-implemented because the firewall
    forbids importing them. Pinned so the two cannot drift silently."""
    payload = {"b": 1, "a": {"z": None, "y": 2.5}, "u": "café"}
    assert canonical_bytes(payload) == (
        b'{"a":{"y":2.5,"z":null},"b":1,"u":"caf\\u00e9"}'
    )


def test_canonical_bytes_refuse_nan():
    with pytest.raises(ValueError):
        canonical_bytes({"x": math.nan})


def test_canonical_bytes_ignore_mapping_insertion_order():
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


# -- identity has exactly one owner --------------------------------------


def test_every_evidence_id_uses_its_whole_fingerprint():
    """Kills truncation anywhere in id construction. A shortened digest lets two
    distinct policies or hypotheses share an id, and a citation to one silently
    becomes a citation to the other."""
    from src.reasoning.models import observation_evidence_id, policy_evidence_id

    policy = "a829b9bde41c3332"
    assert policy_evidence_id(policy) == f"fact:policy:{policy}"
    assert policy_evidence_id(policy).endswith(policy)

    fingerprint = "650add07184f8440"
    built = observation_evidence_id("trend_alignment", 1, fingerprint)
    assert built == f"obs:trend_alignment:v1:{fingerprint}"
    assert built.endswith(fingerprint)


def test_the_packet_builds_its_ids_through_the_shared_helpers():
    """One owner for identity. An id built inline somewhere else would drift
    from this one and only one of the two would ever be tested."""
    from src.reasoning.models import (
        FACT_ASSESSMENT_COUNTS,
        FACT_ASSESSMENT_STATE,
        observation_evidence_id,
        policy_evidence_id,
        reason_evidence_id,
    )

    built = packet()
    ids = built.evidence_ids
    assert policy_evidence_id(built.policy_fingerprint) in ids
    assert FACT_ASSESSMENT_STATE in ids
    assert FACT_ASSESSMENT_COUNTS in ids
    assert reason_evidence_id(built.assessment_reason_codes[0]) in ids
    assert observation_evidence_id(
        "trend_alignment", 1, "650add07184f8440"
    ) in ids


def test_two_policies_sharing_a_prefix_get_different_ids():
    from src.reasoning.models import policy_evidence_id

    assert policy_evidence_id("abcd1111") != policy_evidence_id("abcd2222")


def test_two_hypothesis_versions_get_different_ids():
    from src.reasoning.models import observation_evidence_id

    assert observation_evidence_id("h", 1, "fp") != observation_evidence_id("h", 2, "fp")
    assert observation_evidence_id("h", 1, "aaaa") != observation_evidence_id(
        "h", 1, "aaab"
    )


# -- evidence ids must be injective --------------------------------------


def test_an_identity_component_may_not_contain_an_id_delimiter():
    """Without this, the delimiter join is not injective:

        obs:{a:v1:b}:v2:{c}  ==  obs:{a}:v1:{b:v2:c}

    Two different observations would share one id and a citation to either
    would silently resolve to the other.
    """
    from src.reasoning.models import ID_DELIMITERS, require_identity_text

    for delimiter in ID_DELIMITERS:
        with pytest.raises(ReasoningError, match="may not contain"):
            require_identity_text(f"a{delimiter}b", "hypothesis_id", maximum=64)


def test_the_documented_id_collision_is_now_impossible():
    from src.reasoning.models import observation_evidence_id

    with pytest.raises(ReasoningError):
        observation_evidence_id("a:v1:b", 2, "c")
    with pytest.raises(ReasoningError):
        observation_evidence_id("a", 1, "b:v2:c")


def test_a_datum_id_cannot_be_forged_through_a_feature_name():
    """``{observation}#{feature}`` is only injective while neither half can
    contain a ``#``."""
    with pytest.raises(ReasoningError, match="may not contain"):
        observation(evidence={"a#b": 1.0})


def test_delimiters_are_refused_in_every_identity_carrying_field():
    with pytest.raises(ReasoningError, match="may not contain"):
        observation(hypothesis_id="trend:alignment")
    with pytest.raises(ReasoningError, match="may not contain"):
        observation(hypothesis_fingerprint="6505#8440")
    with pytest.raises(ReasoningError, match="may not contain"):
        observation(reason_codes=("fast:above:slow",))
    with pytest.raises(ReasoningError, match="may not contain"):
        packet(policy_fingerprint="a829:b9bd")
    with pytest.raises(ReasoningError, match="may not contain"):
        packet(assessment_reason_codes=("directional:bullish",))


def test_the_real_ensemble_vocabulary_is_unaffected():
    """The restriction costs nothing real: ids are slugs, fingerprints are hex,
    and feature names are generated from a spec containing neither delimiter."""
    from src.reasoning.models import observation_evidence_id, require_identity_text

    assert observation_evidence_id("momentum_in_trend_context", 1, "6589cb8021b76574")
    assert require_identity_text(
        "sma(field='close',period=20)", "evidence name", maximum=200
    )


# -- signed zero ---------------------------------------------------------


def test_negative_zero_is_normalised_to_positive_zero():
    """``-0.0 == 0.0`` everywhere in this pipeline, but they serialise to
    different bytes. Left alone, numerically identical evidence would
    fingerprint differently and staleness would fire for no reason."""
    from src.reasoning.models import require_finite

    assert require_finite(-0.0, "x") == 0.0
    assert math.copysign(1.0, require_finite(-0.0, "x")) == 1.0
    minus = observation(evidence={"feature": -0.0})
    plus = observation(evidence={"feature": 0.0})
    assert canonical_bytes(minus.canonical()) == canonical_bytes(plus.canonical())


def test_ordinary_negative_values_keep_their_sign():
    from src.reasoning.models import require_finite

    assert require_finite(-1.5, "x") == -1.5


# -- ordering is a model guarantee, not a builder side effect ------------


def test_an_observation_sorts_its_evidence_whoever_built_it():
    """Pinned at the model, not only through ``build_packet``.

    A ``PacketObservation`` constructed directly from an unsorted mapping must
    still expose a deterministic order, or two records holding identical
    evidence would render differently depending on how the mapping happened to
    be populated.
    """
    built = observation(evidence={"z_feature": 1.0, "a_feature": 2.0})
    assert list(built.evidence) == ["a_feature", "z_feature"]


def test_omitted_counts_are_sorted_whoever_built_them():
    built = packet(omitted_counts={"z": 1, "a": 2})
    assert list(built.omitted_counts) == ["a", "z"]


def test_insertion_order_never_reaches_the_canonical_form():
    """Belt and braces: even if ordering were lost, the canonical encoding
    sorts keys, so an identical packet cannot fingerprint two ways."""
    forward = observation(evidence={"a_feature": 1.0, "z_feature": 2.0})
    backward = observation(evidence={"z_feature": 2.0, "a_feature": 1.0})
    assert canonical_bytes(forward.canonical()) == canonical_bytes(backward.canonical())


# -- the summary is inseparable from its grounding -----------------------


def test_a_summary_must_cite_at_least_one_piece_of_evidence():
    """The headline is the sentence a reader is most likely to quote."""
    with pytest.raises(ReasoningError, match="at least one"):
        ReasoningSummary(text="Two hypotheses agreed.", evidence_ids=())


def test_a_summary_must_not_cite_the_same_evidence_twice():
    with pytest.raises(ReasoningError, match="same evidence twice"):
        ReasoningSummary(text="x", evidence_ids=("fact:a", "fact:a"))


def test_summary_text_and_citations_are_one_record():
    """Grouping them removes the state where one exists without the other."""
    fields = {f.name for f in dataclasses.fields(ReasoningSnapshot)}
    assert "summary" in fields
    assert "summary_evidence_ids" not in fields
    assert {f.name for f in dataclasses.fields(ReasoningSummary)} == {
        "text", "evidence_ids",
    }


def test_a_snapshot_refuses_a_bare_string_summary():
    with pytest.raises(ReasoningError, match="ReasoningSummary"):
        ReasoningSnapshot(
            reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, symbol="AAPL",
            data_cutoff=T0, evidence_fingerprint="e", reasoning_fingerprint="r",
            prompt_id="p", prompt_version=1, output_schema_version=1,
            summary="a bare string", claims=(), uncertainties=(),
            usage=usage(), generated_at=T0,
        )


def test_missing_information_was_collapsed_into_uncertainties():
    """Two lists asked the model to make a distinction nothing could verify."""
    fields = {f.name for f in dataclasses.fields(ReasoningSnapshot)}
    assert "uncertainties" in fields
    assert "missing_information" not in fields


def test_the_snapshot_has_no_field_for_advice_or_limitations():
    """Known limits are deterministic UI text, not something a model restates."""
    fields = {f.name for f in dataclasses.fields(ReasoningSnapshot)}
    for forbidden in ("limitations", "recommendation", "target", "confidence",
                      "probability", "ranking", "action", "expected_return"):
        assert not any(forbidden in name for name in fields), forbidden
