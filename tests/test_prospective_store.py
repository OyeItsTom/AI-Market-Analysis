"""Prospective Collection v1: records, the store's files, the lock and the repository probe."""

from __future__ import annotations

import json
import subprocess
from datetime import date

import pytest

from src.prospective import (
    COLLECTION_V1,
    ActivationManifest,
    CollectionStatus,
    GitRepositoryProbe,
    ManifestCorruption,
    ManifestExistsError,
    NotActivatedError,
    ProspectiveStore,
    RecordError,
    RootLockedError,
    RunLogCorruption,
    RunRecord,
    RunStatus,
    SymbolRun,
    dependency_versions,
)
from tests.prospective_fixtures import (  # noqa: F401 - autouse guard
    COLLECTOR_SHA,
    M2_SHA,
    VERSIONS,
    et,
    ny_midnight,
    offline_and_no_live_root,
)


def manifest(**overrides) -> ActivationManifest:
    values = dict(
        activated_at=et(2026, 10, 5, 15),
        collection_id=COLLECTION_V1.collection_id,
        collection_fingerprint=COLLECTION_V1.fingerprint,
        collector_git_commit=COLLECTOR_SHA,
        m2_preregistration_git_commit=M2_SHA,
        holdout_start=COLLECTION_V1.holdout_start,
        universe=COLLECTION_V1.universe,
        interval="1d",
        basis="raw",
        provider="yfinance",
        hypothesis_fingerprints=COLLECTION_V1.hypothesis_fingerprints,
        outcome_spec_fingerprints=COLLECTION_V1.outcome_spec_fingerprints,
        evaluation_version=1,
        dependency_versions=VERSIONS,
    )
    values.update(overrides)
    return ActivationManifest(**values)


def run_record(**overrides) -> RunRecord:
    values = dict(
        run_id="run-1",
        started_at=et(2026, 10, 6, 7),
        finished_at=et(2026, 10, 6, 7, 1),
        run_status=RunStatus.COMPLETED,
        collection_fingerprint=COLLECTION_V1.fingerprint,
        activated_at=et(2026, 10, 5, 15),
        collector_git_commit=COLLECTOR_SHA,
        universe=("SPY",),
        symbols=(SymbolRun(symbol="SPY", status=CollectionStatus.OK, stage="done",
                           built_at=et(2026, 10, 6, 7), tail=ny_midnight(date(2026, 10, 5)),
                           bars=500, artifacts_new=4, artifacts_duplicate=0, outcomes_new=0,
                           outcomes_present=0, pending=12, ineligible=0, refused=0,
                           out_of_window=0,
                           missed_tails=(ny_midnight(date(2026, 10, 2)),)),),
    )
    values.update(overrides)
    return RunRecord(**values)


# -- manifest -----------------------------------------------------------------------------------


class TestManifest:
    def test_round_trip_is_byte_identical(self):
        original = manifest()
        assert ActivationManifest.from_bytes(original.to_bytes()) == original
        assert ActivationManifest.from_bytes(original.to_bytes()).to_bytes() == original.to_bytes()

    def test_schema_fields_are_exactly_the_contract(self):
        payload = json.loads(manifest().to_bytes())
        assert set(payload) == {
            "schema", "activated_at", "collection_id", "collection_fingerprint",
            "collector_git_commit", "m2_preregistration_git_commit", "holdout_start",
            "universe", "interval", "basis", "provider", "hypothesis_fingerprints",
            "outcome_spec_fingerprints", "evaluation_version", "dependency_versions",
        }
        assert payload["schema"] == "prospective_activation_v1"
        assert payload["activated_at"] == "2026-10-05T19:00:00+00:00"

    @pytest.mark.parametrize("mutate", [
        lambda p: p.update(extra="x"),
        lambda p: p.pop("m2_preregistration_git_commit"),
        lambda p: p.update(schema="prospective_activation_v2"),
        lambda p: p.update(collector_git_commit="abc"),
    ])
    def test_a_non_contract_manifest_is_refused(self, mutate):
        payload = json.loads(manifest().to_bytes())
        mutate(payload)
        raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(raw)

    def test_non_canonical_bytes_are_refused(self):
        raw = manifest().to_bytes().replace(b":", b": ", 1)
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(raw)

    def test_both_commits_are_required_and_validated(self):
        with pytest.raises(RecordError):
            manifest(m2_preregistration_git_commit="")
        with pytest.raises(RecordError):
            manifest(collector_git_commit="A" * 40)


