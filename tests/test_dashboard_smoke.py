"""Phase 7 Streamlit smoke tests, driven through ``AppTest``.

Deliberately small. These check that the wiring holds together in a real
Streamlit script run -- that the app starts, that nothing is fetched before a
human asks, and above all that a rerun re-renders without re-acting. The
detailed rules live in the application-layer suites, where they can be tested
without a UI framework in the way.

The provider and the clock are injected through session state before the script
runs, so the whole file is offline and deterministic.
"""

from __future__ import annotations

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_application_snapshot import RecordingProvider, clock

APP = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "dashboard" / "app.py")

OPEN_SUBMIT = "FormSubmitter:open_long_form-Open long (paper)"
CLOSE_SUBMIT = "FormSubmitter:close_form-Close position (paper)"


def start(bar_count: int = 80) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(bar_count)
    app.session_state["clock"] = clock
    app.run()
    assert not app.exception, app.exception
    return app


def press(app: AppTest, key: str) -> AppTest:
    for button in app.button:
        if button.key == key:
            return button.click().run()
    raise AssertionError(f"no button with key {key!r}; have {[b.key for b in app.button]}")


def refresh_with(app: AppTest, symbol: str) -> AppTest:
    app.sidebar.text_input(key="symbol_input").set_value(symbol)
    return press(app, "refresh_button")


# -- startup -------------------------------------------------------------


def test_the_app_starts_without_error():
    app = start()
    assert not app.exception
    assert app.title[0].value == "Local research dashboard"


def test_initial_state_is_empty():
    app = start()
    assert app.session_state["snapshot"] is None
    assert app.session_state["failure"] is None
    assert app.session_state["paper"].portfolio.positions == ()


def test_the_symbol_box_starts_empty():
    app = start()
    assert app.sidebar.text_input(key="symbol_input").value == ""


def test_nothing_is_fetched_before_refresh():
    app = start()
    assert app.session_state["provider"].calls == []


def test_typing_a_symbol_does_not_fetch():
    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL").run()
    assert app.session_state["provider"].calls == []
    assert app.session_state["snapshot"] is None


def test_no_company_assessment_is_preloaded():
    app = start()
    headlines = [m.value for m in app.markdown if m.value.startswith("## ")]
    assert headlines == []


def test_refreshing_with_an_empty_symbol_does_not_fetch():
    app = start()
    app = press(app, "refresh_button")
    assert app.session_state["provider"].calls == []
    assert app.session_state["snapshot"] is None
    assert app.session_state["failure"] is not None


# -- a complete refresh --------------------------------------------------


def test_refresh_fetches_once_and_publishes_a_snapshot():
    app = refresh_with(start(), "AAPL")
    assert not app.exception
    assert len(app.session_state["provider"].calls) == 1
    snapshot = app.session_state["snapshot"]
    assert snapshot is not None
    assert snapshot.symbol == "AAPL"
    assert snapshot.bar_count == 80


def test_refresh_requests_settled_bars_only():
    app = refresh_with(start(), "AAPL")
    assert app.session_state["provider"].calls[0]["include_unsettled"] is False


def test_refresh_renders_the_whole_research_view():
    app = refresh_with(start(), "AAPL")
    text = " ".join(
        [m.value for m in app.markdown]
        + [c.value for c in app.caption]
        + [s.value for s in app.subheader]
    )
    for expected in (
        "Market",
        "Features",
        "Research observations",
        "Research assessment",
    ):
        assert expected in text


def test_refresh_shows_a_headline_state_and_the_disclaimer():
    app = refresh_with(start(), "AAPL")
    headlines = [m.value for m in app.markdown if m.value.startswith("## ")]
    assert len(headlines) == 1
    assert headlines[0].removeprefix("## ") in {
        "BULLISH", "BEARISH", "NEUTRAL", "CONFLICTED", "INSUFFICIENT DATA"
    }
    assert any("not a trading recommendation" in i.value for i in app.info)


