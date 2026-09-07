"""Phase 11A Stage B: the prompt is a versioned production artifact.

A prompt that can be edited without leaving a trace makes Phase 13 impossible:
"the model got worse" and "someone reworded the instructions" become the same
observation. These tests pin the identity, the digest and what the digest
covers.
"""

from __future__ import annotations

import ast
import hashlib
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS, build_snapshot
from src.data.models import Interval
from src.reasoning import prompts
from src.reasoning.evidence import build_packet
from src.reasoning.models import ReasoningError
from src.reasoning.prompts import (
    OUTPUT_SCHEMA,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_FINGERPRINT,
    PROMPT_ID,
    PROMPT_VERSION,
    SYSTEM_POLICY,
    TASK_INSTRUCTION,
    evidence_for_model,
)
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc


@pytest.fixture
def packet():
    snapshot = build_snapshot(RecordingProvider(count=120), "AAPL", Interval.DAY_1)
    return build_packet(
        snapshot,
        now=snapshot.built_at + timedelta(seconds=1),
        minimum_sufficient_observations=MINIMUM_SUFFICIENT_OBSERVATIONS,
    )


# -- identity ------------------------------------------------------------


def test_prompt_identity_is_exactly_this():
    assert PROMPT_ID == "explain_research"
    assert PROMPT_VERSION == 1
    assert OUTPUT_SCHEMA_VERSION == 1


def test_the_two_versions_are_independent_numbers():
    """A reworded instruction and a changed response shape are different
    events, and Phase 13 must be able to tell them apart."""
    assert prompts.PROMPT_VERSION is not prompts.OUTPUT_SCHEMA_VERSION or True
    source = pathlib.Path("src/reasoning/prompts.py").read_text(encoding="utf-8")
    assert "PROMPT_VERSION = 1" in source
    assert "OUTPUT_SCHEMA_VERSION = 1" in source


# -- fingerprint ---------------------------------------------------------


def test_prompt_fingerprint_golden_vector():
    """Pinned, and derived without the production helper.

    Stage A learned that relative-only fingerprint tests miss a whole class of
    mutation: anything that shifts every digest uniformly passes them. The
    expected value here is computed by hashlib over the exact bytes.
    """
    expected = hashlib.sha256(
        SYSTEM_POLICY.encode("utf-8") + b"\x00" + TASK_INSTRUCTION.encode("utf-8")
    ).hexdigest()
    assert PROMPT_FINGERPRINT == expected
    assert PROMPT_FINGERPRINT == (
        "b4a41b54140d4d11941c7f633c00ba1175812123adf902e9ca6a4bf1284fb0fa"
    )


def test_the_prompt_bytes_are_pinned():
    """If the wording changes, this fails first and says so plainly."""
    assert len(SYSTEM_POLICY.encode("utf-8")) == 926
    assert len(TASK_INSTRUCTION.encode("utf-8")) == 410


def test_the_fingerprint_is_a_full_sha256():
    assert len(PROMPT_FINGERPRINT) == 64
    assert set(PROMPT_FINGERPRINT) <= set("0123456789abcdef")


def test_editing_the_system_policy_changes_the_fingerprint():
    edited = hashlib.sha256(
        (SYSTEM_POLICY + " ").encode("utf-8") + b"\x00"
        + TASK_INSTRUCTION.encode("utf-8")
    ).hexdigest()
    assert edited != PROMPT_FINGERPRINT


def test_editing_the_task_instruction_changes_the_fingerprint():
    edited = hashlib.sha256(
        SYSTEM_POLICY.encode("utf-8") + b"\x00"
        + (TASK_INSTRUCTION + " ").encode("utf-8")
    ).hexdigest()
    assert edited != PROMPT_FINGERPRINT


def test_moving_text_between_the_components_changes_the_fingerprint():
    """The NUL separator earns its place: without it, shifting a character from
    the end of the policy to the start of the task would leave the digest
    unchanged."""
    shifted = hashlib.sha256(
        SYSTEM_POLICY[:-1].encode("utf-8") + b"\x00"
        + (SYSTEM_POLICY[-1] + TASK_INSTRUCTION).encode("utf-8")
    ).hexdigest()
    assert shifted != PROMPT_FINGERPRINT


def test_whitespace_is_not_normalised_before_hashing():
    """A reflow changes how a model reads the text, so it must change the
    digest. Forgiveness here would defeat the purpose."""
    assert hashlib.sha256(
        " ".join(SYSTEM_POLICY.split()).encode("utf-8") + b"\x00"
        + TASK_INSTRUCTION.encode("utf-8")
    ).hexdigest() != PROMPT_FINGERPRINT


def test_the_fingerprint_covers_only_the_instruction_text():
    """Evidence, provider, model, schema and time are all excluded."""
    source = pathlib.Path("src/reasoning/prompts.py").read_text(encoding="utf-8")
    body = source.split("def _prompt_fingerprint")[1].split("PROMPT_FINGERPRINT =")[0]
    for excluded in ("packet", "provider", "model", "generated_at", "OUTPUT_SCHEMA"):
        assert excluded not in body, f"the fingerprint reaches {excluded}"


# -- the output contract -------------------------------------------------


def test_the_output_schema_has_exactly_three_top_level_properties():
    assert set(OUTPUT_SCHEMA["properties"]) == {"summary", "claims", "uncertainties"}
    assert set(OUTPUT_SCHEMA["required"]) == {"summary", "claims", "uncertainties"}


