"""Phase 8 causality: never claiming information was available before it was.

This is the release-critical suite. A news layer that lets a story be visible
before it existed would quietly invalidate every study built on top of it, and
the failure leaves no trace in the numbers.

Three facts are kept apart throughout, and these tests exist to prove they stay
apart: what a source *said*, what this system *observed*, and what can be
*defended* as available.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.news import (
    QueryMode,
    TrustMode,
    filter_documents,
    order_documents,
)
from src.news.models import (
    AvailabilityBasis,
    NewsItem,
    OfficialFiling,
    SourceClass,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
YEAR_2024 = datetime(2024, 3, 1, 15, 0, tzinfo=UTC)


def news(**overrides) -> NewsItem:
    fields = dict(
        source="yahoo",
        source_item_id="n1",
        source_class=SourceClass.SECONDARY_NEWS,
        publisher="Reuters",
        headline="A headline",
        canonical_url="https://example.com/a",
        retrieved_at=NOW,
        availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
        source_published_at=NOW - timedelta(hours=2),
        available_from=NOW - timedelta(hours=2),
    )
    fields.update(overrides)
    return NewsItem(**fields)


def filing(**overrides) -> OfficialFiling:
    fields = dict(
        source="edgar",
        source_item_id="f1",
        source_class=SourceClass.OFFICIAL_FILING,
        cik="0000320193",
        form="8-K",
        headline="8-K",
        canonical_url="https://www.sec.gov/x/",
        primary_document_url="https://www.sec.gov/x/d.htm",
        retrieved_at=NOW,
        availability_basis=AvailabilityBasis.SOURCE_EVENT,
        source_event_time=NOW - timedelta(days=1),
        available_from=NOW - timedelta(days=1),
    )
    fields.update(overrides)
    return OfficialFiling(**fields)


# -- the acceptance instant is a bound, not a proof ----------------------


def test_edgar_acceptance_is_recorded_as_a_source_event_not_a_publication():
    """Acceptance proves the SEC received it, not that anyone could read it."""
    record = filing()
    assert record.availability_basis is AvailabilityBasis.SOURCE_EVENT
    assert record.availability_basis is not AvailabilityBasis.SOURCE_PUBLISHED
    assert record.source_event_time == record.available_from


#: Phrases that would upgrade the SEC's acceptance assertion into a proof.
DISSEMINATION_CLAIMS = (
    "disseminated at",
    "published to the public at",
    "publicly available at",
    "proven dissemination",
)

#: A claim preceded by one of these is a denial, which is the opposite of the
#: problem. Explaining the rule must not be mistaken for breaking it.
NEGATIONS = ("not", "never", "rather than", "no ", "cannot", "does not", "is not")


def _unnegated_claims(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for phrase in DISSEMINATION_CLAIMS:
        start = 0
        while (index := lowered.find(phrase, start)) != -1:
            window = lowered[max(0, index - 80):index]
            if not any(negation in window for negation in NEGATIONS):
                found.append(phrase)
            start = index + len(phrase)
    return found


def test_no_phase_eight_text_claims_acceptance_means_dissemination():
    """Checked with negation awareness: a denial is not a claim."""
    import pathlib

    for path in [
        *pathlib.Path("src/news").rglob("*.py"),
        pathlib.Path("src/application/news.py"),
        pathlib.Path("src/dashboard/news_view.py"),
        pathlib.Path("docs/news.md"),
        pathlib.Path("docs/adr/0006-news-and-announcements.md"),
    ]:
        if not path.is_file():
            continue
        claims = _unnegated_claims(path.read_text(encoding="utf-8"))
        assert not claims, f"{path} claims {claims}"


def test_no_rendered_ui_string_claims_dissemination():
    """The stricter half: every non-docstring string a user could see."""
    import ast
    import pathlib

    for path in [
        *pathlib.Path("src/news").rglob("*.py"),
        pathlib.Path("src/application/news.py"),
        pathlib.Path("src/dashboard/news_view.py"),
        pathlib.Path("src/application/view_models.py"),
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                assert not _unnegated_claims(node.value), f"{path.name}: {node.value[:80]!r}"


# -- publication versus retrieval ---------------------------------------


def test_publication_and_retrieval_are_distinct_fields():
    item = news()
    assert item.source_published_at != item.retrieved_at
    assert item.available_from == item.source_published_at


def test_a_missing_publication_time_never_becomes_the_retrieval_time():
    item = news(
        source_published_at=None,
        available_from=NOW,
        availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
    )
    assert item.source_published_at is None
    assert item.availability_basis is AvailabilityBasis.SYSTEM_OBSERVED


def test_a_late_retrieved_old_article_keeps_its_original_publication():
    item = news(
        source_published_at=YEAR_2024,
        available_from=YEAR_2024,
        retrieved_at=NOW,
    )
    assert item.source_published_at == YEAR_2024
    assert item.retrieved_at == NOW


# -- historical backfill: three facts, never collapsed -------------------


BACKFILLED = filing(
    source_event_time=YEAR_2024,
    available_from=YEAR_2024,
    retrieved_at=NOW,
)


def test_backfill_keeps_the_source_event_in_the_past():
    assert BACKFILLED.source_event_time == YEAR_2024


def test_backfill_keeps_our_observation_in_the_present():
    assert BACKFILLED.retrieved_at == NOW


def test_backfill_claims_no_proven_dissemination():
    assert BACKFILLED.availability_basis is AvailabilityBasis.SOURCE_EVENT


def test_source_asserted_sees_a_backfilled_filing_from_its_source_time():
    visible = filter_documents(
        [BACKFILLED],
        as_of=YEAR_2024 + timedelta(days=1),
        mode=QueryMode.STRICT_CAUSAL,
        trust=TrustMode.SOURCE_ASSERTED,
    )
    assert visible == (BACKFILLED,)


def test_system_observed_does_not_see_it_before_we_retrieved_it():
    """The honest cost of trusting no source: backfilled history is invisible
    until the moment this system actually fetched it."""
    visible = filter_documents(
        [BACKFILLED],
        as_of=YEAR_2024 + timedelta(days=1),
        mode=QueryMode.STRICT_CAUSAL,
        trust=TrustMode.SYSTEM_OBSERVED,
    )
    assert visible == ()


def test_system_observed_sees_it_once_we_have_retrieved_it():
    visible = filter_documents(
        [BACKFILLED],
        as_of=NOW,
        mode=QueryMode.STRICT_CAUSAL,
        trust=TrustMode.SYSTEM_OBSERVED,
    )
    assert visible == (BACKFILLED,)


# -- query modes ---------------------------------------------------------


def test_source_time_mode_asks_only_about_the_source_timestamp():
    early = YEAR_2024 + timedelta(days=1)
    assert filter_documents([BACKFILLED], as_of=early, mode=QueryMode.SOURCE_TIME) == (
        BACKFILLED,
    )


def test_source_time_mode_excludes_records_with_no_source_timestamp():
    item = news(
        source_published_at=None,
        available_from=NOW,
        availability_basis=AvailabilityBasis.SYSTEM_OBSERVED,
    )
    assert filter_documents([item], as_of=NOW, mode=QueryMode.SOURCE_TIME) == ()


def test_strict_causal_excludes_a_future_record():
    future = news(
        source_published_at=NOW + timedelta(hours=5),
        available_from=NOW + timedelta(hours=5),
    )
    assert filter_documents([future], as_of=NOW, mode=QueryMode.STRICT_CAUSAL) == ()


def test_no_future_news_leaks_into_a_historical_window():
    past = news(source_item_id="past", source_published_at=NOW - timedelta(days=2),
                available_from=NOW - timedelta(days=2))
    future = news(source_item_id="future", source_published_at=NOW,
                  available_from=NOW)
    visible = filter_documents(
        [past, future], as_of=NOW - timedelta(days=1), mode=QueryMode.STRICT_CAUSAL
    )
    assert [d.source_item_id for d in visible] == ["past"]


# -- unknown availability is excluded, never guessed ---------------------


UNKNOWN = news(
    source_item_id="unknown",
    source_published_at=None,
    available_from=None,
    availability_basis=AvailabilityBasis.UNKNOWN,
)


@pytest.mark.parametrize("trust", list(TrustMode))
def test_unknown_availability_is_excluded_from_strict_queries(trust):
    assert filter_documents(
        [UNKNOWN], as_of=NOW, mode=QueryMode.STRICT_CAUSAL, trust=trust
    ) == ()


def test_unknown_availability_is_still_listed_when_no_as_of_is_given():
    """Excluded from causal reasoning, not deleted from the record."""
    assert filter_documents([UNKNOWN]) == (UNKNOWN,)


# -- ordering ------------------------------------------------------------


def test_chronology_is_not_distorted_by_source_class():
    """A week-old filing must not outrank this morning's news."""
    old_filing = filing(source_item_id="old", source_event_time=NOW - timedelta(days=7),
                        available_from=NOW - timedelta(days=7))
    fresh_news = news(source_item_id="fresh", source_published_at=NOW - timedelta(hours=1),
                      available_from=NOW - timedelta(hours=1))
    ordered = order_documents([old_filing, fresh_news])
    assert [d.source_item_id for d in ordered] == ["fresh", "old"]


