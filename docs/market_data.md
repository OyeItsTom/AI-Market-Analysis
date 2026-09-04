# Phase 1 — Market Data Foundation

This document describes the market-data layer: what it guarantees, how the
pieces fit together, and what it deliberately does **not** do.

> **Status: not production-ready.** This is an educational, evidence-driven
> research and *paper-trading* system. Nothing here executes real-money
> trades, and the only working data source (yfinance) is a development /
> fallback feed, not a market-grade one.

---

## 1. The pipeline

```
Provider (vendor SDK/API)
        │        ← the only place vendor schemas exist
        ▼
Normalization        src/data/normalization.py
        │
        ▼
   MarketBar         src/data/models.py           ← canonical representation
        │
        ▼
  Validation         src/data/validation.py
        │
        ▼
   Storage           src/data/storage.py          → data/raw/<source>/<SYMBOL>/<interval>.csv
```

Everything downstream (features, strategies, backtesting, risk, signals,
paper trading) consumes `MarketBar` objects and nothing else.

## 2. Module map

| Module | Responsibility |
| --- | --- |
| `src/data/models.py` | `MarketBar`, `Interval` — the canonical OHLCV record |
| `src/data/provider.py` | `MarketDataProvider` abstract base + provider error types |
| `src/data/normalization.py` | vendor records → `MarketBar` (field aliases, timestamps) |
| `src/data/validation.py` | per-bar and per-series rules; structured issues |
| `src/data/storage.py` | `CsvBarStore` — local CSV cache of validated series |
| `src/data/providers/yahoo.py` | yfinance adapter (development / fallback) |
| `src/data/providers/alpaca.py` | architectural stub for Phase 2 |

## 3. `MarketBar`

One bar of normalized OHLCV data. Frozen (immutable), so a bar cannot be
mutated somewhere deep in a strategy.

| Field | Type | Notes |
| --- | --- | --- |
| `symbol` | `str` | stripped, upper-cased |
| `timestamp` | `datetime` | **bar OPEN time**, timezone-aware, stored in UTC, plain `datetime` |
| `open` / `high` / `low` / `close` | `float` | finite |
| `volume` | `float` | finite (float so fractional-quantity instruments fit) |
| `interval` | `Interval` | `1m 5m 15m 30m 1h 1d 1wk 1mo` |
| `source` | `str` | provenance, e.g. `"yfinance"` |

### System invariant: timestamp means bar OPEN time

`MarketBar.timestamp` is the **start** of the bar's period. A bar covers
`[timestamp, timestamp + interval)`. **Every provider adapter must honour
this**; an adapter whose vendor stamps bars at close time must subtract the
interval before constructing the bar.

The convention is invisible in the data, which is exactly why it must be
fixed once and written down. If one provider stamped bars at open and another
at close, the two series would merge, validate and store without complaint,
while a strategy reading "the bar at time T" would receive information from
after T for one of them — silent look-ahead bias introduced by a data-layer
detail.

Open time is chosen because it is the only convention under which a bar's
timestamp is knowable before its data is. It also makes completeness
computable: the period is over once `timestamp + interval` has passed.

### Structural vs. semantic validation

`MarketBar.__post_init__` enforces only what must hold for the object to be a
meaningful value: non-empty text fields, finite real numbers, a
timezone-aware timestamp. Financial rules (OHLC relationships, sign rules,
series ordering) live in `validation.py` so they can be applied deliberately
and reported in bulk.

### The only transformations applied

All deterministic and documented — nothing else is ever silently changed:

1. `symbol` is stripped and upper-cased.
2. `timestamp` is converted (never *assigned*) to UTC, and rebuilt as a plain
   `datetime` so `pandas.Timestamp` cannot leak downstream. Sub-microsecond
   precision is dropped.
3. `interval` strings are parsed into `Interval`; unknown values raise.

## 4. `MarketDataProvider`

```python
provider.get_bars(symbol, start, end, interval) -> list[MarketBar]
```

`get_bars` is a *template method* on the base class. It:

1. normalizes the symbol and parses the interval;
2. rejects naive `start`/`end`, reversed windows, unsupported intervals;
3. calls the subclass hook `_fetch_bars(...)`;
4. validates the result (per bar, plus symbol/interval consistency,
   duplicate timestamps, ordering).

So **no adapter can return malformed data unnoticed**, however careless it is.

An **empty list is a valid answer** — "no data in this window" (holiday,
pre-IPO, delisted). It is not an exception.

### Settled vs. unsettled bars

A vendor will happily return the bar for the session that is still open. It
has the same shape as a finished bar, but its `close` is a moving snapshot.
Backtesting on finished bars and then running live against a half-formed one
is a classic backtest/live divergence.

`get_bars(..., include_unsettled=False)` is the default: trailing bars whose
period has not provably ended are withheld, so **historical research and
backtesting get only completed bars**. Pass `include_unsettled=True` to also
receive the in-progress bar, accepting what it is.

