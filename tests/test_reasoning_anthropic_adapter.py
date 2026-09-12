"""Phase 11A Stage D: the first real adapter, exercised entirely offline.

Every test here runs against a hand-built double of the vendor client. Nothing
opens a socket, nothing reads a credential, and no call is ever paid for. What
is *not* faked is the exception hierarchy: the mapping tests raise the real SDK
classes, constructed locally, because a test that asserted a mapping against
look-alike exceptions would prove only that the look-alikes were spelled right.

The point of the suite is the boundary rather than the plumbing. A provider that
quietly repaired an answer, graded one, retried one, or filed it under the wrong
model would still pass a naive happy-path test; each of those has a test here
whose only job is to fail if it starts happening.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import pathlib
import time
import traceback
from datetime import timedelta

import anthropic
import httpx2
import pytest

from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS, build_snapshot
from src.data.models import Interval
from src.reasoning.anthropic_adapter import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_ID,
    AnthropicReasoningProvider,
)
from src.reasoning.evidence import build_packet, evidence_fingerprint
from src.reasoning.models import (
    ProviderReasoningResponse,
    ReasoningError,
    ReasoningFailureCode,
    ReasoningKind,
    ReasoningRequest,
    ReasoningSnapshot,
    ReasoningUsageMetadata,
)
from src.reasoning.prompts import (
    OUTPUT_SCHEMA,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
    SYSTEM_POLICY,
    TASK_INSTRUCTION,
    evidence_for_model,
)
from src.reasoning.providers import ReasoningProvider, ReasoningProviderError
from src.reasoning.validation import ReasoningValidationError, validate_provider_response
from tests.test_application_snapshot import RecordingProvider
from tests.test_reasoning_validation import valid_payload

MODEL_ID = "claude-test-1"
SERVED_MODEL = "claude-test-1-20260101"

#: A value that must never reach a caller. It is planted in vendor exception
#: messages so the leak tests have something unambiguous to look for.
LEAK_MARKER = "marker-do-not-leak-9137"


# -- the double ----------------------------------------------------------


class FakeUsage:
    def __init__(self, input_tokens=1200, output_tokens=340):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeThinkingBlock:
    def __init__(self):
        self.type = "thinking"


#: Distinguishes "the test did not configure usage" from "the response carried
#: no usage at all". Collapsing the two would have made the absent-usage case
#: silently test the happy path instead.
_UNSET = object()


class FakeMessage:
    """Only the fields the adapter actually reads."""

    def __init__(self, *, content=None, model=SERVED_MODEL, usage=_UNSET):
        self.content = content
        self.model = model
        self.usage = FakeUsage() if usage is _UNSET else usage


class FakeAnthropicClient:
    """Records how it was configured and what it was asked, and answers once."""

    def __init__(self, *, message=None, error=None):
        self._message = message
        self._error = error
        self.options: list[dict] = []
        self.calls: list[dict] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return _ConfiguredClient(self)


class _ConfiguredClient:
    def __init__(self, client):
        self._client = client

    @property
    def messages(self):
        return _FakeMessages(self._client)


class _FakeMessages:
    def __init__(self, client):
        self._client = client

    def create(self, **body):
        self._client.calls.append(body)
        if self._client._error is not None:
            raise self._client._error
        return self._client._message


def answering(text, *, model=SERVED_MODEL, usage=_UNSET):
    """A client that returns one text block containing ``text``."""
    return FakeAnthropicClient(
        message=FakeMessage(content=[FakeTextBlock(text)], model=model, usage=usage)
    )


def failing(error):
    return FakeAnthropicClient(error=error)


def vendor_request():
    return httpx2.Request("POST", "https://api.example.invalid/v1/messages")


def vendor_response(status):
    return httpx2.Response(status, request=vendor_request())


def status_error(cls, status):
    return cls(LEAK_MARKER, response=vendor_response(status), body={"x": LEAK_MARKER})


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
        provider=PROVIDER_ID, model=MODEL_ID,
        created_at=packet.data_cutoff + timedelta(seconds=1),
    )


def adapter(client, **overrides):
    fields = {"model_id": MODEL_ID, "clock": iter([0.0, 1.25]).__next__}
    fields.update(overrides)
    return AnthropicReasoningProvider(client, **fields)


def convert(request, response):
    return validate_provider_response(
        request, response,
        generated_at=request.packet.data_cutoff + timedelta(seconds=5),
    )


# -- the Protocol --------------------------------------------------------


def test_the_adapter_matches_the_committed_protocol():
    provider = adapter(FakeAnthropicClient())
    assert isinstance(inspect.getattr_static(AnthropicReasoningProvider,
                                             "provider_id"), property)
    assert isinstance(inspect.getattr_static(AnthropicReasoningProvider,
                                             "model_id"), property)
    kinds = {
        name: parameter.kind
        for name, parameter
        in inspect.signature(AnthropicReasoningProvider.generate).parameters.items()
    }
    assert kinds == {
        "self": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "request": inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    assert set(inspect.signature(ReasoningProvider.generate).parameters) == set(kinds)
    assert provider.provider_id == PROVIDER_ID
    assert provider.model_id == MODEL_ID


def test_the_constructor_takes_no_credential():
    """The strongest available position: there is nowhere to put a key."""
    parameters = set(
        inspect.signature(AnthropicReasoningProvider.__init__).parameters
    )
    assert parameters == {"self", "client", "model_id", "provider_id",
                          "timeout_seconds", "max_tokens", "clock"}


def test_the_default_clock_is_monotonic():
    """A wall clock measures the time of day, not a duration.

    Every test injects a clock, so nothing else here would notice the default
    quietly becoming ``time.time`` -- and a latency computed from a wall clock
    is wrong exactly when it matters, on the machine that adjusts its time
    mid-call.
    """
    assert inspect.signature(
        AnthropicReasoningProvider.__init__
    ).parameters["clock"].default is time.monotonic


def test_a_falsy_client_is_used_rather_than_replaced(request_for):
    """``self._client = client or Anthropic()`` is the accident this forbids.

    It reads as a harmless default and is not one: any client object that is
    falsy -- an empty container, a double with ``__bool__`` -- would be swapped
    for a real one that reads a credential and opens a connection. The ``None``
    guard does not cover it, because ``None`` is rejected earlier.
    """
    class FalsyClient(FakeAnthropicClient):
        def __bool__(self):
            return False

    client = FalsyClient()
    provider = AnthropicReasoningProvider(client, model_id=MODEL_ID)
    with pytest.raises(ReasoningProviderError):
        provider.generate({"not": "a request"})
    assert provider._client is client


def test_an_injected_client_is_required():
    with pytest.raises(ReasoningError, match="injected"):
        AnthropicReasoningProvider(None, model_id=MODEL_ID)


@pytest.mark.parametrize("overrides", [
    {"model_id": ""}, {"model_id": 7}, {"provider_id": ""},
    {"timeout_seconds": 0}, {"timeout_seconds": -1}, {"timeout_seconds": True},
    {"timeout_seconds": 10_000}, {"max_tokens": 0}, {"max_tokens": True},
    {"max_tokens": 10 ** 9}, {"max_tokens": 1.5}, {"clock": "not callable"},
])
def test_operational_configuration_is_validated(overrides):
    with pytest.raises(ReasoningError):
        adapter(FakeAnthropicClient(), **overrides)


# -- D1: the whole chain -------------------------------------------------


def test_d1_a_valid_answer_reaches_a_trusted_snapshot(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    response = adapter(client).generate(request_for)

    assert isinstance(response, ProviderReasoningResponse)
    assert dict(response.payload) == valid_payload(packet)

    snapshot = convert(request_for, response)
    assert isinstance(snapshot, ReasoningSnapshot)
    assert snapshot.symbol == packet.symbol
    assert snapshot.cited_evidence_ids <= packet.evidence_ids
    assert snapshot.usage.attempt_count == 1
    assert snapshot.usage.latency_ms == 1250


# -- D2, D3, D4, D5: schema-shaped answers still face the validator -------


def _case(packet, mutate):
    body = valid_payload(packet)
    mutate(body)
    return body


def _forbidden(body):
    body["claims"][0]["text"] = "The evidence supports a strong buy here."


def _fabricated(body):
    body["claims"][0]["evidence_ids"] = ["obs:invented:v1:deadbeef"]


def _extra_field(body):
    body["confidence"] = 0.93


def _empty_citation(body):
    body["summary"]["evidence_ids"] = []


@pytest.mark.parametrize("mutate,expected", [
    (_forbidden, ReasoningFailureCode.BOUNDARY_VIOLATION),
    (_fabricated, ReasoningFailureCode.GROUNDING_FAILED),
    (_extra_field, ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
    (_empty_citation, ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
], ids=["d2_forbidden", "d3_fabricated", "d4_extra_field", "d5_empty_citation"])
def test_d2_to_d5_the_adapter_passes_bad_answers_through_intact(mutate, expected,
                                                                packet, request_for):
    """Schema-constrained output is not trusted output.

    The service can be asked for a shape and still return prose that recommends
    a trade or cites evidence that does not exist. The adapter returns all of it
    untouched; refusing is somebody else's job, and this is what proves the
    adapter is not quietly doing that job badly.
    """
    body = _case(packet, mutate)
    client = answering(json.dumps(body))
    response = adapter(client).generate(request_for)

    assert client.call_count == 1
    assert dict(response.payload) == body, "the adapter altered the answer"

    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, response)
    assert raised.value.code is expected


# -- D6-D11: a successful call with an unusable answer --------------------


@pytest.mark.parametrize("text", [
    "{not json at all",
    "",
    "[]",
    '"a plain string"',
    "123",
    "null",
    "Here is your explanation, in prose.",
], ids=["d6_invalid_json", "d7_empty", "d8_array", "d9_string", "d9_number",
        "d10_null", "d6_prose"])
def test_d6_to_d10_unusable_output_is_a_successful_call_with_an_empty_payload(
    text, request_for
):
    """The distinction this preserves is the whole reason for the split.

    The call completed and cost tokens, so reporting it as an outage would be a
    lie; the answer is unusable, so returning it as if it were content would be
    a worse one. An empty payload says exactly what happened, and the validator
    says what it means.
    """
    client = answering(text)
    response = adapter(client).generate(request_for)

    assert client.call_count == 1
    assert dict(response.payload) == {}
    assert response.usage.input_tokens == 1200
    assert response.usage.output_tokens == 340

    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, response)
    assert raised.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


@pytest.mark.parametrize("content", [[], [FakeThinkingBlock()]],
                         ids=["d11_no_blocks", "d11_no_text_block"])
def test_d11_a_response_with_no_readable_text_is_also_an_empty_payload(content,
                                                                       request_for):
    client = FakeAnthropicClient(message=FakeMessage(content=content))
    response = adapter(client).generate(request_for)
    assert dict(response.payload) == {}


def test_the_unusable_text_is_not_kept_anywhere(request_for):
    """A rejected answer that survives in a record gets a second chance at the
    reader it was rejected to protect."""
    client = answering(f"prose containing {LEAK_MARKER}")
    response = adapter(client).generate(request_for)
    assert LEAK_MARKER not in repr(dict(response.payload))
    assert LEAK_MARKER not in repr(response.usage)


def test_the_first_text_block_is_the_answer_and_later_blocks_get_no_vote(
    packet, request_for
):
    """A locked rule, because every alternative is a search.

    Taking the first block that *parses* would find a plausible answer inside a
    response that did not contain one; joining the text blocks would invent a
    document the model never emitted. Both look like robustness and both make
    the adapter decide what the answer was.
    """
    usable = json.dumps(valid_payload(packet))

    # A leading non-text block is skipped -- it is not an answer, so it is not
    # the first text block.
    skipped = FakeAnthropicClient(message=FakeMessage(
        content=[FakeThinkingBlock(), FakeTextBlock(usable)]))
    assert dict(adapter(skipped).generate(request_for).payload) == valid_payload(packet)

    # An unusable *first text block* ends it, even though a later text block
    # would have parsed. Searching on would find an answer the response did not
    # give in the place it gave it.
    shadowed = FakeAnthropicClient(message=FakeMessage(
        content=[FakeTextBlock("not json"), FakeTextBlock(usable)]))
    assert dict(adapter(shadowed).generate(request_for).payload) == {}

    # And a usable first block is not spoiled by whatever follows it. This is
    # the case that separates "first text block" from "join the text blocks":
    # joining would append the trailing block and leave invalid JSON.
    trailed = FakeAnthropicClient(message=FakeMessage(
        content=[FakeTextBlock(usable), FakeTextBlock("trailing prose")]))
    assert dict(adapter(trailed).generate(request_for).payload) == valid_payload(packet)

    # Two blocks that both parse: the first one is the answer, and the choice is
    # observable rather than a coincidence of equal values.
    second = dict(valid_payload(packet))
    second["uncertainties"] = ["a different second block"]
    both = FakeAnthropicClient(message=FakeMessage(
        content=[FakeTextBlock(usable), FakeTextBlock(json.dumps(second))]))
    assert dict(adapter(both).generate(request_for).payload) == valid_payload(packet)


@pytest.mark.parametrize("block", [
    FakeTextBlock(None), FakeTextBlock(b"{}"), FakeTextBlock(123),
], ids=["text-none", "text-bytes", "text-int"])
def test_a_text_block_whose_text_is_not_a_string_is_unusable(block, request_for):
    client = FakeAnthropicClient(message=FakeMessage(content=[block]))
    assert dict(adapter(client).generate(request_for).payload) == {}


def test_a_block_without_a_type_is_not_a_text_block(packet, request_for):
    """It carries a *usable* payload on purpose.

    An untyped block holding ``{}`` would be indistinguishable from the empty
    fallback, so the test would pass whether the block was read or skipped.
    Giving it a real answer makes the difference visible.
    """
    class Untyped:
        text = json.dumps(valid_payload(packet))

    client = FakeAnthropicClient(message=FakeMessage(content=[Untyped()]))
    assert dict(adapter(client).generate(request_for).payload) == {}


def test_a_tuple_of_blocks_is_read_the_same_way(packet, request_for):
    client = FakeAnthropicClient(message=FakeMessage(
        content=(FakeTextBlock(json.dumps(valid_payload(packet))),)))
    assert dict(adapter(client).generate(request_for).payload) == valid_payload(packet)


# -- D12: a shape we cannot read at all -----------------------------------


@pytest.mark.parametrize("content", [None, "a bare string", 42],
                         ids=["none", "str", "int"])
def test_d12_an_unreadable_response_shape_is_an_integration_failure(content,
                                                                    request_for):
    """Different from an unusable answer, and deliberately so.

    "The model wrote nonsense" is routine. "The response object is not the shape
    this adapter was written against" means our integration assumption is
    broken -- most likely a library upgrade -- and quietly turning that into an
    empty payload would report a code defect as a bad answer.
    """
    client = FakeAnthropicClient(message=FakeMessage(content=content))
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client).generate(request_for)
    assert raised.value.code is ReasoningFailureCode.UNEXPECTED


# -- D13, D14, D15: identity is checked before anything is spent ----------


def test_d13_a_request_for_another_provider_never_reaches_the_service(packet,
                                                                      request_for):
    client = FakeAnthropicClient()
    provider = adapter(client, provider_id="somebody-else")
    with pytest.raises(ReasoningProviderError) as raised:
        provider.generate(request_for)
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID
    assert client.call_count == 0
    assert client.options == []


def test_d14_a_request_for_another_model_never_reaches_the_service(request_for):
    client = FakeAnthropicClient()
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client, model_id="a-different-model").generate(request_for)
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID
    assert client.call_count == 0


@pytest.mark.parametrize("configured", [
    MODEL_ID.upper(), MODEL_ID.capitalize(), MODEL_ID.replace("-", "_"),
    MODEL_ID + "-1", MODEL_ID[:-1],
], ids=["upper", "capitalised", "underscored", "suffixed", "truncated"])
def test_a_near_miss_model_id_is_still_a_mismatch(configured, request_for):
    """Exact equality, with no normalisation on either side.

    Casefolding or trimming the comparison would let a near-miss through, and
    the answer would then be filed under the id in the request -- the one the
    reasoning fingerprint is built from -- while a differently-spelled model had
    actually been asked. A tolerant comparison here buys nothing: both sides are
    our own configuration, so a near miss is a wiring mistake, not a variant.
    """
    client = FakeAnthropicClient()
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client, model_id=configured).generate(request_for)
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID
    assert client.call_count == 0


@pytest.mark.parametrize("configured", ["ANTHROPIC", "Anthropic", "anthropic2"],
                         ids=["upper", "capitalised", "suffixed"])
def test_a_near_miss_provider_id_is_still_a_mismatch(configured, request_for):
    client = FakeAnthropicClient()
    with pytest.raises(ReasoningProviderError):
        adapter(client, provider_id=configured).generate(request_for)
    assert client.call_count == 0


def test_surrounding_whitespace_is_not_a_near_miss_because_it_never_survives(
    packet, request_for
):
    """Padding is canonicalised by the domain, on both sides, before comparison.

    This is not tolerance in the adapter and must not be mistaken for it. Both
    ``ReasoningRequest.model`` and the adapter's ``model_id`` go through the
    same bounded-text helper, which strips -- so a padded id is not a second
    identity that the comparison forgives, it is the same identity spelled
    loosely, and it has already been rewritten to the canonical form by the time
    either object exists. Case, by contrast, is preserved and does mismatch.
    """
    provider = adapter(answering(json.dumps(valid_payload(packet))),
                       model_id=f"  {MODEL_ID}  ", provider_id=f" {PROVIDER_ID} ")
    assert provider.model_id == MODEL_ID
    assert provider.provider_id == PROVIDER_ID
    assert isinstance(provider.generate(request_for), ProviderReasoningResponse)


def test_d15_a_non_request_never_reaches_the_service():
    client = FakeAnthropicClient()
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client).generate({"packet": "please"})
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID
    assert client.call_count == 0


def test_identity_is_never_rewritten_to_make_it_match(packet, request_for):
    before = {f.name: getattr(request_for, f.name)
              for f in dataclasses.fields(request_for)}
    client = answering(json.dumps(valid_payload(packet)))
    adapter(client).generate(request_for)
    after = {f.name: getattr(request_for, f.name)
             for f in dataclasses.fields(request_for)}
    assert before == after
    assert after["packet"] is packet


# -- D16: the served model is recorded, not policed ------------------------


def test_d16_a_served_model_that_differs_is_recorded_and_not_an_error(packet,
                                                                      request_for):
    """An alias resolving to a pinned version is ordinary.

    Failing on it would turn every alias into an outage; filing the answer under
    the name we asked for would be quietly wrong. Recording what actually
    answered is the only honest option.
    """
    client = answering(json.dumps(valid_payload(packet)), model=SERVED_MODEL)
    response = adapter(client).generate(request_for)
    assert response.usage.model == SERVED_MODEL
    assert response.usage.provider == PROVIDER_ID
    assert request_for.model == MODEL_ID


@pytest.mark.parametrize("served", [None, "", "   ", 7],
                         ids=["missing", "empty", "blank", "wrong-type"])
def test_an_unreported_served_model_falls_back_to_the_configured_one(served, packet,
                                                                     request_for):
    client = answering(json.dumps(valid_payload(packet)), model=served)
    assert adapter(client).generate(request_for).usage.model == MODEL_ID


def test_the_reasoning_fingerprint_follows_the_request_not_the_served_model(
    packet, request_for
):
    body = json.dumps(valid_payload(packet))
    first = convert(request_for, adapter(answering(body, model="served-a"))
                    .generate(request_for))
    second = convert(request_for, adapter(answering(body, model="served-b"))
                     .generate(request_for))
    assert first.reasoning_fingerprint == second.reasoning_fingerprint
    assert first.usage.model != second.usage.model


# -- D17-D27: vendor failures, mapped from the real classes ---------------


@pytest.mark.parametrize("error,expected", [
    (status_error(anthropic.AuthenticationError, 401),
     ReasoningFailureCode.AUTHENTICATION_FAILED),
    (status_error(anthropic.PermissionDeniedError, 403),
     ReasoningFailureCode.AUTHENTICATION_FAILED),
    (status_error(anthropic.RateLimitError, 429),
     ReasoningFailureCode.RATE_LIMITED),
    (anthropic.APIConnectionError(message=LEAK_MARKER, request=vendor_request()),
     ReasoningFailureCode.PROVIDER_UNAVAILABLE),
    (anthropic.APITimeoutError(request=vendor_request()),
     ReasoningFailureCode.PROVIDER_UNAVAILABLE),
    (status_error(anthropic.InternalServerError, 500),
     ReasoningFailureCode.PROVIDER_UNAVAILABLE),
    (status_error(anthropic.BadRequestError, 400),
     ReasoningFailureCode.REQUEST_INVALID),
    (status_error(anthropic.NotFoundError, 404),
     ReasoningFailureCode.REQUEST_INVALID),
    (status_error(anthropic.UnprocessableEntityError, 422),
     ReasoningFailureCode.REQUEST_INVALID),
    (status_error(anthropic.ConflictError, 409),
     ReasoningFailureCode.UNEXPECTED),
    (RuntimeError(LEAK_MARKER), ReasoningFailureCode.UNEXPECTED),
], ids=["d17_auth", "d18_permission", "d19_rate_limit", "d20_connection",
        "d21_timeout", "d22_server", "d23_bad_request", "d24_not_found",
        "d25_unprocessable", "d26_unclassified_api_error", "d27_runtime"])
def test_d17_to_d27_vendor_failures_map_to_operational_codes(error, expected,
                                                             request_for):
    client = failing(error)
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client).generate(request_for)
    assert raised.value.code is expected
    assert raised.value.code.is_operational
    assert client.call_count == 1


def test_known_failures_never_fall_through_to_unexpected(request_for):
    """UNEXPECTED is a last resort, not a shrug.

    Anything the library gives a name to and we can classify must be classified;
    otherwise an outage, a throttle and a rejected request would arrive as one
    undifferentiated code and nobody could act on any of them.
    """
    classified = [
        (anthropic.AuthenticationError, 401), (anthropic.PermissionDeniedError, 403),
        (anthropic.RateLimitError, 429), (anthropic.InternalServerError, 500),
        (anthropic.BadRequestError, 400), (anthropic.NotFoundError, 404),
        (anthropic.UnprocessableEntityError, 422),
    ]
    for cls, status in classified:
        with pytest.raises(ReasoningProviderError) as raised:
            adapter(failing(status_error(cls, status))).generate(request_for)
        assert raised.value.code is not ReasoningFailureCode.UNEXPECTED, cls.__name__


def test_a_provider_failure_never_produces_a_response(request_for):
    with pytest.raises(ReasoningProviderError):
        adapter(failing(status_error(anthropic.RateLimitError, 429))).generate(
            request_for
        )


# -- D28: usage is read, never invented ----------------------------------


@pytest.mark.parametrize("usage", [
    None, FakeUsage(input_tokens=None), FakeUsage(output_tokens="many"),
    FakeUsage(input_tokens=-1), FakeUsage(input_tokens=True),
], ids=["missing", "none", "wrong-type", "negative", "bool"])
def test_d28_unreadable_usage_is_reported_rather_than_fabricated(usage, request_for):
    """A zero that means "we do not know" is indistinguishable from a zero that
    means "free", and one of those is a lie about money."""
    client = FakeAnthropicClient(
        message=FakeMessage(content=[FakeTextBlock("{}")], usage=usage)
    )
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(client).generate(request_for)
    assert raised.value.code is ReasoningFailureCode.UNEXPECTED


def test_usage_is_carried_across_verbatim(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)),
                       usage=FakeUsage(input_tokens=9, output_tokens=3))
    usage = adapter(client).generate(request_for).usage
    assert isinstance(usage, ReasoningUsageMetadata)
    assert (usage.input_tokens, usage.output_tokens) == (9, 3)
    assert usage.attempt_count == 1


def test_a_backwards_clock_cannot_produce_a_negative_latency(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    provider = adapter(client, clock=iter([5.0, 4.0]).__next__)
    assert provider.generate(request_for).usage.latency_ms == 0


# -- D29, D30: retries off, timeout on -----------------------------------


def test_d29_and_d30_every_call_switches_retries_off_and_sets_the_timeout(
    packet, request_for
):
    """Asserted against the invocation, not the constructor.

    The library retries twice by default and waits ten minutes by default, so
    "we configured it" is only true if the configuration reaches the call. A
    test that checked the adapter's own attributes would pass while every real
    call did the opposite.
    """
    client = answering(json.dumps(valid_payload(packet)))
    adapter(client, timeout_seconds=12.5).generate(request_for)
    assert client.options == [{"timeout": 12.5, "max_retries": 0}]


def test_the_default_timeout_is_bounded_and_interactive():
    assert 0 < DEFAULT_TIMEOUT_SECONDS <= 120
    assert 0 < DEFAULT_MAX_TOKENS <= 8192


@pytest.mark.parametrize("client_factory,expected_calls", [
    (lambda p: answering(json.dumps(valid_payload(p))), 1),
    (lambda p: answering("{not json"), 1),
    (lambda p: answering(json.dumps({"unknown": 1})), 1),
    (lambda p: failing(status_error(anthropic.RateLimitError, 429)), 1),
    (lambda p: failing(anthropic.APITimeoutError(request=vendor_request())), 1),
], ids=["success", "unparseable", "schema-shaped-wrong", "rate_limited", "timeout"])
def test_one_generate_call_makes_exactly_one_inference_call(client_factory,
                                                            expected_calls,
                                                            packet, request_for):
    client = client_factory(packet)
    try:
        adapter(client).generate(request_for)
    except ReasoningProviderError:
        pass
    assert client.call_count == expected_calls


# -- D31, D32, D37, D38: what actually leaves the machine ------------------


def captured_body(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    adapter(client).generate(request_for)
    return client.calls[0]


def test_d31_the_evidence_is_serialized_deterministically(packet, request_for):
    """Byte-exact, and derived independently of the adapter."""
    expected = json.dumps(
        evidence_for_model(packet), sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), allow_nan=False,
    )
    content = captured_body(packet, request_for)["messages"][0]["content"]
    assert expected in content
    assert captured_body(packet, request_for) == captured_body(packet, request_for)


def test_d32_the_committed_schema_is_sent_by_reference(packet, request_for):
    """Identity, not equality: an equal copy would still be a second copy."""
    body = captured_body(packet, request_for)
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"] is OUTPUT_SCHEMA


def test_the_policy_and_task_are_the_committed_text_in_separate_slots(packet,
                                                                      request_for):
    body = captured_body(packet, request_for)
    assert body["system"] is SYSTEM_POLICY
    content = body["messages"][0]["content"]
    assert content.startswith(TASK_INSTRUCTION)
    assert SYSTEM_POLICY not in content, "the policy was duplicated into the user turn"
    assert body["messages"][0]["role"] == "user"
    assert len(body["messages"]) == 1


def test_the_operational_configuration_is_sent(packet, request_for):
    body = captured_body(packet, request_for)
    assert body["model"] == MODEL_ID
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS


def test_d37_nothing_but_the_four_committed_pieces_leaves_the_machine(packet,
                                                                      request_for):
    """The egress contract, asserted rather than described.

    Phase 11A sends deterministic research evidence and fixed instructions. If
    a later change starts attaching news, feeds, paper state or a file path to
    the request, this is where it stops.
    """
    body = captured_body(packet, request_for)
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config"}
    rendered = repr(body).lower()
    for forbidden in ("news", "feed", "rss", "paper", "universe", "scanner",
                      "/users/", "barseries", "featureseries", "positions",
                      "portfolio", "headline"):
        assert forbidden not in rendered, f"the request carries {forbidden}"


def test_d38_no_provenance_metadata_is_sent(packet, request_for):
    """Bookkeeping is not evidence, and a model asked to reason about our
    digests would reason about our digests."""
    rendered = repr(captured_body(packet, request_for))
    assert PROMPT_FINGERPRINT not in rendered
    assert evidence_fingerprint(packet) not in rendered
    assert packet.generated_at.isoformat() not in rendered
    assert "reasoning_fingerprint" not in rendered
    assert "evidence_fingerprint" not in rendered


# -- D33-D36: nothing vendor-shaped survives the boundary -----------------


def test_d33_and_d36_the_response_reaches_no_vendor_object(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    provider = adapter(client)
    response = provider.generate(request_for)

    seen: set[int] = set()
    found: list[str] = []

    def walk(value, path="response", depth=0):
        if depth > 7 or id(value) in seen:
            return
        seen.add(id(value))
        # Vendor objects, the adapter itself, and -- when walking a snapshot --
        # the untrusted response. That last one matters: the conversion is the
        # only place trusted state is built, so an untrusted response reachable
        # from a snapshot would mean the trust boundary had been crossed by
        # reference while every type signature still looked right.
        if isinstance(value, (FakeAnthropicClient, FakeMessage, FakeUsage,
                              FakeTextBlock, AnthropicReasoningProvider)):
            found.append(f"{path}:{type(value).__name__}")
        elif path != "response" and isinstance(value, ProviderReasoningResponse):
            found.append(f"{path}:ProviderReasoningResponse")
        # Instance attributes, not just declared fields. A frozen dataclass
        # without __slots__ still accepts ``object.__setattr__``, so an adapter
        # could smuggle the raw vendor message onto the response under a name
        # ``dataclasses.fields`` never mentions -- and a walk that trusted the
        # declaration would report the boundary as clean while it leaked.
        smuggled = getattr(value, "__dict__", None)
        if isinstance(smuggled, dict):
            for name, item in smuggled.items():
                walk(item, f"{path}.{name}", depth + 1)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field in dataclasses.fields(value):
                walk(getattr(value, field.name), f"{path}.{field.name}", depth + 1)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", depth + 1)
        elif hasattr(value, "items"):
            for key, item in value.items():
                walk(item, f"{path}[{key!r}]", depth + 1)

    walk(response)
    assert not found, found

    # The walk must be able to see a smuggled attribute, or the assertion above
    # is only a statement about the dataclass declaration.
    probe = adapter(answering(json.dumps(valid_payload(packet)))).generate(request_for)
    object.__setattr__(probe, "smuggled", FakeMessage())
    seen.clear()
    found.clear()
    walk(probe, "probe")
    assert found, "the reachability walk cannot see attributes set outside the fields"

    seen.clear()
    found.clear()
    snapshot = convert(request_for, response)
    seen.clear()
    found.clear()
    walk(snapshot, "snapshot")
    assert not found, found


def test_d34_no_request_id_or_raw_message_survives(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    client._message._request_id = "req_should_not_travel"
    response = adapter(client).generate(request_for)
    assert "req_should_not_travel" not in repr(dict(response.payload))
    assert "req_should_not_travel" not in repr(response.usage)
    assert not hasattr(response, "_request_id")


@pytest.mark.parametrize("error", [
    status_error(anthropic.AuthenticationError, 401),
    status_error(anthropic.RateLimitError, 429),
    status_error(anthropic.BadRequestError, 400),
    anthropic.APIConnectionError(message=LEAK_MARKER, request=vendor_request()),
    RuntimeError(LEAK_MARKER),
], ids=["auth", "rate", "bad_request", "connection", "runtime"])
def test_d35_no_vendor_text_reaches_the_error_detail(error, request_for):
    """Details are written here, not copied from there.

    The vendor's message may contain a header, a body fragment or a credential
    someone pasted into a request. The adapter writes a category instead, and
    breaks the exception chain so a caller that renders tracebacks cannot
    resurrect the text either.
    """
    with pytest.raises(ReasoningProviderError) as raised:
        adapter(failing(error)).generate(request_for)
    problem = raised.value
    assert LEAK_MARKER not in problem.detail
    assert LEAK_MARKER not in str(problem)
    assert len(problem.detail) <= 300

    # Both links, not just the explicit one. ``raise ... from None`` clears
    # ``__cause__`` and leaves ``__context__`` pointing at the vendor exception,
    # so asserting only the first would have declared the boundary clean while
    # the message and the response body were still one attribute away.
    assert problem.__cause__ is None
    assert problem.__context__ is None
    assert LEAK_MARKER not in repr(vars(problem))
    rendered = "".join(traceback.format_exception(type(problem), problem,
                                                  problem.__traceback__))
    assert LEAK_MARKER not in rendered


# -- D39: the validator is not optional -----------------------------------


def test_d39_the_adapter_never_produces_trusted_state(packet, request_for):
    client = answering(json.dumps(valid_payload(packet)))
    response = adapter(client).generate(request_for)
    assert not isinstance(response, ReasoningSnapshot)
    source = pathlib.Path("src/reasoning/anthropic_adapter.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    called = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    # Calls, not text: the module docstring draws the flow it sits inside and
    # therefore names the validator on purpose. Naming it is documentation;
    # calling it would be the adapter grading its own answer.
    assert "ReasoningSnapshot" not in called
    assert "validate_provider_response" not in called
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "validation" not in imported
