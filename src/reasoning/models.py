"""Frozen records for grounded reasoning. No provider, no prompt text, no I/O.

Every model here refuses to hold something it cannot honestly describe. A
packet with a naive timestamp, a duplicate evidence id, a NaN feature value or
an unknown schema version is not constructed and then flagged -- it raises,
because a record that has to be checked after construction will eventually be
used before it is checked.

The vocabulary is deliberately small. There is one reasoning kind, three claim
types, and no field anywhere that could express a recommendation, a target, a
probability or a score. That is not a matter of prompt wording: an output shape
with nowhere to put advice cannot carry it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

#: Bumped when the meaning of a packet field changes. An unknown version is
#: refused rather than interpreted, exactly as the scanner refuses an unknown
#: configuration version: a later writer may have changed what a field means.
EVIDENCE_SCHEMA_VERSION = 1

# -- limits --------------------------------------------------------------
#
# Every cap is sized against what the pipeline actually produces today (a
# three-hypothesis ensemble, two to three feature values per observation) with
# enough headroom that a larger ensemble is not an outage. They exist to bound
# a payload that leaves this machine, so none of them may be raised casually.

#: The ensemble is three hypotheses. Sixteen leaves room to grow without ever
#: letting an accidental loop build an unbounded packet.
MAX_PACKET_OBSERVATIONS = 16

#: Observed maximum today is three feature values per hypothesis.
MAX_OBSERVATION_EVIDENCE_ITEMS = 16

#: ``ReasonCode`` has thirteen members and ``AssessmentReasonCode`` eight, so no
#: honest record reaches this bound.
MAX_REASON_CODES = 16

MAX_SYMBOL_CHARS = 32
MAX_HYPOTHESIS_ID_CHARS = 128
MAX_FEATURE_NAME_CHARS = 200
MAX_FINGERPRINT_CHARS = 128
MAX_EVIDENCE_ID_CHARS = 512

#: Bound for every free-text field a model may later fill. Applied at Stage A so
#: the ceiling exists before there is anything to put under it.
MAX_REASONING_TEXT_CHARS = 2000

MAX_CLAIMS = 24
MAX_EVIDENCE_IDS_PER_CLAIM = 16
MAX_NOTES = 12


class ReasoningError(Exception):
    """Base class for every reasoning-domain failure."""


# -- vocabulary ----------------------------------------------------------


class ReasoningKind(str, Enum):
    """What the model is being asked to do.

    Exactly one member. An earlier draft split explanation from conflict
    explanation, but a conflict is not a different task -- it is the same task
    over a packet whose assessment happens to be conflicted, and the packet
    already says so. Two kinds would have meant two prompts, two versions and
    two evaluation matrices for one behaviour.
    """

    EXPLAIN_RESEARCH = "explain_research"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ClaimType(str, Enum):
    """How a claim stands relative to the assessment being explained.

    There is deliberately no ``UNCERTAINTY`` member. Uncertainty is a statement
    about evidence that is *absent*, and absent evidence cannot be cited; giving
    it a claim type would force either an empty citation list -- which grounding
    must reject -- or an invented one. It lives in its own field instead.
    """

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXT = "context"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ReasoningFailureCode(str, Enum):
    """Stable, provider-neutral failure identities.

    Defined at Stage A because they are part of the result contract, not
    because any provider exists yet. The split that matters is operational
    versus content: a provider outage and a model that cited evidence it was
    never given are different facts about different things, and collapsing them
    would make an outage look like a hallucination.

    There is no ``INVALID_RESPONSE``: an adapter cannot reliably tell an
    unparseable body from a schema violation, and a distinction that cannot be
    made honestly should not be offered.
    """

    # operational -- the request did not complete
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    REQUEST_INVALID = "request_invalid"

    # content -- a response arrived and could not be trusted
    OUTPUT_SCHEMA_FAILED = "output_schema_failed"
    GROUNDING_FAILED = "grounding_failed"
    BOUNDARY_VIOLATION = "boundary_violation"

    UNEXPECTED = "unexpected"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_operational(self) -> bool:
        return self in _OPERATIONAL_CODES


_OPERATIONAL_CODES = frozenset(
    {
        ReasoningFailureCode.PROVIDER_UNAVAILABLE,
        ReasoningFailureCode.RATE_LIMITED,
        ReasoningFailureCode.AUTHENTICATION_FAILED,
        ReasoningFailureCode.REQUEST_INVALID,
        ReasoningFailureCode.UNEXPECTED,
    }
)


# -- helpers -------------------------------------------------------------


def require_aware(value: object, label: str) -> datetime:
    """A timezone-aware datetime in UTC. Naive input is refused, not assumed.

    A naive timestamp in a causal record is not a small problem: it would make
    the cutoff comparison depend on whichever timezone the reader happened to
    be in.
    """
    if not isinstance(value, datetime):
        raise ReasoningError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReasoningError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def require_text(value: object, label: str, *, maximum: int) -> str:
    """A bounded, non-empty, control-character-free string."""
    if not isinstance(value, str):
        raise ReasoningError(f"{label} must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ReasoningError(f"{label} must not be empty")
    if len(text) > maximum:
        raise ReasoningError(f"{label} exceeds {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ReasoningError(f"{label} contains control characters")
    return text


#: Characters that separate the parts of an evidence id. A component containing
#: one of these could forge a different id, so they are refused at the source.
ID_DELIMITERS = (":", "#")


def require_identity_text(value: object, label: str, *, maximum: int) -> str:
    """A bounded string safe to concatenate into an evidence id.

    Evidence ids are delimiter-joined so a model can cite something legible, and
    that only works if no component can contain a delimiter. Without this check
    the join is not injective:

        obs:{a:v1:b}:v2:{c}   ==   obs:{a}:v1:{b:v2:c}

    Two genuinely different observations would then share one id, and a citation
    to either would silently resolve to the other. Refusing the delimiter at the
    source is cheaper and more honest than escaping it, and costs nothing real:
    hypothesis ids are slugs, fingerprints are hex, and feature names are
    generated from a spec that contains neither character.
    """
    text = require_text(value, label, maximum=maximum)
    for delimiter in ID_DELIMITERS:
        if delimiter in text:
            raise ReasoningError(
                f"{label} may not contain {delimiter!r}: it separates the parts of "
                "an evidence id, and a component holding one could forge another "
                "fact's identity"
            )
    return text


def require_count(value: object, label: str) -> int:
    """A non-negative integer. ``bool`` is refused as a count."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReasoningError(f"{label} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ReasoningError(f"{label} must not be negative")
    return value


