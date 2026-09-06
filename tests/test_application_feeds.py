"""Phase 9 orchestration: isolation, ordering, causality and crash ordering.

The rule with the sharpest teeth is the ordering one. Records are appended and
fsynced before the checkpoint moves, so a crash between the two costs a
redundant fetch rather than losing entries forever behind a ``304``. The tests
below pin that ordering by observation rather than by reading the source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.feeds import (
    FeedService,
    FeedSnapshot,
    RefreshStatus,
    build_service,
    filter_items,
    order_items,
)
from src.feeds.checkpoint import CheckpointStore
from src.feeds.config import FeedConfiguration, FeedDefinition
from src.feeds.models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedFormat,
    FeedItem,
    QueryMode,
    TrustBasis,
    TrustMode,
)
from src.feeds.source import SourceOutcome
from src.feeds.store import FeedStore
from src.feeds.transport import (
    NotModified,
    PayloadTooLarge,
    RateLimited,
    RedirectRefused,
    TransportError,
)
from src.feeds.validation import UnsafeDestination

UTC = timezone.utc
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def atom(*entries: str) -> bytes:
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>T</title>{''.join(entries)}</feed>"
    ).encode()


def entry(n: int, title: str = "T", updated: str = "2026-09-05T10:00:00Z") -> str:
    return (
        f"<entry><id>urn:{n}</id><title>{title}</title>"
        f'<link rel="alternate" href="https://example.com/{n}"/>'
        f"<updated>{updated}</updated></entry>"
    )


ONE = atom(entry(1))


def definition(**overrides) -> FeedDefinition:
    fields = dict(
        source_id="demo",
        feed_format=FeedFormat.ATOM,
        url="https://example.com/feed.xml",
        display_name="Demo",
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
        configured_symbols=("AAPL",),
    )
    fields.update(overrides)
    return FeedDefinition(**fields)


class FakeFetch:
    """Records what was requested and replays scripted answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, *, etag=None, last_modified=None):
        self.calls.append({"url": url, "etag": etag, "last_modified": last_modified})
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Fetched:
    def __init__(self, body, etag=None, last_modified=None):
        self.body = body
        self.etag = etag
        self.last_modified = last_modified
        self.peer_address = "93.184.216.34"


def service(tmp_path, *definitions, fetch=None, now=NOW):
    return FeedService(
        FeedConfiguration(definitions or (definition(),)),
        FeedStore(tmp_path),
        CheckpointStore(tmp_path),
        fetch=fetch or FakeFetch(Fetched(ONE, etag='W/"1"')),
        now=lambda: now,
    )


def item(**overrides) -> FeedItem:
    fields = dict(
        source_id="demo",
        feed_item_id="urn:1",
        declared_trust_class=DeclaredTrustClass.PUBLISHER_FEED,
        trust_basis=TrustBasis.USER_CONFIGURED,
        title="A title",
        canonical_url="https://example.com/a",
        retrieved_at=NOW,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        config_fingerprint="f" * 16,
        source_published_at=NOW - timedelta(hours=1),
        available_from=NOW - timedelta(hours=1),
    )
    fields.update(overrides)
    return FeedItem(**fields)


# -- the happy path ------------------------------------------------------


def test_a_refresh_stores_entries_and_reports_success(tmp_path):
    snapshot = service(tmp_path).refresh()
    assert snapshot.status is RefreshStatus.ALL_OK
    assert len(snapshot.items) == 1
    assert snapshot.counters.accepted == 1


def test_an_association_is_written_for_each_configured_symbol(tmp_path):
    snapshot = service(tmp_path, definition(configured_symbols=("AAPL", "MSFT"))).refresh()
    assert snapshot.counters.associations == 2
    assert snapshot.symbols_for(snapshot.items[0]) == ("AAPL", "MSFT")


def test_a_second_identical_refresh_stores_nothing_new(tmp_path):
    svc = service(tmp_path)
    svc.refresh()
    second = svc.refresh()
    assert second.counters.duplicate == 1
    assert second.counters.accepted == 0


