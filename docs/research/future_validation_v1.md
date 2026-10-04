# FUTURE_VALIDATION_V1 — pre-registered prospective validation (M2)

**Status:** pre-registration. Defined, implemented and tested **before** any
prospective claim exists. Prospective Collection v1 is **not activated**; no
prospective outcome has been seen by anyone. Binding this definition into
activation (the M2 commit, its fingerprint and `origin/main` containment) is a
later, separate gate (M2B).

| Identity | Value |
|---|---|
| validation id | `future_validation_v1` |
| **FUTURE_VALIDATION_V1 fingerprint** | `79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab` |
| superseded (never committed) | `0b113f89387871f4f17c401fee1e71f7bdc7d330015f718328b5d6ea7a17f377` — measured E1/F on the host clock and described a coverage count after the cutoff; replaced in the M2A blocker repair |
| collection (`COLLECTION_V1`) | `af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8` |
| provenance policy (`PROVENANCE_V1`) | `ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117` |
| definition | `src/research/future_validation.py` |
| engine (pure) | `src/research/future_validation_engine.py` |
| runner | `src/application/future_validation.py`, `src/future_validation/store.py` |
| commands | `python -m src.cli.future_validation status` / `run` |
| decision record | `docs/adr/0014-future-validation-v1.md` |

The fingerprint is the full SHA-256 of the definition's canonical JSON (sorted
keys, compact separators, ASCII). It covers every rule written below; the
code pins it as `FUTURE_VALIDATION_V1_FINGERPRINT` and a test rebuilds it.
No command-line option can change any part of it.

## 1. The question

For each of **SPY, QQQ and IWM separately**: after prospective activation, for
legitimate Prospective Collection v1 `trend_alignment` BULLISH claims, how does
the 20-bar RAW forward return (h20) compare with the matched-unconditional
benchmark under exactly the Phase R `matched_unconditional_v1` semantics — and
how does that prospective comparison sit, descriptively, beside the frozen
Phase R retrospective reference?

### Rationale

Phase R (2015–2024) found that `trend_alignment` BULLISH observations on the
three equity ETFs had a **lower** h20 mean and median than the matched
unconditional benchmark (negative deltas on all three). Phase 13A examined
that finding and recommended no hypothesis change, only documentation. The
remaining open question is whether the sign of that retrospective
description holds on data that did not exist when the methodology was frozen.
This validation asks exactly that, once, under rules fixed now.

## 2. Primary analysis

| Item | Frozen value |
|---|---|
| hypothesis | `trend_alignment` v1, fingerprint `650add07184f8440` |
| state | BULLISH |
| horizon | 20 bars (h20), spec fingerprint `a040ca488aa3f51f` |
| basis / interval | RAW / `1d` |
| primary symbols | SPY, QQQ, IWM — **each its own result** |
| statistical view | observation level (matches the Phase R reference) |
| benchmark | `matched_unconditional_v1` |

Each primary symbol produces its own category. Nothing is pooled, averaged,
or combined across symbols; there is no vote and no overall result. SPY, QQQ
and IWM are correlated equity ETFs: the three results are not three
independent replications.

### Primary statistics (per primary symbol)

`bullish_observation_count`, `bullish_episode_count`, `bullish_mean_h20`,
`bullish_median_h20`, `matched_unconditional_count`,
`matched_unconditional_mean_h20`, `matched_unconditional_median_h20`,
`mean_delta`, `median_delta`; and, descriptively only,
`abs_mean_delta_ratio_vs_reference` and `abs_median_delta_ratio_vs_reference`.

## 3. Population, inclusion and exclusion

Per symbol, the population is the observation artifacts of the named
hypothesis (id, version and fingerprint exact) in the Prospective Collection
v1 ledger, read from the frozen input snapshot, that:

