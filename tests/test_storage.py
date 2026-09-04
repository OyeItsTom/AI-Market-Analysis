"""Tests for the local CSV bar store (round-trip, isolation, corruption)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval
from src.data.storage import CsvBarStore, SeriesKey, StorageError
from src.data.validation import ValidationError
from tests.conftest import UTC, make_bar


@pytest.fixture
def store(tmp_path) -> CsvBarStore:
    """A store rooted in a temp dir -- tests never write into data/raw."""
    return CsvBarStore(root=tmp_path / "raw")


KEY = SeriesKey(symbol="AAPL", interval=Interval.DAY_1, source="test")


class TestRoundTrip:
    def test_write_then_read_returns_identical_bars(self, store, bars):
        store.write(bars)
        assert store.read(KEY) == bars

    def test_float_precision_survives_the_round_trip(self, store):
        bar = make_bar(
            open=123.456789012345,
            high=123.999999999999,
            low=123.000000000001,
            close=123.123456789012,
            volume=1234567.891,
        )
        store.write([bar])
        [restored] = store.read(KEY)
        assert restored.open == bar.open
        assert restored.close == bar.close
        assert restored.volume == bar.volume

    def test_timezone_is_preserved_as_utc(self, store):
        eastern = timezone(timedelta(hours=-5))
        bar = make_bar(timestamp=datetime(2024, 1, 2, 9, 30, tzinfo=eastern))
        store.write([bar])
        [restored] = store.read(KEY)
        assert restored.timestamp == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        assert restored.timestamp.tzinfo is timezone.utc

    def test_writing_replaces_the_previous_contents(self, store, bars):
        store.write(bars)
        store.write(bars[:1])
        assert store.read(KEY) == bars[:1]


class TestPathsAndIsolation:
    def test_path_encodes_source_symbol_and_interval(self, store):
        path = store.path_for(KEY)
        assert path.parent.parent.name == "test"
        assert path.parent.name == "AAPL"
        assert path.name == "1d.csv"

    def test_series_from_different_sources_are_stored_separately(self, store, bars):
        store.write(bars)
        store.write([bar.with_source("yfinance") for bar in bars])
        assert store.exists(KEY)
        assert store.exists(SeriesKey("AAPL", Interval.DAY_1, "yfinance"))
        assert len(store.list_series()) == 2

    def test_intervals_are_stored_separately(self, store, bars):
        store.write(bars)
        hourly = [make_bar(interval="1h", timestamp=bar.timestamp) for bar in bars]
        store.write(hourly)
        assert len(store.read(SeriesKey("AAPL", Interval.HOUR_1, "test"))) == 3

    @pytest.mark.parametrize("symbol", ["../etc", "a/b", "..", "AAPL\0"])
    def test_path_traversal_attempts_are_refused(self, store, symbol):
        with pytest.raises(StorageError, match="unsafe path component"):
            store.path_for(SeriesKey(symbol, Interval.DAY_1, "test"))

    def test_listing_an_empty_root_returns_nothing(self, store):
        assert store.list_series() == []


class TestReadFiltering:
    def test_reads_can_be_clipped_to_a_window(self, store, bars):
        store.write(bars)
        clipped = store.read(KEY, start=bars[1].timestamp, end=bars[1].timestamp)
        assert clipped == [bars[1]]

    def test_naive_window_bounds_are_rejected(self, store, bars):
        store.write(bars)
        with pytest.raises(StorageError, match="timezone-aware"):
            store.read(KEY, start=datetime(2024, 1, 2))


class TestWriteGuards:
    def test_invalid_bars_are_never_persisted(self, store, bars):
        with pytest.raises(ValidationError):
            store.write([*bars, bars[0]])  # duplicate + out of order
        assert not store.exists(KEY)

    def test_mixed_sources_in_one_series_are_refused(self, store, bars):
        mixed = [*bars[:2], bars[2].with_source("yfinance")]
        with pytest.raises(StorageError, match="source"):
            store.write(mixed)

    def test_empty_write_requires_an_explicit_key(self, store):
        with pytest.raises(StorageError, match="cannot infer a series key"):
            store.write([])

    def test_empty_write_with_a_key_creates_an_empty_series(self, store):
        store.write([], key=KEY)
        assert store.read(KEY) == []


class TestMerge:
    def test_merge_appends_new_bars(self, store, bars):
        store.write(bars[:2])
        store.merge(bars[2:])
        assert store.read(KEY) == bars

    def test_merge_deduplicates_identical_overlaps(self, store, bars):
        store.write(bars)
        store.merge(bars[1:])
        assert store.read(KEY) == bars

    def test_merge_refuses_to_pick_a_winner_on_conflict(self, store, bars):
        store.write(bars)
        conflicting = make_bar(timestamp=bars[0].timestamp, close=999.0, high=1000.0)
        with pytest.raises(StorageError, match="conflicting bars"):
            store.merge([conflicting])
        assert store.read(KEY) == bars  # original data untouched

    def test_merge_reorders_late_arriving_bars(self, store, bars):
        store.write(bars[1:])
        store.merge(bars[:1])
        assert store.read(KEY) == bars


class TestProvenance:
    """A stored row must match the series it was filed under.

    ``source`` exists so two providers' data is never treated as
    interchangeable evidence. The write path enforces it; without the same
    check on read, an edited or misplaced file silently rewrites provenance.
    """

    def _tamper(self, store, replacement):
        path = store.path_for(KEY)
        path.write_text(path.read_text(encoding="utf-8").replace(*replacement), encoding="utf-8")

    def test_a_row_claiming_another_source_is_rejected(self, store, bars):
        store.write(bars)
        self._tamper(store, (",test\n", ",yfinance\n"))
        with pytest.raises(StorageError, match="provenance"):
            store.read(KEY)

    def test_a_row_claiming_another_symbol_is_rejected(self, store, bars):
        store.write(bars)
        self._tamper(store, (",AAPL,", ",MSFT,"))
        with pytest.raises(StorageError, match="symbol"):
            store.read(KEY)

    def test_a_row_claiming_another_interval_is_rejected(self, store, bars):
        store.write(bars)
        self._tamper(store, (",1d,", ",1h,"))
        with pytest.raises(StorageError, match="interval"):
            store.read(KEY)

    def test_a_file_moved_into_another_providers_directory_is_rejected(self, store, bars):
        store.write(bars)
        misplaced = SeriesKey("AAPL", Interval.DAY_1, "yfinance")
        target = store.path_for(misplaced)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.path_for(KEY).read_bytes())
        with pytest.raises(StorageError, match="provenance"):
            store.read(misplaced)

    def test_the_error_identifies_the_offending_row(self, store, bars):
        store.write(bars)
        path = store.path_for(KEY)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[2] = lines[2].replace(",test", ",yfinance")  # second data row only
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(StorageError, match="row 3"):
            store.read(KEY)

    def test_an_untampered_series_still_round_trips(self, store, bars):
        store.write(bars)
        assert store.read(KEY) == bars


class TestCorruptedFiles:
    def test_missing_series_raises(self, store):
        with pytest.raises(StorageError, match="no stored series"):
            store.read(KEY)

    def test_missing_columns_are_detected(self, store, bars):
        store.write(bars)
        path = store.path_for(KEY)
        path.write_text("timestamp,close\n2024-01-02T00:00:00+00:00,105.0\n", encoding="utf-8")
        with pytest.raises(StorageError, match="missing column"):
            store.read(KEY)

    def test_a_corrupted_row_is_detected_on_read(self, store, bars):
        store.write(bars)
        path = store.path_for(KEY)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace("105.0", "not-a-number")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(StorageError, match="not a valid bar"):
            store.read(KEY)

    def test_data_edited_into_an_invalid_state_is_caught_on_read(self, store, bars):
        store.write(bars)
        path = store.path_for(KEY)
        text = path.read_text(encoding="utf-8")
        # Push high below low on the first data row.
        text = text.replace("110.0", "1.0", 1)
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValidationError):
            store.read(KEY)

    def test_no_temp_file_is_left_behind(self, store, bars):
        store.write(bars)
        assert list(store.path_for(KEY).parent.glob("*.tmp")) == []
