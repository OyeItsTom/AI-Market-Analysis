"""Append-only local JSONL ledger of tracked artifacts and outcomes.

    <root>/<SYMBOL>/<interval>/<basis>/artifacts.jsonl    one line per artifact
    <root>/<SYMBOL>/<interval>/<basis>/outcomes.jsonl     one line per outcome

One directory per :class:`~src.outcomes.ports.LedgerPartition`, basis
included. Phase 1 already keeps raw and adjusted bars in separate files;
the ledger keeps raw and adjusted *claims* in separate directories for the
same reason -- a reader opening one basis can never be handed the other,
and a person inspecting a file sees one context, not a mixture to filter.

What a line is
--------------
One complete JSON object, compact, sorted keys, ASCII-escaped, newline
terminated -- the same canonical form the project's identities are hashed
over, so a line's bytes are a function of the record and nothing else.
Every line carries ``schema_version`` (owned here, never by the domain
models) and an explicit ``record_type``, even though the two record types
live in separate files: the file name is routing, the line is authority.
Floats are written in JSON's shortest round-trip form and read back to the
same ``float`` bit for bit; this is what lets an
:class:`~src.outcomes.models.OutcomeRecord` whose ``forward_return`` must
equal ``future_price / reference_price - 1`` *exactly* be reconstructed
without failing its own invariant. Timestamps are UTC ISO-8601 with an
explicit offset; identity is over the instant and so is storage.

An outcome line embeds its artifact whole. That is deliberate duplication:
an outcome read back is self-contained, its keys are recomputed from its
own bytes, and no join with the artifact file is needed to trust it.

What a read checks
------------------
Every line is decoded into a domain record (which enforces the domain's
own invariants), re-encoded, and compared with what was on disk: a line
that is not the canonical encoding of the record it describes -- an extra
field, a non-UTC timestamp, a naive one -- is corruption. The stored
``artifact_key`` and ``outcome_key`` are then compared with the keys the
reconstructed records compute for themselves; a mismatch is corruption.
A line whose market context is not the partition it sits in is corruption.
Two lines under one key are corruption whether or not they agree: the
writer is idempotent and never produces them, so their presence means a
manual edit or a broken writer, and both deserve a loud stop. A final line
without its newline is a torn append and is corruption too. Nothing is
skipped, truncated, repaired or rewritten; the bytes stay as evidence.

Durability, precisely
---------------------
A successful write is one ``write`` of one complete line followed by
``flush`` and ``fsync``. That is durable enough for a local research
ledger and it is all that is claimed: it is not transactional across the
two files, and an artifact registration and an outcome append are two
separate facts that become durable separately.

Threat model
------------
Path *inputs* (symbol, interval, basis) are untrusted and are refused, never
rewritten, if they could name a location outside the root or a different
location from the one they spell. The *filesystem* under the root is
trusted: this is a local, single-user research directory, and no symlink
hardening (``O_NOFOLLOW``, ``openat``) is attempted. A file where a
directory belongs, or a directory where a file belongs, is reported rather
than read as empty.

Concurrency
-----------
**One local process, one writer.** No lock is taken and none is implied;
two ledgers appending to one partition at once have no defined result.
Every operation re-reads the partition it touches and rebuilds its key
index in memory. That is O(lines) per call, which at this project's scale
(thousands of lines per partition, not millions) is milliseconds, and it
means the index can never be stale with respect to the file. There is no
persistent index and no cache.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from .identity import OutcomeTrackingError, canonical_timestamp, require_key
from .models import (
    ArtifactKind,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
    TrackedArtifact,
)
from .ports import (
    ArtifactMismatchError,
    LedgerCorruption,
    LedgerError,
    LedgerPartition,
    UnregisteredArtifactError,
    UnsupportedSchemaError,
    WriteResult,
    WriteStatus,
)

#: Bumped when the meaning or shape of a stored line changes. A reader
#: refuses any other version rather than interpreting unfamiliar bytes as
#: current. Owned by the persistence layer; the domain records carry none.
SCHEMA_VERSION = 1

ARTIFACTS_FILE = "artifacts.jsonl"
OUTCOMES_FILE = "outcomes.jsonl"

RECORD_TYPE_ARTIFACT = "artifact"
RECORD_TYPE_OUTCOME = "outcome"


# -- serialization -----------------------------------------------------------------------


class _DecodeError(ValueError):
    """A line's content cannot be read as the record it claims to be. Internal;
    the reader turns it into a located :class:`LedgerCorruption`."""


class _UnsupportedSchema(_DecodeError):
    """Internal twin of :class:`UnsupportedSchemaError`, located by the reader."""


def _stamp(value: datetime, label: str) -> str:
    return canonical_timestamp(value, label)


def _parse_stamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise _DecodeError(f"{label} must be an ISO-8601 string, got {type(value).__name__}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _DecodeError(f"{label} is not an ISO-8601 timestamp: {value!r}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _DecodeError(f"{label} {value!r} is naive; stored timestamps carry an offset")
    return parsed


def _refuse_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json.loads`` keeps the *last* of two equal keys and says nothing. A
    ledger line with two spellings of one field is ambiguous, not a record."""
    row: dict[str, Any] = {}
    for name, value in pairs:
        if name in row:
            raise _DecodeError(f"duplicate JSON key {name!r}")
        row[name] = value
    return row


