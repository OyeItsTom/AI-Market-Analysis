"""Phase 9 architecture, enforced by import analysis rather than by review.

    dashboard -> application -> feeds domain/adapters/store

Three firewalls are checked here, and each is structural: the guarantee is that
there is *no name in scope* through which the forbidden thing could be reached,
not that no current line of code happens to reach it.

1. No feed entry may reach a research state or a paper action.
2. Nothing in the feed layer may reach a UI framework.
3. Telegram is deferred, so no name from any Telegram client, and no credential
   of any kind, may appear anywhere in the phase.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"

FEED_FILES = sorted((SRC / "feeds").rglob("*.py"))
APPLICATION_FEEDS = [SRC / "application" / "feeds.py"]
DASHBOARD_FILES = sorted((SRC / "dashboard").rglob("*.py"))
PHASE_9_FILES = FEED_FILES + APPLICATION_FEEDS + [SRC / "dashboard" / "feeds_view.py"]
DECIDING_PACKAGES = ("src.strategies", "src.assessments", "src.portfolio", "src.evaluation")
PRE_PHASE_9_DOMAIN = [
    path
    for path in sorted(SRC.rglob("*.py"))
    if not {"feeds", "dashboard"} & set(path.parts)
    and path.name not in {"feeds.py", "feeds_view.py"}
    # view_models.py is one of the four files this phase may modify: it formats
    # feed records for display, so reaching the feed layer is its job.
    and path.name != "view_models.py"
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

    A module whose docstring explains "no entry can reach an assessment" must
    not be reported as reaching one.
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
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue
    return names


def called_names(path: pathlib.Path) -> set[str]:
    """Names invoked as bare calls, e.g. ``eval(x)``.

    Deliberately not attribute calls: ``re.compile`` is a precompiled pattern,
    not dynamic execution, and a check that cannot tell the two apart would
    force real code to be written worse to satisfy it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def code_strings(path: pathlib.Path) -> set[str]:
    """String literals that are not docstrings.

    Prose explaining a refusal is not the refusal being violated, so module,
    class and function docstrings are excluded before searching.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }


def test_the_phase_nine_files_exist():
    assert FEED_FILES and APPLICATION_FEEDS and PRE_PHASE_9_DOMAIN
    assert (SRC / "dashboard" / "feeds_view.py").is_file()


# -- feeds reach nothing that decides ------------------------------------


@pytest.mark.parametrize("path", FEED_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", DECIDING_PACKAGES)
def test_the_feed_layer_never_imports_a_deciding_package(path, package):
    assert not imports_package(imported(path), package), (
        f"{path.relative_to(REPO)} imports {package}; a feed entry must have no "
        "route to a research state or a paper action"
    )


@pytest.mark.parametrize("path", FEED_FILES, ids=lambda p: p.name)
def test_the_feed_layer_never_imports_the_news_layer(path):
    """Phase 8 and Phase 9 are independent; neither may quietly depend on the other."""
    assert not imports_package(imported(path), "src.news")


@pytest.mark.parametrize("path", FEED_FILES, ids=lambda p: p.name)
def test_the_feed_layer_never_imports_a_ui(path):
    names = imported(path)
    assert not imports_package(names, "streamlit")
    assert not imports_package(names, "src.dashboard")


@pytest.mark.parametrize("path", FEED_FILES, ids=lambda p: p.name)
def test_the_feed_layer_never_imports_the_application_layer(path):
    assert not imports_package(imported(path), "src.application")


@pytest.mark.parametrize("path", FEED_FILES, ids=lambda p: p.name)
def test_the_feed_layer_imports_only_the_standard_library_and_itself(path):
    """Zero new dependencies: everything here is stdlib."""
    for name in imported(path):
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith("src.feeds"), f"{path.name} imports {name}"
            continue
        assert root in {
            "__future__", "dataclasses", "datetime", "email", "enum", "gzip",
            "hashlib", "http", "ipaddress", "json", "os", "pathlib", "re",
            "socket", "ssl", "time", "typing", "urllib", "xml", "zlib",
            # An optional CA bundle, imported lazily inside the TLS context
            # builder and already a dependency of the project.
            "certifi",
        }, f"{path.name} imports unexpected module {name}"


# -- the deciding packages never learn about feeds -----------------------


@pytest.mark.parametrize("path", PRE_PHASE_9_DOMAIN, ids=lambda p: str(p.relative_to(SRC)))
def test_no_earlier_module_imports_the_feed_layer(path):
    names = imported(path)
    assert not imports_package(names, "src.feeds")
    assert not imports_package(names, "src.application.feeds")


def test_the_feed_snapshot_is_not_part_of_the_research_snapshot():
    """Merging them would imply that research consumes feeds. It does not."""
    text = (SRC / "application" / "snapshot.py").read_text(encoding="utf-8")
    assert "feed" not in text.lower()


def test_the_research_snapshot_module_was_not_modified_for_feeds():
    used = code_identifiers(SRC / "application" / "snapshot.py")
    for forbidden in ("FeedSnapshot", "FeedItem", "FeedService", "SymbolLink"):
        assert forbidden not in used


# -- application layer ---------------------------------------------------


@pytest.mark.parametrize("path", APPLICATION_FEEDS, ids=lambda p: p.name)
def test_the_application_feeds_module_imports_no_ui(path):
    assert not imports_package(imported(path), "streamlit")


def test_the_application_feeds_module_touches_no_research_or_paper_package():
    names = imported(SRC / "application" / "feeds.py")
    for package in DECIDING_PACKAGES:
        assert not imports_package(names, package)


def test_the_application_feeds_module_does_not_reach_the_news_layer():
    assert not imports_package(imported(SRC / "application" / "feeds.py"), "src.news")


# -- dashboard -----------------------------------------------------------


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_the_dashboard_never_imports_the_feed_domain(path):
    """It must reach feeds through the application layer, like everything else."""
    assert not imports_package(imported(path), "src.feeds")


def test_the_feeds_view_imports_only_streamlit_and_view_models():
    for name in imported(SRC / "dashboard" / "feeds_view.py"):
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith("src.application"), name
        else:
            assert root in {"__future__", "streamlit"}, name


# -- Telegram is deferred, structurally ----------------------------------


TELEGRAM_LIBRARIES = ("telethon", "pyrogram", "telebot", "telegram", "aiogram")


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_no_telegram_client_is_imported_anywhere_in_the_phase(path):
    names = imported(path)
    for library in TELEGRAM_LIBRARIES:
        assert not imports_package(names, library), f"{path.name} imports {library}"


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_no_telegram_identifier_appears_in_code(path):
    """Prose may explain the deferral; no identifier may implement it."""
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in ("telegram", "telethon", "pyrogram", "api_hash", "api_id", "bot_token"):
        assert forbidden not in used, f"{path.name} uses {forbidden}"


def test_no_telegram_dependency_was_added():
    text = (REPO / "requirements.txt").read_text(encoding="utf-8").lower()
    for library in TELEGRAM_LIBRARIES + ("telethon",):
        assert library not in text


# -- no credentials anywhere ---------------------------------------------


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_no_credential_is_read_or_carried(path):
    """V1 fetches only public feeds, so there is nothing to authenticate with."""
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in (
        "api_key", "apikey", "secret", "password", "passwd", "token",
        "credential", "session_string", "phone_number",
    ):
        assert forbidden not in used, f"{path.name} refers to {forbidden}"


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_no_environment_variable_is_read(path):
    """Nothing in this phase is configured by a secret in the environment."""
    used = code_identifiers(path)
    assert "getenv" not in used
    assert "environ" not in used


# -- no interpretation, no execution, no background work -----------------


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_nothing_scores_interprets_or_summarises(path):
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in (
        "sentiment", "classify", "summarize", "summarise", "relevance_score",
        "openai", "anthropic", "llm", "embedding", "vectorize",
    ):
        assert forbidden not in used, f"{path.name} uses {forbidden}"


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_nothing_runs_in_the_background(path):
    """A refresh happens because a human pressed a button."""
    names = imported(path)
    for module in ("threading", "asyncio", "multiprocessing", "sched", "concurrent",
                   "apscheduler", "celery"):
        assert not imports_package(names, module), f"{path.name} imports {module}"
    used = code_identifiers(path)
    for forbidden in ("Thread", "Timer", "BackgroundScheduler", "create_task"):
        assert forbidden not in used, f"{path.name} uses {forbidden}"


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_nothing_evaluates_or_shells_out(path):
    names = imported(path)
    for module in ("subprocess", "pickle", "shelve", "marshal", "ctypes"):
        assert not imports_package(names, module), f"{path.name} imports {module}"
    called = called_names(path)
    for forbidden in ("eval", "exec", "compile", "__import__", "system", "popen",
                      "spawn", "execv"):
        assert forbidden not in called, f"{path.name} calls {forbidden}"


@pytest.mark.parametrize("path", PHASE_9_FILES, ids=lambda p: p.name)
def test_no_media_or_article_body_is_downloaded(path):
    """Only the configured feed document is fetched. Nothing it links to is."""
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in ("download", "urlretrieve", "scrape", "fetch_article", "fetch_media"):
        assert forbidden not in used, f"{path.name} uses {forbidden}"


# -- the UI states its limits --------------------------------------------


def test_the_feeds_view_never_renders_raw_html():
    """Publisher text is escaped by Streamlit; markup shows as literal characters."""
    used = code_identifiers(SRC / "dashboard" / "feeds_view.py")
    assert "unsafe_allow_html" not in used
    assert "html" not in {name.lower() for name in used}


def test_the_dashboard_never_enables_raw_html_anywhere():
    for path in DASHBOARD_FILES:
        assert "unsafe_allow_html" not in code_identifiers(path), path.name


def test_the_feeds_panel_has_no_action_control():
    """Reading information and acting on it stay separate decisions."""
    used = code_identifiers(SRC / "dashboard" / "feeds_view.py")
    for forbidden in ("open_long", "close_position", "PaperIntent", "RiskDecision"):
        assert forbidden not in used


def test_the_trust_disclaimer_says_the_label_is_the_users_own():
    from src.application.view_models import FEEDS_TRUST_DISCLAIMER

    text = FEEDS_TRUST_DISCLAIMER.lower()
    assert "not verif" in text or "does not verify" in text


def test_the_feeds_disclaimer_denies_analysis_and_denies_reaching_research():
    from src.application.view_models import FEEDS_DISCLAIMER

    text = FEEDS_DISCLAIMER.lower()
    assert "analysed" in text or "analyzed" in text
    assert "research" in text


# -- only configured URLs are ever fetched -------------------------------


def test_the_only_fetch_entry_point_is_the_transport_module():
    """One door: every request goes through the validated transport."""
    for path in FEED_FILES:
        if path.name == "transport.py":
            continue
        names = imported(path)
        assert not imports_package(names, "requests")
        assert not imports_package(names, "httpx")
        assert not imports_package(names, "urllib.request")
        assert not imports_package(names, "http.client")


def test_no_url_is_taken_from_feed_content():
    """A link inside an entry is displayed, never requested.

    Enforced on the adapter: it has no name in scope through which a request
    could be made, so a link it parses cannot become a fetch.
    """
    used = code_identifiers(SRC / "feeds" / "sources" / "rss.py")
    for forbidden in ("fetch_feed", "urlopen", "urlretrieve", "HTTPSConnection",
                      "HTTPConnection", "Session", "resolve_safely"):
        assert forbidden not in used, f"the adapter uses {forbidden}"
    # And it imports nothing that could make a request in the first place.
    names = imported(SRC / "feeds" / "sources" / "rss.py")
    for module in ("http", "urllib", "socket", "ssl", "requests", "httpx"):
        assert not imports_package(names, module)


def test_the_transport_never_relaxes_certificate_verification():
    used = code_identifiers(SRC / "feeds" / "transport.py")
    strings = code_strings(SRC / "feeds" / "transport.py")
    assert "CERT_NONE" not in used
    assert "_create_unverified_context" not in used
    assert not any("CERT_NONE" in text for text in strings)
    text = (SRC / "feeds" / "transport.py").read_text(encoding="utf-8")
    assert "check_hostname = False" not in text
    assert "verify=False" not in text


def test_no_live_feed_data_is_committed():
    assert not (REPO / "data" / "feeds").exists()
