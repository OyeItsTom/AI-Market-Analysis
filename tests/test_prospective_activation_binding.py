"""M2B: activation identity binding (N6) and dependency drift (N-R11).

* the pinned M2A identity matches the committed pre-registration bytes;
* the dependency-environment contract: canonical, strict, fingerprinted, and
  every material change is drift while discovery order is not;
* activation manifest v2 is strict;
* activation with the *real* Git probe on temporary repositories that borrow
  this repository's objects (``objects/info/alternates``): main, clean,
  HEAD == origin/main == server main, the M2A commit in history and the bound
  files unchanged -- every failure refused before anything is written;
* collection refuses a drifted environment before any provider exists;
* future validation checks the binding before it captures, re-derives or
  opens anything.

Every root is temporary; nothing touches the network or ``data/prospective``.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.application.future_validation as future_validation
from src.application.future_validation import binding_mismatches, run, status
from src.application.prospective import (
    ActivationRefused,
    activate,
    build_prospective_store,
    collect,
    health,
    m2_binding_mismatches,
)
from src.cli.prospective import build_parser, main
from src.prospective import (
    COLLECTION_V1,
    DEPENDENCY_SCHEMA,
    M2A_BOUND_PATHS,
    M2A_FUTURE_VALIDATION_FINGERPRINT,
    M2A_PREREGISTRATION_COMMIT,
    ActivationManifest,
    BoundPath,
    DependencyEnvironment,
    DependencyEnvironmentError,
    GitRepositoryProbe,
    IdentityError,
    RecordError,
    RunRecord,
    RunStart,
    RunStatus,
    capture_dependency_environment,
    normalise_distribution_name,
)
from src.research.future_validation import FUTURE_VALIDATION_V1, FUTURE_VALIDATION_V1_FINGERPRINT
from tests.future_validation_fixtures import (  # noqa: F401 - autouse firewall
    AFTER_E1,
    copy_root,
    future_validation_firewall,
    root_templates,
    small_definition,
)
from tests.prospective_fixtures import (
    COLLECTOR_SHA,
    DEPENDENCIES,
    REPO,
    SPY_ONLY,
    Clock,
    ProbeDouble,
    SessionProvider,
    et,
)

ACTIVATED_AT = et(2026, 10, 5, 15)
TUESDAY_RUN = et(2026, 10, 6, 7)
SMALL = small_definition()
BOUND = {bound.path: bound for bound in M2A_BOUND_PATHS}
DEFINITION_PATH = "src/research/future_validation.py"
ENGINE_PATH = "src/research/future_validation_engine.py"
METHODOLOGY_PATH = "docs/research/future_validation_v1.md"


# -- helpers -----------------------------------------------------------------------------------


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=test@example.invalid", "-c", "user.name=test",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _real_objects() -> Path:
    common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    path = Path(common)
    return (path if path.is_absolute() else REPO / path).resolve() / "objects"


@pytest.fixture(scope="session")
def borrowed_template(tmp_path_factory) -> Path:
    """A repository on ``main`` at the M2A commit, borrowing this repository's objects.

    Offline: ``objects/info/alternates`` points at the local object store, so
    the pinned commit and its blobs exist without any fetch or copy.
    """
    root = tmp_path_factory.mktemp("m2b_git") / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".git" / "objects" / "info" / "alternates").write_text(f"{_real_objects()}\n")
    git(root, "checkout", "-q", "-b", "main", M2A_PREREGISTRATION_COMMIT)
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


@pytest.fixture
def repo(borrowed_template, tmp_path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(borrowed_template, target, symlinks=True)
    return target


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def commit_change(root: Path, path: str, text: str = "\n# operational note\n") -> str:
    with (root / path).open("a", encoding="utf-8") as handle:
        handle.write(text)
    git(root, "commit", "-q", "-am", f"change {path}")
    return head(root)


def activate_in(repo_root: Path, tmp_path: Path, *, server=None, collector=None, **kwargs):
    store = build_prospective_store(tmp_path / "prospective" / "v1")
    current = head(repo_root)
    manifest = activate(store, collector_git_commit=collector or current,
                        server_main_git_commit=server or current,
                        repository=GitRepositoryProbe(repo_root),
                        dependency_environment=lambda: DEPENDENCIES,
                        now=lambda: ACTIVATED_AT, **kwargs)
    return store, manifest


def refused(repo_root: Path, tmp_path: Path, **kwargs) -> ActivationRefused:
    with pytest.raises(ActivationRefused) as caught:
        activate_in(repo_root, tmp_path, **kwargs)
    assert not (tmp_path / "prospective").exists(), "a refused activation wrote something"
    return caught.value


def manifest_payload(**overrides) -> dict:
    store_manifest = ActivationManifest(
        activated_at=ACTIVATED_AT,
        collection_id=COLLECTION_V1.collection_id,
        collection_fingerprint=COLLECTION_V1.fingerprint,
        provenance_policy_fingerprint="c" * 64,
        collector_git_commit=COLLECTOR_SHA,
        origin_main_git_commit=COLLECTOR_SHA,
        server_main_git_commit=COLLECTOR_SHA,
        m2_preregistration_git_commit=M2A_PREREGISTRATION_COMMIT,
        future_validation_fingerprint=M2A_FUTURE_VALIDATION_FINGERPRINT,
        m2_bound_paths=M2A_BOUND_PATHS,
        holdout_start=COLLECTION_V1.holdout_start,
        universe=COLLECTION_V1.universe,
        interval="1d",
        basis="raw",
        provider="yfinance",
        hypothesis_fingerprints=COLLECTION_V1.hypothesis_fingerprints,
        outcome_spec_fingerprints=COLLECTION_V1.outcome_spec_fingerprints,
        evaluation_version=1,
        dependency_environment=DEPENDENCIES,
    )
    payload = json.loads(store_manifest.to_bytes())
    payload.update(overrides)
    return payload


def encode(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


class FakeDistribution:
    def __init__(self, name, version):
        self.metadata = {"Name": name}
        self.version = version


def env(*packages, implementation="CPython", version="3.11.3") -> DependencyEnvironment:
    return DependencyEnvironment.from_distributions(implementation, version, packages)


BASE_PACKAGES = (("numpy", "2.3.4"), ("pandas", "3.0.5"), ("yfinance", "1.7.0"))


# == the pinned M2A identity ======================================================================


class TestPins:
    def test_the_pins_are_the_merged_m2a_identity(self):
        assert M2A_PREREGISTRATION_COMMIT == "3dac81078b31c4c5856419faae4f2749cc43ede5"
        assert M2A_FUTURE_VALIDATION_FINGERPRINT == (
            "79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab")
        assert M2A_FUTURE_VALIDATION_FINGERPRINT == FUTURE_VALIDATION_V1_FINGERPRINT \
            == FUTURE_VALIDATION_V1.fingerprint
        assert [bound.path for bound in M2A_BOUND_PATHS] == [
            METHODOLOGY_PATH, DEFINITION_PATH, ENGINE_PATH]

    def test_the_bound_hashes_are_the_committed_bytes_at_the_pinned_commit(self):
        probe = GitRepositoryProbe(REPO)
        assert probe.commit_exists(M2A_PREREGISTRATION_COMMIT)
        for bound in M2A_BOUND_PATHS:
            assert probe.blob_sha256(M2A_PREREGISTRATION_COMMIT, bound.path) == bound.sha256

    def test_this_checkout_satisfies_the_binding(self):
        """The working tree under test holds the pre-registered bytes (M2B never edits them)."""
        probe = GitRepositoryProbe(REPO)
        assert probe.is_ancestor_of_head(M2A_PREREGISTRATION_COMMIT)
        for bound in M2A_BOUND_PATHS:
            assert probe.working_file_sha256(bound.path) == bound.sha256
        assert probe.paths_unchanged_since(M2A_PREREGISTRATION_COMMIT,
                                           [b.path for b in M2A_BOUND_PATHS])

    @pytest.mark.parametrize("path", ["/abs", "../up", "-flag", "a\\b", ""])
    def test_a_bound_path_must_be_a_relative_repository_path(self, path):
        with pytest.raises(IdentityError):
            BoundPath(path, "0" * 64)

    def test_a_bound_hash_must_be_a_full_sha256(self):
        with pytest.raises(IdentityError):
            BoundPath("a.py", "abc")


# == the dependency-environment contract ===========================================================


class TestDependencyContract:
    def test_names_are_pep503_normalised(self):
        assert normalise_distribution_name("PyYAML") == "pyyaml"
        assert normalise_distribution_name("typing_extensions") == "typing-extensions"
        assert normalise_distribution_name("zope.interface") == "zope-interface"
        assert normalise_distribution_name("A__b--C..d") == "a-b-c-d"

    @pytest.mark.parametrize("name", [None, "", "  ", "-lead", "trail-", "sp ace", "x/y"])
    def test_a_non_name_is_refused(self, name):
        with pytest.raises(IdentityError):
            normalise_distribution_name(name)

    def test_discovery_order_and_name_spelling_do_not_matter(self):
        forward = env(("NumPy", "2.3.4"), ("pandas", "3.0.5"), ("yfinance", "1.7.0"))
        backward = env(("yfinance", "1.7.0"), ("Pandas", "3.0.5"), ("numpy", "2.3.4"))
        assert forward == backward
        assert forward.fingerprint == backward.fingerprint
        assert forward.canonical_json() == backward.canonical_json()

    @pytest.mark.parametrize("drifted", [
        pytest.param(env(*BASE_PACKAGES, ("requests", "2.32.5")), id="package-added"),
        pytest.param(env(*BASE_PACKAGES[:2]), id="package-removed"),
        pytest.param(env(("numpy", "2.3.5"), *BASE_PACKAGES[1:]), id="version-changed"),
        pytest.param(env(*BASE_PACKAGES, version="3.11.4"), id="python-patch-changed"),
        pytest.param(env(*BASE_PACKAGES, implementation="PyPy"), id="implementation-changed"),
    ])
    def test_every_material_change_changes_the_environment_and_its_fingerprint(self, drifted):
        base = env(*BASE_PACKAGES)
        assert drifted != base
        assert drifted.fingerprint != base.fingerprint

    def test_a_duplicate_normalised_distribution_is_refused(self):
        with pytest.raises(IdentityError):
            env(("typing_extensions", "4.15.0"), ("typing-extensions", "4.15.0"))
        with pytest.raises(IdentityError):  # even with different versions
            env(("PyYAML", "6.0.2"), ("pyyaml", "6.0.3"))

    def test_the_constructor_accepts_only_canonical_input(self):
        with pytest.raises(IdentityError):
            DependencyEnvironment("CPython", "3.11.3", (("pandas", "3"), ("numpy", "2")))
        with pytest.raises(IdentityError):
            DependencyEnvironment("CPython", "3.11.3", (("NumPy", "2"),))
        with pytest.raises(IdentityError):
            DependencyEnvironment("CPython", "3.11.3", (("numpy", "2"), ("numpy", "2")))
        with pytest.raises(IdentityError):
            DependencyEnvironment("CPython", "", (("numpy", "2"),))
        with pytest.raises(IdentityError):
            DependencyEnvironment("CPython", "3.11.3", (("numpy", " 2"),))

    def test_the_fingerprint_is_sha256_of_the_documented_canonical_json(self):
        import hashlib

        environment = env(("numpy", "2.3.4"))
        expected = json.dumps({"packages": [["numpy", "2.3.4"]],
                               "python_implementation": "CPython",
                               "python_version": "3.11.3", "schema": DEPENDENCY_SCHEMA},
                              sort_keys=True, separators=(",", ":"))
        assert environment.canonical_json() == expected
        assert environment.fingerprint == hashlib.sha256(expected.encode()).hexdigest()

    def test_payload_round_trip(self):
        assert DependencyEnvironment.from_payload(DEPENDENCIES.to_payload()) == DEPENDENCIES

    @pytest.mark.parametrize("mutate", [
        pytest.param(lambda p: p.update(fingerprint="0" * 64), id="wrong-fingerprint"),
        pytest.param(lambda p: p.update(python_version="3.11.4"), id="python-identity"),
        pytest.param(lambda p: p.update(packages={"numpy": "2"}), id="package-map"),
        pytest.param(lambda p: p["packages"].append({"name": "numpy", "version": "2.3.4"}),
                     id="duplicate"),
        pytest.param(lambda p: p["packages"].reverse(), id="unsorted"),
        pytest.param(lambda p: p["packages"][0].update(extra=1), id="package-extra-key"),
        pytest.param(lambda p: p.update(schema="v0"), id="schema"),
        pytest.param(lambda p: p.update(extra="x"), id="extra-key"),
        pytest.param(lambda p: p.pop("fingerprint"), id="missing-key"),
    ])
    def test_a_malformed_payload_is_refused(self, mutate):
        payload = json.loads(json.dumps(DEPENDENCIES.to_payload()))
        mutate(payload)
        with pytest.raises(IdentityError):
            DependencyEnvironment.from_payload(payload)

    def test_capture_canonicalises_synthetic_distributions(self):
        captured = capture_dependency_environment(
            [FakeDistribution("Yfinance", "1.7.0"), FakeDistribution("numpy", "2.3.4"),
             FakeDistribution("pandas", "3.0.5")],
            python_implementation="CPython", python_version="3.11.3")
        assert captured == env(*BASE_PACKAGES)

    @pytest.mark.parametrize("distributions", [
        [FakeDistribution("a_b", "1"), FakeDistribution("A-B", "1")],
        [FakeDistribution(None, "1")],
        [FakeDistribution("numpy", None)],
    ], ids=["duplicate", "no-name", "no-version"])
    def test_capture_refuses_an_unreadable_environment(self, distributions):
        with pytest.raises(DependencyEnvironmentError):
            capture_dependency_environment(distributions, python_implementation="CPython",
                                           python_version="3.11.3")

    def test_capture_of_the_running_interpreter_has_no_machine_paths(self):
        payload = json.dumps(capture_dependency_environment().to_payload())
        assert str(REPO) not in payload and "site-packages" not in payload


# == activation manifest v2 =======================================================================


class TestManifestV2:
    def test_valid_round_trip(self):
        raw = encode(manifest_payload())
        manifest = ActivationManifest.from_bytes(raw)
        assert manifest.to_bytes() == raw
        assert manifest.dependency_environment == DEPENDENCIES
        assert manifest.m2_bound_paths == M2A_BOUND_PATHS

    def test_bound_paths_and_packages_are_recorded_in_full(self):
        payload = manifest_payload()
        assert payload["m2_bound_paths"] == [b.to_payload() for b in M2A_BOUND_PATHS]
        assert payload["dependency_environment"]["fingerprint"] == DEPENDENCIES.fingerprint
        assert payload["git_branch"] == "main" and payload["git_tree_clean"] is True
        assert payload["m2_preregistration_in_history"] is True

    def bound(self, path, sha):
        return [dict(b.to_payload(), sha256=sha) if b.path == path else b.to_payload()
                for b in M2A_BOUND_PATHS]

    @pytest.mark.parametrize("overrides", [
        pytest.param({"schema": "prospective_activation_v1"}, id="legacy-schema"),
        pytest.param({"schema": "prospective_activation_v3"}, id="unknown-schema"),
        pytest.param({"extra": 1}, id="unknown-key"),
        pytest.param({"m2_preregistration_git_commit": "b" * 40}, id="wrong-m2-commit"),
        pytest.param({"m2_preregistration_git_commit": "3dac810"}, id="short-m2-commit"),
        pytest.param({"future_validation_fingerprint": "0" * 64}, id="wrong-fv-fingerprint"),
        pytest.param({"future_validation_fingerprint": "79f7c4da"}, id="short-fv-fingerprint"),
        pytest.param({"collector_git_commit": "abc"}, id="short-collector"),
        pytest.param({"server_main_git_commit": "c" * 40}, id="server-main-differs"),
        pytest.param({"origin_main_git_commit": "c" * 40}, id="origin-main-differs"),
        pytest.param({"git_branch": "feature"}, id="not-main"),
        pytest.param({"git_tree_clean": False}, id="dirty"),
        pytest.param({"git_tree_clean": "true"}, id="clean-not-bool"),
        pytest.param({"m2_preregistration_in_history": False}, id="m2-not-in-history"),
        pytest.param({"collection_fingerprint": "xyz"}, id="invalid-collection-fingerprint"),
        pytest.param({"provenance_policy_fingerprint": 7}, id="provenance-wrong-type"),
        pytest.param({"m2_bound_paths": []}, id="no-bound-paths"),
        pytest.param({"m2_bound_paths": {"a": "b"}}, id="bound-paths-map"),
    ])
    def test_a_non_contract_manifest_is_refused(self, overrides):
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(encode(manifest_payload(**overrides)))

    @pytest.mark.parametrize("path", [DEFINITION_PATH, ENGINE_PATH, METHODOLOGY_PATH])
    def test_a_wrong_bound_file_hash_is_refused(self, path):
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(encode(manifest_payload(
                m2_bound_paths=self.bound(path, "0" * 64))))

    def test_unsorted_bound_paths_are_refused(self):
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(encode(manifest_payload(
                m2_bound_paths=[b.to_payload() for b in reversed(M2A_BOUND_PATHS)])))

    @pytest.mark.parametrize("key", sorted(ActivationManifest.FIELDS - {"schema"}))
    def test_every_field_is_required(self, key):
        payload = manifest_payload()
        payload.pop(key)
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(encode(payload))

    @pytest.mark.parametrize("mutate", [
        pytest.param(lambda d: d.update(fingerprint="0" * 64), id="wrong-dependency-fingerprint"),
        pytest.param(lambda d: d.update(packages={"numpy": "2.3.4"}), id="package-map"),
        pytest.param(lambda d: d["packages"].insert(0, dict(d["packages"][0])),
                     id="duplicate-package"),
        pytest.param(lambda d: d.update(python_version="3.12.0"), id="python-identity"),
        pytest.param(lambda d: d.update(python_implementation="PyPy"),
                     id="python-implementation"),
    ])
    def test_a_malformed_dependency_record_is_refused(self, mutate):
        payload = manifest_payload()
        mutate(payload["dependency_environment"])
        with pytest.raises(RecordError):
            ActivationManifest.from_bytes(encode(payload))


# == activation against real temporary repositories ===============================================


class TestActivationGit:
    def test_main_clean_origin_and_server_main_activates_and_records_the_proof(self, repo,
                                                                               tmp_path):
        store, manifest = activate_in(repo, tmp_path)
        current = head(repo)
        assert sorted(p.name for p in store.root.iterdir()) == ["activation.json",
                                                                "collect.lock"]
        assert manifest.collector_git_commit == manifest.origin_main_git_commit \
            == manifest.server_main_git_commit == current
        assert manifest.m2_preregistration_git_commit == M2A_PREREGISTRATION_COMMIT
        assert manifest.m2_bound_paths == M2A_BOUND_PATHS
        assert manifest.dependency_environment == DEPENDENCIES
        assert store.read_manifest() == manifest

    def test_a_later_operational_commit_on_main_activates(self, repo, tmp_path):
        commit_change(repo, "README.md")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        _, manifest = activate_in(repo, tmp_path)
        assert manifest.collector_git_commit == head(repo) != M2A_PREREGISTRATION_COMMIT

    def test_the_m2_commit_missing_is_refused(self, tmp_path):
        root = tmp_path / "fresh"
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        (root / "a.txt").write_text("a\n")
        git(root, "add", "a.txt")
        git(root, "commit", "-q", "-m", "a")
        git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        assert refused(root, tmp_path).reason == "m2_commit_missing"

    def test_an_m2_commit_outside_head_history_is_refused(self, repo, tmp_path):
        """Same bytes at the bound paths, but on an unrelated history."""
        git(repo, "checkout", "-q", "--orphan", "rewritten")
        git(repo, "commit", "-q", "-m", "orphan copy")
        git(repo, "branch", "-D", "main")
        git(repo, "branch", "-m", "main")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        error = refused(repo, tmp_path)
        assert error.reason == "m2_commit_not_in_history"
        assert error.details == ("m2_commit_not_in_history",)

    @pytest.mark.parametrize("path", [DEFINITION_PATH, ENGINE_PATH, METHODOLOGY_PATH],
                             ids=["definition", "engine", "methodology"])
    def test_a_bound_file_changed_since_the_preregistration_is_refused(self, repo, tmp_path,
                                                                       path):
        commit_change(repo, path)
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        error = refused(repo, tmp_path)
        assert error.reason == "m2_working_tree_bytes_mismatch"
        assert f"m2_working_tree_bytes_mismatch:{path}" in error.details
        assert "m2_bound_paths_changed" in error.details

    def test_a_bound_file_changed_and_restored_later_activates(self, repo, tmp_path):
        """Only the bytes matter: a change reverted in a later commit is not a change."""
        original = (repo / ENGINE_PATH).read_bytes()
        commit_change(repo, ENGINE_PATH)
        (repo / ENGINE_PATH).write_bytes(original)
        git(repo, "commit", "-q", "-am", "revert")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        activate_in(repo, tmp_path)

    def test_a_dirty_tree_is_refused(self, repo, tmp_path):
        (repo / "scratch.txt").write_text("untracked\n")
        assert refused(repo, tmp_path).reason == "dirty_repository"

    def test_an_uncommitted_bound_file_edit_is_refused(self, repo, tmp_path):
        (repo / DEFINITION_PATH).write_text("tampered\n")
        assert refused(repo, tmp_path).reason == "dirty_repository"

    def test_a_branch_other_than_main_is_refused(self, repo, tmp_path):
        git(repo, "checkout", "-q", "-b", "feature")
        assert refused(repo, tmp_path).reason == "not_on_main"

    def test_a_detached_head_is_refused(self, repo, tmp_path):
        git(repo, "checkout", "-q", "--detach")
        assert refused(repo, tmp_path).reason == "not_on_main"

    def test_head_behind_origin_main_is_refused(self, repo, tmp_path):
        behind = head(repo)
        commit_change(repo, "README.md")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(repo, "reset", "-q", "--hard", behind)
        assert refused(repo, tmp_path).reason == "head_not_origin_main"

    def test_head_ahead_of_origin_main_is_refused(self, repo, tmp_path):
        commit_change(repo, "README.md")
        assert refused(repo, tmp_path).reason == "head_not_origin_main"

    def test_a_server_main_that_differs_is_refused(self, repo, tmp_path):
        assert refused(repo, tmp_path, server="e" * 40).reason == "server_main_mismatch"

    def test_a_missing_origin_main_is_refused(self, repo, tmp_path):
        git(repo, "update-ref", "-d", "refs/remotes/origin/main")
        assert refused(repo, tmp_path).reason == "origin_main_missing"

    @pytest.mark.parametrize("kwargs", [
        {"server": "abc123"}, {"server": "E" * 40}, {"collector": "3dac810"},
        {"server": "main"}, {"server": "origin/main"},
    ])
    def test_a_malformed_or_symbolic_sha_is_refused(self, repo, tmp_path, kwargs):
        assert refused(repo, tmp_path, **kwargs).reason == "invalid_commit"

    def test_a_collector_commit_other_than_head_is_refused(self, repo, tmp_path):
        error = refused(repo, tmp_path, collector="f" * 40)
        assert error.reason == "collector_commit_mismatch"

    def test_a_directory_that_is_not_a_repository_is_unverified(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(ActivationRefused) as caught:
            activate(build_prospective_store(tmp_path / "prospective" / "v1"),
                     collector_git_commit="a" * 40, server_main_git_commit="a" * 40,
                     repository=GitRepositoryProbe(plain),
                     dependency_environment=lambda: DEPENDENCIES, now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "repository_unverified"
        assert not (tmp_path / "prospective").exists()

    def test_a_wrong_live_validation_fingerprint_is_refused(self, repo, tmp_path,
                                                            monkeypatch):
        other = replace(FUTURE_VALIDATION_V1,
                        runner_version=FUTURE_VALIDATION_V1.runner_version + 1)
        assert other.fingerprint != M2A_FUTURE_VALIDATION_FINGERPRINT
        monkeypatch.setattr("src.application.prospective.FUTURE_VALIDATION_V1", other)
        error = refused(repo, tmp_path)
        assert error.reason == "future_validation_fingerprint_mismatch"

    def test_a_dependency_snapshot_error_is_refused_before_writing(self, repo, tmp_path):
        def unreadable():
            raise DependencyEnvironmentError("two distributions normalise to one name")

        with pytest.raises(ActivationRefused) as caught:
            activate(build_prospective_store(tmp_path / "prospective" / "v1"),
                     collector_git_commit=head(repo), server_main_git_commit=head(repo),
                     repository=GitRepositoryProbe(repo), dependency_environment=unreadable,
                     now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "dependency_environment_unavailable"
        assert not (tmp_path / "prospective").exists()

    def test_activation_captures_the_dependency_environment_once_after_every_git_check(
            self, repo, tmp_path):
        calls = []

        def source():
            calls.append(1)
            return DEPENDENCIES

        (repo / "scratch.txt").write_text("x\n")
        with pytest.raises(ActivationRefused):
            activate(build_prospective_store(tmp_path / "p" / "v1"),
                     collector_git_commit=head(repo), server_main_git_commit=head(repo),
                     repository=GitRepositoryProbe(repo), dependency_environment=source,
                     now=lambda: ACTIVATED_AT)
        assert calls == []
        (repo / "scratch.txt").unlink()
        activate(build_prospective_store(tmp_path / "q" / "v1"),
                 collector_git_commit=head(repo), server_main_git_commit=head(repo),
                 repository=GitRepositoryProbe(repo), dependency_environment=source,
                 now=lambda: ACTIVATED_AT)
        assert calls == [1]

    def test_a_second_activation_is_refused_and_changes_nothing(self, repo, tmp_path):
        store, _ = activate_in(repo, tmp_path)
        before = {p.name: p.read_bytes() for p in store.root.iterdir()}
        with pytest.raises(ActivationRefused) as caught:
            activate_in(repo, tmp_path)
        assert caught.value.reason == "already_activated"
        assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before

    def test_an_ambiguous_directory_fsync_fails_safe_and_a_retry_is_refused(
            self, repo, tmp_path, monkeypatch):
        import src.prospective.store as store_module

        real = store_module._fsync_directory

        def failing(path):
            raise OSError("EIO on directory fsync")

        monkeypatch.setattr(store_module, "_fsync_directory", failing)
        with pytest.raises(ActivationRefused) as caught:
            activate_in(repo, tmp_path)
        assert caught.value.reason == "activation_write_failed"
        monkeypatch.setattr(store_module, "_fsync_directory", real)
        with pytest.raises(ActivationRefused) as again:
            activate_in(repo, tmp_path)
        assert again.value.reason == "already_activated"
        root = tmp_path / "prospective" / "v1"
        assert sorted(p.name for p in root.iterdir()) == ["activation.json", "collect.lock"]


class TestGitProbe:
    def test_malformed_objects_and_paths_have_no_blob(self, repo):
        probe = GitRepositoryProbe(repo)
        commit = M2A_PREREGISTRATION_COMMIT
        assert probe.blob_sha256(commit, "src/research") is None  # a tree, not a blob
        assert probe.blob_sha256(commit, "no/such/file.py") is None
        assert probe.blob_sha256("f" * 40, DEFINITION_PATH) is None
        assert probe.blob_sha256(commit, DEFINITION_PATH) == BOUND[DEFINITION_PATH].sha256

    def test_commit_exists_is_true_only_for_commit_objects(self, repo):
        probe = GitRepositoryProbe(repo)
        tree = git(repo, "rev-parse", f"{M2A_PREREGISTRATION_COMMIT}^{{tree}}")
        assert probe.commit_exists(M2A_PREREGISTRATION_COMMIT)
        assert not probe.commit_exists(tree)
        assert not probe.commit_exists("f" * 40)

    def test_a_bound_path_missing_at_the_commit_is_a_binding_mismatch(self, repo, monkeypatch):
        missing = (*M2A_BOUND_PATHS, BoundPath("src/research/not_there.py", "0" * 64))
        monkeypatch.setattr("src.application.prospective.M2A_BOUND_PATHS", missing)
        found = m2_binding_mismatches(GitRepositoryProbe(repo))
        assert "m2_preregistered_bytes_mismatch:src/research/not_there.py" in found
        assert "m2_working_tree_bytes_mismatch:src/research/not_there.py" in found

    def test_a_symlinked_bound_file_is_not_its_bytes(self, repo):
        target = repo / DEFINITION_PATH
        copy = repo / "elsewhere.py"
        copy.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(copy)
        assert GitRepositoryProbe(repo).working_file_sha256(DEFINITION_PATH) is None

    def test_branch_and_origin_main(self, repo):
        probe = GitRepositoryProbe(repo)
        assert probe.current_branch() == "main"
        assert probe.origin_main() == head(repo)
        git(repo, "update-ref", "-d", "refs/remotes/origin/main")
        assert probe.origin_main() is None

    def test_the_probe_never_contacts_a_remote(self, repo):
        """The probe source names no fetch, pull, ls-remote, push or remote update."""
        source = (REPO / "src" / "prospective" / "environment.py").read_text()
        for verb in ('"fetch"', '"pull"', '"ls-remote"', '"push"', '"remote"', '"clone"'):
            assert verb not in source


# == collection-time dependency drift ===========================================================


def activated_spy(tmp_path) -> object:
    store = build_prospective_store(tmp_path / "v1")
    activate(store, collector_git_commit=COLLECTOR_SHA, server_main_git_commit=COLLECTOR_SHA,
             repository=ProbeDouble(), dependency_environment=lambda: DEPENDENCIES,
             now=lambda: ACTIVATED_AT, definition=SPY_ONLY)
    return store


DRIFTS = {
    "package-added": DependencyEnvironment.from_distributions(
        "CPython", "3.11.3", (*DEPENDENCIES.packages, ("requests", "2.32.5"))),
    "package-removed": DependencyEnvironment("CPython", "3.11.3", DEPENDENCIES.packages[1:]),
    "version-changed": DependencyEnvironment(
        "CPython", "3.11.3", (("numpy", "2.3.5"), *DEPENDENCIES.packages[1:])),
    "python-patch": DependencyEnvironment("CPython", "3.11.4", DEPENDENCIES.packages),
    "implementation": DependencyEnvironment("PyPy", "3.11.3", DEPENDENCIES.packages),
}


class TestCollectionDrift:
    def test_the_exact_environment_proceeds(self, tmp_path):
        store = activated_spy(tmp_path)
        provider = SessionProvider()
        report = collect(store, provider_factory=lambda: provider, now=Clock(TUESDAY_RUN),
                         definition=SPY_ONLY, repository=ProbeDouble(),
                         dependency_environment=lambda: DEPENDENCIES)
        assert report.outcome == "completed"
        assert len(provider.calls) == 1

    def test_reordered_discovery_of_the_same_set_proceeds(self, tmp_path):
        store = activated_spy(tmp_path)
        reordered = DependencyEnvironment.from_distributions(
            "CPython", "3.11.3", [(name.upper(), version) for name, version
                                  in reversed(DEPENDENCIES.packages)])
        report = collect(store, provider_factory=SessionProvider, now=Clock(TUESDAY_RUN),
                         definition=SPY_ONLY, repository=ProbeDouble(),
                         dependency_environment=lambda: reordered)
        assert report.outcome == "completed"

    @pytest.mark.parametrize("name", sorted(DRIFTS))
    def test_drift_refuses_before_any_provider_and_writes_no_claim(self, tmp_path, name):
        store = activated_spy(tmp_path)
        built = []
        provider = SessionProvider()
        report = collect(store, provider_factory=lambda: built.append(1) or provider,
                         now=Clock(TUESDAY_RUN), definition=SPY_ONLY,
                         repository=ProbeDouble(),
                         dependency_environment=lambda: DRIFTS[name])
        assert report.outcome == "dependency_environment_mismatch"
        assert built == [] and provider.calls == []
        assert not store.ledger_exists()
        log = store.read_run_log()
        assert len(log) == 1 and isinstance(log[0], RunRecord)
        assert log[0].run_status is RunStatus.DEPENDENCY_ENVIRONMENT_MISMATCH
        assert log[0].symbols == ()
        assert not any(isinstance(entry, RunStart) for entry in log)

    def test_an_unreadable_environment_refuses_as_unverified(self, tmp_path):
        store = activated_spy(tmp_path)

        def unreadable():
            raise DependencyEnvironmentError("duplicate")

        built = []
        report = collect(store, provider_factory=lambda: built.append(1),
                         now=Clock(TUESDAY_RUN), definition=SPY_ONLY,
                         repository=ProbeDouble(), dependency_environment=unreadable)
        assert report.outcome == "dependency_environment_unverified"
        assert built == [] and not store.ledger_exists()

    def test_a_refusal_keeps_provenance_ok_and_health_reports_it(self, tmp_path):
        store = activated_spy(tmp_path)
        collect(store, provider_factory=SessionProvider, now=Clock(TUESDAY_RUN),
                definition=SPY_ONLY, repository=ProbeDouble(),
                dependency_environment=lambda: DRIFTS["version-changed"])
        report = health(store, definition=SPY_ONLY, repository=ProbeDouble(),
                        dependency_environment=lambda: DRIFTS["version-changed"])
        assert report.dependency_environment == "mismatch"
        assert report.runs_refused_dependencies == 1
        assert report.provenance.status == "ok"
        fine = health(store, definition=SPY_ONLY, repository=ProbeDouble(),
                      dependency_environment=lambda: DEPENDENCIES)
        assert (fine.dependency_environment, fine.m2_binding) == ("ok", "ok")

    def test_drift_after_completed_runs_stops_the_next_run(self, tmp_path):
        store = activated_spy(tmp_path)
        provider = SessionProvider()
        first = collect(store, provider_factory=lambda: provider, now=Clock(TUESDAY_RUN),
                        definition=SPY_ONLY, repository=ProbeDouble(),
                        dependency_environment=lambda: DEPENDENCIES)
        assert first.outcome == "completed"
        calls = len(provider.calls)
        second = collect(store, provider_factory=lambda: provider,
                         now=Clock(et(2026, 10, 7, 7)), definition=SPY_ONLY,
                         repository=ProbeDouble(),
                         dependency_environment=lambda: DRIFTS["package-added"])
        assert second.outcome == "dependency_environment_mismatch"
        assert len(provider.calls) == calls

    def test_the_cli_has_no_dependency_or_binding_bypass(self):
        parser = build_parser()
        [commands] = [a for a in parser._actions if a.dest == "command"]
        options = {o for choice in commands.choices.values() for a in choice._actions
                   for o in a.option_strings}
        assert options == {"-h", "--help", "--collector-git-commit", "--server-main-sha"}

    @pytest.mark.parametrize("flag", [
        "--force", "--ignore-drift", "--skip-git-check", "--skip-m2-check",
        "--m2-preregistration-git-commit", "--m2-commit", "--validation-fingerprint",
        "--no-dependency-check",
    ])
    def test_bypass_options_are_usage_errors(self, flag, tmp_path):
        argv = ["activate", "--collector-git-commit", COLLECTOR_SHA, "--server-main-sha",
                COLLECTOR_SHA, flag, M2A_PREREGISTRATION_COMMIT]
        out, err = io.StringIO(), io.StringIO()
        assert main(argv, root=tmp_path / "v1", stdout=out, stderr=err,
                    repository=ProbeDouble()) == 2
        assert main(["collect", flag], root=tmp_path / "v1", stdout=out, stderr=err) == 2
        assert not (tmp_path / "v1").exists()

    def test_no_production_module_reads_an_environment_variable(self):
        for path in [*(REPO / "src" / "prospective").glob("*.py"),
                     REPO / "src" / "application" / "prospective.py",
                     REPO / "src" / "application" / "future_validation.py",
                     REPO / "src" / "cli" / "prospective.py",
                     REPO / "src" / "cli" / "future_validation.py"]:
            module = ast.parse(path.read_text())
            names = {n.attr for n in ast.walk(module) if isinstance(n, ast.Attribute)} | {
                n.id for n in ast.walk(module) if isinstance(n, ast.Name)}
            assert not names & {"environ", "getenv", "environb", "putenv"}, path.name


# == future-validation binding =====================================================================


class Level3Sentinel:
    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Level 3 was read")


@pytest.fixture
def matured(root_templates, tmp_path):
    return build_prospective_store(copy_root(root_templates, "matured", tmp_path))


def opened_status(store, repository):
    return status(store, definition=SMALL, pinned_fingerprint=SMALL.fingerprint,
                  collection=SPY_ONLY, repository=repository)


def opened_run(store, repository):
    return run(store, definition=SMALL, pinned_fingerprint=SMALL.fingerprint,
               collection=SPY_ONLY, repository=repository, now=lambda: AFTER_E1)


class TestFutureValidationBinding:
    def test_a_bound_repository_passes_to_the_normal_gates(self, matured, repo):
        report = opened_status(matured, GitRepositoryProbe(repo))
        assert report.m2_binding == "ok"
        assert report.identity_mismatches == ()
        assert report.validity == "ok"
        assert binding_mismatches(matured.read_manifest(), GitRepositoryProbe(repo)) == ()

    def test_a_later_operational_head_with_unchanged_science_still_opens(self, matured, repo):
        commit_change(repo, "src/application/future_validation.py")
        assert opened_status(matured, GitRepositoryProbe(repo)).m2_binding == "ok"
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.completed, outcome

    @pytest.mark.parametrize("path", [DEFINITION_PATH, ENGINE_PATH, METHODOLOGY_PATH],
                             ids=["definition", "engine", "methodology"])
    def test_changed_science_refuses_status_and_run_before_level_three(
            self, matured, repo, monkeypatch, path):
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        commit_change(repo, path)
        report = opened_status(matured, GitRepositoryProbe(repo))
        assert (report.m2_binding, report.validity) == ("mismatch", "invalid")
        assert f"m2_working_tree_bytes_mismatch:{path}" in report.identity_mismatches
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.outcome == "refused"
        assert outcome.detail[0] == "m2_binding_mismatch"
        assert "m2_bound_paths_changed" in outcome.detail
        assert sentinel.calls == 0
        assert not (matured.root / "validation").exists() or not any(
            (matured.root / "validation").rglob("unlock.json"))

    def test_a_dirty_tree_refuses(self, matured, repo, monkeypatch):
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        (repo / "notes.txt").write_text("x\n")
        assert "dirty_repository" in opened_status(matured, GitRepositoryProbe(repo)) \
            .identity_mismatches
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.detail == ("m2_binding_mismatch", "dirty_repository")
        assert sentinel.calls == 0

    def test_an_m2_commit_outside_history_refuses(self, matured, tmp_path):
        root = tmp_path / "fresh"
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        (root / "a.txt").write_text("a\n")
        git(root, "add", "a.txt")
        git(root, "commit", "-q", "-m", "a")
        outcome = opened_run(matured, GitRepositoryProbe(root))
        assert outcome.detail == ("m2_binding_mismatch", "m2_commit_missing")

    def test_a_wrong_prereg_sha_in_the_manifest_refuses(self, matured, monkeypatch):
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        payload = json.loads(matured.manifest_path.read_bytes())
        payload["m2_preregistration_git_commit"] = "b" * 40
        matured.manifest_path.write_bytes(encode(payload))
        report = opened_status(matured, ProbeDouble())
        assert (report.activation, report.validity) == ("invalid_manifest", "invalid")
        assert opened_run(matured, ProbeDouble()).detail == ("invalid_manifest",)
        assert sentinel.calls == 0

    def test_a_manifest_naming_another_validation_fingerprint_refuses(self, matured,
                                                                     monkeypatch):
        """The live definition and the activation must name one fingerprint."""
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        other = replace(FUTURE_VALIDATION_V1, runner_version=FUTURE_VALIDATION_V1.runner_version
                        + 1)
        monkeypatch.setattr(future_validation, "FUTURE_VALIDATION_V1", other)
        report = opened_status(matured, ProbeDouble())
        assert "manifest_future_validation_fingerprint" in report.identity_mismatches
        outcome = opened_run(matured, ProbeDouble())
        assert outcome.detail[:2] == ("m2_binding_mismatch",
                                      "manifest_future_validation_fingerprint")
        assert sentinel.calls == 0

    def test_an_unanswerable_repository_refuses_as_unavailable(self, matured):
        report = opened_status(matured, ProbeDouble(fail=True))
        assert (report.m2_binding, report.validity) == ("unavailable", "invalid")
        assert opened_run(matured, ProbeDouble(fail=True)).detail == (
            "m2_binding_mismatch", "repository_unverified")

    def test_an_existing_unlock_or_result_is_not_rederived_without_the_binding(
            self, matured, repo, monkeypatch):
        """Completed openings re-derive Level 3 to verify; a broken binding stops that too."""
        assert opened_run(matured, GitRepositoryProbe(repo)).completed
        sentinel = Level3Sentinel()
        monkeypatch.setattr(future_validation, "_level_three_evidence", sentinel)
        commit_change(repo, ENGINE_PATH)
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.outcome == "refused" and outcome.detail[0] == "m2_binding_mismatch"
        assert sentinel.calls == 0
        unlock = next((matured.root / "validation").rglob("unlock.json"))
        os.remove(next((matured.root / "validation").rglob("result.json")))
        os.remove(next((matured.root / "validation").rglob("report.md")))
        outcome = opened_run(matured, GitRepositoryProbe(repo))
        assert outcome.detail[0] == "m2_binding_mismatch" and unlock.exists()
        assert sentinel.calls == 0

    def test_the_binding_runs_before_anything_is_captured(self, matured, monkeypatch):
        captured = []
        real = future_validation._capture_locked
        monkeypatch.setattr(future_validation, "_capture_locked",
                            lambda *a, **k: captured.append(1) or real(*a, **k))
        opened_status(matured, ProbeDouble(clean=False))
        opened_run(matured, ProbeDouble(clean=False))
        assert captured == []

    def test_the_cli_status_prints_the_binding(self, matured):
        from src.cli.future_validation import main as validation_main

        out = io.StringIO()
        validation_main(["status"], root=matured.root, definition=SMALL,
                        pinned_fingerprint=SMALL.fingerprint, collection=SPY_ONLY,
                        repository=ProbeDouble(unchanged=False), stdout=out)
        assert "m2_binding=mismatch" in out.getvalue()


# == R1: one manifest identity per future-validation operation ====================================


class Order:
    """Records the call order of instrumented runner stages."""

    def __init__(self, monkeypatch):
        self.calls: list[str] = []
        for name in ("binding_mismatches", "_capture_locked", "_finish_report", "_from_unlock",
                     "_derive_result"):
            self._wrap(monkeypatch, name)
        monkeypatch.setattr(future_validation, "_level_three_evidence", self._level_three)
        self.real_level_three = None

    def _wrap(self, monkeypatch, name):
        real = getattr(future_validation, name)

        def wrapped(*args, **kwargs):
            self.calls.append(name)
            return real(*args, **kwargs)

        monkeypatch.setattr(future_validation, name, wrapped)

    def _level_three(self, *args, **kwargs):
        self.calls.append("_level_three_evidence")
        raise AssertionError("Level 3 was read")

    def __contains__(self, name):
        return name in self.calls


class FlippingProbe(ProbeDouble):
    """Passes the binding on the first ``repository_state`` call, then turns dirty."""

    def repository_state(self):
        state = super().repository_state()
        self.clean = False
        return state


def manifest_sequence(monkeypatch, store, steps):
    """``read_manifest`` performs ``steps[i]`` on its i-th call (the last step repeats).

    A step is ``"corrupt"`` (raise ManifestCorruption), ``"absent"`` (return None),
    ``"real"`` (read the file) or a callable run before reading the file.
    """
    from src.prospective import ManifestCorruption, ProspectiveStore

    real = ProspectiveStore.read_manifest
    count = {"n": 0}

    def read(self):
        step = steps[min(count["n"], len(steps) - 1)]
        count["n"] += 1
        if step == "corrupt":
            raise ManifestCorruption("transient")
        if step == "absent":
            return None
        if callable(step):
            step(self)
        return real(self)

    monkeypatch.setattr(ProspectiveStore, "read_manifest", read)
    return count


def rewrite_manifest(store, mutate):
    payload = json.loads(store.manifest_path.read_bytes())
    mutate(payload)
    store.manifest_path.write_bytes(encode(payload))


def later_activation(store):
    rewrite_manifest(store, lambda p: p.update(activated_at="2026-10-05T19:00:01+00:00"))


def completed(store):
    assert opened_run(store, ProbeDouble()).completed
    return {path.name: path.read_bytes() for path in (store.root / "validation").rglob("*")
            if path.is_file()}


def drop_result(store):
    for name in ("result.json", "report.md"):
        next((store.root / "validation").rglob(name)).unlink()


def unverified(detail, artifacts):
    """A completed result's refusal keeps M2A's ``result_unverifiable`` prefix."""
    if artifacts == "complete":
        assert detail[0] == "result_unverifiable", detail
        return detail[1:]
    return detail


def validation_files(store):
    base = store.root / "validation"
    return {} if not base.exists() else {
        path.name: path.read_bytes() for path in base.rglob("*") if path.is_file()}


class TestManifestIdentityPerOperation:
    def test_r1_unreadable_then_valid_manifest_with_a_broken_binding_never_opens(
            self, matured, monkeypatch):
        """The reviewer's race: unreadable at the pre-check, valid at capture."""
        order = Order(monkeypatch)
        manifest_sequence(monkeypatch, matured, ["corrupt", "real"])
        outcome = opened_run(matured, ProbeDouble(clean=False, unchanged=False))
        assert outcome.outcome == "refused" and outcome.detail == ("invalid_manifest",)
        assert order.calls == []
        assert validation_files(matured) == {}

    @pytest.mark.parametrize("artifacts", ["complete", "unlock-only"])
    def test_r1_with_existing_artifacts(self, matured, monkeypatch, artifacts):
        before = completed(matured)
        if artifacts == "unlock-only":
            drop_result(matured)
            before = validation_files(matured)
        order = Order(monkeypatch)
        manifest_sequence(monkeypatch, matured, ["corrupt", "real"])
        outcome = opened_run(matured, ProbeDouble(clean=False))
        assert outcome.detail == ("invalid_manifest",)
        assert order.calls == []
        assert validation_files(matured) == before  # no result, no report regenerated

    def test_a_valid_unchanged_manifest_with_a_valid_binding_opens(self, matured, monkeypatch):
        order = Order(monkeypatch)
        monkeypatch.setattr(future_validation, "_level_three_evidence",
                            TestManifestIdentityPerOperation._real_level_three)
        outcome = opened_run(matured, ProbeDouble())
        assert outcome.completed
        first_capture = order.calls.index("_capture_locked")
        assert order.calls.count("binding_mismatches") == 2  # before and after capture
        assert order.calls[0] == "binding_mismatches"
        assert order.calls.index("binding_mismatches", 1) > first_capture
        assert order.calls.index("binding_mismatches", 1) < order.calls.index("_derive_result")

    _real_level_three = staticmethod(future_validation._level_three_evidence)

    @pytest.mark.parametrize("steps, detail", [
        (["absent"], ("not_activated",)),
        (["corrupt"], ("invalid_manifest",)),
    ], ids=["absent-throughout", "unreadable-throughout"])
    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_an_unusable_manifest_refuses_before_any_stage(self, matured, monkeypatch, steps,
                                                           detail, artifacts):
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        before = validation_files(matured)
        order = Order(monkeypatch)
        manifest_sequence(monkeypatch, matured, steps)
        outcome = opened_run(matured, ProbeDouble())
        assert (outcome.outcome, outcome.detail) == ("refused", detail)
        assert order.calls == [] and validation_files(matured) == before

    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_an_absent_manifest_on_disk_is_a_controlled_refusal(self, matured, artifacts):
        """No NotActivatedError leaks, whatever validation artifacts exist."""
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        matured.manifest_path.unlink()
        assert opened_run(matured, ProbeDouble()).detail == ("not_activated",)
        assert opened_status(matured, ProbeDouble()).activation == "not_activated"

    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_a_malformed_manifest_on_disk_refuses_before_any_stage(self, matured, monkeypatch,
                                                                   artifacts):
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        matured.manifest_path.write_bytes(matured.manifest_path.read_bytes()[:-10])
        order = Order(monkeypatch)
        assert opened_run(matured, ProbeDouble()).detail == ("invalid_manifest",)
        assert order.calls == []

    def _transition(self, change):
        """A step that performs ``change`` once, on the second read only."""
        done = {"n": 0}

        def step(store):
            done["n"] += 1
            if done["n"] == 1:
                change(store)
        return step

    @pytest.mark.parametrize("change, name", [
        (later_activation, "different-valid"),
        (lambda s: s.manifest_path.unlink(), "deleted"),
        (lambda s: s.manifest_path.write_bytes(
            s.manifest_path.read_bytes().replace(b",", b", ", 1)), "equivalent-bytes"),
        (lambda s: rewrite_manifest(s, lambda p: p.update(
            m2_preregistration_git_commit="b" * 40)), "bad-binding"),
    ], ids=lambda value: value if isinstance(value, str) else "")
    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_a_manifest_changed_after_validation_refuses_before_any_later_stage(
            self, matured, monkeypatch, change, name, artifacts):
        """Valid at the binding check, then changed before capture/recapture."""
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        before = validation_files(matured)
        order = Order(monkeypatch)
        real_capture = future_validation._capture_locked
        changed = {"done": False}

        def capture_after_change(store, recorded=None):
            if not changed["done"]:
                changed["done"] = True
                change(store)
            return real_capture(store, recorded)

        monkeypatch.setattr(future_validation, "_capture_locked", capture_after_change)
        outcome = opened_run(matured, ProbeDouble())
        assert outcome.outcome == "refused"
        detail = unverified(outcome.detail, artifacts)
        assert detail[0] in ("manifest_changed", "snapshot_mismatch"), outcome.detail
        assert "_level_three_evidence" not in order
        assert "_derive_result" not in order
        assert validation_files(matured) == before

    @pytest.mark.parametrize("artifacts", ["none", "complete", "unlock-only"])
    def test_a_repository_that_turns_dirty_after_the_first_check_refuses(
            self, matured, monkeypatch, artifacts):
        """L: the binding is re-checked against the captured manifest before any later stage."""
        if artifacts != "none":
            completed(matured)
            if artifacts == "unlock-only":
                drop_result(matured)
        before = validation_files(matured)
        order = Order(monkeypatch)
        outcome = opened_run(matured, FlippingProbe())
        assert outcome.outcome == "refused"
        assert unverified(outcome.detail, artifacts) == ("m2_binding_mismatch",
                                                         "dirty_repository")
        assert "_level_three_evidence" not in order and "_derive_result" not in order
        assert validation_files(matured) == before

    def test_correct_binding_still_verifies_a_completed_result_and_recovers_an_unlock(
            self, matured):
        files = completed(matured)
        assert opened_run(matured, ProbeDouble()).outcome == "already_complete"
        drop_result(matured)
        assert opened_run(matured, ProbeDouble()).outcome == "completed_after_unlock"
        assert validation_files(matured) == files

    def test_status_never_reports_ok_for_a_manifest_it_did_not_bind(self, matured,
                                                                     monkeypatch):
        real_capture = future_validation._capture_locked

        def capture_after_change(store, recorded=None):
            later_activation(store)
            return real_capture(store, recorded)

        monkeypatch.setattr(future_validation, "_capture_locked", capture_after_change)
        report = opened_status(matured, ProbeDouble())
        assert report.m2_binding != "ok"
        assert report.validity == "invalid"
        assert "manifest_changed" in report.identity_mismatches

    def test_status_rechecks_the_repository_after_capture(self, matured):
        report = opened_status(matured, FlippingProbe())
        assert (report.m2_binding, report.validity) == ("mismatch", "invalid")
        assert "dirty_repository" in report.identity_mismatches

    def test_status_with_an_unreadable_then_valid_manifest_reports_invalid(self, matured,
                                                                          monkeypatch):
        manifest_sequence(monkeypatch, matured, ["corrupt", "real"])
        report = opened_status(matured, ProbeDouble())
        assert (report.activation, report.validity) == ("invalid_manifest", "invalid")
        assert report.m2_binding != "ok"