def require_finite(value: object, label: str) -> float | None:
    """A finite float, or ``None`` for a value the hypothesis did not have.

    NaN and infinity are refused rather than encoded. They are not JSON, a
    digest over them would not round-trip, and in this pipeline they would mean
    a feature computed something it should have reported as missing.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReasoningError(
            f"{label} must be a float or None, got {type(value).__name__}"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ReasoningError(f"{label} must be finite, got {value!r}")
    # -0.0 and 0.0 are equal everywhere in this pipeline, but serialise to
    # different bytes. Left alone, two packets whose evidence is numerically
    # identical would fingerprint differently and staleness would fire for no
    # reason. No feature ascribes meaning to the sign of zero.
    return 0.0 if number == 0.0 else number


def canonical_bytes(payload: Any) -> bytes:
    """Stable JSON encoding for hashing.

    Byte-for-byte the same rules the scanner's universe fingerprint uses --
    ``sort_keys`` makes key order irrelevant, ``ensure_ascii`` keeps the bytes
    identical whatever the platform encoding, and ``allow_nan`` is off because
    NaN is not JSON.

    It is re-implemented here rather than imported. ``src.reasoning`` must not
    import ``src.scanner``, and a boundary is worth more than four saved lines;
    a test pins these bytes against the same rules so the two cannot drift
    silently.

    Floats are *not* rounded. Python's shortest round-trip representation is
    deterministic for a given IEEE double, so rounding would add an arbitrary
    precision rule without adding stability.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _stamp(value: datetime) -> str:
    """Canonical timestamp text: UTC, ISO-8601, one representation only."""
    return value.astimezone(timezone.utc).isoformat()


