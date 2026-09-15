"""Phase 12C: the append-only JSONL ledger.

Every write is idempotent by key and appends at most one line; every read
rebuilds its view from the bytes on disk and refuses bytes it cannot vouch
for. All storage here is under ``tmp_path``; nothing touches the repository.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from src.assessments.assessment import AssessmentReasonCode, AssessmentState
from src.data.models import Interval
from src.data.series import PriceBasis
from src.outcomes import (
    ArtifactMismatchError,
    JsonlOutcomeLedger,
    LedgerCorruption,
    LedgerError,
    LedgerPartition,
    OutcomeTrackingError,
    UnregisteredArtifactError,
    UnsupportedSchemaError,
    WriteStatus,
)
from src.outcomes.store import (
    ARTIFACTS_FILE,
    OUTCOMES_FILE,
    SCHEMA_VERSION,
    _artifact_row,
    _encode_line,
    _outcome_row,
)
from src.strategies.research import ReasonCode, ResearchState

from test_outcomes_models import T0, asmt_artifact, obs_artifact, record

PARTITION = LedgerPartition("AAPL", Interval.DAY_1, PriceBasis.RAW)


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "outcomes"


@pytest.fixture
def ledger(root) -> JsonlOutcomeLedger:
    return JsonlOutcomeLedger(root)


def lines(path: Path) -> list[bytes]:
    return path.read_bytes().split(b"\n")[:-1]


def append_raw(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(text.encode("utf-8"))


def artifact_line(artifact, **edits) -> str:
    row = _artifact_row(artifact)
    row.update(edits)
    return _encode_line(row).decode("ascii")


def outcome_line(outcome, **edits) -> str:
    row = _outcome_row(outcome)
    row.update(edits)
    return _encode_line(row).decode("ascii")


# -- construction and layout ------------------------------------------------------------


class TestConstruction:
    def test_root_is_injected_and_required(self):
        with pytest.raises(OutcomeTrackingError, match="root"):
            JsonlOutcomeLedger("")
        with pytest.raises(OutcomeTrackingError, match="root"):
            JsonlOutcomeLedger(None)  # type: ignore[arg-type]
        assert JsonlOutcomeLedger("some/where").root == Path("some/where")

    def test_layout_is_symbol_interval_basis_per_partition(self, ledger, root):
        assert ledger.partition_dir(PARTITION) == root / "AAPL" / "1d" / "raw"
        assert ledger.artifacts_path(PARTITION) == root / "AAPL" / "1d" / "raw" / ARTIFACTS_FILE
        assert ledger.outcomes_path(PARTITION) == root / "AAPL" / "1d" / "raw" / OUTCOMES_FILE
        adjusted = LedgerPartition("AAPL", Interval.DAY_1, PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        assert ledger.partition_dir(adjusted) == root / "AAPL" / "1d" / "split_and_dividend_adjusted"

    def test_methods_require_a_partition_object(self, ledger):
        with pytest.raises(OutcomeTrackingError, match="LedgerPartition"):
            ledger.iter_artifacts(("AAPL", "1d", "raw"))  # type: ignore[arg-type]
        with pytest.raises(OutcomeTrackingError, match="LedgerPartition"):
            ledger.partition_dir("AAPL/1d/raw")  # type: ignore[arg-type]


# -- artifact writes ----------------------------------------------------------------------


class TestRegisterArtifact:
    def test_new_key_is_written_as_exactly_one_line(self, ledger):
        artifact = obs_artifact()
        result = ledger.register_artifact(artifact)
        assert result.status is WriteStatus.WRITTEN
        assert result.key == artifact.artifact_key
        assert result.detail == ""
        path = ledger.artifacts_path(PARTITION)
        assert path.is_file()
        assert lines(path) == [_encode_line(_artifact_row(artifact))[:-1]]
        assert path.read_bytes().endswith(b"\n")

    def test_same_artifact_again_is_a_duplicate_and_writes_nothing(self, ledger):
        artifact = obs_artifact()
        ledger.register_artifact(artifact)
        before = ledger.artifacts_path(PARTITION).read_bytes()
        result = ledger.register_artifact(artifact)
        assert result.status is WriteStatus.DUPLICATE
        assert result.key == artifact.artifact_key
        assert ledger.artifacts_path(PARTITION).read_bytes() == before

    def test_same_key_different_claim_is_a_conflict_and_writes_nothing(self, ledger):
        ledger.register_artifact(obs_artifact())
        before = ledger.artifacts_path(PARTITION).read_bytes()
        result = ledger.register_artifact(
            obs_artifact(state=ResearchState.BEARISH, reason_codes=(ReasonCode.FAST_BELOW_SLOW,))
        )
        assert result.status is WriteStatus.CONFLICT
        assert result.key == obs_artifact().artifact_key
        assert "reason_codes" in result.detail and "state" in result.detail
        assert ledger.artifacts_path(PARTITION).read_bytes() == before
        assert ledger.get_artifact(PARTITION, result.key) == obs_artifact(), "the first is kept"

    @pytest.mark.parametrize("edit", [
        {"recorded_at": obs_artifact().recorded_at + timedelta(seconds=1)},
        {"data_cutoff": obs_artifact().data_cutoff + timedelta(days=1)},
        {"source": "other_provider"},
        {"observation_bar_fingerprint": "f" * 64},
    ], ids=["audit-timestamp", "cutoff", "source", "bar-fingerprint"])
    def test_same_key_different_audit_facts_is_a_conflict(self, ledger, edit):
        ledger.register_artifact(obs_artifact())
        result = ledger.register_artifact(obs_artifact(**edit))
        assert result.status is WriteStatus.CONFLICT
        assert list(edit)[0] in result.detail
        assert len(lines(ledger.artifacts_path(PARTITION))) == 1

    def test_different_producers_on_the_same_bar_are_different_lines(self, ledger):
        first = ledger.register_artifact(obs_artifact())
        second = ledger.register_artifact(obs_artifact(hypothesis_version=2))
        third = ledger.register_artifact(asmt_artifact())
        assert {r.status for r in (first, second, third)} == {WriteStatus.WRITTEN}
        assert len({first.key, second.key, third.key}) == 3
        assert len(lines(ledger.artifacts_path(PARTITION))) == 3

    def test_a_non_artifact_is_refused(self, ledger, root):
        with pytest.raises(OutcomeTrackingError, match="TrackedArtifact"):
            ledger.register_artifact(record())  # type: ignore[arg-type]
        assert not root.exists()

    def test_the_partition_is_derived_from_the_record(self, ledger, root):
        adjusted = obs_artifact(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        hourly = obs_artifact(interval=Interval.HOUR_1, symbol="MSFT")
        ledger.register_artifact(obs_artifact())
        ledger.register_artifact(adjusted)
        ledger.register_artifact(hourly)
        assert (root / "AAPL" / "1d" / "raw" / ARTIFACTS_FILE).is_file()
        assert (root / "AAPL" / "1d" / "split_and_dividend_adjusted" / ARTIFACTS_FILE).is_file()
        assert (root / "MSFT" / "1h" / "raw" / ARTIFACTS_FILE).is_file()
        assert list(ledger.iter_artifacts(PARTITION)) == [obs_artifact()]
        assert list(ledger.iter_artifacts(LedgerPartition.of_artifact(adjusted))) == [adjusted]


# -- outcome writes ----------------------------------------------------------------------


class TestAppendOutcome:
    def test_new_outcome_with_registered_artifact_is_written(self, ledger):
        outcome = record()
        ledger.register_artifact(outcome.artifact)
        result = ledger.append_outcome(outcome)
        assert result.status is WriteStatus.WRITTEN
        assert result.key == outcome.outcome_key
        assert lines(ledger.outcomes_path(PARTITION)) == [_encode_line(_outcome_row(outcome))[:-1]]

    def test_same_outcome_again_is_a_duplicate(self, ledger):
        outcome = record()
        ledger.register_artifact(outcome.artifact)
        ledger.append_outcome(outcome)
        before = ledger.outcomes_path(PARTITION).read_bytes()
        result = ledger.append_outcome(outcome)
        assert result.status is WriteStatus.DUPLICATE
        assert ledger.outcomes_path(PARTITION).read_bytes() == before

    def test_same_key_different_measurement_is_a_conflict(self, ledger):
        outcome = record()
        ledger.register_artifact(outcome.artifact)
        ledger.append_outcome(outcome)
        different = record(future_price=110.0, forward_return=110.0 / 100.0 - 1.0)
        assert different.outcome_key == outcome.outcome_key, "prices are not identity"
        result = ledger.append_outcome(different)
        assert result.status is WriteStatus.CONFLICT
        assert "future_price" in result.detail and "forward_return" in result.detail
        assert len(lines(ledger.outcomes_path(PARTITION))) == 1
        assert ledger.get_outcome(PARTITION, outcome.outcome_key) == outcome

    def test_a_different_clock_under_the_same_key_is_a_conflict(self, ledger):
        outcome = record()
        ledger.register_artifact(outcome.artifact)
        ledger.append_outcome(outcome)
        result = ledger.append_outcome(record(evaluated_at=outcome.evaluated_at + timedelta(hours=1)))
        assert result.status is WriteStatus.CONFLICT
        assert result.detail.endswith("evaluated_at")

    def test_outcome_without_registered_artifact_is_refused_and_nothing_written(self, ledger, root):
        outcome = record()
        with pytest.raises(UnregisteredArtifactError) as info:
            ledger.append_outcome(outcome)
        assert info.value.artifact_key == outcome.artifact_key
        assert info.value.outcome_key == outcome.outcome_key
        assert not ledger.outcomes_path(PARTITION).exists()
        assert not root.exists(), "a refused write creates nothing"

    def test_outcome_embedding_an_artifact_that_differs_from_the_registered_one_is_refused(
        self, ledger
    ):
        ledger.register_artifact(obs_artifact())
        different_claim = obs_artifact(state=ResearchState.NEUTRAL,
                                       reason_codes=(ReasonCode.WARMUP_INCOMPLETE,))
        outcome = record(artifact=different_claim)
        assert outcome.artifact_key == obs_artifact().artifact_key
        with pytest.raises(ArtifactMismatchError) as info:
            ledger.append_outcome(outcome)
        assert info.value.artifact_key == outcome.artifact_key
        assert "state" in info.value.detail
        assert not ledger.outcomes_path(PARTITION).exists()

    def test_only_outcome_records_are_accepted(self, ledger):
        ledger.register_artifact(obs_artifact())
        for not_an_outcome in (obs_artifact(), {"status": "pending"}, None):
            with pytest.raises(OutcomeTrackingError, match="OutcomeRecord"):
                ledger.append_outcome(not_an_outcome)  # type: ignore[arg-type]
        assert not ledger.outcomes_path(PARTITION).exists()

    def test_outcome_lands_in_its_artifact_partition(self, ledger, root):
        artifact = asmt_artifact(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
                                 state=AssessmentState.BEARISH,
                                 reason_codes=(AssessmentReasonCode.UNANIMOUS_BEARISH,))
        outcome = record(artifact=artifact)
        ledger.register_artifact(artifact)
        ledger.append_outcome(outcome)
        adjusted = LedgerPartition.of_outcome(outcome)
        assert (root / "AAPL" / "1d" / "split_and_dividend_adjusted" / OUTCOMES_FILE).is_file()
        assert list(ledger.iter_outcomes(adjusted)) == [outcome]
        assert list(ledger.iter_outcomes(PARTITION)) == []

    def test_appending_an_outcome_never_registers_its_artifact(self, ledger):
        """Sequencing is explicit and belongs to the caller."""
        outcome = record()
        with pytest.raises(UnregisteredArtifactError):
            ledger.append_outcome(outcome)
        assert not ledger.contains_artifact(PARTITION, outcome.artifact_key)


# -- reads ---------------------------------------------------------------------------------


class TestReads:
    def test_reads_of_an_absent_root_are_empty_and_create_nothing(self, ledger, root):
        key = obs_artifact().artifact_key
        assert list(ledger.iter_artifacts(PARTITION)) == []
        assert list(ledger.iter_outcomes(PARTITION)) == []
        assert ledger.get_artifact(PARTITION, key) is None
        assert ledger.get_outcome(PARTITION, key) is None
        assert ledger.contains_artifact(PARTITION, key) is False
        assert ledger.contains_outcome(PARTITION, key) is False
        assert not root.exists()

    def test_reads_of_an_existing_partition_dir_without_files_create_nothing(self, ledger, root):
        ledger.partition_dir(PARTITION).mkdir(parents=True)
        before = sorted(p.relative_to(root) for p in root.rglob("*"))
        assert list(ledger.iter_artifacts(PARTITION)) == []
        assert list(ledger.iter_outcomes(PARTITION)) == []
        assert ledger.get_artifact(PARTITION, "0" * 64) is None
        assert not ledger.contains_outcome(PARTITION, "0" * 64)
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before

    def test_reads_of_an_absent_partition_under_an_existing_root_create_nothing(self, ledger, root):
        ledger.register_artifact(obs_artifact(symbol="MSFT"))
        other = LedgerPartition("TSLA", Interval.WEEK_1, PriceBasis.RAW)
        assert list(ledger.iter_artifacts(other)) == []
        assert ledger.get_outcome(other, "0" * 64) is None
        assert sorted(p.name for p in root.iterdir()) == ["MSFT"]

    def test_get_and_contains_by_key(self, ledger):
        artifact, outcome = obs_artifact(), record()
        ledger.register_artifact(artifact)
        ledger.append_outcome(outcome)
        assert ledger.get_artifact(PARTITION, artifact.artifact_key) == artifact
        assert ledger.get_outcome(PARTITION, outcome.outcome_key) == outcome
        assert ledger.contains_artifact(PARTITION, artifact.artifact_key)
        assert ledger.contains_outcome(PARTITION, outcome.outcome_key)
        assert not ledger.contains_artifact(PARTITION, outcome.outcome_key)
        assert not ledger.contains_outcome(PARTITION, artifact.artifact_key)
        assert ledger.get_artifact(PARTITION, "0" * 64) is None

    def test_a_malformed_key_is_a_caller_error(self, ledger):
        with pytest.raises(OutcomeTrackingError, match="key"):
            ledger.get_artifact(PARTITION, "not-a-key")
        with pytest.raises(OutcomeTrackingError, match="key"):
            ledger.contains_outcome(PARTITION, "A" * 64)

    def test_iteration_is_append_order(self, ledger):
        artifacts = [obs_artifact(hypothesis_version=v) for v in (3, 1, 2)]
        for artifact in artifacts:
            ledger.register_artifact(artifact)
        assert list(ledger.iter_artifacts(PARTITION)) == artifacts
        outcomes = [record(artifact=a) for a in artifacts]
        for outcome in reversed(outcomes):
            ledger.append_outcome(outcome)
        assert list(ledger.iter_outcomes(PARTITION)) == list(reversed(outcomes))

    def test_reads_return_immutable_records(self, ledger):
        ledger.register_artifact(obs_artifact())
        stored = next(ledger.iter_artifacts(PARTITION))
        with pytest.raises(Exception):
            stored.state = ResearchState.BEARISH  # type: ignore[misc]


# -- durability -----------------------------------------------------------------------------


class TestDurability:
    def test_a_fresh_ledger_instance_reads_back_exactly_what_was_written(self, root):
        artifact, outcome = asmt_artifact(), record(artifact=asmt_artifact())
        writer = JsonlOutcomeLedger(root)
        writer.register_artifact(artifact)
        writer.append_outcome(outcome)
        del writer

        reader = JsonlOutcomeLedger(root)
        assert list(reader.iter_artifacts(PARTITION)) == [artifact]
        assert list(reader.iter_outcomes(PARTITION)) == [outcome]
        read_back = reader.get_outcome(PARTITION, outcome.outcome_key)
        assert read_back == outcome
        assert read_back.outcome_key == outcome.outcome_key
        assert read_back.forward_return == outcome.forward_return
        assert reader.register_artifact(artifact).status is WriteStatus.DUPLICATE
        assert reader.append_outcome(outcome).status is WriteStatus.DUPLICATE

    def test_each_write_is_one_json_object_terminated_by_newline(self, ledger):
        ledger.register_artifact(obs_artifact())
        ledger.register_artifact(obs_artifact(hypothesis_version=2))
        raw = ledger.artifacts_path(PARTITION).read_bytes()
        assert raw.endswith(b"\n") and raw.count(b"\n") == 2
        for line in lines(ledger.artifacts_path(PARTITION)):
            row = json.loads(line)
            assert row["schema_version"] == SCHEMA_VERSION
            assert row["record_type"] == "artifact"

    def test_an_append_is_flushed_and_fsynced(self, ledger, monkeypatch):
        synced: list[int] = []
        real_fsync = os.fsync
        monkeypatch.setattr("src.outcomes.store.os.fsync",
                            lambda fd: (synced.append(fd), real_fsync(fd))[1])
        ledger.register_artifact(obs_artifact())
        assert len(synced) == 1
        ledger.append_outcome(record())
        assert len(synced) == 2
        ledger.register_artifact(obs_artifact())
        assert len(synced) == 2, "a duplicate touches the disk not at all"

    def test_an_encoding_failure_appends_nothing(self, ledger, monkeypatch):
        ledger.register_artifact(obs_artifact())
        before = ledger.artifacts_path(PARTITION).read_bytes()

        def broken(row):
            raise ValueError("cannot encode")

        monkeypatch.setattr("src.outcomes.store._encode_line", broken)
        with pytest.raises(ValueError, match="cannot encode"):
            ledger.register_artifact(obs_artifact(hypothesis_version=2))
        assert ledger.artifacts_path(PARTITION).read_bytes() == before

    def test_an_fsync_failure_propagates_and_leaves_the_line_state_to_the_next_read(
        self, ledger, monkeypatch
    ):
        """After a failed fsync the bytes may or may not be on disk; the
        store claims nothing either way. Here the OS accepted the write and
        only the sync failed, so the line *is* present and the next read
        sees it -- which is exactly why the caller must not assume "not
        written" from the exception."""
        def failing_fsync(fd):
            raise OSError("disk gone")

        monkeypatch.setattr("src.outcomes.store.os.fsync", failing_fsync)
        with pytest.raises(OSError, match="disk gone"):
            ledger.register_artifact(obs_artifact())
        monkeypatch.undo()
        assert ledger.get_artifact(PARTITION, obs_artifact().artifact_key) == obs_artifact()
        assert ledger.register_artifact(obs_artifact()).status is WriteStatus.DUPLICATE

    def test_the_write_is_one_call_to_a_blocking_buffered_writer(self, ledger, monkeypatch):
        """One ``write`` of the whole line. A blocking ``BufferedWriter``
        either takes every byte or raises; it never returns a short count,
        so no partial-write loop is needed or pretended."""
        calls: list[int] = []
        real_open = Path.open

        class Counting:
            def __init__(self, handle):
                self._handle = handle

            def write(self, data):
                calls.append(len(data))
                return self._handle.write(data)

            def __getattr__(self, name):
                return getattr(self._handle, name)

            def __enter__(self):
                self._handle.__enter__()
                return self

            def __exit__(self, *exc):
                return self._handle.__exit__(*exc)

        monkeypatch.setattr(Path, "open", lambda self, *a, **k: Counting(real_open(self, *a, **k)))
        ledger.register_artifact(obs_artifact())
        expected = _encode_line(_artifact_row(obs_artifact()))
        assert calls == [len(expected)]
        assert ledger.artifacts_path(PARTITION).read_bytes() == expected

    def test_files_are_written_in_the_line_contract_bytes(self, ledger):
        ledger.register_artifact(obs_artifact())
        raw = ledger.artifacts_path(PARTITION).read_bytes()
        assert raw == _encode_line(_artifact_row(obs_artifact()))
        raw.decode("ascii")