* settle strictly **after** `activated_at` (the reserved interval is excluded — §12);
* are **not** excluded by the provenance report (degraded evidence — §11);
* have a bar timestamp at or before the symbol's cutoff `C_s` (§7).

An observation contributes a value at horizon *h* only through a non-excluded
outcome record with that horizon's spec fingerprint and evaluation version 1.
An evaluable claim without such a record (still pending, refused after a bar
revision, or outside the fetched history) is unmatured: it is not a member of
any group and it splits episodes. `INSUFFICIENT_DATA` claims carry no outcome.

## 4. Benchmark — `matched_unconditional_v1`, reused exactly

The matched unconditional group is every matured forward return at exactly
the population observations of the **same hypothesis, symbol and horizon,
state ignored** — Phase R's `all_evaluated`. Means are `statistics.fmean` and
medians `statistics.median` over the values in bar order, computed with the
Phase R `DescriptiveStats` class itself; episodes with the Phase R
`count_episodes` function itself; a delta is the state statistic minus the
matched statistic. The engine's `describe_cell` is the Phase R `_group`
computation over a session sequence, and a test runs the frozen Phase R
engine and this engine over one synthetic study and requires identical
counts, means, medians, extremes, sign counts, episode counts and deltas for
every hypothesis, horizon and state.

## 5. Retrospective references (exact, frozen)

Derived once from the tracked Phase R `docs/research/baseline_study_v1/summary.csv`
(rows `state/bullish` and `matched_unconditional/all`, `trend_alignment`,
h20, spec `a040ca488aa3f51f`) and pinned as literals. A test re-derives them
from the file, whose bytes are pinned; nothing re-reads the file at run time.

| Source | Value |
|---|---|
| study | `baseline_study` v1, fingerprint `1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261` |
| methodology commit | `5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31` |
| result commit | `3625e10656b6d11b40479a09d2c467e190480b2e` |
| `summary.csv` SHA-256 | `cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee` |
| `manifest.json` SHA-256 | `d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf` |
| benchmark policy | `matched_unconditional_v1` |

| Symbol | BULLISH n / episodes | BULLISH mean | BULLISH median | matched n | matched mean | matched median | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|
| SPY | 1709 / 26 | 0.00618879428271334 | 0.013607798752205635 | 2516 | 0.009315311305321278 | 0.015199267558811735 | -0.0031265170226079386 | -0.0015914688066061 |
| QQQ | 1732 / 27 | 0.009176130346056625 | 0.016815690415374895 | 2516 | 0.014004018405437404 | 0.019558389789087194 | -0.004827888059380779 | -0.0027426993737122984 |
| IWM | 1580 / 32 | 0.002112656389286471 | 0.006034942929120213 | 2516 | 0.00656092928863241 | 0.009627624744022567 | -0.0044482728993459385 | -0.0035926818149023543 |

Every reference delta is non-zero; the definition refuses to construct with a
zero reference (it would have no sign and could not be a ratio denominator).

## 6. Stop rule (Level 1, blind)

The validation becomes **unlockable** when

* **E1** — `evidence_through` is at least **48 calendar months** after `activated_at`, **and**
* **E2** — for **each** of SPY, QQQ and IWM, at least **750** population
  `trend_alignment` claims carry a matured h20 outcome;

**or** when

* **F** — `evidence_through` is at least **72 calendar months** after
  `activated_at` (forced unlock: permitted even if E2 is not met; the adequacy
  rule alone then decides whether each symbol is conclusive).

**The evidence clock.** `evidence_through` is the settlement time (bar timestamp
plus one daily bar period) of the latest claim bar — any symbol, any producer —
in the frozen input snapshot whose key the provenance report does not exclude
and whose bar settles strictly after `activated_at`; none when there is none.
These are provider market dates that the collector could claim only while they
were current, so the clock cannot run ahead of the collected evidence.

