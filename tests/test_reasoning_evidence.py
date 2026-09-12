"""Phase 11A Stage A: packet assembly from a real research snapshot.

Built against snapshots the actual pipeline produces, not hand-made stubs, so a
change in what research emits shows up here rather than in a prompt.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from src.application.snapshot import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    build_snapshot,
)
from src.data.models import Interval
from src.data.series import BarSeries
from src.features.base import FeatureSeries
from src.reasoning.evidence import build_packet
from src.reasoning.models import (
    EVIDENCE_SCHEMA_VERSION,
    MAX_OBSERVATION_EVIDENCE_ITEMS,
    MAX_PACKET_OBSERVATIONS,
    MAX_REASON_CODES,
    EvidencePacket,
    PacketObservation,
    ReasoningError,
)
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


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


# -- faithful mapping ----------------------------------------------------


def test_the_packet_mirrors_the_snapshot_exactly(snapshot):
    packet = build(snapshot)
    assert packet.schema_version == EVIDENCE_SCHEMA_VERSION
    assert packet.symbol == snapshot.symbol
    assert packet.interval == snapshot.interval.value
    assert packet.basis == snapshot.basis.value
    assert packet.data_cutoff == snapshot.built_at
    assert packet.policy_fingerprint == snapshot.policy_fingerprint
    assert packet.warmup_bars == snapshot.warmup_bars == WARMUP_BARS
    assert packet.minimum_sufficient_observations == MINIMUM_SUFFICIENT_OBSERVATIONS
    assert packet.generated_at == snapshot.built_at + timedelta(seconds=1)


def test_the_assessment_is_copied_not_recomputed(snapshot):
    packet = build(snapshot)
    assessment = snapshot.assessment
    assert packet.assessment_state == assessment.state.value
    assert packet.counts.bullish == assessment.counts.bullish
    assert packet.counts.bearish == assessment.counts.bearish
    assert packet.counts.neutral == assessment.counts.neutral
    assert packet.counts.insufficient == assessment.counts.insufficient
    assert packet.assessment_reason_codes == tuple(
        code.value for code in assessment.reason_codes
    )


def test_every_observation_survives_with_its_own_identity(snapshot):
    packet = build(snapshot)
    assert len(packet.observations) == len(snapshot.observations)
    for built, raw in zip(packet.observations, snapshot.observations):
        assert built.hypothesis_id == raw.hypothesis_id
        assert built.version == raw.version
        assert built.hypothesis_fingerprint == raw.fingerprint
        assert built.state == raw.state.value
        assert built.reason_codes == tuple(code.value for code in raw.reason_codes)
        assert built.timestamp == raw.timestamp
        assert dict(built.evidence) == dict(raw.evidence)


def test_the_interval_is_the_wire_value_not_the_enum_repr(snapshot):
    assert build(snapshot).interval == "1d"


# -- identity ------------------------------------------------------------


def test_observation_ids_are_built_from_domain_identity(snapshot):
    packet = build(snapshot)
    for built, raw in zip(packet.observations, snapshot.observations):
        assert built.evidence_id == (
            f"obs:{raw.hypothesis_id}:v{raw.version}:{raw.fingerprint}"
        )


def test_observation_ids_use_the_whole_fingerprint(snapshot):
    """A truncated digest would let two re-parameterised hypotheses collide."""
    for built, raw in zip(build(snapshot).observations, snapshot.observations):
        assert raw.fingerprint in built.evidence_id
        assert built.evidence_id.endswith(raw.fingerprint)


def test_observation_ids_do_not_depend_on_position(snapshot):
    """Reversing the snapshot's observations must not rename anything."""
    forward = {o.hypothesis_id: o.evidence_id for o in build(snapshot).observations}
    reversed_snapshot = dataclasses.replace(
        snapshot, observations=tuple(reversed(snapshot.observations))
    )
    backward = {
        o.hypothesis_id: o.evidence_id for o in build(reversed_snapshot).observations
    }
    assert forward == backward


def test_datum_ids_name_the_observation_and_the_feature(snapshot):
    observation = build(snapshot).observations[0]
    for name in observation.evidence:
        assert observation.datum_id(name) == f"{observation.evidence_id}#{name}"
        assert observation.datum_id(name) in build(snapshot).evidence_ids


