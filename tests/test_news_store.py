"""Phase 8 storage: append-only, loud about damage, honest about dedup.

The store is where an auditable record layer is won or lost. These tests pin the
three behaviours that make it auditable: nothing is overwritten, nothing broken
is silently discarded, and a document shared across symbols is stored once.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.news.models import (
    AvailabilityBasis,
    NewsItem,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
)
from src.news.source import ItemOutcome
from src.news.store import (
    ASSOCIATIONS_FILE,
    DOCUMENTS_FILE,
    SCHEMA_VERSION,
    CorruptionKind,
    NewsStore,
    NewsStoreCorruption,
    OnCorruption,
    StorageError,
    UnsupportedSchemaError,
    document_to_row,
    row_to_document,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path) -> NewsStore:
    return NewsStore(tmp_path)


def item(**overrides) -> NewsItem:
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
        content_hash="hash-one",
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
        content_hash="filing-hash",
    )
    fields.update(overrides)
    return OfficialFiling(**fields)


def link(**overrides) -> SymbolLink:
    fields = dict(
        source="yahoo", source_item_id="abc-123", symbol="AAPL",
        association=SymbolAssociation.QUERIED_SYMBOL, retrieved_at=T0,
    )
    fields.update(overrides)
    return SymbolLink(**fields)


# -- writing -------------------------------------------------------------


def test_a_new_document_is_accepted_and_stored(store):
    result = store.write_document(item())
    assert result.outcome is ItemOutcome.ACCEPTED
    stored, report = store.read_documents("yahoo")
    assert len(stored) == 1
    assert report.is_clean


def test_identical_content_is_a_duplicate_and_writes_nothing(store):
    store.write_document(item())
    before = store.documents_path("yahoo").read_bytes()

    result = store.write_document(item())
    assert result.outcome is ItemOutcome.DUPLICATE
    assert store.documents_path("yahoo").read_bytes() == before


def test_changed_content_is_appended_as_a_new_revision(store):
    store.write_document(item())
    result = store.write_document(item(headline="Corrected headline",
                                       content_hash="hash-two"))
    assert result.outcome is ItemOutcome.REVISION
    assert result.document.revision == 2

    stored, _ = store.read_documents("yahoo")
    assert len(stored) == 2, "the earlier revision must still be on disk"
    assert [d.revision for d in stored] == [1, 2]


def test_a_revision_never_overwrites_the_earlier_observation(store):
    """The original observation, timestamps and all, survives intact."""
    original_published = T0 - timedelta(hours=5)
    store.write_document(item(source_published_at=original_published,
                              available_from=original_published))
    store.write_document(
        item(headline="Restated", content_hash="hash-two",
             source_published_at=T0, available_from=T0, retrieved_at=T0 + timedelta(hours=1))
    )
    stored, _ = store.read_documents("yahoo")
    first, second = sorted(stored, key=lambda d: d.revision)
    assert first.source_published_at == original_published
    assert second.source_published_at == T0
    assert first.retrieved_at != second.retrieved_at


def test_latest_documents_returns_only_the_newest_revision(store):
    store.write_document(item())
    store.write_document(item(headline="Second", content_hash="hash-two"))
    latest, _ = store.latest_documents("yahoo")
    assert len(latest) == 1
    assert latest[0].revision == 2


def test_an_immutable_field_change_is_a_conflict_not_a_revision(store):
    """A reused identifier must not silently rewrite another document."""
    store.write_document(item())
    result = store.write_document(
        item(canonical_url="https://example.com/completely-different",
             content_hash="hash-two")
    )
    assert result.outcome is ItemOutcome.ID_REUSE_CONFLICT
    stored, _ = store.read_documents("yahoo")
    assert len(stored) == 1, "nothing may be written on a conflict"


def test_a_filing_conflict_is_detected_on_its_own_immutable_fields(store):
    store.write_document(filing())
    result = store.write_document(filing(form="10-K", content_hash="other"))
    assert result.outcome is ItemOutcome.ID_REUSE_CONFLICT


def test_a_filing_revision_is_allowed_on_mutable_fields(store):
    store.write_document(filing())
    result = store.write_document(filing(report_date="2026-06-30", content_hash="other"))
    assert result.outcome is ItemOutcome.REVISION


# -- associations and cross-symbol dedup ---------------------------------


def test_one_document_shared_across_symbols_is_stored_once(store):
    """Measured behaviour: Yahoo returns one article for several symbols."""
    store.write_document(item())
    for symbol in ("AAPL", "AMZN", "TSLA"):
        store.write_link(link(symbol=symbol))

    documents, _ = store.read_documents("yahoo")
    links, _ = store.read_links("yahoo")
    assert len(documents) == 1, "the document must not be duplicated per symbol"
    assert {l.symbol for l in links} == {"AAPL", "AMZN", "TSLA"}


def test_an_identical_association_is_not_appended_twice(store):
    assert store.write_link(link()) is True
    assert store.write_link(link()) is False
    links, _ = store.read_links("yahoo")
    assert len(links) == 1


def test_documents_and_associations_live_in_separate_files(store):
    store.write_document(item())
    store.write_link(link())
    assert store.documents_path("yahoo").name == DOCUMENTS_FILE
    assert store.associations_path("yahoo").name == ASSOCIATIONS_FILE
    assert store.documents_path("yahoo") != store.associations_path("yahoo")


def test_sources_are_stored_separately(store):
    store.write_document(item())
    store.write_document(filing())
    yahoo, _ = store.read_documents("yahoo")
    edgar, _ = store.read_documents("edgar")
    assert len(yahoo) == 1 and len(edgar) == 1


# -- as_of reconstruction -------------------------------------------------


def test_as_of_reconstructs_what_had_been_observed(store):
    later = T0 + timedelta(days=1)
    store.write_document(item())
    store.write_document(item(headline="Later revision", content_hash="hash-two",
                              retrieved_at=later))

    early, _ = store.latest_documents("yahoo", as_of=T0)
    assert early[0].revision == 1 and early[0].headline == "A headline"

    now, _ = store.latest_documents("yahoo", as_of=later)
    assert now[0].revision == 2


def test_as_of_before_any_observation_returns_nothing(store):
    store.write_document(item())
    early, _ = store.latest_documents("yahoo", as_of=T0 - timedelta(days=10))
    assert early == ()


# -- corruption ----------------------------------------------------------


def _corrupt(store: NewsStore, source: str, text: str) -> None:
    path = store.documents_path(source)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def test_a_truncated_final_line_raises_by_default(store):
    store.write_document(item())
    _corrupt(store, "yahoo", '{"schema_version": 1, "source": "yah')

    with pytest.raises(NewsStoreCorruption) as info:
        store.read_documents("yahoo")
    report = info.value.report
    assert len(report.corrupt_lines) == 1
    assert report.corrupt_lines[0].kind is CorruptionKind.CORRUPT_TAIL


def test_corruption_names_the_file_line_and_offset(store):
    store.write_document(item())
    _corrupt(store, "yahoo", "not json at all")
    with pytest.raises(NewsStoreCorruption) as info:
        store.read_documents("yahoo")
    line = info.value.report.corrupt_lines[0]
    assert line.line_number == 2
    assert line.byte_offset > 0
    assert DOCUMENTS_FILE in line.path


def test_an_interior_corrupt_line_is_classified_differently(store):
    """Damage before valid lines cannot be an interrupted append.

    The valid trailing line is appended directly, because the store refuses to
    write into a file it cannot fully read -- see the test below.
    """
    store.write_document(item())
    good = store.documents_path("yahoo").read_text().splitlines()[0]
    _corrupt(store, "yahoo", "broken\n" + good + "\n")

    with pytest.raises(NewsStoreCorruption) as info:
        store.read_documents("yahoo")
    kinds = [line.kind for line in info.value.report.corrupt_lines]
    assert CorruptionKind.CORRUPT_INTERIOR in kinds


def test_writing_into_a_corrupt_store_is_refused(store):
    """Appending to a file we cannot fully read could hide the damage."""
    store.write_document(item())
    _corrupt(store, "yahoo", "broken")
    with pytest.raises(NewsStoreCorruption):
        store.write_document(item(source_item_id="second", content_hash="h2"))


def test_report_mode_returns_the_valid_prefix_and_a_report(store):
    store.write_document(item())
    _corrupt(store, "yahoo", "broken line")

    documents, report = store.read_documents("yahoo", on_corruption=OnCorruption.REPORT)
    assert len(documents) == 1, "valid records before the damage remain readable"
    assert not report.is_clean
    assert "broken" not in documents[0].headline


def test_corruption_is_never_silently_discarded(store):
    """The default is strict: a caller must opt in to continuing."""
    store.write_document(item())
    _corrupt(store, "yahoo", "broken")
    with pytest.raises(NewsStoreCorruption):
        store.read_documents("yahoo")


def test_a_corrupt_read_does_not_repair_or_truncate_the_file(store):
    store.write_document(item())
    _corrupt(store, "yahoo", "broken bytes stay")
    before = store.documents_path("yahoo").read_bytes()

    store.read_documents("yahoo", on_corruption=OnCorruption.REPORT)
    assert store.documents_path("yahoo").read_bytes() == before


def test_invalid_utf8_is_detected_rather_than_decoded_loosely(store):
    store.write_document(item())
    with store.documents_path("yahoo").open("ab") as handle:
        handle.write(b"\xff\xfe not utf-8\n")
    with pytest.raises(NewsStoreCorruption):
        store.read_documents("yahoo")


# -- schema versioning ---------------------------------------------------


def test_a_future_schema_version_is_refused(store):
    store.write_document(item())
    path = store.documents_path("yahoo")
    row = json.loads(path.read_text().splitlines()[0])
    row["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(row) + "\n")

    with pytest.raises(UnsupportedSchemaError):
        store.read_documents("yahoo")


def test_every_written_line_declares_the_schema_version(store):
    store.write_document(item())
    store.write_link(link())
    for path in (store.documents_path("yahoo"), store.associations_path("yahoo")):
        for line in path.read_text().splitlines():
            assert json.loads(line)["schema_version"] == SCHEMA_VERSION


def test_round_trip_preserves_every_field(store):
    original = filing()
    restored = row_to_document(document_to_row(original))
    assert restored == original


def test_news_round_trip_preserves_every_field(store):
    original = item()
    assert row_to_document(document_to_row(original)) == original


# -- file format ---------------------------------------------------------


def test_records_are_one_per_line_and_utf8(store):
    store.write_document(item(headline="Café — naïve"))
    raw = store.documents_path("yahoo").read_bytes()
    assert raw.count(b"\n") == 1
    assert "Café — naïve" in raw.decode("utf-8")


def test_unicode_is_stored_readably_not_escaped(store):
    store.write_document(item(headline="Café"))
    assert "Café" in store.documents_path("yahoo").read_text(encoding="utf-8")


def test_reading_a_missing_file_is_empty_not_an_error(store):
    documents, report = store.read_documents("never-written")
    assert documents == () and report.is_clean


# -- path safety ---------------------------------------------------------


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "", "..", "."])
def test_unsafe_source_names_are_refused(store, bad):
    with pytest.raises(StorageError):
        store.documents_path(bad)


def test_a_revision_is_built_from_the_new_observation_not_the_old_one(store):
    """Regression guard: the appended revision must carry *this* fetch's values.

    Building it from the stored record instead would append a second copy of
    the old observation under a new revision number -- losing the change that
    prompted the revision in the first place.
    """
    store.write_document(item())
    later = T0 + timedelta(hours=3)
    store.write_document(
        item(headline="Corrected", content_hash="hash-two",
             source_published_at=later, available_from=later, retrieved_at=later)
    )
    stored, _ = store.read_documents("yahoo")
    newest = max(stored, key=lambda d: d.revision)
    assert newest.headline == "Corrected"
    assert newest.source_published_at == later
    assert newest.retrieved_at == later


def test_an_append_is_flushed_and_fsynced(store, monkeypatch):
    """Durability is a claim the architecture makes, so it is checked.

    Detection on the next read is the real safety net, but a write that never
    reaches the disk would lose records silently on a crash.
    """
    import os as os_module

    synced: list[int] = []
    real_fsync = os_module.fsync
    monkeypatch.setattr(
        "src.news.store.os.fsync",
        lambda fd: (synced.append(fd), real_fsync(fd))[1],
    )
    store.write_document(item())
    assert synced, "the append was not fsynced"


def test_a_serialized_record_never_contains_a_newline(store):
    """One record per line is what makes corruption locatable."""
    store.write_document(item(headline="line one line two", summary="a\tb"))
    raw = store.documents_path("yahoo").read_bytes()
    assert raw.count(b"\n") == 1
