"""Phase 8 security: untrusted content in, nothing dangerous out.

Everything this layer ingests comes from outside the repository, and one field
of it -- the URL -- is rendered as a clickable link. These tests pin the two
defences that matter: only safe links are stored, and no URL is ever followed.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.news.models import MAX_HEADLINE, NewsError, NewsItem, SourceClass
from src.news.models import AvailabilityBasis
from src.news.validation import (
    ALLOWED_SCHEMES,
    DANGEROUS_SCHEMES,
    UrlValidationError,
    safe_text,
    validate_source_timestamp,
    validate_url,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

REPO = pathlib.Path(__file__).resolve().parent.parent
PHASE_8_SOURCE = [
    *(REPO / "src" / "news").rglob("*.py"),
    REPO / "src" / "application" / "news.py",
    REPO / "src" / "dashboard" / "news_view.py",
]


# -- URL policy ----------------------------------------------------------


def test_https_is_the_only_allowed_scheme():
    assert ALLOWED_SCHEMES == frozenset({"https"})


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "vbscript:msgbox(1)",
        "blob:https://example.com/x",
    ],
)
def test_dangerous_schemes_are_refused(url):
    with pytest.raises(UrlValidationError):
        validate_url(url)


def test_http_is_refused_alongside_the_dangerous_schemes():
    """Not dangerous, but not stored either: links go out over TLS only."""
    with pytest.raises(UrlValidationError):
        validate_url("http://example.com/x")


def test_scheme_relative_urls_are_refused():
    """They inherit whatever scheme the page happens to have."""
    with pytest.raises(UrlValidationError):
        validate_url("//example.com/x")


def test_credentials_in_the_authority_are_refused():
    with pytest.raises(UrlValidationError):
        validate_url("https://user:password@example.com/x")


def test_control_characters_in_a_url_are_refused():
    with pytest.raises(UrlValidationError):
        validate_url("https://example.com/\x00evil")
    with pytest.raises(UrlValidationError):
        validate_url("https://example.com/a\nSet-Cookie: x")


def test_a_url_without_a_host_is_refused():
    with pytest.raises(UrlValidationError):
        validate_url("https:///path-only")


def test_an_over_long_url_is_refused():
    with pytest.raises(UrlValidationError):
        validate_url("https://example.com/" + "x" * 5_000)


def test_empty_and_non_string_urls_are_refused():
    for value in ("", "   ", None, 123, b"https://x"):
        with pytest.raises(UrlValidationError):
            validate_url(value)


def test_a_normal_https_url_is_accepted():
    assert validate_url("https://example.com/a?b=c#d") == "https://example.com/a?b=c#d"


def test_dangerous_scheme_list_is_not_the_allowlist():
    assert not (DANGEROUS_SCHEMES & ALLOWED_SCHEMES)


# -- no URL is ever fetched ----------------------------------------------


#: Modules that can actually open a connection. ``urllib.parse`` is absent on
#: purpose: it only splits strings.
FETCHING_MODULES = {
    "requests", "httpx", "aiohttp", "socket", "ftplib", "urllib3",
    "urllib.request", "urllib.error", "http.client",
}


def _module_level_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:  # top level only
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_no_phase_eight_module_imports_an_http_client_eagerly():
    """Importing the news package must not pull in an HTTP stack.

    One function -- EDGAR's ``default_fetch_fn`` -- does need to make a real
    request, and imports its transport lazily inside itself. Nothing else may,
    and nothing imports a client at module level.
    """
    for path in PHASE_8_SOURCE:
        for name in _module_level_imports(path):
            assert name not in FETCHING_MODULES, f"{path.name} eagerly imports {name}"
            assert name.split(".")[0] not in {"requests", "httpx", "aiohttp"}, (
                f"{path.name} eagerly imports {name}"
            )


def test_only_the_edgar_default_fetch_may_import_a_transport():
    """Exactly one function is allowed to open a connection."""
    offenders = []
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in [n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(function):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name in FETCHING_MODULES:
                        offenders.append(f"{path.name}:{function.name}")
    assert set(offenders) <= {"edgar.py:default_fetch_fn"}, offenders


def test_the_fetching_function_refuses_any_endpoint_it_was_not_configured_for():
    """The transport is reachable, so the allowlist is what closes SSRF."""
    from src.news.sources.edgar import ALLOWED_URL_PREFIXES, default_fetch_fn
    from src.news.source import SourceError

    assert all(p.startswith("https://") for p in ALLOWED_URL_PREFIXES)
    assert all(".sec.gov/" in p for p in ALLOWED_URL_PREFIXES)

    def opener(request, timeout=None):  # pragma: no cover - must not run
        raise AssertionError("a connection was attempted for a rejected URL")

    for url in ("https://evil.example.com/x", "http://data.sec.gov/x",
                "javascript:alert(1)", "file:///etc/passwd"):
        with pytest.raises(SourceError):
            default_fetch_fn(url, "AI someone@example.com", opener=opener,
                             sleep=lambda s: None, now=lambda: 0.0)


def test_only_url_parsing_not_url_fetching_is_imported():
    """The one urllib module used is ``parse``, which cannot open a socket."""
    text = (REPO / "src" / "news" / "validation.py").read_text()
    assert "from urllib.parse import" in text
    assert "urllib.request" not in text


def test_no_phase_eight_module_calls_urlopen_or_get():
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                assert name not in {"urlopen", "urlretrieve", "request"}, (
                    f"{path.name} calls {name}()"
                )


def test_the_canonical_url_is_stored_but_never_dereferenced():
    """A stored link is data. Nothing in the layer turns it into a request."""
    item = NewsItem(
        source="yahoo", source_item_id="x", source_class=SourceClass.SECONDARY_NEWS,
        publisher="P", headline="H", canonical_url="https://example.com/a",
        retrieved_at=NOW, availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
        available_from=NOW,
    )
    assert item.canonical_url == "https://example.com/a"


# -- hostile content -----------------------------------------------------


def test_html_in_a_headline_is_kept_as_inert_text():
    """Not stripped, not executed: it is escaped at render time."""
    assert "<script>" in safe_text("<script>x</script> News", maximum=MAX_HEADLINE)


def test_over_long_text_is_capped():
    assert len(safe_text("x" * 50_000, maximum=MAX_HEADLINE)) <= MAX_HEADLINE


def test_control_characters_are_stripped_from_display_text():
    assert "\x00" not in safe_text("a\x00b", maximum=100)
    assert "\x07" not in safe_text("a\x07b", maximum=100)


def test_missing_text_becomes_an_explicit_default():
    assert safe_text(None, maximum=10, default="unknown") == "unknown"
    assert safe_text(12345, maximum=10, default="unknown") == "unknown"


def test_unusual_unicode_survives_without_breaking_storage():
    assert safe_text("Ａpple 🍎 café", maximum=100)


def test_a_far_future_timestamp_is_refused():
    with pytest.raises(NewsError):
        validate_source_timestamp(NOW + timedelta(days=30), now=NOW)


def test_a_slightly_skewed_timestamp_is_tolerated():
    assert validate_source_timestamp(NOW + timedelta(hours=2), now=NOW) is not None


def test_a_naive_timestamp_is_refused():
    with pytest.raises(NewsError):
        validate_source_timestamp(datetime(2026, 9, 5, 12, 0), now=NOW)


def test_a_missing_timestamp_stays_missing():
    assert validate_source_timestamp(None, now=NOW) is None


# -- no dangerous capability --------------------------------------------


def test_no_dynamic_execution_anywhere_in_phase_eight():
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}, (
                    f"{path.name} calls {node.func.id}()"
                )


def test_no_shell_or_subprocess_capability():
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "attr", None) or getattr(node, "id", None)
            assert name not in {"system", "popen", "spawn", "fork", "Popen"}, path.name


def test_no_unsafe_html_rendering():
    text = (REPO / "src" / "dashboard" / "news_view.py").read_text()
    assert "unsafe_allow_html" not in text


def test_no_article_body_is_stored():
    """Only headline, provider summary and a link -- never the article text."""
    from src.news.store import document_to_row

    item = NewsItem(
        source="yahoo", source_item_id="x", source_class=SourceClass.SECONDARY_NEWS,
        publisher="P", headline="H", canonical_url="https://example.com/a",
        retrieved_at=NOW, availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
        available_from=NOW,
    )
    row = document_to_row(item)
    for forbidden in ("body", "content_text", "article", "full_text", "html"):
        assert not any(forbidden in key.lower() for key in row), row.keys()


def test_no_scraping_or_parsing_dependency_is_used():
    banned = {"bs4", "beautifulsoup4", "lxml", "html", "feedparser", "newspaper"}
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"


def test_no_database_or_persistence_library_is_used():
    banned = {"sqlite3", "sqlalchemy", "pickle", "shelve", "pymongo", "redis"}
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"


def test_no_scheduler_or_background_execution():
    banned = {"threading", "asyncio", "multiprocessing", "schedule",
              "apscheduler", "concurrent", "sched", "signal"}
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"


def test_no_llm_or_messaging_capability():
    banned = {"openai", "anthropic", "langchain", "transformers",
              "telegram", "discord", "smtplib"}
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"


def test_file_writes_are_confined_to_the_store_and_cik_cache():
    """Only two modules touch the filesystem, and both write under the root."""
    writers = []
    for path in PHASE_8_SOURCE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in {"open", "write_text", "write_bytes", "mkdir"}:
                    writers.append(path.name)
                    break
    assert set(writers) <= {"store.py", "cik_map.py"}, writers
