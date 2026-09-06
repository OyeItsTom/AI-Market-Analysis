"""Phase 9 XML safety: entity expansion made structurally impossible.

The choice under test is refusal rather than mitigation. A DOCTYPE is rejected
before the parser sees the document, so a billion-laughs payload never reaches
an expander that could be argued about. Measured on this build, expat allowed
roughly a megabyte of output from a 347-byte input before its own limiter
engaged -- which is why a size cap alone was not considered sufficient.
"""

from __future__ import annotations

import pytest

from src.feeds.models import MAX_ENTRIES, FeedFormat
from src.feeds.xmlsafe import (
    UnsupportedFormat,
    XmlSafetyError,
    detect_format,
    parse_feed_bytes,
)

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
<entry><id>urn:1</id><title>One</title><updated>2026-09-05T10:00:00Z</updated></entry>
</feed>"""

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>One</title><link>https://example.com/1</link><guid>g1</guid></item>
</channel></rss>"""

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<feed xmlns="http://www.w3.org/2005/Atom"><title>&lol4;</title></feed>"""

EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE feed [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<feed xmlns="http://www.w3.org/2005/Atom"><title>&xxe;</title></feed>"""


# -- refusal before parsing ----------------------------------------------


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, EXTERNAL_ENTITY])
def test_a_doctype_is_refused_outright(payload):
    with pytest.raises(XmlSafetyError):
        parse_feed_bytes(payload)


@pytest.mark.parametrize(
    "spelling",
    [b"<!DOCTYPE", b"<!doctype", b"<!DocType", b"<!  DOCTYPE", b"<!\tDOCTYPE",
     b"<!\nDOCTYPE", b"<!\rDOCTYPE", b"<!" + b" " * 40 + b"DOCTYPE"],
)
def test_the_doctype_check_is_not_defeated_by_spacing_or_case(spelling):
    """The *policy* must fire, not merely some parse error.

    A weaker version of this test asserted only ``XmlSafetyError`` against a
    payload expat rejects on its own, so it passed even with the case-insensitive
    match removed. The message is checked so the refusal has to come from the
    DOCTYPE rule, and the document is otherwise well-formed so that nothing else
    can raise.
    """
    payload = (
        b'<?xml version="1.0"?>\n' + spelling + b' feed [\n]>\n'
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title></feed>'
    )
    with pytest.raises(XmlSafetyError) as caught:
        parse_feed_bytes(payload)
    assert "doctype" in str(caught.value).lower() or "dtd" in str(caught.value).lower()


def test_the_same_document_without_its_doctype_parses_cleanly():
    """Proves the refusal above is caused by the DOCTYPE and nothing else."""
    payload = (
        b'<?xml version="1.0"?>\n'
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title></feed>'
    )
    assert parse_feed_bytes(payload).format is FeedFormat.ATOM


def test_a_legitimate_feed_has_no_doctype_so_loses_nothing():
    assert parse_feed_bytes(ATOM).format is FeedFormat.ATOM
    assert parse_feed_bytes(RSS).format is FeedFormat.RSS


# -- format detection ----------------------------------------------------


def test_the_root_element_decides_the_format_not_the_file_name():
    assert detect_format(parse_feed_bytes(ATOM).root) is FeedFormat.ATOM
    assert detect_format(parse_feed_bytes(RSS).root) is FeedFormat.RSS


def test_a_document_that_contradicts_its_configured_type_is_refused():
    """Configuration saying ATOM and the server sending RSS is a real mismatch."""
    with pytest.raises(UnsupportedFormat):
        parse_feed_bytes(RSS, expected=FeedFormat.ATOM)
    with pytest.raises(UnsupportedFormat):
        parse_feed_bytes(ATOM, expected=FeedFormat.RSS)


@pytest.mark.parametrize(
    "payload",
    [
        b"<html><body>Not a feed</body></html>",
        b'{"items": []}',
        b"",
        b"   ",
        b"<feed>no namespace</feed>",
    ],
)
def test_something_that_is_not_a_feed_is_refused(payload):
    with pytest.raises((UnsupportedFormat, XmlSafetyError)):
        parse_feed_bytes(payload)


def test_malformed_xml_is_a_safety_error_not_a_crash():
    with pytest.raises(XmlSafetyError):
        parse_feed_bytes(b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">')


# -- bounds --------------------------------------------------------------


def test_entries_beyond_the_cap_are_truncated_and_the_truncation_is_reported():
    entries = b"".join(
        b"<entry><id>urn:%d</id><title>T</title></entry>" % n
        for n in range(MAX_ENTRIES + 25)
    )
    parsed = parse_feed_bytes(
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        + entries
        + b"</feed>"
    )
    assert parsed.entries_processed == MAX_ENTRIES
    assert parsed.entries_seen == MAX_ENTRIES + 25
    # Reported rather than silently dropped: "we read 100 of 125" is a different
    # statement from "there were 100".
    assert parsed.entries_truncated == 25


def test_a_deeply_nested_document_is_refused():
    payload = (
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        + b"<a>" * 300 + b"x" + b"</a>" * 300
        + b"</feed>"
    )
    with pytest.raises(XmlSafetyError):
        parse_feed_bytes(payload)


def test_a_normal_feed_is_nowhere_near_the_depth_limit():
    assert parse_feed_bytes(ATOM).entries_processed == 1
