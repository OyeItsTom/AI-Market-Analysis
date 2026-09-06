"""Phase 8 orchestration: independence, partial success, and honest reporting.

A refresh touches two unrelated services, so most of what matters here is what
happens when only one of them works.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.news import (
    NewsService,
    NewsSnapshot,
    QueryMode,
    RefreshStatus,
    SymbolNotSupported,
    TrustMode,
    build_service,
)
from src.news.cik_map import CikMap
from src.news.config import SEC_USER_AGENT_VAR
from src.news.models import (
    AvailabilityBasis,
    NewsItem,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
)
from src.news.source import FetchedRecord, SourceError, SourceOutcome
from src.news.store import NewsStore

UTC = timezone.utc
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
VALID_CONTACT = "AI-Market-Analysis someone@example.com"


def clock():
    return NOW


def make_news(item_id="n1", **overrides) -> NewsItem:
    fields = dict(
        source="yahoo", source_item_id=item_id,
        source_class=SourceClass.SECONDARY_NEWS, publisher="Reuters",
        headline=f"Headline {item_id}", canonical_url=f"https://example.com/{item_id}",
        retrieved_at=NOW, availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        source_published_at=NOW - timedelta(hours=1),
        available_from=NOW - timedelta(hours=1), content_hash=f"hash-{item_id}",
    )
    fields.update(overrides)
    return NewsItem(**fields)


def make_filing(item_id="f1", **overrides) -> OfficialFiling:
    fields = dict(
        source="edgar", source_item_id=item_id,
        source_class=SourceClass.OFFICIAL_FILING, cik="0000320193", form="8-K",
        headline=f"8-K {item_id}", canonical_url=f"https://www.sec.gov/{item_id}/",
        primary_document_url=f"https://www.sec.gov/{item_id}/d.htm",
        retrieved_at=NOW, availability_basis=AvailabilityBasis.SOURCE_EVENT,
        source_event_time=NOW - timedelta(days=1),
        available_from=NOW - timedelta(days=1), content_hash=f"hash-{item_id}",
    )
    fields.update(overrides)
    return OfficialFiling(**fields)


def record(document, symbol="AAPL", association=None) -> FetchedRecord:
    association = association or (
        SymbolAssociation.VERIFIED_SOURCE
        if document.source_class.is_official
        else SymbolAssociation.QUERIED_SYMBOL
    )
    return FetchedRecord(
        document,
        (SymbolLink(
            source=document.source, source_item_id=document.source_item_id,
            symbol=symbol, association=association, retrieved_at=NOW,
        ),),
    )


class FakeSource:
    """A source that returns records, raises, or reports an outcome."""

    def __init__(self, name, records=(), error=None):
        self.name = name
        self._records = tuple(records)
        self._error = error
        self.calls = 0

    def fetch_for_symbol(self, symbol, *, now):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._records


def service(tmp_path, sources, **kwargs) -> NewsService:
    return NewsService(
        {s.name: s for s in sources}, NewsStore(tmp_path), now=clock, **kwargs
    )


# -- ordinary refresh ----------------------------------------------------


def test_a_successful_refresh_stores_and_reports(tmp_path):
    svc = service(tmp_path, [FakeSource("yahoo", [record(make_news())])])
    snapshot = svc.refresh("AAPL")

    assert snapshot.status is RefreshStatus.ALL_OK
    assert len(snapshot.documents) == 1
    assert snapshot.source_results[0].outcome is SourceOutcome.SUCCESS
    assert snapshot.counters.accepted == 1


def test_a_snapshot_is_frozen_and_utc(tmp_path):
    snapshot = service(tmp_path, [FakeSource("yahoo", [record(make_news())])]).refresh("AAPL")
    assert snapshot.built_at == NOW
    with pytest.raises(Exception):
        snapshot.symbol = "MSFT"


def test_official_and_secondary_are_separable(tmp_path):
    svc = service(tmp_path, [
        FakeSource("yahoo", [record(make_news())]),
        FakeSource("edgar", [record(make_filing())]),
    ])
    snapshot = svc.refresh("AAPL")
    assert len(snapshot.official) == 1
    assert len(snapshot.secondary) == 1


def test_a_second_refresh_of_identical_content_is_a_duplicate(tmp_path):
    svc = service(tmp_path, [FakeSource("yahoo", [record(make_news())])])
    svc.refresh("AAPL")
    snapshot = svc.refresh("AAPL")
    assert snapshot.counters.duplicate == 1
    assert len(snapshot.documents) == 1


def test_no_items_is_healthy_not_a_failure(tmp_path):
    snapshot = service(tmp_path, [FakeSource("yahoo", [])]).refresh("AAPL")
    assert snapshot.source_results[0].outcome is SourceOutcome.NO_ITEMS
    assert snapshot.status is RefreshStatus.ALL_OK


# -- source independence -------------------------------------------------


def test_edgar_succeeds_while_yahoo_fails(tmp_path):
    svc = service(tmp_path, [
        FakeSource("edgar", [record(make_filing())]),
        FakeSource("yahoo", error=SourceError(SourceOutcome.FAILED, "down")),
    ])
    snapshot = svc.refresh("AAPL")

    assert snapshot.status is RefreshStatus.PARTIAL
    assert len(snapshot.official) == 1, "the healthy source's records must persist"
    outcomes = {r.source: r.outcome for r in snapshot.source_results}
    assert outcomes["edgar"] is SourceOutcome.SUCCESS
    assert outcomes["yahoo"] is SourceOutcome.FAILED


def test_yahoo_succeeds_while_edgar_fails(tmp_path):
    svc = service(tmp_path, [
        FakeSource("edgar", error=SourceError(SourceOutcome.FAILED, "down")),
        FakeSource("yahoo", [record(make_news())]),
    ])
    snapshot = svc.refresh("AAPL")
    assert snapshot.status is RefreshStatus.PARTIAL
    assert len(snapshot.secondary) == 1


def test_a_failing_source_never_rolls_back_a_healthy_one(tmp_path):
    """Explicit: one outage must not erase another source's stored records."""
    store = NewsStore(tmp_path)
    good = NewsService({"edgar": FakeSource("edgar", [record(make_filing())])},
                       store, now=clock)
    good.refresh("AAPL")
    stored_before, _ = store.read_documents("edgar")

    mixed = NewsService(
        {
            "edgar": FakeSource("edgar", error=SourceError(SourceOutcome.FAILED, "down")),
            "yahoo": FakeSource("yahoo", [record(make_news())]),
        },
        store, now=clock,
    )
    mixed.refresh("AAPL")
    stored_after, _ = store.read_documents("edgar")
    assert stored_after == stored_before


