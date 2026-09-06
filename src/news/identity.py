"""Deterministic identity and content hashing for external records.

Two jobs, both of which are silent-corruption risks if left to convention.

**Document identity** is the source's own identifier, never something derived
from the text. A headline-derived key would collide across a wire story and its
syndication, silently merging two different documents -- and would change when a
publisher fixed a typo, silently forking one document into two. So a record
without a provider identifier is refused rather than given a manufactured one.

**Content identity** is a SHA-256 over a canonical encoding of the fields that
constitute the record, used to tell a re-fetch of unchanged content (a
duplicate) from a genuine revision.

Determinism note
----------------
Python's ``hash()`` is randomised per process (PYTHONHASHSEED), so it produces a
different "identity" on every run -- useless for a record meant to outlive the
process. The canonical encoding here is the same JSON contract Phase 6 pinned in
:func:`src.assessments.policy.canonical_bytes`: sorted keys, no insignificant
whitespace, escaped non-ASCII, so two structurally different records cannot
render to the same bytes because of a delimiter appearing inside a value.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

#: Bumped only if the hashed field set changes meaning. A stored hash computed
#: under a different version is not comparable with one computed under this.
CONTENT_HASH_VERSION = 1


def canonical_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to deterministic bytes.

    Pinned contract, so a later edit cannot silently change every hash:

    * ``separators=(",", ":")`` -- no insignificant whitespace
    * ``ensure_ascii=True`` -- non-ASCII escapes, so bytes do not depend on the
      platform encoding
    * ``sort_keys=True`` -- key order fixed by content, not insertion
    * ``allow_nan=False`` -- ``NaN``/``Infinity`` are not valid JSON
    * UTF-8, fixed explicitly rather than inherited from the locale
    """
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
    """A 32-hex-character digest of the record's meaningful content.

    Stable across processes, machines and Python versions. Only the fields the
    caller passes participate: ``retrieved_at`` deliberately does not, or every
    re-fetch of unchanged content would look like a revision.
    """
    payload = {
        "version": CONTENT_HASH_VERSION,
        "fields": {
            key: (_stamp(value) if isinstance(value, datetime) else value)
            for key, value in sorted(fields.items())
        },
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()[:32]


def news_content_hash(
    *,
    headline: str,
    summary: str,
    canonical_url: str,
    publisher: str,
    source_published_at: datetime | None,
) -> str:
    """Content identity of a news article.

    Includes the source's claimed publication time on purpose: a provider that
    silently restates when it published has materially changed the record, and
    that must surface as a revision rather than vanish.
    """
    return content_hash(
        {
            "headline": headline,
            "summary": summary,
            "canonical_url": canonical_url,
            "publisher": publisher,
            "source_published_at": source_published_at,
        }
    )


def filing_content_hash(
    *,
    cik: str,
    form: str,
    items: tuple[str, ...],
    filing_date: str,
    report_date: str,
    primary_document_url: str,
    source_event_time: datetime | None,
) -> str:
    """Content identity of a filing record."""
    return content_hash(
        {
            "cik": cik,
            "form": form,
            "items": list(items),
            "filing_date": filing_date,
            "report_date": report_date,
            "primary_document_url": primary_document_url,
            "source_event_time": source_event_time,
        }
    )


#: Fields that may never change under a stable identifier. A change here means
#: the identifier has been reused for a different thing, which is a conflict
#: rather than a revision -- see :mod:`src.news.store`.
IMMUTABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "edgar": ("cik", "form", "filing_date"),
    "yahoo": ("canonical_url",),
}


def immutable_signature(source: str, record: Mapping[str, Any]) -> tuple[Any, ...]:
    """The values that must stay constant for one ``source_item_id``.

    Sources not listed contribute an empty signature, which means "no conflict
    detectable" rather than "no conflict possible" -- an honest default for an
    adapter whose stability guarantees have not been established.
    """
    return tuple(record.get(name) for name in IMMUTABLE_FIELDS.get(source, ()))


__all__ = [
    "CONTENT_HASH_VERSION",
    "canonical_bytes",
    "content_hash",
    "news_content_hash",
    "filing_content_hash",
    "IMMUTABLE_FIELDS",
    "immutable_signature",
]
