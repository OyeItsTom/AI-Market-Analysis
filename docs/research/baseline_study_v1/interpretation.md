# Phase R — Baseline Study v1 Interpretation

| item | value |
|---|---|
| METHODOLOGY SHA | `5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31` |
| STUDY FINGERPRINT | `1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261` |
| DATA RETRIEVED | `2026-09-16T22:32:33.017027+00:00` (source `yfinance`) |
| GENERATED | `2026-09-16T22:33:54.034807+00:00` |
| frozen artifacts | `manifest.json` `d6d4d8e7…6158bf`, `summary.csv` `cbae399a…cd49ee`, `report.md` `7fa913dc…6ca3f7` (in this directory, byte-identical to the run output); `observations.csv` `c2be1f66…28af76` (37,740 rows; generated raw audit artifact, kept under `data/research/`, not tracked) |

> Interpretation written after the frozen result was generated. It does not
> alter Baseline Study v1 methodology or generated result artifacts.

Every number below is copied from `summary.csv` (full precision there;
rounded to five decimals here) or `manifest.json`. Forward returns are
fractions (0.01 = 1 %) measured from the open of the bar after the
classification to the close of the horizon's last bar, on RAW prices. A
"delta" is a state row's mean or median minus the matched unconditional row's
mean or median for the same symbol, hypothesis and horizon — a descriptive
difference, nothing more. This document uses only the vocabulary the
methodology permits (`docs/research_baseline_study.md`, "Interpretation
rules"): nothing here is a claim of profitability, predictive edge, accuracy
or significance.

## Scope

The study answers one descriptive question: when each of the three existing
hypotheses, unchanged, emitted each state on five ETFs over the daily bars of
2015-01-01 through 2024-12-31, what forward returns at 1, 5 and 20 bars were
subsequently observed, and how do those distributions compare with the
matched unconditional distribution? It measures the system as it was; it
changes nothing. Bars from 2025-01-01 through 2025-02-28 were read only to
measure outcomes of late-2024 observations; chronologically untouched data
begins at 2025-03-01.

## Coverage and sample structure

- 37,740 observation rows: 2,516 observation bars × 5 symbols × 3
  hypotheses. Every symbol delivered 2,640 bars (85 warm-up, 2,516
  observation, 39 outcome-buffer), first bar 2014-09-02, last bar 2025-02-28.
- No `INSUFFICIENT_DATA` observation fell inside the window; all 113,220
  (observation × horizon) outcomes are `evaluated`; no
  `insufficient_future_data`, `no_reference_bar` or `ineligible_observation`
  occurred. Coverage is therefore complete and the matched unconditional row
  of every cell is the full 2,516-bar sample.
- Matched unconditional means at h20 (the drift each delta is measured
  against): SPY +0.00932, QQQ +0.01400, IWM +0.00656, TLT −0.00243,
  GLD +0.00622. Over this decade the equity ETFs and gold drifted up on the
  RAW basis and long Treasuries drifted down.
- Largest absolute single-bar close change per symbol (RAW diagnostic): SPY
  0.10942, QQQ 0.11979, IWM 0.13267, TLT 0.07520, GLD 0.05369. These are the
  largest observed one-day moves in the fetched data; none is of the size a
  share split would produce, and nothing was excluded or adjusted.

State frequency (counts out of 2,516 per symbol, from the coverage rows):

| hypothesis | symbol | bullish | bearish | neutral |
|---|---|---|---|---|
| trend_alignment | SPY | 1709 | 724 | 83 |
| trend_alignment | QQQ | 1732 | 722 | 62 |
| trend_alignment | IWM | 1580 | 850 | 86 |
| trend_alignment | TLT | 1161 | 1243 | 112 |
| trend_alignment | GLD | 1325 | 1099 | 92 |
| momentum_in_trend_context | SPY | 1189 | 279 | 1048 |
| momentum_in_trend_context | QQQ | 1187 | 288 | 1041 |
| momentum_in_trend_context | IWM | 874 | 382 | 1260 |
| momentum_in_trend_context | TLT | 599 | 696 | 1221 |
| momentum_in_trend_context | GLD | 787 | 496 | 1233 |
| trend_crossover | SPY | 25 | 25 | 2466 |
| trend_crossover | QQQ | 25 | 25 | 2466 |
| trend_crossover | IWM | 29 | 30 | 2457 |
| trend_crossover | TLT | 28 | 29 | 2459 |
| trend_crossover | GLD | 27 | 28 | 2461 |

Three structural facts follow. `trend_alignment` is almost never NEUTRAL (62
to 112 bars, 2–4 % of the sample), so its dead-band of 0.1 % of the slow
average rarely engages, and its directional states come in long runs (23 to
32 episodes for roughly 720 to 1,730 observations; dividing the two frozen counts,
that is on average between about 31 consecutive bars per episode (SPY
BEARISH, 724/23) and 64 (QQQ BULLISH, 1,732/27)).
`momentum_in_trend_context` is NEUTRAL on 41–50 % of bars and fragments the
directional states into many more, shorter episodes (52 to 130). `trend_crossover` is directional on about 1 % of bars — 25 to 30
crossings per direction per symbol in ten years — and each directional
observation is its own episode by construction.

## Trend alignment

Directional states at h5 and h20 (h1 deltas of the directional states are
all within ±0.0008 and are omitted here; they are in `summary.csv`):

| symbol | h | matched mean | matched median | state | n | episodes | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|
| SPY | 5 | +0.00210 | +0.00375 | bullish | 1709 | 26 | −0.00043 | −0.00029 |
| SPY | 5 | +0.00210 | +0.00375 | bearish | 724 | 23 | +0.00132 | +0.00169 |
| SPY | 20 | +0.00932 | +0.01520 | bullish | 1709 | 26 | −0.00313 | −0.00159 |
| SPY | 20 | +0.00932 | +0.01520 | bearish | 724 | 23 | +0.00817 | +0.00591 |
| QQQ | 5 | +0.00318 | +0.00498 | bullish | 1732 | 27 | −0.00143 | −0.00104 |
| QQQ | 5 | +0.00318 | +0.00498 | bearish | 722 | 25 | +0.00356 | +0.00477 |
| QQQ | 20 | +0.01400 | +0.01956 | bullish | 1732 | 27 | −0.00483 | −0.00274 |
| QQQ | 20 | +0.01400 | +0.01956 | bearish | 722 | 25 | +0.01230 | +0.01020 |
| IWM | 5 | +0.00124 | +0.00209 | bullish | 1580 | 32 | −0.00081 | −0.00116 |
| IWM | 5 | +0.00124 | +0.00209 | bearish | 850 | 27 | +0.00143 | +0.00232 |
| IWM | 20 | +0.00656 | +0.00963 | bullish | 1580 | 32 | −0.00445 | −0.00359 |
| IWM | 20 | +0.00656 | +0.00963 | bearish | 850 | 27 | +0.00876 | +0.00749 |
| TLT | 5 | −0.00041 | +0.00029 | bullish | 1161 | 27 | +0.00083 | +0.00054 |
| TLT | 5 | −0.00041 | +0.00029 | bearish | 1243 | 29 | −0.00089 | −0.00063 |
| TLT | 20 | −0.00243 | −0.00276 | bullish | 1161 | 27 | +0.00275 | +0.00005 |
| TLT | 20 | −0.00243 | −0.00276 | bearish | 1243 | 29 | −0.00274 | −0.00194 |
| GLD | 5 | +0.00131 | +0.00104 | bullish | 1325 | 27 | +0.00059 | +0.00069 |
| GLD | 5 | +0.00131 | +0.00104 | bearish | 1099 | 28 | −0.00042 | −0.00045 |
| GLD | 20 | +0.00622 | +0.00350 | bullish | 1325 | 27 | +0.00121 | +0.00059 |
| GLD | 20 | +0.00622 | +0.00350 | bearish | 1099 | 28 | −0.00153 | −0.00116 |

Descriptively:

- On the three equity ETFs (SPY, QQQ, IWM) the BULLISH state had a lower
  mean forward return than the matched unconditional sample, and the BEARISH
  state a higher one, at every horizon (18 of 18 cells by mean). The median
  agrees in sign in 17 of those 18 cells; the exception is IWM BULLISH at h1,
  where both deltas are within ±0.0001 (mean −0.00002, median +0.00009). The
  observed state-conditioned differences were therefore opposite to the
  semantic direction of the state labels on the three equity ETFs, in this
  decade's data. The magnitude grows with horizon: for
  SPY BEARISH the mean delta is +0.00013 at h1, +0.00132 at h5 and +0.00817
  at h20. At h20 the equity BEARISH mean deltas (+0.00817, +0.01230,
  +0.00876) are the largest state deltas of any well-populated group in the
  study, but they remain small relative to the observed 20-bar range
  (roughly −0.31 to +0.24 on SPY).
- On TLT and GLD, at h5 and h20, the signs are the other way round: BULLISH
  deltas are positive and BEARISH deltas negative, with magnitudes below
  0.003 at h20 and, for TLT BULLISH at h20, a mean delta of +0.00275 beside a
  median delta of +0.00005 — the mean and median do not agree on any material
  separation there. At h1 the TLT deltas are all within ±0.0001 (both states
  slightly negative) and the GLD deltas within ±0.0002.
- The NEUTRAL state is too infrequent (62–112 observations spread over 39–52
  episodes) for its deltas to carry weight; their signs are mixed across
  symbols and horizons.
- The directional samples are large but clustered: the SPY BEARISH group's
  724 observations arrive in 23 episodes, so the overlapping 20-bar windows
  within each run share most of their bars. n overstates the amount of
  distinct information by a wide margin.

## Momentum in trend context

| symbol | h | matched mean | matched median | state | n | episodes | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|
| SPY | 5 | +0.00210 | +0.00375 | bullish | 1189 | 103 | −0.00046 | −0.00053 |
| SPY | 5 | +0.00210 | +0.00375 | bearish | 279 | 63 | +0.00375 | +0.00588 |
| SPY | 20 | +0.00932 | +0.01520 | bullish | 1189 | 103 | −0.00432 | −0.00344 |
| SPY | 20 | +0.00932 | +0.01520 | bearish | 279 | 63 | +0.01568 | +0.01039 |
| QQQ | 5 | +0.00318 | +0.00498 | bullish | 1187 | 115 | −0.00121 | −0.00148 |
| QQQ | 5 | +0.00318 | +0.00498 | bearish | 288 | 52 | +0.00591 | +0.00732 |
| QQQ | 20 | +0.01400 | +0.01956 | bullish | 1187 | 115 | −0.00554 | −0.00417 |
| QQQ | 20 | +0.01400 | +0.01956 | bearish | 288 | 52 | +0.01392 | +0.00903 |
| IWM | 5 | +0.00124 | +0.00209 | bullish | 874 | 130 | −0.00185 | −0.00239 |
| IWM | 5 | +0.00124 | +0.00209 | bearish | 382 | 71 | −0.00009 | +0.00382 |
| IWM | 20 | +0.00656 | +0.00963 | bullish | 874 | 130 | −0.00874 | −0.00977 |
| IWM | 20 | +0.00656 | +0.00963 | bearish | 382 | 71 | +0.00471 | +0.00168 |
| TLT | 5 | −0.00041 | +0.00029 | bullish | 599 | 85 | +0.00064 | +0.00072 |
| TLT | 5 | −0.00041 | +0.00029 | bearish | 696 | 85 | −0.00140 | −0.00115 |
| TLT | 20 | −0.00243 | −0.00276 | bullish | 599 | 85 | +0.00175 | −0.00316 |
| TLT | 20 | −0.00243 | −0.00276 | bearish | 696 | 85 | −0.00646 | −0.00459 |
| GLD | 5 | +0.00131 | +0.00104 | bullish | 787 | 91 | +0.00047 | +0.00125 |
| GLD | 5 | +0.00131 | +0.00104 | bearish | 496 | 90 | −0.00037 | +0.00070 |
| GLD | 20 | +0.00622 | +0.00350 | bullish | 787 | 91 | +0.00011 | +0.00059 |
| GLD | 20 | +0.00622 | +0.00350 | bearish | 496 | 90 | −0.00044 | +0.00113 |

Descriptively:

- The RSI14 condition makes the directional states subsets of the
  corresponding trend relation, and the sample shrinks accordingly: on SPY,
  BULLISH falls from 1,709 to 1,189 observations and BEARISH from 724 to 279,
  while episodes multiply (23 → 63 for BEARISH).
- The direction of separation on the equity ETFs is the same as for
  `trend_alignment`: BULLISH below the matched sample, BEARISH above, at h5
  and h20, with mean and median agreeing in sign except IWM BEARISH at h5
  (mean −0.00009, median +0.00382). On SPY and QQQ the h20 BEARISH deltas are
  larger in magnitude than the corresponding `trend_alignment` deltas
  (+0.01568 vs +0.00817; +0.01392 vs +0.01230) on a much smaller and more
  fragmented sample; on IWM they are smaller (+0.00471 vs +0.00876).
- On TLT the BEARISH state is below the matched sample at h5 and h20 (mean
  −0.00646, median −0.00459 at h20); the BULLISH state shows a mean delta of
  +0.00175 beside a median delta of −0.00316 at h20 — mean and median point
  in opposite directions. On GLD all directional deltas are within ±0.0015
  and their signs are mixed between mean and median: no descriptive
  separation.
- Adding RSI14 therefore left the broad sign pattern of the trend relation it
  subsets unchanged: the mean-delta sign agrees with `trend_alignment` in 28
  of the 30 directional cells (five symbols × two states × three horizons),
  the two exceptions being near-zero cells (IWM BEARISH h5, TLT BULLISH h1).
  It reduced sample size, increased episode fragmentation, and moved the h20
  magnitudes up on SPY/QQQ and down on IWM.
  Whether that is a property of the RSI condition or of the smaller samples
  cannot be told apart in this study, and nothing here says why.

## Trend crossover

| symbol | h | matched mean | matched median | state | n | episodes | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|
| SPY | 5 | +0.00210 | +0.00375 | bullish | 25 | 25 | −0.00145 | −0.00119 |
| SPY | 5 | +0.00210 | +0.00375 | bearish | 25 | 25 | −0.00596 | +0.00260 |
| SPY | 20 | +0.00932 | +0.01520 | bullish | 25 | 25 | −0.00291 | −0.00412 |
| SPY | 20 | +0.00932 | +0.01520 | bearish | 25 | 25 | −0.01445 | −0.01932 |
| QQQ | 5 | +0.00318 | +0.00498 | bullish | 25 | 25 | +0.00012 | +0.00032 |
| QQQ | 5 | +0.00318 | +0.00498 | bearish | 25 | 25 | −0.00627 | −0.00409 |
| QQQ | 20 | +0.01400 | +0.01956 | bullish | 25 | 25 | −0.00405 | +0.00410 |
| QQQ | 20 | +0.01400 | +0.01956 | bearish | 25 | 25 | +0.00126 | +0.00898 |
| IWM | 5 | +0.00124 | +0.00209 | bullish | 29 | 29 | +0.00431 | +0.00797 |
| IWM | 5 | +0.00124 | +0.00209 | bearish | 30 | 30 | −0.00417 | +0.00255 |
| IWM | 20 | +0.00656 | +0.00963 | bullish | 29 | 29 | +0.00664 | −0.01213 |
| IWM | 20 | +0.00656 | +0.00963 | bearish | 30 | 30 | −0.00152 | +0.01572 |
| TLT | 5 | −0.00041 | +0.00029 | bullish | 28 | 28 | +0.00480 | +0.00442 |
| TLT | 5 | −0.00041 | +0.00029 | bearish | 29 | 29 | −0.00192 | +0.00189 |
| TLT | 20 | −0.00243 | −0.00276 | bullish | 28 | 28 | +0.00157 | +0.00246 |
| TLT | 20 | −0.00243 | −0.00276 | bearish | 29 | 29 | +0.00370 | +0.00663 |
| GLD | 5 | +0.00131 | +0.00104 | bullish | 27 | 27 | −0.00433 | −0.00588 |
| GLD | 5 | +0.00131 | +0.00104 | bearish | 28 | 28 | −0.00118 | −0.00131 |
| GLD | 20 | +0.00622 | +0.00350 | bullish | 27 | 27 | +0.00374 | +0.00963 |
| GLD | 20 | +0.00622 | +0.00350 | bearish | 28 | 28 | +0.00450 | −0.00329 |

Descriptively:

- Each directional state holds 25 to 30 observations per symbol, each its
  own episode. The samples are sparse.
- Mean and median disagree in sign in 7 of the 20 cells above (for example
  SPY BEARISH h5: mean −0.00596, median +0.00260, with a group minimum of
  −0.10436; IWM BULLISH h20: mean +0.00664, median −0.01213). With samples
  this small a single 20-bar return moves the mean materially.
- Signs are not consistent across symbols at any horizon for either
  directional state (see "Cross-symbol consistency").
- The NEUTRAL state is 98 % of the sample, so its rows coincide with the
  matched unconditional rows (deltas within ±0.0003), as expected.
- These samples are too sparse and inconsistent for a strong descriptive
  conclusion about crossover events in either direction in Baseline Study
  v1.

## Neutral reason-code observations

`trend_alignment` and `trend_crossover` each have a single NEUTRAL reason
signature (`trend_margin_below_threshold`, `relationship_unchanged`), so their
neutral_reason rows equal their NEUTRAL rows. `momentum_in_trend_context`
splits into three signatures (counts per symbol at every horizon; deltas at
h20):

| symbol | signature | n | episodes | h20 mean delta | h20 median delta |
|---|---|---|---|---|---|
| SPY | momentum_midrange | 641 | 245 | +0.00015 | +0.00095 |
| SPY | fast_above_slow, momentum_depressed, contradicts | 192 | 77 | −0.00114 | +0.00741 |
| SPY | fast_below_slow, momentum_elevated, contradicts | 215 | 46 | +0.00410 | +0.00562 |
| QQQ | momentum_midrange | 607 | 261 | +0.00291 | +0.00014 |
| QQQ | fast_above_slow, momentum_depressed, contradicts | 210 | 82 | +0.00134 | +0.00992 |
| QQQ | fast_below_slow, momentum_elevated, contradicts | 224 | 52 | +0.00233 | +0.00235 |
| IWM | momentum_midrange | 830 | 285 | +0.00317 | +0.00606 |
| IWM | fast_above_slow, momentum_depressed, contradicts | 234 | 80 | +0.00416 | +0.01096 |
| IWM | fast_below_slow, momentum_elevated, contradicts | 196 | 47 | +0.01144 | +0.00737 |
| TLT | momentum_midrange | 819 | 269 | +0.00091 | +0.00317 |
| TLT | fast_above_slow, momentum_depressed, contradicts | 207 | 66 | +0.00882 | +0.01188 |
| TLT | fast_below_slow, momentum_elevated, contradicts | 195 | 70 | +0.00454 | +0.00181 |
| GLD | momentum_midrange | 804 | 266 | −0.00055 | −0.00263 |
| GLD | fast_above_slow, momentum_depressed, contradicts | 216 | 53 | +0.00514 | +0.00059 |
| GLD | fast_below_slow, momentum_elevated, contradicts | 213 | 70 | −0.00250 | +0.00282 |

The aggregate NEUTRAL state combines a large `momentum_midrange` group whose
deltas sit close to zero (positive mean delta in 5 of its 10 h5/h20 cells)
with two "contradiction" groups whose h5 and h20 deltas are mostly positive
(positive mean delta in 8 of 10 and 7 of 10 cells respectively; the
`fast_above_slow, momentum_depressed` group has h20 median deltas of
+0.00741, +0.00992, +0.01096, +0.01188 on SPY, QQQ, IWM, TLT, although on SPY
its h20 mean delta is −0.00114, so mean and median disagree there). The
negative cells are SPY h20 and QQQ h5 for the first contradiction group and
TLT h5 and GLD h20 for the second. On GLD the three groups are all near zero
or mixed. The reason codes therefore
separate NEUTRAL into descriptively different sub-samples on four of the
five symbols; the aggregate NEUTRAL row masks that. These are still
overlapping, episode-clustered samples (46 to 82 episodes per contradiction
group).

## Cross-symbol consistency

Sign of the mean delta and of the median delta by symbol, in the order SPY,
QQQ, IWM, TLT, GLD, for the two level hypotheses' directional states:

| hypothesis | state | h | mean-delta signs | median-delta signs |
|---|---|---|---|---|
| trend_alignment | bullish | 5 | − − − + + | − − − + + |
| trend_alignment | bullish | 20 | − − − + + | − − − + + |
| trend_alignment | bearish | 5 | + + + − − | + + + − − |
| trend_alignment | bearish | 20 | + + + − − | + + + − − |
| momentum_in_trend_context | bullish | 5 | − − − + + | − − − + + |
| momentum_in_trend_context | bullish | 20 | − − − + + | − − − − + |
| momentum_in_trend_context | bearish | 5 | + + − − − | + + + − + |
| momentum_in_trend_context | bearish | 20 | + + + − − | + + + − + |

The pattern is consistent *within* the equity ETFs and reversed on the bond
and gold ETFs. No directional state of either level hypothesis has the same
delta sign on all five symbols at h5 or h20. Across the five symbols the
behaviour is therefore inconsistent; within the three equity ETFs it is
consistent. For `trend_crossover` the signs are mixed in every cell (for
example BEARISH h5 mean deltas negative on 5 of 5 symbols but median deltas
positive on 3 of 5).

## Horizon consistency

- For the equity ETFs, the `trend_alignment` and `momentum_in_trend_context`
  directional pattern has the same sign at h1, h5 and h20 and its magnitude
  grows with the horizon roughly in proportion to the horizon length (SPY
  `trend_alignment` BEARISH mean delta +0.00013 → +0.00132 → +0.00817). It
  does not reverse.
- h1 deltas are everywhere tiny (all `trend_alignment` and most
  `momentum_in_trend_context` h1 deltas lie within ±0.0008; the largest,
  `momentum_in_trend_context` SPY BEARISH, is +0.00094). Larger h20 deltas
  are not stronger evidence: the overlap between adjacent windows grows with
  the horizon just as the deltas do.
- The h20 figures are the ones most affected by overlapping windows:
  adjacent observations share 19 of 20 future bars, and the level states
  come in runs of dozens of bars, so an h20 group with 700 observations and
  25 episodes describes about 25 partly-overlapping stretches of market
  history, not 700 outcomes.
- `trend_crossover` shows no horizon-stable pattern.

## Limitations

- **Overlap.** Forward windows overlap; at h20 adjacent daily observations
  share up to 19 of 20 future bars, and at h5 up to 4 of 5. `sample_count` is
  not a count of independent trials, and `episode_count` is a reading aid,
  not an effective sample size or a correction.
- **Correlated hypotheses.** All three hypotheses depend on the same
  SMA20/SMA50 relation; `momentum_in_trend_context` adds RSI14 and
  `trend_crossover` is a transition of the same pair. The similar equity
  patterns of the two level hypotheses are one observation seen twice, not
  two confirmations.
- **RAW basis.** Prices are unadjusted. SPY, QQQ and IWM pay quarterly and
  TLT monthly distributions that appear as small ex-date drops in both the
  state and the matched samples; GLD pays none. No adjustment was applied.
- **Retrospective data.** This is a study of the bars Yahoo returned on
  2026-09-16, fingerprinted per symbol in `manifest.json`. It does not
  reconstruct what the provider displayed on any historical date and is not
  the prospective evidence the Phase 12 ledger records.
- **No exchange calendar.** Horizons are bars of the fetched series; missing
  sessions are neither detected nor filled.
- **Sparse states.** `trend_alignment` NEUTRAL (62–112) and every
  `trend_crossover` directional state (25–30) are too small for descriptive
  weight; `momentum_in_trend_context` BEARISH on SPY/QQQ (279/288) is
  moderate and clustered.
- **One decade, one regime set.** The matched unconditional drift was
  positive for equities and gold and negative for TLT over 2015–2024; the
  deltas are measured against that drift and say nothing about other
  periods.
- **No costs, no execution.** Forward returns are properties of the market
  after a classification; no position, fill, cost, sizing or capital exists
  in the study.

## What this study does not establish

It does not establish that any hypothesis is profitable, predictive, an edge,
accurate, or that any state is a signal to buy or sell. It does not establish
statistical significance of any delta; no inferential method for overlapping
samples was applied and none is implied. It does not establish that the
equity-ETF pattern would recur in another period or on other instruments,
nor that the TLT/GLD reversal is anything but what this decade's data
happened to show. It does not rank symbols or hypotheses.

## Evidence-backed Phase 13 questions

1. **Dead-band width.** `trend_alignment` was NEUTRAL on only 2–4 % of bars
   (62–112 per symbol). Is a 0.1 % dead-band a meaningful third state, or is
   the hypothesis effectively binary?
2. **Direction of separation versus state label on equity ETFs.** On SPY,
   QQQ and IWM the BULLISH state's mean forward return was below, and the
   BEARISH state's above, the matched unconditional sample at every horizon,
   with the median agreeing in 17 of 18 cells. The observed differences were
   opposite to the semantic direction of the state labels. What does the
   SMA20/SMA50 level relation describe on these instruments over this
   decade, and should the state vocabulary continue to carry a directional
   meaning that this data did not follow?
3. **Asset-class dependence.** The sign pattern reversed on TLT and GLD,
   where deltas were also much smaller. Are the state definitions stable
   across asset classes, or is any later evaluation of them only meaningful
   per asset class?
4. **What RSI14 adds.** `momentum_in_trend_context` kept the trend relation's
   sign pattern, reduced the directional samples by roughly a third
   (BULLISH) to two thirds (BEARISH), fragmented the episodes, and changed
   h20 magnitudes in both directions across symbols. Does the RSI condition
   contribute information, or mainly subsample the trend state?
5. **NEUTRAL heterogeneity.** The momentum NEUTRAL state pools a
   near-zero-delta `momentum_midrange` group (600–830 per symbol) with two
   contradiction groups whose h5/h20 deltas were mostly positive on four of
   five symbols. Should "momentum contradicts trend" remain a NEUTRAL reason
   code, or is it a distinct classification worth its own vocabulary?
6. **Crossover sparsity.** 25–30 events per direction per symbol in ten
   years, with mean/median sign disagreement in 7 of 20 h5/h20 cells. Can a
   single-bar transition state be evaluated descriptively at daily
   resolution on this universe at all, and what would a transition
   hypothesis have to observe for its sample to become informative?
7. **Overlap and episode structure.** Directional level states arrive in 23
   to 32 episodes per symbol. Any Phase 13 comparison of a changed
   hypothesis against this baseline must reckon with the same clustering;
   what descriptive per-episode view (still non-inferential) would make such
   a comparison honest?
8. **RAW basis on distributing ETFs.** TLT's monthly distributions and the
   equity ETFs' quarterly ones sit inside the forward windows on both sides
   of every comparison. Does an adjusted-basis re-run of the same frozen
   methodology (as a new study version) change any of the descriptive
   patterns above?
9. **Held-out evaluation.** Chronologically untouched data begins on
   2025-03-01. A later phase could reserve that window for one pre-specified
   validation of whatever Phase 13 settles on, rather than consulting it
   during exploration; is the window long enough to be informative for the
   level states, and is it long enough for crossover states at all?

Phase R observes; none of these questions is answered or acted on here.