def test_a_changed_entry_becomes_a_revision(tmp_path):
    fetch = FakeFetch(
        Fetched(ONE, etag='W/"1"'),
        Fetched(atom(entry(1, title="Corrected")), etag='W/"2"'),
    )
    svc = service(tmp_path, fetch=fetch)
    svc.refresh()
    second = svc.refresh()
    assert second.counters.revision == 1
    assert second.items[0].title == "Corrected"
    assert second.items[0].revision == 2


# -- isolation -----------------------------------------------------------


def test_one_failing_feed_does_not_discard_anothers_records(tmp_path):
    def fetch(url, *, etag=None, last_modified=None):
        if "broken" in url:
            raise TransportError("unreachable")
        return Fetched(ONE, etag='W/"1"')

    snapshot = service(
        tmp_path,
        definition(),
        definition(source_id="broken", url="https://broken.example.com/f.xml"),
        fetch=fetch,
    ).refresh()
    assert snapshot.status is RefreshStatus.PARTIAL
    assert len(snapshot.items) == 1
    outcomes = {r.source_id: r.outcome for r in snapshot.source_results}
    assert outcomes["demo"] is SourceOutcome.SUCCESS
    assert outcomes["broken"] is SourceOutcome.FAILED


def test_a_partial_refresh_is_never_reported_as_success(tmp_path):
    """Telling someone their feeds are current while one is missing is a lie."""
    def fetch(url, *, etag=None, last_modified=None):
        if "broken" in url:
            raise TransportError("unreachable")
        return Fetched(ONE)

    snapshot = service(
        tmp_path, definition(), definition(source_id="broken", url="https://broken.example.com/f.xml"),
        fetch=fetch,
    ).refresh()
    assert snapshot.status is not RefreshStatus.ALL_OK


def test_every_feed_failing_is_reported_as_all_failed(tmp_path):
    snapshot = service(tmp_path, fetch=FakeFetch(TransportError("down"))).refresh()
    assert snapshot.status is RefreshStatus.ALL_FAILED


def test_an_unexpected_exception_in_one_feed_is_contained(tmp_path):
    def fetch(url, *, etag=None, last_modified=None):
        raise RuntimeError("something nobody predicted")

    snapshot = service(tmp_path, fetch=fetch).refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.FAILED
    assert "RuntimeError" in snapshot.source_results[0].detail


@pytest.mark.parametrize(
    "error,expected",
    [
        (UnsafeDestination("private"), SourceOutcome.UNSAFE_ENDPOINT),
        (PayloadTooLarge("too big"), SourceOutcome.PAYLOAD_TOO_LARGE),
        (RateLimited("slow down"), SourceOutcome.RATE_LIMITED),
        (RedirectRefused(302, "https://elsewhere.test/"), SourceOutcome.FAILED),
        (TransportError("nope"), SourceOutcome.FAILED),
    ],
)
def test_each_transport_refusal_maps_to_its_own_outcome(tmp_path, error, expected):
    snapshot = service(tmp_path, fetch=FakeFetch(error)).refresh()
    assert snapshot.source_results[0].outcome is expected


def test_a_document_that_is_not_a_feed_is_reported_as_an_unsupported_format(tmp_path):
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(b"<html>nope</html>"))).refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.UNSUPPORTED_SOURCE_FORMAT


def test_a_feed_contradicting_its_configured_type_is_refused(tmp_path):
    rss = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(rss))).refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.UNSUPPORTED_SOURCE_FORMAT


def test_a_disabled_feed_is_reported_but_is_not_a_failure(tmp_path):
    snapshot = service(tmp_path, definition(), definition(source_id="off", enabled=False)).refresh()
    outcomes = {r.source_id: r.outcome for r in snapshot.source_results}
    assert outcomes["off"] is SourceOutcome.UNCONFIGURED
    assert snapshot.status is RefreshStatus.ALL_OK


def test_a_disabled_feed_is_never_fetched(tmp_path):
    fetch = FakeFetch(Fetched(ONE))
    service(tmp_path, definition(source_id="off", enabled=False), fetch=fetch).refresh()
    assert fetch.calls == []


