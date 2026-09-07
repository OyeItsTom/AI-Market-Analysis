"""The first real adapter: one bounded call to an external model service.

    ReasoningRequest              [trusted]
            |
            v
    AnthropicReasoningProvider    <- this module
            |
            v
    the service                   [external, untrusted]
            |
            v
    ProviderReasoningResponse     [untrusted]
            |
            v
    validate_provider_response -> ReasoningSnapshot   [trusted]

This is the only module in the package allowed to name a vendor, and it is
deliberately the thinnest thing that can work: it translates a request into one
request body, makes exactly one call, and turns whatever comes back into the
untrusted response type. It decides nothing about whether the answer is any
good. Native schema-constrained output makes a malformed answer rarer; it does
not make an answer trustworthy, so the validator still runs on every response
and this module never calls it.

**Three things it refuses to do**, each because the alternative is worse than
failing:

*It does not repair.* No filling in a missing citation, no dropping an unknown
key, no softening prohibited wording. A payload arrives here and leaves here
byte-identical.

*It does not carry a credential.* An already-constructed client is injected. The
adapter has no parameter for a key, reads nothing from the surrounding process,
and opens no file. Composing a client from local configuration is the caller's
job and lives outside this package.

*It does not retry.* The SDK retries twice by default, which would silently
break the provider contract and make one invocation cost three; retries are
switched off explicitly on every call, and the timeout is set explicitly because
the library default is ten minutes.

The failures it reports are transport facts only -- unreachable, throttled,
refused, rejected, or something it cannot classify. "The model wrote nonsense"
is not a transport fact: a call that completed and returned an unusable answer
is a *successful* call carrying an empty payload, which the validator then
refuses. Collapsing those two would make an outage and a bad answer look alike.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

import anthropic

from .models import (
    ProviderReasoningResponse,
    ReasoningError,
    ReasoningFailureCode,
    ReasoningRequest,
    ReasoningUsageMetadata,
    require_text,
)
from .prompts import OUTPUT_SCHEMA, SYSTEM_POLICY, TASK_INSTRUCTION, evidence_for_model
from .providers import ReasoningProviderError

#: This adapter's provider identity. A plain string, because the request already
#: carries provider and model as strings and a second identity system would only
#: give the two a way to disagree.
PROVIDER_ID = "anthropic"

#: A call that has not answered in a minute is not going to be useful to someone
#: waiting for an explanation. The library's own default is ten minutes, which
#: is a batch timeout wearing an interactive one's clothes.
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 600.0

#: Enough for a summary, several grounded claims and a few uncertainties, and
#: no more. The ceiling is a cost bound, not an ambition: nothing here benefits
#: from a longer answer, and the schema has nowhere to put one.
DEFAULT_MAX_TOKENS = 2048
MAX_MAX_TOKENS = 8192

#: How the evidence is framed inside the user turn. The instruction and the
#: data are separated by a label so that nothing arriving from the packet can be
#: read as a continuation of the instruction.
EVIDENCE_HEADING = "Evidence (JSON):"


def _require_positive_number(value: object, label: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReasoningError(f"{label} must be a number, got {type(value).__name__}")
    number = float(value)
    if not number > 0:
        raise ReasoningError(f"{label} must be positive")
    if number > maximum:
        raise ReasoningError(f"{label} must not exceed {maximum}")
    return number


def _require_positive_int(value: object, label: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReasoningError(f"{label} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ReasoningError(f"{label} must be at least 1")
    if value > maximum:
        raise ReasoningError(f"{label} must not exceed {maximum}")
    return value


def _canonical_json(payload: Any) -> str:
    """The evidence as one deterministic string.

    The same rules the rest of the package hashes with, for the same reason:
    two identical packets must produce identical bytes, or a request is not
    reproducible and neither is anything measured from it.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class AnthropicReasoningProvider:
    """One configured model, asked one question at a time.

    Satisfies the package's provider contract structurally: ``provider_id``,
    ``model_id``, and a ``generate`` that either returns an untrusted response
    or raises a transport failure. There is no third outcome.
    """

    def __init__(
        self,
        client: Any,
        *,
        model_id: str,
        provider_id: str = PROVIDER_ID,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client is None:
            raise ReasoningError(
                "an already-constructed client must be injected; this adapter "
                "never builds one and never holds a credential of its own"
            )
        if not callable(clock):
            raise ReasoningError("clock must be callable")
        self._client = client
        self._model_id = require_text(model_id, "model_id", maximum=128)
        self._provider_id = require_text(provider_id, "provider_id", maximum=64)
        self._timeout_seconds = _require_positive_number(
            timeout_seconds, "timeout_seconds", maximum=MAX_TIMEOUT_SECONDS
        )
        self._max_tokens = _require_positive_int(
            max_tokens, "max_tokens", maximum=MAX_MAX_TOKENS
        )
        self._clock = clock

    # -- identity --------------------------------------------------------

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    # -- the one call ----------------------------------------------------

    def generate(self, request: ReasoningRequest) -> ProviderReasoningResponse:
        """Ask once, and hand back whatever came out.

        Identity is checked first, before anything is sent. A request meant for
        a different model must not cost a call: the check is free and the call
        is not.
        """
        self._require_matching_identity(request)

        prepared = None
        try:
            prepared = self._vendor_request(request)
        except Exception:
            prepared = None
        if prepared is None:
            raise ReasoningProviderError(
                ReasoningFailureCode.UNEXPECTED,
                "the request could not be prepared for the provider",
            )

        # Both options are set here rather than trusted to the injected client:
        # a caller who forgot them would get the library defaults, which retry
        # twice and wait ten minutes, and the provider contract says neither.
        call = self._client.with_options(
            timeout=self._timeout_seconds, max_retries=0
        )

        started = self._clock()
        failure = None
        try:
            message = call.messages.create(**prepared)
        except anthropic.APITimeoutError:
            failure = (ReasoningFailureCode.PROVIDER_UNAVAILABLE,
                       "the provider did not answer within the time allowed")
        except anthropic.APIConnectionError:
            failure = (ReasoningFailureCode.PROVIDER_UNAVAILABLE,
                       "the provider could not be reached")
        except anthropic.RateLimitError:
            failure = (ReasoningFailureCode.RATE_LIMITED,
                       "the provider asked us to slow down")
        except anthropic.AuthenticationError:
            failure = (ReasoningFailureCode.AUTHENTICATION_FAILED,
                       "the provider rejected the caller's credential")
        except anthropic.PermissionDeniedError:
            failure = (ReasoningFailureCode.AUTHENTICATION_FAILED,
                       "the caller is not permitted to make this call")
        except (
            anthropic.BadRequestError,
            anthropic.NotFoundError,
            anthropic.UnprocessableEntityError,
        ):
            failure = (ReasoningFailureCode.REQUEST_INVALID,
                       "the provider refused the request we sent")
        except anthropic.InternalServerError:
            failure = (ReasoningFailureCode.PROVIDER_UNAVAILABLE,
                       "the provider reported an internal failure")
        except anthropic.APIError:
            failure = (ReasoningFailureCode.UNEXPECTED,
                       "the provider failed in a way this adapter does not classify")
        except Exception:
            # Last resort, and narrow: only what escaped the library's own error
            # hierarchy at the call boundary. BaseException is deliberately not
            # caught, so an interrupt still interrupts.
            failure = (ReasoningFailureCode.UNEXPECTED,
                       "the provider call failed unexpectedly")
        if failure is not None:
            # Raised *after* the handler, and the difference is not cosmetic.
            # ``raise ... from None`` inside a handler clears ``__cause__`` but
            # leaves the vendor exception on ``__context__``, where its message,
            # its response body -- and anything a caller had pasted into the
            # request -- stay reachable to whatever renders the failure. Once
            # the block has exited there is no context left to attach.
            raise ReasoningProviderError(*failure)
        elapsed = self._clock() - started

        usage = self._usage(message, elapsed)
        return ProviderReasoningResponse(payload=self._payload(message), usage=usage)

    # -- identity, before anything is spent -------------------------------

    def _require_matching_identity(self, request: object) -> None:
        """Exact equality, and never a rewrite.

        Both sides of this comparison are our own configuration, so there is
        nothing legitimate for a tolerance to absorb -- a mismatch means the
        caller wired the wrong adapter to the request, and answering it anyway
        would file the answer under a model that never saw the question.
        """
        if not isinstance(request, ReasoningRequest):
            raise ReasoningProviderError(
                ReasoningFailureCode.REQUEST_INVALID,
                "request must be a ReasoningRequest",
            )
        if request.provider != self._provider_id:
            raise ReasoningProviderError(
                ReasoningFailureCode.REQUEST_INVALID,
                "the request names a different provider than this adapter serves",
            )
        if request.model != self._model_id:
            raise ReasoningProviderError(
                ReasoningFailureCode.REQUEST_INVALID,
                "the request names a different model than this adapter serves",
            )

    # -- the request body -------------------------------------------------

    def _vendor_request(self, request: ReasoningRequest) -> dict[str, Any]:
        """The four committed pieces, in the shape this service expects.

        The policy goes in the system slot, the task and the evidence in the
        user turn, the schema in the output configuration. Nothing is retyped:
        the schema object is passed through by reference so there can be no
        second copy to drift from the one the validator enforces.
        """
        evidence = _canonical_json(evidence_for_model(request.packet))
        return {
            "model": self._model_id,
            "max_tokens": self._max_tokens,
            "system": SYSTEM_POLICY,
            "messages": [
                {
                    "role": "user",
                    "content": f"{TASK_INSTRUCTION}\n\n{EVIDENCE_HEADING}\n{evidence}",
                }
            ],
            "output_config": {
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
            },
        }

    # -- reading the answer -----------------------------------------------

    def _payload(self, message: object) -> Mapping[str, Any]:
        """The model's answer as an untrusted mapping, or an empty one.

        The single judgement made here is *did a JSON object come back*, which
        is the same question the untrusted response type already asks of its
        own field -- not a check on what the object says. Anything else that
        arrived, including well-formed JSON that is a list or a number, becomes
        an empty payload: the call succeeded, the answer was unusable, and
        saying so is the validator's job rather than this module's.

        **The first text block is the answer.** Not the first block that happens
        to parse, and not every text block joined together. Both of those are
        searches for something usable, and a search finds a plausible answer in
        a response that did not contain one -- joining would additionally invent
        a document the model never emitted. If the first text block is not a
        JSON object then the answer is not one, and later blocks get no vote.

        The unusable text is not kept. A rejected answer that survives in a
        record has a second chance at the reader it was rejected to protect.
        """
        content = getattr(message, "content", None)
        if content is None or isinstance(content, (str, bytes)) or not isinstance(
            content, (list, tuple)
        ):
            raise ReasoningProviderError(
                ReasoningFailureCode.UNEXPECTED,
                "the provider response did not have a readable content list",
            )

        text: str | None = None
        for block in content:
            if getattr(block, "type", None) == "text":
                candidate = getattr(block, "text", None)
                if isinstance(candidate, str):
                    text = candidate
                break
        if text is None:
            return {}

        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _usage(self, message: object, elapsed: float) -> ReasoningUsageMetadata:
        """What the call cost, and who answered it.

        The served model is recorded rather than checked. An alias resolving to
        a pinned version is ordinary and must not read as an outage; what would
        be dishonest is quietly filing the answer under the name we asked for,
        so the served name wins wherever the service supplies one.

        ``provider`` is *not* served. This service's response carries no field
        naming who answered, so the value here is this adapter's own configured
        id -- an accurate statement about which adapter made the call, and not,
        despite sitting beside a served model, a report from the far end.

        Token counts are never invented. If they cannot be read the call is
        reported as an integration failure, because a zero that means "we do
        not know" is indistinguishable from a zero that means "free".
        """
        raw = getattr(message, "usage", None)
        input_tokens = getattr(raw, "input_tokens", None)
        output_tokens = getattr(raw, "output_tokens", None)
        for value in (input_tokens, output_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReasoningProviderError(
                    ReasoningFailureCode.UNEXPECTED,
                    "the provider response did not report readable token usage",
                )

        served = getattr(message, "model", None)
        model = served.strip() if isinstance(served, str) and served.strip() else None

        return ReasoningUsageMetadata(
            provider=self._provider_id,
            model=model or self._model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # A clock that ran backwards is not evidence of a negative duration.
            latency_ms=max(0, round(elapsed * 1000)),
            # One invocation, one attempt: retries are switched off above, so
            # anything else here would be a number this adapter made up.
            attempt_count=1,
        )


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVIDER_ID",
    "AnthropicReasoningProvider",
]
