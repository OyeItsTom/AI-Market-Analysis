# External feeds

A local, manual-refresh reader for public RSS 2.0 and Atom 1.0 feeds you
configure yourself.

It **records**; it does not interpret. There is no sentiment, no score, no
ranking, no summary this system wrote, and nothing here reaches research,
assessments or paper trading.

> **Telegram is not implemented in this phase**, as input or output. See
> [ADR 0007](adr/0007-external-feeds.md) for why, and what would have to change.

## Setting it up

```bash
cp config/external_feeds.example.json config/external_feeds.local.json
```

Edit the copy, then press **Refresh feeds** in the sidebar. The local file is
git-ignored and is the only source of feed URLs.

Every feed in the shipped example is `"enabled": false`, so copying the file
fetches nothing until you deliberately turn one on.

```json
{
  "schema_version": 1,
  "sources": [
    {
      "source_id": "example-company-blog",
      "type": "RSS",
      "url": "https://example.com/blog/feed.xml",
      "display_name": "Example Corp engineering blog",
      "declared_trust_class": "publisher_feed",
      "configured_symbols": ["AAPL"],
      "enabled": true
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `source_id` | Slug; becomes a directory name under `data/feeds/`. Must be unique. |
| `type` | `RSS` or `ATOM`. A document that contradicts this is refused. |
| `url` | HTTPS only. No credentials, no redirects followed. |
| `display_name` | Shown in the panel. Changing it invalidates nothing. |
| `declared_trust_class` | `official_feed`, `publisher_feed` or `community_feed`. |
| `configured_symbols` | Why you added the feed. Creates the only association claimed. |
| `enabled` | `false` keeps the entry but never fetches it. |

## What the trust label means

**It is your label, not a verification.** Writing `official_feed` does not make
this dashboard check that the feed belongs to whoever it claims to. Nothing in
V1 verifies feed ownership, and rather than approximate it, the system says so:

| Configured as | Rendered as |
| --- | --- |
| `official_feed` | Official feed (configured by you) |
| `publisher_feed` | Publisher feed (configured) |
| `community_feed` | Community feed — unverified |

The label is stored **with each entry**. Relabelling a feed today does not
relabel what was stored last week.

## What the timestamps mean

Three different facts, three separate fields, and one approved phrase each.

| Field | Panel label | Means |
| --- | --- | --- |
| `source_published_at` | Publisher's stated publication time | The publisher said it published then |
| `source_edited_at` | Publisher's stated update time | The publisher said it changed it then |
| `retrieved_at` | First seen by this dashboard | When *we* fetched it |

`availability_basis` records which of these `available_from` came from:

* **`source_published`** — an RSS `pubDate`, or an Atom `published`.
* **`source_updated`** — an Atom `updated` with no `published`. This is an
  *update* time and is never relabelled as a publication time. Every entry in
  the SEC's own Atom feed is this shape.
* **`system_observed`** — the entry carried no usable time, so all that is known
  is when we saw it.
* **`unknown`** — nothing defensible is known. Such an item carries no
  `available_from` at all and is excluded from causal queries.

A channel's `lastBuildDate` is never borrowed as an item time. It describes the
document, not the entry.

## Querying

```python
from src.application.feeds import build_service
from src.feeds.models import QueryMode, TrustMode

service = build_service()
service.refresh()

service.items_for_symbol("AAPL")
service.items_for_symbol("AAPL", as_of=cutoff, mode=QueryMode.STRICT_CAUSAL)
service.items_for_symbol("AAPL", as_of=cutoff, trust=TrustMode.SYSTEM_OBSERVED)
```

* `SOURCE_TIME` — "what carried a source timestamp at or before T?" Reportorial.
* `STRICT_CAUSAL` — "what can we defensibly say was available by T?"
* `SOURCE_ASSERTED` — believe the publisher's own timestamp.
* `SYSTEM_OBSERVED` — believe only our own observation, so a backfilled entry is
  invisible until the moment this system actually retrieved it.

Ordering is strictly chronological, newest first. A trust label never moves an
entry up the list.

## What happens on a refresh

```
configuration -> integrity check -> conditional fetch -> parse -> normalize
              -> store (append + fsync) -> checkpoint -> snapshot
