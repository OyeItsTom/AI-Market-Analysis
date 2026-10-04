"""FUTURE_VALIDATION_V1 architecture and level boundaries, enforced statically.

* the definition module is the pre-registration alone: no project import, no I/O;
* only ``src/future_validation/store.py`` touches files;
* only ``_level_three_evidence`` reads a research state or a forward return,
  it has one call site, and that call happens only after the unlock is written;
* the status path and the stop rule name no Level-3 field;
* nothing new reaches a network, a vendor module or the outcome writers.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests.future_validation_fixtures import future_validation_firewall  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
DEFINITION = SRC / "research" / "future_validation.py"
ENGINE = SRC / "research" / "future_validation_engine.py"
APPLICATION = SRC / "application" / "future_validation.py"
CLI = SRC / "cli" / "future_validation.py"
PACKAGE = SRC / "future_validation"
PACKAGE_FILES = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
NEW_MODULES = [DEFINITION, ENGINE, APPLICATION, CLI, *PACKAGE_FILES]


def tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported(path: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def function(path: pathlib.Path, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


def attributes(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def called(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            out.append(n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
    return out


LEVEL_THREE = {"state", "reason_codes", "forward_return", "reference_price", "future_price",
               "reference_timestamp", "future_timestamp", "open", "high", "low", "close",
               "volume", "outcome_value"}


def test_the_store_package_has_exactly_its_modules():
    assert [p.name for p in PACKAGE_FILES] == ["__init__.py", "store.py"]


def test_the_definition_is_the_pre_registration_alone():
    """M2B binds this file: it must not depend on runner or engine code."""
    roots = {name.split(".")[0] for name in imported(DEFINITION)}
    assert roots <= {"__future__", "hashlib", "json", "dataclasses", "typing"}, roots
    assert not [n for n in imported(DEFINITION) if n.startswith("src")]


@pytest.mark.parametrize("path", [DEFINITION, ENGINE, APPLICATION, CLI],
                         ids=lambda p: p.relative_to(SRC).as_posix())
def test_only_the_store_imports_file_or_process_modules(path):
    """``pathlib`` is allowed in the runner for type hints only: the Phase 7 rule
    (``test_phase_seven_opens_no_files``) already forbids every file primitive there."""
    roots = {name.split(".")[0] for name in imported(path)}
    forbidden = {"os", "shutil", "tempfile", "pathlib", "fcntl", "subprocess", "io", "stat"}
    if path == APPLICATION:
        forbidden.discard("pathlib")
    assert not roots & forbidden, path.name


def test_the_store_imports_only_what_it_needs():
    project = {n for n in imported(PACKAGE / "store.py") if n.startswith("src")}
    assert project == {"src.prospective.provenance", "src.prospective.store"}


def test_nothing_new_reaches_a_network_or_vendor_module():
    for path in NEW_MODULES:
        roots = {name.split(".")[0] for name in imported(path)}
        assert not roots & {"socket", "urllib", "requests", "http", "yfinance", "anthropic",
                            "streamlit", "pandas", "numpy"}, path.name
        assert "default_provider" not in path.read_text(), path.name


def test_the_runner_reads_the_ledger_and_never_writes_it():
    taken = {alias.name for node in ast.walk(tree(APPLICATION))
             if isinstance(node, ast.ImportFrom) and node.module == "src.outcomes"
             for alias in node.names}
    assert taken == {"LedgerCorruption", "LedgerPartition"}
    calls = called(tree(APPLICATION))
    for forbidden in ("refresh_outcomes", "register_artifact", "append_outcome",
                      "evaluate_artifact", "measure_forward", "collect", "activate"):
        assert forbidden not in calls, forbidden


def test_only_one_function_reads_level_three_fields():
    module = tree(APPLICATION)
    readers = sorted(
        node.name for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef) and attributes(node) & LEVEL_THREE
    )
    assert readers == ["_level_three_evidence"]


def test_level_three_is_read_once_and_only_after_the_unlock_is_written():
    module = tree(APPLICATION)
    sites = [node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
             and "_level_three_evidence" in called(node)]
    assert sites == ["_derive_result"]
    callers = sorted(node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
                     and "_derive_result" in called(node))
    assert callers == ["_from_unlock", "run"]
    run = ast.get_source_segment(APPLICATION.read_text(), function(APPLICATION, "run"))
    assert run.index("write_once(UNLOCK_NAME") < run.index("_derive_result(")
    reopen = ast.get_source_segment(APPLICATION.read_text(),
                                    function(APPLICATION, "_from_unlock"))
    assert reopen.index("_decode_unlock(") < reopen.index("_derive_result(")


@pytest.mark.parametrize("name", ["status", "_status_from", "_level_one_evidence",
                                  "_claim_stamp", "_outcome_stamp", "_capture_locked",
                                  "_unlock_payload", "definition_mismatches"])
def test_the_status_path_names_no_level_three_field(name):
    assert not attributes(function(APPLICATION, name)) & LEVEL_THREE, name


def test_the_gate_names_no_level_three_field():
    module = tree(APPLICATION)
    gate = next(n for n in ast.walk(module) if isinstance(n, ast.ClassDef) and n.name == "_Frozen")
    method = next(n for n in gate.body if isinstance(n, ast.FunctionDef) and n.name == "gate")
    assert not attributes(method) & LEVEL_THREE
    assert "_level_three_evidence" not in called(method)


@pytest.mark.parametrize("name", ["population_claims", "matured_artifact_keys", "evidence_through",
                                  "matured_claim_counts", "cutoffs", "evaluate_stop_rule",
                                  "is_reserved", "add_calendar_months", "months_elapsed"])
def test_the_stop_rule_names_no_level_three_field(name):
    assert not attributes(function(ENGINE, name)) & LEVEL_THREE, name


def test_no_clock_reaches_the_gate_or_status():
    """B1: the host clock is read in exactly one place, for unlock metadata."""
    module = tree(APPLICATION)
    gate = next(n for n in ast.walk(module) if isinstance(n, ast.ClassDef) and n.name == "_Frozen")
    method = next(n for n in gate.body if isinstance(n, ast.FunctionDef) and n.name == "gate")
    assert [a.arg for a in method.args.args] == ["self", "definition", "pinned_fingerprint"]
    status = function(APPLICATION, "status")
    assert "now" not in {a.arg for a in status.args.kwonlyargs}
    users = sorted(n.name for n in ast.walk(module) if isinstance(n, ast.FunctionDef)
                   and "now" in called(n))
    assert users == ["_utc_now", "run"]  # the default clock itself, and its one caller
    run = ast.get_source_segment(APPLICATION.read_text(), function(APPLICATION, "run"))
    assert run.count("now()") == 1 and "_unlock_payload(definition, gate, snapshot, now()" in run
    for name in ("evaluate_stop_rule", "evidence_through", "cutoffs", "matured_claim_counts"):
        source = ast.get_source_segment(ENGINE.read_text(), function(ENGINE, name))
        assert "now" not in source.replace("know", "")


def test_no_numeric_threshold_other_than_the_frozen_ones_appears_in_new_code():
    for path in NEW_MODULES:
        floats = [n.value for n in ast.walk(tree(path))
                  if isinstance(n, ast.Constant) and isinstance(n.value, float)]
        allowed = {float("inf"), float("-inf"), 0.0}
        literals = [v for v in floats if v not in allowed]
        if path == DEFINITION:  # only the Phase R reference literals
            from src.research.future_validation import REFERENCES

            # a negative literal is a unary minus applied to its absolute value
            expected = {abs(getattr(r, name)) for r in REFERENCES for name in (
                "bullish_mean", "bullish_median", "matched_mean", "matched_median",
                "mean_delta", "median_delta")}
            assert set(literals) <= expected
        else:
            assert not literals, (path.name, literals)


def test_the_live_root_is_resolved_only_by_the_prospective_application():
    for path in NEW_MODULES:
        text = path.read_text()
        assert "data/prospective" not in text.replace("``data/prospective``", ""), path.name
        assert "DEFAULT_PROSPECTIVE_ROOT" not in text, path.name


def test_the_engine_performs_no_price_arithmetic():
    assert not attributes(tree(ENGINE)) & {"open", "high", "low", "close", "volume",
                                           "reference_price", "future_price"}
