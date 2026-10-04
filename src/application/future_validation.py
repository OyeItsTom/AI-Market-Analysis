"""FUTURE_VALIDATION_V1 runner: blind status, one explicit run, write-once unlock and result.

    status -> manifest -> shared lock (non-blocking) -> capture the evidence bytes -> unlock
              the lock -> Level-1 projection of a private copy -> identities, provenance,
              evidence clock, stop rule.  Never a state, a reason code, a price or a return.
    run    -> definition identity -> result already written? (re-derive it from its
              unlock's recorded prefixes, require identical bytes, then finish the report)
              -> unlock already written? (complete THAT unlock from its recorded prefixes)
              -- an existing unlock is first rebuilt from those prefixes and must match in
              every field but the informational host_recorded_at and runner_repository
              -> otherwise: the same capture and Level-1 gate as status
              -> unlockable? write unlock.json once -> only now read the Level-3 fields
              -> deterministic result.json once -> report.md once

The research question is :data:`~src.research.future_validation.FUTURE_VALIDATION_V1`
and the computation is :mod:`src.research.future_validation_engine`; this
module only coordinates the collection root, its lock and provenance (all
from Prospective Collection v1, unchanged) with the write-once store in
:mod:`src.future_validation`.

Locking. The capture holds the collection root's lock **shared and
non-blocking**, exactly as ``health`` does: a running collector (exclusive)
makes the capture refuse with ``collect_in_progress``, and a collector that
starts while the capture runs waits its bounded 30 s for the exclusive lock.
Nothing is analysed from the live files: the lock is released as soon as the
bytes are in memory, and everything afterwards reads a private temporary copy
of exactly those bytes, so collection may continue while the validation
computes without being able to change it.

Time. E1 and F run on the evidence clock
(:func:`~src.research.future_validation_engine.evidence_through`), never on the
host wall clock. The host clock is read once per opening, for the unlock's
``host_recorded_at`` metadata, and decides nothing.

Blindness. Only :func:`_level_three_evidence` reads a research state or a
forward return, and it is called from one place, :func:`_derive_result`,
which runs only with unlock.json already on disk.
The status path and the stop rule see :class:`~src.research.future_validation_engine.ClaimStamp`
and :class:`~src.research.future_validation_engine.OutcomeStamp` only.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from src.data.models import Interval
from src.future_validation import (
    MATCH_EXACT,
    MATCH_PREFIX,
    REPORT_NAME,
    RESULT_NAME,
    UNLOCK_NAME,
    ArtifactExists,
    InputSnapshot,
    SnapshotMismatch,
    UnsupportedEntry,
    ValidationArtifacts,
    capture,
    materialize,
    recapture,
)
from src.outcomes import LedgerCorruption, LedgerPartition
from src.prospective import (
    COLLECTION_V1,
    ActivationManifest,
    CollectionDefinition,
    LockMissingError,
    ManifestCorruption,
    ProspectiveStore,
    ProvenanceReport,
    RootLockedError,
    RunLogCorruption,
    RunRecord,
    RunStatus,
    provenance_policy_for,
)
from src.research.future_validation import (
    FUTURE_VALIDATION_V1,
    FUTURE_VALIDATION_V1_FINGERPRINT,
    FutureValidationDefinition,
)
from src.research.future_validation_engine import (
    ClaimStamp,
    FutureValidationError,
    LevelOneEvidence,
    LevelThreeEvidence,
    Measurement,
    Observation,
    OutcomeStamp,
    StopRuleEvaluation,
    build_result,
    canonical_bytes,
    cutoffs,
    decode_canonical,
    evaluate_stop_rule,
    evidence_through,
    matured_claim_counts,
    render_report,
    sha256_hex,
)

from .outcomes import build_outcome_ledger
from .prospective import (
    build_prospective_store,
    evaluate_provenance,
    live_configuration_mismatches,
    manifest_mismatches,
)
from .snapshot import BASIS

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


# -- identity ---------------------------------------------------------------------------------


def definition_mismatches(
    definition: FutureValidationDefinition,
    pinned_fingerprint: str,
    collection: CollectionDefinition,
) -> tuple[str, ...]:
    """Every way the running definition differs from what it must be."""
    found: list[str] = []
    if definition.fingerprint != pinned_fingerprint:
        found.append("validation_fingerprint")
    if definition.collection_id != collection.collection_id \
            or definition.collection_fingerprint != collection.fingerprint:
        found.append("collection_fingerprint")
    policy = provenance_policy_for(collection)
    if definition.provenance_policy_id != policy.policy_id \
            or definition.provenance_policy_fingerprint != policy.fingerprint:
        found.append("provenance_policy_fingerprint")
    if not set(definition.symbols) <= set(collection.universe):
        found.append("universe")
    pins = {(p.hypothesis_id, p.version, p.fingerprint) for p in collection.hypotheses}
    for identity in (definition.primary_hypothesis, *definition.secondary_hypotheses):
        if (identity.hypothesis_id, identity.version, identity.fingerprint) not in pins:
            found.append("hypotheses")
            break
    specs = dict(zip(collection.outcome_horizons, collection.outcome_spec_fingerprints))
    if any(specs.get(h) != fp for h, fp in definition.outcome_spec_fingerprints):
        found.append("outcome_spec_fingerprints")
    if (definition.interval, definition.basis, definition.evaluation_version) != (
            collection.interval, collection.basis, collection.evaluation_version):
        found.append("market_context")
    return tuple(found)


# -- Level-1 and Level-3 projections ----------------------------------------------------------


def _claim_stamp(artifact) -> ClaimStamp:
    """Allowlisted Level-1 metadata of one artifact: identity, bar, producer."""
    if artifact.kind.value == "observation":
        return ClaimStamp(key=artifact.artifact_key, symbol=artifact.symbol,
                          timestamp=artifact.timestamp, hypothesis_id=artifact.hypothesis_id,
                          hypothesis_version=artifact.hypothesis_version,
                          hypothesis_fingerprint=artifact.hypothesis_fingerprint)
    return ClaimStamp(key=artifact.artifact_key, symbol=artifact.symbol,
                      timestamp=artifact.timestamp)


def _outcome_stamp(outcome) -> OutcomeStamp:
    """Allowlisted Level-1 metadata of one outcome: identity and horizon, never a value."""
    return OutcomeStamp(key=outcome.outcome_key, artifact_key=outcome.artifact_key,
                        symbol=outcome.artifact.symbol, horizon_bars=outcome.horizon_bars,
                        spec_fingerprint=outcome.spec_fingerprint,
                        evaluation_version=outcome.evaluation_version)


def _partitions(root: Path, collection: CollectionDefinition):
    ledger = build_outcome_ledger(root)
    interval = Interval.parse(collection.interval)
    for symbol in collection.universe:
        partition = LedgerPartition(symbol=symbol, interval=interval, basis=BASIS)
        if ledger.partition_dir(partition).is_dir():
            yield ledger, partition


def _level_one_evidence(store: ProspectiveStore, manifest: ActivationManifest,
                        run_log, collection: CollectionDefinition,
                        report: ProvenanceReport) -> LevelOneEvidence:
    claims: list[ClaimStamp] = []
    outcomes: list[OutcomeStamp] = []
    for ledger, partition in _partitions(store.ledger_root, collection):
        claims.extend(_claim_stamp(a) for a in ledger.iter_artifacts(partition))
        outcomes.extend(_outcome_stamp(o) for o in ledger.iter_outcomes(partition))
    missed: dict[str, set[datetime]] = {}
    for record in run_log:
        if not isinstance(record, RunRecord):
            continue
        for entry in record.symbols:
            missed.setdefault(entry.symbol, set()).update(entry.missed_tails)
    return LevelOneEvidence(
        activated_at=manifest.activated_at,
        claims=tuple(claims),
        outcomes=tuple(outcomes),
        excluded_artifact_keys=report.excluded_artifact_keys,
        excluded_outcome_keys=report.excluded_outcome_keys,
        missed_sessions={symbol: tuple(sorted(stamps)) for symbol, stamps in missed.items()},
    )


def _level_three_evidence(store: ProspectiveStore, collection: CollectionDefinition,
                          level_one: LevelOneEvidence) -> LevelThreeEvidence:
    """The research states and forward returns. Called only after unlock.json exists."""
    observations: list[Observation] = []
    measurements: list[Measurement] = []
    for ledger, partition in _partitions(store.ledger_root, collection):
        for artifact in ledger.iter_artifacts(partition):
            if artifact.kind.value != "observation":
                continue
            observations.append(Observation(
                key=artifact.artifact_key, symbol=artifact.symbol, timestamp=artifact.timestamp,
                hypothesis_id=artifact.hypothesis_id,
                hypothesis_version=artifact.hypothesis_version,
                hypothesis_fingerprint=artifact.hypothesis_fingerprint,
                state=artifact.state.value))
        for outcome in ledger.iter_outcomes(partition):
            measurements.append(Measurement(
                key=outcome.outcome_key, artifact_key=outcome.artifact_key,
                horizon_bars=outcome.horizon_bars, spec_fingerprint=outcome.spec_fingerprint,
                evaluation_version=outcome.evaluation_version,
                forward_return=outcome.forward_return,
                reference_timestamp=outcome.reference_timestamp,
                future_timestamp=outcome.future_timestamp))
    return LevelThreeEvidence(level_one=level_one, observations=tuple(observations),
                              measurements=tuple(measurements))


# -- the gate ---------------------------------------------------------------------------------

VALIDITY_OK = "ok"
VALIDITY_INVALID = "invalid"
VALIDITY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Gate:
    """Level-1 facts of one frozen snapshot."""

    integrity: str
    identity_mismatches: tuple[str, ...]
    provenance: ProvenanceReport | None = None
    manifest: ActivationManifest | None = None
    level_one: LevelOneEvidence | None = None
    stop: StopRuleEvaluation | None = None
    cutoffs: Mapping[str, datetime | None] | None = None

    @property
    def validity(self) -> str:
        if self.identity_mismatches or self.integrity != "ok":
            return VALIDITY_INVALID
        if self.provenance is None or self.provenance.status == "unknown":
            return VALIDITY_UNKNOWN
        if self.provenance.status == "invalid":
            return VALIDITY_INVALID
        return VALIDITY_OK

    @property
    def unlockable(self) -> bool:
        return self.validity == VALIDITY_OK and self.stop is not None and self.stop.unlockable


class _Frozen:
    """A private copy of one snapshot, opened as a collection root."""

    def __init__(self, root: Path, collection: CollectionDefinition) -> None:
        self.store = ProspectiveStore(root)
        self.collection = collection

    def gate(self, definition: FutureValidationDefinition, pinned_fingerprint: str) -> Gate:
        """Level-1 facts of the frozen bytes. No clock argument exists: E1 and F use the
        evidence clock of the same snapshot."""
        identity = list(definition_mismatches(definition, pinned_fingerprint, self.collection))
        try:
            manifest = self.store.read_manifest()
        except ManifestCorruption:
            return Gate(integrity="manifest_corrupt", identity_mismatches=tuple(identity))
        identity += [f"manifest_{name}" for name in manifest_mismatches(manifest, self.collection)]
        identity += [f"live_{name}" for name in live_configuration_mismatches(self.collection)]
        try:
            run_log = self.store.read_run_log()
        except RunLogCorruption:
            return Gate(integrity="run_log_corrupt", identity_mismatches=tuple(identity),
                        manifest=manifest)
        report, component, _ = evaluate_provenance(self.store, manifest, run_log, self.collection)
        if component is not None:
            return Gate(integrity="ledger_corrupt", identity_mismatches=tuple(identity),
                        provenance=report, manifest=manifest)
        try:
            level_one = _level_one_evidence(self.store, manifest, run_log, self.collection,
                                            report)
        except LedgerCorruption:  # pragma: no cover - provenance already read it strictly
            return Gate(integrity="ledger_corrupt", identity_mismatches=tuple(identity),
                        provenance=report, manifest=manifest)
        if report.status not in ("ok", "degraded") or identity:
            return Gate(integrity="ok", identity_mismatches=tuple(identity), provenance=report,
                        manifest=manifest)
        stop = evaluate_stop_rule(definition, activated_at=manifest.activated_at,
                                  evidence_through=evidence_through(level_one),
                                  matured_counts=matured_claim_counts(definition, level_one))
        return Gate(integrity="ok", identity_mismatches=(), provenance=report,
                    manifest=manifest, level_one=level_one, stop=stop,
                    cutoffs=cutoffs(definition, level_one))


@contextmanager
def _opened(snapshot: InputSnapshot, collection: CollectionDefinition) -> Iterator[_Frozen]:
    with materialize(snapshot) as root:
        yield _Frozen(root, collection)


def _capture_locked(store: ProspectiveStore, recorded: Mapping[str, Any] | None = None
                    ) -> InputSnapshot:
    """Capture (or recapture) under the shared lock; raises the lock and store errors."""
    with store.shared_lock():
        return capture(store.root) if recorded is None else recapture(store.root, recorded)


# -- status -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusReport:
    """What the blind status may say. No state, price, return, sign, episode or category."""

    validation_id: str
    validation_fingerprint: str
    definition_identity: str
    activation: str
    integrity: str = "unknown"
    identity_mismatches: tuple[str, ...] = ()
    provenance_status: str = "unknown"
    provenance_reasons: tuple[tuple[str, int], ...] = ()
    excluded_artifact_keys: int = 0
    excluded_outcome_keys: int = 0
    validity: str = VALIDITY_UNKNOWN
    activated_at: datetime | None = None
    evidence_through: datetime | None = None
    e1_due: datetime | None = None
    e1_met: bool | None = None
    e2_minimum: int | None = None
    e2_counts: tuple[tuple[str, int], ...] = ()
    e2_met: bool | None = None
    forced_due: datetime | None = None
    f_met: bool | None = None
    unlockable: bool = False
    unlock_exists: bool = False
    result_exists: bool = False


def _status_from(definition: FutureValidationDefinition, base: dict, gate: Gate) -> StatusReport:
    report = gate.provenance
    stop = gate.stop
    return StatusReport(
        integrity=gate.integrity,
        identity_mismatches=gate.identity_mismatches,
        provenance_status=report.status if report is not None else "unknown",
        provenance_reasons=report.reasons if report is not None else (),
        excluded_artifact_keys=len(report.excluded_artifact_keys) if report is not None else 0,
        excluded_outcome_keys=len(report.excluded_outcome_keys) if report is not None else 0,
        validity=gate.validity,
        activated_at=gate.manifest.activated_at if gate.manifest is not None else None,
        evidence_through=stop.evidence_through if stop else None,
        e1_due=stop.e1_due if stop else None,
        e1_met=stop.e1_met if stop else None,
        e2_minimum=stop.e2_minimum if stop else None,
        e2_counts=stop.e2_counts if stop else (),
        e2_met=stop.e2_met if stop else None,
        forced_due=stop.forced_due if stop else None,
        f_met=stop.f_met if stop else None,
        unlockable=gate.unlockable,
        **base,
    )


def status(
    store: ProspectiveStore | None = None,
    *,
    definition: FutureValidationDefinition = FUTURE_VALIDATION_V1,
    pinned_fingerprint: str = FUTURE_VALIDATION_V1_FINGERPRINT,
    collection: CollectionDefinition = COLLECTION_V1,
) -> StatusReport:
    """Level 1 only, offline, read-only, clock-free. Never creates anything."""
    store = build_prospective_store() if store is None else store
    artifacts = ValidationArtifacts(store.root, definition.validation_id, definition.fingerprint)
    base = dict(
        validation_id=definition.validation_id,
        validation_fingerprint=definition.fingerprint,
        definition_identity=("ok" if not definition_mismatches(
            definition, pinned_fingerprint, collection) else "mismatch"),
        unlock_exists=artifacts.exists(UNLOCK_NAME),
        result_exists=artifacts.exists(RESULT_NAME),
    )
    try:
        manifest = store.read_manifest()
    except ManifestCorruption:
        return StatusReport(activation="invalid_manifest", integrity="manifest_corrupt",
                            validity=VALIDITY_INVALID, **base)
    if manifest is None:
        return StatusReport(activation="not_activated", **base)
    try:
        snapshot = _capture_locked(store)
    except RootLockedError:
        return StatusReport(activation="collect_in_progress", **base)
    except LockMissingError:
        return StatusReport(activation="lock_missing", integrity="lock_missing", **base)
    except UnsupportedEntry:
        return StatusReport(activation="activated", integrity="unsupported_entry",
                            validity=VALIDITY_INVALID, **base)
    with _opened(snapshot, collection) as frozen:
        gate = frozen.gate(definition, pinned_fingerprint)
    return _status_from(definition, dict(base, activation="activated"), gate)


# -- run --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunReport:
    """How one ``run`` ended. Categories only once a result exists."""

    outcome: str
    status: StatusReport | None = None
    detail: tuple[str, ...] = ()
    categories: tuple[tuple[str, str], ...] = ()
    unlock_sha256: str | None = None
    result_sha256: str | None = None

    @property
    def completed(self) -> bool:
        return self.outcome in ("complete", "completed_after_unlock", "already_complete")


UNLOCK_FIELDS = frozenset({
    "schema", "validation_id", "validation_fingerprint", "runner_version", "host_recorded_at",
    "activated_at", "activation_manifest_sha256", "collection_fingerprint",
    "provenance_policy_fingerprint", "provenance", "stop_rule", "cutoffs", "snapshot",
    "runner_repository",
})


#: Unlock fields that are informational only: they record the opening host and
#: repository, are never re-derivable from the frozen snapshot and decide nothing.
#: Every other unlock field is rebuilt from the recaptured snapshot and must match.
UNLOCK_INFORMATIONAL_FIELDS = frozenset({"host_recorded_at", "runner_repository"})


def _unlock_payload(definition, gate: Gate, snapshot: InputSnapshot, host_time: datetime,
                    collection: CollectionDefinition, repository) -> dict[str, Any]:
    runner = None
    if repository is not None:
        try:
            state = repository.repository_state()
            runner = {"clean": bool(state.clean), "head": str(state.head)}
        except Exception:  # an unavailable probe is recorded as unknown, never fatal
            runner = None
    return dict(_deterministic_unlock(definition, gate, snapshot, collection),
                host_recorded_at=_iso(host_time), runner_repository=runner)


def _deterministic_unlock(definition, gate: Gate, snapshot: InputSnapshot,
                          collection: CollectionDefinition) -> dict[str, Any]:
    """Every unlock field that is a function of the definition and the frozen snapshot."""
    report = gate.provenance
    return {
        "schema": definition.unlock_schema,
        "validation_id": definition.validation_id,
        "validation_fingerprint": definition.fingerprint,
        "runner_version": definition.runner_version,
        "activated_at": _iso(gate.manifest.activated_at),
        "activation_manifest_sha256": sha256_hex(snapshot.data("activation.json") or b""),
        "collection_fingerprint": gate.manifest.collection_fingerprint,
        "provenance_policy_fingerprint": provenance_policy_for(collection).fingerprint,
        "provenance": {
            "claims_checked": report.claims_checked,
            "excluded_artifact_keys": len(report.excluded_artifact_keys),
            "excluded_outcome_keys": len(report.excluded_outcome_keys),
            "outcomes_checked": report.outcomes_checked,
            "runs_interrupted": report.runs_interrupted,
            "status": report.status,
        },
        "stop_rule": gate.stop.to_payload(),
        "cutoffs": {symbol: _iso(value) for symbol, value in gate.cutoffs.items()},
        "snapshot": dict(snapshot.payload(), identity=snapshot.identity),
    }


def _is_snapshot_record(value: object) -> bool:
    """The recorded snapshot's shape: relative paths only, typed lengths and hashes."""
    def relative(path: object) -> bool:
        return isinstance(path, str) and path != "" and not path.startswith("/") \
            and ".." not in path.split("/")

    if not isinstance(value, dict) or set(value) != {"directories", "files", "identity"} \
            or not isinstance(value["identity"], str) \
            or not isinstance(value["directories"], list) \
            or not all(relative(d) for d in value["directories"]) \
            or not isinstance(value["files"], list):
        return False
    return all(
        isinstance(f, dict) and set(f) == {"length", "match", "path", "sha256"}
        and relative(f["path"]) and isinstance(f["sha256"], str)
        and isinstance(f["length"], int) and not isinstance(f["length"], bool)
        and f["length"] >= 0 and f["match"] in (MATCH_EXACT, MATCH_PREFIX)
        for f in value["files"])


