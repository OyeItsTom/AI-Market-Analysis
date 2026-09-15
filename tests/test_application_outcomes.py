"""Phase 12D: outcome orchestration on the explicit refresh.

``refresh_outcomes`` joins a completed ``ResearchSnapshot`` to the Phase 12
ledger: it registers what the snapshot claimed and records, through Phase
12B, what the market did after earlier claims. These tests drive it with real
snapshots built by ``build_snapshot`` from a deterministic provider and a
real JSONL ledger under a temporary root, so every line that is written is
a line the production path would write.

Nothing here reaches a network, reads a clock, or touches the repository's
``data/outcomes``.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.application.outcomes import (
    DEFAULT_OUTCOMES_ROOT,
    OUTCOME_HORIZONS,
    OUTCOME_SPECS,
    ArtifactRegistration,
    OutcomeItem,
    OutcomeItemStatus,
    OutcomeRefreshError,
    OutcomeRefreshResult,
    build_outcome_ledger,
    refresh_outcomes,
)
from src.application.snapshot import BASIS, ResearchSnapshot, build_snapshot
from src.assessments.assessment import AssessmentReasonCode, AssessmentState
from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.evaluation import OutcomeSpec, measure_forward
from src.outcomes import (
    EVALUATION_VERSION,
    ArtifactOrigin,
    AssessmentArtifact,
    JsonlOutcomeLedger,
    LedgerCorruption,
    LedgerPartition,
    ObservationArtifact,
    OutcomeTrackingError,
    RefusalReason,
    UnsupportedSchemaError,
    WriteResult,
    WriteStatus,
    bar_fingerprint,
    outcome_key,
)
from src.strategies.research import ReasonCode, ResearchState
from tests.test_application_snapshot import CLOCK_NOW, RecordingProvider

UTC = timezone.utc
REPO = pathlib.Path(__file__).resolve().parent.parent
MODULE = REPO / "src" / "application" / "outcomes.py"

#: Test-only horizons: short enough that two more bars complete the first.
SPECS = (OutcomeSpec(horizon_bars=1), OutcomeSpec(horizon_bars=3))
H1, H3 = SPECS


# -- fixtures ----------------------------------------------------------------------------


def at(days: int) -> datetime:
    return CLOCK_NOW + timedelta(days=days)


def snapshot(count: int = 80, *, now: datetime = CLOCK_NOW, provider=None) -> ResearchSnapshot:
    """A real snapshot from the deterministic ramp provider: ``count`` daily
    bars from 2020-01-01, the last one the research point."""
    provider = provider or RecordingProvider(count)
    return build_snapshot(provider, "AAPL", Interval.DAY_1, now=lambda: now)


def partition_of(snap: ResearchSnapshot) -> LedgerPartition:
    return LedgerPartition(symbol=snap.symbol, interval=snap.interval, basis=snap.basis)


def refresh(snap, ledger, specs=SPECS, *, now=None):
    return refresh_outcomes(snap, specs, ledger, now=snap.built_at if now is None else now)


def lines(path: pathlib.Path) -> int:
    return len(path.read_bytes().split(b"\n")) - 1 if path.exists() else 0


def artifacts_file(ledger, snap) -> pathlib.Path:
    return ledger.artifacts_path(partition_of(snap))


def outcomes_file(ledger, snap) -> pathlib.Path:
    return ledger.outcomes_path(partition_of(snap))


@pytest.fixture
def ledger(tmp_path):
    return build_outcome_ledger(tmp_path / "outcomes")


class OtherSourceProvider(RecordingProvider):
    """The same numbers from a differently named provider."""

    name = "other"


class RevisingProvider(RecordingProvider):
    """The ramp, with one bar's close revised after the fact."""

    def __init__(self, count, *, revised_index):
        super().__init__(count)
        self.revised_index = revised_index

    def get_bars(self, *args, **kwargs):
        bars = super().get_bars(*args, **kwargs)
        target = bars[self.revised_index]
        bars[self.revised_index] = dataclasses.replace(target, close=target.close + 0.5)
        return bars


class DroppingProvider(RecordingProvider):
    """The ramp with one bar missing from the middle of the window."""

    def __init__(self, count, *, dropped_index):
        super().__init__(count)
        self.dropped_index = dropped_index

    def get_bars(self, *args, **kwargs):
        bars = super().get_bars(*args, **kwargs)
        del bars[self.dropped_index]
        return bars


# -- policy --------------------------------------------------------------------------------