def _frozen_mapping(pairs: Mapping[str, Any]) -> Mapping[str, Any]:
    """A read-only view over a private dict, sorted for a stable repr.

    The same shape ``ResearchObservation`` uses for its evidence: a record, not
    a scratchpad. The underlying dict is unreachable through the proxy, so a
    caller cannot mutate packet content after a fingerprint has been taken.
    """
    return MappingProxyType(dict(sorted(pairs.items())))


# -- evidence identity ---------------------------------------------------
#
# One owner. Every id a claim may cite is built by a function here, so a change
# to how identity is formed is a change in one place with one set of tests --
# an earlier draft had the packet building fact ids inline while a helper
# elsewhere built them a second way, and only one of the two was ever exercised.

#: A packet has one assessment state and one set of counts, so their ids are
#: fixed strings rather than derived ones.
FACT_ASSESSMENT_STATE = "fact:assessment-state"
FACT_ASSESSMENT_COUNTS = "fact:assessment-counts"


def reason_evidence_id(code: str) -> str:
    """The id of one assessment reason code."""
    return f"fact:reason:{require_identity_text(code, 'reason code', maximum=64)}"


def policy_evidence_id(policy_fingerprint: str) -> str:
    """The id of the policy that produced the assessment.

    The fingerprint is used whole. Shortening it for looks would let two
    policies share an id, and every citation to one would silently become a
    citation to the other.
    """
    return f"fact:policy:{policy_fingerprint}"


def observation_evidence_id(
    hypothesis_id: str, version: int, hypothesis_fingerprint: str
) -> str:
    """The id of one hypothesis' observation.

    Built from the identity triple the research layer already treats as
    hypothesis identity, and never from position in a list: a citation must
    survive the packet being re-ordered.
    """
    return (
        f"obs:{require_identity_text(hypothesis_id, 'hypothesis_id', maximum=MAX_HYPOTHESIS_ID_CHARS)}"
        f":v{require_count(version, 'version')}"
        f":{require_identity_text(hypothesis_fingerprint, 'hypothesis_fingerprint', maximum=MAX_FINGERPRINT_CHARS)}"
    )


