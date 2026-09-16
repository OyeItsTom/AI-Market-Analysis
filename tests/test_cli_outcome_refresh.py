"""Phase 12G: headless outcome collection through ``python -m src.cli.outcome_refresh``.

The command is driven through ``main`` with an injected offline provider,
an injected clock and a temporary ledger root, so every test runs the real
application path -- ``build_snapshot`` -> ``refresh_outcomes`` ->
``JsonlOutcomeLedger`` -- and every line written is a line production
would write. Nothing here reaches a network, reads a wall clock or touches
the repository's ``data/outcomes``.

Counts pinned below are the deterministic ramp provider's own: 80 daily
bars from 2020-01-01 warm every hypothesis up, so a refresh registers three
observations and one assessment (4 artifacts) under three horizons
(12 items).
"""

from __future__ import annotations

import ast
import io
import pathlib
import shlex
from datetime import timedelta

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.outcomes import (
    OUTCOME_SPECS,
    build_outcome_ledger,
    refresh_outcomes,
)
from src.application.snapshot import SUPPORTED_INTERVALS, build_snapshot
from src.cli import outcome_refresh as cli
from src.cli.outcome_refresh import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    format_success,
    main,
    normalize_symbols,
)
from src.data.models import Interval
from src.data.provider import ProviderUnavailableError
from src.outcomes import LedgerPartition
from tests.test_application_snapshot import CLOCK_NOW, RecordingProvider

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
MODULE = SRC / "cli" / "outcome_refresh.py"
REAL_DEFAULT_ROOT = REPO / "data" / "outcomes"


# -- helpers -----------------------------------------------------------------------------


def at(days: int):
    return lambda: CLOCK_NOW + timedelta(days=days)


def run(argv, *, provider, now=at(0)):
    """``main`` with captured streams; returns (code, stdout lines, stderr text)."""
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, provider=provider, now=now, stdout=out, stderr=err)
    return code, out.getvalue().splitlines(), err.getvalue()


def parse(line: str) -> dict[str, str]:
    """A report line back into its fields, in order."""
    fields: dict[str, str] = {}
    for token in shlex.split(line):
        key, _, value = token.partition("=")
        fields[key] = value
    return fields


def partition(symbol: str, interval: Interval = Interval.DAY_1) -> LedgerPartition:
    from src.data.series import PriceBasis

    return LedgerPartition(symbol=symbol, interval=interval, basis=PriceBasis.RAW)


