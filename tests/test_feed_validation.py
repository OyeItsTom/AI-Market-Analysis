"""Phase 9 URL and address validation: the SSRF surface.

Feed URLs come from a local file rather than being hard-coded, so a typo or a
pasted line can point anywhere. These tests fix the refusal rules in place,
including the ones that a plausible-looking "is it public?" check gets wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.feeds.models import FeedError
from src.feeds.validation import (
    ALLOWED_SCHEMES,
    UnsafeDestination,
    UrlValidationError,
    is_safe_display_url,
    is_unsafe_address,
    plain_text,
    resolve_safely,
    validate_source_timestamp,
    validate_url,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


# -- schemes -------------------------------------------------------------


def test_only_https_is_allowed():
    assert ALLOWED_SCHEMES == frozenset({"https"})


def test_plain_http_is_refused():
    """No downgrade: a feed read over http can be rewritten in transit."""
    with pytest.raises(UrlValidationError):
        validate_url("http://example.com/feed.xml")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/xml;base64,PGZlZWQvPg==",
        "file:///etc/passwd",
        "ftp://example.com/feed.xml",
        "vbscript:msgbox(1)",
        "gopher://example.com/",
        "//example.com/feed.xml",
        "",
        "   ",
        "https://",
        "not a url",
    ],
)
def test_dangerous_or_malformed_urls_are_refused(url):
    with pytest.raises(FeedError):
        validate_url(url)


def test_a_non_string_url_is_refused():
    with pytest.raises(FeedError):
        validate_url(None)


def test_credentials_in_a_url_are_refused():
    """Embedded credentials are both a leak risk and a phishing display trick."""
    with pytest.raises(UrlValidationError):
        validate_url("https://user:password@example.com/feed.xml")


def test_an_over_long_url_is_refused():
    with pytest.raises(UrlValidationError):
        validate_url("https://example.com/" + "a" * 4000)


def test_an_ordinary_https_url_survives():
    assert validate_url("https://www.sec.gov/news/pressreleases.rss") == (
        "https://www.sec.gov/news/pressreleases.rss"
    )


# -- addresses -----------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",          # loopback
        "0.0.0.0",            # unspecified
        "10.0.0.5",           # private
        "172.16.0.1",         # private
        "192.168.1.1",        # private
        "169.254.169.254",    # link-local: the cloud metadata endpoint
        "100.64.0.1",         # carrier-grade NAT
        "224.0.0.1",          # multicast
        "255.255.255.255",    # broadcast
        "::1",                # IPv6 loopback
        "fe80::1",            # IPv6 link-local
        "fc00::1",            # IPv6 unique-local
        "::ffff:127.0.0.1",   # IPv4-mapped loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata endpoint
    ],
)
def test_forbidden_addresses_are_recognised(address):
    assert is_unsafe_address(address), f"{address} should be refused"


def test_multicast_is_refused_even_though_it_reports_as_global():
    """A composite check, not ``is_global`` alone.

    ``ipaddress`` reports ``224.0.0.1`` as ``is_global``, so a validator built
    on that one property would wave multicast straight through.
    """
    import ipaddress

    assert ipaddress.ip_address("224.0.0.1").is_global
    assert is_unsafe_address("224.0.0.1")


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_ordinary_public_addresses_are_permitted(address):
    assert not is_unsafe_address(address)


def test_an_unparseable_address_is_treated_as_unsafe():
    """Fail closed: what cannot be classified is not permitted."""
    assert is_unsafe_address("not-an-address")


def test_resolution_refuses_a_host_that_lands_on_a_private_address(monkeypatch):
    import src.feeds.validation as validation

    monkeypatch.setattr(
        validation.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))],
    )
    with pytest.raises(UnsafeDestination):
        resolve_safely("internal.example.com")


def test_resolution_refuses_when_only_one_of_several_addresses_is_private(monkeypatch):
    """Any forbidden address disqualifies the host, not just all of them."""
    import src.feeds.validation as validation

    monkeypatch.setattr(
        validation.socket, "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(UnsafeDestination):
        resolve_safely("rebinding.example.com")


def test_resolution_failure_is_reported_not_swallowed(monkeypatch):
    import socket as socket_module

    import src.feeds.validation as validation

    def boom(*a, **k):
        raise socket_module.gaierror("no such host")

    monkeypatch.setattr(validation.socket, "getaddrinfo", boom)
    with pytest.raises(FeedError):
        resolve_safely("nowhere.invalid")


# -- display-only links --------------------------------------------------


def test_a_display_url_with_a_dangerous_scheme_is_not_shown_as_a_link():
    assert not is_safe_display_url("javascript:alert(1)")
    assert not is_safe_display_url("data:text/html,<script>x</script>")
    assert not is_safe_display_url(None)


def test_a_display_url_pointing_at_a_literal_private_address_is_refused():
    assert not is_safe_display_url("https://127.0.0.1/x")
    assert not is_safe_display_url("https://169.254.169.254/latest/meta-data/")


# -- source timestamps ---------------------------------------------------


def test_a_naive_source_timestamp_is_refused():
    with pytest.raises(FeedError):
        validate_source_timestamp(datetime(2026, 9, 6, 12, 0), now=T0)


def test_an_absent_source_timestamp_passes_through():
    """Missing is a known unknown; it is not invented here."""
    assert validate_source_timestamp(None, now=T0) is None


def test_an_implausibly_future_timestamp_is_refused():
    with pytest.raises(FeedError):
        validate_source_timestamp(T0 + timedelta(days=400), now=T0)


def test_small_clock_skew_is_tolerated():
    assert validate_source_timestamp(T0 + timedelta(minutes=1), now=T0) is not None


# -- text ----------------------------------------------------------------


def test_markup_is_kept_as_literal_text_not_stripped_by_regex():
    """Regex is not an HTML parser; the text is escaped at render time instead."""
    assert plain_text("<b>bold</b>", maximum=100) == "<b>bold</b>"


def test_control_characters_are_removed_and_whitespace_collapsed():
    assert plain_text("a\x00b\n\n  c", maximum=100) == "ab c"


def test_text_is_truncated_to_the_limit():
    assert len(plain_text("x" * 500, maximum=10)) == 10


def test_non_string_text_becomes_the_default():
    assert plain_text(None, maximum=10) == ""
    assert plain_text(12345, maximum=10, default="none") == "none"


def test_a_url_whose_host_is_a_forbidden_literal_address_is_refused():
    """No DNS needed to classify it, so it is refused at validation time."""
    for url in (
        "https://127.0.0.1/feed.xml",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/feed.xml",
        "https://[::1]/feed.xml",
    ):
        with pytest.raises(UrlValidationError):
            validate_url(url)


def test_a_public_literal_address_is_still_allowed():
    assert validate_url("https://93.184.216.34/feed.xml")


# -- display-link safety is syntactic, never resolved --------------------


def test_an_ordinary_public_link_is_shown_as_a_link():
    """The negative cases are not enough: legitimate links must survive."""
    for url in (
        "https://example.com/story",
        "https://www.sec.gov/news/pressreleases.rss",
        "https://sub.domain.example.co.uk/a/b?c=d#e",
    ):
        assert is_safe_display_url(url), url


def test_a_link_whose_host_does_not_resolve_is_still_shown():
    """Reachability is not safety, and offline use must not strip every link."""
    assert is_safe_display_url("https://this-host-does-not-exist-zz.invalid/x")


def test_deciding_whether_a_link_is_clickable_performs_no_dns(monkeypatch):
    """Rendering must put nothing on the wire.

    This phase fetches only when a human presses Refresh. A DNS lookup per
    rendered link would break that promise and tell the resolver which entries
    are being read.
    """
    import src.feeds.validation as validation

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("is_safe_display_url resolved a hostname")

    monkeypatch.setattr(validation.socket, "getaddrinfo", forbidden)
    assert is_safe_display_url("https://example.com/story")
    assert not is_safe_display_url("https://127.0.0.1/x")
    assert not is_safe_display_url("javascript:alert(1)")


def test_ipv4_mapped_addresses_are_unwrapped_before_classification():
    """Pinned structurally, because CPython 3.11 masks it behaviourally.

    On this interpreter ``IPv6Address.is_private`` already consults the mapped
    v4 address, so deleting the unwrapping changes no observable result here and
    a behavioural test cannot catch it. The unwrapping is still the thing that
    makes the classification correct rather than incidentally correct, so it is
    asserted directly — otherwise it reads as dead code and gets removed.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/feeds/validation.py").read_text(encoding="utf-8"))
    predicate = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "is_unsafe_address"
    )
    source = ast.dump(predicate)
    assert "ipv4_mapped" in source, (
        "is_unsafe_address no longer unwraps IPv4-mapped IPv6; classification "
        "would then depend on the stdlib doing it for us"
    )


@pytest.mark.parametrize(
    "address",
    ["::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:192.168.1.1",
     "::ffff:169.254.169.254", "::ffff:224.0.0.1", "::ffff:0.0.0.0"],
)
def test_every_mapped_private_form_is_refused(address):
    assert is_unsafe_address(address)


def test_a_mapped_public_address_is_still_permitted():
    assert not is_unsafe_address("::ffff:93.184.216.34")
