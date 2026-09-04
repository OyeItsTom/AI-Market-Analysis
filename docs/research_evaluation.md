# Phase 4 — Outcome evaluation

Written for an engineer who will build a simulation layer on top of this. Read
`docs/research_framework.md` (Phase 3) first, then
`docs/adr/0002-outcome-evaluation-conventions.md`.

> **Historical evaluation does not establish future profitability.** Phase 4
> measures what happened after a classification under a stated contract. It
> does not simulate trading, does not model costs, and cannot tell you whether
> anything here would make money.

---

## 1. Research observation vs outcome

| | Phase 3 | Phase 4 |
|---|---|---|
| Question | "what does this evidence classify as?" | "what happened afterwards?" |
| Uses | bars ≤ T | bars > T |
| Produces | `ResearchObservation` | `EvaluatedOutcome` |

**A `ResearchObservation` is not an action or an order.** `BULLISH` does not
mean "buy". Mapping a classification to a hypothetical action is a *simulation
policy*, which Phase 4 deliberately does not implement.

## 2. Observation timestamp vs knowability

`MarketBar.timestamp` is the bar's **open** time (Phase 1 invariant). An
observation at bar `i` is derived from bar `i`'s *completed* OHLCV — its close,
high, low and volume — none of which existed at bar `i`'s open.

> The signal timestamp is **not** an executable price timestamp.

Using bar `i`'s open as a reference price would use a price that existed before
the information that produced the observation. That is look-ahead bias, and it
looks entirely reasonable in a spreadsheet.

## 3. Reference-price convention: `NEXT_BAR_OPEN`

```
reference = OPEN of bar i+1
```

**This is an analytical convention, not a claim that a real order could fill
exactly at that price.** OHLC bars prove nothing about order books, spreads,
queue position, latency, market impact or partial fills.

Phase 3's `evaluable_from` is deliberately **not** used to find the reference
bar — see §14 and ADR 0002 §4.

## 4. Bar-count horizons

Horizons count **bars of the supplied series**, never calendar days. The system
has no exchange calendar, so "five bars" is the only statement it can make
honestly. A five-bar horizon on daily data spanning a holiday covers more than
five calendar days, and the framework does not pretend otherwise.

## 5. Horizon semantics — the reference bar is bar one

```
observation_index = i
reference_index   = i + 1
future_index      = reference_index + horizon_bars - 1
```

| `horizon_bars` | reference | future |
|---|---|---|
| 1 | bar `i+1` OPEN | bar `i+1` CLOSE |
| 2 | bar `i+1` OPEN | bar `i+2` CLOSE |
| 5 | bar `i+1` OPEN | bar `i+5` CLOSE |

`horizon_bars=5` is *"a five-bar outcome beginning at the next bar open and
ending at the close of the fifth bar, counting the reference bar as bar one"* —
never described loosely as "five bars later".

**Forward return** is arithmetic and unannotated:

```
outcome_value = future_price / reference_price - 1
```

A 5% move is `0.05`, never `5`. No logarithms, no annualisation, no percentage
scaling.

## 6. Statuses — nothing is dropped

| Status | Meaning |
|---|---|
| `EVALUATED` | a finite forward return was computed |
| `NO_REFERENCE_BAR` | the observation is the final bar; `i+1` does not exist |
| `INSUFFICIENT_FUTURE_DATA` | the reference bar exists but the full horizon does not |
| `INELIGIBLE_OBSERVATION` | the observation was `INSUFFICIENT_DATA` — no classification to evaluate |

**Every supplied observation produces exactly one record.** An unavailable
outcome is not a 0% return, not a loss and not a win. `EvaluatedOutcome`
enforces this: a non-`EVALUATED` record carrying a value raises.

`EvaluationSummary` checks that
`evaluated + ineligible + insufficient + no_reference == total`, so a silently
dropped record is impossible — end-of-sample survivorship stays visible.

## 7. Price basis

Observation basis, series basis and `OutcomeSpec.required_basis` must all
agree, or evaluation **raises**. No conversion, no fallback.

Same-basis evaluation is internally consistent. It does **not** make adjusted
history point-in-time valid — its factors depend on corporate actions that
happened after the dates they apply to (ADR 0001).

## 8. Provenance — preserved, not authenticated

`EvaluatedOutcome` carries hypothesis id, version and fingerprint; symbol,
interval, basis; observation timestamp and state; the outcome spec's
fingerprint and horizon; the status; and, where they exist, the reference and
future timestamps and prices and the outcome value. Immutable, and readable
without consulting any external mutable state.

**The trust boundary.** Evaluation validates an observation's *structure* —
symbol, interval, basis, and that its timestamp is a real bar in the supplied
series. It does **not** re-run the hypothesis, so it cannot verify that the
recorded fingerprint belongs to a real hypothesis, or that the state is one
that hypothesis would have produced. A hand-built observation is evaluated and
its claimed identity is copied verbatim into the record.

That is deliberate: Phase 3 production and Phase 4 evaluation are separated on
purpose, and re-deriving the observation inside evaluation would defeat the
separation. So these fields answer *"what does this record claim it came
from?"*, not *"is that claim true?"*.

Two further trust boundaries follow the same principle:

