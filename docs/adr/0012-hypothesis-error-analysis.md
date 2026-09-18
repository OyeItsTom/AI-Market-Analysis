# ADR 0012 — Hypothesis error analysis over the frozen baseline (Phase 13A)

**Status**: accepted (Phase 13A: Error Analysis v1)

## Context

Baseline Study v1 ([ADR 0011](0011-first-benchmarked-retrospective-study.md))
produced a frozen, hash-identified description of what the three current
hypotheses' states were followed by on five ETFs over 2015–2024. Its
interpretation raised questions — an equity-ETF sign pattern opposite to the
colloquial direction of the state names, a momentum hypothesis that gates
the same trend state, a heterogeneous NEUTRAL, sparse crossover events,
long clustered episodes, asset-class differences — but Phase R was built not
to answer them. Phase 13 is where they are examined, and the danger is
obvious: examining them by changing things is how a description becomes a
fit.

## Decisions

### 1. Diagnose first, change nothing

Phase 13A makes no change to any hypothesis, threshold, feature, basis,
horizon, universe or window and searches nothing. It regroups the frozen
Phase R rows along predeclared cuts. Whether any Phase 13B change is
warranted is decided afterwards, by a human, from the diagnostics — and "no
change" is a valid outcome.

*Rejected:* proceeding straight to candidate improvements.

### 2. The frozen artifacts are the only input

The engine consumes the exact bytes of Baseline Study v1's `manifest.json`,
`summary.csv` and `observations.csv`, pinned by SHA-256 in the definition,
and refuses anything else before computing a single number. It recomputes
every Phase R state row from the raw rows and requires exact equality with
the frozen summary, so the two artifacts are proven to describe one run.

*Rejected:* re-fetching bars (a new dataset, a second live run, provider
revisions); re-running Phase 4 (unnecessary — every return is already on the
rows).

### 3. No provider, no network

No Phase 13A module imports a provider or network client, and boundary tests
pin that. Perfect data identity, no accidental rerun, no way to touch future
data.

### 4. Common-timestamp gate decomposition

`momentum_in_trend_context` is a gate on the same SMA20/SMA50 relation as
`trend_alignment`; comparing each against its own matched sample cannot tell
"RSI changes outcomes" from "RSI selects fewer bars". Partitioning the trend
directional bars by the momentum state at the same bar — retained, removed
(by exact reason signature), opposite — against the parent trend state's own
sample can, descriptively. The opposite partition is reported rather than
assumed empty.

### 5. Predeclared segments

Five equal two-calendar-year blocks fixed before any segment number was
seen, assigned by observation timestamp. Counts recombine exactly; means only
through the raw rows; medians are never claimed to recombine.

*Rejected:* regime boundaries chosen from the data.

### 6. Episodes, and the episode-start view as secondary

Episodes are maximal same-state runs by observation position (Phase R's
definition); their lengths and shares make clustering legible. An
episode-start sampling view is provided **as a secondary diagnostic**,
labelled as such: it is not a replacement for Phase R and not an
independence correction.

### 7. Asset class is metadata

Symbols are annotated with a class so sign patterns can be read by class;
nothing is pooled by class and no class-specific parameter is introduced.

### 8. Decision aids are descriptive, not tests

A 4-of-5-segments sign count, an episode-concentration share and a
retained-vs-removed sign comparison are computed for every cell and labelled
"predeclared descriptive decision aids". The engine attaches no PASS/FAIL and
selects nothing; the human review gate reads them. Calling them anything
stronger would let an arbitrary constant impersonate statistical authority.

### 9. Semantic contract stated, labels untouched

The source vocabulary defines BULLISH/BEARISH as structural classifications
that promise no forward direction. The equity-ETF finding is therefore
described as forward-return differences opposite to the *colloquial
connotation* of the names, not as a wrong prediction, and no label is
reversed, renamed or re-tuned here.

### 10. Adjusted basis deferred

Changing the price basis changes the data representation for every
hypothesis; it belongs to a separate study version under the Phase R freeze
procedure, not to a diagnostic phase.

### 11. Future data untouched

Any source row on or after 2025-01-01 is refused; nothing from 2025-03-01
onward is read. That window is reserved for one pre-specified validation
after a later methodology freeze.

### 12. Architecture

`src/research/error_analysis.py` (pure engine and frozen definition) and
`error_analysis_render.py` (deterministic renderings) sit beside the Phase R
modules; the artifact store gained a read-back and a named-set write so the
application layer still opens no file; `src/application/error_analysis.py`
orchestrates; `src/cli/error_analysis.py` takes `--git-commit`, `--source`
and `--out` only. Outputs: `manifest.json` (hashing its three siblings, never
itself), `diagnostics.csv`, `episodes.csv`, `report.md`, all small and
tracked at the results gate.

## Consequences

- Phase 13B, if any, starts from named evidence rows rather than from a
  search.
- Every diagnostic is reproducible from the pinned inputs and the definition
  fingerprint.
- The report cannot conclude; a human must, and only after the frozen real run.

## Alternatives rejected

A parameterised diagnostics CLI; new indicators or thresholds "to see";
inferential statistics on overlapping samples; pooling by asset class; using
2025 data "just to look".

## Deferred

Phase 13B (one controlled change, if justified); NEUTRAL as explicit states;
crossover reframing or retirement; adjusted-basis study version; the single
future validation.
