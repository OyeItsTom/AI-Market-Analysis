"""Phase 11A Stage F1: the one place a credential, a vendor and a service meet.

Every test here is offline. The vendor client is a local double injected through
the composition seam, and the one test that exercises the real default factory
monkeypatches ``anthropic.Anthropic`` -- so no credential from the developer's
machine can reach a real call, and no test depends on the developer having one.

What Stage F1 owns is small and almost entirely about *refusal*: which values it
will read, where it will read them, what it declines to build when they are not
there, what it never says out loud, and what it deliberately does not catch. The
matrix below is organised that way rather than by function.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import timedelta

import pytest

from src.application.reasoning import ReasoningService
from src.application.reasoning_composition import (
    ANTHROPIC_API_KEY_VAR,
    ANTHROPIC_MODEL_VAR,
    CONFIGURED_MESSAGE,
    MAX_MODEL_ID_CHARS,
    _build_anthropic_client,
    build_reasoning_service,
    describe_reasoning_configuration,
)
from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS
from src.reasoning.anthropic_adapter import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_ID,
    AnthropicReasoningProvider,
)
from src.reasoning.evidence import build_packet
from src.reasoning.models import ReasoningError, ReasoningSnapshot
from tests.test_application_reasoning import snapshot_with
from tests.test_reasoning_validation import valid_payload

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULE = REPO / "src" / "application" / "reasoning_composition.py"

#: Obviously synthetic, and shaped nothing like a real credential. It exists to
#: be searched for in output, so what matters is that it is unmistakable.
SYNTHETIC_KEY = "synthetic-test-key-not-a-real-credential"
MODEL = "test-model-id"

CONFIGURED = {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: MODEL}


# -- doubles -------------------------------------------------------------


class Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class Usage:
    def __init__(self) -> None:
        self.input_tokens = 41
        self.output_tokens = 17


class Message:
    def __init__(self, payload, served_model: str) -> None:
        self.content = [Block(json.dumps(payload))]
        self.usage = Usage()
        self.model = served_model


class FakeMessages:
    def __init__(self, client: "FakeClient") -> None:
        self._client = client

    def create(self, **kwargs):
        self._client.creates.append(kwargs)
        if self._client.raises is not None:
            raise self._client.raises
        return Message(self._client.payload, self._client.served_model)


class FakeClient:
    """Stands in for ``anthropic.Anthropic``, at exactly the surface Stage D uses."""

    def __init__(self, payload=None, *, served_model="served-model-alias", raises=None):
        self.payload = payload if payload is not None else {}
        self.served_model = served_model
        self.raises = raises
        self.options: list[dict] = []
        self.creates: list[dict] = []
        self.messages = FakeMessages(self)

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


class RecordingFactory:
    """Records every construction, so "exactly once" is a countable claim."""

    def __init__(self, client=None, *, raises=None):
        self.client = client if client is not None else FakeClient()
        self.raises = raises
        self.calls: list[dict] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.client


def compose(environ=None, **factory_kwargs):
    factory = RecordingFactory(**factory_kwargs)
    service = build_reasoning_service(
        CONFIGURED if environ is None else environ, client_factory=factory
    )
    return service, factory


# -- F1-1 .. F1-10: what counts as configured ----------------------------


def test_f1_1_both_values_present_compose_a_service():
    service, factory = compose()
    assert isinstance(service, ReasoningService)
    assert factory.call_count == 1


@pytest.mark.parametrize(
    "environ",
    [
        pytest.param({ANTHROPIC_MODEL_VAR: MODEL}, id="f1-2-key-missing"),
        pytest.param({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY}, id="f1-3-model-missing"),
        pytest.param({}, id="f1-4-both-missing"),
        pytest.param(
            {ANTHROPIC_API_KEY_VAR: "", ANTHROPIC_MODEL_VAR: MODEL}, id="f1-5-key-empty"
        ),
        pytest.param(
            {ANTHROPIC_API_KEY_VAR: "   \t\n ", ANTHROPIC_MODEL_VAR: MODEL},
            id="f1-6-key-whitespace",
        ),
        pytest.param(
            {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: ""},
            id="f1-7-model-empty",
        ),
        pytest.param(
            {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: "  \n"},
            id="f1-8-model-whitespace",
        ),
    ],
)
def test_f1_2_to_8_incomplete_configuration_composes_nothing(environ):
    """``None``, not an exception.

    Shipping without an API key is the state this project is in by default, and
    a feature that raised on the way to being switched off would make every
    caller wrap it before they could ignore it.
    """
    service, factory = compose(environ)
    assert service is None
    assert factory.call_count == 0


def test_f1_9_unrelated_environment_values_are_ignored():
    """A mapping is not a payload.

    Nothing outside the two named variables may influence, or reach, anything
    that gets composed -- least of all another subsystem's credential.
    """
    environ = dict(CONFIGURED)
    environ.update(
        {
            "SEC_USER_AGENT": "AI-Market-Analysis someone@example.com",
            "ALPACA_API_KEY_ID": "alpaca-key-should-never-travel",
            "ALPACA_API_SECRET_KEY": "alpaca-secret-should-never-travel",
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY_EXTRA": "not-the-variable",
        }
    )
    service, factory = compose(environ)
    assert isinstance(service, ReasoningService)
    assert factory.calls == [{"api_key": SYNTHETIC_KEY}]
    provider = service._provider
    assert provider.model_id == MODEL
    assert "alpaca" not in repr(factory.calls).lower()


def test_f1_10_an_injected_mapping_is_used_instead_of_the_process_environment(
    monkeypatch,
):
    """A supplied mapping is the whole story.

    If the ambient environment could still be consulted, a passing test on a
    configured machine would prove nothing at all.
    """
    monkeypatch.setenv(ANTHROPIC_API_KEY_VAR, "ambient-key-must-not-be-used")
    monkeypatch.setenv(ANTHROPIC_MODEL_VAR, "ambient-model-must-not-be-used")
    service, factory = compose({ANTHROPIC_MODEL_VAR: MODEL})
    assert service is None
    assert factory.call_count == 0

    service, factory = compose(CONFIGURED)
    assert factory.calls == [{"api_key": SYNTHETIC_KEY}]
    assert service._provider.model_id == MODEL


def test_f1_10b_environ_none_reads_the_process_environment(monkeypatch):
    """``environ=None`` falls back to ``os.environ`` -- and only then."""
    monkeypatch.delenv(ANTHROPIC_API_KEY_VAR, raising=False)
    monkeypatch.delenv(ANTHROPIC_MODEL_VAR, raising=False)
    factory = RecordingFactory()
    assert build_reasoning_service(client_factory=factory) is None
    assert factory.call_count == 0

    monkeypatch.setenv(ANTHROPIC_API_KEY_VAR, SYNTHETIC_KEY)
    monkeypatch.setenv(ANTHROPIC_MODEL_VAR, MODEL)
    service = build_reasoning_service(client_factory=factory)
    assert isinstance(service, ReasoningService)
    assert factory.calls == [{"api_key": SYNTHETIC_KEY}]


def test_f1_10c_surrounding_whitespace_is_stripped_from_both_values():
    """A value that came from a file usually brings a newline with it."""
    service, factory = compose(
        {
            ANTHROPIC_API_KEY_VAR: f"  {SYNTHETIC_KEY}\n",
            ANTHROPIC_MODEL_VAR: f"\t{MODEL}  ",
        }
    )
    assert factory.calls == [{"api_key": SYNTHETIC_KEY}]
    assert service._provider.model_id == MODEL


def test_f1_10d_a_non_string_value_is_treated_as_absent():
    """The mapping is injectable, so a double can put anything in it."""
    service, factory = compose({ANTHROPIC_API_KEY_VAR: object(), ANTHROPIC_MODEL_VAR: MODEL})
    assert service is None
    assert factory.call_count == 0


# -- F1-11 .. F1-14: describing the configuration ------------------------


def test_f1_11_a_complete_configuration_is_described_as_configured():
    assert describe_reasoning_configuration(CONFIGURED) == CONFIGURED_MESSAGE


def test_f1_12_a_missing_key_is_named_and_the_model_is_not():
    message = describe_reasoning_configuration({ANTHROPIC_MODEL_VAR: MODEL})
    assert ANTHROPIC_API_KEY_VAR in message
    assert ANTHROPIC_MODEL_VAR not in message
    assert "unavailable" in message.lower()


def test_f1_13_a_missing_model_is_named_and_the_key_is_not():
    message = describe_reasoning_configuration({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY})
    assert ANTHROPIC_MODEL_VAR in message
    assert ANTHROPIC_API_KEY_VAR not in message


def test_f1_14_both_missing_names_both():
    message = describe_reasoning_configuration({})
    assert ANTHROPIC_API_KEY_VAR in message
    assert ANTHROPIC_MODEL_VAR in message


@pytest.mark.parametrize(
    "environ",
    [{}, {ANTHROPIC_MODEL_VAR: MODEL}, {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY}],
)
def test_f1_14b_an_unconfigured_description_says_the_rest_still_works(environ):
    """The message a user reads must not imply the dashboard is broken."""
    message = describe_reasoning_configuration(environ)
    assert "works without it" in message
    assert ".env.example" in message


def test_f1_14c_describe_and_build_agree_on_every_mandated_case():
    """Two functions, one answer.

    An interface that enables a control on one basis and composes on another is
    the kind of disagreement nobody finds until a user does.
    """
    cases = [
        {},
        {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY},
        {ANTHROPIC_MODEL_VAR: MODEL},
        {ANTHROPIC_API_KEY_VAR: "  ", ANTHROPIC_MODEL_VAR: MODEL},
        {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: "  "},
        dict(CONFIGURED),
    ]
    for environ in cases:
        composed = build_reasoning_service(environ, client_factory=RecordingFactory())
        described_ok = describe_reasoning_configuration(environ) == CONFIGURED_MESSAGE
        assert (composed is not None) is described_ok, environ


# -- F1-15 .. F1-22: the client factory seam -----------------------------


def test_f1_15_a_valid_configuration_constructs_exactly_one_client():
    _, factory = compose()
    assert factory.call_count == 1


@pytest.mark.parametrize(
    "environ",
    [
        pytest.param({ANTHROPIC_MODEL_VAR: MODEL}, id="f1-16-key-missing"),
        pytest.param({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY}, id="f1-17-model-missing"),
        pytest.param({}, id="f1-18-both-missing"),
    ],
)
def test_f1_16_to_18_incomplete_configuration_constructs_no_client(environ):
    _, factory = compose(environ)
    assert factory.calls == []


def test_f1_19_the_configured_key_is_passed_by_keyword_and_alone():
    _, factory = compose()
    assert factory.calls == [{"api_key": SYNTHETIC_KEY}]


def test_f1_21_no_model_is_passed_to_the_client_constructor():
    """The model belongs to the request, not to the session.

    Stage D puts it in the request body on every call; a client configured with
    one as well would be a second owner of the same value.
    """
    _, factory = compose()
    assert "model" not in factory.calls[0]
    assert MODEL not in repr(factory.calls)


def test_f1_22_the_factory_result_is_the_client_the_adapter_receives():
    client = FakeClient()
    service, factory = compose(client=client)
    assert factory.client is client
    assert service._provider._client is client


def test_f1_22b_describing_the_configuration_constructs_no_client(monkeypatch):
    """Answering "is this configured?" must not cost what using it costs."""
    import anthropic

    built: list[dict] = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: built.append(kwargs))
    assert describe_reasoning_configuration(CONFIGURED) == CONFIGURED_MESSAGE
    assert built == []


# -- F1-23 .. F1-27: the composed provider -------------------------------


def test_f1_23_the_provider_identity_is_stage_ds_default():
    service, _ = compose()
    assert service._provider.provider_id == "anthropic"
    assert service._provider.provider_id == PROVIDER_ID


def test_f1_24_the_model_id_is_the_configured_value():
    service, _ = compose()
    assert service._provider.model_id == MODEL


def keyword_arguments() -> set[str]:
    """Every keyword *passed* by the module, ignoring prose.

    The docstrings explain which adapter settings this file deliberately leaves
    alone, and explaining a rule is not breaking it -- a raw-text search would
    fail the module for documenting its own restraint.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    return {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg is not None
    }


