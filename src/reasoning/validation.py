"""Turning an untrusted provider payload into trusted application state.

    ProviderReasoningResponse   (untrusted)
            |  schema -> boundary language -> grounding -> consistency
            v
    ReasoningSnapshot           (trusted)

:func:`validate_provider_response` is the only production path across that line,
and it is the only production module that constructs a
:class:`~src.reasoning.models.ReasoningSnapshot`. Python cannot make a
constructor private, so that rule is enforced by a boundary test rather than by
the language; the test is the mechanism, and pretending otherwise would be worse
than saying so.

Order matters. Schema first, because the later checks need typed fields.
Boundary language second: it is the most serious failure class and the cheapest
to run, and there is no reason to spend grounding work on text that is going to
be rejected. Construction strictly last, so a snapshot cannot exist until every
check has passed.

What this module refuses to do is as important as what it does. It does not
attempt to decide whether prose contradicts an assessment, whether wording
overstates evidence, or what a sentence means. A regex that claimed to would be
a confident lie in the one place this project cannot afford one. It checks what
is structurally checkable -- shapes, citations, vocabulary -- and leaves
judgement to the human reading the result.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Mapping, Sequence

from .models import (
    MAX_CLAIMS,
    MAX_EVIDENCE_ID_CHARS,
    MAX_EVIDENCE_IDS_PER_CLAIM,
    MAX_NOTES,
    MAX_REASONING_TEXT_CHARS,
    MAX_VALIDATION_DETAIL_CHARS,
    EvidencePacket,
    ProviderReasoningResponse,
    ReasoningClaim,
    ReasoningError,
    ReasoningFailureCode,
    ReasoningRequest,
    ReasoningSnapshot,
    ReasoningSummary,
    ReasoningUsageMetadata,
    require_aware,
)
from .evidence import evidence_fingerprint, reasoning_fingerprint


class ReasoningValidationError(ReasoningError):
    """A provider response that cannot be trusted, and why.

    ``detail`` names a field and a category of problem. It never carries the
    offending text: echoing a rejected payload into a log or an interface hands
    it the reader it was rejected to protect.
    """

    def __init__(self, code: ReasoningFailureCode, detail: str) -> None:
        self.code = ReasoningFailureCode(code)
        self.detail = detail.strip()[:MAX_VALIDATION_DETAIL_CHARS]
        super().__init__(f"{self.code.value}: {self.detail}")


def _fail(code: ReasoningFailureCode, detail: str) -> "ReasoningValidationError":
    return ReasoningValidationError(code, detail)


# -- 1. schema -----------------------------------------------------------

_TOP_LEVEL_KEYS = frozenset({"summary", "claims", "uncertainties"})
_TEXT_ITEM_KEYS = frozenset({"text", "evidence_ids"})


def _require_mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} must be an object")
    for key in value:
        if not isinstance(key, str):
            raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                        f"{where} has a non-string key")
    return value


def _require_exact_keys(value: Mapping[str, Any], allowed: frozenset, where: str) -> None:
    keys = set(value)
    missing = allowed - keys
    if missing:
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} is missing {sorted(missing)}")
    unknown = keys - allowed
    if unknown:
        # Rejected, never dropped. A model or adapter that starts emitting a
        # "confidence" field must fail loudly; silently discarding it would let
        # provider drift run for months unnoticed.
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} has unexpected keys {sorted(unknown)}")


def _require_str(value: object, where: str, *, maximum: int) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} must be a string")
    text = value.strip()
    if not text:
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} must not be empty")
    if len(text) > maximum:
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} exceeds {maximum} characters")
    return text


def _require_list(value: object, where: str, *, maximum: int) -> list[Any]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} must be a list")
    if len(value) > maximum:
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} holds more than {maximum} entries")
    return list(value)


def _require_evidence_ids(value: object, where: str) -> tuple[str, ...]:
    raw = _require_list(value, where, maximum=MAX_EVIDENCE_IDS_PER_CLAIM)
    if not raw:
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} must cite at least one evidence id")
    ids = []
    for item in raw:
        text = _require_str(item, f"{where} entry", maximum=MAX_EVIDENCE_ID_CHARS)
        # An id is an identifier, not prose. ``_require_str`` trims surrounding
        # whitespace, which is right for a sentence and wrong here: grounding is
        # exact membership, so a padded id must be refused rather than quietly
        # repaired into a match. Repairing provider output is what this layer
        # refuses to do everywhere else.
        if text != item:
            raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                        f"{where} entry is padded with whitespace; an evidence id "
                        "must be cited exactly")
        ids.append(text)
    ids = tuple(ids)
    if len(set(ids)) != len(ids):
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    f"{where} cites the same evidence twice")
    return ids


def parse_payload(payload: object) -> dict[str, Any]:
    """The payload as typed pieces, or a schema failure. Strict throughout."""
    body = _require_mapping(payload, "response")
    _require_exact_keys(body, _TOP_LEVEL_KEYS, "response")

    summary = _require_mapping(body["summary"], "summary")
    _require_exact_keys(summary, _TEXT_ITEM_KEYS, "summary")
    parsed_summary = {
        "text": _require_str(summary["text"], "summary.text",
                             maximum=MAX_REASONING_TEXT_CHARS),
        "evidence_ids": _require_evidence_ids(summary["evidence_ids"],
                                              "summary.evidence_ids"),
    }

    claims: list[dict[str, Any]] = []
    for index, raw in enumerate(_require_list(body["claims"], "claims",
                                              maximum=MAX_CLAIMS)):
        where = f"claims[{index}]"
        claim = _require_mapping(raw, where)
        _require_exact_keys(claim, _TEXT_ITEM_KEYS, where)
        claims.append({
            "text": _require_str(claim["text"], f"{where}.text",
                                 maximum=MAX_REASONING_TEXT_CHARS),
            "evidence_ids": _require_evidence_ids(claim["evidence_ids"],
                                                  f"{where}.evidence_ids"),
        })

    uncertainties = tuple(
        _require_str(item, f"uncertainties[{index}]",
                     maximum=MAX_REASONING_TEXT_CHARS)
        for index, item in enumerate(
            _require_list(body["uncertainties"], "uncertainties", maximum=MAX_NOTES)
        )
    )

    return {"summary": parsed_summary, "claims": claims,
            "uncertainties": uncertainties}


# -- 2. boundary language ------------------------------------------------

#: Stems, matched on word boundaries so ``holding`` and ``household`` pass while
#: ``buying`` and ``seller`` do not.
_FORBIDDEN_WORDS = (
    r"buy|buys|buying|buyer|buyers|bought",
    r"sell|sells|selling|seller|sellers|sold",
    r"hold|holds",
    r"overweight|underweight",
    r"allocate|allocates|allocating|allocation",
    r"guarantee|guarantees|guaranteed",
)

#: Multi-word concepts. ``position`` and ``return`` are deliberately not banned
#: alone -- both occur innocently in ordinary prose about evidence.
_FORBIDDEN_PHRASES = (
    "strong buy", "strong sell", "target price", "price target",
    "position size", "position sizing", "expected return", "stop loss",
    "take profit", "entry point", "exit point", "risk reward",
)

_WORD_PATTERN = re.compile(r"\b(?:" + "|".join(_FORBIDDEN_WORDS) + r")\b")

#: Separators an evasion might insert between letters: ``b.u.y``, ``b(u)y``.
#: Every character here is punctuation that never appears inside an English
#: word, so removing it cannot join two legitimate words into a third.
_SEPARATOR_RUN = re.compile(r"(?<=\w)[.\-_*/\\|+~:;,'\"`()\[\]{}<>!?@#$%^&=]+(?=\w)")

#: Three or more single characters separated by spaces -- ``b u y``. Bounded to
#: runs of single characters so ordinary prose, where words are longer than one
#: letter, is untouched.
_SPACED_LETTERS = re.compile(r"\b(?:\w[ \t]+){2,}\w\b")


def normalize_for_boundary(text: str) -> str:
    """Fold the text into the form the vocabulary patterns are written against.

    NFKC collapses compatibility and full-width forms, format characters carry
    zero-width evasions, and casefold removes the case game. Separator runs
    between word characters are dropped so a spelled-out evasion is seen as the
    word it is.

    **This is a backstop, not moderation.** NFKC does not solve arbitrary
    cross-script homoglyphs, and no word list can catch a recommendation phrased
    in words it does not contain. The defences that do not depend on wording --
    a schema with nowhere to put advice, a deterministic disclaimer outside
    model output, and no path from reasoning to a paper action -- are the real
    ones.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(
        character for character in folded
        if unicodedata.category(character) not in {"Cf", "Cc"}
    )
    folded = folded.casefold()
    folded = _SEPARATOR_RUN.sub("", folded)
    folded = _SPACED_LETTERS.sub(lambda match: match.group(0).replace(" ", "")
                                 .replace("\t", ""), folded)
    return " ".join(folded.split())


