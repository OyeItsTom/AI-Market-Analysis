# News and company announcements (Phase 8)

A local, auditable record of what external sources published about a company:
official SEC filings and reported news. It **records**; it does not interpret.
There is no sentiment, no score, no classifier and no direction anywhere in it.

## What it is for

Phases 1–6 answer "what does the price history classify as?" Phase 8 answers a
different question — "what did sources publish, and how well do we know when?" —
and keeps the two apart. Nothing here changes a `ResearchAssessment`, and
nothing here can open a paper position.

## Market scope

**Symbols the SEC's ticker map can resolve to a CIK**, which is about 10,400
registrants including US-listed ADRs. A symbol it cannot resolve reports
`UNSUPPORTED` rather than returning nothing, because silently returning an empty
list would imply coverage that does not exist.

UK/RNS is deliberately deferred: LSEG's announcement API needs authentication
tokens and the aggregators charge per announcement, so there is no free,
machine-readable primary source comparable to EDGAR.

## Sources, and why only these two

| | **SEC EDGAR** | **Yahoo news** |
|---|---|---|
| Class | `OFFICIAL_FILING` | `SECONDARY_NEWS` |
| Identity | `accessionNumber` (permanent) | provider item id |
| Timing | `acceptanceDateTime` (precise) | `pubDate` |
| Symbol link | **the SEC's own CIK→ticker map** | **none — the payload names no ticker** |
| Taxonomy | official `form` + `items` codes | none |
| Cost | free, no API key | free, no API key |

### Yahoo's "press releases" tab is not used

It sounds like the company's own announcements. It is not. Sampled across
`AAPL`, `MSFT` and `TSLA`, it returned only third-party wire copy that mentions
the company — market-research notices, other firms' funding rounds — and **not
one** first-party release. Treating it as official would be the worst mistake
this layer could make, so it is not fetched. **Official means a regulator
accepted it.**

## Symbol association — read this before trusting a headline

The Yahoo payload contains **no ticker field**. A story is associated with a
symbol only because that symbol was the one queried, and querying `AAPL`
demonstrably returns stories primarily about other companies. One article was
observed being returned for `AAPL`, `AMZN` and `TSLA` at once.

So every association records *why* it exists:

| Kind | Meaning | Shown as |
|---|---|---|
| `VERIFIED_SOURCE` | the SEC identified the registrant | "Filed by this company" |
| `QUERIED_SYMBOL` | it came back for this query, and nothing more | **"Returned for AAPL"** |
| `INFERRED` | reserved; never produced in V1 | — |

There is no substring matcher and no company-name matcher, because a guessed
link is indistinguishable from a real one once stored.

## Timing — four facts, never collapsed

| Field | Meaning |
|---|---|
| `source_event_time` | EDGAR **accepted** the filing |
| `source_published_at` | the publisher's claimed publication time |
| `retrieved_at` | when this dashboard fetched it |
| `available_from` + `availability_basis` | the earliest instant we will claim, and why |

`availability_basis` is one of `SOURCE_EVENT`, `SOURCE_PUBLISHED`,
`SYSTEM_OBSERVED` or `UNKNOWN`.

**EDGAR acceptance is a bound, not a proof.** It shows the SEC received the
document; the source does not guarantee it reached the public at that instant.
It is recorded as `SOURCE_EVENT` and labelled "Accepted by the SEC" — never as
a publication or a dissemination.

**`retrieved_at` never substitutes for publication.** When a source supplies no
time, the basis becomes `SYSTEM_OBSERVED` (we know only that we had it by then)
or `UNKNOWN` — and an `UNKNOWN` record is *excluded* from causal queries rather
than given a guessed time.

## Causal queries

```python
mode=SOURCE_TIME                          # "what carried a source timestamp <= T?"
mode=STRICT_CAUSAL, trust=SOURCE_ASSERTED # the ordinary research setting
mode=STRICT_CAUSAL, trust=SYSTEM_OBSERVED # trust no source at all
```

- **SOURCE_TIME** repeats what sources said. Reportorial, not a causal claim.
- **SOURCE_ASSERTED** believes the source's own timestamp.
- **SYSTEM_OBSERVED** uses `max(available_from, retrieved_at)`.

### Historical backfill

A filing accepted in 2024 and fetched in 2026 keeps three separate facts:

| Question | Answer |
|---|---|
| Source said it existed at | 2024 |
| This system observed it at | 2026 |
| Public availability **proven** at | **not claimed** |

`SOURCE_ASSERTED` sees it from 2024. `SYSTEM_OBSERVED` sees it only from 2026.
That second answer makes backfilled history sparse — which is the honest cost of
assuming no source trust, not a bug.

## Revisions

Every revision is a **complete new observation**, appended, never overwriting
the last. Each carries its own `retrieved_at`, `content_hash` and the source
timestamps *as observed in that revision*, so a publisher who silently restates
when it published leaves both values on the record. `as_of(T)` replays the file
to reconstruct what this system had observed at any past moment.

