"""Phase 9 persistence: append-only, honest about damage, never self-repairing.

Two properties matter more than the rest.

**History is appended, never overwritten.** A revision is a new line; the
earlier version stays exactly where it was. A store that edited in place could
not answer "what did this say when we first saw it?", which is the question a
research record exists to answer.

**Damage is reported, never repaired.** A corrupt line is classified and
surfaced. Nothing is deleted, truncated or rewritten to make a read succeed,
because silently discarding evidence is worse than an inconvenient error.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.feeds.models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedItem,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
)
from src.feeds.source import ItemOutcome
from src.feeds.store import (
    CorruptionKind,
    FeedStore,
    FeedStoreCorruption,
    OnCorruption,
    UnsupportedSchemaError,
    item_to_row,
    row_to_item,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def item(**overrides) -> FeedItem:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:1",
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
        trust_basis=TrustBasis.USER_CONFIGURED,
        title="A title",
        canonical_url="https://example.com/a",
        retrieved_at=T0,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        config_fingerprint="f" * 16,
        publisher="Example",
        excerpt="An excerpt.",
        source_published_at=T0 - timedelta(hours=1),
        available_from=T0 - timedelta(hours=1),
        content_hash="a" * 32,
    )
    fields.update(overrides)
    return FeedItem(**fields)


def link(**overrides) -> SymbolLink:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:1",
        symbol="AAPL",
        association=SymbolAssociation.CONFIGURED_SYMBOL,
        retrieved_at=T0,
        config_fingerprint="f" * 16,
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
    )
    fields.update(overrides)
    return SymbolLink(**fields)


@pytest.fixture
def store(tmp_path):
    return FeedStore(tmp_path)


# -- round trip ----------------------------------------------------------


def test_an_item_survives_a_round_trip_unchanged(store):
    original = item()
    store.write_item(original)
    stored, _ = store.read_items("demo")
    assert stored == (original,)


def test_every_field_is_persisted(store):
    """A field silently dropped by the row encoder would be a quiet data loss."""
    from dataclasses import fields as dataclass_fields

    row = item_to_row(item())
    for field in dataclass_fields(FeedItem):
        assert field.name in row, f"{field.name} is not persisted"


def test_a_row_round_trips_through_json(store):
    original = item()
    assert row_to_item(json.loads(json.dumps(item_to_row(original)))) == original


def test_a_link_survives_a_round_trip(store):
    store.write_link(link())
    stored, _ = store.read_links("demo")
    assert stored == (link(),)


def test_reading_an_absent_store_is_empty_not_an_error(store):
    assert store.read_items("never-seen")[0] == ()
    assert store.read_links("never-seen")[0] == ()


# -- classification ------------------------------------------------------


def test_a_new_item_is_accepted(store):
    assert store.write_item(item()).outcome is ItemOutcome.ACCEPTED


def test_the_same_item_again_is_a_duplicate(store):
    store.write_item(item())
    assert store.write_item(item()).outcome is ItemOutcome.DUPLICATE


def test_a_duplicate_appends_nothing(store):
    store.write_item(item())
    store.write_item(item())
    assert len(store.documents_path("demo").read_text().splitlines()) == 1


def test_changed_content_under_the_same_identity_is_a_revision(store):
    store.write_item(item())
    result = store.write_item(item(title="A corrected title", content_hash="b" * 32))
    assert result.outcome is ItemOutcome.REVISION
    assert result.item.revision == 2


def test_a_revision_keeps_the_earlier_version_on_disk(store):
    """The point of append-only: the first version is still answerable for."""
    store.write_item(item())
    store.write_item(item(title="Corrected", content_hash="b" * 32))
    all_items, _ = store.read_items("demo")
    assert [record.title for record in all_items] == ["A title", "Corrected"]
    latest, _ = store.latest_items("demo")
    assert [record.title for record in latest] == ["Corrected"]


def test_revisions_keep_climbing(store):
    store.write_item(item())
    for n, digest in enumerate("bcd", start=2):
        result = store.write_item(item(title=f"v{n}", content_hash=digest * 32))
        assert result.item.revision == n


def test_a_revision_records_this_observations_timestamps_not_the_previous_ones(store):
    """A publisher silently restating a time must leave both values on record."""
    store.write_item(item())
    restated = T0 - timedelta(hours=5)
    store.write_item(
        item(source_published_at=restated, available_from=restated, content_hash="b" * 32)
    )
    all_items, _ = store.read_items("demo")
    assert all_items[0].source_published_at == T0 - timedelta(hours=1)
    assert all_items[1].source_published_at == restated


def test_the_same_identity_on_a_different_host_is_a_conflict_not_a_revision(store):
    """The id now names something else; appending would rewrite another history."""
    store.write_item(item())
    result = store.write_item(
        item(canonical_url="https://attacker.example/a", content_hash="b" * 32)
    )
    assert result.outcome is ItemOutcome.ID_REUSE_CONFLICT
    assert len(store.documents_path("demo").read_text().splitlines()) == 1


def test_a_path_change_on_the_same_host_is_an_ordinary_revision(store):
    """Publishers restructure paths while editing; that is not id reuse."""
    store.write_item(item())
    result = store.write_item(
        item(canonical_url="https://example.com/a-renamed", content_hash="b" * 32)
    )
    assert result.outcome is ItemOutcome.REVISION


def test_classification_survives_a_restart(store, tmp_path):
    """Decided from stored bytes, not from an in-memory set of seen ids."""
    store.write_item(item())
    assert FeedStore(tmp_path).write_item(item()).outcome is ItemOutcome.DUPLICATE


# -- associations --------------------------------------------------------


def test_the_same_association_twice_is_written_once(store):
    assert store.write_link(link()) is True
    assert store.write_link(link()) is False


def test_a_new_symbol_is_a_new_association(store):
    store.write_link(link())
    assert store.write_link(link(symbol="MSFT")) is True


def test_the_same_symbol_under_a_new_configuration_is_a_new_observation(store):
    """Changing trust or symbols changes what an association means."""
    store.write_link(link())
    assert store.write_link(link(config_fingerprint="0" * 16)) is True


def test_one_item_can_carry_many_symbols(store):
    store.write_item(item())
    for symbol in ("AAPL", "MSFT", "GOOG"):
        store.write_link(link(symbol=symbol))
    stored, _ = store.read_links("demo")
    assert {record.symbol for record in stored} == {"AAPL", "MSFT", "GOOG"}
    # One document, many links: the item is stored once.
    assert len(store.read_items("demo")[0]) == 1


# -- corruption ----------------------------------------------------------


def test_a_corrupt_final_line_is_classified_as_a_tail(store):
    """A crash mid-append truncates the last line; that is a recognised shape."""
    store.write_item(item())
    with store.documents_path("demo").open("a") as handle:
        handle.write('{"partial": ')
    report = store.health("demo")
    assert not report.is_clean
    assert report.corrupt_lines[0].kind is CorruptionKind.CORRUPT_TAIL


def test_a_corrupt_interior_line_is_classified_separately(store):
    """Damage that is not a truncated tail means something else went wrong."""
    store.write_item(item())
    store.write_item(item(feed_item_id="urn:2", content_hash="b" * 32))
    path = store.documents_path("demo")
    lines = path.read_text().splitlines()
    path.write_text("\n".join(["{broken", *lines]) + "\n")
    report = store.health("demo")
    assert report.corrupt_lines[0].kind is CorruptionKind.CORRUPT_INTERIOR


def test_reading_raises_by_default_on_corruption(store):
    store.write_item(item())
    with store.documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    with pytest.raises(FeedStoreCorruption):
        store.read_items("demo")


def test_reading_can_report_instead_of_raising(store):
    store.write_item(item())
    with store.documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    items, report = store.read_items("demo", on_corruption=OnCorruption.REPORT)
    assert len(items) == 1
    assert not report.is_clean


def test_nothing_is_repaired_or_deleted_when_damage_is_found(store):
    """The bytes on disk are exactly what they were before the read."""
    store.write_item(item())
    path = store.documents_path("demo")
    with path.open("a") as handle:
        handle.write("{broken\n")
    before = path.read_bytes()
    store.read_items("demo", on_corruption=OnCorruption.REPORT)
    store.health("demo")
    assert path.read_bytes() == before


def test_a_future_schema_version_is_refused_rather_than_guessed_at(store):
    store.write_item(item())
    path = store.documents_path("demo")
    row = json.loads(path.read_text().splitlines()[0])
    row["schema_version"] = 999
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises((UnsupportedSchemaError, FeedStoreCorruption)):
        store.read_items("demo")


def test_a_report_describes_what_was_found(store):
    store.write_item(item())
    with store.documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    described = store.health("demo").describe()
    assert "demo" in described


def test_a_clean_store_reports_clean(store):
    store.write_item(item())
    store.write_link(link())
    assert store.health("demo").is_clean


# -- isolation -----------------------------------------------------------


def test_sources_are_stored_separately(store):
    store.write_item(item())
    store.write_item(item(source_id="other"))
    assert len(store.read_items("demo")[0]) == 1
    assert len(store.read_items("other")[0]) == 1
    assert store.documents_path("demo") != store.documents_path("other")


def test_one_damaged_source_does_not_hide_a_healthy_one(store):
    store.write_item(item())
    store.write_item(item(source_id="other"))
    with store.documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    assert store.health("other").is_clean
    assert not store.health("demo").is_clean


# -- as-of replay --------------------------------------------------------


def test_latest_items_can_replay_what_we_had_seen_by_a_point_in_time(store):
    store.write_item(item())
    later = item(feed_item_id="urn:2", retrieved_at=T0 + timedelta(days=1), content_hash="b" * 32)
    store.write_item(later)
    seen_before, _ = store.latest_items("demo", as_of=T0)
    assert {record.feed_item_id for record in seen_before} == {"urn:1"}


def test_as_of_replays_our_own_observation_not_the_publishers_claim(store):
    """A backfilled entry was not knowable to this system before we fetched it."""
    backfilled = item(
        feed_item_id="urn:old",
        retrieved_at=T0 + timedelta(days=1),
        source_published_at=T0 - timedelta(days=365),
        available_from=T0 - timedelta(days=365),
        content_hash="c" * 32,
    )
    store.write_item(backfilled)
    assert store.latest_items("demo", as_of=T0)[0] == ()


# -- durability is structural: assert the calls, not just the outcome ----


def test_every_append_flushes_and_fsyncs():
    """A missing fsync cannot be observed from a passing test, only from a crash.

    So it is asserted structurally: the append path must flush the buffer and
    fsync the descriptor before returning, or a power loss silently discards
    records the checkpoint has already been advanced past.
    """
    import ast
    import pathlib

    source = pathlib.Path("src/feeds/store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    append = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_append"
    )
    called = {
        node.func.attr
        for node in ast.walk(append)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "flush" in called, "_append does not flush before fsync"
    assert "fsync" in called, "_append does not fsync; a crash would lose records"


def test_the_checkpoint_save_path_also_fsyncs():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/feeds/checkpoint.py").read_text(encoding="utf-8"))
    save = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "save"
    )
    called = {
        node.func.attr
        for node in ast.walk(save)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"flush", "fsync", "replace"} <= called, (
        f"the checkpoint save path is missing durability calls: {called}"
    )
