"""Phase 8 identity: deterministic, source-supplied, and never manufactured.

Identity is where a news store silently corrupts itself. Too weak a key merges
two different stories; too brittle a key forks one story into two. These tests
pin both edges.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone

import pytest

from src.news.identity import (
    CONTENT_HASH_VERSION,
    IMMUTABLE_FIELDS,
    canonical_bytes,
    content_hash,
    filing_content_hash,
    immutable_signature,
    news_content_hash,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def hashed(**overrides) -> str:
    fields = dict(
        headline="A headline",
        summary="A summary",
        canonical_url="https://example.com/a",
        publisher="Reuters",
        source_published_at=T0,
    )
    fields.update(overrides)
    return news_content_hash(**fields)


# -- canonical encoding --------------------------------------------------


def test_canonical_bytes_are_key_order_independent():
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


def test_canonical_bytes_escape_non_ascii():
    encoded = canonical_bytes({"headline": "café"})
    assert b"caf\\u00e9" in encoded
    assert encoded.decode("ascii")


def test_canonical_bytes_reject_nan():
    with pytest.raises(ValueError):
        canonical_bytes({"value": float("nan")})


def test_canonical_bytes_have_no_insignificant_whitespace():
    assert b", " not in canonical_bytes({"a": 1, "b": 2})


# -- determinism ---------------------------------------------------------


def test_hash_is_deterministic_within_a_process():
    assert hashed() == hashed()


def test_hash_is_stable_across_processes_and_hash_seeds():
    """Python's hash() is randomised per process; this must not be."""
    script = (
        "from datetime import datetime, timezone;"
        "from src.news.identity import news_content_hash;"
        "print(news_content_hash(headline='A headline', summary='A summary',"
        " canonical_url='https://example.com/a', publisher='Reuters',"
        " source_published_at=datetime(2026,9,5,12,0,tzinfo=timezone.utc)))"
    )
    digests = set()
    for seed in ("0", "1", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=".",
        )
        assert result.returncode == 0, result.stderr
        digests.add(result.stdout.strip())
    assert len(digests) == 1
    assert digests.pop() == hashed()


def test_hash_length_and_alphabet_are_fixed():
    digest = hashed()
    assert len(digest) == 32
    assert all(character in "0123456789abcdef" for character in digest)


def test_hash_version_participates():
    assert CONTENT_HASH_VERSION == 1
    versioned = content_hash({"a": 1})
    assert versioned != content_hash({"a": 1, "version": 1})


# -- sensitivity ---------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("headline", "Another headline"),
        ("summary", "Another summary"),
        ("canonical_url", "https://example.com/b"),
        ("publisher", "Bloomberg"),
        ("source_published_at", datetime(2026, 9, 5, 13, 0, tzinfo=UTC)),
    ],
)
def test_every_content_field_changes_the_hash(field, value):
    assert hashed(**{field: value}) != hashed()


def test_a_restated_publication_time_is_a_content_change():
    """A provider silently changing when it published must surface, not vanish."""
    assert hashed(source_published_at=datetime(2026, 9, 4, tzinfo=UTC)) != hashed()


def test_hostile_delimiters_do_not_collide():
    """A value containing the encoding's own punctuation must not fake a field."""
    a = hashed(headline='x","summary":"y')
    b = hashed(headline="x", summary="y")
    assert a != b


def test_unicode_lookalikes_do_not_collide():
    assert hashed(headline="Apple") != hashed(headline="Аpple")  # Cyrillic А


def test_filing_hash_covers_official_metadata():
    base = dict(
        cik="0000320193", form="8-K", items=("5.02",), filing_date="2026-09-04",
        report_date="", primary_document_url="https://example.com/d.htm",
        source_event_time=T0,
    )
    first = filing_content_hash(**base)
    assert filing_content_hash(**{**base, "form": "10-K"}) != first
    assert filing_content_hash(**{**base, "items": ("1.01",)}) != first
    assert filing_content_hash(**{**base, "filing_date": "2026-09-05"}) != first


# -- immutable identity fields ------------------------------------------


def test_immutable_fields_are_declared_per_source():
    assert IMMUTABLE_FIELDS["edgar"] == ("cik", "form", "filing_date")
    assert IMMUTABLE_FIELDS["yahoo"] == ("canonical_url",)


def test_immutable_signature_detects_a_changed_url():
    a = immutable_signature("yahoo", {"canonical_url": "https://example.com/a"})
    b = immutable_signature("yahoo", {"canonical_url": "https://example.com/b"})
    assert a != b


def test_immutable_signature_ignores_mutable_content():
    a = immutable_signature("yahoo", {"canonical_url": "https://x/a", "headline": "one"})
    b = immutable_signature("yahoo", {"canonical_url": "https://x/a", "headline": "two"})
    assert a == b


def test_an_unknown_source_has_no_detectable_conflict():
    """An honest empty signature: 'not detectable', not 'not possible'."""
    assert immutable_signature("somewhere-else", {"anything": 1}) == ()


# -- no manufactured identity -------------------------------------------


def test_identity_module_offers_no_headline_derived_key():
    """There must be no helper that turns text into an item id."""
    import src.news.identity as module

    names = [name for name in dir(module) if not name.startswith("_")]
    for forbidden in ("item_id", "make_id", "derive_id", "fallback_id", "synth"):
        assert not any(forbidden in name.lower() for name in names), names