def files_under(root: pathlib.Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def line_count(path: pathlib.Path) -> int:
    return path.read_bytes().count(b"\n") if path.exists() else 0


@pytest.fixture
def root(tmp_path):
    return tmp_path / "ledger"


class EmptyProvider(RecordingProvider):
    """A source that has no bars for anything -- a mistyped or delisted symbol."""

    def get_bars(self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False):
        super().get_bars(symbol, start, end, interval, include_unsettled=include_unsettled)
        return []


class FailingFor(RecordingProvider):
    """Raises the provider's own outage error for one symbol, serves the rest."""

    def __init__(self, failing: str, count: int = 80):
        super().__init__(count)
        self.failing = failing

    def get_bars(self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False):
        if str(symbol).strip().upper() == self.failing:
            raise ProviderUnavailableError(f"{symbol}: upstream refused the request")
        return super().get_bars(symbol, start, end, interval, include_unsettled=include_unsettled)


# -- A. one symbol, the real path ---------------------------------------------------------


class TestOneSymbol:
    def test_first_run_registers_the_tail_and_writes_the_ledger(self, root):
        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=RecordingProvider(80))
        assert code == EXIT_OK
        assert err == ""
        assert len(lines) == 2
        fields = parse(lines[0])
        assert fields["symbol"] == "AAPL"
        assert fields["interval"] == "1d"
        assert fields["status"] == "ok"
        assert fields["source"] == "fake"
        assert fields["built_at"] == CLOCK_NOW.isoformat()
        assert fields["tail"] == "2020-03-20T00:00:00+00:00"
        assert fields["bars"] == "80"
        assert fields["artifacts"] == "4"
        assert fields["artifacts_new"] == "4"
        assert fields["artifacts_duplicate"] == "0"
        assert fields["outcomes_new"] == "0"
        assert fields["outcomes_present"] == "0"
        assert fields["pending"] == "12"
        assert fields["ineligible"] == fields["refused"] == fields["out_of_window"] == "0"
        assert parse(lines[1]) == {"symbols": "1", "ok": "1", "failed": "0"}

        written = files_under(root)
        assert list(written) == ["AAPL/1d/raw/artifacts.jsonl"]
        assert written["AAPL/1d/raw/artifacts.jsonl"].count(b"\n") == 4

    def test_the_lifecycle_completes_outcomes_on_later_runs(self, root):
        argv = ["AAPL", "--interval", "1d", "--outcome-root", str(root)]
        run(argv, provider=RecordingProvider(80), now=at(0))
        code, lines, _ = run(argv, provider=RecordingProvider(82), now=at(1))
        assert code == EXIT_OK
        second = parse(lines[0])
        assert (second["artifacts_new"], second["outcomes_new"], second["pending"]) == ("4", "4", "20")
        code, lines, _ = run(argv, provider=RecordingProvider(101), now=at(2))
        assert code == EXIT_OK
        third = parse(lines[0])
        assert (third["artifacts_new"], third["outcomes_new"], third["outcomes_present"],
                third["pending"]) == ("4", "16", "4", "16")
        assert line_count(root / "AAPL/1d/raw/artifacts.jsonl") == 12
        assert line_count(root / "AAPL/1d/raw/outcomes.jsonl") == 20

    def test_the_provider_is_asked_for_settled_bars_over_the_application_window(self, root):
        provider = RecordingProvider(80)
        run(["aapl", "--interval", "1wk", "--outcome-root", str(root)], provider=provider)
        (call,) = provider.calls
        assert call["symbol"] == "AAPL"
        assert call["interval"] is Interval.WEEK_1
        assert call["include_unsettled"] is False
        assert call["end"] == CLOCK_NOW
        # The CLI never names a window; this is build_snapshot's own policy.
        from src.application.snapshot import history_window

        assert call["start"] == CLOCK_NOW - history_window(Interval.WEEK_1)

    def test_the_default_provider_is_used_when_none_is_injected(self, monkeypatch, root):
        seen = {}

        def fake_default():
            seen["built"] = True
            return RecordingProvider(80)

        monkeypatch.setattr(cli, "default_provider", fake_default)
        out = io.StringIO()
        code = main(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                    now=at(0), stdout=out, stderr=io.StringIO())
        assert code == EXIT_OK and seen == {"built": True}


# -- B..E. arguments and normalization ---------------------------------------------------