Completeness is deliberately **not a field on `MarketBar`**. It is not a
property of the record but of the record *relative to now* — a bar cached as
unsettled is settled a minute later, so persisting the flag would persist a
value that is wrong by the time it is read back. The provider decides at
request time from `timestamp + interval.max_duration`.

`Interval.max_duration` is an **upper** bound (a month counts as 31 days).
Over-estimating can only delay treating a bar as settled; under-estimating
would let an in-progress bar pass as finished, which is the failure being
prevented. Nothing is ever declared final that cannot be proven final.

Errors: `ProviderUnavailableError` (upstream failed),
`ProviderConfigurationError` (missing SDK/credentials), `ValidationError`
(upstream returned bad data), `ValueError`/`TypeError` (bad request).

### Why the abstraction exists

Strategies must never import a vendor SDK. If a strategy called
`yfinance.download()` directly, then swapping to Alpaca, adding a second
venue, or replaying a stored dataset would mean rewriting every strategy —
and every module would need to know that vendor's column names, timezone
quirks and error types. The adapter boundary is where the vendor stops.

## 5. Validation rules

Per bar (`check_bar` / `validate_bar`):

| Code | Rule |
| --- | --- |
| `empty_symbol` | symbol must be non-empty |
| `naive_timestamp` | timestamp must be timezone-aware |
| `non_finite_value` | no NaN / ±inf in any numeric field |
| `non_positive_price` | O/H/L/C must be `> 0` |
| `negative_volume` | volume must be `>= 0` (zero is legal) |
| `high_below_low` / `high_below_open` / `high_below_close` | high must be the maximum |
| `low_above_open` / `low_above_close` | low must be the minimum |

Per series (`check_bars` / `validate_bars`):

| Code | Rule |
| --- | --- |
| `duplicate_timestamp` | timestamps unique (compared in UTC) |
| `unordered_timestamp` | strictly increasing (unless `require_sorted=False`) |
| `symbol_mismatch` | one symbol per series |
| `interval_mismatch` | one interval per series |

`check_*` returns **every** issue as structured `ValidationIssue` objects
(`code`, `message`, `index`); `validate_*` raises `ValidationError` carrying
that list in `.issues`.

### Why validation matters — and why we reject rather than repair

Corrupted market data does not announce itself; it shows up as a backtest
that looks unusually profitable. A bar whose `high` is below its `close` is
evidence of an upstream bug, and quietly rewriting it would bury that bug
inside plausible-looking results. Missing values are never zero-filled,
forward-filled or interpolated — inventing prices manufactures returns that
never existed. The only "fix" available is `skip_incomplete=True`, which
**drops** rows and never fills them.

## 6. Normalization

`bars_from_records()` maps vendor field names onto canonical ones
(`Open`/`o`/`open`, `Date`/`t`/`timestamp`, …) and builds `MarketBar`s.
Adapters convert their vendor payload into plain mappings and hand them over,
so vendor column names exist in exactly one place.

`coerce_timestamp()` accepts aware datetimes and ISO-8601 strings and returns
UTC. A naive timestamp is **refused** unless the adapter was explicitly
configured with `assume_timezone` — guessing an exchange's timezone is how
off-by-one-session bugs are born.

Even with `assume_timezone` set, two local times are refused rather than
resolved: a time that is **ambiguous** (occurs twice, at the autumn DST
fall-back) and one that is **nonexistent** (skipped by the spring-forward
jump). `datetime.replace` answers both silently and arbitrarily, and an hour
of silent error in an intraday series is very hard to find later. Detection
is standard library only — an ambiguous time has two different UTC offsets
depending on `fold`; a nonexistent time does not survive a round trip through
UTC.

### `skip_incomplete` is deliberately narrow

It drops a row only when a required value is **present but missing**
(`None`/NaN/NaT). It does **not** suppress a missing column, an unparseable
or timezone-less timestamp, a DST fault, or an unexpected type. Those mean the
vendor's schema or our assumptions have changed, and dropping those rows would
turn an infrastructure failure into an empty result indistinguishable from
"the market was closed". Rows are only ever dropped, never filled.

## 7. Storage

`CsvBarStore` writes validated series to:

```
data/raw/<source>/<SYMBOL>/<interval>.csv
```

- Plain CSV, standard library only. **No database in Phase 1** — there is no
  query pattern yet that a directory of CSV files cannot serve, and a schema
  chosen before the access patterns are known is a liability. The class is
  the seam for swapping in Parquet or SQLite later.
- Provenance is in the path, so bars from different providers are never
  silently mixed.
- `write()` replaces; `merge()` combines with what is stored, de-duplicates
  identical overlaps, and **raises on a conflict** instead of picking a
  winner.
- Writes go to a temp file and are renamed, so an interrupted run cannot
  leave a half-written cache file.
