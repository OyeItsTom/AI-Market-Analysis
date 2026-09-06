"""Phase 9 normalization: identity from the provider, timing without overclaim.

This is where a publisher's words become a claim the system will repeat, so
these tests are mostly about refusing to say more than was said. The central
one: an Atom entry carrying only ``updated`` is recorded as an *update* time.
Every entry in the SEC's own Atom feed is that shape, so relabelling it as a
publication time would have mislabelled the most authoritative source in the
project.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.feeds.config import FeedDefinition
from src.feeds.models import AvailabilityBasis, DeclaredTrustClass, FeedFormat, SymbolAssociation
from src.feeds.sources import normalize_feed
from src.feeds.xmlsafe import parse_feed_bytes

UTC = timezone.utc
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def definition(**overrides) -> FeedDefinition:
    fields = dict(
        source_id="demo",
        feed_format=FeedFormat.ATOM,
        url="https://example.com/feed.xml",
        display_name="Demo",
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
        configured_symbols=("AAPL",),
    )
    fields.update(overrides)
    return FeedDefinition(**fields)


def atom(entries: str) -> bytes:
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>T</title>{entries}</feed>"
    ).encode()


def rss(items: str, channel_extra: str = "") -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        f"{channel_extra}{items}</channel></rss>"
    ).encode()


def normalize(payload: bytes, fmt=FeedFormat.ATOM, **overrides):
    parsed = parse_feed_bytes(payload, expected=fmt)
    return normalize_feed(parsed, definition(feed_format=fmt, **overrides), now=NOW)


def only(payload: bytes, fmt=FeedFormat.ATOM, **overrides):
    entries, rejected = normalize(payload, fmt, **overrides)
    assert len(entries) == 1, f"expected one entry, got {len(entries)} (rejected {rejected})"
    return entries[0]


ATOM_UPDATED_ONLY = atom(
    "<entry><id>urn:1</id><title>Updated only</title>"
    '<link rel="alternate" href="https://example.com/1"/>'
    "<updated>2026-09-05T10:00:00Z</updated></entry>"
)

ATOM_BOTH = atom(
    "<entry><id>urn:2</id><title>Both</title>"
    '<link rel="alternate" href="https://example.com/2"/>'
    "<published>2026-09-04T08:00:00Z</published>"
    "<updated>2026-09-05T09:00:00Z</updated></entry>"
)


# -- Atom timing ---------------------------------------------------------


def test_an_atom_entry_with_only_updated_is_recorded_as_an_update():
    """The SEC's own feed is exactly this shape on every entry."""
    item = only(ATOM_UPDATED_ONLY).item
    assert item.availability_basis is AvailabilityBasis.SOURCE_UPDATED
    assert item.source_published_at is None
    assert item.source_edited_at == datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    assert item.available_from == item.source_edited_at


def test_an_update_time_is_never_relabelled_as_a_publication_time():
    item = only(ATOM_UPDATED_ONLY).item
    assert item.availability_basis is not AvailabilityBasis.SOURCE_PUBLISHED
    assert item.source_published_at is None


def test_an_atom_entry_with_published_uses_it_and_keeps_the_update_separately():
    item = only(ATOM_BOTH).item
    assert item.availability_basis is AvailabilityBasis.SOURCE_PUBLISHED
    assert item.source_published_at == datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
    assert item.source_edited_at == datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert item.available_from == item.source_published_at


def test_identical_published_and_updated_leaves_no_spurious_edit():
    payload = atom(
        "<entry><id>urn:3</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/3"/>'
        "<published>2026-09-04T08:00:00Z</published>"
        "<updated>2026-09-04T08:00:00Z</updated></entry>"
    )
    assert only(payload).item.source_edited_at is None


def test_an_atom_entry_with_no_timestamps_falls_back_to_observation():
    payload = atom(
        "<entry><id>urn:4</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/4"/></entry>'
    )
    item = only(payload).item
    assert item.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED
    assert item.available_from == NOW


def test_a_naive_or_unparseable_timestamp_is_dropped_not_guessed():
    payload = atom(
        "<entry><id>urn:5</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/5"/>'
        "<updated>not a date</updated></entry>"
    )
    item = only(payload).item
    assert item.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED


def test_an_implausibly_future_timestamp_costs_the_claim_not_the_entry():
    """Dropping the record would hide a publisher's clock error."""
    payload = atom(
        "<entry><id>urn:6</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/6"/>'
        "<updated>2099-01-01T00:00:00Z</updated></entry>"
    )
    item = only(payload).item
    assert item.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED
    assert item.source_edited_at is None


# -- RSS timing ----------------------------------------------------------


def test_an_rss_pubdate_is_a_publication_claim():
    payload = rss(
        "<item><title>T</title><link>https://example.com/r1</link><guid>g1</guid>"
        "<pubDate>Fri, 05 Sep 2026 10:00:00 GMT</pubDate></item>"
    )
    item = only(payload, FeedFormat.RSS).item
    assert item.availability_basis is AvailabilityBasis.SOURCE_PUBLISHED
    assert item.source_published_at == datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    # RSS 2.0 has no per-item edit timestamp, so none is invented.
    assert item.source_edited_at is None


def test_a_channel_last_build_date_is_never_borrowed_as_an_item_time():
    """It describes the document, not the entry."""
    payload = rss(
        "<item><title>T</title><link>https://example.com/r2</link><guid>g2</guid></item>",
        channel_extra="<lastBuildDate>Fri, 05 Sep 2026 23:59:00 GMT</lastBuildDate>",
    )
    item = only(payload, FeedFormat.RSS).item
    assert item.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED
    assert item.source_published_at is None
    assert item.available_from == NOW
    assert item.available_from != datetime(2026, 9, 5, 23, 59, tzinfo=UTC)


# -- identity ------------------------------------------------------------


def test_an_atom_id_is_the_identity():
    assert only(ATOM_UPDATED_ONLY).item.feed_item_id == "urn:1"


def test_an_rss_guid_is_the_identity():
    payload = rss(
        "<item><title>T</title><link>https://example.com/r3</link>"
        "<guid>opaque-3</guid></item>"
    )
    assert only(payload, FeedFormat.RSS).item.feed_item_id == "opaque-3"


def test_a_permalink_guid_is_still_treated_as_an_opaque_string():
    """It may look like a URL; it is never fetched because of that."""
    payload = rss(
        "<item><title>T</title><link>https://example.com/r4</link>"
        '<guid isPermaLink="true">https://example.com/permalink/4</guid></item>'
    )
    assert only(payload, FeedFormat.RSS).item.feed_item_id == "https://example.com/permalink/4"


def test_the_canonical_link_is_the_last_resort_identity():
    payload = rss("<item><title>T</title><link>https://example.com/r5</link></item>")
    assert only(payload, FeedFormat.RSS).item.feed_item_id == "https://example.com/r5"


def test_an_entry_with_no_usable_identity_is_refused():
    """No key is manufactured from a title, a timestamp or a hash of the text."""
    payload = atom("<entry><title>No id and no link</title></entry>")
    entries, rejected = normalize(payload)
    assert entries == []
    assert rejected == 1


def test_an_entry_with_no_title_is_refused():
    payload = atom(
        '<entry><id>urn:7</id><link rel="alternate" href="https://example.com/7"/></entry>'
    )
    assert normalize(payload)[0] == []


def test_an_entry_whose_link_is_not_https_is_refused():
    payload = atom(
        '<entry><id>urn:8</id><title>T</title><link rel="alternate" href="javascript:alert(1)"/></entry>'
    )
    assert normalize(payload)[0] == []


def test_one_malformed_entry_does_not_take_its_siblings_down():
    payload = atom(
        "<entry><title>No identity</title></entry>"
        "<entry><id>urn:9</id><title>Fine</title>"
        '<link rel="alternate" href="https://example.com/9"/></entry>'
    )
    entries, rejected = normalize(payload)
    assert [e.item.feed_item_id for e in entries] == ["urn:9"]
    assert rejected == 1


# -- associations and trust ----------------------------------------------


