"""Phase 8 architecture, enforced by import analysis rather than review.

    dashboard -> application -> news domain/adapters/store

The firewall that matters most is the one between news and everything that
decides: no headline may reach a research state or a paper action. It is
enforced structurally -- ``src/news`` has no name in scope through which a
``ResearchAssessment`` or a ``PaperIntent`` could be reached.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"

NEWS_FILES = sorted((SRC / "news").rglob("*.py"))
APPLICATION_NEWS = [SRC / "application" / "news.py"]
DASHBOARD_FILES = sorted((SRC / "dashboard").rglob("*.py"))
DOMAIN_PACKAGES = (
    "src.data", "src.features", "src.strategies", "src.assessments",
    "src.portfolio", "src.evaluation", "src.backtesting", "src.signals",
)
PRE_PHASE_8_DOMAIN = [
    path
    for path in sorted(SRC.rglob("*.py"))
    if not {"news", "dashboard"} & set(path.parts)
    and path.name != "news.py"
]


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
    """Identifiers the file actually uses, ignoring prose.

    A module that explains "no headline can reach an assessment" must not be
    reported as reaching one.
    """
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


def test_the_phase_eight_packages_exist():
    assert NEWS_FILES and DASHBOARD_FILES and PRE_PHASE_8_DOMAIN


# -- news imports nothing that decides -----------------------------------


@pytest.mark.parametrize("path", NEWS_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", ["src.strategies", "src.assessments", "src.portfolio"])
def test_news_never_imports_a_deciding_package(path, package):
    assert not imports_package(imported(path), package), (
        f"{path.relative_to(REPO)} imports {package}; a news record must have no "
        "route to a research state or a paper action"
    )


@pytest.mark.parametrize("path", NEWS_FILES, ids=lambda p: p.name)
def test_news_never_imports_the_dashboard_or_streamlit(path):
    names = imported(path)
    assert not imports_package(names, "streamlit")
    assert not imports_package(names, "src.dashboard")


@pytest.mark.parametrize("path", NEWS_FILES, ids=lambda p: p.name)
def test_news_never_imports_the_application_layer(path):
    assert not imports_package(imported(path), "src.application")


@pytest.mark.parametrize("path", NEWS_FILES, ids=lambda p: p.name)
def test_news_imports_only_stdlib_and_itself(path):
    for name in imported(path):
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith("src.news"), f"{path.name} imports {name}"
            continue
        assert root in {
            "__future__", "dataclasses", "datetime", "enum", "json", "hashlib",
            "os", "pathlib", "types", "typing", "urllib", "collections", "decimal",
            # Used only inside EDGAR's lazy default_fetch_fn, which is the one
            # place a real request is made; see test_news_security.py.
            "gzip", "time",
            # The single third-party import, and it is lazy: it lives inside the
            # real fetch function so no test ever loads it.
            "yfinance",
        }, f"{path.name} imports unexpected module {name}"


def test_the_only_third_party_import_is_lazy():
    """yfinance must not be imported at module level, or importing the news
    package would pull the whole vendor library into every test."""
    tree = ast.parse((SRC / "news" / "sources" / "yahoo.py").read_text(encoding="utf-8"))
    for node in tree.body:  # module level only
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            assert not any("yfinance" in n for n in names), "yfinance is imported eagerly"


# -- the deciding packages never learn about news ------------------------


@pytest.mark.parametrize("path", PRE_PHASE_8_DOMAIN, ids=lambda p: str(p.relative_to(SRC)))
def test_no_phase_one_to_seven_module_imports_news(path):
    names = imported(path)
    assert not imports_package(names, "src.news")
    assert not imports_package(names, "src.application.news")
    assert not imports_package(names, "src.dashboard")


def test_no_phase_one_to_seven_source_mentions_the_news_packages():
    for path in PRE_PHASE_8_DOMAIN:
        text = path.read_text(encoding="utf-8")
        assert "src.news" not in text, path


# -- application layer ---------------------------------------------------


@pytest.mark.parametrize("path", APPLICATION_NEWS, ids=lambda p: p.name)
def test_the_application_news_module_imports_no_ui(path):
    assert not imports_package(imported(path), "streamlit")


def test_the_application_news_module_touches_no_research_or_paper_package():
    names = imported(SRC / "application" / "news.py")
    for package in ("src.strategies", "src.assessments", "src.portfolio", "src.evaluation"):
        assert not imports_package(names, package)


def test_the_news_snapshot_is_not_part_of_the_research_snapshot():
    """Merging them would imply Phase 3-6 research consumes news."""
    text = (SRC / "application" / "snapshot.py").read_text(encoding="utf-8")
    assert "news" not in text.lower()
    assert "NewsSnapshot" not in text


def test_the_research_snapshot_module_was_not_modified_for_news():
    used = code_identifiers(SRC / "application" / "snapshot.py")
    for forbidden in ("NewsSnapshot", "NewsItem", "OfficialFiling", "NewsService"):
        assert forbidden not in used


# -- dashboard -----------------------------------------------------------


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_the_dashboard_never_imports_the_news_domain(path):
    """It must reach news through the application layer, like everything else."""
    assert not imports_package(imported(path), "src.news")


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", DOMAIN_PACKAGES)
def test_the_dashboard_never_imports_a_domain_package(path, package):
    assert not imports_package(imported(path), package)


def test_the_news_view_imports_only_streamlit_and_view_models():
    names = imported(SRC / "dashboard" / "news_view.py")
    for name in names:
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith("src.application"), name
        else:
            assert root in {"__future__", "streamlit"}, name


def test_the_news_panel_has_no_action_control():
    """No button, form or submit control lives on the news panel."""
    tree = ast.parse((SRC / "dashboard" / "news_view.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("button", "form", "form_submit_button", "download_button"):
        assert forbidden not in called, f"news_view calls st.{forbidden}"


def test_the_news_panel_cannot_render_research_or_paper_state():
    used = code_identifiers(SRC / "dashboard" / "news_view.py")
    for forbidden in (
        "AssessmentView", "assessment_view", "AssessmentState", "ResearchState",
        "PaperSession", "open_long", "close_position", "portfolio",
    ):
        assert forbidden not in used


# -- no route from a headline to a decision ------------------------------


DECIDING_NAMES = {
    "ResearchObservation", "ResearchAssessment", "AssessmentState", "ResearchState",
    "PaperIntent", "PaperAction", "OpenLongIntent", "CloseIntent", "PaperPortfolio",
}


@pytest.mark.parametrize("path", NEWS_FILES + APPLICATION_NEWS, ids=lambda p: p.name)
def test_no_deciding_identifier_is_in_scope_for_news_code(path):
    """The firewall in its strongest form: not "it does not currently do it",
    but "there is no name available to do it with"."""
    assert not (code_identifiers(path) & DECIDING_NAMES)


def test_no_news_module_constructs_a_paper_intent():
    for path in NEWS_FILES + APPLICATION_NEWS + DASHBOARD_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
                if name in {"OpenLongIntent", "CloseIntent"}:
                    assert path.name in {"paper.py", "app.py"}, (
                        f"{path.name} constructs {name}"
                    )


def test_the_app_never_passes_news_into_a_paper_action():
    """Control-flow check: no paper mutation may be gated on news."""
    tree = ast.parse((SRC / "dashboard" / "app.py").read_text(encoding="utf-8"))
    links = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            links[child] = node

    news_names = {"news_snapshot", "news_service", "NewsSnapshot", "news_view"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if called not in {"open_long", "close_position", "apply_open_long", "apply_close"}:
            continue
        current = node
        while current is not None:
            parent = links.get(current)
            if isinstance(parent, (ast.If, ast.While)) and current is not parent.test:
                mentioned = {
                    n.id for n in ast.walk(parent.test) if isinstance(n, ast.Name)
                } | {
                    n.attr for n in ast.walk(parent.test) if isinstance(n, ast.Attribute)
                }
                assert not (mentioned & news_names), (
                    f"{called}() is conditional on news state {mentioned & news_names}"
                )
            current = parent


# -- scope ---------------------------------------------------------------


def test_no_news_module_reaches_the_market_data_store():
    """Phase 8 stores its own records; it does not touch Phase 1 storage.

    Checked against imports and used identifiers rather than raw text: a
    docstring may legitimately point at ``src.data.storage`` as the precedent
    the layout follows without importing anything from it.
    """
    for path in NEWS_FILES + APPLICATION_NEWS:
        assert not imports_package(imported(path), "src.data")
        assert "CsvBarStore" not in code_identifiers(path)


def test_requirements_were_not_changed_for_phase_eight():
    """Phase 8 adds no dependency: stdlib only."""
    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "main", "--", "requirements.txt"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    assert changed == "", "requirements.txt must not change in Phase 8"
