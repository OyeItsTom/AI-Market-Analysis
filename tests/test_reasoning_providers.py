"""Phase 11A Stage C: the provider is a transport, and nothing more.

Every case here runs offline. There is no adapter to any real service yet and
none is needed -- what Stage C defines is the *shape* of the boundary, and the
only thing that can prove a boundary holds is a double that is deliberately
willing to behave badly on the far side of it.

The fake lives here rather than in ``src.reasoning``. That follows the
established pattern in this repository -- ``RecordingProvider`` for market data,
the fake sources for news, the fake transports for feeds are all test-local --
and it matters more here than it does there: a fabricator exported from the
production package would be one import away from being wired into the real
path, where it would look exactly like a provider while inventing everything it
returned.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta

import pytest

from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS, build_snapshot
from src.data.models import Interval
from src.reasoning.evidence import build_packet
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
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
)
from src.reasoning.providers import (
    MAX_PROVIDER_DETAIL_CHARS,
    PROVIDER_FAILURE_CODES,
    ReasoningProvider,
    ReasoningProviderError,
)
from src.reasoning.validation import ReasoningValidationError, validate_provider_response
from tests.test_application_snapshot import RecordingProvider
from tests.test_reasoning_validation import usage, valid_payload


# -- the double ----------------------------------------------------------


class FakeReasoningProvider:
    """A provider that returns exactly what it was told to return.

    Deterministic by construction. It has no clock, no source of randomness and
    no way to reach anything: the answer is decided when the fake is built, and
    every call reproduces it.

    Two ownership decisions, made explicitly because both are observable:

    **The configured payload is copied on the way in.** A test that keeps a
    reference to the dict it passed and edits it later must not be able to
    change what earlier or later calls return -- a double whose answers depend
    on when you looked is not a fixture, it is a race.

    **A fresh copy goes out on every call.** Two responses therefore share no
    object at all, not even a nested list, so a caller that edits one response
    cannot reach into the next one. That is what makes "the same request gives
    the same answer" a fact about the fake rather than a fact about whether
    anybody touched the result.

    The copy is a ``deepcopy``, which is wider than JSON in both directions: it
    will carry values no real service could put on the wire (a ``set``, a
    ``datetime``), and it refuses a few that a caller might reach for -- a
    ``mappingproxy``, so a returned ``response.payload`` cannot be fed straight
    back in as a fixture. Both are artefacts of being an in-process double, not
    statements about what a provider can emit.

    What it deliberately does *not* do is look at the payload. It does not
    validate it, repair it, fill in citations, drop unknown keys or soften
    wording. It is standing in for something untrusted, and a helpful double
    would test a boundary that does not exist.
    """

    def __init__(
        self,
        *,
        payload=None,
        usage=None,
        failure=None,
        provider_id: str = "fake",
        model_id: str = "fake-1",
    ) -> None:
        if (payload is None) == (failure is None):
            raise ValueError(
                "configure exactly one of payload or failure: a provider either "
                "answered or it did not"
            )
        if failure is not None and not isinstance(failure, ReasoningProviderError):
            raise TypeError(
                "failure must be a ReasoningProviderError; a provider reports how "
                "the call went in the vocabulary the domain already has"
            )
        self._provider_id = provider_id
        self._model_id = model_id
        self._payload = deepcopy(payload) if payload is not None else None
        self._failure = failure
        self._usage = usage if usage is not None else (
            None if payload is None else ReasoningUsageMetadata(
                provider=provider_id, model=model_id, input_tokens=0,
                output_tokens=0, latency_ms=0, attempt_count=1,
            )
        )
        #: Every request this provider was handed, in order. Requests are frozen
        #: and already trusted, so they are held by reference rather than copied.
        self.calls: list = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def call_count(self) -> int:
        """Invocations of :meth:`generate`.

        Not ``usage.attempt_count``, which is the provider's own report of how
        many attempts it made behind one invocation. One call can honestly
        report several attempts; conflating the two would make a retrying
        adapter look like a retrying caller.
        """
        return len(self.calls)

    def generate(self, request):
        # Counted first: a call that is about to be refused still happened, and
        # a count that only recorded successes could not prove the absence of a
        # retry.
        self.calls.append(request)
        if not isinstance(request, ReasoningRequest):
            raise ReasoningProviderError(
                ReasoningFailureCode.REQUEST_INVALID,
                "request must be a ReasoningRequest",
            )
        if self._failure is not None:
            raise self._failure
        return ProviderReasoningResponse(
            payload=deepcopy(self._payload), usage=self._usage
        )


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


def convert(request, response):
    return validate_provider_response(
        request, response,
        generated_at=request.packet.data_cutoff + timedelta(seconds=5),
    )


def failure(code, detail="the service did not answer"):
    return ReasoningProviderError(code, detail)


# -- the Protocol --------------------------------------------------------


def test_the_protocol_asks_for_exactly_three_things():
    members = {
        name for name in dir(ReasoningProvider)
        if not name.startswith("_")
    }
    assert members == {"provider_id", "model_id", "generate"}


@pytest.mark.parametrize("name", ["provider_id", "model_id"])
def test_identity_is_a_property_not_a_method(name):
    """The distinction is not cosmetic and a name check cannot see it.

    ``dir()`` is satisfied either way, so dropping the decorator would leave
    every caller reading ``provider.provider_id`` and getting a bound method --
    a truthy object that is not the string anybody wanted, and one that would
    reach a log or a comparison before anything complained.
    """
    assert isinstance(inspect.getattr_static(ReasoningProvider, name), property)


def test_generate_takes_one_request_and_returns_a_response():
    signature = inspect.signature(ReasoningProvider.generate)
    assert list(signature.parameters) == ["self", "request"]
    assert signature.parameters["request"].annotation == "ReasoningRequest"
    assert signature.return_annotation == "ProviderReasoningResponse"


def test_the_request_is_passed_positionally():
    """Parameter *kind*, not just parameter name.

    Comparing names alone accepts a signature quietly turned keyword-only,
    which reads identically in the test and breaks every ``generate(request)``
    call site. The kind is the part of the contract callers actually depend on.
    """
    kinds = {
        name: parameter.kind
        for name, parameter in inspect.signature(ReasoningProvider.generate)
        .parameters.items()
    }
    assert kinds == {
        "self": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "request": inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }


def test_the_protocol_is_synchronous():
    """One question, one answer, one caller waiting.

    There is no concurrency in this path to justify colouring it, and async
    added now would propagate to every future caller for a benefit nobody has
    measured.
    """
    assert not inspect.iscoroutinefunction(ReasoningProvider.generate)


def test_the_protocol_is_deliberately_not_runtime_checkable():
    """An isinstance check here would assert three names exist, and read as a
    guarantee about behaviour. The tests below assert the behaviour instead."""
    with pytest.raises(TypeError):
        isinstance(FakeReasoningProvider(payload={}), ReasoningProvider)


def test_the_fake_matches_the_protocol_member_for_member():
    fake = FakeReasoningProvider(payload={})
    assert isinstance(fake.provider_id, str) and fake.provider_id
    assert isinstance(fake.model_id, str) and fake.model_id
    assert list(inspect.signature(fake.generate).parameters) == ["request"]


# -- identity ------------------------------------------------------------


def test_the_configured_identity_is_what_is_exposed():
    fake = FakeReasoningProvider(payload={}, provider_id="acme", model_id="acme-9")
    assert fake.provider_id == "acme"
    assert fake.model_id == "acme-9"


def test_identity_is_read_only_on_the_fake():
    fake = FakeReasoningProvider(payload={})
    with pytest.raises(AttributeError):
        fake.provider_id = "other"


# -- C1: the success path ------------------------------------------------


def test_c1_a_valid_response_comes_back_as_the_untrusted_type(packet, request_for):
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    response = fake.generate(request_for)
    assert isinstance(response, ProviderReasoningResponse)
    assert not isinstance(response, ReasoningSnapshot)
    assert dict(response.payload) == valid_payload(packet)


def test_the_configured_usage_is_returned_untouched(packet, request_for):
    metadata = usage(input_tokens=1234, output_tokens=77, latency_ms=812,
                     attempt_count=3)
    fake = FakeReasoningProvider(payload=valid_payload(packet), usage=metadata)
    assert fake.generate(request_for).usage is metadata


def test_the_default_usage_reports_the_configured_identity(packet, request_for):
    fake = FakeReasoningProvider(payload=valid_payload(packet),
                                 provider_id="acme", model_id="acme-9")
    metadata = fake.generate(request_for).usage
    assert (metadata.provider, metadata.model) == ("acme", "acme-9")
    assert metadata.attempt_count == 1


# -- C14, C16, C17, C18: determinism and ownership ------------------------


def test_c14_repeated_calls_return_equal_answers(packet, request_for):
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    answers = [dict(fake.generate(request_for).payload) for _ in range(3)]
    assert answers[0] == answers[1] == answers[2]
    assert fake.call_count == 3


def test_c16_two_responses_share_no_object(packet, request_for):
    """Not even a nested one: a caller editing one answer cannot reach the next."""
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    first, second = fake.generate(request_for), fake.generate(request_for)
    assert first.payload is not second.payload
    assert first.payload["claims"] is not second.payload["claims"]
    first.payload["claims"].clear()
    assert second.payload["claims"]
    assert dict(fake.generate(request_for).payload) == valid_payload(packet)


def test_c17_editing_the_configured_dict_afterwards_changes_nothing(packet,
                                                                    request_for):
    configured = valid_payload(packet)
    fake = FakeReasoningProvider(payload=configured)
    configured["summary"]["text"] = "rewritten after construction"
    configured["claims"].clear()
    assert dict(fake.generate(request_for).payload) == valid_payload(packet)


def test_c18_the_response_payload_is_a_read_only_view(packet, request_for):
    response = FakeReasoningProvider(payload=valid_payload(packet)).generate(
        request_for
    )
    with pytest.raises(TypeError):
        response.payload["summary"] = {}


def test_c18_the_snapshot_does_not_reach_back_to_the_response(packet, request_for):
    """Nothing unvalidated survives the conversion.

    Reachability over **declared and attached** state. The earlier version of
    this walker followed only ``dataclasses.fields``, which sounded like the
    whole object but is only its declaration: a frozen dataclass without
    ``__slots__`` still accepts ``object.__setattr__``, so a single line in the
    validator --

        object.__setattr__(snapshot, "_raw", response)

    -- put the untrusted response on the trusted snapshot and walked straight
    past a test whose name says that cannot happen. It was found by mutating
    the validator and watching this file stay green.

    What this now covers, stated exactly: identity with the response or its
    payload, declared dataclass fields, instance ``__dict__`` values, and the
    ordinary containers -- mappings (``mappingproxy`` included), tuples, lists,
    sets. What it is not: a memory-safety proof, sandbox isolation, or complete
    object-graph analysis. A custom descriptor, a ``__getattr__`` that
    materialises on access, or a C-level container could still hold a reference
    this never sees.
    """
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    response = fake.generate(request_for)
    snapshot = convert(request_for, response)

    seen: set[int] = set()

    def reaches(value, depth=0):
        if depth > 6 or id(value) in seen:
            return False
        seen.add(id(value))
        if value is response or value is response.payload:
            return True

        # Every applicable container, not the first one that matches. An object
        # can be a dataclass *and* carry attributes that were never declared,
        # and it is precisely the undeclared half that a smuggling change uses.
        children: list = []
        if not isinstance(value, type):
            if dataclasses.is_dataclass(value):
                children += [getattr(value, field.name)
                             for field in dataclasses.fields(value)]
            attributes = getattr(value, "__dict__", None)
            if isinstance(attributes, Mapping):
                children += list(attributes.values())
        if isinstance(value, Mapping):
            children += list(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            children += list(value)
        return any(reaches(child, depth + 1) for child in children)

    def walks(value) -> bool:
        seen.clear()
        return reaches(value)

    # -- the walker can see what it claims to see ------------------------
    #
    # Without this the negative assertion below is a statement about the
    # dataclass declaration wearing the word "reachability". Each probe is a
    # route a smuggling change could actually take.
    def smuggling(**attributes):
        probe = convert(request_for, fake.generate(request_for))
        for name, value in attributes.items():
            object.__setattr__(probe, name, value)
        return probe

    assert walks(smuggling(_raw=response))
    assert walks(smuggling(_payload=response.payload))
    assert walks(smuggling(_nested={"x": [response]}))
    assert walks(smuggling(_nested=({"x": response.payload},)))
    # A set cannot hold the response itself -- its payload is a mappingproxy,
    # so the frozen dataclass is unhashable -- but it can hold something
    # hashable that points at it, which is the route that actually exists.
    class Holder:
        pass

    holder = Holder()
    holder.response = response
    assert walks(smuggling(_nested={holder}))
    assert walks(smuggling(_nested=frozenset({holder})))

    # A cycle must terminate, and must not hide anything inside itself.
    loop: dict = {"self": None}
    loop["self"] = loop
    assert not walks(loop)
    baited: dict = {"self": None, "hidden": response}
    baited["self"] = baited
    assert walks(baited)

    # -- and the real snapshot is clean ----------------------------------
    assert not walks(snapshot)
    assert not walks(convert(request_for, fake.generate(request_for)))


# -- C15, C26: the request is not the provider's to change ----------------


def test_c15_generate_does_not_mutate_the_request(packet, request_for):
    before = {
        field.name: getattr(request_for, field.name)
        for field in dataclasses.fields(request_for)
    }
    fake = FakeReasoningProvider(payload=valid_payload(packet),
                                 provider_id="other", model_id="other-2")
    fake.generate(request_for)
    after = {
        field.name: getattr(request_for, field.name)
        for field in dataclasses.fields(request_for)
    }
    assert before == after
    assert after["packet"] is packet


def test_the_captured_request_is_the_object_that_was_passed(packet, request_for):
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    fake.generate(request_for)
    assert fake.calls == [request_for]
    assert fake.calls[0] is request_for


def test_ordinary_assignment_to_a_request_is_refused(request_for):
    """A guardrail against accident, and only that.

    Said precisely because the opposite would be a comfortable lie: a frozen
    dataclass refuses ``request.provider = ...`` and does **not** refuse
    ``object.__setattr__``. Python offers no way to close that, so provenance
    is not protected by the type -- it is protected by the provider not doing
    it, which is why ``test_c15_generate_does_not_mutate_the_request`` compares
    every field rather than trusting the freeze.
    """
    with pytest.raises(dataclasses.FrozenInstanceError):
        request_for.provider = "someone-else"

    object.__setattr__(request_for, "provider", "someone-else")
    assert request_for.provider == "someone-else", (
        "if this ever fails, frozen dataclasses have become sandboxes and the "
        "surrounding comment is out of date"
    )
    object.__setattr__(request_for, "provider", "fake")


# -- C12: three identities, none reconciled here --------------------------


def test_c12_a_provider_model_mismatch_is_not_an_error_in_this_stage(packet,
                                                                     request_for):
    """Intended, configured and served identity may all disagree.

    Stage C exposes all three and reconciles none: what to do when they differ
    is a policy question, and a provider that quietly rewrote one of them to
    make them agree would erase the evidence that policy needs.
    """
    fake = FakeReasoningProvider(
        payload=valid_payload(packet),
        usage=usage(provider="served", model="served-3"),
        provider_id="configured", model_id="configured-2",
    )
    response = fake.generate(request_for)
    assert (request_for.provider, request_for.model) == ("fake", "fake-1")
    assert (fake.provider_id, fake.model_id) == ("configured", "configured-2")
    assert (response.usage.provider, response.usage.model) == ("served", "served-3")


def test_the_reasoning_fingerprint_follows_the_request_not_the_provider(packet,
                                                                        request_for):
    aligned = FakeReasoningProvider(payload=valid_payload(packet))
    mismatched = FakeReasoningProvider(
        payload=valid_payload(packet),
        usage=usage(provider="served", model="served-3"),
        provider_id="configured", model_id="configured-2",
    )
    assert (
        convert(request_for, aligned.generate(request_for)).reasoning_fingerprint
        == convert(request_for,
                   mismatched.generate(request_for)).reasoning_fingerprint
    )


# -- C7-C11, C19: operational failure -------------------------------------


@pytest.mark.parametrize("code", sorted(PROVIDER_FAILURE_CODES, key=str),
                         ids=lambda c: c.value)
def test_c7_to_c11_a_configured_failure_raises_that_exact_code(code, packet,
                                                               request_for):
    fake = FakeReasoningProvider(failure=failure(code))
    with pytest.raises(ReasoningProviderError) as raised:
        fake.generate(request_for)
    assert raised.value.code is code
    assert raised.value.code.is_operational


def test_c19_a_failed_call_is_not_retried(request_for):
    fake = FakeReasoningProvider(
        failure=failure(ReasoningFailureCode.PROVIDER_UNAVAILABLE)
    )
    with pytest.raises(ReasoningProviderError):
        fake.generate(request_for)
    assert fake.call_count == 1
    with pytest.raises(ReasoningProviderError):
        fake.generate(request_for)
    assert fake.call_count == 2


def test_a_refused_call_still_counts(request_for):
    fake = FakeReasoningProvider(failure=failure(ReasoningFailureCode.RATE_LIMITED))
    with pytest.raises(ReasoningProviderError):
        fake.generate(request_for)
    assert fake.calls == [request_for]


def test_call_count_and_attempt_count_are_different_numbers(packet, request_for):
    """One invocation may honestly report several attempts behind it."""
    fake = FakeReasoningProvider(payload=valid_payload(packet),
                                 usage=usage(attempt_count=4))
    response = fake.generate(request_for)
    assert fake.call_count == 1
    assert response.usage.attempt_count == 4


def test_a_non_request_is_refused_as_an_invalid_request(packet):
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    with pytest.raises(ReasoningProviderError) as raised:
        fake.generate({"packet": "please"})
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID


def test_a_fake_needs_an_answer_or_a_failure_and_not_both(packet):
    with pytest.raises(ValueError):
        FakeReasoningProvider()
    with pytest.raises(ValueError):
        FakeReasoningProvider(payload=valid_payload(packet),
                              failure=failure(ReasoningFailureCode.UNEXPECTED))


def test_a_failure_must_speak_the_domain_vocabulary(packet):
    with pytest.raises(TypeError):
        FakeReasoningProvider(failure=RuntimeError("the socket closed"))


# -- the provider error contract -----------------------------------------


def test_the_permitted_codes_are_exactly_the_operational_ones():
    assert {code.value for code in PROVIDER_FAILURE_CODES} == {
        "provider_unavailable", "rate_limited", "authentication_failed",
        "request_invalid", "unexpected",
    }


@pytest.mark.parametrize("code", [
    ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
    ReasoningFailureCode.GROUNDING_FAILED,
    ReasoningFailureCode.BOUNDARY_VIOLATION,
], ids=lambda c: c.value)
def test_a_provider_may_not_report_a_content_failure(code):
    """Those are judgements about an answer, made after it arrives. A provider
    reporting one would be marking its own homework."""
    with pytest.raises(ReasoningError, match="validation"):
        ReasoningProviderError(code, "not mine to say")


def test_a_provider_error_is_a_reasoning_error_but_not_a_validation_error():
    error = failure(ReasoningFailureCode.RATE_LIMITED)
    assert isinstance(error, ReasoningError)
    assert not isinstance(error, ReasoningValidationError)


def test_the_detail_is_bounded():
    error = ReasoningProviderError(ReasoningFailureCode.UNEXPECTED, "x" * 5000)
    assert len(error.detail) == MAX_PROVIDER_DETAIL_CHARS


def test_the_detail_must_be_text():
    with pytest.raises(ReasoningError):
        ReasoningProviderError(ReasoningFailureCode.UNEXPECTED, {"body": "..."})


def test_a_bounded_detail_is_not_a_redacted_detail():
    """Said plainly, because the opposite would be a comfortable lie.

    The class truncates; it does not inspect. Anything a caller puts at the
    front of a detail survives, so "never put a credential in a detail" is a
    rule adapters keep, not one this code enforces.
    """
    error = ReasoningProviderError(ReasoningFailureCode.AUTHENTICATION_FAILED,
                                   "marker-value-1234 " + "x" * 5000)
    assert "marker-value-1234" in error.detail


def test_the_error_message_names_the_code_and_the_detail():
    error = failure(ReasoningFailureCode.RATE_LIMITED, "the service asked us to wait")
    assert str(error) == "rate_limited: the service asked us to wait"


# -- C2-C6, C13: malformed answers travel intact --------------------------


def malformed_cases(packet):
    unknown = valid_payload(packet)
    unknown["confidence"] = 0.91

    forbidden = valid_payload(packet)
    forbidden["claims"][0]["text"] = "The evidence supports a strong buy here."

    fabricated = valid_payload(packet)
    fabricated["claims"][0]["evidence_ids"] = ["obs:invented:v1:deadbeef"]

    empty = valid_payload(packet)
    empty["summary"]["evidence_ids"] = []

    provenance = valid_payload(packet)
    provenance["provider"] = "someone-else"
    provenance["evidence_fingerprint"] = "0" * 64

    return {
        "c2_unknown_field": (unknown, ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
        "c3_forbidden_language": (forbidden,
                                  ReasoningFailureCode.BOUNDARY_VIOLATION),
        "c4_fabricated_evidence_id": (fabricated,
                                      ReasoningFailureCode.GROUNDING_FAILED),
        "c5_empty_summary_citation": (empty,
                                      ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
        "c13_supplied_provenance": (provenance,
                                    ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
    }


MALFORMED_CASE_IDS = (
    "c2_unknown_field",
    "c3_forbidden_language",
    "c4_fabricated_evidence_id",
    "c5_empty_summary_citation",
    "c13_supplied_provenance",
)


@pytest.mark.parametrize("case", MALFORMED_CASE_IDS)
def test_a_malformed_answer_is_returned_intact_and_refused_later(case, packet,
                                                                 request_for):
    payload, expected = malformed_cases(packet)[case]
    fake = FakeReasoningProvider(payload=payload)

    response = fake.generate(request_for)
    assert fake.call_count == 1
    assert dict(response.payload) == payload, "the provider altered the answer"

    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, response)
    assert raised.value.code is expected


def test_c6_malformed_usage_is_a_validation_failure_not_a_provider_failure(
    packet, request_for
):
    """A provider reporting zero attempts for a response that arrived is
    describing something it did not do -- but it is still a response, and
    refusing it is the validator's job."""
    fake = FakeReasoningProvider(payload=valid_payload(packet),
                                 usage=usage(attempt_count=0))
    response = fake.generate(request_for)
    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, response)
    assert raised.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


