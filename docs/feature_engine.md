# Phase 2 — Research data semantics and the feature engine

Written for an engineer who will build strategies and a backtester on top of
this. Read `docs/market_data.md` (Phase 1) first, then
`docs/adr/0001-price-basis-and-corporate-actions.md` for the price-basis
decision.

> Nothing here predicts markets or generates trading signals. These are inputs
> to research.

---

## 1. Where Phase 2 sits

```
Provider  →  Normalization  →  Validation  →  MarketBar        (Phase 1)
                                                  ↓
                                              BarSeries         ← Phase 2
                                          (symbol, interval,
                                           source, price basis)
                                                  ↓
                          ┌───────────────────────┴──────────────────┐
                          ↓                                          ↓
                   adjustment.adjust()                        feature engine
                   (raw → derived series)                     (pure functions)
                          ↓                                          ↓
                   derived BarSeries                          FeatureSeries
```

## 2. `BarSeries` — the safe unit

A bare `list[MarketBar]` is not a safe research input. It can silently mix
symbols, intervals, providers or price bases, and every one of those produces
plausible numbers rather than an error.

`BarSeries` guarantees, at construction: one symbol, one interval, one source,
one `PriceBasis`, unique and strictly increasing timestamps, and every bar
individually valid. Bars are held in a tuple, so a validated series cannot be
mutated or reordered afterwards.

**Features accept `BarSeries` only.** Passing a list raises `FeatureError`.

`require_compatible()` guards any operation combining two series and compares
**basis** as well as identity — a raw and an adjusted series for the same
symbol are not interchangeable.

### Phase 1 contract strengthened

`check_bars` now also reports `source_mismatch`. Phase 1 accepted a series
mixing two providers' bars; only `storage.write` caught it. `storage.write`
still raises `StorageError` for that case (its provenance check runs first),
so the Phase 1 storage contract is unchanged.

## 3. Price basis

See the ADR for the decision and its evidence. The operational summary:

| Basis | Meaning |
|---|---|
| `RAW` | Prices as traded and reported. The source of record. A split appears as a large mechanical move, because that is what happened to the quote. |
| `SPLIT_AND_DIVIDEND_ADJUSTED` | Scaled to remove the mechanical effect of **both** splits and cash dividends. Conventionally a "total return" basis. |

The name is deliberate: Yahoo's `Adj Close / Close` factor was verified against
the installed yfinance implementation to encode dividends as well as splits.
`SPLIT_ADJUSTED` would have been a misleading label.

**Raw is never overwritten.** An adjusted series is derived from raw, carries a
provenance string, and is persisted under its own storage identity: storage
identity is `(symbol, interval, source, price_basis)`, so raw and adjusted
never collide. Reading with the wrong basis fails loudly, and the file's own
`price_basis` column — not its filename — is the authority.

Adjusted *values* round-trip exactly (**value reproducibility**). The factors
that produced them are not stored, so the derivation cannot be re-executed
from storage alone (**transformation reproducibility** is DEFERRED).

### Point-in-time warning

An adjusted series is **not** point-in-time safe. Its factors depend on
corporate actions that happened *after* the dates they apply to. It is right
for computing comparable returns and wrong for "what was knowable then". A
backtester that conflates the two is using future information.

### Volume

Adjustment leaves volume **unchanged**, matching Yahoo. Therefore:

> Adjusted price × reported volume is **not** historical traded notional.

Volume also has a mechanical step at a split. Features needing price-volume
consistency must handle this themselves.

## 4. Sessions and gaps — exchange awareness is DEFERRED

`src/data/sessions.py` separates two things that are usually conflated:

- **Observation** — "these two bars are more than one interval apart". Factual,
  needs no calendar.
- **Classification** — "was that a missing session or a closed exchange?"
  Needs a calendar.

The system holds **no venue metadata**: `MarketBar` knows a symbol string and
a source, not an exchange. So the default `UnknownTradingCalendar` answers
`UNKNOWN` for every gap, and `find_gaps` reports observed gaps with that
status.

`UNKNOWN` means "this needs a calendar". It does **not** mean missing data.
`GapReport.missing_sessions` only ever contains gaps a real calendar positively
identified, so it is empty by default — `has_unclassified_gaps` is the flag
that says completeness is unverified.

Deliberately not done: inferring an exchange from a ticker (the same ticker
trades on different venues with different calendars), assuming weekdays are
sessions, adding a calendar dependency, or filling anything in.

## 5. Feature engine

Every feature is a pure function `BarSeries -> FeatureSeries`. No feature
fetches data, touches a provider, reads the clock, uses global state, or looks
at a bar after the one it is computing.

### Output: `FeatureSeries`

`timestamps[i]` is the open time of the bar that produced `values[i]`. Both
tuples are always the same length, so positional drift is impossible. Filter
with `ready_pairs()`, which keeps values attached to their timestamps rather
than returning a bare list that could be re-indexed against the wrong bars.

Provenance (symbol, interval, source, **basis**), the feature name and its
parameters travel with the output.

### Timing: open time vs knowable time

`MarketBar.timestamp` is the bar's **open** time (Phase 1 invariant). A feature
value at that timestamp is derived from the bar's close/high/low/volume — none
of which are known until the bar **finishes**.

