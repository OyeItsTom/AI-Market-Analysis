# ADR 0010 — Prospective outcome tracking and deterministic aggregation

**Status**: accepted (Phase 12: 12A–12F)

## Context

Phase 4 ([ADR 0002](0002-outcome-evaluation-conventions.md)) measures what
the market did after a research observation, and forgets the result. It is
*retrospective*: given stored history and a hypothesis, it evaluates every
bar in the window at once, on data that was all present when the study was
run. That is the right tool for a study and the wrong one for a track record,
because nothing in it distinguishes "the hypothesis said BULLISH on 3 March"
from "replaying the hypothesis today over March says BULLISH" — and the
second is worth much less than the first.

Phase 12 adds the record the pipeline lacked: **what was actually claimed at
time T, and what happened afterwards**, kept so that neither half can be
altered once written. The design had to prevent, by construction rather than
by discipline:

- **retrospective backfill** — a claim written today about a bar from last
  year, indistinguishable from one made at the time;
- **lookahead** — an outcome completed from data that existed when the claim
  was made;
- **mutable claims** — a record that can be updated, deleted or re-ordered
  after the fact;
- **silent source revision** — a claim about bar T measured against a bar T
  the vendor has since changed;
- **accidental double counting** — several artifacts at one bar measuring one
  market move being read as several samples;
- **AI or trading authority** — any route from an outcome to a model's
  judgement or a paper position;
- **misleading aggregate statistics** — hit rates, rankings, significance or
  any figure that reads as a performance claim.

## Decisions

### 1. Architecture: 12A → 12E

| Stage | Module | Owns |
| --- | --- | --- |
| 12A | `src/outcomes/identity.py`, `models.py` | The outcome domain: `ObservationArtifact`, `AssessmentArtifact`, `OutcomeRecord`, deterministic keys and bar fingerprints |
| 12B | `src/outcomes/tracking.py` | `evaluate_artifact`: one artifact against one settled series through Phase 4, returning exactly one `OutcomeRecord` or a deterministic reason there is none |
| 12C | `src/outcomes/ports.py`, `store.py` | The append-only `OutcomeLedger` / `OutcomeReader` contracts and `JsonlOutcomeLedger` |
| 12D | `src/application/outcomes.py` | `refresh_outcomes`: registration and evaluation sequenced on the dashboard's explicit Refresh |
| 12E | `src/outcomes/summary.py` | `summarize_outcomes`: deterministic, descriptive per-partition aggregation through the reader port |
| 12F | this ADR, `docs/outcomes.md` | Documentation and closure |

The flow, end to end:

```
settled market data
  -> ResearchSnapshot                      (Phase 7 refresh, include_unsettled=False)
  -> ObservationArtifact / AssessmentArtifact  (12A: the tail bar's claims, verbatim)
  -> append-only artifact ledger           (12C: artifacts.jsonl)
  -> a later settled refresh               (12D: the next explicit Refresh)
  -> Phase 4 forward measurement           (12B: measure_forward, the only price reader)
  -> OutcomeRecord                         (12A: immutable, self-checking)
  -> append-only outcome ledger            (12C: outcomes.jsonl)
  -> deterministic per-partition summaries (12E: coverage + descriptive metrics)
```

Each arrow is a separate module with a separate test surface, and the
boundaries are pinned by AST tests (`tests/test_outcomes_boundaries.py`):
only `tracking.py` and `summary.py` may import `src.evaluation`, nothing in
`src/outcomes` reads a clock, a file or the network except the store, and no
later-stage module (analysis, monitoring, an application summary, outcome
reasoning) exists before its gate.

### 2. Prospective-only semantics

- An artifact is created only from the **current snapshot's tail** — the
  last settled bar of the series the snapshot was computed from.
  `refresh_outcomes` refuses a snapshot whose observations or assessment
  describe any other bar (`_require_coherent`). There is no historical
  backfill and no replay; `ArtifactOrigin` has one member, `SNAPSHOT`.
- `timestamp` is the claim time: the open of the bar the claim describes.
- `data_cutoff` is the open of the latest settled bar the producer had. In
  the current production flow the tail bar *is* the cutoff, so
  `data_cutoff == timestamp`. The record enforces only
  `timestamp <= data_cutoff <= recorded_at`; it does not prove settledness,
  which is the fetch layer's guarantee (`include_unsettled=False`).
