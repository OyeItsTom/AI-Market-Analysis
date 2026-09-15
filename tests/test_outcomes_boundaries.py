"""Phase 12A/12B architecture, enforced by import and call analysis.

``src.outcomes`` is a pure domain package: models, identity and -- since
12B -- the tracking integration that asks Phase 4 to measure. It reaches
only the Phase 1/3/4/6 record types it describes and the Phase 4 public
measurement API, and nothing reaches it yet -- the ledger, the application
service and the dashboard hook are later stages. The dependency direction
(outcomes consume evaluation, never the reverse) is pinned here so it cannot
quietly flip.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import pkgutil

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
OUTCOMES = SRC / "outcomes"
OUTCOME_FILES = sorted(p for p in OUTCOMES.rglob("*.py") if "__pycache__" not in p.parts)


def source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def imported(path: pathlib.Path) -> set[str]:
    tree = ast.parse(source(path), filename=str(path))
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


def called_names(path: pathlib.Path) -> set[str]:
    """Every callee spelled in the file: bare names and dotted attributes."""
    tree = ast.parse(source(path), filename=str(path))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
                if isinstance(func.value, ast.Name):
                    called.add(f"{func.value.id}.{func.attr}")
    return called


def attribute_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(source(path), filename=str(path))
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


# -- the package exists with exactly the 12B shape ------------------------------


def test_the_12b_package_has_exactly_four_modules():
    names = sorted(p.name for p in OUTCOME_FILES)
    assert names == ["__init__.py", "identity.py", "models.py", "tracking.py"], names


def test_later_stage_modules_do_not_exist_yet():
    for later in ("ports.py", "store.py", "summary.py"):
        assert not (OUTCOMES / later).exists(), later


# -- what it may and may not import ----------------------------------------------


ALLOWED_PREFIXES = (
    "src.data", "src.strategies", "src.assessments", "src.evaluation",
)

FORBIDDEN_PACKAGES = (
    "src.application", "src.dashboard", "src.portfolio", "src.reasoning",
    "src.scanner", "src.news", "src.feeds", "src.features", "src.backtesting",
    "src.signals", "src.evaluation.metrics",
)

FORBIDDEN_MODULES = (
    "anthropic", "streamlit", "requests", "urllib", "urllib3", "httpx", "socket",
    "logging", "os", "sys", "subprocess", "threading", "asyncio", "sqlite3",
    "csv", "pickle", "shelve", "tempfile", "random", "time", "locale", "io",
    "pathlib", "importlib",
)


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_every_project_import_is_an_allowed_domain_dependency(path):
    project = {name for name in imported(path) if name.startswith("src")}
    offenders = [
        name for name in project
        if not any(name == prefix or name.startswith(prefix + ".") for prefix in ALLOWED_PREFIXES)
    ]
    assert not offenders, offenders


@pytest.mark.parametrize("package", FORBIDDEN_PACKAGES)
def test_no_forbidden_layer_is_imported(package):
    for path in OUTCOME_FILES:
        assert not imports_package(imported(path), package), f"{path.name} imports {package}"


@pytest.mark.parametrize("module", FORBIDDEN_MODULES)
def test_no_io_network_clock_or_vendor_module_is_imported(module):
    for path in OUTCOME_FILES:
        assert not imports_package(imported(path), module), f"{path.name} imports {module}"


def test_only_tracking_consumes_phase_four_and_only_its_public_api():
    """The domain records (12A) stay measurement-free; the integration module
    is the one place Phase 4 is asked anything, and it asks through
    ``src.evaluation``'s public surface, never a submodule or a private name."""
    for path in OUTCOME_FILES:
        phase_four = {n for n in imported(path) if imports_package({n}, "src.evaluation")}
        if path.name == "tracking.py":
            assert phase_four == {"src.evaluation"}, phase_four
        else:
            assert not phase_four, f"{path.name} imports {phase_four}"

    tree = ast.parse(source(OUTCOMES / "tracking.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.evaluation":
            names = {alias.name for alias in node.names}
            assert not any(name.startswith("_") for name in names), names
            evaluation = importlib.import_module("src.evaluation")
            assert names <= set(evaluation.__all__), names - set(evaluation.__all__)


def test_no_forward_return_arithmetic_outside_phase_four():
    """Phase 4 is the measurement authority. ``tracking.py`` must never
    divide, subtract or multiply anything, and must never read a price off a
    bar: every number it stores is read off a ``ForwardMeasurement``."""
    tree = ast.parse(source(OUTCOMES / "tracking.py"))
    arithmetic = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp)
                  and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Sub, ast.Mult, ast.Pow, ast.Add))]
    assert not arithmetic, [ast.dump(n) for n in arithmetic]
    price_reads = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                   and n.attr in {"open", "high", "low", "close", "volume"}]
    assert not price_reads, price_reads
    # ...and no dynamic route around the static check. Prices reach this
    # module only through ``bar_fingerprint``/``bars_fingerprint`` (identity)
    # and ``ForwardMeasurement`` (Phase 4).
    dynamic = called_names(OUTCOMES / "tracking.py") & {"getattr", "vars", "astuple", "asdict"}
    assert not dynamic, dynamic
    assert "__dict__" not in attribute_names(OUTCOMES / "tracking.py")