def test_nothing_configured_is_a_state_not_a_failure(tmp_path):
    svc = FeedService(
        FeedConfiguration(()), FeedStore(tmp_path), CheckpointStore(tmp_path),
        fetch=FakeFetch(Fetched(ONE)), now=lambda: NOW,
    )
    snapshot = svc.refresh()
    assert snapshot.status is RefreshStatus.NOTHING_CONFIGURED
    assert not snapshot.is_configured


# -- conditional requests and checkpoint ordering ------------------------


def test_stored_validators_are_sent_on_the_next_refresh(tmp_path):
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"', last_modified="Sat, 05 Sep 2026 10:00:00 GMT"))
    svc = service(tmp_path, fetch=fetch)
    svc.refresh()
    svc.refresh()
    assert fetch.calls[0]["etag"] is None
    assert fetch.calls[1]["etag"] == 'W/"1"'
    assert fetch.calls[1]["last_modified"] == "Sat, 05 Sep 2026 10:00:00 GMT"


def test_not_modified_is_distinct_from_having_no_items(tmp_path):
    """"Nothing was sent" and "there is nothing" are different facts."""
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"'), NotModified('W/"1"', None))
    svc = service(tmp_path, fetch=fetch)
    svc.refresh()
    second = svc.refresh()
    assert second.source_results[0].outcome is SourceOutcome.NOT_MODIFIED
    assert second.source_results[0].outcome is not SourceOutcome.NO_ITEMS


def test_not_modified_stores_no_records(tmp_path):
    fetch = FakeFetch(NotModified('W/"1"', None))
    snapshot = service(tmp_path, fetch=fetch).refresh()
    assert snapshot.items == ()
    assert snapshot.counters.accepted == 0


def test_an_empty_but_readable_feed_reports_no_items(tmp_path):
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(atom()))).refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.NO_ITEMS


def test_a_checkpoint_is_not_saved_when_storing_failed(tmp_path, monkeypatch):
    """The ordering rule: nothing may promise a 304 for entries we never stored.

    A checkpoint written before the append would, after a crash, make the source
    answer 304 for entries that are not on disk -- and they would never be seen
    again.
    """
    svc = service(tmp_path)
    monkeypatch.setattr(
        FeedStore, "write_item",
        lambda self, item: (_ for _ in ()).throw(OSError("disk full")),
    )
    svc.refresh()
    assert CheckpointStore(tmp_path).load(
        "demo", endpoint_fingerprint=definition().endpoint_fingerprint
    ).checkpoint is None


def test_a_refresh_after_a_failed_store_is_unconditional(tmp_path, monkeypatch):
    """No checkpoint means no If-None-Match, so the entries are offered again."""
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"'))
    svc = service(tmp_path, fetch=fetch)
    monkeypatch.setattr(
        FeedStore, "write_item",
        lambda self, item: (_ for _ in ()).throw(OSError("disk full")),
    )
    svc.refresh()
    monkeypatch.undo()
    svc.refresh()
    assert fetch.calls[1]["etag"] is None
    assert len(svc.snapshot().items) == 1


def test_a_checkpoint_failure_does_not_fail_the_refresh(tmp_path, monkeypatch):
    """Losing a cache costs one redundant fetch; failing would cost the records."""
    svc = service(tmp_path)
    monkeypatch.setattr(
        CheckpointStore, "save",
        lambda self, checkpoint: (_ for _ in ()).throw(OSError("read-only")),
    )
    snapshot = svc.refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.SUCCESS
    assert len(snapshot.items) == 1


def test_a_changed_endpoint_discards_the_stored_validators(tmp_path):
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"'))
    service(tmp_path, definition(), fetch=fetch).refresh()
    moved = definition(url="https://example.com/moved.xml")
    service(tmp_path, moved, fetch=fetch).refresh()
    assert fetch.calls[1]["etag"] is None


# -- store integrity dominates -------------------------------------------


def test_a_damaged_store_stops_ingestion(tmp_path):
    svc = service(tmp_path)
    svc.refresh()
    with FeedStore(tmp_path).documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    snapshot = svc.refresh()
    assert snapshot.source_results[0].outcome is SourceOutcome.STORAGE_CORRUPTION


