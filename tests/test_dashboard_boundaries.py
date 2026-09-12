"""Phase 7 architecture and scope, enforced by import analysis rather than review.

The dependency direction is::

    dashboard  ->  application  ->  Phase 1-6 domain

Every rule below is checked against the parsed source, so a boundary cannot be
crossed by an import that merely looks harmless in a diff. The Phase 5/6
independence checks are repeated here because Phase 7 puts research and paper
actions on the same screen for the first time -- the one place where a shortcut
between them would be tempting.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"

DOMAIN_PACKAGES = (
    "src.data",
    "src.features",
    "src.strategies",
    "src.assessments",
    "src.portfolio",
    "src.evaluation",
    "src.backtesting",
    "src.signals",
)


def python_files(*relative: str) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for part in relative:
        root = REPO / part
        if root.is_file():
            found.append(root)
        else:
            found += sorted(root.rglob("*.py"))
    return found


def imported_modules(path: pathlib.Path) -> set[str]:
    """Every module name this file imports, at any depth in the file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside its own package
                continue
            if node.module:
                names.add(node.module)
    return names


def imports_package(names: set[str], package: str) -> bool:
    return any(name == package or name.startswith(package + ".") for name in names)


def code_identifiers(path: pathlib.Path) -> set[str]:
    """Every identifier the file actually *uses*, ignoring prose.

    Docstrings and comments are documentation: a module that explains "no code
    path turns BULLISH into OPEN_LONG" must not be reported as doing it. Only
    names, attributes and imported symbols count as capability.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


DASHBOARD_FILES = python_files("src/dashboard")
APPLICATION_FILES = python_files("src/application")
DOMAIN_FILES = [
    path
    for path in python_files("src")
    if "application" not in path.parts and "dashboard" not in path.parts
]


def test_the_phase_seven_packages_exist():
    assert DASHBOARD_FILES and APPLICATION_FILES and DOMAIN_FILES


# -- dashboard -> application only --------------------------------------


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("package", DOMAIN_PACKAGES)
def test_dashboard_never_imports_a_domain_package(path, package):
    names = imported_modules(path)
    assert not imports_package(names, package), (
        f"{path.relative_to(REPO)} imports {package} directly; the dashboard may "
        "only reach the domain through src.application"
    )


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_dashboard_imports_only_streamlit_stdlib_and_application(path):
    for name in imported_modules(path):
        root = name.split(".")[0]
        if root in {"streamlit", "src"}:
            if root == "src":
                assert name.startswith("src.application") or name.startswith(
                    "src.dashboard"
                ), f"{path.name} imports {name}"
            continue
        # Anything else must be the standard library.
        assert root in {
            "__future__", "dataclasses", "datetime", "decimal", "typing",
            "traceback", "enum", "types", "pathlib", "collections",
            # Phase 10: the market scan shows transient elapsed time while it
            # runs. Named individually, like every other entry here -- the set
            # stays a literal allowlist rather than a stdlib detector.
            "time",
        }, f"{path.name} imports unexpected third-party module {name}"


# -- application never imports the UI -----------------------------------


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=lambda p: p.name)
def test_application_never_imports_streamlit(path):
    assert not imports_package(imported_modules(path), "streamlit"), (
        f"{path.relative_to(REPO)} imports streamlit; the application layer must "
        "stay headlessly testable"
    )


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=lambda p: p.name)
def test_application_never_imports_the_dashboard(path):
    assert not imports_package(imported_modules(path), "src.dashboard")


# -- domain never learns about Phase 7 ----------------------------------


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_domain_never_imports_the_application_layer(path):
    names = imported_modules(path)
    assert not imports_package(names, "src.application")
    assert not imports_package(names, "src.dashboard")


def test_no_phase_one_to_six_source_was_modified_to_reach_phase_seven():
    """Belt and braces: not one domain file mentions the new packages at all."""
    for path in DOMAIN_FILES:
        text = path.read_text()
        assert "src.application" not in text
        assert "src.dashboard" not in text


# -- the research-to-action firewall ------------------------------------


def test_paper_module_never_imports_the_assessment_package():
    names = imported_modules(SRC / "application" / "paper.py")
    assert not imports_package(names, "src.assessments")
    assert not imports_package(names, "src.strategies")


def test_assessments_and_portfolio_stay_independent():
    for path in python_files("src/assessments"):
        assert not imports_package(imported_modules(path), "src.portfolio")
    for path in python_files("src/portfolio"):
        assert not imports_package(imported_modules(path), "src.assessments")
        assert not imports_package(imported_modules(path), "src.strategies")


def test_the_paper_view_cannot_render_an_assessment():
    """The paper panel has no way to show research state as a reason to act.

    Checked against used identifiers, not raw text: the module's docstring
    explains the rule, and explaining a rule is not breaking it.
    """
    used = code_identifiers(SRC / "dashboard" / "paper_view.py")
    for forbidden in (
        "AssessmentView", "assessment_view", "AssessmentState", "ResearchState",
    ):
        assert forbidden not in used


def test_the_research_view_has_no_action_control():
    """No button, form or submit control may exist on the research panel."""
    tree = ast.parse((SRC / "dashboard" / "research_view.py").read_text())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("button", "form", "form_submit_button", "download_button"):
        assert forbidden not in called, f"research_view calls st.{forbidden}"


def test_the_research_view_cannot_touch_paper_state():
    text = (SRC / "dashboard" / "research_view.py").read_text()
    for forbidden in ("PaperSession", "open_long", "close_position", "portfolio"):
        assert forbidden not in text


#: Identifiers through which a research classification could be read.
RESEARCH_STATE_NAMES = {
    "AssessmentState", "ResearchState", "ResearchAssessment", "AssessmentView",
    "ResearchObservation",
}


def test_the_mutating_module_cannot_see_a_research_state():
    """``paper.py`` has no identifier through which a state could be read.

    This is the firewall in its strongest form: not "it does not currently
    branch on BULLISH", but "there is no name in scope that could be branched
    on". Prose is ignored -- the module's docstring explains the rule.
    """
    used = code_identifiers(SRC / "application" / "paper.py")
    assert not (used & RESEARCH_STATE_NAMES)


def test_no_research_value_reaches_an_action_call():
    """Every argument of an ``open_long`` call comes from the human's form.

    ``app.py`` is the one module that legitimately renders research *and*
    applies paper actions, so the check is on the call itself: nothing derived
    from the snapshot or the assessment may appear in its arguments.
    """
    forbidden_sources = {"snapshot", "assessment", "state", "observations"}
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name not in {"open_long", "close_position"}:
                continue
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                for inner in ast.walk(argument):
                    if isinstance(inner, ast.Name):
                        assert inner.id not in forbidden_sources, (
                            f"{path.name}: {name}() receives {inner.id!r}"
                        )


#: Names through which a research classification could be reached.
RESEARCH_VALUE_NAMES = {
    "snapshot", "assessment", "observations", "state", "counts",
    "AssessmentState", "ResearchState", "ResearchAssessment", "AssessmentView",
    "is_conflicted", "is_insufficient", "bullish", "bearish", "conflicted",
}

#: Every function that changes paper state.
MUTATOR_NAMES = {"open_long", "close_position", "apply", "apply_open_long", "apply_close"}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    links: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            links[child] = node
    return links


def _mentions_research(expression: ast.AST) -> str | None:
    for node in ast.walk(expression):
        if isinstance(node, ast.Name) and node.id in RESEARCH_VALUE_NAMES:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in RESEARCH_VALUE_NAMES:
            return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in {"bullish", "bearish", "conflicted"}:
                return node.value
    return None


def test_no_paper_action_is_conditional_on_a_research_state():
    """No action may be *gated* on what the research said.

    The companion test below checks data flow -- that no research value is
    passed as an argument. This one checks control flow, which is the form the
    forbidden mapping would actually take::

        if assessment.state == BULLISH:      # <- this
            session.open_long(...)

    Nothing derived from a research classification may decide *whether* a paper
    action happens, which is the whole ``BULLISH -> OPEN_LONG`` prohibition.
    """
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        links = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if called not in MUTATOR_NAMES:
                continue
            current: ast.AST | None = node
            while current is not None:
                parent = links.get(current)
                if isinstance(parent, (ast.If, ast.While)) and current is not parent.test:
                    culprit = _mentions_research(parent.test)
                    assert culprit is None, (
                        f"{path.name}: {called}() is conditional on {culprit!r}; "
                        "a research state must never decide whether a paper "
                        "action happens"
                    )
                elif isinstance(parent, ast.IfExp) and current is not parent.test:
                    culprit = _mentions_research(parent.test)
                    assert culprit is None, (
                        f"{path.name}: {called}() is conditional on {culprit!r}"
                    )
                current = parent


def test_portfolio_apply_is_never_called_from_rendering_code():
    """Mutation belongs to the application layer, not to a render pass."""
    for path in DASHBOARD_FILES:
        text = path.read_text()
        assert ".apply(" not in text, f"{path.name} applies an intent directly"


def test_only_the_paper_session_mutates_the_portfolio():
    applies = [
        path
        for path in python_files("src/application", "src/dashboard")
        if ".apply(" in path.read_text()
    ]
    assert [path.name for path in applies] == ["paper.py"]


# -- loopback / network exposure ----------------------------------------

CONFIG = REPO / ".streamlit" / "config.toml"


def active_config_lines() -> list[str]:
    """Configuration lines only -- comments are documentation, not settings."""
    lines = []
    for raw in CONFIG.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def test_streamlit_config_exists():
    assert CONFIG.is_file()


def test_loopback_address_is_configured_explicitly():
    assert 'address = "127.0.0.1"' in active_config_lines()


def test_the_config_never_binds_to_all_interfaces():
    for line in active_config_lines():
        assert "0.0.0.0" not in line


def test_no_phase_seven_runtime_file_configures_all_interfaces():
    """A comment warning against 0.0.0.0 is fine; a setting is not."""
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        for raw in path.read_text().splitlines():
            code = raw.split("#", 1)[0]
            assert "0.0.0.0" not in code, f"{path.name}: {raw.strip()}"


def test_streamlit_resolves_the_loopback_address():
    """The installed Streamlit must actually accept this configuration."""
    from streamlit import config

    config.get_config_options()
    assert config.get_option("server.address") == "127.0.0.1"


# -- scope: nothing Phase 7 must not contain ----------------------------

FORBIDDEN_IMPORTS = (
    "sqlite3", "sqlalchemy", "psycopg2", "pymongo", "redis",
    "openai", "anthropic", "langchain", "transformers",
    "telegram", "telethon", "discord", "smtplib",
    "alpaca_trade_api", "ib_insync", "ccxt", "robin_stocks",
    "schedule", "apscheduler", "celery", "croniter",
    "subprocess", "socket", "http.server", "flask", "fastapi",
    "keyring", "boto3", "paramiko",
)


#: The one file in these two layers permitted to import a model vendor, and the
#: one vendor it may import.
#:
#: Phase 11A Stage F1. Stage D's adapter refuses to construct a client -- it
#: receives one already built, holds no credential and reads nothing from the
#: process -- and Stage E refuses to know a vendor exists at all. Something has
#: to compose the two, and this is the file that does it. The permission is
#: written as data rather than as an ``if`` so that adding a second one is an
#: edit somebody has to make and defend, and so the test below can insist the
#: permission is actually being exercised: an exemption nobody uses is a hole
#: nobody is watching.
VENDOR_EXEMPTIONS = {"reasoning_composition.py": frozenset({"anthropic"})}


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_imports_nothing_out_of_scope(path):
    names = imported_modules(path)
    exempt = VENDOR_EXEMPTIONS.get(path.name, frozenset())
    for forbidden in FORBIDDEN_IMPORTS:
        if forbidden in exempt:
            continue
        assert not imports_package(names, forbidden), (
            f"{path.relative_to(REPO)} imports {forbidden}"
        )


def test_the_vendor_exemption_is_exercised_rather_than_merely_granted():
    """A permission nobody uses is a hole nobody is watching.

    If the composition module stops importing the SDK -- because the vendor
    moved, or because the file was emptied and left behind -- the exemption must
    be deleted rather than left standing as a quiet allowance for whatever is
    written in that file next.
    """
    for name, vendors in VENDOR_EXEMPTIONS.items():
        matches = [path for path in APPLICATION_FILES if path.name == name]
        assert matches, f"{name} is exempted but does not exist"
        for path in matches:
            names = imported_modules(path)
            for vendor in vendors:
                assert imports_package(names, vendor), (
                    f"{name} is exempted for {vendor} but no longer imports it; "
                    "delete the exemption rather than leaving it open"
                )


def test_exactly_two_production_files_import_the_model_vendor():
    """Swept across the whole of ``src``, not only the Phase 7 layers.

    Stage D permitted one importer, Stage F1 makes it two, and the split of
    responsibility is the point: the adapter owns the provider, the composition
    module owns the client. A third importer would mean something had started
    reaching the vendor without going through either, which is how a
    provider-neutral contract quietly becomes one provider plus paperwork.
    """
    importers = sorted(
        path.relative_to(SRC).as_posix()
        for path in python_files("src")
        if imports_package(imported_modules(path), "anthropic")
    )
    assert importers == [
        "application/reasoning_composition.py",
        "reasoning/anthropic_adapter.py",
    ], importers


#: Constructors that open a session with a vendor and read a credential to do it.
VENDOR_CLIENT_CONSTRUCTORS = frozenset({
    "Anthropic", "AsyncAnthropic", "AnthropicBedrock", "AnthropicVertex",
    "AnthropicAWS", "AnthropicFoundry", "OpenAI", "AsyncOpenAI",
})


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_only_the_composition_module_constructs_a_vendor_client(path):
    """The *call*, not the import.

    ``src/application/reasoning.py`` is the one this matters most for: Stage E
    is provider-neutral by construction, and a ``client or Anthropic()`` default
    appearing there would reintroduce both the credential and the vendor into
    the module whose whole value is not having either. Its own suite says so
    too; this states it generically, so a *new* application file cannot acquire
    the capability without failing here.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    constructed = {
        getattr(node.func, "id", getattr(node.func, "attr", ""))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    } & VENDOR_CLIENT_CONSTRUCTORS
    if path.name == "reasoning_composition.py":
        assert constructed == {"Anthropic"}, (
            "the composition module no longer builds the client it exists to build"
        )
        return
    assert not constructed, f"{path.name} constructs {constructed}"


