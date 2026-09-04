# ADR 0001 — Price basis and corporate actions

- **Status:** accepted
- **Date:** 2026-09-04
- **Phase:** 2 (Research-grade data + feature engine)
- **Supersedes:** nothing. Phase 1 left this unresolved and recorded it as debt.

## Problem

Phase 1 stores raw, unadjusted OHLC from Yahoo and models no corporate actions.
Two things follow, and they pull in opposite directions.

A **4-for-1 split makes the raw close fall ~75% in one bar.** Nothing economic
happened; the share count changed. Any return, momentum or volatility feature
computed over that bar reports a catastrophic loss that never occurred. Every
long-horizon backtest built on raw prices is wrong at every corporate action.

But the obvious fix is also wrong. **Overwriting stored OHLC with adjusted
values claims those were the prices that traded.** They were not. A share of
AAPL did not change hands at $25 in 2019. Adjusted values are a present-day
restatement, and treating them as observations destroys the audit trail and
any ability to reason about what a price actually was.

So the system needs both, kept apart, and needs to make combining them by
accident difficult.

A secondary question: Phase 1 discovered that `check_bars` accepts a series
mixing two providers' bars. Feature code consuming `list[MarketBar]` would
inherit that.

## Alternatives considered

**A — `PriceBasis` field on `MarketBar`.** Basis travels with every bar and
cannot be lost. Rejected: basis is a property of a *series*, not of a single
bar; it changes a Phase 1 canonical contract and the CSV schema; and
`SeriesKey` still could not separate raw from adjusted, so both bases would
collide in one file.

**B — `BarSeries` wrapper carrying series-level metadata.** `MarketBar` is
untouched; metadata lives where it is actually true; one place enforces
homogeneity.

**C — Segregate by `source` string (`"yfinance"` vs `"yfinance-adjusted"`).**
Cheapest. Rejected: encodes a critical invariant as a string convention with
no type checking, defeated by a typo.

**D — Raw-only storage plus separate corporate-action records and an explicit
adjustment transform.** Most auditable; raw is never rewritten; adjustment is
reproducible and re-derivable.

## Decision: B + D

1. `MarketBar` is **unchanged**. It remains the canonical observed bar from
   Phase 1: raw OHLCV, nine fields, no basis, no corporate-action fields.
2. `BarSeries` (`src/data/series.py`) is the unit research code consumes. It
   guarantees exactly one symbol, one interval, one source and one
   `PriceBasis`.
3. Raw OHLCV is the **source of record** and is never overwritten.
4. Corporate actions are their own record type (`src/data/corporate_actions.py`),
   not fields on a bar.
5. Adjustment is an **explicit, pure transform** (`src/data/adjustment.py`)
   returning a *new* `BarSeries` with a derived basis and a provenance string.
6. **Storage identity includes price basis** (added after the initial
   decision — see "Price-basis-aware persistence" below).

### Why `MarketBar` stays unchanged

It represents an observation. A split ratio is not an attribute of a bar, and
neither is "which basis am I denominated in" — that is a statement about a
whole series. Adding either would make the canonical record mean two different
things depending on where it came from, which is what Phase 1 was built to
prevent.

### Price-basis naming

The enum is `SPLIT_AND_DIVIDEND_ADJUSTED`, **not** `SPLIT_ADJUSTED`.

This was verified rather than assumed. In the installed yfinance 1.7.0
(`yfinance/scrapers/history.py`), the dividend-repair routine computes:

```python
pre_adj  = df2['Adj Close'].iloc[div_idx-1] / df2['Close'].iloc[div_idx-1]
post_adj = df2['Adj Close'].iloc[div_idx]   / df2['Close'].iloc[div_idx]
div_missing_from_adjclose = post_adj == pre_adj
implied_div_yield = 1.0 - (pre_adj / post_adj)
```

yfinance *expects* the `Adj Close / Close` ratio to move across a dividend
date and treats an unchanged ratio as Yahoo having failed to apply the
dividend. The factor therefore encodes **cash dividends as well as splits**.
Calling the result "split adjusted" would misdescribe the transformation and
mislead anyone computing a price return from it. This basis is what is
conventionally called a total-return basis.

A split-only basis is derivable from the split records now captured, but is
**not defined** until something needs it: an unimplemented enum member is an
invitation to mislabel data.

### Yahoo retrieval

`Ticker.history(auto_adjust=False, actions=True)`.

- `auto_adjust=False` keeps `Open/High/Low/Close` as **raw traded prices** —
  the Phase 1 contract — and additionally returns `Adj Close`.
- `actions=True` adds `Dividends` and `Stock Splits` to the **same response**,
  so capturing corporate actions costs **no extra request**.
- The extra columns are consumed only by `get_adjustment_data()`. The raw bar
  path ignores them, so `MarketBar` keeps exactly its Phase 1 meaning.

Previously these columns were fetched and silently discarded.

### Volume

**Reported volume is carried through adjustment unchanged.** Yahoo does not
adjust volume either, and manufacturing a share count nobody reported would be
fabrication of the kind Phase 1 forbids.

The consequence must be respected by callers:

> **Adjusted price × reported volume is NOT historical traded notional.**

A raw volume series also has a mechanical step at a split, exactly as the raw
price series does. Any feature needing price-volume economic consistency must
handle this itself; the data layer will not paper over it.

### Point-in-time limitation — important for the backtester

**An adjusted series is not point-in-time safe.**

The factor attached to a bar in 2019 depends on every split and dividend that
has happened *since* — events that had not occurred at that date. An adjusted
series is a present-day restatement of history. It is correct for computing
economically comparable returns and **wrong** for answering "what would a
screen have shown on that date".

Two distinct concepts, not to be conflated:

