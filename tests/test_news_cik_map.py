"""Phase 8 CIK map: freshness, offline resilience, and no historical overclaim."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.news.cik_map import (
    CIK_MAP_SCHEMA_VERSION,
    CIK_MAP_URL,
    CikMap,
    CikMapError,
    CikMapFetch,
    CikMapStore,
    load_cik_map,
    parse_company_tickers,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}


class Recorder:
    """Records every conditional fetch so freshness behaviour is observable."""

    def __init__(self, *responses: CikMapFetch):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, last_modified: str) -> CikMapFetch:
        self.calls.append((url, last_modified))
        if not self.responses:
            raise AssertionError("unexpected extra fetch")
        return self.responses.pop(0)


def clock():
    return T0


# -- parsing -------------------------------------------------------------


def test_parsing_produces_zero_padded_ciks():
    entries = parse_company_tickers(PAYLOAD)
    assert entries["AAPL"] == "0000320193"
    assert len(entries["AAPL"]) == 10


def test_malformed_rows_are_skipped_not_fatal():
    payload = {
        **PAYLOAD,
        "2": {"cik_str": "not-an-int", "ticker": "BAD"},
        "3": {"ticker": "", "cik_str": 1},
        "4": "not-a-dict",
        "5": {"cik_str": -5, "ticker": "NEG"},
    }
    entries = parse_company_tickers(payload)
    assert set(entries) == {"AAPL", "MSFT"}


def test_an_entirely_unusable_payload_raises():
    with pytest.raises(CikMapError):
        parse_company_tickers({"0": {"ticker": "", "cik_str": 0}})
    with pytest.raises(CikMapError):
        parse_company_tickers(["not", "a", "dict"])


# -- resolution ----------------------------------------------------------


def test_resolution_is_case_insensitive():
    cik_map = CikMap(parse_company_tickers(PAYLOAD), T0)
    assert cik_map.resolve("aapl") == "0000320193"
    assert cik_map.supports("AAPL")


def test_an_unlisted_symbol_resolves_to_none():
    """None means 'not an SEC registrant', which the caller reports as
    UNSUPPORTED -- never as 'no news'."""
    cik_map = CikMap(parse_company_tickers(PAYLOAD), T0)
    assert cik_map.resolve("BARC") is None
    assert not cik_map.supports("BARC")


def test_the_map_describes_its_own_vintage():
    cik_map = CikMap(parse_company_tickers(PAYLOAD), T0, last_modified="Wed, 02 Sep 2026")
    described = cik_map.describe()
    assert "2" in described and "Wed, 02 Sep 2026" in described


def test_a_map_without_a_vintage_says_so_rather_than_implying_freshness():
    assert "unknown vintage" in CikMap(parse_company_tickers(PAYLOAD), T0).describe()


# -- lifecycle -----------------------------------------------------------


def test_first_load_fetches_and_persists(tmp_path):
    store = CikMapStore(tmp_path)
    fetch = Recorder(CikMapFetch(PAYLOAD, last_modified="Wed, 02 Sep 2026"))

    cik_map = load_cik_map(store, fetch, now=clock)
    assert cik_map.size == 2
    assert fetch.calls == [(CIK_MAP_URL, "")]
    assert store.exists()


def test_a_stored_map_is_reused_without_refetching(tmp_path):
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    never = Recorder()  # any call raises
    reused = load_cik_map(store, never, now=clock, refresh=False)
    assert reused.size == 2
    assert never.calls == [], "an ordinary request must not re-fetch the map"


def test_refresh_sends_if_modified_since(tmp_path):
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    conditional = Recorder(CikMapFetch(None, not_modified=True))
    load_cik_map(store, conditional, now=clock)
    assert conditional.calls == [(CIK_MAP_URL, "v1")]


def test_not_modified_keeps_the_stored_map(tmp_path):
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    reused = load_cik_map(store, Recorder(CikMapFetch(None, not_modified=True)), now=clock)
    assert reused.size == 2
    assert reused.last_modified == "v1"


def test_a_newer_last_modified_replaces_the_stored_map(tmp_path):
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    bigger = {**PAYLOAD, "2": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla"}}
    updated = load_cik_map(store, Recorder(CikMapFetch(bigger, last_modified="v2")), now=clock)
    assert updated.size == 3
    assert updated.last_modified == "v2"
    assert store.read().size == 3


def test_a_network_failure_falls_back_to_the_stored_map(tmp_path):
    """A news refresh must not fail because a mapping file could not be
    re-checked."""
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    def explode(url, last_modified):
        raise ConnectionError("offline")

    offline = load_cik_map(store, explode, now=clock)
    assert offline.size == 2


def test_a_network_failure_with_no_stored_map_raises(tmp_path):
    def explode(url, last_modified):
        raise ConnectionError("offline")

    with pytest.raises(CikMapError):
        load_cik_map(CikMapStore(tmp_path), explode, now=clock)


def test_not_modified_with_no_stored_map_raises(tmp_path):
    with pytest.raises(CikMapError):
        load_cik_map(
            CikMapStore(tmp_path), Recorder(CikMapFetch(None, not_modified=True)), now=clock
        )


# -- the cache is a cache ------------------------------------------------


def test_a_corrupt_cache_is_rebuilt_rather_than_raising(tmp_path):
    """This file is a rebuildable copy of a public document, not the record
    store: re-fetching is the correct repair, and it is the only place in
    Phase 8 where unreadable bytes are discarded."""
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)
    store.path.write_text("not json")

    assert store.read() is None
    rebuilt = load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v2")), now=clock)
    assert rebuilt.size == 2


def test_an_unknown_cache_schema_is_ignored(tmp_path):
    store = CikMapStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({
        "schema_version": CIK_MAP_SCHEMA_VERSION + 1,
        "retrieved_at": T0.isoformat(), "entries": {"AAPL": "1"},
    }))
    assert store.read() is None


def test_the_stored_envelope_records_provenance(tmp_path):
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="Wed, 02 Sep")), now=clock)
    envelope = json.loads(store.path.read_text())
    assert envelope["retrieved_at"] == T0.isoformat()
    assert envelope["last_modified"] == "Wed, 02 Sep"
    assert envelope["schema_version"] == CIK_MAP_SCHEMA_VERSION


# -- no historical overclaim --------------------------------------------


def test_the_map_offers_no_historical_lookup():
    """There is no as_of on the map, because the data to answer one does not
    exist: the SEC publishes today's mapping, with no history."""
    cik_map = CikMap(parse_company_tickers(PAYLOAD), T0)
    for forbidden in ("as_of", "at_time", "historical", "resolve_at"):
        assert not hasattr(cik_map, forbidden)


