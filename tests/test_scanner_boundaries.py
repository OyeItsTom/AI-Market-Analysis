"""Phase 10 architecture, enforced by import analysis rather than by review.

    dashboard -> application -> scanner domain -> {data, assessments}
                                      ^
                              scanner adapter (config.py)

Three firewalls are structural: a scan result has no name in scope through which
it could reach a paper action, an LLM, or the news and feed layers. The fourth
guarantee is about the filesystem -- exactly one module may read, and none may
write.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
SCANNER = SRC / "scanner"

PURE_MODULES = [SCANNER / name for name in
                ("models.py", "universe.py", "eligibility.py", "ranking.py")]
ADAPTER = SCANNER / "config.py"
ALL_SCANNER = sorted(SCANNER.rglob("*.py"))

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
    """Identifiers actually used, ignoring prose.

    A module whose docstring explains "no result can reach a paper action" must
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


def test_the_scanner_package_exists():
    assert ALL_SCANNER and ADAPTER.is_file()
    assert len(PURE_MODULES) == 4


# -- the scanner reaches nothing that decides or renders -----------------


#: No exceptions. The scanner is a leaf: it imports no application module at
#: all, so the existing "domain never imports the application layer" boundary
#: holds for every file here.
FORBIDDEN_PACKAGES = (
    "src.application", "src.dashboard", "src.news", "src.feeds",
    "src.portfolio", "src.evaluation", "src.data.storage",
)
FORBIDDEN_PAIRS = [
    (path, package) for path in ALL_SCANNER for package in FORBIDDEN_PACKAGES
]


@pytest.mark.parametrize(
    "path, package", FORBIDDEN_PAIRS, ids=lambda v: v.name if hasattr(v, "name") else v
)
def test_the_scanner_never_imports_a_forbidden_package(path, package):
    assert not imports_package(imported(path), package), (
        f"{path.relative_to(REPO)} imports {package}"
    )


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_the_scanner_never_imports_a_ui(path):
    names = imported(path)
    assert not imports_package(names, "streamlit")
    assert not imports_package(names, "src.dashboard")


def test_eligibility_maps_failure_kinds_without_importing_them():
    """The mapping is keyed on kind *values*, so the domain stays a leaf.

    Importing the application error enum would invert the dependency direction
    the repository has maintained since Phase 1.
    """
    from src.application.errors import FailureKind
    from src.scanner.eligibility import ERROR_FOR_KIND

    assert not [n for n in imported(SCANNER / "eligibility.py")
                if n.startswith("src.application")]
    # Every real kind is covered, so the decoupling costs no completeness.
    assert set(ERROR_FOR_KIND) == {kind.value for kind in FailureKind}


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_the_scanner_imports_only_the_standard_library_and_permitted_domains(path):
    """Zero new dependencies: everything here is stdlib or an existing domain."""
    for name in imported(path):
        root = name.split(".")[0]
        if root == "src":
            assert name.startswith(("src.scanner", "src.data", "src.assessments")), (
                f"{path.name} imports {name}"
            )
            continue
        assert root in {
            "__future__", "dataclasses", "datetime", "enum", "hashlib",
            "itertools", "json", "pathlib", "typing",
        }, f"{path.name} imports unexpected module {name}"


# -- no earlier phase learns about the scanner ---------------------------


def test_only_the_orchestrator_imports_the_scanner_domain():
    """The scanner is reached through the application layer, like everything else.

    Stage E adds exactly one consumer. A second one appearing -- especially in
    the dashboard -- would mean the layering had been bypassed.
    """
    consumers = [
        path for path in sorted(SRC.rglob("*.py"))
        if "scanner" not in path.parts and imports_package(imported(path), "src.scanner")
    ]
    assert [p.relative_to(SRC).as_posix() for p in consumers] == ["application/scanner.py"]


def test_the_dashboard_does_not_import_the_scanner_domain():
    for path in sorted((SRC / "dashboard").rglob("*.py")):
        assert not imports_package(imported(path), "src.scanner"), path.name


# -- file I/O is confined to the adapter ---------------------------------


@pytest.mark.parametrize("path", PURE_MODULES, ids=lambda p: p.name)
def test_the_pure_modules_touch_no_file(path):
    assert not (called_names(path) & FILE_PRIMITIVES)
    assert not (attribute_calls(path) & FILE_PRIMITIVES)
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in IO_MODULES:
                assert node.func.attr not in {"load", "dump"}, path.name


def test_the_adapter_owns_the_read():
    """Positively: the read lives here, is read-only, and is bounded.

    The bound is on the read itself, not only on a prior ``stat``: a file can
    grow between being measured and being read, so a stat-only check would only
    prove it was small a moment ago.
    """
    source = ADAPTER.read_text(encoding="utf-8")
    assert 'path.open("rb")' in source, "the read must go through an explicit handle"
    assert "handle.read(limit + 1)" in source, "the read must be bounded"
    assert "json.loads" in source
    assert "json.load(" not in source, "must not decode from a file handle"
    assert "stat().st_size" in source, "the cheap pre-check should remain"