> A feature value at timestamp `T` was **not** available at `T`.
> `knowable_at(i)` returns `T + interval` — the **earliest** instant it could
> have been known.

A strategy or backtester must act at or after `knowable_at`, never at
`timestamps[i]`. Treating them as the same thing is look-ahead bias, and the
aligned output array makes that easy to do by accident.

**`knowable_at` is a bound, not a measurement.** Phase 1 has no exchange
calendar and no latency model, so the true instant is not computable. It errs
in both directions depending on what you are asking:

| | |
|---|---|
| vs. **bar completion** | **late** — a daily session closes hours before `T+1d`; `1wk`/`1mo` use `Interval.max_duration`, an upper bound. Safe. |
| vs. **data availability** | **optimistic** — it models completion, not publication. yfinance intraday is delayed, so an hourly value is not retrievable at `T+1h`. |

Do not read it as "the data existed by then". A backtester needing realistic
execution timing must add its own latency assumption.

### Warm-up: one representation, `None`

A value is `None` exactly when the indicator lacks history (`SMA(20)` at bar 5)
or is genuinely undefined (relative volume against zero average volume).

`None` rather than `NaN` because it cannot be silently propagated through
arithmetic — it raises, which is correct for a value that does not exist.
Nothing is back-filled, seeded from the future, or computed over a quietly
shortened window. `ready_from` and `is_ready(i)` report readiness.

### Anti-look-ahead contract

For a value at bar `i`: bars `0..i` only, never `i+1` or later.

Enforced by property, not by inspection (`tests/lookahead.py`):

> Take series A. Build series B identical for the first `k` bars and radically
> different after. Every feature value at index `< k` must be **exactly** equal.

Exact equality is deliberate: a causal feature does not produce *similar*
values when the future changes, it produces identical ones. A tolerance would
hide the bug being hunted. `assert_causal_at_every_split` runs this at every
split point, so an off-by-one that leaks a single bar is caught.

The harness has a self-test: a deliberately cheating feature must make it fail.
Otherwise a passing sweep would prove nothing.

## 6. Features and their exact conventions

| Feature | First defined index | Notes |
|---|---|---|
| `simple_return` | 1 | `p[i]/p[i-1] - 1` |
| `log_return` | 1 | `ln(p[i]/p[i-1])` |
| `sma(period)` | `period-1` | trailing mean, inclusive of bar `i` |
| `ema(period)` | `period-1` | `alpha = 2/(period+1)`, **seeded with the SMA of the first `period` values** |
| `rsi(period)` | `period` | Wilder; see below |
| `realized_volatility(period)` | `period` | sample sd (`ddof=1`) of log returns, **not annualised** |
| `atr(period)` | `period-1` | Wilder; see below |
| `average_volume(period)` | `period-1` | trailing mean of volume |
| `relative_volume(period)` | `period-1` | `volume[i] / average_volume[i]`; `None` if the average is 0 |

### RSI — Wilder (1978)

1. `d[i] = c[i] - c[i-1]`; `gain = max(d,0)`, `loss = max(-d,0)`.
2. Seed at index `p`: simple means of the first `p` gains and losses.
3. Smoothing for `i > p`, **`alpha = 1/p`, not `2/(p+1)`**:
   `avg[i] = (avg[i-1]*(p-1) + x[i]) / p`.
4. `RSI = 100 - 100/(1 + avg_gain/avg_loss)`.

Degenerate cases, chosen explicitly: no losses → **100**; no gains → **0**;
perfectly flat (0/0, genuinely undefined) → **50**.

Tested against hand-computed fixtures. Wilder's published table is also checked
but only to ±0.1: that table's displayed averages (0.2382/0.0993) are not
reproducible from its displayed closes (which give 0.2386/0.1000), so the
difference is in the reference data, not the formula. **No equivalence with any
library is claimed.**

### ATR

- `TR[i] = max(high-low, |high - close[i-1]|, |low - close[i-1]|)` for `i >= 1`.
- `TR[0] = high[0] - low[0]` — no previous close exists, and the gap terms are
  omitted rather than guessed. The first TR is therefore not directly
  comparable with later ones.
- Initial ATR at `period-1` is the simple mean of `TR[0..period-1]`.
- Then Wilder smoothing: `ATR[i] = (ATR[i-1]*(period-1) + TR[i]) / period`.

### Volatility is not annualised

Annualising requires a bars-per-year constant, which requires a trading
calendar, which this system does not have (§4). Multiply by `sqrt(n)` yourself
if you need it.

## 7. Known limitations

- Derived series persist with **value** reproducibility only; the adjustment
  factors behind them are not stored, so a derivation cannot be re-executed
  from disk (**transformation reproducibility** deferred).
- Adjustment needs a factor for **every** bar; a partial factor set is refused
  outright rather than gap-filled.
- Adjusted data is **not point-in-time safe** (§3).
- Adjusted price × reported volume is not traded notional (§3).
- No exchange calendar, so no confirmed missing-session detection (§4).
- Only splits and cash dividends are modelled; no spin-offs, mergers or
  special distributions. Dividend currency is unknown.
- Features are implemented in plain Python and are O(n) but not vectorised.
  Fine for research-scale series; not tuned for millions of bars.
- yfinance remains a development/fallback source, not execution-grade data.
