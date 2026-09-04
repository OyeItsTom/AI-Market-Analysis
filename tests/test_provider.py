"""Tests for the MarketDataProvider contract.

A tiny in-memory provider stands in for a real adapter, so these tests cover
the guarantees every provider inherits: argument checking, symbol/interval
normalization, and validation of whatever the adapter returns.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

import pytest

from src.data.models import Interval, MarketBar
from src.data.provider import MarketDataProvider
from src.data.validation import IssueCode, ValidationError
from tests.conftest import UTC, corrupt_bar, make_bar

WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 31, tzinfo=UTC)

#: Pinned "now" for tests that do not care about completeness. Well past every
#: fixture, so those bars are unambiguously settled.
LATER = datetime(2025, 1, 1, tzinfo=UTC)


class FakeProvider(MarketDataProvider):
    """Returns a canned response and records the arguments it was given."""

    name = "fake"

    def __init__(self, bars: Sequence[MarketBar] = (), now: datetime = LATER):
        self._bars = list(bars)
        self.calls: list[tuple] = []
        self._pinned_now = now

    def _now(self) -> datetime:
        return self._pinned_now

    def _fetch_bars(self, symbol, start, end, interval) -> Sequence[MarketBar]:
        self.calls.append((symbol, start, end, interval))
        return self._bars


class NarrowProvider(FakeProvider):
    name = "narrow"
    supported_intervals = frozenset({Interval.DAY_1})


class TestRequestValidation:
    def test_symbol_is_normalized_before_reaching_the_adapter(self, bars):
        provider = FakeProvider(bars)
        provider.get_bars(" aapl ", WINDOW_START, WINDOW_END, "1d")
        assert provider.calls[0][0] == "AAPL"

    def test_interval_string_is_parsed_before_reaching_the_adapter(self, bars):
        provider = FakeProvider(bars)
        provider.get_bars("AAPL", WINDOW_START, WINDOW_END, "1d")
        assert provider.calls[0][3] is Interval.DAY_1

    @pytest.mark.parametrize("symbol", ["", "   "])
    def test_empty_symbol_is_rejected(self, symbol):
        with pytest.raises(ValueError, match="symbol"):
            FakeProvider().get_bars(symbol, WINDOW_START, WINDOW_END)

    @pytest.mark.parametrize("field", ["start", "end"])
    def test_naive_window_bounds_are_rejected(self, field):
        window = {"start": WINDOW_START, "end": WINDOW_END, field: datetime(2024, 1, 5)}
        with pytest.raises(ValueError, match="timezone-aware"):
            FakeProvider().get_bars("AAPL", **window)

    def test_reversed_window_is_rejected(self):
        with pytest.raises(ValueError, match="must not be after"):
            FakeProvider().get_bars("AAPL", WINDOW_END, WINDOW_START)

    def test_unknown_interval_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported interval"):
            FakeProvider().get_bars("AAPL", WINDOW_START, WINDOW_END, "1day")

    def test_interval_unsupported_by_this_provider_is_rejected(self):
        with pytest.raises(ValueError, match="does not support interval"):
            NarrowProvider().get_bars("AAPL", WINDOW_START, WINDOW_END, "1m")


class TestResponseGuarantees:
    def test_returns_normalized_bars(self, bars):
        result = FakeProvider(bars).get_bars("AAPL", WINDOW_START, WINDOW_END, "1d")
        assert result == bars
        assert all(isinstance(item, MarketBar) for item in result)

    def test_empty_response_is_allowed_and_is_not_an_error(self):
        assert FakeProvider([]).get_bars("AAPL", WINDOW_START, WINDOW_END) == []

    def test_adapter_returning_corrupt_bars_raises(self):
        broken = corrupt_bar(make_bar(), high=1.0)
        with pytest.raises(ValidationError):
            FakeProvider([broken]).get_bars("AAPL", WINDOW_START, WINDOW_END)

    def test_adapter_returning_the_wrong_symbol_raises(self):
        wrong = [make_bar(symbol="MSFT")]
        with pytest.raises(ValidationError) as excinfo:
            FakeProvider(wrong).get_bars("AAPL", WINDOW_START, WINDOW_END)
        assert any(issue.code is IssueCode.SYMBOL_MISMATCH for issue in excinfo.value.issues)

    def test_adapter_returning_the_wrong_interval_raises(self):
        with pytest.raises(ValidationError) as excinfo:
            FakeProvider([make_bar(interval="1h")]).get_bars("AAPL", WINDOW_START, WINDOW_END, "1d")
        assert any(issue.code is IssueCode.INTERVAL_MISMATCH for issue in excinfo.value.issues)

    def test_adapter_returning_unordered_bars_raises(self, bars):
        with pytest.raises(ValidationError) as excinfo:
            FakeProvider(list(reversed(bars))).get_bars("AAPL", WINDOW_START, WINDOW_END)
        assert any(issue.code is IssueCode.UNORDERED_TIMESTAMP for issue in excinfo.value.issues)


class TestSettledBars:
    """Only bars whose period has provably ended are returned by default.

    Completeness is not stored on the bar: it is a property of the bar
    relative to now, so it is decided at request time from
    ``timestamp + interval``.
    """

    def _daily(self, *days):
        return [make_bar(timestamp=datetime(2024, 1, day, tzinfo=UTC)) for day in days]

    def test_an_in_progress_trailing_bar_is_withheld_by_default(self):
        bars = self._daily(2, 3, 4)
        # Mid-session on the 4th: that bar's period has not ended.
        provider = FakeProvider(bars, now=datetime(2024, 1, 4, 17, 0, tzinfo=UTC))
        result = provider.get_bars("AAPL", WINDOW_START, WINDOW_END)
        assert [bar.timestamp.day for bar in result] == [2, 3]

    def test_it_can_be_requested_explicitly(self):
        bars = self._daily(2, 3, 4)
        provider = FakeProvider(bars, now=datetime(2024, 1, 4, 17, 0, tzinfo=UTC))
        result = provider.get_bars("AAPL", WINDOW_START, WINDOW_END, include_unsettled=True)
        assert [bar.timestamp.day for bar in result] == [2, 3, 4]

    def test_a_bar_is_settled_exactly_when_its_period_has_elapsed(self):
        bar_time = datetime(2024, 1, 2, tzinfo=UTC)
        period_end = bar_time + Interval.DAY_1.max_duration
        assert FakeProvider(self._daily(2), now=period_end).get_bars("AAPL", WINDOW_START, WINDOW_END)
        one_tick_early = period_end - timedelta(microseconds=1)
        assert FakeProvider(self._daily(2), now=one_tick_early).get_bars(
            "AAPL", WINDOW_START, WINDOW_END
        ) == []

    def test_completeness_is_judged_from_the_bar_open_time_plus_the_interval(self):
        # An hourly bar opened at 16:00 is settled at 17:00, not at 16:00+1day.
        bar = make_bar(timestamp=datetime(2024, 1, 2, 16, 0, tzinfo=UTC), interval="1h")
        settled = FakeProvider([bar], now=datetime(2024, 1, 2, 17, 0, tzinfo=UTC))
        assert settled.get_bars("AAPL", WINDOW_START, WINDOW_END, "1h") == [bar]
        unsettled = FakeProvider([bar], now=datetime(2024, 1, 2, 16, 30, tzinfo=UTC))
        assert unsettled.get_bars("AAPL", WINDOW_START, WINDOW_END, "1h") == []

    def test_calendar_intervals_are_never_declared_settled_early(self):
        # A monthly bar opened 2024-01-01 must not be called settled on the 29th.
        bar = make_bar(timestamp=datetime(2024, 1, 1, tzinfo=UTC), interval="1mo")
        provider = FakeProvider([bar], now=datetime(2024, 1, 29, tzinfo=UTC))
        assert provider.get_bars("AAPL", WINDOW_START, WINDOW_END, "1mo") == []

    def test_trimming_never_punches_a_hole_in_the_middle(self):
        bars = self._daily(2, 3, 4)
        provider = FakeProvider(bars, now=datetime(2024, 1, 4, 17, 0, tzinfo=UTC))
        result = provider.get_bars("AAPL", WINDOW_START, WINDOW_END)
        assert result == bars[: len(result)]  # a contiguous prefix, always

    def test_an_all_unsettled_series_returns_empty_not_an_error(self):
        provider = FakeProvider(self._daily(2), now=datetime(2024, 1, 2, 1, 0, tzinfo=UTC))
        assert provider.get_bars("AAPL", WINDOW_START, WINDOW_END) == []


class TestAbstractness:
    def test_the_base_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            MarketDataProvider()  # type: ignore[abstract]

    def test_window_bounds_in_other_zones_are_accepted(self, bars):
        eastern = timezone(timedelta(hours=-5))
        provider = FakeProvider(bars)
        result = provider.get_bars(
            "AAPL",
            WINDOW_START.astimezone(eastern),
            WINDOW_END.astimezone(eastern),
            "1d",
        )
        assert result == bars