# -- who may read the reasoning environment -----------------------------

#: Read by the composition module and by nothing else in these two layers.
REASONING_ENVIRONMENT_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")

#: The one file permitted to read them, and to reach ``os.environ`` at all from
#: the Phase 7 layers. Scoped deliberately: ``src/news/config.py`` and
#: ``src/data/providers/alpaca.py`` read the environment too, legitimately, from
#: the domain packages this rule does not cover.
ENVIRONMENT_EXEMPTIONS = frozenset({"reasoning_composition.py"})


def string_constants(path: pathlib.Path) -> set[str]:
    """String *literals*, not identifiers.

    ``src/application/__init__.py`` re-exports ``ANTHROPIC_API_KEY_VAR`` and
    names it in ``__all__``; that is the constant's name travelling, not the
    variable being read. Matching on equality against literals keeps the two
    apart, where a substring search over raw text would report the package
    ``__init__`` as an environment reader.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


@pytest.mark.parametrize("variable", REASONING_ENVIRONMENT_VARS)
def test_one_file_owns_each_reasoning_environment_variable(variable):
    readers = sorted(
        path.name
        for path in DASHBOARD_FILES + APPLICATION_FILES
        if variable in string_constants(path)
    )
    assert readers == ["reasoning_composition.py"], (
        f"{variable} is named in {readers}; exactly one file may own it"
    )


@pytest.mark.parametrize("variable", REASONING_ENVIRONMENT_VARS)
def test_the_environment_exemption_is_exercised(variable):
    """Asserted as used, for the same reason the vendor exemption is."""
    owner = SRC / "application" / "reasoning_composition.py"
    assert variable in string_constants(owner)


def reaches_process_environment(path: pathlib.Path) -> bool:
    """Whether this file reads the *process* environment.

    Deliberately narrow. ``src/application/news.py`` takes an ``environ``
    mapping as a parameter and passes it along -- that is injection, and it is
    the pattern this repository wants -- so a rule that flagged the bare name
    ``environ`` would report the well-behaved file and teach the next author to
    stop injecting. What is detected here is ``os.environ`` and ``os.getenv``
    specifically: the ambient source that cannot be substituted in a test.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in {"environ", "getenv"}:
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "os":
            return True
    return False


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_only_the_composition_module_reaches_the_process_environment(path):
    """No second source, hidden or otherwise.

    ``dotenv`` is refused alongside it, because a loader would put a *file*
    behind the same variable names and make "read from the environment" quietly
    untrue -- the injected mapping would stop being the whole story.
    """
    names = imported_modules(path)
    assert not imports_package(names, "dotenv"), f"{path.name} imports dotenv"
    if path.name in ENVIRONMENT_EXEMPTIONS:
        assert reaches_process_environment(path), (
            f"{path.name} is exempted but no longer reads the environment"
        )
        return
    assert not reaches_process_environment(path), (
        f"{path.name} reads the process environment directly"
    )


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_calls_no_dynamic_execution(path):
    """AST-aware: the *call*, not the word appearing in prose."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "eval",
                "exec",
                "compile",
                "__import__",
            }, f"{path.name} calls {node.func.id}()"


#: Filesystem primitives, matched on the method name alone. Nothing in this
#: repository legitimately names a domain method any of these, so a match here
#: is a real touch of the filesystem whatever the receiver is.
FILE_PRIMITIVES = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "to_csv", "read_csv", "unlink", "mkdir", "rmdir", "touch",
})

#: Modules whose ``load``/``dump`` really are serialization I/O. These verbs are
#: matched **only** when qualified by one of these names, because ``load`` and
#: ``dump`` are also ordinary abstraction verbs -- ``CheckpointStore.load()``
#: reads a domain object through a store, and ``os.remove`` is a real deletion.
IO_MODULES = frozenset({
    "json", "pickle", "marshal", "shelve", "yaml", "toml", "csv", "os", "shutil",
})


@pytest.mark.parametrize("path", DASHBOARD_FILES + APPLICATION_FILES, ids=lambda p: p.name)
def test_phase_seven_opens_no_files(path):
    """Phase 7 reaches the filesystem through no primitive of its own.

    ADR 0005: "Phase 7 opens no files at all." The dashboard and the application
    layer are a read-through view -- they hold no state on disk and never reach
    around a storage abstraction to touch the filesystem directly.

    What is checked is the *primitive*, not the verb. An earlier version failed
    any attribute call named ``load``, which flagged ``self._checkpoints.load()``
    -- a domain object read through a store -- as file I/O, while missing
    ``Path.read_bytes`` entirely. It also let Phase 8's ``NewsStore`` persistence
    through purely because its methods are named ``write_document`` rather than
    ``dump``, so it was enforcing a naming convention rather than the boundary.

    Storage *abstractions* (``CheckpointStore``, ``FeedStore``, ``NewsStore``)
    are the approved route and are deliberately not flagged: later phases are
    allowed to persist, through those, from their own layers. What no file here
    may do is open, read or write one itself.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in FILE_PRIMITIVES:
            pytest.fail(f"{path.name} calls {node.func.id}()")
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in FILE_PRIMITIVES:
                pytest.fail(f"{path.name} performs file I/O via .{node.func.attr}()")
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in IO_MODULES:
                pytest.fail(
                    f"{path.name} performs file I/O via "
                    f"{receiver.id}.{node.func.attr}()"
                )