**The host wall clock is not authoritative.** It never decides E1, F,
unlockability, `C_s`, adequacy, a category, a population or a result. `status`
reads no clock at all; `run` reads it once, for the unlock's
`host_recorded_at` metadata. Setting the host clock forward (or backward)
cannot open — or close — the validation.

**A stalled collection never opens.** If collection stops before
`evidence_through` reaches 72 calendar months (and E1 with E2 was never met),
FUTURE_VALIDATION_V1 is never opened (§16).

**Calendar months.** `activated_at` is converted to UTC; adding *n* calendar
months adds *n* to the month (carrying into the year), keeps the time of day,
and clamps the day to the last day of the target month (2026-01-31 + 1 month =
2026-02-28; 2028-02-29 + 48 months = 2032-02-29; + 72 months = 2034-02-28). A
threshold is met when `evidence_through` is at or after that boundary; with no
`evidence_through`, no threshold is met. It is never approximated as a number
of days; DST cannot affect it.

**Blindness.** The stop rule and `status` read only Level-1 metadata:
identities, fingerprints, artifact and outcome keys, bar timestamps (the
evidence clock is computed from claim keys and bar timestamps alone), horizons,
spec fingerprints and provenance status. Never a state, reason code, price,
return, sign or aggregate, and never the host wall clock. BULLISH episode
adequacy is therefore **not** part of the stop rule.

## 7. Cutoff `C_s`

At unlock, per symbol, `C_s` is the latest bar timestamp of a population
`trend_alignment` claim with a matured h20 outcome in the frozen input
snapshot (none when there is none). It is recorded in `unlock.json`. It is
distinct from the evidence clock: `evidence_through` measures how far the
collected evidence reaches (for E1/F), `C_s` bounds the analysis. Every
analysis of the symbol — primary and secondary — uses only claims at or before
`C_s`; collection may continue, but nothing later can alter the v1 result.

## 8. Adequacy (after unlock)

A primary symbol is adequate when its primary population has at least
**8 BULLISH episodes** with matured, provenance-eligible h20 observations.
Fewer than 8: `inconclusive_insufficient_sample`. There is no BEARISH-episode
minimum and no unconditional-sample minimum: the 750-claim stop rule already
supplies broad coverage.

## 9. Episodes

Per symbol, the **session sequence** is the sorted union of every registered
claim bar timestamp (any producer) and every known missed tail recorded in the
run log, at or before `C_s` and after activation. An episode is a maximal run
of consecutive positions that are population observations in the state with a
matured value at the horizon — exactly Phase R's `count_episodes` membership
(and the Phase 13A same-state run concept). A missed session, an excluded or
unmatured claim, or a session with no claim of the hypothesis is a non-member
and **splits** an episode; missing observations never bridge one. A weekend or
holiday has no bar and does not split. Episode count is an adequacy measure
and dependence context, not a second primary test.

## 10. Categories (per primary symbol)

Evaluated in this order:

1. `invalid` — the symbol's evidence failed an identity, provenance or
   measurement-integrity condition (e.g. a reference bar not after its claim).
2. `inconclusive_insufficient_sample` — fewer than 8 BULLISH episodes.
3. directional category:
   * `directionally_consistent` — prospective mean delta **and** median delta
     are both non-zero and each has the same sign as its frozen reference delta;
   * `directionally_reversed` — both non-zero and each has the opposite sign;
   * `mixed` — everything else: mean and median disagree, either is exactly
     zero, or one is consistent and the other reversed.

The category is a function of six inputs only: validity, adequacy, the two
prospective primary deltas and the two frozen reference deltas.

**Magnitude ratios** (`abs(prospective delta) / abs(reference delta)`, mean and
median separately; null when the prospective delta is undefined) are reported
**descriptively only**. They never enter a category, and no magnitude
threshold of any kind exists — not 0.5x, not any other value.

**No overall result.** The output is three symbol-level categories side by
side. There is no overall verdict, no pooled or averaged statistic, no vote
and no k-of-3 rule.