def _require_str_tuple(
    values: object, label: str, *, maximum: int, item_max: int, identity: bool = False
) -> tuple[str, ...]:
    """A bounded tuple of strings; ``identity`` also refuses id delimiters."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ReasoningError(f"{label} must be a sequence of strings")
    if len(values) > maximum:
        raise ReasoningError(f"{label} holds more than {maximum} entries")
    check = require_identity_text if identity else require_text
    return tuple(
        check(value, f"{label} entry", maximum=item_max) for value in values
    )


# -- evidence ------------------------------------------------------------


@dataclass(frozen=True)
class PacketCounts:
    """How many hypotheses classified each way. Integers, never a score.

    Mirrors ``AssessmentCounts`` deliberately: four counts a reader can add up
    themselves, and nothing derived from them.
    """

    bullish: int
    bearish: int
    neutral: int
    insufficient: int

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        for name in ("bullish", "bearish", "neutral", "insufficient"):
            set_(self, name, require_count(getattr(self, name), name))

    def canonical(self) -> dict[str, int]:
        return {
            "bullish": self.bullish,
            "bearish": self.bearish,
            "neutral": self.neutral,
            "insufficient": self.insufficient,
        }


@dataclass(frozen=True)
class PacketObservation:
    """One hypothesis' classification, reduced to what an explanation needs.

    Carries the hypothesis' own identity -- id, version and fingerprint -- so a
    citation refers to a hypothesis rather than to a row number, and carries the
    feature values *that hypothesis actually used*. It deliberately does not
    carry the feature series those values came from: the values are the
    evidence, the series is the machinery.

    ``evidence_id`` is **derived, never stored**. Holding it beside the identity
    it is built from would allow a record whose id contradicts its own
    hypothesis -- and a citation to that id would then resolve to an observation
    that says it is something else. Derivation makes the contradiction
    unrepresentable rather than merely unlikely.
    """

    hypothesis_id: str
    version: int
    hypothesis_fingerprint: str
    state: str
    reason_codes: tuple[str, ...]
    timestamp: datetime
    evidence: Mapping[str, float | None]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "hypothesis_id",
             require_identity_text(self.hypothesis_id, "hypothesis_id",
                                   maximum=MAX_HYPOTHESIS_ID_CHARS))
        set_(self, "version", require_count(self.version, "version"))
        set_(self, "hypothesis_fingerprint",
             require_identity_text(self.hypothesis_fingerprint,
                                   "hypothesis_fingerprint",
                                   maximum=MAX_FINGERPRINT_CHARS))
        set_(self, "state", require_text(self.state, "state", maximum=64))
        set_(self, "reason_codes",
             _require_str_tuple(self.reason_codes, "reason_codes",
                                maximum=MAX_REASON_CODES, item_max=64,
                                identity=True))
        set_(self, "timestamp", require_aware(self.timestamp, "observation timestamp"))

        if not isinstance(self.evidence, Mapping):
            raise ReasoningError("evidence must be a mapping")
        if len(self.evidence) > MAX_OBSERVATION_EVIDENCE_ITEMS:
            raise ReasoningError(
                f"an observation may carry at most "
                f"{MAX_OBSERVATION_EVIDENCE_ITEMS} evidence values, "
                f"got {len(self.evidence)}"
            )
        cleaned: dict[str, float | None] = {}
        for name, value in self.evidence.items():
            key = require_identity_text(name, "evidence name",
                                        maximum=MAX_FEATURE_NAME_CHARS)
            if key in cleaned:
                raise ReasoningError(f"duplicate evidence name {key!r}")
            cleaned[key] = require_finite(value, f"evidence value for {key!r}")
        set_(self, "evidence", _frozen_mapping(cleaned))

    @property
    def evidence_id(self) -> str:
        """This observation's stable id, derived from its own identity."""
        return observation_evidence_id(
            self.hypothesis_id, self.version, self.hypothesis_fingerprint
        )

    def datum_id(self, feature_name: str) -> str:
        """The stable id of one feature value inside this observation."""
        return f"{self.evidence_id}#{feature_name}"

    def canonical(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
            "hypothesis_fingerprint": self.hypothesis_fingerprint,
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "timestamp": _stamp(self.timestamp),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class EvidencePacket:
    """Everything a model is allowed to know about one symbol, and nothing else.

    Bounded on purpose. This object is what leaves the machine, so every field
    is here because an explanation would be wrong or dishonest without it:
    ``basis`` because RAW prices are a real limitation, ``warmup_bars`` and
    ``minimum_sufficient_observations`` because "not enough evidence yet" is a
    finding the model must be able to state, ``omitted_counts`` because a
    truncated packet that did not say so would invite a confident answer about
    evidence nobody sent.

    ``assessment_state`` and ``counts`` are optional because
    ``ResearchSnapshot.assessment`` is optional. Absence is represented as
    absence; there is no manufactured "unknown" state.
    """

    schema_version: int
    symbol: str
    interval: str
    basis: str
    data_cutoff: datetime
    policy_fingerprint: str
    warmup_bars: int
    minimum_sufficient_observations: int
    assessment_state: str | None
    counts: PacketCounts | None
    assessment_reason_codes: tuple[str, ...]
    observations: tuple[PacketObservation, ...]
    generated_at: datetime
    omitted_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ReasoningError(
                f"packet declares schema_version {self.schema_version!r}, but this "
                f"build understands only {EVIDENCE_SCHEMA_VERSION}; refusing to "
                "interpret it"
            )
        set_(self, "symbol", require_text(self.symbol, "symbol", maximum=MAX_SYMBOL_CHARS))
        set_(self, "interval", require_text(self.interval, "interval", maximum=16))
        set_(self, "basis", require_text(self.basis, "basis", maximum=64))
        set_(self, "data_cutoff", require_aware(self.data_cutoff, "data_cutoff"))
        set_(self, "generated_at", require_aware(self.generated_at, "generated_at"))
        if self.generated_at < self.data_cutoff:
            raise ReasoningError(
                "generated_at precedes data_cutoff: a packet cannot have been "
                "assembled before the research it describes was observed"
            )
        set_(self, "policy_fingerprint",
             require_identity_text(self.policy_fingerprint, "policy_fingerprint",
                                   maximum=MAX_FINGERPRINT_CHARS))
        set_(self, "warmup_bars", require_count(self.warmup_bars, "warmup_bars"))
        set_(self, "minimum_sufficient_observations",
             require_count(self.minimum_sufficient_observations,
                           "minimum_sufficient_observations"))

        if self.assessment_state is not None:
            set_(self, "assessment_state",
                 require_text(self.assessment_state, "assessment_state", maximum=64))
        if self.counts is not None and not isinstance(self.counts, PacketCounts):
            raise ReasoningError("counts must be a PacketCounts or None")
        if (self.assessment_state is None) != (self.counts is None):
            raise ReasoningError(
                "an assessment is either present with counts or absent entirely"
            )

        set_(self, "assessment_reason_codes",
             _require_str_tuple(self.assessment_reason_codes,
                                "assessment_reason_codes",
                                maximum=MAX_REASON_CODES, item_max=64,
                                identity=True))
        if self.assessment_state is None and self.assessment_reason_codes:
            raise ReasoningError(
                "reason codes describe an assessment; there is none to describe"
            )

        observations = tuple(self.observations)
        if len(observations) > MAX_PACKET_OBSERVATIONS:
            raise ReasoningError(
                f"a packet may carry at most {MAX_PACKET_OBSERVATIONS} observations, "
                f"got {len(observations)}"
            )
        for observation in observations:
            if not isinstance(observation, PacketObservation):
                raise ReasoningError(
                    "observations must be PacketObservation records, got "
                    f"{type(observation).__name__}"
                )
            if observation.timestamp > self.data_cutoff:
                raise ReasoningError(
                    f"observation {observation.evidence_id} is timestamped after the "
                    "data cutoff; an explanation may not see the future"
                )
        set_(self, "observations", observations)

        ids = [observation.evidence_id for observation in observations]
        if len(set(ids)) != len(ids):
            raise ReasoningError("evidence ids must be unique within a packet")

        if not isinstance(self.omitted_counts, Mapping):
            raise ReasoningError("omitted_counts must be a mapping")
        omitted = {
            require_text(name, "omitted_counts key", maximum=64):
                require_count(value, f"omitted_counts[{name!r}]")
            for name, value in self.omitted_counts.items()
        }
        set_(self, "omitted_counts", _frozen_mapping(omitted))

    # -- derived ---------------------------------------------------------

    @property
    def has_assessment(self) -> bool:
        return self.assessment_state is not None

    @property
    def evidence_ids(self) -> frozenset[str]:
        """Every id a claim may legitimately cite.

        Built here so grounding validation in a later stage compares against
        the packet rather than against a list a prompt happened to render.
        """
        ids = {
            observation.evidence_id
            for observation in self.observations
        }
        ids |= {
            observation.datum_id(name)
            for observation in self.observations
            for name in observation.evidence
        }
        ids.add(policy_evidence_id(self.policy_fingerprint))
        if self.has_assessment:
            ids.add(FACT_ASSESSMENT_STATE)
            ids.add(FACT_ASSESSMENT_COUNTS)
            ids |= {
                reason_evidence_id(code) for code in self.assessment_reason_codes
            }
        return frozenset(ids)

    def canonical(self, *, include_generated_at: bool = False) -> dict[str, Any]:
        """The packet as plain JSON-able data.

        ``generated_at`` is excluded by default and included only where
        provenance genuinely wants it. It records when the packet was built,
        which says nothing about what it contains -- letting it into the
        evidence digest would make an identical packet look like new evidence
        every time it was rebuilt, and staleness detection would never settle.
        """
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "basis": self.basis,
            "data_cutoff": _stamp(self.data_cutoff),
            "policy_fingerprint": self.policy_fingerprint,
            "warmup_bars": self.warmup_bars,
            "minimum_sufficient_observations": self.minimum_sufficient_observations,
            "assessment_state": self.assessment_state,
            "counts": self.counts.canonical() if self.counts is not None else None,
            "assessment_reason_codes": list(self.assessment_reason_codes),
            "observations": [o.canonical() for o in self.observations],
            "omitted_counts": dict(self.omitted_counts),
        }
        if include_generated_at:
            payload["generated_at"] = _stamp(self.generated_at)
        return payload