def _refuse_constant(token: str) -> Any:
    """``NaN``/``Infinity`` are not JSON; the writer never emits them
    (``allow_nan=False``) and the reader does not accept them either."""
    raise _DecodeError(f"non-finite JSON constant {token!r}")


def _parse_line(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_refuse_duplicate_keys,
                      parse_constant=_refuse_constant)


def _field(row: Mapping[str, Any], name: str, kind: type | tuple[type, ...]) -> Any:
    if name not in row:
        raise _DecodeError(f"missing field {name!r}")
    value = row[name]
    if isinstance(value, bool) or not isinstance(value, kind):
        expected = kind.__name__ if isinstance(kind, type) else "/".join(k.__name__ for k in kind)
        raise _DecodeError(f"field {name!r} must be {expected}, got {type(value).__name__}")
    return value


def _artifact_body(artifact: TrackedArtifact) -> dict[str, Any]:
    """The artifact as stored, without the line-level envelope."""
    body: dict[str, Any] = {
        "artifact_key": artifact.artifact_key,
        "kind": artifact.kind.value,
        "symbol": artifact.symbol,
        "interval": artifact.interval.value,
        "basis": artifact.basis.value,
        "timestamp": _stamp(artifact.timestamp, "timestamp"),
        "state": artifact.state.value,
        "reason_codes": [code.value for code in artifact.reason_codes],
        "source": artifact.source,
        "data_cutoff": _stamp(artifact.data_cutoff, "data_cutoff"),
        "recorded_at": _stamp(artifact.recorded_at, "recorded_at"),
        "observation_bar_fingerprint": artifact.observation_bar_fingerprint,
        "origin": artifact.origin.value,
    }
    if isinstance(artifact, ObservationArtifact):
        body["hypothesis_id"] = artifact.hypothesis_id
        body["hypothesis_version"] = artifact.hypothesis_version
        body["hypothesis_fingerprint"] = artifact.hypothesis_fingerprint
    elif isinstance(artifact, AssessmentArtifact):
        body["policy_fingerprint"] = artifact.policy_fingerprint
    else:  # pragma: no cover - the base class is not constructible
        raise OutcomeTrackingError(f"unknown artifact type {type(artifact).__name__}")
    return body