## 11. Provenance and degraded evidence

The live provenance policy must be `PROVENANCE_V1` (fingerprint above).

* `ok` — proceed.
* `degraded` — proceed only with **every** excluded artifact and outcome key
  removed before any count, cutoff, population, benchmark, episode, primary or
  secondary statistic; an excluded claim position is a non-member of every
  episode. Degraded evidence is never primary or secondary evidence.
* `invalid` — the runner refuses; nothing is unlocked.
* `unknown` — the runner refuses until provenance can be determined.

## 12. Reserved interval

Bars from **2025-03-01** up to `activated_at` (any bar that settles at or
before `activated_at`) are permanently outside FUTURE_VALIDATION_V1 and are
never combined with prospective claims. A separately pre-registered
retrospective study may examine them; it would be a different study.

## 13. Secondary analyses (descriptive only)

None of these can change a primary category, replace the primary conclusion
or produce a combined result. All are restricted to claims at or before each
symbol's `C_s`.

* `A_primary_cell_h5` — the primary cell at horizon 5.
* `B_trend_alignment_bearish` — `trend_alignment` BEARISH vs matched unconditional, h5 and h20.
* `C_primary_episode_start` — h20 values at the first observation of each primary BULLISH episode.
* `D_primary_by_calendar_year` — the primary cell per calendar year of the bar timestamp.
* `E_momentum_in_trend_context` — BULLISH and BEARISH vs its own matched unconditional, h5 and h20.
* `F_trend_alignment_tlt_gld` — `trend_alignment` BULLISH and BEARISH h20 on TLT and GLD, per symbol.
* `G_coverage` — per symbol, **at or before the cutoff only**: missed
  sessions; population claims; matured h20 claims; unmatured claims (pending,
  refused, revised or outside the fetched history — not distinguishable per
  claim from the ledger); degraded/excluded claims; insufficient-history
  claims; plus the count of reserved-interval claims excluded. No run-level
  count from after the cutoff is reported.

## 14. Out of scope

* trend_crossover (sparse transition states)
* assessment-policy artifacts as validation targets
* horizon 1
* NEUTRAL subgroups and reason-signature groups
* the depressed-RSI question
* the adjusted price basis
* pooled cross-symbol statistics
* a pooled asset-class statistic
* hit rate
* Sharpe or any risk-adjusted ratio
* p-values
* confidence intervals
* any trading, position or profit framing
* the reserved interval from 2025-03-01 to activated_at

## 15. Invalidity

INVALID conditions: prospective provenance invalid; COLLECTION_V1 fingerprint
mismatch (manifest or live code); PROVENANCE_V1 fingerprint mismatch;
FUTURE_VALIDATION_V1 fingerprint mismatch; activation manifest corruption;
required ledger or run-log corruption; required historical records missing (a
frozen input prefix changed, shrank or vanished); M2 definition or runner
identity mismatch once activation binding exists; a material lookahead or
measurement defect discovered in the evidence; unsupported evidence
contamination that cannot be excluded safely (e.g. a symbolic link in the
ledger).

**Not** invalidating (they affect coverage or conclusiveness only): missed
sessions, provider refusal, bar revisions, degraded evidence that was
excluded, low sample, operational early termination of collection.

An evidence base that is invalid or unknown at the gate is **never opened**:
the runner refuses and writes nothing, and `status` reports the validity. A
measurement defect found after unlock makes that symbol's category `invalid`.

## 16. Early termination

None in v1. There is no operator-controlled, host-clock or result-driven
early opening. If Prospective Collection v1 ends permanently before
`evidence_through` reaches 72 calendar months (and E1 with E2 was never met),
**FUTURE_VALIDATION_V1 is never opened** — there is no fallback to the host
clock and no "terminate and validate now" action. Analysing such a terminated
collection would require a separately pre-registered amendment or a new
validation version, frozen before anyone looks. This deliberately prefers
blindness and pre-registration integrity over a guaranteed eventual opening.

