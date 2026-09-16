"""Phase 12A-12E architecture, enforced by import and call analysis.

``src.outcomes`` is a domain package with one filesystem adapter at its
edge: models, identity, the tracking integration that asks Phase 4 to
measure (12B), the persistence port (12C, pure), the JSONL ledger (12C,
the only module allowed to touch a file) and the descriptive summary that
reads a partition back through the port (12E, pure, read-only). It reaches
only the Phase 1/3/4/6
record types it describes and the Phase 4 public measurement API. Exactly
one production module consumes it -- the 12D application orchestration,
``src/application/outcomes.py`` -- and the dashboard reaches outcomes only
through that module, never through the package. The dependency direction
(outcomes consume evaluation, never the reverse) is pinned here so it
cannot quietly flip.
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


#: The one module that may open a file. Everything else in the package is
#: pure, and the port that the store implements is pure by construction.
STORE = OUTCOMES / "store.py"
PURE_FILES = [p for p in OUTCOME_FILES if p != STORE]


# -- the package exists with exactly the 12C shape ------------------------------


def test_the_phase_12_package_has_exactly_seven_modules():
    names = sorted(p.name for p in OUTCOME_FILES)
    assert names == ["__init__.py", "identity.py", "models.py", "ports.py", "store.py",
                     "summary.py", "tracking.py"], names


#: The one production consumer of ``src.outcomes``: 12D orchestration.
APPLICATION_OUTCOMES = SRC / "application" / "outcomes.py"


#: The 12E summary: pure, read-only, the only module that aggregates.
SUMMARY = OUTCOMES / "summary.py"


def test_the_stage_boundary_is_12e():
    """12D orchestration and 12E summary are in. Error analysis (Phase 13),
    outcome-aware reasoning (11B), an application-level summary and any
    monitoring are later gates, and no module for them may appear before
    its gate."""
    assert APPLICATION_OUTCOMES.exists()
    assert SUMMARY.exists()
    for later in (
        OUTCOMES / "analysis.py", OUTCOMES / "errors.py", OUTCOMES / "monitoring.py",
        SRC / "application" / "outcome_summary.py",
        SRC / "application" / "outcome_analysis.py",
        SRC / "application" / "monitoring.py",
        SRC / "reasoning" / "outcomes.py",
        SRC / "monitoring",
    ):
        assert not later.exists(), later


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

#: What the store may add on top of the domain's imports, and nothing else:
#: a serializer and the two names it needs to append and fsync a file.
STORE_ONLY_MODULES = frozenset({"json", "os", "pathlib"})


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
    for path in PURE_FILES:
        assert not imports_package(imported(path), module), f"{path.name} imports {module}"
    if module not in STORE_ONLY_MODULES:
        assert not imports_package(imported(STORE), module), f"store.py imports {module}"


def test_the_store_imports_exactly_its_filesystem_allowance():
    stdlib = {name for name in imported(STORE) if not name.startswith(("src", "."))}
    assert stdlib & {"os", "pathlib", "json"} == {"os", "pathlib", "json"}
    assert not stdlib & (set(FORBIDDEN_MODULES) - STORE_ONLY_MODULES), stdlib
    assert "hashlib" not in stdlib, "the store never hashes; keys come from the domain"


def test_the_port_is_pure():
    """ports.py is the contract; it must be importable without any adapter
    concern -- no serializer, no filesystem, no os."""
    assert not imported(OUTCOMES / "ports.py") & (set(FORBIDDEN_MODULES) | {"json", "hashlib"})


def test_only_tracking_and_summary_see_phase_four_and_only_its_public_api():
    """The domain records (12A) stay measurement-free. The integration module
    is the one place Phase 4 is asked to *measure*; the summary (12E) sees
    Phase 4 only to name the specification it reports under. Both ask
    through ``src.evaluation``'s public surface, never a submodule or a
    private name."""
    for path in OUTCOME_FILES:
        phase_four = {n for n in imported(path) if imports_package({n}, "src.evaluation")}
        if path.name in ("tracking.py", "summary.py"):
            assert phase_four == {"src.evaluation"}, phase_four
        else:
            assert not phase_four, f"{path.name} imports {phase_four}"

    evaluation = importlib.import_module("src.evaluation")
    for path in (OUTCOMES / "tracking.py", SUMMARY):
        tree = ast.parse(source(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.evaluation":
                names = {alias.name for alias in node.names}
                assert not any(name.startswith("_") for name in names), names
                assert names <= set(evaluation.__all__), names - set(evaluation.__all__)
                if path == SUMMARY:
                    assert names == {"OutcomeSpec"}, names


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


#: The store may open, append, flush, fsync, create its directories and read
#: a file back. It still may not read the environment, print, or execute code.
STORE_IO_CALLS = {"open", "os.fsync", "fsync", "mkdir", "read_bytes", "is_file", "write",
                  "flush", "fileno"}


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_io_call(path):
    allowed = STORE_IO_CALLS if path == STORE else set()
    offenders = (called_names(path) & IO_CALLS) - allowed
    assert not offenders, offenders


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_clock_read(path):
    """Every timestamp is caller-supplied; a domain record never asks what
    time it is."""
    assert not (called_names(path) & CLOCK_CALLS), called_names(path) & CLOCK_CALLS


@pytest.mark.parametrize("path", OUTCOME_FILES, ids=lambda p: p.name)
def test_no_environment_or_filesystem_attribute(path):
    filesystem = {"read_text", "write_text", "read_bytes", "write_bytes", "fsync"}
    environment = {"environ", "getenv"}
    forbidden = environment if path == STORE else environment | filesystem
    assert not (attribute_names(path) & forbidden)


def test_the_store_never_reads_a_default_root_from_anywhere():
    """The root is injected. No module-level default path, no environment
    lookup, no ``Path.cwd()``/``Path.home()`` and no ``__file__``-relative
    repository root: where a ledger lives is the application's decision."""
    text = source(STORE)
    for forbidden in ("REPO_ROOT", "DEFAULT_", "__file__", "cwd(", "home("):
        assert forbidden not in text, forbidden
    assert not attribute_names(STORE) & {"environ", "getenv"}
    assert not called_names(STORE) & {"getenv", "os.getenv"}


