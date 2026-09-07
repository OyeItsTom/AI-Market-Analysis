"""Phase 11A Stage E architecture, enforced by analysis rather than review.

    dashboard  ->  application.reasoning  ->  reasoning domain  ->  (a provider)

Stage E is the one place that walks a research result all the way to a trusted
explanation, and the value of that is entirely in what it *cannot* do: it holds
no vendor, no credential, no network, no clock of its own beyond the one it is
handed, and no memory between calls. Those are the claims this file turns into
rules.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
MODULE = SRC / "application" / "reasoning.py"


def source(path: pathlib.Path = MODULE) -> str:
    return path.read_text(encoding="utf-8")


def imported(path: pathlib.Path = MODULE) -> set[str]:
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


def imported_names(path: pathlib.Path) -> set[str]:
    """Every symbol pulled in by name, for consumer-ownership questions."""
    tree = ast.parse(source(path), filename=str(path))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def uses_name(path: pathlib.Path, name: str) -> bool:
    """Whether a file *uses* a symbol, rather than merely passing it along.

    A package ``__init__`` that re-exports a name imports it and mentions it in
    ``__all__`` as a string; it never depends on the contract. Counting that as
    consumption would make the ownership rule report a second consumer that
    does nothing, and the rule would have to be relaxed to stay true -- which
    is how an architectural test becomes decoration.
    """
    tree = ast.parse(source(path), filename=str(path))
    imports = {
        node
        for parent in ast.walk(tree)
        if isinstance(parent, (ast.Import, ast.ImportFrom))
        for node in ast.walk(parent)
    }
    return any(
        isinstance(node, ast.Name) and node.id == name and node not in imports
        for node in ast.walk(tree)
    )


def called(path: pathlib.Path) -> set[str]:
    tree = ast.parse(source(path), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def production_files() -> list[pathlib.Path]:
    return [p for p in sorted(SRC.rglob("*.py")) if "__pycache__" not in p.parts]


def test_the_orchestration_exists():
    assert MODULE.exists()


# -- provider-neutral, and structurally so -------------------------------


VENDORS = ("anthropic", "openai", "google", "vertexai", "cohere", "mistralai",
           "langchain", "litellm", "transformers", "ollama")


@pytest.mark.parametrize("vendor", VENDORS)
def test_the_orchestration_names_no_vendor(vendor):
    """It depends on the contract, never on an implementation.

    A vendor here would make the use case one provider's use case, and would
    put the thing that must be replaceable in the one module nobody would think
    to look at when replacing it.
    """
    assert not imports_package(imported(), vendor)
    assert vendor not in source().lower()


def test_the_orchestration_constructs_no_client():
    offenders = called(MODULE) & {
        "Anthropic", "AsyncAnthropic", "OpenAI", "Client",
        "AnthropicReasoningProvider", "build_provider", "default_provider",
    }
    assert not offenders, f"the orchestration builds {offenders}"


NETWORK = ("requests", "httpx", "httpx2", "urllib", "urllib3", "http", "socket",
           "ssl", "aiohttp", "websockets")


@pytest.mark.parametrize("module", NETWORK)
def test_the_orchestration_reaches_no_network(module):
    assert not imports_package(imported(), module)


STORAGE = ("os", "pathlib", "shutil", "tempfile", "sqlite3", "sqlalchemy",
           "shelve", "pickle", "dbm", "csv", "dotenv", "json", "yaml", "toml")


@pytest.mark.parametrize("module", STORAGE)
def test_the_orchestration_reads_and_writes_nothing(module):
    """No configuration file, no store, no serialiser.

    Everything it needs arrives as an argument or an injected dependency, which
    is what makes the whole use case testable without a machine to configure.
    """
    assert not imports_package(imported(), module)


def test_the_orchestration_reads_no_credential_or_ambient_configuration():
    text = source().lower()
    for forbidden in ("api_key", "apikey", "getenv", "environ", "secret",
                      "bearer", "authorization", "token=", ".env"):
        assert forbidden not in text, forbidden
    assert not (called(MODULE) & {"getenv", "environ", "open", "read_text"})


BACKGROUND = ("threading", "asyncio", "multiprocessing", "concurrent", "sched",
              "schedule", "apscheduler", "subprocess", "signal", "importlib",
              "builtins", "functools",
              # ``logging`` is deferred rather than forbidden forever. Nothing
              # here has an observability requirement yet, and the first thing
              # a log line in this module would be handed is an error detail --
              # the one string the layer below bounds precisely because it may
              # carry whatever a provider put in it. When logging is designed,
              # this entry is the thing that has to be argued away.
              "logging")


@pytest.mark.parametrize("module", BACKGROUND)
def test_nothing_runs_in_the_background_and_nothing_is_memoised(module):
    """``functools`` is on the list for ``lru_cache``.

    A cached explanation would outlive the provider, prompt and model it was
    produced by, and would be served as though it had been asked for now.
    """
    assert not imports_package(imported(), module)


def test_the_orchestration_is_synchronous_and_loopless():
    tree = ast.parse(source(), filename=str(MODULE))
    assert not [n for n in ast.walk(tree)
                if isinstance(n, (ast.AsyncFunctionDef, ast.Await, ast.While))]
    assert not (called(MODULE) & {"cache", "lru_cache", "cache_data",
                                  "cache_resource", "memoize", "sleep", "retry"})


# -- the layers it must not reach ----------------------------------------


FORBIDDEN_LAYERS = (
    "src.news", "src.feeds", "src.dashboard", "src.scanner", "src.portfolio",
    "src.application.news", "src.application.feeds", "src.application.paper",
    "src.application.scanner", "src.data", "src.backtesting", "src.evaluation",
)


@pytest.mark.parametrize("package", FORBIDDEN_LAYERS)
def test_the_orchestration_imports_no_unrelated_layer(package):
    """Phase 11A explains deterministic research evidence and nothing else.

    News, feeds, paper state and scanner universes are not part of the grounded
    evidence contract, and market data is not this layer's to fetch -- the
    snapshot arrives already built.
    """
    assert not imports_package(imported(), package)


RESEARCH_PIPELINE = {"get_bars", "build_snapshot", "build_evidence",
                     "evaluate_at", "assess", "build_ensemble", "build_policy",
                     "deduplicate_specs"}


def test_the_orchestration_fetches_no_market_data():
    """It neither calls the research pipeline nor imports it.

    Importing a builder changes nothing on its own, which is why it is worth
    refusing: it is the cheap half of recomputing research inside the module
    whose entire job is to explain research somebody else computed.
    """
    offenders = called(MODULE) & RESEARCH_PIPELINE
    assert not offenders, f"the orchestration recomputes research: {offenders}"
    reachable = imported_names(MODULE) & RESEARCH_PIPELINE
    assert not reachable, f"the orchestration imports {reachable}"


# -- ownership -----------------------------------------------------------


def test_the_orchestration_is_the_only_production_provider_consumer():
    """One consumer, so there is one place the contract is depended upon.

    The adapter *implements* the protocol rather than consuming it, and the
    module that defines it is not a consumer either -- so a second name here
    would mean a second workflow had started calling providers directly.
    """
    consumers = [
        path.relative_to(SRC).as_posix()
        for path in production_files()
        if uses_name(path, "ReasoningProvider")
    ]
    assert consumers == ["application/reasoning.py"], consumers


def test_the_orchestration_is_the_only_production_validator_caller():
    callers = [
        path.relative_to(SRC).as_posix()
        for path in production_files()
        if "validate_provider_response" in called(path)
    ]
    assert callers == ["application/reasoning.py"], callers


def test_the_canonical_packet_builder_is_used_rather_than_reimplemented():
    """Built once, by its owner, and not adjusted afterwards.

    ``dataclasses.replace`` is on the list because it is the polite version of
    rebuilding: it produces a packet that is equal today and is still a second
    construction path, which is the thing the canonical builder exists to be
    the only one of.
    """
    assert "build_packet" in called(MODULE)
    offenders = called(MODULE) & {"EvidencePacket", "PacketObservation",
                                  "PacketCounts", "evidence_fingerprint",
                                  "reasoning_fingerprint", "replace",
                                  "research_context_fingerprint"}
    assert not offenders, f"the orchestration rebuilds domain state: {offenders}"
    assert not imports_package(imported(), "dataclasses")


def test_the_reasoning_domain_still_imports_no_application_module():
    """One-way dependency: Stage E imports the domain, never the reverse."""
    for path in sorted((SRC / "reasoning").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        assert not imports_package(imported(path), "src.application"), path.name
        assert "src.application" not in source(path), path.name


def test_the_dashboard_has_not_started_consuming_reasoning_yet():
    """Stage F owns the interface. Until then this stays a fact, not a promise."""
    for path in sorted((SRC / "dashboard").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        names = imported(path)
        assert not imports_package(names, "src.reasoning"), path.name
        assert not imports_package(names, "src.application.reasoning"), path.name


# -- the public surface --------------------------------------------------


def test_the_module_defines_exactly_the_intended_surface():
    """Pinned, so a second result model or a factory has to be argued for."""
    tree = ast.parse(source(), filename=str(MODULE))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert classes == ["ReasoningAvailability", "ReasoningUnavailable",
                       "ReasoningService"], classes
    assert functions == ["_utc_now"], functions


def test_the_exports_are_what_stage_f_will_need():
    """Including the reasoning types, re-exported rather than duplicated.

    The dashboard firewall permits ``src.application`` imports and forbids
    ``src.reasoning`` ones, so an interface that has to catch a provider
    failure can only reach the class through here. These are the same class
    objects, not copies.
    """
    from src.application import reasoning
    from src.reasoning.models import ReasoningFailureCode, ReasoningSnapshot
    from src.reasoning.providers import ReasoningProviderError
    from src.reasoning.validation import ReasoningValidationError

    assert set(reasoning.__all__) == {
        "Clock", "ReasoningAvailability", "ReasoningFailureCode",
        "ReasoningProviderError", "ReasoningService", "ReasoningSnapshot",
        "ReasoningUnavailable", "ReasoningValidationError",
    }
    assert reasoning.ReasoningFailureCode is ReasoningFailureCode
    assert reasoning.ReasoningSnapshot is ReasoningSnapshot
    assert reasoning.ReasoningProviderError is ReasoningProviderError
    assert reasoning.ReasoningValidationError is ReasoningValidationError


def test_no_duplicate_result_or_failure_model_was_introduced():
    text = source()
    for forbidden in ("@dataclass", "ExplanationResult", "ReasoningOutcome",
                      "ReasoningResult", "class ReasoningFailure"):
        assert forbidden not in text, forbidden


def test_no_test_double_ships_in_the_application_layer():
    for path in sorted((SRC / "application").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(source(path), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                lowered = node.name.lower()
                for marker in ("fake", "stub", "dummy", "mock", "recording"):
                    assert marker not in lowered, f"{path.name} defines {node.name}"


def test_the_orchestration_constructs_no_trusted_snapshot_of_its_own():
    """It returns the validator's snapshot; it never builds one."""
    tree = ast.parse(source(), filename=str(MODULE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name != "ReasoningSnapshot", "the orchestration forges trusted state"
