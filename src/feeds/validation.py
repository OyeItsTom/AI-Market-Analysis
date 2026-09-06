"""Validation for untrusted feed content, URLs and network destinations.

Two different URL policies live here, and conflating them would be a security
bug rather than an inconvenience:

**Configured feed URLs are fetched.** They must clear the full destination
policy -- scheme, host, and every address the host resolves to.

**Item links are only displayed.** Nothing follows them, so they do not need
destination checks to be *safe*; they get them anyway as defence in depth, so
the interface never hands a reader a clickable link to their own router.
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .models import MAX_URL, FeedError

ALLOWED_SCHEMES = frozenset({"https"})
DANGEROUS_SCHEMES = frozenset({"javascript", "data", "file", "ftp", "vbscript", "blob"})

#: How far ahead of our clock a source timestamp may sit before it is treated
#: as malformed. Publisher clock skew is ordinary; a week is not.
MAX_CLOCK_SKEW = timedelta(hours=26)


class UrlValidationError(FeedError):
    """Raised when a URL is not safe to fetch, store or display."""


class UnsafeDestination(FeedError):
    """Raised when a host resolves, or connects, to a forbidden address."""


def validate_url(value: object, *, label: str = "url") -> str:
    """Scheme/shape checks common to configured feeds and item links."""
    if not isinstance(value, str):
        raise UrlValidationError(f"{label} must be a str, got {type(value).__name__}")
    url = value.strip()
    if not url:
        raise UrlValidationError(f"{label} must not be empty")
    if len(url) > MAX_URL:
        raise UrlValidationError(f"{label} exceeds {MAX_URL} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise UrlValidationError(f"{label} contains control characters")
    if url.startswith("//"):
        raise UrlValidationError(
            f"{label} is scheme-relative; it would inherit the page's scheme"
        )

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if not scheme:
        raise UrlValidationError(f"{label} has no scheme")
    if scheme in DANGEROUS_SCHEMES:
        raise UrlValidationError(f"{label} uses the unsafe scheme {scheme!r}")
    if scheme not in ALLOWED_SCHEMES:
        raise UrlValidationError(
            f"{label} uses scheme {scheme!r}; only {sorted(ALLOWED_SCHEMES)} are allowed"
        )
    if not parts.hostname:
        raise UrlValidationError(f"{label} has no host")
    if "@" in parts.netloc:
        raise UrlValidationError(f"{label} embeds credentials in its authority")
    if _is_literal_address(parts.hostname) and is_unsafe_address(parts.hostname):
        # A host written as a literal address needs no DNS to classify, so it is
        # refused here rather than at fetch time. The resolution and peer checks
        # still stand behind this; catching it at load time only means the user
        # learns their configuration is wrong before pressing Refresh.
        raise UrlValidationError(
            f"{label} points at {parts.hostname}, which is not a permitted destination"
        )
    return url


def _is_literal_address(host: str) -> bool:
    """Whether a host is written as an IP literal rather than a name."""
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def is_unsafe_address(value: str | ipaddress._BaseAddress) -> bool:
    """Whether an address is one this application must never talk to.

    Built from :mod:`ipaddress` classification rather than a hand-kept range
    table. The composite is deliberate: ``is_global`` alone is not enough,
    because a multicast address such as ``224.0.0.1`` reports ``is_global``
    True and would slip through.

    IPv4-mapped IPv6 (``::ffff:10.0.0.1``) is unwrapped first, so the mapped
    form cannot be used to smuggle a private v4 destination past the check.

    Anything unparseable is reported unsafe. This predicate is asked whether a
    destination is *forbidden*, so the honest answer to "I cannot tell" is yes:
    an exception here would otherwise have to be caught correctly at every call
    site to avoid becoming an accidental permit.
    """
    if isinstance(value, str):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return True
    else:
        address = value
    mapped = getattr(address, "ipv4_mapped", None)
    effective = mapped or address
    return (
        not effective.is_global
        or effective.is_loopback
        or effective.is_private
        or effective.is_link_local
        or effective.is_multicast
        or effective.is_reserved
        or effective.is_unspecified
    )


def resolve_safely(host: str, port: int = 443) -> list[str]:
    """Resolve ``host`` and refuse it unless **every** address is safe.

    Every address, not merely the first: a host that answers with one public
    and one private address would otherwise be reachable on a later connection
    attempt. Resolution alone does not close the rebinding window -- the
    transport re-checks the address it actually connected to.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeDestination(f"could not resolve {host!r}: {exc}") from exc
    if not infos:
        raise UnsafeDestination(f"{host!r} resolved to no addresses")

    addresses = []
    for info in infos:
        address = info[4][0]
        if is_unsafe_address(address):
            raise UnsafeDestination(
                f"{host!r} resolves to {address}, which is not a permitted destination"
            )
        addresses.append(address)
    return addresses


def is_safe_display_url(value: object) -> bool:
    """Whether a link may be rendered as clickable.

    Never fetched by us, so this is defence in depth: an item link pointing at a
    private address is shown as text rather than offered to the reader as a
    click target.

    The judgement is **purely syntactic and never resolves the host.** Rendering
    a panel must not put a packet on the wire: this phase fetches only when a
    human presses Refresh, and a DNS lookup per link would both break that
    promise and tell the resolver which entries are being read. Resolving would
    also be worthless here -- the browser resolves again when the link is
    actually clicked, so any answer obtained now says nothing about then.

    Reachability is deliberately not consulted. Whether a host resolves on this
    machine at this moment has no bearing on whether the link is safe to show,
    and treating it as though it did would strip every link when offline.
    """
    try:
        url = validate_url(value, label="canonical_url")
    except FeedError:
        return False
    host = urlsplit(url).hostname or ""
    if _is_literal_address(host):
        return not is_unsafe_address(host)
    return True


def validate_source_timestamp(
    value: datetime | None, *, now: datetime, label: str = "source timestamp"
) -> datetime | None:
    """Refuse a source timestamp that cannot be true.

    ``None`` passes through unchanged: a missing timestamp is a known unknown
    and is represented by the availability basis, not invented here.
    """
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeedError(f"{label} must be timezone-aware")
    if value > now + MAX_CLOCK_SKEW:
        raise FeedError(
            f"{label} {value.isoformat()} is implausibly far in the future "
            f"(now {now.isoformat()})"
        )
    return value


def plain_text(value: object, *, maximum: int, default: str = "") -> str:
    """Collapse feed text to safe plain text.

    Feed titles and descriptions frequently carry escaped HTML. It is neither
    parsed nor regex-stripped -- regex is not an HTML parser and pretending
    otherwise is how sanitisers fail. The text is kept as characters, control
    characters removed, whitespace collapsed and length capped; the dashboard
    renders it through Streamlit's escaping text APIs, so any markup shows as
    the literal text it is.
    """
    if not isinstance(value, str):
        return default
    cleaned = "".join(
        character for character in value
        if ord(character) >= 32 or character in "\t\n"
    )
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > maximum:
        cleaned = cleaned[:maximum].rstrip()
    return cleaned or default


__all__ = [
    "ALLOWED_SCHEMES",
    "DANGEROUS_SCHEMES",
    "MAX_CLOCK_SKEW",
    "UrlValidationError",
    "UnsafeDestination",
    "validate_url",
    "is_unsafe_address",
    "resolve_safely",
    "is_safe_display_url",
    "validate_source_timestamp",
    "plain_text",
]
