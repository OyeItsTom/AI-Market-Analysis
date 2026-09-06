"""Normalize RSS 2.0 and Atom 1.0 entries into :class:`FeedItem` records.

The timing rules here carry the weight of the whole phase, because this is
where a source's own words become a claim this system will repeat.

**Atom.** ``updated`` is required by RFC 4287; ``published`` is optional, and
real feeds routinely omit it -- every entry in the SEC's own Atom feed has
``updated`` and no ``published``. So an entry with only ``updated`` is recorded
as :attr:`AvailabilityBasis.SOURCE_UPDATED`, never relabelled as a publication
time. Doing otherwise would have mislabelled every SEC entry, which is precisely
the overclaim the separate basis exists to prevent.

**RSS.** ``pubDate`` is a publication claim and is recorded as one. RSS 2.0 has
no per-item edit timestamp, so ``source_edited_at`` stays ``None`` and a
revision is known only from *same identity, changed content, observed at
``retrieved_at``*. The channel-level ``lastBuildDate`` is **never** borrowed as
an item time: it describes the document, not the entry.

Identity is always the provider's own: Atom ``<id>``, RSS ``<guid>``, else the
canonical link, else the entry is refused. An ``<id>`` or a permalink ``<guid>``
may look like a URL, but it is treated as an opaque string and never fetched.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..config import FeedDefinition
from ..identity import item_content_hash
from ..models import (
    MAX_EXCERPT,
    MAX_FEED_ITEM_ID,
    MAX_PUBLISHER,
    MAX_TITLE,
    AvailabilityBasis,
    FeedError,
    FeedFormat,
    FeedItem,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
)
from ..validation import plain_text, validate_source_timestamp, validate_url
from ..xmlsafe import ATOM_NS, ParsedFeed, text_of

ATOM = {"a": ATOM_NS}


class NormalizedEntry:
    """One entry plus the associations its configuration justifies."""

    __slots__ = ("item", "links")

    def __init__(self, item: FeedItem, links: tuple[SymbolLink, ...]) -> None:
        self.item = item
        self.links = links


def normalize_feed(
    parsed: ParsedFeed, definition: FeedDefinition, *, now: datetime
) -> tuple[list[NormalizedEntry], int]:
    """Normalize every bounded entry. Returns the entries and a rejected count.

    Every entry in the document is normalized on every refresh -- there is no
    "already seen" filter anywhere in this path. Whether an entry is new, a
    duplicate or a revision is decided later by the store, from identity and
    content, which is what makes a correction to an old entry visible.
    """
    entries: list[NormalizedEntry] = []
    rejected = 0
    for element in parsed.entries:
        try:
            entry = _normalize_entry(element, parsed.format, definition, now=now)
        except FeedError:
            entry = None
        if entry is None:
            # One malformed entry is dropped on its own; its siblings are fine.
            rejected += 1
        else:
            entries.append(entry)
    return entries, rejected


def _normalize_entry(
    element: ET.Element,
    feed_format: FeedFormat,
    definition: FeedDefinition,
    *,
    now: datetime,
) -> NormalizedEntry | None:
    if feed_format is FeedFormat.ATOM:
        title, link, item_id, publisher, excerpt, published, updated = _atom_fields(element)
    else:
        title, link, item_id, publisher, excerpt, published, updated = _rss_fields(element)

    if not item_id or len(item_id) > MAX_FEED_ITEM_ID:
        # IDENTITY_UNSAFE: no usable provider identifier, and none is invented.
        return None
    if not title or not link:
        return None

    try:
        canonical_url = validate_url(link, label="canonical_url")
    except FeedError:
        return None

    # An implausible source timestamp costs the claim, not the entry. Dropping
    # the whole record would hide a publisher's clock error; keeping the record
    # while refusing its unusable assertion states exactly what is known.
    published = _plausible(published, now=now)
    updated = _plausible(updated, now=now)

    if published is not None:
        available_from, basis = published, AvailabilityBasis.SOURCE_PUBLISHED
    elif updated is not None:
        # Atom guarantees updated but not published. This is an update time and
        # is labelled as one; it is not promoted to a publication claim.
        available_from, basis = updated, AvailabilityBasis.SOURCE_UPDATED
    else:
        available_from, basis = now, AvailabilityBasis.SYSTEM_OBSERVED

    excerpt = plain_text(excerpt, maximum=MAX_EXCERPT)
    publisher = plain_text(publisher, maximum=MAX_PUBLISHER)
    title = plain_text(title, maximum=MAX_TITLE)
    if not title:
        return None

    item = FeedItem(
        source_id=definition.source_id,
        feed_item_id=item_id,
        declared_trust_class=definition.declared_trust_class,
        trust_basis=TrustBasis.USER_CONFIGURED,
        title=title,
        canonical_url=canonical_url,
        retrieved_at=now,
        availability_basis=basis,
        config_fingerprint=definition.config_fingerprint,
        publisher=publisher,
        excerpt=excerpt,
        source_published_at=published,
        source_edited_at=updated if published is None or updated != published else None,
        available_from=available_from,
        content_hash=item_content_hash(
            title=title,
            excerpt=excerpt,
            canonical_url=canonical_url,
            publisher=publisher,
            source_published_at=published,
            source_edited_at=updated,
        ),
    )

    links = tuple(
        SymbolLink(
            source_id=definition.source_id,
            feed_item_id=item_id,
            symbol=symbol,
            # The only truthful claim: this feed is configured for that symbol.
            association=SymbolAssociation.CONFIGURED_SYMBOL,
            retrieved_at=now,
            config_fingerprint=definition.config_fingerprint,
            declared_trust_class=definition.declared_trust_class,
        )
        for symbol in definition.configured_symbols
    )
    return NormalizedEntry(item, links)


def _plausible(value: datetime | None, *, now: datetime) -> datetime | None:
    try:
        return validate_source_timestamp(value, now=now)
    except FeedError:
        return None


def _atom_fields(element: ET.Element):
    title = text_of(element.find("a:title", ATOM))
    item_id = text_of(element.find("a:id", ATOM)).strip()
    summary = element.find("a:summary", ATOM)
    content = element.find("a:content", ATOM)
    excerpt = text_of(summary if summary is not None else content)
    author = element.find("a:author/a:name", ATOM)
    publisher = text_of(author)

    link = ""
    for candidate in element.findall("a:link", ATOM):
        rel = candidate.get("rel", "alternate")
        if rel == "alternate" and candidate.get("href"):
            link = candidate.get("href", "").strip()
            break
    if not link:
        first = element.find("a:link", ATOM)
        link = (first.get("href", "").strip() if first is not None else "")

    published = _parse_iso(text_of(element.find("a:published", ATOM)))
    updated = _parse_iso(text_of(element.find("a:updated", ATOM)))
    if not item_id:
        item_id = link
    return title, link, item_id, publisher, excerpt, published, updated


def _rss_fields(element: ET.Element):
    title = text_of(element.find("title"))
    link = text_of(element.find("link")).strip()
    excerpt = text_of(element.find("description"))
    publisher = text_of(element.find("source"))

    guid_element = element.find("guid")
    guid = text_of(guid_element).strip()
    # A permalink guid is still treated as an opaque identity string. It is
    # never fetched merely because it happens to look like a URL.
    item_id = guid or link

    # Deliberately only the item's own pubDate. The channel's lastBuildDate
    # describes the document, not this entry, and borrowing it would invent an
    # item timestamp the publisher never gave.
    published = _parse_rfc822(text_of(element.find("pubDate")))
    return title, link, item_id, publisher, excerpt, published, None


def _parse_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _parse_rfc822(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


__all__ = ["NormalizedEntry", "normalize_feed"]