- Future data is consumed only on a **later refresh**. Nothing waits, polls
  or schedules; the next explicit Refresh is the next chance to complete an
  outcome.
- Phase 4 (`measure_forward`) remains the **sole** forward-return authority.
  12B never re-derives the reference, the horizon arithmetic or the return.
- The reference is the open of bar T+1; the horizon is counted in **bars**,
  reference bar as bar one; the consumed evidence is bars T+1 … T+H, and
  `consumed_bars_fingerprint` is the order-sensitive fingerprint of exactly
  those bars.
- `OutcomeRecord` refuses `future_timestamp <= data_cutoff`: the bar that
  closes the measurement must not have existed when the claim was recorded.
  It also refuses `evaluated_at <= future_timestamp` and
  `evaluated_at < recorded_at`.
- Consequently the snapshot that registers a claim can never complete that
  claim's outcome: its last bar is the claimed bar, and the reference bar is
  after it.

These are necessary conditions checked on every record. They refuse
impossible sequences; they are not a proof that every bar was settled when
read, and this ADR claims nothing stronger than the checks provide.

### 3. Artifact identity

An artifact key is the full SHA-256 of a canonical-JSON payload (with a
`scheme` and `scheme_version`) over the **stable semantic claim slot**:

- kind (`observation` | `assessment`)
- symbol, interval, basis, timestamp
- producer identity —
  observation: `hypothesis_id`, `hypothesis_version`, `hypothesis_fingerprint`;
  assessment: `policy_fingerprint`.

The *state* is deliberately not in the key: a producer makes exactly one
claim per bar, so a different claim under the same key is a **conflict** for
the ledger to detect, not a second artifact. Audit fields — `recorded_at`,
`source`, `observation_bar_fingerprint`, `state`, `reason_codes`, `origin`
— are likewise outside the key, but they are inside the durable record, and
the ledger compares the whole record: a re-offered key with any differing
field is `CONFLICT`, byte-identical is `DUPLICATE`.

### 4. Outcome identity

```
outcome_key = H(artifact_key, spec_fingerprint, evaluation_version)
```

Three inputs and no more. Prices, returns and clocks are results; keying on
them would let one measurement be stored twice whenever a result differed.
`EVALUATION_VERSION` (currently 1) names the Phase 12 measurement
implementation, so a future change produces new records *beside* the old,
never over them; the outcome *contract* (horizon, reference, price field,
basis) is already named by `OutcomeSpec.fingerprint`, which every record
also carries. A record declaring an unsupported version is refused on read.

### 5. Source and revision semantics

`evaluate_artifact` decides, in order: eligibility → source → Phase 4 →
revision → completion.

- `artifact.source != series.source` is `REFUSED (SOURCE_MISMATCH)`, checked
  before any bar is read. Numerically identical bars from a different
  provider are a different evidential basis.
- Bar T is fingerprinted at registration (`observation_bar_fingerprint`,
  over symbol, interval, timestamp and OHLCV). At evaluation the series'
  bar T is fingerprinted again; a difference is `REFUSED
  (SOURCE_BAR_REVISED)` and the measurement is discarded unread. Revision
  outranks pending: the claim's premise is gone whether or not the future
  has arrived.
- This is conservative by design and **reduces completed coverage**. A
  vendor revision refuses every artifact whose claimed bar it changed, for
  as long as the provider serves the revised history; a corporate-action
  back-adjustment changes every bar before the event, so it refuses every
  earlier artifact in that partition at once.

**Known limitation, recorded here rather than solved:** artifacts refused
for revision are not a random subset of claims. Symbols with corporate
actions, and periods before them, drop out of the completed sample, which is
a **selection effect** the summaries cannot see. 12E coverage diagnostics
expose *that* outcomes are missing; because refusals are derived on each
refresh and never persisted, they do not say *why*. The revision policy is
not claimed to be complete or optimal, only explicit.

### 6. Persistence

`JsonlOutcomeLedger` (12C):

- **Append-only JSONL**, one directory per `LedgerPartition`
  (`<root>/<SYMBOL>/<interval>/<basis>/`), two files: `artifacts.jsonl` and
  `outcomes.jsonl`. Basis is in the partition so a reader of RAW claims is
  never handed adjusted ones.