def test_phase_seven_never_touches_the_csv_bar_store():
    """CsvBarStore is explicitly out of scope for V1."""
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        text = path.read_text()
        assert "CsvBarStore" not in text
        assert "src.data.storage" not in text


def test_the_dashboard_offers_no_unsettled_bar_control():
    for path in DASHBOARD_FILES:
        assert "include_unsettled" not in path.read_text()


def test_the_application_only_ever_requests_settled_bars():
    text = (SRC / "application" / "snapshot.py").read_text()
    assert "include_unsettled=False" in text
    assert "include_unsettled=True" not in text


def test_the_dashboard_offers_no_price_basis_toggle():
    for path in DASHBOARD_FILES:
        text = path.read_text()
        assert "SPLIT_AND_DIVIDEND_ADJUSTED" not in text
        assert "PriceBasis" not in text


# -- the snapshot is the only cache -------------------------------------


def test_nothing_caches_a_derived_value_independently():
    """No memoisation may outlive the snapshot it was derived from.

    A cached assessment or feature series could survive a Refresh that replaced
    the bars, which is precisely the "fresh bars beside a stale assessment"
    state ``ResearchSnapshot`` exists to make unrepresentable. The snapshot is
    the only thing held between runs.
    """
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            assert name not in {
                "cache_data", "cache_resource", "cache", "lru_cache", "memoize"
            }, f"{path.name} memoises a derived value ({name})"


