"""Prospective Collection v1 operational records: the activation manifest and run log.

Both are **Level 1** by construction: identities, clocks, counts, timestamps
of bars and status classes. Neither type has a field that could carry a
price, a return, a research state, a reason code or any performance figure,
and their decoders refuse any key outside the declared allowlist, so an
unexpected field on disk is corruption rather than something carried along.

Serialisation is canonical JSON (sorted keys, compact separators, ASCII,
UTC ISO timestamps), one object per manifest file and one per run-log line.
A decoder re-encodes what it read and compares bytes, as the Phase 12 ledger
does: a record is either exactly what this module would write, or refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping

from .definition import DefinitionError, require_aware, validate_commit_sha

MANIFEST_SCHEMA = "prospective_activation_v1"
RUN_SCHEMA = "prospective_run_v1"
RUN_START_SCHEMA = "prospective_run_start_v1"


class RecordError(ValueError):
    """A manifest or run record is malformed, or its bytes are not canonical."""


class CollectionStatus(str, Enum):
    """Operational outcome of one symbol, or of a run refused as a whole.

    None of these is a research result; none is persisted in the outcome
    ledger. A missed bar is not a status of the run that notices it -- it
    is listed in that symbol's ``missed_tails``.
    """

    #: A new current-tail claim was registered; earlier claims were evaluated.
    OK = "ok"
    #: The current tail was already registered; earlier claims were evaluated.
    DUPLICATE_ALREADY_EXISTS = "duplicate_already_exists"
    #: The series is shorter than the warm-up; the existing path registered
    #: claims that are not evaluable (their state is INSUFFICIENT_DATA). A
    #: valid claim, not a gap. Named for the history, not the state, so no
    #: operational value spells a research-state value.
    INSUFFICIENT_HISTORY = "insufficient_history"
    #: The tail settled at or before activation; nothing touched the ledger.
    PRE_ACTIVATION = "pre_activation"
    #: The run (or this symbol) fell outside 00:30-09:00 ET; no provider call.
    OUTSIDE_COLLECTION_WINDOW = "outside_collection_window"
    #: The tail is not the current one (a weekday has passed since it
    #: settled) and was never claimed; claiming it now would be late.
    STALE_TAIL = "stale_tail"
    #: The provider could not be reached or refused the request.
    PROVIDER_FAILURE = "provider_failure"
    #: The snapshot could not be built for a reason other than the provider.
    SNAPSHOT_FAILURE = "snapshot_failure"
    #: The provider returned no settled bars.
    NO_SETTLED_BAR = "no_settled_bar"
    #: A daily bar was not stamped 00:00:00 America/New_York.
    TIMESTAMP_CONVENTION = "timestamp_convention"
    #: The outcome ledger could not be read strictly.
    CORRUPT_LEDGER = "corrupt_ledger"
    #: The outcome refresh raised for any other reason (e.g. a conflict).
    REFRESH_FAILURE = "refresh_failure"
    #: The live configuration or the provider differs from the frozen definition.
    CONFIG_MISMATCH = "config_mismatch"
    #: A defect raised outside every classified stage. Recorded, never hidden.
    UNEXPECTED_FAILURE = "unexpected_failure"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Statuses that mean the symbol completed as designed.
SUCCESS_STATUSES = frozenset({
    CollectionStatus.OK,
    CollectionStatus.DUPLICATE_ALREADY_EXISTS,
    CollectionStatus.INSUFFICIENT_HISTORY,
})


class RunStatus(str, Enum):
    """How a recorded run ended as a whole.

    Only ``COMPLETED`` follows a run-start record and carries symbols. Every
    other value is a refusal recorded before any provider existed; such a
    record has no symbols and wrote nothing to the ledger.
    """

    COMPLETED = "completed"
    OUTSIDE_COLLECTION_WINDOW = "outside_collection_window"
    CONFIG_MISMATCH = "config_mismatch"
    #: The repository HEAD is not the collector commit the manifest records.
    COLLECTOR_COMMIT_MISMATCH = "collector_commit_mismatch"
    #: The collector's working tree has uncommitted or untracked changes.
    DIRTY_COLLECTOR_TREE = "dirty_collector_tree"
    #: The repository could not be inspected, so the collector is unverified.
    COLLECTOR_UNVERIFIED = "collector_unverified"
    #: The existing ledger failed provenance reconciliation.
    PROVENANCE_INVALID = "provenance_invalid"
    #: The existing ledger could not be read strictly, so provenance is unknown.
    PROVENANCE_UNKNOWN = "provenance_unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# -- canonical encoding ---------------------------------------------------------------------


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def encode_time(value: datetime) -> str:
    return require_aware(value, "timestamp").astimezone(timezone.utc).isoformat()


def decode_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RecordError(f"{label} must be an ISO timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RecordError(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise RecordError(f"{label} must carry a timezone")
    return parsed


def _require_keys(payload: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RecordError(f"{label} must be a JSON object")
    keys = set(payload)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise RecordError(f"{label} keys differ from the schema: missing={missing} extra={extra}")
    return payload


def _int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RecordError(f"{label} must be a non-negative integer")
    return value


def _optional_int(value: object, label: str) -> int | None:
    return None if value is None else _int(value, label)


def _str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecordError(f"{label} must be a non-empty string")
    return value


def _str_map(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise RecordError(f"{label} must map strings to strings")
    return dict(value)


def _str_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise RecordError(f"{label} must be a list of non-empty strings")
    return tuple(value)


# -- activation manifest --------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationManifest:
    """The write-once record of the explicitly approved activation."""

    activated_at: datetime
    collection_id: str
    collection_fingerprint: str
    collector_git_commit: str
    m2_preregistration_git_commit: str
    holdout_start: date
    universe: tuple[str, ...]
    interval: str
    basis: str
    provider: str
    hypothesis_fingerprints: Mapping[str, str]
    outcome_spec_fingerprints: tuple[str, ...]
    evaluation_version: int
    dependency_versions: Mapping[str, str]

    FIELDS = frozenset({
        "schema", "activated_at", "collection_id", "collection_fingerprint",
        "collector_git_commit", "m2_preregistration_git_commit", "holdout_start",
        "universe", "interval", "basis", "provider", "hypothesis_fingerprints",
        "outcome_spec_fingerprints", "evaluation_version", "dependency_versions",
    })

    def __post_init__(self) -> None:
        try:
            require_aware(self.activated_at, "activated_at")
            validate_commit_sha(self.collector_git_commit, "collector_git_commit")
            validate_commit_sha(self.m2_preregistration_git_commit,
                                "m2_preregistration_git_commit")
        except DefinitionError as exc:
            raise RecordError(str(exc)) from exc
        object.__setattr__(self, "universe", tuple(self.universe))
        object.__setattr__(self, "outcome_spec_fingerprints",
                           tuple(self.outcome_spec_fingerprints))
        object.__setattr__(self, "hypothesis_fingerprints", dict(self.hypothesis_fingerprints))
        object.__setattr__(self, "dependency_versions", dict(self.dependency_versions))

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "activated_at": encode_time(self.activated_at),
            "collection_id": self.collection_id,
            "collection_fingerprint": self.collection_fingerprint,
            "collector_git_commit": self.collector_git_commit,
            "m2_preregistration_git_commit": self.m2_preregistration_git_commit,
            "holdout_start": self.holdout_start.isoformat(),
            "universe": list(self.universe),
            "interval": self.interval,
            "basis": self.basis,
            "provider": self.provider,
            "hypothesis_fingerprints": dict(self.hypothesis_fingerprints),
            "outcome_spec_fingerprints": list(self.outcome_spec_fingerprints),
            "evaluation_version": self.evaluation_version,
            "dependency_versions": dict(self.dependency_versions),
        }

    def to_bytes(self) -> bytes:
        return (canonical_json(self.to_payload()) + "\n").encode("ascii")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ActivationManifest":
        try:
            payload = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordError("activation manifest is not ASCII JSON") from exc
        payload = _require_keys(payload, cls.FIELDS, "activation manifest")
        if payload["schema"] != MANIFEST_SCHEMA:
            raise RecordError(f"unknown activation manifest schema {payload['schema']!r}")
        try:
            holdout = date.fromisoformat(_str(payload["holdout_start"], "holdout_start"))
        except ValueError as exc:
            raise RecordError("holdout_start is not an ISO date") from exc
        manifest = cls(
            activated_at=decode_time(payload["activated_at"], "activated_at"),
            collection_id=_str(payload["collection_id"], "collection_id"),
            collection_fingerprint=_str(payload["collection_fingerprint"],
                                        "collection_fingerprint"),
            collector_git_commit=_str(payload["collector_git_commit"], "collector_git_commit"),
            m2_preregistration_git_commit=_str(payload["m2_preregistration_git_commit"],
                                               "m2_preregistration_git_commit"),
            holdout_start=holdout,
            universe=_str_tuple(payload["universe"], "universe"),
            interval=_str(payload["interval"], "interval"),
            basis=_str(payload["basis"], "basis"),
            provider=_str(payload["provider"], "provider"),
            hypothesis_fingerprints=_str_map(payload["hypothesis_fingerprints"],
                                             "hypothesis_fingerprints"),
            outcome_spec_fingerprints=_str_tuple(payload["outcome_spec_fingerprints"],
                                                 "outcome_spec_fingerprints"),
            evaluation_version=_int(payload["evaluation_version"], "evaluation_version"),
            dependency_versions=_str_map(payload["dependency_versions"], "dependency_versions"),
        )
        if manifest.to_bytes() != raw:
            raise RecordError("activation manifest bytes are not canonical")
        return manifest


# -- run log --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolRun:
    """What one collection run did for one symbol. Level-1 fields only."""

    symbol: str
    status: CollectionStatus
    stage: str
    error_class: str | None = None
    built_at: datetime | None = None
    tail: datetime | None = None
    bars: int | None = None
    artifacts_new: int | None = None
    artifacts_duplicate: int | None = None
    outcomes_new: int | None = None
    outcomes_present: int | None = None
    pending: int | None = None
    ineligible: int | None = None
    refused: int | None = None
    out_of_window: int | None = None
    missed_tails: tuple[datetime, ...] = field(default_factory=tuple)

    FIELDS = frozenset({
        "symbol", "status", "stage", "error_class", "built_at", "tail", "bars",
        "artifacts_new", "artifacts_duplicate", "outcomes_new", "outcomes_present",
        "pending", "ineligible", "refused", "out_of_window", "missed_tails",
    })
    COUNTS = ("bars", "artifacts_new", "artifacts_duplicate", "outcomes_new",
              "outcomes_present", "pending", "ineligible", "refused", "out_of_window")
    STAGES = frozenset({"window", "snapshot", "validation", "activation", "ledger",
                        "outcomes", "done"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CollectionStatus(self.status))
        if self.stage not in self.STAGES:
            raise RecordError(f"unknown stage {self.stage!r}")
        for name in self.COUNTS:
            _optional_int(getattr(self, name), name)
        object.__setattr__(self, "missed_tails", tuple(self.missed_tails))
        for value in (self.built_at, self.tail, *self.missed_tails):
            if value is not None:
                require_aware(value, "timestamp")

    @property
    def succeeded(self) -> bool:
        return self.status in SUCCESS_STATUSES

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "status": self.status.value,
            "stage": self.stage,
            "error_class": self.error_class,
            "built_at": None if self.built_at is None else encode_time(self.built_at),
            "tail": None if self.tail is None else encode_time(self.tail),
            "missed_tails": [encode_time(value) for value in self.missed_tails],
        }
        for name in self.COUNTS:
            payload[name] = getattr(self, name)
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> "SymbolRun":
        payload = _require_keys(payload, cls.FIELDS, "symbol run")
        try:
            status = CollectionStatus(payload["status"])
        except ValueError as exc:
            raise RecordError(f"unknown collection status {payload['status']!r}") from exc
        error_class = payload["error_class"]
        if error_class is not None:
            error_class = _str(error_class, "error_class")
        missed = payload["missed_tails"]
        if not isinstance(missed, list):
            raise RecordError("missed_tails must be a list")
        return cls(
            symbol=_str(payload["symbol"], "symbol"),
            status=status,
            stage=_str(payload["stage"], "stage"),
            error_class=error_class,
            built_at=None if payload["built_at"] is None
            else decode_time(payload["built_at"], "built_at"),
            tail=None if payload["tail"] is None else decode_time(payload["tail"], "tail"),
            missed_tails=tuple(decode_time(value, "missed_tails") for value in missed),
            **{name: _optional_int(payload[name], name) for name in cls.COUNTS},
        )


@dataclass(frozen=True)
class RunRecord:
    """One attempted collection run against an activated root."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    run_status: RunStatus
    collection_fingerprint: str
    activated_at: datetime
    collector_git_commit: str
    universe: tuple[str, ...]
    symbols: tuple[SymbolRun, ...]

    FIELDS = frozenset({
        "schema", "run_id", "started_at", "finished_at", "run_status",
        "collection_fingerprint", "activated_at", "collector_git_commit", "universe",
        "symbols_attempted", "symbols_ok", "symbols_failed", "symbols_pre_activation",
        "symbols",
    })

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_status", RunStatus(self.run_status))
        object.__setattr__(self, "universe", tuple(self.universe))
        object.__setattr__(self, "symbols", tuple(self.symbols))
        for value in (self.started_at, self.finished_at, self.activated_at):
            require_aware(value, "timestamp")
        _str(self.run_id, "run_id")

    @property
    def symbols_attempted(self) -> int:
        return len(self.symbols)

    @property
    def symbols_ok(self) -> int:
        return sum(1 for entry in self.symbols if entry.succeeded)

    @property
    def symbols_pre_activation(self) -> int:
        return sum(1 for entry in self.symbols
                   if entry.status is CollectionStatus.PRE_ACTIVATION)

    @property
    def symbols_failed(self) -> int:
        return self.symbols_attempted - self.symbols_ok - self.symbols_pre_activation

    @property
    def succeeded(self) -> bool:
        return self.run_status is RunStatus.COMPLETED and self.symbols_failed == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": RUN_SCHEMA,
            "run_id": self.run_id,
            "started_at": encode_time(self.started_at),
            "finished_at": encode_time(self.finished_at),
            "run_status": self.run_status.value,
            "collection_fingerprint": self.collection_fingerprint,
            "activated_at": encode_time(self.activated_at),
            "collector_git_commit": self.collector_git_commit,
            "universe": list(self.universe),
            "symbols_attempted": self.symbols_attempted,
            "symbols_ok": self.symbols_ok,
            "symbols_failed": self.symbols_failed,
            "symbols_pre_activation": self.symbols_pre_activation,
            "symbols": [entry.to_payload() for entry in self.symbols],
        }

    def to_line(self) -> bytes:
        return (canonical_json(self.to_payload()) + "\n").encode("ascii")

    @classmethod
    def from_line(cls, raw: bytes) -> "RunRecord":
        """Decode one line *without* its terminating newline."""
        try:
            payload = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordError("run record is not ASCII JSON") from exc
        payload = _require_keys(payload, cls.FIELDS, "run record")
        if payload["schema"] != RUN_SCHEMA:
            raise RecordError(f"unknown run record schema {payload['schema']!r}")
        symbols = payload["symbols"]
        if not isinstance(symbols, list):
            raise RecordError("symbols must be a list")
        try:
            run_status = RunStatus(payload["run_status"])
        except ValueError as exc:
            raise RecordError(f"unknown run status {payload['run_status']!r}") from exc
        record = cls(
            run_id=_str(payload["run_id"], "run_id"),
            started_at=decode_time(payload["started_at"], "started_at"),
            finished_at=decode_time(payload["finished_at"], "finished_at"),
            run_status=run_status,
            collection_fingerprint=_str(payload["collection_fingerprint"],
                                        "collection_fingerprint"),
            activated_at=decode_time(payload["activated_at"], "activated_at"),
            collector_git_commit=_str(payload["collector_git_commit"], "collector_git_commit"),
            universe=_str_tuple(payload["universe"], "universe"),
            symbols=tuple(SymbolRun.from_payload(entry) for entry in symbols),
        )
        if record.to_line() != raw + b"\n":
            raise RecordError("run record bytes are not canonical")
        return record