# -- request and result --------------------------------------------------


@dataclass(frozen=True)
class ReasoningRequest:
    """One reasoning job, fully described before anything is sent.

    Holds the packet plus the identity of the instructions and schema that will
    shape the answer. Every field is recorded on the result, so a later phase
    can ask *why was this explanation different?* and get an answer better than
    "the model changed".
    """

    reasoning_kind: ReasoningKind
    packet: EvidencePacket
    prompt_id: str
    prompt_version: int
    prompt_fingerprint: str
    output_schema_version: int
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "reasoning_kind", ReasoningKind(self.reasoning_kind))
        if not isinstance(self.packet, EvidencePacket):
            raise ReasoningError("packet must be an EvidencePacket")
        set_(self, "prompt_id", require_text(self.prompt_id, "prompt_id", maximum=64))
        set_(self, "prompt_version",
             require_count(self.prompt_version, "prompt_version"))
        set_(self, "prompt_fingerprint",
             require_text(self.prompt_fingerprint, "prompt_fingerprint",
                          maximum=MAX_FINGERPRINT_CHARS))
        set_(self, "output_schema_version",
             require_count(self.output_schema_version, "output_schema_version"))
        set_(self, "provider", require_text(self.provider, "provider", maximum=64))
        set_(self, "model", require_text(self.model, "model", maximum=128))
        set_(self, "created_at", require_aware(self.created_at, "created_at"))