def test_both_sources_failing_is_all_failed(tmp_path):
    svc = service(tmp_path, [
        FakeSource("edgar", error=SourceError(SourceOutcome.FAILED, "down")),
        FakeSource("yahoo", error=SourceError(SourceOutcome.FAILED, "down")),
    ])
    snapshot = svc.refresh("AAPL")
    assert snapshot.status is RefreshStatus.ALL_FAILED
    assert snapshot.documents == ()


def test_both_sources_with_no_items_is_all_ok(tmp_path):
    snapshot = service(tmp_path, [
        FakeSource("edgar", []), FakeSource("yahoo", []),
    ]).refresh("AAPL")
    assert snapshot.status is RefreshStatus.ALL_OK


def test_an_unconfigured_source_is_reported_without_blocking_the_other(tmp_path):
    svc = NewsService(
        {"yahoo": FakeSource("yahoo", [record(make_news())])},
        NewsStore(tmp_path), now=clock,
        unconfigured={"edgar": "EDGAR is switched off"},
    )
    snapshot = svc.refresh("AAPL")

    assert snapshot.status is RefreshStatus.PARTIAL
    outcomes = {r.source: r.outcome for r in snapshot.source_results}
    assert outcomes["edgar"] is SourceOutcome.UNCONFIGURED
    assert outcomes["yahoo"] is SourceOutcome.SUCCESS
    assert len(snapshot.secondary) == 1


