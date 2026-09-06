"""Phase 9 dashboard wiring, driven through the real Streamlit script.

Every application-layer feed test injects a service, which is exactly how a
missing piece of production wiring stays invisible: the panel works perfectly in
the tests and does nothing in the app. Phase 8 shipped that bug once already.
These tests drive ``src/dashboard/app.py`` itself and assert on the wiring the
injected-service tests cannot see.

Offline throughout: ``build_service`` is patched, so a real network call would
be a test failure rather than a slow test.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_application_snapshot import RecordingProvider, clock

APP = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "dashboard" / "app.py")
UTC = timezone.utc


def start() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(80)
    app.session_state["clock"] = clock
    app.run()
    assert not app.exception, app.exception
    return app


def press(app: AppTest, key: str) -> AppTest:
    for button in app.button:
        if button.key == key:
            return button.click().run()
    raise AssertionError(f"no button with key {key!r}; have {[b.key for b in app.button]}")


class _FakeFeedService:
    """Stands in for the real service without touching a network."""

    def __init__(self):
        self.calls: list[object] = []

    def refresh(self, source_ids=None):
        from src.application.feeds import FeedSnapshot, RefreshStatus
        from src.feeds.source import IngestionCounters, SourceOutcome, SourceResult

        self.calls.append(source_ids)
        return FeedSnapshot(
            built_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
            items=(), links=(),
            source_results=(
                SourceResult("demo", SourceOutcome.NO_ITEMS, IngestionCounters()),
            ),
            status=RefreshStatus.ALL_OK,
            definitions=(),
        )


@pytest.fixture
def built(monkeypatch):
    service = _FakeFeedService()
    monkeypatch.setattr("src.application.feeds.build_service", lambda **kw: service)
    return service


# -- the wiring actually exists ------------------------------------------


def test_the_feeds_panel_builds_a_service_when_none_was_injected(built):
    """The bug this file exists to catch: a panel that works only in tests."""
    app = start()
    assert app.session_state["feed_service"] is None, "nothing is built at start-up"

    app = press(app, "refresh_feeds_button")

    assert app.session_state["feed_service"] is not None, "no service was built"
    assert app.session_state["feed_failure"] is None
    assert app.session_state["feed_snapshot"] is not None
    assert built.calls == [None], "the refresh must cover every configured feed"


def test_a_feed_refresh_takes_no_symbol(built):
    """Feeds are configured, not searched, so the sidebar symbol is irrelevant."""
    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_feeds_button")
    assert built.calls == [None]


# -- nothing happens until a human asks ----------------------------------


def test_opening_the_app_never_builds_or_fetches_feeds():
    app = start()
    assert app.session_state["feed_service"] is None
    assert app.session_state["feed_snapshot"] is None
    assert app.session_state["feed_failure"] is None


def test_an_ordinary_rerun_never_fetches_feeds(built):
    app = start()
    app = press(app, "refresh_feeds_button")
    assert len(built.calls) == 1
    app.run()  # a rerun, as Streamlit does on any widget interaction
    assert len(built.calls) == 1, "a rerun re-fetched"


def test_a_market_refresh_never_fetches_feeds(built):
    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_button")
    assert built.calls == []
    assert app.session_state["feed_snapshot"] is None


# -- the panels stay out of one another's state --------------------------


def test_a_feed_refresh_never_fetches_market_data(built):
    app = start()
    app = press(app, "refresh_feeds_button")
    assert app.session_state["provider"].calls == []
    assert app.session_state["snapshot"] is None


def test_a_feed_refresh_never_fetches_news(built, monkeypatch):
    news_calls = []
    monkeypatch.setattr(
        "src.application.news.build_service",
        lambda **kw: news_calls.append(1),
    )
    app = start()
    app = press(app, "refresh_feeds_button")
    assert news_calls == []
    assert app.session_state["news_snapshot"] is None


def test_a_feed_refresh_never_touches_paper_state(built):
    app = start()
    before = app.session_state["paper"].portfolio.positions
    app = press(app, "refresh_feeds_button")
    assert app.session_state["paper"].portfolio.positions == before
    assert app.session_state["paper_error"] is None


# -- failure is reported, never raised -----------------------------------


def test_a_service_that_cannot_be_built_is_reported_not_raised(monkeypatch):
    def boom(**kwargs):
        raise ValueError("bad configuration file")

    monkeypatch.setattr("src.application.feeds.build_service", boom)
    app = start()
    app = press(app, "refresh_feeds_button")
    assert not app.exception
    assert app.session_state["feed_failure"]
    assert "external_feeds.local.json" in app.session_state["feed_failure"]


def test_a_failing_refresh_leaves_the_previous_snapshot_in_place(built):
    app = start()
    app = press(app, "refresh_feeds_button")
    good = app.session_state["feed_snapshot"]
    assert good is not None

    def boom(source_ids=None):
        raise RuntimeError("network gone")

    built.refresh = boom
    app = press(app, "refresh_feeds_button")
    assert not app.exception
    assert app.session_state["feed_snapshot"] is good, "a failure discarded good data"
    assert app.session_state["feed_failure"]


# -- the panel renders honestly ------------------------------------------


def test_the_unconfigured_panel_explains_itself_rather_than_erroring(built):
    app = start()
    app = press(app, "refresh_feeds_button")
    text = " ".join(i.value for i in app.info)
    assert "external_feeds.local.json" in text
    assert not app.error
