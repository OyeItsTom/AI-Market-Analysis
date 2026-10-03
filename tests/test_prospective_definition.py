"""Prospective Collection v1: the frozen definition and its pure time rules."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.application.prospective import live_configuration_mismatches
from src.prospective import (
    COLLECTION_V1,
    DefinitionError,
    in_collection_window,
    is_current_tail,
    is_new_york_midnight,
    is_pre_activation,
    missed_tails,
    validate_commit_sha,
)
from tests.prospective_fixtures import (  # noqa: F401 - autouse guard
    NY,
    UTC,
    et,
    ny_midnight,
    offline_and_no_live_root,
)

LONDON = ZoneInfo("Europe/London")

#: Pinned so any change to the frozen definition is a visible, reviewed edit.
COLLECTION_V1_FINGERPRINT = "af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8"


# -- the definition --------------------------------------------------------------------------


class TestDefinition:
    def test_fingerprint_is_pinned(self):
        assert COLLECTION_V1.fingerprint == COLLECTION_V1_FINGERPRINT

    def test_fingerprint_is_deterministic_and_is_the_canonical_json_hash(self):
        import hashlib

        again = replace(COLLECTION_V1)
        assert again.fingerprint == COLLECTION_V1.fingerprint
        assert again.canonical_json() == COLLECTION_V1.canonical_json()
        assert COLLECTION_V1.fingerprint == hashlib.sha256(
            COLLECTION_V1.canonical_json().encode("ascii")).hexdigest()

    def test_the_contract_values(self):
        form = COLLECTION_V1.canonical_form()
        assert form["universe"] == ["SPY", "QQQ", "IWM", "TLT", "GLD"]
        assert form["interval"] == "1d"
        assert form["basis"] == "raw"
        assert form["settled_only"] is True
        assert form["provider"] == "yfinance"
        assert form["hypotheses"] == [
            {"hypothesis_id": "trend_alignment", "version": 1, "fingerprint": "650add07184f8440"},
            {"hypothesis_id": "momentum_in_trend_context", "version": 1,
             "fingerprint": "6589cb8021b76574"},
            {"hypothesis_id": "trend_crossover", "version": 1, "fingerprint": "f1126ca778e6f7ce"},
        ]
        assert form["assessment_rule"] == "directional_presence_v1"
        assert form["minimum_sufficient_observations"] == 2
        assert form["outcome_horizons"] == [1, 5, 20]
        assert form["evaluation_version"] == 1
        assert form["holdout_start"] == "2025-03-01"
        assert form["collection_timezone"] == "America/New_York"
        assert (form["collection_window_start"], form["collection_window_end"]) == ("00:30",
                                                                                    "09:00")
        assert form["prospective_policy_version"] == 1

    def test_no_machine_path_or_activation_time_is_in_the_fingerprint_input(self):
        text = COLLECTION_V1.canonical_json()
        for forbidden in ("/Users", "data/", "activated", "prospective/v1", "home"):
            assert forbidden not in text
        assert set(json.loads(text)) == set(COLLECTION_V1.canonical_form())

    @pytest.mark.parametrize("change", [
        {"universe": ("SPY", "QQQ", "IWM", "TLT")},
        {"universe": ("QQQ", "SPY", "IWM", "TLT", "GLD")},
        {"interval": "1wk"},
        {"collection_window_end": "09:30"},
        {"holdout_start": date(2025, 3, 2)},
        {"evaluation_version": 2},
    ])
    def test_every_field_moves_the_fingerprint(self, change):
        assert replace(COLLECTION_V1, **change).fingerprint != COLLECTION_V1.fingerprint

    @pytest.mark.parametrize("bad", [
        {"universe": ()},
        {"universe": ("SPY", "SPY")},
        {"universe": ("spy",)},
        {"outcome_horizons": (1, 5)},
    ])
    def test_malformed_definitions_are_refused(self, bad):
        with pytest.raises(DefinitionError):
            replace(COLLECTION_V1, **bad)

    def test_the_declared_pins_match_the_live_code(self):
        assert live_configuration_mismatches(COLLECTION_V1) == ()

    def test_a_drifted_pin_is_reported(self):
        drifted = replace(COLLECTION_V1, policy_fingerprint="0" * 16, warmup_bars=50)
        assert live_configuration_mismatches(drifted) == ("policy_fingerprint", "warmup_bars")


# -- the collection window -------------------------------------------------------------------


class TestCollectionWindow:
    @pytest.mark.parametrize("moment, inside", [
        # EST (UTC-5), January.
        (datetime(2026, 1, 15, 5, 29, 59, tzinfo=UTC), False),   # 00:29:59 ET
        (datetime(2026, 1, 15, 5, 30, 0, tzinfo=UTC), True),     # 00:30:00 ET
        (datetime(2026, 1, 15, 13, 59, 59, tzinfo=UTC), True),   # 08:59:59 ET
        (datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC), False),    # 09:00:00 ET
        # EDT (UTC-4), July.
        (datetime(2026, 7, 15, 4, 29, 59, tzinfo=UTC), False),
        (datetime(2026, 7, 15, 4, 30, 0, tzinfo=UTC), True),
        (datetime(2026, 7, 15, 12, 59, 59, tzinfo=UTC), True),
        (datetime(2026, 7, 15, 13, 0, 0, tzinfo=UTC), False),
    ])
    def test_boundaries_in_utc(self, moment, inside):
        assert in_collection_window(moment) is inside

    @pytest.mark.parametrize("local, inside", [
        ((0, 29, 59), False), ((0, 30, 0), True), ((8, 59, 59), True), ((9, 0, 0), False),
        ((23, 59, 59), False), ((0, 0, 0), False), ((16, 30, 0), False),
    ])
    @pytest.mark.parametrize("day", [date(2026, 1, 15), date(2026, 7, 15)])
    def test_boundaries_in_new_york_wall_clock(self, day, local, inside):
        moment = datetime(day.year, day.month, day.day, *local, tzinfo=NY)
        assert in_collection_window(moment) is inside

    @pytest.mark.parametrize("london, inside, naive_differs", [
        # 2026-03-20: US already on EDT (UTC-4), UK still on GMT (UTC+0): a 4-hour gap.
        (datetime(2026, 3, 20, 4, 15, tzinfo=LONDON), False, False),   # 00:15 ET
        (datetime(2026, 3, 20, 4, 45, tzinfo=LONDON), True, True),     # 00:45 ET
        (datetime(2026, 3, 20, 12, 45, tzinfo=LONDON), True, False),   # 08:45 ET
        (datetime(2026, 3, 20, 13, 15, tzinfo=LONDON), False, True),   # 09:15 ET
        # 2026-10-28: UK back on GMT, US still on EDT: again 4 hours, not 5.
        (datetime(2026, 10, 28, 12, 30, tzinfo=LONDON), True, False),  # 08:30 ET
        (datetime(2026, 10, 28, 13, 5, tzinfo=LONDON), False, True),   # 09:05 ET
    ])
    def test_us_uk_daylight_saving_mismatch_weeks_use_new_york_time(self, london, inside,
                                                                   naive_differs):
        assert in_collection_window(london) is inside
        # Where marked, a naive fixed five-hour UK->ET offset decides the other way.
        naive_et = (london.astimezone(UTC) - timedelta(hours=5)).time()
        naive_inside = time(0, 30) <= naive_et < time(9, 0)
        assert (naive_inside != inside) is naive_differs

    @pytest.mark.parametrize("moment", [
        et(2026, 3, 8, 0, 45),   # spring-forward day, before the 02:00 jump
        et(2026, 3, 8, 3, 15),   # after the jump
        et(2026, 11, 1, 1, 30),  # fall-back day, the repeated hour
    ])
    def test_transition_days(self, moment):
        assert in_collection_window(moment)

    def test_a_naive_clock_is_refused(self):
        with pytest.raises(DefinitionError):
            in_collection_window(datetime(2026, 1, 15, 7, 0))


# -- daily timestamp convention -------------------------------------------------------------


class TestTimestampConvention:
    @pytest.mark.parametrize("day", [date(2026, 1, 15), date(2026, 7, 15), date(2026, 3, 9),
                                     date(2026, 11, 2)])
    def test_new_york_midnight_is_accepted_in_both_offsets(self, day):
        assert is_new_york_midnight(ny_midnight(day))

    @pytest.mark.parametrize("stamp", [
        datetime(2026, 1, 15, 0, 0, tzinfo=UTC),    # UTC midnight (19:00 ET the day before)
        datetime(2026, 7, 15, 5, 0, tzinfo=UTC),    # winter offset in summer: 01:00 EDT
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),  # the session open
        datetime(2026, 1, 15, 5, 0, 1, tzinfo=UTC),
    ])
    def test_anything_else_is_refused(self, stamp):
        assert not is_new_york_midnight(stamp)


# -- activation boundary, current tail, missed tails ---------------------------------------


class TestActivationBoundary:
    def test_a_bar_settled_before_activation_is_pre_activation(self):
        monday = ny_midnight(date(2026, 10, 5))
        assert is_pre_activation(monday, et(2026, 10, 6, 0, 10))
        assert is_pre_activation(monday, et(2026, 10, 6, 0, 0))  # settles exactly then

    def test_a_bar_settling_after_activation_is_claimable(self):
        monday = ny_midnight(date(2026, 10, 5))
        assert not is_pre_activation(monday, et(2026, 10, 5, 15, 0))


class TestCurrentTail:
    @pytest.mark.parametrize("tail_day, run, current", [
        (date(2026, 10, 5), et(2026, 10, 6, 7), True),    # Mon tail, Tue morning
        (date(2026, 10, 9), et(2026, 10, 10, 7), True),   # Fri tail, Sat
        (date(2026, 10, 9), et(2026, 10, 11, 7), True),   # Fri tail, Sun
        (date(2026, 10, 9), et(2026, 10, 12, 7), True),   # Fri tail, Mon morning
        (date(2026, 10, 9), et(2026, 10, 13, 7), False),  # Fri tail, Tue: Monday passed
        (date(2026, 10, 5), et(2026, 10, 7, 7), False),   # Mon tail, Wed: Tuesday passed
        (date(2026, 10, 5), et(2026, 10, 5, 23), False),  # same day: not settled
    ])
    def test_weekday_rule(self, tail_day, run, current):
        assert is_current_tail(ny_midnight(tail_day), run) is current


class TestMissedTails:
    def test_unclaimed_settled_bars_between_claims_are_reported_once(self):
        days = [date(2026, 10, d) for d in (5, 6, 7, 8)]
        series = [ny_midnight(d) for d in days]
        held = [series[0]]
        missed = missed_tails(series, held, activated_at=et(2026, 10, 5, 15), tail=series[3])
        assert missed == (series[1], series[2])

    def test_nothing_before_the_last_claim_or_before_activation_is_reported(self):
        series = [ny_midnight(date(2026, 10, d)) for d in (1, 2, 5, 6, 7)]
        # Monday 10-05 settles at Tuesday 00:00 ET, after a Monday 15:00 activation.
        missed = missed_tails(series, [], activated_at=et(2026, 10, 5, 15), tail=series[4])
        assert missed == (series[2], series[3])
        assert missed_tails(series, [series[3]], activated_at=et(2026, 10, 5, 15),
                            tail=series[3]) == ()


class TestCommitSha:
    @pytest.mark.parametrize("value", ["", "abc", "A" * 40, "g" * 40, "a" * 39, None, 7])
    def test_malformed_shas_are_refused(self, value):
        with pytest.raises(DefinitionError):
            validate_commit_sha(value, "sha")

    def test_a_full_lower_case_sha_is_accepted(self):
        assert validate_commit_sha("0123456789abcdef" * 2 + "01234567", "sha")
