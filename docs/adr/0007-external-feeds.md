# ADR 0007 — External RSS and Atom feeds

**Status**: accepted (Phase 9)

## Problem

Phase 8 added two named sources with fixed semantics: EDGAR is the SEC, and
Yahoo is Yahoo. Phase 9 opens the system to feeds the *user* chooses, which
changes the problem in kind rather than in degree.

Three dangers are specific to user-configured sources.

**Borrowed authority.** A feed labelled "SEC filings" in a config file is not the
SEC. If the interface renders that label the way it renders a verified fact, the
system has manufactured authority out of a line of JSON — and the user will
believe it, because they will have forgotten they typed it.

**Arbitrary destinations.** A configured URL is an instruction to make a request.
Hard-coded endpoints could be audited once; a user-supplied URL is an SSRF
primitive pointed at whatever the machine can reach, including cloud metadata
endpoints and the local network.

**Hostile documents.** RSS and Atom are XML, and XML parsers have a long history
of entity expansion attacks. A feed is also compressible, so a small response can
become an enormous one after decompression.

## Decisions

### Telegram is deferred, and not partially implemented

Telegram was in the original scope for this phase and has been removed from it
entirely — input and output.

The Bot API cannot retrieve history: `getUpdates` retains roughly 24 hours and is
consumed on read, so a manual-refresh model built on it would silently miss
anything posted between refreshes. That is precisely the quiet-gap failure this
project exists to avoid. The client API can read history, but requires a phone
number and a long-lived session file whose blast radius is the user's entire
Telegram account, not one channel.

Neither is acceptable for a local research tool in V1, and a half-built version
of either would be worse than none. The deferral is enforced structurally rather
than by intention: `tests/test_feed_boundaries.py` fails if any Telegram client,
identifier or credential name appears anywhere in the phase.

### Only RSS 2.0 and Atom 1.0, only HTTPS, only from configuration

A feed is fetched because it appears in `config/external_feeds.local.json`.
Nothing typed into the dashboard becomes a request, no feed is discovered, and no
URL found *inside* a feed entry is ever followed. Links in entries are rendered
for a human to click and are never requested by this application.

### Trust is quoted, never asserted

`declared_trust_class` is the user's own label. It is stored on every record with
`trust_basis = USER_CONFIGURED`, and the interface renders it as "Official feed
(configured by you)", "Publisher feed (configured)" or "Community feed —
unverified". The word "verified" appears nowhere except inside "unverified".

The label is read **from the stored item**, not from today's configuration.
Relabelling a feed as official tomorrow must not retroactively make yesterday's
entries look verified.

### An update time is not a publication time

This is the decision with the widest blast radius, and it came from measurement:
every entry in the SEC's own Atom feed carries `updated` and no `published`.

Atom requires `updated` and makes `published` optional. Mapping `updated` onto a
publication field would have mislabelled every entry from the most authoritative
source in the project. So `AvailabilityBasis` gained a fourth member,
`SOURCE_UPDATED`, and the domain model refuses to construct an item that claims
`SOURCE_PUBLISHED` without a publication time — or one that claims
`SOURCE_UPDATED` while carrying one.

RSS has no per-item edit timestamp, so `source_edited_at` stays empty and a
revision is known only from changed content. The channel-level `lastBuildDate`
is never borrowed as an item time: it describes the document, not the entry.

Because this basis has no counterpart in the Phase 8 vocabulary, `src/feeds`
shares **no types** with the news layer. The duplication is deliberate: merging
the two enums would have forced one of the two phases to lie about its sources.

### Identity comes from the provider or the entry is refused

Atom `<id>`, then RSS `<guid>`, then the canonical link. If none is present the
entry is refused as `IDENTITY_UNSAFE`. No identity is manufactured from a title,
an excerpt, a timestamp or a hash of the text — a synthesised key changes when
the publisher fixes a typo, turning one item into two.

A `guid` with `isPermaLink="true"` is still treated as an opaque string. It may
look like a URL; it is never fetched because of that.

