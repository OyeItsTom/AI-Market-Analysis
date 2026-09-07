"""Phase 10 Stage F architecture, enforced by import analysis rather than review.

    dashboard -> application -> scanner domain

``scanner_view.py`` is render-only, and ``app.py`` reaches the scanner only
through the application layer -- so the dashboard never names a scanner-domain
module, and the config file is read only by the adapter that owns it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
VIEW = SRC / "dashboard" / "scanner_view.py"
APP = SRC / "dashboard" / "app.py"
VIEW_MODELS = SRC / "application" / "view_models.py"

FILE_PRIMITIVES = {"open", "read_text", "write_text", "read_bytes", "write_bytes",
                   "to_csv", "read_csv", "unlink", "mkdir", "rmdir", "touch"}
IO_MODULES = {"json", "pickle", "marshal", "shelve", "yaml", "toml", "csv", "os", "shutil"}


def imported(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                names.add(node.module)
    return names


def imports_package(names: set[str], package: str) -> bool:
    return any(n == package or n.startswith(package + ".") for n in names)


def identifiers(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.alias):
            out.add((node.asname or node.name).split(".")[0])
    return out


def called(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def attribute_calls(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def function_body(path: pathlib.Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} defines no {name}()")


def assigned_names(node: ast.AST) -> set[str]:
    """Every name and string subscript this code writes to."""
    out: set[str] = set()
    for child in ast.walk(node):
        targets = []
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
        elif isinstance(child, (ast.AugAssign, ast.AnnAssign)):
            targets = [child.target]
        for target in targets:
            if isinstance(target, ast.Name):
                out.add(target.id)
            elif isinstance(target, ast.Attribute):
                out.add(target.attr)
            elif isinstance(target, ast.Subscript):
                index = target.slice
                if isinstance(index, ast.Constant) and isinstance(index.value, str):
                    out.add(index.value)
    return out


def words(path: pathlib.Path) -> set[str]:
    """Identifier-like words, so a substring never masquerades as a match."""
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", path.read_text(encoding="utf-8")))


def test_the_scanner_view_exists():
    assert VIEW.is_file()


# -- render-only ---------------------------------------------------------


def test_the_scanner_view_owns_no_widget():
    """Every control lives in app.py, as in the news and feeds panels."""
    source = VIEW.read_text(encoding="utf-8")
    for widget in ("st.button", "st.selectbox", "st.text_input", "st.radio",
                   "st.checkbox", "st.form", "st.slider", "st.file_uploader"):
        assert widget not in source, f"scanner_view creates {widget}"
    assert "key=" not in source, "scanner_view declares a widget key"


def test_the_scanner_view_imports_only_streamlit_and_view_models():
    for name in imported(VIEW):
        root = name.split(".")[0]
        if root == "src":
            assert name == "src.application.view_models", name
        else:
            assert root in {"__future__", "typing"} or root == "streamlit", name


@pytest.mark.parametrize(
    "package",
    ["src.scanner", "src.data", "src.assessments", "src.application.scanner",
     "src.application.snapshot", "src.news", "src.feeds", "src.portfolio"],
)
def test_the_scanner_view_never_imports_a_domain_package(package):
    assert not imports_package(imported(VIEW), package)


def test_the_scanner_view_calls_no_service():
    used = identifiers(VIEW)
    for forbidden in ("MarketScanner", "scan", "load_universes", "build_snapshot",
                      "session_state"):
        assert forbidden not in used, f"scanner_view uses {forbidden}"


# -- app.py layering -----------------------------------------------------


def test_the_dashboard_never_imports_the_scanner_domain():
    """Config and orchestration both arrive through the application layer."""
    for path in sorted((SRC / "dashboard").rglob("*.py")):
        assert not imports_package(imported(path), "src.scanner"), path.name


def test_app_reaches_the_scanner_only_through_the_application_layer():
    names = imported(APP)
    assert imports_package(names, "src.application.scanner")
    assert not imports_package(names, "src.scanner")


def test_app_does_not_reimplement_domain_logic():
    """Reading ``snapshot.universe_fingerprint`` is fine; recomputing it is not.

    So this looks for *calls*, not for the name anywhere -- the staleness check
    legitimately compares a fingerprint the domain already produced.
    """
    invoked = called(APP) | attribute_calls(APP)
    for forbidden in ("eligibility_for", "category_for", "rank_key", "order_results",
                      "status_for", "universe_fingerprint", "normalize_symbol",
                      "assess", "build_evidence", "ranked_rows"):
        assert forbidden not in invoked, f"app.py computes {forbidden} itself"


# -- file I/O ------------------------------------------------------------


@pytest.mark.parametrize("path", [APP, VIEW, VIEW_MODELS], ids=lambda p: p.name)
def test_stage_f_modules_perform_no_file_io(path):
    """Only the scanner config adapter may read a file, and it only reads."""
    calls = called(path) | attribute_calls(path)
    assert not (calls & FILE_PRIMITIVES), calls & FILE_PRIMITIVES
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in IO_MODULES:
                assert node.func.attr not in {"load", "dump", "loads", "dumps"}, (
                    f"{path.name} performs {receiver.id}.{node.func.attr}"
                )


# -- firewalls -----------------------------------------------------------


def test_the_market_panel_creates_no_paper_action():
    """Selecting a result and opening it in Research is the only action."""
    source = APP.read_text(encoding="utf-8")
    panel = source.split("def render_market_panel")[1].split("\ndef ")[0]
    for forbidden in ("PaperIntent", "OpenLongIntent", "CloseIntent",
                      "PaperPortfolio", "apply_open_long", "apply_close"):
        assert forbidden not in panel, f"the market panel uses {forbidden}"


def test_the_scan_path_touches_no_news_or_feeds():
    source = APP.read_text(encoding="utf-8")
    scan = source.split("def scan_market")[1].split("\ndef ")[0]
    for forbidden in ("news", "feed", "News", "Feed"):
        assert forbidden not in scan, f"scan_market references {forbidden}"


def test_no_background_work_was_introduced():
    for path in (APP, VIEW, VIEW_MODELS):
        names = imported(path)
        for module in ("threading", "asyncio", "multiprocessing", "concurrent",
                       "sched", "schedule", "apscheduler"):
            assert not imports_package(names, module), f"{path.name} imports {module}"
        used = identifiers(path)
        for forbidden in ("Thread", "Timer", "ThreadPoolExecutor", "create_task"):
            assert forbidden not in used, f"{path.name} uses {forbidden}"


def test_no_cancellation_or_eta_was_introduced():
    """Both were explicitly deferred by the benchmark decision."""
    vocabulary = {w.lower() for w in words(APP) | words(VIEW)}
    for forbidden in ("cancel", "cancelled", "cancellation", "eta",
                      "estimated_completion", "time_remaining", "remaining_seconds"):
        assert forbidden not in vocabulary, f"Stage F introduced {forbidden}"


def test_no_scanner_persistence():
    for path in (APP, VIEW, VIEW_MODELS):
        used = identifiers(path)
        assert "CsvBarStore" not in used
        assert "src.data.storage" not in path.read_text(encoding="utf-8")


def test_the_handoff_never_assigns_symbol_input_after_the_widget():
    """symbol_input may be written only in the pre-widget apply step."""
    assert "symbol_input" in assigned_names(
        function_body(APP, "apply_pending_research_symbol")
    ), "the pre-widget step never applies the parked symbol"
    for name in ("open_in_research", "render_market_panel", "scan_market"):
        assert "symbol_input" not in assigned_names(function_body(APP, name)), (
            f"{name}() writes the widget key after the widget exists"
        )
    assert "pending_research_symbol" in assigned_names(
        function_body(APP, "open_in_research")
    ), "the handoff parks nothing"


def test_the_pending_apply_runs_before_render_controls():
    """Ordering is load-bearing: after the widget exists, Streamlit refuses."""
    source = APP.read_text(encoding="utf-8")
    main = source.split("def main()")[1]
    assert main.index("apply_pending_research_symbol()") < main.index("render_controls()")


def test_market_overview_is_the_first_tab():
    source = APP.read_text(encoding="utf-8")
    assert '"Market Overview", "Research", "News", "External feeds", "Paper portfolio"' in source


# -- who guards the guards ------------------------------------------------
#
# The three legacy compatibility whitelists are ``<=`` assertions, so widening
# one can never fail the test that owns it: a mutation that adds "os" to the
# import allowlist, or "scan_results" to the session allowlist, survives
# silently. These pin the exact membership so a later phase has to argue a new
# entry in here too, rather than slipping it in where nothing is watching.

LEGACY_BOUNDARIES = REPO / "tests" / "test_dashboard_boundaries.py"
LEGACY_SMOKE = REPO / "tests" / "test_dashboard_smoke.py"


def allowlist_in(path: pathlib.Path, function: str) -> set[str]:
    """The string members of the set literal ``function`` asserts against.

    Selected structurally rather than by position: these functions also contain
    set literals used for control flow, and an index would silently read the
    wrong one the moment either file is re-ordered.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == function), None)
    assert node is not None, f"{path.name} defines no {function}()"
    sets = [n for statement in node.body if isinstance(statement, ast.Assert)
            for n in ast.walk(statement) if isinstance(n, ast.Set)]
    sets += [n for statement in ast.walk(node) if isinstance(statement, ast.Assert)
             for n in ast.walk(statement) if isinstance(n, ast.Set)]
    assert sets, f"{function} asserts against no set literal"
    return {e.value for e in sets[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)}