def test_the_dashboard_holds_only_whole_snapshots_between_runs():
    """Session state carries the snapshot itself, not pieces of one."""
    tree = ast.parse((SRC / "dashboard" / "app.py").read_text())
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(
                    target.value, ast.Name
                ) and target.value.id == "state":
                    assigned.add(target.attr)
    # Whole objects only: no observations, features or assessment stored apart.
    # The news_* keys are Phase 8 additions and are whole objects too:
    # news_snapshot is a complete NewsSnapshot, news_service an application
    # dependency, news_failure a complete classified failure.
    # The feed_* keys are the Phase 9 equivalents and hold the same three shapes:
    # feed_snapshot is one whole coherent FeedSnapshot, feed_service the
    # application dependency, feed_failure a complete classified failure string.
    # Listed individually, never by prefix: a key such as feed_items or
    # feed_documents would be fragmented state and must still fail here.
    # The scan_* keys are the Phase 10 additions and hold the same whole shapes:
    # scan_snapshot is one complete MarketScanSnapshot, scan_universes a whole
    # UniverseConfiguration, scan_failure a complete classified failure string,
    # scan_universe_id the selected universe identity and
    # pending_research_symbol a one-shot navigation handoff. Listed
    # individually for the same reason: scan_results, scan_counters or
    # scan_progress would be pieces of a snapshot and must still fail here.
    # The reasoning_* keys are the Phase 11A Stage F2 additions and hold the
    # same three shapes again: reasoning_service is the composed
    # ReasoningService dependency, retained for the session; reasoning_snapshot
    # one whole trusted ReasoningSnapshot; reasoning_failure one whole safe
    # ReasoningFailureView. Listed individually for the same reason: a key such
    # as reasoning_claims, reasoning_response or reasoning_request would be a
    # piece of a result -- or worse, an unvalidated one -- and must still fail.
    assert assigned <= {
        "snapshot", "failure", "paper", "paper_error", "provider", "clock",
        "news_snapshot", "news_service", "news_failure",
        "feed_snapshot", "feed_service", "feed_failure",
        "scan_snapshot", "scan_failure", "scan_universes",
        "scan_universe_id", "pending_research_symbol",
        "reasoning_service", "reasoning_snapshot", "reasoning_failure",
    }
    for forbidden in ("observations", "assessment", "features", "series"):
        assert forbidden not in assigned
    # Nothing that could carry a credential, a client or an untrusted answer
    # is held between runs under any name.
    for fragment in ("client", "api_key", "credential", "raw_response",
                     "request", "packet", "exception", "payload"):
        assert not [key for key in assigned if fragment in key], fragment


