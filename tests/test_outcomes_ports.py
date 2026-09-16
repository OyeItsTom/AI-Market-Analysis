"""Phase 12C: the persistence port -- protocols, statuses, partitions, errors.

The port is pure: it names what a ledger means without touching a file.
These tests pin the shape (which methods, which arguments, which of them
write) against the real adapter's signatures, because the project's
protocols are deliberately not ``runtime_checkable``.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import typing

import pytest

from src.data.models import Interval
from src.data.series import PriceBasis
from src.outcomes import (
    ArtifactMismatchError,
    JsonlOutcomeLedger,
    LedgerCorruption,
    LedgerError,
    LedgerPartition,
    OutcomeLedger,
    OutcomeReader,
    OutcomeTrackingError,
    UnregisteredArtifactError,
    UnsupportedSchemaError,
    WriteResult,
    WriteStatus,
)
from src.outcomes import ports

from test_outcomes_models import asmt_artifact, obs_artifact, record

KEY = "c" * 64
PORTS = pathlib.Path(ports.__file__)

READ_METHODS = {
    "iter_artifacts": ("self", "partition"),
    "iter_outcomes": ("self", "partition"),
    "get_artifact": ("self", "partition", "key"),
    "get_outcome": ("self", "partition", "key"),
    "contains_artifact": ("self", "partition", "key"),
    "contains_outcome": ("self", "partition", "key"),
}
WRITE_METHODS = {
    "register_artifact": ("self", "artifact"),
    "append_outcome": ("self", "outcome"),
}


def protocol_methods(protocol: type) -> set[str]:
    return {
        name for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    }


# -- protocol shape --------------------------------------------------------------------


class TestProtocols:
    def test_reader_has_exactly_the_read_methods_and_no_write(self):
        assert protocol_methods(OutcomeReader) == set(READ_METHODS)
        for name in WRITE_METHODS:
            assert not hasattr(OutcomeReader, name), name

    def test_ledger_adds_exactly_the_two_writes(self):
        assert protocol_methods(OutcomeLedger) == set(WRITE_METHODS)
        assert OutcomeReader in OutcomeLedger.__mro__
        assert typing.Protocol in OutcomeReader.__mro__
        assert typing.Protocol in OutcomeLedger.__mro__

    def test_protocols_are_not_runtime_checkable(self):
        """Project convention: a Protocol ``isinstance`` is a spelling check,
        so the shape is asserted here against real signatures instead."""
        for protocol in (OutcomeReader, OutcomeLedger):
            assert not getattr(protocol, "_is_runtime_protocol", False), protocol.__name__

    @pytest.mark.parametrize("name,params", {**READ_METHODS, **WRITE_METHODS}.items())
    def test_the_adapter_implements_each_method_with_the_protocol_signature(self, name, params):
        owner = OutcomeLedger if name in WRITE_METHODS else OutcomeReader
        declared = tuple(inspect.signature(getattr(owner, name)).parameters)
        implemented = tuple(inspect.signature(getattr(JsonlOutcomeLedger, name)).parameters)
        assert declared == params, (name, declared)
        assert implemented == params, (name, implemented)

    def test_a_reader_view_exposes_no_way_to_write(self):
        """What a future read-only consumer receives has the read surface and
        nothing that mutates, by construction of the protocol."""
        assert not any(
            name for name in protocol_methods(OutcomeReader)
            if name.startswith(("register", "append", "write", "delete", "update", "remove"))
        )


# -- purity of the port module ---------------------------------------------------------


class TestPortsModuleIsPure:
    def test_imports_no_filesystem_io_or_environment_module(self):
        tree = ast.parse(PORTS.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module)
        forbidden = {"os", "io", "pathlib", "json", "tempfile", "shutil", "sqlite3",
                     "pickle", "csv", "logging", "time", "socket", "sys"}
        assert not {n.split(".")[0] for n in names} & forbidden, names

    def test_only_domain_imports(self):
        tree = ast.parse(PORTS.read_text(encoding="utf-8"))
        project = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src")
        }
        assert project <= {"src.data.models", "src.data.series"}, project

    def test_no_open_read_or_write_call(self):
        tree = ast.parse(PORTS.read_text(encoding="utf-8"))
        called = {
            (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None))
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        assert not called & {"open", "read_text", "write_text", "read_bytes", "write_bytes",
                             "mkdir", "fsync", "getenv", "now", "utcnow"}, called


# -- write status and result ----------------------------------------------------------------


class TestWriteResult:
    def test_exactly_three_statuses(self):
        assert {s.value for s in WriteStatus} == {"written", "duplicate", "conflict"}

    def test_result_coerces_status_and_validates_key(self):
        result = WriteResult("written", KEY)
        assert result.status is WriteStatus.WRITTEN
        assert result.written
        assert result.detail == ""
        assert not WriteResult(WriteStatus.DUPLICATE, KEY).written
        assert not WriteResult(WriteStatus.CONFLICT, KEY, "state").written

    def test_result_refuses_unknown_status_bad_key_or_non_text_detail(self):
        with pytest.raises(OutcomeTrackingError, match="write status"):
            WriteResult("updated", KEY)
        with pytest.raises(OutcomeTrackingError, match="key"):
            WriteResult(WriteStatus.WRITTEN, "short")
        with pytest.raises(OutcomeTrackingError, match="detail"):
            WriteResult(WriteStatus.WRITTEN, KEY, detail=None)

    def test_result_is_frozen(self):
        result = WriteResult(WriteStatus.WRITTEN, KEY)
        with pytest.raises(Exception):
            result.status = WriteStatus.CONFLICT  # type: ignore[misc]


# -- partition ---------------------------------------------------------------------------------


class TestLedgerPartition:
    def test_coerces_interval_and_basis_and_keeps_symbol_verbatim(self):
        partition = LedgerPartition("AAPL", "1d", "raw")
        assert partition.interval is Interval.DAY_1
        assert partition.basis is PriceBasis.RAW
        assert partition.symbol == "AAPL"
        assert partition.label == "AAPL/1d/raw"
        assert LedgerPartition(" aapl ", "1d", "raw").symbol == " aapl ", "identity is not rewritten"

    def test_refuses_blank_symbol_unknown_interval_or_basis(self):
        with pytest.raises(OutcomeTrackingError, match="symbol"):
            LedgerPartition("  ", "1d", "raw")
        with pytest.raises(OutcomeTrackingError, match="interval"):
            LedgerPartition("AAPL", "1day", "raw")
        with pytest.raises(OutcomeTrackingError, match="basis"):
            LedgerPartition("AAPL", "1d", "adjusted")

    def test_basis_is_part_of_the_partition(self):
        raw = LedgerPartition("AAPL", Interval.DAY_1, PriceBasis.RAW)
        adjusted = LedgerPartition("AAPL", Interval.DAY_1, PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        assert raw != adjusted
        assert len({raw, adjusted}) == 2

    def test_derived_from_artifact_and_outcome(self):
        artifact = asmt_artifact(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        partition = LedgerPartition.of_artifact(artifact)
        assert partition == LedgerPartition("AAPL", Interval.DAY_1,
                                            PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        assert LedgerPartition.of_outcome(record()) == LedgerPartition.of_artifact(obs_artifact())
        with pytest.raises(OutcomeTrackingError, match="TrackedArtifact"):
            LedgerPartition.of_artifact(record())
        with pytest.raises(OutcomeTrackingError, match="OutcomeRecord"):
            LedgerPartition.of_outcome(obs_artifact())

    def test_contains_is_exact_on_all_three_fields(self):
        partition = LedgerPartition.of_artifact(obs_artifact())
        assert partition.contains(obs_artifact())
        assert partition.contains(asmt_artifact())
        assert not partition.contains(obs_artifact(symbol="MSFT"))
        assert not partition.contains(obs_artifact(interval=Interval.HOUR_1))
        assert not partition.contains(obs_artifact(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        assert not partition.contains(obs_artifact(symbol="aapl")), "case is identity"


# -- errors -----------------------------------------------------------------------------------


class TestErrors:
    def test_hierarchy(self):
        assert issubclass(LedgerError, OutcomeTrackingError)
        assert issubclass(LedgerCorruption, LedgerError)
        assert issubclass(UnsupportedSchemaError, LedgerCorruption)
        assert issubclass(UnregisteredArtifactError, LedgerError)
        assert issubclass(ArtifactMismatchError, LedgerError)
        assert not issubclass(UnregisteredArtifactError, LedgerCorruption)
        assert not issubclass(ArtifactMismatchError, LedgerCorruption)

    def test_corruption_names_file_line_offset_and_reason(self):
        error = LedgerCorruption(path="/x/artifacts.jsonl", line_number=3, byte_offset=412,
                                 reason="invalid JSON")
        assert (error.path, error.line_number, error.byte_offset, error.reason) == (
            "/x/artifacts.jsonl", 3, 412, "invalid JSON")
        assert str(error) == "/x/artifacts.jsonl:3 (byte 412): invalid JSON"

    def test_unregistered_and_mismatch_carry_both_keys(self):
        missing = UnregisteredArtifactError(artifact_key="a" * 64, outcome_key="b" * 64)
        assert missing.artifact_key == "a" * 64 and missing.outcome_key == "b" * 64
        assert "register the artifact first" in str(missing)
        mismatch = ArtifactMismatchError(artifact_key="a" * 64, outcome_key="b" * 64,
                                         detail="state")
        assert mismatch.detail == "state"
        assert "nothing was written" in str(mismatch)