def test_a_second_refresh_fetches_again():
    app = refresh_with(start(), "AAPL")
    app = press(app, "refresh_button")
    assert len(app.session_state["provider"].calls) == 2


def test_zero_bars_renders_the_no_data_message_without_crashing():
    app = refresh_with(start(0), "AAPL")
    assert not app.exception
    assert any("No data for this symbol and interval." in i.value for i in app.info)


def test_short_history_renders_without_crashing():
    app = refresh_with(start(10), "AAPL")
    assert not app.exception
    assert app.session_state["snapshot"].bar_count == 10


# -- failure atomicity in the UI ----------------------------------------


def test_a_failed_refresh_keeps_the_previous_snapshot_on_screen():
    app = refresh_with(start(), "AAPL")
    good = app.session_state["snapshot"]

    class Broken(RecordingProvider):
        def get_bars(self, *args, **kwargs):
            from src.data.provider import ProviderUnavailableError

            raise ProviderUnavailableError("upstream down")

    app.session_state["provider"] = Broken()
    app = press(app, "refresh_button")

    assert not app.exception
    assert app.session_state["snapshot"] is good
    assert any("Refresh failed at" in e.value for e in app.error)
    assert any("Showing the previous snapshot from" in e.value for e in app.error)


def test_a_failed_first_refresh_shows_no_stale_snapshot_claim():
    class Broken(RecordingProvider):
        def get_bars(self, *args, **kwargs):
            from src.data.provider import ProviderUnavailableError

            raise ProviderUnavailableError("upstream down")

    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = Broken()
    app.session_state["clock"] = clock
    app.run()
    app = refresh_with(app, "AAPL")
    assert app.session_state["snapshot"] is None
    assert not any("Showing the previous snapshot" in e.value for e in app.error)


# -- paper actions: exactly once ----------------------------------------


def submit_open(app: AppTest, symbol: str = "AAPL", notional: str = "1000") -> AppTest:
    app.text_input(key="open_symbol").set_value(symbol)
    app.text_input(key="open_notional").set_value(notional)
    return press(app, OPEN_SUBMIT)


def test_changing_a_widget_applies_no_paper_intent():
    app = start()
    app.text_input(key="open_symbol").set_value("AAPL").run()
    app.text_input(key="open_notional").set_value("1000").run()
    assert app.session_state["paper"].portfolio.positions == ()
    assert app.session_state["paper"].last_decision is None


def test_intent_ids_are_stable_across_ordinary_reruns():
    app = start()
    before = app.session_state["paper"].pending_open_ids()
    app.sidebar.text_input(key="symbol_input").set_value("MSFT").run()
    app.text_input(key="open_symbol").set_value("AAPL").run()
    assert app.session_state["paper"].pending_open_ids() == before


def test_one_submit_opens_exactly_one_position():
    app = submit_open(start())
    assert not app.exception
    portfolio = app.session_state["paper"].portfolio
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].symbol == "AAPL"
    assert app.session_state["paper"].last_decision.approved


def test_an_ordinary_rerun_does_not_repeat_the_approved_action():
    app = submit_open(start())
    assert len(app.session_state["paper"].portfolio.positions) == 1

    for value in ("MSFT", "TSLA", "NVDA"):
        app.sidebar.text_input(key="symbol_input").set_value(value).run()
        assert len(app.session_state["paper"].portfolio.positions) == 1


def test_a_refresh_after_an_action_does_not_repeat_it():
    app = submit_open(start())
    app = refresh_with(app, "AAPL")
    assert len(app.session_state["paper"].portfolio.positions) == 1


def test_a_rejected_submit_creates_no_position():
    app = submit_open(start(), notional="99999999")
    assert app.session_state["paper"].portfolio.positions == ()
    decision = app.session_state["paper"].last_decision
    assert decision is not None and not decision.approved
    assert any("REJECTED" in i.value for i in app.info)


def test_a_rejection_is_not_styled_as_a_crash():
    app = submit_open(start(), notional="99999999")
    assert not app.exception
    assert any("normal outcome" in i.value for i in app.info)


# -- manual close --------------------------------------------------------


