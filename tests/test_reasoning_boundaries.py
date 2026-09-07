"""Phase 11A Stage A architecture, enforced by import analysis rather than review.

    src.reasoning  ->  (nothing in src)

The reasoning domain is a leaf, like ``src.news`` and ``src.feeds``. A snapshot
arrives duck-typed and leaves as a bounded packet; no domain package is imported
to make that happen. That is what lets the Phase 7, 8 and 9 firewalls sweep
these files without a single amendment, and it is asserted here rather than
hoped for.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
REASONING = SRC / "reasoning"
REASONING_FILES = sorted(REASONING.rglob("*.py"))


def imported(path: pathlib.Path) -> set[str]:
    """Every module this file imports, at any depth, by AST rather than text."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative, stays inside this package
                continue
            if node.module:
                names.add(node.module)
    return names


def imports_package(names: set[str], package: str) -> bool:
    return any(name == package or name.startswith(package + ".") for name in names)


def called(path: pathlib.Path) -> set[str]:
    """Every bare function name called, and every attribute called on something."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def test_the_reasoning_package_exists():
    assert REASONING_FILES
    assert (REASONING / "models.py") in REASONING_FILES
    assert (REASONING / "evidence.py") in REASONING_FILES


# -- the reasoning domain is a leaf --------------------------------------


FORBIDDEN_SRC_PACKAGES = (
    "src.application",
    "src.dashboard",
    "src.news",
    "src.feeds",
    "src.scanner",
    "src.portfolio",
    "src.evaluation",
    "src.data",
    "src.features",
    "src.strategies",
    "src.assessments",
    "src.backtesting",
    "src.signals",
)


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", FORBIDDEN_SRC_PACKAGES)
def test_reasoning_imports_no_other_src_package(path, package):
    """A duck-typed snapshot needs no import. Keeping it that way is what keeps
    every existing firewall satisfied without amending one of them."""
    assert not imports_package(imported(path), package), (
        f"{path.relative_to(REPO)} imports {package}"
    )


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_reasoning_mentions_no_forbidden_package_even_in_prose(path):
    """The Phase 7 and Phase 8 firewalls check *text*, not only imports.

    Both sweep every domain file, and this package is a domain file. Matching
    them here means a docstring that merely names one of those packages fails in
    this file, where the reason is obvious, rather than in a Phase 7 test whose
    subject looks unrelated.
    """
    text = path.read_text(encoding="utf-8")
    for package in ("src.application", "src.dashboard", "src.news", "src.feeds"):
        assert package not in text, f"{path.name} mentions {package}"


# -- no model vendor, no UI ----------------------------------------------


VENDOR_SDKS = (
    "anthropic", "openai", "google", "google.generativeai", "vertexai",
    "langchain", "transformers", "cohere", "mistralai", "ollama", "litellm",
    "tiktoken", "sentence_transformers",
)


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("vendor", VENDOR_SDKS)
def test_the_reasoning_domain_imports_no_model_vendor(path, vendor):
    """Stage A has no provider at all; when one arrives it lives in an adapter,
    never here."""
    assert not imports_package(imported(path), vendor), (
        f"{path.relative_to(REPO)} imports {vendor}"
    )


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_the_reasoning_domain_imports_no_ui(path):
    assert not imports_package(imported(path), "streamlit")


# -- no network, no filesystem, no background work -----------------------


NETWORK_MODULES = (
    "requests", "httpx", "httpx2", "urllib", "urllib3", "http", "socket",
    "ssl", "aiohttp", "websockets", "ftplib", "smtplib", "telnetlib",
)


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("module", NETWORK_MODULES)
def test_the_reasoning_domain_reaches_no_network(path, module):
    assert not imports_package(imported(path), module), (
        f"{path.relative_to(REPO)} imports {module}"
    )


BACKGROUND_MODULES = (
    "threading", "asyncio", "multiprocessing", "concurrent", "sched",
    "schedule", "apscheduler", "subprocess", "signal",
    # importlib is banned outright rather than for its own sake: without it a
    # dynamic ``import_module("requests")`` would slip past every module-name
    # ban above, since the module being imported is a string the AST scan
    # cannot follow. A pure domain package has no legitimate use for it.
    "importlib",
)


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("module", BACKGROUND_MODULES)
def test_nothing_runs_in_the_background(path, module):
    assert not imports_package(imported(path), module), (
        f"{path.relative_to(REPO)} imports {module}"
    )


STORAGE_MODULES = ("sqlite3", "sqlalchemy", "shelve", "pickle", "dbm", "csv",
                   "os", "shutil", "tempfile", "pathlib")


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("module", STORAGE_MODULES)
def test_the_reasoning_domain_persists_nothing(path, module):
    """Stage A is session-only by construction: it cannot reach a file."""
    assert not imports_package(imported(path), module), (
        f"{path.relative_to(REPO)} imports {module}"
    )


FILE_PRIMITIVES = {
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "unlink", "mkdir", "rmdir", "touch", "to_csv", "read_csv",
}


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_the_reasoning_domain_calls_no_file_primitive(path):
    """The *call*, not the word: a docstring may say "open" without opening."""
    offenders = called(path) & FILE_PRIMITIVES
    assert not offenders, f"{path.name} calls {offenders}"


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_the_reasoning_domain_evaluates_nothing_dynamically(path):
    offenders = called(path) & {"eval", "exec", "compile", "__import__"}
    assert not offenders, f"{path.name} calls {offenders}"


# -- no clock of its own -------------------------------------------------


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_the_reasoning_domain_reads_no_clock(path):
    """``now`` is injected. A hidden clock would make packets irreproducible and
    every fingerprint comparison meaningless."""
    offenders = called(path) & {"now", "utcnow", "today", "time", "monotonic"}
    assert not offenders, f"{path.name} reads a clock: {offenders}"


# -- no credentials, no environment --------------------------------------


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_the_reasoning_domain_reads_no_credential_or_environment(path):
    text = path.read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "apikey", "getenv", "environ", "secret",
                      "bearer", "authorization", "token="):
        assert forbidden not in text, f"{path.name} mentions {forbidden}"


# -- no scoring vocabulary -----------------------------------------------


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
def test_no_scoring_or_recommendation_identifier_exists(path):
    """Scoped to identifiers: a docstring may deny a score, and does."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name.lower())
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id.lower())
        elif isinstance(node, ast.arg):
            defined.add(node.arg.lower())
    for forbidden in ("score", "confidence", "probability", "recommendation",
                      "rating", "conviction", "target_price", "buy", "sell"):
        offenders = {name for name in defined if forbidden in name}
        assert not offenders, f"{path.name} defines {offenders}"


# -- the package surface -------------------------------------------------


def test_the_package_exports_no_wildcard():
    text = (REASONING / "__init__.py").read_text(encoding="utf-8")
    assert "import *" not in text


def test_every_public_export_resolves():
    import src.reasoning as package

    for name in package.__all__:
        assert hasattr(package, name), f"__all__ names missing {name}"