@dataclass(frozen=True)
class RunStart:
    """The durable intent of one collection run, written before any provider exists.

    Appended (and fsynced) under the exclusive lock after every identity,
    configuration, integrity and provenance check has passed. The completed
    :class:`RunRecord` reuses its ``run_id``. A start with no completed record
    is an interrupted run: evidence that ledger writes stamped inside its
    interval may come from the supported collector, never a licence for them
    (see :mod:`src.prospective.provenance`). It carries identities and a
    clock only -- nothing a run could have learnt.
    """

    run_id: str
    started_at: datetime
    collection_fingerprint: str
    provenance_policy_fingerprint: str
    activated_at: datetime
    collector_git_commit: str
    universe: tuple[str, ...]

    FIELDS = frozenset({
        "schema", "run_id", "started_at", "collection_fingerprint",
        "provenance_policy_fingerprint", "activated_at", "collector_git_commit", "universe",
    })

    def __post_init__(self) -> None:
        object.__setattr__(self, "universe", tuple(self.universe))
        for value in (self.started_at, self.activated_at):
            require_aware(value, "timestamp")
        _str(self.run_id, "run_id")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": RUN_START_SCHEMA,
            "run_id": self.run_id,
            "started_at": encode_time(self.started_at),
            "collection_fingerprint": self.collection_fingerprint,
            "provenance_policy_fingerprint": self.provenance_policy_fingerprint,
            "activated_at": encode_time(self.activated_at),
            "collector_git_commit": self.collector_git_commit,
            "universe": list(self.universe),
        }

    def to_line(self) -> bytes:
        return (canonical_json(self.to_payload()) + "\n").encode("ascii")

    @classmethod
    def from_payload(cls, payload: object, raw: bytes) -> "RunStart":
        payload = _require_keys(payload, cls.FIELDS, "run start")
        if payload["schema"] != RUN_START_SCHEMA:
            raise RecordError(f"unknown run start schema {payload['schema']!r}")
        record = cls(
            run_id=_str(payload["run_id"], "run_id"),
            started_at=decode_time(payload["started_at"], "started_at"),
            collection_fingerprint=_str(payload["collection_fingerprint"],
                                        "collection_fingerprint"),
            provenance_policy_fingerprint=_str(payload["provenance_policy_fingerprint"],
                                               "provenance_policy_fingerprint"),
            activated_at=decode_time(payload["activated_at"], "activated_at"),
            collector_git_commit=_str(payload["collector_git_commit"], "collector_git_commit"),
            universe=_str_tuple(payload["universe"], "universe"),
        )
        if record.to_line() != raw + b"\n":
            raise RecordError("run start bytes are not canonical")
        return record


def decode_run_log_line(raw: bytes) -> "RunStart | RunRecord":
    """One run-log line (without its newline): a :class:`RunStart` or a :class:`RunRecord`."""
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordError("run log line is not ASCII JSON") from exc
    if isinstance(payload, dict) and payload.get("schema") == RUN_START_SCHEMA:
        return RunStart.from_payload(payload, raw)
    return RunRecord.from_line(raw)


__all__ = [
    "MANIFEST_SCHEMA",
    "RUN_SCHEMA",
    "RUN_START_SCHEMA",
    "RecordError",
    "CollectionStatus",
    "SUCCESS_STATUSES",
    "RunStatus",
    "ActivationManifest",
    "SymbolRun",
    "RunRecord",
    "RunStart",
    "decode_run_log_line",
    "canonical_json",
]