def test_f1_25_the_provider_id_is_not_duplicated_as_application_configuration():
    """Read from the adapter, never retyped here.

    A second spelling of ``"anthropic"`` in this layer is a value that can drift
    from the one the adapter checks a request against.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert PROVIDER_ID not in literals
    assert "provider_id" not in keyword_arguments()


def test_f1_26_adapter_defaults_remain_in_force():
    """Timeout, retry suppression and the token ceiling stay Stage D's."""
    service, _ = compose()
    provider = service._provider
    assert provider._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert provider._max_tokens == DEFAULT_MAX_TOKENS
    passed = keyword_arguments()
    for forbidden in ("timeout", "timeout_seconds", "max_tokens", "max_retries",
                      "clock"):
        assert forbidden not in passed, f"composition restates {forbidden}"
    assert passed == {"api_key", "model_id", "maximum"}, passed


def test_f1_27_composition_makes_no_provider_call():
    client = FakeClient()
    service, _ = compose(client=client)
    assert isinstance(service, ReasoningService)
    assert client.creates == []
    assert client.options == []


def test_f1_27b_the_composed_provider_is_the_stage_d_adapter():
    service, _ = compose()
    assert isinstance(service._provider, AnthropicReasoningProvider)


# -- F1-28 .. F1-31: the composed service --------------------------------


