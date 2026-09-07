"""Phase 11A reasoning domain: the evidence an explanation may be built from.

This package answers one question -- *what is a language model allowed to
know?* -- and answers it as a value, not as a prompt. Everything here is a
frozen record or a pure function over one.

**It imports nothing from ``src``.** Not the application layer, not the
dashboard, not the news or feed layers, not the scanner, not the portfolio. A
``ResearchSnapshot`` arrives as a duck-typed argument and leaves as a bounded
:class:`~src.reasoning.models.EvidencePacket`; the domain objects themselves are
read and discarded. That keeps this package a leaf, the way the news and feed
packages are leaves, and it is what lets the existing Phase 7/8/9 firewalls
sweep these files without a single amendment.

Three properties are load-bearing and are enforced by construction rather than
by convention.

**Nothing heavy survives the boundary.** A packet holds strings, integers,
floats and timestamps. No ``BarSeries``, no ``FeatureSeries``, no
``ResearchSnapshot``. A hundred packets are a hundred small records, and a
packet cannot be used to reach back into the pipeline that produced it.

**Identity comes from the domain, never from position.** An evidence id is built
from the hypothesis identity the research layer already publishes -- id, version
and fingerprint -- so re-ordering a packet cannot change what a citation refers
to. Phase 12 will compare reasoning across runs; an id that moved when a list
was sorted would make that comparison meaningless.

**Two fingerprints, because two different questions are asked.** The evidence
fingerprint covers what was known. The reasoning fingerprint additionally covers
how it was reasoned about -- prompt, schema, provider, model. Changing the model
must not make the underlying evidence look stale, and only separate digests can
express that.

The package now also holds the versioned prompt contract, the validators that
turn an untrusted provider payload into a trusted snapshot, and the provider
contract itself -- a Protocol and an operational error type, with no adapter
behind it. There is still no network here, and no vendor.
"""

from __future__ import annotations

from .evidence import (
    build_packet,
    evidence_fingerprint,
    reasoning_fingerprint,
    research_context_fingerprint,
)
from .prompts import (
    OUTPUT_SCHEMA,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
    SYSTEM_POLICY,
    TASK_INSTRUCTION,
    evidence_for_model,
)
from .providers import (
    MAX_PROVIDER_DETAIL_CHARS,
    PROVIDER_FAILURE_CODES,
    ReasoningProvider,
    ReasoningProviderError,
)
from .validation import (
    ReasoningValidationError,
    validate_provider_response,
)
from .models import (
    EVIDENCE_SCHEMA_VERSION,
    MAX_EVIDENCE_ID_CHARS,
    MAX_HYPOTHESIS_ID_CHARS,
    MAX_OBSERVATION_EVIDENCE_ITEMS,
    MAX_PACKET_OBSERVATIONS,
    MAX_REASON_CODES,
    MAX_REASONING_TEXT_CHARS,
    MAX_VALIDATION_DETAIL_CHARS,
    MAX_SYMBOL_CHARS,
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
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "OUTPUT_SCHEMA",
    "OUTPUT_SCHEMA_VERSION",
    "PROMPT_FINGERPRINT",
    "PROMPT_ID",
    "PROMPT_VERSION",
    "SYSTEM_POLICY",
    "TASK_INSTRUCTION",
    "MAX_EVIDENCE_ID_CHARS",
    "MAX_HYPOTHESIS_ID_CHARS",
    "MAX_OBSERVATION_EVIDENCE_ITEMS",
    "MAX_PACKET_OBSERVATIONS",
    "MAX_PROVIDER_DETAIL_CHARS",
    "MAX_REASON_CODES",
    "MAX_REASONING_TEXT_CHARS",
    "MAX_VALIDATION_DETAIL_CHARS",
    "MAX_SYMBOL_CHARS",
    "PROVIDER_FAILURE_CODES",
    "EvidencePacket",
    "PacketCounts",
    "PacketObservation",
    "ProviderReasoningResponse",
    "ReasoningClaim",
    "ReasoningError",
    "ReasoningFailureCode",
    "ReasoningKind",
    "ReasoningProvider",
    "ReasoningProviderError",
    "ReasoningRequest",
    "ReasoningSnapshot",
    "ReasoningSummary",
    "ReasoningUsageMetadata",
    "ReasoningValidationError",
    "build_packet",
    "evidence_for_model",
    "evidence_fingerprint",
    "reasoning_fingerprint",
    "research_context_fingerprint",
    "validate_provider_response",
]