def _artifact_from_body(body: Mapping[str, Any]) -> TrackedArtifact:
    """Reconstruct, then verify the stored key against the record's own.

    Enum-valued fields are handed to the domain as their stored strings;
    the domain constructors coerce each into its *own* vocabulary
    (``ResearchState`` for an observation, ``AssessmentState`` for an
    assessment) and refuse anything else, so the two vocabularies cannot
    be collapsed here by accident.
    """
    if not isinstance(body, Mapping):
        raise _DecodeError(f"artifact must be a JSON object, got {type(body).__name__}")
    kind_value = _field(body, "kind", str)
    try:
        kind = ArtifactKind(kind_value)
    except ValueError:
        raise _DecodeError(f"unknown artifact kind {kind_value!r}") from None

    reason_codes = _field(body, "reason_codes", list)
    if not all(isinstance(code, str) for code in reason_codes):
        raise _DecodeError("field 'reason_codes' must be a list of strings")
    common = dict(
        symbol=_field(body, "symbol", str),
        interval=_field(body, "interval", str),
        basis=_field(body, "basis", str),
        timestamp=_parse_stamp(_field(body, "timestamp", str), "timestamp"),
        state=_field(body, "state", str),
        reason_codes=tuple(reason_codes),
        source=_field(body, "source", str),
        data_cutoff=_parse_stamp(_field(body, "data_cutoff", str), "data_cutoff"),
        recorded_at=_parse_stamp(_field(body, "recorded_at", str), "recorded_at"),
        observation_bar_fingerprint=_field(body, "observation_bar_fingerprint", str),
        origin=_field(body, "origin", str),
    )
    try:
        if kind is ArtifactKind.OBSERVATION:
            artifact: TrackedArtifact = ObservationArtifact(
                **common,
                hypothesis_id=_field(body, "hypothesis_id", str),
                hypothesis_version=_field(body, "hypothesis_version", int),
                hypothesis_fingerprint=_field(body, "hypothesis_fingerprint", str),
            )
        else:
            artifact = AssessmentArtifact(
                **common, policy_fingerprint=_field(body, "policy_fingerprint", str)
            )
    except OutcomeTrackingError as exc:
        raise _DecodeError(f"malformed artifact: {exc}") from None

    stored_key = _field(body, "artifact_key", str)
    if stored_key != artifact.artifact_key:
        raise _DecodeError(
            f"stored artifact_key {stored_key!r} does not match the key the artifact "
            f"computes for itself, {artifact.artifact_key!r}"
        )
    _require_canonical(body, _artifact_body(artifact), "artifact")
    return artifact


def _artifact_row(artifact: TrackedArtifact) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE_ARTIFACT,
        **_artifact_body(artifact),
    }


def _outcome_row(outcome: OutcomeRecord) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE_OUTCOME,
        "outcome_key": outcome.outcome_key,
        "artifact_key": outcome.artifact_key,
        "artifact": _artifact_body(outcome.artifact),
        "spec_fingerprint": outcome.spec_fingerprint,
        "horizon_bars": outcome.horizon_bars,
        "evaluation_version": outcome.evaluation_version,
        "evaluated_at": _stamp(outcome.evaluated_at, "evaluated_at"),
        "consumed_bars_fingerprint": outcome.consumed_bars_fingerprint,
        "reference_timestamp": _stamp(outcome.reference_timestamp, "reference_timestamp"),
        "reference_price": outcome.reference_price,
        "future_timestamp": _stamp(outcome.future_timestamp, "future_timestamp"),
        "future_price": outcome.future_price,
        "forward_return": outcome.forward_return,
    }


def _check_envelope(row: Mapping[str, Any], record_type: str) -> None:
    if "schema_version" not in row:
        raise _DecodeError("missing field 'schema_version'")
    version = row["schema_version"]
    # ``type`` rather than ``isinstance``/``==``: ``True == 1`` and
    # ``1.0 == 1`` in Python, and neither is the integer this writer stores.
    if type(version) is not int or version != SCHEMA_VERSION:
        raise _UnsupportedSchema(
            f"line declares schema_version {version!r}, but this build understands "
            f"only {SCHEMA_VERSION}; refusing to reinterpret it"
        )
    stored_type = _field(row, "record_type", str)
    if stored_type != record_type:
        raise _DecodeError(f"record_type is {stored_type!r}, expected {record_type!r}")


def _artifact_from_row(row: Mapping[str, Any]) -> TrackedArtifact:
    _check_envelope(row, RECORD_TYPE_ARTIFACT)
    body = {name: value for name, value in row.items()
            if name not in ("schema_version", "record_type")}
    return _artifact_from_body(body)


