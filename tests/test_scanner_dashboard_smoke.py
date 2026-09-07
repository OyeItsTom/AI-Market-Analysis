"""Phase 10 Stage F dashboard wiring, driven through the real Streamlit script.

Every application-layer scanner test injects a service or a provider, which is
exactly how a missing piece of production wiring stays invisible: the panel
works perfectly in the tests and does nothing in the app. Phase 8 shipped that
bug once. These tests drive ``src/dashboard/app.py`` itself.

Offline throughout: the provider is seeded into session state before the script
runs, and the universe configuration is pointed at a temporary file, so a real
network call would be a failure rather than a slow test.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_application_snapshot import RecordingProvider, clock

APP = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "dashboard" / "app.py")


def universe_payload(symbols=("AAA", "MMM", "ZZZ"), universe_id="bench", enabled=True):
    return {
        "schema_version": 1,
        "universes": [
            {
                "universe_id": universe_id,
                "display_name": "Test universe",
                "source_kind": "local_static",
                "source_reference": "illustrative test membership",
                "as_of": "2026-09-06",
                "symbols": list(symbols),
                "enabled": enabled,
            }
        ],
    }


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point the application's universe loader at a temporary config."""
    path = tmp_path / "universes.local.json"
    path.write_text(json.dumps(universe_payload()))

    import src.application.scanner as module

    real = module.load_universes
    monkeypatch.setattr(module, "load_universes", lambda p=None: real(str(path)))
    return path


@pytest.fixture
def no_config(tmp_path, monkeypatch):
    import src.application.scanner as module

    real = module.load_universes
    missing = tmp_path / "absent.json"
    monkeypatch.setattr(module, "load_universes", lambda p=None: real(str(missing)))
    return missing


def start(bars: int = 300) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(bars)
    app.session_state["clock"] = clock
    app.run()
    assert not app.exception, app.exception
    return app


def press(app: AppTest, key: str) -> AppTest:
    for button in app.button:
        if button.key == key:
            return button.click().run()
    raise AssertionError(f"no button {key!r}; have {[b.key for b in app.button]}")


def texts(app: AppTest) -> str:
    parts = [e.value for e in app.info] + [e.value for e in app.warning]
    parts += [e.value for e in app.error] + [e.value for e in app.caption]
    parts += [e.value for e in app.markdown]
    return " ".join(str(p) for p in parts)


# -- A. no local configuration -------------------------------------------


def test_the_app_renders_with_no_universe_configuration(no_config):
    app = start()
    assert not app.exception
    assert "universes.local.json" in texts(app)
    assert app.session_state["scan_snapshot"] is None


def test_scan_is_disabled_without_a_configured_universe(no_config):
    app = start()
    scan = [b for b in app.button if b.key == "scan_market_button"]
    assert scan, "the Scan Market button should still be present"
    assert scan[0].disabled, "Scan must be disabled with no universe"


# -- B/E. configured universe and five tabs ------------------------------


def test_a_configured_universe_is_offered(config_file):
    app = start()
    assert [s.key for s in app.selectbox if s.key == "universe_select"]
    assert app.session_state["scan_universe_id"] == "bench"
    assert app.session_state["scan_universes"] is not None


def test_the_dashboard_has_five_tabs_with_market_overview_first(config_file):
    app = start()
    labels = [t.label for t in app.tabs]
    assert labels == ["Market Overview", "Research", "News", "External feeds",
                      "Paper portfolio"]


# -- C/D. manual scanning only -------------------------------------------


def test_opening_the_app_runs_no_scan(config_file):
    app = start()
    assert app.session_state["scan_snapshot"] is None
    assert app.session_state["provider"].calls == []


def test_an_ordinary_rerun_runs_no_scan(config_file):
    app = start()
    app.run()
    assert app.session_state["scan_snapshot"] is None
    assert app.session_state["provider"].calls == []


def test_pressing_scan_market_stores_a_whole_snapshot(config_file):
    app = start()
    app = press(app, "scan_market_button")
    snapshot = app.session_state["scan_snapshot"]
    assert snapshot is not None
    assert len(snapshot.results) == 3
    assert app.session_state["scan_failure"] is None
    assert len(app.session_state["provider"].calls) == 3


