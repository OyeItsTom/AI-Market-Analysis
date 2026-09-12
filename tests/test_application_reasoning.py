"""Phase 11A Stage E: the application layer's one reasoning use case.

Every test here is offline. The provider is a small local double, because what
Stage E owns is the *order and provenance* of the steps -- which value came from
where, what is asked before anything is spent, and what is never allowed to
reach a caller. None of that needs a real service, and one of the things it
must guarantee is that asking whether an explanation is possible costs nothing.

The double is deliberately not the Stage C fake. That one is shaped around
adapter concerns -- payload copying, deep-copy semantics, failure scripting --
and importing it would couple two suites for a partial fit.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.reasoning import (
    ReasoningAvailability,
    ReasoningService,
    ReasoningUnavailable,
)
from src.application.snapshot import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    build_ensemble,
    build_policy,
    build_snapshot,
)
from src.assessments.assessment import AssessmentState
from src.assessments.policy import AssessmentPolicy, HypothesisIdentity
from src.data.models import Interval
from src.reasoning.evidence import evidence_fingerprint
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
from src.reasoning.providers import ReasoningProviderError
from src.reasoning.validation import ReasoningValidationError
from tests.test_application_snapshot import RecordingProvider
from tests.test_reasoning_validation import valid_payload

PROVIDER_ID = "provider-x"
MODEL_ID = "model-y"


# -- the double ----------------------------------------------------------


class RecordingReasoningProvider:
    """Records what it was asked and answers exactly as configured."""

    def __init__(self, *, payload=None, failure=None, usage=None,
                 provider_id: str = PROVIDER_ID, model_id: str = MODEL_ID):
        self._payload = payload
        self._failure = failure
        self._usage = usage
        self._provider_id = provider_id
        self._model_id = model_id
        self.requests: list[ReasoningRequest] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def generate(self, request):
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        usage = self._usage or ReasoningUsageMetadata(
            provider=self._provider_id, model=self._model_id, input_tokens=10,
            output_tokens=5, latency_ms=7, attempt_count=1,
        )
        return ProviderReasoningResponse(payload=self._payload or {}, usage=usage)


# -- fixtures ------------------------------------------------------------


def snapshot_with(count: int):
    return build_snapshot(RecordingProvider(count=count), "AAPL", Interval.DAY_1)


@pytest.fixture
def assessed():
    return snapshot_with(120)


@pytest.fixture
def unassessed():
    """No bars at all, so the pipeline never reaches the assessment step."""
    return snapshot_with(0)


@pytest.fixture
def warming():
    """Real assessment, but the ensemble has not warmed up."""
    snapshot = snapshot_with(1)
    assert snapshot.assessment is not None
    assert snapshot.assessment.state is AssessmentState.INSUFFICIENT_DATA
    return snapshot


def clock_for(snapshot, *, offset=5, values=None):
    """A deterministic clock at or after the snapshot's cutoff."""
    if values is None:
        values = [snapshot.built_at + timedelta(seconds=offset)]
    calls: list[datetime] = []

    def now():
        calls.append(values[min(len(calls), len(values) - 1)])
        return calls[-1]

    now.calls = calls
    return now


# -- E1, E13, E23, E25: the success path ---------------------------------


def explaining(snapshot, **overrides):
    """A service whose provider returns a payload grounded in the real packet."""
    provider = RecordingReasoningProvider(**overrides)
    service = ReasoningService(provider, now=clock_for(snapshot))
    if provider._payload is None and provider._failure is None:
        provider._payload = valid_payload(
            service._packet(snapshot, snapshot.built_at + timedelta(seconds=5))
        )
    return service, provider


def test_e1_an_assessed_snapshot_produces_a_trusted_explanation(assessed):
    service, provider = explaining(assessed)
    result = service.explain(assessed)
    assert isinstance(result, ReasoningSnapshot)
    assert provider.call_count == 1
    assert result.symbol == assessed.symbol
    assert result.reasoning_kind is ReasoningKind.EXPLAIN_RESEARCH


def test_e13_the_whole_chain_composes(assessed):
    service, provider = explaining(assessed)
    result = service.explain(assessed)
    assert isinstance(result, ReasoningSnapshot)
    assert result.cited_evidence_ids <= service._packet(
        assessed, assessed.built_at + timedelta(seconds=5)
    ).evidence_ids
    assert provider.call_count == 1


def test_e25_a_successful_call_leaves_the_research_untouched(assessed):
    before = {f.name: getattr(assessed, f.name) for f in dataclasses.fields(assessed)}
    service, _ = explaining(assessed)
    service.explain(assessed)
    after = {f.name: getattr(assessed, f.name) for f in dataclasses.fields(assessed)}
    assert before == after
    assert after["assessment"] is before["assessment"]


