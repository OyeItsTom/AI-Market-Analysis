"""Where the credential, the vendor and the environment meet -- and nowhere else.

    ANTHROPIC_API_KEY / ANTHROPIC_MODEL      [local configuration]
            |
            v
    anthropic.Anthropic(api_key=...)         [the vendor client]
            |
            v
    AnthropicReasoningProvider(client, ...)  [Stage D transport]
            |
            v
    ReasoningService(provider)               [Stage E orchestration]

Stage D refuses to build a client -- "composing a client from local
configuration is the caller's job and lives outside this package" -- and Stage E
refuses to know a vendor exists. This module is the caller both of them were
written against, and it is deliberately the *only* one: it is the second and
final production file permitted to import the Anthropic SDK, and the single
place in the application and dashboard layers that reads either reasoning
environment variable. Both permissions are asserted, and asserted as *used*, by
the Phase 7 boundary suite -- a permission nobody exercises is a hole nobody is
watching.

**Absence is a setup step, not a fault.** An unset key or model switches the AI
explanation off and changes nothing else: no exception, no client, no provider,
no network. The dashboard keeps fetching bars, computing features, assessing
hypotheses and running paper positions exactly as it did before Phase 11
existed. That is the same shape the SEC contact address already uses -- an
absent value reports the source as unconfigured rather than failing a refresh --
and it is the reason this feature can ship without making every user of the
project acquire an API key.

**One thing is caught, and it is the value being validated.** There is exactly
one ``try`` in this file. It wraps a single call to the reasoning domain's own
text contract, applied to the configured model id, and its only possible cause
is that value failing that contract -- which is the one failure this module is
entitled to translate. Everything else propagates untouched: a client factory
that returns nothing, a factory that raises, a programming error. Those are
defects in something the caller controls, and laundering them into "not
configured" would send the operator looking for a variable they had already set.

The model is checked *before* anything is built rather than by catching the
adapter's refusal afterwards, and the difference matters twice over. It keeps
the catch provably single-cause -- the adapter constructor has other reasons to
raise, and a handler wrapped around it could not tell them apart. And it lets
the same answer serve both entry points, so :func:`describe_reasoning_configuration`
and :func:`build_reasoning_service` cannot disagree: an interface that reported
"configured" and then failed to compose would be a contradiction the user
discovers instead of the tests.

A malformed value is still not reported as an absent one. It gets its own
sentence, saying the variable is set and its value cannot be used, so the
remedy on screen matches the mistake that was made.

**The credential is a local.** It is read from a mapping, handed to the client
factory as a keyword argument, and then it is gone. It is not stored on this
module, not returned, not placed on the provider or the service, not written
into a packet, a request, a fingerprint or a snapshot, and it is never named in
any message this module produces. The client that receives it necessarily holds
it -- that is what a client is for -- and no claim is made otherwise. The
boundary this module keeps is narrower and checkable: the credential does not
escape the client.

No default model id is written here. Model identifiers are operational
configuration and age on their own schedule; one hardcoded today would go stale
quietly and resurface much later as a transport failure, which is a
configuration mistake wearing an outage's costume. Requiring the variable makes
the mistake say what it is.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

import anthropic

from src.application.reasoning import ReasoningService
from src.reasoning.anthropic_adapter import AnthropicReasoningProvider
from src.reasoning.models import ReasoningError, require_text

#: The two variables, and the only two. Names are exported so an interface can
#: tell the user what to set without retyping the strings; values never are.
ANTHROPIC_API_KEY_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL_VAR = "ANTHROPIC_MODEL"

#: The adapter's bound on a model id, applied here so a value it would refuse is
#: reported as unusable configuration instead of arriving as an exception the
#: interface layer has no vocabulary to catch.
#:
#: The adapter spells this bound inline, so there is no constant to derive it
#: from and this is a second copy. A copy that agrees today and answers to
#: nobody afterwards is exactly what this project refuses elsewhere, so the two
#: are held together by a test that drives the *adapter* at the boundary in both
#: directions: a model id of this length must be accepted and one character more
#: must be refused. Change either side and that test fails immediately.
MAX_MODEL_ID_CHARS = 128

#: Shown when both are present. Deliberately says nothing about whether the
#: credential *works*: finding that out costs a call, and answering a
#: configuration question with a paid request is exactly what the local
#: availability check exists to avoid.
CONFIGURED_MESSAGE = "AI explanation is configured."

#: What the client factory has to be. Kept as an alias rather than spelled out
#: at each use so the seam is one named thing; the vendor's own client type is
#: deliberately absent, because naming it here would put a vendor type in a
#: signature that leaves this module.
ClientFactory = Callable[..., Any]


def _configured_value(source: Mapping[str, str], name: str) -> str | None:
    """One variable's usable value, or ``None`` when there is not one.

    Missing, empty and whitespace-only collapse to the same answer on purpose.
    They are the same situation to the person reading the message -- the
    variable is not set to anything -- and the remedy is identical, so offering
    three states would be offering a distinction that changes nothing.

    Anything that is not a string is treated as absent too. That cannot arise
    from a real environment, but this mapping is injectable and a test double
    is a mapping like any other.
    """
    value = source.get(name)
    if not isinstance(value, str):
        return None
    # Stripped, because a value that arrived from a file usually brings a
    # newline with it, and a credential with a trailing newline fails
    # authentication in a way that looks nothing like a formatting problem.
    return value.strip() or None


def _read_configuration(
    environ: Mapping[str, str] | None,
) -> tuple[str | None, str | None, str | None]:
    """The key, the model, and what is wrong with the model if anything.

    One reading, shared by both entry points, so the question "can this be
    composed?" has exactly one answer however it is asked.

    ``environ`` is injectable so no test depends on the developer's shell, and
    ``os.environ`` is consulted only when nothing was supplied -- a caller who
    passes a mapping gets that mapping and nothing else, so a test cannot be
    quietly influenced by a variable the machine happened to have set.

    The model is put through the reasoning domain's own text contract rather
    than through rules restated here: the adapter applies that same contract,
    and two hand-written copies of "non-empty, bounded, no control characters"
    would drift the first time either was edited. The failure it raises names
    the variable and the category of problem and never the value -- which is
    why the message is safe to hand straight to a person.
    """
    source = os.environ if environ is None else environ
    api_key = _configured_value(source, ANTHROPIC_API_KEY_VAR)

    raw_model = _configured_value(source, ANTHROPIC_MODEL_VAR)
    if raw_model is None:
        return api_key, None, None
    try:
        # The one handler in this module, around the one call whose only
        # possible failure is the value it was given.
        model_id = require_text(
            raw_model, ANTHROPIC_MODEL_VAR, maximum=MAX_MODEL_ID_CHARS
        )
    except ReasoningError as exc:
        return api_key, None, str(exc)
    return api_key, model_id, None


def _build_anthropic_client(*, api_key: str) -> Any:
    """The default seam: one client, from one key, and no request.

    Constructing a client opens no connection -- the first byte goes out when
    something is asked -- so this is safe to do while merely deciding whether
    the feature can be offered. Retry and timeout are deliberately not set
    here: Stage D sets both explicitly on every call, and a second owner for
    either is a value that can drift from the one the adapter documents.
    """
    return anthropic.Anthropic(api_key=api_key)


def build_reasoning_service(
    environ: Mapping[str, str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
) -> ReasoningService | None:
    """The composed service, or ``None`` when the feature is not configured.

    ``None`` rather than an exception, because "no API key" is not an error
    condition -- it is the state this project ships in. A caller that must know
    *why* asks :func:`describe_reasoning_configuration`, which answers the same
    question in words meant for a person.

    When either value is absent, nothing at all happens: no factory call, no
    client, no provider, no service, no socket. That matters more than it
    looks. This function is the one an interface calls to decide whether to
    offer the feature, and deciding must not cost anything.

    Everything the provider and the service need is read off what was built
    before them. The model reaches the request through ``provider.model_id``
    and the provider identity through ``provider.provider_id``, exactly as
    Stage E arranged, so there is no second copy of either to disagree with the
    adapter that will be asked.
    """
    api_key, model_id, _ = _read_configuration(environ)
    if api_key is None or model_id is None:
        return None

    factory = _build_anthropic_client if client_factory is None else client_factory
    client = factory(api_key=api_key)

    # Adapter defaults are left alone -- provider_id, timeout_seconds,
    # max_tokens and the monotonic clock all stay Stage D's. Restating one here
    # would move its ownership to a file that has no business having an opinion
    # about how long a call may take.
    provider = AnthropicReasoningProvider(client, model_id=model_id)
    return ReasoningService(provider)


def describe_reasoning_configuration(
    environ: Mapping[str, str] | None = None,
) -> str:
    """One line for a person: configured, or which variable to set.

    Names variables, never values. The message ends up in a screenshot, a bug
    report or a support thread eventually, and a status line that quoted a
    credential -- or its length, or its first few characters -- would be a
    credential leak with a helpful tone.

    "Set to something unusable" gets its own wording rather than being folded
    into "not set". They are different mistakes with different remedies, and
    telling someone a variable is missing when they can see it in their own
    shell is how a status line loses its reader's trust.
    """
    api_key, model_id, model_problem = _read_configuration(environ)

    problems = []
    if api_key is None:
        problems.append(f"{ANTHROPIC_API_KEY_VAR} is not configured")
    if model_problem is not None:
        problems.append(f"{model_problem} -- the variable is set but unusable")
    elif model_id is None:
        problems.append(f"{ANTHROPIC_MODEL_VAR} is not configured")

    if not problems:
        return CONFIGURED_MESSAGE
    return (
        f"AI explanation is unavailable because {' and '.join(problems)}. "
        "See .env.example. Everything else on this dashboard works without it."
    )


__all__ = [
    "ANTHROPIC_API_KEY_VAR",
    "ANTHROPIC_MODEL_VAR",
    "CONFIGURED_MESSAGE",
    "build_reasoning_service",
    "describe_reasoning_configuration",
]