def test_a_scan_uses_the_injected_provider(config_file):
    """Otherwise the test would silently exercise the real network path."""
    app = start()
    app = press(app, "scan_market_button")
    assert app.session_state["provider"].calls, "the injected provider was never used"


# -- F/G. results rendering ----------------------------------------------


def test_candidates_are_rendered_after_a_scan(config_file):
    app = start()
    app = press(app, "scan_market_button")
    body = texts(app)
    assert "Research candidates" in body
    assert "Research candidates only" in body        # the disclaimer


def test_no_data_is_shown_separately_from_operational_failures(config_file):
    """The BK live-benchmark case: a symbol with no bars is not a failure."""
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(0)     # no bars for anything
    app.session_state["clock"] = clock
    app.run()
    app = press(app, "scan_market_button")
    snapshot = app.session_state["scan_snapshot"]
    assert snapshot.counters.symbols_no_data == 3
    assert snapshot.counters.symbols_failed == 0
    assert snapshot.status.value == "all_ok"
    body = texts(app)
    assert "Not assessable this scan" in body
    assert "operational failure" in body.lower()


def test_a_scan_of_unassessable_symbols_is_not_reported_as_failure(config_file):
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(0)
    app.session_state["clock"] = clock
    app.run()
    app = press(app, "scan_market_button")
    assert app.session_state["scan_failure"] is None


# -- H/I/J/K/L. the research handoff -------------------------------------


def test_selecting_a_result_and_opening_it_sets_the_research_symbol(config_file):
    app = start()
    app = press(app, "scan_market_button")
    select = [s for s in app.selectbox if s.key == "scan_symbol_select"]
    assert select, "an eligible-result selector should be present"
    chosen = select[0].value
    app = press(app, "open_in_research_button")
    assert not app.exception, app.exception
    assert app.session_state["symbol_input"] == chosen
    assert app.session_state["pending_research_symbol"] is None


def test_the_handoff_survives_a_further_rerun(config_file):
    app = start()
    app = press(app, "scan_market_button")
    app = press(app, "open_in_research_button")
    symbol = app.session_state["symbol_input"]
    app.run()
    assert app.session_state["symbol_input"] == symbol


# -- M/N/O/P. the handoff fetches nothing --------------------------------


def test_opening_in_research_causes_no_further_fetch(config_file):
    app = start()
    app = press(app, "scan_market_button")
    before = len(app.session_state["provider"].calls)
    app = press(app, "open_in_research_button")
    assert len(app.session_state["provider"].calls) == before
    assert app.session_state["snapshot"] is None, "research must stay manual"


def test_opening_in_research_touches_no_news_or_feeds(config_file):
    app = start()
    app = press(app, "scan_market_button")
    app = press(app, "open_in_research_button")
    assert app.session_state["news_snapshot"] is None
    assert app.session_state["news_service"] is None
    assert app.session_state["feed_snapshot"] is None
    assert app.session_state["feed_service"] is None


def test_opening_in_research_does_not_touch_paper_state(config_file):
    app = start()
    before = app.session_state["paper"].portfolio.positions
    app = press(app, "scan_market_button")
    app = press(app, "open_in_research_button")
    assert app.session_state["paper"].portfolio.positions == before
    assert app.session_state["paper_error"] is None


def test_scanning_never_fetches_news_or_feeds(config_file):
    app = start()
    app = press(app, "scan_market_button")
    assert app.session_state["news_snapshot"] is None
    assert app.session_state["feed_snapshot"] is None


# -- reload and snapshot lifecycle ---------------------------------------


def test_reloading_universes_keeps_the_last_good_configuration(config_file):
    app = start()
    good = app.session_state["scan_universes"]
    assert good is not None
    config_file.write_text("{not json")
    app = press(app, "reload_universes_button")
    assert not app.exception
    assert app.session_state["scan_universes"] is good, "last-good config was lost"
    assert "Could not read" in texts(app)
    assert app.session_state["scan_failure"] is None, "a config error is not a scan failure"


def test_a_successful_reload_replaces_the_configuration(config_file):
    app = start()
    config_file.write_text(json.dumps(universe_payload(symbols=("AAA", "BBB"))))
    app = press(app, "reload_universes_button")
    assert app.session_state["scan_universes"].universes[0].symbol_count == 2


