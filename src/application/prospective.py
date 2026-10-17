"""Prospective Collection v1: activate once, collect inside the window, report health blind.

    activate  -> verify repository (main, clean, HEAD == named collector == origin/main ==
                 operator-verified server main), the pinned M2A binding, live config and
                 the dependency environment -> collect.lock, then activation.json, once
                 (no network)
    collect   -> manifest -> exclusive lock (bounded wait)
                 -> run-log integrity -> fingerprint -> ET window -> collector identity
                    (clean tree, HEAD == manifest commit) -> dependency environment
                    (== the activation's) -> ledger integrity + provenance
                 -> run start (fsynced)
                 -> per symbol: window -> build_snapshot -> validate -> activation boundary
                    -> missed tails -> current-tail rule -> refresh_outcomes (unchanged)
                 -> one run record -> unlock
    health    -> manifest -> shared lock (non-blocking) -> run log + ledger, read strictly,
                 provenance reconciled; Level-1 counts only (no network)

This module **orchestrates** around Phase 12. It never measures, never
registers or evaluates a claim itself and never reconstructs one: the only
path to the ledger is the unchanged :func:`~src.application.outcomes.refresh_outcomes`,
invoked only when the current tail is legal to claim, against the dedicated
ledger under ``data/prospective/v1/ledger`` -- never the dashboard's
``data/outcomes``. Its own decisions are *whether* that call may happen:

* the collection window ``00:30 <= ET < 09:00`` is checked on the run's
  start clock **before any provider is constructed**, again before each
  symbol's fetch, and on each snapshot's ``built_at`` (the claim's
  ``recorded_at``); outside it nothing is fetched or written;
* every daily bar must be stamped 00:00:00 America/New_York;
* a tail that settled at or before ``activated_at`` is never claimed;
* a tail with any claim still unregistered is claimed only while current
  (no weekday has passed since it settled), so nothing -- not even the rest
  of a set a crashed run left partial -- is claimed late;
* settled post-activation bars that were never claimed are reported as
  missed, as operational metadata, and are never claimed afterwards;
* nothing is fetched unless the running code is the activated collector
  commit with a clean tree, the installed dependency environment is exactly
  the one activation recorded, and every existing ledger record reconciles to
  this collection's own run log (:mod:`src.prospective.provenance`): a
  record written by any other tool -- e.g. the generic ``outcome_refresh``
  pointed at this ledger -- makes provenance ``invalid`` and stops
  collection. Nothing is repaired, deleted or rewritten.

Blindness. Nothing here reads a price, a forward return or a research
state for reporting. The run record and the health report carry
identities, clocks, counts, bar timestamps and status classes only.
Exception *messages* are not recorded or returned -- a domain message may
quote a value -- only exception class names and stages.

The reserved interval (2025-03-01 to activation) reaches this module only
as in-memory causal lookback inside :func:`build_snapshot`'s two-year
window: needed for SMA50/RSI14, never claimed, evaluated, persisted or
printed here.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from src.data.models import Interval
from src.outcomes import EVALUATION_VERSION, LedgerCorruption, LedgerPartition
from src.prospective import (
    AUTHORITATIVE_BRANCH,
    COLLECTION_V1,
    M2A_BOUND_PATHS,
    M2A_FUTURE_VALIDATION_FINGERPRINT,
    M2A_PREREGISTRATION_COMMIT,
    ActivationManifest,
    CollectionDefinition,
    CollectionStatus,
    DefinitionError,
    DependencyEnvironment,
    DependencyEnvironmentError,
    GitRepositoryProbe,
    ManifestCorruption,
    ManifestExistsError,
    ProspectiveStore,
    DEFAULT_LOCK_TIMEOUT,
    PROVENANCE_V1,
    ClaimMeta,
    LockMissingError,
    OutcomeMeta,
    PartitionMeta,
    ProvenanceReport,
    RepositoryProbeError,
    RepositoryState,
    RootLockedError,
    RunLogCorruption,
    RunRecord,
    RunStart,
    RunStatus,
    SymbolRun,
    capture_dependency_environment,
    first_non_midnight,
    import_path_overrides,
    in_collection_window,
    is_current_tail,
    is_pre_activation,
    missed_tails,
    new_york_date,
    provenance_policy_for,
    running_python,
    unknown_report,
    validate_commit_sha,
    verify_provenance,
)
from src.research.future_validation import FUTURE_VALIDATION_V1

from .errors import ApplicationError, FailureKind
from .outcomes import OUTCOME_SPECS, build_outcome_ledger, refresh_outcomes
from .snapshot import (
    BASIS,
    HISTORY_WINDOWS,
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    build_ensemble,
    build_policy,
    build_snapshot,
    default_provider,
)

Clock = Callable[[], datetime]

_REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]

#: The live prospective root. Absent until an explicitly approved activation.
#: Resolved from this file, never from the working directory, and distinct
#: from the dashboard's ``data/outcomes`` so a Refresh can never write here.
DEFAULT_PROSPECTIVE_ROOT: Path = _REPOSITORY_ROOT / "data" / "prospective" / "v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveError(f"{label} must be a timezone-aware datetime")
    return value


class ProspectiveError(RuntimeError):
    """A prospective request is malformed."""


class ActivationRefused(ProspectiveError):
    """Activation was refused; nothing was written. ``reason`` is a stable code."""

    def __init__(self, reason: str, message: str, details: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details


class RepositoryProbe(Protocol):
    """Read-only, local answers about one repository (see :class:`GitRepositoryProbe`)."""

    def repository_state(self) -> RepositoryState: ...

    def is_ancestor_of_head(self, commit: str) -> bool: ...

    def current_branch(self) -> str | None: ...

    def origin_main(self) -> str | None: ...

    def commit_exists(self, commit: str) -> bool: ...

    def blob_sha256(self, commit: str, path: str) -> str | None: ...

    def working_file_sha256(self, path: str) -> str | None: ...

    def paths_unchanged_since(self, commit: str, paths) -> bool: ...


DependencySource = Callable[[], DependencyEnvironment]


def build_prospective_store(root: str | Path | None = None) -> ProspectiveStore:
    """The store for ``root``, or the live default. Construction touches nothing."""
    return ProspectiveStore(DEFAULT_PROSPECTIVE_ROOT if root is None else root)


def default_repository_probe() -> GitRepositoryProbe:
    return GitRepositoryProbe(_REPOSITORY_ROOT)


def collection_definition() -> CollectionDefinition:
    return COLLECTION_V1


def current_dependency_environment() -> DependencyEnvironment:
    """The running interpreter's dependency environment; :class:`DependencyEnvironmentError`."""
    return capture_dependency_environment()


