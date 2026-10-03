"""``python -m src.cli.prospective``: activate / collect / health, driven offline through ``main``."""

from __future__ import annotations

import io
import shlex
import shutil

import pytest

from src.cli.prospective import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, build_parser, main
from src.data.provider import ProviderUnavailableError
from tests.prospective_fixtures import (  # noqa: F401 - autouse guard
    COLLECTOR_SHA,
    M2_SHA,
    VERSIONS,
    Clock,
    ProbeDouble,
    SessionProvider,
    build_matured_root,
    et,
    install_offline_guard,
    offline_and_no_live_root,
)

ACTIVATE = ["activate", "--collector-git-commit", COLLECTOR_SHA,
            "--m2-preregistration-git-commit", M2_SHA]

#: Every key a health line may carry. Level 1 only.
HEALTH_KEYS = {
    "prospective_status", "root_exists", "ledger_exists", "collection_id",
    "collection_fingerprint", "manifest_fingerprint_match", "live_configuration_match",
    "activated_at", "collector_git_commit", "m2_preregistration_git_commit", "universe",
    "interval", "basis",
    "symbol", "readable", "claims_total", "tails_registered", "claims_evaluable",
    "claims_insufficient", "outcomes_matured_h1", "outcomes_matured_h5", "outcomes_matured_h20",
    "pending", "missed_collections", "missed_dates", "last_tail",
    "runs_total", "runs_completed", "runs_outside_window", "runs_config_mismatch", "last_run",
    "last_success", "symbol_statuses",
    "integrity", "corrupt_component", "corrupt_line",
}

#: Every key a collect line may carry.
COLLECT_KEYS = {
    "symbol", "status", "stage", "error_class", "built_at", "tail", "bars", "artifacts_new",
    "artifacts_duplicate", "outcomes_new", "outcomes_present", "pending", "ineligible",
    "refused", "out_of_window", "missed_tails",
    "run_status", "run_id", "started_at", "finished_at", "symbols", "ok", "pre_activation",
    "failed", "collect", "reason",
}


def cli(argv, root, *, provider=None, now=None, repository=None):
    out, err = io.StringIO(), io.StringIO()
    kwargs = dict(root=root, stdout=out, stderr=err, versions=VERSIONS,
                  repository=repository if repository is not None else ProbeDouble())
    if provider is not None:
        kwargs["provider_factory"] = lambda: provider
    if now is not None:
        kwargs["now"] = Clock(now)
    code = main(argv, **kwargs)
    return code, out.getvalue().splitlines(), err.getvalue()


def parse(line):
    fields = {}
    for token in shlex.split(line):
        key, _, value = token.partition("=")
        fields[key] = value
    return fields


@pytest.fixture
def root(tmp_path):
    return tmp_path / "v1"


@pytest.fixture
def active(root):
    code, _, _ = cli(ACTIVATE, root, now=et(2026, 10, 5, 15))
    assert code == EXIT_OK
    return root


class TestParser:
    def test_exactly_three_commands_and_no_research_flags(self):
        parser = build_parser()
        [commands] = [a for a in parser._actions if a.dest == "command"]
        assert sorted(commands.choices) == ["activate", "collect", "health"]
        for name in ("collect", "health"):
            options = {o for a in commands.choices[name]._actions for o in a.option_strings}
            assert options == {"-h", "--help"}
        activate_options = {o for a in commands.choices["activate"]._actions
                            for o in a.option_strings}
        assert activate_options == {"-h", "--help", "--collector-git-commit",
                                    "--m2-preregistration-git-commit"}

    @pytest.mark.parametrize("argv", [
        ["collect", "--symbol", "SPY"], ["collect", "SPY"], ["collect", "--root", "/tmp/x"],
        ["health", "--interval", "1wk"], [], ["activate", "--collector-git-commit", "a" * 40],
    ])
    def test_anything_else_is_a_usage_error(self, argv, root, capsys):
        code, _, _ = cli(argv, root)
        assert code == 2
        assert not root.exists()


class TestActivate:
    def test_writes_once_and_reports_identity(self, root):
        code, lines, err = cli(ACTIVATE, root, now=et(2026, 10, 5, 15))
        assert (code, err) == (EXIT_OK, "")
        fields = parse(lines[0])
        assert fields["activation"] == "written"
        assert fields["activated_at"] == "2026-10-05T15:00:00-04:00"
        assert fields["m2_preregistration_git_commit"] == M2_SHA
        assert sorted(p.name for p in root.iterdir()) == ["activation.json"]
        code, lines, _ = cli(ACTIVATE, root, now=et(2026, 10, 6, 15))
        assert code == EXIT_REFUSED
        assert parse(lines[0]) == {"activation": "refused", "reason": "already_activated"}

    @pytest.mark.parametrize("argv, repository, reason", [
        (["activate", "--collector-git-commit", COLLECTOR_SHA,
          "--m2-preregistration-git-commit", "not-a-sha"], None, "invalid_commit"),
        (ACTIVATE, ProbeDouble(head="d" * 40), "collector_commit_mismatch"),
        (ACTIVATE, ProbeDouble(clean=False), "dirty_repository"),
        (ACTIVATE, ProbeDouble(ancestors=()), "m2_commit_not_in_history"),
    ])
    def test_refusals(self, root, argv, repository, reason):
        code, lines, _ = cli(argv, root, now=et(2026, 10, 5, 15), repository=repository)
        assert code == EXIT_REFUSED
        assert parse(lines[0]) == {"activation": "refused", "reason": reason}
        assert not root.exists()