- **Canonical serialization**: compact, sorted keys, ASCII-escaped, one
  newline-terminated JSON object per line; floats in shortest round-trip
  form so `forward_return == future_price / reference_price - 1` survives a
  round trip exactly; timestamps UTC ISO-8601 with offset.
- `schema_version` and `record_type` on every line, **owned by the store**,
  never by the domain models. An unknown version is `UnsupportedSchemaError`
  (a corruption subtype): no forward guessing, no migration.
- **Duplicate vs conflict**: a write under a held key is `DUPLICATE` when the
  offered row equals the held row and `CONFLICT` when it does not; a conflict
  writes nothing and keeps what was held. Which of the two is right is not
  the ledger's question.
- An outcome line **embeds its artifact whole**, so it is self-contained;
  `append_outcome` refuses an outcome whose artifact is unregistered
  (`UnregisteredArtifactError`) or registered with different content
  (`ArtifactMismatchError`). Appending an outcome never registers its
  artifact.
- **`write` + `flush` + `fsync` per append.** The partition is re-read and
  its index rebuilt in memory on every operation; there is no persistent
  index and no cache. One local process, one writer; no lock.
- **Strict corruption detection on read**: every line is decoded into a
  domain record, re-encoded, and compared with the bytes on disk; stored
  keys are compared with recomputed keys; a line in the wrong partition, a
  key seen twice (agreeing or not), a non-newline-terminated final line
  (torn append), an unknown schema version or an unreadable JSON value is
  `LedgerCorruption` with path, line number and byte offset. Nothing is
  skipped, repaired or rewritten; the bytes stay as evidence.
- **No cross-file transaction.** Registering an artifact and appending an
  outcome are two separate durable facts.

### 7. Partial success, not transactions

A refresh is a sequence of independent appends. If it raises part-way —
a `CONFLICT`, a corrupt partition, a series that should hold a bar and
does not — every artifact and outcome appended before the failure is
already durable and stays so. Nothing is rolled back, because nothing is
wrong with those records. The next refresh re-reads the ledger, finds them
`DUPLICATE` / `PRESENT`, and continues from where the previous one stopped.
Idempotency by key, not atomicity, is what makes a partial refresh safe.
Nothing here is transactional and this ADR does not describe it as such.

### 8. `OUT_OF_WINDOW`

The dashboard fetches a finite history window. An evaluable ledger artifact
whose bar precedes the refreshed series' first bar is `OUT_OF_WINDOW`:
decided in the application layer before Phase 4 is asked, **non-terminal**,
**not persisted**, and retried on any later refresh whose series begins at
or before the artifact's bar. It is distinct from `PENDING` (bar present, horizon not
yet complete), `INELIGIBLE` (`INSUFFICIENT_DATA`, nothing to measure) and
`REFUSED` (source or bar-content mismatch). A bar *inside* the window that
is missing remains a hard error, not a status.

### 9. 12E aggregation

`summarize_outcomes(reader, partition, specs)` is:

- **per `LedgerPartition`** — no cross-symbol, cross-interval or
  cross-basis figure;
- **read-only** — through `OutcomeReader`, each iterator consumed exactly
  once, no write path;
- **deterministic** — groups ordered by requested spec position, artifact
  kind, producer identity, state, source, evaluation version; the reader's
  order plays no part;
- **descriptive only** — counts and plain statistics of stored
  `forward_return` values; the only division in the module is the coverage
  fraction.

Coverage identity: `spec_fingerprint × producer × state × source`.
Metric identity: coverage identity `× evaluation_version`.

Requested specs are explicit; outcomes under unrequested specs are integrity-
checked and then ignored. A reader that yields a foreign record, a duplicate
key, an orphan outcome, an outcome embedding a different artifact than the
registered one, or a horizon that contradicts its spec raises
`OutcomeSummaryError`.

### 10. Coverage semantics

Per coverage group:

