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


#: The one file permitted to name a vendor, and the one vendor it may name.
#:
#: Written as data rather than as an ``if`` so the exemption is a list somebody
#: has to edit -- and so the test below can insist it is actually being used. A
#: permission nobody exercises is a hole nobody is watching.
VENDOR_EXEMPTIONS = {"anthropic_adapter.py": frozenset({"anthropic"})}


@pytest.mark.parametrize("path", REASONING_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("vendor", VENDOR_SDKS)
def test_the_reasoning_domain_imports_no_model_vendor(path, vendor):
    """One file may reach one vendor. Every other file, and every other vendor.

    The adapter exists precisely so this ban can stay absolute everywhere else:
    the moment a second module imports a model vendor, the package has stopped
    being provider-neutral and the neutrality of the contract is decoration.
    """
    if vendor in VENDOR_EXEMPTIONS.get(path.name, frozenset()):
        assert imports_package(imported(path), vendor), (
            f"{path.name} is exempted for {vendor} but no longer imports it; "
            "delete the exemption rather than leaving it open"
        )
        return
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


# -- Stage C: the provider contract stays a contract ----------------------


PROVIDERS = REASONING / "providers.py"


def test_the_provider_module_exists_and_is_a_module_not_a_package():
    """One file, deliberately.

    A ``providers/`` directory is where vendor adapters accumulate, and Stage C
    has no vendor. Keeping it a single module means adding one is a visible
    decision rather than dropping a file into a folder that was already there.
    """
    assert PROVIDERS in REASONING_FILES
    assert not (REASONING / "providers").exists()


def test_the_provider_module_uses_only_permitted_stdlib():
    """A Protocol and an error type need nothing but ``typing``.

    Anything else appearing here would be transport, and transport is what this
    module describes rather than performs.
    """
    permitted = {"__future__", "typing"}
    external = {
        name for name in imported(PROVIDERS)
        if not name.startswith(".") and not name.startswith("src.")
    }
    assert external <= permitted, f"providers.py imports {external - permitted}"


def test_the_provider_module_imports_only_within_this_package():
    for name in imported(PROVIDERS):
        assert not name.startswith("src."), f"providers.py imports {name}"


def test_the_provider_module_names_no_vendor_even_in_prose():
    """The import ban is not enough on its own.

    A vendor-shaped request body needs no import to be wrong: the moment a
    message envelope appears here, the abstraction has stopped being
    provider-neutral and has become one provider's shape wearing a neutral
    name.
    """
    text = PROVIDERS.read_text(encoding="utf-8").lower()
    for vendor in ("anthropic", "openai", "gemini", "vertex", "bedrock", "cohere",
                   "mistral", "ollama", "llama", "gpt-", "claude"):
        assert vendor not in text, f"providers.py mentions {vendor}"
    for envelope in ('"role"', "'role'", "messages=", "system=", "assistant",
                     "completion", "chat"):
        assert envelope not in text, f"providers.py carries {envelope}"


def test_the_provider_module_does_not_validate():
    """Transport and judgement are separate jobs, and this is the transport.

    A provider that reached the validator could pre-screen its own output, and
    the one thing a caller must be able to assume -- that what came back is
    exactly what arrived -- would quietly stop being true.
    """
    text = PROVIDERS.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(PROVIDERS))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "validation":
            raise AssertionError("providers.py imports the validator")
    offenders = called(PROVIDERS) & {
        "validate_provider_response", "parse_payload", "validate_grounding",
        "validate_boundary_language", "validate_consistency",
        "find_boundary_violation", "normalize_for_boundary",
    }
    assert not offenders, f"providers.py calls {offenders}"


def test_the_provider_module_has_no_retry_machinery():
    """Retry policy needs real failure semantics, and there are none yet.

    A loop written now would encode a guess about how a service fails, and the
    guess would be indistinguishable from a decision once it was in place.
    """
    offenders = called(PROVIDERS) & {"sleep", "retry", "backoff", "jitter",
                                     "wait", "uniform", "randint", "random"}
    assert not offenders, f"providers.py calls {offenders}"
    tree = ast.parse(PROVIDERS.read_text(encoding="utf-8"), filename=str(PROVIDERS))
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.For))]
    assert not loops or all(isinstance(n, ast.For) for n in loops), (
        "providers.py contains a while loop"
    )