| Situation | Outcome |
|---|---|
| same id, same content | `DUPLICATE` — nothing written |
| same id, changed content | `REVISION` — appended |
| same id, changed **immutable** field | `ID_REUSE_CONFLICT` — refused |
| no provider id | `IDENTITY_UNSAFE` — refused |

Immutable fields are `cik`/`form`/`filing_date` for EDGAR and `canonical_url`
for Yahoo. A missing provider id is refused rather than given a manufactured
key: a headline-derived id would merge a wire story with its syndication and
fork a document when a publisher fixed a typo.

## Storage

```
data/news/<source>/documents.jsonl      one line per document revision
data/news/<source>/associations.jsonl   one line per (document, symbol) link
data/news/sec/company_tickers.json      the cached ticker map
```

Documents and associations are separate because they are different facts: a
document is global to its source, an association is query-specific. One article
returned for three symbols is **one document and three links** — storing a copy
per symbol would make "deduplicated" a false claim.

Append-only UTF-8 JSONL, one JSON object per line, `schema_version` on every
line. Writes serialize the complete line, append, flush and `fsync`. No claim is
made that this is atomic on every filesystem; the safety net is detection on the
next read. **Assumption: one local process, one writer.** No locking exists.

### Corruption is loud

A malformed line is never skipped in silence. Reads raise by default, naming the
file, line number and byte offset, and classify the damage as `CORRUPT_TAIL`
(final line only — consistent with an interrupted append) or `CORRUPT_INTERIOR`
(damage to already-written bytes, which is worse). A caller may pass
`on_corruption=REPORT` to get the valid prefix plus an integrity report it must
handle, and the dashboard shows it as a warning.

**Nothing is truncated, rewritten or repaired automatically.** The bad bytes
stay on disk as evidence. Writing into a store that cannot be fully read is
refused. The one exception is `company_tickers.json`, which is a rebuildable
cache of a public file, not a record — a corrupt copy is simply re-fetched.

An unknown `schema_version` is refused outright rather than interpreted under
today's rules, because a future writer may have changed what a field means.

## The SEC contact address

The SEC asks automated clients to identify themselves. This is **contact
identification, not an API key** — EDGAR has no key.

```
export SEC_USER_AGENT="AI-Market-Analysis your-email@example.com"
```

Copy `.env.example` to `.env` (git-ignored) and edit it. Without it the EDGAR
source reports `UNCONFIGURED`, is switched off, and **Yahoo news keeps working**.
The value is read from that one variable only — never from git config, the
GitHub account or the OS user — and is never echoed back in an error message.

## Access discipline

EDGAR publishes a 10 requests/second ceiling. This client targets ~2/s, times
out at 30 seconds, retries at most twice with bounded backoff, and stops on
`403`/`429` rather than retrying into a block. Yahoo gets one call per refresh.
**No scraping, no crawling, no background polling.**

## Content and copyright

Stored: headline, the provider's own summary, the canonical URL, source
metadata, timing and identity. **Never the article body.** No HTML is fetched or
parsed, and no third-party article is mirrored. For filings the document *URL*
is stored, constructed from trusted identifiers — the document itself is not
copied. Links are rendered for you to click; this application never follows one.

## The ticker map

Fetched once, persisted with `retrieved_at` and `Last-Modified`, and refreshed
with `If-Modified-Since` so keeping it current costs one small conditional
request. If the network is unavailable, the stored map is used.

**It maps tickers as they are today.** It is *not evidence* of a historical
mapping: tickers get reassigned and companies rename, and the file carries no
history. Each association records the map vintage used, and historical ticker
identity is **not reconstructible** in V1.

## Refresh, and partial success

Manual only. Press **Refresh news**; nothing runs in the background, on a timer
or in a thread.

Sources are refreshed **independently**. EDGAR failing never discards Yahoo's
records and vice versa, and each source reports its own outcome — `SUCCESS`,
`NO_ITEMS`, `UNSUPPORTED`, `UNCONFIGURED`, `RATE_LIMITED` or `FAILED`. A refresh
where one source worked is reported as **PARTIAL**, never as success.

Within one response each record is normalized, validated and stored on its own,
so a malformed story is rejected and its siblings are kept.

## Ordering

Newest first, ties broken deterministically. **Source class never reorders
chronology** — a week-old 8-K must not appear above this morning's story merely
because it is official. Class is a label and a filter, nothing more.

## Boundaries

- News is a **separate `NewsSnapshot`**. It is not part of `ResearchSnapshot`.
- `src/news` imports nothing from `src.strategies`, `src.assessments` or
  `src.portfolio` — there is no name in scope through which a headline could
  reach a research state or a paper action.
- The news panel has **no action control**, and is never passed an assessment.
- No LLM, no sentiment, no "positive for the stock", no BUY/SELL.
- No database, no scheduler, no monitoring, no broker, no real money.

## Phase 8 non-goals

Event-level clustering across sources · UK/RNS · market-wide feeds · full
article bodies · any taxonomy beyond EDGAR's own `form`/`items` · sentiment ·
LLM summarisation · any research integration · continuous monitoring.