def _outcome_from_row(row: Mapping[str, Any]) -> OutcomeRecord:
    _check_envelope(row, RECORD_TYPE_OUTCOME)
    artifact = _artifact_from_body(_field(row, "artifact", dict))
    try:
        outcome = OutcomeRecord(
            artifact=artifact,
            spec_fingerprint=_field(row, "spec_fingerprint", str),
            horizon_bars=_field(row, "horizon_bars", int),
            evaluation_version=_field(row, "evaluation_version", int),
            evaluated_at=_parse_stamp(_field(row, "evaluated_at", str), "evaluated_at"),
            consumed_bars_fingerprint=_field(row, "consumed_bars_fingerprint", str),
            reference_timestamp=_parse_stamp(
                _field(row, "reference_timestamp", str), "reference_timestamp"),
            reference_price=_field(row, "reference_price", float),
            future_timestamp=_parse_stamp(_field(row, "future_timestamp", str), "future_timestamp"),
            future_price=_field(row, "future_price", float),
            forward_return=_field(row, "forward_return", float),
        )
    except OutcomeTrackingError as exc:
        raise _DecodeError(f"malformed outcome: {exc}") from None

    stored_artifact_key = _field(row, "artifact_key", str)
    if stored_artifact_key != outcome.artifact_key:
        raise _DecodeError(
            f"stored artifact_key {stored_artifact_key!r} does not match the embedded "
            f"artifact's key {outcome.artifact_key!r}"
        )
    stored_key = _field(row, "outcome_key", str)
    if stored_key != outcome.outcome_key:
        raise _DecodeError(
            f"stored outcome_key {stored_key!r} does not match the key the outcome "
            f"computes for itself, {outcome.outcome_key!r}"
        )
    _require_canonical(row, _outcome_row(outcome), "outcome")
    return outcome


