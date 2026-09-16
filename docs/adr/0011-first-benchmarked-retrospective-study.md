# ADR 0011 — First benchmarked retrospective study (Phase R)

**Status**: accepted (Phase R: Baseline Study v1)

## Context

Twelve phases built a deterministic research pipeline — bars, features,
hypotheses, outcome evaluation, assessment, a dashboard, a prospective outcome
ledger — and never once asked what the hypotheses actually do on history
relative to a benchmark. Phase 4 ([ADR 0002](0002-outcome-evaluation-conventions.md))
can evaluate every bar of a stored series, and the dashboard evaluates one.
Nothing in between exists: no fixed universe, no fixed period, no benchmark,
no reproducible study artifact.

Phase 13 (error analysis and controlled improvement) needs a baseline to
improve against. Improving a hypothesis before measuring it would make the
measurement describe the improvement rather than the hypothesis.

The retrospective study also has a specific failure mode: it has as many
degrees of freedom as the researcher has knobs, and every knob turned after
seeing a result turns a description into a fit.

## Decisions

### 1. The methodology is frozen before the first result

The universe, windows, interval, basis, horizons, hypotheses, metrics,
benchmark and interpretation vocabulary are constants in
`src/research/definition.py`, covered by a study fingerprint and pinned by
tests. The CLI accepts `--git-commit` and `--out` and nothing else. The code
is committed before the first real-data run, the run records the commit, and
the results are committed after. A methodology change is a new study version
with its own fingerprint and output directory; version 1 is never re-run
after a change.

*Rejected:* a parameterised research CLI. Every parameter is a knob, and the
first study's value lies in having none.

### 2. Reuse, not a second evaluator

Observations come from `ResearchHypothesis.evaluate` over `build_evidence`;
outcomes from `evaluate_observations` under the Phase 12 `OutcomeSpec`s;
aggregates from `summarize`. Phase R adds windowing, grouping, a
descriptive-statistics helper (min, max, sign counts, episodes), a subtraction
and renderers. It computes no forward return and reads no price except for
the raw-basis diagnostic.

### 3. Matched unconditional benchmark

For each hypothesis × symbol × horizon the benchmark is the forward returns at
exactly the timestamps where that hypothesis produced an evaluable
observation, state ignored — Phase 4's `all_evaluated`. The state groups
partition it. It shares the identical timestamps, horizon, reference
convention and basis with the state-conditioned sample, and it costs nothing
to compute per hypothesis even though the three hypotheses' eligibility
differs by one bar.

*Rejected:* all market timestamps (differs by the eligibility gap and needs a
second code path); buy-and-hold (implies a position); a competitor indicator
strategy (a second research programme); a global market benchmark (different
data).

### 4. Three half-open windows

`[fetch_start, observation_start)` warm-up only; `[observation_start,
observation_end)` classification; `[observation_end, outcome_data_end)`
outcome-only buffer, read to measure the outcomes of late observations and
never classified. Warm-up is counted and reported, never a study observation;
a symbol with fewer than 51 warm-up bars fails loudly rather than having its
observation start moved. Bars outside the fetch window are refused, not
trimmed.

The buffer is **not** a held-out window. Chronologically untouched data
begins at `outcome_data_end`.

*Rejected:* truncating late observations (end-of-sample survivorship);
extending the observation window to use the buffer (the buffer would then
need its own buffer).

### 5. Universe and period

Five ETFs across four return drivers, chosen for asset-class diversity and
raw-basis safety before any result was seen. Single equities were excluded
because a split on the RAW basis reads as a large negative return. Ten fixed
calendar years, 2015 through 2024, spanning several regimes, chosen for
roundness and regime diversity rather than by any performance criterion.

*Rejected:* SPY only (cannot expose cross-symbol instability); SPY + QQQ
(near-tautological consistency); a broad universe (the first study must stay
readable).

### 6. Daily only, Phase 12 horizons