# -- run records --------------------------------------------------------------------------------


def _walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


class TestRunRecord:
    def test_round_trip(self):
        record = run_record()
        line = record.to_line()
        assert line.endswith(b"\n") and line.count(b"\n") == 1
        assert RunRecord.from_line(line[:-1]) == record

    def test_field_allowlist_is_exact(self):
        payload = json.loads(run_record().to_line())
        assert set(payload) == RunRecord.FIELDS
        assert set(payload["symbols"][0]) == SymbolRun.FIELDS
        assert SymbolRun.FIELDS == {
            "symbol", "status", "stage", "error_class", "built_at", "tail", "bars",
            "artifacts_new", "artifacts_duplicate", "outcomes_new", "outcomes_present",
            "pending", "ineligible", "refused", "out_of_window", "missed_tails",
        }

    def test_no_value_in_a_run_record_can_be_a_float(self):
        """Every number is a count: a price or a return has no place to live."""
        for value in _walk(json.loads(run_record().to_line())):
            assert not isinstance(value, float), value

    def test_derived_counts(self):
        record = run_record(symbols=(
            SymbolRun(symbol="SPY", status=CollectionStatus.OK, stage="done"),
            SymbolRun(symbol="QQQ", status=CollectionStatus.PRE_ACTIVATION, stage="activation"),
            SymbolRun(symbol="IWM", status=CollectionStatus.PROVIDER_FAILURE, stage="snapshot"),
            SymbolRun(symbol="TLT", status=CollectionStatus.DUPLICATE_ALREADY_EXISTS, stage="done"),
            SymbolRun(symbol="GLD", status=CollectionStatus.STALE_TAIL, stage="validation"),
        ))
        payload = json.loads(record.to_line())
        assert (payload["symbols_attempted"], payload["symbols_ok"],
                payload["symbols_pre_activation"], payload["symbols_failed"]) == (5, 2, 1, 2)
        assert not record.succeeded

    def test_an_unknown_field_or_status_is_refused(self):
        payload = json.loads(run_record().to_line())
        payload["symbols"][0]["forward_return"] = 0.01
        with pytest.raises(RecordError):
            RunRecord.from_line(json.dumps(payload, sort_keys=True,
                                           separators=(",", ":")).encode())
        payload = json.loads(run_record().to_line())
        payload["symbols"][0]["status"] = "bullish"
        with pytest.raises(RecordError):
            RunRecord.from_line(json.dumps(payload, sort_keys=True,
                                           separators=(",", ":")).encode())

    def test_no_operational_status_spells_a_research_state(self):
        states = {"bullish", "bearish", "neutral", "conflicted", "insufficient_data"}
        assert not {status.value for status in CollectionStatus} & states
        assert not {status.value for status in RunStatus} & states


# -- the store ----------------------------------------------------------------------------------