def test_evidence_ids_are_unique(snapshot):
    packet = build(snapshot)
    ids = [o.evidence_id for o in packet.observations]
    ids += [o.datum_id(n) for o in packet.observations for n in o.evidence]
    assert len(ids) == len(set(ids))


# -- determinism ---------------------------------------------------------


def test_evidence_keys_are_sorted_regardless_of_source_order(snapshot):
    for observation in build(snapshot).observations:
        assert list(observation.evidence) == sorted(observation.evidence)


def test_building_twice_from_the_same_inputs_is_identical(snapshot):
    first, second = build(snapshot), build(snapshot)
    assert first.canonical() == second.canonical()


def test_observation_order_follows_the_snapshot(snapshot):
    packet = build(snapshot)
    assert [o.hypothesis_id for o in packet.observations] == [
        o.hypothesis_id for o in snapshot.observations
    ]


# -- what must not survive the boundary ----------------------------------


def _reachable(value, depth=0, seen=None):
    """Every object reachable from a record, by identity rather than by name."""
    seen = seen if seen is not None else set()
    if depth > 6 or id(value) in seen:
        return
    seen.add(id(value))
    yield value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from _reachable(getattr(value, f.name), depth + 1, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _reachable(item, depth + 1, seen)
    elif hasattr(value, "items") and not isinstance(value, (str, bytes)):
        for key, item in value.items():
            yield from _reachable(key, depth + 1, seen)
            yield from _reachable(item, depth + 1, seen)


@pytest.mark.parametrize("forbidden", [BarSeries, FeatureSeries])
def test_no_heavy_research_object_is_retained(snapshot, forbidden):
    """Checked by object identity, not by field name -- a series smuggled in
    under any attribute would keep the whole snapshot alive."""
    packet = build(snapshot)
    offenders = [v for v in _reachable(packet) if isinstance(v, forbidden)]
    assert not offenders, f"packet retains {forbidden.__name__}"


def test_the_research_snapshot_itself_is_not_retained(snapshot):
    packet = build(snapshot)
    assert not any(v is snapshot for v in _reachable(packet))
    assert not any(type(v).__name__ == "ResearchSnapshot" for v in _reachable(packet))


def test_the_packet_holds_only_plain_values(snapshot):
    """Strings, numbers, timestamps and packet records. Nothing else."""
    allowed = (str, int, float, bool, type(None), datetime,
               EvidencePacket, PacketObservation)
    for value in _reachable(build(snapshot)):
        if isinstance(value, (tuple, list, set, frozenset)) or hasattr(value, "items"):
            continue
        if type(value).__name__ == "PacketCounts":
            continue
        assert isinstance(value, allowed), f"packet retains {type(value).__name__}"


# -- causality -----------------------------------------------------------


def test_an_observation_after_the_cutoff_is_refused(snapshot):
    future = dataclasses.replace(
        snapshot.observations[0], timestamp=snapshot.built_at + timedelta(days=1)
    )
    poisoned = dataclasses.replace(snapshot, observations=(future,))
    with pytest.raises(ReasoningError, match="after the data cutoff"):
        build(poisoned)


def test_a_future_observation_is_not_silently_clamped_or_dropped(snapshot):
    """Refusal, not repair: a quietly fixed causal breach is worse than a loud one."""
    future = dataclasses.replace(
        snapshot.observations[0], timestamp=snapshot.built_at + timedelta(seconds=1)
    )
    poisoned = dataclasses.replace(
        snapshot, observations=(future,) + snapshot.observations[1:]
    )
    with pytest.raises(ReasoningError):
        build(poisoned)


def test_every_packet_observation_is_at_or_before_the_cutoff(snapshot):
    packet = build(snapshot)
    assert all(o.timestamp <= packet.data_cutoff for o in packet.observations)


# -- injected values -----------------------------------------------------


def test_now_is_injected_and_never_read_from_the_clock(snapshot):
    stamp = datetime(2031, 1, 1, tzinfo=UTC)
    assert build(snapshot, now=stamp).generated_at == stamp


def test_a_packet_cannot_predate_the_research_it_describes(snapshot):
    """``generated_at`` before ``data_cutoff`` is nonsense provenance: the
    packet would claim to have been assembled before the snapshot existed."""
    with pytest.raises(ReasoningError, match="precedes data_cutoff"):
        build(snapshot, now=snapshot.built_at - timedelta(seconds=1))


def test_a_packet_generated_exactly_at_the_cutoff_is_accepted(snapshot):
    assert build(snapshot, now=snapshot.built_at).generated_at == snapshot.built_at


def test_a_naive_now_is_refused(snapshot):
    with pytest.raises(ReasoningError, match="timezone-aware"):
        build(snapshot, now=datetime(2026, 9, 7, 12))


def test_the_policy_minimum_must_be_supplied(snapshot):
    """It lives in the application layer, which this package may not import, and
    it is not published on the snapshot. Guessing it would misreport the rule."""
    with pytest.raises(TypeError):
        build_packet(snapshot, now=NOW)


# -- absence -------------------------------------------------------------


def test_a_snapshot_without_an_assessment_yields_an_honest_packet(snapshot):
    without = dataclasses.replace(snapshot, assessment=None)
    packet = build(without)
    assert packet.assessment_state is None
    assert packet.counts is None
    assert packet.assessment_reason_codes == ()
    assert packet.has_assessment is False
    assert packet.observations


# -- caps and omission ---------------------------------------------------


def test_nothing_is_omitted_from_an_ordinary_packet(snapshot):
    assert dict(build(snapshot).omitted_counts) == {}


def test_too_many_observations_refuse_the_packet(snapshot):
    """Authoritative evidence is never truncated.

    Every hypothesis contributed to the assessment the packet carries, so a
    truncated packet would state counts its own observations cannot account
    for -- an explanation of a verdict on evidence the model was not shown.
    Refusal is the same choice the universe loader makes for too many symbols.
    """
    one = snapshot.observations[0]
    many = tuple(
        dataclasses.replace(one, hypothesis_id=f"hypothesis_{index}")
        for index in range(MAX_PACKET_OBSERVATIONS + 3)
    )
    with pytest.raises(ReasoningError, match="cannot account for"):
        build(dataclasses.replace(snapshot, observations=many))


def test_a_packet_never_carries_an_assessment_it_cannot_explain(snapshot):
    """The concrete failure refusal prevents: counts describing more
    hypotheses than the packet holds observations for."""
    one = snapshot.observations[0]
    many = tuple(
        dataclasses.replace(one, hypothesis_id=f"hypothesis_{index}")
        for index in range(MAX_PACKET_OBSERVATIONS + 1)
    )
    with pytest.raises(ReasoningError):
        build(dataclasses.replace(snapshot, observations=many))


def test_too_many_evidence_values_refuse_the_packet(snapshot):
    wide = dataclasses.replace(
        snapshot.observations[0],
        evidence={f"feature_{i:02d}": float(i)
                  for i in range(MAX_OBSERVATION_EVIDENCE_ITEMS + 2)},
    )
    with pytest.raises(ReasoningError, match="partial evidence"):
        build(dataclasses.replace(snapshot, observations=(wide,)))


def test_too_many_reason_codes_refuse_the_packet(snapshot):
    """Reason codes are why the assessment says what it says."""
    crowded = dataclasses.replace(
        snapshot.observations[0],
        reason_codes=tuple(
            snapshot.observations[0].reason_codes[:1] * (MAX_REASON_CODES + 1)
        ),
    )
    with pytest.raises(ReasoningError, match="part of an"):
        build(dataclasses.replace(snapshot, observations=(crowded,)))


def test_a_packet_at_exactly_the_cap_is_accepted(snapshot):
    one = snapshot.observations[0]
    exact = tuple(
        dataclasses.replace(one, hypothesis_id=f"hypothesis_{index}")
        for index in range(MAX_PACKET_OBSERVATIONS)
    )
    packet = build(dataclasses.replace(snapshot, observations=exact))
    assert len(packet.observations) == MAX_PACKET_OBSERVATIONS