def test_the_legacy_import_allowlist_is_exactly_this():
    allowed = allowlist_in(
        LEGACY_BOUNDARIES, "test_dashboard_imports_only_streamlit_stdlib_and_application"
    )
    assert allowed == {
        "__future__", "dataclasses", "datetime", "decimal", "typing",
        "traceback", "enum", "types", "pathlib", "collections", "time",
    }, "the dashboard import allowlist was widened"


def test_the_legacy_session_allowlist_is_exactly_this():
    allowed = allowlist_in(
        LEGACY_BOUNDARIES, "test_the_dashboard_holds_only_whole_snapshots_between_runs"
    )
    assert allowed == {
        "snapshot", "failure", "paper", "paper_error", "provider", "clock",
        "news_snapshot", "news_service", "news_failure",
        "feed_snapshot", "feed_service", "feed_failure",
        "scan_snapshot", "scan_failure", "scan_universes",
        "scan_universe_id", "pending_research_symbol",
    }, "the session-state allowlist was widened"


def test_the_legacy_button_allowlist_is_exactly_this():
    """Two names come from module constants, so compare what can be compared."""
    allowed = allowlist_in(
        LEGACY_SMOKE, "test_the_research_panel_offers_no_paper_action_control"
    )
    assert allowed == {
        "refresh_button", "refresh_news_button", "refresh_feeds_button",
        "reload_universes_button", "scan_market_button",
    }, "the control allowlist was widened"
    source = LEGACY_SMOKE.read_text(encoding="utf-8")
    block = source.split("def test_the_research_panel_offers_no_paper_action_control")[1]
    assert "OPEN_SUBMIT, CLOSE_SUBMIT," in block, "the paper form submitters changed"


def test_the_scanner_adds_no_paper_or_trading_control_key():
    """Every widget key app.py declares, checked against forbidden vocabulary."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    keys = {kw.value.value for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg == "key" and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)}
    assert "scan_market_button" in keys, "the campaign anchor moved; update this test"
    for key in keys:
        for forbidden in ("buy", "sell", "open_long", "close_position", "trade", "order"):
            assert forbidden not in key, f"{key} looks like a trading control"
