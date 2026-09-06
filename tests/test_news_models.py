"""Phase 8 domain records: immutability, vocabulary and honest absence.

These tests are mostly about what the records refuse to represent. A field that
does not exist cannot be filled in with a guess, which is the main defence this
layer has against turning "a source published this" into "this means something".
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.news.models import (
    AvailabilityBasis,
    EventType,
    NewsError,
    NewsItem,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
    require_aware,
    require_symbol,
    require_text,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def news(**overrides) -> NewsItem:
    fields = dict(
        source="yahoo",
        source_item_id="abc-123",
        source_class=SourceClass.SECONDARY_NEWS,
        publisher="Reuters",
        headline="A headline",
        canonical_url="https://example.com/a",
        retrieved_at=T0,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        source_published_at=T0 - timedelta(hours=1),
        available_from=T0 - timedelta(hours=1),
    )
    fields.update(overrides)
    return NewsItem(**fields)


def filing(**overrides) -> OfficialFiling:
    fields = dict(
        source="edgar",
        source_item_id="0000320193-26-000001",
        source_class=SourceClass.OFFICIAL_FILING,
        cik="0000320193",
        form="8-K",
        headline="8-K filed by AAPL",
        canonical_url="https://www.sec.gov/Archives/edgar/data/320193/x/",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/320193/x/d.htm",
        retrieved_at=T0,
        availability_basis=AvailabilityBasis.SOURCE_EVENT,
        source_event_time=T0 - timedelta(days=1),
        available_from=T0 - timedelta(days=1),
        filing_date="2026-09-04",
        items=("5.02",),
    )
    fields.update(overrides)
    return OfficialFiling(**fields)


# -- vocabulary ----------------------------------------------------------


def test_source_classes_are_exactly_official_and_secondary():
    assert {c.value for c in SourceClass} == {"official_filing", "secondary_news"}


def test_association_kinds_are_exactly_three():
    assert {a.value for a in SymbolAssociation} == {
        "verified_source", "queried_symbol", "inferred"
    }


def test_availability_bases_are_exactly_four():
    assert {b.value for b in AvailabilityBasis} == {
        "source_event", "source_published", "system_observed", "unknown"
    }


def test_event_types_carry_no_interpretation():
    assert {e.value for e in EventType} == {"filing", "unknown"}


def test_only_source_asserted_bases_report_as_such():
    assert AvailabilityBasis.SOURCE_EVENT.is_source_asserted
    assert AvailabilityBasis.SOURCE_PUBLISHED.is_source_asserted
    assert not AvailabilityBasis.SYSTEM_OBSERVED.is_source_asserted
    assert not AvailabilityBasis.UNKNOWN.is_source_asserted


# -- immutability --------------------------------------------------------


def test_news_item_is_frozen():
    item = news()
    with pytest.raises(FrozenInstanceError):
        item.headline = "changed"


def test_filing_is_frozen():
    record = filing()
    with pytest.raises(FrozenInstanceError):
        record.form = "10-K"


def test_filing_items_are_an_immutable_tuple():
    record = filing()
    assert isinstance(record.items, tuple)
    with pytest.raises(TypeError):
        record.items[0] = "9.99"


def test_symbol_link_is_frozen():
    link = SymbolLink(
        source="yahoo", source_item_id="abc", symbol="AAPL",
        association=SymbolAssociation.QUERIED_SYMBOL, retrieved_at=T0,
    )
    with pytest.raises(FrozenInstanceError):
        link.symbol = "MSFT"


# -- timestamps ----------------------------------------------------------


def test_naive_timestamps_are_rejected():
    with pytest.raises(NewsError):
        news(retrieved_at=datetime(2026, 9, 5, 12, 0))


def test_timestamps_are_normalized_to_utc():
    other = timezone(timedelta(hours=5))
    item = news(retrieved_at=datetime(2026, 9, 5, 17, 0, tzinfo=other))
    assert item.retrieved_at.tzinfo is UTC
    assert item.retrieved_at == datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def test_the_three_timing_facts_are_separate_fields():
    """The whole point of the model: no field doubles as another."""
    record = filing()
    assert record.source_event_time != record.retrieved_at
    assert record.available_from == record.source_event_time
    assert record.available_from != record.retrieved_at

    item = news()
    assert item.source_published_at != item.retrieved_at
    assert item.available_from == item.source_published_at


def test_retrieved_at_is_never_the_source_time():
    item = news(
        source_published_at=None,
        available_from=T0,
        availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
    )
    assert item.source_time is None
    assert item.retrieved_at == T0


def test_unknown_basis_may_not_carry_an_availability():
    with pytest.raises(NewsError):
        news(availability_basis=AvailabilityBasis.UNKNOWN, available_from=T0)


def test_a_known_basis_requires_an_availability():
    with pytest.raises(NewsError):
        news(availability_basis=AvailabilityBasis.SOURCE_PUBLISHED, available_from=None)


# -- semantic separation -------------------------------------------------


def test_a_filing_must_be_official():
    with pytest.raises(NewsError):
        filing(source_class=SourceClass.SECONDARY_NEWS)


def test_news_and_filings_are_different_types():
    assert type(news()) is not type(filing())
    assert not isinstance(news(), OfficialFiling)


def test_filings_expose_official_codes_not_a_written_summary():
    record = filing()
    assert "8-K" in record.summary
    assert "5.02" in record.summary


def test_a_filing_names_the_regulator_as_publisher():
    assert "Securities and Exchange Commission" in filing().publisher


# -- no interpretation ---------------------------------------------------


@pytest.mark.parametrize("record", [news(), filing()])
def test_records_carry_no_sentiment_or_score(record):
    surface = {name for name in dir(record) if not name.startswith("_")}
    for forbidden in (
        "sentiment", "score", "relevance", "importance", "confidence",
        "probability", "impact", "rating", "direction", "bullish", "bearish",
    ):
        offenders = [name for name in surface if forbidden in name.lower()]
        assert not offenders, f"{type(record).__name__} exposes {offenders}"


def test_yahoo_records_have_no_event_classification():
    assert news().event_type is EventType.UNKNOWN


# -- identity and association -------------------------------------------


def test_item_key_is_source_scoped():
    assert news().item_key == ("yahoo", "abc-123")
    assert filing().item_key == ("edgar", "0000320193-26-000001")


def test_inferred_association_cannot_be_constructed():
    """No matcher exists in V1, so a guessed link must not be storable."""
    with pytest.raises(NewsError):
        SymbolLink(
            source="yahoo", source_item_id="abc", symbol="AAPL",
            association=SymbolAssociation.INFERRED, retrieved_at=T0,
        )


def test_link_defaults_queried_symbol_to_the_symbol():
    link = SymbolLink(
        source="yahoo", source_item_id="abc", symbol="aapl",
        association=SymbolAssociation.QUERIED_SYMBOL, retrieved_at=T0,
    )
    assert link.symbol == "AAPL"
    assert link.queried_symbol == "AAPL"


# -- input hardening -----------------------------------------------------


def test_headline_length_is_bounded():
    with pytest.raises(NewsError):
        news(headline="x" * 5_000)


def test_control_characters_are_rejected_in_text():
    with pytest.raises(NewsError):
        news(headline="head\x00line")


def test_empty_required_text_is_rejected():
    with pytest.raises(NewsError):
        news(headline="   ")


def test_missing_publisher_becomes_explicit_not_silent():
    assert news(publisher=None).publisher == "unknown publisher"


def test_symbols_are_normalized_and_checked():
    assert require_symbol(" aapl ") == "AAPL"
    with pytest.raises(NewsError):
        require_symbol("AA PL")
    with pytest.raises(NewsError):
        require_symbol("")


def test_revision_must_be_a_positive_int():
    with pytest.raises(NewsError):
        news(revision=0)
    with pytest.raises(NewsError):
        news(revision=True)


def test_require_aware_rejects_non_datetime():
    with pytest.raises(NewsError):
        require_aware("2026-09-05", "field")


def test_require_text_rejects_non_string():
    with pytest.raises(NewsError):
        require_text(123, "field", maximum=10)
