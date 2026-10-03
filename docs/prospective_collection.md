# Prospective Collection v1

Research-controlled, prospective collection of the existing pipeline's
claims over a frozen universe, into its own Phase 12 ledger, with blind
operational visibility. Decision record:
**[ADR 0013](adr/0013-prospective-collection-and-holdout.md)**.

> **Status: implemented, not activated.** No activation manifest exists, no
> claim has been collected and no scheduler is installed. Activation is
> blocked until (1) the M2 future-validation pre-registration is frozen and
> remote-durable, (2) a human explicitly approves activation, (3) a
> dedicated collector clone is checked out at the collector commit (see
> Scheduler setup), and (4) the local scheduler is set up. The N2
> provenance hardening is implemented: a write into this ledger by any
> other tool — e.g. the generic `outcome_refresh` — is **detected**, and
> collection refuses while it is present (see Provenance). Nothing below
> describes something that has already been run.

It is research bookkeeping. It trades nothing, recommends nothing and
computes no performance figure.

## Architecture

```
src/prospective/definition.py   COLLECTION_V1 + fingerprint; ET window, timestamp,
                                activation, current-tail and missed-tail rules (pure)
src/prospective/records.py      ActivationManifest, RunRecord, SymbolRun, statuses (Level 1)
src/prospective/store.py        collect.lock + activation.json (write-once), runs.jsonl, locks
src/prospective/environment.py  git HEAD / clean / ancestry probe; dependency versions
src/prospective/provenance.py   PROVENANCE_V1 + fingerprint; pure ledger/run-log reconciliation
src/application/prospective.py  activate / collect / health orchestration
src/cli/prospective.py          python -m src.cli.prospective {activate,collect,health}
```

The outcome ledger itself is Phase 12's, unchanged
([docs/outcomes.md](outcomes.md)). `collect` reaches it only through the
unchanged `refresh_outcomes`, which registers the current tail's claims and
evaluates earlier ones exactly as the dashboard does — but against this
collection's own root, and only when the wrapper has decided the call is
legal.

`COLLECTION_V1`: SPY, QQQ, IWM, TLT, GLD (in that order); `1d`; RAW; settled
bars only; provider `yfinance`; the three existing hypotheses (fingerprints
650add07184f8440, 6589cb8021b76574, f1126ca778e6f7ce);
`directional_presence_v1`, minimum 2; horizons 1, 5, 20; evaluation
version 1; holdout start 2025-03-01; window 00:30–09:00 America/New_York.
Fingerprint `af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8`.

## Location

```
data/prospective/v1/activation.json   write-once activation manifest
data/prospective/v1/runs.jsonl        Level-1 run starts and one run record per collect attempt
data/prospective/v1/collect.lock      flock target, holds no data; created by activate
data/prospective/v1/ledger/<SYM>/1d/raw/{artifacts,outcomes}.jsonl
data/prospective/logs/                launchd stdout/stderr (outside the v1 root)
```

All of `data/prospective/` is git-ignored. It is **not** `data/outcomes/`:
the dashboard's Refresh keeps writing there and can never write here. The
CLI has no root flag; tests inject temporary roots programmatically.

## Commands

### `activate` (once, human-approved, no network)

```
python -m src.cli.prospective activate \
  --collector-git-commit <40-hex HEAD> \
  --m2-preregistration-git-commit <40-hex frozen M2 commit>
```

Writes the empty `collect.lock` and then `activation.json`, once, and
nothing else (the lock first, so an activated root always has the lock
`health` and `collect` require). If any write or fsync fails the command
refuses with `activation_write_failed`: activation durability could not be
confirmed, and the root may hold the lock and possibly a partial — or even
complete — `activation.json` (a failure in the final fsync comes after the
bytes were written, and `health` may then report `active`). Treat it as
unconfirmed and follow "Failed or interrupted activation" under Failure
recovery before any retry, collection or scheduler installation. Refused,
writing nothing, when: either SHA is malformed; the working tree is dirty
(including untracked files); HEAD is not the collector commit; the M2
commit is not in HEAD's history; the live code differs from
`COLLECTION_V1`; or the root is not empty (`already_activated`). The manifest records `activated_at` (one
clock reading), the collection id and fingerprint, both commits, the
holdout start, universe, interval, basis, provider, hypothesis and outcome
spec fingerprints, the evaluation version and the Python, yfinance and
pandas versions.