def test_the_store_does_no_price_arithmetic_and_reimplements_no_key():
    """The store persists what the domain produced. It must never derive a
    forward return, and it must obtain every key from the record itself."""
    tree = ast.parse(source(STORE))
    arithmetic = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp)
                  and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Sub, ast.Mult, ast.Pow))]
    assert not arithmetic, [ast.dump(n) for n in arithmetic]
    assert not called_names(STORE) & {
        "digest", "sha256", "hash", "canonical_bytes",
        "observation_artifact_key", "assessment_artifact_key", "outcome_key",
    }
    assert not called_names(STORE) & {"getattr", "vars", "astuple", "asdict", "loads_pickle"}
    assert "__dict__" not in attribute_names(STORE)
    assert "pickle" not in source(STORE)


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


def test_only_the_application_orchestration_consumes_outcomes():
    """Consumers, by name. The 12D application module is the only production
    code that may register, evaluate or read through the ledger; the Phase R
    study orchestration reuses only the package's bar fingerprint for its
    manifest. The dashboard reaches outcomes through the application's API,
    and nothing else does."""
    consumers = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
        and "outcomes" not in path.parts
        and imports_package(imported(path), "src.outcomes")
    ]
    assert consumers == ["application/outcomes.py", "application/study.py"], consumers


def test_the_study_orchestration_reuses_only_the_bar_fingerprint():
    """Phase R records what bars it read; it never registers, evaluates or
    reads a ledger. The one name it takes from the package says so."""
    tree = ast.parse(source(SRC / "application" / "study.py"))
    taken = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.outcomes"
        for alias in node.names
    }
    assert taken == {"bars_fingerprint"}, taken


