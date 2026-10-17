"""Pre-activation hardening, package 1 (R2, R3, R5, R1-NB1, R1-NB2, P-2).

* R2: a tracked file flagged assume-unchanged or skip-worktree is hidden from
  ``git status``; the probe reports such a repository as not clean (edited or
  not, and without clearing the flag), so activation, collection and future
  validation refuse it.
* R3: ``PYTHONPATH`` / ``PYTHONHOME`` can make code importable without
  distribution metadata; while either is in effect the dependency environment
  is unverifiable -- unless the interpreter ignores the environment (``-E``).
* R5: an unexpected failure while reading distributions is the same
  controlled "unverified" refusal, never a traceback.
* R1-NB1: a file-system error reading ``activation.json`` is the controlled
  ``invalid_manifest`` everywhere.
* R1-NB2: the ABA manifest swap (bind B, restore A before capture) refuses.
* P-2: ``health`` reports the CURRENT runtime identity, also before activation.

Every root and repository is temporary; nothing touches the network or
``data/prospective``.
"""

from __future__ import annotations

import errno
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.application.future_validation as future_validation
from src.application.prospective import (
    ActivationRefused,
    activate,
    build_prospective_store,
    collect,
    current_import_path_overrides as REAL_IMPORT_PATH_OVERRIDES,
    health,
    runtime_identity,
)
from src.cli.prospective import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from src.prospective import (
    IMPORT_PATH_VARIABLES,
    DependencyEnvironment,
    DependencyEnvironmentError,
    GitRepositoryProbe,
    ManifestCorruption,
    RunRecord,
    RunStart,
    RunStatus,
    capture_dependency_environment,
    import_path_overrides,
    running_python,
)
from tests.prospective_fixtures import (
    COLLECTOR_SHA,
    DEPENDENCIES,
    REPO,
    SPY_ONLY,
    Clock,
    ProbeDouble,
    SessionProvider,
)
from tests.test_prospective_activation_binding import (  # noqa: F401 - fixtures
    ACTIVATED_AT,
    DRIFTS,
    TUESDAY_RUN,
    FakeDistribution,
    Level3Sentinel,
    Order,
    activate_in,
    activated_spy,
    borrowed_template,
    completed,
    drop_result,
    future_validation_firewall,
    git,
    head,
    later_activation,
    matured,
    opened_run,
    opened_status,
    refused,
    repo,
    root_templates,
    unverified,
    validation_files,
)

REAL_LEVEL_THREE = future_validation._level_three_evidence

#: A tracked operational file of the collector at the M2A commit (not M2A-bound).
COLLECTOR_FILE = "src/application/snapshot.py"
FLAGS = {"assume-unchanged": ("--assume-unchanged", "h"),
         "skip-worktree": ("--skip-worktree", "S")}


def flag(root: Path, path: str, name: str, *, edit: bool) -> None:
    git(root, "update-index", FLAGS[name][0], path)
    if edit:
        with (root / path).open("a", encoding="utf-8") as handle:
            handle.write("\n# edit hidden by an index flag\n")


def tags(root: Path) -> dict[str, str]:
    return {line[2:]: line[0] for line in git(root, "ls-files", "-v").splitlines()}


def distributions(environment: DependencyEnvironment = DEPENDENCIES):
    return [FakeDistribution(name, version) for name, version in environment.packages]


def capture(**kwargs) -> DependencyEnvironment:
    """The real capture over synthetic distributions that equal ``DEPENDENCIES``."""
    kwargs.setdefault("ignore_environment", False)
    return capture_dependency_environment(
        distributions(), python_implementation=DEPENDENCIES.python_implementation,
        python_version=DEPENDENCIES.python_version, **kwargs)


@pytest.fixture
def no_import_path(monkeypatch):
    for name in IMPORT_PATH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


# == R2: Git index flags ==========================================================================