class TestArguments:
    def test_interval_is_required(self, root, capsys):
        code, lines, _ = run(["AAPL", "--outcome-root", str(root)], provider=RecordingProvider())
        assert code == EXIT_USAGE
        assert lines == []
        assert "--interval" in capsys.readouterr().err
        assert not root.exists()

    @pytest.mark.parametrize("interval", ["1m", "1h", "1day", "daily", ""])
    def test_an_unsupported_interval_is_a_usage_error(self, root, interval):
        provider = RecordingProvider()
        code, lines, _ = run(["AAPL", "--interval", interval, "--outcome-root", str(root)],
                             provider=provider)
        assert code == EXIT_USAGE
        assert lines == [] and provider.calls == [] and not root.exists()

    def test_the_interval_choices_are_exactly_the_application_set(self):
        parser = cli.build_parser()
        action = next(a for a in parser._actions if a.dest == "interval")
        assert action.required is True
        assert action.default is None
        assert list(action.choices) == [i.value for i in SUPPORTED_INTERVALS]

    def test_at_least_one_symbol_is_required(self, root):
        code, lines, _ = run(["--interval", "1d", "--outcome-root", str(root)],
                             provider=RecordingProvider())
        assert code == EXIT_USAGE and lines == [] and not root.exists()

    @pytest.mark.parametrize("argv", [["AAPL", "  "], [""], ["\t", "MSFT"]])
    def test_a_blank_symbol_is_a_usage_error_before_anything_runs(self, root, argv):
        provider = RecordingProvider()
        code, lines, err = run(argv + ["--interval", "1d", "--outcome-root", str(root)],
                               provider=provider)
        assert code == EXIT_USAGE
        assert lines == []
        assert "blank" in err
        assert provider.calls == [] and not root.exists()

    @pytest.mark.parametrize("argv", [["AAPL", "aapl"], ["MSFT", " msft "], ["A", "B", "A"]])
    def test_a_duplicate_symbol_after_normalization_is_a_usage_error(self, root, argv):
        provider = RecordingProvider()
        code, lines, err = run(argv + ["--interval", "1d", "--outcome-root", str(root)],
                               provider=provider)
        assert code == EXIT_USAGE
        assert lines == []
        assert "more than once" in err
        assert provider.calls == [] and not root.exists()

    def test_normalization_strips_uppercases_and_keeps_order(self):
        assert normalize_symbols([" qqq", "Spy ", "aapl"]) == ("QQQ", "SPY", "AAPL")
        with pytest.raises(ValueError):
            normalize_symbols(["SPY", "spy"])
        with pytest.raises(ValueError):
            normalize_symbols([" "])

    def test_help_exits_zero_without_running(self, root, capsys):
        provider = RecordingProvider()
        code, lines, _ = run(["--help"], provider=provider)
        assert code == 0 and lines == [] and provider.calls == []
        assert "--outcome-root" in capsys.readouterr().out

    def test_no_forbidden_option_exists(self):
        parser = cli.build_parser()
        options = {opt for action in parser._actions for opt in action.option_strings}
        for forbidden in ("--period", "--horizon", "--evaluation-version", "--basis",
                          "--origin", "--producer", "--provider", "--universe", "--watchlist"):
            assert forbidden not in options


# -- F. empty snapshot -------------------------------------------------------------------


class TestEmptySnapshot:
    def test_zero_bars_is_reported_as_failure_and_nothing_is_written(self, root):
        provider = EmptyProvider()
        code, lines, err = run(["ZZZZ", "--interval", "1d", "--outcome-root", str(root)],
                               provider=provider)
        assert code == EXIT_FAILED
        assert parse(lines[0]) == {"symbol": "ZZZZ", "interval": "1d", "status": "failed",
                                   "stage": "snapshot", "reason": "empty_snapshot"}
        assert parse(lines[1]) == {"symbols": "1", "ok": "0", "failed": "1"}
        assert len(provider.calls) == 1
        assert not root.exists()

    def test_the_dashboard_still_treats_an_empty_series_as_a_fact(self):
        """The CLI's rule is its own: the application returns the empty snapshot."""
        snapshot = build_snapshot(EmptyProvider(), "ZZZZ", Interval.DAY_1, now=at(0))
        assert snapshot.bar_count == 0 and snapshot.assessment is None


# -- G. provider / snapshot failure ----------------------------------------------------


