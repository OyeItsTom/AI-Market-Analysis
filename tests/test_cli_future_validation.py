"""FUTURE_VALIDATION_V1 CLI: two commands, no knobs, blind status output, exit codes."""

from __future__ import annotations

import io
import re

import pytest

from src.cli.future_validation import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    build_parser,
    main,
)
from src.prospective import ProspectiveStore
from tests.future_validation_fixtures import (  # noqa: F401 - autouse firewall
    AFTER_E1,
    copy_root,
    future_validation_firewall,
    root_templates,
    small_definition,
)
from tests.prospective_fixtures import SPY_ONLY, ProbeDouble, et

SMALL = small_definition()


def cli(argv, root, at=AFTER_E1, definition=SMALL, **kwargs):
    out = io.StringIO()
    code = main(argv, root=root, now=lambda: at, definition=definition,
                pinned_fingerprint=definition.fingerprint, collection=SPY_ONLY,
                repository=ProbeDouble(), stdout=out, **kwargs)
    return code, out.getvalue()


class TestParser:
    def test_only_status_and_run_exist_and_neither_takes_an_option(self):
        parser = build_parser()
        commands = next(a for a in parser._actions if a.dest == "command")
        assert sorted(commands.choices) == ["run", "status"]
        for sub in commands.choices.values():
            assert [a.dest for a in sub._actions] == ["help"]
        assert [a.dest for a in parser._actions] == ["help", "command"]

    @pytest.mark.parametrize("flag", ["--symbol=SPY", "--horizon=5", "--state=bearish",
                                      "--minimum-episodes=1", "--threshold=0", "--root=/tmp",
                                      "--hypothesis=trend_crossover", "--cutoff=2030-01-01",
                                      "--benchmark=x", "--metric=mean"])
    def test_no_research_or_location_flag_is_accepted(self, flag, tmp_path, capsys):
        for command in ("status", "run"):
            assert main([command, flag], root=tmp_path / "v1") == EXIT_REFUSED
        assert not (tmp_path / "v1").exists()


class TestStatusOutput:
    def test_not_activated(self, tmp_path):
        code, out = cli(["status"], tmp_path / "v1")
        assert code == EXIT_OK and "activation=not_activated" in out
        assert not (tmp_path / "v1").exists()

    def test_activated_status_is_level_one(self, root_templates, tmp_path):
        code, out = cli(["status"], copy_root(root_templates, "matured", tmp_path))
        assert code == EXIT_OK
        assert "unlockable=yes" in out and "matured_eligible_h20_claims=4" in out
        assert "evidence_through=2026-11-06T00:00:00-05:00" in out or \
            "evidence_through=2026-11-06T05:00:00+00:00" in out
        lowered = out.lower()
        for forbidden in ("bullish", "bearish", "neutral", "category", "consistent",
                          "reversed", "mixed", "mean", "median", "episode", "return",
                          "price", "cutoff"):
            assert forbidden not in lowered, forbidden
        without_times = re.sub(r"\d{4}-\d\d-\d\dT[\d:+.]+", "", out)
        assert not re.search(r"\d\.\d", without_times)  # no decimal number at all

    def test_invalid_evidence_exits_one(self, root_templates, tmp_path):
        root = copy_root(root_templates, "matured", tmp_path)
        (root / "ledger" / "SPY" / "1d" / "raw" / "foreign.jsonl").write_bytes(b"{}\n")
        code, out = cli(["status"], root)
        assert code == EXIT_FAILED and "validity=invalid" in out

    def test_a_running_collector_exits_two(self, root_templates, tmp_path):
        root = copy_root(root_templates, "matured", tmp_path)
        with ProspectiveStore(root).exclusive_lock():
            code, out = cli(["status"], root)
        assert code == EXIT_REFUSED and "activation=collect_in_progress" in out


class TestRunOutput:
    def test_refused_before_the_stop_rule(self, root_templates, tmp_path):
        # E1 two months after activation: ~1 month of evidence, whatever the host clock says
        code, out = cli(["run"], copy_root(root_templates, "matured", tmp_path),
                        at=et(2036, 6, 1, 12),
                        definition=small_definition(stop_rule_minimum_calendar_months=2))
        assert code == EXIT_REFUSED and "run=refused detail=not_unlockable" in out
        assert "category" not in out

    def test_complete_then_already_complete(self, root_templates, tmp_path):
        root = copy_root(root_templates, "matured", tmp_path)
        code, out = cli(["run"], root)
        assert code == EXIT_OK
        assert out.splitlines()[0].startswith("run=complete unlock_sha256=")
        assert "symbol=SPY category=mixed" in out
        code, again = cli(["run"], root)
        assert code == EXIT_OK and again.startswith("run=already_complete")
        assert again.splitlines()[1:] == out.splitlines()[1:]

    def test_not_activated_run_is_refused_and_creates_nothing(self, tmp_path):
        code, out = cli(["run"], tmp_path / "v1")
        assert code == EXIT_REFUSED and "detail=not_activated" in out
        assert not (tmp_path / "v1").exists()
