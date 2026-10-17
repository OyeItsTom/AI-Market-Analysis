# Prospective Collection v1

Research-controlled, prospective collection of the existing pipeline's
claims over a frozen universe, into its own Phase 12 ledger, with blind
operational visibility. Decision record:
**[ADR 0013](adr/0013-prospective-collection-and-holdout.md)**.

> **Status: implemented, not activated.** No activation manifest exists, no
> claim has been collected and no scheduler is installed. The M2
> future-validation pre-registration is frozen and merged (commit
> `3dac81078b31c4c5856419faae4f2749cc43ede5`, hard-pinned by M2B — see
> Activation identity binding). Activation is
> blocked until (1) pre-activation hardening is merged and every
> requirement under **Activation readiness, retention and recovery** is met
> (dedicated pinned clone outside protected folders, runtime parity probe,
> verified backup, free disk), (2) a human explicitly approves activation,
> (3) the dedicated collector clone is checked out at the collector commit
> (see Scheduler setup), and (4) the local scheduler is set up. The N2
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
src/prospective/records.py      ActivationManifest (v2), RunRecord, SymbolRun, statuses (Level 1)
src/prospective/store.py        collect.lock + activation.json (write-once), runs.jsonl, locks
src/prospective/identity.py     pinned M2A identity; dependency-environment contract (pure)
src/prospective/environment.py  read-only local git probe; dependency-environment capture
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
  --server-main-sha <40-hex from the preflight below>
```

Immediately before, in the same checkout, the operator runs the **server-main
preflight** (activation itself never contacts a remote):

```
git fetch origin
git ls-remote origin refs/heads/main      # copy the full 40-hex SHA it prints
git rev-parse HEAD refs/remotes/origin/main
```

`--server-main-sha` is not a research knob; it is the operator's assertion
of the server's `main` at that moment. There is no option to name the M2
commit, a fingerprint, or to skip, force or relax any check.

Writes the empty `collect.lock` and then `activation.json`, once, and
nothing else (the lock first, so an activated root always has the lock
`health` and `collect` require). If any write or fsync fails the command
refuses with `activation_write_failed`: activation durability could not be
confirmed, and the root may hold the lock and possibly a partial — or even
complete — `activation.json` (a failure in the final fsync comes after the
bytes were written, and `health` may then report `active`). Treat it as
unconfirmed and follow "Failed or interrupted activation" under Failure
recovery (it applies only while v1 has never been activated) before any
retry, collection or scheduler installation. Refused,
writing nothing — not even the root directory — when (checked in this order,
the first failure is the `reason`): either SHA is not a full lower-case
40-hex SHA (`invalid_commit`); git cannot answer (`repository_unverified`);
the checked-out branch is not `main` (`not_on_main`, including a detached
HEAD); the working tree is dirty, including untracked files and any tracked
file hidden from `git status` by an `assume-unchanged` or `skip-worktree`
index flag, edited or not (`dirty_repository`; the flag is never cleared —
remove it yourself with `git update-index --no-assume-unchanged` /
`--no-skip-worktree` and check the file); HEAD is not the collector commit
(`collector_commit_mismatch`); `refs/remotes/origin/main` is missing
(`origin_main_missing`) or is not HEAD — behind, ahead or diverged
(`head_not_origin_main`); the server main is not HEAD
(`server_main_mismatch`); the M2A binding fails (`m2_commit_missing`,
`m2_commit_not_in_history`, `m2_preregistered_bytes_mismatch`,
`m2_working_tree_bytes_mismatch`, `m2_bound_paths_changed`,
`future_validation_fingerprint_mismatch`; every failing check is printed in
`details=`); the live code differs from `COLLECTION_V1` (`config_mismatch`);
the dependency environment cannot be read or verified — including while
`PYTHONPATH` or `PYTHONHOME` is in effect
(`dependency_environment_unavailable`); or the root is not empty
(`already_activated`). Activation makes no provider call and reads no market
data. The manifest (schema `prospective_activation_v2`) is described under
Activation identity binding.

### `collect` (scheduled; one finite run)

```
python -m src.cli.prospective collect
```

1. Load and verify the manifest (absent → `not_activated`; unreadable —
   malformed bytes or a file-system error such as a permission refusal —
   → `invalid_manifest`; both write nothing).
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
6a. Recompute the dependency environment and require it to equal the
   manifest's exactly (`dependency_environment_mismatch`, or
   `dependency_environment_unverified` when it cannot be read canonically).
7. Read every ledger partition strictly and reconcile it with the run log
   (see Provenance): `provenance_unknown` if a partition is unreadable,
   `provenance_invalid` if any record cannot be attributed. `degraded`
   provenance proceeds; its records stay excluded.
8. Append and fsync a **run start** (`prospective_run_start_v1`: run id,
   start clock, collection and provenance-policy fingerprints, activation
   time, collector commit, universe). Steps 4–7 refuse with one run record
   (no symbols) and no run start; every refusal happens before any provider
   exists, so a refused run makes no provider call and writes no claim or
   outcome.
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

Never constructs a provider, never fetches, never creates a file; it runs
only the read-only, local git queries of the M2A binding (`m2_binding`). Reads the manifest, then takes the lock **shared and non-blocking**
before reading the run log and the ledger strictly, so it never inspects
files a collector is mutating: while `collect` holds the lock it reports
`prospective_status=collect_in_progress` and `provenance=unknown`, never a
false corruption. Prints **Level 1** only:

```
prospective_status=active root_exists=yes ledger_exists=yes collection_id=… collection_fingerprint=…
  manifest_fingerprint_match=yes live_configuration_match=yes activated_at=… collector_git_commit=…
  m2_preregistration_git_commit=… m2_binding=ok dependency_environment=ok
  runtime_python_implementation=CPython runtime_python_version=3.11.3
  runtime_dependencies=ok runtime_dependency_fingerprint=…
  runtime_import_path_overrides=none
  universe=SPY,QQQ,IWM,TLT,GLD interval=1d basis=raw