```

Every feed is refreshed independently. One failing never discards another's
records, and a refresh where some feeds failed reports `PARTIAL` — never
success.

Every entry in the document is re-examined on every refresh. There is no
"already seen" filter, which is what lets a publisher's correction surface as a
revision instead of being skipped.

| Outcome | Meaning |
| --- | --- |
| `SUCCESS` | Entries were returned and processed. |
| `NO_ITEMS` | The feed answered and had no usable entries. |
| `NOT_MODIFIED` | The source says nothing changed. Distinct from `NO_ITEMS`. |
| `TRUNCATED` | More entries than the per-refresh bound; the rest were not read. |
| `RATE_LIMITED` | The source asked us to stop. Never retried around. |
| `UNSUPPORTED_SOURCE_FORMAT` | Not RSS or Atom, or contradicted its configured type. |
| `PAYLOAD_TOO_LARGE` | Past the byte ceiling, measured after decompression. |
| `UNSAFE_ENDPOINT` | The host, or the address actually connected to, is not permitted. |
| `STORAGE_CORRUPTION` | The store is damaged. Ingestion refused, nothing repaired. |
| `CHECKPOINT_WARNING` | Transport state was unusable and rebuilt; ingestion still ran. |
| `UNCONFIGURED` | Present in configuration but switched off. |
| `FAILED` | Could not be reached, or answered with something unusable. |

## Storage

```
data/feeds/<source_id>/documents.jsonl      append-only entries
data/feeds/<source_id>/associations.jsonl   append-only (item, symbol) links
data/feeds/<source_id>/checkpoint.json      ETag and Last-Modified only
```

All git-ignored. Downloaded third-party content is never committed.

**Append-only.** A revision is a new line; the earlier version stays exactly
where it was, so "what did this say when we first saw it?" stays answerable.

**Damage is reported, never repaired.** A corrupt line is classified as
`CORRUPT_TAIL` (a crash mid-append) or `CORRUPT_INTERIOR` (something else) and
surfaced in the panel. Nothing is deleted, truncated or rewritten to make a read
succeed.

**Records are durable before the checkpoint moves.** A crash between the two
costs a redundant fetch, not lost entries behind a `304`.

## Security posture

* **HTTPS only.** No plain HTTP, no credentials in URLs.
* **Configured URLs only.** Nothing typed into the dashboard is fetched, and no
  link inside an entry is ever followed.
* **The address we check is the address we use.** Every resolved address is
  validated, and the real peer is validated again after connecting — which is
  what closes DNS rebinding rather than mitigating it.
* **No redirects.** A `3xx` is refused and its `Location` reported, not fetched.
* **DOCTYPE refused outright**, making XML entity expansion structurally
  impossible rather than merely bounded.
* **Bounded decompression.** The ceiling is on output, because a 28 KB response
  was measured expanding to 11.6 MB.
* **No raw HTML rendered.** Publisher text is escaped, so markup shows as the
  literal characters it is.
* **No credentials anywhere.** V1 reads only public feeds, so there is nothing to
  authenticate with — and the boundary tests fail if a credential name appears.

## Known limits

* **Absence is not deletion.** Feeds are sliding windows. An entry leaving the
  window says nothing, and is not recorded as a removal.
* **No ownership verification.** See above; the system says so rather than
  approximating it.
* **No text matching.** A feed configured for no symbol claims no company, even
  if an entry names one in its title.
* **Hard limits, stated rather than implied.** At most 100 entries are read per
  refresh (a feed offering more is reported as `TRUNCATED`, never silently
  clipped); a response body may not exceed 2 MB *after* decompression; the
  configuration file may not exceed 256 KB or 50 feeds; a feed may name at most
  20 symbols. Titles are capped at 500 characters and excerpts at 2000 — the
  excerpt is the only field truncated rather than refused, because an identity
  field that was quietly shortened would no longer be an identity.
* **Manual refresh only.** There is no scheduler and nothing runs in the
  background.
