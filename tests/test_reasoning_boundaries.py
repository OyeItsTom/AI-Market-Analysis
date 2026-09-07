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


def called_bare(path: pathlib.Path) -> set[str]:
    """Only builtins called by bare name.

    ``re.compile`` is not dynamic code execution, and ``some.open`` on a byte
    stream is not a filesystem call. Merging bare names with attribute names
    conflates the builtin with any method that happens to share its spelling.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


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
    # builtins would reach the dangerous callables by attribute, which
    # called_bare deliberately does not follow. Banning the module closes that
    # route without re-flagging re.compile.
    "builtins",
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
    """Scoped to the builtins, called by bare name.

    ``re.compile`` compiles a regex, not code; flagging it would force the
    module to reach for a worse pattern API to satisfy a test that had
    misidentified what it was looking at.
    """
    offenders = called_bare(path) & {"eval", "exec", "compile", "__import__"}
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


# -- Stage B modules stay as pure as Stage A ------------------------------


STAGE_B_FILES = [REASONING / "prompts.py", REASONING / "validation.py"]


def test_the_stage_b_modules_exist():
    for path in STAGE_B_FILES:
        assert path in REASONING_FILES, path


@pytest.mark.parametrize("path", STAGE_B_FILES, ids=lambda p: p.name)
def test_stage_b_modules_use_only_permitted_stdlib(path):
    """Prompt and validation are pure: text, hashing and pattern matching.

    ``re`` and ``unicodedata`` are the only additions Stage B needs, both
    stdlib, so no dependency and no ban-list entry changes.
    """
    permitted = {
        "__future__", "hashlib", "typing", "re", "unicodedata", "datetime",
    }
    external = {
        name for name in imported(path)
        if not name.startswith(".") and not name.startswith("src.")
    }
    assert external <= permitted, f"{path.name} imports {external - permitted}"


@pytest.mark.parametrize("path", STAGE_B_FILES, ids=lambda p: p.name)
def test_stage_b_modules_import_only_within_this_package(path):
    """Relative imports inside the package are how the leaf property holds."""
    for name in imported(path):
        assert not name.startswith("src."), f"{path.name} imports {name}"


def _constructs_snapshot(path: pathlib.Path) -> bool:
    """Whether this file builds a ReasoningSnapshot, under any ordinary name.

    Matching only ``ReasoningSnapshot(...)`` by bare name was trivially evaded
    two ways that normal Python code writes every day: importing it under an
    alias, and calling it through its module. Both are checked here. This is
    not complete static analysis and does not pretend to be -- it enforces the
    ownership rule against the forms a developer would actually write.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    local_names = {"ReasoningSnapshot"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name.split(".")[-1] == "ReasoningSnapshot":
                    local_names.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in local_names:
            return True
        if isinstance(func, ast.Attribute) and func.attr == "ReasoningSnapshot":
            return True
    return False


def test_only_validation_constructs_the_trusted_snapshot():
    """The trust boundary is enforced here, not by Python.

    A constructor cannot be made private, so the type split alone is a
    convention. This test is what turns it into a rule: production code may
    build a ReasoningSnapshot in exactly one module, the one that validated it.
    """
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts and _constructs_snapshot(path)
    ]
    assert offenders == ["reasoning/validation.py"], offenders


def test_no_model_authored_claim_type_survives_anywhere():
    for path in REASONING_FILES:
        assert "ClaimType" not in path.read_text(encoding="utf-8"), path.name
