"""Prospective provenance v1: can every ledger record be attributed to the supported collector?

The prospective ledger is an ordinary Phase 12 ledger, and the generic
``outcome_refresh`` can be pointed at it. Phase 12 is deliberately left
unchanged, so this module does not *prevent* such a write -- it *detects*
it, and the application refuses to collect (and a future validation refuses
to open) while any is present.

Detection rests on one exact link that already exists. The supported
collector calls the unchanged ``refresh_outcomes`` with
``now=snapshot.built_at``, and ``refresh_outcomes`` stamps that clock on
every artifact it registers (``recorded_at``) and every outcome it appends
(``evaluated_at``). The collector also records ``built_at`` and ``tail`` for
each symbol in its run record. So a legitimate claim has a completed
symbol-run with ``built_at == recorded_at`` and ``tail == timestamp``, and a
legitimate outcome has one with ``built_at == evaluated_at``; the run
record's counts say how many of each that clock reading produced. A write by
any other tool carries its own clock reading, which no run record holds.

Everything here is **pure** and **blind**: it receives normalised metadata
(:class:`ClaimMeta`, :class:`OutcomeMeta`, ledger entry names) built by the
application from the ledger, plus the run log and manifest facts, and
returns a :class:`ProvenanceReport` of statuses, reason codes, counts and
positions. It never sees a research state, a reason code, a price, a return
or any aggregate; the metadata types have no field that could carry one.

Statuses
--------
``ok``        every record reconciles to a completed run.
``degraded``  every record passes every per-record check, and the records
              that do not reconcile to a completed run lie inside the
              interval of an *interrupted* run (a run start with no
              completed record) under the conservative rule below. They are
              listed for exclusion; collection may continue.
``invalid``   at least one record cannot be attributed (or the run log
              contradicts itself or the ledger). Collection and validation
              stop. Nothing is repaired, deleted or rewritten.
``unknown``   provenance could not be evaluated (not activated, a collector
              is running, or the evidence is unreadable). Produced by the
              application, never by :func:`verify_provenance`.

Interrupted runs
----------------
A run start never blesses a record by itself. An unreconciled record is
attributed to interrupted run ``S`` only if: it passes every per-record
check; its clock reading ``t`` satisfies
``S.started_at - interrupted_run_backward_tolerance_seconds <= t``, ``t`` is
before the next run-log entry's start, ``t`` is on the same New York date as
``S.started_at`` and within :attr:`ProvenancePolicy.interrupted_run_max_seconds`
of it; and, per symbol, everything attributed to ``S`` shares a single clock
reading (one snapshot per symbol per run), a single tail, at most
``claims_per_tail`` claims, and outcomes whose clock equals that of the
symbol's orphan claims when there are any. Anything else is ``invalid``.

Wall clocks
-----------
Every persisted time is a wall-clock reading, and a host clock can step
backward (time synchronisation, wake from sleep). Attribution therefore never
depends on the *order* of readings taken inside one run: a completed run is
proved by run-id pairing and exact equality (``built_at == recorded_at`` /
``evaluated_at``, ``tail == timestamp``), not by ``started_at <= built_at <=
finished_at``. The one place a same-run ordering is needed -- placing a crash
orphan after its run start -- allows a small, frozen backward tolerance.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from .definition import (
    COLLECTION_V1,
    CollectionDefinition,
    in_collection_window,
    is_current_tail,
    is_new_york_midnight,
    is_pre_activation,
    new_york_date,
)
from .records import CollectionStatus, RunRecord, RunStart, RunStatus

POLICY_ID = "prospective_provenance_v1"
POLICY_SCHEMA_VERSION = 1

# -- vocabulary ----------------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_INVALID = "invalid"
STATUS_UNKNOWN = "unknown"
STATUSES = (STATUS_OK, STATUS_DEGRADED, STATUS_INVALID, STATUS_UNKNOWN)

#: Reasons that make provenance ``invalid``.
INVALID_REASONS = (
    "unmatched_claim",
    "unmatched_outcome",
    "claim_outside_window",
    "outcome_outside_window",
    "pre_activation_claim",
    "late_claim",
    "claim_timestamp_convention",
    "unexpected_partition",
    "unexpected_source",
    "unexpected_origin",
    "unexpected_producer",
    "unexpected_outcome_spec",
    "artifact_count_mismatch",
    "outcome_count_mismatch",
    "missing_claimed_artifacts",
    "missing_claimed_outcomes",
    "run_record_inconsistent",
    "collector_commit_mismatch",
)
#: The one reason that makes provenance ``degraded``.
DEGRADED_REASONS = ("interrupted_run",)
#: Reasons the application attaches to ``unknown``.
UNKNOWN_REASONS = ("not_activated", "collect_in_progress", "integrity_corrupt",
                   "lock_missing")
REASONS = INVALID_REASONS + DEGRADED_REASONS + UNKNOWN_REASONS

#: Symbol-run statuses whose run reached ``refresh_outcomes`` and may have written.
_REFRESHED = frozenset({
    CollectionStatus.OK,
    CollectionStatus.DUPLICATE_ALREADY_EXISTS,
    CollectionStatus.INSUFFICIENT_HISTORY,
    CollectionStatus.REFRESH_FAILURE,
    CollectionStatus.CORRUPT_LEDGER,
})
#: Of those, the ones whose counts are exact (the refresh returned a result).
#: A refresh that raised (REFRESH_FAILURE / CORRUPT_LEDGER at stage ``outcomes``)
#: has no counts -- the accepted N10 limitation -- and is bounded instead.
_EXACT = frozenset({
    CollectionStatus.OK,
    CollectionStatus.DUPLICATE_ALREADY_EXISTS,
    CollectionStatus.INSUFFICIENT_HISTORY,
})

#: How far (seconds) a crash orphan's clock reading may precede its run start and
#: still be attributed to it: a host wall clock stepping backward during the run.
#: Completed runs need no tolerance at all (attribution is by exact equality).
INTERRUPTED_RUN_BACKWARD_TOLERANCE_SECONDS = 5

#: Files the ledger may contain, per partition directory.
LEDGER_FILES = ("artifacts.jsonl", "outcomes.jsonl")
#: Names ignored anywhere under the ledger root (operating-system metadata
#: written by a file browser; they hold no record and are never read).
IGNORED_LEDGER_NAMES = (".DS_Store",)


# -- the policy ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvenancePolicy:
    """What a legitimate Prospective Collection v1 ledger looks like. Frozen; fingerprinted."""

    policy_id: str
    schema_version: int
    collection_id: str
    collection_fingerprint: str
    universe: tuple[str, ...]
    interval: str
    basis: str
    provider: str
    origin: str
    hypotheses: tuple[tuple[str, int, str], ...]
    assessment_policy_fingerprint: str
    assessment_rule: str
    claims_per_tail: int
    outcome_horizons: tuple[int, ...]
    outcome_spec_fingerprints: tuple[str, ...]
    evaluation_version: int
    collection_timezone: str
    collection_window_start: str
    collection_window_end: str
    daily_bar_timestamp_convention: str
    activation_boundary_rule: str
    current_tail_rule: str
    claim_run_evidence_rule: str
    outcome_run_evidence_rule: str
    interrupted_run_treatment: str
    interrupted_run_max_seconds: int
    interrupted_run_backward_tolerance_seconds: int
    interrupted_run_attribution_rule: str
    run_log_consistency_rule: str
    ledger_files: tuple[str, ...]
    ignored_ledger_names: tuple[str, ...]
    statuses: tuple[str, ...]
    invalid_reasons: tuple[str, ...]
    degraded_reasons: tuple[str, ...]
    unknown_reasons: tuple[str, ...]

    def canonical_form(self) -> dict[str, object]:
        return {
            "activation_boundary_rule": self.activation_boundary_rule,
            "assessment_policy_fingerprint": self.assessment_policy_fingerprint,
            "assessment_rule": self.assessment_rule,
            "basis": self.basis,
            "claim_run_evidence_rule": self.claim_run_evidence_rule,
            "claims_per_tail": self.claims_per_tail,
            "collection_fingerprint": self.collection_fingerprint,
            "collection_id": self.collection_id,
            "collection_timezone": self.collection_timezone,
            "collection_window_end": self.collection_window_end,
            "collection_window_start": self.collection_window_start,
            "current_tail_rule": self.current_tail_rule,
            "daily_bar_timestamp_convention": self.daily_bar_timestamp_convention,
            "degraded_reasons": list(self.degraded_reasons),
            "evaluation_version": self.evaluation_version,
            "hypotheses": [
                {"fingerprint": fp, "hypothesis_id": hid, "version": version}
                for hid, version, fp in self.hypotheses
            ],
            "ignored_ledger_names": list(self.ignored_ledger_names),
            "interrupted_run_attribution_rule": self.interrupted_run_attribution_rule,
            "interrupted_run_backward_tolerance_seconds":
                self.interrupted_run_backward_tolerance_seconds,
            "interrupted_run_max_seconds": self.interrupted_run_max_seconds,
            "interrupted_run_treatment": self.interrupted_run_treatment,
            "interval": self.interval,
            "invalid_reasons": list(self.invalid_reasons),
            "ledger_files": list(self.ledger_files),
            "origin": self.origin,
            "outcome_horizons": list(self.outcome_horizons),
            "outcome_run_evidence_rule": self.outcome_run_evidence_rule,
            "outcome_spec_fingerprints": list(self.outcome_spec_fingerprints),
            "policy_id": self.policy_id,
            "provider": self.provider,
            "run_log_consistency_rule": self.run_log_consistency_rule,
            "schema_version": self.schema_version,
            "statuses": list(self.statuses),
            "universe": list(self.universe),
            "unknown_reasons": list(self.unknown_reasons),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_form(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)

    @property
    def fingerprint(self) -> str:
        """Full SHA-256 of the canonical JSON."""
        return hashlib.sha256(self.canonical_json().encode("ascii")).hexdigest()

    @property
    def permitted_producers(self) -> frozenset[tuple]:
        return frozenset(
            {("observation", hid, version, fp) for hid, version, fp in self.hypotheses}
            | {("assessment", self.assessment_policy_fingerprint)}
        )

    @property
    def spec_horizons(self) -> dict[str, int]:
        return dict(zip(self.outcome_spec_fingerprints, self.outcome_horizons))


def provenance_policy_for(definition: CollectionDefinition) -> ProvenancePolicy:
    """The v1 provenance policy for one collection definition."""
    return ProvenancePolicy(
        policy_id=POLICY_ID,
        schema_version=POLICY_SCHEMA_VERSION,
        collection_id=definition.collection_id,
        collection_fingerprint=definition.fingerprint,
        universe=definition.universe,
        interval=definition.interval,
        basis=definition.basis,
        provider=definition.provider,
        origin="snapshot",
        hypotheses=tuple((p.hypothesis_id, p.version, p.fingerprint)
                         for p in definition.hypotheses),
        assessment_policy_fingerprint=definition.policy_fingerprint,
        assessment_rule=definition.assessment_rule,
        claims_per_tail=definition.claims_per_tail,
        outcome_horizons=definition.outcome_horizons,
        outcome_spec_fingerprints=definition.outcome_spec_fingerprints,
        evaluation_version=definition.evaluation_version,
        collection_timezone=definition.collection_timezone,
        collection_window_start=definition.collection_window_start,
        collection_window_end=definition.collection_window_end,
        daily_bar_timestamp_convention=definition.daily_bar_timestamp_convention,
        activation_boundary_rule=(
            "claim bar settles strictly after activated_at and recorded_at is after activated_at"),
        current_tail_rule=(
            "no weekday strictly between the claim bar's ET date and recorded_at's ET date, "
            "and the bar's ET date is before recorded_at's ET date"),
        claim_run_evidence_rule=(
            "a completed run record holds a symbol-run that reached refresh_outcomes with "
            "built_at == recorded_at and tail == timestamp; per built_at the claim count "
            "equals artifacts_new when the refresh returned, else at most claims_per_tail; "
            "data_cutoff == timestamp"),
        outcome_run_evidence_rule=(
            "the outcome's artifact is in the partition; a completed run record holds a "
            "symbol-run that reached refresh_outcomes with built_at == evaluated_at; per "
            "built_at the outcome count equals outcomes_new when the refresh returned; "
            "evaluated_at after the artifact's recorded_at"),
        interrupted_run_treatment="degraded_excluded",
        interrupted_run_max_seconds=3600,
        interrupted_run_backward_tolerance_seconds=INTERRUPTED_RUN_BACKWARD_TOLERANCE_SECONDS,
        interrupted_run_attribution_rule=(
            "a record that fails to reconcile with a completed run is attributed to an "
            "interrupted run (a run start with no completed record) only if it passes every "
            "per-record check; its clock reading is at or after the run start minus "
            "interrupted_run_backward_tolerance_seconds, before the started_at of the next "
            "run-log entry, on the same America/New_York date as the run start and at most "
            "interrupted_run_max_seconds after it; per interrupted run and symbol all its "
            "claims share one clock reading and one tail and number at most claims_per_tail, "
            "and its outcomes share one clock reading equal to those claims' when there are "
            "any; outcomes of excluded claims are excluded; anything else is invalid"),
        run_log_consistency_rule=(
            "run ids are unique; every completed record follows its own run start with the "
            "same run_id and started_at, and the run start carries the manifest's collection "
            "fingerprint, activation time, collector commit and universe and this policy's "
            "fingerprint, started inside the window after activation; a completed record "
            "lists the universe in order and its refreshed (symbol, built_at) pairs are "
            "unique; a refusal record has no symbols and no run start; every record carries "
            "the manifest's activation time and collector commit; no ordering between "
            "started_at, built_at and finished_at within one run is required"),
        ledger_files=LEDGER_FILES,
        ignored_ledger_names=IGNORED_LEDGER_NAMES,
        statuses=STATUSES,
        invalid_reasons=INVALID_REASONS,
        degraded_reasons=DEGRADED_REASONS,
        unknown_reasons=UNKNOWN_REASONS,
    )


# -- normalised metadata -------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimMeta:
    """The provenance-relevant facts of one ledger artifact. No state, no reason codes."""

    symbol: str
    line: int
    key: str
    producer: tuple
    interval: str
    basis: str
    timestamp: datetime
    data_cutoff: datetime
    recorded_at: datetime
    source: str
    origin: str


@dataclass(frozen=True)
class OutcomeMeta:
    """The provenance-relevant facts of one ledger outcome. No price, no return."""

    symbol: str
    line: int
    key: str
    artifact_key: str
    spec_fingerprint: str
    horizon_bars: int
    evaluation_version: int
    evaluated_at: datetime


@dataclass(frozen=True)
class PartitionMeta:
    """One expected partition's records, in file order (``line`` is the file line)."""

    symbol: str
    claims: tuple[ClaimMeta, ...] = ()
    outcomes: tuple[OutcomeMeta, ...] = ()


