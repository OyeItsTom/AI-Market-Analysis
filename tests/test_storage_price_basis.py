"""Price-basis-aware persistence.

Target invariant: two series differing only in price basis must never share a
storage identity, share a path, overwrite one another, or be returned as
though they were equivalent.
"""

from __future__ import annotations

import csv
from datetime import datetime

import pytest

from src.data.adjustment import AdjustmentData, adjust
from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.data.storage import (
    CSV_COLUMNS,
    REQUIRED_CSV_COLUMNS,
    CsvBarStore,
    SeriesKey,
    StorageError,
)
from tests.conftest import UTC

ADJUSTED = PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
RAW_KEY = SeriesKey("AAPL", Interval.DAY_1, "yfinance")
ADJ_KEY = SeriesKey("AAPL", Interval.DAY_1, "yfinance", ADJUSTED)


@pytest.fixture
def store(tmp_path) -> CsvBarStore:
    return CsvBarStore(root=tmp_path / "raw")


def bar(day: int, close: float) -> MarketBar:
    return MarketBar(
        "AAPL", datetime(2024, 1, day, tzinfo=UTC),
        close, close * 1.1, close * 0.9, close, 1_000.0, "1d", "yfinance",
    )


@pytest.fixture
def raw_series() -> BarSeries:
    return BarSeries.from_bars([bar(2, 400.0), bar(3, 408.0)], basis=PriceBasis.RAW)


@pytest.fixture
def adjusted_series(raw_series) -> BarSeries:
    data = AdjustmentData(
        "AAPL", "yfinance", "1d", ADJUSTED,
        {timestamp: 0.25 for timestamp in raw_series.timestamps},
    )
    return adjust(raw_series, data)


class TestStorageIdentity:
    def test_raw_and_adjusted_keys_are_unequal(self):
        assert RAW_KEY != ADJ_KEY
        assert hash(RAW_KEY) != hash(ADJ_KEY)

    def test_raw_and_adjusted_resolve_to_different_paths(self, store):
        assert store.path_for(RAW_KEY) != store.path_for(ADJ_KEY)

    def test_basis_is_part_of_the_key_not_the_source_string(self):
        # Basis must stay a typed concept; it must never be smuggled into
        # `source` as "yfinance-adjusted".
        assert ADJ_KEY.source == "yfinance"
        assert ADJ_KEY.basis is ADJUSTED

    def test_key_normalisation_preserves_basis(self):
        assert SeriesKey("aapl", "1d", " yfinance ", ADJUSTED).normalized().basis is ADJUSTED

    def test_from_series_carries_the_basis(self, adjusted_series):
        assert SeriesKey.from_series(adjusted_series).basis is ADJUSTED

    def test_from_bar_assumes_raw_because_a_bar_has_no_basis(self):
        assert SeriesKey.from_bar(bar(2, 400.0)).basis is PriceBasis.RAW


class TestNoCollision:
    def test_saving_adjusted_cannot_overwrite_raw(self, store, raw_series, adjusted_series):
        store.write_series(raw_series)
        store.write_series(adjusted_series)
        assert store.read_series(RAW_KEY).values("close") == (400.0, 408.0)

    def test_saving_raw_cannot_overwrite_adjusted(self, store, raw_series, adjusted_series):
        store.write_series(adjusted_series)
        store.write_series(raw_series)
        assert store.read_series(ADJ_KEY).values("close") == (100.0, 102.0)

    def test_both_files_coexist_on_disk(self, store, raw_series, adjusted_series):
        raw_path = store.write_series(raw_series)
        adj_path = store.write_series(adjusted_series)
        assert raw_path.is_file() and adj_path.is_file()
        assert raw_path != adj_path

    def test_exists_distinguishes_the_two(self, store, raw_series):
        store.write_series(raw_series)
        assert store.exists(RAW_KEY) is True
        assert store.exists(ADJ_KEY) is False

    def test_list_series_reports_both_with_their_bases(self, store, raw_series, adjusted_series):
        store.write_series(raw_series)
        store.write_series(adjusted_series)
        assert {key.basis for key in store.list_series()} == {PriceBasis.RAW, ADJUSTED}
        assert len(store.list_series()) == 2


