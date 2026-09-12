"""The instructions and the output contract, versioned as production artifacts.

A prompt is not a string literal someone tweaks between runs. It decides what a
model is asked and therefore what comes back, so it is versioned, fingerprinted
and recorded on every result -- otherwise Phase 13 cannot tell "the model got
worse" from "someone edited the prompt".

Four components, never one blob:

``SYSTEM_POLICY``
    durable boundaries. Rules that hold for every job of this kind.
``TASK_INSTRUCTION``
    this job, and only this job.
``OUTPUT_SCHEMA``
    the machine-checkable contract the answer must satisfy.
evidence
    assembled per call by :func:`evidence_for_model`, and framed as data.

The separation is the point. Evidence is serialized as JSON and never
concatenated into the instruction text, so nothing arriving from outside can be
read as an instruction. There is no vendor message format here: how these four
become a provider's request shape is an adapter's problem, not the domain's.

The prompt fingerprint covers the system policy and task instruction **exactly**
-- byte for byte, no whitespace normalisation. A reflow changes how a model
reads the text, so a reflow must change the digest. The output schema is not
part of it: it is versioned separately by ``OUTPUT_SCHEMA_VERSION``, because a
schema change is a contract change requiring a validator change, while a prompt
change is a wording change requiring an evaluation.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .models import EvidencePacket, ReasoningError

PROMPT_ID = "explain_research"
PROMPT_VERSION = 1

#: Bumped when the response *shape* changes -- a field added, removed, renamed
#: or retyped. Rewording an instruction bumps ``PROMPT_VERSION`` instead.
OUTPUT_SCHEMA_VERSION = 1


SYSTEM_POLICY = """\
You explain research evidence that has already been computed. You do not \
produce it, extend it, or judge it.

Rules that always apply:

1. Explain only the evidence supplied in this request. Do not use outside \
knowledge about the company, the market, or recent events.
2. Every factual statement must cite one or more evidence_ids from the supplied \
evidence.
3. Never write an evidence_id that does not appear in the supplied evidence.
4. If the evidence does not settle something, say so in "uncertainties" rather \
than guessing.
5. Do not give recommendations or advice. Do not mention target prices, \
position sizes, expected returns, probabilities, or confidence values.
6. "bullish" and "bearish" are labels for what the evidence looks like. They are \
not instructions to act, and must never be described as such.
7. Return only the JSON object described in the output schema, with no \
additional keys and no text outside it.\
"""


TASK_INSTRUCTION = """\
Explain what this research found and why it reached that conclusion.

Write a short summary, then a claim for each distinct point worth making. Ground \
every claim in the specific hypotheses and values it rests on. Where hypotheses \
disagree, say so plainly and cite both sides. Where the evidence is thin, say \
what it does not establish.

Be concise. Prefer fewer, better-grounded claims over many shallow ones.\
"""


#: The response contract, described for the model in the same terms the schema
#: validator enforces. Kept in one place so the two cannot drift apart.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "claims", "uncertainties"],
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "object",
            "required": ["text", "evidence_ids"],
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "evidence_ids"],
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
}


def _prompt_fingerprint() -> str:
    """Digest of the trusted instruction text, byte for byte.

    A NUL byte separates the two components so that moving text from the end of
    the policy to the start of the task cannot leave the digest unchanged.
    """
    return hashlib.sha256(
        SYSTEM_POLICY.encode("utf-8") + b"\x00" + TASK_INSTRUCTION.encode("utf-8")
    ).hexdigest()


PROMPT_FINGERPRINT = _prompt_fingerprint()


# -- evidence, as the model sees it --------------------------------------


def evidence_for_model(packet: EvidencePacket) -> dict[str, Any]:
    """The packet rendered as the data a model may reason over.

    Every id the model is allowed to cite appears here **beside the fact it
    names**. An id without its fact would be an identifier the model could
    quote but not understand, which is how a citation becomes decoration.

    Application metadata is deliberately absent. ``generated_at`` records when
    the packet was assembled, the fingerprints identify it for staleness and
    provenance, and the schema version tells this build how to read it -- none
    of them are evidence about a symbol, and sending them would invite the model
    to reason about our bookkeeping.
    """
    if not isinstance(packet, EvidencePacket):
        raise ReasoningError("evidence_for_model needs an EvidencePacket")

    facts: list[dict[str, Any]] = [
        {
            "evidence_id": f"fact:policy:{packet.policy_fingerprint}",
            "fact": "the hypothesis ensemble and aggregation policy that produced "
                    "this assessment",
            "value": packet.policy_fingerprint,
        }
    ]
    if packet.has_assessment:
        facts.append({
            "evidence_id": "fact:assessment-state",
            "fact": "the combined research classification",
            "value": packet.assessment_state,
        })
        facts.append({
            "evidence_id": "fact:assessment-counts",
            "fact": "how many hypotheses classified each way",
            "value": {
                "bullish": packet.counts.bullish,
                "bearish": packet.counts.bearish,
                "neutral": packet.counts.neutral,
                "insufficient": packet.counts.insufficient,
            },
        })
        facts.extend(
            {
                "evidence_id": f"fact:reason:{code}",
                "fact": "a reason code the aggregation recorded",
                "value": code,
            }
            for code in packet.assessment_reason_codes
        )

    observations = [
        {
            "evidence_id": observation.evidence_id,
            "hypothesis_id": observation.hypothesis_id,
            "version": observation.version,
            "state": observation.state,
            "reason_codes": list(observation.reason_codes),
            "observed_bar_opened_at": observation.timestamp.isoformat(),
            "values": [
                {
                    "evidence_id": observation.datum_id(name),
                    "feature": name,
                    "value": value,
                }
                for name, value in observation.evidence.items()
            ],
        }
        for observation in packet.observations
    ]

    return {
        "symbol": packet.symbol,
        "interval": packet.interval,
        "price_basis": packet.basis,
        "data_cutoff": packet.data_cutoff.isoformat(),
        "warmup_bars": packet.warmup_bars,
        "minimum_sufficient_observations": packet.minimum_sufficient_observations,
        "assessment_present": packet.has_assessment,
        "facts": facts,
        "observations": observations,
    }


__all__ = [
    "OUTPUT_SCHEMA",
    "OUTPUT_SCHEMA_VERSION",
    "PROMPT_FINGERPRINT",
    "PROMPT_ID",
    "PROMPT_VERSION",
    "SYSTEM_POLICY",
    "TASK_INSTRUCTION",
    "evidence_for_model",
]
