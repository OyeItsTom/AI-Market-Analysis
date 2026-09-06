"""Validation for untrusted external records, especially their URLs.

Everything Phase 8 ingests comes from outside this repository, so the rules here
are a boundary rather than a formality.

URL policy
----------
A stored URL is rendered as a clickable link in the dashboard, which makes it an
attack surface. Only ``https`` is accepted. ``javascript:`` and ``data:`` are
script execution wearing a link's clothes; ``file:`` reads the viewer's disk;
scheme-relative ``//host/path`` inherits whatever scheme the page happens to
have. Credentials in the authority are refused because they are almost always
either a phishing construction or a secret about to be displayed.

**No URL from a payload is ever fetched.** Validation makes a link safe to
*show*, not safe to *follow*; nothing in Phase 8 follows one, which is what
closes the SSRF question rather than mitigating it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .models import MAX_URL, NewsError

#: The only scheme a stored, rendered link may use.
ALLOWED_SCHEMES = frozenset({"https"})

#: Schemes named explicitly so a rejection message can say what was wrong.
DANGEROUS_SCHEMES = frozenset({"javascript", "data", "file", "ftp", "vbscript", "blob"})

#: How far ahead of the build clock a source timestamp may sit before it is
#: treated as malformed. Small clock skew between a publisher and this machine
#: is ordinary; a week is not.
MAX_CLOCK_SKEW = timedelta(hours=26)


class UrlValidationError(NewsError):
    """Raised when a URL is not safe to store or display."""


def validate_url(value: object, *, label: str = "url") -> str:
    """Return ``value`` if it is a link this system will store and display."""
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
            f"{label} uses scheme {scheme!r}; only {sorted(ALLOWED_SCHEMES)} are stored"
        )
    if not parts.netloc:
        raise UrlValidationError(f"{label} has no host")
    if "@" in parts.netloc:
        raise UrlValidationError(f"{label} embeds credentials in its authority")
    return url


def validate_source_timestamp(
    value: datetime | None, *, now: datetime, label: str = "source timestamp"
) -> datetime | None:
    """Reject a source timestamp that cannot be true.

    A far-future publication time is a malformed record, not a scoop: accepting
    one would let a story be "available" before any plausible reader saw it.
    Returns ``None`` unchanged -- a missing timestamp is a known unknown and is
    handled by the availability basis, not invented here.
    """
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise NewsError(f"{label} must be timezone-aware")
    if value > now + MAX_CLOCK_SKEW:
        raise NewsError(
            f"{label} {value.isoformat()} is implausibly far in the future "
            f"(now {now.isoformat()})"
        )
    return value


def safe_text(value: object, *, maximum: int, default: str = "") -> str:
    """Best-effort text cleaning for a display-only field.

    Control characters are stripped and length is capped. HTML is **not**
    interpreted anywhere -- it is escaped at render time -- so markup arriving
    inside a headline is inert text rather than something to sanitise into
    silence.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    cleaned = "".join(
        character for character in value if ord(character) >= 32 or character == "\t"
    ).strip()
    if len(cleaned) > maximum:
        cleaned = cleaned[:maximum].rstrip()
    return cleaned or default


__all__ = [
    "ALLOWED_SCHEMES",
    "DANGEROUS_SCHEMES",
    "MAX_CLOCK_SKEW",
    "UrlValidationError",
    "validate_url",
    "validate_source_timestamp",
    "safe_text",
]
