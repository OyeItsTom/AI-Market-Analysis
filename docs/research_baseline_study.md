# Baseline Study v1 (Phase R)

Phase R is the project's first benchmarked retrospective research study. It
asks one descriptive question of the system exactly as it exists, on a fixed
universe and a fixed decade, and writes down the answer beside a matched
benchmark. It builds no new hypothesis, tunes nothing, simulates no trade and
infers nothing. See [ADR 0011](adr/0011-first-benchmarked-retrospective-study.md)
for why each decision was made and frozen before any result existed.

> **This methodology is frozen.** Every research decision below is a constant
> in `src/research/definition.py` and part of the study fingerprint. Changing
> any of them is a new study version. Nothing here may be changed after a
> result has been seen and re-run under the same version.

## The question

> For the fixed universe {SPY, QQQ, IWM, TLT, GLD}, using daily RAW bars from
> the current Yahoo adapter, with observations from 2015-01-01 through
> 2024-12-31, when each of the three current deterministic hypotheses emitted
> each `ResearchState`, what forward returns at horizons 1, 5 and 20 bars were
> subsequently observed, and how do those state-conditioned distributions
> compare descriptively with matched unconditional forward-return
> distributions over the same symbol, horizon and hypothesis-eligible
> timestamps?

The study does **not** ask which hypothesis is best, what to buy or sell, how
much money would have been made, whether anything is statistically
significant, whether a hypothesis is profitable, or whether the system has
predictive edge. A result that shows no descriptive separation anywhere is a
complete, valid outcome of this study.

## Identity

| field | value |
|---|---|
| `study_id` | `baseline_study` |
| `study_version` | `1` |
| `study_schema_version` | `1` (layout of the manifest and CSV columns) |
| `study_fingerprint` | SHA-256 over the canonical definition payload; pinned in `tests/test_research_definition.py` |

The fingerprint covers the universe, interval, basis, all four window bounds,
the minimum warm-up, every hypothesis identity (id, version, fingerprint,
canonical form), every outcome-specification identity, the metric list, the
delta list and the benchmark policy.

## Hypotheses

The three hypotheses the repository has, unchanged (`src/strategies/hypotheses.py`):

| hypothesis | version | fingerprint | evidence |
|---|---|---|---|
| `trend_alignment` | 1 | `650add07184f8440` | SMA20 vs SMA50 with a 0.1% dead-band |
| `momentum_in_trend_context` | 1 | `6589cb8021b76574` | RSI14 (55/45 bands) read against SMA20 vs SMA50 |
| `trend_crossover` | 1 | `f1126ca778e6f7ce` | SMA20/SMA50 transition, lookback 1 |

The state vocabulary is exactly `BULLISH`, `BEARISH`, `NEUTRAL` and
`INSUFFICIENT_DATA`. There is no conflicted state; "momentum contradicts
trend" is a reason code inside `NEUTRAL`, and the study reports it as such.

All three share the SMA20/SMA50 structure. They are **not independent
confirmations** of one another, and no combined score is computed.

## Universe

`SPY`, `QQQ`, `IWM`, `TLT`, `GLD`, in that reporting order. Five liquid
US-listed ETFs across four return drivers (US large-cap, US large-cap growth,
US small-cap, long Treasuries, gold), all listed before 2005 and, to the
authors' knowledge, unsplit within the window. They were chosen for
asset-class diversity and raw-basis safety, not for how any hypothesis behaves
on them. Single equities were excluded because a split on the RAW basis reads
as a large negative return.

## Data

| item | value |
|---|---|
| provider | the current `YahooFinanceProvider` (`source = "yfinance"`) |
| interval | `1d` only |
| basis | `RAW` — prices as traded, no split or dividend adjustment |
| settled bars | `include_unsettled=False` through the existing provider path |

Dividends (quarterly for SPY/QQQ/IWM, monthly for TLT, none for GLD) appear in
raw prices as small discontinuities on ex-dates. They affect a state group and
its matched benchmark identically, so they are documented, not corrected. The
run records `max_abs_single_bar_close_return` per symbol so that any jump is
visible; **nothing is deleted, adjusted, winsorised or excluded** because of
it.

## Windows (UTC, half-open)

| window | bounds | role |
|---|---|---|
| warm-up | `[2014-09-01, 2015-01-01)` | feature warm-up only; never a study observation |
| observation | `[2015-01-01, 2025-01-01)` | the classification window; last observation date 2024-12-31 |
| outcome-only buffer | `[2025-01-01, 2025-03-01)` | read solely to measure forward outcomes of late-2024 observations; never classified |