def test_documentation_states_the_historical_limitation():
    import pathlib

    doc = pathlib.Path("docs/news.md").read_text()
    assert "historical" in doc.lower()
    assert "not evidence" in doc.lower() or "not reconstructible" in doc.lower()


def test_a_malformed_remote_payload_never_replaces_a_valid_cache(tmp_path):
    """Regression: one bad SEC response used to raise and kill the refresh.

    A cached map is still perfectly usable; turning a single malformed response
    into a lasting outage is the opposite of resilient.
    """
    store = CikMapStore(tmp_path)
    load_cik_map(store, Recorder(CikMapFetch(PAYLOAD, last_modified="v1")), now=clock)

    kept = load_cik_map(
        store, Recorder(CikMapFetch({"0": {"junk": True}}, last_modified="v2")), now=clock
    )
    assert kept.size == 2
    assert kept.last_modified == "v1", "the good cache must be kept, not replaced"
    assert store.read().size == 2


def test_a_malformed_payload_with_no_cache_still_raises(tmp_path):
    """With nothing to fall back to, the failure must surface."""
    with pytest.raises(CikMapError):
        load_cik_map(
            CikMapStore(tmp_path),
            Recorder(CikMapFetch({"0": {"junk": True}}, last_modified="v1")),
            now=clock,
        )
