"""The provider contract: where a trusted request becomes an untrusted answer.

    ReasoningRequest            [trusted]
            |
            v
    ReasoningProvider.generate
            |
            v
    ProviderReasoningResponse   [untrusted]
            |
            v
    validate_provider_response  ->  ReasoningSnapshot   [trusted]

A provider is a transport, not an authority. It knows how to ask something
outside this process a question and how to hand back what came out; it does not
know what the answer means, and nothing here is allowed to decide that. The
module therefore holds a Protocol, one error type and a list of the failures a
transport is permitted to report -- and no logic that inspects a payload.

**Three identities, deliberately not reconciled.** Provider and model appear in
three places, and they answer three different questions:

``request.provider`` / ``request.model``
    who the caller *intended* to ask. This is trusted provenance, and it is what
    the reasoning fingerprint is computed from.
``provider.provider_id`` / ``provider.model_id``
    who this adapter, *as configured*, is going to ask.
``usage.provider`` / ``usage.model``
    who the response says actually answered. An observation, and untrusted like
    everything else that arrives from outside.

All three can disagree -- a configured adapter can be handed a request meant for
a different model, and a service can silently serve a substitute. Exposing them
separately is what makes that disagreement *visible*; deciding what to do about
it is a later stage's policy, and a provider that quietly rewrote one of them to
make the three agree would destroy the evidence that policy needs.

**Failures here are operational only.** A transport can report that it could not
be reached, that it was throttled, that it was refused, that the request was
malformed, or that something happened it cannot classify. It can never report
that a response failed the schema, cited evidence that does not exist, or used
prohibited vocabulary: those are judgements about content, they are made after
the fact by the validator, and a provider that graded its own output would be
marking its own homework.

The consequence is deliberate and is the point of the split: a **malformed
payload is a successful call**. It is returned intact -- unrepaired, unfiltered,
with its fabricated citations and its unknown keys still in it -- and refused
later, where refusing is somebody's job.

There is no retry here, and no clock. Retry policy needs real failure semantics
to be designed against, and there are none yet; a loop written now would be a
guess wearing the costume of a policy.
"""

from __future__ import annotations

from typing import Protocol

from .models import (
    MAX_VALIDATION_DETAIL_CHARS,
    ProviderReasoningResponse,
    ReasoningError,
    ReasoningFailureCode,
    ReasoningRequest,
)

#: Bound on a provider failure detail. Derived from the validation bound rather
#: than retyped: both exist for the same reason, and two literals would drift.
MAX_PROVIDER_DETAIL_CHARS = MAX_VALIDATION_DETAIL_CHARS

#: The failures a transport is allowed to report.
#:
#: Exactly the operational half of :class:`ReasoningFailureCode`, read from the
#: enum's own ``is_operational`` rather than retyped as a second list -- one
#: vocabulary, one owner. A test pins the resulting membership, so a later edit
#: that reclassified a code would have to say so out loud.
PROVIDER_FAILURE_CODES = frozenset(
    code for code in ReasoningFailureCode if code.is_operational
)


class ReasoningProviderError(ReasoningError):
    """A call that did not produce an answer, and why -- in transport terms.

    Separate from ``ReasoningValidationError`` because the two describe
    different worlds. "The service was throttled" and "the model cited evidence
    it was never given" are not degrees of the same problem, and a caller that
    could not tell them apart would report an outage as a hallucination, or
    worse, the other way round.

    ``detail`` is bounded, and bounding is all it is. Truncation is not
    redaction: this class does not inspect what it was handed and cannot know
    whether a caller put something in it that should not be there. The rule that
    a detail names a category and a stage -- never a credential, never a header,
    never a prompt, never a response body -- is the adapter's to keep, and it is
    written here because the code cannot enforce it.
    """

    def __init__(self, code: ReasoningFailureCode, detail: str) -> None:
        code = ReasoningFailureCode(code)
        if code not in PROVIDER_FAILURE_CODES:
            raise ReasoningError(
                f"{code.value!r} is a content failure and belongs to validation; a "
                "provider reports how the call went, never whether the answer "
                "could be trusted"
            )
        if not isinstance(detail, str):
            raise ReasoningError(
                f"detail must be a str, got {type(detail).__name__}"
            )
        self.code = code
        self.detail = detail.strip()[:MAX_PROVIDER_DETAIL_CHARS]
        super().__init__(f"{self.code.value}: {self.detail}")


class ReasoningProvider(Protocol):
    """What the rest of the system needs from anything that can be asked.

    Structural, and deliberately not ``runtime_checkable``. An ``isinstance``
    check against a Protocol asserts only that three names exist -- it would
    accept an object whose ``generate`` takes the wrong arguments and returns
    the wrong type -- so it reads as a guarantee while being a spelling check.
    Where the shape genuinely has to be asserted, the tests assert it against
    the real signatures.

    Synchronous. One question, one answer, one caller waiting: there is no
    concurrency in this path to justify colouring it, and adding it now would
    make every caller async for a future that may never need it.
    """

    @property
    def provider_id(self) -> str:
        """The service this adapter is configured to ask."""

    @property
    def model_id(self) -> str:
        """The model this adapter is configured to ask for."""

    def generate(self, request: ReasoningRequest) -> ProviderReasoningResponse:
        """Ask, and return whatever came back -- unexamined.

        The response is untrusted: its payload is returned exactly as received,
        with nothing repaired, filled in, reordered or removed. An implementation
        that "helped" here would be validating without the vocabulary to do it,
        in the one place where a plausible answer is more dangerous than a
        missing one.

        Raises :class:`ReasoningProviderError` when the call did not produce an
        answer at all. A response that arrived and is wrong is not an error
        here; it is the validator's to refuse.
        """


__all__ = [
    "MAX_PROVIDER_DETAIL_CHARS",
    "PROVIDER_FAILURE_CODES",
    "ReasoningProvider",
    "ReasoningProviderError",
]
