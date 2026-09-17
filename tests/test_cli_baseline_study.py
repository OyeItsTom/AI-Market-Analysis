"""Phase R command: one frozen study, two operator inputs, three exit codes."""

from __future__ import annotations

import io
import pathlib
import shlex

import pytest

from src.application.study import ARTIFACT_NAMES
from src.cli import baseline_study
from src.cli.baseline_study import EXIT_FAILED, EXIT_OK, EXIT_USAGE, build_parser, main
from tests.test_application_study import CLOCK, GIT, SyntheticProvider, clock_at
from tests.test_research_definition import small_definition

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULE = REPO / "src" / "cli" / "baseline_study.py"


def run(argv, *, provider, now=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, provider=provider, now=now, stdout=out, stderr=err)
    return code, out.getvalue().splitlines(), err.getvalue()


def parse(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in shlex.split(line):
        key, _, value = token.partition("=")
        fields[key] = value
    return fields


@pytest.fixture(autouse=True)
def _never_touch_the_network(monkeypatch):
    """The default provider is never constructed by these tests."""
    def refuse():
        raise AssertionError("default_provider() must not be called under pytest")
    monkeypatch.setattr(baseline_study, "default_provider", refuse)


@pytest.fixture(autouse=True)
def _frozen_definition_is_small(monkeypatch):
    """The CLI has no definition flag; bind the runner's default to the short
    engine definition so the command runs in seconds. The binding is the
    keyword default of ``run_baseline_study`` and nothing else."""
    from src.application import study as application_study

    definition = small_definition()
    original = application_study.run_baseline_study

    def bound(provider, **kwargs):
        return original(provider, definition=definition, **kwargs)

    monkeypatch.setattr(baseline_study, "run_baseline_study", bound)
    monkeypatch.setattr(baseline_study, "STUDY_LABEL", definition.label)


class TestParser:
    def test_only_git_commit_and_out_are_accepted(self):
        parser = build_parser()
        options = {a.dest for a in parser._actions if a.dest != "help"}
        assert options == {"git_commit", "out"}

    @pytest.mark.parametrize("flag", ["--symbols", "--symbol", "--start", "--end", "--interval",
                                      "--horizon", "--basis", "--hypothesis", "--state", "--metric"])
    def test_no_research_flag_exists(self, flag, tmp_path, capsys):
        code, _, _ = run([flag, "x", "--git-commit", GIT, "--out", str(tmp_path)], provider=SyntheticProvider())
        assert code == EXIT_USAGE
        assert "unrecognized arguments" in capsys.readouterr().err  # argparse's own stream

    def test_git_commit_is_required(self, tmp_path, capsys):
        code, _, _ = run(["--out", str(tmp_path)], provider=SyntheticProvider())
        assert code == EXIT_USAGE
        assert "--git-commit" in capsys.readouterr().err

    def test_help_exits_zero(self):
        code, _, _ = run(["--help"], provider=SyntheticProvider())
        assert code == EXIT_OK

    @pytest.mark.parametrize("value", ["abc", "ccfa47d", GIT.upper()])
    def test_malformed_git_commit_is_a_usage_error(self, value, tmp_path):
        code, out, err = run(["--git-commit", value, "--out", str(tmp_path)], provider=SyntheticProvider())
        assert code == EXIT_USAGE
        assert out == []
        assert "40-character" in err

    def test_blank_out_is_a_usage_error(self):
        code, _, err = run(["--git-commit", GIT, "--out", "  "], provider=SyntheticProvider())
        assert code == EXIT_USAGE
        assert "--out must not be blank" in err


class TestRun:
    def test_success_prints_one_line_per_symbol_then_the_study_line(self, tmp_path):
        provider = SyntheticProvider()
        code, out, err = run(["--git-commit", GIT, "--out", str(tmp_path)], provider=provider,
                             now=clock_at(CLOCK))
        assert code == EXIT_OK
        assert err == ""
        assert len(out) == 3
        first, second, study = (parse(line) for line in out)
        assert list(first) == ["symbol", "status", "bars", "warmup", "observations", "buffer",
                               "first", "last", "fingerprint"]
        assert first["symbol"] == "AAA" and second["symbol"] == "BBB"
        assert first["status"] == "ok" and int(first["warmup"]) >= 51
        assert len(first["fingerprint"]) == 64
        assert study["study"] == "engine_test_v1"
        assert study["status"] == "ok"
        assert study["git_commit"] == GIT
        assert study["source"] == "synthetic"
        assert study["retrieved_at"] == CLOCK.isoformat()
        assert study["out"] == str(tmp_path / "engine_test_v1")
        for name in ARTIFACT_NAMES:
            key = f"sha256_{name.replace('.', '_')}"
            assert len(study[key]) == 64
            assert (tmp_path / "engine_test_v1" / name).is_file()

    def test_a_provider_failure_is_one_failed_line_and_exit_one(self, tmp_path):
        code, out, err = run(["--git-commit", GIT, "--out", str(tmp_path)],
                             provider=SyntheticProvider(failing="AAA"), now=clock_at(CLOCK))
        assert code == EXIT_FAILED
        assert len(out) == 1
        fields = parse(out[0])
        assert fields["status"] == "failed"
        assert fields["stage"] == "market data"
        assert fields["kind"] == "provider"
        assert err == ""  # a classified outage carries no traceback
        assert not (tmp_path / "engine_test_v1").exists()

    def test_a_domain_refusal_is_reported_without_a_traceback(self, tmp_path):
        code, out, err = run(["--git-commit", GIT, "--out", str(tmp_path)],
                             provider=SyntheticProvider(short_warmup="BBB"), now=clock_at(CLOCK))
        assert code == EXIT_FAILED
        fields = parse(out[0])
        assert fields["kind"] == "domain" and "precede the observation start" in fields["error"]
        assert err == ""

    def test_an_existing_run_is_refused(self, tmp_path):
        argv = ["--git-commit", GIT, "--out", str(tmp_path)]
        assert run(argv, provider=SyntheticProvider(), now=clock_at(CLOCK))[0] == EXIT_OK
        code, out, _ = run(argv, provider=SyntheticProvider(), now=clock_at(CLOCK))
        assert code == EXIT_FAILED
        assert "not overwritten" in parse(out[0])["error"]

    def test_an_unexpected_error_sends_its_traceback_to_stderr(self, tmp_path):
        class Broken(SyntheticProvider):
            def get_bars(self, *args, **kwargs):
                raise RuntimeError("boom")

        code, out, err = run(["--git-commit", GIT, "--out", str(tmp_path)], provider=Broken(),
                             now=clock_at(CLOCK))
        assert code == EXIT_FAILED
        assert parse(out[0])["kind"] == "unexpected"
        assert "RuntimeError: boom" in err


class TestBoundary:
    def test_the_module_reaches_the_pipeline_only_through_the_application(self):
        text = MODULE.read_text(encoding="utf-8")
        for forbidden in ("src.research", "src.strategies", "src.evaluation", "src.data",
                          "src.outcomes", "pathlib", "subprocess", "yfinance"):
            assert forbidden not in text, forbidden