def test_a_damaged_store_is_not_fetched_at_all(tmp_path):
    """Integrity is checked before the request, not after."""
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"'))
    svc = service(tmp_path, fetch=fetch)
    svc.refresh()
    with FeedStore(tmp_path).documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    svc.refresh()
    assert len(fetch.calls) == 1


def test_a_damaged_store_leaves_the_checkpoint_untouched(tmp_path):
    svc = service(tmp_path)
    svc.refresh()
    path = CheckpointStore(tmp_path).path_for("demo")
    before = path.read_bytes()
    with FeedStore(tmp_path).documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    svc.refresh()
    assert path.read_bytes() == before


def test_damaged_stored_rows_are_surfaced_in_the_snapshot(tmp_path):
    svc = service(tmp_path)
    svc.refresh()
    with FeedStore(tmp_path).documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    snapshot = svc.snapshot()
    assert snapshot.has_integrity_warning


def test_a_damaged_feed_does_not_hide_a_healthy_one(tmp_path):
    other = definition(source_id="other", url="https://other.example.com/f.xml")
    svc = service(tmp_path, definition(), other)
    svc.refresh()
    with FeedStore(tmp_path).documents_path("demo").open("a") as handle:
        handle.write("{broken\n")
    snapshot = svc.refresh()
    outcomes = {r.source_id: r.outcome for r in snapshot.source_results}
    assert outcomes["demo"] is SourceOutcome.STORAGE_CORRUPTION
    assert outcomes["other"].is_healthy


# -- truncation ----------------------------------------------------------


def test_a_truncated_feed_is_reported_as_truncated(tmp_path):
    from src.feeds.models import MAX_ENTRIES

    payload = atom(*(entry(n) for n in range(MAX_ENTRIES + 10)))
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(payload))).refresh()
    result = snapshot.source_results[0]
    assert result.outcome is SourceOutcome.TRUNCATED
    assert result.counters.entries_truncated == 10
    assert result.counters.entries_seen == MAX_ENTRIES + 10


def test_truncated_entries_are_still_stored(tmp_path):
    """Truncation limits how much is read, not whether what was read is kept."""
    from src.feeds.models import MAX_ENTRIES

    payload = atom(*(entry(n) for n in range(MAX_ENTRIES + 10)))
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(payload))).refresh()
    assert snapshot.counters.accepted == MAX_ENTRIES


def test_a_rejected_entry_is_counted_not_silently_dropped(tmp_path):
    payload = atom("<entry><title>No identity</title></entry>", entry(1))
    snapshot = service(tmp_path, fetch=FakeFetch(Fetched(payload))).refresh()
    assert snapshot.counters.rejected == 1
    assert snapshot.counters.accepted == 1


# -- ordering ------------------------------------------------------------


def test_items_are_ordered_newest_first():
    older = item(feed_item_id="old", available_from=NOW - timedelta(days=2),
                 source_published_at=NOW - timedelta(days=2))
    newer = item(feed_item_id="new", available_from=NOW - timedelta(hours=1),
                 source_published_at=NOW - timedelta(hours=1))
    assert [i.feed_item_id for i in order_items([older, newer])] == ["new", "old"]


def test_a_trust_label_never_reorders_time():
    """A word typed into a config file must not rearrange chronology."""
    old_official = item(
        feed_item_id="old", declared_trust_class=DeclaredTrustClass.OFFICIAL_FEED,
        available_from=NOW - timedelta(days=7), source_published_at=NOW - timedelta(days=7),
    )
    new_community = item(
        feed_item_id="new", declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED,
        available_from=NOW - timedelta(hours=1), source_published_at=NOW - timedelta(hours=1),
    )
    assert [i.feed_item_id for i in order_items([old_official, new_community])] == ["new", "old"]


def test_ordering_is_deterministic_for_identical_timestamps():
    a = item(feed_item_id="a")
    b = item(feed_item_id="b")
    assert order_items([b, a]) == order_items([a, b])


# -- causal filtering ----------------------------------------------------


