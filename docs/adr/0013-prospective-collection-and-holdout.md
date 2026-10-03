# ADR 0013 — Prospective collection and the reserved holdout (M1)

**Status**: accepted (Prospective Collection v1: infrastructure implemented,
**not activated**; amended for N2 provenance hardening — decisions 10–12)

## Context

Phase 12 built an append-only ledger that records each research claim
before its outcome exists, and 12G a headless command to feed it. Neither
was ever switched on: there is no ledger on this machine and no claim has
been recorded. Meanwhile the retrospective work (Phase R, Phase 13A) read
history only through 2025-02-28 and found nothing to change in the
hypotheses; the one form of evidence the project still lacks is evidence
that could not have been fitted, because it did not exist when the
methodology was frozen.

Prospective claims are irreplaceable — a day that is not recorded can never
be recorded afterwards — but they are also easy to contaminate: a claim
recorded after the next session has opened, a claim reconstructed for a
missed day, a ledger shared with ad-hoc dashboard refreshes, a configuration
that drifts during collection, or outcomes looked at before the question
asked of them is fixed.

## Decisions

### 1. Prospective evidence is collected under a frozen definition

`COLLECTION_V1` (`src/prospective/definition.py`) fixes, in code: universe
SPY, QQQ, IWM, TLT, GLD (in that order); interval `1d`; RAW basis; settled
bars only; provider `yfinance`; the three existing hypotheses by id, version
and fingerprint (650add07184f8440, 6589cb8021b76574, f1126ca778e6f7ce);
`directional_presence_v1` with minimum 2 and its policy fingerprint; outcome
horizons 1, 5, 20 and their spec fingerprints; evaluation version 1; the
2-year history window and 51-bar warm-up; holdout start 2025-03-01; the ET
collection window. Its fingerprint (full SHA-256 of canonical JSON) contains
no machine path and no activation time. Every collection run recomputes it
and checks the declared pins against the live code; any difference refuses
the run before a provider exists.

*Rejected:* universe or interval as command-line flags (`outcome_refresh`
stays as the generic, manual tool).

### 2. The reserved interval and the causal-lookback exception

Bars from 2025-03-01 to the activation timestamp are a reserved historical
interval: never claimed, never evaluated, never persisted or printed by the
prospective subsystem, never summarised. There is **no backfill** from
2025-03-01.

They may still pass through memory: every claim needs 51+ settled bars of
history for SMA50 and RSI14, and `build_snapshot` fetches a two-year window.
That causal lookback is the only permitted use. It does not make the
interval "inspected" in the research sense — no outcome over it is computed
and no human reads it through this path — but it also does not make market
prices secret; what the reservation protects is unrun analysis.

### 3. Dedicated root, write-once activation

The collection lives under `data/prospective/v1/` (git-ignored):
`activation.json`, `runs.jsonl`, `collect.lock` and its own Phase 12 ledger
under `ledger/`. It never uses `data/outcomes/`, so a dashboard Refresh can
neither contaminate it nor race it as a second writer.

`activation.json` is **write-once** (`O_EXCL`, and refused on a non-empty
root). Activation creates the empty `collect.lock` first and the manifest
second, so an activated root always has its lock (decision 12). Activation requires a clean working tree, HEAD equal to the named
collector commit, the named **M2 pre-registration commit** in HEAD's
history, and live code matching `COLLECTION_V1`. It makes no provider call
and creates no claim. A tail bar that settled at or before `activated_at` is
`PRE_ACTIVATION` and is never claimed: the first claim always concerns a bar
that settled after activation.

### 4. The safe collection window: 00:30 ≤ America/New_York < 09:00

A daily bar is stamped 00:00 ET and settles at the next midnight ET; a
claim is prospective only if it is recorded before the next session opens
at 09:30 ET. Collection is therefore allowed only in 00:30–09:00 ET — a
30-minute buffer after settlement and a 30-minute margin before the open.
The window is checked on the run's clock before any provider is
constructed, again before each symbol's fetch, and on each snapshot's
`built_at` (the claim's `recorded_at`). Outside it: no provider call, no
claim, no ledger write; only a run record (`OUTSIDE_COLLECTION_WINDOW`).

A claim is either recorded inside the window or permanently missed. A late
claim is **not** registered and flagged afterwards.

Two further guards keep "inside the window" from meaning "late":
every daily bar must be stamped exactly 00:00:00 ET (anything else is
`TIMESTAMP_CONVENTION`, refused, never reinterpreted); and a tail with any
claim not yet registered — including the remainder of a set a crashed run
left partial — is claimable only if no weekday lies between its date and
the run's ET date (`STALE_TAIL` otherwise — a lagging feed would otherwise
produce a claim recorded after a session it never saw). A tail whose claims
are all held is only re-seen, and the run proceeds so earlier claims keep
maturing. Without an exchange calendar
this rule refuses conservatively after a weekday holiday; that costs a claim,
never contaminates one.

