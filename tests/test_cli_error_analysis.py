"""Phase 13A command: frozen analysis, three operational flags, three exit codes, no provider."""

from __future__ import annotations

import io
import pathlib
import shlex

import pytest

from src.cli import error_analysis as cli
from src.cli.error_analysis import EXIT_FAILED, EXIT_OK, EXIT_USAGE, build_parser, main
from src.research.error_analysis import SOURCE_OBSERVATIONS
from src.research.error_analysis_render import ARTIFACT_NAMES
from tests.error_analysis_fixtures import build_texts, definition_for, write_source
from tests.test_application_error_analysis import CLOCK, GIT, clock_at

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULE = REPO / "src" / "cli" / "error_analysis.py"


def run(argv, *, now=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, now=now, stdout=out, stderr=err)
    return code, out.getvalue().splitlines(), err.getvalue()


def parse(line):
    fields = {}
    for token in shlex.split(line):
        key, _, value = token.partition("=")
        fields[key] = value
    return fields


@pytest.fixture
def source(tmp_path):
    texts = build_texts()
    directory = tmp_path / "frozen"
    write_source(directory, texts)
    return directory, definition_for(texts)


@pytest.fixture(autouse=True)
def _bind_synthetic_definition(monkeypatch, source):
    """The CLI has no definition flag; bind the runner's default to the synthetic
    definition (the keyword default of ``run_error_analysis_study``) so the
    command runs on the fixture and never on the real frozen artifacts."""
    from src.application import error_analysis as application

    _, definition = source
    original = application.run_error_analysis_study

    def bound(**kwargs):
        return original(definition=definition, **kwargs)

    monkeypatch.setattr(cli, "run_error_analysis_study", bound)


class TestParser:
    def test_only_operational_flags(self):
        options = {a.dest for a in build_parser()._actions if a.dest != "help"}
        assert options == {"git_commit", "source", "out"}

    @pytest.mark.parametrize("flag", ["--segments", "--segment", "--metric", "--threshold", "--symbol",
                                      "--class", "--horizon", "--diagnostic", "--hypothesis", "--provider"])
    def test_no_research_flag(self, flag, tmp_path, capsys, source):
        code, _, _ = run([flag, "x", "--git-commit", GIT, "--source", str(source[0]), "--out", str(tmp_path / "o")])
        assert code == EXIT_USAGE
        assert "unrecognized arguments" in capsys.readouterr().err

    def test_git_commit_required_and_validated(self, tmp_path, capsys, source):
        code, _, _ = run(["--source", str(source[0]), "--out", str(tmp_path)])
        assert code == EXIT_USAGE and "--git-commit" in capsys.readouterr().err
        code, out, err = run(["--git-commit", "abc", "--source", str(source[0]), "--out", str(tmp_path)])
        assert code == EXIT_USAGE and out == [] and "40-character" in err

    @pytest.mark.parametrize("flag", ["--source", "--out"])
    def test_blank_paths_are_usage_errors(self, flag, tmp_path, source):
        argv = ["--git-commit", GIT, "--source", str(source[0]), "--out", str(tmp_path)]
        argv[argv.index(flag) + 1] = "  "
        code, _, err = run(argv)
        assert code == EXIT_USAGE and f"{flag} must not be blank" in err

    def test_help_exits_zero(self):
        assert run(["--help"])[0] == EXIT_OK


class TestRun:
    def test_success_prints_source_then_study_lines(self, tmp_path, source):
        directory, definition = source
        code, out, err = run(["--git-commit", GIT, "--source", str(directory), "--out", str(tmp_path / "o")],
                             now=clock_at(CLOCK))
        assert code == EXIT_OK and err == "" and len(out) == 2
        src, study = parse(out[0]), parse(out[1])
        assert src["status"] == "verified" and src["source"] == str(directory)
        assert all(len(src[f"sha256_{n}"]) == 64 for n in ("manifest_json", "summary_csv", "observations_csv"))
        assert int(src["observation_rows"]) > 0 and int(src["summary_rows_checked"]) > 0
        assert study["study"] == "error_analysis_v1" and study["status"] == "ok"
        assert study["git_commit"] == GIT and study["study_fingerprint"] == definition.fingerprint
        assert study["out"] == str(tmp_path / "o" / "error_analysis_v1")
        for name in ARTIFACT_NAMES:
            assert len(study[f"sha256_{name.replace('.', '_')}"]) == 64
            assert (tmp_path / "o" / "error_analysis_v1" / name).is_file()

    def test_altered_source_is_one_failed_line_and_exit_one(self, tmp_path, source):
        directory, _ = source
        path = directory / SOURCE_OBSERVATIONS
        path.write_bytes(path.read_bytes() + b"\n")
        code, out, err = run(["--git-commit", GIT, "--source", str(directory), "--out", str(tmp_path / "o")],
                             now=clock_at(CLOCK))
        assert code == EXIT_FAILED and len(out) == 1 and err == ""
        fields = parse(out[0])
        assert fields["status"] == "failed" and fields["stage"] == "analysis" and fields["kind"] == "domain"
        assert not (tmp_path / "o").exists()

    def test_existing_run_is_refused(self, tmp_path, source):
        directory, _ = source
        argv = ["--git-commit", GIT, "--source", str(directory), "--out", str(tmp_path / "o")]
        assert run(argv, now=clock_at(CLOCK))[0] == EXIT_OK
        code, out, _ = run(argv, now=clock_at(CLOCK))
        assert code == EXIT_FAILED and "not overwritten" in parse(out[0])["error"]

    def test_unexpected_error_goes_to_stderr(self, tmp_path, source, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(cli, "run_error_analysis_study", boom)
        code, out, err = run(["--git-commit", GIT, "--source", str(source[0]), "--out", str(tmp_path)])
        assert code == EXIT_FAILED and parse(out[0])["error_type"] == "RuntimeError" and "boom" in err


class TestBoundary:
    def test_the_module_is_a_caller_of_the_application_only(self):
        text = MODULE.read_text(encoding="utf-8")
        for forbidden in ("src.research", "src.strategies", "src.evaluation", "src.data", "src.outcomes",
                          "pathlib", "subprocess", "yfinance", "default_provider", "--symbol", "--segment",
                          "--threshold", "--horizon"):
            assert forbidden not in text, forbidden