def test_the_close_form_is_absent_with_no_open_positions():
    app = start()
    assert CLOSE_SUBMIT not in [b.key for b in app.button]


def test_the_manual_close_workflow():
    app = submit_open(start())
    position_id = app.session_state["paper"].open_positions[0].position_id
    assert CLOSE_SUBMIT in [b.key for b in app.button]

    app = press(app, CLOSE_SUBMIT)
    assert not app.exception
    session = app.session_state["paper"]
    assert session.open_positions == ()
    assert len(session.closed_positions) == 1
    assert session.closed_positions[0].position_id == position_id


def test_closing_removes_the_position_from_the_selector():
    app = submit_open(start())
    app = press(app, CLOSE_SUBMIT)
    assert CLOSE_SUBMIT not in [b.key for b in app.button]


def test_an_ordinary_rerun_does_not_repeat_a_close():
    app = submit_open(start())
    app = press(app, CLOSE_SUBMIT)
    closed_before = len(app.session_state["paper"].closed_positions)
    app.sidebar.text_input(key="symbol_input").set_value("MSFT").run()
    assert len(app.session_state["paper"].closed_positions) == closed_before


# -- panel separation ----------------------------------------------------


def test_the_paper_panel_always_shows_the_session_only_warning():
    app = start()
    assert any(
        "Nothing here is saved to disk" in w.value for w in app.warning
    )


def test_the_research_panel_offers_no_paper_action_control():
    """Every button in the app belongs to the sidebar or the paper forms."""
    app = refresh_with(start(), "AAPL")
    keys = {b.key for b in app.button}
    # refresh_news_button is a Phase 8 sidebar information-refresh control, not
    # a paper action: it fetches news and cannot open or close a position.
    # refresh_feeds_button is the Phase 9 equivalent for external RSS/Atom feeds.
    # reload_universes_button and scan_market_button are the Phase 10 pair on
    # Market Overview. Neither can open or close a position: one re-reads the
    # local universe configuration, the other runs a read-only market scan.
    # All are named individually rather than matched by prefix: the point of
    # this assertion is that every control is accounted for, so a future button
    # must be argued for here rather than admitted by a pattern.
    assert keys <= {
        "refresh_button", "refresh_news_button", "refresh_feeds_button",
        "reload_universes_button", "scan_market_button",
        OPEN_SUBMIT, CLOSE_SUBMIT,
    }


def test_there_is_no_control_for_unsettled_bars_or_basis():
    app = refresh_with(start(), "AAPL")
    labels = [c.label for c in app.checkbox] + [s.label for s in app.selectbox]
    joined = " ".join(labels).lower()
    for forbidden in ("unsettled", "adjusted", "basis", "raw"):
        assert forbidden not in joined


def test_there_is_no_start_date_control():
    app = refresh_with(start(), "AAPL")
    assert not app.date_input


def test_only_the_three_supported_intervals_are_offered():
    app = start()
    options = app.sidebar.selectbox(key="interval_input").options
    assert [str(option) for option in options] == ["1d", "1wk", "1mo"]


# -- importing the entrypoint must not run it ---------------------------


def test_importing_the_app_module_does_not_run_the_app():
    """Regression: a bare import built a provider and rendered every widget.

    Streamlit executes this file as the ``__main__`` module, so the guard keeps
    ``streamlit run`` and ``AppTest`` working (every test above proves it) while
    an ordinary import stays inert.
    """
    import importlib
    import sys

    import streamlit as st

    for name in ("src.dashboard.app",):
        sys.modules.pop(name, None)
    st.session_state.clear()

    importlib.import_module("src.dashboard.app")

    assert dict(st.session_state) == {}


def test_the_entrypoint_guards_its_invocation():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(APP).read_text())
    top_level_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert not top_level_calls, "the entrypoint calls something at import time"


# -- a normal research state must never be styled as a fault ------------