def test_ordering_is_newest_first():
    a = news(source_item_id="a", source_published_at=NOW - timedelta(hours=3),
             available_from=NOW - timedelta(hours=3))
    b = news(source_item_id="b", source_published_at=NOW - timedelta(hours=1),
             available_from=NOW - timedelta(hours=1))
    assert [d.source_item_id for d in order_documents([a, b])] == ["b", "a"]


def test_ties_are_broken_deterministically():
    same = NOW - timedelta(hours=1)
    a = news(source_item_id="zzz", source_published_at=same, available_from=same)
    b = filing(source_item_id="aaa", source_event_time=same, available_from=same)
    first = order_documents([a, b])
    for _ in range(10):
        assert order_documents([b, a]) == first


# -- windows -------------------------------------------------------------


def test_start_and_end_bound_the_window():
    a = news(source_item_id="a", source_published_at=NOW - timedelta(days=5),
             available_from=NOW - timedelta(days=5))
    b = news(source_item_id="b", source_published_at=NOW - timedelta(days=1),
             available_from=NOW - timedelta(days=1))
    selected = filter_documents([a, b], start=NOW - timedelta(days=2))
    assert [d.source_item_id for d in selected] == ["b"]


def test_source_class_filter_selects_official_only():
    selected = filter_documents(
        [news(), filing()], source_class=SourceClass.OFFICIAL_FILING
    )
    assert all(d.source_class.is_official for d in selected)
    assert len(selected) == 1
