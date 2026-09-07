"""What ``scanner_view`` actually draws, recorded call by call.

The panel is reached through AppTest elsewhere; here the Streamlit module is
replaced by a recorder so a dropped column or a missing empty state is visible
as the absent call it is, rather than as a subtly shorter table.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.application.scanner import MarketScanner
from src.application.snapshot import build_snapshot
from src.application.view_models import SCANNER_EMPTY_HELP, scanner_view
from src.data.models import Interval
from src.dashboard import scanner_view as panel
from src.scanner.universe import build_universe
from tests.test_application_snapshot import RecordingProvider

UTC = timezone.utc
T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

LOCKED_CANDIDATE_COLUMNS = {
    "Symbol", "Evidence structure", "Assessment", "Bullish", "Bearish",
    "Neutral", "Why it surfaced", "Latest bar", "Data cutoff",
}
LOCKED_ISSUE_COLUMNS = {
    "Symbol", "Status", "Operational failure", "Detail", "Latest bar", "Data cutoff",
}


class Recorder:
    """Stands in for the ``streamlit`` module and remembers every call."""

    def __init__(self, log=None):
        self.log = [] if log is None else log

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.log.append((name, args, kwargs))
            if name == "columns":
                return [Recorder(self.log) for _ in range(args[0])]
            return Recorder(self.log)

        return call

    def names(self):
        return [name for name, _, _ in self.log]

    def args_of(self, name):
        return [args for called, args, _ in self.log if called == name]

    def text(self):
        return " ".join(
            str(arg) for _, args, _ in self.log for arg in args if isinstance(arg, str)
        )


@pytest.fixture
def recorder(monkeypatch):
    fake = Recorder()
    monkeypatch.setattr(panel, "st", fake)
    return fake


def view(bars: int = 300, symbols=("AAA", "MMM", "ZZZ")):
    definition, _ = build_universe(
        universe_id="demo", display_name="Example research watchlist",
        symbols=list(symbols), source_kind="local_static",
        source_reference="illustrative research-demo membership",
        as_of=date(2026, 9, 6),
    )

    def build(provider, symbol, interval, *, now):
        return build_snapshot(RecordingProvider(bars), symbol, interval, now=now)

    snapshot = MarketScanner(
        RecordingProvider(bars), build=build, now=lambda: T0
    ).scan(definition, Interval.DAY_1)
    return scanner_view(snapshot)


def test_the_panel_before_any_scan_is_never_blank(recorder):
    panel.render_market_overview(None)
    assert SCANNER_EMPTY_HELP in recorder.text()
    assert "Scan Market" in recorder.text()
    assert "dataframe" not in recorder.names()


def test_the_panel_after_a_scan_draws_the_summary_and_the_table(recorder):
    panel.render_market_overview(view())
    assert "dataframe" in recorder.names()
    assert "Market Overview" in recorder.text()


def test_every_candidate_row_carries_its_own_data_cutoff(recorder):
    scanned = view()
    panel.render_candidate_table(scanned)
    rows = recorder.args_of("dataframe")[0][0]
    assert len(rows) == len(scanned.rows)
    for row in rows:
        assert set(row) == LOCKED_CANDIDATE_COLUMNS
        assert row["Data cutoff"], "a row was drawn with no data cutoff"


def test_every_issue_row_carries_its_own_data_cutoff(recorder):
    scanned = view(bars=0)
    panel.render_issue_table(scanned)
    rows = recorder.args_of("dataframe")[0][0]
    assert len(rows) == len(scanned.issues)
    for row in rows:
        assert set(row) == LOCKED_ISSUE_COLUMNS
        assert row["Data cutoff"], "an issue was drawn with no data cutoff"


def test_the_summary_never_reports_one_market_wide_cutoff(recorder):
    panel.render_scan_summary(view())
    text = recorder.text()
    assert "Each row shows the moment its own data was observed." in text
    assert "market data as of" not in text.lower()


def test_no_data_is_drawn_as_no_data_and_not_as_a_failure(recorder):
    panel.render_market_overview(view(bars=0))
    rows = recorder.args_of("dataframe")[0][0]
    assert all(row["Status"] == "No data" for row in rows)
    assert all(row["Operational failure"] == "no" for row in rows)
    assert "error" not in recorder.names()