### `collect` (scheduled; one finite run)

```
python -m src.cli.prospective collect
```

1. Load and verify the manifest (absent → `not_activated`; unreadable →
   `invalid_manifest`; both write nothing).
2. Take the root lock exclusively, waiting up to 30 s (monotonic clock) for
   a brief `health` reader to finish (`locked` afterwards; `lock_missing`
   if the lock file is gone — no provider, no record, the lock is never
   recreated).
3. Read the run log strictly (`corrupt_run_log` otherwise: nothing is
   appended to a corrupt log, no provider).
4. Recompute `COLLECTION_V1` and check it against the manifest and the live
   code (`config_mismatch` otherwise).
5. Check the start clock against **00:30 ≤ ET < 09:00**
   (`OUTSIDE_COLLECTION_WINDOW` otherwise).
6. Check the collector itself: the working tree is clean and HEAD equals
   the manifest's `collector_git_commit` (`dirty_collector_tree`,
   `collector_commit_mismatch`, or `collector_unverified` when git cannot
   be asked).
7. Read every ledger partition strictly and reconcile it with the run log
   (see Provenance): `provenance_unknown` if a partition is unreadable,
   `provenance_invalid` if any record cannot be attributed. `degraded`
   provenance proceeds; its records stay excluded.
8. Append and fsync a **run start** (`prospective_run_start_v1`: run id,
   start clock, collection and provenance-policy fingerprints, activation
   time, collector commit, universe). Steps 4–7 refuse with one run record
   and no run start; every refusal happens before any provider exists.
9. For each symbol, in frozen order: re-check the window; build the
   snapshot (settled bars only); require the frozen provider, interval and
   basis; re-check the window on `built_at`; require every daily bar at
   00:00:00 ET; skip a `PRE_ACTIVATION` tail without touching the ledger;
   derive missed tails; refuse a `STALE_TAIL`; otherwise call the unchanged
   `refresh_outcomes`.
10. Append one run record (same run id as the start); release the lock;
   print `key=value` lines. A refusal's summary line also carries
   `provenance=` and `provenance_reasons=` when provenance was evaluated.

Exit codes: `0` every symbol collected (or was pre-activation); `1` the run
completed but at least one symbol did not; `2` refused as a whole or usage
error.

### `health` (offline, read-only, any time)

```
python -m src.cli.prospective health
```

Never constructs a provider, never fetches, never runs git, never creates a
file. Reads the manifest, then takes the lock **shared and non-blocking**
before reading the run log and the ledger strictly, so it never inspects
files a collector is mutating: while `collect` holds the lock it reports
`prospective_status=collect_in_progress` and `provenance=unknown`, never a
false corruption. Prints **Level 1** only:

```
prospective_status=active root_exists=yes ledger_exists=yes collection_id=… collection_fingerprint=…
  manifest_fingerprint_match=yes live_configuration_match=yes activated_at=… collector_git_commit=…
  m2_preregistration_git_commit=… universe=SPY,QQQ,IWM,TLT,GLD interval=1d basis=raw
symbol=SPY readable=yes claims_total=… tails_registered=… claims_evaluable=… claims_insufficient=…
  outcomes_matured_h1=… outcomes_matured_h5=… outcomes_matured_h20=… pending=…
  missed_collections=… missed_dates=… last_tail=…
runs_total=… runs_completed=… runs_outside_window=… runs_config_mismatch=…
  runs_refused_collector=… runs_refused_provenance=… runs_interrupted=… last_run=… last_success=…
  symbol_statuses=ok:…,duplicate_already_exists:…
provenance=ok provenance_reasons=none provenance_policy_fingerprint=… claims_checked=… outcomes_checked=…
integrity=ok
```

