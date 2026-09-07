# ADR 0008 — Market universe and multi-stock scanner

**Status**: accepted (Phase 10)

## Problem

Every phase up to this one looked at a single symbol. Phase 7 made that legible:
type a ticker, press Refresh, read what the ensemble made of it. The obvious
next question — *which symbol should I be typing?* — is where a research tool
usually stops being a research tool.

Three dangers are specific to looking at many symbols at once.

**A list becomes a ranking, and a ranking becomes advice.** The moment several
symbols appear in one table with an order, a reader will take the top row as the
best one. If the ordering is built from anything resembling a score, that reading
is not even wrong — it is what the system said. Phase 6 already refused to
produce a confidence from a handful of integer classifications, and a scanner
that quietly reintroduced one through a sort key would undo that decision without
anyone deciding to.

**Many symbols means many failures.** One provider outage, one delisted ticker,
one symbol with three weeks of history. If those are handled as *the scan
failing*, a healthy scan of fifty symbols where two had no bars reports as
broken. If they are handled as nothing at all, a real outage disappears. The
distinction between "we could not research this" and "there was nothing to
research" has to survive all the way to the screen.

**Scanning is where a research tool grows a scheduler.** A loop over symbols is
one refactor away from a background thread, and a background thread is one
convenience away from continuous monitoring — at which point the system is
making requests nobody asked for and the user is reading numbers they did not
trigger.

## Decisions

### Universes are bounded, local and attributed

A scan runs over a universe named in `config/universes.local.json`, which the
user writes and which is git-ignored. The tracked
`config/universes.example.json` is a template and is **never a fallback**: with
no local file the panel shows an empty state, because silently scanning symbols
the user never chose would be a worse failure than showing nothing.

`source_kind` has exactly two values, `local_static` and `user_defined`. A value
such as `verified_index` would be unconstructible — nothing here can check index
membership — and offering the word would let a line of JSON borrow authority the
system cannot supply. `as_of` is required for the same reason the news layer
separates its timestamps: a membership list is a dated claim, and a list captured
today but scanned across years of history is survivorship-biased.

The caps (50 universes, 100 symbols each, 256 KB of configuration) are resource
bounds, not recommendations. The file is user-written, which makes it trusted in
intent and untrusted in content, so it is validated as strictly as anything
arriving over a network — size, count, slug shape, symbol shape, uniqueness.

### The scan reuses `build_snapshot` unchanged

Every value a scan records comes from the existing Phase 1–6 pipeline through the
same call the Research tab makes. No feature is computed in the scanner, no
hypothesis is evaluated there, and no ranking rule is re-implemented.

A second, disagreeing copy of the research rules is the specific failure this
layer exists to avoid. It would not announce itself: the two paths would agree
on most symbols and diverge on the interesting ones.

### Per-symbol isolation, but only for per-symbol faults

The `try` around each symbol covers **only the research call**. A classified
application error becomes an error row; any other exception from that call
becomes `UNEXPECTED`; either way the remaining symbols are still scanned.

Summarising the result runs *outside* that catch, deliberately. If categorising
an assessment raises, or a result invariant is violated, or the progress callback
fails, the whole scan aborts. Those are faults in this code, and recording them
as `UNEXPECTED` rows would make a programming defect indistinguishable from a
provider outage — a scan could report `ALL_FAILED` while the market was fine.

An unusable *request* — an unsupported interval, a universe with no symbols —
raises before anything is fetched. There is no partial truth to report about a
scan that was never valid.

### A snapshot is published whole or not at all

Results accumulate locally and one immutable `MarketScanSnapshot` is returned
once the loop finishes. The session replaces the whole object; a failed scan
leaves the previous one untouched, so a failure never costs the reader the
results they were looking at.

The snapshot is self-describing: `universe_id`, `universe_fingerprint`,
`universe_display_name`, `universe_as_of`, `interval`, `basis`,
`policy_fingerprint`, `warmup_bars`, `minimum_sufficient_observations`,
`scan_started_at`, `scan_completed_at`, `results`, `counters` and `status`.

Two details in that list are decisions rather than bookkeeping. Policy metadata
is read from the research configuration, **not** from whichever symbol happened
to succeed first — an all-failed scan still has a policy, and metadata that
appeared only on success would make two scans of the same universe describe
themselves differently. And there is deliberately **no global market cutoff**: a
scan spanning minutes never observed one simultaneous market state, so each
result carries its own `data_cutoff` instead.

`ScanStatus` is judged by operational errors alone. There is no
`NOTHING_CONFIGURED` member, because a snapshot describes a scan that ran, and
manufacturing one for an unconfigured system would be inventing a record of
something that never happened.

### Ordering is structural, and there is no score

The sort key is lexicographic over an enum and three plain values: evidence
structure, then classifying-hypothesis count descending, then latest bar
descending, then symbol. Every step is explicable in a sentence, and a missing
timestamp sorts last through a sentinel rather than by comparing `datetime` to
`None`.

No weighted composite exists. Phase 6 states that a handful of integer
classifications cannot yield a confidence; a composite over four small counts
would manufacture precisely the pseudo-precision that decision refused, and would
do it in the one place a reader is most likely to read it as a recommendation.

One rule inside the categoriser is load-bearing and easy to get wrong: a modifier
is not a category. `INSUFFICIENT_INPUTS_EXCLUDED` appears alongside bullish,
bearish, conflicted, neutral *and* insufficient results, so any rule that took
"the first reason code" would mis-categorise roughly a third of real assessments.
Categorisation tests reason-code identity, never position or text.