| Field | Meaning |
| --- | --- |
| `artifacts_registered` | registered artifacts in the group |
| `artifacts_evaluable` | those with `artifact.is_evaluable` (state ≠ `INSUFFICIENT_DATA`) |
| `artifacts_completed` | **distinct** registered artifacts with ≥ 1 completed outcome under this spec, under **any** evaluation version |
| `raw_coverage_fraction` | `artifacts_completed / artifacts_registered` |
| `evaluable_coverage_fraction` | `artifacts_completed / artifacts_evaluable` |

A zero denominator yields `None`, never `NaN`: "no artifacts" is not "zero
coverage".

Separately, each **metric group** (one per evaluation version with ≥ 1
outcome) reports `sample_count` and its own version-specific
`raw_coverage_fraction = sample_count / artifacts_registered` and
`evaluable_coverage_fraction = sample_count / artifacts_evaluable`, using the
coverage group's denominators. A partially evaluated new version therefore
cannot inherit the older version's coverage:

```
10 registered, evaluable artifacts
v1 outcomes = 10
v2 outcomes = 2

coverage group:      artifacts_completed = 10 of 10   (any version)
v1 metric group:     sample_count = 10, coverage 100 %
v2 metric group:     sample_count = 2,  coverage  20 %
```

### 11. Zero-outcome groups

A coverage group exists for every registered `(producer, state, source)`
under every requested spec, **including groups with no completed outcome**.
Such a group has its coverage row and nothing else: no evaluation version is
invented for it and no empty metric group is fabricated. A metric group
exists only where at least one outcome completed.

### 12. Descriptive metrics only

A metric group reports exactly: `sample_count`, `positive_count`,
`negative_count`, `zero_count`, `mean_forward_return`,
`median_forward_return`, `min_forward_return`, `max_forward_return`, plus the
denominators, the timestamp span of the measured artifacts and
`sample_floor_met`.

Phase 12 does **not** compute: hit rate, win rate, accuracy, profitability,
Sharpe, alpha, statistical significance, confidence intervals, probability of
success, producer ranking, or any global combined return across producers.
There is no figure across groups of any kind.

### 13. Sample floor

`MIN_SUMMARY_SAMPLES = 20`; `sample_floor_met = sample_count >= 20`. It is a
**descriptive display floor** — a flag a later presentation stage may use,
not a filter (values are reported either way). It does not mean the sample is
statistically sufficient, independent, significant, or that the producer is a
reliable predictor. The number is a display convention and is documented as
one.

### 14. Overlapping windows

Prospective claims are made every refresh, so consecutive outcomes share
most of their forward window: a claim at T with horizon 20 and a claim at T+1
with horizon 20 share 19 of 20 future bars. Outcomes are therefore
**descriptive observations, not independent statistical trials**.
`OutcomeSummary.overlap_caveat` carries this on the type, so no consumer can
receive a summary without it, and no significance inference is performed in
Phase 12.

### 15. Producer double counting

At one bar the ledger holds one artifact per hypothesis plus one for the
assessment — e.g. hypothesis A, hypothesis B and the policy — and every one
of them measures the *same* market forward return. Pooling them would turn
one market move into several apparent samples. Producer identity is
therefore **mandatory** in every group key, and 12E never produces an
overall return distribution across producers.

### 16. Read-only and AI boundary

Outcome aggregation does not write to the ledger, access bars, recompute a
return, call an AI provider, rank strategies, create a paper position or
produce a trading instruction. Outcome tracking as a whole reaches no paper
action and no research classification.

AI remains outside Phase 12. The Phase 11A explanation is built from a
`ResearchSnapshot` only and never sees a ledger, a result or a summary. A
later Phase 11B may consume bounded aggregates **for explanation only**; the
LLM will have no authority over evaluation or aggregation there either.

## Known limitations

1. **Vendor revisions reduce coverage.** Any change to bar T's content
   refuses every later evaluation of claims about T; corporate-action
   back-adjustments refuse whole stretches. The resulting sample is
   selected, not random.
2. **Reasons for missing outcomes are not persisted.** `PENDING`, `REFUSED`,
   `INELIGIBLE` and `OUT_OF_WINDOW` are derived per refresh and reported
   once; the ledger records only claims and completed outcomes.
3. **Corrupt or torn lines stop the partition.** A `LedgerCorruption` names
   the line and byte offset and nothing proceeds until a person inspects it.
4. **No automatic repair tooling.** Nothing rewrites, truncates or
   quarantines a bad line.