@pytest.mark.parametrize(
    "constructor",
    ["AnthropicReasoningProvider", "ReasoningService", "factory"],
)
def test_there_is_exactly_one_construction_path_for_each_composed_object(constructor):
    """One call site each, so composition has one way to build each thing.

    Not a runtime counter -- how many times a constructor happens to run is an
    implementation detail with no failure behind it. What is worth pinning is
    that there is a single *place* where each object comes into being. A second
    call site is a second construction path, and the value of a composition root
    is entirely that it is the only one; it is also how a divergent second
    provider ("build it again, but with a longer timeout") gets in without
    changing the one the tests look at.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == constructor
    ]
    assert len(sites) == 1, f"{len(sites)} call sites for {constructor}"


def test_f1_28_the_returned_object_is_a_reasoning_service():
    service, _ = compose()
    assert type(service) is ReasoningService


def test_f1_29_missing_configuration_returns_none_rather_than_a_disabled_service():
    assert build_reasoning_service({}, client_factory=RecordingFactory()) is None


def test_f1_30_the_service_holds_only_the_provider_and_a_clock():
    """Stage E's guarantee, re-checked from the composed object.

    If composition had smuggled a key, a model string or a client onto the
    service, this is where the extra attribute would show up.
    """
    service, _ = compose()
    assert set(vars(service)) == {"_provider", "_now"}
    assert service._provider is not None
    assert callable(service._now)


def explaining_service():
    """A composed service whose fake client answers with a grounded payload."""
    snapshot = snapshot_with(120)
    packet = build_packet(
        snapshot,
        now=snapshot.built_at + timedelta(seconds=1),
        minimum_sufficient_observations=MINIMUM_SUFFICIENT_OBSERVATIONS,
    )
    client = FakeClient(valid_payload(packet))
    service, factory = compose(client=client)
    return snapshot, service, client, factory


def test_f1_31_the_composed_provider_drives_the_request_identity():
    """The whole chain, end to end, with no network anywhere in it.

    The adapter refuses a request naming a different provider or model than it
    serves, and Stage E reads both off the provider -- so a composition that had
    written either value a second time would fail here rather than silently file
    an answer under a model that never saw the question.
    """
    snapshot, service, client, _ = explaining_service()
    result = service.explain(snapshot)

    assert isinstance(result, ReasoningSnapshot)
    assert len(client.creates) == 1
    sent = client.creates[0]
    assert sent["model"] == MODEL
    assert sent["max_tokens"] == DEFAULT_MAX_TOKENS
    # Stage D's call options, set on every call and not by this layer.
    assert client.options == [
        {"timeout": DEFAULT_TIMEOUT_SECONDS, "max_retries": 0}
    ]
    # The served alias is recorded rather than corrected.
    assert result.usage.model == "served-model-alias"
    assert result.usage.provider == PROVIDER_ID
    assert result.symbol == snapshot.symbol
    assert result.data_cutoff == snapshot.built_at


def test_f1_31b_availability_costs_no_call():
    """Composition exists so an interface can *ask*, and asking must be free."""
    snapshot, service, client, _ = explaining_service()
    service.availability(snapshot)
    assert client.creates == []


# -- F1-32 .. F1-35: the credential does not escape ----------------------


def test_f1_32_the_key_is_absent_from_every_description():
    for environ in ({}, {ANTHROPIC_MODEL_VAR: MODEL}, dict(CONFIGURED)):
        message = describe_reasoning_configuration(environ)
        assert SYNTHETIC_KEY not in message
        assert SYNTHETIC_KEY[:8] not in message
        assert str(len(SYNTHETIC_KEY)) not in message


def test_f1_33_the_key_is_absent_from_the_composed_public_state():
    service, _ = compose()
    provider = service._provider
    surfaces = [
        repr(service),
        repr(provider),
        provider.provider_id,
        provider.model_id,
        repr(sorted(vars(service))),
        repr(build_reasoning_service(CONFIGURED, client_factory=RecordingFactory())),
    ]
    for surface in surfaces:
        assert SYNTHETIC_KEY not in surface


def test_f1_34_the_key_is_absent_from_a_trusted_result():
    snapshot, service, _, _ = explaining_service()
    result = service.explain(snapshot)
    assert SYNTHETIC_KEY not in repr(result)
    assert SYNTHETIC_KEY not in json.dumps(
        {
            "symbol": result.symbol,
            "summary": result.summary.text,
            "claims": [claim.text for claim in result.claims],
            "uncertainties": list(result.uncertainties),
            "evidence_fingerprint": result.evidence_fingerprint,
            "reasoning_fingerprint": result.reasoning_fingerprint,
        }
    )


def test_f1_35_the_key_is_absent_from_a_provider_failure_raised_through_it():
    """A controlled transport failure, driven by the fake client.

    The failure deliberately carries the credential in its own message, because
    the thing being checked is that nothing on the path copies a vendor
    exception's text into what a caller can read. Stage D clears ``__cause__``
    and ``__context__`` for exactly this reason; this checks the composed object
    end to end rather than trusting that promise.
    """
    from src.reasoning.providers import ReasoningProviderError

    snapshot = snapshot_with(120)
    failing = FakeClient(
        raises=RuntimeError(f"transport blew up carrying {SYNTHETIC_KEY}")
    )
    service, _ = compose(client=failing)

    with pytest.raises(ReasoningProviderError) as caught:
        service.explain(snapshot)
    rendered = f"{caught.value} {caught.value.detail} {caught.value!r}"
    assert SYNTHETIC_KEY not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# -- F1-36: nothing is laundered ----------------------------------------


def test_f1_36_the_only_handler_guards_the_one_call_it_is_entitled_to():
    """Structural proof that the single catch cannot launder anything.

    Not "there are few handlers" but "there is one, it catches
    ``ReasoningError``, and the block it guards contains exactly one call, to
    the domain's text contract". A handler wrapped around the adapter
    constructor instead would look almost identical in a diff and would be
    catching several unrelated failures -- a broken client factory among them --
    and reporting all of them as unconfigured.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert len(tries) == 1, f"{len(tries)} try blocks"

    block = tries[0]
    assert block.orelse == [] and block.finalbody == []
    assert len(block.handlers) == 1
    handler = block.handlers[0]
    assert isinstance(handler.type, ast.Name) and handler.type.id == "ReasoningError", (
        "the handler must name exactly ReasoningError"
    )

    calls = [
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(ast.Module(body=block.body, type_ignores=[]))
        if isinstance(n, ast.Call)
    ]
    assert calls == ["require_text"], calls