class TestSnapshotFailure:
    def test_a_provider_outage_is_reported_with_the_application_classification(self, root):
        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=FailingFor("AAPL"))
        assert code == EXIT_FAILED
        fields = parse(lines[0])
        assert (fields["symbol"], fields["interval"], fields["status"], fields["stage"]) == (
            "AAPL", "1d", "failed", "snapshot")
        assert fields["kind"] == FailureKind.PROVIDER.value
        assert fields["step"] == "market data"
        assert "upstream refused" in fields["error"]
        assert "reason" not in fields
        assert err == ""  # a classified outage is one line, as on the dashboard
        assert parse(lines[1]) == {"symbols": "1", "ok": "0", "failed": "1"}
        assert not root.exists()

    def test_an_unexpected_snapshot_failure_is_classified_and_gets_its_traceback(self, root):
        class Broken(RecordingProvider):
            def get_bars(self, *a, **k):
                raise RuntimeError("a defect, not an outage")

        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=Broken())
        assert code == EXIT_FAILED
        fields = parse(lines[0])
        assert (fields["stage"], fields["kind"]) == ("snapshot", FailureKind.UNEXPECTED.value)
        assert "RuntimeError" in err and "a defect, not an outage" in err

    def test_the_failure_line_matches_the_application_error_fields(self, root):
        provider = FailingFor("AAPL")
        with pytest.raises(ApplicationError) as excinfo:
            build_snapshot(provider, "AAPL", Interval.DAY_1, now=at(0))
        exc = excinfo.value
        _, lines, _ = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                          provider=provider)
        fields = parse(lines[0])
        assert fields["kind"] == exc.kind.value
        assert fields["step"] == exc.step
        assert fields["error"] == " ".join(exc.message.split())


# -- H. corrupt ledger -----------------------------------------------------------------


class TestLedgerFailure:
    def test_a_corrupt_partition_fails_the_symbol_and_is_left_untouched(self, root):
        ledger = build_outcome_ledger(root)
        path = ledger.artifacts_path(partition("AAPL"))
        path.parent.mkdir(parents=True)
        garbage = b'{"not": "a record"}\n'
        path.write_bytes(garbage)

        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=RecordingProvider(80))
        assert code == EXIT_FAILED
        fields = parse(lines[0])
        assert (fields["status"], fields["stage"]) == ("failed", "outcomes")
        assert fields["error_type"] == "LedgerCorruption"
        assert "LedgerCorruption" in err
        assert parse(lines[1]) == {"symbols": "1", "ok": "0", "failed": "1"}
        assert path.read_bytes() == garbage
        assert files_under(root) == {"AAPL/1d/raw/artifacts.jsonl": garbage}

    def test_a_refresh_error_is_reported_by_type_and_earlier_writes_stay(self, root, monkeypatch):
        """A failure inside refresh_outcomes after an append: the append is durable
        and the line says so by saying nothing about rollback."""
        from src.application.outcomes import OutcomeRefreshError

        real = cli.refresh_outcomes
        state = {"calls": 0}

        def flaky(snapshot, specs, ledger, *, now):
            state["calls"] += 1
            result = real(snapshot, specs, ledger, now=now)
            raise OutcomeRefreshError("simulated failure after appends")

        monkeypatch.setattr(cli, "refresh_outcomes", flaky)
        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=RecordingProvider(80))
        assert code == EXIT_FAILED and state["calls"] == 1
        fields = parse(lines[0])
        assert (fields["stage"], fields["error_type"]) == ("outcomes", "OutcomeRefreshError")
        assert fields["error"] == "simulated failure after appends"
        assert "rollback" not in lines[0] and "rolled back" not in lines[0]
        assert line_count(root / "AAPL/1d/raw/artifacts.jsonl") == 4