def _require_canonical(stored: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    """The line must be exactly the encoding this writer would produce.

    Compared as parsed values, not bytes, so key order and whitespace do
    not matter (they are fixed on write anyway); but an unknown field, a
    missing one, a non-UTC or otherwise non-canonical timestamp string, or
    a value that changed under reconstruction all differ, and each one
    means the line was not written by this writer as it stands. Number
    *types* are checked before this point: a price spelt ``100`` where the
    writer would have spelt ``100.0`` is refused as the wrong type.
    """
    if stored == expected:
        return
    differing = sorted(
        name for name in set(stored) | set(expected)
        if name not in stored or name not in expected or stored[name] != expected[name]
    )
    raise _DecodeError(
        f"{label} line is not the canonical encoding of the record it describes; "
        f"differing fields: {', '.join(differing)}"
    )


def _differing_fields(stored: Mapping[str, Any], offered: Mapping[str, Any]) -> str:
    return ", ".join(sorted(name for name in set(stored) | set(offered)
                            if stored.get(name) != offered.get(name)))


def _encode_line(row: Mapping[str, Any]) -> bytes:
    """One complete line: compact, sorted keys, ASCII only, newline terminated.

    ``ensure_ascii=True`` also escapes every control character, so a value
    containing a newline can never split a record across two lines.
    """
    text = json.dumps(row, separators=(",", ":"), ensure_ascii=True, sort_keys=True,
                      allow_nan=False)
    if "\n" in text or "\r" in text:  # pragma: no cover - ensure_ascii escapes them
        raise OutcomeTrackingError("serialized record contains a newline")
    return text.encode("ascii") + b"\n"


# -- paths --------------------------------------------------------------------------


def _safe_component(value: str, label: str) -> str:
    """Refuse anything that could escape the root or be misread as another
    location. Never rewrites: a symbol is identity, and identity is not
    sanitised into something else."""
    if (
        not value
        or value in (".", "..")
        or value != value.strip()
        or any(character in value for character in ("/", "\\", "\0"))
        or ".." in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise OutcomeTrackingError(f"unsafe path component for {label}: {value!r}")
    return value


# -- the ledger -----------------------------------------------------------------------


class JsonlOutcomeLedger:
    """An :class:`~src.outcomes.ports.OutcomeLedger` over one root directory.

    ``root`` is injected and nothing else is consulted: no default location,
    no environment variable, no working-directory lookup. The application
    stage decides where a ledger lives.
    """

    def __init__(self, root: str | Path) -> None:
        if not isinstance(root, (str, Path)) or not str(root):
            raise OutcomeTrackingError(f"root must be a non-empty path, got {root!r}")
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    # -- paths ---------------------------------------------------------------

    def partition_dir(self, partition: LedgerPartition) -> Path:
        partition = _require_partition(partition)
        return self._root.joinpath(
            _safe_component(partition.symbol, "symbol"),
            _safe_component(partition.interval.value, "interval"),
            _safe_component(partition.basis.value, "basis"),
        )

    def artifacts_path(self, partition: LedgerPartition) -> Path:
        return self.partition_dir(partition).joinpath(ARTIFACTS_FILE)

    def outcomes_path(self, partition: LedgerPartition) -> Path:
        return self.partition_dir(partition).joinpath(OUTCOMES_FILE)

    # -- reading ---------------------------------------------------------------

    def iter_artifacts(self, partition: LedgerPartition) -> Iterator[TrackedArtifact]:
        return iter(tuple(entry.record for entry in self._artifacts(partition).values()))

    def iter_outcomes(self, partition: LedgerPartition) -> Iterator[OutcomeRecord]:
        return iter(tuple(entry.record for entry in self._outcomes(partition).values()))

    def get_artifact(self, partition: LedgerPartition, key: str) -> TrackedArtifact | None:
        entry = self._artifacts(partition).get(require_key(key, "key"))
        return None if entry is None else entry.record

    def get_outcome(self, partition: LedgerPartition, key: str) -> OutcomeRecord | None:
        entry = self._outcomes(partition).get(require_key(key, "key"))
        return None if entry is None else entry.record

    def contains_artifact(self, partition: LedgerPartition, key: str) -> bool:
        return require_key(key, "key") in self._artifacts(partition)

    def contains_outcome(self, partition: LedgerPartition, key: str) -> bool:
        return require_key(key, "key") in self._outcomes(partition)

    # -- writing ---------------------------------------------------------------

    def register_artifact(self, artifact: TrackedArtifact) -> WriteResult:
        if not isinstance(artifact, TrackedArtifact):
            raise OutcomeTrackingError(
                f"artifact must be a TrackedArtifact, got {type(artifact).__name__}"
            )
        partition = LedgerPartition.of_artifact(artifact)
        key = artifact.artifact_key
        row = _artifact_row(artifact)
        # The partition is read in full first, so a damaged file stops the
        # write rather than receiving another line on top of unreadable bytes.
        held = self._artifacts(partition).get(key)
        if held is not None:
            return _compare(key, held.row, row)
        self._append(self.artifacts_path(partition), row)
        return WriteResult(WriteStatus.WRITTEN, key)

    def append_outcome(self, outcome: OutcomeRecord) -> WriteResult:
        if not isinstance(outcome, OutcomeRecord):
            raise OutcomeTrackingError(
                f"outcome must be an OutcomeRecord, got {type(outcome).__name__}"
            )
        partition = LedgerPartition.of_outcome(outcome)
        key = outcome.outcome_key
        row = _outcome_row(outcome)

        registered = self._artifacts(partition).get(outcome.artifact_key)
        if registered is None:
            raise UnregisteredArtifactError(artifact_key=outcome.artifact_key, outcome_key=key)
        if registered.row != _artifact_row(outcome.artifact):
            raise ArtifactMismatchError(
                artifact_key=outcome.artifact_key, outcome_key=key,
                detail=_differing_fields(registered.row, _artifact_row(outcome.artifact)),
            )

        held = self._outcomes(partition).get(key)
        if held is not None:
            return _compare(key, held.row, row)
        self._append(self.outcomes_path(partition), row)
        return WriteResult(WriteStatus.WRITTEN, key)

    # -- internals ---------------------------------------------------------------

    def _artifacts(self, partition: LedgerPartition) -> dict[str, _Entry]:
        partition = _require_partition(partition)
        return _load(self._root, self.artifacts_path(partition), partition, _artifact_from_row,
                     lambda record: record.artifact_key, lambda record: record)

    def _outcomes(self, partition: LedgerPartition) -> dict[str, _Entry]:
        partition = _require_partition(partition)
        return _load(self._root, self.outcomes_path(partition), partition, _outcome_from_row,
                     lambda record: record.outcome_key, lambda record: record.artifact)

    @staticmethod
    def _append(path: Path, row: Mapping[str, Any]) -> None:
        """Append one complete line, then flush and fsync.

        Encoding happens before the file is opened, so an encoding failure
        appends nothing and creates nothing. The single ``write`` hands the
        whole line to a blocking buffered writer, which either accepts every
        byte or raises; ``flush`` and ``fsync`` then push it to the disk.

        What is and is not claimed: if this returns, the line is durable
        under ordinary filesystem semantics. If ``flush`` or ``fsync``
        raises, the exception propagates and **the line may or may not be
        on disk** -- the caller must not assume either; the next read of the
        partition is what decides (a torn line is corruption, a complete one
        is a record). No transaction spans the two files.
        """
        line = _encode_line(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class _Entry:
    """One held record, the exact row it was read from (so a write can be
    compared against what is on disk without re-encoding) and where it sits."""

    __slots__ = ("row", "record", "line_number")

    def __init__(self, row: dict[str, Any], record: Any, line_number: int) -> None:
        self.row = row
        self.record = record
        self.line_number = line_number


def _require_partition(partition: object) -> LedgerPartition:
    if not isinstance(partition, LedgerPartition):
        raise OutcomeTrackingError(
            f"partition must be a LedgerPartition, got {type(partition).__name__}"
        )
    return partition


def _compare(key: str, held: Mapping[str, Any], offered: Mapping[str, Any]) -> WriteResult:
    if held == offered:
        return WriteResult(WriteStatus.DUPLICATE, key)
    return WriteResult(
        WriteStatus.CONFLICT, key,
        f"a different record is already held under this key; differing fields: "
        f"{_differing_fields(held, offered)}",
    )


def _require_routable(root: Path, path: Path) -> None:
    """A missing file is an empty ledger; a file where a directory should be,
    or a directory where the file should be, is neither and must not read
    as empty. Checked from the root down so the first wrong thing is named."""
    for ancestor in reversed([parent for parent in path.parents
                              if parent == root or root in parent.parents]):
        if ancestor.exists() and not ancestor.is_dir():
            raise LedgerError(f"{ancestor} exists and is not a directory; the ledger "
                              "cannot be routed through it")
    if path.exists() and not path.is_file():
        raise LedgerError(f"{path} exists and is not a regular file")


def _load(root: Path, path: Path, partition: LedgerPartition, decode, key_of, artifact_of,
          ) -> dict[str, _Entry]:
    """Parse one file into ``{key: entry}`` in file order, refusing damage.

    A missing file is an empty ledger; nothing is created. Every line is
    checked in turn: UTF-8, JSON object, envelope, domain reconstruction,
    canonical form, stored keys, partition membership, key uniqueness. The
    first failure raises with the file, line and byte offset.
    """
    _require_routable(root, path)
    if not path.exists():
        return {}
    data = path.read_bytes()
    if not data:
        return {}

    def corrupt(line_number: int, offset: int, reason: str) -> LedgerCorruption:
        return LedgerCorruption(path=str(path), line_number=line_number,
                               byte_offset=offset, reason=reason)

    entries: dict[str, _Entry] = {}
    raw_lines = data.split(b"\n")
    # A newline-terminated file splits into N records plus one empty tail.
    # Anything else in the tail is a line whose append never completed.
    tail = raw_lines.pop()
    offset = 0
    for line_number, raw in enumerate(raw_lines, start=1):
        line_offset = offset
        offset += len(raw) + 1
        if not raw.strip():
            raise corrupt(line_number, line_offset, "blank line; the writer never produces one")
        try:
            row = _parse_line(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise corrupt(line_number, line_offset, f"invalid UTF-8: {exc}") from None
        except _DecodeError as exc:
            raise corrupt(line_number, line_offset, str(exc)) from None
        except ValueError as exc:
            raise corrupt(line_number, line_offset, f"invalid JSON: {exc}") from None
        if not isinstance(row, dict):
            raise corrupt(line_number, line_offset, "line is not a JSON object")
        try:
            record = decode(row)
        except _UnsupportedSchema as exc:
            raise UnsupportedSchemaError(path=str(path), line_number=line_number,
                                         byte_offset=line_offset, reason=str(exc)) from None
        except _DecodeError as exc:
            raise corrupt(line_number, line_offset, str(exc)) from None
        if not partition.contains(artifact_of(record)):
            raise corrupt(
                line_number, line_offset,
                f"record belongs to {LedgerPartition.of_artifact(artifact_of(record)).label}, "
                f"not to this partition {partition.label}",
            )
        key = key_of(record)
        if key in entries:
            same = entries[key].row == row
            raise corrupt(
                line_number, line_offset,
                f"key {key} already appears on line {entries[key].line_number}; "
                + ("an identical repeated line, which the idempotent writer never produces"
                   if same else "a different record under the same key"),
            )
        entries[key] = _Entry(row, record, line_number)
    if tail:
        raise corrupt(len(raw_lines) + 1, offset,
                      "final line is not newline-terminated; the append did not complete")
    return entries


__all__ = [
    "SCHEMA_VERSION",
    "ARTIFACTS_FILE",
    "OUTCOMES_FILE",
    "RECORD_TYPE_ARTIFACT",
    "RECORD_TYPE_OUTCOME",
    "JsonlOutcomeLedger",
]