*Rejected:* registering late claims with a `LATE_REGISTRATION` flag to be
excluded later — it puts contaminated records in the evidence and moves the
decision to after the outcomes exist.

### 5. Missed collection

When a later snapshot shows settled post-activation bars after the last
claim that were never claimed, their timestamps are recorded in that run's
record as `missed_tails` — operational metadata only. No claim is ever
created for them. The provider's own bars are the session calendar; no
exchange calendar is introduced. Registered claims keep maturing on later
runs, so a gap shorter than the history window delays outcomes but loses
only the missed claims.

### 6. Blind access levels

| Level | Content | Access |
| --- | --- | --- |
| 1 | counts, clocks, bar timestamps, status/error classes, integrity, configuration identity | routine: `collect` output, `runs.jsonl`, `health` |
| 2 | individual claim states and outcome values (`artifacts.jsonl`, `outcomes.jsonl`) | not viewed |
| 3 | aggregates (`summarize_outcomes`, any mean, sign count, hit rate, comparison) | locked until the M2 pre-registration opens them |

Supported surfaces are Level 1 by construction: the run record and the
health report have no field that could hold a price, return or state, their
decoders refuse unknown keys, no run-log number is a float, exception
messages are never recorded (only class names), and boundary tests forbid
the new modules from naming price, return, state or summary attributes.
Claim states count as Level 2: a state plus the public price path is nearly
an outcome. Nothing stops `cat`; the rule is that nobody opens the ledger
files until M2 says so.

### 7. M2 before activation

The future-validation pre-registration (M2) must be frozen and
remote-durable **before** real activation, and activation records its
commit. Claim generation does not depend on any validation question, so
collecting first would be defensible only on a behavioural promise; with M2
frozen first, no validation question can be chosen after claims (and,
through states, outcomes) could have been seen.

### 8. Scheduler and locking

Collection is one finite command (`python -m src.cli.prospective collect`).
A local launchd job triggers it; the repository ships only a portable
template (`config/launchd/…plist.example`) and installs nothing. launchd
uses machine-local time, so the operator chooses triggers that put at least
one run — preferably an early run and a later retry — inside the ET window
in every week; the application refuses any other trigger before provider
access. Trigger times are machine-local and must be mapped to ET by the
operator when installing — times written for a New York machine are wrong on
a UK one — and the application's window check remains the authority.