def test_strict_causal_hides_an_item_not_yet_available():
    future = item(available_from=NOW + timedelta(hours=1),
                  source_published_at=NOW + timedelta(hours=1))
    assert filter_items([future], as_of=NOW) == ()


def test_strict_causal_shows_an_item_already_available():
    assert len(filter_items([item()], as_of=NOW)) == 1


def test_system_observed_trust_hides_a_backfilled_item():
    """An entry stamped last year but first fetched today was not knowable earlier."""
    backfilled = item(
        source_published_at=NOW - timedelta(days=365),
        available_from=NOW - timedelta(days=365),
        retrieved_at=NOW + timedelta(days=1),
    )
    assert filter_items([backfilled], as_of=NOW, trust=TrustMode.SYSTEM_OBSERVED) == ()
    assert len(filter_items([backfilled], as_of=NOW, trust=TrustMode.SOURCE_ASSERTED)) == 1


def test_an_unknown_availability_is_excluded_from_a_causal_query():
    """Nothing defensible is known, so it is excluded rather than guessed in."""
    unknown = item(
        availability_basis=AvailabilityBasis.UNKNOWN,
        source_published_at=None,
        available_from=None,
    )
    assert filter_items([unknown], as_of=NOW) == ()


def test_source_time_mode_asks_a_different_question():
    observed = item(
        availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
        source_published_at=None,
        available_from=NOW - timedelta(hours=1),
    )
    # It has no source timestamp, so a reportorial query cannot include it...
    assert filter_items([observed], as_of=NOW, mode=QueryMode.SOURCE_TIME) == ()
    # ...but a causal one can, because we know when we saw it.
    assert len(filter_items([observed], as_of=NOW, mode=QueryMode.STRICT_CAUSAL)) == 1


def test_an_update_time_counts_as_a_source_time():
    updated = item(
        availability_basis=AvailabilityBasis.SOURCE_UPDATED,
        source_published_at=None,
        source_edited_at=NOW - timedelta(hours=2),
        available_from=NOW - timedelta(hours=2),
    )
    assert len(filter_items([updated], as_of=NOW, mode=QueryMode.SOURCE_TIME)) == 1


def test_a_window_filters_by_availability():
    old = item(feed_item_id="old", available_from=NOW - timedelta(days=10),
               source_published_at=NOW - timedelta(days=10))
    assert filter_items([old, item()], start=NOW - timedelta(days=1)) == (item(),)


def test_items_can_be_filtered_by_feed_and_by_trust_class():
    other = item(source_id="other", declared_trust_class=DeclaredTrustClass.OFFICIAL_FEED)
    assert filter_items([item(), other], source_id="other") == (other,)
    assert filter_items(
        [item(), other], trust_class=DeclaredTrustClass.OFFICIAL_FEED
    ) == (other,)


# -- symbol scoping ------------------------------------------------------


def test_a_symbol_query_returns_only_items_linked_to_it(tmp_path):
    svc = service(
        tmp_path,
        definition(configured_symbols=("AAPL",)),
        definition(source_id="msft-feed", url="https://msft.example.com/f.xml",
                   configured_symbols=("MSFT",)),
        fetch=lambda url, **k: Fetched(
            atom(entry(1 if "msft" not in url else 2)), etag='W/"1"'
        ),
    )
    svc.refresh()
    assert {i.source_id for i in svc.items_for_symbol("AAPL")} == {"demo"}
    assert {i.source_id for i in svc.items_for_symbol("MSFT")} == {"msft-feed"}


def test_an_unconfigured_symbol_returns_nothing_rather_than_guessing(tmp_path):
    svc = service(tmp_path)
    svc.refresh()
    assert svc.items_for_symbol("TSLA") == ()


# -- snapshot ------------------------------------------------------------


def test_a_snapshot_fetches_nothing(tmp_path):
    fetch = FakeFetch(Fetched(ONE))
    svc = service(tmp_path, fetch=fetch)
    svc.snapshot()
    assert fetch.calls == []