class TestReadRefusesTheWrongBasis:
    def test_requesting_raw_from_an_adjusted_file_fails_loudly(self, store, adjusted_series):
        store.write_series(adjusted_series)
        # Move the adjusted file onto the raw path: the NAME now says raw.
        adjusted_path = store.path_for(ADJ_KEY)
        store.path_for(RAW_KEY).write_bytes(adjusted_path.read_bytes())
        with pytest.raises(StorageError, match="price basis"):
            store.read(RAW_KEY)

    def test_requesting_adjusted_from_a_raw_file_fails_loudly(self, store, raw_series):
        store.write_series(raw_series)
        raw_path = store.path_for(RAW_KEY)
        adjusted_path = store.path_for(ADJ_KEY)
        adjusted_path.write_bytes(raw_path.read_bytes())
        with pytest.raises(StorageError, match="price basis"):
            store.read(ADJ_KEY)

    def test_renaming_alone_cannot_launder_the_basis(self, store, adjusted_series):
        """The file's own metadata is authoritative, not its filename."""
        store.write_series(adjusted_series)
        store.path_for(RAW_KEY).write_bytes(store.path_for(ADJ_KEY).read_bytes())
        with pytest.raises(StorageError) as excinfo:
            store.read(RAW_KEY)
        assert "renaming a file does not change what its numbers mean" in str(excinfo.value)

    def test_the_error_names_both_bases(self, store, adjusted_series):
        store.write_series(adjusted_series)
        store.path_for(RAW_KEY).write_bytes(store.path_for(ADJ_KEY).read_bytes())
        with pytest.raises(StorageError) as excinfo:
            store.read(RAW_KEY)
        assert "split_and_dividend_adjusted" in str(excinfo.value)
        assert "'raw'" in str(excinfo.value)

    def test_an_unknown_basis_value_fails_loudly(self, store, raw_series):
        path = store.write_series(raw_series)
        text = path.read_text(encoding="utf-8").replace(",raw\n", ",total_return\n")
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="unknown price basis"):
            store.read(RAW_KEY)

    def test_a_single_tampered_row_is_enough_to_refuse(self, store, raw_series):
        path = store.write_series(raw_series)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[2] = lines[2].replace(",raw", f",{ADJUSTED.value}")  # second data row only
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(StorageError, match="price basis"):
            store.read(RAW_KEY)


class TestRoundTrip:
    def test_basis_survives_a_round_trip(self, store, adjusted_series):
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).basis is ADJUSTED

    def test_values_survive_a_round_trip_exactly(self, store, adjusted_series):
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).values("close") == adjusted_series.values("close")

    def test_symbol_survives_a_round_trip(self, store, adjusted_series):
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).symbol == "AAPL"

    def test_interval_survives_a_round_trip(self, store, adjusted_series):
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).interval is Interval.DAY_1

    def test_source_survives_a_round_trip(self, store, adjusted_series):
        # The ORIGINAL provider, not a basis-mangled variant.
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).source == "yfinance"

    def test_volume_survives_unadjusted(self, store, adjusted_series):
        store.write_series(adjusted_series)
        assert store.read_series(ADJ_KEY).values("volume") == (1_000.0, 1_000.0)

    def test_read_series_returns_a_usable_barseries(self, store, adjusted_series):
        store.write_series(adjusted_series)
        loaded = store.read_series(ADJ_KEY)
        assert isinstance(loaded, BarSeries)
        loaded.require_compatible(adjusted_series)

    def test_a_reloaded_series_is_not_compatible_with_the_other_basis(
        self, store, raw_series, adjusted_series
    ):
        from src.data.series import SeriesError

        store.write_series(raw_series)
        store.write_series(adjusted_series)
        with pytest.raises(SeriesError, match="basis"):
            store.read_series(RAW_KEY).require_compatible(store.read_series(ADJ_KEY))

    def test_write_series_rejects_a_bare_list(self, store, adjusted_series):
        with pytest.raises(StorageError, match="BarSeries"):
            store.write_series(list(adjusted_series.bars))


