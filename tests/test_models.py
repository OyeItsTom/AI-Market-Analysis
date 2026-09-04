"""Tests for MarketBar and Interval (structural invariants)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval, MarketBar
from tests.conftest import UTC, make_bar


class TestMarketBarCreation:
    def test_valid_bar_keeps_its_values(self):
        bar = make_bar()
        assert bar.symbol == "AAPL"
        assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 110.0, 95.0, 105.0)
        assert bar.volume == 1_000.0
        assert bar.interval is Interval.DAY_1
        assert bar.source == "test"

    def test_symbol_is_stripped_and_upper_cased(self):
        assert make_bar(symbol="  aapl ").symbol == "AAPL"

    def test_integer_inputs_become_floats(self):
        bar = make_bar(open=100, high=110, low=95, close=105, volume=10)
        assert all(isinstance(value, float) for value in (bar.open, bar.high, bar.low, bar.close, bar.volume))

    def test_bar_is_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            make_bar().close = 1.0  # type: ignore[misc]

    @pytest.mark.parametrize("symbol", ["", "   "])
    def test_empty_symbol_is_rejected(self, symbol):
        with pytest.raises(ValueError, match="symbol"):
            make_bar(symbol=symbol)

    @pytest.mark.parametrize("field", ["symbol", "source"])
    def test_non_string_text_fields_are_rejected(self, field):
        with pytest.raises(TypeError):
            make_bar(**{field: 123})

    def test_empty_source_is_rejected(self):
        with pytest.raises(ValueError, match="source"):
            make_bar(source="  ")


class TestTimestamps:
    def test_naive_timestamp_is_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            make_bar(timestamp=datetime(2024, 1, 2, 14, 30))

    def test_aware_timestamp_is_converted_to_utc(self):
        eastern = timezone(timedelta(hours=-5))
        bar = make_bar(timestamp=datetime(2024, 1, 2, 9, 30, tzinfo=eastern))
        assert bar.timestamp.tzinfo is timezone.utc
        assert bar.timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_timestamp_is_a_plain_datetime_not_a_vendor_subclass(self):
        class VendorTimestamp(datetime):
            """Stands in for pandas.Timestamp, which subclasses datetime."""

        vendor_value = VendorTimestamp(2024, 1, 2, 14, 30, tzinfo=UTC)
        bar = make_bar(timestamp=vendor_value)
        assert type(bar.timestamp) is datetime
        assert bar.timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_non_datetime_timestamp_is_rejected(self):
        with pytest.raises(TypeError):
            make_bar(timestamp="2024-01-02T00:00:00+00:00")


class TestNumericGuards:
    @pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
    def test_nan_is_rejected(self, field):
        with pytest.raises(ValueError, match="finite"):
            make_bar(**{field: float("nan")})

    @pytest.mark.parametrize("value", [float("inf"), float("-inf")])
    def test_infinity_is_rejected(self, value):
        with pytest.raises(ValueError, match="finite"):
            make_bar(close=value)

    @pytest.mark.parametrize("value", ["100.0", None, [1.0]])
    def test_non_numeric_prices_are_rejected(self, value):
        with pytest.raises(TypeError):
            make_bar(open=value)

    def test_bool_is_not_accepted_as_a_price(self):
        with pytest.raises(TypeError):
            make_bar(open=True)


class TestInterval:
    def test_parses_known_strings(self):
        assert Interval.parse("1d") is Interval.DAY_1
        assert Interval.parse(" 1m ") is Interval.MINUTE_1
        assert Interval.parse(Interval.HOUR_1) is Interval.HOUR_1

    def test_unknown_interval_is_rejected_not_invented(self):
        with pytest.raises(ValueError, match="unsupported interval"):
            Interval.parse("1day")

    def test_bar_normalizes_interval_strings(self):
        assert make_bar(interval="1h").interval is Interval.HOUR_1

    @pytest.mark.parametrize(
        ("interval", "expected"),
        [("1m", timedelta(minutes=1)), ("1h", timedelta(hours=1)), ("1d", timedelta(days=1))],
    )
    def test_max_duration_is_exact_for_fixed_intervals(self, interval, expected):
        assert Interval.parse(interval).max_duration == expected

    @pytest.mark.parametrize(("interval", "floor"), [("1wk", 7), ("1mo", 31)])
    def test_max_duration_over_estimates_calendar_intervals(self, interval, floor):
        # Must be an UPPER bound: under-estimating would let an in-progress bar
        # be mistaken for a settled one.
        assert Interval.parse(interval).max_duration >= timedelta(days=floor)

    def test_every_interval_has_a_duration(self):
        assert all(i.max_duration > timedelta(0) for i in Interval)


class TestTimestampConvention:
    """The canonical convention: timestamp == bar OPEN time (period start).

    Nothing in the data reveals which convention a vendor used, so this is a
    system invariant every adapter must honour. These tests pin the meaning
    that the rest of the system (completeness, ordering) relies on.
    """

    def test_a_bar_covers_the_period_that_starts_at_its_timestamp(self):
        bar = make_bar(timestamp=datetime(2024, 1, 2, 14, 30, tzinfo=UTC), interval="1h")
        period_start = bar.timestamp
        period_end = bar.timestamp + bar.interval.max_duration
        assert period_start == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        assert period_end == datetime(2024, 1, 2, 15, 30, tzinfo=UTC)

    def test_consecutive_bars_are_spaced_by_one_interval(self):
        first = make_bar(timestamp=datetime(2024, 1, 2, 14, 30, tzinfo=UTC), interval="1h")
        second = make_bar(timestamp=datetime(2024, 1, 2, 15, 30, tzinfo=UTC), interval="1h")
        assert second.timestamp - first.timestamp == first.interval.max_duration

    def test_the_invariant_is_documented_for_future_adapter_authors(self):
        # Cheap, but it is the only executable guard against the invariant
        # being silently dropped from the model that defines it.
        import src.data.models as models

        assert "bar open time" in (models.MarketBar.__doc__ or "").lower()
        assert "open time" in (models.__doc__ or "").lower()


class TestSerialization:
    def test_round_trip_through_dict(self):
        bar = make_bar(open=123.456789, volume=987654.0)
        restored = MarketBar.from_dict(bar.to_dict())
        assert restored == bar

    def test_to_dict_is_plain_types(self):
        payload = make_bar().to_dict()
        assert payload["interval"] == "1d"
        assert isinstance(payload["timestamp"], str)
        assert all(isinstance(payload[key], float) for key in ("open", "high", "low", "close", "volume"))

    def test_with_source_returns_a_retagged_copy(self):
        bar = make_bar(source="test")
        retagged = bar.with_source("yfinance")
        assert retagged.source == "yfinance"
        assert bar.source == "test"
        assert math.isclose(retagged.close, bar.close)
