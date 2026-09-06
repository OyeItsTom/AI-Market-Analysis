# ADR 0006 — News and company announcements

**Status**: accepted (Phase 8)

## Problem

The research pipeline has never seen anything outside a price series. Adding
external information is easy; adding it without quietly corrupting the research
above it is not.

Three specific dangers shaped every decision here.

**Future leakage.** A story used before it was available invalidates any study
built on it, and leaves no trace in the numbers — the results simply look better.

**False provenance.** A headline attached to the wrong company, or a wire story
presented as a company announcement, is worse than no news at all, because it
arrives with the authority of a record.

**Interpretation creep.** Once a system stores headlines, it is one small step to
"positive/negative", and one more to a signal. Phase 8 is where that step is
refused explicitly rather than left to later restraint.

## Decisions

### 1. Two sources, chosen on measured evidence

SEC EDGAR for the official tier, Yahoo news for the secondary tier. Both were
probed live before the design was fixed, and two findings drove everything:

EDGAR supplies what a research record needs — a permanent `accessionNumber`, a
precise `acceptanceDateTime`, official `form`/`items` codes, and an
**authoritative ticker mapping** from the SEC's own CIK register.

Yahoo supplies **no ticker field at all**. Its association with a symbol is
purely "this is what came back when we asked", and querying `AAPL` returned an
Amazon-focused article and a Nvidia/Micron market piece. One article was
returned for `AAPL`, `AMZN` and `TSLA` simultaneously.

### 2. Yahoo's "press releases" tab is rejected as an official source

The obvious way to get company announcements would be Yahoo's "press releases"
tab. Sampled across three symbols, **zero of twelve** items were first-party
company releases: they were GlobeNewswire and Business Wire copy about ECG
monitors, Jamf and Lyte. Classing that as `OFFICIAL_FILING` would have given
third-party marketing the authority of a regulatory filing.

Official therefore means exactly one thing: **a regulator accepted the document**.

### 3. Symbol association carries its own trust level

`VERIFIED_SOURCE` for EDGAR, `QUERIED_SYMBOL` for Yahoo, and an `INFERRED`
member that V1 refuses to construct at all.

This is the most important field in the model. Without it the only options were
to record a false `VERIFIED` claim or to drop Yahoo entirely; with it the
interface can honestly say *"returned for AAPL"*. There is no substring or
company-name matcher, because a guessed link is indistinguishable from a real
one once written down.

### 4. Four timing facts, and an explicit basis

`source_event_time`, `source_published_at`, `retrieved_at`, and
`available_from` paired with an `availability_basis`.

The subtle decision is EDGAR's. `acceptanceDateTime` proves the SEC *accepted* a
filing; it does not prove public dissemination, however close the two are in
practice. Recording it as `SOURCE_EVENT` — a bound, not a measurement — keeps the
distinction visible, exactly as Phase 3 does with `evaluable_from`.

`retrieved_at` is never promoted to a publication time. When a source gives no
timing the basis becomes `SYSTEM_OBSERVED` or `UNKNOWN`, and `UNKNOWN` records
are excluded from causal queries rather than given a plausible-looking value.

### 5. Two query modes and a trust parameter

`SOURCE_TIME` is reportorial. `STRICT_CAUSAL` takes a trust mode:
`SOURCE_ASSERTED` believes the source's timestamp, `SYSTEM_OBSERVED` believes
only our own observation and uses `max(available_from, retrieved_at)`.

A single "correct" answer was not available. A 2024 filing fetched in 2026 was
genuinely accepted in 2024 *and* genuinely unknown to this system until 2026,
and which of those matters depends on the study. Offering both, with the sparse
consequence of the strict one documented, is more honest than picking one and
hiding the assumption.

### 6. Revisions are whole observations, appended

Never a patch. Each revision carries its own retrieval time, content hash and
the source timestamps as observed *in that revision*, so a provider silently
restating its publication time leaves both values on the record and the
disagreement itself becomes auditable.

A changed **immutable** field is an `ID_REUSE_CONFLICT`, not a revision: the
identifier now refers to something else, and appending would rewrite an
unrelated document's history. A missing provider id is `IDENTITY_UNSAFE` and is
refused, because a headline-derived fallback key would merge a wire story with
its syndication and fork a document over a corrected typo.

