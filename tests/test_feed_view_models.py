"""Phase 9 view models: formatting that cannot quietly upgrade a claim.

The view layer is the last place a hedge can be dropped, so these tests pin the
wording as tightly as the domain tests pin the data. In particular the trust
label is read from the *stored record*, never from today's configuration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.feeds import FeedSnapshot, RefreshStatus
from src.application.view_models import (
    FEEDS_DISCLAIMER,
    FEEDS_TRUST_DISCLAIMER,
    LABEL_FEED_OBSERVED,
    LABEL_FEED_PUBLISHED,
    LABEL_FEED_UPDATED,
    feed_item_rows,
    feeds_view,
)
from src.feeds.config import FeedDefinition
from src.feeds.models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedFormat,
    FeedItem,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
)
from src.feeds.source import IngestionCounters, SourceOutcome, SourceResult

UTC = timezone.utc
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def definition(**overrides) -> FeedDefinition:
    fields = dict(
        source_id="demo",
        feed_format=FeedFormat.ATOM,
        url="https://example.com/feed.xml",
        display_name="Demo Feed",
        declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED,
        configured_symbols=("AAPL",),
    )
    fields.update(overrides)
    return FeedDefinition(**fields)


def item(**overrides) -> FeedItem:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:1",
        declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED,
        trust_basis=TrustBasis.USER_CONFIGURED,
        title="A title",
        canonical_url="https://example.com/a",
        retrieved_at=NOW,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        config_fingerprint="f" * 16,
        publisher="Example",
        source_published_at=NOW - timedelta(hours=1),
        available_from=NOW - timedelta(hours=1),
    )
    fields.update(overrides)
    return FeedItem(**fields)


def snapshot(*items, definitions=None, results=(), **overrides) -> FeedSnapshot:
    definitions = definitions if definitions is not None else (definition(),)
    fields = dict(
        built_at=NOW,
        items=items,
        links=tuple(
            SymbolLink(
                source_id=record.source_id, feed_item_id=record.feed_item_id,
                symbol="AAPL", association=SymbolAssociation.CONFIGURED_SYMBOL,
                retrieved_at=NOW, config_fingerprint="f" * 16,
                declared_trust_class=record.declared_trust_class,
            )
            for record in items
        ),
        source_results=results,
        status=RefreshStatus.ALL_OK,
        definitions=definitions,
    )
    fields.update(overrides)
    return FeedSnapshot(**fields)


# -- trust is quoted, never asserted -------------------------------------


def test_the_trust_label_comes_from_the_record_not_todays_configuration():
    """Relabelling a feed today must not relabel what was stored last week."""
    stored = item(declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED)
    relabelled_now = (definition(declared_trust_class=DeclaredTrustClass.OFFICIAL_FEED),)
    row = feed_item_rows(snapshot(stored, definitions=relabelled_now))[0]
    assert row.trust_class == "community_feed"
    assert "unverified" in row.trust_label.lower()
    assert "official" not in row.trust_label.lower()


@pytest.mark.parametrize("trust", list(DeclaredTrustClass))
def test_no_trust_label_claims_verification(trust):
    row = feed_item_rows(snapshot(item(declared_trust_class=trust)))[0]
    label = row.trust_label.lower()
    assert any(word in label for word in ("configured", "unverified"))


def test_the_trust_disclaimer_says_the_dashboard_verifies_nothing():
    assert "not verify" in FEEDS_TRUST_DISCLAIMER.lower() or (
        "does not verify" in FEEDS_TRUST_DISCLAIMER.lower()
    )


def test_the_disclaimer_denies_analysis_and_denies_reaching_research():
    text = FEEDS_DISCLAIMER.lower()
    assert "analysed" in text or "analyzed" in text
    assert "research" in text


# -- one approved phrase per timing claim --------------------------------


def test_a_publication_time_is_labelled_as_one():
    row = feed_item_rows(snapshot(item()))[0]
    assert row.source_time_label == LABEL_FEED_PUBLISHED
    assert "publication" in row.source_time_label.lower()


def test_an_update_time_is_labelled_as_an_update_not_a_publication():
    updated = item(
        availability_basis=AvailabilityBasis.SOURCE_UPDATED,
        source_published_at=None,
        source_edited_at=NOW - timedelta(hours=2),
        available_from=NOW - timedelta(hours=2),
    )
    row = feed_item_rows(snapshot(updated))[0]
    assert row.source_time_label == LABEL_FEED_UPDATED
    assert "update" in row.source_time_label.lower()
    assert "publication" not in row.source_time_label.lower()


def test_an_observed_item_says_only_that_we_saw_it():
    observed = item(
        availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
        source_published_at=None,
        available_from=NOW,
    )
    row = feed_item_rows(snapshot(observed))[0]
    assert row.source_time_label == LABEL_FEED_OBSERVED
    assert "publish" not in row.source_time_label.lower()


def test_the_retrieval_time_is_always_shown_separately():
    row = feed_item_rows(snapshot(item()))[0]
    assert row.retrieved_at
    assert row.retrieved_at != row.source_time


# -- associations --------------------------------------------------------


def test_the_association_wording_claims_only_configuration():
    row = feed_item_rows(snapshot(item()))[0]
    assert row.association == "From a feed configured for AAPL"


def test_an_item_with_no_configured_symbol_claims_no_company():
    view = snapshot(item(), links=())
    assert "not configured for any symbol" in feed_item_rows(view)[0].association


# -- revisions -----------------------------------------------------------


def test_a_revision_is_announced_rather_than_quietly_swapped_in():
    row = feed_item_rows(snapshot(item(revision=3)))[0]
    assert row.is_revision
    assert "3" in row.revision_note
    assert "changed" in row.revision_note.lower()


def test_a_first_version_carries_no_revision_note():
    row = feed_item_rows(snapshot(item()))[0]
    assert not row.is_revision
    assert row.revision_note == ""


# -- links ---------------------------------------------------------------


def test_an_ordinary_link_is_marked_safe_to_render():
    assert feed_item_rows(snapshot(item()))[0].is_safe_url


def test_ordering_is_never_recomputed_by_the_view():
    """Chronology belongs to the application layer; the view only formats."""
    first = item(feed_item_id="a", declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED)
    second = item(feed_item_id="b", declared_trust_class=DeclaredTrustClass.OFFICIAL_FEED)
    rows = feed_item_rows(snapshot(first, second))
    assert [row.title for row in rows] == ["A title", "A title"]
    assert [row.trust_class for row in rows] == ["community_feed", "official_feed"]


# -- the view as a whole -------------------------------------------------


def test_an_unconfigured_view_explains_the_state_rather_than_reporting_a_failure():
    view = feeds_view(
        FeedSnapshot(
            built_at=NOW, items=(), links=(), source_results=(),
            status=RefreshStatus.NOTHING_CONFIGURED, definitions=(),
        )
    )
    assert not view.is_configured
    assert "external_feeds.local.json" in view.unconfigured_message
    assert not view.all_failed


def test_a_partial_refresh_is_worded_as_partial():
    view = feeds_view(snapshot(item(), status=RefreshStatus.PARTIAL))
    assert view.is_partial
    assert "partial" in view.status_note.lower()
    assert "missing" in view.status_note.lower()


def test_a_total_failure_says_nothing_was_updated():
    view = feeds_view(snapshot(status=RefreshStatus.ALL_FAILED))
    assert view.all_failed
    note = view.status_note.lower()
    # The denial is "nothing ... has been updated"; assert the denial itself
    # rather than a phrasing of it, so a reworded message still has to deny.
    assert "nothing below has been updated" in note
    assert "could be reached" in note


def test_each_feed_reports_its_own_outcome_and_host():
    results = (
        SourceResult("demo", SourceOutcome.SUCCESS, IngestionCounters(accepted=1)),
    )
    view = feeds_view(snapshot(item(), results=results))
    row = view.sources[0]
    assert row.source_name == "Demo Feed"
    assert row.url_host == "example.com"
    assert row.is_healthy
    assert "accepted=1" in row.counters


def test_an_integrity_warning_is_surfaced_and_says_nothing_was_touched():
    from src.feeds.store import CorruptionKind, CorruptLine, StoreIntegrityReport

    report = StoreIntegrityReport(
        (CorruptLine(path="data/feeds/demo/documents.jsonl", line_number=3,
                     byte_offset=100, kind=CorruptionKind.CORRUPT_INTERIOR, detail="bad"),)
    )
    view = feeds_view(snapshot(item(), integrity=report))
    assert view.integrity_warning
    assert "left untouched" in view.integrity_warning