# -- corruption ----------------------------------------------------------------------------


class TestCorruption:
    def corrupt_read(self, ledger, partition=PARTITION, *, outcomes=False):
        with pytest.raises(LedgerCorruption) as info:
            list(ledger.iter_outcomes(partition) if outcomes else ledger.iter_artifacts(partition))
        return info.value

    def test_truncated_final_line_is_a_torn_append(self, ledger):
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION), '{"schema_version": 1, "record_ty')
        error = self.corrupt_read(ledger)
        assert error.line_number == 2
        assert error.byte_offset == len(_encode_line(_artifact_row(obs_artifact())))
        assert "not newline-terminated" in error.reason
        assert error.path == str(ledger.artifacts_path(PARTITION))

    def test_a_complete_json_line_without_its_newline_is_still_torn(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact()).rstrip("\n"))
        error = self.corrupt_read(ledger)
        assert "not newline-terminated" in error.reason

    def test_invalid_json_names_file_line_and_offset(self, ledger):
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION), "not json at all\n")
        error = self.corrupt_read(ledger)
        assert (error.line_number, error.byte_offset) == (
            2, len(_encode_line(_artifact_row(obs_artifact()))))
        assert error.reason.startswith("invalid JSON")
        assert str(error).startswith(f"{ledger.artifacts_path(PARTITION)}:2 (byte ")

    def test_interior_damage_is_found_at_its_line(self, ledger):
        path = ledger.artifacts_path(PARTITION)
        append_raw(path, "{broken\n")
        ledger_ok = obs_artifact(hypothesis_version=2)
        append_raw(path, artifact_line(ledger_ok))
        error = self.corrupt_read(ledger)
        assert (error.line_number, error.byte_offset) == (1, 0)

    def test_blank_line_is_corruption(self, ledger):
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION), "\n")
        error = self.corrupt_read(ledger)
        assert error.line_number == 2 and "blank line" in error.reason
        append_raw(ledger.artifacts_path(PARTITION), "   \n")

    def test_non_object_json_is_corruption(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), "[1, 2]\n")
        assert "not a JSON object" in self.corrupt_read(ledger).reason

    def test_invalid_utf8_is_corruption(self, ledger):
        path = ledger.artifacts_path(PARTITION)
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{"a": "\xff"}\n')
        assert "invalid UTF-8" in self.corrupt_read(ledger).reason

    def test_wrong_record_type_is_corruption(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), outcome_line(record()))
        error = self.corrupt_read(ledger)
        assert "record_type is 'outcome', expected 'artifact'" in error.reason
        append_raw(ledger.outcomes_path(PARTITION), artifact_line(obs_artifact()))
        error = self.corrupt_read(ledger, outcomes=True)
        assert "record_type is 'artifact', expected 'outcome'" in error.reason

    def test_missing_schema_version_is_corruption(self, ledger):
        row = _artifact_row(obs_artifact())
        del row["schema_version"]
        append_raw(ledger.artifacts_path(PARTITION), _encode_line(row).decode())
        assert "missing field 'schema_version'" in self.corrupt_read(ledger).reason

    @pytest.mark.parametrize("version", [SCHEMA_VERSION + 1, 0, "1", True, None])
    def test_unsupported_schema_version_is_refused(self, ledger, version):
        append_raw(ledger.artifacts_path(PARTITION),
                   artifact_line(obs_artifact(), schema_version=version))
        with pytest.raises(UnsupportedSchemaError) as info:
            list(ledger.iter_artifacts(PARTITION))
        assert isinstance(info.value, LedgerCorruption)
        assert info.value.line_number == 1
        assert f"schema_version {version!r}" in info.value.reason
        assert "refusing" in info.value.reason
        # ...and a write on top of it is refused too.
        with pytest.raises(UnsupportedSchemaError):
            ledger.register_artifact(obs_artifact(hypothesis_version=2))
        assert len(lines(ledger.artifacts_path(PARTITION))) == 1

    @pytest.mark.parametrize("field", [
        "artifact_key", "kind", "symbol", "interval", "basis", "timestamp", "state",
        "reason_codes", "source", "data_cutoff", "recorded_at", "observation_bar_fingerprint",
        "origin", "hypothesis_id", "hypothesis_version", "hypothesis_fingerprint",
    ])
    def test_missing_artifact_field_is_corruption(self, ledger, field):
        row = _artifact_row(obs_artifact())
        del row[field]
        append_raw(ledger.artifacts_path(PARTITION), _encode_line(row).decode())
        assert f"missing field {field!r}" in self.corrupt_read(ledger).reason

    @pytest.mark.parametrize("field", [
        "outcome_key", "artifact_key", "artifact", "spec_fingerprint", "horizon_bars",
        "evaluation_version", "evaluated_at", "consumed_bars_fingerprint",
        "reference_timestamp", "reference_price", "future_timestamp", "future_price",
        "forward_return",
    ])
    def test_missing_outcome_field_is_corruption(self, ledger, field):
        row = _outcome_row(record())
        del row[field]
        append_raw(ledger.outcomes_path(PARTITION), _encode_line(row).decode())
        assert f"missing field {field!r}" in self.corrupt_read(ledger, outcomes=True).reason

    def test_missing_field_inside_the_embedded_artifact_is_corruption(self, ledger):
        row = _outcome_row(record())
        del row["artifact"]["state"]
        append_raw(ledger.outcomes_path(PARTITION), _encode_line(row).decode())
        assert "missing field 'state'" in self.corrupt_read(ledger, outcomes=True).reason

    @pytest.mark.parametrize("edit,fragment", [
        ({"state": "sideways"}, "unknown state"),
        ({"state": "conflicted"}, "unknown state"),         # an assessment word on an observation
        ({"reason_codes": ["unanimous_bullish"]}, "reason_codes"),
        ({"reason_codes": []}, "must not be empty"),
        ({"reason_codes": "fast_above_slow"}, "must be list"),
        ({"kind": "replay"}, "unknown artifact kind"),
        ({"origin": "backfill"}, "unknown origin"),
        ({"interval": "1day"}, "interval"),
        ({"basis": "adjusted"}, "price basis"),
        ({"hypothesis_version": 0}, "hypothesis_version"),
        ({"hypothesis_version": "1"}, "must be int"),
        ({"hypothesis_version": True}, "must be int"),
    ])
    def test_invalid_enum_or_value_is_corruption(self, ledger, edit, fragment):
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact(), **edit))
        assert fragment in self.corrupt_read(ledger).reason

    @pytest.mark.parametrize("value,fragment", [
        ("2024-01-05", "naive"),
        ("yesterday", "not an ISO-8601 timestamp"),
        ("2024-13-05T00:00:00+00:00", "not an ISO-8601 timestamp"),
        ("2024-01-05T00:00:00", "naive"),
        (1704412800, "must be str, got int"),
        (None, "must be str, got NoneType"),
    ])
    def test_invalid_or_naive_timestamp_is_corruption(self, ledger, value, fragment):
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact(), timestamp=value))
        assert fragment in self.corrupt_read(ledger).reason

    def test_a_non_utc_offset_on_disk_is_not_canonical(self, ledger):
        """Same instant, different bytes: the writer never produces it, so a
        line carrying it was not written by this writer as it stands."""
        append_raw(ledger.artifacts_path(PARTITION),
                   artifact_line(obs_artifact(), timestamp="2024-01-05T05:00:00+05:00"))
        error = self.corrupt_read(ledger)
        assert "not the canonical encoding" in error.reason and "timestamp" in error.reason

    @pytest.mark.parametrize("edit,fragment", [
        ({"reference_price": "100.0"}, "must be float, got str"),
        ({"reference_price": None}, "must be float, got NoneType"),
        ({"future_price": True}, "must be float, got bool"),
        ({"reference_price": 100}, "must be float, got int"),
        ({"forward_return": 0}, "must be float, got int"),
        ({"horizon_bars": 5.0}, "must be int, got float"),
        ({"horizon_bars": True}, "must be int, got bool"),
        ({"horizon_bars": -1}, "horizon_bars"),
        ({"evaluation_version": 1.0}, "must be int, got float"),
        ({"evaluation_version": True}, "must be int, got bool"),
        ({"reference_price": 0.0}, "finite positive"),
        ({"forward_return": 0.25}, "does not agree with its own prices"),
        ({"horizon_bars": "5"}, "must be int"),
        ({"evaluation_version": 2}, "not supported"),
    ])
    def test_invalid_number_is_corruption(self, ledger, edit, fragment):
        append_raw(ledger.outcomes_path(PARTITION), outcome_line(record(), **edit))
        assert fragment in self.corrupt_read(ledger, outcomes=True).reason

    @pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
    @pytest.mark.parametrize("field,spelling", [
        ("forward_return", '"forward_return":0.050000000000000044'),
        ("reference_price", '"reference_price":100.0'),
        ("horizon_bars", '"horizon_bars":5'),
        ("schema_version", '"schema_version":1'),
    ])
    def test_non_finite_json_constant_is_refused_at_the_parser(self, ledger, constant, field, spelling):
        """``json.loads`` accepts ``NaN``/``Infinity`` by default; this reader
        does not, anywhere, before any domain rule is consulted."""
        text = outcome_line(record()).replace(spelling, f'"{field}":{constant}')
        assert constant in text
        append_raw(ledger.outcomes_path(PARTITION), text)
        error = self.corrupt_read(ledger, outcomes=True)
        assert error.reason == f"non-finite JSON constant {constant!r}"

    @pytest.mark.parametrize("field,spelling,twin", [
        ("state", '"state":"bullish"', '"state":"bearish","state":"bullish"'),
        ("schema_version", '"schema_version":1', '"schema_version":999,"schema_version":1'),
        ("artifact_key", '"artifact_key":"' + "d", '"artifact_key":"' + "0" * 64 + '","artifact_key":"d'),
    ])
    def test_duplicate_json_object_key_is_corruption(self, ledger, field, spelling, twin):
        """``json.loads`` keeps the last of two equal keys silently. Two
        spellings of one field on one line is ambiguity, not a record --
        even when the surviving value would have been canonical."""
        text = artifact_line(obs_artifact()).replace(spelling, twin, 1)
        assert text.count(f'"{field}":') == 2
        append_raw(ledger.artifacts_path(PARTITION), text)
        assert self.corrupt_read(ledger).reason == f"duplicate JSON key {field!r}"

    def test_duplicate_json_key_inside_the_embedded_artifact_is_corruption(self, ledger):
        text = outcome_line(record()).replace('"source":"yfinance"',
                                              '"source":"other","source":"yfinance"', 1)
        append_raw(ledger.outcomes_path(PARTITION), text)
        assert self.corrupt_read(ledger, outcomes=True).reason == "duplicate JSON key 'source'"

    @pytest.mark.parametrize("version", [1.0, 1.5, [1], {"v": 1}])
    def test_schema_version_must_be_the_integer_one(self, ledger, version):
        """``1.0 == 1`` and ``True == 1`` in Python; neither is what the
        writer stores, and neither is accepted."""
        append_raw(ledger.artifacts_path(PARTITION),
                   artifact_line(obs_artifact(), schema_version=version))
        with pytest.raises(UnsupportedSchemaError) as info:
            list(ledger.iter_artifacts(PARTITION))
        assert f"schema_version {version!r}" in info.value.reason

    def test_byte_offset_counts_bytes_not_characters(self, ledger):
        """A hand-written line with multi-byte UTF-8 before the damage must
        not shift the reported offset of the damaged line."""
        path = ledger.artifacts_path(PARTITION)
        unicode_line = '{"schema_version":1,"record_type":"artifact","note":"\u00e9 and é and 日本"}\n'
        unicode_line = unicode_line.replace("\\n", "\n")
        first = artifact_line(obs_artifact())
        append_raw(path, first)
        append_raw(path, unicode_line)
        error = self.corrupt_read(ledger)
        assert (error.line_number, error.byte_offset) == (2, len(first.encode("ascii")))
        assert len(unicode_line.encode("utf-8")) > len(unicode_line), "the probe is multi-byte"
        # And a third line after a multi-byte second line, in a file whose
        # second line is *valid*, is located by bytes too.
        path.unlink()
        second = artifact_line(obs_artifact(source="yfinancé", hypothesis_version=2))
        append_raw(path, first)
        append_raw(path, second)
        append_raw(path, "broken\n")
        error = self.corrupt_read(ledger)
        assert (error.line_number, error.byte_offset) == (
            3, len(first.encode("ascii")) + len(second.encode("ascii")))

    def test_stored_artifact_key_mismatch_is_corruption(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact(), artifact_key="0" * 64))
        error = self.corrupt_read(ledger)
        assert "stored artifact_key" in error.reason and "does not match" in error.reason

    def test_edited_identity_field_under_the_old_key_is_corruption(self, ledger):
        """The key is recomputed from the reconstructed fields, so editing a
        field that is *in* the key without re-keying is caught."""
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact(), symbol="MSFT"))
        assert "stored artifact_key" in self.corrupt_read(ledger).reason

    def test_stored_outcome_key_mismatch_is_corruption(self, ledger):
        append_raw(ledger.outcomes_path(PARTITION), outcome_line(record(), outcome_key="0" * 64))
        error = self.corrupt_read(ledger, outcomes=True)
        assert "stored outcome_key" in error.reason

    def test_outcome_top_level_artifact_key_disagreeing_with_embedded_is_corruption(self, ledger):
        append_raw(ledger.outcomes_path(PARTITION), outcome_line(record(), artifact_key="0" * 64))
        error = self.corrupt_read(ledger, outcomes=True)
        assert "stored artifact_key" in error.reason and "embedded" in error.reason

    def test_wrong_embedded_artifact_is_corruption(self, ledger):
        row = _outcome_row(record())
        row["artifact"] = _artifact_row(obs_artifact(hypothesis_version=2))
        for envelope in ("schema_version", "record_type"):
            del row["artifact"][envelope]
        append_raw(ledger.outcomes_path(PARTITION), _encode_line(row).decode())
        error = self.corrupt_read(ledger, outcomes=True)
        assert "stored artifact_key" in error.reason

    def test_unknown_extra_field_is_corruption(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact(), note="edited"))
        error = self.corrupt_read(ledger)
        assert "not the canonical encoding" in error.reason and "note" in error.reason

    def test_embedded_artifact_carrying_an_envelope_is_corruption(self, ledger):
        row = _outcome_row(record())
        row["artifact"]["schema_version"] = 1
        append_raw(ledger.outcomes_path(PARTITION), _encode_line(row).decode())
        assert "not the canonical encoding" in self.corrupt_read(ledger, outcomes=True).reason

    def test_duplicate_identical_physical_lines_are_corruption(self, ledger):
        """The idempotent writer never repeats a line; a repeated one means a
        manual edit or a broken writer, and is refused rather than tolerated."""
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(obs_artifact()))
        error = self.corrupt_read(ledger)
        assert error.line_number == 2
        assert "already appears on line 1" in error.reason
        assert "identical repeated line" in error.reason

        ledger2 = JsonlOutcomeLedger(ledger.root)
        with pytest.raises(LedgerCorruption):
            ledger2.register_artifact(obs_artifact(hypothesis_version=2))
        assert len(lines(ledger.artifacts_path(PARTITION))) == 2, "nothing appended on corruption"

    def test_conflicting_lines_under_one_key_are_corruption_not_first_or_last(self, ledger):
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION),
                   artifact_line(obs_artifact(state=ResearchState.BEARISH,
                                              reason_codes=(ReasonCode.FAST_BELOW_SLOW,))))
        error = self.corrupt_read(ledger)
        assert error.line_number == 2
        assert "a different record under the same key" in error.reason
        with pytest.raises(LedgerCorruption):
            ledger.get_artifact(PARTITION, obs_artifact().artifact_key)

    def test_duplicate_outcome_lines_are_corruption(self, ledger):
        ledger.register_artifact(obs_artifact())
        ledger.append_outcome(record())
        append_raw(ledger.outcomes_path(PARTITION), outcome_line(record()))
        error = self.corrupt_read(ledger, outcomes=True)
        assert "already appears on line 1" in error.reason

    def test_a_record_from_another_partition_in_this_file_is_corruption(self, ledger):
        """The directory is routing, the line is authority, and they must agree."""
        foreign = obs_artifact(symbol="MSFT")
        append_raw(ledger.artifacts_path(PARTITION), artifact_line(foreign))
        error = self.corrupt_read(ledger)
        assert "belongs to MSFT/1d/raw, not to this partition AAPL/1d/raw" in error.reason
        adjusted = record(artifact=obs_artifact(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        append_raw(ledger.outcomes_path(PARTITION), outcome_line(adjusted))
        error = self.corrupt_read(ledger, outcomes=True)
        assert "split_and_dividend_adjusted" in error.reason

    def test_corruption_is_found_before_any_write_and_the_file_is_untouched(self, ledger):
        path = ledger.artifacts_path(PARTITION)
        append_raw(path, "garbage\n")
        before = path.read_bytes()
        with pytest.raises(LedgerCorruption):
            ledger.register_artifact(obs_artifact())
        with pytest.raises(LedgerCorruption):
            ledger.append_outcome(record())
        assert path.read_bytes() == before
        assert not ledger.outcomes_path(PARTITION).exists()

    def test_corruption_in_the_artifact_file_blocks_outcome_writes(self, ledger):
        ledger.register_artifact(obs_artifact())
        append_raw(ledger.artifacts_path(PARTITION), "{\n")
        with pytest.raises(LedgerCorruption) as info:
            ledger.append_outcome(record())
        assert info.value.path == str(ledger.artifacts_path(PARTITION))

    def test_an_empty_file_is_an_empty_ledger(self, ledger):
        path = ledger.artifacts_path(PARTITION)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")
        assert list(ledger.iter_artifacts(PARTITION)) == []

    def test_corruption_message_carries_no_traceback_internals(self, ledger):
        append_raw(ledger.artifacts_path(PARTITION), "{\n")
        error = self.corrupt_read(ledger)
        assert "Traceback" not in str(error) and "File \"" not in str(error)
        assert error.__cause__ is None


# -- path safety -------------------------------------------------------------------------------


class TestFilesystemEdges:
    """A file where a directory belongs, or a directory where a file belongs,
    is reported -- never read as an empty ledger."""

    def test_root_that_is_a_file_is_refused_on_read_and_write(self, tmp_path):
        root = tmp_path / "rootfile"
        root.write_text("x")
        ledger = JsonlOutcomeLedger(root)
        with pytest.raises(LedgerError, match="not a directory"):
            list(ledger.iter_artifacts(PARTITION))
        with pytest.raises(LedgerError, match="not a directory"):
            ledger.contains_artifact(PARTITION, "0" * 64)
        with pytest.raises(LedgerError, match="not a directory"):
            ledger.register_artifact(obs_artifact())
        assert root.read_text() == "x"

    def test_partition_component_that_is_a_file_is_refused(self, ledger, root):
        root.mkdir()
        (root / "AAPL").write_text("x")
        with pytest.raises(LedgerError, match=r"AAPL exists and is not a directory"):
            list(ledger.iter_outcomes(PARTITION))
        with pytest.raises(LedgerError, match="not a directory"):
            ledger.register_artifact(obs_artifact())
        assert (root / "AAPL").read_text() == "x"

    def test_ledger_file_path_that_is_a_directory_is_refused(self, ledger):
        ledger.artifacts_path(PARTITION).mkdir(parents=True)
        with pytest.raises(LedgerError, match="not a regular file"):
            list(ledger.iter_artifacts(PARTITION))
        with pytest.raises(LedgerError, match="not a regular file"):
            ledger.register_artifact(obs_artifact())
        with pytest.raises(LedgerError, match="not a regular file"):
            ledger.append_outcome(record())

    def test_a_relative_root_is_resolved_against_the_process_cwd_only_at_use(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ledger = JsonlOutcomeLedger("ledger")
        ledger.register_artifact(obs_artifact())
        assert (tmp_path / "ledger" / "AAPL" / "1d" / "raw" / ARTIFACTS_FILE).is_file()

    def test_no_sidecar_index_or_temp_files_are_ever_created(self, ledger, root):
        ledger.register_artifact(obs_artifact())
        ledger.append_outcome(record())
        list(ledger.iter_artifacts(PARTITION))
        assert sorted(p.name for p in root.rglob("*") if p.is_file()) == [ARTIFACTS_FILE, OUTCOMES_FILE]


class TestPathSafety:
    @pytest.mark.parametrize("symbol", [
        "../etc", "..", ".", "a/b", "a\\b", "/abs", "AAPL\0", "AAPL..", "..AAPL",
        "AAP\nL", " AAPL", "AAPL ", "\tAAPL", "AAPL\x7f", "C:\\AAPL", "~/AAPL",
        "AAPL/../MSFT", "%2e%2e/x/../y",
    ], ids=repr)
    def test_unsafe_symbol_is_refused_not_rewritten(self, ledger, root, symbol):
        partition = LedgerPartition(symbol, Interval.DAY_1, PriceBasis.RAW)
        with pytest.raises(OutcomeTrackingError, match="unsafe path component"):
            ledger.partition_dir(partition)
        with pytest.raises(OutcomeTrackingError, match="unsafe path component"):
            list(ledger.iter_artifacts(partition))
        assert not root.exists()

    def test_unsafe_symbol_on_a_record_refuses_the_write(self, ledger, root):
        artifact = obs_artifact(symbol="../escape")
        with pytest.raises(OutcomeTrackingError, match="unsafe path component"):
            ledger.register_artifact(artifact)
        assert not root.exists()
        assert not (root.parent / "escape").exists()

    def test_the_symbol_reaches_the_path_verbatim(self, ledger, root):
        for symbol in ("BRK-B", "BRK.B", "^GSPC", "EURUSD=X", "BTC-USD", "C:", "~", "%2e", "a:b",
                       "X" * 200):
            partition = LedgerPartition(symbol, Interval.DAY_1, PriceBasis.RAW)
            assert ledger.partition_dir(partition) == root / symbol / "1d" / "raw"

    def test_every_partition_dir_stays_under_root(self, ledger, root):
        for interval in Interval:
            for basis in PriceBasis:
                partition = LedgerPartition("AAPL", interval, basis)
                directory = ledger.partition_dir(partition).resolve()
                assert root.resolve() in directory.parents


# -- the identity firewall inside the store -------------------------------------------------


class TestStoreReusesDomainKeys:
    def test_store_never_hashes(self):
        import ast
        import src.outcomes.store as store

        tree = ast.parse(Path(store.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.module}
        assert "hashlib" not in imported
        called = {
            (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None))
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        assert not called & {"digest", "sha256", "hash", "observation_artifact_key",
                             "assessment_artifact_key", "outcome_key", "canonical_bytes"}
        text = Path(store.__file__).read_text(encoding="utf-8")
        assert "scheme_version" not in text and '"scheme"' not in text

    def test_stored_keys_are_the_domain_keys(self, ledger):
        artifact, outcome = obs_artifact(), record()
        ledger.register_artifact(artifact)
        ledger.append_outcome(outcome)
        artifact_row = json.loads(lines(ledger.artifacts_path(PARTITION))[0])
        outcome_row = json.loads(lines(ledger.outcomes_path(PARTITION))[0])
        assert artifact_row["artifact_key"] == artifact.artifact_key
        assert outcome_row["outcome_key"] == outcome.outcome_key
        assert outcome_row["artifact_key"] == outcome.artifact_key
        assert outcome_row["artifact"] == {
            k: v for k, v in artifact_row.items() if k not in ("schema_version", "record_type")
        }