def _dependencies(source: DependencySource | None) -> DependencyEnvironment:
    return (current_dependency_environment if source is None else source)()


def current_import_path_overrides() -> tuple[str, ...]:
    """``PYTHONPATH`` / ``PYTHONHOME`` if in effect for this interpreter (see the adapter)."""
    return import_path_overrides()


@dataclass(frozen=True)
class RuntimeIdentity:
    """The CURRENT runtime as an activation here would record it -- not the manifest's.

    ``environment`` is ``None`` when the dependency environment cannot be
    verified (for example while ``PYTHONPATH`` is in effect); the Python
    implementation and version are then the interpreter's own.
    """

    python_implementation: str
    python_version: str
    import_path_overrides: tuple[str, ...]
    environment: DependencyEnvironment | None

    @property
    def dependency_fingerprint(self) -> str | None:
        return None if self.environment is None else self.environment.fingerprint


def runtime_identity(source: DependencySource | None = None) -> RuntimeIdentity:
    """Read-only: the interpreter, its import-path verdict and its dependency environment."""
    try:
        environment: DependencyEnvironment | None = _dependencies(source)
    except DependencyEnvironmentError:
        environment = None
    implementation, version = running_python() if environment is None else (
        environment.python_implementation, environment.python_version)
    return RuntimeIdentity(implementation, version, current_import_path_overrides(),
                           environment)


def _probe(repository: RepositoryProbe | None) -> RepositoryProbe:
    return default_repository_probe() if repository is None else repository


# -- live configuration -------------------------------------------------------------------


def live_configuration_mismatches(
    definition: CollectionDefinition = COLLECTION_V1,
) -> tuple[str, ...]:
    """Names of every frozen item the running code no longer matches."""
    mismatches: list[str] = []
    hypotheses = build_ensemble()
    live_pins = tuple(
        (h.spec.hypothesis_id, h.spec.version, h.fingerprint) for h in hypotheses
    )
    pinned = tuple((p.hypothesis_id, p.version, p.fingerprint) for p in definition.hypotheses)
    if live_pins != pinned:
        mismatches.append("hypotheses")
    policy = build_policy(hypotheses)
    if policy.fingerprint != definition.policy_fingerprint:
        mismatches.append("policy_fingerprint")
    rule = getattr(policy.aggregation_rule, "value", policy.aggregation_rule)
    if rule != definition.assessment_rule:
        mismatches.append("assessment_rule")
    if MINIMUM_SUFFICIENT_OBSERVATIONS != definition.minimum_sufficient_observations:
        mismatches.append("minimum_sufficient_observations")
    if tuple(spec.horizon_bars for spec in OUTCOME_SPECS) != definition.outcome_horizons:
        mismatches.append("outcome_horizons")
    if tuple(spec.fingerprint for spec in OUTCOME_SPECS) != definition.outcome_spec_fingerprints:
        mismatches.append("outcome_spec_fingerprints")
    if EVALUATION_VERSION != definition.evaluation_version:
        mismatches.append("evaluation_version")
    if BASIS.value != definition.basis:
        mismatches.append("basis")
    try:
        interval = Interval.parse(definition.interval)
        if HISTORY_WINDOWS[interval].days != definition.history_window_days:
            mismatches.append("history_window_days")
    except (ValueError, KeyError):
        mismatches.append("interval")
    if WARMUP_BARS != definition.warmup_bars:
        mismatches.append("warmup_bars")
    return tuple(mismatches)