### 7. Documents and associations are stored separately

Document identity is `(source, source_item_id)`, global per source. Association
identity includes the symbol and is query-specific.

This followed directly from measurement: with per-symbol files, the article
returned for three symbols would have been stored three times, and calling the
store "deduplicated" would have been false. One document, three links, is what
actually happened.

### 8. Append-only JSONL, not SQLite

An earlier draft justified this by claiming SQLite's idiom would destroy
revision history. **That was wrong and is withdrawn** — SQLite models append-only
history perfectly well, and `sqlite3` is stdlib, so "no new dependency" does not
separate them either.

The real reasons are smaller and honest: the access pattern is "read a source's
records and filter by time" at volumes in the hundreds; plain text matches the
`CsvBarStore` precedent and its warning against schemas chosen before access
patterns are known; a torn line is human-readable and recoverable while a
corrupt SQLite page is not; and fixtures are literal text. SQLite remains the
documented upgrade path once indexing is actually needed.

### 9. Corruption is loud, and never repaired automatically

Reads raise by default, naming file, line and byte offset, and distinguish a
damaged final line (an interrupted append) from interior damage (already-written
bytes changed). A caller may opt into a tolerant read and receive an integrity
report it must handle.

Nothing is truncated or rewritten. A store that silently discards what it cannot
parse cannot be audited, and the whole point of this layer is that it can be.
The single exception is the cached ticker map, which is a rebuildable copy of a
public file rather than a record.

### 10. The SEC contact is configuration, not a secret

`SEC_USER_AGENT`, read from the environment only — never from git config, the
GitHub account or the OS user, any of which would put a personal address into
outbound requests without the user choosing to. Absence disables EDGAR and
nothing else: it surfaces as `UNCONFIGURED`, Yahoo keeps working, and the value
is never echoed into an error message that might end up in a screenshot.

### 11. Sources and items fail independently

A refresh touches two unrelated services, so one outage must not discard the
other's records. Each source reports its own outcome and a refresh with one
healthy source is `PARTIAL` — never "succeeded". Within a response each record is
handled on its own, so a malformed story is rejected and its siblings kept.

An earlier draft said both "the batch is validated fully" and "one malformed
item never voids a good batch". Those cannot both be true; the per-item model
was kept and the batch-atomicity language dropped.

### 12. Chronology is never reordered by source class

Official filings are labelled and filterable, and appear in the same timeline as
news. Floating them to the top would put a week-old 8-K above this morning's
story and quietly imply an editorial judgement the system has not made.

### 13. News never touches research or paper state

`NewsSnapshot` is a separate object; nothing was added to `ResearchSnapshot`.
`src/news` imports nothing from `src.strategies`, `src.assessments` or
`src.portfolio`, so there is no name in scope through which a headline could
reach a research state or a paper action. The news panel has no action control
and is never handed an assessment.

## Consequences

Coverage is limited to SEC registrants, so a non-US symbol reports `UNSUPPORTED`
rather than degrading quietly. UK/RNS needs a separate paid or authenticated
source and is deferred.

`SYSTEM_OBSERVED` queries make backfilled history nearly invisible. That is
correct and will be surprising; it is documented rather than smoothed over.

The store is a file scan. It is adequate for a local single-user tool and will
need an index long before it needs a different format.

Yahoo is an unofficial endpoint that can change shape without notice. It is
secondary-tier for that reason as well as for its provenance.

## Alternatives rejected

**A single universal record type.** Filings and articles have genuinely
different fields; one shape would have meant inventing values for whichever
record lacked them.

**Event-level clustering across sources.** It needs semantic similarity, and a
keyword clusterer would be the interpretation this phase exists to refuse.

**Storing article bodies.** It would make the repository a mirror of other
people's copyrighted work for no benefit the URL does not already provide.

**Fetching stored URLs to enrich records.** That is an SSRF surface reachable
from third-party data. Links are shown; they are never followed.

**A relevance or importance score.** There is no defensible way to compute one
here, and an indefensible one would be treated as real by everything downstream.