class TestCollect:
    def test_not_activated(self, root):
        code, lines, _ = cli(["collect"], root, provider=SessionProvider(), now=et(2026, 10, 6, 7))
        assert code == EXIT_REFUSED
        assert parse(lines[0]) == {"collect": "refused", "reason": "not_activated"}
        assert not root.exists()

    def test_outside_window_refuses_before_the_provider(self, active):
        provider = SessionProvider()
        code, lines, _ = cli(["collect"], active, provider=provider, now=et(2026, 10, 6, 9))
        assert code == EXIT_REFUSED
        assert provider.calls == []
        assert parse(lines[-1])["run_status"] == "outside_collection_window"

    def test_a_completed_run(self, active):
        code, lines, err = cli(["collect"], active, provider=SessionProvider(),
                               now=et(2026, 10, 6, 7))
        assert (code, err) == (EXIT_OK, "")
        assert len(lines) == 6
        symbols = [parse(line) for line in lines[:5]]
        assert [s["symbol"] for s in symbols] == ["SPY", "QQQ", "IWM", "TLT", "GLD"]
        assert {s["status"] for s in symbols} == {"ok"}
        assert symbols[0]["artifacts_new"] == "4" and symbols[0]["missed_tails"] == "0"
        summary = parse(lines[-1])
        assert (summary["run_status"], summary["ok"], summary["failed"]) == ("completed", "5", "0")
        for line in lines:
            assert set(parse(line)) <= COLLECT_KEYS

    def test_failures_exit_one_and_print_no_message(self, active):
        failing = SessionProvider(fail=ProviderUnavailableError("price 7777.123456 refused"))
        code, lines, err = cli(["collect"], active, provider=failing, now=et(2026, 10, 6, 7))
        assert code == EXIT_FAILED
        assert parse(lines[0])["status"] == "provider_failure"
        assert "7777" not in "\n".join(lines) + err


@pytest.fixture(scope="module")
def matured_template(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        install_offline_guard(patch)
        return build_matured_root(tmp_path_factory.mktemp("cli-matured"), 22)


class TestHealth:
    def test_not_activated_is_ok_and_creates_nothing(self, root):
        code, lines, _ = cli(["health"], root)
        assert code == EXIT_OK
        assert parse(lines[0])["prospective_status"] == "not_activated"
        assert parse(lines[-1]) == {"integrity": "ok"}
        assert not root.exists()

    def test_active_after_runs(self, active):
        cli(["collect"], active, provider=SessionProvider(), now=et(2026, 10, 6, 7))
        code, lines, _ = cli(["health"], active)
        assert code == EXIT_OK
        head = parse(lines[0])
        assert head["prospective_status"] == "active"
        assert head["universe"] == "SPY,QQQ,IWM,TLT,GLD"
        spy = parse(lines[1])
        assert (spy["claims_total"], spy["pending"], spy["outcomes_matured_h1"]) == ("4", "12",
                                                                                    "0")
        for line in lines:
            assert set(parse(line)) <= HEALTH_KEYS

    def test_corruption_exits_one(self, active):
        cli(["collect"], active, provider=SessionProvider(), now=et(2026, 10, 6, 7))
        path = active / "runs.jsonl"
        path.write_bytes(path.read_bytes() + b"{")
        code, lines, _ = cli(["health"], active)
        assert code == EXIT_FAILED
        assert parse(lines[-1]) == {"integrity": "corrupt", "corrupt_component": "run_log",
                                    "corrupt_line": "2"}

    def test_matured_health_output_leaks_no_value(self, matured_template, tmp_path):
        from src.application.prospective import build_outcome_ledger
        from src.data.models import Interval
        from src.data.series import PriceBasis
        from src.outcomes import LedgerPartition

        root = tmp_path / "v1"
        shutil.copytree(matured_template, root)
        _, lines, _ = cli(["health"], root)
        text = "\n".join(lines)
        assert "outcomes_matured_h20=8" in text  # SPY partition was read (2 tails x 4)
        source = build_outcome_ledger(root / "ledger")
        partition = LedgerPartition(symbol="SPY", interval=Interval.DAY_1, basis=PriceBasis.RAW)
        values = set()
        for outcome in source.iter_outcomes(partition):
            for number in (outcome.forward_return, outcome.reference_price, outcome.future_price):
                values.update({repr(number), f"{number:.6f}", f"{number:.4f}"})
        for artifact in source.iter_artifacts(partition):
            values.add(artifact.state.value)
        assert values
        assert not [value for value in values if value in text]
        assert "7777" not in text
        for line in lines:
            assert set(parse(line)) <= HEALTH_KEYS