### Direction is never a preference

Bullish and bearish produce identical categories and identical sort keys.
Direction appears nowhere in the comparator, so a bearish case cannot sort below
an otherwise identical bullish one.

This is enforced structurally rather than by intention, and the vocabulary is
enforced too: research states are rendered as classifications and there is no
mapping anywhere from `bullish` to Buy. A single approved phrase per category
lives in one place, so no renderer can invent a more flattering word for a weaker
finding.

### Serial, manual, daily — for V1

The scan is serial because the provider fetches one symbol per call and because
ordering stays deterministic and failures stay isolated that way. It is manual
because a scan happens when a person asks for one: nothing fetches on load, on
rerun, on selection, on configuration reload or on the research handoff.

It is daily-only because the scanner's freshness and history assumptions have
been reasoned through for daily bars and not for the others. Research still
offers weekly and monthly; the scanner refuses them rather than accepting them
untested.

Concurrency was reviewed against a benchmark covering the full 100-symbol
ceiling — 185 provider calls, no operational failures, no rate-limit evidence,
timing usable interactively — and was **not justified**. Nothing here starts a
thread, a timer or a scheduler.

### Session state holds whole objects, and the handoff is a parked symbol

Phase 10 adds exactly five session keys: `scan_snapshot`, `scan_failure`,
`scan_universes`, `scan_universe_id` and `pending_research_symbol`. Each holds a
complete thing. Keys such as `scan_results`, `scan_counters` or `scan_progress`
would be pieces of a snapshot that could disagree with each other between
reruns, and the boundary tests fail if one appears.

The Research handoff is a parked symbol rather than a direct assignment because
Streamlit refuses to set a widget's value after that widget has been built. The
symbol goes on a non-widget key and is applied at the top of the next rerun,
before the control exists. That ordering is load-bearing and has a test that
fails if the two calls are ever swapped.

The handoff fetches nothing. Navigation that quietly performed a refresh would
make "open this in Research" a network action, and the user would have no way to
tell which of the two panels they were waiting for.

### Layering, and three firewalls

The dependency runs `dashboard → application → scanner config adapter`. The
dashboard imports no scanner-domain module; a thin `load_universes` facade in the
application layer is how it reaches configuration, which keeps the file read
inside the one adapter that owns it and out of any view.

Three boundaries are asserted rather than assumed. **News and feeds** reach
neither eligibility, category nor ordering — there is no name in scope through
which a headline could move a symbol up the table. **Paper trading** is
unreachable from the panel: no intent, no portfolio, no action control.
**Background execution** does not exist: no threading, asyncio or scheduler
import appears in the scanner domain, the orchestrator, the view models or the
dashboard, and no cancellation or ETA vocabulary appears in the panel or its
view.

## Consequences

* A scan is a session artefact. Nothing is persisted, so a snapshot explains
  itself while held but is not a durable reproduction — provider data may be
  revised, and re-running tomorrow may legitimately differ.
* A universe with no local configuration is a normal, empty, silent state. Users
  who skip the setup step see an instruction, not a demo.
* Symbols with no data or too little history are ordinary outcomes with their own
  section, and never inflate the failure count. A scan where every symbol
  returned no bars is `ALL_OK`.
* The scanner cannot answer "which of these is the better investment", and this
  is not a gap to be filled later by adding a score. It is the property the
  ordering was designed to lack.
* Serial execution means scan time grows with universe size. The 100-symbol
  ceiling bounds that, and the benchmark is published with its caveats rather
  than converted into a service level.
* Zero new dependencies.

## Alternatives rejected

**Scan automatically, or on a schedule.** Convenient, and it would make the
dashboard feel alive. It also makes requests nobody asked for, turns provider
rate limits into an unbounded exposure, and puts numbers on screen that the
reader did not trigger and cannot date. A research tool that refreshes itself
teaches the user to stop asking when the data came from.

**Scan concurrently.** Considered seriously and measured rather than assumed. At
the tested ceiling the serial path stayed interactive with no failures and no
rate-limit evidence, so concurrency would have bought speed the benchmark did not
show was needed, in exchange for non-deterministic ordering, entangled failures
and a provider-politeness question nobody has answered. Rejected on the evidence
available; nothing here is scheduled to revisit it.

**Rank by a weighted score or confidence.** The most requested shape and the most
dangerous. It contradicts Phase 6 directly, and it fails silently: a composite
number looks authoritative regardless of how little is behind it. Ordering by
explicit structure keeps every position explicable in one sentence.

**Put bullish results first.** Superficially useful for a long-only paper
portfolio, and exactly how a research classification becomes a trade preference.
Bearish evidence is evidence.

**Rank by news or sentiment.** The news and feed layers already exist, so this
was reachable. It would have made a headline able to move a symbol up a research
table before any reasoning layer had been designed, evaluated or bounded — and
the resulting ordering would have been indistinguishable from a recommendation.

**Keep scan results as separate session keys** — rows here, counters there,
progress somewhere else. Cheaper to update incrementally, and it makes an
internally inconsistent screen possible: counters from one scan beside rows from
another. Counters are read from the snapshot that produced the rows.

**Persist scan history in this phase.** Tempting, since a stored scan invites
"what did this look like last week?". But a persisted snapshot makes durability
and revision claims the phase has not designed, and the honest answer to that
question is currently no. Deferred rather than half-built.

**Let the dashboard import the scanner domain directly.** One fewer indirection,
and it would put a configuration file read inside a view. The application layer
already owns every other path from interface to domain, and the exception would
be the first crack in that rule rather than a small convenience.
