# Market scanner (Phase 10)

A manual, one-press scan across a bounded universe of symbols you configure
yourself, so you can decide which single symbol is worth opening in Research.

It **triages**; it does not recommend. There is no score, no confidence and no
probability anywhere in it. Results do have an order, and that order describes
the *structure of the research evidence* — how much there is to inspect — never
which symbol is the better investment. Nothing here reaches paper trading.

Every state, count and reason code the scanner shows was produced by the Phase
1–6 pipeline through the same `build_snapshot` call the Research tab uses. The
scanner adds no research rule of its own.

## Setting it up

```bash
cp config/universes.example.json config/universes.local.json
```

Edit the copy, then open the **Market Overview** tab. The local file is
git-ignored and is the only source of scan universes.

The example file is a **template and is never loaded automatically**. Until you
create the local file, the panel says so and scans nothing — silently scanning
symbols you never chose would be worse than an empty state. The dashboard never
creates the local file for you, and a missing local file is a normal state
rather than an error.

```json
{
  "schema_version": 1,
  "universes": [
    {
      "universe_id": "example-watchlist",
      "display_name": "Example research watchlist",
      "source_kind": "local_static",
      "source_reference": "Illustrative research-demo membership...",
      "as_of": "2026-09-06",
      "symbols": ["AAPL", "MSFT", "JNJ"],
      "enabled": true
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `schema_version` | Must be `1`. An unknown version is refused, never guessed at. |
| `universe_id` | Slug: letters, digits, `-` and `_` only, lower-cased on load, at most 64 characters. Identifies the universe; the description is `display_name`. |
| `display_name` | Shown in the selector. At most 200 characters. |
| `symbols` | The list to scan. Upper-cased, de-duplicated and sorted on load; at most 100. |
| `source_kind` | `local_static` or `user_defined`. Those are the only two. |
| `source_reference` | Your own note on where the list came from. At most 500 characters. |
| `as_of` | The date this membership list was captured. |
| `enabled` | `false` keeps the entry but never offers it in the selector. |

**`source_kind` is your own attribution, not a verification.** There is
deliberately no value meaning "verified index membership": nothing in this
repository can check an index's constituents, so offering the word would let a
line of JSON make a claim the system cannot support.

### What `as_of` is for

`as_of` records when the membership list was captured, and the panel shows it
beside the universe name so a list's vintage stays visible when results are
read later. The shipped example states the reason directly: a list captured
today and scanned across years of history is survivorship-biased, because the
companies that left the list are absent from it.

### Reloading

**Reload universes** re-reads the file on demand. A failed reload deliberately
keeps the last-good configuration in place for the session — a typo must not
destroy a working selector — and shows the error for that render only. If the
universe you had selected disappears or is switched off, the selection falls
back to the first enabled universe rather than dangling.

Configuration lives in that file and in the current dashboard session. Nothing
about a scan is persisted; see [Known limits](#known-limits).

## Running a scan

1. Choose a configured universe.
2. Press **Scan Market**.
3. Read the results, then open one in Research.

Nothing is fetched until you press the button. There is no scan on app load, on
an ordinary rerun, on selecting a different universe, on reloading the
configuration, on the Research handoff, or on rendering a tab.

The scan is **serial and synchronous**: symbols are fetched one at a time, in
the universe's stored order (which is sorted, not the order you typed them), in
the rerun you started. While it runs you see a progress bar, how many symbols
are done out of how many, elapsed seconds, and a running count of symbols that
could not be scanned. None of that progress is stored — it exists for the
duration of the scan and then goes away.

### Daily bars only

Market scans always use daily bars (`1d`), whatever the Research sidebar's
interval is set to. Single-symbol Research still supports `1d`, `1wk` and
`1mo`.

The restriction is deliberate rather than incidental: the scanner's freshness
and history assumptions have only been reasoned through for daily, and a scan
that quietly accepted a weekly request would be shipping an untested claim. A
request for another interval is refused outright, not downgraded.

## What the scanner is not

It is not an investment recommender, a buy/sell signal generator, a broker, an
auto-trader, a portfolio optimizer, a confidence model or a probability model.

`Bullish` and `Bearish` are research classifications and are rendered as such.
They are never mapped to Buy or Sell — the moment "bullish" becomes "buy", a
classification has been turned into advice this system never gave.

## Eligibility

Whether a symbol could be researched. Never whether it is attractive.

| Status | Means |
| --- | --- |
| `ELIGIBLE` | An assessment was produced. |
| `NO_DATA` | The provider returned no bars at all. |
| `INSUFFICIENT_EVIDENCE` | Bars existed, but too few hypotheses classified for a finding. |

Those three are the whole vocabulary. A symbol that failed operationally has no
eligibility at all — `eligibility` is `None`, because eligibility was never
determined. That is a third kind of outcome, not a fourth status.

## Evidence structure

The shape of the evidence behind an assessment, not a judgement about it. The
category is the scanner's own grouping, derived from the assessment the research
pipeline already produced — it adds no research rule, and it never changes what
the assessment said.

| Category | Shown as | Means |
| --- | --- | --- |
| `UNANIMOUS_DIRECTIONAL` | Unanimous directional | Every hypothesis that classified agreed on a direction. |
| `DIRECTIONAL_WITH_NEUTRAL` | Directional with neutral | A direction among abstentions: some classified neutral. |
| `CONFLICTED` | Conflicted | Hypotheses disagreed on direction. |
| `NEUTRAL` | Neutral | Everything that classified agreed there is no direction. |
| `NOT_ASSESSABLE` | Not assessable | No assessment to describe: no data, too little evidence, or an error. |

`CONFLICTED` sorting above `NEUTRAL` is not a claim that disagreement is
better. Disagreement is often the most informative case to *read*, which is
what the ordering measures.

## Ordering

Ordering answers *which research cases are structurally interesting to
inspect*. It does not answer which security is a better investment, and nothing
in the interface presents it as though it did.

The sort key, in order:

1. **Evidence structure**, in the order of the table above.
2. **Classifying-hypothesis count, descending** — more evidence to read first.
3. **Latest bar, descending** — fresher data first. A row with no bar timestamp
   sorts after every row that has one.
4. **Symbol, ascending** — the final tie-break, so two runs over identical data
   produce identical order.

This is **structural ordering**. It is not a score, a confidence, a conviction,
an expected-return ranking or a measure of investment strength. There is no
weighted composite anywhere: a handful of integer classifications cannot yield a
confidence, and combining four small counts into one number would manufacture
exactly the pseudo-precision the project refuses.

### Direction is never a preference

**Bullish and bearish have identical structural priority.** They produce
identical categories and identical sort keys, and direction appears nowhere in
the comparator — so a bearish case can never sort below an otherwise identical
bullish one. Bullish results are not treated as better, stronger, more
attractive or higher quality.

## Reading Market Overview

Before any scan the tab shows what the scanner is and the three steps above —
never a blank panel.

After a scan the summary names the universe, its membership `as_of`, a prefix of
the universe fingerprint, that the scan used daily bars, and a prefix of the
research policy fingerprint, followed by eight figures:

**Symbols · Completed · Assessable · Scan status** and
**No data · Insufficient evidence · Operational failures · Duration**

Those counts come from the scan's own counters, not from re-counting the rows on
screen. Beneath them a caption gives the window the scan ran across and a note
that each row carries its own data cutoff.

### Research candidates

The assessable rows, in the order the scanner decided. Nine columns:

| Column | Shows |
| --- | --- |
| `Symbol` | The symbol, normalized. |
| `Evidence structure` | The category, from the table above. |
| `Assessment` | The research state: Bullish, Bearish, Conflicted or Neutral. |
| `Bullish` / `Bearish` / `Neutral` | How many hypotheses classified each way. |
| `Why it surfaced` | One fixed phrase per category. |
| `Latest bar` | The opening time of the most recent settled bar. |
| `Data cutoff` | When this symbol's own data was observed. |

*Why it surfaced* is deterministic text generated from the category — one
approved phrase for each, never prose this system wrote about a company.

### Not assessable this scan

Symbols with nothing to assess **and** symbols that failed operationally, in one
table, with a column that keeps them apart. Six columns:

| Column | Shows |
| --- | --- |
| `Symbol` | The symbol, normalized. |
| `Status` | `No data`, `Insufficient evidence`, or one of the five error labels below. |
| `Operational failure` | `yes` or `no`. This is the column that separates the two groups. |
| `Detail` | A fixed explanation for the two eligibility cases; for an error, the truncated provider text, or a note that none was reported. |
| `Latest bar` | The most recent settled bar, or `—` when none is known. |
| `Data cutoff` | See [Provenance and data cutoff](#provenance-and-data-cutoff) — it means something different on a failure row. |

The caption above it says how many symbols had nothing to assess and how many
could not be scanned, and states that only the second group is an operational
failure. Calling a symbol the provider simply had no bars for a "failure" would
misreport a scan that worked.

## Opening a result in Research

Pick an assessable symbol and press **Open selected in Research**. Only
assessable symbols are offered — no-data, insufficient-evidence and failed
symbols are not in the list. A selection that no longer exists after a new scan
is reset rather than left dangling.

The handoff sets the Research symbol and nothing else. It does **not** fetch
market data, refresh Research, fetch News, fetch External Feeds or touch paper
positions. Open the Research tab and press **Refresh** yourself when you want
the full single-symbol view.

Mechanically the symbol is parked on a non-widget key and applied at the top of
the next rerun, before the symbol control is built — assigning that control's
value after it exists is something Streamlit refuses.

## When a scan goes wrong

### A symbol with no data is not a failure

If a provider returns no usable bars for a symbol, the result is `NO_DATA` with
no error code, and the panel reads **No data**. The scan itself succeeded. A
scan in which every symbol returned no bars is still a completed scan with zero
operational failures.

### Operational failures

A genuine fault while researching one symbol becomes an error row:

| Code | Shown as |
| --- | --- |
| `PROVIDER_UNAVAILABLE` | Provider unavailable |
| `DATA_QUALITY` | Data quality issue |
| `SYMBOL_MISMATCH` | Symbol mismatch |
| `REQUEST_INVALID` | Request invalid |
| `UNEXPECTED` | Unexpected scanner error |

Diagnostic text is truncated at 300 characters. It comes from a provider
exception, and must never be long enough to dominate a record — or to be
mistaken for something the ordering consulted.

**Isolation is specific, not universal.** A failure *while fetching and
researching one symbol* is caught, recorded and the scan moves on. Faults the
scanner owns are not: if summarising a result breaks an invariant, or the
progress callback raises, the whole scan aborts. That is deliberate — turning a
programming defect into an `UNEXPECTED` row would let a bug in this code look
like a market condition, and a whole scan could report every symbol as failed
while the market was fine.

### Scan status

| Status | Means |
| --- | --- |
| `ALL_OK` | No symbol failed operationally. |
| `PARTIAL` | Some symbols failed operationally, some did not. |
| `ALL_FAILED` | Every symbol failed operationally. |

All three are **coherent statuses of a completed scan**. `ALL_FAILED` describes
the symbols, not a crash: the scan ran to completion and is reported normally.

### Global failure

Different from any of the above: a global failure means no snapshot was produced
at all — an unusable request, an unsupported interval, or an unexpected
exception around the scan itself.

When that happens the previous completed snapshot stays exactly where it was,
the failure is shown above the panel, and nothing partial is published. You
never see half of a new scan beside part of an old one, because a snapshot is
built completely and then replaced whole. A successful scan clears the message.

## Provenance and data cutoff

A completed scan describes itself: which universe it ran over, that universe's
`display_name`, `as_of` and fingerprint, the interval, the research policy
fingerprint, and when the scan started and finished.

**There is no single global market-data cutoff.** A scan of many symbols takes
minutes, so the first and last symbols were observed at different moments; one
"as of" for the whole scan would assert a simultaneous market state that never
existed. Each row carries its own `data cutoff` instead:

* On a **successful** row it is that symbol's research snapshot build time — the
  moment its own data was observed.
* On an **operational failure** row it is when the failure was recorded. It is
  *not* a market-data cutoff: no market data was obtained, so none can be
  reported. The row's error code is what tells you that.

A snapshot is self-describing while you hold it. It is **not** a durable
reproduction: nothing is persisted, and provider data may be revised, so
re-running tomorrow may legitimately differ.

## Measured performance

One benchmark run against the live provider:

| Symbols | Wall clock |
| --- | --- |
| 10 | 5.66 s |
| 25 | 8.32 s |
| 50 | 10.37 s |
| 100 | 19.80 s |

Across those timed runs: **185 provider calls, 0 operational failures, 0
provider failures, and no rate-limit evidence observed.**

That figure counts *provider calls* — one per symbol. The raw HTTP request
count was **not measured** and is unknown; a provider call is not guaranteed to
be exactly one request.

**These numbers are a measurement, not a guarantee.** They come from one
machine, one network and one measurement window, and provider behaviour varies
with time of day and with conditions outside this project's control. A
100-symbol scan taking about twenty seconds in that window does not mean a
100-symbol scan takes twenty seconds. It is not a service level.

### Serial execution, confirmed for V1

The scanner runs serially, and stays that way in V1. The benchmark covers the
full 100-symbol ceiling, timing stayed usable interactively in the measured
environment, no operational or provider failure occurred, and nothing suggested
a rate limit was approached. Serial execution also keeps ordering deterministic
and keeps one symbol's failure away from the others.

Concurrency was reviewed against those measurements and **not justified**. It is
not implemented.

## Boundaries

* **News and External Feeds reach nothing here.** Neither affects eligibility,
  evidence structure or ordering. No headline changes a scanner result.
* **No paper action.** Market Overview exposes no Open Long, no Close, no paper
  intent and no portfolio change. Opening a result in Research is the only
  action on the panel.
* **Nothing runs in the background.** No scheduler, no polling, no thread, no
  async scan, no continuous monitoring. A scan happens because a person pressed
  **Scan Market**.
* **The dashboard never reaches the scanner domain directly.** It goes through
  the application layer, and the configuration file is read in exactly one
  adapter. See [ADR 0008](adr/0008-market-scanner.md).

## Known limits

* **Hard limits, stated rather than implied.** At most 50 universes; at most 100
  symbols per universe; the configuration file may not exceed 256 KB; a
  `universe_id` is capped at 64 characters, a `display_name` at 200, a
  `source_reference` at 500, a symbol at 32, and error detail at 300.
* **100 symbols is a safety ceiling.** It is a resource bound, not a performance
  guarantee, not a claim that every environment handles 100 identically, and
  certainly not a recommendation about how many symbols to research. Start
  small and increase deliberately.
* **Session-only.** A scan snapshot lives in the dashboard session. There is no
  scan history, no database and no persistence of any kind.
* **Manual and synchronous.** One scan, when you ask for it, in the foreground.
* **Daily only**, as above.
* **No concurrency, no cancellation, no estimated time remaining.** A running
  scan reports symbols completed, elapsed time and how many could not be
  scanned, and runs to completion.
* **No LLM, no sentiment, no news-driven ranking, no outcome tracking.** None of
  these exist in this phase, and nothing in the scanner is shaped to imply they
  are coming.