def test_the_provider_module_defines_exactly_the_contract_and_nothing_else():
    """The surface is pinned, because every way it could grow is a mistake.

    Three of them are worth naming. A second provider implementation shipping
    here -- under any name, not only one spelled "fake" -- would be a
    fabricator in the production package. A ``LLMResponse`` or ``TokenUsage``
    class would be a competing type for something the domain already owns, and
    the two would drift the first time one was edited. A helper that assembled
    a vendor request body would make the neutral abstraction one vendor's shape
    wearing a neutral name.

    A name-based ban catches none of those; a pinned surface catches all of
    them, and turns adding anything into a decision somebody has to defend.
    """
    tree = ast.parse(PROVIDERS.read_text(encoding="utf-8"), filename=str(PROVIDERS))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert classes == ["ReasoningProviderError", "ReasoningProvider"], classes
    assert functions == [], functions


def test_no_test_double_ships_in_the_reasoning_package():
    """The fake lives in the tests, the way every other fake in this repo does.

    A fabricator exported from a production package is one import away from
    being wired into the real path, and it would look exactly like a provider
    while inventing everything it returned.
    """
    for path in REASONING_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                lowered = node.name.lower()
                for marker in ("fake", "stub", "dummy", "mock", "recording"):
                    assert marker not in lowered, f"{path.name} defines {node.name}"


def test_the_snapshot_construction_sweep_actually_covers_providers():
    """Verified, not re-asserted.

    ``test_only_validation_constructs_the_trusted_snapshot`` already sweeps every
    production file, so the useful thing to check is that providers.py is in the
    set it sweeps -- a second, weaker copy of that test would be the kind of
    duplicate that rots.
    """
    swept = [
        path for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    assert PROVIDERS in swept
    assert not _constructs_snapshot(PROVIDERS)


# -- Stage D: one adapter, and only one --------------------------------------


ADAPTER = REASONING / "anthropic_adapter.py"


def test_the_adapter_exists_and_is_the_only_exemption():
    assert ADAPTER in REASONING_FILES
    assert set(VENDOR_EXEMPTIONS) == {ADAPTER.name}


def test_the_vendor_name_appears_only_where_it_must():
    """Import analysis is not enough: a name is contagious.

    A vendor-shaped request body needs no import to be wrong, and a helper in a
    neutral module named after one service is how "provider-neutral" quietly
    becomes "one provider, plus adapters for the others". The package export is
    permitted because it is the module path, not a vendor concept.
    """
    permitted = {ADAPTER.name, "__init__.py"}
    for path in REASONING_FILES:
        if path.name in permitted:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for vendor in ("anthropic", "openai", "gemini", "vertex", "bedrock"):
            assert vendor not in text, f"{path.name} mentions {vendor}"


def test_the_adapter_imports_only_stdlib_and_the_one_vendor():
    """The SDK owns transport, so the adapter owns none of it.

    No network module appears here -- that is what keeps the package-wide
    network ban unamended and applying to this file like every other.
    """
    permitted = {"__future__", "json", "time", "typing", "anthropic"}
    external = {
        name for name in imported(ADAPTER)
        if not name.startswith(".") and not name.startswith("src.")
    }
    assert external <= permitted, f"adapter imports {external - permitted}"


def test_the_adapter_is_still_bound_by_every_unamended_sweep():
    """The vendor ban is the only thing Stage D relaxed.

    Network, filesystem, credential, dynamic-execution and clock bans all still
    apply to the adapter unchanged, and this states that as a fact rather than
    leaving it to be inferred from the absence of an exemption.
    """
    names = imported(ADAPTER)
    for module in NETWORK_MODULES + BACKGROUND_MODULES + STORAGE_MODULES:
        assert not imports_package(names, module), f"adapter imports {module}"
    assert not (called(ADAPTER) & FILE_PRIMITIVES)
    assert not (called_bare(ADAPTER) & {"eval", "exec", "compile", "__import__"})
    # The clock ban is deliberately NOT exempted. It still bites an inline
    # ``time.monotonic()`` and is satisfied only by an injected callable, which
    # is exactly the outcome the ban was written to force.
    assert not (called(ADAPTER) & {"now", "utcnow", "today", "time", "monotonic"})
    text = ADAPTER.read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "apikey", "getenv", "environ", "secret",
                      "bearer", "authorization", "token="):
        assert forbidden not in text, f"adapter mentions {forbidden}"