class TestPolicy:
    def test_the_dashboard_tracks_one_five_and_twenty_bars(self):
        assert OUTCOME_HORIZONS == (1, 5, 20)
        assert tuple(spec.horizon_bars for spec in OUTCOME_SPECS) == OUTCOME_HORIZONS

    def test_every_production_spec_is_on_the_dashboard_basis(self):
        assert all(spec.required_basis is BASIS for spec in OUTCOME_SPECS)

    def test_production_spec_fingerprints_are_distinct(self):
        assert len({spec.fingerprint for spec in OUTCOME_SPECS}) == len(OUTCOME_SPECS)

    def test_the_default_root_is_a_path_the_conftest_guard_has_redirected(self, tmp_path):
        assert isinstance(DEFAULT_OUTCOMES_ROOT, pathlib.Path)
        import src.application.outcomes as module

        assert module.DEFAULT_OUTCOMES_ROOT == tmp_path / "outcomes-default"

    def test_the_unpatched_default_root_is_the_repository_data_outcomes(self):
        """The conftest guard patches the attribute in this process; a fresh
        interpreter shows what production composes."""
        import subprocess
        import sys

        printed = subprocess.run(
            [sys.executable, "-c",
             "import src.application.outcomes as m; print(m.DEFAULT_OUTCOMES_ROOT)"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert pathlib.Path(printed) == REPO / "data" / "outcomes"

    def test_build_outcome_ledger_injects_the_root_and_touches_nothing(self, tmp_path):
        root = tmp_path / "somewhere"
        ledger = build_outcome_ledger(root)
        assert isinstance(ledger, JsonlOutcomeLedger)
        assert ledger.root == root
        assert not root.exists()

    def test_build_outcome_ledger_uses_the_default_root_when_none_is_given(self, tmp_path):
        import src.application.outcomes as module

        assert build_outcome_ledger().root == module.DEFAULT_OUTCOMES_ROOT
        assert str(module.DEFAULT_OUTCOMES_ROOT).startswith(str(tmp_path))


# -- artifact creation -----------------------------------------------------------------


class TestArtifactCreation:
    def test_every_observation_and_the_assessment_become_artifacts(self, ledger):
        snap = snapshot()
        result = refresh(snap, ledger)
        held = list(ledger.iter_artifacts(partition_of(snap)))
        assert len(snap.observations) == 3 and snap.assessment is not None
        assert len(held) == 4
        assert [type(a) for a in held] == [ObservationArtifact] * 3 + [AssessmentArtifact]
        assert result.artifacts_considered == 4 and result.artifacts_written == 4

    def test_observation_artifacts_copy_the_claim_and_provenance_exactly(self, ledger):
        snap = snapshot()
        refresh(snap, ledger)
        held = [a for a in ledger.iter_artifacts(partition_of(snap))
                if isinstance(a, ObservationArtifact)]
        for artifact, observation in zip(held, snap.observations):
            assert artifact.state is observation.state
            assert artifact.reason_codes == observation.reason_codes
            assert artifact.hypothesis_id == observation.hypothesis_id
            assert artifact.hypothesis_version == observation.version
            assert artifact.hypothesis_fingerprint == observation.fingerprint
            assert artifact.timestamp == observation.timestamp

    def test_the_assessment_artifact_copies_the_policy_and_claim_exactly(self, ledger):
        snap = snapshot()
        refresh(snap, ledger)
        artifact = [a for a in ledger.iter_artifacts(partition_of(snap))
                    if isinstance(a, AssessmentArtifact)][0]
        assert artifact.policy_fingerprint == snap.assessment.policy_fingerprint
        assert artifact.policy_fingerprint == snap.policy_fingerprint
        assert artifact.state is snap.assessment.state
        assert artifact.reason_codes == snap.assessment.reason_codes

    def test_audit_fields_come_from_the_series_tail_and_the_injected_clock(self, ledger):
        snap = snapshot()
        now = at(0)
        refresh(snap, ledger, now=now)
        tail = snap.series[-1]
        for artifact in ledger.iter_artifacts(partition_of(snap)):
            assert artifact.symbol == snap.symbol == snap.series.symbol
            assert artifact.interval is snap.interval
            assert artifact.basis is snap.basis
            assert artifact.source == snap.series.source == "fake"
            assert artifact.timestamp == tail.timestamp == snap.latest_bar_open
            assert artifact.data_cutoff == tail.timestamp
            assert artifact.recorded_at == now
            assert artifact.observation_bar_fingerprint == bar_fingerprint(tail)
            assert artifact.origin is ArtifactOrigin.SNAPSHOT

    def test_only_the_tail_bar_is_registered_never_history(self, ledger):
        snap = snapshot()
        refresh(snap, ledger)
        stamps = {a.timestamp for a in ledger.iter_artifacts(partition_of(snap))}
        assert stamps == {snap.series[-1].timestamp}

    def test_registrations_are_reported_in_snapshot_order(self, ledger):
        snap = snapshot()
        result = refresh(snap, ledger)
        labels = [entry.label for entry in result.registrations]
        assert labels == [o.label for o in snap.observations] + [
            f"policy#{snap.policy_fingerprint}"
        ]
        assert [entry.status for entry in result.registrations] == [WriteStatus.WRITTEN] * 4

    def test_keys_are_the_domain_records_own(self, ledger):
        snap = snapshot()
        result = refresh(snap, ledger)
        held = {a.artifact_key: a for a in ledger.iter_artifacts(partition_of(snap))}
        for entry in result.registrations:
            assert entry.artifact_key == held[entry.artifact_key].artifact_key

    def test_a_snapshot_with_no_bars_registers_nothing_and_writes_nothing(self, ledger):
        snap = snapshot(0)
        assert snap.observations == () and snap.assessment is None
        result = refresh(snap, ledger)
        assert result.registrations == () and result.items == ()
        assert not artifacts_file(ledger, snap).exists()


# -- INSUFFICIENT_DATA -------------------------------------------------------------------


class TestInsufficientData:
    def test_insufficient_claims_are_registered_but_ineligible(self, ledger):
        snap = snapshot(20)
        assert all(o.state is ResearchState.INSUFFICIENT_DATA for o in snap.observations)
        assert snap.assessment.state is AssessmentState.INSUFFICIENT_DATA
        result = refresh(snap, ledger)
        assert result.artifacts_written == 4
        assert result.ineligible == len(result.items) == 4 * len(SPECS)
        assert not outcomes_file(ledger, snap).exists()

    def test_repeating_the_refresh_adds_no_line(self, ledger):
        snap = snapshot(20)
        refresh(snap, ledger)
        before = lines(artifacts_file(ledger, snap))
        result = refresh(snap, ledger, now=at(1))
        assert result.artifact_duplicates == 4 and result.artifacts_written == 0
        assert lines(artifacts_file(ledger, snap)) == before == 4

    def test_insufficient_artifacts_stay_ineligible_when_the_future_arrives(self, ledger):
        refresh(snapshot(20), ledger)
        later = snapshot(30, now=at(10))
        result = refresh(later, ledger)
        old = [i for i in result.items if i.timestamp == snapshot(20).series[-1].timestamp]
        assert old and all(i.status is OutcomeItemStatus.INELIGIBLE for i in old)
        assert not outcomes_file(ledger, later).exists()


# -- registration idempotency ------------------------------------------------------------


class TestRegistrationIdempotency:
    def test_first_written_then_duplicate_with_no_growth(self, ledger):
        snap = snapshot()
        first = refresh(snap, ledger)
        assert [e.status for e in first.registrations] == [WriteStatus.WRITTEN] * 4
        second = refresh(snap, ledger)
        assert [e.status for e in second.registrations] == [WriteStatus.DUPLICATE] * 4
        assert lines(artifacts_file(ledger, snap)) == 4

    def test_a_later_clock_on_the_same_claim_is_a_duplicate_not_a_conflict(self, ledger):
        """Two refreshes on one day: same settled bars, same claim, later clock.
        The registration clock is the ledger's and belongs to the first."""
        snap = snapshot()
        refresh(snap, ledger, now=at(0))
        result = refresh(snap, ledger, now=at(0) + timedelta(hours=6))
        assert result.artifact_duplicates == 4 and result.artifacts_written == 0
        assert lines(artifacts_file(ledger, snap)) == 4
        assert {a.recorded_at for a in ledger.iter_artifacts(partition_of(snap))} == {at(0)}

    def test_a_re_sighted_claim_is_offered_with_the_held_clock_and_the_ledger_decides(
        self, ledger
    ):
        """No application-side comparison: the held registration clock is
        applied and ``register_artifact`` is called for every claim."""
        snap = snapshot()
        refresh(snap, ledger, now=at(0))
        offered = []

        class Watching:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def register_artifact(self, artifact):
                offered.append(artifact)
                return self.inner.register_artifact(artifact)

        result = refresh(snap, Watching(ledger), now=at(0) + timedelta(hours=6))
        assert len(offered) == 4
        assert {a.recorded_at for a in offered} == {at(0)}
        assert [e.status for e in result.registrations] == [WriteStatus.DUPLICATE] * 4

    def test_the_same_identity_with_a_different_claim_fails_the_refresh(self, ledger):
        snap = snapshot()
        refresh(snap, ledger)
        flipped = dataclasses.replace(
            snap.observations[0], state=ResearchState.BEARISH,
            reason_codes=(ReasonCode.FAST_BELOW_SLOW,),
        )
        contradicting = dataclasses.replace(
            snap, observations=(flipped,) + snap.observations[1:], assessment=None,
        )
        before = artifacts_file(ledger, snap).read_bytes()
        with pytest.raises(OutcomeRefreshError, match="different claim"):
            refresh(contradicting, ledger)
        assert artifacts_file(ledger, snap).read_bytes() == before
        assert not outcomes_file(ledger, snap).exists()

    def test_the_same_identity_with_a_different_source_fails_the_refresh(self, ledger):
        snap = snapshot()
        refresh(snap, ledger)
        with pytest.raises(OutcomeRefreshError, match="different claim"):
            refresh(snapshot(provider=OtherSourceProvider(80)), ledger)


# -- the lifecycle -----------------------------------------------------------------------


class TestLifecycle:
    def test_pending_then_evaluated_across_two_refreshes(self, ledger):
        first_snap = snapshot(80, now=at(0))
        first = refresh(first_snap, ledger)
        assert first.artifacts_written == 4
        assert first.pending == len(first.items) == 8
        assert first.outcomes_written == 0
        assert not outcomes_file(ledger, first_snap).exists()

        second_snap = snapshot(82, now=at(2))
        second = refresh(second_snap, ledger)
        old_stamp = first_snap.series[-1].timestamp
        old = [i for i in second.items if i.timestamp == old_stamp]
        new = [i for i in second.items if i.timestamp == second_snap.series[-1].timestamp]
        assert {(i.horizon_bars, i.status) for i in old} == {
            (1, OutcomeItemStatus.WRITTEN), (3, OutcomeItemStatus.PENDING)
        }
        assert all(i.status is OutcomeItemStatus.PENDING for i in new) and len(new) == 8
        assert second.artifacts_written == 4 and second.outcomes_written == 4
        assert lines(artifacts_file(ledger, second_snap)) == 8
        assert lines(outcomes_file(ledger, second_snap)) == 4

    def test_the_completed_outcome_is_phase_four_measurement_of_the_old_claim(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        second_snap = snapshot(82, now=at(2))
        refresh(second_snap, ledger)
        part = partition_of(second_snap)
        old_artifacts = [a for a in ledger.iter_artifacts(part)
                         if a.timestamp == first_snap.series[-1].timestamp]
        assert len(old_artifacts) == 4
        for artifact in old_artifacts:
            outcome = ledger.get_outcome(part, outcome_key(
                artifact_key=artifact.artifact_key, spec_fingerprint=H1.fingerprint,
                evaluation_version=EVALUATION_VERSION))
            assert outcome is not None
            expected = measure_forward(
                second_snap.series, H1, symbol=artifact.symbol, interval=artifact.interval,
                basis=artifact.basis, timestamp=artifact.timestamp,
            )
            assert outcome.forward_return == expected.outcome_value
            assert outcome.reference_timestamp == expected.reference_timestamp
            assert outcome.future_timestamp == expected.future_timestamp
            assert outcome.evaluated_at == at(2)
            assert outcome.artifact == artifact          # original recorded_at kept
            assert outcome.recorded_at == at(0)

    def test_no_retrospective_identity_change_and_no_duplicate_lines(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        before = artifacts_file(ledger, first_snap).read_bytes()
        refresh(snapshot(82, now=at(2)), ledger)
        after = artifacts_file(ledger, first_snap).read_bytes()
        assert after.startswith(before)
        assert lines(artifacts_file(ledger, first_snap)) == 8

    def test_multi_horizon_completes_in_turn_without_remeasuring(self, ledger, monkeypatch):
        import src.application.outcomes as module

        refresh(snapshot(80, now=at(0)), ledger)
        second = refresh(snapshot(82, now=at(2)), ledger)
        assert (second.outcomes_written, second.pending) == (4, 12)

        calls: list[tuple[str, int]] = []
        real = module.evaluate_artifact

        def spy(artifact, series, spec, *, evaluated_at):
            calls.append((artifact.artifact_key, spec.horizon_bars))
            return real(artifact, series, spec, evaluated_at=evaluated_at)

        monkeypatch.setattr(module, "evaluate_artifact", spy)
        third_snap = snapshot(84, now=at(4))
        third = refresh(third_snap, ledger)
        old_stamp = snapshot(80).series[-1].timestamp
        old = [i for i in third.items if i.timestamp == old_stamp]
        assert {(i.horizon_bars, i.status) for i in old} == {
            (1, OutcomeItemStatus.PRESENT), (3, OutcomeItemStatus.WRITTEN)
        }
        present_keys = {i.artifact_key for i in old}
        assert not [c for c in calls if c[0] in present_keys and c[1] == 1], (
            "an already-durable outcome was re-measured"
        )
        assert [c for c in calls if c[0] in present_keys and c[1] == 3]
        assert lines(outcomes_file(ledger, third_snap)) == 4 + 4 + 4

    def test_pending_is_reported_retried_and_never_stored(self, ledger):
        snap = snapshot(80, now=at(0))
        result = refresh(snap, ledger)
        assert result.pending == 8
        directory = ledger.partition_dir(partition_of(snap))
        assert sorted(p.name for p in directory.iterdir()) == ["artifacts.jsonl"]
        again = refresh(snap, ledger, now=at(1))
        assert again.pending == 8
        assert sorted(p.name for p in directory.iterdir()) == ["artifacts.jsonl"]

    def test_present_outcomes_are_not_reevaluated_on_a_repeat(self, ledger, monkeypatch):
        import src.application.outcomes as module

        refresh(snapshot(80, now=at(0)), ledger)
        completed = refresh(snapshot(82, now=at(2)), ledger)
        durable = {(i.artifact_key, i.horizon_bars) for i in completed.items
                   if i.status is OutcomeItemStatus.WRITTEN}
        assert len(durable) == 4
        real = module.evaluate_artifact

        def guard(artifact, series, spec, *, evaluated_at):
            assert (artifact.artifact_key, spec.horizon_bars) not in durable, (
                "evaluate_artifact was called for an already-durable outcome"
            )
            return real(artifact, series, spec, evaluated_at=evaluated_at)

        monkeypatch.setattr(module, "evaluate_artifact", guard)
        again = refresh(snapshot(82, now=at(3)), ledger)
        assert {(i.artifact_key, i.horizon_bars) for i in again.items
                if i.status is OutcomeItemStatus.PRESENT} == durable


# -- durability across ledger instances ---------------------------------------------------


class TestRestart:
    def test_a_fresh_ledger_instance_rediscovers_the_registered_claims(self, tmp_path):
        """No in-memory registration state: session A registers, session B
        (a new ledger over the same root) evaluates and persists."""
        root = tmp_path / "outcomes"
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, build_outcome_ledger(root))
        second_snap = snapshot(82, now=at(2))
        second = refresh(second_snap, build_outcome_ledger(root))
        assert second.artifacts_tracked == 8 and second.outcomes_written == 4
        third = refresh(snapshot(82, now=at(3)), build_outcome_ledger(root))
        assert third.outcomes_already_present == 4 and third.outcomes_written == 0
        part = partition_of(second_snap)
        assert len(list(build_outcome_ledger(root).iter_outcomes(part))) == 4

    def test_a_failure_part_way_leaves_earlier_appends_durable_and_the_next_refresh_resumes(
        self, ledger
    ):
        refresh(snapshot(80, now=at(0)), ledger)

        class FailsOnSecondAppend:
            def __init__(self, inner):
                self.inner = inner
                self.appends = 0

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def append_outcome(self, outcome):
                self.appends += 1
                if self.appends == 2:
                    raise OutcomeTrackingError("simulated failure after one durable append")
                return self.inner.append_outcome(outcome)

        second_snap = snapshot(82, now=at(2))
        with pytest.raises(OutcomeTrackingError, match="simulated"):
            refresh(second_snap, FailsOnSecondAppend(ledger))
        assert lines(outcomes_file(ledger, second_snap)) == 1          # durable, kept
        assert lines(artifacts_file(ledger, second_snap)) == 8         # registered first
        resumed = refresh(snapshot(82, now=at(3)), ledger)
        assert resumed.outcomes_already_present == 1
        assert resumed.outcomes_written == 3
        assert lines(outcomes_file(ledger, second_snap)) == 4


# -- refusals -----------------------------------------------------------------------------


class TestRefused:
    def test_a_different_source_is_refused_and_nothing_is_written(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        before = artifacts_file(ledger, first_snap).read_bytes()
        second = refresh(snapshot(82, now=at(2), provider=OtherSourceProvider(82)), ledger)
        old = [i for i in second.items if i.timestamp == first_snap.series[-1].timestamp]
        assert old and all(i.status is OutcomeItemStatus.REFUSED for i in old)
        assert {i.refusal for i in old} == {RefusalReason.SOURCE_MISMATCH}
        assert second.refused == 8 and second.outcomes_written == 0
        assert not outcomes_file(ledger, first_snap).exists()
        assert artifacts_file(ledger, first_snap).read_bytes().startswith(before)
        # The new claims, from the other source, are registered as their own.
        assert second.artifacts_written == 4

    def test_a_revised_source_bar_is_refused_and_nothing_is_written(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        provider = RevisingProvider(82, revised_index=79)
        second = refresh(snapshot(82, now=at(2), provider=provider), ledger)
        old = [i for i in second.items if i.timestamp == first_snap.series[-1].timestamp]
        assert {i.refusal for i in old} == {RefusalReason.SOURCE_BAR_REVISED}
        assert second.refused == 8 and second.outcomes_written == 0
        assert not outcomes_file(ledger, first_snap).exists()
        assert lines(artifacts_file(ledger, first_snap)) == 8

    def test_a_refusal_is_not_converted_to_pending(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        second = refresh(snapshot(82, now=at(2), provider=OtherSourceProvider(82)), ledger)
        old = [i for i in second.items if i.timestamp == first_snap.series[-1].timestamp]
        assert not [i for i in old if i.status is OutcomeItemStatus.PENDING]


# -- hard errors ---------------------------------------------------------------------------


class TestHardErrors:
    def test_a_bar_missing_inside_the_window_is_a_hard_error(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)
        provider = DroppingProvider(82, dropped_index=79)
        with pytest.raises(OutcomeTrackingError):
            refresh(snapshot(82, now=at(2), provider=provider), ledger)
        assert not outcomes_file(ledger, first_snap).exists()

    def test_a_retrospective_claim_is_refused_before_anything_is_written(self, ledger):
        snap = snapshot()
        earlier = snap.series[-2].timestamp
        stale = dataclasses.replace(snap.observations[1], timestamp=earlier)
        retro = dataclasses.replace(
            snap, observations=(snap.observations[0], stale, snap.observations[2]),
            assessment=None,
        )
        with pytest.raises(OutcomeRefreshError, match="retrospective"):
            refresh(retro, ledger)
        assert not artifacts_file(ledger, snap).exists()

    def test_a_snapshot_that_does_not_describe_its_series_is_refused(self, ledger):
        snap = snapshot()
        wrong = dataclasses.replace(snap, source="somebody else")
        with pytest.raises(OutcomeRefreshError, match="does not describe its own data"):
            refresh(wrong, ledger)
        assert not artifacts_file(ledger, snap).exists()

    def test_claims_without_bars_are_refused(self, ledger):
        snap = snapshot()
        empty = BarSeries(symbol=snap.symbol, interval=snap.interval, source=snap.source,
                          basis=snap.basis, bars=())
        with pytest.raises(OutcomeRefreshError, match="no bars"):
            refresh(dataclasses.replace(snap, series=empty), ledger)

    def test_a_clock_before_a_registration_is_a_hard_error(self, ledger):
        snap = snapshot(80, now=at(0))
        refresh(snap, ledger)
        with pytest.raises(OutcomeTrackingError):
            refresh(snapshot(82, now=at(2)), ledger, now=at(-1))

    def test_a_snapshot_of_the_wrong_type_is_refused(self, ledger):
        with pytest.raises(OutcomeRefreshError, match="ResearchSnapshot"):
            refresh_outcomes(object(), SPECS, ledger, now=at(0))


# -- the ledger stays authoritative ------------------------------------------------------


class TestLedger:
    def test_corruption_propagates_and_nothing_is_repaired(self, ledger):
        snap = snapshot(80, now=at(0))
        refresh(snap, ledger)
        path = artifacts_file(ledger, snap)
        damaged = path.read_bytes() + b"{not json\n"
        path.write_bytes(damaged)
        with pytest.raises(LedgerCorruption):
            refresh(snapshot(82, now=at(2)), ledger)
        assert path.read_bytes() == damaged
        assert not outcomes_file(ledger, snap).exists()
        assert sorted(p.name for p in path.parent.iterdir()) == ["artifacts.jsonl"]

    def test_an_unsupported_schema_propagates(self, ledger):
        snap = snapshot(80, now=at(0))
        refresh(snap, ledger)
        path = artifacts_file(ledger, snap)
        first = path.read_bytes().split(b"\n")[0]
        path.write_bytes(first.replace(b'"schema_version":1', b'"schema_version":2') + b"\n")
        with pytest.raises(UnsupportedSchemaError):
            refresh(snap, ledger, now=at(1))

    def test_a_pre_existing_conflicting_artifact_fails_the_refresh(self, ledger):
        snap = snapshot()
        artifacts = list(_current(snap, at(0)))
        contradiction = dataclasses.replace(
            artifacts[0], state=ResearchState.BEARISH,
            reason_codes=(ReasonCode.FAST_BELOW_SLOW,),
        )
        assert ledger.register_artifact(contradiction).status is WriteStatus.WRITTEN
        before = artifacts_file(ledger, snap).read_bytes()
        with pytest.raises(OutcomeRefreshError, match="different claim"):
            refresh(snap, ledger, now=at(0))
        assert artifacts_file(ledger, snap).read_bytes() == before
        assert not outcomes_file(ledger, snap).exists()

    def test_an_outcome_conflict_is_an_orchestration_failure(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)

        class Conflicting:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def append_outcome(self, outcome):
                return WriteResult(WriteStatus.CONFLICT, outcome.outcome_key, "forced")

        with pytest.raises(OutcomeRefreshError, match="different outcome"):
            refresh(snapshot(82, now=at(2)), Conflicting(ledger))

    def test_an_outcome_duplicate_verdict_counts_as_present(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)

        class Duplicating:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def append_outcome(self, outcome):
                return WriteResult(WriteStatus.DUPLICATE, outcome.outcome_key)

        result = refresh(snapshot(82, now=at(2)), Duplicating(ledger))
        assert result.outcomes_written == 0 and result.outcomes_already_present == 4

    def test_the_partition_read_once_and_every_write_goes_through_the_ledger(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)
        calls: list[str] = []

        class Counting:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                target = getattr(self.inner, name)
                if not callable(target):
                    return target

                def call(*args, **kwargs):
                    calls.append(name)
                    return target(*args, **kwargs)
                return call

        refresh(snapshot(82, now=at(2)), Counting(ledger))
        assert calls.count("iter_artifacts") == 1
        assert calls.count("iter_outcomes") == 1
        assert calls.count("register_artifact") == 4
        assert calls.count("append_outcome") == 4
        assert "contains_outcome" not in calls and "get_outcome" not in calls


def _current(snap, now):
    """The artifacts the refresh would build, via the domain constructors."""
    tail = snap.series[-1]
    audit = dict(source=snap.series.source, data_cutoff=tail.timestamp, recorded_at=now,
                 observation_bar_fingerprint=bar_fingerprint(tail),
                 origin=ArtifactOrigin.SNAPSHOT)
    yield from (ObservationArtifact.from_observation(o, **audit) for o in snap.observations)
    if snap.assessment is not None:
        yield AssessmentArtifact.from_assessment(snap.assessment, **audit)


# -- partitions and windows ---------------------------------------------------------------


class TestPartitions:
    def test_raw_and_adjusted_are_separate_partitions(self, ledger):
        raw = snapshot()
        adjusted_series = BarSeries.from_bars(list(raw.series.bars), basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        adjusted = dataclasses.replace(
            raw, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED, series=adjusted_series,
            observations=tuple(dataclasses.replace(o, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
                               for o in raw.observations),
            assessment=dataclasses.replace(raw.assessment, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
        )
        adjusted_specs = tuple(
            OutcomeSpec(horizon_bars=s.horizon_bars, required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
            for s in SPECS
        )
        refresh(raw, ledger)
        result = refresh(adjusted, ledger, adjusted_specs)
        assert result.artifacts_written == 4
        assert result.artifacts_tracked == 4          # no raw artifact was seen
        assert artifacts_file(ledger, raw) != artifacts_file(ledger, adjusted)
        assert lines(artifacts_file(ledger, raw)) == 4
        assert lines(artifacts_file(ledger, adjusted)) == 4
        raw_keys = {a.artifact_key for a in ledger.iter_artifacts(partition_of(raw))}
        assert raw_keys.isdisjoint(i.artifact_key for i in result.items)

    def test_a_claim_older_than_the_fetched_window_is_out_of_window(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)

        class Shifted(RecordingProvider):
            """Same ramp, but the fetch now begins after the old claim's bar."""

            def get_bars(self, *args, **kwargs):
                return super().get_bars(*args, **kwargs)[81:]

        provider = Shifted(81 + 60)
        later = snapshot(provider=provider, now=at(100))
        assert later.series[0].timestamp > first_snap.series[-1].timestamp
        result = refresh(later, ledger)
        old = [i for i in result.items if i.timestamp == first_snap.series[-1].timestamp]
        assert old and all(i.status is OutcomeItemStatus.OUT_OF_WINDOW for i in old)
        assert result.out_of_window == 8 and result.outcomes_written == 0
        assert "outside the fetched history" in result.summary
        assert not outcomes_file(ledger, later).exists()

    def test_out_of_window_is_retried_when_the_window_covers_the_bar_again(self, ledger):
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)

        class Shifted(RecordingProvider):
            def get_bars(self, *args, **kwargs):
                return super().get_bars(*args, **kwargs)[81:]

        narrow = refresh(snapshot(provider=Shifted(141), now=at(100)), ledger)
        assert narrow.out_of_window == 8
        wide = refresh(snapshot(141, now=at(101)), ledger)
        old = [i for i in wide.items if i.timestamp == first_snap.series[-1].timestamp]
        assert {i.status for i in old} == {OutcomeItemStatus.WRITTEN}

    def test_an_ineligible_claim_older_than_the_window_is_still_ineligible(self, ledger):
        first_snap = snapshot(20, now=at(0))
        refresh(first_snap, ledger)

        class Shifted(RecordingProvider):
            def get_bars(self, *args, **kwargs):
                return super().get_bars(*args, **kwargs)[21:]

        result = refresh(snapshot(provider=Shifted(101), now=at(100)), ledger)
        old = [i for i in result.items if i.timestamp == first_snap.series[-1].timestamp]
        assert old and {i.status for i in old} == {OutcomeItemStatus.INELIGIBLE}

    def test_window_boundaries_are_exact(self, ledger):
        """Equal to the first bar: normal 12B. Inside but absent: hard error.
        After the tail: hard error. Before the first: out of window."""
        first_snap = snapshot(80, now=at(0))
        refresh(first_snap, ledger)

        class From79(RecordingProvider):
            def get_bars(self, *args, **kwargs):
                return super().get_bars(*args, **kwargs)[79:]

        edge = refresh(snapshot(provider=From79(82), now=at(2)), ledger)
        old = [i for i in edge.items if i.timestamp == first_snap.series[-1].timestamp]
        assert {(i.horizon_bars, i.status) for i in old} == {
            (1, OutcomeItemStatus.WRITTEN), (3, OutcomeItemStatus.PENDING)
        }
        with pytest.raises(OutcomeTrackingError):
            refresh(snapshot(82, now=at(3), provider=DroppingProvider(82, dropped_index=79)),
                    ledger)
        with pytest.raises(OutcomeTrackingError):
            # The old claim is now after the tail: the series shrank.
            refresh(snapshot(70, now=at(4)), ledger)


# -- specs ---------------------------------------------------------------------------------


class TestSpecValidation:
    @pytest.mark.parametrize("specs, message", [
        ((), "must not be empty"),
        ((H1, OutcomeSpec(horizon_bars=1)), "duplicate"),
        ((H1, OutcomeSpec(horizon_bars=5, required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)), "requires"),
        ((H1, "5"), "OutcomeSpec"),
        ("h1", "sequence"),
        (H1, "sequence"),
    ])
    def test_rejected_and_nothing_written(self, ledger, specs, message):
        snap = snapshot()
        with pytest.raises(OutcomeRefreshError, match=message):
            refresh(snap, ledger, specs)
        assert not artifacts_file(ledger, snap).exists()

    def test_caller_order_is_kept_in_the_items(self, ledger):
        result = refresh(snapshot(), ledger, (H3, H1))
        assert [i.horizon_bars for i in result.items[:2]] == [3, 1]

    def test_the_production_policy_is_accepted(self, ledger):
        result = refresh(snapshot(), ledger, OUTCOME_SPECS)
        assert result.pending == 4 * len(OUTCOME_SPECS)


# -- clocks --------------------------------------------------------------------------------


class TestClock:
    def test_a_naive_clock_is_refused(self, ledger):
        snap = snapshot()
        with pytest.raises(OutcomeRefreshError, match="timezone-aware"):
            refresh(snap, ledger, now=datetime(2026, 9, 5, 12, 0))
        assert not artifacts_file(ledger, snap).exists()

    def test_a_non_datetime_clock_is_refused(self, ledger):
        with pytest.raises(OutcomeRefreshError, match="datetime"):
            refresh(snapshot(), ledger, now="2026-09-05T12:00:00+00:00")

    def test_the_injected_clock_is_both_recorded_at_and_evaluated_at(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger, now=at(0) + timedelta(minutes=7))
        snap = snapshot(82, now=at(2))
        refresh(snap, ledger, now=at(2) + timedelta(minutes=9))
        part = partition_of(snap)
        stamps = {a.recorded_at for a in ledger.iter_artifacts(part)}
        assert stamps == {at(0) + timedelta(minutes=7), at(2) + timedelta(minutes=9)}
        assert {o.evaluated_at for o in ledger.iter_outcomes(part)} == {
            at(2) + timedelta(minutes=9)
        }


# -- the result model -----------------------------------------------------------------


class TestResultModel:
    def test_is_immutable(self, ledger):
        result = refresh(snapshot(), ledger)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.items = ()
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.items[0].status = OutcomeItemStatus.WRITTEN

    def test_counts_are_derived_and_coherent(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)
        result = refresh(snapshot(82, now=at(2)), ledger)
        assert (
            result.outcomes_already_present + result.outcomes_written + result.pending
            + result.ineligible + result.refused + result.out_of_window
        ) == len(result.items)
        assert result.artifacts_written + result.artifact_duplicates == result.artifacts_considered
        assert result.artifacts_tracked == 8
        assert len(result.items) == result.artifacts_tracked * len(SPECS)

    def test_items_are_ledger_order_crossed_with_spec_order(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)
        snap = snapshot(82, now=at(2))
        result = refresh(snap, ledger)
        keys = [a.artifact_key for a in ledger.iter_artifacts(partition_of(snap))]
        assert [i.artifact_key for i in result.items] == [k for k in keys for _ in SPECS]
        assert [i.horizon_bars for i in result.items] == [s.horizon_bars for s in SPECS] * 8

    def test_describes_exactly_its_snapshot(self, ledger):
        snap = snapshot()
        result = refresh(snap, ledger)
        assert result.describes(snap)
        assert not result.describes(snapshot(now=at(1)))
        assert not result.describes(dataclasses.replace(snap, symbol="MSFT"))
        assert not result.describes(None)

    def test_summary_is_operational_counts_only(self, ledger):
        refresh(snapshot(80, now=at(0)), ledger)
        result = refresh(snapshot(82, now=at(2)), ledger)
        assert result.summary == (
            "Outcome tracking: 4 claims registered (4 new), 4 new outcomes, 12 pending."
        )

    def test_summary_names_ineligible_and_refused_claims(self, ledger):
        insufficient = refresh(snapshot(20, now=at(0)), ledger)
        assert insufficient.summary == (
            "Outcome tracking: 4 claims registered (4 new), 0 new outcomes, 0 pending, "
            "8 not evaluable."
        )
        refresh(snapshot(80, now=at(0)), ledger)
        moved = refresh(snapshot(82, now=at(2), provider=OtherSourceProvider(82)), ledger)
        assert moved.summary.endswith("8 refused.")

    @pytest.mark.parametrize("word", ["rate", "accuracy", "mean", "average", "profit",
                                      "hit", "score", "performance", "return"])
    def test_no_performance_field(self, word):
        names = {f.name for f in dataclasses.fields(OutcomeRefreshResult)}
        names |= {n for n in dir(OutcomeRefreshResult) if not n.startswith("_")}
        names |= {f.name for f in dataclasses.fields(OutcomeItem)}
        assert not [n for n in names if word in n.lower()], word

    def test_a_conflict_cannot_be_a_registration_result(self):
        with pytest.raises(OutcomeRefreshError):
            ArtifactRegistration("a" * 64, "observation", "x", WriteStatus.CONFLICT)

    def test_an_item_carries_a_refusal_exactly_when_refused(self):
        common = dict(artifact_key="a" * 64, kind="observation", label="x",
                      timestamp=at(0), spec_fingerprint=H1.fingerprint, horizon_bars=1)
        with pytest.raises(OutcomeRefreshError):
            OutcomeItem(**common, status=OutcomeItemStatus.REFUSED)
        with pytest.raises(OutcomeRefreshError):
            OutcomeItem(**common, status=OutcomeItemStatus.PENDING,
                        refusal=RefusalReason.SOURCE_MISMATCH)


# -- purity and boundaries ------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _imports() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _calls() -> set[str]:
    called: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
                if isinstance(func.value, ast.Name):
                    called.add(f"{func.value.id}.{func.attr}")
    return called


def _attributes() -> set[str]:
    return {n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)}


class TestBoundaries:
    @pytest.mark.parametrize("module", [
        "json", "os", "hashlib", "io", "shutil", "tempfile", "sqlite3", "csv", "pickle",
        "time", "threading", "asyncio", "sched", "subprocess", "socket", "requests",
        "urllib", "httpx", "anthropic", "streamlit",
    ])
    def test_imports_no_io_clock_network_or_vendor_module(self, module):
        assert not any(n == module or n.startswith(module + ".") for n in _imports()), module

    @pytest.mark.parametrize("package", [
        "src.dashboard", "src.portfolio", "src.scanner", "src.news", "src.feeds",
        "src.reasoning", "src.data.provider", "src.data.providers", "src.data.storage",
        "src.outcomes.store", "src.outcomes.identity", "src.evaluation.metrics",
        "src.application.reasoning", "src.application.paper",
    ])
    def test_imports_no_forbidden_layer(self, package):
        assert not any(n == package or n.startswith(package + ".") for n in _imports()), package

    def test_consumes_outcomes_through_the_package_surface_only(self):
        assert "src.outcomes" in _imports()
        assert not [n for n in _imports() if n.startswith("src.outcomes.")]

    @pytest.mark.parametrize("name", [
        "open", "read_text", "write_text", "read_bytes", "write_bytes", "mkdir", "unlink",
        "touch", "exists", "iterdir", "glob", "rglob", "fsync", "sha256", "hexdigest",
        "now", "utcnow", "today", "time", "get_bars", "getenv", "environ", "measure_forward",
        "print", "sleep", "Thread", "Timer",
    ])
    def test_calls_no_io_clock_fetch_or_measurement(self, name):
        assert name not in _calls(), name

    def test_reads_no_price_field(self):
        assert not _attributes() & {"open", "high", "low", "close", "volume"}

    def test_does_no_arithmetic_at_all(self):
        """No return, no horizon, no index: nothing here computes a number.

        ``BitOr`` is the ``str | None`` union in annotations; the only ``Div``
        is ``Path / "data" / "outcomes"``, the default-root constant.
        """
        tree = _tree()
        operators = {type(n.op).__name__ for n in ast.walk(tree) if isinstance(n, ast.BinOp)}
        assert operators <= {"Add", "BitOr", "Div"}, operators
        divisions = [n for n in ast.walk(tree)
                     if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)]
        assert len(divisions) == 2
        assert {d.right.value for d in divisions} == {"data", "outcomes"}

    @pytest.mark.parametrize("text", [
        "artifacts.jsonl", "outcomes.jsonl", "schema_version", "SCHEMA_VERSION", "fsync",
        "json.", "hashlib", "artifacts_path", "outcomes_path", "partition_dir",
        "datetime.now", "utcnow",
    ])
    def test_knows_no_persistence_detail(self, text):
        assert text not in MODULE.read_text(encoding="utf-8"), text

    def test_the_only_filesystem_resolution_is_the_default_root_constant(self):
        """``Path(__file__).resolve()`` is the repository's root idiom; it may
        appear in the one assignment that names the default root and nowhere
        else, so no function body resolves a path at call time."""
        tree = _tree()
        resolving = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "resolve"
        ]
        assert len(resolving) == 1
        owners = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(n is resolving[0] for n in ast.walk(node))
        ]
        assert len(owners) == 1
        target = owners[0].target if isinstance(owners[0], ast.AnnAssign) else owners[0].targets[0]
        assert isinstance(target, ast.Name) and target.id == "DEFAULT_OUTCOMES_ROOT"
        assert isinstance(owners[0].value, ast.BinOp)     # module level, no def
        assert not any(
            isinstance(node, ast.FunctionDef) and any(n is resolving[0] for n in ast.walk(node))
            for node in ast.walk(tree)
        )

    def test_every_write_is_a_ledger_method(self):
        assert {"register_artifact", "append_outcome"} <= _calls()
        assert "iter_artifacts" in _calls() and "iter_outcomes" in _calls()

    def test_no_lock_thread_or_loop_primitive(self):
        text = MODULE.read_text(encoding="utf-8")
        for word in ("while True", "threading", "asyncio", "schedule", "cron", "poll"):
            assert word not in text, word