def test_a_previous_snapshot_survives_a_failed_scan(config_file, monkeypatch):
    app = start()
    app = press(app, "scan_market_button")
    good = app.session_state["scan_snapshot"]
    assert good is not None

    import src.application.scanner as module

    def boom(self, universe, interval=None, *, progress=None):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(module.MarketScanner, "scan", boom)
    app = press(app, "scan_market_button")
    assert not app.exception
    assert app.session_state["scan_snapshot"] is good, "good data was discarded"
    assert app.session_state["scan_failure"]


def test_the_research_workflow_still_works(config_file):
    """No scanner side effect on ordinary single-symbol research."""
    app = start()
    app.sidebar.text_input(key="symbol_input").set_value("AAPL")
    app = press(app, "refresh_button")
    assert not app.exception
    assert app.session_state["snapshot"] is not None
    assert app.session_state["snapshot"].symbol == "AAPL"


# -- H. wiring the mutation campaign found unguarded ----------------------


class ScriptedProvider(RecordingProvider):
    """A provider with a different answer per symbol.

    ``RecordingProvider`` gives every symbol the same bars, which cannot express
    the case that matters most here: one scan holding assessable symbols, quiet
    symbols and an operational failure at the same time.
    """

    def __init__(self, script: dict, default: int = 300):
        super().__init__(default)
        self.script = script

    def get_bars(self, symbol, start, end, interval=None, **kwargs):
        action = self.script.get(str(symbol).strip().upper(), self.count)
        if isinstance(action, BaseException):
            self.calls.append({"symbol": symbol, "raised": type(action).__name__})
            raise action
        self.count = action
        return super().get_bars(symbol, start, end, interval or "1d", **kwargs)


def start_scripted(script: dict) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = ScriptedProvider(script)
    app.session_state["clock"] = clock
    app.run()
    assert not app.exception, app.exception
    return app


def rewrite(path: pathlib.Path, **overrides) -> None:
    path.write_text(json.dumps(universe_payload(**overrides)))


def test_a_partial_scan_is_a_result_and_not_a_scan_failure(config_file):
    """PARTIAL describes the symbols. The scan itself succeeded."""
    app = press(start_scripted({"MMM": RuntimeError("provider down")}),
                "scan_market_button")
    snapshot = app.session_state["scan_snapshot"]
    assert snapshot is not None
    assert snapshot.status.value == "partial"
    assert snapshot.counters.symbols_failed == 1
    assert app.session_state["scan_failure"] is None, (
        "a partial scan was reported as a failed scan"
    )


def test_a_successful_scan_clears_an_earlier_scan_failure(config_file):
    app = start()
    app.session_state["scan_failure"] = "Market scan failed: RuntimeError: earlier"
    app = press(app.run(), "scan_market_button")
    assert app.session_state["scan_snapshot"] is not None
    assert app.session_state["scan_failure"] is None, "a stale failure outlived its scan"


def test_the_configuration_is_read_once_and_not_on_every_rerun(config_file, monkeypatch):
    import src.application.scanner as module

    reads = []
    real = module.load_universes
    monkeypatch.setattr(module, "load_universes",
                        lambda p=None: (reads.append(1), real(str(config_file)))[1])

    app = start()
    assert len(reads) == 1
    press(app, "scan_market_button")
    assert len(reads) == 1, "the config file is re-read on every rerun"


def test_reload_re_reads_the_file_on_demand(config_file, monkeypatch):
    import src.application.scanner as module

    reads = []
    real = module.load_universes
    monkeypatch.setattr(module, "load_universes",
                        lambda p=None: (reads.append(1), real(str(config_file)))[1])

    press(start(), "reload_universes_button")
    assert len(reads) == 2, "Reload did not re-read the configuration"


def test_results_for_a_different_universe_say_so(config_file):
    app = press(start(), "scan_market_button")
    assert app.session_state["scan_snapshot"] is not None
    rewrite(config_file, universe_id="other")
    app = press(app, "reload_universes_button")
    assert "Press Scan Market" in texts(app), (
        "results from another universe were shown without a warning"
    )