def test_f1_36_the_handler_does_not_wrap_construction():
    """Belt and braces on the same rule, from the other direction."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    guarded = {
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for block in ast.walk(tree)
        if isinstance(block, ast.Try)
        for n in ast.walk(ast.Module(body=block.body, type_ignores=[]))
        if isinstance(n, ast.Call)
    }
    for forbidden in ("AnthropicReasoningProvider", "ReasoningService",
                      "factory", "client_factory", "_build_anthropic_client"):
        assert forbidden not in guarded, f"a handler wraps {forbidden}"


MALFORMED_MODELS = [
    pytest.param("x" * (MAX_MODEL_ID_CHARS + 1), id="over-the-adapter-bound"),
    pytest.param("model\nid", id="newline"),
    pytest.param("mo\tdel", id="tab"),
    pytest.param("model\x7fid", id="delete-character"),
]


@pytest.mark.parametrize("model", MALFORMED_MODELS)
def test_f1_36b_a_malformed_model_is_unusable_configuration_not_an_exception(model):
    """The defect this review found, pinned.

    A value the adapter would refuse must not leave this function as an
    exception. ``ReasoningError`` lives in the reasoning domain, the dashboard
    is forbidden from importing that package, and the application layer does not
    re-export it -- so an interface could only catch it by catching bare
    ``Exception``. Refusing here, where the reason is known, is what makes the
    feature switchable-off rather than crash-prone.
    """
    factory = RecordingFactory()
    environ = {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: model}
    assert build_reasoning_service(environ, client_factory=factory) is None
    # Refused before anything was built: a bad value costs nothing.
    assert factory.call_count == 0


@pytest.mark.parametrize("model", MALFORMED_MODELS)
def test_f1_36b2_a_malformed_model_is_described_as_set_but_unusable(model):
    """Not reported as missing: the operator can see it in their own shell."""
    environ = {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: model}
    message = describe_reasoning_configuration(environ)
    assert message != CONFIGURED_MESSAGE
    assert ANTHROPIC_MODEL_VAR in message
    assert "unusable" in message
    assert "not configured" not in message
    assert SYNTHETIC_KEY not in message
    # The category of problem is named; the offending value never is.
    assert model not in message


def test_f1_36b3_the_bound_this_module_applies_is_the_adapters_own():
    """Two literals, held together by driving the adapter at the boundary.

    The adapter spells its bound inline, so there is nothing to import. This is
    what stops the copy in the composition module from becoming a number that
    agrees today and answers to nobody afterwards: the moment either side moves,
    one of these two halves fails.
    """
    client = FakeClient()
    at_the_bound = "x" * MAX_MODEL_ID_CHARS
    provider = AnthropicReasoningProvider(client, model_id=at_the_bound)
    assert provider.model_id == at_the_bound

    with pytest.raises(ReasoningError):
        AnthropicReasoningProvider(client, model_id="x" * (MAX_MODEL_ID_CHARS + 1))

    # And the module agrees with the adapter at exactly the same place.
    accepted, factory = compose(
        {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: at_the_bound}
    )
    assert accepted is not None and factory.call_count == 1
    refused, factory = compose(
        {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY,
         ANTHROPIC_MODEL_VAR: "x" * (MAX_MODEL_ID_CHARS + 1)}
    )
    assert refused is None and factory.call_count == 0


@pytest.mark.parametrize(
    "environ",
    [
        pytest.param({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: ""},
                     id="empty-model"),
        pytest.param({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: "  \n"},
                     id="whitespace-model"),
        pytest.param({ANTHROPIC_API_KEY_VAR: "", ANTHROPIC_MODEL_VAR: MODEL},
                     id="empty-key"),
        pytest.param({ANTHROPIC_API_KEY_VAR: " \t ", ANTHROPIC_MODEL_VAR: MODEL},
                     id="whitespace-key"),
    ],
)
def test_a_blank_value_is_described_as_not_configured_not_as_unusable(environ):
    """The two unavailable states stay distinct, and blank belongs to the first.

    Missing, empty and whitespace-only are deliberately one situation -- the
    variable is not set to anything, and the remedy is the same -- while "set to
    something the model id contract refuses" is a different mistake with a
    different remedy. Reporting a blank value as "set but unusable" would send
    someone hunting for a malformed value in a variable that is effectively
    empty, which is the confusion the separate wording exists to prevent.
    """
    message = describe_reasoning_configuration(environ)
    assert "is not configured" in message
    assert "unusable" not in message


def test_f1_36b4_a_usable_unicode_model_is_not_refused():
    """The contract is control characters and length, not ASCII.

    Over-validating a value this project does not own would reject models that
    work, which is the failure mode a "safety" check most often actually has.
    """
    service, factory = compose(
        {ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY, ANTHROPIC_MODEL_VAR: "modèl-ø"}
    )
    assert service is not None
    assert service._provider.model_id == "modèl-ø"


def test_f1_36c_an_unrelated_factory_failure_is_not_converted_to_unconfigured():
    boom = RuntimeError("the factory itself is broken")
    with pytest.raises(RuntimeError) as caught:
        build_reasoning_service(CONFIGURED, client_factory=RecordingFactory(raises=boom))
    assert caught.value is boom


def test_f1_36d_a_factory_returning_no_client_is_a_defect_not_an_absence():
    """A broken seam must not look like a missing variable."""

    def empty_factory(**kwargs):
        return None

    with pytest.raises(ReasoningError) as caught:
        build_reasoning_service(CONFIGURED, client_factory=empty_factory)
    assert "client" in str(caught.value)


# -- import-time and application-start safety ---------------------------


def fresh_import(monkeypatch, name: str):
    """Import a module as though for the first time, and put the suite back.

    ``monkeypatch.delitem`` restores the original ``sys.modules`` entries at
    teardown, so the duplicate objects this creates never outlive the test.
    Reloading in place would not do: it rebinds the *live* module every other
    test in the session is already holding references into.
    """
    import importlib
    import sys

    # Importing a submodule also rebinds it as an attribute of its parent
    # package, and ``import src.application as x`` reads that attribute before
    # it reads sys.modules. Recording the current value with setattr is what
    # makes monkeypatch put the original back; restoring sys.modules alone would
    # leave every later test holding the throwaway copy.
    parent = sys.modules["src"]
    monkeypatch.setattr(parent, "application", parent.application)
    for cached in ("src.application.reasoning_composition", "src.application"):
        monkeypatch.delitem(sys.modules, cached, raising=False)
    return importlib.import_module(name)


def test_importing_the_module_reads_no_configuration_and_builds_nothing(monkeypatch):
    """Import must neither depend on the configuration nor touch the vendor."""
    import anthropic

    monkeypatch.delenv(ANTHROPIC_API_KEY_VAR, raising=False)
    monkeypatch.delenv(ANTHROPIC_MODEL_VAR, raising=False)

    built: list[dict] = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: built.append(kwargs))

    module = fresh_import(monkeypatch, "src.application.reasoning_composition")
    assert built == []
    assert callable(module.build_reasoning_service)


def test_importing_the_application_package_is_safe_without_configuration(monkeypatch):
    """A machine with no Anthropic configuration must still start the app."""
    import anthropic

    monkeypatch.delenv(ANTHROPIC_API_KEY_VAR, raising=False)
    monkeypatch.delenv(ANTHROPIC_MODEL_VAR, raising=False)

    built: list[dict] = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: built.append(kwargs))

    package = fresh_import(monkeypatch, "src.application")
    assert built == []
    assert callable(package.build_reasoning_service)
    assert callable(package.describe_reasoning_configuration)
    assert package.build_reasoning_service() is None


def test_the_module_composes_nothing_at_module_level():
    """No eager composition, and no module-level state to hold it in."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    assignments = [
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    assert assignments == [
        "ANTHROPIC_API_KEY_VAR",
        "ANTHROPIC_MODEL_VAR",
        "MAX_MODEL_ID_CHARS",
        "CONFIGURED_MESSAGE",
        "ClientFactory",
        "__all__",
    ], assignments