@dataclass(frozen=True)
class ReasoningUsageMetadata:
    """What the call cost and how it behaved. Never what it said.

    Carries no prompt, no evidence text and no credential -- this is the record
    that is safe to log.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempt_count: int

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "provider", require_text(self.provider, "provider", maximum=64))
        set_(self, "model", require_text(self.model, "model", maximum=128))
        for name in ("input_tokens", "output_tokens", "latency_ms", "attempt_count"):
            set_(self, name, require_count(getattr(self, name), name))


@dataclass(frozen=True)
class ProviderReasoningResponse:
    """Raw provider output. Untrusted by type, not merely by convention.

    Deliberately a different class from :class:`ReasoningSnapshot`. Validation
    is what converts one into the other, so there is no way to render or store
    an unvalidated model response by accident -- the type will not fit.
    """

    payload: Mapping[str, Any]
    usage: ReasoningUsageMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise ReasoningError("payload must be a mapping")
        if not isinstance(self.usage, ReasoningUsageMetadata):
            raise ReasoningError("usage must be a ReasoningUsageMetadata")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class ReasoningClaim:
    """One attributable statement.

    Atomic on purpose. A paragraph with a citation at the end cannot be checked
    -- nothing says which sentence the citation covers. A claim that must name
    its evidence can be checked by a loop.
    """

    text: str
    claim_type: ClaimType
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "text",
             require_text(self.text, "claim text", maximum=MAX_REASONING_TEXT_CHARS))
        set_(self, "claim_type", ClaimType(self.claim_type))
        ids = _require_str_tuple(self.evidence_ids, "evidence_ids",
                                 maximum=MAX_EVIDENCE_IDS_PER_CLAIM,
                                 item_max=MAX_EVIDENCE_ID_CHARS)
        if len(set(ids)) != len(ids):
            raise ReasoningError("a claim must not cite the same evidence twice")
        set_(self, "evidence_ids", ids)


@dataclass(frozen=True)
class ReasoningSnapshot:
    """One validated explanation. Application-trusted, immutable, session-only.

    Records the two fingerprints separately. The evidence fingerprint answers
    "was this built from what is on screen now?"; the reasoning fingerprint
    answers "was it built the same way?". A new model must not make old evidence
    look stale, and only two digests can say that.
    """

    reasoning_kind: ReasoningKind
    symbol: str
    data_cutoff: datetime
    evidence_fingerprint: str
    reasoning_fingerprint: str
    prompt_id: str
    prompt_version: int
    output_schema_version: int
    summary: str
    summary_evidence_ids: tuple[str, ...]
    claims: tuple[ReasoningClaim, ...]
    uncertainties: tuple[str, ...]
    missing_information: tuple[str, ...]
    usage: ReasoningUsageMetadata
    generated_at: datetime

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "reasoning_kind", ReasoningKind(self.reasoning_kind))
        set_(self, "symbol",
             require_text(self.symbol, "symbol", maximum=MAX_SYMBOL_CHARS))
        set_(self, "data_cutoff", require_aware(self.data_cutoff, "data_cutoff"))
        set_(self, "generated_at", require_aware(self.generated_at, "generated_at"))
        set_(self, "evidence_fingerprint",
             require_text(self.evidence_fingerprint, "evidence_fingerprint",
                          maximum=MAX_FINGERPRINT_CHARS))
        set_(self, "reasoning_fingerprint",
             require_text(self.reasoning_fingerprint, "reasoning_fingerprint",
                          maximum=MAX_FINGERPRINT_CHARS))
        set_(self, "prompt_id", require_text(self.prompt_id, "prompt_id", maximum=64))
        set_(self, "prompt_version",
             require_count(self.prompt_version, "prompt_version"))
        set_(self, "output_schema_version",
             require_count(self.output_schema_version, "output_schema_version"))
        set_(self, "summary",
             require_text(self.summary, "summary", maximum=MAX_REASONING_TEXT_CHARS))
        set_(self, "summary_evidence_ids",
             _require_str_tuple(self.summary_evidence_ids, "summary_evidence_ids",
                                maximum=MAX_EVIDENCE_IDS_PER_CLAIM,
                                item_max=MAX_EVIDENCE_ID_CHARS))

        claims = tuple(self.claims)
        if len(claims) > MAX_CLAIMS:
            raise ReasoningError(f"at most {MAX_CLAIMS} claims, got {len(claims)}")
        for claim in claims:
            if not isinstance(claim, ReasoningClaim):
                raise ReasoningError(
                    f"claims must be ReasoningClaim records, got {type(claim).__name__}"
                )
        set_(self, "claims", claims)

        set_(self, "uncertainties",
             _require_str_tuple(self.uncertainties, "uncertainties",
                                maximum=MAX_NOTES, item_max=MAX_REASONING_TEXT_CHARS))
        set_(self, "missing_information",
             _require_str_tuple(self.missing_information, "missing_information",
                                maximum=MAX_NOTES, item_max=MAX_REASONING_TEXT_CHARS))
        if not isinstance(self.usage, ReasoningUsageMetadata):
            raise ReasoningError("usage must be a ReasoningUsageMetadata")

    @property
    def cited_evidence_ids(self) -> frozenset[str]:
        """Every id this explanation relies on, summary included."""
        ids = set(self.summary_evidence_ids)
        for claim in self.claims:
            ids |= set(claim.evidence_ids)
        return frozenset(ids)


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "FACT_ASSESSMENT_COUNTS",
    "FACT_ASSESSMENT_STATE",
    "MAX_CLAIMS",
    "MAX_EVIDENCE_ID_CHARS",
    "MAX_EVIDENCE_IDS_PER_CLAIM",
    "MAX_FEATURE_NAME_CHARS",
    "MAX_FINGERPRINT_CHARS",
    "MAX_HYPOTHESIS_ID_CHARS",
    "MAX_NOTES",
    "MAX_OBSERVATION_EVIDENCE_ITEMS",
    "MAX_PACKET_OBSERVATIONS",
    "MAX_REASON_CODES",
    "MAX_REASONING_TEXT_CHARS",
    "MAX_SYMBOL_CHARS",
    "ClaimType",
    "EvidencePacket",
    "PacketCounts",
    "PacketObservation",
    "ProviderReasoningResponse",
    "ReasoningClaim",
    "ReasoningError",
    "ReasoningFailureCode",
    "ReasoningKind",
    "ReasoningRequest",
    "ReasoningSnapshot",
    "ReasoningUsageMetadata",
    "ID_DELIMITERS",
    "canonical_bytes",
    "observation_evidence_id",
    "policy_evidence_id",
    "reason_evidence_id",
    "require_aware",
    "require_count",
    "require_identity_text",
    "require_finite",
    "require_text",
]