| | |
|---|---|
| **Historically adjusted dataset** | Restated with today's knowledge. What we produce. Good for return series. |
| **Point-in-time data** | What was actually knowable at that date. We do **not** produce this. |

A backtest that assumes the second from the first is using future information.
This is documented, not solved, in Phase 2.

## Price-basis-aware persistence

`SeriesKey` originally identified a stored series by `(symbol, interval,
source)`. Once derived series existed, a raw and an adjusted series for the
same instrument resolved to the same identity and the same file — they would
have overwritten each other. Resolved before a backtester could depend on it.

### Design

`SeriesKey` gains a fourth field, `basis: PriceBasis = PriceBasis.RAW`.

Basis is expressed in **three** places, each doing a different job:

| Where | Job |
|---|---|
| `SeriesKey.basis` | identity — two keys differing only in basis are unequal |
| Filename suffix | routing — `1d.csv` (raw) vs `1d.split_and_dividend_adjusted.csv` |
| `price_basis` CSV column | **authority** — what the file says it is |

The filename is deliberately *not* the authority. A file can be moved or
renamed; its own metadata cannot. `read()` compares the stored `price_basis`
against the requested key and refuses on any mismatch, so renaming an adjusted
file onto the raw path fails loudly rather than silently returning adjusted
numbers as raw.

Basis remains a typed concept. It is **not** encoded by mangling `source` into
`"yahoo-adjusted"`, and it is never inferred from a filename or a source
string.

### Backward-compatibility policy

Phase 1 created a storage contract before `PriceBasis` existed. The policy:

- **Legacy `SeriesKey` usage maps explicitly to RAW.** The default value means
  every three-argument call site keeps working and now states its basis rather
  than omitting the concept.
- **Legacy files keep their exact path.** RAW uses the unchanged Phase 1
  filename (`1d.csv`); only derived series get a suffix. Nothing on disk moves.
- **`price_basis` is optional on read, mandatory on write.** A file lacking
  the column was written by Phase 1, when adjustment did not exist, so it is
  RAW *by definition* — not by inference from its name, source or contents.
  A present-but-unrecognised value is a fault and raises.
- Rewriting a legacy file upgrades it to self-describing.

### Value vs transformation reproducibility

Two different claims, and only one is delivered:

| | Status |
|---|---|
| **Value reproducibility** — "I can reload the exact adjusted numbers" | **DELIVERED.** Round-trip is exact; basis, symbol, interval and source all survive. |
| **Transformation reproducibility** — "I can reproduce how those numbers were derived from raw" | **DEFERRED.** |

Persisting adjusted values does **not** make the derivation reproducible. The
factor set and the corporate-action snapshot that produced them are not
stored, so the transform cannot be re-executed or audited from storage alone.
Doing so needs versioned factor sets or vintage-stamped action snapshots —
deliberately out of scope. `read_series()` says so in the provenance string of
any derived series it returns, so the limitation travels with the data.

### Alternatives rejected

- **Basis in the path only.** Fails as soon as a file is renamed or moved;
  provenance becomes unverifiable.
- **Basis in the CSV only.** Raw and adjusted would still collide on one path
  and overwrite each other before anything could be verified.
- **A separate store class for derived series.** Duplicates the storage
  implementation for one extra field.
- **Encoding basis in `source`.** Explicitly rejected: it destroys the typed
  concept and launders provenance through a string.

## Consequences

**Gained**

- A split no longer looks like a −75% loss to a return feature.
- Raw traded prices are never rewritten and remain auditable.
- Raw/adjusted series cannot be silently combined: `require_compatible`
  compares basis, and `FeatureSeries` carries basis forward.
- Double adjustment raises instead of silently corrupting prices.
- Corporate actions are retained, so other bases can be derived later without
  refetching.
- The mixed-source hole is closed: `check_bars` now reports `source_mismatch`,
  and `BarSeries` enforces it.

**Given up / costs**

- A new type (`BarSeries`) that research code must adopt; a bare
  `list[MarketBar]` is still constructible and is rejected by features.
- Adjustment requires a factor for *every* bar; a partial factor set is
  refused rather than gap-filled, so a sparse Yahoo response yields no
  adjusted series at all.
- Adjusted price × reported volume is not meaningful (above).
- Storage identity is basis-aware: raw and adjusted coexist, neither can
  overwrite the other, and reading with the wrong basis fails loudly.

## Known misuse the type system cannot prevent

`store.write(adjusted_series.bars)` — deliberately unwrapping a derived series
into bare `MarketBar`s — discards the basis and files adjusted values as RAW.

This follows directly from the decision that `MarketBar` carries no basis: the
bars of a derived series are identical in type to raw ones, so storage cannot
detect the difference. Mitigations in place:

- `write()` accepts a `BarSeries` directly and uses its basis;
- `write_series()` is the sanctioned path and is documented as such;
- `write()`'s docstring warns about this exact call.

Eliminating it entirely would require either putting basis on `MarketBar`
(rejected above) or removing `write()`'s ability to infer a key from bare bars
(a Phase 1 contract break). Neither is justified by a misuse that requires
deliberate unwrapping. Recorded, not solved.

## Deferred

- **Transformation reproducibility.** Adjusted *values* persist exactly;
  the factors and corporate-action snapshot behind them do not (above).
- **Split-only basis.** Derivable from captured split records; not defined
  until needed.
- **Point-in-time / as-reported data.** Requires vintage-stamped adjustment
  factors no free source provides.
- **Corporate actions beyond splits and cash dividends** (spin-offs, mergers,
  special dividends, capital gains distributions).
- **Currency of dividend amounts.** Yahoo does not report it; we do not invent
  one.
- **Exchange calendars** — see `src/data/sessions.py`; tracked separately.