A retry is idempotent only when the provider returns the same bar content.
If the provider revises the already-recorded bar between runs, the retry
produces a loud conflict/refusal (the ledger reports `CONFLICT`, the
symbol's run status is `refresh_failure`) rather than silently replacing or
backfilling the claim. The revision can also make the original claim's later
outcomes unusable (`SOURCE_BAR_REVISED`). This is intentional fail-closed
behaviour: a retry never rewrites the original prospective claim and never
creates a historical or backfilled replacement.

One run at a time holds an exclusive `flock` on `collect.lock`; a second run
is refused (`locked`, after the bounded wait of decision 12) without a
provider or a record. The kernel releases the lock if the holder dies, so
there is no stale lock to break.

The window check trusts the host system clock. A clock running
significantly slow (more than the 30-minute margin before the 09:30 open)
could let a run be recorded after the true open; operating-system time
synchronisation is therefore an operational requirement. The application
does not and cannot solve this residual risk itself.

### 9. Explicit activation, never automatic

Merging this code activates nothing. Real activation is a separate, human-
approved step after M2 is frozen: AI proposes the exact command → the human
approves and runs `activate` (no network) → the human installs the launchd
job → the first provider call happens at the first scheduled trigger inside
the window.

### 10. Provenance: detect and refuse, Phase 12 unchanged (N2)

The generic `outcome_refresh` can be pointed at the prospective ledger and
write claims and outcomes that bypass the window, the activation boundary
and the current-tail rule. Rather than change mature Phase 12 code, the
prospective subsystem **detects** such writes and refuses to continue.

A frozen, separately fingerprinted policy, `prospective_provenance_v1`
(`ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117`,
`src/prospective/provenance.py`), reconciles every ledger record with this
collection's run log through a link that already exists: the collector
passes `now = snapshot.built_at` to the unchanged `refresh_outcomes`, which
stamps that clock on every artifact (`recorded_at`) and outcome
(`evaluated_at`) it writes, while the run record keeps `built_at`, `tail`
and the write counts per symbol. A record no completed run accounts for, a
record outside the window or before activation, a late claim, a foreign
partition, source, origin, producer or outcome spec, a count that disagrees
with the run, or a run log that contradicts itself or the manifest makes
provenance **invalid**. Attribution never depends on the order of wall-clock
readings inside one run — a host clock may step backward — only on run-id
pairing and exact equalities. The verifier is pure and reads only metadata —
never a state, reason code, price or return — and its output is Level 1.
`COLLECTION_V1` and its fingerprint are unchanged.

A durable **run start** (`prospective_run_start_v1`) is appended and
fsynced before any provider exists. A run start without a completed record
is an interrupted run; records inside its interval that pass every check
and form one snapshot per symbol are **degraded** — collection continues,
and a future validation must exclude them (degraded is never primary
evidence). Their clock may precede the run start by at most a frozen 5 s
backward-clock tolerance; the attribution rule, its span (3600 s) and the
tolerance are part of the fingerprinted policy. A run start never blesses a record
by itself. `health` reports `provenance=ok|degraded|invalid|unknown` with
reason counts; `collect` refuses on `invalid` or `unknown`; nothing is ever
repaired, deleted or rewritten, and `invalid` ends collection v1 for that
root.

*Accepted limits:* a refresh that raised records no counts (N10), so its
writes are bounded (≤ 4 claims) rather than counted; a deleted
completed-record line reads as a crash (degraded, excluded); a forger who
also writes matching run-log lines is out of scope (no signature or hash
chain).

*Rejected:* changing `refresh_outcomes`/`outcome_refresh` to refuse the
prospective root (Phase 12 stays generic and unchanged); registering
provenance inside artifact records (schema change to frozen Phase 12
records); treating a crash orphan as invalid (one power cut would end the
collection) or as valid (a run start would bless anything).

### 11. The collector is the activated code (N14)

Before any provider exists, `collect` requires a clean working tree and
`HEAD == activation_manifest.collector_git_commit`
(`dirty_collector_tree`, `collector_commit_mismatch`,
`collector_unverified`; one refusal record, no provider, no ledger write).
Real collection therefore runs from a dedicated clone pinned at the
collector commit, to which the launchd job points; a branch switch or an
edit in the development checkout can stop collection but never change it.
The collector commit is thereby frozen for the life of Collection v1: a
code fix cannot be applied in place, and a materially changed collector
requires an explicit new collection version, a new provenance contract and
a new activation decision. Dependency versions are recorded but not
enforced; before activation, either enforcement against the manifest or a
checklist-verified pinned virtualenv must be chosen.

### 12. Locking for readers (N4)

`health` takes `collect.lock` **shared and non-blocking** before reading
the run log or the ledger; while a collector holds it exclusively, `health`
reports `collect_in_progress` (provenance `unknown`, exit 2) and inspects
nothing — a half-written state can never be reported as corruption or as a
provenance finding. `collect` waits up to 30 s (monotonic) for its
exclusive lock so a human `health` call cannot cost a scheduled run.
Neither creates the lock file: activation does, and a missing lock is
`lock_missing`, fail closed, recreated only by a recorded operator
decision. A corrupt run log is never appended to (`corrupt_run_log`).

## Consequences

- Prospective evidence, once collected, is uncontaminated by construction:
  frozen configuration, recorded inside the window, never reconstructed,
  never shared with ad-hoc refreshes.
- Coverage depends on one machine being awake between 00:30 and 09:00 ET;
  gaps are recorded, not filled, and are not random.
- Holiday days after an unclaimed Friday, feed lag past a weekday and any
  provider revision cost claims or outcomes rather than quality.
- The ledger is the only copy of irreplaceable data: it needs a local
  backup that is never Git.

## Deferred

M2 pre-registration (design and freeze, including the activation-time proof
of the M2 commit's content and remote durability); the dependency-drift
decision (enforce versions against the manifest, or a checklist-verified
pinned virtualenv) — required before activation; real activation; the
pinned collector clone and scheduler installation; any exchange calendar;
any dependency-version enforcement beyond recording it; a tamper-evident
(hash-chained or signed) run log; any reader of Level 2 or 3 data.

See [docs/prospective_collection.md](../prospective_collection.md) for
operation, [docs/outcomes.md](../outcomes.md) for the ledger it wraps, and
[ADR 0010](0010-prospective-outcome-tracking.md) for Phase 12.