- **Ordering.** `evaluate_observations` returns records in the **caller's
  order** — it does not sort. Each record is independently correct regardless
  of ordering, and `summarize` is permutation-invariant, so ordering affects
  the output tuple only. Duplicate observation timestamps are rejected.
- **Aggregation.** `summarize` is a pure aggregation over trusted evaluated
  records. It checks they share one symbol, interval, basis and spec, but does
  not deduplicate: passing the same record twice counts it twice. Grouped or
  re-partitioned analyses may legitimately re-summarise the same records, so a
  blanket duplicate check there would be wrong.

## 8b. Record consistency

A record cannot describe bars its own status says were never reached.
`NO_REFERENCE_BAR` and `INELIGIBLE_OBSERVATION` carry no reference or future
fields; `INSUFFICIENT_FUTURE_DATA` may keep the reference bar it did find but
never a future one; `EVALUATED` must carry all of them plus a finite value.
Construction raises otherwise.

## 9. Metrics

Accounting: total, eligible, evaluated, ineligible, insufficient-future,
no-reference, and counts by `ResearchState`.

Per group (all evaluated, BULLISH, BEARISH, NEUTRAL): count, mean forward
return, median forward return, positive-return rate. Plus a directional hit
rate for BULLISH and BEARISH only.

**Undefined is `None`, never `0.0`.** No evaluated bearish observations means
`bearish.mean_forward_return is None` — not "the mean was zero".

## 10. Directional hit rate

- BULLISH hit ⟺ `forward_return > 0`
- BEARISH hit ⟺ `forward_return < 0`
- **exactly zero is a MISS for both**, and is counted, not discarded

The denominator is only the **evaluated outcomes in that directional state**.

For BULLISH the hit rate and the positive-return rate are the same quantity by
definition; for BEARISH they are not complements whenever zero returns occur.

## 11. Neutral treatment

`NEUTRAL` gets count, mean, median and positive-return rate — and **no hit
rate**. There is no direction to be right or wrong about, and scoring it either
way would be inventing a contract. `INSUFFICIENT_DATA` observations are
ineligible and reported separately.

## 12. Overlapping horizons

With `horizon_bars > 1`, consecutive observations share most of their forward
window — daily observations at H=20 overlap in 19 of 20 bars.

> **Observations are not independent samples.**

No p-values, confidence intervals or significance tests are computed, because
every standard one assumes an independence this data does not have. Do not add
them without an estimator that handles overlap.

## 13. Benchmark

`unconditional_mean_forward_return` is a **same-sample reference statistic**,
not an investment benchmark. It is the mean over **exactly the same evaluated
sample**, ignoring the classification.

It is **not** buy-and-hold, not a market index, not a risk-free rate and not
tradeable. Exceeding it does not demonstrate outperformance in any investment
sense: there is no position, no cost and no capital in this system. Same timestamps, same
horizon, same reference convention, same basis.

It equals `all_evaluated.mean_forward_return` by construction, and is named
separately so a reader comparing a bullish mean against "the market" can see
which sample the comparison was taken over. An "always bullish" baseline would
be arithmetically identical and is deliberately not built.

## 14. Causality protections

Two independent properties, tested over the whole pipeline
(`tests/evaluation_lookahead.py`):

1. **Post-horizon perturbation** — replacing every bar after an outcome's
   future bar must not change it.
2. **Truncation invariance** — truncating immediately after the future bar must
   give the identical record.

Neither subsumes the other: truncation changes length and removes later
timestamps, which perturbation preserves; perturbation changes later values,
which truncation removes.

The harness was attacked with evaluators reading the final dataset value,
global future maximum and minimum, dataset length, future-row existence, tail
parity, and tail direction. All are caught. An index-dependent evaluator passes
and *should*: a bar's index depends only on how many bars precede it, so it
uses no future information.

## 15. Held-out-data discipline — protocol, not enforcement

**Phase 4 does not enforce this in code.** No `Partition` exists yet.

- **Development data** may be used while designing hypotheses.
- **Held-out data** must be evaluated *once*.

Once held-out results have been inspected and used to change a threshold, the
hypothesis logic, the feature choice, the horizon or the evaluation protocol,
that data is no longer held out. Re-running it after tuning produces a number
that describes the tuning, not the hypothesis.

Splits must be **chronological**. Never randomly shuffle time-series
observations: shuffling puts future bars in the training set.

**No parameter optimisation is performed anywhere in Phase 4.** The framework
measures definitions supplied to it; it does not improve them, rank them, or
select a winner.

## 16. Limitations of OHLC evaluation

Historical bars do not establish an exact fill price, order-book liquidity,
queue position, bid/ask spread, market impact, latency or partial fills. The
next-bar-open reference is a convention chosen for causal safety, not a
simulated execution.

## 17. What Phase 4 does not do

No simulated positions, trades, entries, exits, transaction costs, slippage,
equity curves, drawdown, Sharpe ratio or trading win rate. The directional hit
rate is a **research** statistic about classifications — it is not a trading
win rate and must not be reported as one.

## 18. What Phase 4 does not prove

A hypothesis whose bullish mean forward return exceeds the unconditional mean
has **not** been shown to be profitable, tradeable, or statistically
significant. It has been shown to have that property, on that sample, under
that outcome contract, with overlapping and therefore non-independent
observations, before any cost.

> **Historical backtest performance does not establish future profitability.**