# -- Phase 11A Stage F2: how the dashboard may reach reasoning ----------
#
# The dashboard consumes reasoning through ``src.application`` and nothing
# else. It receives a composed service, asks it two questions, and renders what
# comes back through a view model. Every pipeline step in between -- packet,
# request, provider call, validation -- has exactly one owner in Stage E, and
# the rules below make sure the interface never grows a second copy of any of
# them.

APP = SRC / "dashboard" / "app.py"
REASONING_VIEW = SRC / "dashboard" / "reasoning_view.py"

#: Names through which the reasoning pipeline could be driven directly.
REASONING_PIPELINE_NAMES = frozenset({
    "EvidencePacket", "ReasoningRequest", "build_packet",
    "validate_provider_response", "ReasoningProvider", "generate",
    "ProviderReasoningResponse", "AnthropicReasoningProvider",
    "evidence_fingerprint", "reasoning_fingerprint",
})


def parsed(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def calls_in(tree: ast.AST, method: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
    ]


def enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    """Every node mapped to the name of the function that contains it.

    Takes the tree rather than the path: node identity is per parse, so the
    caller must ask about the same tree it found the node in.
    """
    owner: dict[ast.AST, str] = {}

    def visit(node: ast.AST, current: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = node.name
        owner[node] = current
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree, "<module>")
    return owner


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_the_dashboard_never_drives_the_reasoning_pipeline_directly(path):
    """Checked on used identifiers, so a docstring naming a step is not a call."""
    offenders = code_identifiers(path) & REASONING_PIPELINE_NAMES
    assert not offenders, f"{path.name} reaches the reasoning pipeline: {offenders}"


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_the_dashboard_never_calls_generate(path):
    """The provider is asked by Stage E and by nothing in the interface."""
    assert not calls_in(parsed(path), "generate"), f"{path.name} calls .generate()"


def test_exactly_one_production_call_site_asks_for_an_explanation():
    """One ``.explain(...)`` in the whole dashboard, and it is inside the action.

    Proved on the AST rather than by counting text: the call must belong to the
    function the button branch dispatches to, so a second call site -- in a
    render pass, in ``refresh``, at module level -- fails here by name.
    """
    sites = [
        (path.name, tree, call)
        for path in DASHBOARD_FILES
        for tree in [parsed(path)]
        for call in calls_in(tree, "explain")
    ]
    assert len(sites) == 1, [name for name, _, _ in sites]
    name, tree, call = sites[0]
    assert name == "app.py"
    assert enclosing_functions(tree)[call] == "explain_with_ai"


def test_the_explanation_action_is_dispatched_only_from_the_button_branch():
    """``explain_with_ai`` is called once, inside ``if st.button(...)``.

    Walks up from the call to the ``If`` that contains it and requires that
    test to be the ``Explain with AI`` button, so the action cannot be moved to
    load, to a rerun, to ``refresh`` or into a render pass.
    """
    tree = parsed(APP)
    links = _parents(tree)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "explain_with_ai"
    ]
    assert len(calls) == 1, "explain_with_ai must be dispatched from one place"
    current: ast.AST | None = calls[0]
    gated_by_button = False
    rechecks_eligibility = False
    while current is not None:
        parent = links.get(current)
        if isinstance(parent, ast.If) and current is not parent.test:
            test = parent.test
            # The branch re-checks the service's answer rather than trusting
            # the widget's disabled flag alone -- the same belt and braces the
            # scan control uses with its universe.
            if isinstance(test, ast.Name) and test.id == "eligible":
                rechecks_eligibility = True
            if (
                isinstance(test, ast.Call)
                and isinstance(test.func, ast.Attribute)
                and test.func.attr == "button"
                and any(
                    kw.arg == "key"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "explain_with_ai_button"
                    for kw in test.keywords
                )
            ):
                gated_by_button = True
        current = parent
    assert gated_by_button, "explain_with_ai is reachable without the button"
    assert rechecks_eligibility, "the branch must re-check availability itself"
    assert enclosing_functions(tree)[calls[0]] == "render_reasoning_section"