def test_a_changed_universe_membership_is_reported_against_old_results(config_file):
    app = press(start(), "scan_market_button")
    rewrite(config_file, symbols=("AAA", "MMM", "ZZZ", "QQQ"))
    app = press(app, "reload_universes_button")
    assert "has changed since this scan" in texts(app), (
        "a stale fingerprint was shown as current"
    )


def test_only_assessable_results_are_offered_for_research(config_file):
    app = press(start_scripted({"MMM": 0, "ZZZ": RuntimeError("down")}),
                "scan_market_button")
    chooser = [s for s in app.selectbox if s.key == "scan_symbol_select"]
    assert chooser, "no research chooser was rendered"
    assert list(chooser[0].options) == ["AAA"], (
        "a symbol with nothing to assess was offered for research"
    )


def test_a_selection_that_no_longer_exists_is_reset(config_file):
    app = press(start_scripted({}), "scan_market_button")
    for box in app.selectbox:
        if box.key == "scan_symbol_select":
            app = box.select("ZZZ").run()
    assert app.session_state["scan_symbol_select"] == "ZZZ"

    app.session_state["provider"] = ScriptedProvider({"ZZZ": 0})
    app = press(app.run(), "scan_market_button")
    chooser = [s for s in app.selectbox if s.key == "scan_symbol_select"][0]
    assert "ZZZ" not in chooser.options
    assert chooser.value in chooser.options, "a stale selection survived the new scan"


# -- I. F9 regressions: gaps a fresh mutation campaign found --------------


def test_choosing_a_different_universe_fetches_nothing(config_file):
    """Selecting is not scanning. Only the button scans."""
    payload = universe_payload()
    payload["universes"].append({
        "universe_id": "second", "display_name": "Second universe",
        "source_kind": "local_static", "source_reference": "illustrative test membership",
        "as_of": "2026-09-06", "symbols": ["AAA"], "enabled": True,
    })
    config_file.write_text(json.dumps(payload))

    app = press(start(), "reload_universes_button")
    before = len(app.session_state["provider"].calls)
    chooser = [s for s in app.selectbox if s.key == "universe_select"][0]
    other = [o for o in chooser.options if o != chooser.value][0]
    app = chooser.select(other).run()

    assert app.session_state["scan_universe_id"] == "second"
    assert len(app.session_state["provider"].calls) == before, (
        "changing the universe started a scan"
    )
    assert app.session_state["scan_snapshot"] is None


def test_the_scan_uses_daily_bars_whatever_research_is_set_to(config_file):
    """Market Overview is daily-only; the Research interval must not leak in.

    ``SCANNER_INTERVALS`` is ``(DAY_1,)``, so a scan that passed the Research
    interval through would not merely differ -- it would fail outright once the
    sidebar was set to weekly.
    """
    from src.data.models import Interval

    app = start()
    for box in app.selectbox:
        if box.key == "interval_input":
            app = box.select(Interval.WEEK_1).run()
    assert app.session_state["interval_input"] is Interval.WEEK_1

    app = press(app, "scan_market_button")
    snapshot = app.session_state["scan_snapshot"]
    assert snapshot is not None, app.session_state["scan_failure"]
    assert snapshot.interval is Interval.DAY_1
    assert app.session_state["scan_failure"] is None
    intervals = {str(c["interval"]) for c in app.session_state["provider"].calls}
    assert intervals == {str(Interval.DAY_1)}, intervals


def test_an_all_failed_scan_is_a_result_not_a_scan_failure(config_file):
    """ALL_FAILED describes every symbol. The scan itself still completed."""
    app = press(start_scripted({
        "AAA": RuntimeError("down"), "MMM": RuntimeError("down"),
        "ZZZ": RuntimeError("down"),
    }), "scan_market_button")

    snapshot = app.session_state["scan_snapshot"]
    assert snapshot is not None
    assert snapshot.status.value == "all_failed"
    assert snapshot.counters.symbols_failed == 3
    assert app.session_state["scan_failure"] is None, (
        "an all-failed scan was reported as a failed scan"
    )
    # Nothing is assessable, so nothing is offered for research.
    assert not [s for s in app.selectbox if s.key == "scan_symbol_select"]
    assert not [b for b in app.button if b.key == "open_in_research_button"]
