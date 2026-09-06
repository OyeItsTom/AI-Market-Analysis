"""Safe XML parsing for feed documents.

A feed is untrusted XML from the public internet, so the parser is the first
thing an attacker reaches.

**No DTD, at all.** Any document containing a DOCTYPE declaration is refused
before parsing begins. Neither RSS 2.0 nor Atom 1.0 needs one, and without an
internal subset there is nowhere for entities to be declared -- which makes
entity expansion *structurally impossible* rather than merely bounded. That
matters: expat's own amplification limiter has an absolute activation floor, and
was measured allowing roughly a megabyte of output from a few hundred bytes of
input before it fired. Refusing the DTD outright removes the whole class.

External entities (XXE) are refused by the same rule, since they too require a
DOCTYPE.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .models import MAX_ENTRIES, FeedError, FeedFormat

ATOM_NS = "http://www.w3.org/2005/Atom"
ATOM_FEED_TAG = f"{{{ATOM_NS}}}feed"
RSS_ROOT_TAG = "rss"

#: Matches a DOCTYPE however it is spaced or cased. Deliberately liberal: this
#: is a refusal rule, so over-matching costs a legitimate feed nothing (they do
#: not carry DTDs) while under-matching would let an entity bomb through.
_DOCTYPE = re.compile(rb"<!\s*DOCTYPE", re.IGNORECASE)

#: An XML declaration may name an encoding; ElementTree honours it from bytes.
_MAX_DEPTH = 100


class XmlSafetyError(FeedError):
    """Raised when a document is refused before or during parsing."""


class UnsupportedFormat(FeedError):
    """Raised when the root element is neither an RSS nor an Atom feed."""


@dataclass(frozen=True)
class ParsedFeed:
    """A parsed feed document plus what parsing had to leave out."""

    format: FeedFormat
    root: ET.Element
    entries: tuple[ET.Element, ...]
    entries_seen: int
    entries_truncated: int

    @property
    def entries_processed(self) -> int:
        return len(self.entries)


def parse_feed_bytes(raw: bytes, *, expected: FeedFormat | None = None) -> ParsedFeed:
    """Parse a feed document safely, or refuse it.

    ``expected`` is the format the source is configured as. A mismatch is
    refused rather than silently honoured: quietly reinterpreting a source's
    declared type would mean the configuration no longer describes what is
    being ingested.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise XmlSafetyError("feed body must be bytes")
    if not raw.strip():
        raise XmlSafetyError("feed body is empty")
    if _DOCTYPE.search(raw):
        raise XmlSafetyError(
            "the document declares a DTD; feeds do not need one and it is "
            "refused so entities cannot be declared"
        )

    try:
        root = ET.fromstring(bytes(raw))
    except ET.ParseError as exc:
        raise XmlSafetyError(f"malformed XML: {exc}") from exc

    _require_bounded_depth(root)

    detected = detect_format(root)
    if expected is not None and detected is not expected:
        raise UnsupportedFormat(
            f"source is configured as {expected.value!r} but the document is "
            f"{detected.value!r}; refusing to reinterpret the configured type"
        )

    all_entries = _entries_of(root, detected)
    kept = all_entries[:MAX_ENTRIES]
    return ParsedFeed(
        format=detected,
        root=root,
        entries=tuple(kept),
        entries_seen=len(all_entries),
        entries_truncated=max(0, len(all_entries) - len(kept)),
    )


def detect_format(root: ET.Element) -> FeedFormat:
    """Dispatch on the root element only. No heuristics, no sniffing."""
    if root.tag == ATOM_FEED_TAG:
        return FeedFormat.ATOM
    if root.tag == RSS_ROOT_TAG:
        return FeedFormat.RSS
    raise UnsupportedFormat(
        f"unsupported root element {root.tag!r}; only RSS 2.0 and Atom 1.0 are parsed"
    )


def _entries_of(root: ET.Element, feed_format: FeedFormat) -> list[ET.Element]:
    if feed_format is FeedFormat.ATOM:
        return list(root.findall(f"{{{ATOM_NS}}}entry"))
    channel = root.find("channel")
    return list(channel.findall("item")) if channel is not None else []


def _require_bounded_depth(root: ET.Element, limit: int = _MAX_DEPTH) -> None:
    """Refuse pathologically nested documents.

    Deep nesting is not an expansion attack once DTDs are refused, but it can
    still drive deep recursion in consumers, so it is bounded here iteratively.
    """
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        if depth > limit:
            raise XmlSafetyError(f"document nesting exceeds {limit} levels")
        for child in element:
            stack.append((child, depth + 1))


def text_of(element: ET.Element | None) -> str:
    """Concatenated text of an element, entities already decoded by the parser."""
    if element is None:
        return ""
    return "".join(element.itertext())


__all__ = [
    "ATOM_NS",
    "ATOM_FEED_TAG",
    "RSS_ROOT_TAG",
    "XmlSafetyError",
    "UnsupportedFormat",
    "ParsedFeed",
    "parse_feed_bytes",
    "detect_format",
    "text_of",
]