def test_no_reasoning_call_happens_in_refresh_or_at_module_level():
    tree = parsed(APP)
    owner = enclosing_functions(tree)
    for method in ("explain", "availability"):
        for call in calls_in(tree, method):
            assert owner[call] not in {"<module>", "refresh", "main", "init_session",
                                       "render_controls", "scan_market",
                                       "refresh_news", "refresh_feeds"}, method


def test_the_explanation_action_catches_only_reasoning_failures():
    """No ``except Exception`` and no bare ``except`` around the provider call.

    A broad handler would turn a programming error into a "provider failure"
    on screen, which is a bug wearing an outage's costume. The three
    application-facing failure types are the whole vocabulary.
    """
    tree = ast.parse(APP.read_text(), filename=str(APP))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "explain_with_ai"
    )
    handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)]
    assert handlers, "the action must catch the reasoning failures"
    caught: set[str] = set()
    for handler in handlers:
        assert handler.type is not None, "bare except in explain_with_ai"
        names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        for name in names:
            assert isinstance(name, ast.Name), ast.dump(name)
            caught.add(name.id)
    assert caught == {
        "ReasoningProviderError", "ReasoningValidationError", "ReasoningUnavailable",
    }, caught


def test_the_action_stores_only_the_mapped_failure_view():
    """The exception is mapped, never assigned. ``exc`` reaches one call only."""
    tree = ast.parse(APP.read_text(), filename=str(APP))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "explain_with_ai"
    )
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for inner in ast.walk(node.value):
                if isinstance(inner, ast.Name) and inner.id == "exc":
                    assert (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "reasoning_failure_view"
                    ), "the exception object must not be stored"
    for node in ast.walk(function):
        assert not isinstance(node, ast.Attribute) or node.attr != "detail", (
            "explain_with_ai reads the error detail"
        )
    for path in DASHBOARD_FILES:
        assert "exception" not in {
            node.func.attr for node in ast.walk(parsed(path))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }, f"{path.name} calls st.exception()"


