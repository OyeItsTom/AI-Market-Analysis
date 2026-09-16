# Outcome tracking (Phase 12)

A prospective, append-only record of what the research pipeline claimed at
each explicit Refresh, and of what the market did afterwards — measured by
Phase 4, stored once, never rewritten, and summarised descriptively.

It is research bookkeeping. It scores nothing, ranks nothing, recommends
nothing and opens no position; a forward return here is a property of the
market, not of a strategy, and **historical outcomes do not establish future
profitability**. Decision record: **[ADR 0010](adr/0010-prospective-outcome-tracking.md)**.

## Purpose

Phase 4 (`src/evaluation`, [docs/research_evaluation.md](research_evaluation.md))
answers "what happened after a classification?" over stored history, all at
once, and keeps nothing. That is a *retrospective* study, and a retrospective
study cannot tell a claim made at the time from a claim replayed later.

Phase 12 keeps the claim. When you press Refresh, the observations and the
assessment for the latest settled bar are written to a local ledger with the
clock they were made under and a fingerprint of the bar they rested on. On a
later Refresh, once enough settled bars have arrived, Phase 4 measures the
forward return from that bar and the result is written beside the claim.
Neither record can be changed afterwards.

| | Phase 4 (retrospective) | Phase 12 (prospective) |
| --- | --- | --- |
| When the claim is made | during the study, over history | at Refresh time, about the current bar |
| Data available | the whole window | only bars up to the claim |
| Persistence | none | append-only ledger |
| Measurement | Phase 4 | Phase 4 (unchanged) |
| Aggregation | `EvaluationSummary` | descriptive per-partition summary with explicit coverage |

## Prospective lifecycle

```
Refresh #1  (tail bar T settled)
  register  ObservationArtifact × hypotheses, AssessmentArtifact × 1   -> artifacts.jsonl
  evaluate  every ledger artifact under every horizon                   -> PENDING (T+1.. not yet in series)

Refresh #2..N  (bars T+1 .. T+H settled)
  register  the new tail's claims                                       -> WRITTEN / DUPLICATE
  evaluate  the claim about T under horizon H                           -> OutcomeRecord -> outcomes.jsonl
```

Rules the code enforces (`src/application/outcomes.py`, `src/outcomes/models.py`):

- Only the **current snapshot's tail** is registered. A snapshot whose
  claims describe any other bar is refused. No backfill, no replay.