@pytest.fixture
def small_repo(tmp_path) -> Path:
    root = tmp_path / "small"
    root.mkdir()
    git(root, "init", "-q")
    (root / "collector.py").write_text("VALUE = 1\n")
    (root / "other.py").write_text("OTHER = 2\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "initial")
    return root


class TestIndexFlags:
    def test_a_plain_clean_repository_is_clean(self, small_repo):
        state = GitRepositoryProbe(small_repo).repository_state()
        assert state.clean and state.head == head(small_repo)

    @pytest.mark.parametrize("edit", [False, True], ids=["unchanged", "edited"])
    @pytest.mark.parametrize("name", sorted(FLAGS))
    def test_a_flagged_tracked_file_makes_the_repository_not_clean(self, small_repo, name,
                                                                   edit):
        flag(small_repo, "collector.py", name, edit=edit)
        assert git(small_repo, "status", "--porcelain") == ""  # what ordinary status sees
        assert not GitRepositoryProbe(small_repo).repository_state().clean

    @pytest.mark.parametrize("name", sorted(FLAGS))
    def test_the_flag_is_reported_never_cleared(self, small_repo, name):
        flag(small_repo, "collector.py", name, edit=True)
        before = (tags(small_repo), (small_repo / "collector.py").read_bytes())
        GitRepositoryProbe(small_repo).repository_state()
        assert tags(small_repo)["collector.py"] == FLAGS[name][1]
        assert (tags(small_repo), (small_repo / "collector.py").read_bytes()) == before

    def test_clearing_the_flag_restores_ordinary_detection(self, small_repo):
        flag(small_repo, "collector.py", "assume-unchanged", edit=True)
        git(small_repo, "update-index", "--no-assume-unchanged", "collector.py")
        assert not GitRepositoryProbe(small_repo).repository_state().clean
        git(small_repo, "checkout", "--", "collector.py")
        assert GitRepositoryProbe(small_repo).repository_state().clean

    def test_every_git_call_disables_the_file_system_monitor(self, small_repo, monkeypatch):
        import src.prospective.environment as adapter

        seen = []
        real = adapter.subprocess.run

        def spy(command, *args, **kwargs):
            seen.append(command)
            return real(command, *args, **kwargs)

        monkeypatch.setattr(adapter.subprocess, "run", spy)
        GitRepositoryProbe(small_repo).repository_state()
        assert {tuple(c[3:5]) for c in seen} == {("-c", "core.fsmonitor=false")}
        assert any("ls-files" in c for c in seen) and any("status" in c for c in seen)

    def test_an_ls_files_failure_is_unverified(self, small_repo, monkeypatch):
        import src.prospective.environment as adapter

        real = adapter.subprocess.run

        def failing(command, *args, **kwargs):
            if "ls-files" in command:
                return subprocess.CompletedProcess(command, 128, b"", b"")
            return real(command, *args, **kwargs)

        monkeypatch.setattr(adapter.subprocess, "run", failing)
        with pytest.raises(adapter.RepositoryProbeError):
            GitRepositoryProbe(small_repo).repository_state()


class TestIndexFlagsInTheApplication:
    @pytest.mark.parametrize("edit", [False, True], ids=["unchanged", "edited"])
    @pytest.mark.parametrize("name", sorted(FLAGS))
    def test_activation_refuses_before_writing(self, repo, tmp_path, name, edit):
        flag(repo, COLLECTOR_FILE, name, edit=edit)
        assert refused(repo, tmp_path).reason == "dirty_repository"

    @pytest.mark.parametrize("name", sorted(FLAGS))
    def test_collection_refuses_before_any_provider(self, repo, tmp_path, name):
        store, _ = activate_in(repo, tmp_path)
        flag(repo, COLLECTOR_FILE, name, edit=True)
        built, provider = [], SessionProvider()
        report = collect(store, provider_factory=lambda: built.append(1) or provider,
                         now=Clock(TUESDAY_RUN), repository=GitRepositoryProbe(repo),
                         dependency_environment=lambda: DEPENDENCIES)
        assert report.outcome == RunStatus.DIRTY_COLLECTOR_TREE.value
        assert built == [] and provider.calls == []
        assert not store.ledger_exists()
        log = store.read_run_log()
        assert len(log) == 1 and isinstance(log[0], RunRecord) and log[0].symbols == ()
        assert not any(isinstance(entry, RunStart) for entry in log)

    def test_the_same_collection_proceeds_without_the_flag(self, repo, tmp_path):
        store, _ = activate_in(repo, tmp_path, definition=SPY_ONLY)
        provider = SessionProvider()
        report = collect(store, provider_factory=lambda: provider, now=Clock(TUESDAY_RUN),
                         definition=SPY_ONLY, repository=GitRepositoryProbe(repo),
                         dependency_environment=lambda: DEPENDENCIES)
        assert report.outcome == "completed" and len(provider.calls) == 1

    @pytest.mark.parametrize("name", sorted(FLAGS))
    def test_future_validation_refuses_before_level_three(self, matured, repo, monkeypatch,
                                                          name):
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        flag(repo, COLLECTOR_FILE, name, edit=True)
        report = opened_status(matured, GitRepositoryProbe(repo))
        assert "dirty_repository" in report.identity_mismatches
        assert report.validity == "invalid"
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.detail == ("m2_binding_mismatch", "dirty_repository")
        assert sentinel.calls == 0
        assert validation_files(matured) == {}


# == R3: PYTHONPATH / PYTHONHOME ==================================================================


class TestImportPathOverrides:
    @pytest.mark.parametrize("variables, expected", [
        ({}, ()),
        ({"PYTHONPATH": "", "PYTHONHOME": ""}, ()),
        ({"PYTHONPATH": "/elsewhere"}, ("PYTHONPATH",)),
        ({"PYTHONHOME": "/elsewhere"}, ("PYTHONHOME",)),
        ({"PYTHONPATH": "/a", "PYTHONHOME": "/b"}, ("PYTHONHOME", "PYTHONPATH")),
        ({"PYTHONSTARTUP": "/a", "HOME": "/b"}, ()),
    ], ids=["unset", "empty", "path", "home", "both", "unrelated"])
    def test_the_variables_in_effect(self, variables, expected):
        assert import_path_overrides(variables, ignore_environment=False) == expected

    def test_an_interpreter_that_ignores_the_environment_has_none(self):
        both = {"PYTHONPATH": "/a", "PYTHONHOME": "/b"}
        assert import_path_overrides(both, ignore_environment=True) == ()

    def test_the_default_reads_the_process_environment(self, monkeypatch, no_import_path):
        assert import_path_overrides(ignore_environment=False) == ()
        monkeypatch.setenv("PYTHONPATH", "/elsewhere")
        assert import_path_overrides(ignore_environment=False) == ("PYTHONPATH",)

    @pytest.mark.parametrize("flags, expected", [((), "PYTHONPATH"), (("-E",), "none")],
                             ids=["normal", "ignore-environment"])
    def test_a_real_interpreter_honours_its_ignore_environment_flag(self, tmp_path, flags,
                                                                    expected):
        variables = {k: v for k, v in os.environ.items() if k not in IMPORT_PATH_VARIABLES}
        variables["PYTHONPATH"] = str(tmp_path)
        code = ("from src.prospective.environment import import_path_overrides as f; "
                "print(','.join(f()) or 'none')")
        completed_process = subprocess.run([sys.executable, *flags, "-c", code], cwd=REPO,
                                           env=variables, capture_output=True, text=True,
                                           check=True, timeout=60)
        assert completed_process.stdout.strip() == expected


class TestImportPathRefusal:
    @pytest.mark.parametrize("name", IMPORT_PATH_VARIABLES)
    def test_capture_refuses_while_a_variable_is_in_effect(self, name):
        with pytest.raises(DependencyEnvironmentError, match=name):
            capture(variables={name: "/elsewhere"})

    def test_capture_succeeds_without_them_or_when_they_are_ignored(self):
        assert capture(variables={}) == DEPENDENCIES
        both = {"PYTHONPATH": "/a", "PYTHONHOME": "/b"}
        assert capture(variables=both, ignore_environment=True) == DEPENDENCIES

    def test_the_variables_never_reach_the_recorded_environment(self):
        assert "PYTHON" not in capture(variables={}).canonical_json().replace(
            "python_implementation", "").replace("python_version", "")

    def test_activation_refuses_and_writes_nothing(self, tmp_path, monkeypatch,
                                                   no_import_path):
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
        store = build_prospective_store(tmp_path / "v1")
        with pytest.raises(ActivationRefused) as caught:
            activate(store, collector_git_commit=COLLECTOR_SHA,
                     server_main_git_commit=COLLECTOR_SHA, repository=ProbeDouble(),
                     dependency_environment=capture, now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "dependency_environment_unavailable"
        assert not store.root_exists()

    @pytest.mark.parametrize("name", IMPORT_PATH_VARIABLES)
    def test_collection_refuses_before_any_provider(self, tmp_path, monkeypatch,
                                                     no_import_path, name):
        store = activated_spy(tmp_path)
        monkeypatch.setenv(name, str(tmp_path))
        built = []
        report = collect(store, provider_factory=lambda: built.append(1),
                         now=Clock(TUESDAY_RUN), definition=SPY_ONLY,
                         repository=ProbeDouble(), dependency_environment=capture)
        assert report.outcome == RunStatus.DEPENDENCY_ENVIRONMENT_UNVERIFIED.value
        assert built == [] and not store.ledger_exists()
        log = store.read_run_log()
        assert len(log) == 1 and log[0].symbols == ()
        assert not any(isinstance(entry, RunStart) for entry in log)

    def test_the_same_collection_proceeds_once_unset(self, tmp_path, no_import_path):
        store = activated_spy(tmp_path)
        provider = SessionProvider()
        report = collect(store, provider_factory=lambda: provider, now=Clock(TUESDAY_RUN),
                         definition=SPY_ONLY, repository=ProbeDouble(),
                         dependency_environment=capture)
        assert report.outcome == "completed" and len(provider.calls) == 1


# == R5: unexpected capture failures ==============================================================


class Exploding:
    def __init__(self, error: BaseException):
        self.error = error

    @property
    def metadata(self):
        raise self.error

    version = "1.0"


def failing_discovery(error):
    def generate():
        yield FakeDistribution("numpy", "2.3.4")
        raise error
    return generate()


class TestUnexpectedCaptureFailure:
    @pytest.mark.parametrize("found", [
        lambda: failing_discovery(RuntimeError("boom")),
        lambda: [Exploding(RuntimeError("boom"))],
        lambda: [Exploding(AttributeError("boom"))],
        lambda: [Exploding(LookupError("boom"))],
    ], ids=["discovery", "metadata", "attribute", "lookup"])
    def test_is_the_controlled_unverified_error(self, found):
        with pytest.raises(DependencyEnvironmentError) as caught:
            capture_dependency_environment(found(), ignore_environment=False)
        assert isinstance(caught.value.__cause__, Exception)

    def test_a_failing_metadata_scan_is_controlled(self, monkeypatch):
        import src.prospective.environment as adapter

        def broken():
            raise RuntimeError("scan failed")

        monkeypatch.setattr(adapter.metadata, "distributions", broken)
        with pytest.raises(DependencyEnvironmentError, match="RuntimeError"):
            capture_dependency_environment(variables={}, ignore_environment=False)

    @pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
    def test_interrupts_are_never_swallowed(self, error):
        with pytest.raises(error):
            capture_dependency_environment(failing_discovery(error()), ignore_environment=False)

    def unexpected(self):
        return capture_dependency_environment([Exploding(RuntimeError("boom"))],
                                              ignore_environment=False)

    def test_collection_records_an_unverified_refusal(self, tmp_path):
        store = activated_spy(tmp_path)
        built = []
        report = collect(store, provider_factory=lambda: built.append(1),
                         now=Clock(TUESDAY_RUN), definition=SPY_ONLY,
                         repository=ProbeDouble(), dependency_environment=self.unexpected)
        assert report.outcome == RunStatus.DEPENDENCY_ENVIRONMENT_UNVERIFIED.value
        assert built == [] and not store.ledger_exists()
        assert [type(entry) for entry in store.read_run_log()] == [RunRecord]

    def test_activation_refuses_and_writes_nothing(self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        with pytest.raises(ActivationRefused) as caught:
            activate(store, collector_git_commit=COLLECTOR_SHA,
                     server_main_git_commit=COLLECTOR_SHA, repository=ProbeDouble(),
                     dependency_environment=self.unexpected, now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "dependency_environment_unavailable"
        assert not store.root_exists()

    def test_health_reports_it_without_a_traceback(self, tmp_path):
        store = activated_spy(tmp_path)
        out = io.StringIO()
        code = main(["health"], root=store.root, stdout=out, stderr=io.StringIO(),
                    repository=ProbeDouble(), dependency_environment=self.unexpected)
        assert code == EXIT_FAILED
        assert "dependency_environment=unavailable" in out.getvalue()
        assert "runtime_dependencies=unavailable" in out.getvalue()


# == R1-NB1: an unreadable activation manifest ==================================================


def unreadable_manifest(monkeypatch, error: OSError, *, at: str = "read_bytes") -> None:
    real = getattr(Path, at)

    def refuse(self, *args, **kwargs):
        if self.name == "activation.json":
            raise error
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, at, refuse)


OS_ERRORS = {
    "permission": PermissionError(errno.EACCES, "Permission denied"),
    "not-permitted": PermissionError(errno.EPERM, "Operation not permitted"),
    "io": OSError(errno.EIO, "Input/output error"),
    "vanished": FileNotFoundError(errno.ENOENT, "No such file or directory"),
}


class TestUnreadableManifest:
    @pytest.mark.parametrize("name", sorted(OS_ERRORS))
    def test_the_store_raises_the_controlled_corruption(self, tmp_path, monkeypatch, name):
        store = activated_spy(tmp_path)
        unreadable_manifest(monkeypatch, OS_ERRORS[name])
        with pytest.raises(ManifestCorruption, match=type(OS_ERRORS[name]).__name__):
            store.read_manifest()

    def test_a_refused_existence_check_is_the_same(self, tmp_path, monkeypatch):
        store = activated_spy(tmp_path)
        unreadable_manifest(monkeypatch, OS_ERRORS["permission"], at="exists")
        with pytest.raises(ManifestCorruption):
            store.read_manifest()

    def test_absent_and_malformed_keep_their_meaning(self, tmp_path):
        assert build_prospective_store(tmp_path / "none").read_manifest() is None
        store = activated_spy(tmp_path)
        store.manifest_path.write_bytes(store.manifest_path.read_bytes()[:-5])
        with pytest.raises(ManifestCorruption, match="^activation manifest: "):
            store.read_manifest()

    @pytest.mark.parametrize("name", ["permission", "io"])
    def test_collection_refuses_before_any_provider(self, tmp_path, monkeypatch, name):
        store = activated_spy(tmp_path)
        before = store.run_log_path.exists()
        unreadable_manifest(monkeypatch, OS_ERRORS[name])
        built = []
        report = collect(store, provider_factory=lambda: built.append(1),
                         now=Clock(TUESDAY_RUN), definition=SPY_ONLY,
                         repository=ProbeDouble(), dependency_environment=lambda: DEPENDENCIES)
        assert (report.outcome, report.record) == ("invalid_manifest", None)
        assert built == [] and store.run_log_path.exists() == before
        out = io.StringIO()
        assert main(["collect"], root=store.root, stdout=out, stderr=io.StringIO(),
                    repository=ProbeDouble(), provider_factory=lambda: built.append(1),
                    now=Clock(TUESDAY_RUN)) == EXIT_REFUSED
        assert "reason=invalid_manifest" in out.getvalue() and built == []

    @pytest.mark.parametrize("name", ["permission", "io"])
    def test_health_is_invalid_and_exits_one(self, tmp_path, monkeypatch, name):
        store = activated_spy(tmp_path)
        unreadable_manifest(monkeypatch, OS_ERRORS[name])
        report = health(store, repository=ProbeDouble(),
                        dependency_environment=lambda: DEPENDENCIES)
        assert (report.status, report.integrity, report.corrupt_component) == (
            "invalid_manifest", "corrupt", "manifest")
        out = io.StringIO()
        assert main(["health"], root=store.root, stdout=out, stderr=io.StringIO(),
                    repository=ProbeDouble(),
                    dependency_environment=lambda: DEPENDENCIES) == EXIT_FAILED
        assert "prospective_status=invalid_manifest" in out.getvalue()

    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    @pytest.mark.parametrize("name", ["permission", "io"])
    def test_future_validation_refuses_before_any_stage(self, matured, monkeypatch, name,
                                                        artifacts):
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        before = validation_files(matured)
        order = Order(monkeypatch)
        unreadable_manifest(monkeypatch, OS_ERRORS[name])
        outcome = opened_run(matured, ProbeDouble())
        assert (outcome.outcome, outcome.detail) == ("refused", ("invalid_manifest",))
        report = opened_status(matured, ProbeDouble())
        assert (report.activation, report.validity) == ("invalid_manifest", "invalid")
        assert order.calls == [] and validation_files(matured) == before


# == R1-NB2: the ABA manifest swap ================================================================


class TestManifestSwapABA:
    """Bind a different valid manifest B, then restore the original A before capture.

    A's bytes are exactly what an existing unlock recorded, so a check against
    the recorded snapshot alone would accept them; the per-operation invariant
    (the captured manifest must be byte-identical to the one bound at the start
    of *this* operation) refuses.
    """

    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_restoring_the_original_before_capture_refuses(self, matured, monkeypatch,
                                                           artifacts):
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        before = validation_files(matured)
        original = matured.manifest_path.read_bytes()
        later_activation(matured)  # B: valid, binds, differs from A
        assert matured.manifest_path.read_bytes() != original
        order = Order(monkeypatch)
        real_capture = future_validation._capture_locked
        restored = []

        def capture_after_restore(store, recorded=None):
            if not restored:
                store.manifest_path.write_bytes(original)  # back to A
                restored.append(True)
            return real_capture(store, recorded)

        monkeypatch.setattr(future_validation, "_capture_locked", capture_after_restore)
        outcome = opened_run(matured, ProbeDouble())
        assert outcome.outcome == "refused"
        assert unverified(outcome.detail, artifacts) == ("manifest_changed",)
        assert restored == [True]
        assert order.calls[0] == "binding_mismatches"
        assert "_level_three_evidence" not in order and "_derive_result" not in order
        assert validation_files(matured) == before
        assert matured.manifest_path.read_bytes() == original

        monkeypatch.setattr(future_validation, "_capture_locked", real_capture)
        monkeypatch.setattr(future_validation, "_level_three_evidence", REAL_LEVEL_THREE)
        expected = {"none": "complete", "complete": "already_complete",
                    "unlock-only": "completed_after_unlock"}[artifacts]
        assert opened_run(matured, ProbeDouble()).outcome == expected  # A alone is fine


# == P-2: current runtime identity ================================================================


class TestRuntimeIdentity:
    def test_before_activation_health_reports_the_current_runtime(self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        report = health(store, repository=ProbeDouble(),
                        dependency_environment=lambda: DEPENDENCIES)
        assert report.status == "not_activated"
        assert report.dependency_environment == "unavailable"  # nothing to compare with yet
        assert (report.runtime_python_implementation, report.runtime_python_version,
                report.runtime_dependencies, report.runtime_dependency_fingerprint,
                report.runtime_import_path_overrides) == (
            "CPython", "3.11.3", "ok", DEPENDENCIES.fingerprint, ())
        assert not store.root_exists()

    def test_it_is_deterministic_and_captured_once(self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        calls = []

        def source():
            calls.append(1)
            return DEPENDENCIES

        first = health(store, repository=ProbeDouble(), dependency_environment=source)
        assert calls == [1]
        assert first == health(store, repository=ProbeDouble(),
                               dependency_environment=source)

    def test_an_unverifiable_runtime_still_names_the_interpreter(self, tmp_path):
        def unverifiable():
            raise DependencyEnvironmentError("PYTHONPATH is set")

        report = health(build_prospective_store(tmp_path / "v1"), repository=ProbeDouble(),
                        dependency_environment=unverifiable)
        assert (report.runtime_dependencies,
                report.runtime_dependency_fingerprint) == ("unavailable", None)
        assert (report.runtime_python_implementation,
                report.runtime_python_version) == running_python()

    def test_the_import_path_verdict_comes_from_the_adapter(self, tmp_path, monkeypatch,
                                                            no_import_path):
        monkeypatch.setattr("src.application.prospective.current_import_path_overrides",
                            REAL_IMPORT_PATH_OVERRIDES)
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
        expected = () if sys.flags.ignore_environment else ("PYTHONPATH",)
        assert runtime_identity(lambda: DEPENDENCIES).import_path_overrides == expected
        report = health(build_prospective_store(tmp_path / "v1"), repository=ProbeDouble(),
                        dependency_environment=lambda: DEPENDENCIES)
        assert report.runtime_import_path_overrides == expected

    def test_after_activation_the_runtime_is_compared_with_the_manifest(self, tmp_path):
        store = activated_spy(tmp_path)
        same = health(store, definition=SPY_ONLY, repository=ProbeDouble(),
                      dependency_environment=lambda: DEPENDENCIES)
        assert same.dependency_environment == "ok"
        assert same.runtime_dependency_fingerprint == \
            store.read_manifest().dependency_environment.fingerprint
        drifted = health(store, definition=SPY_ONLY, repository=ProbeDouble(),
                         dependency_environment=lambda: DRIFTS["python-patch"])
        assert drifted.dependency_environment == "mismatch"
        assert (drifted.runtime_python_version, drifted.runtime_dependency_fingerprint) == (
            "3.11.4", DRIFTS["python-patch"].fingerprint)


def fields(line: str) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in line.split())


class TestRuntimeIdentityCli:
    RUNTIME_KEYS = ("runtime_python_implementation", "runtime_python_version",
                    "runtime_dependencies", "runtime_dependency_fingerprint",
                    "runtime_import_path_overrides")

    def run_health(self, root, source):
        out = io.StringIO()
        code = main(["health"], root=root, stdout=out, stderr=io.StringIO(),
                    repository=ProbeDouble(), dependency_environment=source)
        return code, out.getvalue().splitlines()

    def test_pre_activation_fields_are_stable_key_values(self, tmp_path):
        code, lines = self.run_health(tmp_path / "v1", lambda: DEPENDENCIES)
        head_fields = fields(lines[0])
        assert code == EXIT_OK
        assert {key: head_fields[key] for key in self.RUNTIME_KEYS} == {
            "runtime_python_implementation": "CPython",
            "runtime_python_version": "3.11.3",
            "runtime_dependencies": "ok",
            "runtime_dependency_fingerprint": DEPENDENCIES.fingerprint,
            "runtime_import_path_overrides": "none",
        }
        assert head_fields["dependency_environment"] == "unavailable"
        assert not (tmp_path / "v1").exists()

    def test_an_unverifiable_runtime_does_not_change_the_pre_activation_exit(self, tmp_path,
                                                                              monkeypatch):
        monkeypatch.setattr("src.application.prospective.current_import_path_overrides",
                            lambda: ("PYTHONHOME", "PYTHONPATH"))

        def unverifiable():
            raise DependencyEnvironmentError("set")

        code, lines = self.run_health(tmp_path / "v1", unverifiable)
        head_fields = fields(lines[0])
        assert code == EXIT_OK
        assert (head_fields["runtime_dependencies"],
                head_fields["runtime_dependency_fingerprint"],
                head_fields["runtime_import_path_overrides"]) == (
            "unavailable", "none", "PYTHONHOME,PYTHONPATH")