`1d` gives roughly 2,500 observations per symbol; weekly would give a few
hundred and a handful of crossovers; pooling intervals conflates what "20
bars" means. Horizons 1, 5 and 20 are the tracked Phase 12 specifications,
constructed in the research package and pinned by fingerprint to the
application's `OUTCOME_SPECS`, so retrospective and prospective numbers are
comparable later.

### 7. Descriptive only, with a small locked metric set

Count, mean, median, min, max, sign counts, episode count, and two deltas
against the matched row. No hit rate, positive-return rate, risk-adjusted
ratio, equity statistic, p-value or confidence interval. Phase 4's
`StateMetrics` carries a directional hit rate; the study does not surface it,
because a hit rate reads as accuracy and this study defines no prediction.

The episode count exists so that overlap is legible (`n=900, episodes=18`).
It is not an effective sample size.

### 8. No cross-symbol pooling

Primary reporting is hypothesis × symbol × horizon × state. Observation- and
symbol-weighted aggregates answer different questions and either lets a
high-count symbol dominate silently; neither is built in v1.

### 9. Artifacts and Git

Four generated files under git-ignored `data/research/<study>_v<n>/`:
`manifest.json`, `summary.csv`, `observations.csv`, `report.md`. At the
results gate the manifest, summary and report are copied to
`docs/research/baseline_study_v1/` and tracked; `observations.csv` never is
(large, provider-derived). The manifest records the SHA-256 of its three
sibling files -- never of itself; the command prints that -- and says which
are tracked. Writes are sequential and not rolled back; a partial directory
is refused by the next run rather than completed. The report states facts
only; interpretation is human, written after the run, in a fixed permitted
vocabulary.

### 10. Reproducibility identity

The manifest records the study fingerprint, the operator-supplied commit SHA,
the provider, and per symbol `bars_fingerprint` over the full fetched
sequence, with counts and bounds. Given identical inputs and clock the four
files are byte-identical; a different clock leaves the CSVs unchanged and
changes only `retrieved_at`, `generated_at`, the report line that prints them
and, consequently, the report's recorded hash. The application does not run `git`; the freeze procedure ties
the recorded SHA to the committed methodology.

### 11. Retrospective is not prospective

The study evaluates the dataset the provider returned at retrieval time,
which may embed revisions and back-fills. It is reproducible against that
fingerprinted dataset; it does not establish what the provider showed at any
historical instant. Phase 12's ledger ([ADR 0010](0010-prospective-outcome-tracking.md))
serves that purpose, and the two are not to be blurred.

### 12. Architecture

`src/research` is a domain package (definition, engine, renderers, and the
artifact store that is the one place it opens files — the same shape as the
Phase 12 ledger store, because the application layer opens no files under
[ADR 0005](0005-local-dashboard.md)). `src/application/study.py` fetches,
checks, fingerprints, orchestrates and chooses the output root.
`src/cli/baseline_study.py` parses two flags and prints. The research package
never imports a caller tier, and the CLI reaches the pipeline only through
the application.

## Known limitations

Overlapping windows; RAW basis with dividend discontinuities; provider
revisions; no exchange calendar; shared SMA structure across all three
hypotheses; sparse crossover states; no costs, fills or capital; no
inferential statistics. Phase 4 rebuilds `BarSeries.timestamps` on every
measurement, so a ten-year, five-symbol run takes minutes; acceptable for a
one-off study, noted for later.

## Consequences

- Phase 13 receives a fixed, reproducible baseline and evidence-backed
  questions, not a tuned result.
- A reader can recompute every summary row from `observations.csv` and every
  identity from the manifest.
- The study can honestly report no separation at all, and that report is
  complete.

## Alternatives rejected

An experiment-tracking framework, a notebook, pandas, a database, a generic
benchmark engine, a scheduler, an LLM anywhere in the numbers, and any
parameter that could be changed after seeing a result.

## Deferred

Phase 13 error analysis and controlled improvement; held-out evaluation on
data from `2025-03-01` onward; inferential methods that handle overlap;
cross-symbol aggregation with a stated weighting; an adjusted-basis re-run;
performance work on Phase 4's timestamp access.