- `timestamp` is the claim time (the claimed bar's open); `data_cutoff` is
  the latest settled bar the producer had — in production, the same bar.
  `recorded_at` is the snapshot's own `built_at`, read once per Refresh.
- Future data is consumed only on a later refresh — a dashboard Refresh or a
  headless run (below). Nothing in the repository polls or schedules.
- The reference is the open of bar T+1; horizons count bars, reference bar as
  bar one; bars T+1 … T+H are the consumed evidence and are fingerprinted.
- An `OutcomeRecord` refuses `future_timestamp <= data_cutoff`,
  `evaluated_at <= future_timestamp` and `evaluated_at < recorded_at`. The
  refresh that registers a claim can never complete that claim.

## Artifact types

Both are frozen copies of the Phase 3 / Phase 6 record, taken verbatim:

- **`ObservationArtifact`** — one hypothesis's `ResearchObservation`.
  Producer: `hypothesis_id`, `hypothesis_version`, `hypothesis_fingerprint`.
  State vocabulary: `ResearchState`.
- **`AssessmentArtifact`** — one policy's `ResearchAssessment`. Producer:
  `policy_fingerprint`. State vocabulary: `AssessmentState` (so `CONFLICTED`
  survives as itself).

Common audit fields: `source` (provider name), `data_cutoff`, `recorded_at`,
`observation_bar_fingerprint` (content of bar T at registration), `origin`
(`snapshot`, the only member). Reason codes are required — an unexplained
claim is not auditable. `INSUFFICIENT_DATA` artifacts are registered but
`is_evaluable` is false: there is nothing to measure.

**Identity.** `artifact_key` is the full SHA-256 of a canonical-JSON payload
over kind, symbol, interval, basis, timestamp and the producer identity.
State and audit fields are *not* in the key, but they are in the record, and
the ledger compares whole records: same key + same record = `DUPLICATE`;
same key + any difference = `CONFLICT`, and nothing is written.

## Outcome evaluation

`evaluate_artifact(artifact, series, spec, evaluated_at=…)` in
`src/outcomes/tracking.py` returns one `TrackingResult`:

| Status | Meaning | Carries |
| --- | --- | --- |
| `EVALUATED` | Phase 4 completed the horizon | one `OutcomeRecord` |
| `PENDING` | reference or future bars not in the series yet | Phase 4's own finding |
| `INELIGIBLE` | artifact state is `INSUFFICIENT_DATA` | nothing |
| `REFUSED` | series is not this artifact's data | a `RefusalReason` |

Decision order: eligibility → source → Phase 4 → revision → completion.

- **Source.** `artifact.source` must equal `series.source`
  (`SOURCE_MISMATCH` otherwise). Checked before any bar is read.
- **Phase 4.** `measure_forward` validates the market point and measures it.
  A series that structurally cannot describe the artifact (wrong symbol,
  interval, basis, or a timestamp that is not a bar) raises; it is a caller
  error, not a status.
- **Revision.** The series' bar T is fingerprinted and compared with the
  artifact's. A difference is `SOURCE_BAR_REVISED`; the measurement is
  discarded unread. Revision outranks pending.

`OutcomeRecord` embeds the artifact it measured and carries
`spec_fingerprint`, `horizon_bars`, `evaluation_version`, `evaluated_at`,
`consumed_bars_fingerprint`, reference and future timestamp/price and
`forward_return`. It checks `forward_return == future_price / reference_price
- 1` exactly and computes nothing itself.

**Identity.** `outcome_key = H(artifact_key, spec_fingerprint,
evaluation_version)`. `EVALUATION_VERSION` is 1; a change to how outcomes are
derived produces new records beside the old.

## Persistence

`JsonlOutcomeLedger` (`src/outcomes/store.py`) implements the `OutcomeLedger`
port (`src/outcomes/ports.py`):

```
data/outcomes/<SYMBOL>/<interval>/<basis>/artifacts.jsonl
data/outcomes/<SYMBOL>/<interval>/<basis>/outcomes.jsonl
```

- One directory per `LedgerPartition` `(symbol, interval, basis)`.
  `data/outcomes/` is git-ignored and is created on the first write, never at
  start-up.
- One canonical JSON object per line: compact, sorted keys, ASCII, newline
  terminated, floats in shortest round-trip form, UTC timestamps. Every line
  carries `schema_version` (owned by the store) and `record_type`.
- Two writes, both idempotent by key: `register_artifact`, `append_outcome`.
  No update, delete or reorder exists. An outcome line embeds its artifact
  whole; appending one requires the artifact to be registered with exactly
  that content.
- Each append is one `write`, `flush`, `fsync`. The partition is re-read and
  indexed in memory on every operation — no persistent index, no cache, one
  local process, one writer.
- Reads are strict: every line is decoded, re-encoded and compared with the
  bytes on disk, keys are recomputed and compared, and a foreign partition, a
  duplicate key, an unknown schema version or a final line without its
  newline is `LedgerCorruption` with path, line number and byte offset.
  Nothing is skipped, repaired or rewritten.

There is **no transaction across the two files**. Registration and outcome
append are separate durable facts.

## Refresh behavior

Tracking runs once per successful dashboard Refresh, in the Refresh branch
after the snapshot is published, and at no other time — not on a rerun, a
widget change, a scan or an AI explanation (`src/dashboard/app.py`,
`track_outcomes`) — and once per symbol of a headless run
(`src/cli/outcome_refresh.py`, see [Headless collection](#headless-collection-12g)).
Both callers make the same three application calls. Horizons are
`OUTCOME_HORIZONS = (1, 5, 20)` bars on the snapshot's RAW basis, declared
once in `src/application/outcomes.py`.

`refresh_outcomes(snapshot, specs, ledger, now=snapshot.built_at)`:

1. Validates the request (non-empty, distinct specs on the snapshot's basis;
   aware clock) and the snapshot's coherence with its own series (symbol,
   interval, basis, source; every claim is the tail bar).
2. Registers each claim. A key the ledger already holds is offered with the
   *held* `recorded_at`, so two refreshes that see the same tail bar differ
   in nothing and are `DUPLICATE`; any other difference is `CONFLICT` and
   raises.
3. Evaluates every ledger artifact in the partition under every horizon:
   `PRESENT` if the outcome key is already held; `OUT_OF_WINDOW` if the
   artifact's bar precedes the fetched series; otherwise through
   `evaluate_artifact`, appending an `EVALUATED` result.

The result is one `OutcomeRefreshResult` of per-item statuses and counts
derived from them, rendered as a single caption under the assessment:

> Outcome tracking: 4 claims registered (4 new), 0 new outcomes, 12 pending.

**`OUT_OF_WINDOW`** is application-derived, non-terminal and not persisted:
the fetch window is finite and a claim older than it is not a data fault. It
is retried whenever a later or wider series begins at or before the bar. A
bar *inside* the window that is missing is a hard error.

**Failure isolation.** Tracking is auxiliary. Any failure — a ledger that
cannot be read, a conflict, an unexpected exception — leaves the snapshot on
screen, shows one line naming the failure class, and sends the detail to the
terminal. The dashboard never sees a path, a key or a record.

**Partial success.** A refresh is a sequence of independent appends, not a
transaction. If it fails part-way, everything appended before the failure is
durable and stays; the next refresh finds those records `DUPLICATE` /
`PRESENT` and resumes. Idempotency, not atomicity.

## Headless collection (12G)

```
python -m src.cli.outcome_refresh SYMBOL [SYMBOL ...] --interval {1d,1wk,1mo} [--outcome-root PATH]
```

The same refresh without Streamlit. For each symbol, in command-line order,
the command calls exactly what the dashboard's Refresh calls —
`default_provider()`, `build_snapshot(...)` (settled bars only, the
application's own history window), `build_outcome_ledger(...)` and
`refresh_outcomes(snapshot, OUTCOME_SPECS, ledger, now=snapshot.built_at)` —
prints one line, and after the last symbol prints totals and exits. It
decides nothing: no horizon, window, identity or measurement lives in it.

**Scope.** One interval per invocation (a second interval is a second
command); a few explicit symbols; no universe, watchlist or discovery.
Symbols are stripped and upper-cased; a blank or duplicate symbol is a usage
error and nothing runs.

**Output.** One `key=value` line per symbol on stdout, fields in a fixed
order, then `symbols=N ok=N failed=N`:

```
symbol=SPY interval=1d status=ok source=yfinance built_at=2026-09-16T21:05:00+00:00 tail=2026-09-15T00:00:00+00:00 bars=502 artifacts=4 artifacts_new=4 artifacts_duplicate=0 outcomes_new=0 outcomes_present=0 pending=12 ineligible=0 refused=0 out_of_window=0
symbol=QQQ interval=1d status=failed stage=snapshot kind=provider step="market data" error=...
symbols=2 ok=1 failed=1
```

`built_at` is the snapshot's clock (also the refresh clock); `tail` is the
registered bar; the counts are `OutcomeRefreshResult`'s own
(`artifacts_considered`, `artifacts_written`, `artifact_duplicates`,
`outcomes_written`, `outcomes_already_present`, `pending`, `ineligible`,
`refused`, `out_of_window`). Stderr carries a traceback only where the
dashboard would print one — an unexpected snapshot failure, or any failure
inside the refresh; a classified provider outage is its one stdout line.

**Exit codes.** `0` every symbol completed; `1` at least one failed; `2`
usage or configuration error. A symbol fails when the snapshot cannot be
built (`stage=snapshot`, with the application's `kind`/`step`), when the
provider returns **no settled bars** (`stage=snapshot reason=empty_snapshot`
— the application treats an empty series as a fact, but a scheduled
collector must not succeed forever on a mistyped or delisted symbol; nothing
is registered), or when the refresh raises (`stage=outcomes error_type=…`,
e.g. `LedgerCorruption`, `OutcomeRefreshError`). A failed symbol does not
stop later symbols. Nothing is rolled back: appends that completed before a
failure are durable, as on the dashboard, and the next run resumes over them.

**Idempotency.** Running the same command again over the same settled tail
registers nothing (`artifacts_new=0`, `artifacts_duplicate=N`) and measures
nothing already held (`outcomes_present`); the files are byte-for-byte
unchanged. The CLI implements none of this — artifact identity, the ledger's
`DUPLICATE` verdict and outcome identity do — so redundant runs on weekends,
holidays or during the session are safe, and no market calendar is needed.

**Ledger location.** Without `--outcome-root` the application's default
local ledger (`data/outcomes/`, git-ignored) is used; the CLI never names the
path itself. Manual smoke against a temporary root, outside the suite:

```
python -m src.cli.outcome_refresh SPY \
  --interval 1d \
  --outcome-root /tmp/ai-market-analysis-outcomes
```

**Scheduling is outside the repository.** The command runs once and exits;
there is no in-process scheduler, daemon or polling loop. An operator's
scheduler invokes it:

```
scheduler (launchd / cron)  ->  python -m src.cli.outcome_refresh SPY --interval 1d  ->  exit
```

On macOS prefer **launchd** (`~/Library/LaunchAgents/*.plist` with
`StartCalendarInterval`, `WorkingDirectory` set to the repository and the
virtual environment's `python`): unlike cron, launchd runs a missed
calendar job after the machine wakes. A daily run after the US close for
`1d`, weekly for `1wk` and monthly for `1mo` is enough; more often is safe
but only repeats duplicates and provider requests. Do not let two invocations
run against one ledger at the same time — the store is single-writer and
takes no lock; give each scheduled command time to finish before the next.

**What local scheduling does not give you.** This machine is the only
durable host. If it is asleep, launchd may run the job after wake; if it is
powered off, no collection happens while it is off. A tail bar whose refresh
never ran is **never registered later** — claims are prospective and nothing
backfills — so a gap is a missing claim, a non-random one. Claims that were
registered are still measured on the next run from historical settled bars,
so outcomes are late, not lost, as long as the gap is shorter than the
history window. No cloud durability or continuous service is claimed.
GitHub Actions is not a fit: an ephemeral runner would not keep the ledger.

## Aggregation

`summarize_outcomes(reader, partition, specs)` in `src/outcomes/summary.py`
reads one partition through the `OutcomeReader` port and returns an
`OutcomeSummary`. It is read-only, deterministic and descriptive: it touches
no bars, recomputes no return, and the only division in the module is a
coverage fraction.

Two group kinds:

- **Coverage group**, keyed by `spec_fingerprint × producer × state × source`.
  One per registered producer/state/source under each requested spec, even
  with zero completed outcomes.
- **Metric group**, keyed by coverage key `× evaluation_version`. One per
  version with at least one completed outcome. No version is invented for a
  group with none, and no empty metric group is fabricated.

Producer identity is mandatory. At one bar, hypothesis A, hypothesis B and
the assessment all measure the same market move; pooling them would count it
three times. There is no overall return across producers, no ranking and no
figure across groups.

Ordering is fixed: requested spec position, then artifact kind (observations
before assessments), producer, state, source, evaluation version.

**Not yet displayed.** The dashboard currently shows only the refresh caption
above. No 12E summary is rendered anywhere; `summarize_outcomes` is a library
function with no application or UI consumer in Phase 12.

## Coverage

Per coverage group:

- `artifacts_registered` — registered artifacts in the group
- `artifacts_evaluable` — those with `is_evaluable` (state ≠ `INSUFFICIENT_DATA`)
- `artifacts_completed` — **distinct** artifacts with at least one completed
  outcome under this spec, under **any** evaluation version
- `raw_coverage_fraction = artifacts_completed / artifacts_registered`
- `evaluable_coverage_fraction = artifacts_completed / artifacts_evaluable`
- zero denominator → `None`

Per metric group, separately: `sample_count` and version-specific
`raw_coverage_fraction = sample_count / artifacts_registered`,
`evaluable_coverage_fraction = sample_count / artifacts_evaluable`.

```
10 artifacts registered and evaluable
v1 outcomes = 10,  v2 outcomes = 2

coverage group   artifacts_completed = 10 of 10
v1 metric group  sample_count = 10   coverage 100 %
v2 metric group  sample_count = 2    coverage  20 %
```

A partially re-evaluated version shows its own, smaller coverage; it cannot
borrow the older version's.

Coverage measures *that* claims completed, never *why* some did not:
`PENDING`, `REFUSED` and `OUT_OF_WINDOW` are derived per refresh and are not
in the ledger.

## Interpretation limits

A metric group reports exactly `sample_count`, `positive_count`,
`negative_count`, `zero_count`, and the mean, median, minimum and maximum of
`forward_return`, with `sample_floor_met`.

- **`MIN_SUMMARY_SAMPLES = 20`** is a descriptive display floor.
  `sample_floor_met` is a flag, not a filter, and says nothing about
  statistical sufficiency, independence, significance or predictive
  reliability.
- **Overlapping windows.** A claim at T with horizon 20 and a claim at T+1
  with horizon 20 share 19 of 20 bars. Outcome samples are descriptive
  observations, not independent trials. `OutcomeSummary.overlap_caveat`
  carries this on the type and no significance inference is performed.
- **Not computed:** hit rate, win rate, accuracy, profitability, Sharpe,
  alpha, significance, confidence intervals, probability of success,
  producer ranking, combined return across producers.
- **No costs.** No spread, slippage, sizing or fill; these are not returns
  anyone could have earned.

## Failure behavior

| Situation | Behaviour |
| --- | --- |
| Same claim re-registered | `DUPLICATE`, nothing written |
| Different claim under a held key | `CONFLICT`; refresh raises; earlier appends stay |
| Outcome for an unregistered artifact | `UnregisteredArtifactError` |
| Outcome embedding an artifact that differs from the registered one | `ArtifactMismatchError` |
| Provider changed | `REFUSED (SOURCE_MISMATCH)`, not persisted |
| Bar T content changed | `REFUSED (SOURCE_BAR_REVISED)`, not persisted |
| Claim older than the fetched window | `OUT_OF_WINDOW`, retried later |
| Horizon not yet complete | `PENDING`, retried later |
| Corrupt, torn or unknown-schema line | `LedgerCorruption` on read; nothing proceeds, nothing is touched |
| Tracking fails on the dashboard | snapshot stays; one-line notice; detail to terminal |
| A symbol fails in a headless run | `status=failed` line; later symbols still run; exit `1`; earlier appends stay |
| Provider returns no settled bars in a headless run | `stage=snapshot reason=empty_snapshot`; nothing registered; exit `1` |

## Known limitations

1. Vendor revisions and corporate-action back-adjustments refuse later
   evaluations of earlier claims, reducing coverage in a non-random way. The
   summaries show the gap, not its cause.
2. Reasons for missing outcomes are not durably persisted.
3. Corrupt or torn ledger lines stop the partition and require manual
   inspection; there is no repair tooling.
4. Artifacts copy the claim, not the feature values behind it; forensic
   reconstruction needs the bars and the hypothesis version too.
5. JSONL with a full re-read per operation does not scale indefinitely.
6. The vendor's RAW prices with `auto_adjust=False` are not guaranteed to be
   as-traded values; see [ADR 0001](adr/0001-price-basis-and-corporate-actions.md).
7. No inferential statistics, no transaction costs, no profitability claim.
8. Horizons are daily-research oriented: `(1, 5, 20)` bars apply unchanged
   to `1d`, `1wk` and `1mo` refreshes, each tracked in its own partition.

9. Headless collection is only as continuous as the machine running it;
   a missed run is a missing prospective claim (see
   [Headless collection](#headless-collection-12g)).

Not part of Phase 12 and not started: scheduler code or installation, a
benchmarked retrospective study (Phase R), error analysis (Phase 13),
outcome-aware AI explanation (11B), any dashboard rendering of summaries,
and any monitoring or repair tooling.