def find_boundary_violation(text: str) -> str | None:
    """The forbidden term this text contains, or ``None``."""
    normalized = normalize_for_boundary(text)
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in normalized:
            return phrase
    match = _WORD_PATTERN.search(normalized)
    return match.group(0) if match else None


def validate_boundary_language(parsed: Mapping[str, Any]) -> None:
    """Every model-authored string, including negations.

    A model may not write "this is not a buy recommendation": the disclaimer is
    rendered deterministically outside model output, so there is no reason for
    the vocabulary to appear at all, and a total prohibition is far simpler to
    enforce than a negation-aware rule.
    """
    checks: list[tuple[str, str]] = [("summary.text", parsed["summary"]["text"])]
    checks += [(f"claims[{i}].text", claim["text"])
               for i, claim in enumerate(parsed["claims"])]
    checks += [(f"uncertainties[{i}]", note)
               for i, note in enumerate(parsed["uncertainties"])]
    for where, text in checks:
        found = find_boundary_violation(text)
        if found is not None:
            raise _fail(ReasoningFailureCode.BOUNDARY_VIOLATION,
                        f"{where} uses prohibited trading vocabulary ({found!r})")


# -- 3. grounding --------------------------------------------------------


def validate_grounding(parsed: Mapping[str, Any], packet: EvidencePacket) -> None:
    """Every citation must name evidence this packet actually contains.

    No partial acceptance: one unknown id fails the whole response. A result
    that is right about four things and invented the fifth is not four-fifths
    trustworthy -- it is a result whose author was willing to invent.
    """
    universe = packet.evidence_ids
    cited: list[tuple[str, tuple[str, ...]]] = [
        ("summary.evidence_ids", parsed["summary"]["evidence_ids"])
    ]
    cited += [(f"claims[{i}].evidence_ids", claim["evidence_ids"])
              for i, claim in enumerate(parsed["claims"])]
    for where, ids in cited:
        for evidence_id in ids:
            if evidence_id not in universe:
                raise _fail(
                    ReasoningFailureCode.GROUNDING_FAILED,
                    f"{where} cites an evidence id that is not in this packet",
                )