def test_the_dashboard_never_reaches_outcomes_directly():
    for path in sorted((SRC / "dashboard").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        names = imported(path)
        assert not imports_package(names, "src.outcomes"), path.name
        text = source(path)
        for word in ("JsonlOutcomeLedger", "artifacts.jsonl", "outcomes.jsonl",
                     "data/outcomes", "register_artifact", "append_outcome",
                     "evaluate_artifact", "artifact_key", "outcome_key", "SCHEMA_VERSION"):
            assert word not in text, f"{path.name} mentions {word}"


def test_the_orchestration_uses_the_package_surface_not_the_store_module():
    names = imported(APPLICATION_OUTCOMES)
    assert "src.outcomes" in names
    assert not [n for n in names if n.startswith("src.outcomes.")], names


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
    # 12C
    "LedgerError", "LedgerCorruption", "UnsupportedSchemaError",
    "UnregisteredArtifactError", "ArtifactMismatchError",
    "WriteStatus", "WriteResult", "LedgerPartition",
    "OutcomeReader", "OutcomeLedger", "JsonlOutcomeLedger",
    # 12E -- the group-key types stay module-public (``src.outcomes.summary``)
    # and off the package surface: consumers read keys off groups, never
    # construct them.
    "MIN_SUMMARY_SAMPLES", "OVERLAP_CAVEAT", "OutcomeSummaryError",
    "ProducerKey", "OutcomeCoverageGroup", "OutcomeMetricGroup", "OutcomeSummary",
    "summarize_outcomes",
}


def test_public_api_is_exactly_the_phase_12_surface():
    module = importlib.import_module("src.outcomes")
    assert set(module.__all__) == EXPECTED_PUBLIC
    for name in EXPECTED_PUBLIC:
        assert hasattr(module, name), name


def test_tracking_exports_exactly_its_public_names():
    module = importlib.import_module("src.outcomes.tracking")
    assert set(module.__all__) == {"TrackingStatus", "RefusalReason", "TrackingResult",
                                   "evaluate_artifact"}


def test_ports_exports_exactly_its_public_names():
    module = importlib.import_module("src.outcomes.ports")
    assert set(module.__all__) == {
        "LedgerError", "LedgerCorruption", "UnsupportedSchemaError",
        "UnregisteredArtifactError", "ArtifactMismatchError",
        "WriteStatus", "WriteResult", "LedgerPartition", "OutcomeReader", "OutcomeLedger",
    }


def test_store_exports_the_adapter_and_its_schema_constants_only():
    """Encoders and decoders stay private: the line format is the store's
    contract with its own files, not an API."""
    module = importlib.import_module("src.outcomes.store")
    assert set(module.__all__) == {
        "SCHEMA_VERSION", "ARTIFACTS_FILE", "OUTCOMES_FILE",
        "RECORD_TYPE_ARTIFACT", "RECORD_TYPE_OUTCOME", "JsonlOutcomeLedger",
    }
    assert module.SCHEMA_VERSION == 1
    package = importlib.import_module("src.outcomes")
    assert not hasattr(package, "SCHEMA_VERSION"), "schema version is the store's, not the domain's"


def test_summary_exports_exactly_its_public_names():
    module = importlib.import_module("src.outcomes.summary")
    assert set(module.__all__) == {
        "MIN_SUMMARY_SAMPLES", "OVERLAP_CAVEAT", "OutcomeSummaryError",
        "ProducerKey", "CoverageGroupKey", "MetricGroupKey",
        "OutcomeCoverageGroup", "OutcomeMetricGroup", "OutcomeSummary",
        "summarize_outcomes",
    }
    assert module.MIN_SUMMARY_SAMPLES == 20
    package = importlib.import_module("src.outcomes")
    assert not hasattr(package, "CoverageGroupKey") and not hasattr(package, "MetricGroupKey")


# -- the summary is a pure, read-only, descriptive reader --------------------------------