# -- the default factory, proved without a request -----------------------


def test_the_default_client_factory_constructs_the_anthropic_client(monkeypatch):
    """Behavioural, not a source-string assertion -- and still offline.

    ``anthropic.Anthropic`` is replaced for the duration, so the real
    constructor is never reached and no credential is required to run this.
    """
    import anthropic

    built: list[dict] = []

    class Recorded:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Recorded)
    client = _build_anthropic_client(api_key=SYNTHETIC_KEY)
    assert isinstance(client, Recorded)
    assert built == [{"api_key": SYNTHETIC_KEY}]


def test_the_default_factory_is_used_when_none_is_injected(monkeypatch):
    import anthropic

    built: list[dict] = []

    class Recorded:
        def __init__(self, **kwargs):
            built.append(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Recorded)
    service = build_reasoning_service(CONFIGURED)
    assert isinstance(service, ReasoningService)
    assert built == [{"api_key": SYNTHETIC_KEY}]
    assert isinstance(service._provider._client, Recorded)


@pytest.mark.parametrize(
    "fragment",
    ["claude", "sonnet", "opus", "haiku", "gpt-", "default_model", "fallback_model"],
)
def test_no_default_model_identifier_is_written_anywhere(fragment):
    """Model ids age independently of the reasoning contract.

    One hardcoded here would go stale quietly and resurface much later as a
    transport failure -- a configuration mistake wearing an outage's costume.
    """
    assert fragment not in MODULE.read_text(encoding="utf-8").lower()