# -- 4. structural consistency -------------------------------------------


def validate_consistency(parsed: Mapping[str, Any]) -> None:
    """The structural checks that can be made honestly.

    Exact duplicate claims are rejected -- same text *and* the same set of
    citations says nothing twice. Order is not part of that comparison: citing
    the same two facts in the other order is the same claim.

    Deliberately absent: any attempt to decide whether prose contradicts the
    assessment, or whether wording overstates the evidence. Those need a reader,
    and a regex pretending to do them would be a confident lie.
    """
    seen: set[tuple[str, frozenset[str]]] = set()
    for index, claim in enumerate(parsed["claims"]):
        identity = (claim["text"], frozenset(claim["evidence_ids"]))
        if identity in seen:
            raise _fail(ReasoningFailureCode.GROUNDING_FAILED,
                        f"claims[{index}] repeats an earlier claim verbatim")
        seen.add(identity)


# -- 5. the trusted conversion -------------------------------------------


def _validated_usage(usage: object) -> ReasoningUsageMetadata:
    if not isinstance(usage, ReasoningUsageMetadata):
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    "usage must be a ReasoningUsageMetadata")
    if usage.attempt_count < 1:
        # A response that arrived took at least one attempt. Zero would mean the
        # adapter is reporting something it did not do.
        raise _fail(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
                    "usage.attempt_count must be at least 1 for a response")
    return usage


def validate_provider_response(
    request: ReasoningRequest,
    response: ProviderReasoningResponse,
    *,
    generated_at: datetime,
) -> ReasoningSnapshot:
    """The one production path from untrusted payload to trusted snapshot.

    Provenance comes from the request, never from the payload -- and cannot come
    from the payload, because the strict schema has no key for it. The model
    supplies three things and only three: a summary, some claims, and whatever
    it could not establish.

    ``generated_at`` is injected rather than read from a clock or taken from the
    provider, and must not precede the cutoff of the evidence it describes.

    The raw payload is not retained. Nothing that failed validation, and nothing
    that was never validated, survives this call.
    """
    if not isinstance(request, ReasoningRequest):
        raise _fail(ReasoningFailureCode.REQUEST_INVALID,
                    "request must be a ReasoningRequest")
    if not isinstance(response, ProviderReasoningResponse):
        raise _fail(ReasoningFailureCode.REQUEST_INVALID,
                    "response must be a ProviderReasoningResponse")

    stamp = require_aware(generated_at, "generated_at")
    packet = request.packet
    if stamp < packet.data_cutoff:
        raise _fail(
            ReasoningFailureCode.REQUEST_INVALID,
            "generated_at precedes the data cutoff of the evidence it explains",
        )

    usage = _validated_usage(response.usage)

    parsed = parse_payload(response.payload)
    validate_boundary_language(parsed)
    validate_grounding(parsed, packet)
    validate_consistency(parsed)

    evidence_digest = evidence_fingerprint(packet)
    return ReasoningSnapshot(
        reasoning_kind=request.reasoning_kind,
        symbol=packet.symbol,
        data_cutoff=packet.data_cutoff,
        evidence_fingerprint=evidence_digest,
        reasoning_fingerprint=reasoning_fingerprint(
            evidence_fingerprint=evidence_digest,
            reasoning_kind=request.reasoning_kind,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            prompt_fingerprint=request.prompt_fingerprint,
            output_schema_version=request.output_schema_version,
            # From the request, not from what the provider reported it served:
            # a reported model is an observation, while the fingerprint records
            # what was asked for.
            provider=request.provider,
            model=request.model,
        ),
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        output_schema_version=request.output_schema_version,
        summary=ReasoningSummary(
            text=parsed["summary"]["text"],
            evidence_ids=parsed["summary"]["evidence_ids"],
        ),
        claims=tuple(
            ReasoningClaim(text=claim["text"], evidence_ids=claim["evidence_ids"])
            for claim in parsed["claims"]
        ),
        uncertainties=parsed["uncertainties"],
        usage=usage,
        generated_at=stamp,
    )


__all__ = [
    "ReasoningValidationError",
    "find_boundary_violation",
    "normalize_for_boundary",
    "parse_payload",
    "validate_boundary_language",
    "validate_consistency",
    "validate_grounding",
    "validate_provider_response",
]