def test_an_unexpected_source_exception_does_not_take_down_the_refresh(tmp_path):
    svc = service(tmp_path, [
        FakeSource("edgar", error=RuntimeError("kaboom")),
        FakeSource("yahoo", [record(make_news())]),
    ])
    snapshot = svc.refresh("AAPL")
    assert snapshot.status is RefreshStatus.PARTIAL
    assert len(snapshot.documents) == 1


def test_a_symbol_no_source_supports_is_reported_clearly(tmp_path):
    svc = service(tmp_path, [
        FakeSource("edgar", error=SourceError(SourceOutcome.UNSUPPORTED, "no CIK")),
    ])
    with pytest.raises(SymbolNotSupported) as info:
        svc.refresh("BARC")
    assert "coverage limit" in str(info.value)


# -- item independence ---------------------------------------------------


def test_one_bad_record_does_not_void_its_siblings(tmp_path):
    class HalfBroken(FakeSource):
        def fetch_for_symbol(self, symbol, *, now):
            good = record(make_news("good"))
            broken = FetchedRecord(make_news("broken"), ())
            object.__setattr__(broken.document, "source", "yahoo/../escape")
            return (good, broken)

    svc = service(tmp_path, [HalfBroken("yahoo")])
    snapshot = svc.refresh("AAPL")
    assert snapshot.counters.rejected == 1
    assert snapshot.counters.accepted == 1


# -- cross-symbol --------------------------------------------------------


def test_one_document_returned_for_several_symbols_is_stored_once(tmp_path):
    store = NewsStore(tmp_path)
    document = make_news("shared")
    for symbol in ("AAPL", "AMZN", "TSLA"):
        NewsService(
            {"yahoo": FakeSource("yahoo", [record(document, symbol=symbol)])},
            store, now=clock,
        ).refresh(symbol)

    documents, _ = store.read_documents("yahoo")
    links, _ = store.read_links("yahoo")
    assert len(documents) == 1
    assert {l.symbol for l in links} == {"AAPL", "AMZN", "TSLA"}


def test_a_symbol_only_sees_its_own_associations(tmp_path):
    store = NewsStore(tmp_path)
    NewsService({"yahoo": FakeSource("yahoo", [record(make_news("a"), symbol="AAPL")])},
                store, now=clock).refresh("AAPL")
    NewsService({"yahoo": FakeSource("yahoo", [record(make_news("b"), symbol="MSFT")])},
                store, now=clock).refresh("MSFT")

    svc = NewsService({"yahoo": FakeSource("yahoo", [])}, store, now=clock)
    assert [d.source_item_id for d in svc.documents_for_symbol("AAPL")] == ["a"]
    assert [d.source_item_id for d in svc.documents_for_symbol("MSFT")] == ["b"]


# -- association trust ---------------------------------------------------


def test_the_snapshot_reports_each_document_s_association(tmp_path):
    svc = service(tmp_path, [
        FakeSource("yahoo", [record(make_news())]),
        FakeSource("edgar", [record(make_filing())]),
    ])
    snapshot = svc.refresh("AAPL")
    by_source = {d.source: snapshot.association_for(d) for d in snapshot.documents}
    assert by_source["yahoo"] is SymbolAssociation.QUERIED_SYMBOL
    assert by_source["edgar"] is SymbolAssociation.VERIFIED_SOURCE


# -- integrity -----------------------------------------------------------


def test_a_corrupt_store_surfaces_as_a_warning_not_a_crash(tmp_path):
    store = NewsStore(tmp_path)
    svc = NewsService({"yahoo": FakeSource("yahoo", [record(make_news())])},
                      store, now=clock)
    svc.refresh("AAPL")
    with store.documents_path("yahoo").open("a", encoding="utf-8") as handle:
        handle.write("broken line")

    quiet = NewsService({"yahoo": FakeSource("yahoo", [])}, store, now=clock)
    snapshot = quiet.refresh("AAPL")
    assert snapshot.has_integrity_warning
    assert snapshot.integrity is not None