# -- E2, E24, E4, E61: no assessment -------------------------------------


def test_e2_a_snapshot_without_bars_has_no_assessment(unassessed):
    assert unassessed.assessment is None
    service, provider = explaining(unassessed, payload={})
    assert service.availability(unassessed) is ReasoningAvailability.NO_ASSESSMENT
    assert provider.call_count == 0


def test_e4_explain_refuses_without_being_asked_first(unassessed):
    """The policy lives here, not in whatever calls it.

    An interface that only disables a button leaves the rule in the interface,
    and the next caller is a script.
    """
    service, provider = explaining(unassessed, payload={})
    with pytest.raises(ReasoningUnavailable) as raised:
        service.explain(unassessed)
    assert provider.call_count == 0
    assert isinstance(raised.value, ApplicationError)
    assert raised.value.kind is FailureKind.REQUEST


def test_e24_refusing_costs_nothing(unassessed):
    service, provider = explaining(unassessed, payload={})
    for _ in range(3):
        with pytest.raises(ReasoningUnavailable):
            service.explain(unassessed)
        service.availability(unassessed)
    assert provider.call_count == 0
    assert provider.requests == []


# -- E3, E21: insufficient data is still explainable ---------------------


def test_e3_insufficient_data_is_an_assessment_and_stays_eligible(warming):
    """The distinction this protects is easy to lose and expensive to lose.

    A warming-up ensemble has reached a real verdict with real reason codes,
    and explaining *why the evidence is not yet enough* is one of the more
    useful things this feature does. Only the complete absence of an
    assessment -- no bars at all -- is unexplainable.
    """
    assert warming.assessment.state is AssessmentState.INSUFFICIENT_DATA
    service, provider = explaining(warming)
    assert service.availability(warming) is ReasoningAvailability.AVAILABLE
    assert isinstance(service.explain(warming), ReasoningSnapshot)
    assert provider.call_count == 1


def test_availability_is_free_for_every_snapshot(assessed, warming, unassessed):
    for snapshot in (assessed, warming, unassessed):
        service, provider = explaining(snapshot, payload={})
        service.availability(snapshot)
        assert provider.call_count == 0


# -- E5, E6: the threshold, and that it is the governing one -------------


def _policy_with(minimum: int) -> AssessmentPolicy:
    return AssessmentPolicy(
        tuple(
            HypothesisIdentity(h.spec.hypothesis_id, h.spec.version, h.fingerprint)
            for h in build_ensemble()
        ),
        minimum,
        "directional_presence_v1",
    )


def test_e5_the_packet_carries_the_threshold_that_governed_the_assessment(assessed):
    """Propagation, not a comparison of two constants.

    The policy fingerprint covers the minimum, and the snapshot carries that
    digest. So reconstructing the policy from the *packet's* threshold and
    matching the snapshot's fingerprint proves the packet describes the
    assessment that was actually made -- a duplicated constant that happened to
    be equal would prove nothing.
    """
    service, _ = explaining(assessed)
    packet = service._packet(assessed, assessed.built_at + timedelta(seconds=5))
    assert (
        _policy_with(packet.minimum_sufficient_observations).fingerprint
        == assessed.policy_fingerprint
    )


def test_e6_a_drifted_threshold_would_not_match(assessed):
    """The negative control, so the assertion above cannot pass on any value."""
    service, _ = explaining(assessed)
    packet = service._packet(assessed, assessed.built_at + timedelta(seconds=5))
    drifted = packet.minimum_sufficient_observations + 1
    assert _policy_with(drifted).fingerprint != assessed.policy_fingerprint