class TestStore:
    def test_construction_and_reads_create_nothing(self, tmp_path):
        root = tmp_path / "prospective" / "v1"
        store = ProspectiveStore(root)
        assert store.read_manifest() is None
        assert list(store.iter_runs()) == []
        assert not store.root_exists() and not store.ledger_exists()
        assert not (tmp_path / "prospective").exists()

    def test_layout(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        assert store.manifest_path.name == "activation.json"
        assert store.run_log_path.name == "runs.jsonl"
        assert store.lock_path.name == "collect.lock"
        assert store.ledger_root == tmp_path / "v1" / "ledger"

    def test_manifest_is_written_once(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        store.write_manifest(manifest())
        assert store.read_manifest() == manifest()
        before = store.manifest_path.read_bytes()
        with pytest.raises(ManifestExistsError):
            store.write_manifest(manifest(activated_at=et(2026, 10, 7, 15)))
        assert store.manifest_path.read_bytes() == before

    def test_activation_refuses_a_non_empty_root(self, tmp_path):
        root = tmp_path / "v1"
        (root / "ledger").mkdir(parents=True)
        with pytest.raises(ManifestExistsError):
            ProspectiveStore(root).write_manifest(manifest())
        assert not (root / "activation.json").exists()

    def test_a_corrupt_manifest_is_reported_not_repaired(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        store.write_manifest(manifest())
        store.manifest_path.write_bytes(b"{not json")
        with pytest.raises(ManifestCorruption):
            store.read_manifest()
        assert store.manifest_path.read_bytes() == b"{not json"

    def test_run_log_requires_activation_and_appends(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        with pytest.raises(NotActivatedError):
            store.append_run(run_record())
        assert not store.root_exists()
        store.write_manifest(manifest())
        store.append_run(run_record(run_id="one"))
        store.append_run(run_record(run_id="two"))
        assert [r.run_id for r in store.iter_runs()] == ["one", "two"]

    def test_a_torn_run_log_line_is_corruption_with_its_line_number(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        store.write_manifest(manifest())
        store.append_run(run_record())
        with store.run_log_path.open("ab") as handle:
            handle.write(b'{"schema":"prospective_run_v1"')
        with pytest.raises(RunLogCorruption) as caught:
            list(store.iter_runs())
        assert caught.value.line_number == 2

    def test_a_tampered_run_log_line_is_corruption(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        store.write_manifest(manifest())
        store.append_run(run_record())
        data = store.run_log_path.read_bytes().replace(b'"bars":500', b'"bars":501.5')
        store.run_log_path.write_bytes(data)
        with pytest.raises(RunLogCorruption) as caught:
            list(store.iter_runs())
        assert caught.value.line_number == 1

    def test_the_lock_is_exclusive_and_released(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        store.write_manifest(manifest())
        other = ProspectiveStore(tmp_path / "v1")
        with store.exclusive_lock():
            with pytest.raises(RootLockedError):
                with other.exclusive_lock():
                    pass  # pragma: no cover
        with other.exclusive_lock():
            pass

    def test_the_lock_is_refused_on_an_unactivated_root(self, tmp_path):
        store = ProspectiveStore(tmp_path / "v1")
        with pytest.raises(NotActivatedError):
            with store.exclusive_lock():
                pass  # pragma: no cover
        assert not store.root_exists()


# -- environment --------------------------------------------------------------------------------


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class TestRepositoryProbe:
    @pytest.fixture
    def repository(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "test@example.invalid")
        _git(root, "config", "user.name", "test")
        (root / "a.txt").write_text("one\n")
        _git(root, "add", "a.txt")
        _git(root, "commit", "-q", "-m", "one")
        return root

    def test_head_and_clean(self, repository):
        state = GitRepositoryProbe(repository).repository_state()
        assert state.head == _git(repository, "rev-parse", "HEAD")
        assert state.clean

    def test_untracked_or_modified_files_are_dirty(self, repository):
        (repository / "b.txt").write_text("new\n")
        assert not GitRepositoryProbe(repository).repository_state().clean
        (repository / "b.txt").unlink()
        (repository / "a.txt").write_text("changed\n")
        assert not GitRepositoryProbe(repository).repository_state().clean

    def test_ancestry(self, repository):
        first = _git(repository, "rev-parse", "HEAD")
        (repository / "a.txt").write_text("two\n")
        _git(repository, "commit", "-q", "-am", "two")
        probe = GitRepositoryProbe(repository)
        assert probe.is_ancestor_of_head(first)
        assert probe.is_ancestor_of_head(_git(repository, "rev-parse", "HEAD"))
        assert not probe.is_ancestor_of_head("c" * 40)


def test_dependency_versions_name_python_yfinance_and_pandas():
    versions = dependency_versions()
    assert set(versions) == {"python", "yfinance", "pandas"}
    assert all(isinstance(value, str) and value for value in versions.values())