# -- I. idempotency --------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.parametrize("count, days", [(80, 0), (101, 2)])
    def test_running_twice_appends_nothing(self, root, count, days):
        argv = ["AAPL", "--interval", "1d", "--outcome-root", str(root)]
        if count > 80:
            run(argv, provider=RecordingProvider(80), now=at(0))
        first_code, first_lines, _ = run(argv, provider=RecordingProvider(count), now=at(days))
        before = files_under(root)
        second_code, second_lines, err = run(argv, provider=RecordingProvider(count), now=at(days))
        assert first_code == second_code == EXIT_OK and err == ""
        assert files_under(root) == before  # byte for byte
        first, second = parse(first_lines[0]), parse(second_lines[0])
        assert second["artifacts"] == first["artifacts"] == "4"
        assert second["artifacts_new"] == "0"
        assert second["artifacts_duplicate"] == "4"
        assert second["outcomes_new"] == "0"
        assert int(second["outcomes_present"]) == int(first["outcomes_present"]) + int(first["outcomes_new"])
        assert second["pending"] == first["pending"]
        assert second["tail"] == first["tail"] and second["built_at"] == first["built_at"]

    def test_a_later_clock_over_the_same_tail_is_still_a_duplicate(self, root):
        argv = ["AAPL", "--interval", "1d", "--outcome-root", str(root)]
        run(argv, provider=RecordingProvider(80), now=at(0))
        before = files_under(root)
        _, lines, _ = run(argv, provider=RecordingProvider(80), now=at(3))
        assert files_under(root) == before
        fields = parse(lines[0])
        assert (fields["artifacts_new"], fields["artifacts_duplicate"]) == ("0", "4")
        assert fields["built_at"] == (CLOCK_NOW + timedelta(days=3)).isoformat()

    def test_the_cli_carries_no_deduplication_of_its_own(self):
        """Identifiers the code *uses* (prose in the docstring may explain them)."""
        used = _identifiers()
        for word in ("DUPLICATE", "PRESENT", "WRITTEN", "CONFLICT", "artifact_key", "outcome_key",
                     "fingerprint", "contains_artifact", "contains_outcome", "iter_artifacts",
                     "iter_outcomes", "registrations"):
            assert word not in used, word


# -- J. several symbols ---------------------------------------------------------------


class TestSeveralSymbols:
    def test_symbols_run_in_order_and_a_failure_does_not_stop_the_rest(self, root):
        provider = FailingFor("QQQ")
        code, lines, err = run(["spy", "qqq", "iwm", "--interval", "1d", "--outcome-root", str(root)],
                               provider=provider)
        assert code == EXIT_FAILED
        assert [parse(l)["symbol"] for l in lines[:3]] == ["SPY", "QQQ", "IWM"]
        assert [parse(l)["status"] for l in lines[:3]] == ["ok", "failed", "ok"]
        assert parse(lines[1])["stage"] == "snapshot"
        assert parse(lines[3]) == {"symbols": "3", "ok": "2", "failed": "1"}
        assert [c["symbol"] for c in provider.calls] == ["SPY", "IWM"]
        assert sorted(files_under(root)) == ["IWM/1d/raw/artifacts.jsonl", "SPY/1d/raw/artifacts.jsonl"]

    def test_an_earlier_success_is_durable_after_a_later_failure(self, root):
        argv = ["SPY", "ZZZZ", "--interval", "1d", "--outcome-root", str(root)]

        class Mixed(RecordingProvider):
            def get_bars(self, symbol, *a, **k):
                bars = super().get_bars(symbol, *a, **k)
                return [] if str(symbol).upper() == "ZZZZ" else bars

        code, lines, _ = run(argv, provider=Mixed(80))
        assert code == EXIT_FAILED
        assert parse(lines[1])["reason"] == "empty_snapshot"
        assert line_count(root / "SPY/1d/raw/artifacts.jsonl") == 4
        # And the rerun is idempotent over the survivor.
        code, lines, _ = run(argv, provider=Mixed(80))
        assert code == EXIT_FAILED
        assert parse(lines[0])["artifacts_duplicate"] == "4"
        assert line_count(root / "SPY/1d/raw/artifacts.jsonl") == 4

    def test_all_succeed_exits_zero(self, root):
        code, lines, _ = run(["SPY", "QQQ", "--interval", "1wk", "--outcome-root", str(root)],
                             provider=RecordingProvider(80))
        assert code == EXIT_OK
        assert parse(lines[-1]) == {"symbols": "2", "ok": "2", "failed": "0"}
        assert {parse(l)["interval"] for l in lines[:2]} == {"1wk"}
        assert sorted(files_under(root)) == ["QQQ/1wk/raw/artifacts.jsonl", "SPY/1wk/raw/artifacts.jsonl"]


# -- K. ledger root --------------------------------------------------------------------