def test_counters_sum_every_declared_field(tmp_path):
    """Summed reflectively, so a counter added later cannot be dropped."""
    from dataclasses import fields as dataclass_fields

    from src.feeds.source import IngestionCounters, SourceResult

    counters = IngestionCounters(**{f.name: 3 for f in dataclass_fields(IngestionCounters)})
    snapshot = FeedSnapshot(
        built_at=NOW, items=(), links=(),
        source_results=(SourceResult("a", SourceOutcome.SUCCESS, counters),
                        SourceResult("b", SourceOutcome.SUCCESS, counters)),
        status=RefreshStatus.ALL_OK,
    )
    for field in dataclass_fields(IngestionCounters):
        assert getattr(snapshot.counters, field.name) == 6, field.name


def test_a_snapshot_requires_an_aware_timestamp():
    from src.feeds.models import FeedError

    with pytest.raises(FeedError):
        FeedSnapshot(
            built_at=datetime(2026, 9, 6, 12, 0), items=(), links=(),
            source_results=(), status=RefreshStatus.ALL_OK,
        )


def test_an_item_reports_the_trust_class_it_was_stored_under(tmp_path):
    """Relabelling a feed today must not relabel what we stored last week."""
    svc = service(tmp_path, definition(declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED))
    svc.refresh()
    relabelled = service(
        tmp_path, definition(declared_trust_class=DeclaredTrustClass.OFFICIAL_FEED)
    )
    snapshot = relabelled.snapshot()
    assert snapshot.trust_class_for(snapshot.items[0]) is DeclaredTrustClass.COMMUNITY_FEED


# -- assembly ------------------------------------------------------------


def test_building_a_service_without_a_configuration_file_is_not_an_error(tmp_path):
    svc = build_service(config_path=tmp_path / "absent.json", store_root=tmp_path)
    assert svc.configuration.sources == ()
    assert svc.refresh().status is RefreshStatus.NOTHING_CONFIGURED


def test_a_new_symbol_is_associated_even_when_the_item_is_an_unchanged_duplicate(tmp_path):
    """"The item did not change" and "nothing changed" are different statements.

    Adding a symbol to a feed's configuration is a new fact about an item we
    already hold. Gating association writes on the *item* outcome would report
    "nothing changed" while the user's configuration plainly did.
    """
    fetch = FakeFetch(Fetched(ONE, etag='W/"1"'))
    service(tmp_path, definition(configured_symbols=("AAPL",)), fetch=fetch).refresh()

    widened = service(
        tmp_path, definition(configured_symbols=("AAPL", "MSFT")), fetch=fetch
    )
    snapshot = widened.refresh()

    assert snapshot.counters.duplicate == 1, "the item itself is unchanged"
    assert snapshot.counters.associations >= 1, "but the new symbol is a new association"
    assert "MSFT" in snapshot.symbols_for(snapshot.items[0])
    assert widened.items_for_symbol("MSFT")


def test_a_refresh_that_could_not_store_anything_is_not_reported_as_success(tmp_path, monkeypatch):
    """Counters saying "rejected" while the outcome says SUCCESS is a quiet lie."""
    svc = service(tmp_path)
    monkeypatch.setattr(
        FeedStore, "write_item",
        lambda self, item: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = svc.refresh().source_results[0]
    assert result.outcome is SourceOutcome.FAILED
    assert not result.outcome.is_healthy
    assert result.counters.rejected == 1
    assert result.counters.accepted == 0


def test_a_storage_failure_outranks_truncation_in_the_reported_outcome(tmp_path, monkeypatch):
    """A feed that was truncated *and* failed to store must not read as TRUNCATED,

    which is a healthy outcome.
    """
    from src.feeds.models import MAX_ENTRIES

    payload = atom(*(entry(n) for n in range(MAX_ENTRIES + 5)))
    svc = service(tmp_path, fetch=FakeFetch(Fetched(payload)))
    monkeypatch.setattr(
        FeedStore, "write_item",
        lambda self, item: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = svc.refresh().source_results[0]
    assert result.outcome is SourceOutcome.FAILED
    assert result.counters.entries_truncated == 5


def test_a_failed_store_leaves_the_whole_refresh_reported_as_failed(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(
        FeedStore, "write_item",
        lambda self, item: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert svc.refresh().status is RefreshStatus.ALL_FAILED
