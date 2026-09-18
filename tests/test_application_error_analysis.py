"""Phase 13A application orchestration, offline: read the synthetic frozen source through
the artifact store, verify, diagnose, write four files, prove immutability -- no provider,
no network, nothing under the repository's data/."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.application import (
    DEFAULT_ERROR_ANALYSIS_SOURCE,
    DEFAULT_RESEARCH_ROOT,
    ERROR_ANALYSIS_LABEL,
    ErrorAnalysisRun,
    run_error_analysis_study,
)
from src.application import error_analysis as application_module
from src.application.errors import ApplicationError, FailureKind
from src.research.error_analysis import SOURCE_ARTIFACT_NAMES, SOURCE_OBSERVATIONS
from src.research.error_analysis_render import (
    ARTIFACT_DIAGNOSTICS,
    ARTIFACT_EPISODES,
    ARTIFACT_MANIFEST,
    ARTIFACT_NAMES,
    ARTIFACT_REPORT,
)
from tests.error_analysis_fixtures import build_texts, definition_for, parse_csv, sha256, write_source

UTC = timezone.utc
GIT = "89abcdef0123456789abcdef0123456789abcdef"
CLOCK = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
REPO_DATA = DEFAULT_RESEARCH_ROOT.parent


def clock_at(*instants):
    remaining = list(instants)

    def now():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return now


@pytest.fixture
def source(tmp_path):
    texts = build_texts()
    directory = tmp_path / "frozen" / "baseline_study_v1"
    write_source(directory, texts)
    return directory, texts, definition_for(texts)


def run(tmp_path, source, **kwargs):
    directory, _, definition = source
    return run_error_analysis_study(git_commit=GIT, source_root=directory, out_root=tmp_path / "out",
                                    now=clock_at(CLOCK), definition=definition, **kwargs)


class TestArtifacts:
    def test_exactly_four_files_in_the_labelled_directory(self, tmp_path, source):
        result = run(tmp_path, source)
        assert isinstance(result, ErrorAnalysisRun)
        assert result.output_dir == tmp_path / "out" / "error_analysis_v1"
        assert sorted(p.name for p in result.output_dir.iterdir()) == sorted(ARTIFACT_NAMES)

    def test_file_hashes_match_the_run_and_the_manifest(self, tmp_path, source):
        result = run(tmp_path, source)
        for name in ARTIFACT_NAMES:
            assert hashlib.sha256(result.path(name).read_bytes()).hexdigest() == result.artifact_sha256[name]
        manifest = json.loads(result.path(ARTIFACT_MANIFEST).read_text(encoding="utf-8"))
        for name in (ARTIFACT_DIAGNOSTICS, ARTIFACT_EPISODES, ARTIFACT_REPORT):
            assert manifest["artifacts"][name]["sha256"] == result.artifact_sha256[name]
        assert ARTIFACT_MANIFEST not in manifest["artifacts"]
        assert result.artifact_sha256[ARTIFACT_MANIFEST] not in result.path(ARTIFACT_MANIFEST).read_text()
        assert manifest == dict(result.manifest)

    def test_manifest_records_source_lineage(self, tmp_path, source):
        _, texts, definition = source
        result = run(tmp_path, source)
        assert dict(result.source_sha256) == {n: sha256(texts[n]) for n in SOURCE_ARTIFACT_NAMES}
        assert result.manifest["source"]["artifact_sha256"] == dict(definition.source_hashes)
        assert result.manifest["git_commit"] == GIT
        assert result.manifest["generated_at"] == CLOCK.isoformat()

    def test_csvs_parse(self, tmp_path, source):
        result = run(tmp_path, source)
        rows = parse_csv(result.path(ARTIFACT_DIAGNOSTICS).read_text(encoding="utf-8"))
        assert len(rows) == len(result.result.diagnostics)
        assert len(parse_csv(result.path(ARTIFACT_EPISODES).read_text(encoding="utf-8"))) == len(result.result.episodes)


class TestImmutabilityAndSafety:
    def test_source_bytes_are_unchanged_after_the_run(self, tmp_path, source):
        directory, texts, _ = source
        before = {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in SOURCE_ARTIFACT_NAMES}
        run(tmp_path, source)
        after = {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in SOURCE_ARTIFACT_NAMES}
        assert before == after == {n: sha256(texts[n]) for n in SOURCE_ARTIFACT_NAMES}
        assert sorted(p.name for p in directory.iterdir()) == sorted(SOURCE_ARTIFACT_NAMES)

    def test_output_inside_or_equal_to_source_is_refused(self, tmp_path, source):
        directory, _, definition = source
        with pytest.raises(ApplicationError) as excinfo:
            run_error_analysis_study(git_commit=GIT, source_root=directory, out_root=directory,
                                     now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.REQUEST
        # An output directory that would *contain* the source is refused too.
        nested_source = tmp_path / "x" / "error_analysis_v1" / "inner"
        write_source(nested_source, build_texts())
        with pytest.raises(ApplicationError) as excinfo:
            run_error_analysis_study(git_commit=GIT, source_root=nested_source, out_root=tmp_path / "x",
                                     now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.REQUEST
        assert sorted(p.name for p in (tmp_path / "x" / "error_analysis_v1").iterdir()) == ["inner"]
        # A sibling directory is fine.
        sibling = run_error_analysis_study(git_commit=GIT, source_root=directory, out_root=directory.parent,
                                           now=clock_at(CLOCK), definition=definition)
        assert sibling.output_dir == directory.parent / "error_analysis_v1"

    def test_altered_source_writes_nothing(self, tmp_path, source):
        directory, texts, definition = source
        (directory / SOURCE_OBSERVATIONS).write_bytes((texts[SOURCE_OBSERVATIONS] + "\n").encode())
        with pytest.raises(ApplicationError) as excinfo:
            run(tmp_path, source)
        assert excinfo.value.kind is FailureKind.DOMAIN
        assert "pinned source hash" in excinfo.value.message
        assert not (tmp_path / "out").exists()

    def test_missing_source_file_is_a_request_error(self, tmp_path, source):
        directory, _, _ = source
        (directory / SOURCE_OBSERVATIONS).unlink()
        with pytest.raises(ApplicationError) as excinfo:
            run(tmp_path, source)
        assert excinfo.value.kind is FailureKind.REQUEST
        assert not (tmp_path / "out").exists()

    def test_an_existing_run_is_never_overwritten(self, tmp_path, source):
        first = run(tmp_path, source)
        before = {n: first.path(n).read_bytes() for n in ARTIFACT_NAMES}
        with pytest.raises(ApplicationError) as excinfo:
            run(tmp_path, source)
        assert "not overwritten" in excinfo.value.message
        assert {n: first.path(n).read_bytes() for n in ARTIFACT_NAMES} == before

    def test_git_commit_is_validated(self, tmp_path, source):
        directory, _, definition = source
        with pytest.raises(ValueError):
            run_error_analysis_study(git_commit="abc", source_root=directory, out_root=tmp_path,
                                     definition=definition)


class TestDeterminism:
    def test_same_inputs_same_clock_byte_identical(self, tmp_path, source):
        a = run(tmp_path / "a", source)
        b = run(tmp_path / "b", source)
        for name in ARTIFACT_NAMES:
            assert a.path(name).read_bytes() == b.path(name).read_bytes(), name

    def test_different_clock_changes_only_time_bearing_bytes(self, tmp_path, source):
        directory, _, definition = source
        a = run_error_analysis_study(git_commit=GIT, source_root=directory, out_root=tmp_path / "a",
                                     now=clock_at(CLOCK), definition=definition)
        b = run_error_analysis_study(git_commit=GIT, source_root=directory, out_root=tmp_path / "b",
                                     now=clock_at(CLOCK + timedelta(days=1)), definition=definition)
        assert a.path(ARTIFACT_DIAGNOSTICS).read_bytes() == b.path(ARTIFACT_DIAGNOSTICS).read_bytes()
        assert a.path(ARTIFACT_EPISODES).read_bytes() == b.path(ARTIFACT_EPISODES).read_bytes()
        ra = a.path(ARTIFACT_REPORT).read_text().splitlines()
        rb = b.path(ARTIFACT_REPORT).read_text().splitlines()
        assert [x for x, y in zip(ra, rb) if x != y] == [l for l in ra if "generated at" in l]
        ma, mb = dict(a.manifest), dict(b.manifest)
        assert {k for k in ma if ma[k] != mb[k]} == {"generated_at", "artifacts"}


class TestDefaults:
    def test_defaults_point_at_the_research_tree_and_are_redirected_under_pytest(self, tmp_path):
        assert ERROR_ANALYSIS_LABEL == "error_analysis_v1"
        assert DEFAULT_ERROR_ANALYSIS_SOURCE == REPO_DATA / "research" / "baseline_study_v1"
        # Under pytest the conftest guards redirect both defaults into tmp_path,
        # so a run with no roots can neither read the real frozen study nor
        # write under the repository.
        assert tmp_path in application_module.DEFAULT_ERROR_ANALYSIS_SOURCE.parents
        with pytest.raises(ApplicationError) as excinfo:
            run_error_analysis_study(git_commit=GIT, now=clock_at(CLOCK))
        assert excinfo.value.kind is FailureKind.REQUEST  # the redirected default source is empty
        assert not (REPO_DATA / "research" / "error_analysis_v1").exists()

    def test_no_provider_is_imported(self):
        import src.application.error_analysis as app
        import src.cli.error_analysis as cli
        import src.research.error_analysis as engine
        import src.research.error_analysis_render as render

        for module in (app, cli, engine, render):
            text = open(module.__file__, encoding="utf-8").read()
            for forbidden in ("src.data.providers", "yfinance", "MarketDataProvider", "get_bars",
                              "default_provider", "urllib", "requests", "socket"):
                assert forbidden not in text, (module.__name__, forbidden)