symbol=SPY readable=yes claims_total=… tails_registered=… claims_evaluable=… claims_insufficient=…
  outcomes_matured_h1=… outcomes_matured_h5=… outcomes_matured_h20=… pending=…
  missed_collections=… missed_dates=… last_tail=…
runs_total=… runs_completed=… runs_outside_window=… runs_config_mismatch=…
  runs_refused_collector=… runs_refused_provenance=… runs_refused_dependencies=…
  runs_interrupted=… last_run=… last_success=…
  symbol_statuses=ok:…,duplicate_already_exists:…
provenance=ok provenance_reasons=none provenance_policy_fingerprint=… claims_checked=… outcomes_checked=…
integrity=ok
```

A provenance finding adds `provenance_component=`, `provenance_symbol=` and
`provenance_line=` (the first invalid finding: a component name, a symbol
and a file line number — never a record's content).

The `runtime_*` fields are the **current** interpreter, before and after
activation — never the manifest's: implementation and version, whether its
dependency environment can be verified (`runtime_dependencies=ok`
or `unavailable`), the fingerprint an activation run here would record
(`none` when unavailable) and which of `PYTHONHOME`/`PYTHONPATH` is in effect
(`none` normally). They are what the runtime parity probe compares (see
Activation readiness); they do not change the exit code. After activation,
`dependency_environment` compares the same runtime with the manifest.

Exit codes:

| exit | when |
| --- | --- |
| `0` | not activated; or active with `provenance=ok`, `m2_binding=ok` and `dependency_environment=ok` |
| `1` | anything needing attention: `provenance=degraded` or `invalid`, `corrupt`, `config_mismatch`, `m2_binding` or `dependency_environment` not `ok`, `invalid_manifest`, `lock_missing` |
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

## Activation readiness, retention and recovery

These requirements come from the pre-activation hardening review. They are
procedure, not code: nothing in the repository creates the clone, installs
a scheduler, configures a backup or checks free disk. Each must be true —
and recorded in the activation gate — before the first and only activation.

### Dedicated pinned clone, outside protected folders

The first real activation runs from a **dedicated, full (non-shallow)
clone** with its own virtualenv — never the development checkout. It must
**not** live under `~/Desktop`, `~/Documents`, `~/Downloads`, iCloud Drive,
or any other location whose access macOS grants only to interactive apps
(privacy/TCC-protected or cloud-synced folders). A launchd job is not an
interactive app: in such a location the scheduled interpreter can be refused
access ("Operation not permitted") to the code, the Git objects, the root
and even the log files, so the job fails or never starts. A cloud-synced
folder can also evict or replace local files. A neutral location such as
`~/AI-Market-Analysis-Prospective` is an example only; no path is hard-coded.

Check the clone with `git rev-parse --is-shallow-repository` (`false`) and
`git cat-file -e 3dac81078b31c4c5856419faae4f2749cc43ede5^{commit}`.

### Runtime parity probe (before installing the scheduler and before activating)

Activation records the dependency environment of the interpreter that runs
it; every scheduled `collect` must reproduce it exactly or refuse — and a
refusal on the first scheduled run would end Collection v1. So, **before
activation**, in the dedicated clone:

1. Run `health` interactively the way activation will be run:
   `<clone>/.venv/bin/python -m src.cli.prospective health` with the clone
   as working directory.
2. Run the **same** command in the environment launchd will use — a
   temporary, one-shot LaunchAgent with the same `ProgramArguments` (but
   `health`, not `collect`), the same `WorkingDirectory` and log paths
   outside the future v1 root — then remove it. This is a probe only: it
   never runs `collect` or `activate`.
3. Compare the first lines. These must be identical:
   `runtime_python_implementation`, `runtime_python_version`,
   `runtime_dependencies` (must be `ok`),
   `runtime_dependency_fingerprint`, `runtime_import_path_overrides` (must
   be `none`), and `m2_binding=ok` (proves the job can read the clone and
   its Git objects). The probe's stdout/stderr files must have been
   written (proves the job can write its logs).

Any difference is a blocker: fix the environment, never activate around it.

### Host freeze for the life of Collection v1

Do not casually, while v1 runs: upgrade, reinstall or remove the python.org
3.11.3 framework the venv points to; replace, recreate or `pip`-modify the
clone's venv; remove the Command Line Tools / `git`; move or rename the
clone; set `PYTHONPATH` or `PYTHONHOME` for the job. Each of these makes
`collect` refuse (fail closed) — it is never absorbed. An intentional
environment change means Collection v1 stops, and the change goes through
an explicitly reviewed versioning procedure (new collection version, new
root, new activation decision); v1's evidence stays as it is.

### Free disk

Before activation the clone's volume must have **at least 5 GB free**, and
should be kept there. Collection v1 itself is small: measured on synthetic
ledgers, about 12 KB per symbol per session (claim, run-log and outcome
lines), i.e. roughly 60 KB per day for five symbols and under 100 MB over
six years. The margin (about 50×) is for the venv, logs, local backup
snapshots and the OS. Running out is fail-closed but harmful: an append that
cannot complete leaves a torn line, and every later `collect` refuses on the
corrupt file. The threshold is operational only and part of no fingerprint.

### Backup and restore verification (required before activation)

The prospective root is the only copy of evidence that cannot be
regenerated. Before activation:

- a real backup destination exists and is running (Time Machine, or another
  local or encrypted mechanism — the mechanism is the operator's choice);
- it includes the whole dedicated clone **including git-ignored content**
  (`.venv/`, and after activation `data/prospective/`) and is never Git;
- a **restore test** has been done: restore or copy the clone to a separate
  location, then, from that restored copy, run
  `<restored>/.venv/bin/python -m src.cli.prospective health` (read-only)
  and check `m2_binding=ok`, `runtime_dependencies=ok` with the
  same fingerprint, and that the restored clone is non-shallow and contains
  the M2A commit. Never run `collect` or `activate` in a restored copy and
  never schedule it.
- the restored copy is also **clean as Git sees it** (the "Clean
  repository" rule under Activation identity binding). In the restored
  copy, each of these must hold:
  - `git -c core.fsmonitor=false status --short --untracked-files=normal`
    prints nothing (nothing modified, staged or untracked);
  - `git -c core.fsmonitor=false diff --cached --quiet` exits 0 (nothing
    staged);
  - `git -c core.fsmonitor=false ls-files -v | grep -v '^H '` prints
    nothing: every tracked entry is tagged `H`, so no file carries an
    `assume-unchanged` (lower-case tag) or `skip-worktree` (`S`) flag;
  - `git branch --show-current` prints `main`, and `git rev-parse HEAD`
    prints the expected commit — the commit the dedicated clone was
    pinned to (after activation, the manifest's `collector_git_commit`).

  A restored copy that fails any of these is **not** a verified restore
  and is not ready to resume Collection v1, even if `health` looks right.
  Never clear an index flag (`git update-index --no-assume-unchanged` /
  `--no-skip-worktree`), reset, stash or delete files to make it pass:
  find out why the restore differs, repair the backup or the restore
  procedure, and restore again.

Immediately after activation, take a backup and repeat the restore test
(including the Git checks above) on the activated root: the restored
copy's `health` must report
`prospective_status=active` with the same `activated_at` and
`collector_git_commit`, and `activation.json`, `runs.jsonl` and the ledger
files must have the same SHA-256 as the originals. Because every file is
append-only or write-once, a copy taken while no `collect` runs is a
consistent snapshot.

### Retention contract: what must survive

Verifying — or recovering — the future validation years from now needs,
exactly:

- `data/prospective/v1/activation.json`, byte for byte;
- the prefix of `data/prospective/v1/runs.jsonl` recorded at the opening;
- the prefix of every prospective ledger file
  (`data/prospective/v1/ledger/<SYM>/1d/raw/{artifacts,outcomes}.jsonl`)
  recorded at the opening;
- `data/prospective/v1/validation/<validation_id>/<fingerprint>/unlock.json`
  and `result.json` (`report.md` can be regenerated from the result);
- the clone's full, non-shallow Git history, including the M2A commit
  `3dac81078b31c4c5856419faae4f2749cc43ede5`.

The future-validation snapshot records only the **lengths and SHA-256** of
those prefixes, not their bytes: it does not archive the evidence. The
source files must therefore remain available, unmodified up to their
recorded length, for as long as the result may need to be verified. The
code only ever appends to them or writes them once; their survival depends
on the operator and the backup.

### Prohibited maintenance in the dedicated clone (after activation)

> **Never**, in the dedicated clone:
> - `git clean -x` or `git clean -X` (they delete the git-ignored
>   `data/prospective/` — the evidence);
> - delete, move or recreate `data/prospective/`, or delete, re-clone or
>   recreate the clone;
> - truncate, rotate, rewrite, "compact" or replace any file under
>   `data/prospective/v1/` (including `activation.json`);
> - run `activate` again — for any reason, including after losing the root.

### If the prospective root is lost or damaged

A lost root looks exactly like a never-activated one (`health` then says
`prospective_status=not_activated` and exits 0), so watch for
`prospective_status=active` after activation. Whether v1 was ever
activated is decided by the record, not by what the root shows now:
Collection v1 **was activated** if any `activate` run ever printed
`activation=written`, if `health` ever reported `prospective_status=active`
for v1, if an unconfirmed activation was ever accepted by a recorded
decision, or if any `collect` ever ran or a scheduler was ever installed.
In that case this section applies — never "Failed or interrupted
activation" under Failure recovery, even if the root is now empty, missing,
or holds only an empty `collect.lock`. If the root is missing, truncated or
damaged:

1. **Stop collection** (unload the LaunchAgent).
2. **Restore from the verified backup** into the dedicated clone, then
   check it with `health` as in the restore test.
3. **Do not run `activate` again.** Re-activating would start a new
   collection under the same name and silently discard the original
   evidence. Collection v1 is activated once; if its evidence cannot be
   restored, v1 ends and anything further is a new, explicitly reviewed
   collection version.

## Scheduler setup (after approved activation only)

Template: `config/launchd/com.ai-market-analysis.prospective-collect.plist.example`.

0. **Pinned collector clone.** Real collection runs from a dedicated clone
   of the repository checked out at exactly the collector commit
   recorded in `activation.json`, with its own virtualenv — not from the
   development checkout. It must be a full (non-shallow) clone outside
   `~/Desktop`, `~/Documents`, `~/Downloads` and iCloud Drive, and the
   runtime parity probe must have passed before activation (see Activation
   readiness, retention and recovery). Activation requires that clone to be on its `main`
   branch at the freshly fetched `origin/main` (see `activate`); afterwards
   `collect` only requires HEAD == the collector commit and a clean tree, so
   the clone may stay on `main` (never pulled) or be detached at that
   commit. `collect` refuses unless that checkout is clean
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

   **Dependencies are recorded and enforced (M2B, N-R11).** Activation
   records the complete installed environment of the clone's virtualenv and
   every `collect` refuses on any difference (see Dependency environment).
   Upgrading, adding or removing any package in that virtualenv — or
   changing the Python patch version — stops Collection v1; it is never
   silently absorbed.
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
the dedicated clone including `data/prospective/` locally (e.g. Time Machine
or an encrypted copy) and never into Git. Because every file is append-only
or write-once, a copy is a consistent snapshot when no `collect` is running;
`health` verifies a restored copy strictly. A configured backup and a
verified restore are activation requirements, and the retention contract
lists what must survive — see Activation readiness, retention and recovery.

## Failure recovery

- **Root lost, truncated or damaged**: stop collection, restore from the
  verified backup, **never run `activate` again** — see "If the prospective
  root is lost or damaged" under Activation readiness.
- **`dependency_environment_unverified` with `runtime_import_path_overrides`
  not `none`**: `PYTHONPATH`/`PYTHONHOME` reached the job; remove it from
  the job's environment. Nothing to repair in the root.
- **Provider outage / failed symbol**: nothing to do; the retry trigger or
  next day's run continues. Unclaimed days become missed.
- **`locked`**: another collect is running; the kernel releases the lock if
  that process dies. There is no stale lock to break.
- **Failed or interrupted activation** (`activation_write_failed`, or a
  crash during `activate`). **This applies only while Collection v1 has
  never been activated** — the first activation attempt failed and no
  earlier attempt succeeded (see "If the prospective root is lost or
  damaged" for what counts as activated). If v1 was ever activated, this
  procedure never applies: stop collection, restore from the verified
  backup, and never run `activate` again. Nothing is cleaned up
  automatically, and a retry is refused (`already_activated`) because the
  root is not empty. Inspect the root by hand (`ls -la data/prospective/v1`):
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
    scheduler is installed. Once accepted, v1 counts as activated.
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

## Activation identity binding (M2B)

M2B closes N6 (Git identity enforced, not merely recorded) and N-R11
(dependency drift). It changes no research definition: `COLLECTION_V1`,
`PROVENANCE_V1` and `FUTURE_VALIDATION_V1` keep their fingerprints.

**The pinned M2A identity** (`src/prospective/identity.py`) is
`M2A_PREREGISTRATION_COMMIT = 3dac81078b31c4c5856419faae4f2749cc43ede5`,
`FUTURE_VALIDATION_V1` fingerprint
`79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab`, and three
bound scientific paths with the SHA-256 of their bytes at that commit:

| path | SHA-256 at the commit |
|---|---|
| `docs/research/future_validation_v1.md` | `3cb6fe9b2968c258fa513cf826efbd868b9b7326b9318af615047c0d3307fb19` |
| `src/research/future_validation.py` | `b39d33aeb867c7bb9676c0f39fc910856633b4117e47f77fe0a0c36e84fe6ccf` |
| `src/research/future_validation_engine.py` | `5212d48f234844a8079e3270ae19ef6a9ce057a46530a944668e73772419c5f2` |

The binding holds when the commit object exists, it is HEAD or an ancestor
of HEAD, each path is a blob with exactly that SHA-256 at the commit,
`git diff --quiet <commit> HEAD -- <paths>` reports no change, each
working-tree file (a regular file, not a symlink) has the same SHA-256, and
the live `FUTURE_VALIDATION_V1` has the pinned fingerprint. The runner,
store and CLI of M2A are deliberately not bound: later non-scientific
hardening of them is legitimate.

**Authoritative main.** Activation never fetches. It verifies locally that
the branch is `main`, the tree is clean, and HEAD equals the named collector
commit, the already-fetched `refs/remotes/origin/main`, and the operator's
`--server-main-sha` from the preflight — so HEAD is the server's `main` as of
the preflight, and the M2A commit is in its history.

**Manifest v2** (`prospective_activation_v2`, canonical JSON, exact keys):
`activated_at`; `collection_id`, `collection_fingerprint`,
`provenance_policy_fingerprint`; `collector_git_commit`,
`origin_main_git_commit`, `server_main_git_commit` (all equal),
`git_branch` (`main`), `git_tree_clean` (`true`);
`m2_preregistration_git_commit`, `m2_preregistration_in_history` (`true`),
`future_validation_fingerprint`, `m2_bound_paths` (`[{path, sha256}]`, sorted);
the M1 fields (`holdout_start`, `universe`, `interval`, `basis`, `provider`,
`hypothesis_fingerprints`, `outcome_spec_fingerprints`,
`evaluation_version`); and `dependency_environment`. Decoding refuses an
unknown schema (including v1 — no v1 manifest was ever written, so there is
no migration), a missing or extra key, a wrong type, a short SHA, a
malformed SHA-256, an M2 identity other than the pin, inconsistent recorded
proof (e.g. `server_main_git_commit` ≠ the collector commit), and any
non-canonical byte. It holds no research value and no market data.

**Dependency environment.** Recorded at activation, never hard-coded in
source: `{schema: prospective_dependency_environment_v1,
python_implementation, python_version, packages: [{name, version}],
fingerprint}`. `packages` is every distribution `importlib.metadata`
finds on the interpreter's `sys.path`, names PEP 503-normalised
(lower case, runs of `-_.` → `-`) and sorted; two distributions that
normalise to one name are refused, never resolved. No path or timestamp is
included. The fingerprint is SHA-256 of the canonical JSON (sorted keys,
compact, ASCII) of `{schema, python_implementation, python_version,
packages: [[name, version], …]}`. Discovery order cannot change it; adding,
removing or changing any package, the Python version (including the patch
level) or the implementation does.
Because discovery follows `sys.path`, run `activate` exactly as the
scheduler will run `collect`: the pinned clone's virtualenv interpreter,
the clone's root as working directory (the plist's `WorkingDirectory`), and
no `PYTHONPATH`. A different interpreter, working directory with extra
distribution metadata, or path makes `collect` refuse — it never absorbs it.
Distribution metadata cannot see code that is importable without it, so
while `PYTHONPATH` or `PYTHONHOME` is set to a non-empty value the
environment is **unverifiable**: activation refuses
(`dependency_environment_unavailable`), `collect` refuses
(`dependency_environment_unverified`, before any provider) and `health`
reports `runtime_dependencies=unavailable`. Nothing is stripped or
ignored silently; under `python -E` (which really ignores those variables)
they are not in effect and do not refuse. An unexpected failure while
reading the distributions is the same controlled "unavailable/unverified"
refusal, never a traceback. The schema and the fingerprint are unchanged:
the variables are checked, never recorded.

**Clean repository.** Wherever this document says clean (activation,
`collect`'s collector identity, future validation's binding), it means both
that `git status --porcelain --untracked-files=normal` reports nothing and
that no tracked file carries an `assume-unchanged` or `skip-worktree` index
flag (`git ls-files -v` shows only `H`): such a flag hides a file's edits
from `status`, so a flagged file is never trusted, edited or not. Every Git
query runs with `core.fsmonitor` disabled. The check reports; it never
clears a flag or changes Git state.

*Why the whole environment.* Transitive libraries (HTTP, parsing, time
zones, numerics) can change provider behaviour, timestamps and numbers as
much as yfinance or pandas can. Collection v1 is meant to stay frozen, so
any drift fails closed. The cost is that even a harmless upgrade (e.g. of
`pip`) stops collection; an intentional environment change requires a new,
explicitly reviewed collection version and procedure rather than silently
changing v1.

**Future validation.** Before it captures, re-derives or opens anything,
`python -m src.cli.future_validation {status,run}` requires the manifest to
decode as v2 (so it names the pinned commit, fingerprint and bound hashes),
its `future_validation_fingerprint` to equal the live definition's, the
working tree to be clean, and the M2A binding to hold in the local
repository. HEAD need not equal the activation HEAD — later operational
commits are allowed — and no network is needed years later: authoritative
`main` was proven once, at activation, and is recorded in the manifest.
`status` reports `m2_binding=ok|mismatch|unavailable` and an invalid
validity on failure; `run` refuses `m2_binding_mismatch,<reasons>` before
any Level-3 read. The manifest is read once per operation: an absent or
unreadable one refuses at once (`not_activated` / `invalid_manifest`), and
after every capture or recapture the snapshot's `activation.json` must be
byte-identical to the bound manifest (`manifest_changed` otherwise) and the
repository binding is re-checked, before any result verification, unlock
recovery or Level-3 read.

**Health** adds `m2_binding` (local Git; also before activation) and
`dependency_environment` (installed vs the manifest; `unavailable` before
activation), each `ok`, `mismatch` or `unavailable`, and
`runs_refused_dependencies`; it exits `1` unless both are `ok` on an active
root.

**Durability.** The manifest write is unchanged: the lock then the
manifest, each `O_EXCL`, written, flushed and `fsync`ed, then the root
directory is `fsync`ed. Those calls narrow but do not eliminate the window
in which a power loss can lose a just-written file; that is why any write
or fsync error reports `activation_write_failed` (durability unconfirmed),
and a retry is refused (`already_activated`) because the root is not empty
— never a second activation.

## Relationship to future validation (M2)

M2 — the future-validation pre-registration — is frozen and merged;
activation verifies and records its pinned commit and bound files (M2B).
Collection answers no question by itself; it only accumulates claims whose
outcomes stay unread until M2's frozen procedure opens them, once. That
procedure will require provenance `ok`, or `degraded` with the excluded
records removed (`evaluate_provenance` in the application returns the
report and the excluded keys); `invalid` or `unknown` prevents it.