def test_the_summary_never_writes_and_never_names_a_ledger():
    """12E reads through ``OutcomeReader`` only. It must not call either
    write, must not import the ledger protocol or the adapter, and must
    not reach for a record by key (one pass over each iterator)."""
    assert not called_names(SUMMARY) & {
        "register_artifact", "append_outcome", "get_artifact", "get_outcome",
        "contains_artifact", "contains_outcome",
    }
    tree = ast.parse(source(SUMMARY))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            assert not names & {"OutcomeLedger", "JsonlOutcomeLedger"}, names
            assert node.module not in ("store", "src.outcomes.store"), node.module
    for name in ("iter_artifacts", "iter_outcomes"):
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == name]
        assert len(calls) == 1, f"{name} must be called exactly once"


def test_the_summary_reads_no_price_and_recomputes_no_return():
    """The only number read off a record is ``forward_return``; prices,
    bars and every arithmetic operator except counting are absent. The one
    division is the coverage fraction, in its own named helper."""
    tree = ast.parse(source(SUMMARY))
    assert not attribute_names(SUMMARY) & {
        "open", "high", "low", "close", "volume", "reference_price", "future_price",
        "bars", "series", "measurement",
    }
    operators = {type(n.op).__name__ for n in ast.walk(tree) if isinstance(n, ast.BinOp)}
    assert operators <= {"Add", "Div", "BitOr"}, operators   # BitOr: ``X | None`` annotations
    divisions = [
        function.name for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef)
        and any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) for n in ast.walk(function))
    ]
    assert divisions == ["_fraction"], divisions
    assert not called_names(SUMMARY) & {
        "measure_forward", "evaluate_artifact", "getattr", "vars", "astuple", "asdict",
        "digest", "sha256", "canonical_bytes", "bar_fingerprint", "bars_fingerprint",
    }
    assert "__dict__" not in attribute_names(SUMMARY)


def test_the_summary_exposes_no_ranking_or_inference():
    """No hit rate, score, rank, best-anything or significance -- not as a
    field, a property or a method on any public result type."""
    module = importlib.import_module("src.outcomes.summary")
    forbidden = ("rate", "score", "rank", "best", "overall", "accuracy", "sharpe",
                 "sortino", "alpha", "beta", "confidence", "pvalue", "p_value",
                 "significan", "probability", "win", "hit", "leaderboard", "profit",
                 "sufficien", "power")
    for name in module.__all__:
        obj = getattr(module, name)
        if not isinstance(obj, type):
            continue
        members = {m for m in dir(obj) if not m.startswith("_")}
        members |= {f.name for f in getattr(obj, "__dataclass_fields__", {}).values()}
        for member in members:
            for word in forbidden:
                assert word not in member.lower(), f"{name}.{member} suggests {word!r}"
    assert not imports_package(imported(SUMMARY), "statistics.stdev")
    assert not called_names(SUMMARY) & {"stdev", "pstdev", "variance", "pvariance",
                                         "NormalDist", "correlation", "linear_regression"}


def test_the_summary_carries_the_overlap_caveat():
    module = importlib.import_module("src.outcomes.summary")
    assert module.OutcomeSummary.overlap_caveat == module.OVERLAP_CAVEAT
    assert "overlapping forward windows" in module.OVERLAP_CAVEAT
    assert "not independent statistical trials" in module.OVERLAP_CAVEAT


def test_domain_models_carry_no_schema_version():
    for name in ("TrackedArtifact", "ObservationArtifact", "AssessmentArtifact", "OutcomeRecord"):
        cls = getattr(importlib.import_module("src.outcomes.models"), name)
        assert "schema_version" not in getattr(cls, "__dataclass_fields__", {}), name
    assert "schema_version" not in source(OUTCOMES / "models.py")
    assert "schema_version" not in source(OUTCOMES / "identity.py")


def test_every_module_imports_cleanly():
    package = importlib.import_module("src.outcomes")
    for info in pkgutil.walk_packages(package.__path__, "src.outcomes."):
        importlib.import_module(info.name)
