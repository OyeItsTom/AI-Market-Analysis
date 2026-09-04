# ADR 0002 — Outcome evaluation conventions

- **Status:** accepted
- **Date:** 2026-09-04
- **Phase:** 4 (Outcome evaluation engine)

## Problem

Phase 3 produces `ResearchObservation` records: a hypothesis' classification of
evidence at a bar. Nothing yet asks what happened afterwards.

Answering that requires conventions that are individually small and jointly
decisive. Get any one wrong and the resulting numbers look like forward returns
while measuring something else — and nothing about a plausible-looking mean
return announces that it was computed from the wrong bar.

## Decisions

### 1. Outcome evaluation is separated from economic simulation

Phase 4 implements **outcome evaluation only**: forward returns and their
aggregation. No simulated position, cost, slippage, equity curve or trade
record exists.

*Rejected:* building both together. Everything a simulation adds is convention
— an entry rule, an exit rule, a cost assumption, a sizing rule — none of which
OHLC data can justify. Those conventions are cheap to add onto a correct
outcome layer and expensive to unpick from a wrong one. There is also a
presentational asymmetry: an equity curve reads as a performance claim in a way
a mean forward return does not, especially at zero cost.

### 2. Reference price = OPEN of bar `i+1`

An observation at bar `i` is derived from bar `i`'s **completed** OHLCV, so it
was not knowable at bar `i`'s open. Using bar `i`'s open as the reference would
place the reference *before* the information that produced the observation.

*Rejected:* bar `i` open (look-ahead), bar `i` close (present in the evidence,
but not demonstrably executable and still same-bar).

**This is an analytical convention, not a claim that an order could fill at
that price.** OHLC bars carry no order book, spread, queue position, latency,
market impact or partial fills.

### 3. Horizons are counted in bars, and the reference bar is bar one

```
reference_index = i + 1
future_index    = reference_index + horizon_bars - 1
```

So `horizon_bars=1` is a one-bar outcome from the next bar's open to that same
bar's close; `horizon_bars=5` runs to the close of the fifth bar, **counting
the reference bar as bar one**.

*Rejected:* calendar horizons ("5 days"). The system has no exchange calendar,
so a calendar horizon could not be resolved without inventing session rules.

### 4. `evaluable_from` is NOT used to select the reference bar

Phase 3's `evaluable_from` is `timestamp + interval.max_duration`, and
`max_duration` is an **upper bound** (Phase 2). For a monthly series, a 1 Feb
observation has `evaluable_from` of 3 March while the next bar opens 1 March.
Selecting "the first bar at or after `evaluable_from`" would silently **skip
March and use April**.

Reference selection is therefore by **bar count**, which is correct for every
interval. A regression test pins this.

### 5. Spacing guard applies to intraday intervals only

`BarSeries` validates that timestamps strictly increase but not that bars do
not *overlap*: two bars labelled `1h` thirty minutes apart are accepted. For
such a series the "next" bar begins before the observation bar's data is
complete.

The guard requires `next.timestamp - observation.timestamp >= interval` for
`1m/5m/15m/30m/1h`, where the interval is an exact physical duration in UTC.

It is **not** applied to `1d/1wk/1mo`: a daylight-saving transition changes the
UTC offset of a session-local midnight (verified: 8 → 9 March 2024 New York is
23 hours in UTC), and months vary in length. Applying it there would reject
valid data. The residual gap — malformed calendar-interval spacing — is
documented as a known limitation rather than papered over with a tolerance.

### 6. Same-basis evaluation is required

The observation's basis, the series' basis and the spec's `required_basis` must
all agree, or evaluation raises. No conversion happens inside evaluation.

Same-basis evaluation is *internally consistent*; it does not make adjusted
history point-in-time valid (ADR 0001).

### 7. Unavailable outcomes are retained, never dropped

Four statuses: `EVALUATED`, `NO_REFERENCE_BAR`, `INSUFFICIENT_FUTURE_DATA`,
`INELIGIBLE_OBSERVATION`.

Every supplied observation produces exactly one record. Silently dropping
observations whose horizon runs past the end of the data is how end-of-sample
survivorship enters a study, and the summary's accounting invariant
(`evaluated + ineligible + insufficient + no_reference == total`) makes a
dropped record impossible to hide.

`INELIGIBLE_OBSERVATION` was added beyond the three originally proposed:
`ResearchState.INSUFFICIENT_DATA` observations carry no classification to
evaluate, but must still appear in the totals. A fourth status was the smallest
way to keep both properties true.

### 8. Economic simulation deferred

To its own phase, with its own review.

## Consequences

- A forward return is a property of the market, not of a strategy; nothing in
  Phase 4 can be read as a performance claim.
- Off-by-one in the horizon changes the outcome specification's fingerprint, so
  results computed under different conventions cannot be silently compared.
- Overlapping horizons make observations non-independent; no significance
  testing is offered (see `docs/research_evaluation.md`).
- The bar-count horizon cannot express "one week" for an irregular series.

## Deferred

Economic simulation · exchange calendars · calendar-based horizons · spacing
validation for calendar intervals · point-in-time data · chronological
partition enforcement in code.
