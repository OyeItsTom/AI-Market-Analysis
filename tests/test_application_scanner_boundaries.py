"""Phase 10 Stage E boundaries, enforced by import analysis rather than review.

    dashboard -> application/scanner -> {scanner domain, application/snapshot}

The orchestrator sits above the scanner domain, so it may import the application
error taxonomy that the domain deliberately cannot. What it may not do is reach
sideways into news, feeds or paper trading, or downwards into the filesystem.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULE = REPO / "src" / "application" / "scanner.py"

FILE_PRIMITIVES = {
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "to_csv", "read_csv", "unlink", "mkdir", "rmdir", "touch",
}
IO_MODULES = {"json", "pickle", "marshal", "shelve", "yaml", "toml", "csv", "os", "shutil"}


def imported(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                names.add(node.module)
    return names


def imports_package(names: set[str], package: str) -> bool:
    return any(name == package or name.startswith(package + ".") for name in names)


def code_identifiers(path: pathlib.Path) -> set[str]:
    """Identifiers used, ignoring prose, so a docstring cannot fail its own module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


def called_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def attribute_calls(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_the_orchestrator_exists():
    assert MODULE.is_file()


# -- no sideways or upward reach ----------------------------------------


@pytest.mark.parametrize(
    "package",
    ["src.dashboard", "streamlit", "src.news", "src.feeds", "src.portfolio",
     "src.data.storage", "src.evaluation", "src.backtesting"],
)
def test_the_orchestrator_never_imports_a_forbidden_package(package):
    assert not imports_package(imported(MODULE), package), (
        f"src/application/scanner.py imports {package}"
    )


def test_the_orchestrator_imports_only_permitted_sources():
    for name in imported(MODULE):
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith(
                ("src.scanner", "src.application.snapshot", "src.application.errors",
                 "src.data", "src.assessments")
            ), f"unexpected import {name}"
            continue
        assert root in {"__future__", "dataclasses", "datetime", "typing"}, name


def test_no_new_dependency_is_introduced():
    """Everything the orchestrator needs already ships with the project."""
    third_party = {
        name for name in imported(MODULE)
        if not name.startswith("src.")
        and name.split(".")[0] not in {"__future__", "dataclasses", "datetime", "typing"}
    }
    assert third_party == set()


# -- firewalls -----------------------------------------------------------


def test_no_news_or_feed_reference():
    used = code_identifiers(MODULE)
    for forbidden in ("NewsSnapshot", "FeedSnapshot", "NewsService", "FeedService"):
        assert forbidden not in used, forbidden


def test_no_paper_reference():
    used = code_identifiers(MODULE)
    for forbidden in ("PaperIntent", "OpenLongIntent", "CloseIntent", "PaperAction",
                      "PaperPortfolio", "RiskDecision", "RiskPolicy"):
        assert forbidden not in used, forbidden


def test_no_llm_sentiment_or_telegram():
    used = {name.lower() for name in code_identifiers(MODULE)}
    names = imported(MODULE)
    for forbidden in ("openai", "anthropic", "llm", "sentiment", "embedding",
                      "telegram", "telethon", "pyrogram"):
        assert forbidden not in used, forbidden
        assert not imports_package(names, forbidden)


def test_nothing_runs_in_the_background():
    """Serial by decision. Concurrency is not authorized before measurement."""
    names = imported(MODULE)
    for module in ("threading", "asyncio", "multiprocessing", "concurrent",
                   "sched", "schedule", "apscheduler", "celery"):
        assert not imports_package(names, module), module
    used = code_identifiers(MODULE)
    for forbidden in ("Thread", "Timer", "ThreadPoolExecutor", "ProcessPoolExecutor",
                      "create_task", "gather", "BackgroundScheduler"):
        assert forbidden not in used, forbidden


def test_no_persistence_of_any_kind():
    used = code_identifiers(MODULE)
    assert "CsvBarStore" not in used
    assert "src.data.storage" not in MODULE.read_text(encoding="utf-8")
    calls = called_names(MODULE) | attribute_calls(MODULE)
    assert not (calls & FILE_PRIMITIVES), calls & FILE_PRIMITIVES
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in IO_MODULES:
                pytest.fail(f"persistence via {receiver.id}.{node.func.attr}")


def test_no_direct_network_capability():
    """The only market-data work goes through the injected snapshot builder."""
    names = imported(MODULE)
    for module in ("http", "urllib", "requests", "httpx", "socket", "ssl"):
        assert not imports_package(names, module), module


def test_no_dashboard_or_session_state():
    """Checked on identifiers and imports, not raw substrings.

    A prose check for ``st.`` matches ordinary English ("must.", "list.") and
    would fail on its own docstring -- the kind of test that forces worse
    writing rather than catching a real dependency.
    """
    names = imported(MODULE)
    assert not imports_package(names, "streamlit")
    assert not imports_package(names, "src.dashboard")
    used = code_identifiers(MODULE)
    for forbidden in ("session_state", "st", "sidebar", "text_input", "selectbox",
                      "button", "rerun"):
        assert forbidden not in used, forbidden


def test_no_scoring_vocabulary_in_identifiers():
    used = {name.lower() for name in code_identifiers(MODULE)}
    for forbidden in ("score", "confidence", "probability", "rating", "conviction",
                      "price_target", "recommendation"):
        assert forbidden not in used, forbidden


# -- the research pipeline is reused, not reimplemented ------------------


def test_the_orchestrator_reuses_build_snapshot():
    assert "build_snapshot" in imported(MODULE) or "build_snapshot" in code_identifiers(MODULE)


def test_no_research_logic_is_reimplemented():
    """No feature, hypothesis or assessment call appears here."""
    used = code_identifiers(MODULE)
    for forbidden in ("assess", "build_evidence", "evaluate_at", "FeatureSeries",
                      "EvidenceSet", "ResearchHypothesis"):
        assert forbidden not in used, f"scanner reimplements research via {forbidden}"


def test_ranking_and_status_use_the_locked_helpers():
    used = code_identifiers(MODULE)
    assert "status_for" in used, "status must not be re-derived"
    assert "from_results" in used, "counters must not be hand-built"
    assert "category_for" in used
    assert "eligibility_for" in used


def test_no_research_state_is_mutated():
    """Nothing here assigns to a research object's attribute."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    assert target.attr not in {
                        "assessment", "observations", "features", "state", "series"
                    }, f"mutates research state: {target.attr}"


# -- scope ---------------------------------------------------------------


def test_stage_f_files_do_not_exist_yet():
    for path in ("src/dashboard/scanner_view.py", "docs/scanner.md",
                 "docs/adr/0008-market-scanner.md", "config/universes.local.json"):
        assert not (REPO / path).exists(), f"{path} belongs to a later stage"


def test_the_scanner_domain_still_imports_no_application_module():
    """Stage E must not have loosened the Stage A-D leaf property."""
    for path in sorted((REPO / "src" / "scanner").rglob("*.py")):
        assert not imports_package(imported(path), "src.application"), path.name


# -- the assumption Stage E's metadata rests on --------------------------


def test_build_snapshot_offers_no_policy_or_ensemble_injection():
    """Stage E reports policy metadata it derives itself, which is only sound
    while ``build_snapshot`` has exactly one policy path.

    If a future change lets a caller inject a different ensemble or policy, the
    scanner's independently-derived metadata would describe the default while
    the scan actually ran something else -- and the snapshot would be quietly
    wrong. This pins that assumption so the change cannot pass unnoticed.
    """
    import inspect

    from src.application.snapshot import build_snapshot

    parameters = set(inspect.signature(build_snapshot).parameters)
    assert parameters == {"provider", "symbol", "interval", "now"}, (
        f"build_snapshot's signature changed to {sorted(parameters)}; Stage E "
        "derives policy metadata independently and must be re-reviewed"
    )


def test_the_scanner_reads_policy_metadata_dynamically_not_by_copying():
    """The values must come from the research module, not be duplicated here.

    A literal 51 or 2 in the scanner would silently stop describing reality the
    day the research configuration changed.
    """
    source = MODULE.read_text(encoding="utf-8")
    assert "WARMUP_BARS" in source and "MINIMUM_SUFFICIENT_OBSERVATIONS" in source
    tree = ast.parse(source)
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    assert 51 not in literals, "warm-up bars is hard-coded"
    assert not ({2, 3} & literals), "a policy threshold appears to be hard-coded"


def test_the_scanner_derives_the_fingerprint_rather_than_storing_one():
    """A pasted fingerprint would describe a policy that no longer exists."""
    source = MODULE.read_text(encoding="utf-8")
    from src.application.snapshot import build_ensemble, build_policy

    live = build_policy(build_ensemble()).fingerprint
    assert live not in source, "the policy fingerprint is hard-coded"
    assert "build_policy(build_ensemble())" in source
