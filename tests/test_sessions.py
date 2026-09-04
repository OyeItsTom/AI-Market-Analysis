"""Session-gap contract. Exchange-aware classification is DEFERRED."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.data.models import Interval
from src.data.sessions import (
    GapReport,
    ObservedGap,
    SessionStatus,
    TradingCalendar,
    UnknownTradingCalendar,
    find_gaps,
)
from tests.conftest import UTC, make_series


def daily(days):
    """A daily series on the given days of January 2024."""
    closes = [100.0 + index for index in range(len(days))]
    series = make_series(closes)
    bars = [
        bar_with(bar, datetime(2024, 1, day, tzinfo=UTC))
        for bar, day in zip(series.bars, days)
    ]
    return series.with_bars(bars)


def bar_with(bar, timestamp):
    from dataclasses import replace

    return replace(bar, timestamp=timestamp)


class TestObservation:
    def test_a_contiguous_series_has_no_gaps(self):
        assert find_gaps(daily([2, 3, 4])).gaps == ()

    def test_a_missing_day_is_observed(self):
        report = find_gaps(daily([2, 3, 5]))
        assert len(report.gaps) == 1
        assert report.gaps[0].after == datetime(2024, 1, 3, tzinfo=UTC)
        assert report.gaps[0].before == datetime(2024, 1, 5, tzinfo=UTC)

    def test_gap_length_is_reported(self):
        gap = find_gaps(daily([2, 9])).gaps[0]
        assert gap.duration == timedelta(days=7)
        assert gap.missing_intervals == 6

    def test_an_empty_or_single_bar_series_has_no_gaps(self):
        assert find_gaps(make_series([1.0])).gaps == ()


class TestHonestDefault:
    """Without a calendar the answer is UNKNOWN, never a guess."""

    def test_every_gap_is_unknown_by_default(self):
        report = find_gaps(daily([5, 8, 15]))  # a weekend, then a week
        assert {gap.status for gap in report.gaps} == {SessionStatus.UNKNOWN}

    def test_a_weekend_is_not_reported_as_a_missing_session(self):
        # Fri 5 Jan -> Mon 8 Jan 2024. Observed, but NOT confirmed missing.
        report = find_gaps(daily([5, 8]))
        assert len(report.gaps) == 1
        assert report.missing_sessions == ()

    def test_unclassified_gaps_are_flagged_as_unverified(self):
        report = find_gaps(daily([5, 8]))
        assert report.has_unclassified_gaps is True

    def test_a_clean_series_is_not_falsely_flagged(self):
        assert find_gaps(daily([2, 3, 4])).has_unclassified_gaps is False

    def test_the_report_names_the_calendar_used(self):
        assert "no exchange calendar" in find_gaps(daily([2, 5])).calendar

    def test_nothing_is_filled_in(self):
        series = daily([2, 5])
        before = series.values("close")
        find_gaps(series)
        assert series.values("close") == before
        assert len(series) == 2  # no bar was inserted for the 3rd or 4th


class TestCalendarExtensionPoint:
    def test_a_custom_calendar_can_classify_gaps(self):
        class WeekendAware(TradingCalendar):
            """Illustrative only -- NOT shipped, and not correct for holidays."""

            name = "test-only weekend calendar"

            def classify(self, symbol, interval, after, before):
                spans_weekend = any(
                    (after + timedelta(days=offset)).weekday() >= 5
                    for offset in range(1, (before - after).days)
                )
                return (
                    SessionStatus.NON_TRADING_DAY
                    if spans_weekend
                    else SessionStatus.EXPECTED_SESSION_MISSING
                )

        report = find_gaps(daily([5, 8, 11]), WeekendAware())
        assert report.gaps[0].status is SessionStatus.NON_TRADING_DAY   # Fri -> Mon
        assert report.gaps[1].status is SessionStatus.EXPECTED_SESSION_MISSING  # Mon -> Thu
        assert len(report.missing_sessions) == 1

    def test_the_base_calendar_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            TradingCalendar()  # type: ignore[abstract]

    def test_the_three_statuses_are_distinct_concepts(self):
        assert len({status.value for status in SessionStatus}) == 3
        assert SessionStatus.UNKNOWN is not SessionStatus.NON_TRADING_DAY
        assert SessionStatus.UNKNOWN is not SessionStatus.EXPECTED_SESSION_MISSING


class TestNoInference:
    def test_no_exchange_is_inferred_from_the_symbol(self):
        # Same shape of gap, different tickers -> identical (UNKNOWN) verdict.
        calendar = UnknownTradingCalendar()
        for symbol in ("AAPL", "VOD.L", "7203.T"):
            status = calendar.classify(symbol, Interval.DAY_1,
                                       datetime(2024, 1, 5, tzinfo=UTC),
                                       datetime(2024, 1, 8, tzinfo=UTC))
            assert status is SessionStatus.UNKNOWN