def test_a_missing_model_is_never_substituted():
    """Behavioural companion to the text check above.

    The naming ban only catches the identifiers that exist today; this catches
    any default at all, whatever it is spelled.
    """
    service, factory = compose({ANTHROPIC_API_KEY_VAR: SYNTHETIC_KEY})
    assert service is None
    assert factory.call_count == 0


# -- what this module may not become -------------------------------------


def imported_modules() -> set[str]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    "module",
    ["streamlit", "logging", "dotenv", "functools", "pathlib", "json",
     "threading", "asyncio", "requests", "httpx"],
)
def test_the_composition_module_imports_nothing_it_has_no_business_with(module):
    """``functools`` is on the list for ``lru_cache``.

    A memoised service would outlive the configuration it was built from, and a
    key rotated in the environment would keep being ignored for as long as the
    process lived.
    """
    names = imported_modules()
    assert not any(
        name == module or name.startswith(module + ".") for name in names
    ), f"composition imports {module}"


def test_the_composition_module_imports_only_what_it_needs():
    assert imported_modules() == {
        "__future__",
        "os",
        "typing",
        "anthropic",
        "src.application.reasoning",
        "src.reasoning.anthropic_adapter",
        "src.reasoning.models",
    }


def test_the_composition_module_caches_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    names = {
        getattr(node, "id", getattr(node, "attr", ""))
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert not (names & {"cache", "lru_cache", "cache_data", "cache_resource",
                         "memoize", "session_state"})


def test_the_composition_module_defines_exactly_the_intended_surface():
    """Pinned, so a class, a second factory or a config object has to be argued
    for rather than appearing."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert classes == [], classes
    assert functions == [
        "_configured_value",
        "_read_configuration",
        "_build_anthropic_client",
        "build_reasoning_service",
        "describe_reasoning_configuration",
    ], functions


def test_the_public_surface_exposes_no_vendor_object():
    import src.application.reasoning_composition as composition

    assert set(composition.__all__) == {
        "ANTHROPIC_API_KEY_VAR",
        "ANTHROPIC_MODEL_VAR",
        "CONFIGURED_MESSAGE",
        "build_reasoning_service",
        "describe_reasoning_configuration",
    }
    for name in composition.__all__:
        assert "client" not in name.lower()
        assert "factory" not in name.lower()


def test_the_application_package_exports_the_composition_api():
    import src.application as application

    assert application.build_reasoning_service is build_reasoning_service
    assert (
        application.describe_reasoning_configuration is describe_reasoning_configuration
    )
    assert application.ANTHROPIC_API_KEY_VAR == ANTHROPIC_API_KEY_VAR
    assert application.ANTHROPIC_MODEL_VAR == ANTHROPIC_MODEL_VAR
    for forbidden in ("AnthropicReasoningProvider", "Anthropic", "ClientFactory"):
        assert forbidden not in application.__all__


def test_the_composition_module_returns_a_service_never_a_client():
    """The client is reachable through the provider it was given to, which is
    Stage D's design; what must never happen is composition handing one back."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                assert inner.id != "client", "composition returns the vendor client"


# -- .env.example --------------------------------------------------------


ENV_EXAMPLE = REPO / ".env.example"


def test_the_example_env_documents_both_variables_as_empty_placeholders():
    lines = [line.strip() for line in ENV_EXAMPLE.read_text().splitlines()]
    assert f"{ANTHROPIC_API_KEY_VAR}=" in lines
    assert f"{ANTHROPIC_MODEL_VAR}=" in lines


def test_the_example_env_carries_no_credential_and_no_model_identifier():
    text = ENV_EXAMPLE.read_text()
    for forbidden in ("sk-ant", "claude-", "sonnet", "opus", "haiku"):
        assert forbidden not in text.lower(), f".env.example contains {forbidden}"
