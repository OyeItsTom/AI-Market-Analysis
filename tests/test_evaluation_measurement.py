"""Phase 4 measurement primitive: ``measure_forward`` and ``ForwardMeasurement``.

Phase 12 needs to measure a *market point* -- ``(symbol, interval, basis,
timestamp)`` -- without fabricating a ``ResearchObservation``. The primitive
was extracted from ``evaluate_observations``, which now delegates to it. Two
things are proven here:

1. the primitive reproduces every existing Phase 4 semantic (reference
   convention, horizon indexing, statuses, alignment, exact matching,
   spacing guard) and agrees with ``evaluate_observations`` bar for bar;
2. ``evaluate_observations`` itself is **bit-identical** to its
   pre-extraction output: a golden digest over 56 representative cases (638
   records and 15 exception messages) was taken at commit ``74e7462``,
   before the extraction, and is pinned below. It is never re-pinned.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.evaluation import (
    EvaluatedOutcome,
    EvaluationError,
    ForwardMeasurement,
    OutcomeError,
    OutcomeSpec,
    OutcomeStatus,
    PriceField,
    evaluate_observations,
    measure_forward,
)
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState
from tests.conftest import make_observations
from tests.evaluation_lookahead import perturb_after

UTC = timezone.utc
S = ResearchState


def series(count, *, interval="1d", basis=PriceBasis.RAW, step=None, symbol="X", source="t",
           start=None, closes=None):
    """Bar n (1-based): open n*100, close n*100+50 -- unless ``closes`` is given."""
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    step = step or Interval.parse(interval).max_duration
    bars = []
    for i in range(count):
        c = closes[i] if closes else (i + 1) * 100.0 + 50.0
        o = c * 0.98 if closes else (i + 1) * 100.0
        bars.append(MarketBar(symbol, start + step * i, o, max(o, c) * 1.1, min(o, c) * 0.9,
                              c, 1000.0 + i, interval, source))
    return BarSeries.from_bars(bars, basis=basis)


def point(s, index=0, **overrides):
    fields = dict(symbol=s.symbol, interval=s.interval, basis=s.basis, timestamp=s.timestamps[index])
    fields.update(overrides)
    return fields


def measure(s, index=0, spec=None, **overrides):
    return measure_forward(s, spec or OutcomeSpec(), **point(s, index, **overrides))


# -- reference convention and horizon indexing ---------------------------------------------


class TestReferenceConvention:
    def test_reference_is_the_next_bar_open(self):
        s = series(6)
        m = measure(s)
        assert m.reference_timestamp == s.timestamps[1]
        assert m.reference_price == 200.0

    def test_the_point_bar_is_never_the_reference(self):
        s = series(6)
        m = measure(s)
        assert m.reference_price not in (s[0].open, s[0].close)
        assert m.reference_timestamp != m.observation_timestamp
        assert m.observation_timestamp == s.timestamps[0]

    def test_the_last_bar_has_no_reference(self):
        s = series(6)
        m = measure(s, 5)
        assert m.status is OutcomeStatus.NO_REFERENCE_BAR
        assert not m.is_evaluated
        assert m.reference_timestamp is None and m.outcome_value is None


class TestHorizonIndexing:
    @pytest.mark.parametrize(
        ("horizon", "future_bar_number"), [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]
    )
    def test_future_index_is_reference_plus_horizon_minus_one(self, horizon, future_bar_number):
        s = series(6)
        m = measure(s, spec=OutcomeSpec(horizon_bars=horizon))
        assert m.status is OutcomeStatus.EVALUATED
        assert m.horizon_bars == horizon
        assert m.reference_timestamp == s.timestamps[1]
        assert m.future_timestamp == s.timestamps[future_bar_number - 1]
        assert m.reference_price == 200.0
        assert m.future_price == future_bar_number * 100.0 + 50.0
        assert m.outcome_value == m.future_price / m.reference_price - 1.0

    def test_horizon_one_ends_on_the_reference_bar(self):
        m = measure(series(6), spec=OutcomeSpec(horizon_bars=1))
        assert m.reference_timestamp == m.future_timestamp
        assert m.outcome_value == 250.0 / 200.0 - 1.0

    def test_horizon_two_ends_one_bar_later(self):
        s = series(6)
        m = measure(s, spec=OutcomeSpec(horizon_bars=2))
        assert m.future_timestamp == s.timestamps[2]

    @pytest.mark.parametrize("field, expected", [
        (PriceField.OPEN, 300.0), (PriceField.HIGH, 385.0),
        (PriceField.LOW, 270.0), (PriceField.CLOSE, 350.0),
    ])
    def test_the_future_field_is_read(self, field, expected):
        s = series(6)  # bar 3: open 300, close 350, high 385, low 270
        m = measure(s, spec=OutcomeSpec(horizon_bars=2, future_field=field))
        assert m.future_price == getattr(s[2], field.value)
        assert m.future_price == pytest.approx(expected)

    def test_a_horizon_overrunning_the_series_is_insufficient(self):
        s = series(4)
        m = measure(s, 1, spec=OutcomeSpec(horizon_bars=3))
        assert m.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        assert m.reference_timestamp == s.timestamps[2]
        assert m.reference_price == 300.0
        assert m.future_timestamp is None and m.future_price is None
        assert m.outcome_value is None

    def test_the_horizon_ending_exactly_on_the_last_bar_is_evaluated(self):
        s = series(4)
        m = measure(s, 0, spec=OutcomeSpec(horizon_bars=3))
        assert m.status is OutcomeStatus.EVALUATED
        assert m.future_timestamp == s.timestamps[3]

    def test_gaps_are_counted_in_bars_not_time(self):
        # A missing calendar day between bars does not change which bar is
        # the reference or the future: bars are counted.
        start = datetime(2024, 1, 1, tzinfo=UTC)
        stamps = [start, start + timedelta(days=1), start + timedelta(days=4), start + timedelta(days=5)]
        bars = [MarketBar("X", ts, (i + 1) * 100.0, (i + 1) * 100.0 + 90, (i + 1) * 100.0 - 10,
                          (i + 1) * 100.0 + 50, 1000.0, "1d", "t") for i, ts in enumerate(stamps)]
        s = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        m = measure(s, spec=OutcomeSpec(horizon_bars=2))
        assert m.reference_timestamp == stamps[1]
        assert m.future_timestamp == stamps[2]
        assert m.future_price == 350.0


class TestForwardReturn:
    def test_is_the_documented_expression(self):
        m = measure(series(3))
        assert m.outcome_value == 250.0 / 200.0 - 1.0 == 0.25

    def test_negative_and_zero_returns_are_results(self):
        bars = [MarketBar("X", datetime(2024, 1, d, tzinfo=UTC), 100.0, 120.0, 80.0, c, 1000.0, "1d", "t")
                for d, c in ((1, 105.0), (2, 90.0), (3, 100.0))]
        s = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        assert measure(s).outcome_value == pytest.approx(-0.10)
        assert measure(s, spec=OutcomeSpec(horizon_bars=2)).outcome_value == 0.0
        assert measure(s, spec=OutcomeSpec(horizon_bars=2)).status is OutcomeStatus.EVALUATED


# -- alignment, exact matching, spacing --------------------------------------------------------


class TestAlignment:
    def test_wrong_symbol_raises(self):
        with pytest.raises(EvaluationError, match="symbol 'OTHER' != 'X'"):
            measure(series(6), symbol="OTHER")

    def test_wrong_interval_raises(self):
        with pytest.raises(EvaluationError, match="interval '1h' != '1d'"):
            measure(series(6), interval="1h")

    def test_wrong_basis_raises(self):
        with pytest.raises(EvaluationError, match="basis"):
            measure(series(6), basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)

    def test_series_basis_must_match_the_spec(self):
        with pytest.raises(EvaluationError, match="requires 'split_and_dividend_adjusted'"):
            measure(series(6), spec=OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        adjusted = series(6, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        with pytest.raises(EvaluationError, match="data layer"):
            measure(adjusted)

    def test_a_matching_adjusted_basis_is_accepted(self):
        adjusted = series(6, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        m = measure(adjusted, spec=OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        assert m.status is OutcomeStatus.EVALUATED

    def test_the_error_names_the_market_point_not_an_observation(self):
        with pytest.raises(EvaluationError, match="market point does not describe"):
            measure(series(6), symbol="OTHER")

    def test_a_timestamp_not_in_the_series_raises(self):
        s = series(6)
        with pytest.raises(EvaluationError, match="does not correspond to any bar"):
            measure(s, timestamp=s.timestamps[0] + timedelta(hours=7))

    def test_nearest_timestamp_is_not_matched(self):
        s = series(6)
        with pytest.raises(EvaluationError, match="never matches an approximate"):
            measure(s, timestamp=s.timestamps[1] - timedelta(seconds=1))

    def test_a_naive_timestamp_matches_nothing(self):
        s = series(6)
        with pytest.raises(EvaluationError, match="does not correspond"):
            measure(s, timestamp=s.timestamps[0].replace(tzinfo=None))

    def test_the_same_instant_in_another_zone_matches(self):
        s = series(6)
        shifted = s.timestamps[0].astimezone(timezone(timedelta(hours=-5)))
        assert measure(s, timestamp=shifted).status is OutcomeStatus.EVALUATED

    @pytest.mark.parametrize("bad", ["1day", 7, None])
    def test_an_unknown_interval_is_an_evaluation_error(self, bad):
        with pytest.raises(EvaluationError, match="market point"):
            measure(series(6), interval=bad)

    def test_an_unknown_basis_is_an_evaluation_error(self):
        with pytest.raises(EvaluationError, match="market point"):
            measure(series(6), basis="nominal")

    def test_a_non_datetime_timestamp_is_an_evaluation_error(self):
        with pytest.raises(EvaluationError, match="must be a datetime"):
            measure(series(6), timestamp="2024-01-01")

    def test_a_non_series_raises(self):
        s = series(6)
        with pytest.raises(EvaluationError, match="BarSeries"):
            measure_forward(list(s.bars), OutcomeSpec(), **point(s))

    def test_a_non_spec_raises(self):
        s = series(6)
        with pytest.raises(EvaluationError, match="OutcomeSpec"):
            measure_forward(s, "spec", **point(s))

    def test_an_empty_series_has_no_bar_to_match(self):
        empty = BarSeries.from_bars((), basis=PriceBasis.RAW, symbol="X", interval="1d", source="t")
        with pytest.raises(EvaluationError, match="does not correspond"):
            measure_forward(empty, OutcomeSpec(), symbol="X", interval="1d", basis=PriceBasis.RAW,
                            timestamp=datetime(2024, 1, 1, tzinfo=UTC))


class TestSpacingGuard:
    def _hourly(self, minutes):
        return series(4, interval="1h", step=timedelta(minutes=minutes))

    def test_overlapping_intraday_bars_are_rejected(self):
        with pytest.raises(EvaluationError, match="before the observation bar's period ends"):
            measure(self._hourly(30))

    def test_exact_and_wider_spacing_pass(self):
        assert measure(self._hourly(60)).status is OutcomeStatus.EVALUATED
        assert measure(self._hourly(180)).status is OutcomeStatus.EVALUATED

    def test_the_guard_is_not_applied_to_calendar_intervals(self):
        bars = [MarketBar("X", datetime(2024, m, 1, tzinfo=UTC), 100.0, 120.0, 80.0, 110.0, 1000.0, "1mo", "t")
                for m in (1, 2, 3, 4)]
        s = BarSeries.from_bars(bars, basis=PriceBasis.RAW)
        assert measure(s).status is OutcomeStatus.EVALUATED

    def test_the_guard_does_not_fire_for_the_last_bar(self):
        # No reference bar means no spacing to check; the status wins.
        assert measure(self._hourly(30), 3).status is OutcomeStatus.NO_REFERENCE_BAR


# -- the measurement type ------------------------------------------------------------------------


class TestForwardMeasurement:
    def test_is_frozen(self):
        m = measure(series(6))
        with pytest.raises(dataclasses.FrozenInstanceError):
            m.outcome_value = 0.0

    def test_carries_no_producer_or_claim(self):
        names = {f.name for f in dataclasses.fields(ForwardMeasurement)}
        assert names == {
            "observation_timestamp", "horizon_bars", "status", "reference_timestamp",
            "future_timestamp", "reference_price", "future_price", "outcome_value",
        }
        for forbidden in ("hypothesis", "state", "symbol", "artifact", "policy"):
            assert not any(forbidden in n for n in names)

    def test_ineligible_observation_is_not_a_market_status(self):
        with pytest.raises(OutcomeError, match="cannot be 'ineligible_observation'"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), 1, OutcomeStatus.INELIGIBLE_OBSERVATION)

    def test_an_evaluated_measurement_must_carry_every_value(self):
        with pytest.raises(OutcomeError, match="must carry"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), 1, OutcomeStatus.EVALUATED,
                               reference_price=1.0)

    def test_an_unavailable_measurement_cannot_carry_a_value(self):
        with pytest.raises(OutcomeError, match="not a zero result"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), 1, OutcomeStatus.NO_REFERENCE_BAR,
                               outcome_value=0.0)

    def test_no_reference_bar_cannot_describe_a_reference(self):
        with pytest.raises(OutcomeError, match="never reached"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), 1, OutcomeStatus.NO_REFERENCE_BAR,
                               reference_price=1.0)

    def test_insufficient_future_cannot_describe_a_future_bar(self):
        with pytest.raises(OutcomeError, match="never reached"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), 2, OutcomeStatus.INSUFFICIENT_FUTURE_DATA,
                               reference_timestamp=datetime(2024, 1, 2, tzinfo=UTC), reference_price=1.0,
                               future_price=2.0)

    @pytest.mark.parametrize("bad", [0, -1, True, 1.0, "1"])
    def test_horizon_must_be_a_positive_int(self, bad):
        with pytest.raises(OutcomeError, match="horizon_bars"):
            ForwardMeasurement(datetime(2024, 1, 1, tzinfo=UTC), bad, OutcomeStatus.NO_REFERENCE_BAR)

    def test_describe(self):
        m = measure(series(6))
        assert "-> evaluated +0.250000" in m.describe()
        assert "n/a" in measure(series(6), 5).describe()


# -- agreement with evaluate_observations ----------------------------------------------------------


def _market_half(o: EvaluatedOutcome) -> tuple:
    return (o.observation_timestamp, o.horizon_bars, o.status, o.reference_timestamp,
            o.future_timestamp, o.reference_price, o.future_price, o.outcome_value)


def _as_tuple(m: ForwardMeasurement) -> tuple:
    return (m.observation_timestamp, m.horizon_bars, m.status, m.reference_timestamp,
            m.future_timestamp, m.reference_price, m.future_price, m.outcome_value)


class TestAgreementWithEvaluateObservations:
    @pytest.mark.parametrize("horizon", [1, 2, 3, 5, 19, 20])
    @pytest.mark.parametrize("field", list(PriceField))
    def test_every_bar_agrees_exactly(self, horizon, field):
        closes = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.2 for i in range(20)]
        s = series(20, closes=closes)
        spec = OutcomeSpec(horizon_bars=horizon, future_field=field)
        outcomes = evaluate_observations(make_observations(s, [S.BULLISH] * 20), s, spec)
        for index, outcome in enumerate(outcomes):
            assert _market_half(outcome) == _as_tuple(measure(s, index, spec)), index

    def test_agreement_on_intraday_monthly_and_dst_series(self):
        hourly = series(6, interval="1h")
        monthly = BarSeries.from_bars(
            [MarketBar("X", datetime(2024, m, 1, tzinfo=UTC), m * 100.0, m * 100.0 + 90, m * 100.0 - 10,
                       m * 100.0 + 50, 1000.0, "1mo", "t") for m in range(1, 9)], basis=PriceBasis.RAW)
        dst = BarSeries.from_bars(
            [MarketBar("X", ts, 100.0, 120.0, 80.0, 110.0, 1000.0, "1d", "t") for ts in (
                datetime(2024, 3, 8, 5, tzinfo=UTC), datetime(2024, 3, 9, 4, tzinfo=UTC),
                datetime(2024, 3, 10, 4, tzinfo=UTC))], basis=PriceBasis.RAW)
        for s in (hourly, monthly, dst):
            spec = OutcomeSpec(horizon_bars=2)
            outcomes = evaluate_observations(make_observations(s, [S.BEARISH] * len(s)), s, spec)
            for index, outcome in enumerate(outcomes):
                assert _market_half(outcome) == _as_tuple(measure(s, index, spec))

    def test_the_ineligible_status_is_the_observation_layer_only(self):
        s = series(6)
        outcome = evaluate_observations(make_observations(s, [S.INSUFFICIENT_DATA] * 6), s, OutcomeSpec())[0]
        assert outcome.status is OutcomeStatus.INELIGIBLE_OBSERVATION
        assert measure(s).status is OutcomeStatus.EVALUATED  # the market point has an outcome

    def test_measurement_is_causal(self):
        closes = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.2 for i in range(20)]
        s = series(20, closes=closes)
        spec = OutcomeSpec(horizon_bars=3)
        for index in range(20):
            before = measure(s, index, spec)
            if before.future_timestamp is None:
                continue
            future_index = s.timestamps.index(before.future_timestamp)
            assert _as_tuple(measure(perturb_after(s, future_index), index, spec)) == _as_tuple(before)
            assert _as_tuple(measure(s.prefix(future_index + 1), index, spec)) == _as_tuple(before)

    def test_measurement_is_deterministic_and_does_not_mutate_the_series(self):
        s = series(8)
        before = s.values("close")
        results = {_as_tuple(measure(s, 2, OutcomeSpec(horizon_bars=3))) for _ in range(5)}
        assert len(results) == 1
        assert s.values("close") == before


# -- bit-identity of evaluate_observations before and after the extraction ------------------------


#: SHA-256 of the canonical JSON of every record and every exception message
#: produced by ``evaluate_observations`` over the 56 cases below, computed at
#: commit 74e7462 (before ``measure_forward`` existed). Never re-pin.
PRE_EXTRACTION_DIGEST = "0e886c34dc99293fd4d9b209029938399621b33732b28feac97992e8680eedf6"

#: The same baseline, one 16-hex digest per case, so a drift names the case
#: that moved rather than only the fact that something did. Same commit,
#: same rule: never re-pin. A deliberate Phase 4 semantic change is its own
#: gate and re-derives both constants from the commit before the change.
PRE_EXTRACTION_CASE_DIGESTS = {
    'adjusted ok': '57d441e11a48ba3c',
    'adjusted spec vs raw series': '5cd50654c05ce8ab',
    'basis mismatch obs': '426fed3869343f28',
    'daily20 h=1 close': 'be0885e373ab7682',
    'daily20 h=1 high': 'c62313d03d20db4b',
    'daily20 h=1 low': '3d8ad97c1471f185',
    'daily20 h=1 open': '67d29a09206c26cd',
    'daily20 h=19 close': '227335364efbd47d',
    'daily20 h=19 high': '1d668997fa81dcc7',
    'daily20 h=19 low': 'd63a6b784c8ae036',
    'daily20 h=19 open': '48a6bf2c06b0dd62',
    'daily20 h=2 close': '13d1f3d104583ee3',
    'daily20 h=2 high': 'dd8d0257f34fbee2',
    'daily20 h=2 low': '12ec97dc59990c5b',
    'daily20 h=2 open': 'edde09bd44a4ad0c',
    'daily20 h=20 close': '99bf38df20ed4042',
    'daily20 h=20 high': 'df2235f566c60598',
    'daily20 h=20 low': 'a66860dacb635ad8',
    'daily20 h=20 open': '88637049e5f8a02f',
    'daily20 h=25 close': 'c3bbe78f78131837',
    'daily20 h=25 high': '7fb91fd5707b9448',
    'daily20 h=25 low': '974033f34f02d30b',
    'daily20 h=25 open': '527396e0c964b728',
    'daily20 h=3 close': '34b5ca25456803a2',
    'daily20 h=3 high': '382a817a6507d048',
    'daily20 h=3 low': 'fbaa00a5c60ea28f',
    'daily20 h=3 open': '8c9104f5b4fd8f7e',
    'daily20 h=5 close': '1fb7886c7e7b578a',
    'daily20 h=5 high': 'beac64241cc7fd3b',
    'daily20 h=5 low': '6e701576c7cf8bbc',
    'daily20 h=5 open': '95bae6b127990160',
    'daily20 reversed': 'aa72e5a805a138e2',
    'dst daily': 'd4918760e005a70c',
    'duplicate': 'b55ff7d96585a836',
    'hourly 180m apart': 'a533fb959f539328',
    'hourly 30m apart': '10f68c9beeb47aab',
    'hourly 30m apart all insufficient': 'bbc63da17daffe77',
    'hourly 30m apart last only bullish': '975622df5d842c3c',
    'hourly 60m apart': '9bad855e8348ac40',
    'interval mismatch': 'b46b12ebd2333797',
    'monthly h3': '219ca5956b07b9f7',
    'near timestamp': '37daaf9f926bad64',
    'no observations': '4112b9a18df6832f',
    'not a series': '32bc4411f60595f4',
    'not a spec': '60f6e659095a06a4',
    'not an observation': 'c9fd6a5e6e9d6f56',
    'not an observation second': 'c9fd6a5e6e9d6f56',
    'one bar': '9b6d94fcd6471637',
    'raw spec vs adjusted series': '614e0c4cb5efb60b',
    'stray timestamp': '8ef1dc94e23b76fa',
    'stray timestamp insufficient': '8ef1dc94e23b76fa',
    'symbol mismatch': 'fa8cf865d00ea57e',
    'symbol mismatch insufficient': 'fa8cf865d00ea57e',
    'two bars h1': '1095022ac549112e',
    'two bars h2': '1e3fe4b1b62dfb79',
    'weekly h4': '74af0a686141ea3b',
}


def _observations(s, states, **over):
    return tuple(
        ResearchObservation(
            hypothesis_id="h", version=1, fingerprint="0123456789abcdef",
            symbol=over.get("symbol", s.symbol), interval=over.get("interval", s.interval),
            basis=over.get("basis", s.basis), timestamp=b.timestamp, state=st,
            evidence={}, reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
        )
        for b, st in zip(s.bars, states)
    )


def _comparable(o: EvaluatedOutcome) -> list:
    return [o.hypothesis_id, o.hypothesis_version, o.hypothesis_fingerprint, o.symbol,
            o.interval.value, o.basis.value, o.observation_timestamp.isoformat(),
            o.observation_state.value, o.spec_fingerprint, o.horizon_bars, o.status.value,
            None if o.reference_timestamp is None else o.reference_timestamp.isoformat(),
            None if o.future_timestamp is None else o.future_timestamp.isoformat(),
            o.reference_price, o.future_price, o.outcome_value]


def _golden_cases() -> dict:
    closes20 = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.2 for i in range(20)]
    cases = {}
    base = series(20, closes=closes20)
    states_mixed = [S.INSUFFICIENT_DATA, S.INSUFFICIENT_DATA, S.BULLISH, S.BEARISH, S.NEUTRAL] * 4
    for h in (1, 2, 3, 5, 19, 20, 25):
        for field in (PriceField.CLOSE, PriceField.OPEN, PriceField.HIGH, PriceField.LOW):
            cases[f"daily20 h={h} {field.value}"] = (
                _observations(base, states_mixed), base, OutcomeSpec(horizon_bars=h, future_field=field))
    cases["daily20 reversed"] = (tuple(reversed(_observations(base, states_mixed))), base,
                                 OutcomeSpec(horizon_bars=3))
    one = series(1)
    cases["one bar"] = (_observations(one, [S.BULLISH]), one, OutcomeSpec())
    two = series(2)
    cases["two bars h1"] = (_observations(two, [S.BULLISH, S.BULLISH]), two, OutcomeSpec())
    cases["two bars h2"] = (_observations(two, [S.BULLISH, S.BULLISH]), two, OutcomeSpec(horizon_bars=2))
    cases["no observations"] = ((), base, OutcomeSpec())
    adj = series(8, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
    cases["adjusted ok"] = (_observations(adj, [S.BULLISH] * 8), adj,
                            OutcomeSpec(horizon_bars=2, required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
    cases["adjusted spec vs raw series"] = (_observations(base, [S.BULLISH] * 20), base,
                                            OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
    cases["raw spec vs adjusted series"] = (_observations(adj, [S.BULLISH] * 8), adj, OutcomeSpec())
    for minutes in (30, 60, 180):
        hs = series(6, interval="1h", step=timedelta(minutes=minutes))
        cases[f"hourly {minutes}m apart"] = (_observations(hs, [S.BULLISH] * 6), hs, OutcomeSpec(horizon_bars=2))
    hs30 = series(6, interval="1h", step=timedelta(minutes=30))
    cases["hourly 30m apart all insufficient"] = (_observations(hs30, [S.INSUFFICIENT_DATA] * 6), hs30, OutcomeSpec())
    cases["hourly 30m apart last only bullish"] = (
        _observations(hs30, [S.INSUFFICIENT_DATA] * 5 + [S.BULLISH]), hs30, OutcomeSpec())
    mo = BarSeries.from_bars(
        [MarketBar("X", datetime(2024, m, 1, tzinfo=UTC), m * 100.0, m * 100.0 + 90, m * 100.0 - 10,
                   m * 100.0 + 50, 1000.0, "1mo", "t") for m in range(1, 9)], basis=PriceBasis.RAW)
    cases["monthly h3"] = (_observations(mo, [S.BULLISH] * 8), mo, OutcomeSpec(horizon_bars=3))
    wk = series(10, interval="1wk")
    cases["weekly h4"] = (_observations(wk, [S.BEARISH] * 10), wk, OutcomeSpec(horizon_bars=4))
    dst = BarSeries.from_bars(
        [MarketBar("X", ts, 100.0, 120.0, 80.0, 110.0, 1000.0, "1d", "t") for ts in (
            datetime(2024, 3, 8, 5, tzinfo=UTC), datetime(2024, 3, 9, 4, tzinfo=UTC),
            datetime(2024, 3, 10, 4, tzinfo=UTC))], basis=PriceBasis.RAW)
    cases["dst daily"] = (_observations(dst, [S.BULLISH] * 3), dst, OutcomeSpec())
    cases["symbol mismatch"] = (_observations(base, [S.BULLISH] * 20, symbol="OTHER"), base, OutcomeSpec())
    cases["interval mismatch"] = (_observations(base, [S.BULLISH] * 20, interval="1h"), base, OutcomeSpec())
    cases["basis mismatch obs"] = (
        _observations(base, [S.BULLISH] * 20, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED), base, OutcomeSpec())
    first = _observations(base, [S.BULLISH])[0]
    stray = (dataclasses.replace(first, evidence={}, timestamp=base.timestamps[0] + timedelta(hours=7)),)
    cases["stray timestamp"] = (stray, base, OutcomeSpec())
    cases["stray timestamp insufficient"] = (
        (dataclasses.replace(stray[0], evidence={}, state=S.INSUFFICIENT_DATA),), base, OutcomeSpec())
    cases["near timestamp"] = (
        (dataclasses.replace(first, evidence={}, timestamp=base.timestamps[1] - timedelta(seconds=1)),),
        base, OutcomeSpec())
    obs = _observations(base, [S.BULLISH] * 20)
    cases["duplicate"] = (obs + (obs[0],), base, OutcomeSpec())
    cases["not a series"] = (obs, list(base.bars), OutcomeSpec())
    cases["not a spec"] = (obs, base, "spec")
    cases["not an observation"] = (("x",), base, OutcomeSpec())
    cases["not an observation second"] = ((obs[0], "x"), base, OutcomeSpec())
    cases["symbol mismatch insufficient"] = (
        _observations(base, [S.INSUFFICIENT_DATA] * 20, symbol="OTHER"), base, OutcomeSpec())
    return cases


def _golden_snapshot() -> dict:
    out = {}
    for name, (o, s, sp) in _golden_cases().items():
        try:
            out[name] = {"records": [_comparable(r) for r in evaluate_observations(o, s, sp)]}
        except Exception as exc:  # noqa: BLE001 - the exception *is* the snapshot
            out[name] = {"error": type(exc).__name__, "message": str(exc)}
    return out


class TestEvaluateObservationsIsBitIdenticalToPreExtraction:
    def test_the_case_set_is_the_pinned_one(self):
        snapshot = _golden_snapshot()
        assert set(snapshot) == set(PRE_EXTRACTION_CASE_DIGESTS)
        assert len(snapshot) == 56
        assert sum(len(v["records"]) for v in snapshot.values() if "records" in v) == 638
        assert sum(1 for v in snapshot.values() if "error" in v) == 15

    def test_each_case_matches_its_pre_extraction_digest(self):
        """Per-case pins: a failure here says *which* case drifted, and the
        assertion message shows that case's current records or error so the
        drift can be read, not only detected."""
        snapshot = _golden_snapshot()
        drifted = {
            name: snapshot[name]
            for name, expected in PRE_EXTRACTION_CASE_DIGESTS.items()
            if hashlib.sha256(
                json.dumps(snapshot[name], sort_keys=True).encode("utf-8")
            ).hexdigest()[:16] != expected
        }
        assert not drifted, (
            "evaluate_observations output drifted from the pre-extraction baseline "
            f"(commit 74e7462) in {len(drifted)} case(s): {sorted(drifted)}. "
            "Current output for the first drifted case: "
            + json.dumps(next(iter(drifted.values())), sort_keys=True, indent=1)
        )

    def test_records_and_exception_messages_match_the_pre_extraction_digest(self):
        """The whole-snapshot pin. Redundant with the per-case pins by
        construction; kept because it is the single number that was recorded
        against the pre-extraction commit."""
        text = json.dumps(_golden_snapshot(), sort_keys=True, indent=1)
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PRE_EXTRACTION_DIGEST, (
            "whole-snapshot digest differs from the pre-extraction baseline; "
            "see test_each_case_matches_its_pre_extraction_digest for the case"
        )
