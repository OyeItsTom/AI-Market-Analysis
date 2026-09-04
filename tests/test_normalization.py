"""Tests for vendor-record -> MarketBar normalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval
from zoneinfo import ZoneInfo

from src.data.normalization import (
    NormalizationError,
    bars_from_records,
    coerce_timestamp,
    is_missing,
)
from src.data.validation import ValidationError, validate_bars
from tests.conftest import UTC

EASTERN = timezone(timedelta(hours=-5))


def record(**overrides):
    base = {
        "Date": datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        "Open": 100.0,
        "High": 110.0,
        "Low": 95.0,
        "Close": 105.0,
        "Volume": 1_000,
    }
    base.update(overrides)
    return base


class TestCoerceTimestamp:
    def test_accepts_aware_datetime_and_converts_to_utc(self):
        result = coerce_timestamp(datetime(2024, 1, 2, 9, 30, tzinfo=EASTERN))
        assert result == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        assert result.tzinfo is timezone.utc

    def test_accepts_iso_strings(self):
        assert coerce_timestamp("2024-01-02T14:30:00+00:00") == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_naive_timestamp_is_refused_by_default(self):
        with pytest.raises(NormalizationError, match="timezone-naive"):
            coerce_timestamp(datetime(2024, 1, 2, 9, 30))

    def test_naive_timestamp_localized_only_when_explicitly_configured(self):
        result = coerce_timestamp(datetime(2024, 1, 2, 9, 30), assume_timezone=EASTERN)
        assert result == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_unparseable_values_raise(self):
        with pytest.raises(NormalizationError):
            coerce_timestamp("not-a-date")
        with pytest.raises(NormalizationError):
            coerce_timestamp(object())


class TestDaylightSavingEdges:
    """Naive local times around a DST transition must never be guessed."""

    NY = ZoneInfo("America/New_York")

    def test_a_normal_local_time_is_converted(self):
        assert coerce_timestamp(
            datetime(2024, 6, 3, 9, 30), assume_timezone=self.NY
        ) == datetime(2024, 6, 3, 13, 30, tzinfo=UTC)

    def test_an_ambiguous_local_time_is_refused(self):
        # 01:30 on 2024-11-03 happens twice in New York.
        with pytest.raises(NormalizationError, match="ambiguous"):
            coerce_timestamp(datetime(2024, 11, 3, 1, 30), assume_timezone=self.NY)

    def test_a_nonexistent_local_time_is_refused(self):
        # 02:30 on 2024-03-10 never happens in New York.
        with pytest.raises(NormalizationError, match="does not exist"):
            coerce_timestamp(datetime(2024, 3, 10, 2, 30), assume_timezone=self.NY)

    def test_the_two_dst_faults_are_distinguished(self):
        with pytest.raises(NormalizationError) as ambiguous:
            coerce_timestamp(datetime(2024, 11, 3, 1, 30), assume_timezone=self.NY)
        with pytest.raises(NormalizationError) as nonexistent:
            coerce_timestamp(datetime(2024, 3, 10, 2, 30), assume_timezone=self.NY)
        assert "does not exist" not in str(ambiguous.value)
        assert "ambiguous" not in str(nonexistent.value)

    def test_a_fixed_offset_timezone_has_no_dst_edges(self):
        assert coerce_timestamp(
            datetime(2024, 11, 3, 1, 30), assume_timezone=EASTERN
        ) == datetime(2024, 11, 3, 6, 30, tzinfo=UTC)


class TestSkipIncompleteIsNarrow:
    """``skip_incomplete`` may only ever drop a genuinely absent measurement.

    Anything else -- a schema change, a timezone fault, a malformed value --
    means our assumptions about the vendor are wrong, and silently dropping
    those rows would report an infrastructure failure as "no data".
    """

    def test_a_row_with_no_values_may_be_skipped(self):
        rows = [record(), record(Date=datetime(2024, 1, 3, 14, 30, tzinfo=UTC), Close=float("nan"))]
        assert len(bars_from_records(rows, symbol="AAPL", interval="1d", source="t", skip_incomplete=True)) == 1

    def test_a_none_value_counts_as_missing(self):
        rows = [record(Volume=None)]
        assert bars_from_records(rows, symbol="AAPL", interval="1d", source="t", skip_incomplete=True) == []

    def test_a_missing_column_still_raises(self):
        broken = record()
        del broken["Volume"]
        with pytest.raises(NormalizationError, match="missing required field"):
            bars_from_records([broken], symbol="AAPL", interval="1d", source="t", skip_incomplete=True)

    def test_a_timezone_naive_timestamp_still_raises(self):
        with pytest.raises(NormalizationError, match="timezone-naive"):
            bars_from_records(
                [record(Date=datetime(2024, 1, 2, 9, 30))],
                symbol="AAPL", interval="1d", source="t", skip_incomplete=True,
            )

    def test_a_dst_fault_still_raises(self):
        with pytest.raises(NormalizationError, match="ambiguous"):
            bars_from_records(
                [record(Date=datetime(2024, 11, 3, 1, 30))],
                symbol="AAPL", interval="1d", source="t", skip_incomplete=True,
                assume_timezone=ZoneInfo("America/New_York"),
            )

    def test_a_malformed_timestamp_still_raises(self):
        with pytest.raises(NormalizationError, match="cannot parse timestamp"):
            bars_from_records(
                [record(Date="not-a-date")],
                symbol="AAPL", interval="1d", source="t", skip_incomplete=True,
            )

    def test_an_unexpected_type_still_raises(self):
        with pytest.raises(NormalizationError):
            bars_from_records(
                [record(Close=["105.0"])],
                symbol="AAPL", interval="1d", source="t", skip_incomplete=True,
            )

    def test_an_infinite_price_still_raises(self):
        with pytest.raises(NormalizationError, match="finite"):
            bars_from_records(
                [record(Close=float("inf"))],
                symbol="AAPL", interval="1d", source="t", skip_incomplete=True,
            )

    def test_financially_invalid_bars_pass_through_to_validation(self):
        # high < low is not a *normalization* fault; the bar is built and the
        # validation layer rejects it. It must never be silently dropped here.
        [bar] = bars_from_records(
            [record(High=1.0)], symbol="AAPL", interval="1d", source="t", skip_incomplete=True
        )
        assert bar.high == 1.0
        with pytest.raises(ValidationError):
            validate_bars([bar])

    def test_by_default_a_missing_value_names_the_fields(self):
        with pytest.raises(NormalizationError, match=r"no value for \['close'\]"):
            bars_from_records([record(Close=None)], symbol="AAPL", interval="1d", source="t")


class TestIsMissing:
    @pytest.mark.parametrize("value", [None, float("nan")])
    def test_absent_values(self, value):
        assert is_missing(value) is True

    @pytest.mark.parametrize("value", [0, 0.0, "", 105.0, float("inf")])
    def test_present_values(self, value):
        # 0 and "" are present-but-falsy; infinity is present-but-invalid and
        # must reach the strict path rather than being dropped as "missing".
        assert is_missing(value) is False


class TestBarsFromRecords:
    def test_vendor_column_names_are_mapped(self):
        [bar] = bars_from_records(
            [record()], symbol="AAPL", interval="1d", source="unit-test"
        )
        assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (100.0, 110.0, 95.0, 105.0, 1000.0)
        assert bar.interval is Interval.DAY_1
        assert bar.source == "unit-test"

    def test_short_alpaca_style_keys_are_mapped(self):
        payload = {"t": "2024-01-02T14:30:00+00:00", "o": 100, "h": 110, "l": 95, "c": 105, "v": 12}
        [bar] = bars_from_records([payload], symbol="AAPL", interval="1m", source="unit-test")
        assert bar.close == 105.0
        assert bar.timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_empty_input_yields_no_bars(self):
        assert bars_from_records([], symbol="AAPL", interval="1d", source="unit-test") == []

    def test_missing_field_raises_instead_of_defaulting(self):
        broken = record()
        del broken["Volume"]
        with pytest.raises(NormalizationError, match="volume"):
            bars_from_records([broken], symbol="AAPL", interval="1d", source="unit-test")

    @pytest.mark.parametrize("value", [float("nan"), None])
    def test_incomplete_rows_raise_by_default(self, value):
        with pytest.raises(NormalizationError, match="record 0"):
            bars_from_records(
                [record(Close=value)], symbol="AAPL", interval="1d", source="unit-test"
            )