def test_the_adapter_opens_nothing_for_writing():
    """The one permitted open is read-only."""
    import re

    source = ADAPTER.read_text(encoding="utf-8")
    modes = re.findall(r"\.open\(\s*([\"'])([^\"']*)\1", source)
    assert modes, "expected an explicit open mode"
    for _, mode in modes:
        assert set(mode) <= {"r", "b"}, f"config.py opens with mode {mode!r}"


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_nothing_in_the_scanner_writes_a_file(path):
    """Phase 10 Stages A-D write nothing at all.

    Checked on write *primitives* and on open *modes*, not on the presence of
    the word ``open``: the adapter legitimately opens a file read-only, and a
    rule that could not tell the two apart would force worse code.
    """
    import re

    source = path.read_text(encoding="utf-8")
    calls = called_names(path) | attribute_calls(path)
    # Unambiguous write primitives, matched by name: nothing here is plausibly
    # named any of these for another purpose.
    for forbidden in ("write_text", "write_bytes", "unlink", "mkdir", "rmdir",
                      "touch", "rmtree"):
        assert forbidden not in calls, f"{path.name} calls {forbidden}"
    # `replace`, `remove` and `rename` are matched only when qualified by an
    # I/O module. Bare names would collide with `str.replace`,
    # `datetime.replace` and `list.remove` -- forcing real code to be written
    # worse to satisfy a test that cannot tell them apart.
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in IO_MODULES:
                assert node.func.attr not in {"replace", "remove", "rename",
                                              "unlink", "mkdir", "rmtree"}, (
                    f"{path.name} calls {receiver.id}.{node.func.attr}"
                )
    for _, mode in re.findall(r"open\(\s*([\"'])([^\"']*)\1", source):
        assert set(mode) <= {"r", "b"}, f"{path.name} opens with mode {mode!r}"
    for _, mode in re.findall(r"open\([^,)]*,\s*([\"'])([^\"']*)\1", source):
        assert set(mode) <= {"r", "b"}, f"{path.name} opens with mode {mode!r}"


@pytest.mark.parametrize("path", PURE_MODULES, ids=lambda p: p.name)
def test_no_pure_module_opens_anything(path):
    """Only the adapter may open a file, in any mode."""
    assert "open(" not in path.read_text(encoding="utf-8")


# -- firewalls -----------------------------------------------------------


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_no_paper_or_research_mutation_is_reachable(path):
    used = code_identifiers(path)
    for forbidden in ("PaperIntent", "OpenLongIntent", "CloseIntent", "PaperAction",
                      "PaperPortfolio", "RiskDecision", "RiskPolicy",
                      "ResearchAssessment", "ResearchObservation"):
        assert forbidden not in used, f"{path.name} uses {forbidden}"


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_no_llm_sentiment_or_telegram(path):
    used = {name.lower() for name in code_identifiers(path)}
    names = imported(path)
    for forbidden in ("openai", "anthropic", "llm", "sentiment", "embedding",
                      "telegram", "telethon", "pyrogram", "summarize", "summarise"):
        assert forbidden not in used, f"{path.name} uses {forbidden}"
        assert not imports_package(names, forbidden)


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_nothing_runs_in_the_background(path):
    names = imported(path)
    for module in ("threading", "asyncio", "multiprocessing", "sched",
                   "concurrent", "apscheduler", "celery", "schedule"):
        assert not imports_package(names, module), f"{path.name} imports {module}"
    used = code_identifiers(path)
    for forbidden in ("Thread", "Timer", "BackgroundScheduler", "create_task"):
        assert forbidden not in used


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_nothing_evaluates_or_shells_out(path):
    names = imported(path)
    for module in ("subprocess", "pickle", "shelve", "marshal", "ctypes", "socket"):
        assert not imports_package(names, module), f"{path.name} imports {module}"
    called = called_names(path)
    for forbidden in ("eval", "exec", "compile", "__import__", "system", "popen"):
        assert forbidden not in called, f"{path.name} calls {forbidden}"


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_no_credential_or_environment_access(path):
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in ("api_key", "secret", "password", "token", "credential",
                      "getenv", "environ"):
        assert forbidden not in used, f"{path.name} refers to {forbidden}"


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_no_network_capability(path):
    names = imported(path)
    for module in ("http", "urllib", "requests", "httpx", "ssl", "socket"):
        assert not imports_package(names, module), f"{path.name} imports {module}"


# -- no scoring vocabulary in the domain ---------------------------------


@pytest.mark.parametrize("path", ALL_SCANNER, ids=lambda p: p.name)
def test_no_scoring_identifier_exists(path):
    """Scoped to identifiers, not prose: a docstring may explain the refusal."""
    used = {name.lower() for name in code_identifiers(path)}
    for forbidden in ("score", "confidence", "probability", "rating",
                      "conviction", "expected_return", "price_target"):
        assert forbidden not in used, f"{path.name} defines {forbidden}"


def test_stage_g_modules_do_not_exist_yet():
    """Scope guard: docs and the runtime config belong to a later stage."""
    for path in ("docs/scanner.md", "docs/adr/0008-market-scanner.md",
                 "config/universes.local.json"):
        assert not (REPO / path).exists(), f"{path} belongs to a later stage"