## 17. One-open rule, snapshot and crash recovery

    status (Level 1) -> explicit run -> write-once unlock.json
                     -> deterministic computation -> write-once result.json -> report.md

Files live under the ignored collection root:
`<prospective root>/validation/future_validation_v1/<fingerprint>/{unlock.json,result.json,report.md}`,
named by the definition's full fingerprint, so a run under any other
definition can never occupy or block this definition's one opening.

* **Snapshot.** The activation manifest, the run log and every ledger file are
  read into memory under the collection root's **shared, non-blocking** lock
  (the same lock `health` takes; a running collector holds it exclusively, so
  the run refuses with `collect_in_progress`; a collector starting meanwhile
  waits its bounded 30 s). The lock is released once the bytes are in memory;
  the analysis reads a private temporary copy of exactly those bytes, so
  collection may continue without being able to change the result.
* **unlock.json** (canonical JSON, written once by atomic no-replace link)
  records: schema, validation id/fingerprint, runner version,
  `host_recorded_at` (host clock, metadata only), `activated_at`, the
  activation manifest SHA-256, the collection and provenance fingerprints, the
  provenance status and exclusion counts, the stop-rule evidence
  (`evidence_through`, E1/E2/F, counts, due dates, basis), every symbol's
  `C_s`, the snapshot (every file's path, byte length, SHA-256 and exact/prefix
  match rule, the directory list and an overall identity) and the runner's
  repository HEAD/cleanliness when available. No research value.
* **Crash after unlock.** If `unlock.json` exists without `result.json`, a run
  may only complete that same unlock: it re-reads only the recorded prefix of
  each recorded file (the manifest must be byte-identical), refuses if any
  prefix changed, shrank or vanished, ignores anything appended later,
  re-evaluates the gate on those bytes (the evidence clock is part of them) and
  requires the same stop-rule evidence, cutoffs and provenance status. A second
  unlock is never created.
* **result.json** (canonical JSON, write-once) holds the per-symbol category,
  primary metrics, magnitude ratios, adequacy, `C_s`, retrospective reference,
  secondary results, coverage, disclosures, limitations and identities.
  **report.md** is rendered deterministically from it. Once `result.json`
  exists, `run` never replaces it. Every later run **verifies** it: the result
  must name the unlock on disk by its SHA-256 and be byte-identical to the
  result re-derived from that unlock's recorded prefixes, or the run refuses
  (`result_mismatch`, `result_unlock_mismatch`, `result_unverifiable`). Only a
  verified result has its missing report rendered; a differing report is
  refused. An edited result is therefore detectable for as long as the
  recorded ledger prefixes survive.

## 18. Result language and disclosures

Categories are the only verdict words. The result is a research comparison
only; it makes no claim about positions, costs or achievable returns. Every
report states:

* h20 forward windows of adjacent observations overlap heavily (up to 19 of 20 bars).
* Observations within one episode are serially dependent; the observation count is not a count of independent trials.
* SPY, QQQ and IWM are correlated equity ETFs; the three symbol results are not three independent confirmations.
* No inferential significance claim is made: no p-value, confidence interval or test.
* This is a research comparison of forward returns only. It says nothing about any position, order, cost or achievable return of any market participant.

## 19. Limitations

* RAW basis: distributions appear as discontinuities.
* No exchange calendar: sessions are the bars the provider returned.
* An unmatured claim's reason (pending, refused, revised, outside the history)
  is not recorded per claim by the ledger.
* Exclusions shrink the sample; nothing is repaired.
* The retrospective reference describes 2015–2024 on one retrieved dataset;
  the prospective period is a different market period.
* **Pre-activation, unresolved here:** dependency drift between activation
  and later runs (runtime enforcement against activation metadata, or a
  verified pinned environment) must be resolved by the later M2B /
  activation-hardening gate.
