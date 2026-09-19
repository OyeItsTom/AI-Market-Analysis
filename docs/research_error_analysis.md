# Error Analysis v1 (Phase 13A)

Phase 13A diagnoses the current hypotheses using only the frozen output of
Baseline Study v1. It is a **read-only, zero-network, descriptive**
regrouping of the Phase R rows. It changes no hypothesis, threshold, feature,
basis, horizon, universe or window; it fetches no market data; it computes no
forward return; it performs no threshold search and no inferential
statistics. See [ADR 0012](adr/0012-hypothesis-error-analysis.md).

> **This methodology is frozen.** Every research choice below is a constant in
> `src/research/error_analysis.py`, covered by the study fingerprint and pinned
> by tests. Changing any of them is a new study version.

## Identity and source contract

| field | value |
|---|---|
| `study_id` / version / schema | `error_analysis` / 1 / 1 (label `error_analysis_v1`) |
| source study | `baseline_study` v1, fingerprint `1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261` |
| source methodology commit | `5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31` |
| source result commit | `3625e10656b6d11b40479a09d2c467e190480b2e` |
| source `manifest.json` SHA-256 | `d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf` |
| source `summary.csv` SHA-256 | `cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee` |
| source `observations.csv` SHA-256 | `c2be1f66f10d7dc31debfaac76d67c850664166a65d1585bdd3769d0a228af76` |
| source observation window | `[2015-01-01T00:00:00Z, 2025-01-01T00:00:00Z)` |

The engine is handed the three frozen texts and **fails closed** before any
diagnostic if a single byte differs from the pinned hashes, if the manifest's
identity (study, version, fingerprint, methodology commit, universe,
hypotheses, horizons, window) differs, if any observation lies on or after
2025-01-01 or before 2015-01-01 (refused, never filtered), or if any Phase R
state / matched / neutral-reason row of `summary.csv` fails to recompute
exactly from the raw rows. Baseline Study v1 is never rerun, regenerated or
modified; the source directory is re-hashed after the run.

## Locked choices

- **Universe, hypotheses, horizons**: copied from the source identity — SPY,
  QQQ, IWM, TLT, GLD; `trend_alignment@v1#650add07184f8440`,
  `momentum_in_trend_context@v1#6589cb8021b76574`,
  `trend_crossover@v1#f1126ca778e6f7ce`; horizons 1, 5, 20.
- **Segments** (half-open, UTC, by observation timestamp, fixed before any
  segment number was seen): `2015-2016` `[2015-01-01, 2017-01-01)`,
  `2017-2018` `[2017-01-01, 2019-01-01)`, `2019-2020` `[2019-01-01, 2021-01-01)`,
  `2021-2022` `[2021-01-01, 2023-01-01)`, `2023-2024` `[2023-01-01, 2025-01-01)`.
- **Asset classes** (descriptive metadata only): SPY, QQQ, IWM → `equity`;
  TLT → `treasury`; GLD → `gold`. Nothing is pooled by class and no
  class-specific parameter exists.
- **Metrics per group**: `sample_count`, mean, median, min, max,
  positive / negative / zero counts, `episode_count` — the Phase R set. Deltas
  are plain subtractions against a stated reference. Not surfaced: hit rate,
  positive-return rate, Sharpe, alpha, p-values, confidence intervals.

## Diagnostics

