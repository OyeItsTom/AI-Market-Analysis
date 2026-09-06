"""Phase 9 identity: stable hashes, and fingerprints that separate concerns.

Two fingerprints exist because two different questions are asked of the
configuration. ``endpoint_fingerprint`` keys the cached ETag and must change
only when the endpoint changes. ``config_fingerprint`` records what an
observation *meant* and must change whenever trust or symbols change. Collapsing
them would either throw away valid caches on a rename or keep serving a cache
after the URL moved.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.feeds.identity import (
    canonical_bytes,
    config_fingerprint,
    content_hash,
    endpoint_fingerprint,
    item_content_hash,
    url_host,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def base_config(**overrides):
    fields = dict(
        source_id="demo",
        feed_format="atom",
        url="https://example.com/feed.xml",
        declared_trust_class="publisher_feed",
        configured_symbols=("AAPL",),
    )
    fields.update(overrides)
    return fields


def base_item(**overrides):
    fields = dict(
        title="A title",
        excerpt="An excerpt.",
        canonical_url="https://example.com/a",
        publisher="Example",
        source_published_at=T0,
        source_edited_at=None,
    )
    fields.update(overrides)
    return fields


# -- canonical encoding --------------------------------------------------


def test_key_order_does_not_change_the_encoding():
    assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})


def test_the_encoding_is_ascii_safe_and_stable():
    encoded = canonical_bytes({"t": "café ☕"})
    assert isinstance(encoded, bytes)
    assert encoded == canonical_bytes({"t": "café ☕"})
    assert all(byte < 128 for byte in encoded)


def test_non_finite_numbers_are_refused():
    """NaN is not JSON and never round-trips; a hash over it would be a lie."""
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})


def test_hashes_are_hex_and_deterministic():
    first = content_hash({"a": 1})
    assert first == content_hash({"a": 1})
    # A truncated sha256: 128 bits is far more than enough to tell two versions
    # of one feed entry apart, and the digest is never a security boundary.
    assert len(first) == 32
    int(first, 16)


def test_the_hash_takes_no_retrieval_time():
    """Otherwise every re-fetch of unchanged content would look like a revision.

    Enforced on the signature: there is no parameter through which a retrieval
    time could be passed in.
    """
    import inspect

    parameters = set(inspect.signature(item_content_hash).parameters)
    assert not {p for p in parameters if "retriev" in p or "fetch" in p}
    assert parameters == {
        "title", "excerpt", "canonical_url", "publisher",
        "source_published_at", "source_edited_at",
    }


# -- item content ---------------------------------------------------------


def test_a_changed_title_changes_the_item_hash():
    assert item_content_hash(**base_item()) != item_content_hash(
        **base_item(title="A different title")
    )


def test_a_changed_excerpt_changes_the_item_hash():
    assert item_content_hash(**base_item()) != item_content_hash(
        **base_item(excerpt="Rewritten.")
    )


def test_a_restated_publication_time_changes_the_item_hash():
    """A publisher silently restating when it published has changed the record."""
    assert item_content_hash(**base_item()) != item_content_hash(
        **base_item(source_published_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    )


def test_a_bumped_update_time_changes_the_item_hash():
    assert item_content_hash(**base_item()) != item_content_hash(
        **base_item(source_edited_at=T0)
    )


def test_an_unchanged_entry_hashes_the_same():
    assert item_content_hash(**base_item()) == item_content_hash(**base_item())


# -- configuration fingerprints ------------------------------------------


def test_a_display_name_is_not_an_input_to_either_fingerprint():
    """Renaming a feed must not invalidate a cache or reinterpret records.

    Asserted on the signatures rather than by passing two names: display_name is
    not a parameter of either function, so there is no way for it to influence a
    fingerprint. An equality check between two identical configs would have
    passed no matter what the functions did with the name.
    """
    import inspect

    assert "display_name" not in inspect.signature(config_fingerprint).parameters
    assert "display_name" not in inspect.signature(endpoint_fingerprint).parameters
    assert config_fingerprint(**base_config()) == config_fingerprint(**base_config())


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://example.com/other.xml"},
        {"source_id": "other"},
        {"feed_format": "rss"},
    ],
)
def test_an_identity_change_changes_both_fingerprints(change):
    assert endpoint_fingerprint(
        source_id=base_config()["source_id"],
        feed_format=base_config()["feed_format"],
        url=base_config()["url"],
    ) != endpoint_fingerprint(
        source_id=base_config(**change)["source_id"],
        feed_format=base_config(**change)["feed_format"],
        url=base_config(**change)["url"],
    )
    assert config_fingerprint(**base_config()) != config_fingerprint(**base_config(**change))


@pytest.mark.parametrize(
    "change",
    [
        {"declared_trust_class": "official_feed"},
        {"configured_symbols": ("AAPL", "MSFT")},
        {"configured_symbols": ()},
    ],
)
def test_a_trust_or_symbol_change_changes_only_the_config_fingerprint(change):
    """The endpoint is the same, so the cached ETag stays valid...

    ...but what a new observation *means* has changed, so records made after the
    change must be distinguishable from records made before it.
    """
    changed = base_config(**change)
    assert endpoint_fingerprint(
        source_id=changed["source_id"],
        feed_format=changed["feed_format"],
        url=changed["url"],
    ) == endpoint_fingerprint(
        source_id=base_config()["source_id"],
        feed_format=base_config()["feed_format"],
        url=base_config()["url"],
    )
    assert config_fingerprint(**base_config()) != config_fingerprint(**changed)


def test_symbol_order_does_not_change_the_config_fingerprint():
    """Reordering a list in a JSON file is not a change of meaning."""
    assert config_fingerprint(**base_config(configured_symbols=("AAPL", "MSFT"))) == (
        config_fingerprint(**base_config(configured_symbols=("MSFT", "AAPL")))
    )


# -- hosts ---------------------------------------------------------------


def test_url_host_is_lowercased():
    assert url_host("https://WWW.Example.COM/feed.xml") == "www.example.com"


def test_url_host_of_something_unparseable_is_empty_not_an_error():
    assert url_host("not a url") == ""


def test_a_look_alike_host_is_displayed_in_punycode_not_as_the_name_it_imitates():
    """A Cyrillic homograph must not be able to render as the Latin spelling."""
    homograph = url_host("https://examрle.com/feed.xml")
    assert homograph.startswith("xn--")
    assert homograph != "example.com"


def test_two_scripts_that_render_alike_are_different_identities():
    assert url_host("https://examрle.com/a") != url_host("https://example.com/a")


def test_an_ordinary_international_host_still_encodes_predictably():
    assert url_host("https://bücher.example/f") == "xn--bcher-kva.example"
