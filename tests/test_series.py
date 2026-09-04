"""BarSeries: the homogeneity boundary research code depends on."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.data.models import Interval
from src.data.series import PRICE_FIELDS, BarSeries, PriceBasis, SeriesError
from tests.conftest import UTC, make_bar, make_series


class TestConstruction:
    def test_infers_metadata_from_the_bars(self):
        series = make_series([1.0, 2.0], symbol="aapl", source="yfinance")
        assert series.symbol == "AAPL"
        assert series.interval is Interval.DAY_1
        assert series.source == "yfinance"
        assert series.basis is PriceBasis.RAW

    def test_bars_are_stored_immutably(self, series):
        assert isinstance(series.bars, tuple)
        with pytest.raises((AttributeError, TypeError)):
            series.bars = ()  # type: ignore[misc]

    def test_an_empty_series_needs_explicit_metadata(self):
        with pytest.raises(SeriesError, match="cannot be inferred"):
            BarSeries.from_bars([], basis=PriceBasis.RAW)

    def test_an_empty_series_with_metadata_is_valid(self):
        empty = BarSeries.from_bars(
            [], basis=PriceBasis.RAW, symbol="AAPL", interval="1d", source="test"
        )
        assert len(empty) == 0
        assert empty.symbol == "AAPL"

    def test_basis_accepts_its_string_form(self):
        assert make_series([1.0], basis="raw").basis is PriceBasis.RAW


class TestHomogeneityIsEnforced:
    """Each of these is a silent-wrong-answer bug if it gets through."""

    def _pair(self, second_kwargs):
        first = make_bar(timestamp=datetime(2024, 1, 2, tzinfo=UTC))
        second = make_bar(timestamp=datetime(2024, 1, 3, tzinfo=UTC), **second_kwargs)
        return [first, second]

    def test_mixed_sources_are_rejected(self):
        # Regression: Phase 1 validation accepted this; only storage caught it.
        with pytest.raises(SeriesError, match="source"):
            BarSeries.from_bars(self._pair({"source": "yfinance"}), basis=PriceBasis.RAW)

    def test_mixed_symbols_are_rejected(self):
        with pytest.raises(SeriesError, match="symbol"):
            BarSeries.from_bars(self._pair({"symbol": "MSFT"}), basis=PriceBasis.RAW)

    def test_mixed_intervals_are_rejected(self):
        with pytest.raises(SeriesError, match="interval"):
            BarSeries.from_bars(self._pair({"interval": "1h"}), basis=PriceBasis.RAW)

    def test_duplicate_timestamps_are_rejected(self):
        bar = make_bar()
        with pytest.raises(SeriesError, match="duplicate"):
            BarSeries.from_bars([bar, bar], basis=PriceBasis.RAW)

    def test_out_of_order_bars_are_rejected_not_sorted(self):
        later = make_bar(timestamp=datetime(2024, 1, 3, tzinfo=UTC))
        earlier = make_bar(timestamp=datetime(2024, 1, 2, tzinfo=UTC))
        with pytest.raises(SeriesError, match="unordered"):
            BarSeries.from_bars([later, earlier], basis=PriceBasis.RAW)

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ({"symbol": "MSFT"}, "symbol"),
            ({"source": "alpaca"}, "source"),
            ({"interval": "1h"}, "interval"),
        ],
    )
    def test_declared_metadata_must_match_the_bars(self, declared, expected):
        """A series must not claim provenance its bars contradict.

        Without this the series could advertise ``source="alpaca"`` while
        holding yfinance bars -- provenance laundering by constructor argument.
        """
        bar = make_bar(symbol="AAPL", source="yfinance", interval="1d")
        with pytest.raises(SeriesError, match=expected):
            BarSeries.from_bars([bar], basis=PriceBasis.RAW, **declared)

    def test_matching_declared_metadata_is_accepted(self):
        bar = make_bar(symbol="AAPL", source="yfinance", interval="1d")
        series = BarSeries.from_bars(
            [bar], basis=PriceBasis.RAW, symbol="AAPL", source="yfinance", interval="1d"
        )
        assert series.source == "yfinance"


class TestCompatibility:
    def test_identical_series_are_compatible(self):
        make_series([1.0]).require_compatible(make_series([1.0]))

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"symbol": "OTHER"}, "symbol"),
            ({"source": "other"}, "source"),
            ({"interval": "1h"}, "interval"),
            ({"basis": PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED}, "basis"),
        ],
    )
    def test_any_metadata_difference_is_incompatible(self, kwargs, expected):
        with pytest.raises(SeriesError, match=expected):
            make_series([1.0]).require_compatible(make_series([1.0], **kwargs))

    def test_raw_and_adjusted_are_never_interchangeable(self):
        raw = make_series([1.0], basis=PriceBasis.RAW)
        adjusted = make_series([1.0], basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        with pytest.raises(SeriesError, match="basis"):
            raw.require_compatible(adjusted)


class TestAccess:
    def test_values_extracts_one_column_in_order(self):
        series = make_series([1.0, 2.0, 3.0])
        assert series.values("close") == (1.0, 2.0, 3.0)

    def test_unknown_fields_are_rejected(self, series):
        with pytest.raises(SeriesError, match="unknown field"):
            series.values("symbol")

    def test_price_fields_are_all_extractable(self, series):
        for field in (*PRICE_FIELDS, "volume"):
            assert len(series.values(field)) == len(series)

    def test_with_bars_returns_a_new_series_and_leaves_the_original(self, series):
        original_closes = series.values("close")
        derived = series.with_bars(series.bars[:2])
        assert len(derived) == 2
        assert series.values("close") == original_closes
        assert derived is not series

    def test_prefix_is_a_valid_shorter_series(self, series):
        assert series.prefix(3).values("close") == series.values("close")[:3]

    def test_negative_prefix_is_rejected(self, series):
        with pytest.raises(SeriesError):
            series.prefix(-1)


class TestPriceBasis:
    def test_raw_is_not_derived(self):
        assert PriceBasis.RAW.is_derived is False

    def test_adjusted_is_derived(self):
        assert PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED.is_derived is True

    def test_the_adjusted_name_states_both_effects(self):
        # The Yahoo factor encodes dividends as well as splits (verified against
        # the installed yfinance implementation); a SPLIT_ADJUSTED name would
        # misdescribe it. See docs/adr/0001.
        name = PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED.value
        assert "split" in name and "dividend" in name

    def test_no_split_only_basis_is_defined_yet(self):
        # An unimplemented enum member is an invitation to mislabel data.
        assert {basis.value for basis in PriceBasis} == {"raw", "split_and_dividend_adjusted"}