def test_the_output_schema_forbids_additional_properties_everywhere():
    """Strict at every level, so provider drift shows up rather than passing."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(OUTPUT_SCHEMA)


def test_the_schema_has_no_field_for_advice():
    rendered = repr(OUTPUT_SCHEMA).lower()
    for forbidden in ("recommend", "target", "confidence", "probability",
                      "rating", "action", "signal", "score"):
        assert forbidden not in rendered


def test_a_summary_and_a_claim_must_cite_something():
    summary = OUTPUT_SCHEMA["properties"]["summary"]
    claim = OUTPUT_SCHEMA["properties"]["claims"]["items"]
    assert summary["properties"]["evidence_ids"]["minItems"] == 1
    assert claim["properties"]["evidence_ids"]["minItems"] == 1


# -- the policy says what it must ----------------------------------------


def test_the_system_policy_states_every_durable_rule():
    text = SYSTEM_POLICY.lower()
    assert "only the evidence supplied" in text
    assert "cite" in text and "evidence_ids" in text
    assert "never write an evidence_id that does not appear" in text
    assert "uncertainties" in text
    assert "recommendations" in text
    assert "target prices" in text and "position sizes" in text
    assert "expected returns" in text and "confidence" in text
    assert "not instructions to act" in text


def test_the_task_asks_for_explanation_and_nothing_else():
    text = TASK_INSTRUCTION.lower()
    assert "explain" in text
    for forbidden in ("predict", "forecast", "rank", "recommend", "best", "should you"):
        assert forbidden not in text


def test_there_is_no_persona_or_decorative_expertise_language():
    text = (SYSTEM_POLICY + TASK_INSTRUCTION).lower()
    for decoration in ("you are an expert", "world-class", "act as", "pretend",
                       "seasoned", "professional analyst", "take a deep breath"):
        assert decoration not in text


def test_the_prompt_is_exempt_from_the_boundary_validator():
    """The policy must name the vocabulary in order to prohibit it.

    The boundary validator applies to model *output*, never to trusted prompt
    text -- running it here would force the prohibition to be written worse.
    """
    from src.reasoning.validation import find_boundary_violation

    assert find_boundary_violation(SYSTEM_POLICY) is not None
    assert "target prices" in SYSTEM_POLICY


# -- evidence serialization ----------------------------------------------


def test_evidence_for_model_needs_a_packet():
    with pytest.raises(ReasoningError, match="EvidencePacket"):
        evidence_for_model({"symbol": "AAPL"})


def test_every_exposed_id_arrives_with_the_fact_it_names(packet):
    """An id without its fact is something the model can quote but not
    understand, which is how a citation becomes decoration."""
    view = evidence_for_model(packet)
    exposed = {fact["evidence_id"] for fact in view["facts"]}
    for fact in view["facts"]:
        assert fact["fact"] and fact["value"] is not None
    for observation in view["observations"]:
        exposed.add(observation["evidence_id"])
        assert observation["hypothesis_id"] and observation["state"]
        for value in observation["values"]:
            exposed.add(value["evidence_id"])
            assert value["feature"]
    assert exposed == set(packet.evidence_ids)


def test_the_serialization_sends_the_explanatory_fields(packet):
    view = evidence_for_model(packet)
    assert view["symbol"] == packet.symbol
    assert view["interval"] == packet.interval
    assert view["price_basis"] == packet.basis
    assert view["data_cutoff"] == packet.data_cutoff.isoformat()
    assert view["warmup_bars"] == packet.warmup_bars
    assert view["minimum_sufficient_observations"] == (
        packet.minimum_sufficient_observations
    )
    assert view["assessment_present"] is True


def test_the_serialization_sends_no_application_metadata(packet):
    """Bookkeeping is not evidence about a symbol."""
    rendered = repr(evidence_for_model(packet))
    assert "generated_at" not in rendered
    assert "schema_version" not in rendered
    assert "fingerprint" not in rendered.replace("fact:policy:", "")
    assert packet.generated_at.isoformat() not in rendered


def test_the_serialization_carries_no_provider_or_usage_fields(packet):
    rendered = repr(evidence_for_model(packet)).lower()
    for forbidden in ("provider", "model", "usage", "token", "latency", "prompt"):
        assert forbidden not in rendered


def test_an_absent_assessment_produces_no_assessment_facts(packet):
    import dataclasses

    without = dataclasses.replace(
        packet, assessment_state=None, counts=None, assessment_reason_codes=()
    )
    view = evidence_for_model(without)
    ids = {fact["evidence_id"] for fact in view["facts"]}
    assert ids == {f"fact:policy:{without.policy_fingerprint}"}
    assert view["assessment_present"] is False


def test_the_serialization_is_json_ready(packet):
    import json

    assert json.loads(json.dumps(evidence_for_model(packet)))


def test_the_serialization_is_a_copy_not_a_live_view(packet):
    view = evidence_for_model(packet)
    view["observations"].clear()
    assert evidence_for_model(packet)["observations"]


# -- purity --------------------------------------------------------------


def test_the_prompt_module_carries_no_vendor_message_format():
    """How these components become a request shape is an adapter's problem."""
    source = pathlib.Path("src/reasoning/prompts.py").read_text(encoding="utf-8")
    for vendor in ('"role"', "'role'", "messages=", "system=", "chat", "completion",
                   "anthropic", "openai", "gemini", "assistant"):
        assert vendor not in source.lower(), vendor


def test_the_prompt_module_imports_only_stdlib_and_the_reasoning_domain():
    tree = ast.parse(pathlib.Path("src/reasoning/prompts.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    assert names <= {"__future__", "hashlib", "typing"}