5. **Original evidence values are not retained.** An artifact copies the
   claim (state, reason codes) but not the feature values that produced it;
   full forensic reconstruction of *why* a hypothesis said what it said
   needs the bars and the hypothesis version, not the ledger alone.
6. **JSONL scans do not scale indefinitely.** Every operation re-reads the
   partition; fine at thousands of lines, not designed for millions.
7. **Vendor "RAW" may not be as-traded.** The RAW basis is what the provider
   returns with `auto_adjust=False`; that is not guaranteed to equal the
   historically traded price, and a vendor adjustment after the fact is
   exactly the revision that refuses evaluation.
8. **No inferential statistics.** Means and medians of overlapping,
   non-independent samples, with no confidence interval and no test.
9. **No costs and no profitability.** A forward return is a property of the
   market. No spread, slippage, sizing or fill is modelled, and none of
   these numbers is a return anyone could have earned.
10. **Horizons are daily-research oriented.** Production tracks
    `OUTCOME_HORIZONS = (1, 5, 20)` bars of whichever interval was refreshed
    (`1d`, `1wk` or `1mo`, each its own partition) on the RAW basis. The
    horizons were chosen with daily research in mind; 20 monthly bars is a
    different study, and no horizon is chosen per interval.

## Consequences

Positive:

- Prospective evidence: every claim carries the clock it was made under and
  the content of the bar it rested on, and can be completed only by data
  that arrived later.
- A strong causal boundary, enforced by record invariants rather than by
  convention.
- Reproducible claim identity across machines and time.
- Idempotent refresh: re-running is safe, and a partial failure resumes.
- Explicit coverage: incompleteness is a number, not an omission.
- Safe descriptive summaries that cannot pool producers or infer.
- No AI or trading authority is created anywhere in the phase.

Costs and trade-offs:

- More storage: every outcome line repeats its artifact.
- Strict failures: a conflict or a corrupt line stops the refresh rather
  than degrading.
- Missing outcomes under revision, and a selected sample as a result.
- No automatic recovery; manual inspection is the recovery path.
- JSONL's limited scale.
- Conservative semantics that will look like lost data when they are
  working as designed.
- Aggregates are descriptive, not inferential, and cannot answer "is this
  hypothesis good?".

## Alternatives rejected

- **Retrospective backfilling of prospective artifacts.** It would create
  records indistinguishable from live claims and hand every later study a
  lookahead it cannot detect. A replay is a different origin with different
  evidential weight, and it is not represented.
- **Dashboard rerenders as tracking triggers.** Streamlit reruns on every
  widget change; tracking on rerun would write on interactions the user did
  not ask for. Tracking runs once, in the Refresh branch, after publication.
- **Recomputing forward returns in outcomes.** A second implementation of
  Phase 4 is a second convention to drift. `OutcomeRecord` checks
  consistency with its own prices and computes nothing.
- **Storing pending / refused / ineligible as outcomes.** They would be
  records without a measurement, and a ledger that must later "update"
  them stops being append-only.
- **Silently accepting revised source bars.** It would attach outcomes to
  claims nobody made.
- **Cross-producer pooled return metrics.** Four artifacts at one bar are
  one market move; a pool would count it four times.
- **Hit-rate and ranking metrics.** They read as performance claims over
  overlapping, non-independent, cost-free samples. Not computed.
- **AI-generated outcome interpretation as authority.** The model can
  neither see nor score outcomes in Phase 12, and 11B is scoped to
  explanation only.
- **Automatic repair of corrupt ledger lines.** A tool that rewrites
  evidence is a tool that can rewrite the wrong line; the bytes stay and a
  person decides.

## Deferred

Not decided here and not committed architecture: headless or scheduled
collection (12G), a benchmarked retrospective study (Phase R), error
analysis (Phase 13), outcome-aware reasoning (11B), any dashboard
presentation of 12E summaries, any alternative storage engine, any second
data provider, intraday tracking, and any monitoring or repair tooling.

See [docs/outcomes.md](../outcomes.md) for the architecture as built,
[ADR 0002](0002-outcome-evaluation-conventions.md) for the Phase 4
conventions it rests on, and [ADR 0009](0009-grounded-reasoning.md) for the
AI boundary it preserves.