def manifest_mismatches(
    manifest: ActivationManifest, definition: CollectionDefinition = COLLECTION_V1
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if manifest.collection_id != definition.collection_id:
        mismatches.append("collection_id")
    if manifest.collection_fingerprint != definition.fingerprint:
        mismatches.append("collection_fingerprint")
    if manifest.provenance_policy_fingerprint != provenance_policy_for(definition).fingerprint:
        mismatches.append("provenance_policy_fingerprint")
    return tuple(mismatches)


# -- M2A binding ----------------------------------------------------------------------------


def m2_binding_mismatches(repository: RepositoryProbe) -> tuple[str, ...]:
    """Every way the repository differs from the pinned M2A pre-registration; ``()`` if none.

    The pinned commit must exist and be in HEAD's history; each bound path
    must hold its pinned bytes at that commit, in HEAD (no change between the
    commit and HEAD) and in the working tree; and the live
    ``FUTURE_VALIDATION_V1`` must have the pinned fingerprint. Read-only and
    local; raises :class:`RepositoryProbeError` when Git cannot answer.
    """
    found: list[str] = []
    if FUTURE_VALIDATION_V1.fingerprint != M2A_FUTURE_VALIDATION_FINGERPRINT:
        found.append("future_validation_fingerprint_mismatch")
    commit = M2A_PREREGISTRATION_COMMIT
    if not repository.commit_exists(commit):
        return (*found, "m2_commit_missing")
    if not repository.is_ancestor_of_head(commit):
        found.append("m2_commit_not_in_history")
    for bound in M2A_BOUND_PATHS:
        if repository.blob_sha256(commit, bound.path) != bound.sha256:
            found.append(f"m2_preregistered_bytes_mismatch:{bound.path}")
        if repository.working_file_sha256(bound.path) != bound.sha256:
            found.append(f"m2_working_tree_bytes_mismatch:{bound.path}")
    if not repository.paths_unchanged_since(commit, [bound.path for bound in M2A_BOUND_PATHS]):
        found.append("m2_bound_paths_changed")
    return tuple(found)


def _code(mismatch: str) -> str:
    return mismatch.split(":", 1)[0]


# -- activation -----------------------------------------------------------------------------


def activate(
    store: ProspectiveStore,
    *,
    collector_git_commit: str,
    server_main_git_commit: str,
    repository: RepositoryProbe,
    dependency_environment: DependencySource | None = None,
    now: Clock = _utc_now,
    definition: CollectionDefinition = COLLECTION_V1,
) -> ActivationManifest:
    """Write the activation manifest once. No provider, no claim, no outcome, no network.

    ``server_main_git_commit`` is the operator's assertion of the server's
    ``main``, taken from ``git ls-remote origin refs/heads/main`` immediately
    after ``git fetch origin``; activation itself never contacts a remote.

    Refused (:class:`ActivationRefused`, nothing written -- the root is not
    even created) unless, in this order: both SHAs are full 40-hex; Git can
    answer; the checked-out branch is ``main``; the working tree is clean;
    HEAD is the named collector commit; the fetched ``refs/remotes/origin/main``
    exists and equals HEAD; the server main equals HEAD; the pinned M2A
    binding holds (:func:`m2_binding_mismatches`); the running code matches
    the frozen definition; the dependency environment can be read; and the
    root is empty. Writes the lock file first and the manifest second, so an
    activated root always has the lock ``health`` and ``collect`` need.
    ``activation_write_failed`` means durability could not be confirmed: the
    root may hold the lock and possibly a partial or complete manifest.
    """
    try:
        collector = validate_commit_sha(collector_git_commit, "collector_git_commit")
        server_main = validate_commit_sha(server_main_git_commit, "server_main_git_commit")
    except DefinitionError as exc:
        raise ActivationRefused("invalid_commit", str(exc)) from exc
    try:
        state = repository.repository_state()
        branch = repository.current_branch()
        origin_main = repository.origin_main()
    except RepositoryProbeError as exc:
        raise ActivationRefused("repository_unverified",
                                "git could not report the repository's state") from exc
    if branch != AUTHORITATIVE_BRANCH:
        raise ActivationRefused("not_on_main", "the checked-out branch is not main")
    if not state.clean:
        raise ActivationRefused("dirty_repository",
                                "the working tree has uncommitted or untracked changes")
    if state.head != collector:
        raise ActivationRefused("collector_commit_mismatch",
                                "HEAD is not the named collector commit")
    if origin_main is None:
        raise ActivationRefused("origin_main_missing",
                                "refs/remotes/origin/main does not exist; fetch origin first")
    if origin_main != state.head:
        raise ActivationRefused("head_not_origin_main",
                                "HEAD is not the fetched origin/main (behind, ahead or diverged)")
    if server_main != state.head:
        raise ActivationRefused("server_main_mismatch",
                                "HEAD is not the server main named by the preflight")
    try:
        binding = m2_binding_mismatches(repository)
    except RepositoryProbeError as exc:
        raise ActivationRefused("repository_unverified",
                                "git could not verify the M2A binding") from exc
    if binding:
        raise ActivationRefused(_code(binding[0]),
                                "the M2A pre-registration binding fails: " + ",".join(binding),
                                binding)
    live = live_configuration_mismatches(definition)
    if live:
        raise ActivationRefused("config_mismatch",
                                "running code differs from the frozen definition: "
                                + ",".join(live))
    try:
        environment = _dependencies(dependency_environment)
    except DependencyEnvironmentError as exc:
        raise ActivationRefused("dependency_environment_unavailable",
                                "the installed dependency environment could not be read") from exc
    activated_at = _aware(now(), "activation clock")
    manifest = ActivationManifest(
        activated_at=activated_at,
        collection_id=definition.collection_id,
        collection_fingerprint=definition.fingerprint,
        provenance_policy_fingerprint=provenance_policy_for(definition).fingerprint,
        collector_git_commit=collector,
        origin_main_git_commit=origin_main,
        server_main_git_commit=server_main,
        m2_preregistration_git_commit=M2A_PREREGISTRATION_COMMIT,
        future_validation_fingerprint=M2A_FUTURE_VALIDATION_FINGERPRINT,
        m2_bound_paths=M2A_BOUND_PATHS,
        holdout_start=definition.holdout_start,
        universe=definition.universe,
        interval=definition.interval,
        basis=definition.basis,
        provider=definition.provider,
        hypothesis_fingerprints=definition.hypothesis_fingerprints,
        outcome_spec_fingerprints=definition.outcome_spec_fingerprints,
        evaluation_version=definition.evaluation_version,
        dependency_environment=environment,
    )
    try:
        store.write_manifest(manifest)
    except ManifestExistsError as exc:
        raise ActivationRefused("already_activated", str(exc)) from exc
    except OSError as exc:
        # The lock is created before the manifest, but the failure may come at
        # any step: creating the lock (nothing activated), writing the manifest
        # (no or partial manifest) or fsyncing it or its directory *after* its
        # bytes were written -- then a complete manifest may exist and health
        # may report the root active. Durability is unconfirmed either way, so
        # the result is a refusal plus manual inspection, never an assumption.
        # A retry is refused (non-empty root) until an operator inspects it.
        raise ActivationRefused(
            "activation_write_failed",
            f"activation durability could not be confirmed ({type(exc).__name__}); the root "
            "may hold collect.lock and possibly a partial or complete activation.json -- "
            "inspect it by hand before any retry, collection or scheduler installation",
        ) from exc
    return manifest


# -- collection -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectionReport:
    """What one ``collect`` invocation did. ``record`` is ``None`` when nothing was logged.

    ``outcome`` is one of ``not_activated``, ``invalid_manifest``, ``locked``,
    ``lock_missing``, ``corrupt_run_log`` (nothing written anywhere) or a
    :class:`RunStatus` value (one run record appended; for ``completed``, a
    run start was appended first). ``provenance`` is the verdict the run was
    gated on, when provenance was evaluated.
    """

    outcome: str
    record: RunRecord | None
    provenance: ProvenanceReport | None = None


class _LazyProvider:
    """Constructs the provider on first use, so a refused run never builds one."""

    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory
        self._provider: object | None = None

    def get(self) -> object:
        if self._provider is None:
            self._provider = self._factory()
        return self._provider


def collect(
    store: ProspectiveStore,
    *,
    provider_factory: Callable[[], object] | None = None,
    now: Clock = _utc_now,
    run_id_factory: Callable[[], str] = _new_run_id,
    definition: CollectionDefinition = COLLECTION_V1,
    repository: RepositoryProbe | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    lock_monotonic: Callable[[], float] = time.monotonic,
    lock_sleep: Callable[[float], None] = time.sleep,
    dependency_environment: DependencySource | None = None,
) -> CollectionReport:
    """One collection run over the frozen universe. See the module docstring.

    Everything up to the run start happens under the exclusive lock and
    before any provider exists, in this order: run-log integrity (a corrupt
    log is never appended to), configuration, window, collector identity
    (clean tree and HEAD == the manifest's collector commit), dependency
    environment (recomputed and exactly equal to the manifest's), ledger
    integrity and provenance. Any failure appends one refusal record (when
    the log is healthy; it has no symbols and no run start) and stops.
    """
    try:
        manifest = store.read_manifest()
    except ManifestCorruption:
        return CollectionReport("invalid_manifest", None)
    if manifest is None:
        return CollectionReport("not_activated", None)

    try:
        with store.exclusive_lock(timeout=lock_timeout, monotonic=lock_monotonic,
                                  sleep=lock_sleep):
            return _collect_locked(store, manifest, definition, provider_factory, now,
                                   run_id_factory, repository, dependency_environment)
    except RootLockedError:
        return CollectionReport("locked", None)
    except LockMissingError:
        return CollectionReport("lock_missing", None)


def _collector_identity(
    manifest: ActivationManifest, repository: RepositoryProbe | None
) -> RunStatus | None:
    """The refusal for a collector that is not the activated one, or ``None``."""
    try:
        state = _probe(repository).repository_state()
    except RepositoryProbeError:
        return RunStatus.COLLECTOR_UNVERIFIED
    if not state.clean:
        return RunStatus.DIRTY_COLLECTOR_TREE
    if state.head != manifest.collector_git_commit:
        return RunStatus.COLLECTOR_COMMIT_MISMATCH
    return None


def dependency_environment_status(
    manifest: ActivationManifest, source: DependencySource | None = None
) -> str:
    """``ok``, ``mismatch`` or ``unavailable``: the installed environment vs the manifest's."""
    try:
        current = _dependencies(source)
    except DependencyEnvironmentError:
        return "unavailable"
    return _environment_status(current, manifest)


def _environment_status(current: DependencyEnvironment | None,
                        manifest: ActivationManifest) -> str:
    if current is None:
        return "unavailable"
    recorded = manifest.dependency_environment
    if current != recorded or current.fingerprint != recorded.fingerprint:
        return "mismatch"
    return "ok"


_DEPENDENCY_REFUSALS = {
    "mismatch": RunStatus.DEPENDENCY_ENVIRONMENT_MISMATCH,
    "unavailable": RunStatus.DEPENDENCY_ENVIRONMENT_UNVERIFIED,
}


def _collect_locked(store, manifest, definition, provider_factory, now, run_id_factory,
                    repository, dependency_environment) -> CollectionReport:
    started_at = _aware(now(), "clock")
    try:
        run_log = store.read_run_log()
    except RunLogCorruption:
        return CollectionReport("corrupt_run_log", None)

    provenance: ProvenanceReport | None = None
    if manifest_mismatches(manifest, definition) or live_configuration_mismatches(definition):
        decision = RunStatus.CONFIG_MISMATCH
    elif not in_collection_window(started_at):
        decision = RunStatus.OUTSIDE_COLLECTION_WINDOW
    else:
        decision = (_collector_identity(manifest, repository)
                    or _DEPENDENCY_REFUSALS.get(
                        dependency_environment_status(manifest, dependency_environment))
                    or RunStatus.COMPLETED)
    if decision is RunStatus.COMPLETED:
        provenance, _, _ = evaluate_provenance(store, manifest, run_log, definition)
        if provenance.status == "unknown":
            decision = RunStatus.PROVENANCE_UNKNOWN
        elif not provenance.permits_collection:
            decision = RunStatus.PROVENANCE_INVALID

    run_id = run_id_factory()
    symbols: tuple[SymbolRun, ...] = ()
    if decision is RunStatus.COMPLETED:
        store.append_run_start(RunStart(
            run_id=run_id,
            started_at=started_at,
            collection_fingerprint=definition.fingerprint,
            provenance_policy_fingerprint=provenance_policy_for(definition).fingerprint,
            activated_at=manifest.activated_at,
            collector_git_commit=manifest.collector_git_commit,
            universe=definition.universe,
        ))
        provider = _LazyProvider(
            default_provider if provider_factory is None else provider_factory
        )
        symbols = tuple(
            _collect_symbol_guarded(symbol, store, manifest, definition, provider, now)
            for symbol in definition.universe
        )
    record = RunRecord(
        run_id=run_id,
        started_at=started_at,
        finished_at=_aware(now(), "clock"),
        run_status=decision,
        collection_fingerprint=definition.fingerprint,
        activated_at=manifest.activated_at,
        collector_git_commit=manifest.collector_git_commit,
        universe=definition.universe,
        symbols=symbols,
    )
    store.append_run(record)
    return CollectionReport(decision.value, record, provenance)


def _collect_symbol_guarded(symbol, store, manifest, definition, provider, now) -> SymbolRun:
    try:
        return _collect_symbol(symbol, store, manifest, definition, provider, now)
    except Exception as exc:  # a defect must still leave a run record
        return SymbolRun(symbol=symbol, status=CollectionStatus.UNEXPECTED_FAILURE,
                         stage="done", error_class=type(exc).__name__)


def _collect_symbol(
    symbol: str,
    store: ProspectiveStore,
    manifest: ActivationManifest,
    definition: CollectionDefinition,
    provider: _LazyProvider,
    now: Clock,
) -> SymbolRun:
    if not in_collection_window(_aware(now(), "clock")):
        return SymbolRun(symbol=symbol, status=CollectionStatus.OUTSIDE_COLLECTION_WINDOW,
                         stage="window")

    source = provider.get()
    if getattr(source, "name", None) != definition.provider:
        return SymbolRun(symbol=symbol, status=CollectionStatus.CONFIG_MISMATCH,
                         stage="snapshot")

    interval = Interval.parse(definition.interval)
    try:
        snapshot = build_snapshot(source, symbol, interval, now=now)
    except ApplicationError as exc:
        status = (CollectionStatus.PROVIDER_FAILURE if exc.kind is FailureKind.PROVIDER
                  else CollectionStatus.SNAPSHOT_FAILURE)
        return SymbolRun(symbol=symbol, status=status, stage="snapshot",
                         error_class=f"{type(exc).__name__}.{exc.kind.value}")

    facts = dict(symbol=symbol, built_at=snapshot.built_at, bars=snapshot.bar_count)
    if snapshot.bar_count == 0:
        return SymbolRun(status=CollectionStatus.NO_SETTLED_BAR, stage="snapshot", **facts)
    if (snapshot.source != definition.provider or snapshot.basis.value != definition.basis
            or snapshot.interval is not interval):
        return SymbolRun(status=CollectionStatus.CONFIG_MISMATCH, stage="validation", **facts)
    if not in_collection_window(snapshot.built_at):
        return SymbolRun(status=CollectionStatus.OUTSIDE_COLLECTION_WINDOW, stage="validation",
                         **facts)
    timestamps = snapshot.series.timestamps
    if first_non_midnight(timestamps) is not None:
        return SymbolRun(status=CollectionStatus.TIMESTAMP_CONVENTION, stage="validation",
                         **facts)

    tail = snapshot.latest_bar_open
    facts["tail"] = tail
    if is_pre_activation(tail, manifest.activated_at):
        return SymbolRun(status=CollectionStatus.PRE_ACTIVATION, stage="activation", **facts)

    ledger = build_outcome_ledger(store.ledger_root)
    partition = LedgerPartition(symbol=snapshot.symbol, interval=snapshot.interval,
                                basis=snapshot.basis)
    try:
        registered = [artifact.timestamp for artifact in ledger.iter_artifacts(partition)]
    except LedgerCorruption as exc:
        return SymbolRun(status=CollectionStatus.CORRUPT_LEDGER, stage="ledger",
                         error_class=type(exc).__name__, **facts)
    missed = missed_tails(timestamps, registered, activated_at=manifest.activated_at,
                          tail=tail)
    facts["missed_tails"] = missed
    # A tail whose claims are all held is only re-seen (DUPLICATE) and may
    # proceed so earlier claims keep maturing. Anything that would still
    # *write* a claim for it -- including the rest of a set a crashed run left
    # partial -- must be current, or it would be a late claim.
    if registered.count(tail) < definition.claims_per_tail \
            and not is_current_tail(tail, snapshot.built_at):
        return SymbolRun(status=CollectionStatus.STALE_TAIL, stage="validation", **facts)

    try:
        result = refresh_outcomes(snapshot, OUTCOME_SPECS, ledger, now=snapshot.built_at)
    except LedgerCorruption as exc:
        return SymbolRun(status=CollectionStatus.CORRUPT_LEDGER, stage="outcomes",
                         error_class=type(exc).__name__, **facts)
    except Exception as exc:
        return SymbolRun(status=CollectionStatus.REFRESH_FAILURE, stage="outcomes",
                         error_class=type(exc).__name__, **facts)

    if snapshot.bar_count < definition.warmup_bars:
        status = CollectionStatus.INSUFFICIENT_HISTORY
    elif result.artifacts_written == 0:
        status = CollectionStatus.DUPLICATE_ALREADY_EXISTS
    else:
        status = CollectionStatus.OK
    return SymbolRun(
        status=status, stage="done",
        artifacts_new=result.artifacts_written,
        artifacts_duplicate=result.artifact_duplicates,
        outcomes_new=result.outcomes_written,
        outcomes_present=result.outcomes_already_present,
        pending=result.pending,
        ineligible=result.ineligible,
        refused=result.refused,
        out_of_window=result.out_of_window,
        **facts,
    )


# -- provenance -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _PartitionRecords:
    """One expected partition read strictly: its artifacts and outcomes, in file order."""

    symbol: str
    exists: bool
    artifacts: tuple = ()
    outcomes: tuple = ()


class _PartitionUnreadable(Exception):
    """A partition failed its strict read; carries the symbol and the line."""

    def __init__(self, symbol: str, line_number: int | None) -> None:
        super().__init__(symbol)
        self.symbol = symbol
        self.line_number = line_number


def _read_partitions(store: ProspectiveStore,
                     definition: CollectionDefinition) -> tuple[_PartitionRecords, ...]:
    ledger = build_outcome_ledger(store.ledger_root)
    interval = Interval.parse(definition.interval)
    read: list[_PartitionRecords] = []
    for symbol in definition.universe:
        partition = LedgerPartition(symbol=symbol, interval=interval, basis=BASIS)
        if not ledger.partition_dir(partition).is_dir():
            read.append(_PartitionRecords(symbol=symbol, exists=False))
            continue
        try:
            artifacts = tuple(ledger.iter_artifacts(partition))
            outcomes = tuple(ledger.iter_outcomes(partition))
        except LedgerCorruption as exc:
            raise _PartitionUnreadable(symbol, getattr(exc, "line_number", None)) from exc
        read.append(_PartitionRecords(symbol, True, artifacts, outcomes))
    return tuple(read)


def _ledger_entries(store: ProspectiveStore) -> tuple[str, ...]:
    """Posix paths of everything under the ledger root, relative to it."""
    root = store.ledger_root
    if not root.is_dir():
        return ()
    return tuple(sorted(path.relative_to(root).as_posix() for path in root.rglob("*")))


def _claim_meta(artifact, line: int) -> ClaimMeta:
    """Allowlisted provenance metadata of one artifact. Never its claim."""
    kind = artifact.kind.value
    if kind == "observation":
        producer = (kind, artifact.hypothesis_id, artifact.hypothesis_version,
                    artifact.hypothesis_fingerprint)
    else:
        producer = (kind, artifact.policy_fingerprint)
    return ClaimMeta(
        symbol=artifact.symbol,
        line=line,
        key=artifact.artifact_key,
        producer=producer,
        interval=artifact.interval.value,
        basis=artifact.basis.value,
        timestamp=artifact.timestamp,
        data_cutoff=artifact.data_cutoff,
        recorded_at=artifact.recorded_at,
        source=artifact.source,
        origin=artifact.origin.value,
    )


def _outcome_meta(outcome, line: int) -> OutcomeMeta:
    """Allowlisted provenance metadata of one outcome. Never its measurement."""
    return OutcomeMeta(
        symbol=outcome.artifact.symbol,
        line=line,
        key=outcome.outcome_key,
        artifact_key=outcome.artifact.artifact_key,
        spec_fingerprint=outcome.spec_fingerprint,
        horizon_bars=outcome.horizon_bars,
        evaluation_version=outcome.evaluation_version,
        evaluated_at=outcome.evaluated_at,
    )


def _partition_meta(records: _PartitionRecords) -> PartitionMeta:
    return PartitionMeta(
        symbol=records.symbol,
        claims=tuple(_claim_meta(a, n) for n, a in enumerate(records.artifacts, start=1)),
        outcomes=tuple(_outcome_meta(o, n) for n, o in enumerate(records.outcomes, start=1)),
    )


def _verify(manifest, run_log, definition, partitions, entries) -> ProvenanceReport:
    return verify_provenance(
        provenance_policy_for(definition),
        activated_at=manifest.activated_at,
        collection_fingerprint=manifest.collection_fingerprint,
        collector_git_commit=manifest.collector_git_commit,
        run_log=run_log,
        ledger_entries=entries,
        partitions=tuple(_partition_meta(p) for p in partitions if p.exists),
    )


def evaluate_provenance(
    store: ProspectiveStore,
    manifest: ActivationManifest,
    run_log,
    definition: CollectionDefinition = COLLECTION_V1,
) -> tuple[ProvenanceReport, str | None, int | None]:
    """Provenance of the ledger against ``run_log``; ``unknown`` if a partition is unreadable.

    The caller must hold the root lock (exclusive or shared). Returns the
    report plus the unreadable component and line, when there is one. This
    is the interface a future validation requires: it may open only when
    the status is ``ok``, or ``degraded`` with the excluded keys removed.
    """
    try:
        partitions = _read_partitions(store, definition)
    except _PartitionUnreadable as exc:
        return unknown_report("integrity_corrupt"), f"ledger:{exc.symbol}", exc.line_number
    return _verify(manifest, run_log, definition, partitions, _ledger_entries(store)), None, None


# -- health ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolHealth:
    """Level-1 counts for one symbol's partition. No state, price or return."""

    symbol: str
    readable: bool
    claims_total: int = 0
    tails_registered: int = 0
    claims_evaluable: int = 0
    claims_insufficient: int = 0
    outcomes_matured: tuple[tuple[int, int], ...] = ()
    pending: int = 0
    missed_dates: tuple[date, ...] = ()
    last_tail: datetime | None = None


@dataclass(frozen=True)
class HealthReport:
    """Operational health of one prospective root. Level 1 only."""

    status: str
    root_exists: bool
    ledger_exists: bool
    collection_id: str
    collection_fingerprint: str
    universe: tuple[str, ...]
    interval: str
    basis: str
    integrity: str
    provenance: ProvenanceReport = field(
        default_factory=lambda: unknown_report("not_activated"))
    provenance_policy_fingerprint: str = PROVENANCE_V1.fingerprint
    corrupt_component: str | None = None
    corrupt_line: int | None = None
    activated_at: datetime | None = None
    manifest_fingerprint_match: bool | None = None
    live_configuration_match: bool | None = None
    collector_git_commit: str | None = None
    m2_preregistration_git_commit: str | None = None
    m2_binding: str = "unavailable"
    dependency_environment: str = "unavailable"
    runtime_python_implementation: str = "unavailable"
    runtime_python_version: str = "unavailable"
    runtime_dependencies: str = "unavailable"
    runtime_dependency_fingerprint: str | None = None
    runtime_import_path_overrides: tuple[str, ...] = ()
    symbols: tuple[SymbolHealth, ...] = ()
    runs_total: int = 0
    runs_completed: int = 0
    runs_outside_window: int = 0
    runs_config_mismatch: int = 0
    runs_refused_collector: int = 0
    runs_refused_provenance: int = 0
    runs_refused_dependencies: int = 0
    runs_interrupted: int = 0
    last_run: datetime | None = None
    last_success: datetime | None = None
    status_counts: tuple[tuple[str, int], ...] = ()


_COLLECTOR_REFUSALS = frozenset({RunStatus.COLLECTOR_COMMIT_MISMATCH,
                                 RunStatus.DIRTY_COLLECTOR_TREE,
                                 RunStatus.COLLECTOR_UNVERIFIED})
_PROVENANCE_REFUSALS = frozenset({RunStatus.PROVENANCE_INVALID, RunStatus.PROVENANCE_UNKNOWN})
_DEPENDENCY_REFUSAL_STATUSES = frozenset(_DEPENDENCY_REFUSALS.values())


def m2_binding_status(repository: RepositoryProbe | None = None) -> str:
    """``ok``, ``mismatch`` or ``unavailable`` (Git could not answer) for the M2A binding."""
    try:
        return "mismatch" if m2_binding_mismatches(_probe(repository)) else "ok"
    except RepositoryProbeError:
        return "unavailable"


def health(
    store: ProspectiveStore,
    *,
    definition: CollectionDefinition = COLLECTION_V1,
    repository: RepositoryProbe | None = None,
    dependency_environment: DependencySource | None = None,
) -> HealthReport:
    """Read-only, offline. Never constructs a provider; never creates anything.

    Inspects the run log and the ledger only under a shared, non-blocking
    lock: while a collector holds the root exclusively, the report is
    ``collect_in_progress`` with provenance ``unknown`` -- never a false
    corruption or provenance finding from a half-written state.

    ``m2_binding`` (local Git, before and after activation) and
    ``dependency_environment`` (installed vs the manifest's; ``unavailable``
    before activation) are ``ok``, ``mismatch`` or ``unavailable``.

    The ``runtime_*`` fields describe the CURRENT interpreter, before and after
    activation, so an interactive shell and the scheduler's environment can be
    compared field by field before activating: implementation, version,
    import-path overrides and the dependency fingerprint an activation here
    would record (``runtime_dependencies=unavailable`` and no
    fingerprint when it cannot be verified). They are never the manifest's.
    """
    runtime = runtime_identity(dependency_environment)
    base = dict(
        runtime_python_implementation=runtime.python_implementation,
        runtime_python_version=runtime.python_version,
        runtime_dependencies="unavailable" if runtime.environment is None else "ok",
        runtime_dependency_fingerprint=runtime.dependency_fingerprint,
        runtime_import_path_overrides=runtime.import_path_overrides,
        m2_binding=m2_binding_status(repository),
        root_exists=store.root_exists(),
        ledger_exists=store.ledger_exists(),
        collection_id=definition.collection_id,
        collection_fingerprint=definition.fingerprint,
        universe=definition.universe,
        interval=definition.interval,
        basis=definition.basis,
        live_configuration_match=not live_configuration_mismatches(definition),
        provenance_policy_fingerprint=provenance_policy_for(definition).fingerprint,
    )
    try:
        manifest = store.read_manifest()
    except ManifestCorruption:
        return HealthReport(status="invalid_manifest", integrity="corrupt",
                            corrupt_component="manifest",
                            provenance=unknown_report("integrity_corrupt"), **base)
    if manifest is None:
        return HealthReport(status="not_activated", integrity="ok",
                            provenance=unknown_report("not_activated"), **base)

    identity = dict(
        activated_at=manifest.activated_at,
        manifest_fingerprint_match=not manifest_mismatches(manifest, definition),
        collector_git_commit=manifest.collector_git_commit,
        m2_preregistration_git_commit=manifest.m2_preregistration_git_commit,
        dependency_environment=_environment_status(runtime.environment, manifest),
    )
    try:
        with store.shared_lock():
            return _health_locked(store, manifest, definition, base, identity)
    except RootLockedError:
        return HealthReport(status="collect_in_progress", integrity="unknown",
                            provenance=unknown_report("collect_in_progress"),
                            **identity, **base)
    except LockMissingError:
        return HealthReport(status="lock_missing", integrity="unknown",
                            corrupt_component="lock",
                            provenance=unknown_report("lock_missing"), **identity, **base)


def _health_locked(store, manifest, definition, base, identity) -> HealthReport:
    integrity, component, line = "ok", None, None
    try:
        run_log = store.read_run_log()
    except RunLogCorruption as exc:
        integrity, component, line = "corrupt", "run_log", exc.line_number
        run_log = ()
    runs = [entry for entry in run_log if isinstance(entry, RunRecord)]
    completed_ids = {r.run_id for r in runs if r.run_status is RunStatus.COMPLETED}

    missed_by_symbol: dict[str, set[datetime]] = {}
    status_counts: dict[str, int] = {}
    for record in runs:
        for entry in record.symbols:
            status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1
            missed_by_symbol.setdefault(entry.symbol, set()).update(entry.missed_tails)

    ledger = build_outcome_ledger(store.ledger_root)
    horizons = definition.outcome_horizons
    spec_fingerprints = set(definition.outcome_spec_fingerprints)
    interval = Interval.parse(definition.interval)
    symbols: list[SymbolHealth] = []
    partitions: list[_PartitionRecords] = []
    for symbol in definition.universe:
        partition = LedgerPartition(symbol=symbol, interval=interval, basis=BASIS)
        exists = ledger.partition_dir(partition).is_dir()
        try:
            artifacts = tuple(ledger.iter_artifacts(partition))
            outcomes = tuple(ledger.iter_outcomes(partition))
        except LedgerCorruption as exc:
            if integrity == "ok":
                integrity, component, line = "corrupt", f"ledger:{symbol}", exc.line_number
            symbols.append(SymbolHealth(symbol=symbol, readable=False))
            continue
        partitions.append(_PartitionRecords(symbol, exists, artifacts, outcomes))
        registered = {artifact.timestamp for artifact in artifacts}
        evaluable = sum(1 for artifact in artifacts if artifact.is_evaluable)
        matured = tuple(
            (horizon, sum(
                1 for outcome in outcomes
                if outcome.horizon_bars == horizon
                and outcome.evaluation_version == definition.evaluation_version
                and outcome.spec_fingerprint in spec_fingerprints
            ))
            for horizon in horizons
        )
        missed = sorted(missed_by_symbol.get(symbol, set()) - registered)
        symbols.append(SymbolHealth(
            symbol=symbol,
            readable=True,
            claims_total=len(artifacts),
            tails_registered=len(registered),
            claims_evaluable=evaluable,
            claims_insufficient=len(artifacts) - evaluable,
            outcomes_matured=matured,
            pending=evaluable * len(horizons) - sum(count for _, count in matured),
            missed_dates=tuple(new_york_date(value) for value in missed),
            last_tail=max(registered) if registered else None,
        ))

    if integrity != "ok":
        provenance = unknown_report("integrity_corrupt")
    else:
        provenance = _verify(manifest, run_log, definition, partitions,
                             _ledger_entries(store))

    if integrity != "ok":
        status = "corrupt"
    elif not (identity["manifest_fingerprint_match"] and base["live_configuration_match"]):
        status = "config_mismatch"
    else:
        status = "active"
    successes = [record.finished_at for record in runs if record.succeeded]
    return HealthReport(
        status=status,
        integrity=integrity,
        provenance=provenance,
        corrupt_component=component,
        corrupt_line=line,
        symbols=tuple(symbols),
        runs_total=len(runs),
        runs_completed=len(completed_ids),
        runs_outside_window=sum(1 for r in runs
                                if r.run_status is RunStatus.OUTSIDE_COLLECTION_WINDOW),
        runs_config_mismatch=sum(1 for r in runs if r.run_status is RunStatus.CONFIG_MISMATCH),
        runs_refused_collector=sum(1 for r in runs if r.run_status in _COLLECTOR_REFUSALS),
        runs_refused_provenance=sum(1 for r in runs if r.run_status in _PROVENANCE_REFUSALS),
        runs_refused_dependencies=sum(1 for r in runs
                                      if r.run_status in _DEPENDENCY_REFUSAL_STATUSES),
        runs_interrupted=sum(1 for entry in run_log if isinstance(entry, RunStart)
                             and entry.run_id not in completed_ids),
        last_run=runs[-1].finished_at if runs else None,
        last_success=successes[-1] if successes else None,
        status_counts=tuple(sorted(status_counts.items())),
        **identity,
        **base,
    )


__all__ = [
    "DEFAULT_PROSPECTIVE_ROOT",
    "ProspectiveError",
    "ActivationRefused",
    "RepositoryProbe",
    "build_prospective_store",
    "default_repository_probe",
    "collection_definition",
    "live_configuration_mismatches",
    "manifest_mismatches",
    "m2_binding_mismatches",
    "m2_binding_status",
    "dependency_environment_status",
    "activate",
    "current_dependency_environment",
    "current_import_path_overrides",
    "RuntimeIdentity",
    "runtime_identity",
    "CollectionReport",
    "ProvenanceReport",
    "collect",
    "evaluate_provenance",
    "SymbolHealth",
    "HealthReport",
    "health",
]