def test_the_provider_never_raises_for_a_malformed_answer(packet, request_for):
    for payload, _ in malformed_cases(packet).values():
        assert isinstance(
            FakeReasoningProvider(payload=payload).generate(request_for),
            ProviderReasoningResponse,
        )


# -- C20, C24: the two error worlds stay apart ----------------------------


def test_c20_the_whole_chain_composes_and_validation_is_the_only_door(packet,
                                                                      request_for):
    fake = FakeReasoningProvider(payload=valid_payload(packet))
    snapshot = convert(request_for, fake.generate(request_for))

    assert isinstance(snapshot, ReasoningSnapshot)
    assert snapshot.symbol == packet.symbol
    assert snapshot.data_cutoff == packet.data_cutoff
    assert snapshot.prompt_id == request_for.prompt_id
    assert snapshot.prompt_version == request_for.prompt_version
    assert snapshot.output_schema_version == request_for.output_schema_version
    assert snapshot.reasoning_kind is request_for.reasoning_kind
    assert snapshot.cited_evidence_ids <= packet.evidence_ids


def test_an_operational_failure_and_a_content_failure_are_different_types(
    packet, request_for
):
    unreachable = FakeReasoningProvider(
        failure=failure(ReasoningFailureCode.PROVIDER_UNAVAILABLE)
    )
    with pytest.raises(ReasoningProviderError) as operational:
        unreachable.generate(request_for)

    answered = FakeReasoningProvider(
        payload=malformed_cases(packet)["c4_fabricated_evidence_id"][0]
    )
    with pytest.raises(ReasoningValidationError) as content:
        convert(request_for, answered.generate(request_for))

    assert not isinstance(operational.value, ReasoningValidationError)
    assert not isinstance(content.value, ReasoningProviderError)
    assert operational.value.code.is_operational
    assert not content.value.code.is_operational