def test_the_reasoning_path_never_reads_a_failure_detail():
    """``.detail`` is not read anywhere an error could be the receiver.

    ``FailureReport.detail`` (the Phase 7 refresh failure) and the scanner and
    feed row details are legitimately rendered from view models elsewhere in
    the dashboard; the functions and module that handle reasoning read none.
    """
    tree = parsed(APP)
    owner = enclosing_functions(tree)
    reasoning_functions = {"explain_with_ai", "render_reasoning_section",
                           "reasoning_service"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "detail":
            assert owner[node] not in reasoning_functions, owner[node]
    assert "detail" not in code_identifiers(REASONING_VIEW)
    # The mapper itself: no attribute named detail and no str(error), checked
    # on its body so its docstring may say "detail is never read" and mean it.
    view_models = parsed(SRC / "application" / "view_models.py")
    mapper = next(
        node for node in ast.walk(view_models)
        if isinstance(node, ast.FunctionDef) and node.name == "reasoning_failure_view"
    )
    for node in ast.walk(mapper):
        assert not (isinstance(node, ast.Attribute) and node.attr == "detail")
        assert not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and any(isinstance(a, ast.Name) and a.id == "error" for a in node.args)
        )


def test_the_reasoning_view_only_draws():
    """No button, no service, no session state, no environment, no domain."""
    tree = ast.parse(REASONING_VIEW.read_text(), filename=str(REASONING_VIEW))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("button", "form", "form_submit_button", "download_button",
                      "explain", "availability", "generate", "rerun"):
        assert forbidden not in called, f"reasoning_view calls .{forbidden}()"
    used = code_identifiers(REASONING_VIEW)
    for forbidden in ("session_state", "ReasoningService", "build_reasoning_service",
                      "describe_reasoning_configuration", "environ", "getenv",
                      "ReasoningSnapshot", "snapshot", "assessment"):
        assert forbidden not in used, f"reasoning_view uses {forbidden}"
    for name in imported_modules(REASONING_VIEW):
        root = name.split(".")[0]
        if root == "src":
            assert name == "src.application.view_models", name
        else:
            assert root in {"__future__", "streamlit"}, name


def test_the_reasoning_view_cannot_touch_paper_or_scanner_state():
    text = REASONING_VIEW.read_text()
    for forbidden in ("PaperSession", "open_long", "close_position", "portfolio",
                      "MarketScanner", "scan_snapshot", "news_snapshot",
                      "feed_snapshot"):
        assert forbidden not in text


