"""Tests for the validation layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.validation import (
    IssueCode,
    ValidationError,
    check_bar,
    check_bars,
    is_valid_bar,
    validate_bar,
    validate_bars,
)
from tests.conftest import UTC, corrupt_bar, make_bar


def codes(issues):
    return {issue.code for issue in issues}


class TestSingleBar:
    def test_valid_bar_produces_no_issues(self, bar):
        assert check_bar(bar) == []
        assert is_valid_bar(bar)
        assert validate_bar(bar) is bar

    def test_high_below_low_is_rejected(self):
        bad = corrupt_bar(make_bar(), high=90.0, low=95.0, open=92.0, close=93.0)
        assert IssueCode.HIGH_BELOW_LOW in codes(check_bar(bad))

    def test_high_below_open_is_rejected(self):
        bad = corrupt_bar(make_bar(), open=120.0)
        assert IssueCode.HIGH_BELOW_OPEN in codes(check_bar(bad))

    def test_high_below_close_is_rejected(self):
        bad = corrupt_bar(make_bar(), close=120.0)
        assert IssueCode.HIGH_BELOW_CLOSE in codes(check_bar(bad))

    def test_low_above_open_is_rejected(self):
        bad = corrupt_bar(make_bar(), open=90.0)
        assert IssueCode.LOW_ABOVE_OPEN in codes(check_bar(bad))

    def test_low_above_close_is_rejected(self):
        bad = corrupt_bar(make_bar(), close=90.0)
        assert IssueCode.LOW_ABOVE_CLOSE in codes(check_bar(bad))

    @pytest.mark.parametrize("field", ["open", "high", "low", "close"])
    def test_zero_and_negative_prices_are_rejected(self, field):
        for value in (0.0, -1.0):
            bad = corrupt_bar(make_bar(), **{field: value})
            assert IssueCode.NON_POSITIVE_PRICE in codes(check_bar(bad))

    def test_negative_volume_is_rejected(self):
        bad = corrupt_bar(make_bar(), volume=-1.0)
        assert IssueCode.NEGATIVE_VOLUME in codes(check_bar(bad))

    def test_zero_volume_is_allowed(self):
        assert check_bar(make_bar(volume=0.0)) == []

    @pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
    def test_nan_is_rejected(self, field):
        bad = corrupt_bar(make_bar(), **{field: float("nan")})
        assert codes(check_bar(bad)) == {IssueCode.NON_FINITE_VALUE}

    @pytest.mark.parametrize("value", [float("inf"), float("-inf")])
    def test_infinity_is_rejected(self, value):
        bad = corrupt_bar(make_bar(), close=value)
        assert IssueCode.NON_FINITE_VALUE in codes(check_bar(bad))

    def test_relational_checks_are_skipped_when_values_are_non_finite(self):
        # NaN comparisons are meaningless; reporting "high < low" on top of
        # "not a number" would be noise.
        bad = corrupt_bar(make_bar(), high=float("nan"))
        assert codes(check_bar(bad)) == {IssueCode.NON_FINITE_VALUE}

    def test_naive_timestamp_is_rejected(self):
        bad = corrupt_bar(make_bar(), timestamp=datetime(2024, 1, 2, 14, 30))
        assert IssueCode.NAIVE_TIMESTAMP in codes(check_bar(bad))

    def test_empty_symbol_is_rejected(self):
        bad = corrupt_bar(make_bar(), symbol="   ")
        assert IssueCode.EMPTY_SYMBOL in codes(check_bar(bad))

    def test_non_marketbar_input_is_rejected(self):
        assert codes(check_bar({"symbol": "AAPL"})) == {IssueCode.WRONG_TYPE}

    def test_all_issues_are_reported_not_just_the_first(self):
        bad = corrupt_bar(make_bar(), open=-5.0, high=1.0, low=2.0)
        assert {IssueCode.NON_POSITIVE_PRICE, IssueCode.HIGH_BELOW_LOW} <= codes(check_bar(bad))

    def test_validate_bar_raises_with_structured_issues(self):
        bad = corrupt_bar(make_bar(), volume=-1.0)
        with pytest.raises(ValidationError) as excinfo:
            validate_bar(bad)
        assert excinfo.value.issues[0].code is IssueCode.NEGATIVE_VOLUME

    def test_validation_never_repairs_the_bar(self):
        bad = corrupt_bar(make_bar(), high=1.0)
        with pytest.raises(ValidationError):
            validate_bar(bad)
        assert bad.high == 1.0  # untouched: we reject, we do not "fix"


class TestSequences:
    def test_valid_series_passes(self, bars):
        assert check_bars(bars) == []
        assert validate_bars(bars) == bars

    def test_empty_series_is_valid(self):
        assert check_bars([]) == []
        assert validate_bars([]) == []

    def test_duplicate_timestamps_are_rejected(self, bars):
        duplicated = [*bars, bars[-1]]
        assert IssueCode.DUPLICATE_TIMESTAMP in codes(check_bars(duplicated))

    def test_duplicate_across_timezones_is_detected(self):
        eastern = timezone(timedelta(hours=-5))
        first = make_bar(timestamp=datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
        same_instant = make_bar(timestamp=datetime(2024, 1, 2, 9, 30, tzinfo=eastern))
        assert IssueCode.DUPLICATE_TIMESTAMP in codes(check_bars([first, same_instant]))

    def test_out_of_order_timestamps_are_rejected(self, bars):
        assert IssueCode.UNORDERED_TIMESTAMP in codes(check_bars(list(reversed(bars))))

    def test_out_of_order_can_be_allowed_explicitly(self, bars):
        assert check_bars(list(reversed(bars)), require_sorted=False) == []

    def test_symbol_mismatch_within_a_series_is_rejected(self, bars):
        mixed = [*bars, make_bar(symbol="MSFT", timestamp=datetime(2024, 1, 9, tzinfo=UTC))]
        assert IssueCode.SYMBOL_MISMATCH in codes(check_bars(mixed))

    def test_expected_symbol_mismatch_is_rejected(self, bars):
        assert IssueCode.SYMBOL_MISMATCH in codes(check_bars(bars, expected_symbol="MSFT"))

    def test_expected_symbol_is_case_insensitive(self, bars):
        assert check_bars(bars, expected_symbol="aapl") == []

    def test_interval_mismatch_within_a_series_is_rejected(self, bars):
        mixed = [*bars, make_bar(interval="1h", timestamp=datetime(2024, 1, 9, tzinfo=UTC))]
        assert IssueCode.INTERVAL_MISMATCH in codes(check_bars(mixed))

    def test_expected_interval_mismatch_is_rejected(self, bars):
        assert IssueCode.INTERVAL_MISMATCH in codes(check_bars(bars, expected_interval="1h"))

    def test_per_bar_issues_carry_their_index(self, bars):
        broken = [*bars, corrupt_bar(make_bar(timestamp=datetime(2024, 1, 9, tzinfo=UTC)), volume=-1.0)]
        issues = [issue for issue in check_bars(broken) if issue.code is IssueCode.NEGATIVE_VOLUME]
        assert issues and issues[0].index == 3

class TestInvalidBarsNeverCrashTheChecker:
    """Regression: the checker must report, never raise something unrelated.

    A naive timestamp cannot be compared against an aware one -- Python raises
    TypeError -- so the sequence checks used to crash on exactly the input they
    existed to diagnose.
    """

    def _naive(self, day):
        return corrupt_bar(make_bar(), timestamp=datetime(2024, 1, day))

    def test_aware_then_naive(self, bars):
        issues = check_bars([bars[0], self._naive(9)])
        assert IssueCode.NAIVE_TIMESTAMP in codes(issues)

    def test_naive_then_aware(self, bars):
        issues = check_bars([self._naive(1), bars[0]])
        assert IssueCode.NAIVE_TIMESTAMP in codes(issues)

    def test_multiple_invalid_bars_are_all_reported(self, bars):
        issues = check_bars(
            [self._naive(1), bars[0], self._naive(9), corrupt_bar(make_bar(), volume=-5.0)]
        )
        assert codes(issues) >= {IssueCode.NAIVE_TIMESTAMP, IssueCode.NEGATIVE_VOLUME}
        assert len([i for i in issues if i.code is IssueCode.NAIVE_TIMESTAMP]) == 2

    def test_a_rejected_naive_bar_cannot_distort_the_ordering_of_valid_bars(self):
        """The naive bar must be excluded, not silently coerced.

        Written to be independent of the machine's timezone: the naive
        timestamp is 76 years ahead, which no local offset (max +-14h) can
        bridge. If the naive bar were coerced into the comparison instead of
        skipped, the aware 2024 bar after it would be reported out of order.
        """
        far_future_naive = corrupt_bar(make_bar(), timestamp=datetime(2100, 1, 1))
        aware = make_bar(timestamp=datetime(2024, 1, 2, tzinfo=UTC))
        found = codes(check_bars([far_future_naive, aware]))
        assert IssueCode.NAIVE_TIMESTAMP in found
        assert IssueCode.UNORDERED_TIMESTAMP not in found

    def test_a_rejected_naive_bar_cannot_create_a_false_duplicate(self):
        far_past_naive = corrupt_bar(make_bar(), timestamp=datetime(1900, 1, 1))
        aware = make_bar(timestamp=datetime(2024, 1, 2, tzinfo=UTC))
        found = codes(check_bars([aware, far_past_naive]))
        assert IssueCode.DUPLICATE_TIMESTAMP not in found
        assert IssueCode.UNORDERED_TIMESTAMP not in found

    def test_a_naive_bar_does_not_become_the_ordering_baseline(self, bars):
        # The naive bar is skipped for ordering; the aware bars around it are
        # still compared against each other.
        issues = check_bars([bars[0], self._naive(9), bars[2], bars[1]])
        assert IssueCode.UNORDERED_TIMESTAMP in codes(issues)

    def test_validate_bars_reports_a_non_marketbar_as_a_validation_error(self):
        # Regression: building the error message used to dereference .symbol on
        # the very object that had just been rejected for not being a MarketBar.
        with pytest.raises(ValidationError) as excinfo:
            validate_bars([{"symbol": "AAPL"}])
        assert excinfo.value.issues[0].code is IssueCode.WRONG_TYPE

    def test_a_non_marketbar_mixed_into_a_good_series_is_reported(self, bars):
        with pytest.raises(ValidationError) as excinfo:
            validate_bars([*bars, "not a bar"])
        assert IssueCode.WRONG_TYPE in codes(excinfo.value.issues)


class TestSequencesContinued:
    def test_validate_bars_raises_and_lists_every_problem(self, bars):
        broken = [*bars, bars[0]]  # duplicate + out of order
        with pytest.raises(ValidationError) as excinfo:
            validate_bars(broken)
        assert {IssueCode.DUPLICATE_TIMESTAMP, IssueCode.UNORDERED_TIMESTAMP} <= codes(
            excinfo.value.issues
        )