class TestLedgerRoot:
    def test_an_explicit_root_is_the_only_place_written(self, tmp_path, monkeypatch):
        root = tmp_path / "explicit"
        monkeypatch.chdir(tmp_path)
        before = set(tmp_path.iterdir())
        run(["AAPL", "--interval", "1d", "--outcome-root", str(root)], provider=RecordingProvider(80))
        assert set(tmp_path.iterdir()) - before == {root}
        assert list(files_under(root)) == ["AAPL/1d/raw/artifacts.jsonl"]
        assert not REAL_DEFAULT_ROOT.exists()

    def test_the_default_root_is_resolved_by_the_application_at_call_time(self, tmp_path, monkeypatch):
        """No --outcome-root: the ledger lands where the application says *now*
        (the conftest guard redirects that to tmp_path), never at a path the CLI
        captured at import time."""
        import src.application.outcomes as outcomes

        assert outcomes.DEFAULT_OUTCOMES_ROOT == tmp_path / "outcomes-default"
        code, lines, _ = run(["AAPL", "--interval", "1d"], provider=RecordingProvider(80))
        assert code == EXIT_OK
        assert list(files_under(tmp_path / "outcomes-default")) == ["AAPL/1d/raw/artifacts.jsonl"]
        assert not REAL_DEFAULT_ROOT.exists()

    @pytest.mark.parametrize("value", ["", "   "])
    def test_a_blank_root_is_a_usage_error_before_anything_runs(self, value):
        provider = RecordingProvider()
        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", value],
                               provider=provider)
        assert code == EXIT_USAGE
        assert lines == [] and "--outcome-root" in err
        assert provider.calls == [] and not REAL_DEFAULT_ROOT.exists()

    def test_the_cli_never_names_the_default_root(self):
        text = MODULE.read_text(encoding="utf-8")
        assert "DEFAULT_OUTCOMES_ROOT" not in text
        assert 'Path(' not in text and "__file__" not in text


# -- L, M. output contract and correspondence to the snapshot --------------------------


SUCCESS_FIELDS = (
    "symbol", "interval", "status", "source", "built_at", "tail", "bars",
    "artifacts", "artifacts_new", "artifacts_duplicate",
    "outcomes_new", "outcomes_present", "pending", "ineligible", "refused", "out_of_window",
)


class TestOutputContract:
    def test_success_fields_and_order(self, root):
        _, lines, _ = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                          provider=RecordingProvider(80))
        assert tuple(parse(lines[0])) == SUCCESS_FIELDS
        assert tuple(parse(lines[1])) == ("symbols", "ok", "failed")

    def test_failure_fields_and_order(self, root):
        _, lines, _ = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                          provider=FailingFor("AAPL"))
        assert tuple(parse(lines[0])) == ("symbol", "interval", "status", "stage", "kind", "step", "error")
        _, lines, _ = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                          provider=EmptyProvider())
        assert tuple(parse(lines[0])) == ("symbol", "interval", "status", "stage", "reason")

    def test_values_with_whitespace_are_quoted_and_single_line(self):
        assert cli.format_line({"a": "x", "step": "market data"}) == 'a=x step="market data"'
        assert cli.format_line({"e": 'say "hi"\nnow'}) == 'e="say \\"hi\\" now"'
        assert cli.format_line({"e": "k=v"}) == 'e="k=v"'
        assert cli.format_line({"e": "it's"}) == 'e="it\'s"'
        assert cli.format_line({"e": ""}) == 'e=""'
        assert "\n" not in cli.format_line({"e": "a\n\nb"})
        assert parse(cli.format_line({"step": "market data", "e": "k=v"})) == {
            "step": "market data", "e": "k=v"}

    def test_the_line_is_the_snapshot_and_its_own_refresh_result(self, root, tmp_path):
        """Reproduce the CLI's work independently: the same provider data and
        clock give the same snapshot, whose refresh into a second root gives a
        result that *describes* it; the CLI printed exactly that pair."""
        _, lines, _ = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                          provider=RecordingProvider(80), now=at(0))
        snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=at(0))
        result = refresh_outcomes(snapshot, OUTCOME_SPECS, build_outcome_ledger(tmp_path / "other"),
                                  now=snapshot.built_at)
        assert result.describes(snapshot)
        assert lines[0] == format_success(snapshot, result)
        assert parse(lines[0])["built_at"] == snapshot.built_at.isoformat()
        assert parse(lines[0])["tail"] == snapshot.latest_bar_open.isoformat()

    def test_what_was_written_carries_the_snapshot_clock_and_tail(self, root):
        run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
            provider=RecordingProvider(80), now=at(0))
        snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=at(0))
        artifacts = list(build_outcome_ledger(root).iter_artifacts(partition("AAPL")))
        assert len(artifacts) == 4
        assert {a.recorded_at for a in artifacts} == {snapshot.built_at}
        assert {a.timestamp for a in artifacts} == {snapshot.latest_bar_open}
        assert {a.source for a in artifacts} == {"fake"}

    def test_stdout_carries_the_contract_and_stderr_only_tracebacks(self, root):
        code, lines, err = run(["AAPL", "--interval", "1d", "--outcome-root", str(root)],
                               provider=RecordingProvider(80))
        assert err == ""
        assert all("=" in line for line in lines)


