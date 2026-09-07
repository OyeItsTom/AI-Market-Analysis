"""Phase 11A Stage B: nothing crosses into trusted state unvalidated.

Every payload here is a plain dict, constructed offline. No provider exists yet
and none is needed: the point is that a response is untrusted whatever produced
it, so the tests supply the hostile ones a provider might.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS, build_snapshot
from src.data.models import Interval
from src.reasoning.evidence import build_packet, evidence_fingerprint
from src.reasoning.models import (
    MAX_CLAIMS,
    MAX_EVIDENCE_IDS_PER_CLAIM,
    MAX_NOTES,
    MAX_REASONING_TEXT_CHARS,
    MAX_VALIDATION_DETAIL_CHARS,
    ProviderReasoningResponse,
    ReasoningFailureCode,
    ReasoningKind,
    ReasoningRequest,
    ReasoningSnapshot,
    ReasoningUsageMetadata,
)
from src.reasoning.prompts import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
)
from src.reasoning.validation import (
    ReasoningValidationError,
    find_boundary_violation,
    normalize_for_boundary,
    parse_payload,
    validate_provider_response,
)
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc


# -- fixtures ------------------------------------------------------------


@pytest.fixture
def packet():
    snapshot = build_snapshot(RecordingProvider(count=120), "AAPL", Interval.DAY_1)
    return build_packet(
        snapshot,
        now=snapshot.built_at + timedelta(seconds=1),
        minimum_sufficient_observations=MINIMUM_SUFFICIENT_OBSERVATIONS,
    )


@pytest.fixture
def request_for(packet):
    return ReasoningRequest(
        reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH, packet=packet,
        prompt_id=PROMPT_ID, prompt_version=PROMPT_VERSION,
        prompt_fingerprint=PROMPT_FINGERPRINT,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        provider="fake", model="fake-1",
        created_at=packet.data_cutoff + timedelta(seconds=1),
    )


def usage(**overrides) -> ReasoningUsageMetadata:
    fields = {"provider": "fake", "model": "fake-1", "input_tokens": 100,
              "output_tokens": 50, "latency_ms": 900, "attempt_count": 1}
    fields.update(overrides)
    return ReasoningUsageMetadata(**fields)


def valid_payload(packet, **overrides):
    """A well-formed response grounded in the supplied packet."""
    observation = packet.observations[0]
    body = {
        "summary": {
            "text": "Two hypotheses classified the trend upward and one was neutral.",
            "evidence_ids": ["fact:assessment-state", "fact:assessment-counts"],
        },
        "claims": [
            {
                "text": "The trend hypothesis read the faster average above the slower.",
                "evidence_ids": [observation.evidence_id],
            },
            {
                "text": "One hypothesis reported no directional reading.",
                "evidence_ids": [packet.observations[-1].evidence_id],
            },
        ],
        "uncertainties": [
            "The supplied evidence does not establish how this behaves outside "
            "the observed hypothesis set.",
        ],
    }
    body.update(overrides)
    return body


def respond(packet, **overrides):
    return ProviderReasoningResponse(payload=valid_payload(packet, **overrides),
                                     usage=usage())


def convert(request, response=None, **kwargs):
    packet = request.packet
    stamp = kwargs.pop("generated_at", packet.data_cutoff + timedelta(seconds=5))
    return validate_provider_response(
        request, response if response is not None else respond(packet),
        generated_at=stamp,
    )


# -- P1: the supported path ----------------------------------------------


def test_p1_a_valid_explanation_becomes_a_trusted_snapshot(request_for):
    snapshot = convert(request_for)
    assert isinstance(snapshot, ReasoningSnapshot)
    assert snapshot.symbol == request_for.packet.symbol
    assert snapshot.summary.text.startswith("Two hypotheses")
    assert len(snapshot.claims) == 2
    assert len(snapshot.uncertainties) == 1


def test_every_cited_id_survives_into_the_snapshot(request_for):
    snapshot = convert(request_for)
    assert snapshot.cited_evidence_ids <= request_for.packet.evidence_ids


# -- P2-P5: the other assessment shapes ----------------------------------


@pytest.mark.parametrize("state", ["conflicted", "neutral", "insufficient_data"])
def test_p2_p4_non_directional_assessments_are_supported(request_for, state):
    """A conflicted or neutral aggregate is still explicable. A validator that
    demanded a direction would reject the cases most worth explaining."""
    packet = dataclasses.replace(request_for.packet, assessment_state=state)
    request = dataclasses.replace(request_for, packet=packet)
    assert convert(request).summary.text


def test_p5_an_absent_assessment_is_mechanically_validatable(request_for):
    """Stage E will not offer the action for such a packet; Stage B still must
    not crash if a fixture builds one."""
    packet = dataclasses.replace(
        request_for.packet, assessment_state=None, counts=None,
        assessment_reason_codes=(),
    )
    request = dataclasses.replace(request_for, packet=packet)
    payload = valid_payload(packet, summary={
        "text": "The supplied research produced no combined assessment.",
        "evidence_ids": [f"fact:policy:{packet.policy_fingerprint}"],
    })
    snapshot = convert(request, ProviderReasoningResponse(payload=payload,
                                                          usage=usage()))
    assert snapshot.summary.evidence_ids == (
        f"fact:policy:{packet.policy_fingerprint}",
    )


def test_citing_an_assessment_fact_that_is_absent_is_refused(request_for):
    packet = dataclasses.replace(
        request_for.packet, assessment_state=None, counts=None,
        assessment_reason_codes=(),
    )
    request = dataclasses.replace(request_for, packet=packet)
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request, ProviderReasoningResponse(payload=valid_payload(packet),
                                                    usage=usage()))
    assert caught.value.code is ReasoningFailureCode.GROUNDING_FAILED


# -- P6-P8: grounding ----------------------------------------------------


def test_p6_an_unknown_citation_fails_grounding(request_for):
    payload = valid_payload(request_for.packet,
                            summary={"text": "x", "evidence_ids": ["obs:invented:v1:zz"]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.GROUNDING_FAILED


def test_one_bad_citation_fails_the_whole_response(request_for):
    """No partial acceptance: a result willing to invent one id is not
    four-fifths trustworthy."""
    packet = request_for.packet
    payload = valid_payload(packet)
    payload["claims"][1]["evidence_ids"] = ["obs:invented:v1:zz"]
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.GROUNDING_FAILED


def test_a_citation_from_another_packet_fails(request_for):
    """An id that is valid *somewhere* is still invalid here.

    The second packet is given a different policy fingerprint deliberately: the
    two fixtures share an ensemble, so without that they would legitimately
    share the policy id and the test would prove nothing.
    """
    other = dataclasses.replace(request_for.packet,
                                policy_fingerprint="0" * 16)
    foreign = f"fact:policy:{other.policy_fingerprint}"
    assert foreign in other.evidence_ids
    assert foreign not in request_for.packet.evidence_ids
    payload = valid_payload(request_for.packet,
                            summary={"text": "x", "evidence_ids": [foreign]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.GROUNDING_FAILED


def test_p7_a_duplicate_citation_is_a_schema_failure(request_for):
    payload = valid_payload(
        request_for.packet,
        summary={"text": "x", "evidence_ids": ["fact:assessment-state"] * 2},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_p8_an_empty_citation_list_is_refused(request_for):
    payload = valid_payload(request_for.packet,
                            summary={"text": "x", "evidence_ids": []})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


# -- P9-P10, P16-P18: strict schema --------------------------------------


def test_p9_an_obsolete_claim_type_field_is_rejected(request_for):
    """The field a previous draft carried is now an unknown key, not a value to
    ignore."""
    payload = valid_payload(request_for.packet)
    payload["claims"][0]["claim_type"] = "supporting"
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


@pytest.mark.parametrize("field", [
    "confidence", "probability", "target_price", "recommendation",
    "instruction", "url", "system_prompt", "trade", "action",
])
def test_p10_p16_p18_any_unknown_top_level_field_is_rejected(request_for, field):
    """Rejected, never dropped -- a model that starts emitting `confidence`
    must fail loudly rather than have it quietly discarded."""
    payload = valid_payload(request_for.packet)
    payload[field] = "anything"
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_p19_an_unknown_nested_summary_key_is_rejected(request_for):
    payload = valid_payload(
        request_for.packet,
        summary={"text": "x", "evidence_ids": ["fact:assessment-state"],
                 "confidence": 0.9},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_a_missing_top_level_key_is_rejected(request_for):
    for key in ("summary", "claims", "uncertainties"):
        payload = valid_payload(request_for.packet)
        del payload[key]
        with pytest.raises(ReasoningValidationError) as caught:
            convert(request_for,
                    ProviderReasoningResponse(payload=payload, usage=usage()))
        assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


@pytest.mark.parametrize("payload", [
    "not an object", 42, ["a", "list"], None,
])
def test_a_non_object_payload_is_rejected(payload):
    with pytest.raises(ReasoningValidationError):
        parse_payload(payload)


def test_wrong_types_are_rejected(request_for):
    packet = request_for.packet
    for bad in (
        {"summary": "a string"},
        {"claims": {"not": "a list"}},
        {"uncertainties": "a string"},
    ):
        payload = valid_payload(packet, **bad)
        with pytest.raises(ReasoningValidationError) as caught:
            convert(request_for,
                    ProviderReasoningResponse(payload=payload, usage=usage()))
        assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_a_bool_is_not_accepted_as_text(request_for):
    payload = valid_payload(request_for.packet,
                            summary={"text": True,
                                     "evidence_ids": ["fact:assessment-state"]})
    with pytest.raises(ReasoningValidationError):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


def test_empty_text_is_rejected(request_for):
    payload = valid_payload(request_for.packet,
                            summary={"text": "   ",
                                     "evidence_ids": ["fact:assessment-state"]})
    with pytest.raises(ReasoningValidationError, match="empty"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


# -- P11-P12: caps -------------------------------------------------------


def test_p11_an_oversized_summary_is_rejected(request_for):
    payload = valid_payload(
        request_for.packet,
        summary={"text": "x" * (MAX_REASONING_TEXT_CHARS + 1),
                 "evidence_ids": ["fact:assessment-state"]},
    )
    with pytest.raises(ReasoningValidationError, match="exceeds"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


def test_p12_too_many_claims_are_rejected(request_for):
    one = {"text": "a point", "evidence_ids": ["fact:assessment-state"]}
    payload = valid_payload(request_for.packet,
                            claims=[dict(one, text=f"point {i}")
                                    for i in range(MAX_CLAIMS + 1)])
    with pytest.raises(ReasoningValidationError, match="more than"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


def test_too_many_uncertainties_are_rejected(request_for):
    payload = valid_payload(request_for.packet,
                            uncertainties=[f"note {i}" for i in range(MAX_NOTES + 1)])
    with pytest.raises(ReasoningValidationError, match="more than"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


def test_too_many_citations_on_one_claim_are_rejected(request_for):
    payload = valid_payload(
        request_for.packet,
        summary={"text": "x",
                 "evidence_ids": [f"fact:reason:{i}"
                                  for i in range(MAX_EVIDENCE_IDS_PER_CLAIM + 1)]},
    )
    with pytest.raises(ReasoningValidationError, match="more than"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


# -- P13-P15: boundary language ------------------------------------------


@pytest.mark.parametrize("text", [
    "The evidence suggests you should buy.",
    "Consider selling this position.",
    "This is a strong buy.",
    "The target price is higher.",
    "A price target of 300 follows.",
    "Use a position size of two percent.",
    "The expected return is positive.",
    "Place a stop loss below the average.",
    "Take profit at the prior high.",
    "A good entry point appears here.",
    "The exit point is the slower average.",
    "The risk reward is favourable.",
    "Returns are guaranteed by this setup.",
    "Investors were buying heavily.",
    "The seller pressure eased.",
    "Allocate more to this name.",
    "Increase your allocation.",
    "Go overweight on this symbol.",
])
def test_p13_trading_vocabulary_is_refused(request_for, text):
    payload = valid_payload(request_for.packet,
                            summary={"text": text,
                                     "evidence_ids": ["fact:assessment-state"]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


@pytest.mark.parametrize("text", [
    "BUY", "Buy", "bUy", "b.u.y", "b-u-y", "b_u_y",
    "ＢＵＹ",                      # full-width, folded by NFKC
    "b​uy",                  # zero-width space
    "s­ell",                 # soft hyphen
])
def test_p14_p15_disguised_vocabulary_is_still_refused(request_for, text):
    payload = valid_payload(
        request_for.packet,
        summary={"text": f"The reading says {text} now.",
                 "evidence_ids": ["fact:assessment-state"]},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


def test_a_negated_recommendation_is_still_refused(request_for):
    """The disclaimer is rendered deterministically outside model output, so a
    model has no reason to use the vocabulary even to deny it."""
    payload = valid_payload(
        request_for.packet,
        summary={"text": "This is not a buy recommendation.",
                 "evidence_ids": ["fact:assessment-state"]},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


@pytest.mark.parametrize("text", [
    "The holding period of the moving average is twenty bars.",
    "Household names dominate this universe.",
    "The position of the faster average is above the slower.",
    "The return series was computed over fifty bars.",
    "Two hypotheses agree on direction and one abstains.",
    "The relationship between the averages was unchanged.",
    "Momentum was elevated relative to its own range.",
    "Data entry errors would show as validation failures.",
])
def test_innocent_wording_is_not_falsely_rejected(request_for, text):
    """Over-banning is its own failure: it would force explanations to be
    written worse to survive a validator."""
    payload = valid_payload(request_for.packet,
                            summary={"text": text,
                                     "evidence_ids": ["fact:assessment-state"]})
    assert convert(request_for,
                   ProviderReasoningResponse(payload=payload, usage=usage()))


def test_boundary_checking_covers_claims_and_uncertainties(request_for):
    packet = request_for.packet
    payload = valid_payload(packet)
    payload["claims"][0]["text"] = "The evidence says buy."
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION

    payload = valid_payload(packet,
                            uncertainties=["It is unclear whether to sell."])
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


def test_normalization_is_a_backstop_not_moderation():
    """Stated so nobody mistakes it for complete coverage.

    NFKC folds compatibility and full-width forms; it does not solve arbitrary
    cross-script homoglyphs, and no word list catches a recommendation phrased
    in words it does not contain.
    """
    assert normalize_for_boundary("ＢＵＹ") == "buy"
    assert normalize_for_boundary("b​u​y") == "buy"
    assert find_boundary_violation("this one looks like the one to own") is None


# -- consistency ---------------------------------------------------------


def test_an_exact_duplicate_claim_is_rejected(request_for):
    packet = request_for.packet
    one = {"text": "The same point.", "evidence_ids": [packet.observations[0].evidence_id]}
    payload = valid_payload(packet, claims=[dict(one), dict(one)])
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.GROUNDING_FAILED


def test_duplicate_detection_ignores_citation_order(request_for):
    packet = request_for.packet
    ids = ["fact:assessment-state", "fact:assessment-counts"]
    payload = valid_payload(packet, claims=[
        {"text": "The same point.", "evidence_ids": ids},
        {"text": "The same point.", "evidence_ids": list(reversed(ids))},
    ])
    with pytest.raises(ReasoningValidationError, match="repeats"):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))


def test_the_same_text_with_different_citations_is_allowed(request_for):
    packet = request_for.packet
    payload = valid_payload(packet, claims=[
        {"text": "A hypothesis classified directionally.",
         "evidence_ids": [packet.observations[0].evidence_id]},
        {"text": "A hypothesis classified directionally.",
         "evidence_ids": [packet.observations[1].evidence_id]},
    ])
    assert len(convert(request_for,
                       ProviderReasoningResponse(payload=payload,
                                                  usage=usage())).claims) == 2


def test_different_text_with_the_same_citations_is_allowed(request_for):
    packet = request_for.packet
    ids = [packet.observations[0].evidence_id]
    payload = valid_payload(packet, claims=[
        {"text": "The faster average sat above the slower.", "evidence_ids": ids},
        {"text": "That reading was recorded at the last settled bar.",
         "evidence_ids": ids},
    ])
    assert len(convert(request_for,
                       ProviderReasoningResponse(payload=payload,
                                                  usage=usage())).claims) == 2


def test_claim_order_is_preserved(request_for):
    packet = request_for.packet
    payload = valid_payload(packet, claims=[
        {"text": f"Point {i}.", "evidence_ids": ["fact:assessment-state"]}
        for i in range(4)
    ])
    snapshot = convert(request_for,
                       ProviderReasoningResponse(payload=payload, usage=usage()))
    assert [c.text for c in snapshot.claims] == [f"Point {i}." for i in range(4)]


# -- pipeline order ------------------------------------------------------


def test_boundary_language_is_checked_before_grounding(request_for):
    """A payload failing both reports the more serious class."""
    payload = valid_payload(
        request_for.packet,
        summary={"text": "You should buy.", "evidence_ids": ["obs:invented:v1:zz"]},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


def test_schema_is_checked_before_boundary_language(request_for):
    payload = valid_payload(request_for.packet,
                            summary={"text": "You should buy.",
                                     "evidence_ids": ["fact:assessment-state"]},
                            confidence=0.9)
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_no_snapshot_exists_when_any_check_fails(request_for, monkeypatch):
    """Construction is strictly last."""
    built: list[object] = []
    original = ReasoningSnapshot.__post_init__

    def spy(self):
        built.append(self)
        return original(self)

    monkeypatch.setattr(ReasoningSnapshot, "__post_init__", spy)
    payload = valid_payload(request_for.packet,
                            summary={"text": "You should buy.",
                                     "evidence_ids": ["fact:assessment-state"]})
    with pytest.raises(ReasoningValidationError):
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert built == []


# -- provenance ----------------------------------------------------------


def test_provenance_comes_from_the_request_not_the_payload(request_for):
    snapshot = convert(request_for)
    assert snapshot.prompt_id == PROMPT_ID
    assert snapshot.prompt_version == PROMPT_VERSION
    assert snapshot.output_schema_version == OUTPUT_SCHEMA_VERSION
    assert snapshot.reasoning_kind is ReasoningKind.EXPLAIN_RESEARCH
    assert snapshot.data_cutoff == request_for.packet.data_cutoff
    assert snapshot.evidence_fingerprint == evidence_fingerprint(request_for.packet)


def test_p20_a_reported_model_does_not_change_the_reasoning_fingerprint(request_for):
    """The fingerprint records what was asked for; a reported model is an
    observation, and Stage D decides what a mismatch means."""
    baseline = convert(request_for).reasoning_fingerprint
    mismatched = ProviderReasoningResponse(
        payload=valid_payload(request_for.packet),
        usage=usage(provider="other", model="a-different-model"),
    )
    snapshot = convert(request_for, mismatched)
    assert snapshot.reasoning_fingerprint == baseline
    assert snapshot.usage.model == "a-different-model"


def test_the_payload_cannot_supply_provenance(request_for):
    for key in ("prompt_version", "model", "provider", "evidence_fingerprint",
                "reasoning_fingerprint", "generated_at", "data_cutoff"):
        payload = valid_payload(request_for.packet)
        payload[key] = "forged"
        with pytest.raises(ReasoningValidationError) as caught:
            convert(request_for,
                    ProviderReasoningResponse(payload=payload, usage=usage()))
        assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


# -- generated_at --------------------------------------------------------


def test_generated_at_is_injected_and_normalised(request_for):
    stamp = request_for.packet.data_cutoff + timedelta(hours=3)
    other = stamp.astimezone(timezone(timedelta(hours=5)))
    assert convert(request_for, generated_at=other).generated_at == stamp


def test_generated_at_may_not_precede_the_cutoff(request_for):
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for,
                generated_at=request_for.packet.data_cutoff - timedelta(seconds=1))
    assert caught.value.code is ReasoningFailureCode.REQUEST_INVALID


def test_a_naive_generated_at_is_refused(request_for):
    from src.reasoning.models import ReasoningError

    with pytest.raises(ReasoningError, match="timezone-aware"):
        convert(request_for, generated_at=datetime(2030, 1, 1))


# -- usage ---------------------------------------------------------------


def test_p20_a_zero_attempt_count_is_refused(request_for):
    """A response that arrived took at least one attempt."""
    bad = ProviderReasoningResponse(payload=valid_payload(request_for.packet),
                                    usage=usage(attempt_count=0))
    with pytest.raises(ReasoningValidationError, match="attempt_count"):
        convert(request_for, bad)


def test_malformed_usage_is_refused_at_construction():
    from src.reasoning.models import ReasoningError

    for bad in ({"input_tokens": -1}, {"latency_ms": -5}, {"provider": "  "}):
        with pytest.raises(ReasoningError):
            usage(**bad)


def test_usage_must_be_the_right_type(request_for):
    with pytest.raises(Exception):
        ProviderReasoningResponse(payload=valid_payload(request_for.packet),
                                  usage={"provider": "fake"})


# -- non-retention -------------------------------------------------------


def _reachable(value, depth=0, seen=None):
    seen = seen if seen is not None else set()
    if depth > 6 or id(value) in seen:
        return
    seen.add(id(value))
    yield value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from _reachable(getattr(value, f.name), depth + 1, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _reachable(item, depth + 1, seen)
    elif hasattr(value, "items") and not isinstance(value, (str, bytes)):
        for key, item in value.items():
            yield from _reachable(key, depth + 1, seen)
            yield from _reachable(item, depth + 1, seen)


def test_the_snapshot_retains_no_raw_provider_object(request_for):
    """Nothing unvalidated survives the conversion."""
    response = respond(request_for.packet)
    snapshot = convert(request_for, response)
    reachable = list(_reachable(snapshot))
    assert not any(v is response for v in reachable)
    assert not any(v is response.payload for v in reachable)
    assert not any(isinstance(v, ProviderReasoningResponse) for v in reachable)


def test_the_snapshot_holds_no_mapping_from_the_payload(request_for):
    snapshot = convert(request_for)
    mappings = [v for v in _reachable(snapshot)
                if hasattr(v, "items") and not isinstance(v, (str, bytes))]
    assert mappings == []


# -- failure detail ------------------------------------------------------


def test_failure_detail_is_bounded_and_quotes_no_payload_text(request_for):
    secret = "SECRETPAYLOAD" + "y" * 500
    payload = valid_payload(request_for.packet,
                            summary={"text": secret + " buy",
                                     "evidence_ids": ["fact:assessment-state"]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    detail = caught.value.detail
    assert len(detail) <= MAX_VALIDATION_DETAIL_CHARS
    assert "SECRETPAYLOAD" not in detail
    assert "summary.text" in detail


def test_a_validation_error_carries_a_typed_code(request_for):
    payload = valid_payload(request_for.packet)
    payload["extra"] = 1
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert isinstance(caught.value.code, ReasoningFailureCode)
    assert caught.value.code.is_operational is False


# -- construction ownership ----------------------------------------------


def test_only_validation_constructs_a_trusted_snapshot():
    """Python cannot make a constructor private, so this is the enforcement.

    Stated honestly rather than dressed up: the type split is real, but nothing
    at runtime stops a caller building a snapshot directly. This test does.
    """
    offenders = []
    for path in sorted(pathlib.Path("src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "ReasoningSnapshot"):
                offenders.append(str(path))
    assert offenders == ["src/reasoning/validation.py"], offenders


def test_a_long_failure_detail_is_actually_truncated(request_for):
    """The bound must bite, not merely be declared.

    Unknown keys are named in the detail so a reader can fix the adapter, and a
    payload carrying many long ones would otherwise produce an unbounded
    message -- attacker-chosen text arriving in a log by another route.
    """
    payload = valid_payload(request_for.packet)
    for index in range(20):
        payload[f"unexpected_field_with_a_very_long_name_{index:02d}"] = 1
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    detail = caught.value.detail
    assert len(detail) == MAX_VALIDATION_DETAIL_CHARS
    assert "unexpected_field_with_a_very_long_name_00" in detail
    assert "unexpected_field_with_a_very_long_name_19" not in detail


def test_the_error_message_is_bounded_too(request_for):
    payload = valid_payload(request_for.packet)
    for index in range(20):
        payload[f"unexpected_field_with_a_very_long_name_{index:02d}"] = 1
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    code_prefix = len(caught.value.code.value) + 2
    assert len(str(caught.value)) <= MAX_VALIDATION_DETAIL_CHARS + code_prefix


# -- grounding is exact membership, not a fuzzy match ---------------------


@pytest.mark.parametrize("mangled", [
    " {id} ", "{id} ", " {id}", "\t{id}", "{id}\n",
])
def test_a_padded_evidence_id_is_refused_rather_than_repaired(request_for, mangled):
    """An id is an identifier, not prose.

    Trimming it before comparison would make grounding a normalised match
    rather than exact membership, and quietly repairing provider output is what
    this layer refuses to do everywhere else.
    """
    real = request_for.packet.observations[0].evidence_id
    payload = valid_payload(request_for.packet,
                            summary={"text": "x",
                                     "evidence_ids": [mangled.format(id=real)]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


@pytest.mark.parametrize("transform", [
    lambda i: i.upper(),
    lambda i: i[:-4],
    lambda i: i + "X",
    lambda i: i + "#not_a_feature",
    lambda i: i.replace("o", "о", 1),
])
def test_grounding_does_no_prefix_case_or_lookalike_matching(request_for, transform):
    real = request_for.packet.observations[0].evidence_id
    payload = valid_payload(request_for.packet,
                            summary={"text": "x", "evidence_ids": [transform(real)]})
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code in {
        ReasoningFailureCode.GROUNDING_FAILED,
        ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
    }


# -- obfuscation: every separator class an evasion would reach for --------


@pytest.mark.parametrize("spelling", [
    "b.u.y", "b-u-y", "b_u_y", "b/u/y", "b|u|y", "b+u+y", "b~u~y",
    "b(u)y", "b[u]y", "b{u}y", "b:u:y", "b;u;y", "b,u,y", "b'u'y",
    "b!u!y", "b?u?y", "b@u@y", "b#u#y",
    "B U Y", "b u y", "s e l l",
])
def test_punctuation_and_spacing_evasions_are_caught(request_for, spelling):
    payload = valid_payload(
        request_for.packet,
        summary={"text": f"the reading says {spelling}",
                 "evidence_ids": ["fact:assessment-state"]},
    )
    with pytest.raises(ReasoningValidationError) as caught:
        convert(request_for, ProviderReasoningResponse(payload=payload, usage=usage()))
    assert caught.value.code is ReasoningFailureCode.BOUNDARY_VIOLATION


@pytest.mark.parametrize("text", [
    "RSI(14) was elevated; SMA(20) sat above SMA(50).",
    "The holding period was one session, and the return series was volatile.",
    "Data entry errors were present, so the relative position was unclear.",
    "Two hypotheses agree on direction; one abstained.",
])
def test_separator_folding_does_not_corrupt_ordinary_prose(request_for, text):
    """Only punctuation that never appears inside a word is folded, and only
    runs of single characters are joined, so real sentences are untouched."""
    payload = valid_payload(request_for.packet,
                            summary={"text": text,
                                     "evidence_ids": ["fact:assessment-state"]})
    assert convert(request_for,
                   ProviderReasoningResponse(payload=payload, usage=usage()))
