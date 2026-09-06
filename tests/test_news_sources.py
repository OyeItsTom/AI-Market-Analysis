"""Phase 8 source adapters, driven entirely from recorded payload shapes.

Both fetch functions are injected, so nothing here touches the network. The
fixtures mirror the real payloads observed from EDGAR and Yahoo, including the
awkward parts: Yahoo carries no ticker field, and its results for one symbol
routinely concern other companies.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.news.cik_map import CikMap
from src.news.config import SecContact
from src.news.models import (
    AvailabilityBasis,
    EventType,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
)
from src.news.source import SourceError, SourceOutcome
from src.news.sources.edgar import EdgarFilingsSource
from src.news.sources.yahoo import YahooNewsSource

UTC = timezone.utc
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
CONTACT = SecContact("AI-Market-Analysis someone@example.com")
CIK_MAP = CikMap({"AAPL": "0000320193"}, NOW, last_modified="Wed, 02 Sep 2026")


# -- EDGAR ---------------------------------------------------------------


def edgar_payload(**overrides):
    recent = {
        "accessionNumber": ["0001140361-26-035325", "0001140361-26-035362"],
        "filingDate": ["2026-09-01", "2026-09-01"],
        "reportDate": ["", ""],
        "acceptanceDateTime": ["2026-09-01T20:30:35.000Z", "2026-09-01T22:32:04.000Z"],
        "form": ["8-K", "4"],
        "items": ["5.02", ""],
        "primaryDocument": ["ef20081427_8ka.htm", "form4.xml"],
    }
    recent.update(overrides)
    return {"cik": "0000320193", "filings": {"recent": recent}}


def edgar_source(payload=None, **kwargs):
    def fetch(url, user_agent):
        assert user_agent == CONTACT.user_agent
        if isinstance(payload, Exception):
            raise payload
        return edgar_payload() if payload is None else payload

    return EdgarFilingsSource(fetch_fn=fetch, cik_map=CIK_MAP, contact=CONTACT, **kwargs)


def test_edgar_returns_official_filings():
    records = edgar_source().fetch_for_symbol("AAPL", now=NOW)
    assert len(records) == 2
    for record in records:
        assert isinstance(record.document, OfficialFiling)
        assert record.document.source_class is SourceClass.OFFICIAL_FILING


def test_edgar_uses_the_accession_number_as_identity():
    records = edgar_source().fetch_for_symbol("AAPL", now=NOW)
    assert records[0].document.source_item_id == "0001140361-26-035325"


def test_edgar_records_the_acceptance_instant_as_a_source_event():
    document = edgar_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.source_event_time == datetime(2026, 9, 1, 20, 30, 35, tzinfo=UTC)
    assert document.availability_basis is AvailabilityBasis.SOURCE_EVENT
    assert document.available_from == document.source_event_time


def test_edgar_keeps_filing_date_separate_from_acceptance():
    """They are different facts: a filing accepted late is dated next day."""
    document = edgar_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.filing_date == "2026-09-01"
    assert document.source_event_time.isoformat() != document.filing_date


def test_edgar_preserves_form_and_items():
    document = edgar_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.form == "8-K"
    assert document.items == ("5.02",)
    assert document.event_type is EventType.FILING


def test_edgar_association_is_source_verified():
    """The SEC maps this CIK to this ticker, so the link is a source fact."""
    record = edgar_source().fetch_for_symbol("AAPL", now=NOW)[0]
    link = record.links[0]
    assert link.association is SymbolAssociation.VERIFIED_SOURCE
    assert link.cik_map_last_modified == "Wed, 02 Sep 2026"


def test_edgar_builds_the_document_url_from_trusted_identifiers():
    """Constructed, never taken from a payload URL."""
    document = edgar_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.primary_document_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000114036126035325/ef20081427_8ka.htm"
    )
    assert document.primary_document_url.startswith("https://www.sec.gov/")


def test_edgar_ignores_any_url_present_in_the_payload():
    payload = edgar_payload()
    payload["filings"]["recent"]["primaryDocument"] = ["ok.htm", "ok2.htm"]
    payload["evilUrl"] = "https://attacker.example.com/x"
    document = edgar_source(payload).fetch_for_symbol("AAPL", now=NOW)[0].document
    assert "attacker" not in document.primary_document_url


def test_an_unresolvable_symbol_is_unsupported_not_empty():
    with pytest.raises(SourceError) as info:
        edgar_source().fetch_for_symbol("BARC", now=NOW)
    assert info.value.outcome is SourceOutcome.UNSUPPORTED
    assert "coverage limit" in info.value.message


def test_a_transport_failure_becomes_a_failed_outcome():
    with pytest.raises(SourceError) as info:
        edgar_source(ConnectionError("boom")).fetch_for_symbol("AAPL", now=NOW)
    assert info.value.outcome is SourceOutcome.FAILED


def test_an_empty_filing_index_returns_no_records():
    assert edgar_source({"filings": {"recent": {}}}).fetch_for_symbol("AAPL", now=NOW) == ()


def test_a_non_object_response_fails_cleanly():
    with pytest.raises(SourceError):
        edgar_source(["not", "an", "object"]).fetch_for_symbol("AAPL", now=NOW)


def test_a_malformed_filing_is_dropped_without_losing_its_siblings():
    payload = edgar_payload()
    payload["filings"]["recent"]["accessionNumber"] = ["", "0001140361-26-035362"]
    records = edgar_source(payload).fetch_for_symbol("AAPL", now=NOW)
    assert len(records) == 1
    assert records[0].document.source_item_id == "0001140361-26-035362"


def test_a_missing_acceptance_time_falls_back_to_system_observed():
    """No source instant: we record only that we have it now, never a guess."""
    payload = edgar_payload(acceptanceDateTime=["", ""])
    document = edgar_source(payload).fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.source_event_time is None
    assert document.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED
    assert document.available_from == NOW


def test_a_far_future_acceptance_time_is_rejected():
    payload = edgar_payload(acceptanceDateTime=["2030-01-01T00:00:00.000Z", ""])
    records = edgar_source(payload).fetch_for_symbol("AAPL", now=NOW)
    assert all(r.document.source_item_id != "0001140361-26-035325" for r in records)


def test_edgar_declares_conservative_access_limits():
    from src.news.sources import edgar

    assert edgar.REQUESTS_PER_SECOND <= 10
    assert edgar.TIMEOUT_SECONDS == 30
    assert edgar.MAX_RETRIES <= 2


# -- Yahoo ---------------------------------------------------------------


def yahoo_item(**overrides):
    content = {
        "id": "d4625f56-eac1-3d46-8966-c28e6e483f22",
        "title": "Apple draws a new lawsuit",
        "summary": "A summary supplied by the provider.",
        "pubDate": "2026-09-05T11:00:00Z",
        "provider": {"displayName": "Reuters"},
        "canonicalUrl": {"url": "https://example.com/story"},
    }
    content.update(overrides)
    return {"id": content.get("id"), "content": content}


def yahoo_source(items=None):
    def fetch(symbol, count):
        if isinstance(items, Exception):
            raise items
        return [yahoo_item()] if items is None else items

    return YahooNewsSource(fetch_fn=fetch)


def test_yahoo_returns_secondary_news():
    record = yahoo_source().fetch_for_symbol("AAPL", now=NOW)[0]
    assert record.document.source_class is SourceClass.SECONDARY_NEWS
    assert record.document.event_type is EventType.UNKNOWN


def test_yahoo_uses_the_provider_id():
    document = yahoo_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.source_item_id == "d4625f56-eac1-3d46-8966-c28e6e483f22"


def test_a_missing_provider_id_is_refused_not_manufactured():
    """No fallback key: a headline-derived id would merge syndicated stories."""
    broken = yahoo_item()
    broken["id"] = None
    broken["content"]["id"] = None
    assert yahoo_source([broken]).fetch_for_symbol("AAPL", now=NOW) == ()


def test_the_association_is_only_the_queried_symbol():
    """The payload names no ticker, so nothing stronger may be claimed."""
    link = yahoo_source().fetch_for_symbol("AAPL", now=NOW)[0].links[0]
    assert link.association is SymbolAssociation.QUERIED_SYMBOL
    assert link.association is not SymbolAssociation.VERIFIED_SOURCE
    assert link.queried_symbol == "AAPL"


def test_a_story_about_another_company_still_only_gets_a_queried_link():
    """Observed live: querying AAPL returns stories primarily about others."""
    other = yahoo_item(title="Prediction: Amazon Will Join Nvidia and Alphabet")
    record = yahoo_source([other]).fetch_for_symbol("AAPL", now=NOW)[0]
    assert record.links[0].association is SymbolAssociation.QUERIED_SYMBOL
    assert record.links[0].symbol == "AAPL"


def test_yahoo_records_the_publication_time_as_source_published():
    document = yahoo_source().fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.source_published_at == datetime(2026, 9, 5, 11, 0, tzinfo=UTC)
    assert document.availability_basis is AvailabilityBasis.SOURCE_PUBLISHED
    assert document.retrieved_at == NOW
    assert document.source_published_at != document.retrieved_at


def test_a_missing_publication_time_never_becomes_the_retrieval_time():
    document = yahoo_source([yahoo_item(pubDate=None, displayTime=None)]).fetch_for_symbol(
        "AAPL", now=NOW
    )[0].document
    assert document.source_published_at is None
    assert document.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED


def test_epoch_publication_times_are_understood():
    document = yahoo_source([yahoo_item(pubDate=1757070000)]).fetch_for_symbol(
        "AAPL", now=NOW
    )[0].document
    assert document.source_published_at is not None


def test_a_far_future_publication_time_is_rejected():
    assert yahoo_source([yahoo_item(pubDate="2030-01-01T00:00:00Z")]).fetch_for_symbol(
        "AAPL", now=NOW
    ) == ()


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "//example.com/x",
        "https://user:pass@example.com/x",
    ],
)
def test_unsafe_urls_are_refused(url):
    assert yahoo_source([yahoo_item(canonicalUrl={"url": url})]).fetch_for_symbol(
        "AAPL", now=NOW
    ) == ()


def test_a_missing_url_is_refused():
    item = yahoo_item()
    item["content"].pop("canonicalUrl")
    assert yahoo_source([item]).fetch_for_symbol("AAPL", now=NOW) == ()


def test_a_malformed_story_does_not_lose_its_siblings():
    good = yahoo_item()
    bad = yahoo_item(title="")
    bad["id"] = "second"
    bad["content"]["id"] = "second"
    records = yahoo_source([bad, good]).fetch_for_symbol("AAPL", now=NOW)
    assert len(records) == 1


def test_html_in_a_headline_is_stored_as_inert_text():
    item = yahoo_item(title="<script>alert(1)</script> Apple news")
    document = yahoo_source([item]).fetch_for_symbol("AAPL", now=NOW)[0].document
    assert "<script>" in document.headline  # escaped at render, never executed


def test_an_over_long_headline_is_capped():
    item = yahoo_item(title="x" * 10_000)
    document = yahoo_source([item]).fetch_for_symbol("AAPL", now=NOW)[0].document
    assert len(document.headline) <= 1_000


def test_a_missing_publisher_becomes_explicit():
    item = yahoo_item()
    item["content"]["provider"] = {}
    document = yahoo_source([item]).fetch_for_symbol("AAPL", now=NOW)[0].document
    assert document.publisher == "unknown publisher"


def test_a_transport_failure_becomes_a_failed_outcome():
    with pytest.raises(SourceError) as info:
        yahoo_source(ConnectionError("boom")).fetch_for_symbol("AAPL", now=NOW)
    assert info.value.outcome is SourceOutcome.FAILED


def test_an_unusable_payload_fails_cleanly():
    with pytest.raises(SourceError):
        YahooNewsSource(fetch_fn=lambda s, c: "not a list").fetch_for_symbol("AAPL", now=NOW)


def test_yahoo_never_produces_an_official_class():
    documents = [r.document for r in yahoo_source().fetch_for_symbol("AAPL", now=NOW)]
    assert all(not d.source_class.is_official for d in documents)


def test_the_press_releases_tab_is_not_requested():
    """Sampled live across three symbols, that tab returned third-party wire
    copy about other companies -- never the company's own releases.

    Checked against the values actually passed as ``tab``, not against prose:
    the module docstring explains why the tab is avoided, and explaining it is
    not requesting it.
    """
    import ast

    from src.news.sources import yahoo as module

    assert module.NEWS_TAB == "news"

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    tab_values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "tab":
                    tab_values.append(ast.dump(keyword.value))
    assert tab_values, "the adapter should pass an explicit tab"
    for value in tab_values:
        assert "press" not in value.lower()
        assert "NEWS_TAB" in value or "'news'" in value


# -- the EDGAR access policy is applied, not merely declared -------------


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
    def read(self): return self._payload
    def __enter__(self): return self
    def __exit__(self, *a): return False


def policy_fetch(responses, *, slept=None, clock=None):
    """Drive default_fetch_fn with injected opener/sleep/clock."""
    from src.news.sources.edgar import default_fetch_fn
    calls = []
    ticks = iter(clock or [0.0] * 50)

    def opener(request, timeout=None):
        calls.append({"url": request.full_url, "timeout": timeout,
                      "ua": request.get_header("User-agent")})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    return default_fetch_fn, opener, calls, (slept if slept is not None else []), ticks


def test_the_declared_rate_limit_constants_are_actually_used():
    """Regression: they were declared and documented but never loaded."""
    import ast
    import pathlib

    from src.news.sources import edgar

    tree = ast.parse(pathlib.Path(edgar.__file__).read_text(encoding="utf-8"))
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    for name in ("REQUESTS_PER_SECOND", "TIMEOUT_SECONDS", "MAX_RETRIES"):
        assert name in loaded, f"{name} is declared but never used"


def test_the_documented_timeout_is_passed_to_the_transport():
    from src.news.sources import edgar

    fn, opener, calls, slept, ticks = policy_fetch([b'{"ok": true}'])
    fn("https://data.sec.gov/submissions/CIK0000320193.json", "AI someone@example.com",
       opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert calls[0]["timeout"] == edgar.TIMEOUT_SECONDS


def test_the_contact_header_is_sent():
    fn, opener, calls, slept, ticks = policy_fetch([b'{"ok": true}'])
    fn("https://data.sec.gov/x.json", "AI-Market-Analysis someone@example.com",
       opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert calls[0]["ua"] == "AI-Market-Analysis someone@example.com"


def test_requests_are_paced_to_the_documented_rate():
    from src.news.sources import edgar

    edgar._LAST_REQUEST[0] = 0.0
    fn, opener, calls, slept, ticks = policy_fetch([b'{"a":1}'], clock=[0.1, 0.1])
    fn("https://data.sec.gov/x.json", "AI someone@example.com",
       opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert slept, "no throttle delay was applied"
    assert slept[0] <= 1.0 / edgar.REQUESTS_PER_SECOND


def test_a_transient_failure_is_retried_at_most_twice_with_backoff():
    from src.news.sources import edgar

    edgar._LAST_REQUEST[0] = 0.0
    responses = [OSError("boom"), OSError("boom"), b'{"ok": true}']
    fn, opener, calls, slept, ticks = policy_fetch(responses, clock=[0.0] * 10)
    result = fn("https://data.sec.gov/x.json", "AI someone@example.com",
                opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert result == {"ok": True}
    assert len(calls) == 3, "should be one attempt plus two retries"
    backoffs = [s for s in slept if s >= 1.0]
    assert backoffs == sorted(backoffs) and len(backoffs) == 2


def test_retries_are_bounded_and_then_fail():
    from src.news.sources import edgar

    edgar._LAST_REQUEST[0] = 0.0
    responses = [OSError("boom")] * (edgar.MAX_RETRIES + 1)
    fn, opener, calls, slept, ticks = policy_fetch(responses, clock=[0.0] * 10)
    with pytest.raises(SourceError) as info:
        fn("https://data.sec.gov/x.json", "AI someone@example.com",
           opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert info.value.outcome is SourceOutcome.FAILED
    assert len(calls) == edgar.MAX_RETRIES + 1


@pytest.mark.parametrize("code", [403, 429])
def test_a_refusal_stops_immediately_without_retrying(code):
    """Retrying into a block is how a client gets banned."""
    import urllib.error

    from src.news.sources import edgar

    edgar._LAST_REQUEST[0] = 0.0
    error = urllib.error.HTTPError("https://data.sec.gov/x", code, "no", {}, None)
    fn, opener, calls, slept, ticks = policy_fetch([error], clock=[0.0] * 10)
    with pytest.raises(SourceError) as info:
        fn("https://data.sec.gov/x.json", "AI someone@example.com",
           opener=opener, sleep=slept.append, now=lambda: next(ticks))
    assert info.value.outcome is SourceOutcome.RATE_LIMITED
    assert len(calls) == 1, "a refusal must not be retried"


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example.com/x.json",
        "http://data.sec.gov/x.json",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "",
    ],
)
def test_only_configured_sec_endpoints_may_be_fetched(url):
    """A URL that reached the fetcher from anywhere else is refused first."""
    from src.news.sources import edgar

    edgar._LAST_REQUEST[0] = 0.0

    def opener(request, timeout=None):  # pragma: no cover - must not run
        raise AssertionError("a connection was attempted")

    with pytest.raises(SourceError):
        edgar.default_fetch_fn(url, "AI someone@example.com", opener=opener,
                               sleep=lambda s: None, now=lambda: 0.0)


# -- no hidden inference may creep into symbol association --------------


@pytest.mark.parametrize(
    "headline",
    [
        "Apple hits a record high",
        "AAPL surges after results",
        "Amazon, Apple and Alphabet all gain",
        "Tesla and Nvidia lead the market",
    ],
)
def test_the_association_symbol_is_the_queried_one_never_the_headline(headline):
    """Regression: a headline matcher survived the mutation campaign.

    The symbol on a link must come from the query and nothing else. Deriving it
    from the text would be the inference this layer refuses to make -- and it
    would be wrong exactly when it looked most convincing, because a story
    naming several companies is not "about" any one of them.
    """
    record = yahoo_source([yahoo_item(title=headline)]).fetch_for_symbol("MSFT", now=NOW)[0]
    link = record.links[0]
    assert link.symbol == "MSFT"
    assert link.queried_symbol == "MSFT"
    assert link.association is SymbolAssociation.QUERIED_SYMBOL


def test_the_yahoo_adapter_never_reads_the_headline_to_choose_a_symbol():
    """Structural: the symbol passed to SymbolLink is the function argument."""
    import ast
    import pathlib

    from src.news.sources import yahoo as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name != "SymbolLink":
            continue
        for keyword in node.keywords:
            if keyword.arg in {"symbol", "queried_symbol"}:
                assert isinstance(keyword.value, ast.Name), (
                    f"{keyword.arg} is computed rather than taken from the query"
                )
                assert keyword.value.id == "symbol", keyword.value.id


def test_no_symbol_is_ever_assigned_from_text_in_the_adapters():
    """No assignment to `symbol` may depend on headline or summary content."""
    import ast
    import pathlib

    for name in ("yahoo.py", "edgar.py"):
        path = pathlib.Path("src/news/sources") / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if "symbol" not in targets:
                    continue
                read = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                assert not (read & {"headline", "summary", "title", "content"}), (
                    f"{name}: symbol is derived from record text"
                )
