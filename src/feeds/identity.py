"""Deterministic identity, content hashing and configuration fingerprints.

Identity is always the provider's own declared id. Nothing is derived from
title, excerpt or timestamp: a text-derived key merges a wire story with its
syndication, and forks a document the moment a publisher fixes a typo. A record
without a usable provider id is refused instead.

Determinism note: Python's ``hash()`` is randomised per process, so every value
here goes through a pinned canonical JSON encoding and SHA-256 -- stable across
processes, machines and runs, which is what a persisted record requires.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

#: Bumped only if the hashed field set changes meaning.
CONTENT_HASH_VERSION = 1
CONFIG_FINGERPRINT_VERSION = 1


def canonical_bytes(payload: Any) -> bytes:
    """Serialize deterministically: sorted keys, no whitespace, escaped, UTF-8."""
    return json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def content_hash(fields: Mapping[str, Any]) -> str:
    """A 32-hex digest of an item's meaningful content.

    ``retrieved_at`` is deliberately excluded: including it would make every
    re-fetch of unchanged content look like a revision.
    """
    payload = {
        "version": CONTENT_HASH_VERSION,
        "fields": {
            key: (_stamp(value) if isinstance(value, datetime) else value)
            for key, value in sorted(fields.items())
        },
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()[:32]


def item_content_hash(
    *,
    title: str,
    excerpt: str,
    canonical_url: str,
    publisher: str,
    source_published_at: datetime | None,
    source_edited_at: datetime | None,
) -> str:
    """Content identity of one feed entry.

    Both source timestamps participate: a publisher silently restating when it
    published, or bumping an update time, has materially changed the record and
    that must surface as a revision rather than vanish.
    """
    return content_hash(
        {
            "title": title,
            "excerpt": excerpt,
            "canonical_url": canonical_url,
            "publisher": publisher,
            "source_published_at": source_published_at,
            "source_edited_at": source_edited_at,
        }
    )


def config_fingerprint(
    *,
    source_id: str,
    feed_format: str,
    url: str,
    declared_trust_class: str,
    configured_symbols: tuple[str, ...],
) -> str:
    """Fingerprint of everything about a source that changes what a record means.

    ``display_name`` is absent on purpose: renaming a feed changes nothing about
    what was observed, and letting it churn the fingerprint would invalidate
    transport validators and manufacture association observations for a cosmetic
    edit.
    """
    return hashlib.sha256(
        canonical_bytes(
            {
                "version": CONFIG_FINGERPRINT_VERSION,
                "source_id": source_id,
                "format": feed_format,
                "url": url,
                "declared_trust_class": declared_trust_class,
                "configured_symbols": sorted(configured_symbols),
            }
        )
    ).hexdigest()[:32]


def endpoint_fingerprint(*, source_id: str, feed_format: str, url: str) -> str:
    """Fingerprint of the identity-bearing fields only.

    Transport validators (ETag/Last-Modified) belong to an *endpoint*, so they
    are keyed on this rather than on the full configuration: retagging a feed's
    trust class must not throw away a perfectly good ETag, while changing its
    URL must.
    """
    return hashlib.sha256(
        canonical_bytes(
            {
                "version": CONFIG_FINGERPRINT_VERSION,
                "source_id": source_id,
                "format": feed_format,
                "url": url,
            }
        )
    ).hexdigest()[:32]


def url_host(url: str) -> str:
    """Lower-cased host in punycode, the immutable half of item identity.

    Publishers restructure paths while editing an entry, so the path is treated
    as revisable content. Moving to a different host under the same provider id
    is a different matter and is reported as an identity conflict.

    Non-ASCII hosts are encoded to their IDNA form so a look-alike domain cannot
    be *displayed* as the name it imitates: a Cyrillic "examp\u0440le.com" becomes a
    visibly different ``xn--`` string rather than a convincing counterfeit of the
    Latin spelling. It also makes the identity comparison exact, since two
    scripts that render alike encode differently.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        # Un-encodable is left as-is rather than silently dropped; the caller
        # compares and displays it, and an empty host would be the worse lie.
        return host


__all__ = [
    "CONTENT_HASH_VERSION",
    "CONFIG_FINGERPRINT_VERSION",
    "canonical_bytes",
    "content_hash",
    "item_content_hash",
    "config_fingerprint",
    "endpoint_fingerprint",
    "url_host",
]