# -- queries -------------------------------------------------------------


def test_queries_respect_causal_mode(tmp_path):
    store = NewsStore(tmp_path)
    old = make_filing("old", source_event_time=datetime(2024, 3, 1, tzinfo=UTC),
                      available_from=datetime(2024, 3, 1, tzinfo=UTC))
    NewsService({"edgar": FakeSource("edgar", [record(old)])}, store, now=clock).refresh("AAPL")

    svc = NewsService({"edgar": FakeSource("edgar", [])}, store, now=clock)
    asserted = svc.documents_for_symbol(
        "AAPL", as_of=datetime(2024, 6, 1, tzinfo=UTC), trust=TrustMode.SOURCE_ASSERTED
    )
    observed = svc.documents_for_symbol(
        "AAPL", as_of=datetime(2024, 6, 1, tzinfo=UTC), trust=TrustMode.SYSTEM_OBSERVED
    )
    assert len(asserted) == 1
    assert observed == (), "we did not have it in 2024; we fetched it in 2026"


def test_official_filings_helper_filters_by_class(tmp_path):
    svc = service(tmp_path, [
        FakeSource("yahoo", [record(make_news())]),
        FakeSource("edgar", [record(make_filing())]),
    ])
    svc.refresh("AAPL")
    assert all(d.source_class.is_official for d in svc.official_filings("AAPL"))


def test_latest_documents_is_bounded(tmp_path):
    records = [record(make_news(f"n{i}")) for i in range(10)]
    svc = service(tmp_path, [FakeSource("yahoo", records)])
    svc.refresh("AAPL")
    assert len(svc.latest_documents("AAPL", limit=3)) == 3


# -- construction --------------------------------------------------------


def test_build_service_switches_edgar_off_without_a_contact(tmp_path):
    svc = build_service(store_root=tmp_path, environ={}, now=clock,
                        yahoo_fetch_fn=lambda s, c: [])
    snapshot = svc.refresh("AAPL")
    outcomes = {r.source: r.outcome for r in snapshot.source_results}
    assert outcomes["edgar"] is SourceOutcome.UNCONFIGURED
    assert outcomes["yahoo"] is SourceOutcome.NO_ITEMS


def test_build_service_enables_edgar_with_a_contact_and_a_map(tmp_path):
    svc = build_service(
        store_root=tmp_path,
        environ={SEC_USER_AGENT_VAR: VALID_CONTACT},
        cik_map=CikMap({"AAPL": "0000320193"}, NOW, last_modified="v1"),
        edgar_fetch_fn=lambda url, ua: {"filings": {"recent": {}}},
        yahoo_fetch_fn=lambda s, c: [],
        now=clock,
    )
    snapshot = svc.refresh("AAPL")
    outcomes = {r.source: r.outcome for r in snapshot.source_results}
    assert outcomes["edgar"] is SourceOutcome.NO_ITEMS
    assert snapshot.cik_map_last_modified == "v1"


def test_build_service_switches_edgar_off_without_a_map(tmp_path):
    svc = build_service(
        store_root=tmp_path, environ={SEC_USER_AGENT_VAR: VALID_CONTACT},
        cik_map=None, yahoo_fetch_fn=lambda s, c: [], now=clock,
    )
    outcomes = {r.source: r.outcome for r in svc.refresh("AAPL").source_results}
    assert outcomes["edgar"] is SourceOutcome.UNCONFIGURED


def test_an_empty_symbol_is_refused(tmp_path):
    with pytest.raises(Exception):
        service(tmp_path, [FakeSource("yahoo", [])]).refresh("   ")


# -- the firewall --------------------------------------------------------


