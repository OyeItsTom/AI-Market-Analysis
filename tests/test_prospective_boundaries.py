"""Prospective Collection v1 architecture and blind-output firewall, enforced statically.

What is pinned here:

* the package's module set and who may touch a file, a process or a lock;
* the orchestration reaches the ledger only through the unchanged
  ``refresh_outcomes`` (one call site) and reads it only for timestamps,
  eligibility and horizon counts -- never a price, a return or a state;
* no new module names the Phase 12 summary or any aggregate field;
* the health path never names the provider or snapshot path;
* the CLI has no research or location flag;
* the live root is git-ignored, the launchd example is portable and
  uninstalled, and the docs carry the corrected scheduling guidance.
"""

from __future__ import annotations

import ast
import pathlib
import plistlib
import subprocess

import pytest

from tests.prospective_fixtures import offline_and_no_live_root  # noqa: F401 - autouse guard

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
PACKAGE = SRC / "prospective"
PACKAGE_FILES = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
APPLICATION = SRC / "application" / "prospective.py"
CLI = SRC / "cli" / "prospective.py"
NEW_MODULES = PACKAGE_FILES + [APPLICATION, CLI]


def tree(path: pathlib.Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported(path: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def attributes(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def identifiers(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.alias):
            found.add((n.asname or n.name).split(".")[-1])
    return found


def called(node: ast.AST) -> list[str]:
    names = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            names.append(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


# -- package shape -------------------------------------------------------------------------------


def test_the_package_has_exactly_its_modules():
    assert [p.name for p in PACKAGE_FILES] == [
        "__init__.py", "definition.py", "environment.py", "provenance.py", "records.py",
        "store.py"]


@pytest.mark.parametrize("path", PACKAGE_FILES, ids=lambda p: p.name)
def test_the_package_reaches_no_other_project_layer_but_market_data_types(path):
    project = {name for name in imported(path) if name.startswith("src")}
    assert all(name == "src.data.models" for name in project), project


IO_MODULES = {"os", "fcntl", "pathlib", "subprocess", "socket", "shutil", "tempfile",
              "urllib", "requests", "http", "time", "random", "importlib", "platform"}
ALLOWED_IO = {
    "store.py": {"os", "fcntl", "pathlib", "time"},
    "environment.py": {"subprocess", "pathlib", "importlib", "platform"},
}


@pytest.mark.parametrize("path", PACKAGE_FILES, ids=lambda p: p.name)
def test_only_the_store_touches_files_and_only_the_probe_runs_a_process(path):
    roots = {name.split(".")[0] for name in imported(path)}
    assert roots & IO_MODULES <= ALLOWED_IO.get(path.name, set()), path.name


def test_nothing_new_imports_a_network_or_vendor_module():
    for path in NEW_MODULES:
        roots = {name.split(".")[0] for name in imported(path)}
        assert not roots & {"socket", "urllib", "requests", "http", "yfinance", "anthropic",
                            "streamlit"}, path.name


# -- the orchestration reuses Phase 12 and nothing more -------------------------------------------


def test_the_orchestration_takes_only_three_names_from_the_outcome_package():
    taken = {
        alias.name
        for node in ast.walk(tree(APPLICATION))
        if isinstance(node, ast.ImportFrom) and node.module == "src.outcomes"
        for alias in node.names
    }
    assert taken == {"EVALUATION_VERSION", "LedgerCorruption", "LedgerPartition"}


def test_refresh_outcomes_is_the_only_ledger_write_and_has_one_call_site():
    calls = called(tree(APPLICATION))
    assert calls.count("refresh_outcomes") == 1
    for forbidden in ("register_artifact", "append_outcome", "evaluate_artifact",
                      "summarize_outcomes", "measure_forward"):
        assert forbidden not in calls, forbidden


#: Names through which a price, a return, a state or an aggregate could be read.
PROHIBITED_ATTRIBUTES = {
    "forward_return", "reference_price", "future_price", "positive_count", "negative_count",
    "zero_count", "mean_forward_return", "median_forward_return", "min_forward_return",
    "max_forward_return", "state", "reason_codes", "high", "low", "volume", "observations",
    "assessment", "features",
}
PROHIBITED_IDENTIFIERS = {
    "summarize_outcomes", "OutcomeSummary", "OutcomeMetricGroup", "OutcomeCoverageGroup",
    "ResearchState", "AssessmentState", "MIN_SUMMARY_SAMPLES",
}


@pytest.mark.parametrize("path", NEW_MODULES, ids=lambda p: p.relative_to(SRC).as_posix())
def test_no_new_module_reads_a_price_return_state_or_aggregate(path):
    module = tree(path)
    assert not attributes(module) & PROHIBITED_ATTRIBUTES, path.name
    assert not identifiers(module) & PROHIBITED_IDENTIFIERS, path.name


def _function(path: pathlib.Path, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


def test_the_health_path_never_names_the_provider_or_snapshot_path():
    for path, name in ((APPLICATION, "health"), (CLI, "_run_health"), (CLI, "format_health")):
        used = identifiers(_function(path, name))
        for forbidden in ("default_provider", "build_snapshot", "refresh_outcomes",
                          "_LazyProvider", "provider", "provider_factory", "collect"):
            assert forbidden not in used, (name, forbidden)


def test_activation_never_names_the_provider_or_snapshot_path():
    """``provider`` itself appears only as the manifest's recorded provider name."""
    used = identifiers(_function(APPLICATION, "activate"))
    for forbidden in ("default_provider", "build_snapshot", "refresh_outcomes",
                      "build_outcome_ledger", "_LazyProvider", "provider_factory", "collect"):
        assert forbidden not in used, forbidden


def test_the_collection_window_is_checked_before_any_provider_exists():
    """``collect`` decides the window before it can construct a provider, and each
    symbol re-checks it before it asks the lazy provider for one."""
    source = APPLICATION.read_text()
    collect_body = ast.get_source_segment(source, _function(APPLICATION, "_collect_locked"))
    assert collect_body.index("in_collection_window(started_at)") < collect_body.index(
        "_LazyProvider(")
    symbol_body = ast.get_source_segment(source, _function(APPLICATION, "_collect_symbol"))
    assert symbol_body.index("in_collection_window(") < symbol_body.index("provider.get()")


#: Every function on the collect and health paths, whose output is Level 1.
LEVEL_ONE_PATHS = (
    (APPLICATION, "collect"), (APPLICATION, "_collect_locked"),
    (APPLICATION, "_collect_symbol"),
    (APPLICATION, "_collect_symbol_guarded"), (APPLICATION, "health"),
    (CLI, "_run_collect"), (CLI, "format_symbol_run"), (CLI, "_run_health"),
    (CLI, "format_health"),
)


@pytest.mark.parametrize("path, name", LEVEL_ONE_PATHS, ids=lambda v: getattr(v, "name", v))
def test_exception_messages_never_reach_a_run_record_or_report(path, name):
    """Only exception class names are recorded on these paths: a domain message
    can quote a value, so no ``str(exc)``, ``exc.message`` or ``exc.args``."""
    function = _function(path, name)
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"str", "repr", "format"}:
            assert not any(isinstance(arg, ast.Name) and arg.id == "exc" for arg in node.args)
        if isinstance(node, ast.FormattedValue):
            assert not (isinstance(node.value, ast.Name) and node.value.id == "exc")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "exc":
            assert node.attr in {"kind", "line_number"}, node.attr


# -- the CLI -------------------------------------------------------------------------------------


def test_the_cli_has_no_research_or_location_flag():
    text = CLI.read_text()
    for forbidden in ("--symbol", "--interval", "--basis", "--horizon", "--universe",
                      "--root", "--outcome-root", "--out", "--hypothesis", "--provider"):
        assert f'"{forbidden}"' not in text, forbidden


# -- git, launchd, docs --------------------------------------------------------------------------


@pytest.mark.parametrize("relative", [
    "data/prospective/v1/activation.json",
    "data/prospective/v1/runs.jsonl",
    "data/prospective/v1/collect.lock",
    "data/prospective/v1/ledger/SPY/1d/raw/artifacts.jsonl",
    "data/prospective/v1/ledger/SPY/1d/raw/outcomes.jsonl",
    "data/prospective/logs/collect.out.log",
])
def test_the_live_paths_are_git_ignored(relative):
    result = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", relative],
                            capture_output=True)
    assert result.returncode == 0, relative


def test_nothing_under_the_prospective_data_root_is_tracked():
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "data/prospective"],
                             capture_output=True, text=True, check=True).stdout
    assert tracked == ""


PLIST = REPO / "config" / "launchd" / "com.ai-market-analysis.prospective-collect.plist.example"


def test_the_launchd_example_parses_and_runs_only_collect():
    with PLIST.open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["Label"] == "com.ai-market-analysis.prospective-collect"
    assert plist["ProgramArguments"][1:] == ["-m", "src.cli.prospective", "collect"]
    triggers = plist["StartCalendarInterval"]
    assert len(triggers) >= 2
    assert all(set(t) == {"Hour", "Minute"} for t in triggers)
    assert plist["RunAtLoad"] is False


def test_the_launchd_example_is_portable_and_logs_outside_the_v1_root():
    text = PLIST.read_text()
    assert "/Users/" not in text and "/home/" not in text
    assert "__REPOSITORY__" in text and "__VENV_PYTHON__" in text
    with PLIST.open("rb") as handle:
        plist = plistlib.load(handle)
    for key in ("StandardOutPath", "StandardErrorPath"):
        assert plist[key].startswith("__REPOSITORY__/data/prospective/logs/")
        assert "/v1/" not in plist[key]
    for phrase in ("LOCAL TIME", "00:30", "09:00", "America/New_York"):
        assert phrase in text


def test_the_launchd_example_is_not_installed():
    agents = pathlib.Path.home() / "Library" / "LaunchAgents"
    if agents.exists():
        assert not [p for p in agents.iterdir() if "prospective" in p.name]


def test_the_scheduling_guidance_is_corrected():
    outcomes = (REPO / "docs" / "outcomes.md").read_text()
    assert "A daily run after the US close" not in outcomes
    assert "prospective_collection.md" in outcomes
    guide = (REPO / "docs" / "prospective_collection.md").read_text()
    for phrase in ("00:30", "09:00", "America/New_York", "MISSED_COLLECTION",
                   "OUTSIDE_COLLECTION_WINDOW", "not activated", "Level 1"):
        assert phrase in guide, phrase
    adr = (REPO / "docs" / "adr" / "0013-prospective-collection-and-holdout.md").read_text()
    for phrase in ("2025-03-01", "causal lookback", "M2", "write-once", "no backfill"):
        assert phrase.lower() in adr.lower(), phrase