| id | what | reference for deltas |
|---|---|---|
| D1 episode structure | per hypothesis × symbol × state: episode count, observation count, length min / median / max, share of observations in the largest and three largest episodes; plus an **episode-start** view (returns of each episode's first bar only) marked `sampling_view = episode_start` | — |
| D2 gate decomposition | per symbol: the complete 4 × 4 `trend_alignment` × `momentum_in_trend_context` state cross-tab on common timestamps; per trend direction × horizon: partitions `retained` (momentum same direction), `removed` (momentum NEUTRAL, also split by exact momentum reason signature) and `opposite` (reported, never assumed impossible) | the parent trend state's own evaluated sample |
| D3 temporal segmentation | per hypothesis × symbol × horizon × segment: the segment's matched unconditional row and its bullish / bearish / neutral rows | the segment's matched unconditional sample |
| D4 asset-class signs | per hypothesis × state × horizon: each symbol's Phase R mean/median delta and its sign, annotated with its class, plus per-class sign strings | Phase R matched unconditional (recomputed) |
| D5 crossover events | one row per directional `trend_crossover` bar: timestamp, direction, bars since the previous crossing (none for the first), h1/h5/h20 returns as frozen | — |
| D6 semantic contract | report text quoting the source vocabulary contract: BULLISH / BEARISH are structural classifications that promise no forward direction | — |

An **episode** is a maximal run of consecutive observation-bar positions with
the same hypothesis state, as in Phase R; weekends and holidays do not split a
run; a reason-signature change inside a NEUTRAL run does not split it (the
signature recorded is the episode's first bar's). Segment membership uses the
observation timestamp only. Segment counts sum back to the full-window
counts; means recombine only through the raw observations; medians do not
recombine and the report never claims they do.

## Predeclared descriptive decision aids

Computed for every symbol, state and horizon so no favourable subset can be
chosen later, and labelled as such in every artifact:

- `segment_sign_agreement`: for a level hypothesis × symbol × directional
  state × horizon, how many of the five segments share the full-window sign
  of the mean delta and of the median delta (reference count 4 of 5).
- `episode_concentration`: the share of that state's observations held by
  its largest episode and its three largest (reference share 0.25).
- `gate_partition_signs`: the signs of the retained and removed partitions'
  mean and median deltas against the parent trend state.

They are **not** statistical significance tests, confidence criteria, proofs
of robustness, effective-sample-size corrections or acceptance thresholds.
The engine attaches no PASS/FAIL and selects no change; the human review gate
reads them.

## Artifacts

Generated under `data/research/error_analysis_v1/` (git-ignored) by
`python -m src.cli.error_analysis --git-commit <SHA> [--source DIR] [--out DIR]`:

| file | content | Git (results gate) |
|---|---|---|
| `manifest.json` | identity, fingerprint, `git_commit`, `generated_at`, source lineage with the three pinned hashes, segments, classes, decision-aid entries, SHA-256 of the three sibling files | tracked copy |
| `diagnostics.csv` | one row per diagnostic cell; `row_type` ∈ {`episode_summary`, `episode_start`, `gate_crosstab`, `gate_partition`, `segment_state`, `segment_matched`, `class_signs`, `crossover_event`} | tracked copy |
| `episodes.csv` | one row per episode with start/end/length and episode-start statuses and returns | tracked copy |
| `report.md` | the same facts as tables, the semantic contract, the decision aids (labelled), the fixed limitations; no interpretation | tracked copy |

`--source` and `--out` are locations, not research knobs; the source is
accepted only if its bytes are the frozen ones, and the output directory may
not be, contain or lie inside the source. A completed run is never
overwritten. The manifest never hashes itself.

## Future data

Data from **2025-03-01 onward** is chronologically untouched and remains so:
Phase 13A reads no provider, and any source row on or after 2025-01-01 is
refused. A later phase may reserve that window for **one** pre-specified
validation after a Phase 13 methodology freeze.

## What Phase 13A does not do

No hypothesis, threshold, feature, basis, horizon or universe change; no new
`ResearchState`; no NEUTRAL split in production; no adjusted-basis
reconstruction; no retirement or reframing of `trend_crossover`; no
profitability, edge, accuracy or significance claim; no selection of a Phase
13B change. Interpretation happens after a frozen real run, in a separate
human-written document.

## Status — first frozen result

Error Analysis v1 was run exactly once from methodology commit
`9ce8dab743bde6ace5737ab8e815f430d3b60c76` (generated
2026-09-18T22:01:15Z, offline, `network: none`) and mechanically validated.
The tracked result — `manifest.json`, `diagnostics.csv`, `episodes.csv`,
`report.md` (byte-identical to the run output) and the human-written,
independently reviewed `interpretation.md` — lives under
[docs/research/error_analysis_v1/](research/error_analysis_v1/). The
interpretation's conclusion is that no computational Phase 13B change is
justified; the only nominated follow-up is documentation hardening of what
BULLISH/BEARISH name, changing no computation. Nothing above this section
was changed by the result; a methodology change is version 2.

## References

Only Qlib's habit of comparing variants on identical samples is borrowed, as
the principle behind D2; no dependency or code from any external framework.