Every symbol must have **at least 51 settled bars** before the observation
start (SMA50 plus the crossover's one-bar lookback). Fewer is a loud failure;
the observation start is never moved to fit the data. Warm-up bars are counted
and reported, never classified into the study.

No observation or hypothesis classification after 2024-12-31 is part of
Baseline Study v1. Bars from 2025-01-01 through the outcome-data end are
outcome-only evidence. **They are not a held-out window.** Chronologically
untouched data begins at `2025-03-01T00:00:00Z`.

One fetch per symbol covers `[2014-09-01, 2025-03-01)`; a bar outside that
range is refused, not trimmed.

## Evaluation protocol

Everything is the existing machinery:

```
BarSeries -> build_evidence -> hypothesis.evaluate (every bar)
          -> evaluate_observations (per OutcomeSpec) -> summarize
          -> Phase R grouping -> renderers
```

| item | value |
|---|---|
| outcome specifications | horizons 1, 5, 20 bars; RAW; reference = open of bar `i+1`; future = close of bar `i+H` counting the reference bar as bar 1 — identical, by fingerprint, to the Phase 12 `OUTCOME_SPECS` (`83e9dabf9b4e27de`, `b586481caf972d58`, `a040ca488aa3f51f`) |
| statuses | every observation in the window receives one Phase 4 status per horizon: `evaluated`, `insufficient_future_data`, `no_reference_bar`, `ineligible_observation`; nothing is dropped |
| causality | features see only bars `<= T` (Phase 2); a hypothesis sees only `[T-lookback, T]` (Phase 3); an outcome reads bars `<= T+H` (Phase 4). Phase R adds no feature and no price arithmetic of its own |

## Benchmark

**Matched unconditional.** For each hypothesis × symbol × horizon, the
benchmark is the set of all `EVALUATED` forward returns at exactly the
timestamps where that hypothesis produced an evaluable observation, state
ignored. It is Phase 4's `all_evaluated` / `unconditional_mean_forward_return`
for the same outcome list, and the state groups partition it exactly.

It is not buy-and-hold, not an index, not another strategy, not all market
timestamps, and not tradeable. It is the one reference that shares the
identical timestamps, horizon, reference convention and price basis with the
state-conditioned sample.

## Result groups and metrics

Primary rows: `hypothesis × symbol × horizon × state` for evaluated `bullish`,
`bearish` and `neutral`, plus the matched unconditional row (`state = all`).
Secondary, predeclared: `neutral` split by exact reason-code signature.
`INSUFFICIENT_DATA` appears in coverage accounting only.

Per row, and nothing else:

| metric | definition |
|---|---|
| `sample_count` | number of evaluated outcomes in the group |
| `mean_forward_return`, `median_forward_return` | `statistics.fmean` / `statistics.median` over the group — the same functions Phase 4 uses |
| `min_forward_return`, `max_forward_return` | extremes of the group |
| `positive_count`, `negative_count`, `zero_count` | sign partition of the group; they sum to `sample_count` |
| `episode_count` | number of maximal runs of consecutive observation bars in the group; adjacency is observation-bar adjacency, so a weekend never splits a run |
| `mean_delta_vs_matched_unconditional` | group mean − matched unconditional mean |
| `median_delta_vs_matched_unconditional` | group median − matched unconditional median |

Undefined is empty (`None`), never `0`. The deltas are plain descriptive
differences; they are never called alpha, edge or excess profit.

**Not surfaced, by decision:** directional hit rate, positive-return rate,
Sharpe, Sortino, CAGR, drawdown, profit factor, alpha, accuracy, win rate, any
inferential statistic. Phase 4's `StateMetrics` still carries a hit rate; the
study does not read it.

## Coverage accounting

Per hypothesis × symbol: `bars_fetched`, `warmup_bars`, `observation_bars`,
`outcome_buffer_bars`, `total_observations`, and counts by state. Per horizon:
`evaluated`, `insufficient_future_data`, `no_reference_bar`, `ineligible`,
which sum to `total_observations`. Phase 4's summary enforces the balance and
the study re-checks it.

## Overlap

Forward windows overlap: at horizon 20, observations on adjacent daily bars
share up to 19 of 20 future bars. **`sample_count` is not a number of
independent statistical trials.** `episode_count` is a descriptive reading
aid, not an effective sample size and not a correction. No p-value, confidence
interval or significance test is computed in v1.

## Reporting

No cross-symbol pooling: no observation-weighted or equal-symbol aggregate
return figure exists in the outputs. Cross-symbol statements are made in
prose, from the per-symbol table, in the vocabulary below.

## Artifacts

A run writes exactly four files to `data/research/baseline_study_v1/`
(git-ignored):

| file | content | Git |
|---|---|---|
| `manifest.json` | identity, windows, hypotheses, specs, conventions, per-symbol bar fingerprints and counts, `retrieved_at`, `generated_at`, SHA-256 of the three sibling files, caveats | tracked copy at the results gate |
| `summary.csv` | one row per coverage cell and per result group; `row_type` ∈ {`coverage`, `state`, `matched_unconditional`, `neutral_reason`} | tracked copy at the results gate |
| `observations.csv` | one row per symbol × observation bar × hypothesis with state, reason codes and, per horizon, status, return, reference and future timestamps | **never tracked** — generated raw audit artifact |
| `report.md` | the same facts as tables, with the fixed limitations; no interpretation | tracked copy at the results gate |

Every state row is reproducible from `observations.csv`, and the tests prove
it. A completed run directory is never overwritten.

**Hash model.** The manifest records the SHA-256 of the exact bytes of
`summary.csv`, `observations.csv` and `report.md`. It does not contain its
own hash — a file cannot — so the command prints the manifest's hash on its
final line for the operator to record; a later reader verifies the manifest
file against that. The report never prints its own hash.

**Write failure.** The four files are written in order (manifest, summary,
observations, report) with no rollback. A run that fails part-way leaves
what it wrote; the next run refuses that directory as an existing one, so a
partial run is never silently completed. The operator removes it.

## Reproducibility

The manifest names the commit (`--git-commit`, operator-supplied and
verified at the freeze gate), the study fingerprint, the source, and for each
symbol the `bars_fingerprint` (`src.outcomes.identity.bars_fingerprint` over
the full fetched sequence: warm-up + observation + buffer), bar count, first
and last timestamps and the window partition. Given the same definition, the
same bars, the same commit and the same clock, all four files are
byte-identical; with a different clock the two CSVs are unchanged, the report
differs only on the line that prints the two instants, and the manifest
differs only in `retrieved_at`, `generated_at` and, because the report
prints them, the report's recorded hash.

This is a **retrospective** study of the dataset the provider returned at
retrieval time. The provider may have revised or back-filled bars; the study
is reproducible against the fingerprinted retrieved dataset and does not
establish what the provider displayed at any historical instant. Phase 12's
prospective ledger serves that audit purpose.

## Running it

```
python -m src.cli.baseline_study --git-commit <SHA> [--out DIR]
```

There is no flag for the universe, dates, interval, basis, hypotheses,
horizons, metrics, benchmark or state filtering. `--out` chooses where the
artifacts land; `--git-commit` records which commit was run. pytest never
runs the live study; every test uses injected deterministic bars.

## Freeze procedure

1. Approve this methodology.
2. Commit the code, tests and documentation — before any real-data run.
3. Record the commit SHA and confirm a clean tree.
4. Run the command once from that commit with `--git-commit <that SHA>`.
5. Copy `manifest.json`, `summary.csv` and `report.md` to
   `docs/research/baseline_study_v1/`; write the human interpretation and
   the Phase 13 questions; commit as the results gate.
6. Do not modify the methodology and re-run under version 1. A change is
   version 2, with its own fingerprint and output directory.

## Interpretation rules

Allowed: "BULLISH observations had a higher median 5-bar return than the
matched unconditional sample"; "the difference was small relative to the
range"; "windows overlap"; "behaviour was inconsistent across symbols"; "the
sample was sparse (n, episodes)"; "no clear descriptive separation was
observed".

Not allowed: profitable, predictive edge, strategy works, buy or sell signal,
beats the market, statistically significant, accuracy, hit rate, win rate,
confirmed by multiple hypotheses.

## Limitations

- overlapping forward windows; `sample_count` is not independent trials
- RAW basis; dividends and corporate actions appear as price discontinuities
- provider revisions and back-fills; retrospective, not prospective, evidence
- no exchange calendar; horizons are bars of the fetched series
- shared hypothesis structure; no independent confirmation
- crossover states are transitions and may be sparse
- no transaction costs, fills, positions or capital
- no profitability claim; no inferential statistics

## Phase 13 handoff

Phase R observes; Phase 13 changes. The results gate ends by listing
evidence-backed questions only — for example whether one hypothesis mostly
duplicates another, whether neutral states dominate, whether behaviour is
unstable across symbols, whether coverage is poor, or whether a state shows no
separation. None of those is answered, or acted on, in Phase R.

## Status — first frozen result

Baseline Study v1 was run exactly once from methodology commit
`5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31` (data retrieved
2026-09-16T22:32:33Z from `yfinance`) and mechanically validated. The tracked
result — `manifest.json`, `summary.csv`, `report.md` (byte-identical to the
run output) and the human-written `interpretation.md` — lives under
[docs/research/baseline_study_v1/](research/baseline_study_v1/). The raw
`observations.csv` stays under git-ignored `data/research/`. Nothing above
this section was changed by the result; a methodology change is version 2.

## References

Patterns borrowed as ideas only, with no dependency or code: Freqtrade's
separation of start-up candles from the evaluated time range (warm-up vs
observation window); LEAN's practice of recording every run parameter beside
the result (the manifest); Qlib's time-segment separation (the three windows).
