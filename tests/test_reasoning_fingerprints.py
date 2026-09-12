"""Phase 11A Stage A: two digests, two questions, no leakage between them.

The evidence fingerprint answers *was this built from what is on screen now?*
The reasoning fingerprint answers *was it built the same way?* Every test here
exists to kill one specific way those two could quietly become one.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from src.application.snapshot import MINIMUM_SUFFICIENT_OBSERVATIONS, build_snapshot
from src.data.models import Interval
from src.reasoning.evidence import (
    build_packet,
    evidence_fingerprint,
    reasoning_fingerprint,
    research_context_fingerprint,
)
from src.reasoning.models import PacketCounts, ReasoningError, ReasoningKind
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)

PROMPT = {
    "prompt_id": "explain_research",
    "prompt_version": 1,
    "prompt_fingerprint": "c0ffee00c0ffee00",
    "output_schema_version": 1,
    "provider": "fake",
    "model": "fake-1",
}


@pytest.fixture
def snapshot():
    return build_snapshot(RecordingProvider(count=120), "AAPL", Interval.DAY_1)


def build(snapshot, **overrides):
    """A packet built the way the application will build one.

    ``now`` defaults to just after the snapshot was observed, because that is
    the only order that can happen in practice: a packet is assembled from a
    snapshot that already exists.
    """
    fields = {"now": snapshot.built_at + timedelta(seconds=1),
              "minimum_sufficient_observations": MINIMUM_SUFFICIENT_OBSERVATIONS}
    fields.update(overrides)
    return build_packet(snapshot, **fields)


def reasoning_of(packet, **overrides):
    fields = dict(PROMPT)
    fields.update(overrides)
    return reasoning_fingerprint(
        evidence_fingerprint=evidence_fingerprint(packet),
        reasoning_kind=ReasoningKind.EXPLAIN_RESEARCH,
        **fields,
    )


# -- shape ---------------------------------------------------------------


def test_a_fingerprint_is_a_full_sha256_hex_digest(snapshot):
    digest = evidence_fingerprint(build(snapshot))
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_the_evidence_fingerprint_needs_a_packet():
    with pytest.raises(ReasoningError, match="EvidencePacket"):
        evidence_fingerprint({"symbol": "AAPL"})


# -- generated_at must not leak into evidence identity -------------------


def test_generated_at_does_not_change_the_evidence_fingerprint(snapshot):
    """The mutation this kills: a packet rebuilt a second later looking new,
    which would fire staleness on every rerun and so mean nothing."""
    early = build(snapshot, now=snapshot.built_at)
    late = build(snapshot, now=snapshot.built_at + timedelta(days=365))
    assert early.generated_at != late.generated_at
    assert evidence_fingerprint(early) == evidence_fingerprint(late)


def test_generated_at_is_absent_from_the_canonical_payload(snapshot):
    assert "generated_at" not in build(snapshot).canonical()
    assert "generated_at" in build(snapshot).canonical(include_generated_at=True)


# -- every meaningful field must change the evidence fingerprint ---------


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("symbol", "MSFT"),
        ("interval", "1wk"),
        ("basis", "split_and_dividend_adjusted"),
        ("policy_fingerprint", "0000000000000000"),
        ("warmup_bars", 52),
        ("minimum_sufficient_observations", 3),
        ("assessment_state", "bearish"),
        ("assessment_reason_codes", ("unanimous_bearish",)),
    ],
)
def test_changing_a_meaningful_field_changes_the_evidence_fingerprint(
    snapshot, field_name, value
):
    packet = build(snapshot)
    mutated = dataclasses.replace(packet, **{field_name: value})
    assert evidence_fingerprint(mutated) != evidence_fingerprint(packet)


def test_changing_the_cutoff_changes_the_evidence_fingerprint(snapshot):
    packet = build(snapshot, now=snapshot.built_at + timedelta(days=2))
    mutated = dataclasses.replace(packet, data_cutoff=packet.data_cutoff + timedelta(1))
    assert evidence_fingerprint(mutated) != evidence_fingerprint(packet)


def test_changing_counts_changes_the_evidence_fingerprint(snapshot):
    packet = build(snapshot)
    mutated = dataclasses.replace(
        packet, counts=PacketCounts(bullish=0, bearish=2, neutral=1, insufficient=0)
    )
    assert evidence_fingerprint(mutated) != evidence_fingerprint(packet)


def test_dropping_an_observation_changes_the_evidence_fingerprint(snapshot):
    packet = build(snapshot)
    fewer = dataclasses.replace(packet, observations=packet.observations[:-1])
    assert evidence_fingerprint(fewer) != evidence_fingerprint(packet)


def test_changing_one_evidence_value_changes_the_evidence_fingerprint(snapshot):
    packet = build(snapshot)
    first = packet.observations[0]
    name = next(iter(first.evidence))
    altered = dataclasses.replace(
        first, evidence={**dict(first.evidence), name: 1.0}
    )
    mutated = dataclasses.replace(
        packet, observations=(altered,) + packet.observations[1:]
    )
    assert evidence_fingerprint(mutated) != evidence_fingerprint(packet)


def test_omitted_counts_change_the_evidence_fingerprint(snapshot):
    """A truncated packet is not the same evidence as a complete one."""
    packet = build(snapshot)
    mutated = dataclasses.replace(packet, omitted_counts={"observations": 1})
    assert evidence_fingerprint(mutated) != evidence_fingerprint(packet)


# -- ordering and mapping order ------------------------------------------


def test_observation_order_is_part_of_the_evidence_fingerprint(snapshot):
    """Order is content here: it is the order the pipeline reported, and a
    packet that reordered it would not be the same record."""
    packet = build(snapshot)
    reordered = dataclasses.replace(
        packet, observations=tuple(reversed(packet.observations))
    )
    assert evidence_fingerprint(reordered) != evidence_fingerprint(packet)


def test_mapping_insertion_order_does_not_change_the_evidence_fingerprint(snapshot):
    forward = snapshot.observations[0]
    shuffled = dataclasses.replace(
        forward, evidence=dict(reversed(list(forward.evidence.items())))
    )
    a = build(dataclasses.replace(snapshot, observations=(forward,)))
    b = build(dataclasses.replace(snapshot, observations=(shuffled,)))
    assert evidence_fingerprint(a) == evidence_fingerprint(b)


def test_timezone_representation_does_not_change_the_evidence_fingerprint(snapshot):
    """The same instant written in another offset is the same instant."""
    packet = build(snapshot)
    other = timezone(timedelta(hours=5, minutes=30))
    shifted = dataclasses.replace(
        packet, data_cutoff=packet.data_cutoff.astimezone(other)
    )
    assert evidence_fingerprint(shifted) == evidence_fingerprint(packet)


# -- the split: model and prompt must not touch evidence identity --------


def test_provider_and_model_do_not_change_the_evidence_fingerprint(snapshot):
    """The mutation this kills: a model upgrade making every stored explanation
    look as though the underlying research had changed."""
    packet = build(snapshot)
    before = evidence_fingerprint(packet)
    reasoning_of(packet, model="other-model", provider="other")
    assert evidence_fingerprint(packet) == before


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("prompt_id", "something_else"),
        ("prompt_version", 2),
        ("prompt_fingerprint", "deadbeefdeadbeef"),
        ("output_schema_version", 2),
        ("provider", "other"),
        ("model", "other-model"),
    ],
)
def test_each_reasoning_input_changes_the_reasoning_fingerprint(
    snapshot, field_name, value
):
    packet = build(snapshot)
    assert reasoning_of(packet, **{field_name: value}) != reasoning_of(packet)


def test_changing_the_evidence_changes_the_reasoning_fingerprint(snapshot):
    packet = build(snapshot)
    fewer = dataclasses.replace(packet, observations=packet.observations[:-1])
    assert reasoning_of(fewer) != reasoning_of(packet)


def test_the_reasoning_fingerprint_carries_no_timestamp(snapshot):
    """The same question, asked the same way, of the same evidence, has one
    identity -- whenever it was asked."""
    early = build(snapshot, now=snapshot.built_at)
    late = build(snapshot, now=snapshot.built_at + timedelta(days=1000))
    assert reasoning_of(early) == reasoning_of(late)


def test_the_same_inputs_give_the_same_reasoning_fingerprint(snapshot):
    packet = build(snapshot)
    assert reasoning_of(packet) == reasoning_of(packet)


def test_the_reasoning_fingerprint_refuses_missing_identity(snapshot):
    packet = build(snapshot)
    with pytest.raises(ReasoningError):
        reasoning_of(packet, prompt_id="")
    with pytest.raises(ReasoningError):
        reasoning_of(packet, model="   ")


# -- research-context fingerprint ----------------------------------------


def test_the_research_context_fingerprint_is_stable(snapshot):
    assert research_context_fingerprint(snapshot) == research_context_fingerprint(
        snapshot
    )


def test_it_needs_no_packet_and_no_provider(snapshot):
    """Cheap enough to run on every rerun: one already-materialised snapshot."""
    assert len(research_context_fingerprint(snapshot)) == 64


@pytest.mark.parametrize(
    "field_name,value",
    [("symbol", "MSFT"), ("policy_fingerprint", "0" * 16), ("warmup_bars", 7)],
)
def test_changing_research_identity_changes_the_context_fingerprint(
    snapshot, field_name, value
):
    mutated = dataclasses.replace(snapshot, **{field_name: value})
    assert research_context_fingerprint(mutated) != research_context_fingerprint(
        snapshot
    )


def test_a_new_assessment_changes_the_context_fingerprint(snapshot):
    without = dataclasses.replace(snapshot, assessment=None)
    assert research_context_fingerprint(without) != research_context_fingerprint(
        snapshot
    )


def test_a_changed_observation_changes_the_context_fingerprint(snapshot):
    first = snapshot.observations[0]
    name = next(iter(first.evidence))
    altered = dataclasses.replace(first, evidence={**dict(first.evidence), name: 0.5})
    mutated = dataclasses.replace(
        snapshot, observations=(altered,) + snapshot.observations[1:]
    )
    assert research_context_fingerprint(mutated) != research_context_fingerprint(
        snapshot
    )


def test_refetching_the_same_bars_does_not_invalidate_an_explanation(snapshot):
    """``source``, ``decision_index`` and ``history_label`` describe how the
    snapshot was fetched and windowed, not what the research found."""
    refetched = dataclasses.replace(snapshot, source="another-provider")
    assert research_context_fingerprint(refetched) == research_context_fingerprint(
        snapshot
    )


def test_the_context_fingerprint_tracks_the_packet_it_would_produce(snapshot):
    """Two snapshots that agree on research produce the same packet identity."""
    twin = dataclasses.replace(snapshot, source="elsewhere")
    assert evidence_fingerprint(build(twin)) == evidence_fingerprint(build(snapshot))
    assert research_context_fingerprint(twin) == research_context_fingerprint(snapshot)


# -- the evidence digest is a function of the packet and nothing else ----


def test_the_evidence_fingerprint_is_exactly_the_digest_of_the_packet(snapshot):
    """Kills the mutation that folds anything extra -- a model name, a salt, a
    constant -- into the evidence digest. Such a change shifts every digest
    uniformly, so no comparison test notices it; only pinning the derivation
    does."""
    import hashlib

    from src.reasoning.models import canonical_bytes

    packet = build(snapshot)
    expected = hashlib.sha256(canonical_bytes(packet.canonical())).hexdigest()
    assert evidence_fingerprint(packet) == expected


def test_the_reasoning_fingerprint_is_exactly_the_digest_of_its_inputs(snapshot):
    import hashlib

    from src.reasoning.models import canonical_bytes

    packet = build(snapshot)
    expected = hashlib.sha256(
        canonical_bytes(
            {
                "evidence_fingerprint": evidence_fingerprint(packet),
                "reasoning_kind": "explain_research",
                "prompt_id": PROMPT["prompt_id"],
                "prompt_version": PROMPT["prompt_version"],
                "prompt_fingerprint": PROMPT["prompt_fingerprint"],
                "output_schema_version": PROMPT["output_schema_version"],
                "provider": PROMPT["provider"],
                "model": PROMPT["model"],
            }
        )
    ).hexdigest()
    assert reasoning_of(packet) == expected


# -- golden vectors ------------------------------------------------------
#
# Pinned constants, not values recomputed with the helpers under test. A
# derivation test proves the digest is a function of the packet; only a pinned
# vector proves the canonical form itself has not silently changed.


def test_canonical_bytes_golden_vector():
    from src.reasoning.models import canonical_bytes

    payload = {"b": [1, 2], "a": {"y": 2.5, "z": None}, "u": "café", "n": -0.0}
    assert canonical_bytes(payload) == (
        b'{"a":{"y":2.5,"z":null},"b":[1,2],"n":-0.0,"u":"caf\\u00e9"}'
    )


def test_evidence_fingerprint_golden_vector():
    """A fixed packet hashes to a fixed digest. If the canonical form changes,
    this fails even though every relative-comparison test still passes."""
    import hashlib

    from src.reasoning.models import (
        EVIDENCE_SCHEMA_VERSION,
        EvidencePacket,
        PacketObservation,
    )

    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    fixed = EvidencePacket(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        symbol="AAPL", interval="1d", basis="raw",
        data_cutoff=stamp, policy_fingerprint="a829b9bde41c3332",
        warmup_bars=51, minimum_sufficient_observations=2,
        assessment_state="bullish",
        counts=PacketCounts(bullish=2, bearish=0, neutral=1, insufficient=0),
        assessment_reason_codes=("directional_bullish_with_neutral",),
        observations=(
            PacketObservation(
                hypothesis_id="trend_alignment", version=1,
                hypothesis_fingerprint="650add07184f8440", state="bullish",
                reason_codes=("fast_above_slow",), timestamp=stamp,
                evidence={"sma(field='close',period=20)": 209.5},
            ),
        ),
        generated_at=stamp, omitted_counts={},
    )
    expected_bytes = (
        b'{"assessment_reason_codes":["directional_bullish_with_neutral"],'
        b'"assessment_state":"bullish","basis":"raw",'
        b'"counts":{"bearish":0,"bullish":2,"insufficient":0,"neutral":1},'
        b'"data_cutoff":"2026-01-01T00:00:00+00:00","interval":"1d",'
        b'"minimum_sufficient_observations":2,"observations":'
        b'[{"evidence":{"sma(field=\'close\',period=20)":209.5},'
        b'"evidence_id":"obs:trend_alignment:v1:650add07184f8440",'
        b'"hypothesis_fingerprint":"650add07184f8440",'
        b'"hypothesis_id":"trend_alignment","reason_codes":["fast_above_slow"],'
        b'"state":"bullish","timestamp":"2026-01-01T00:00:00+00:00","version":1}],'
        b'"omitted_counts":{},"policy_fingerprint":"a829b9bde41c3332",'
        b'"schema_version":1,"symbol":"AAPL","warmup_bars":51}'
    )
    from src.reasoning.models import canonical_bytes

    assert canonical_bytes(fixed.canonical()) == expected_bytes
    assert evidence_fingerprint(fixed) == hashlib.sha256(expected_bytes).hexdigest()
    assert evidence_fingerprint(fixed) == (
        "1883aad994092d8a598bb06e1344250a9a9bc5410d20871c3283ba9db0bc0eed"
    )