# == health ==================================================================================


class TestHealthBinding:
    def test_before_activation_the_binding_is_reported_and_dependencies_unavailable(
            self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        report = health(store, repository=ProbeDouble())
        assert (report.status, report.m2_binding, report.dependency_environment) == (
            "not_activated", "ok", "unavailable")
        assert health(store, repository=ProbeDouble(unchanged=False)).m2_binding == "mismatch"
        assert health(store, repository=ProbeDouble(fail=True)).m2_binding == "unavailable"
        assert not store.root_exists()

    @pytest.mark.parametrize("kwargs, expected", [
        ({}, 0),
        ({"repository": ProbeDouble(unchanged=False)}, 1),
        ({"repository": ProbeDouble(fail=True)}, 1),
        ({"dependency_environment": lambda: DRIFTS["python-patch"]}, 1),
    ], ids=["bound", "binding-mismatch", "binding-unavailable", "dependency-drift"])
    def test_a_binding_or_dependency_problem_makes_health_exit_one(self, tmp_path, kwargs,
                                                                  expected):
        store = build_prospective_store(tmp_path / "v1")
        activate(store, collector_git_commit=COLLECTOR_SHA,
                 server_main_git_commit=COLLECTOR_SHA, repository=ProbeDouble(),
                 now=lambda: ACTIVATED_AT)
        out = io.StringIO()
        arguments = dict(repository=ProbeDouble(), dependency_environment=lambda: DEPENDENCIES)
        arguments.update(kwargs)
        code = main(["health"], root=store.root, stdout=out, stderr=io.StringIO(), **arguments)
        assert code == expected, out.getvalue()
        text = out.getvalue()
        assert ("m2_binding=ok" in text) == ("repository" not in kwargs)
        assert ("dependency_environment=ok" in text) == ("dependency_environment" not in kwargs)
