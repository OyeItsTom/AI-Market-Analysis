"""Phase 9 domain records: immutability, vocabulary and honest absence.

These tests are mostly about what the records refuse to represent. The one that
matters most is the separation of ``SOURCE_PUBLISHED`` from ``SOURCE_UPDATED``:
a feed that only says when it last *changed* an entry has not told us when it
was published, and no code path may quietly promote the one into the other.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.feeds.models import (
    MAX_EXCERPT,
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedError,
    FeedFormat,
    FeedItem,
    QueryMode,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
    TrustMode,
    require_aware,
    require_source_id,
    require_symbol,
    require_text,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def item(**overrides) -> FeedItem:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:uuid:1",
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
        trust_basis=TrustBasis.USER_CONFIGURED,
        title="A title",
        canonical_url="https://example.com/a",
        retrieved_at=T0,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        config_fingerprint="f" * 16,
        source_published_at=T0 - timedelta(hours=1),
        available_from=T0 - timedelta(hours=1),
    )
    fields.update(overrides)
    return FeedItem(**fields)


def link(**overrides) -> SymbolLink:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:uuid:1",
        symbol="AAPL",
        association=SymbolAssociation.CONFIGURED_SYMBOL,
        retrieved_at=T0,
        config_fingerprint="f" * 16,
    )
    fields.update(overrides)
    return SymbolLink(**fields)


# -- vocabulary ----------------------------------------------------------


def test_only_rss_and_atom_are_supported():
    assert {f.value for f in FeedFormat} == {"rss", "atom"}


def test_trust_classes_are_exactly_three():
    assert {t.value for t in DeclaredTrustClass} == {
        "official_feed", "publisher_feed", "community_feed"
    }


def test_every_trust_label_says_the_user_configured_it():
    """No label may read as something this system verified."""
    for trust in DeclaredTrustClass:
        label = trust.label.lower()
        assert any(word in label for word in ("configured", "unverified")), label
        for forbidden in ("verified", "trusted", "authentic", "confirmed"):
            if forbidden == "verified" and "unverified" in label:
                continue
            assert forbidden not in label, f"{trust.value} label claims {forbidden!r}"


def test_the_only_trust_basis_is_user_configuration():
    """V1 verifies nothing, so no other basis may be constructible."""
    assert {b.value for b in TrustBasis} == {"user_configured"}


def test_the_only_association_is_a_configured_symbol():
    """No text matcher exists, so no inferred association may be storable."""
    assert {a.value for a in SymbolAssociation} == {"configured_symbol"}


def test_availability_bases_are_exactly_four():
    assert {b.value for b in AvailabilityBasis} == {
        "source_published", "source_updated", "system_observed", "unknown"
    }


def test_an_update_time_is_marked_as_source_asserted_but_is_not_a_publication():
    assert AvailabilityBasis.SOURCE_UPDATED.is_source_asserted
    assert AvailabilityBasis.SOURCE_UPDATED is not AvailabilityBasis.SOURCE_PUBLISHED
    assert not AvailabilityBasis.SYSTEM_OBSERVED.is_source_asserted
    assert not AvailabilityBasis.UNKNOWN.is_source_asserted


def test_query_and_trust_modes_are_the_two_documented_pairs():
    assert {m.value for m in QueryMode} == {"source_time", "strict_causal"}
    assert {m.value for m in TrustMode} == {"source_asserted", "system_observed"}


# -- immutability --------------------------------------------------------


def test_feed_item_is_frozen():
    with pytest.raises(FrozenInstanceError):
        item().title = "changed"


def test_symbol_link_is_frozen():
    with pytest.raises(FrozenInstanceError):
        link().symbol = "MSFT"


# -- the timing separation that the whole phase rests on -----------------


def test_source_updated_requires_an_edit_time():
    with pytest.raises(FeedError):
        item(
            availability_basis=AvailabilityBasis.SOURCE_UPDATED,
            source_published_at=None,
            source_edited_at=None,
            available_from=T0,
        )


def test_source_updated_may_not_carry_a_publication_time():
    """An entry with a stated publication time is SOURCE_PUBLISHED, not UPDATED."""
    with pytest.raises(FeedError):
        item(
            availability_basis=AvailabilityBasis.SOURCE_UPDATED,
            source_published_at=T0 - timedelta(hours=2),
            source_edited_at=T0 - timedelta(hours=1),
            available_from=T0 - timedelta(hours=1),
        )


def test_source_published_requires_a_publication_time():
    with pytest.raises(FeedError):
        item(
            availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
            source_published_at=None,
            available_from=T0,
        )


def test_the_three_timing_facts_are_separate_fields():
    record = item(
        source_published_at=T0 - timedelta(days=2),
        source_edited_at=T0 - timedelta(days=1),
        available_from=T0 - timedelta(days=2),
    )
    assert record.source_published_at != record.retrieved_at
    assert record.source_edited_at != record.source_published_at
    assert record.available_from == record.source_published_at


def test_an_update_only_entry_keeps_publication_empty():
    record = item(
        availability_basis=AvailabilityBasis.SOURCE_UPDATED,
        source_published_at=None,
        source_edited_at=T0 - timedelta(hours=3),
        available_from=T0 - timedelta(hours=3),
    )
    assert record.source_published_at is None
    assert record.source_time == record.source_edited_at


def test_unknown_basis_may_not_carry_an_availability():
    with pytest.raises(FeedError):
        item(
            availability_basis=AvailabilityBasis.UNKNOWN,
            source_published_at=None,
            available_from=T0,
        )


def test_a_known_basis_requires_an_availability():
    with pytest.raises(FeedError):
        item(available_from=None)


def test_naive_timestamps_are_rejected():
    with pytest.raises(FeedError):
        item(retrieved_at=datetime(2026, 9, 6, 12, 0))


def test_timestamps_are_normalized_to_utc():
    other = timezone(timedelta(hours=5))
    record = item(retrieved_at=datetime(2026, 9, 6, 17, 0, tzinfo=other))
    assert record.retrieved_at == T0
    assert record.retrieved_at.tzinfo is UTC


# -- no interpretation ---------------------------------------------------


@pytest.mark.parametrize("record", [item(), link()])
def test_records_carry_no_sentiment_or_score(record):
    surface = {name for name in dir(record) if not name.startswith("_")}
    for forbidden in (
        "sentiment", "score", "relevance", "importance", "confidence",
        "probability", "impact", "rating", "direction", "bullish", "bearish",
        "credibility", "reliability", "quality",
    ):
        offenders = [name for name in surface if forbidden in name.lower()]
        assert not offenders, f"{type(record).__name__} exposes {offenders}"


def test_an_item_records_the_trust_class_it_was_stored_under():
    """Relabelling a feed later must not rewrite what old entries claimed."""
    record = item(declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED)
    assert record.declared_trust_class is DeclaredTrustClass.COMMUNITY_FEED
    assert record.trust_basis is TrustBasis.USER_CONFIGURED


# -- identity and association -------------------------------------------


def test_item_key_is_source_scoped():
    assert item().item_key == ("demo", "urn:uuid:1")


def test_link_key_includes_the_configuration_it_was_made_under():
    """Adding a symbol to a feed is a new observation, not a rewrite of old ones."""
    key = link().link_key
    assert key == ("demo", "urn:uuid:1", "AAPL", "f" * 16)
    assert link(config_fingerprint="0" * 16).link_key != key


def test_symbols_are_normalized_and_checked():
    assert require_symbol(" aapl ") == "AAPL"
    with pytest.raises(FeedError):
        require_symbol("AA PL")
    with pytest.raises(FeedError):
        require_symbol("")


def test_source_ids_are_slugs():
    assert require_source_id(" My-Feed_1 ") == "my-feed_1"
    for bad in ("", "a/b", "a b", "../etc", "a.b", "x" * 200):
        with pytest.raises(FeedError):
            require_source_id(bad)


# -- input hardening -----------------------------------------------------


def test_title_length_is_bounded():
    with pytest.raises(FeedError):
        item(title="x" * 5_000)


def test_control_characters_are_rejected_in_required_text():
    with pytest.raises(FeedError):
        item(title="ti\x00tle")


def test_empty_required_text_is_rejected():
    with pytest.raises(FeedError):
        item(title="   ")


def test_missing_publisher_becomes_explicit_not_silent():
    assert item(publisher=None).publisher == "unknown publisher"


def test_excerpt_is_bounded():
    with pytest.raises(FeedError):
        item(excerpt="x" * (MAX_EXCERPT + 1))


def test_revision_must_be_a_positive_int():
    with pytest.raises(FeedError):
        item(revision=0)
    with pytest.raises(FeedError):
        item(revision=True)


def test_require_aware_rejects_non_datetime():
    with pytest.raises(FeedError):
        require_aware("2026-09-06", "field")


def test_require_text_rejects_non_string():
    with pytest.raises(FeedError):
        require_text(123, "field", maximum=10)