def test_a_snapshot_carries_no_research_or_paper_state(tmp_path):
    snapshot = service(tmp_path, [FakeSource("yahoo", [record(make_news())])]).refresh("AAPL")
    surface = {name for name in dir(snapshot) if not name.startswith("_")}
    for forbidden in ("assessment", "observation", "portfolio", "intent",
                      "position", "sentiment", "score", "recommendation"):
        assert not any(forbidden in name.lower() for name in surface), surface


# -- regressions from the independent review ----------------------------


def test_an_undecodable_stored_row_is_reported_not_fatal(tmp_path):
    """Regression: a future schema_version crashed the entire refresh.

    A row this build cannot decode is an integrity problem to surface, not a
    reason to lose every source that reads perfectly well.
    """
    import json

    from src.news.store import SCHEMA_VERSION

    store = NewsStore(tmp_path)
    NewsService({"yahoo": FakeSource("yahoo", [record(make_news())])},
                store, now=clock).refresh("AAPL")

    path = store.documents_path("yahoo")
    row = json.loads(path.read_text().splitlines()[0])
    row["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(row) + "\n")

    snapshot = NewsService({"yahoo": FakeSource("yahoo", [])},
                           store, now=clock).refresh("AAPL")
    assert snapshot.has_integrity_warning
    assert "schema_version" in snapshot.integrity.describe()


def test_a_healthy_source_survives_an_undecodable_row_in_another(tmp_path):
    import json

    from src.news.store import SCHEMA_VERSION

    store = NewsStore(tmp_path)
    NewsService({"edgar": FakeSource("edgar", [record(make_filing())])},
                store, now=clock).refresh("AAPL")
    path = store.documents_path("edgar")
    row = json.loads(path.read_text().splitlines()[0])
    row["schema_version"] = SCHEMA_VERSION + 99
    path.write_text(json.dumps(row) + "\n")

    snapshot = NewsService(
        {"edgar": FakeSource("edgar", []),
         "yahoo": FakeSource("yahoo", [record(make_news())])},
        store, now=clock,
    ).refresh("AAPL")
    assert len(snapshot.secondary) == 1, "the readable source must still appear"
    assert snapshot.has_integrity_warning


def test_a_new_association_is_counted_even_when_the_document_is_a_duplicate(tmp_path):
    """Regression: counters read as "nothing changed" when something did.

    The same article returned for a second symbol is a duplicate *document* but
    a brand-new association, and the refresh must say so.
    """
    store = NewsStore(tmp_path)
    document = make_news("shared")

    first = NewsService({"yahoo": FakeSource("yahoo", [record(document, symbol="AAPL")])},
                        store, now=clock).refresh("AAPL")
    assert first.counters.accepted == 1
    assert first.counters.associations == 1

    second = NewsService({"yahoo": FakeSource("yahoo", [record(document, symbol="AMZN")])},
                         store, now=clock).refresh("AMZN")
    assert second.counters.duplicate == 1
    assert second.counters.associations == 1, "a new link is a real change"
    assert "associations=1" in second.counters.describe()


def test_a_repeated_identical_association_is_not_counted_again(tmp_path):
    store = NewsStore(tmp_path)
    document = make_news("shared")
    service = NewsService({"yahoo": FakeSource("yahoo", [record(document, symbol="AAPL")])},
                          store, now=clock)
    service.refresh("AAPL")
    again = service.refresh("AAPL")
    assert again.counters.duplicate == 1
    assert again.counters.associations == 0, "nothing new happened the second time"


def test_an_orphaned_association_is_inert_rather_than_surfacing(tmp_path):
    """A link whose document is absent must not fabricate a document."""
    store = NewsStore(tmp_path)
    store.write_link(SymbolLink(
        source="yahoo", source_item_id="never-stored", symbol="AAPL",
        association=SymbolAssociation.QUERIED_SYMBOL, retrieved_at=NOW,
    ))
    snapshot = NewsService({"yahoo": FakeSource("yahoo", [])},
                           store, now=clock).refresh("AAPL")
    assert snapshot.documents == ()