A provenance finding adds `provenance_component=`, `provenance_symbol=` and
`provenance_line=` (the first invalid finding: a component name, a symbol
and a file line number — never a record's content).

Exit codes:

| exit | when |
| --- | --- |
| `0` | not activated; or active with `provenance=ok` |
| `1` | anything needing attention: `provenance=degraded` or `invalid`, `corrupt`, `config_mismatch`, `invalid_manifest`, `lock_missing` |
| `2` | `collect_in_progress` — nothing was inspected; run `health` again after the collection |

## Status vocabulary

| Status | Meaning | Ledger touched |
| --- | --- | --- |
| `ok` | new current-tail claims registered; earlier claims evaluated | yes |
| `duplicate_already_exists` | the tail was already registered; earlier claims evaluated | evaluation only |
| `insufficient_history` | fewer bars than the warm-up; the existing path registered non-evaluable claims (state `INSUFFICIENT_DATA`) — a valid claim, not a gap | yes |
| `pre_activation` | the tail settled at or before activation | no |
| `OUTSIDE_COLLECTION_WINDOW` (`outside_collection_window`) | run or symbol outside 00:30–09:00 ET | no, and no provider call |
| `stale_tail` | a tail with any claim still unregistered, and a weekday has passed since it settled: claiming it now would be late | no |
| `timestamp_convention` | a daily bar not at 00:00:00 ET | no |
| `provider_failure` / `snapshot_failure` / `no_settled_bar` | the snapshot could not be built or was empty | no |
| `corrupt_ledger` | the partition failed its strict read | no (left as evidence) |
| `refresh_failure` / `unexpected_failure` | the refresh or a defect raised; class name only | earlier appends stay |
| `config_mismatch` | definition, manifest, live code or provider drift | no |

Refusals of a whole run (one run record, no symbols, no run start, no
provider): `outside_collection_window`, `config_mismatch`,
`collector_commit_mismatch`, `dirty_collector_tree`, `collector_unverified`,
`provenance_invalid`, `provenance_unknown`. `not_activated`,
`invalid_manifest`, `locked`, `lock_missing` and `corrupt_run_log` write
nothing at all.

`MISSED_COLLECTION` is not a symbol status: missed bars are listed as
`missed_tails` on the run that first sees them after the last claim, and
counted by `health` as `missed_collections` / `missed_dates`. They are never
claimed.

## Provenance (N2)

Policy `prospective_provenance_v1`, schema 1, fingerprint
`ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117`
(`src/prospective/provenance.py`, `PROVENANCE_V1`). It is separate from
`COLLECTION_V1`, whose fingerprint is unchanged. It freezes the collection
identity, universe, interval, basis, provider, origin, permitted producers
(the three hypothesis pins and the assessment policy), claims per tail (4),
outcome specs and evaluation version, the window, the activation-boundary
and current-tail rules, the claim and outcome run-evidence rules, the
run-log consistency rule, the interrupted-run attribution rule, treatment,
span (3600 s) and backward-clock tolerance (5 s), and the status and reason
vocabulary.

**The link.** The collector calls the unchanged `refresh_outcomes` with
`now = snapshot.built_at`, which stamps every artifact it registers
(`recorded_at`) and every outcome it appends (`evaluated_at`) with that one
clock reading; the run record holds the same `built_at` and the `tail` for
each symbol, plus how many artifacts and outcomes it wrote. Any other tool
stamps its own clock reading, which no run record holds. So, reading only
metadata (identities, timestamps, source, origin, spec, version — never a
state, reason code, price or return):

- every ledger entry is an expected path (`<SYMBOL>/1d/raw/{artifacts,outcomes}.jsonl`
  for the five symbols; `.DS_Store` files are ignored) — else `unexpected_partition`;
- every claim has the frozen source, origin and producer, `data_cutoff ==
  timestamp` at 00:00 ET, `recorded_at` inside the window, a bar that
  settled after activation, and is current for `recorded_at`;
- every claim matches a completed run's symbol-run that reached the refresh
  with `built_at == recorded_at` and `tail == timestamp` — else `unmatched_claim`;
- per such `built_at`, the claim and outcome counts equal the run's
  `artifacts_new` / `outcomes_new` (`missing_claimed_*` /
  `*_count_mismatch` otherwise). A refresh that raised (`refresh_failure`)
  records no counts (accepted limitation N10): at most 4 claims are accepted;
- every outcome belongs to a claim in the partition, has a frozen spec and
  version, `evaluated_at` inside the window and after the claim, and
  matches a completed run's `built_at` — else `unmatched_outcome`;
- the run log is consistent with itself and the manifest (unique run ids, a
  run start before each completed record, the same fingerprints, activation
  time, collector commit and universe) — else `run_record_inconsistent` /
  `collector_commit_mismatch`. A refusal record is inert (no symbols).

**Wall clocks.** Every stored time is a host wall-clock reading, and a host
clock can step backward (time synchronisation, waking from sleep). A
completed run is therefore attributed by run-id pairing and the exact
equalities above, never by the order of readings inside the run:
`started_at <= built_at <= finished_at` is **not** required, so a backward
step of any size during a legitimate run does not invalidate it.

| provenance | meaning | collect | future validation |
| --- | --- | --- | --- |
| `ok` | everything reconciles to completed runs | proceeds | may open |
| `degraded` | only `interrupted_run` findings: crash orphans, excluded | proceeds | may proceed only while excluding every degraded key |
| `invalid` | at least one record cannot be attributed | refuses (`provenance_invalid`) | cannot open |
| `unknown` | not activated, collection in progress, unreadable evidence, missing lock | refuses | cannot open |

**Interrupted runs.** A run start with no completed record means the
process died. A record it might explain is attributed to it only if the
record passes every per-record check, its clock reading lies no more than
5 s before the run start (the frozen backward-clock tolerance — a crash
orphan's snapshot clock can read slightly earlier than its run start only
if the host clock stepped back), before the next run-log entry, on the same
ET date and within 3600 s after the run start; and, per symbol, everything attributed to that run shares one
clock reading and one tail, has at most 4 claims, and its outcomes carry
the orphan claims' clock. Then provenance is `degraded` and the keys are
listed for exclusion (outcomes of excluded claims are excluded too).
Anything else is `invalid`. A run start never blesses a record by itself.
`degraded` is not a weaker kind of valid: `permits_validation` is true for
it only in the sense that a validation may *proceed while excluding every
degraded key*; degraded records are never primary evidence, and M2 must
enforce the exclusion.

**What it cannot see.** A writer that also forges a matching run-log line,
a clock collision to the microsecond with a real run, or a deleted
*completed-record* line (its claims then read as a crash: `degraded`,
excluded — never `ok`). There is no signature or hash chain; this detects
manual and accidental writes, not a determined forger.

**No repair.** Nothing is repaired, skipped, deleted or rewritten.
`invalid` is permanent for this root: collection v1 cannot resume, and a
new collection version needs a new root and a recorded decision.

## The safe collection window

A daily bar is stamped 00:00 America/New_York and settles at the following
midnight ET. A claim about it is prospective only until the next session
opens at 09:30 ET. Collection is therefore allowed only in
**00:30 ≤ ET < 09:00**; the application converts its clock to New York time
itself, whatever the machine's timezone.

A claim is recorded inside the window, or it is permanently missed. There
is no late registration and no later reconstruction.

## Holdout and lookback

2025-03-01 up to `activated_at` is a reserved interval: never claimed,
evaluated, persisted, printed or summarised by this subsystem. Each
collection's two-year fetch necessarily contains those bars as in-memory
causal lookback for SMA50/RSI14; that is their only use here.

## Blindness: what must not be viewed

- Level 1 (routine): `collect` output, `runs.jsonl`, `health`.
- Level 2 (not viewed): `ledger/**/artifacts.jsonl` (claim states) and
  `ledger/**/outcomes.jsonl` (prices and forward returns). Do not open,
  `cat`, grep or load them. A claim's state plus the public price path is
  nearly its outcome.
- Level 3 (locked): any aggregate — `summarize_outcomes`, means, sign
  counts, hit rates, comparisons by state, producer or symbol — until the
  frozen M2 pre-registration opens it.

Nothing in the supported surfaces can show Level 2 or 3: run records and
health reports have no field for a price, return or state, run-log numbers
are integers only, and exception messages are never recorded.

## Scheduler setup (after approved activation only)

Template: `config/launchd/com.ai-market-analysis.prospective-collect.plist.example`.

0. **Pinned collector clone.** Real collection runs from a dedicated clone
   of the repository checked out (detached) at exactly the collector commit
   recorded in `activation.json`, with its own virtualenv — not from the
   development checkout. `collect` refuses unless that checkout is clean
   and its HEAD equals the manifest's `collector_git_commit`, so switching
   branch, pulling or editing the development repository can never change
   the collector silently; it can only stop it. The live root is resolved
   from the code's own location, so it lives inside the pinned clone.
   Activation itself is run from that clone. Nothing creates this clone
   today.

   **The collector commit is frozen for the life of Collection v1.** Once
   v1 is activated, no code fix or change can be applied to the running
   collector in place: pulling, checking out another commit or editing
   the pinned clone makes every later `collect` refuse
   (`collector_commit_mismatch` / `dirty_collector_tree`). This is
   intentional research freezing, not a temporary operational state. A
   materially changed collector — a bug fix, a provider-adapter fix, a
   rule change — requires an explicit new collection version, a new
   provenance contract, a new root and a new human-approved activation
   decision; Collection v1 ends at that point and its evidence stays as it
   is.

   **Dependencies are recorded, not enforced.** The manifest records the
   Python, yfinance and pandas versions, but `collect` does not compare
   them: the same Git commit in a different environment could still behave
   differently. Before activation one of these must be chosen and
   recorded: (A) `collect` enforces the installed versions against the
   activation manifest, or (B) the pinned clone runs from a dedicated
   virtualenv whose exact dependencies (`requirements.txt`) are verified by
   the activation checklist and never upgraded during v1.
1. Copy the template to `~/Library/LaunchAgents/`, replace
   `__VENV_PYTHON__` and `__REPOSITORY__` with absolute paths **of the
   pinned clone**, and `mkdir -p <pinned clone>/data/prospective/logs`.
2. `StartCalendarInterval` is **machine-local time, not New York time**.
   The template's 01:00 and 07:30 are examples **only for a machine whose
   timezone is America/New_York**; do not copy them unchanged to a machine
   in any other timezone. On a UK machine, for example, 01:00 local is
   20:00 or 21:00 ET the previous evening and is refused every day. Pick
   local times so that at least one trigger — preferably an early
   collection and a later retry — falls inside 00:30–09:00 ET in every week
   of the year, including the weeks when US and local daylight-saving
   changes fall on different dates (US/UK differ for two to three weeks in
   March and in October/November). As an example only, checked for 2026:
   06:00 and 12:30 UK local both land inside the ET window on every day of
   that year. This is not a permanent schedule — daylight-saving rules can
   change — so verify the actual ET mapping of your chosen times when
   installing. The application's window check remains the authority.
3. Any trigger outside the window is refused by the application before a
   provider is constructed.
4. **Retries.** A retry is idempotent only when the provider returns the
   same bar content. If the provider revises the already-recorded bar
   between runs, the retry produces a loud conflict/refusal rather than
   silently replacing or backfilling the claim:
   - **unchanged bar** — `duplicate_already_exists`; no byte of the ledger
     changes;
   - **revised bar** — the ledger reports `CONFLICT`, the symbol's run
     status is `refresh_failure` and the command exits `1`; the original
     claim stays exactly as recorded, and the revision can make its later
     outcomes unusable (`SOURCE_BAR_REVISED`, not persisted).

   This is intentional fail-closed behaviour: a retry never rewrites the
   original prospective claim and never creates a historical or backfilled
   replacement. Placing the primary trigger later in the window (so the
   provider has longer to finish overnight revisions) and treating the
   second trigger as a retry after a failure reduces how often this occurs.
5. If the machine is asleep, launchd runs the job on wake — inside the
   window it collects, outside it is refused. If the machine is off, the
   day is missed and recorded as missed on the next collection.
6. **Keep the host clock synchronised.** The window check trusts the
   system clock. A clock running significantly slow — more than the
   30-minute margin between 09:00 and the 09:30 open — could let a run be
   recorded after the true market open. Normal operating-system time
   synchronisation is an operational requirement; the application does not
   check the clock against any external source and cannot remove this
   residual risk itself.

## Backup

The ledger is the only copy of evidence that cannot be regenerated. Back up
`data/prospective/` locally (e.g. Time Machine or an encrypted copy) and
never into Git. Because every file is append-only or write-once, a copy is a
consistent snapshot when no `collect` is running; `health` verifies a
restored copy strictly.

## Failure recovery

- **Provider outage / failed symbol**: nothing to do; the retry trigger or
  next day's run continues. Unclaimed days become missed.
- **`locked`**: another collect is running; the kernel releases the lock if
  that process dies. There is no stale lock to break.
- **Failed or interrupted activation** (`activation_write_failed`, or a
  crash during `activate`). Nothing is cleaned up automatically, and a
  retry is refused (`already_activated`) because the root is not empty.
  Inspect the root by hand (`ls -la data/prospective/v1`):
  - **only an empty `collect.lock`** (0 bytes; no `activation.json`, no
    `runs.jsonl`, no `ledger/`): the root is not activated — `health`
    reports `prospective_status=not_activated root_exists=yes` and exits 0.
    No claim can exist. Recovery, as a recorded operator decision: remove
    that empty lock file and the empty `v1` directory, then run the
    approved `activate` command again;
  - **anything else** — an `activation.json` of any size, a `runs.jsonl`, a
    `ledger/`, or a lock file that is not empty: stop and investigate. Do
    not delete anything. A complete `activation.json` after
    `activation_write_failed` means the bytes were written but durability
    was not confirmed (e.g. the final fsync failed); whether to accept or
    abandon that activation is a human decision to record, made before any
    scheduler is installed.
- **Torn or invalid `activation.json`** (e.g. activation interrupted
  mid-write): `collect` refuses (`invalid_manifest`), `health` reports
  `prospective_status=invalid_manifest`, and `activate` refuses
  (`already_activated`) because activation is write-once and never reuses a
  non-empty root. Nothing overwrites or auto-repairs the file. Manual
  operator inspection and recovery are required before any live
  collection, and the recovery itself is a decision to record, not a
  routine step.
- **`corrupt_ledger` / `integrity=corrupt`**: stop and inspect by hand at the
  reported component and line; nothing repairs or skips it. Inspecting a
  corrupt ledger line is a Level-2 act — record that it happened.
- **`config_mismatch`**: the code no longer matches `COLLECTION_V1`
  (e.g. a hypothesis changed). Collection v1 cannot resume under different
  code; restore the frozen code. A new definition is a new collection
  version and a new root, never a reuse of this one.
- **Never point another tool at this ledger.** `outcome_refresh
  --outcome-root data/prospective/v1/ledger` would bypass the window, the
  activation boundary and the stale-tail rule. The prospective ledger is
  written only by `collect`. Such a write is **detected** (`health` reports
  `provenance=invalid`, typically `unmatched_claim` / `unmatched_outcome`)
  and `collect` refuses from then on (`provenance_invalid`, no provider).
  It cannot be undone: there is no repair, and v1 does not resume. Phase 12
  itself is not changed for this.
- **`provenance=degraded`** (`interrupted_run`): a collection died after
  writing. Collection continues; the listed records stay excluded from any
  validation. Nothing to repair.
- **`collector_commit_mismatch` / `dirty_collector_tree`**: the scheduled
  job is not running the activated code. Restore the pinned clone to the
  manifest's commit with a clean tree; do not activate again.
- **`lock_missing`**: `collect.lock` was deleted. Nothing recreates it.
  Restoring an empty `collect.lock` is a manual operator decision, to be
  recorded, after checking that no collector is running.
- **`health` while `collect` runs**: `health` takes the lock shared and
  non-blocking; while a collection holds it, `health` reports
  `collect_in_progress` (exit 2) and inspects nothing. Re-run it afterwards.
  A collection waits up to 30 s for a `health` reader to release the lock.
- **Diagnosing a failure**: run records hold the exception class and stage
  only. Reproduce outside the prospective root (e.g. `outcome_refresh`
  against a temporary `--outcome-root`, inside the window) rather than
  adding detail to this subsystem's output.

## Relationship to future validation (M2)

M2 — the future-validation pre-registration — must be frozen and
remote-durable before activation, and activation records its commit.
Collection answers no question by itself; it only accumulates claims whose
outcomes stay unread until M2's frozen procedure opens them, once. That
procedure will require provenance `ok`, or `degraded` with the excluded
records removed (`evaluate_provenance` in the application returns the
report and the excluded keys); `invalid` or `unknown` prevents it.