def _decode_unlock(raw: bytes) -> dict[str, Any]:
    payload = decode_canonical(raw, "unlock.json")
    if set(payload) != UNLOCK_FIELDS:
        raise FutureValidationError("unlock.json keys differ from the schema")
    if not _is_snapshot_record(payload["snapshot"]):
        raise FutureValidationError("unlock.json snapshot record is malformed")
    if not _is_aware_iso(payload["host_recorded_at"]):
        raise FutureValidationError("unlock.json host_recorded_at is malformed")
    runner = payload["runner_repository"]
    if runner is not None and not (
            isinstance(runner, dict) and set(runner) == {"clean", "head"}
            and isinstance(runner["clean"], bool) and isinstance(runner["head"], str)):
        raise FutureValidationError("unlock.json runner_repository is malformed")
    return payload


def _is_aware_iso(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _decode_result(raw: bytes, definition: FutureValidationDefinition) -> dict[str, Any]:
    """Decode result.json and check the shape read before verification; never coerce.

    Only ``categories`` and ``unlock.sha256`` are read before the result is
    compared byte for byte with its re-derivation, so every other field's shape
    is enforced by that comparison.
    """
    payload = decode_canonical(raw, "result.json")
    if payload.get("schema") != definition.result_schema \
            or payload.get("validation_fingerprint") != definition.fingerprint:
        raise FutureValidationError("result.json is not this validation's result")
    categories = payload.get("categories")
    if not isinstance(categories, list) \
            or not all(isinstance(item, list) and len(item) == 2
                       and all(isinstance(part, str) for part in item) for item in categories) \
            or [item[0] for item in categories] != list(definition.primary_symbols) \
            or any(item[1] not in definition.categories for item in categories):
        raise FutureValidationError("result.json categories are not the frozen vocabulary")
    unlock = payload.get("unlock")
    if not isinstance(unlock, dict) or not isinstance(unlock.get("sha256"), str):
        raise FutureValidationError("result.json does not name its unlock")
    return payload


def _categories(result: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple((symbol, category) for symbol, category in result["categories"])


def _derive_result(frozen: _Frozen, definition: FutureValidationDefinition, gate: Gate,
                   unlock: Mapping[str, Any], unlock_raw: bytes) -> dict[str, Any]:
    """Level 3 -- reached only with unlock.json on disk: the deterministic result payload."""
    evidence = _level_three_evidence(frozen.store, frozen.collection, gate.level_one)
    return build_result(definition, evidence, unlock=unlock,
                        unlock_sha256=sha256_hex(unlock_raw))


def _write_result(artifacts: ValidationArtifacts, result: Mapping[str, Any],
                  unlock_raw: bytes, outcome: str) -> RunReport:
    raw = canonical_bytes(result)
    artifacts.write_once(RESULT_NAME, raw)
    artifacts.write_once(REPORT_NAME, render_report(result).encode("utf-8"))
    return RunReport(outcome, categories=_categories(result),
                     unlock_sha256=sha256_hex(unlock_raw), result_sha256=sha256_hex(raw))


def _from_unlock(store, definition, pinned_fingerprint, collection, raw_unlock: bytes
                 ) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Re-derive the result of an existing unlock from its recorded prefixes, or say why not.

    Used both to complete an interrupted opening and to verify a written result;
    it never creates an unlock, a snapshot or a cutoff of its own.
    """
    try:
        unlock = _decode_unlock(raw_unlock)
    except FutureValidationError:
        return None, ("unlock_corrupt",)
    if unlock["schema"] != definition.unlock_schema \
            or unlock["validation_fingerprint"] != definition.fingerprint \
            or unlock["validation_id"] != definition.validation_id:
        return None, ("unlock_identity_mismatch",)
    recorded = {key: value for key, value in unlock["snapshot"].items() if key != "identity"}
    try:
        snapshot = _capture_locked(store, recorded)
    except RootLockedError:
        return None, ("collect_in_progress",)
    except LockMissingError:
        return None, ("lock_missing",)
    except (SnapshotMismatch, UnsupportedEntry):
        return None, ("snapshot_mismatch",)
    if snapshot.identity != unlock["snapshot"]["identity"]:
        return None, ("snapshot_mismatch",)
    with _opened(snapshot, collection) as frozen:
        gate = frozen.gate(definition, pinned_fingerprint)
        if gate.validity != VALIDITY_OK or not gate.unlockable:
            return None, ("unlock_inconsistent", gate.validity)
        # Every deterministic field (identities, activation, manifest hash, provenance
        # evidence, stop rule, cutoffs, snapshot) is rebuilt from the recaptured bytes;
        # only the informational host and repository fields are taken as recorded.
        recorded_fields = {key: value for key, value in unlock.items()
                           if key not in UNLOCK_INFORMATIONAL_FIELDS}
        if _deterministic_unlock(definition, gate, snapshot, collection) != recorded_fields:
            return None, ("unlock_metadata_mismatch",)
        return _derive_result(frozen, definition, gate, unlock, raw_unlock), ()


def _finish_report(store, artifacts: ValidationArtifacts, definition, pinned_fingerprint,
                   collection, raw_result: bytes) -> RunReport:
    """result.json exists: verify it, never replace it; write report.md from it if missing.

    The result must name the unlock on disk by its SHA-256 and be byte-identical to
    the result re-derived from that unlock's recorded prefixes, so an edited result
    -- even a canonical one with a valid category -- is refused, not returned.
    """
    try:
        result = _decode_result(raw_result, definition)
    except FutureValidationError as exc:
        return RunReport("refused", detail=("result_corrupt", type(exc).__name__))
    raw_unlock = artifacts.read(UNLOCK_NAME)
    if raw_unlock is None:
        return RunReport("refused", detail=("unlock_missing",))
    if result.get("unlock", {}).get("sha256") != sha256_hex(raw_unlock):
        return RunReport("refused", detail=("result_unlock_mismatch",))
    derived, why = _from_unlock(store, definition, pinned_fingerprint, collection, raw_unlock)
    if derived is None:
        return RunReport("refused", detail=("result_unverifiable", *why))
    if canonical_bytes(derived) != raw_result:
        return RunReport("refused", detail=("result_mismatch",))
    report = render_report(result).encode("utf-8")
    existing = artifacts.read(REPORT_NAME)
    if existing is None:
        try:
            artifacts.write_once(REPORT_NAME, report)
        except ArtifactExists:  # pragma: no cover - a concurrent identical writer
            pass
    elif existing != report:
        return RunReport("refused", detail=("report_mismatch",))
    return RunReport("already_complete", categories=_categories(result),
                     unlock_sha256=result["unlock"]["sha256"],
                     result_sha256=sha256_hex(raw_result))


def run(
    store: ProspectiveStore | None = None,
    *,
    definition: FutureValidationDefinition = FUTURE_VALIDATION_V1,
    pinned_fingerprint: str = FUTURE_VALIDATION_V1_FINGERPRINT,
    collection: CollectionDefinition = COLLECTION_V1,
    now: Clock = _utc_now,
    repository=None,
) -> RunReport:
    """The one explicit opening. Refuses (writing nothing) unless every gate passes.

    ``now`` is host metadata only (``host_recorded_at``); it decides nothing.
    """
    store = build_prospective_store() if store is None else store
    if definition_mismatches(definition, pinned_fingerprint, collection):
        return RunReport("refused", detail=("definition_mismatch",
                                            *definition_mismatches(definition,
                                                                   pinned_fingerprint,
                                                                   collection)))
    artifacts = ValidationArtifacts(store.root, definition.validation_id, definition.fingerprint)
    raw_result = artifacts.read(RESULT_NAME)
    if raw_result is not None:
        return _finish_report(store, artifacts, definition, pinned_fingerprint, collection,
                              raw_result)
    raw_unlock = artifacts.read(UNLOCK_NAME)
    if raw_unlock is not None:
        result, why = _from_unlock(store, definition, pinned_fingerprint, collection,
                                   raw_unlock)
        if result is None:
            return RunReport("refused", detail=why)
        return _write_result(artifacts, result, raw_unlock, "completed_after_unlock")

    try:
        manifest = store.read_manifest()
    except ManifestCorruption:
        return RunReport("refused", detail=("invalid_manifest",))
    if manifest is None:
        return RunReport("refused", detail=("not_activated",))
    try:
        snapshot = _capture_locked(store)
    except RootLockedError:
        return RunReport("refused", detail=("collect_in_progress",))
    except LockMissingError:
        return RunReport("refused", detail=("lock_missing",))
    except UnsupportedEntry:
        return RunReport("refused", detail=("unsupported_entry",))

    with _opened(snapshot, collection) as frozen:
        gate = frozen.gate(definition, pinned_fingerprint)
        current = _status_from(definition, dict(
            validation_id=definition.validation_id,
            validation_fingerprint=definition.fingerprint, definition_identity="ok",
            activation="activated"), gate)
        if gate.validity != VALIDITY_OK:
            return RunReport("refused", status=current,
                             detail=(f"validity_{gate.validity}", gate.integrity,
                                     *gate.identity_mismatches))
        if not gate.unlockable:
            return RunReport("refused", status=current, detail=("not_unlockable",))
        unlock = _unlock_payload(definition, gate, snapshot, now(), collection, repository)
        unlock_raw = canonical_bytes(unlock)
        try:
            artifacts.write_once(UNLOCK_NAME, unlock_raw)
        except ArtifactExists:
            return RunReport("refused", status=current, detail=("unlock_exists",))
        result = _derive_result(frozen, definition, gate, unlock, unlock_raw)
        return _write_result(artifacts, result, unlock_raw, "complete")


__all__ = [
    "VALIDITY_OK",
    "VALIDITY_INVALID",
    "VALIDITY_UNKNOWN",
    "definition_mismatches",
    "Gate",
    "StatusReport",
    "RunReport",
    "UNLOCK_FIELDS",
    "UNLOCK_INFORMATIONAL_FIELDS",
    "status",
    "run",
]