def test_every_value_in_the_request_is_a_reference_to_its_owner():
    """The invariant, stated as itself rather than as a proxy for itself.

    An earlier version of this test banned every integer literal in the module.
    It killed the mutants, and it was the wrong rule: it also rejects a stray
    ``0`` that has nothing to do with provenance, so the first maintainer to
    write one would relax the ban and take the real protection with it.

    What actually matters is narrower and checkable: every value handed to
    ``ReasoningRequest`` and the threshold handed to ``build_packet`` must be a
    *reference* -- a name or an attribute -- and never a constant. A literal
    that happens to equal its owner today is precisely the drift the owner
    exists to prevent, and ``PROMPT_VERSION == 1`` means comparing values could
    never have caught it.
    """
    tree = ast.parse(pathlib.Path("src/application/reasoning.py").read_text(
        encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if callee not in {"ReasoningRequest", "build_packet"}:
            continue
        for keyword in node.keywords:
            if callee == "build_packet" and keyword.arg != (
                "minimum_sufficient_observations"
            ):
                continue
            assert isinstance(keyword.value, (ast.Name, ast.Attribute)), (
                f"{callee}({keyword.arg}=...) is a literal; it must name its owner"
            )
            checked += 1
    assert checked == 10, f"expected every request field to be checked, saw {checked}"


# -- E7-E12: identity and prompt provenance ------------------------------


def test_e7_and_e8_request_identity_comes_from_the_provider(assessed):
    service, provider = explaining(assessed, provider_id="acme", model_id="acme-9")
    provider._payload = valid_payload(
        service._packet(assessed, assessed.built_at + timedelta(seconds=5))
    )
    service.explain(assessed)
    request = provider.requests[0]
    assert request.provider == "acme"
    assert request.model == "acme-9"


def test_no_authoritative_name_is_reassigned_after_it_is_imported():
    """Importing a value is not enough; it must not be shadowed afterwards.

    ``MINIMUM_SUFFICIENT_OBSERVATIONS = 2`` written below the import binds a
    literal over the authoritative one. Every call site still *reads a name*,
    so the reference check above passes, and the value agrees today so the
    fingerprint check passes too -- and the module has quietly stopped tracking
    its owner. Only forbidding the reassignment catches that.
    """
    tree = ast.parse(pathlib.Path("src/application/reasoning.py").read_text(
        encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assigned = {
        target.id
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    shadowed = imported & assigned
    assert not shadowed, f"the orchestration rebinds {sorted(shadowed)}"
    assert "MINIMUM_SUFFICIENT_OBSERVATIONS" in imported


def test_no_vendor_or_model_literal_exists_in_the_orchestration():
    source = pathlib.Path("src/application/reasoning.py").read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "gemini", "claude-", "gpt-"):
        assert forbidden not in source.lower(), forbidden


@pytest.mark.parametrize("field,expected", [
    ("prompt_id", PROMPT_ID),
    ("prompt_version", PROMPT_VERSION),
    ("prompt_fingerprint", PROMPT_FINGERPRINT),
    ("output_schema_version", OUTPUT_SCHEMA_VERSION),
], ids=["e9_prompt_id", "e10_prompt_version", "e11_fingerprint", "e12_schema_version"])
def test_e9_to_e12_prompt_identity_comes_from_the_committed_constants(
    field, expected, assessed
):
    service, provider = explaining(assessed)
    service.explain(assessed)
    assert getattr(provider.requests[0], field) == expected


def test_the_orchestration_restates_no_prompt_text():
    source = pathlib.Path("src/application/reasoning.py").read_text(encoding="utf-8")
    for fragment in ("SYSTEM_POLICY", "TASK_INSTRUCTION", "OUTPUT_SCHEMA\"",
                     "explain_research", "json_schema", "additionalProperties"):
        assert fragment not in source, fragment


def test_the_request_is_the_committed_type_with_every_field_populated(assessed):
    service, provider = explaining(assessed)
    service.explain(assessed)
    request = provider.requests[0]
    assert isinstance(request, ReasoningRequest)
    for field in dataclasses.fields(request):
        assert getattr(request, field.name) is not None


# -- E14-E18: failures propagate, distinctly -----------------------------


@pytest.mark.parametrize("code", [
    ReasoningFailureCode.RATE_LIMITED,
    ReasoningFailureCode.PROVIDER_UNAVAILABLE,
    ReasoningFailureCode.AUTHENTICATION_FAILED,
], ids=lambda c: c.value)
def test_e14_and_e15_provider_failures_propagate_unchanged(code, assessed):
    failure = ReasoningProviderError(code, "the service did not answer")
    service, provider = explaining(assessed, failure=failure)
    before = {f.name: getattr(assessed, f.name) for f in dataclasses.fields(assessed)}

    with pytest.raises(ReasoningProviderError) as raised:
        service.explain(assessed)

    assert raised.value is failure
    assert raised.value.code is code
    assert not isinstance(raised.value, ApplicationError)
    assert provider.call_count == 1
    assert {f.name: getattr(assessed, f.name)
            for f in dataclasses.fields(assessed)} == before


def _mutated(service, snapshot, mutate):
    body = valid_payload(
        service._packet(snapshot, snapshot.built_at + timedelta(seconds=5))
    )
    mutate(body)
    return body


@pytest.mark.parametrize("mutate,expected", [
    (lambda b: b["claims"][0].__setitem__("evidence_ids", ["obs:made:v1:up"]),
     ReasoningFailureCode.GROUNDING_FAILED),
    (lambda b: b["claims"][0].__setitem__("text", "A strong buy on this evidence."),
     ReasoningFailureCode.BOUNDARY_VIOLATION),
    (lambda b: b.__setitem__("confidence", 0.9),
     ReasoningFailureCode.OUTPUT_SCHEMA_FAILED),
], ids=["e16_fabricated_citation", "e17_forbidden_wording", "e18_malformed_schema"])
def test_e16_to_e18_validation_failures_propagate_unchanged(mutate, expected, assessed):
    """Stage E does not help the provider, and does not rename the refusal."""
    service, provider = explaining(assessed)
    provider._payload = _mutated(service, assessed, mutate)

    with pytest.raises(ReasoningValidationError) as raised:
        service.explain(assessed)

    assert raised.value.code is expected
    assert not isinstance(raised.value, ApplicationError)
    assert provider.call_count == 1


def test_the_two_failure_worlds_stay_distinguishable(assessed):
    """A caller must be able to tell an outage from a bad answer.

    Collapsing both into one application error would discard the split the
    whole layer below was built to preserve.
    """
    outage, _ = explaining(assessed, failure=ReasoningProviderError(
        ReasoningFailureCode.PROVIDER_UNAVAILABLE, "unreachable"))
    with pytest.raises(ReasoningProviderError) as operational:
        outage.explain(assessed)

    content, provider = explaining(assessed)
    provider._payload = _mutated(
        content, assessed,
        lambda b: b["claims"][0].__setitem__("evidence_ids", ["obs:made:v1:up"]))
    with pytest.raises(ReasoningValidationError) as answered:
        content.explain(assessed)

    assert type(operational.value) is not type(answered.value)
    assert operational.value.code.is_operational
    assert not answered.value.code.is_operational


@pytest.mark.parametrize("failure_kind", ["provider", "validation"])
def test_e26_and_e27_failure_leaves_the_research_untouched(failure_kind, assessed):
    before = {f.name: getattr(assessed, f.name) for f in dataclasses.fields(assessed)}
    if failure_kind == "provider":
        service, _ = explaining(assessed, failure=ReasoningProviderError(
            ReasoningFailureCode.RATE_LIMITED, "slow down"))
        expected = ReasoningProviderError
    else:
        service, provider = explaining(assessed)
        provider._payload = _mutated(
            service, assessed,
            lambda b: b["claims"][0].__setitem__("evidence_ids", ["obs:made:v1:up"]))
        expected = ReasoningValidationError
    with pytest.raises(expected):
        service.explain(assessed)
    assert {f.name: getattr(assessed, f.name)
            for f in dataclasses.fields(assessed)} == before


# -- E19, E20: the clock -------------------------------------------------


def test_e19_the_injected_timestamp_is_the_one_that_is_recorded(assessed):
    moment = assessed.built_at + timedelta(seconds=5)
    service, provider = explaining(assessed)
    result = service.explain(assessed)
    assert result.generated_at == moment
    assert provider.requests[0].created_at == moment


def test_one_timestamp_per_call(assessed):
    """The packet, the request and the validation speak about one instant.

    Three neighbouring wall-clock reads would make a record that is almost
    true, and "almost" is not a property a causal invariant can be built on.
    """
    now = clock_for(assessed)
    provider = RecordingReasoningProvider()
    service = ReasoningService(provider, now=now)
    provider._payload = valid_payload(
        service._packet(assessed, assessed.built_at + timedelta(seconds=5))
    )
    before = len(now.calls)
    service.explain(assessed)
    assert len(now.calls) - before == 1

    before = len(now.calls)
    service.availability(assessed)
    assert len(now.calls) - before == 1


def test_e20_a_timestamp_before_the_cutoff_is_refused_before_any_call(assessed):
    """Refused by the packet invariant, which fires first.

    The validator has its own temporal check, but with a single captured
    timestamp it can never be the one to fire: a packet whose ``generated_at``
    precedes its own cutoff cannot be constructed at all. Nothing is repaired
    and nothing is spent.
    """
    provider = RecordingReasoningProvider()
    service = ReasoningService(
        provider, now=lambda: assessed.built_at - timedelta(seconds=1)
    )
    with pytest.raises(ReasoningError, match="precedes data_cutoff"):
        service.explain(assessed)
    assert provider.call_count == 0


def test_a_naive_clock_is_refused_by_the_existing_contracts(assessed):
    provider = RecordingReasoningProvider()
    service = ReasoningService(provider, now=lambda: datetime(2030, 1, 1))
    with pytest.raises(ReasoningError):
        service.explain(assessed)
    assert provider.call_count == 0


# -- E21, E22: repetition without memory ---------------------------------


def test_e21_and_e22_two_requests_are_two_calls(assessed):
    first = assessed.built_at + timedelta(seconds=5)
    second = assessed.built_at + timedelta(seconds=90)
    now = clock_for(assessed, values=[first, second])
    provider = RecordingReasoningProvider()
    service = ReasoningService(provider, now=now)
    provider._payload = valid_payload(service._packet(assessed, first))

    one = service.explain(assessed)
    two = service.explain(assessed)

    assert provider.call_count == 2
    assert one.evidence_fingerprint == two.evidence_fingerprint
    assert one.reasoning_fingerprint == two.reasoning_fingerprint
    assert one.generated_at == first and two.generated_at == second


def test_the_service_remembers_nothing(assessed):
    service, _ = explaining(assessed)
    service.explain(assessed)
    held = set(vars(service))
    assert held == {"_provider", "_now"}, held


def test_e37_and_e38_nothing_is_called_before_it_is_asked_for(assessed):
    provider = RecordingReasoningProvider()
    service = ReasoningService(provider, now=clock_for(assessed))
    assert provider.call_count == 0
    service.availability(assessed)
    assert provider.call_count == 0


# -- E34-E36, E39, E40: the shape of the API -----------------------------


def test_e34_the_api_takes_one_snapshot(assessed):
    import inspect

    assert list(inspect.signature(ReasoningService.explain).parameters) == [
        "self", "snapshot"]
    assert list(inspect.signature(ReasoningService.availability).parameters) == [
        "self", "snapshot"]


def test_e36_a_provider_is_required():
    import inspect

    parameters = inspect.signature(ReasoningService.__init__).parameters
    assert list(parameters) == ["self", "provider", "now"]
    assert parameters["provider"].default is inspect.Parameter.empty


def test_e40_a_raw_response_never_reaches_the_caller(assessed):
    service, provider = explaining(assessed)
    result = service.explain(assessed)
    assert not isinstance(result, ProviderReasoningResponse)
    assert isinstance(result, ReasoningSnapshot)
    seen: set[int] = set()

    def reaches(value, depth=0):
        if depth > 6 or id(value) in seen:
            return False
        seen.add(id(value))
        if isinstance(value, (ProviderReasoningResponse, RecordingReasoningProvider)):
            return True
        attributes = getattr(value, "__dict__", None)
        children = list(attributes.values()) if isinstance(attributes, dict) else []
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            children += [getattr(value, f.name) for f in dataclasses.fields(value)]
        if isinstance(value, (list, tuple)):
            children += list(value)
        elif hasattr(value, "values"):
            children += list(value.values())
        return any(reaches(child, depth + 1) for child in children)

    assert not reaches(result)


def test_e39_the_validator_is_the_only_door(assessed):
    """Proven by consequence: a payload that cannot validate never returns."""
    service, provider = explaining(assessed)
    provider._payload = {"summary": {"text": "x", "evidence_ids": ["nope"]},
                         "claims": [], "uncertainties": []}
    with pytest.raises(ReasoningValidationError):
        service.explain(assessed)


def test_an_empty_payload_is_the_validator_s_to_refuse(assessed):
    """The orchestration does not pre-screen what came back.

    An empty answer looks like something worth catching early, and catching it
    early is exactly wrong: it would report a provider that answered badly as
    an application availability problem, and the two are not the same thing to
    anyone deciding what to do next. It goes to the validator like every other
    payload and comes back as a schema failure.
    """
    service, provider = explaining(assessed, payload={})
    with pytest.raises(ReasoningValidationError) as raised:
        service.explain(assessed)
    assert raised.value.code is ReasoningFailureCode.OUTPUT_SCHEMA_FAILED
    assert not isinstance(raised.value, ReasoningUnavailable)
    assert provider.call_count == 1


# -- E43: the request carries nothing the application added ---------------


def test_e43_the_request_carries_only_bounded_reasoning_state(assessed):
    service, provider = explaining(assessed)
    service.explain(assessed)
    rendered = repr(provider.requests[0]).lower()
    for forbidden in ("news", "rss", "feed", "paper", "portfolio", "position",
                      "universe", "scanner", "/users/", "barseries",
                      "featureseries", "api_key", "headline"):
        assert forbidden not in rendered, f"the request carries {forbidden}"