# -- N. boundaries ---------------------------------------------------------------------


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


def _identifiers() -> set[str]:
    """Names, attributes and string constants the code uses; docstrings excluded."""
    used: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 40:
            used.add(node.value)
    return used


def _calls() -> set[str]:
    called: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    return called


class TestBoundaries:
    """What is specific to this module. The tier rule itself -- cli imports
    only stdlib and src.application, and nothing imports cli -- lives in
    ``test_dashboard_boundaries``; the single-consumer rule for
    ``src.outcomes`` lives in ``test_outcomes_boundaries``."""

    @pytest.mark.parametrize("module", [
        "streamlit", "yfinance", "pandas", "requests", "anthropic", "asyncio", "threading",
        "multiprocessing", "concurrent", "subprocess", "sched", "time", "os", "pathlib",
        "logging", "click", "typer",
    ])
    def test_imports_no_ui_vendor_scheduler_or_filesystem_module(self, module):
        assert not any(n == module or n.startswith(module + ".") for n in _imports()), module

    def test_reaches_the_pipeline_through_the_application_layer_only(self):
        src_imports = {n for n in _imports() if n.startswith("src")}
        assert src_imports == {"src.application.errors", "src.application.outcomes",
                               "src.application.snapshot"}

    @pytest.mark.parametrize("name", [
        "now", "utcnow", "today", "get_bars", "measure_forward", "evaluate_artifact",
        "register_artifact", "append_outcome", "JsonlOutcomeLedger", "OutcomeSpec",
        "YahooFinanceProvider", "open", "mkdir", "sleep", "Thread", "Timer", "run", "Popen",
    ])
    def test_calls_no_clock_fetch_measurement_store_or_scheduler(self, name):
        assert name not in _calls(), name

    def test_owns_no_horizon_window_or_interval_policy(self):
        text = MODULE.read_text(encoding="utf-8")
        for word in ("(1, 5, 20)", "HISTORY_WINDOWS", "timedelta", "WARMUP_BARS",
                     "include_unsettled", "'1d'", '"1d"', '"1wk"', '"1mo"'):
            assert word not in text, word
        assert "OUTCOME_SPECS" in text and "SUPPORTED_INTERVALS" in text

    def test_the_only_clock_is_the_injected_one_passed_to_build_snapshot(self):
        assert "datetime.now" not in MODULE.read_text(encoding="utf-8")
        assert "now" not in _calls()  # ``now`` is passed through, never called here


# -- the repository's own data directory is never touched -----------------------------


def test_no_test_in_this_module_writes_the_repository_ledger():
    assert not REAL_DEFAULT_ROOT.exists()