class TestPhase1BackwardCompatibility:
    """Phase 1 wrote files before PriceBasis existed. They must still work."""

    def _legacy_file(self, store, key=RAW_KEY):
        """Write a file in the exact Phase 1 schema: no price_basis column."""
        path = store.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy_columns = [column for column in CSV_COLUMNS if column != "price_basis"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=legacy_columns)
            writer.writeheader()
            for day, close in ((2, 400.0), (3, 408.0)):
                row = bar(day, close).to_dict()
                writer.writerow({column: row[column] for column in legacy_columns})
        return path

    def test_a_legacy_three_argument_key_still_works(self):
        assert SeriesKey("AAPL", Interval.DAY_1, "yfinance").basis is PriceBasis.RAW

    def test_a_legacy_file_is_still_readable(self, store):
        self._legacy_file(store)
        assert [b.close for b in store.read(RAW_KEY)] == [400.0, 408.0]

    def test_a_legacy_file_is_interpreted_as_raw(self, store):
        self._legacy_file(store)
        assert store.read_series(RAW_KEY).basis is PriceBasis.RAW

    def test_a_legacy_file_keeps_the_phase_1_filename(self, store):
        assert store.path_for(RAW_KEY).name == "1d.csv"

    def test_a_legacy_file_cannot_be_read_as_adjusted(self, store):
        legacy = self._legacy_file(store)
        store.path_for(ADJ_KEY).write_bytes(legacy.read_bytes())
        with pytest.raises(StorageError, match="price basis"):
            store.read(ADJ_KEY)

    def test_blanking_the_basis_column_cannot_launder_adjusted_data(
        self, store, adjusted_series
    ):
        """A blank cell is a corrupt modern file, not a legacy one.

        Regression: the legacy rule once keyed on the cell being empty rather
        than the column being absent, so blanking the column of an adjusted
        file laundered it into a raw one -- adjusted numbers returned as RAW.
        """
        store.write_series(adjusted_series)
        raw_path = store.path_for(RAW_KEY)
        raw_path.write_bytes(
            store.path_for(ADJ_KEY)
            .read_text(encoding="utf-8")
            .replace(f",{ADJUSTED.value}", ",")
            .encode("utf-8")
        )
        with pytest.raises(StorageError, match="no value for it"):
            store.read(RAW_KEY)

    def test_a_single_blank_basis_cell_is_refused(self, store, raw_series):
        path = store.write_series(raw_series)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1][: lines[1].rfind(",") + 1]  # blank the last field
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(StorageError, match="no value for it"):
            store.read(RAW_KEY)

    def test_the_legacy_rule_keys_on_the_header_not_the_cell(self, store):
        # Column absent entirely -> legacy -> RAW (allowed).
        self._legacy_file(store)
        assert store.read_series(RAW_KEY).basis is PriceBasis.RAW

    def test_price_basis_is_not_a_required_column(self):
        assert "price_basis" not in REQUIRED_CSV_COLUMNS
        assert "price_basis" in CSV_COLUMNS

    def test_the_other_columns_are_all_still_required(self, store):
        path = self._legacy_file(store)
        text = path.read_text(encoding="utf-8").replace("volume", "vol", 1)
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="missing column"):
            store.read(RAW_KEY)

    def test_rewriting_a_legacy_file_upgrades_it_to_self_describing(self, store):
        self._legacy_file(store)
        bars = store.read(RAW_KEY)
        path = store.write(bars, key=RAW_KEY)
        assert "price_basis" in path.read_text(encoding="utf-8").splitlines()[0]
        assert store.read_series(RAW_KEY).basis is PriceBasis.RAW


class TestWriteBasisPlumbing:
    def test_writing_a_barseries_files_it_under_its_own_basis(self, store, adjusted_series):
        assert store.write(adjusted_series) == store.path_for(ADJ_KEY)

    def test_an_explicit_key_beats_inference(self, store, raw_series):
        path = store.write(list(raw_series.bars), key=ADJ_KEY)
        assert path == store.path_for(ADJ_KEY)
        assert store.read_series(ADJ_KEY).basis is ADJUSTED

    def test_merge_respects_the_basis(self, store, adjusted_series):
        store.write_series(adjusted_series)
        store.merge(list(adjusted_series.bars), key=ADJ_KEY)
        assert store.read_series(ADJ_KEY).values("close") == adjusted_series.values("close")
        assert not store.exists(RAW_KEY)

    def test_every_written_row_declares_the_basis(self, store, adjusted_series):
        path = store.write_series(adjusted_series)
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        assert {row["price_basis"] for row in rows} == {ADJUSTED.value}