### Documents and associations are stored separately

One entry, however many symbols. The association records only what is true —
*this feed is configured for AAPL* — and is keyed on the configuration
fingerprint, so adding a symbol to a feed later creates a new observation rather
than rewriting what an old one meant.

No entry is ever matched to a company by reading its text. There is no matcher to
be wrong.

### Two fingerprints, because two different questions are asked

`endpoint_fingerprint` covers identity-bearing fields only and keys the cached
ETag. `config_fingerprint` additionally covers trust and symbols, and records
what an observation meant. `display_name` is in neither: renaming a feed must not
invalidate a cache or reinterpret a record.

### Records are durable before the checkpoint moves

Entries are appended and fsynced, and only then is the ETag written. Reversed, a
crash between the two would leave a checkpoint promising a `304` for entries
never stored, and they would never be seen again. In this order the worst case is
re-fetching a document we already hold, which classifies as a duplicate.

The checkpoint holds ETag, Last-Modified, the endpoint fingerprint and the last
success time — and nothing else. An earlier sketch kept a set of seen item ids so
refreshes could skip familiar entries; that would have made every publisher
correction invisible.

Store integrity dominates: a damaged store stops ingestion before any request is
made, and leaves the checkpoint exactly as it was.

### The destination we check is the destination we use

Every resolved address is validated before connecting, and the real peer from
`getpeername()` is validated again after the socket is up. Pre-resolution alone
leaves a DNS rebinding window; the peer check closes it. TLS is untouched
throughout — certificate verification and SNI use the real hostname.

Redirects are not followed. A `3xx` is a classified refusal that reports its
`Location` for diagnosis and is never retried, because a redirect is a settled
answer rather than a transient one.

### A DOCTYPE is refused outright

Measured on this build, expat allowed roughly a megabyte of output from a
347-byte input before its own limiter engaged. Rather than argue about whether
that headroom is survivable, any document containing a DOCTYPE is rejected before
parsing. Legitimate feeds do not carry DTDs, so this costs nothing real and makes
entity expansion structurally impossible instead of merely bounded.

### Decompression is bounded on output, not on the wire

A 28 KB gzip response was measured expanding to 11.6 MB, so a cap on wire bytes
measures the wrong thing. Reads are chunked against a running limit and
decompression uses `zlib.decompressobj(max_length=…)`, aborting while inflating
rather than after.

## Consequences

* Nothing here reaches research, assessments or paper trading. `src/feeds`
  imports none of those packages, so no feed entry has a name in scope through
  which it could reach a decision.
* Zero new dependencies. The whole layer is standard library.
* An entry disappearing from a feed window is **not** treated as a deletion.
  Feeds are sliding windows; absence is not evidence.
* A feed that is renamed keeps its cache; a feed that moves loses it. That is the
  intended asymmetry.
* Duplicated vocabulary between `src/news` and `src/feeds` is a maintenance cost
  accepted deliberately in exchange for each layer being able to describe its own
  sources honestly.

## Alternatives rejected

**Reuse the Phase 8 `AvailabilityBasis`.** Would have forced Atom's `updated`
into either `SOURCE_PUBLISHED` (a lie) or `SYSTEM_OBSERVED` (throwing away a real
source timestamp). Both were worse than a fourth member.

**Follow one redirect.** Feed URLs move, and following would be convenient. But
a single hop is enough to reach a private address, and the destination policy
would then have to be re-run per hop with the rebinding window reopened each
time. Refusing and reporting the `Location` lets the user update their config.

**Keep seen ids in the checkpoint to skip work.** Faster, and it would have made
corrections invisible. The store compares stored content on every refresh
instead.

**Verify feed ownership somehow.** There is no honest way to do this for an
arbitrary URL in a local tool. Rather than approximate it, the system says
plainly that it has not.

**Sanitise HTML out of titles with a regex.** Regex is not an HTML parser.
Publisher text is kept as characters, with control characters removed, and is
escaped at render time so markup shows as the literal text it is.