@dataclass(frozen=True)
class Finding:
    """One reason code at one position. Level 1: names, symbols and line numbers."""

    reason: str
    component: str
    symbol: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ProvenanceReport:
    """The verdict. ``excluded_*`` hold the ledger keys of degraded evidence."""

    status: str
    findings: tuple[Finding, ...] = ()
    claims_checked: int = 0
    outcomes_checked: int = 0
    runs_interrupted: int = 0
    excluded_artifact_keys: frozenset[str] = field(default_factory=frozenset)
    excluded_outcome_keys: frozenset[str] = field(default_factory=frozenset)

    @property
    def reasons(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(finding.reason for finding in self.findings)
        return tuple(sorted(counts.items()))

    @property
    def first_finding(self) -> Finding | None:
        """The first invalid finding if any, else the first finding."""
        for finding in self.findings:
            if finding.reason in INVALID_REASONS:
                return finding
        return self.findings[0] if self.findings else None

    @property
    def permits_collection(self) -> bool:
        return self.status in (STATUS_OK, STATUS_DEGRADED)

    @property
    def permits_validation(self) -> bool:
        """Whether a validation process may *proceed* -- not whether all evidence is valid.

        ``True`` for ``degraded`` means only: the process may run while
        excluding every key in :attr:`excluded_artifact_keys` and
        :attr:`excluded_outcome_keys`. Degraded evidence is never valid
        primary evidence; the validation (M2) must enforce the exclusions.
        """
        return self.status in (STATUS_OK, STATUS_DEGRADED)


def unknown_report(reason: str) -> ProvenanceReport:
    if reason not in UNKNOWN_REASONS:
        raise ValueError(f"unknown-provenance reason {reason!r} is not in the vocabulary")
    return ProvenanceReport(status=STATUS_UNKNOWN,
                            findings=(Finding(reason=reason, component="provenance"),))


# -- verification --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Interrupted:
    start: RunStart
    window_end: datetime | None  # the next run-log entry's start, if any


def _entry_start(entry: RunStart | RunRecord) -> datetime:
    return entry.started_at


def verify_provenance(
    policy: ProvenancePolicy,
    *,
    activated_at: datetime,
    collection_fingerprint: str,
    collector_git_commit: str,
    run_log: Sequence[RunStart | RunRecord],
    ledger_entries: Iterable[str],
    partitions: Iterable[PartitionMeta],
) -> ProvenanceReport:
    """Reconcile the ledger with the run log. Pure; see the module docstring.

    ``ledger_entries`` are the posix paths of every file and directory under
    the ledger root, relative to it. ``partitions`` are the expected
    partitions that exist, read strictly by the caller.
    """
    findings: list[Finding] = []
    partitions = tuple(partitions)

    def flag(reason: str, component: str, symbol: str | None = None,
             line: int | None = None) -> None:
        findings.append(Finding(reason, component, symbol, line))

    # 1. the run log, on its own and against the manifest -------------------------------------
    completed: dict[str, RunRecord] = {}
    starts: dict[str, tuple[int, RunStart]] = {}
    seen_ids: set[str] = set()
    for position, entry in enumerate(run_log, start=1):
        if isinstance(entry, RunStart):
            if entry.run_id in seen_ids:
                flag("run_record_inconsistent", "run_log", line=position)
                continue
            seen_ids.add(entry.run_id)
            starts[entry.run_id] = (position, entry)
            if (entry.collection_fingerprint != collection_fingerprint
                    or entry.collection_fingerprint != policy.collection_fingerprint
                    or entry.provenance_policy_fingerprint != policy.fingerprint
                    or entry.activated_at != activated_at
                    or entry.universe != policy.universe
                    or not in_collection_window(entry.started_at)
                    or entry.started_at <= activated_at):
                flag("run_record_inconsistent", "run_log", line=position)
            if entry.collector_git_commit != collector_git_commit:
                flag("collector_commit_mismatch", "run_log", line=position)
            continue
        # a run record
        if entry.collector_git_commit != collector_git_commit:
            flag("collector_commit_mismatch", "run_log", line=position)
        if entry.activated_at != activated_at:
            flag("run_record_inconsistent", "run_log", line=position)
        if entry.run_status is not RunStatus.COMPLETED:
            # A refusal: recorded before any provider, wrote nothing, has no symbols.
            if entry.symbols or entry.run_id in seen_ids:
                flag("run_record_inconsistent", "run_log", line=position)
            seen_ids.add(entry.run_id)
            continue
        start = starts.get(entry.run_id)
        if start is None or entry.run_id in completed:
            flag("run_record_inconsistent", "run_log", line=position)
            continue
        _, begun = start
        # Identity and pairing only. No wall-clock ordering between started_at,
        # built_at and finished_at is required: a host clock may step backward
        # during a legitimate run, and the exact built_at equalities below are
        # what attribute records to it.
        if (begun.started_at != entry.started_at
                or entry.collection_fingerprint != collection_fingerprint
                or entry.universe != policy.universe
                or tuple(s.symbol for s in entry.symbols) != policy.universe):
            flag("run_record_inconsistent", "run_log", line=position)
            continue
        completed[entry.run_id] = entry

    # Clock readings of every completed symbol-run that reached the refresh.
    refreshed: dict[tuple[str, datetime], object] = {}
    for record in completed.values():
        for symbol_run in record.symbols:
            if symbol_run.status not in _REFRESHED or symbol_run.built_at is None \
                    or symbol_run.tail is None:
                continue
            key = (symbol_run.symbol, symbol_run.built_at)
            if key in refreshed:
                flag("run_record_inconsistent", "run_log", symbol_run.symbol)
                continue
            refreshed[key] = symbol_run

    # Interrupted runs and the interval each may explain.
    ordered = list(run_log)
    interrupted: list[_Interrupted] = []
    for index, entry in enumerate(ordered):
        if isinstance(entry, RunStart) and entry.run_id not in completed:
            later = ordered[index + 1:]
            window_end = _entry_start(later[0]) if later else None
            interrupted.append(_Interrupted(entry, window_end))
    max_span = timedelta(seconds=policy.interrupted_run_max_seconds)
    backward = timedelta(seconds=policy.interrupted_run_backward_tolerance_seconds)

    def interrupted_run_for(moment: datetime) -> _Interrupted | None:
        for candidate in reversed(interrupted):
            begun = candidate.start.started_at
            if begun - backward <= moment and (candidate.window_end is None
                                               or moment < candidate.window_end) \
                    and moment - begun <= max_span \
                    and new_york_date(moment) == new_york_date(begun):
                return candidate
        return None

    # 2. the ledger's shape --------------------------------------------------------------------
    allowed: set[str] = set()
    for symbol in policy.universe:
        base = f"{symbol}/{policy.interval}/{policy.basis}"
        allowed.update({symbol, f"{symbol}/{policy.interval}", base})
        allowed.update(f"{base}/{name}" for name in policy.ledger_files)
    for entry_name in sorted(ledger_entries):
        if entry_name.rsplit("/", 1)[-1] in policy.ignored_ledger_names:
            continue
        if entry_name not in allowed:
            flag("unexpected_partition", f"ledger:{entry_name}")

    # 3. claims and outcomes -------------------------------------------------------------------
    producers = policy.permitted_producers
    spec_horizons = policy.spec_horizons
    claims_checked = outcomes_checked = 0
    excluded_artifacts: set[str] = set()
    excluded_outcomes: set[str] = set()

    for partition in partitions:
        symbol = partition.symbol
        component = f"ledger:{symbol}:artifacts"
        claim_count_by_clock: Counter = Counter()
        claims_by_key: dict[str, ClaimMeta] = {}
        orphan_claims: dict[str, list[ClaimMeta]] = defaultdict(list)
        claims_by_tail: Counter = Counter()

        for claim in partition.claims:
            claims_checked += 1
            claims_by_key[claim.key] = claim
            claims_by_tail[claim.timestamp] += 1
            problems: list[str] = []
            if claim.symbol != symbol or claim.interval != policy.interval \
                    or claim.basis != policy.basis:
                problems.append("unexpected_partition")
            if claim.source != policy.provider:
                problems.append("unexpected_source")
            if claim.origin != policy.origin:
                problems.append("unexpected_origin")
            if claim.producer not in producers:
                problems.append("unexpected_producer")
            if claim.data_cutoff != claim.timestamp or not is_new_york_midnight(claim.timestamp):
                problems.append("claim_timestamp_convention")
            if not in_collection_window(claim.recorded_at):
                problems.append("claim_outside_window")
            if is_pre_activation(claim.timestamp, activated_at) \
                    or claim.recorded_at <= activated_at:
                problems.append("pre_activation_claim")
            if not is_current_tail(claim.timestamp, claim.recorded_at):
                problems.append("late_claim")
            for reason in problems:
                flag(reason, component, symbol, claim.line)

            symbol_run = refreshed.get((symbol, claim.recorded_at))
            if symbol_run is not None and symbol_run.tail == claim.timestamp:
                claim_count_by_clock[claim.recorded_at] += 1
                continue
            candidate = None if problems else interrupted_run_for(claim.recorded_at)
            if candidate is None or symbol_run is not None:
                flag("unmatched_claim", component, symbol, claim.line)
                continue
            orphan_claims[candidate.start.run_id].append(claim)

        for tail, count in claims_by_tail.items():
            if count > policy.claims_per_tail:
                flag("artifact_count_mismatch", component, symbol)

        # orphan claims: one snapshot (clock + tail) per interrupted run and symbol
        orphan_clock: dict[str, datetime] = {}
        for run_id, group in orphan_claims.items():
            clocks = {c.recorded_at for c in group}
            tails = {c.timestamp for c in group}
            if len(clocks) != 1 or len(tails) != 1 or len(group) > policy.claims_per_tail:
                for claim in group:
                    flag("unmatched_claim", component, symbol, claim.line)
                continue
            orphan_clock[run_id] = next(iter(clocks))
            for claim in group:
                excluded_artifacts.add(claim.key)
                flag("interrupted_run", component, symbol, claim.line)

        # outcomes
        component = f"ledger:{symbol}:outcomes"
        outcome_count_by_clock: Counter = Counter()
        orphan_outcomes: dict[str, list[OutcomeMeta]] = defaultdict(list)
        for outcome in partition.outcomes:
            outcomes_checked += 1
            problems = []
            claim = claims_by_key.get(outcome.artifact_key)
            if outcome.symbol != symbol:
                problems.append("unexpected_partition")
            if spec_horizons.get(outcome.spec_fingerprint) != outcome.horizon_bars \
                    or outcome.evaluation_version != policy.evaluation_version:
                problems.append("unexpected_outcome_spec")
            if not in_collection_window(outcome.evaluated_at):
                problems.append("outcome_outside_window")
            for reason in problems:
                flag(reason, component, symbol, outcome.line)
            if claim is None or outcome.evaluated_at <= claim.recorded_at:
                flag("unmatched_outcome", component, symbol, outcome.line)
                continue
            if claim.key in excluded_artifacts:
                excluded_outcomes.add(outcome.key)
            if (symbol, outcome.evaluated_at) in refreshed:
                outcome_count_by_clock[outcome.evaluated_at] += 1
                continue
            candidate = None if problems else interrupted_run_for(outcome.evaluated_at)
            if candidate is None:
                flag("unmatched_outcome", component, symbol, outcome.line)
                continue
            orphan_outcomes[candidate.start.run_id].append(outcome)

        for run_id, group in orphan_outcomes.items():
            clocks = {o.evaluated_at for o in group}
            expected = orphan_clock.get(run_id)
            if len(clocks) != 1 or (expected is not None and clocks != {expected}):
                for outcome in group:
                    flag("unmatched_outcome", component, symbol, outcome.line)
                continue
            for outcome in group:
                excluded_outcomes.add(outcome.key)
                flag("interrupted_run", component, symbol, outcome.line)

        # counts against the run records, for every refreshed clock of this symbol
        _check_counts(policy, symbol, refreshed, claim_count_by_clock, outcome_count_by_clock,
                      flag)

    # Partitions that do not exist but whose runs say they wrote something.
    present = {p.symbol for p in partitions}
    for (symbol, _), symbol_run in refreshed.items():
        if symbol in present:
            continue
        if symbol_run.status in _EXACT and (symbol_run.artifacts_new or 0) > 0:
            flag("missing_claimed_artifacts", f"ledger:{symbol}:artifacts", symbol)
        if symbol_run.status in _EXACT and (symbol_run.outcomes_new or 0) > 0:
            flag("missing_claimed_outcomes", f"ledger:{symbol}:outcomes", symbol)

    invalid = any(f.reason in INVALID_REASONS for f in findings)
    degraded = any(f.reason in DEGRADED_REASONS for f in findings)
    status = STATUS_INVALID if invalid else STATUS_DEGRADED if degraded else STATUS_OK
    return ProvenanceReport(
        status=status,
        findings=tuple(findings),
        claims_checked=claims_checked,
        outcomes_checked=outcomes_checked,
        runs_interrupted=len(interrupted),
        excluded_artifact_keys=frozenset(excluded_artifacts),
        excluded_outcome_keys=frozenset(excluded_outcomes),
    )


def _check_counts(policy, symbol, refreshed, claim_counts, outcome_counts, flag) -> None:
    for (run_symbol, clock), symbol_run in refreshed.items():
        if run_symbol != symbol:
            continue
        claims = claim_counts.get(clock, 0)
        outcomes = outcome_counts.get(clock, 0)
        if symbol_run.status in _EXACT:
            expected_claims = symbol_run.artifacts_new or 0
            expected_outcomes = symbol_run.outcomes_new or 0
            if claims < expected_claims:
                flag("missing_claimed_artifacts", f"ledger:{symbol}:artifacts", symbol)
            elif claims > expected_claims:
                flag("artifact_count_mismatch", f"ledger:{symbol}:artifacts", symbol)
            if outcomes < expected_outcomes:
                flag("missing_claimed_outcomes", f"ledger:{symbol}:outcomes", symbol)
            elif outcomes > expected_outcomes:
                flag("outcome_count_mismatch", f"ledger:{symbol}:outcomes", symbol)
        elif claims > policy.claims_per_tail:
            flag("artifact_count_mismatch", f"ledger:{symbol}:artifacts", symbol)


#: The provenance policy of Prospective Collection v1. Its fingerprint is pinned by a test.
PROVENANCE_V1: ProvenancePolicy = provenance_policy_for(COLLECTION_V1)


__all__ = [
    "POLICY_ID",
    "POLICY_SCHEMA_VERSION",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "STATUS_INVALID",
    "STATUS_UNKNOWN",
    "STATUSES",
    "INVALID_REASONS",
    "DEGRADED_REASONS",
    "UNKNOWN_REASONS",
    "REASONS",
    "LEDGER_FILES",
    "IGNORED_LEDGER_NAMES",
    "INTERRUPTED_RUN_BACKWARD_TOLERANCE_SECONDS",
    "ProvenancePolicy",
    "provenance_policy_for",
    "PROVENANCE_V1",
    "ClaimMeta",
    "OutcomeMeta",
    "PartitionMeta",
    "Finding",
    "ProvenanceReport",
    "unknown_report",
    "verify_provenance",
]