def test_a_structurally_similar_provider_cannot_smuggle_a_raw_answer(packet,
                                                                    request_for):
    """The Protocol cannot enforce a return type, so something must.

    An object with the right three members can return a bare dict that looks
    exactly like a payload. Nothing at the provider boundary catches that --
    the validator does, and it is the reason the trusted type is a type rather
    than a shape.
    """
    class Lookalike:
        provider_id = "looks-right"
        model_id = "looks-right-1"

        def generate(self, request):
            return dict(valid_payload(packet))

    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, Lookalike().generate(request_for))
    assert raised.value.code is ReasoningFailureCode.REQUEST_INVALID


def test_the_fake_is_wider_than_json_and_the_validator_still_refuses(request_for):
    """A classification, not a licence.

    The fake copies whatever it is given, so it will happily carry a ``set`` or
    a ``datetime`` -- values no real service could ever put on the wire. That
    latitude is an artefact of being an in-process double and must not be read
    as a claim about what a provider can emit; what it buys is one more shape
    the validator is shown refusing.
    """
    from datetime import datetime as _datetime

    exotic = {"summary": {1, 2}, "claims": b"\x00", "uncertainties": _datetime.now()}
    fake = FakeReasoningProvider(payload=exotic)
    response = fake.generate(request_for)
    assert set(response.payload) == set(exotic)

    with pytest.raises(ReasoningValidationError) as raised:
        convert(request_for, response)
    assert raised.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED


# -- the fake keeps its own promises --------------------------------------


def _fake_source_tree():
    return ast.parse(inspect.getsource(FakeReasoningProvider))


def test_the_fake_reads_no_clock_and_rolls_no_dice():
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(_fake_source_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    forbidden = {"now", "utcnow", "today", "time", "monotonic", "perf_counter",
                 "random", "uniform", "randint", "choice", "shuffle", "sleep",
                 "open", "getenv"}
    assert not (calls & forbidden), calls & forbidden


def test_the_fake_does_not_validate_or_convert():
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(_fake_source_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert "validate_provider_response" not in calls
    assert "ReasoningSnapshot" not in calls


def test_the_fake_contains_no_loop():
    """No retry, because there is no failure semantics to design one against."""
    assert not [
        node for node in ast.walk(_fake_source_tree())
        if isinstance(node, (ast.While, ast.For))
    ]