def test_one_link_is_made_for_each_configured_symbol():
    entry = only(ATOM_UPDATED_ONLY, configured_symbols=("AAPL", "MSFT"))
    assert {link.symbol for link in entry.links} == {"AAPL", "MSFT"}
    assert all(
        link.association is SymbolAssociation.CONFIGURED_SYMBOL for link in entry.links
    )


def test_a_feed_configured_for_no_symbol_produces_no_association():
    """No text matcher exists, so an unconfigured feed claims no company."""
    assert only(ATOM_UPDATED_ONLY, configured_symbols=()).links == ()


def test_a_symbol_mentioned_in_the_text_creates_no_association():
    payload = atom(
        "<entry><id>urn:10</id><title>Why TSLA and NVDA are soaring</title>"
        '<link rel="alternate" href="https://example.com/10"/></entry>'
    )
    entry = only(payload, configured_symbols=("AAPL",))
    assert {link.symbol for link in entry.links} == {"AAPL"}


def test_the_configured_trust_class_is_recorded_on_the_item_and_its_links():
    entry = only(ATOM_UPDATED_ONLY, declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED)
    assert entry.item.declared_trust_class is DeclaredTrustClass.COMMUNITY_FEED
    assert all(
        link.declared_trust_class is DeclaredTrustClass.COMMUNITY_FEED for link in entry.links
    )


# -- text ----------------------------------------------------------------


def test_markup_in_a_title_survives_as_literal_text():
    payload = atom(
        "<entry><id>urn:11</id><title>&lt;script&gt;alert(1)&lt;/script&gt;</title>"
        '<link rel="alternate" href="https://example.com/11"/></entry>'
    )
    assert only(payload).item.title == "<script>alert(1)</script>"


def test_a_missing_author_becomes_an_explicit_unknown():
    assert only(ATOM_UPDATED_ONLY).item.publisher == "unknown publisher"


def test_an_atom_author_name_becomes_the_publisher():
    payload = atom(
        "<entry><id>urn:12</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/12"/>'
        "<author><name>Jane Example</name></author></entry>"
    )
    assert only(payload).item.publisher == "Jane Example"


def test_an_over_long_excerpt_is_truncated_rather_than_rejected():
    payload = atom(
        "<entry><id>urn:13</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/13"/>'
        f"<summary>{'x' * 5000}</summary></entry>"
    )
    from src.feeds.models import MAX_EXCERPT

    assert len(only(payload).item.excerpt) <= MAX_EXCERPT


def test_summary_is_preferred_over_content_for_the_excerpt():
    payload = atom(
        "<entry><id>urn:14</id><title>T</title>"
        '<link rel="alternate" href="https://example.com/14"/>'
        "<summary>The summary.</summary><content>The whole article.</content></entry>"
    )
    assert only(payload).item.excerpt == "The summary."


# -- no filtering at normalization ---------------------------------------


def test_every_entry_is_normalized_on_every_refresh():
    """No "already seen" filter here: a correction to an old entry must surface.

    Deciding new-versus-duplicate belongs to the store, which compares stored
    content. An adapter that skipped familiar ids would make revisions invisible.
    """
    payload = atom(
        "".join(
            f"<entry><id>urn:{n}</id><title>T{n}</title>"
            f'<link rel="alternate" href="https://example.com/{n}"/></entry>'
            for n in range(5)
        )
    )
    first, _ = normalize(payload)
    second, _ = normalize(payload)
    assert len(first) == len(second) == 5


def test_normalization_produces_the_same_content_hash_for_unchanged_entries():
    first = only(ATOM_BOTH).item
    second = only(ATOM_BOTH).item
    assert first.content_hash == second.content_hash


def test_a_changed_title_changes_the_content_hash():
    changed = ATOM_BOTH.replace(b"<title>Both</title>", b"<title>Both (corrected)</title>")
    assert only(ATOM_BOTH).item.content_hash != only(changed).item.content_hash


def test_an_rss_item_with_no_guid_and_no_link_is_refused_not_keyed_on_its_title():
    """A title is not an identity: it changes when the publisher fixes a typo,

    which would turn one corrected item into two unrelated ones.
    """
    payload = rss("<item><title>Only a title</title></item>")
    entries, rejected = normalize(payload, FeedFormat.RSS)
    assert entries == []
    assert rejected == 1
