"""One use case: explain the research the user is already looking at.

    ResearchSnapshot            [deterministic, already built]
            |
            v
    build_packet                bounded evidence, canonical builder
            |
            v
    has_assessment?             no  ->  refuse, spend nothing
            |
            v
    ReasoningRequest            provenance assembled from owners, never retyped
            |
            v
    ReasoningProvider.generate  one call, whoever the provider is
            |
            v
    validate_provider_response  ->  ReasoningSnapshot   [trusted]

This module is the whole distance between deterministic research and a trusted
explanation, and it is deliberately the only place that distance is travelled:
nothing above it should have to remember the order of these steps, and nothing
below it may skip one.

**Provider-neutral, and structurally so.** It depends on the provider contract,
never on an implementation -- there is no vendor name here, no client, no key,
and nothing is read from the surrounding process. Which service answers, and how it is configured, is a
composition question that belongs where configuration already lives; this
module only needs something that can be asked. The existing Phase 7 firewall
already forbids a vendor import in this layer, so the neutrality is enforced
rather than merely intended.

**Nothing is retyped.** The evidence threshold is imported from the module that
governs the assessment, provider and model are read off the injected provider,
and prompt identity comes from the committed constants. Every value that
appears in a request has exactly one owner somewhere else, because a second
copy of any of them is a value that can drift from the thing it claims to
describe -- and a request whose provenance is subtly wrong produces an
explanation filed under the wrong evidence.

**Absence is not insufficiency.** A warming-up ensemble still reaches a verdict
-- ``INSUFFICIENT_DATA`` is a real assessment with real reason codes, and
explaining it is useful. What cannot be explained is an assessment that does
not exist at all, which happens when no bars arrived. That case is refused
before a provider is touched, so asking costs nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from src.application.errors import ApplicationError, FailureKind
from src.application.snapshot import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    ResearchSnapshot,
)
from src.reasoning.evidence import build_packet
from src.reasoning.models import (
    EvidencePacket,
    ReasoningFailureCode,
    ReasoningKind,
    ReasoningRequest,
    ReasoningSnapshot,
)
from src.reasoning.prompts import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
)
from src.reasoning.providers import ReasoningProvider, ReasoningProviderError
from src.reasoning.validation import (
    ReasoningValidationError,
    validate_provider_response,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReasoningAvailability(str, Enum):
    """Whether this research result can be explained at all.

    Two members, and research-semantic only. Whether a provider is configured
    is not a state here: a service is constructed with one or it is not
    constructed, so "no provider" cannot be a condition this type has to
    describe. Adding transport states -- rate limited, unauthenticated -- would
    be worse still, because answering them would require the call this question
    exists to avoid.
    """

    AVAILABLE = "available"
    NO_ASSESSMENT = "no_assessment"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ReasoningUnavailable(ApplicationError):
    """An explanation was requested for research that has no assessment.

    Deliberately not a :class:`ReasoningFailureCode`. Nothing was asked of a
    provider and nothing came back, so this is not a reasoning failure at all
    -- it is a request the application declines to make, which is why it uses
    the application's own error vocabulary.
    """

    def __init__(self, message: str) -> None:
        super().__init__(FailureKind.REQUEST, "reasoning", message)


class ReasoningService:
    """Explains one research result, using whichever provider it was given.

    Holds two injected dependencies and no state of its own. There is no
    memoisation and no last-result field: two requests for the same explanation
    are two questions, and quietly answering the second from the first would
    hide a changed model, a changed prompt, or a provider that had started
    failing.
    """

    def __init__(self, provider: ReasoningProvider, *, now: Clock = _utc_now) -> None:
        self._provider = provider
        self._now = now

    # -- can this be explained at all? -----------------------------------

    def availability(self, snapshot: ResearchSnapshot) -> ReasoningAvailability:
        """Local, free, and exactly what the explanation would see.

        The question is answered by building the real packet and asking it,
        rather than by reading ``snapshot.assessment`` directly. Those two can
        only ever agree today, but only one of them is the value a model would
        actually be shown -- and an interface that enables a control on one
        basis while the call refuses on another is the kind of disagreement
        nobody finds until a user does.

        No provider is contacted. Deciding whether to offer an explanation must
        not cost what the explanation costs.
        """
        return (
            ReasoningAvailability.AVAILABLE
            if self._packet(snapshot, self._now()).has_assessment
            else ReasoningAvailability.NO_ASSESSMENT
        )

    # -- the explanation --------------------------------------------------

    def explain(self, snapshot: ResearchSnapshot) -> ReasoningSnapshot:
        """One packet, one request, one call, one validation.

        The eligibility check is repeated here rather than trusted to the
        caller. An interface that only disables a button leaves the policy in
        the interface, and the next caller is a script.

        Failures are passed through as they are. A provider outage and an
        answer that cited evidence it was never given are different facts about
        different things, both already carry a
        :class:`~src.reasoning.models.ReasoningFailureCode`, and flattening them
        into one application error would throw away the distinction the whole
        layer below was built to preserve.
        """
        moment = self._now()
        packet = self._packet(snapshot, moment)
        if not packet.has_assessment:
            raise ReasoningUnavailable(
                "this research has no assessment to explain; an explanation "
                "would have nothing to be grounded in"
            )

        request = ReasoningRequest(
            reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH,
            packet=packet,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            prompt_fingerprint=PROMPT_FINGERPRINT,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            # Read off the provider rather than configured a second time. The
            # adapter refuses a request naming a different model, and the only
            # way to make that check unfailable is to have nowhere else to
            # write the answer.
            provider=self._provider.provider_id,
            model=self._provider.model_id,
            created_at=moment,
        )

        response = self._provider.generate(request)
        return validate_provider_response(request, response, generated_at=moment)

    # -- the one place a packet is built ----------------------------------

    def _packet(self, snapshot: ResearchSnapshot, moment: datetime) -> EvidencePacket:
        """The canonical builder, with the threshold that governed the verdict.

        ``MINIMUM_SUFFICIENT_OBSERVATIONS`` is imported from the module whose
        ``build_policy`` hands the same binding to the assessment. Writing the
        number here instead would create a second copy that agrees today and
        answers to nobody afterwards -- and because the policy fingerprint
        covers the threshold, a packet carrying a different one would describe
        an assessment that was never made.

        One timestamp per call, captured by the caller and threaded through, so
        the packet, the request and the validation all speak about the same
        instant instead of three neighbouring ones.
        """
        return build_packet(
            snapshot,
            now=moment,
            minimum_sufficient_observations=MINIMUM_SUFFICIENT_OBSERVATIONS,
        )


__all__ = [
    "Clock",
    "ReasoningAvailability",
    "ReasoningFailureCode",
    "ReasoningProviderError",
    "ReasoningService",
    "ReasoningSnapshot",
    "ReasoningUnavailable",
    "ReasoningValidationError",
]