def test_no_vendor_or_framework_name_appears_at_all():
    for path in OUTCOME_FILES:
        text = source(path)
        for forbidden in ("anthropic", "streamlit", "requests", "urllib", "httpx"):
            assert forbidden not in text, f"{path.name} mentions {forbidden!r}"


# -- purity: no I/O, no clock, no environment ----------------------------------------


IO_CALLS = {
    "open", "os.open", "fsync", "os.fsync", "read_text", "write_text", "read_bytes",
    "write_bytes", "mkdir", "unlink", "rename", "replace", "connect", "urlopen",
    "getenv", "environ", "os.getenv", "print", "input",
    # dynamic-import / code-execution escape hatches around the static checks
    "__import__", "import_module", "eval", "exec", "compile",
}
CLOCK_CALLS = {"now", "utcnow", "today", "time", "time.time", "monotonic", "perf_counter",
               "datetime.now", "datetime.utcnow", "date.today"}


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_io_call(path):
    assert not (called_names(path) & IO_CALLS), called_names(path) & IO_CALLS


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_clock_read(path):
    """Every timestamp is caller-supplied; a domain record never asks what
    time it is."""
    assert not (called_names(path) & CLOCK_CALLS), called_names(path) & CLOCK_CALLS


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_environment_or_filesystem_attribute(path):
    assert not (attribute_names(path) & {"environ", "getenv", "read_text", "write_text",
                                         "read_bytes", "write_bytes", "fsync"})


def test_no_python_hash_is_used_for_identity():
    """``hash()`` is randomised per process; identity is SHA-256 only."""
    for path in OUTCOME_FILES:
        tree = ast.parse(source(path), filename=str(path))
        builtin_hash_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "hash"
        ]
        assert not builtin_hash_calls, path.name


# -- nothing consumes it yet, and the direction is pinned ---------------------------------


def test_no_production_module_imports_outcomes_yet():
    """12B is unconsumed. The ledger (12C), the application service (12D)
    and the dashboard hook are later gates; a consumer appearing now would be
    scope creep."""
    consumers = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
        and "outcomes" not in path.parts
        and imports_package(imported(path), "src.outcomes")
    ]
    assert consumers == [], consumers


@pytest.mark.parametrize("package", ["assessments", "strategies", "evaluation", "portfolio",
                                     "reasoning", "features", "data"])
def test_no_upstream_layer_can_ever_see_outcomes(package):
    """Evaluation consumes assessments and observations; nothing flows back."""
    for path in sorted((SRC / package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        assert not imports_package(imported(path), "src.outcomes"), path


# -- the public surface -----------------------------------------------------------------


EXPECTED_PUBLIC = {
    # 12A
    "ArtifactKind", "ArtifactOrigin", "TrackedArtifact", "ObservationArtifact",
    "AssessmentArtifact", "OutcomeRecord", "OutcomeTrackingError",
    "EVALUATION_VERSION", "SUPPORTED_EVALUATION_VERSIONS",
    "observation_artifact_key", "assessment_artifact_key", "outcome_key",
    "bar_fingerprint", "bars_fingerprint",
    # 12B
    "TrackingStatus", "RefusalReason", "TrackingResult", "evaluate_artifact",
}


def test_public_api_is_exactly_the_12b_surface():
    module = importlib.import_module("src.outcomes")
    assert set(module.__all__) == EXPECTED_PUBLIC
    for name in EXPECTED_PUBLIC:
        assert hasattr(module, name), name


def test_tracking_exports_exactly_its_public_names():
    module = importlib.import_module("src.outcomes.tracking")
    assert set(module.__all__) == {"TrackingStatus", "RefusalReason", "TrackingResult",
                                   "evaluate_artifact"}


def test_every_module_imports_cleanly():
    package = importlib.import_module("src.outcomes")
    for info in pkgutil.walk_packages(package.__path__, "src.outcomes."):
        importlib.import_module(info.name)