def test_the_adapter_module_defines_exactly_one_provider():
    """Pinned, so a factory, a client builder or a second response type has to
    be argued for rather than appearing."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"), filename=str(ADAPTER))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert classes == ["AnthropicReasoningProvider"], classes
    assert functions == ["_require_positive_number", "_require_positive_int",
                         "_canonical_json"], functions


def test_the_adapter_keeps_no_second_copy_of_the_output_schema():
    """It references the committed schema; it does not restate it.

    A second literal would pass every test in this file while disagreeing with
    the one the validator enforces -- the two would drift the first time either
    was edited, and the drift would show up as unexplained provider failures.
    """
    text = ADAPTER.read_text(encoding="utf-8")
    assert "OUTPUT_SCHEMA" in text
    for fragment in ("additionalProperties", "minItems", '"claims"',
                     '"uncertainties"', '"evidence_ids"'):
        assert fragment not in text, f"adapter restates {fragment}"


def test_the_adapter_constructs_no_snapshot_and_runs_no_validator():
    assert not _constructs_snapshot(ADAPTER)
    # It has no reason to name the trusted type at all. Importing it changes no
    # behaviour on its own, which is exactly why it is worth refusing: it is the
    # cheap first half of a change nobody would approve as a whole.
    for node in ast.walk(ast.parse(ADAPTER.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert alias.name.split(".")[-1] != "ReasoningSnapshot"
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"), filename=str(ADAPTER))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "validation":
            raise AssertionError("the adapter imports the validator")
    offenders = called(ADAPTER) & {
        "validate_provider_response", "parse_payload", "validate_grounding",
        "validate_boundary_language", "validate_consistency",
    }
    assert not offenders, f"the adapter calls {offenders}"


def test_the_adapter_never_constructs_a_vendor_client():
    """It may import the library; it may not create a session with it.

    Constructing a client is where a credential gets read and a connection gets
    opened. The adapter receives one already built, so the constructor call has
    no business appearing here at all -- and banning the call is what stops a
    plausible-looking ``client or Anthropic()`` default from reintroducing both.
    """
    offenders = called(ADAPTER) & {"Anthropic", "AsyncAnthropic", "AnthropicBedrock",
                                   "AnthropicVertex", "AnthropicAWS", "AnthropicFoundry",
                                   "AnthropicBedrockMantle", "Client"}
    assert not offenders, f"the adapter constructs {offenders}"


def test_the_adapter_reaches_the_domain_by_name_not_by_module():
    """``from .models import X``, never ``from . import models``.

    A module object is a namespace the AST cannot follow: with one in hand,
    ``object.__new__(models.ReasoningSnapshot)`` and
    ``getattr(models, "Reasoning" + "Snapshot")()`` both build trusted state
    while every name-based guard reports the file as clean -- both were tried
    and both survived until this. Importing the symbols the adapter actually
    uses costs nothing and removes the namespace entirely.
    """
    for node in ast.walk(ast.parse(ADAPTER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level and node.module is None:
            raise AssertionError(
                "the adapter imports a sibling module as an object: "
                f"{[alias.name for alias in node.names]}"
            )


def test_the_adapter_has_no_retry_machinery():
    offenders = called(ADAPTER) & {"sleep", "retry", "backoff", "jitter",
                                   "uniform", "randint", "random"}
    assert not offenders, f"adapter calls {offenders}"
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"), filename=str(ADAPTER))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)]
