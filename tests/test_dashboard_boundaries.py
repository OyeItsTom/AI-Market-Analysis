"""Phase 7 architecture and scope, enforced by import analysis rather than review.

The dependency direction is::

    dashboard  ->  application  ->  Phase 1-6 domain

Every rule below is checked against the parsed source, so a boundary cannot be
crossed by an import that merely looks harmless in a diff. The Phase 5/6
independence checks are repeated here because Phase 7 puts research and paper
actions on the same screen for the first time -- the one place where a shortcut
between them would be tempting.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"

DOMAIN_PACKAGES = (
    "src.data",
    "src.features",
    "src.strategies",
    "src.assessments",
    "src.portfolio",
    "src.evaluation",
    "src.backtesting",
    "src.signals",
)


def python_files(*relative: str) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for part in relative:
        root = REPO / part
        if root.is_file():
            found.append(root)
        else:
            found += sorted(root.rglob("*.py"))
    return found


def imported_modules(path: pathlib.Path) -> set[str]:
    """Every module name this file imports, at any depth in the file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside its own package
                continue
            if node.module:
                names.add(node.module)
    return names


def imports_package(names: set[str], package: str) -> bool:
    return any(name == package or name.startswith(package + ".") for name in names)


def code_identifiers(path: pathlib.Path) -> set[str]:
    """Every identifier the file actually *uses*, ignoring prose.

    Docstrings and comments are documentation: a module that explains "no code
    path turns BULLISH into OPEN_LONG" must not be reported as doing it. Only
    names, attributes and imported symbols count as capability.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


DASHBOARD_FILES = python_files("src/dashboard")
APPLICATION_FILES = python_files("src/application")
DOMAIN_FILES = [
    path
    for path in python_files("src")
    if "application" not in path.parts and "dashboard" not in path.parts
]


def test_the_phase_seven_packages_exist():
    assert DASHBOARD_FILES and APPLICATION_FILES and DOMAIN_FILES


# -- dashboard -> application only --------------------------------------


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", DOMAIN_PACKAGES)
def test_dashboard_never_imports_a_domain_package(path, package):
    names = imported_modules(path)
    assert not imports_package(names, package), (
        f"{path.relative_to(REPO)} imports {package} directly; the dashboard may "
        "only reach the domain through src.application"
    )


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_dashboard_imports_only_streamlit_stdlib_and_application(path):
    for name in imported_modules(path):
        root = name.split(".")[0]
        if root in {"streamlit", "src"}:
            if root == "src":
                assert name.startswith("src.application") or name.startswith(
                    "src.dashboard"
                ), f"{path.name} imports {name}"
            continue
        # Anything else must be the standard library.
        assert root in {
            "__future__", "dataclasses", "datetime", "decimal", "typing",
            "traceback", "enum", "types", "pathlib", "collections",
        }, f"{path.name} imports unexpected third-party module {name}"


# -- application never imports the UI -----------------------------------


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=lambda p: p.name)
def test_application_never_imports_streamlit(path):
    assert not imports_package(imported_modules(path), "streamlit"), (
        f"{path.relative_to(REPO)} imports streamlit; the application layer must "
        "stay headlessly testable"
    )


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=lambda p: p.name)
def test_application_never_imports_the_dashboard(path):
    assert not imports_package(imported_modules(path), "src.dashboard")


# -- domain never learns about Phase 7 ----------------------------------


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_domain_never_imports_the_application_layer(path):
    names = imported_modules(path)
    assert not imports_package(names, "src.application")
    assert not imports_package(names, "src.dashboard")


def test_no_phase_one_to_six_source_was_modified_to_reach_phase_seven():
    """Belt and braces: not one domain file mentions the new packages at all."""
    for path in DOMAIN_FILES:
        text = path.read_text()
        assert "src.application" not in text
        assert "src.dashboard" not in text


# -- the research-to-action firewall ------------------------------------


def test_paper_module_never_imports_the_assessment_package():
    names = imported_modules(SRC / "application" / "paper.py")
    assert not imports_package(names, "src.assessments")
    assert not imports_package(names, "src.strategies")


def test_assessments_and_portfolio_stay_independent():
    for path in python_files("src/assessments"):
        assert not imports_package(imported_modules(path), "src.portfolio")
    for path in python_files("src/portfolio"):
        assert not imports_package(imported_modules(path), "src.assessments")
        assert not imports_package(imported_modules(path), "src.strategies")


def test_the_paper_view_cannot_render_an_assessment():
    """The paper panel has no way to show research state as a reason to act.

    Checked against used identifiers, not raw text: the module's docstring
    explains the rule, and explaining a rule is not breaking it.
    """
    used = code_identifiers(SRC / "dashboard" / "paper_view.py")
    for forbidden in (
        "AssessmentView", "assessment_view", "AssessmentState", "ResearchState",
    ):
        assert forbidden not in used


def test_the_research_view_has_no_action_control():
    """No button, form or submit control may exist on the research panel."""
    tree = ast.parse((SRC / "dashboard" / "research_view.py").read_text())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("button", "form", "form_submit_button", "download_button"):
        assert forbidden not in called, f"research_view calls st.{forbidden}"


def test_the_research_view_cannot_touch_paper_state():
    text = (SRC / "dashboard" / "research_view.py").read_text()
    for forbidden in ("PaperSession", "open_long", "close_position", "portfolio"):
        assert forbidden not in text


#: Identifiers through which a research classification could be read.
RESEARCH_STATE_NAMES = {
    "AssessmentState", "ResearchState", "ResearchAssessment", "AssessmentView",
    "ResearchObservation",
}


def test_the_mutating_module_cannot_see_a_research_state():
    """``paper.py`` has no identifier through which a state could be read.

    This is the firewall in its strongest form: not "it does not currently
    branch on BULLISH", but "there is no name in scope that could be branched
    on". Prose is ignored -- the module's docstring explains the rule.
    """
    used = code_identifiers(SRC / "application" / "paper.py")
    assert not (used & RESEARCH_STATE_NAMES)


def test_no_research_value_reaches_an_action_call():
    """Every argument of an ``open_long`` call comes from the human's form.

    ``app.py`` is the one module that legitimately renders research *and*
    applies paper actions, so the check is on the call itself: nothing derived
    from the snapshot or the assessment may appear in its arguments.
    """
    forbidden_sources = {"snapshot", "assessment", "state", "observations"}
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name not in {"open_long", "close_position"}:
                continue
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                for inner in ast.walk(argument):
                    if isinstance(inner, ast.Name):
                        assert inner.id not in forbidden_sources, (
                            f"{path.name}: {name}() receives {inner.id!r}"
                        )


#: Names through which a research classification could be reached.
RESEARCH_VALUE_NAMES = {
    "snapshot", "assessment", "observations", "state", "counts",
    "AssessmentState", "ResearchState", "ResearchAssessment", "AssessmentView",
    "is_conflicted", "is_insufficient", "bullish", "bearish", "conflicted",
}

#: Every function that changes paper state.
MUTATOR_NAMES = {"open_long", "close_position", "apply", "apply_open_long", "apply_close"}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    links: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            links[child] = node
    return links


def _mentions_research(expression: ast.AST) -> str | None:
    for node in ast.walk(expression):
        if isinstance(node, ast.Name) and node.id in RESEARCH_VALUE_NAMES:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in RESEARCH_VALUE_NAMES:
            return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in {"bullish", "bearish", "conflicted"}:
                return node.value
    return None


def test_no_paper_action_is_conditional_on_a_research_state():
    """No action may be *gated* on what the research said.

    The companion test below checks data flow -- that no research value is
    passed as an argument. This one checks control flow, which is the form the
    forbidden mapping would actually take::

        if assessment.state == BULLISH:      # <- this
            session.open_long(...)

    Nothing derived from a research classification may decide *whether* a paper
    action happens, which is the whole ``BULLISH -> OPEN_LONG`` prohibition.
    """
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        links = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if called not in MUTATOR_NAMES:
                continue
            current: ast.AST | None = node
            while current is not None:
                parent = links.get(current)
                if isinstance(parent, (ast.If, ast.While)) and current is not parent.test:
                    culprit = _mentions_research(parent.test)
                    assert culprit is None, (
                        f"{path.name}: {called}() is conditional on {culprit!r}; "
                        "a research state must never decide whether a paper "
                        "action happens"
                    )
                elif isinstance(parent, ast.IfExp) and current is not parent.test:
                    culprit = _mentions_research(parent.test)
                    assert culprit is None, (
                        f"{path.name}: {called}() is conditional on {culprit!r}"
                    )
                current = parent


def test_portfolio_apply_is_never_called_from_rendering_code():
    """Mutation belongs to the application layer, not to a render pass."""
    for path in DASHBOARD_FILES:
        text = path.read_text()
        assert ".apply(" not in text, f"{path.name} applies an intent directly"


def test_only_the_paper_session_mutates_the_portfolio():
    applies = [
        path
        for path in python_files("src/application", "src/dashboard")
        if ".apply(" in path.read_text()
    ]
    assert [path.name for path in applies] == ["paper.py"]


# -- loopback / network exposure ----------------------------------------

CONFIG = REPO / ".streamlit" / "config.toml"


def active_config_lines() -> list[str]:
    """Configuration lines only -- comments are documentation, not settings."""
    lines = []
    for raw in CONFIG.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def test_streamlit_config_exists():
    assert CONFIG.is_file()


def test_loopback_address_is_configured_explicitly():
    assert 'address = "127.0.0.1"' in active_config_lines()


def test_the_config_never_binds_to_all_interfaces():
    for line in active_config_lines():
        assert "0.0.0.0" not in line


def test_no_phase_seven_runtime_file_configures_all_interfaces():
    """A comment warning against 0.0.0.0 is fine; a setting is not."""
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        for raw in path.read_text().splitlines():
            code = raw.split("#", 1)[0]
            assert "0.0.0.0" not in code, f"{path.name}: {raw.strip()}"


def test_streamlit_resolves_the_loopback_address():
    """The installed Streamlit must actually accept this configuration."""
    from streamlit import config

    config.get_config_options()
    assert config.get_option("server.address") == "127.0.0.1"


# -- scope: nothing Phase 7 must not contain ----------------------------

FORBIDDEN_IMPORTS = (
    "sqlite3", "sqlalchemy", "psycopg2", "pymongo", "redis",
    "openai", "anthropic", "langchain", "transformers",
    "telegram", "telethon", "discord", "smtplib",
    "alpaca_trade_api", "ib_insync", "ccxt", "robin_stocks",
    "schedule", "apscheduler", "celery", "croniter",
    "subprocess", "socket", "http.server", "flask", "fastapi",
    "keyring", "boto3", "paramiko",
)


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_imports_nothing_out_of_scope(path):
    names = imported_modules(path)
    for forbidden in FORBIDDEN_IMPORTS:
        assert not imports_package(names, forbidden), (
            f"{path.relative_to(REPO)} imports {forbidden}"
        )


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_calls_no_dynamic_execution(path):
    """AST-aware: the *call*, not the word appearing in prose."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "eval",
                "exec",
                "compile",
                "__import__",
            }, f"{path.name} calls {node.func.id}()"


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_opens_no_files(path):
    """No persistence and no user-controlled file access anywhere in Phase 7."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                pytest.fail(f"{path.name} calls open()")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "write_text", "read_text", "to_csv", "read_csv", "dump", "load"
            }:
                pytest.fail(f"{path.name} performs file I/O via {node.func.attr}")


def test_phase_seven_never_touches_the_csv_bar_store():
    """CsvBarStore is explicitly out of scope for V1."""
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        text = path.read_text()
        assert "CsvBarStore" not in text
        assert "src.data.storage" not in text


def test_the_dashboard_offers_no_unsettled_bar_control():
    for path in DASHBOARD_FILES:
        assert "include_unsettled" not in path.read_text()


def test_the_application_only_ever_requests_settled_bars():
    text = (SRC / "application" / "snapshot.py").read_text()
    assert "include_unsettled=False" in text
    assert "include_unsettled=True" not in text


def test_the_dashboard_offers_no_price_basis_toggle():
    for path in DASHBOARD_FILES:
        text = path.read_text()
        assert "SPLIT_AND_DIVIDEND_ADJUSTED" not in text
        assert "PriceBasis" not in text


# -- the snapshot is the only cache -------------------------------------


def test_nothing_caches_a_derived_value_independently():
    """No memoisation may outlive the snapshot it was derived from.

    A cached assessment or feature series could survive a Refresh that replaced
    the bars, which is precisely the "fresh bars beside a stale assessment"
    state ``ResearchSnapshot`` exists to make unrepresentable. The snapshot is
    the only thing held between runs.
    """
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            assert name not in {
                "cache_data", "cache_resource", "cache", "lru_cache", "memoize"
            }, f"{path.name} memoises a derived value ({name})"


def test_the_dashboard_holds_only_whole_snapshots_between_runs():
    """Session state carries the snapshot itself, not pieces of one."""
    tree = ast.parse((SRC / "dashboard" / "app.py").read_text())
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(
                    target.value, ast.Name
                ) and target.value.id == "state":
                    assigned.add(target.attr)
    # Whole objects only: no observations, features or assessment stored apart.
    # The news_* keys are Phase 8 additions and are whole objects too:
    # news_snapshot is a complete NewsSnapshot, news_service an application
    # dependency, news_failure a complete classified failure.
    assert assigned <= {
        "snapshot", "failure", "paper", "paper_error", "provider", "clock",
        "news_snapshot", "news_service", "news_failure",
    }
    for forbidden in ("observations", "assessment", "features", "series"):
        assert forbidden not in assigned
