# Prospective Collection v1

Research-controlled, prospective collection of the existing pipeline's
claims over a frozen universe, into its own Phase 12 ledger, with blind
operational visibility. Decision record:
**[ADR 0013](adr/0013-prospective-collection-and-holdout.md)**.

> **Status: implemented, not activated.** No activation manifest exists, no
> claim has been collected and no scheduler is installed. Activation is
> blocked until (1) the M2 future-validation pre-registration is frozen and
> remote-durable, (2) a human explicitly approves activation, and (3) the
> local scheduler is set up. **Pre-activation hardening is also required**:
> the generic `outcome_refresh` can currently write into this ledger
> undetected (see Failure recovery), and a separate decision must settle
> whether `health` detects such provenance mismatches before activation.
> Nothing below describes something that has already been run.

It is research bookkeeping. It trades nothing, recommends nothing and
computes no performance figure.

## Architecture

```
src/prospective/definition.py   COLLECTION_V1 + fingerprint; ET window, timestamp,
                                activation, current-tail and missed-tail rules (pure)
src/prospective/records.py      ActivationManifest, RunRecord, SymbolRun, statuses (Level 1)
src/prospective/store.py        activation.json (write-once), runs.jsonl, collect.lock
src/prospective/environment.py  git HEAD / clean / ancestry probe; dependency versions
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
data/prospective/v1/runs.jsonl        one Level-1 record per collect attempt
data/prospective/v1/collect.lock      flock target, holds no data
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

Writes `activation.json` once and nothing else. Refused, writing nothing,
when: either SHA is malformed; the working tree is dirty (including
untracked files); HEAD is not the collector commit; the M2 commit is not in
HEAD's history; the live code differs from `COLLECTION_V1`; or the root is
not empty (`already_activated`). The manifest records `activated_at` (one
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
2. Recompute `COLLECTION_V1` and check it against the manifest and the live
   code (`config_mismatch` otherwise).
3. Check the start clock against **00:30 ≤ ET < 09:00**
   (`OUTSIDE_COLLECTION_WINDOW` otherwise) — before any provider exists.
4. Take the root lock (`locked` otherwise: no provider, no record).
5. For each symbol, in frozen order: re-check the window; build the
   snapshot (settled bars only); require the frozen provider, interval and
   basis; re-check the window on `built_at`; require every daily bar at
   00:00:00 ET; skip a `PRE_ACTIVATION` tail without touching the ledger;
   derive missed tails; refuse a `STALE_TAIL`; otherwise call the unchanged
   `refresh_outcomes`.
6. Append one run record; release the lock; print `key=value` lines.

Exit codes: `0` every symbol collected (or was pre-activation); `1` the run
completed but at least one symbol did not; `2` refused as a whole or usage
error.

### `health` (offline, read-only, any time)

```
python -m src.cli.prospective health
```

Never constructs a provider, never fetches, never creates a file. Reads the
manifest, the run log and the ledger strictly. Prints **Level 1** only:

```
prospective_status=active root_exists=yes ledger_exists=yes collection_id=… collection_fingerprint=…
  manifest_fingerprint_match=yes live_configuration_match=yes activated_at=… collector_git_commit=…
  m2_preregistration_git_commit=… universe=SPY,QQQ,IWM,TLT,GLD interval=1d basis=raw
symbol=SPY readable=yes claims_total=… tails_registered=… claims_evaluable=… claims_insufficient=…
  outcomes_matured_h1=… outcomes_matured_h5=… outcomes_matured_h20=… pending=…
  missed_collections=… missed_dates=… last_tail=…
runs_total=… runs_completed=… runs_outside_window=… runs_config_mismatch=… last_run=… last_success=…
  symbol_statuses=ok:…,duplicate_already_exists:…
integrity=ok
```

Exit `0` when active or not activated, `1` on corruption or configuration
mismatch.

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

`MISSED_COLLECTION` is not a symbol status: missed bars are listed as
`missed_tails` on the run that first sees them after the last claim, and
counted by `health` as `missed_collections` / `missed_dates`. They are never
claimed.

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

1. Copy it to `~/Library/LaunchAgents/`, replace `__VENV_PYTHON__` and
   `__REPOSITORY__` with absolute paths, and
   `mkdir -p <repository>/data/prospective/logs`.
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
  written only by `collect`. Today nothing *detects* such a write —
  `health` would still report `active` — so this is **pre-activation
  hardening required**: before real activation, a separate design decision
  must determine whether `health` should flag ledger claims without
  matching run-log evidence, `recorded_at` values outside the collection
  window, or other provenance mismatches. Phase 12 itself is not changed
  for this.
- **`health` while `collect` runs**: `health` takes no lock; if it reads the
  run log in the instant a line is being appended it can report a torn final
  line. Re-run it after the collection finishes before treating that as
  corruption.
- **Diagnosing a failure**: run records hold the exception class and stage
  only. Reproduce outside the prospective root (e.g. `outcome_refresh`
  against a temporary `--outcome-root`, inside the window) rather than
  adding detail to this subsystem's output.

## Relationship to future validation (M2)

M2 — the future-validation pre-registration — must be frozen and
remote-durable before activation, and activation records its commit.
Collection answers no question by itself; it only accumulates claims whose
outcomes stay unread until M2's frozen procedure opens them, once.