- Reads are re-validated — cache files can be edited or truncated between
  runs — and each row's `symbol`, `interval` and `source` must match the
  requested `SeriesKey`, so a misplaced or edited file cannot silently rewrite
  a bar's provenance.
- Path components are checked, so a symbol cannot escape the store root.

`data/raw/` and `data/processed/` are git-ignored: **downloaded market data
is never committed.**

## 8. Provider adapters

### Yahoo / yfinance — `YahooFinanceProvider`

Development and fallback source. Handles flat columns (`Ticker.history`) and
ticker-keyed MultiIndex columns (`yfinance.download`), converts timestamps to
UTC, and clips results to the requested closed window.

#### Prices are RAW / UNADJUSTED

The adapter requests `auto_adjust=False` and `actions=False`. The OHLC values
it produces are the **raw prices as traded**. `Adj Close` is not requested,
not consumed and not stored.

Understand the consequences before relying on this source:

- **corporate actions are not represented by `MarketBar` at all** — there is
  no split ratio, no dividend, no adjustment factor in the model;
- a 4:1 split therefore appears as a ≈−75% single-day return, and a large
  dividend as an unexplained gap down;
- **splits and dividends require dedicated handling before long-horizon
  strategy research can rely on this source**;
- **the adjustment policy — raw vs. back-adjusted, and where adjustment
  happens — must be addressed before serious strategy backtesting.**

This is deliberately out of scope for Phase 1 and is recorded as known debt,
not solved. Volume is likewise unadjusted for splits.

**Other known limitations — do not treat this as market-grade data:**

- unofficial, undocumented, unsupported endpoint; schema and availability can
  change without notice, and it is rate-limited (HTTP 429 under load);
- intraday history is short (~30 days for 1-minute bars) and delayed;
- no exchange-official volume guarantees; occasional NaN/holiday padding;
- no order book, no corporate-action detail, no survivorship-bias-free
  universe;
- **not suitable for live trading decisions.**

Constructor options: `download_fn` (injected in tests so the suite runs
offline), `assume_timezone` (only way to accept a naive index),
`skip_incomplete_rows` (drops NaN rows; never fills).

### Alpaca — `AlpacaProvider` (stub)

Implements the interface; every data request raises `NotImplementedError`.
It exists to prove a second provider slots in without touching anything
downstream, and to record what finishing it needs:

1. `alpaca-py` added to `requirements.txt` (**not installed today**);
2. credentials from the environment — `ALPACA_API_KEY_ID`,
   `ALPACA_API_SECRET_KEY` (see `.env.example`); never hard-coded, never
   logged, never printed;
3. **paper endpoints only** (`https://paper-api.alpaca.markets`);
4. interval → `TimeFrame` mapping; `t/o/h/l/c/v` fields (already covered by
   the default aliases); `next_page_token` pagination; feed (`iex` vs `sip`)
   recorded in `source`;
5. HTTP/auth/rate-limit errors mapped onto the provider error types;
6. offline tests with canned payloads, same pattern as the Yahoo adapter.

`credentials_present()` returns a bool and never returns, logs or prints the
values themselves.

## 9. Usage

```python
from datetime import datetime, timezone

from src.data import CsvBarStore, Interval, SeriesKey
from src.data.providers import YahooFinanceProvider

provider = YahooFinanceProvider()
store = CsvBarStore()  # -> data/raw/

bars = provider.get_bars(
    "AAPL",
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 3, 1, tzinfo=timezone.utc),
    Interval.DAY_1,
)

store.write(bars)
cached = store.read(SeriesKey("AAPL", Interval.DAY_1, "yfinance"))
```

## 10. Testing

```bash
pytest -q
```

The suite is fully offline: provider tests inject a fake `download_fn`, and
storage tests write into pytest's `tmp_path`. No test touches the network or
`data/raw/`.

## 11. Out of scope for Phase 1

No indicators, strategies, buy/sell signals, ML, LLM/news analysis,
portfolio optimization, dashboard, or broker execution of any kind.

## 12. Known technical debt

Recorded deliberately, not solved in Phase 1:

| Item | Note |
| --- | --- |
| **Price adjustment policy** | Raw prices only; corporate actions unmodelled. Must be settled before serious backtesting. |
| Vendor integration coverage | `_default_download` — the only code that touches yfinance — has no test. |
| Gap detection | Missing trading days are not flagged (needs an exchange calendar). |
| `pytest.ini` warning filter | `error::DeprecationWarning:src.*` cannot match; the file is near-inert. |
| Test-helper organization | Helpers are imported from `tests/conftest.py` rather than a helpers module. |
| CSV spreadsheet injection | A symbol like `=1+1` is written unescaped into the local cache CSV. |
| Dependency declaration | `requirements.txt` is a flat `pip freeze`; no Python floor declared (code needs ≥3.10). |
