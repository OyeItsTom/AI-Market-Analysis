"""Turning a research snapshot into the bounded evidence a model may see.

    ResearchSnapshot -> build_packet -> EvidencePacket -> (later) a request

One pure function and three digests. No I/O, no network, no clock of its own --
``now`` is injected so a packet is reproducible from its inputs alone, which is
what makes the fingerprints mean anything.

**The snapshot is read, never held.** Fields are copied out as strings, integers
and floats; the snapshot, its ``BarSeries`` and its ``FeatureSeries`` are not
referenced by the result. That is the memory bound this layer exists to give,
and it is also a privacy bound: what is not in the packet cannot leave the
machine.

**Duck-typed on purpose.** Nothing here imports the application layer, the
strategy package or the assessment package. The snapshot arrives as an object
with the attributes this module reads, exactly the way the view models format
records they do not import. That keeps this package a leaf and keeps every
existing firewall sweeping these files without amendment.

**Feature series are deliberately absent.** ``ResearchObservation.evidence``
already carries the feature values that hypothesis actually consulted. Copying
``FeatureSeries`` in as well would add no information and would open a second
interpretation path -- indicator values no hypothesis looked at, which a model
could reason from and produce a claim no deterministic rule supports.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping

from .models import (
    EVIDENCE_SCHEMA_VERSION,
    MAX_FEATURE_NAME_CHARS,
    MAX_OBSERVATION_EVIDENCE_ITEMS,
    MAX_PACKET_OBSERVATIONS,
    MAX_REASON_CODES,
    EvidencePacket,
    PacketCounts,
    PacketObservation,
    ReasoningError,
    ReasoningKind,
    canonical_bytes,
    require_aware,
    require_count,
    require_finite,
    require_identity_text,
    require_text,
)

def _enum_value(value: object, label: str) -> str:
    """The stable wire form of an enum-like value.

    Reads ``.value`` when present so ``Interval.DAY_1`` becomes ``"1d"`` rather
    than ``"Interval.DAY_1"``, and falls back to ``str`` for a plain string.
    Nothing is imported to do this: the domain enums are all ``str`` subclasses
    with a ``value``, and duck-typing them keeps this package a leaf.
    """
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise ReasoningError(f"{label} must be a string or string enum, got {value!r}")
    return raw


def _reason_codes(codes: object, label: str) -> tuple[str, ...]:
    """Reason codes as wire strings. Over the cap, the packet is refused.

    Reason codes are *why the assessment says what it says*. Dropping one would
    leave an explanation quietly missing part of its own justification, so the
    cap is a refusal rather than a truncation.
    """
    values = tuple(_enum_value(code, f"{label} entry") for code in codes)
    if len(values) > MAX_REASON_CODES:
        raise ReasoningError(
            f"{label} holds {len(values)} entries, over the {MAX_REASON_CODES} "
            "the packet may carry; refusing rather than explaining part of an "
            "assessment"
        )
    return values


def _observation_evidence(evidence: object, label: str) -> dict[str, float | None]:
    """One observation's feature values, sorted and validated.

    Sorted by feature name so the canonical form does not depend on the order a
    hypothesis happened to populate its mapping. Values are validated as finite
    floats or ``None``; ``None`` is a real outcome (the hypothesis had no value
    during warm-up) and is preserved rather than dropped.

    Over the cap the packet is refused. These values are the basis the
    hypothesis actually classified on; keeping some of them would describe a
    classification the remaining evidence does not account for.
    """
    if not isinstance(evidence, Mapping):
        raise ReasoningError(f"{label} must be a mapping, got {type(evidence).__name__}")
    cleaned: dict[str, float | None] = {}
    for name, value in evidence.items():
        key = require_identity_text(name, f"{label} name",
                                    maximum=MAX_FEATURE_NAME_CHARS)
        if key in cleaned:
            raise ReasoningError(f"duplicate {label} name {key!r}")
        cleaned[key] = require_finite(value, f"{label} value for {key!r}")
    if len(cleaned) > MAX_OBSERVATION_EVIDENCE_ITEMS:
        raise ReasoningError(
            f"{label} holds {len(cleaned)} values, over the "
            f"{MAX_OBSERVATION_EVIDENCE_ITEMS} the packet may carry; refusing "
            "rather than describing a classification on partial evidence"
        )
    return dict(sorted(cleaned.items()))


def build_packet(
    snapshot: Any, *, now: datetime, minimum_sufficient_observations: int
) -> EvidencePacket:
    """The bounded evidence for one research snapshot.

    Pure: the same snapshot, ``now`` and policy minimum produce the same packet,
    and nothing else is consulted. No news, no feeds, no scanner, no paper
    state, no provider, no file, no socket.

    ``minimum_sufficient_observations`` is **injected, not read**. It is a
    policy constant that lives in the application layer, which this package may
    not import, and it is not published on ``ResearchSnapshot``. Passing it in
    keeps the number honest: the alternative was defaulting to zero, which would
    have quietly told a model that no minimum exists and made "the ensemble is
    still warming up" unexplainable.

    Nothing is truncated. ``omitted_counts`` stays empty here and exists for the
    optional external evidence a later phase may add, where a sliding window
    genuinely can hold more than a packet should carry. Research observations
    are not that kind of evidence: every hypothesis contributed to the
    assessment, so dropping one would leave the packet carrying a verdict its
    own evidence cannot account for. Over any cap, construction is refused --
    the same choice the universe loader makes when a configuration names too
    many symbols.

    Raises :class:`ReasoningError` rather than repairing anything. An
    observation timestamped after the snapshot was built is refused outright --
    not clamped, not dropped -- because either would turn a broken causal
    invariant into a quiet one, and the whole point of the cutoff is that it can
    be trusted without re-derivation.
    """
    data_cutoff = require_aware(getattr(snapshot, "built_at", None), "snapshot.built_at")
    generated_at = require_aware(now, "now")

    symbol = require_text(getattr(snapshot, "symbol", None), "snapshot.symbol",
                          maximum=32)
    interval = _enum_value(getattr(snapshot, "interval", None), "snapshot.interval")
    basis = _enum_value(getattr(snapshot, "basis", None), "snapshot.basis")
    policy_fingerprint = require_text(
        getattr(snapshot, "policy_fingerprint", None), "snapshot.policy_fingerprint",
        maximum=128,
    )

    # -- the assessment, or its honest absence ---------------------------
    assessment = getattr(snapshot, "assessment", None)
    if assessment is None:
        assessment_state: str | None = None
        counts: PacketCounts | None = None
        assessment_reason_codes: tuple[str, ...] = ()
    else:
        assessment_state = _enum_value(
            getattr(assessment, "state", None), "assessment.state"
        )
        raw_counts = getattr(assessment, "counts", None)
        if raw_counts is None:
            raise ReasoningError("an assessment must carry counts")
        counts = PacketCounts(
            bullish=getattr(raw_counts, "bullish", None),
            bearish=getattr(raw_counts, "bearish", None),
            neutral=getattr(raw_counts, "neutral", None),
            insufficient=getattr(raw_counts, "insufficient", None),
        )
        assessment_reason_codes = _reason_codes(
            getattr(assessment, "reason_codes", ()), "assessment.reason_codes"
        )

    # -- the hypotheses --------------------------------------------------
    raw_observations = tuple(getattr(snapshot, "observations", ()) or ())
    if len(raw_observations) > MAX_PACKET_OBSERVATIONS:
        raise ReasoningError(
            f"the snapshot carries {len(raw_observations)} observations, over the "
            f"{MAX_PACKET_OBSERVATIONS} a packet may hold. Every hypothesis "
            "contributed to the assessment, so a truncated packet would carry an "
            "assessment its own evidence cannot account for; refusing instead"
        )

    observations: list[PacketObservation] = []
    for raw in raw_observations:
        hypothesis_id = require_text(
            getattr(raw, "hypothesis_id", None), "observation.hypothesis_id",
            maximum=128,
        )
        version = require_count(getattr(raw, "version", None), "observation.version")
        fingerprint = require_text(
            getattr(raw, "fingerprint", None), "observation.fingerprint", maximum=128
        )
        codes = _reason_codes(
            getattr(raw, "reason_codes", ()), "observation.reason_codes"
        )
        evidence = _observation_evidence(
            getattr(raw, "evidence", {}), "observation.evidence"
        )

        observations.append(
            PacketObservation(
                hypothesis_id=hypothesis_id,
                version=version,
                hypothesis_fingerprint=fingerprint,
                state=_enum_value(getattr(raw, "state", None), "observation.state"),
                reason_codes=codes,
                timestamp=require_aware(
                    getattr(raw, "timestamp", None), "observation.timestamp"
                ),
                evidence=evidence,
            )
        )
    return EvidencePacket(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        symbol=symbol,
        interval=interval,
        basis=basis,
        data_cutoff=data_cutoff,
        policy_fingerprint=policy_fingerprint,
        warmup_bars=getattr(snapshot, "warmup_bars", 0),
        minimum_sufficient_observations=minimum_sufficient_observations,
        assessment_state=assessment_state,
        counts=counts,
        assessment_reason_codes=assessment_reason_codes,
        observations=tuple(observations),
        generated_at=generated_at,
        omitted_counts={},
    )


# -- fingerprints --------------------------------------------------------


def _digest(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def evidence_fingerprint(packet: EvidencePacket) -> str:
    """Identity of *what the model is allowed to know*.

    Excludes ``generated_at``: rebuilding an identical packet a second later
    must produce the same digest, or staleness would fire on every rerun and
    mean nothing. Excludes provider and model entirely -- those describe how a
    question was asked, not what was known, and letting them in would make a
    model change look like new evidence.
    """
    if not isinstance(packet, EvidencePacket):
        raise ReasoningError("evidence_fingerprint needs an EvidencePacket")
    return _digest(packet.canonical())


def reasoning_fingerprint(
    *,
    evidence_fingerprint: str,
    reasoning_kind: ReasoningKind | str,
    prompt_id: str,
    prompt_version: int,
    prompt_fingerprint: str,
    output_schema_version: int,
    provider: str,
    model: str,
) -> str:
    """Identity of *how the evidence was reasoned about*.

    Built over the evidence digest plus prompt, schema, provider and model, so
    two explanations of the same evidence by different models are comparable and
    distinguishable. Carries no timestamp: the same question asked the same way
    of the same evidence has one identity, whenever it was asked.
    """
    return _digest(
        {
            "evidence_fingerprint": require_text(
                evidence_fingerprint, "evidence_fingerprint", maximum=128
            ),
            "reasoning_kind": ReasoningKind(reasoning_kind).value,
            "prompt_id": require_text(prompt_id, "prompt_id", maximum=64),
            "prompt_version": int(prompt_version),
            "prompt_fingerprint": require_text(
                prompt_fingerprint, "prompt_fingerprint", maximum=128
            ),
            "output_schema_version": int(output_schema_version),
            "provider": require_text(provider, "provider", maximum=64),
            "model": require_text(model, "model", maximum=128),
        }
    )


def research_context_fingerprint(snapshot: Any) -> str:
    """Identity of the research a packet would be built from.

    Computed straight from an already-materialised snapshot so a staleness check
    costs no I/O, no packet rebuild and no provider call -- the dashboard runs
    this on a rerun and compares one string.

    It covers every fact that could change an explanation and nothing else.
    ``series`` and ``features`` are excluded because the packet does not carry
    them; ``source``, ``decision_index`` and ``history_label`` are excluded
    because they describe how the snapshot was fetched and windowed, not what
    the research found -- refetching the same bars from the same provider must
    not invalidate an explanation that is still accurate.
    """
    assessment = getattr(snapshot, "assessment", None)
    if assessment is None:
        assessment_payload: Any = None
    else:
        counts = getattr(assessment, "counts", None)
        assessment_payload = {
            "state": _enum_value(getattr(assessment, "state", None), "assessment.state"),
            "counts": {
                "bullish": getattr(counts, "bullish", None),
                "bearish": getattr(counts, "bearish", None),
                "neutral": getattr(counts, "neutral", None),
                "insufficient": getattr(counts, "insufficient", None),
            },
            "reason_codes": [
                _enum_value(code, "assessment.reason_codes entry")
                for code in getattr(assessment, "reason_codes", ())
            ],
            "timestamp": require_aware(
                getattr(assessment, "timestamp", None), "assessment.timestamp"
            ).isoformat(),
            "assessment_as_of": require_aware(
                getattr(assessment, "assessment_as_of", None),
                "assessment.assessment_as_of",
            ).isoformat(),
        }

    payload = {
        "symbol": require_text(getattr(snapshot, "symbol", None), "snapshot.symbol",
                               maximum=32),
        "interval": _enum_value(getattr(snapshot, "interval", None),
                                "snapshot.interval"),
        "basis": _enum_value(getattr(snapshot, "basis", None), "snapshot.basis"),
        "built_at": require_aware(
            getattr(snapshot, "built_at", None), "snapshot.built_at"
        ).isoformat(),
        "policy_fingerprint": require_text(
            getattr(snapshot, "policy_fingerprint", None), "snapshot.policy_fingerprint",
            maximum=128,
        ),
        "warmup_bars": getattr(snapshot, "warmup_bars", 0),
        "assessment": assessment_payload,
        "observations": [
            {
                "hypothesis_id": require_text(
                    getattr(observation, "hypothesis_id", None),
                    "observation.hypothesis_id", maximum=128,
                ),
                "version": getattr(observation, "version", None),
                "fingerprint": require_text(
                    getattr(observation, "fingerprint", None),
                    "observation.fingerprint", maximum=128,
                ),
                "state": _enum_value(
                    getattr(observation, "state", None), "observation.state"
                ),
                "reason_codes": [
                    _enum_value(code, "observation.reason_codes entry")
                    for code in getattr(observation, "reason_codes", ())
                ],
                "timestamp": require_aware(
                    getattr(observation, "timestamp", None), "observation.timestamp"
                ).isoformat(),
                "evidence": dict(
                    sorted(
                        (
                            require_text(name, "evidence name", maximum=200),
                            require_finite(value, f"evidence value for {name!r}"),
                        )
                        for name, value in getattr(observation, "evidence", {}).items()
                    )
                ),
            }
            for observation in getattr(snapshot, "observations", ()) or ()
        ],
    }
    return _digest(payload)


__all__ = [
    "build_packet",
    "evidence_fingerprint",
    "reasoning_fingerprint",
    "research_context_fingerprint",
]