def test_insufficient_data_is_shown_as_information_not_as_an_error():
    """Regression: ``INSUFFICIENT_DATA`` is a research state, not a failure.

    Ten bars is a genuine shortage of history. The panel must explain it with
    ``st.info``; rendering it through ``st.error`` would tell a beginner the
    dashboard is broken when it is working exactly as designed.
    """
    app = refresh_with(start(10), "AAPL")
    assert not app.exception

    infos = " ".join(i.value for i in app.info)
    errors = " ".join(e.value for e in app.error)

    assert "could classify" in infos
    assert "settled bars" in infos
    assert "could classify" not in errors
    assert errors == "", f"a normal research state was rendered as an error: {errors}"


def test_zero_bars_is_also_not_an_error():
    app = refresh_with(start(0), "AAPL")
    assert not app.exception
    assert "".join(e.value for e in app.error) == ""


def test_a_genuine_provider_failure_does_use_an_error():
    """The contrast that gives the rule meaning."""

    class Broken(RecordingProvider):
        def get_bars(self, *args, **kwargs):
            from src.data.provider import ProviderUnavailableError

            raise ProviderUnavailableError("upstream down")

    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = Broken()
    app.session_state["clock"] = clock
    app.run()
    app = refresh_with(app, "AAPL")
    assert any("Refresh failed at" in e.value for e in app.error)


# -- the news panel must actually work in the real app ------------------


class _FakeNewsService:
    """Stands in for the real service without touching a network."""

    def __init__(self):
        self.calls: list[str] = []

    def refresh(self, symbol):
        from datetime import datetime, timezone

        from src.application.news import NewsSnapshot, RefreshStatus
        from src.news.source import IngestionCounters, SourceOutcome, SourceResult

        self.calls.append(symbol)
        return NewsSnapshot(
            symbol=symbol,
            built_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            documents=(), links=(),
            source_results=(SourceResult("yahoo", SourceOutcome.NO_ITEMS,
                                         IngestionCounters()),),
            status=RefreshStatus.ALL_OK,
        )


def test_the_news_panel_builds_a_service_when_none_was_injected(monkeypatch):
    """Regression: the app never built one, so News Refresh always failed.

    Every application-layer test injected a service, so the missing production
    wiring was invisible until the real app was driven.
    """
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)

    app = start()
    assert app.session_state["news_service"] is None, "nothing is built at start-up"

    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_news_button")

    assert app.session_state["news_service"] is not None, "no service was built"
    assert app.session_state["news_failure"] is None
    assert app.session_state["news_snapshot"] is not None
    assert built.calls == ["AAPL"]


def test_opening_the_app_never_builds_or_fetches_news():
    app = start()
    assert app.session_state["news_service"] is None
    assert app.session_state["news_snapshot"] is None
    assert app.session_state["news_failure"] is None


def test_an_ordinary_rerun_never_fetches_news(monkeypatch):
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)

    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_news_button")
    assert built.calls == ["AAPL"]

    for value in ("MSFT", "TSLA"):
        app.sidebar.text_input(key="symbol_input").set_value(value).run()
    assert built.calls == ["AAPL"], "a rerun must not refetch news"


def test_a_market_refresh_never_fetches_news(monkeypatch):
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)
    app = refresh_with(start(), "AAPL")
    assert built.calls == [], "the market Refresh button must not touch news"


def test_a_news_refresh_never_fetches_market_data(monkeypatch):
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)
    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_news_button")
    assert app.session_state["provider"].calls == [], "news refresh fetched bars"
    assert app.session_state["snapshot"] is None


def test_a_news_refresh_never_touches_paper_state(monkeypatch):
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)
    app = start()
    before = app.session_state["paper"].portfolio
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_news_button")
    assert app.session_state["paper"].portfolio is before
    assert app.session_state["paper"].last_decision is None


def test_an_empty_symbol_news_refresh_builds_nothing(monkeypatch):
    built = _FakeNewsService()
    monkeypatch.setattr("src.application.news.build_service", lambda **kw: built)
    app = start()
    app = press(app, "refresh_news_button")
    assert built.calls == []
    assert app.session_state["news_failure"] is not None