def test_no_paper_action_depends_on_a_reasoning_value():
    """An explanation may not gate, feed or prefill a paper action."""
    reasoning_names = {
        "reasoning_snapshot", "reasoning_failure", "reasoning_service",
        "ReasoningExplanationView", "ReasoningFailureView", "explanation",
        "explained", "retained",
    }
    for path in DASHBOARD_FILES + APPLICATION_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        links = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if called not in MUTATOR_NAMES | {"render_open_form", "render_close_form"}:
                continue
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                for inner in ast.walk(argument):
                    if isinstance(inner, ast.Name):
                        assert inner.id not in reasoning_names, (
                            f"{path.name}: {called}() receives {inner.id!r}"
                        )
                    if isinstance(inner, ast.Attribute):
                        assert inner.attr not in reasoning_names, (
                            f"{path.name}: {called}() reads {inner.attr!r}"
                        )
            current: ast.AST | None = node
            while current is not None:
                parent = links.get(current)
                if isinstance(parent, (ast.If, ast.IfExp)) and current is not parent.test:
                    for inner in ast.walk(parent.test):
                        name = getattr(inner, "id", getattr(inner, "attr", ""))
                        assert name not in reasoning_names, (
                            f"{path.name}: {called}() is conditional on {name!r}"
                        )
                current = parent


def test_the_scanner_and_feeds_never_see_a_reasoning_name():
    """No AI column, score or per-row explanation, and no feed/news reasoning."""
    for name in ("scanner_view.py", "news_view.py", "feeds_view.py", "paper_view.py"):
        used = code_identifiers(SRC / "dashboard" / name)
        for forbidden in ("reasoning_service", "reasoning_snapshot", "explain",
                          "ReasoningService", "render_reasoning",
                          "reasoning_explanation_view"):
            assert forbidden not in used, f"{name} uses {forbidden}"
    for name in ("scanner.py", "news.py", "feeds.py", "paper.py"):
        used = code_identifiers(SRC / "application" / name)
        assert "ReasoningService" not in used, name
        assert "explain" not in used, name


def test_the_research_scanner_panel_passes_no_snapshot_to_reasoning():
    """Exactly one ``availability`` call, and it receives the research snapshot."""
    tree = parsed(APP)
    calls = calls_in(tree, "availability")
    assert len(calls) == 1
    (call,) = calls
    assert [ast.unparse(a) for a in call.args] == ["snapshot"]
    assert enclosing_functions(tree)[call] == "render_reasoning_section"


def test_the_explanation_scope_is_one_research_snapshot():
    """``explain`` is passed the one research snapshot and nothing else."""
    (call,) = calls_in(parsed(APP), "explain")
    assert [ast.unparse(a) for a in call.args] == ["snapshot"]
    assert not call.keywords


def test_the_dashboard_has_no_reasoning_loop_retry_or_fallback():
    tree = parsed(APP)
    owner = enclosing_functions(tree)
    for node in ast.walk(tree):
        if owner.get(node) in {"explain_with_ai", "render_reasoning_section",
                               "reasoning_service"}:
            assert not isinstance(node, (ast.For, ast.While, ast.AsyncFunctionDef,
                                         ast.Await, ast.Try)) or (
                isinstance(node, ast.Try) and owner[node] == "explain_with_ai"
            ), f"{type(node).__name__} in {owner[node]}"
    for path in DASHBOARD_FILES:
        used = code_identifiers(path)
        for forbidden in ("retry", "fallback", "sleep", "Thread", "run_in_executor",
                          "create_task", "logging", "getLogger", "cache_data",
                          "cache_resource", "lru_cache"):
            assert forbidden not in used, f"{path.name} uses {forbidden}"


def test_the_privacy_disclosure_is_rendered_with_the_action():
    """The disclosure and the button live in the same function, and the
    disclosure is unconditional: it is written before any branch."""
    tree = ast.parse(APP.read_text(), filename=str(APP))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "render_reasoning_section"
    )
    top_level_calls = [
        ast.unparse(statement.value)
        for statement in function.body
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    ]
    assert "st.caption(REASONING_PRIVACY_NOTE)" in top_level_calls
    first_branch = next(
        i for i, statement in enumerate(function.body) if isinstance(statement, ast.If)
    )
    disclosure_at = next(
        i for i, statement in enumerate(function.body)
        if isinstance(statement, ast.Expr)
        and ast.unparse(statement.value) == "st.caption(REASONING_PRIVACY_NOTE)"
    )
    assert disclosure_at < first_branch


def test_no_dashboard_or_view_model_claims_nothing_leaves_the_machine():
    for path in DASHBOARD_FILES + [SRC / "application" / "view_models.py"]:
        text = path.read_text().lower()
        for phrase in ("no data leaves", "nothing leaves your", "never leaves your",
                       "stays on your machine", "does not leave your"):
            assert phrase not in text, f"{path.name}: {phrase!r}"
