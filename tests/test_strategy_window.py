"""The causal evidence window: bounded history without weakening causality."""

from __future__ import annotations

import pytest

from src.data.series import PriceBasis
from src.strategies import (
    EvidenceError,
    EvidenceWindow,
    FeatureSpec,
    HypothesisError,
    HypothesisSpec,
    ReasonCode,
    ResearchHypothesis,
    ResearchState,
    TrendCrossover,
    build_evidence,
)
from tests.conftest import make_series
from tests.strategy_lookahead import (
    assert_hypothesis_causal,
    assert_hypothesis_deterministic,
    assert_series_unchanged,
)

FAST = FeatureSpec("sma", {"period": 2, "field": "close"})
SLOW = FeatureSpec("sma", {"period": 3, "field": "close"})


def window(rows, lookback):
    return EvidenceWindow(rows, lookback)


class Crossing(ResearchHypothesis):
    """Minimal history-dependent hypothesis for framework tests."""

    hypothesis_id = "test_crossing"
    version = 1
    display_name = "Test crossing"
    required_features = (FAST, SLOW)
    lookback = 1

    def _classify(self, values):
        now = values.past(FAST, 0) - values.past(SLOW, 0)
        before = values.past(FAST, 1) - values.past(SLOW, 1)
        if before <= 0 < now:
            return ResearchState.BULLISH, (ReasonCode.CROSSED_ABOVE,)
        if before >= 0 > now:
            return ResearchState.BEARISH, (ReasonCode.CROSSED_BELOW,)
        return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)


class PointInTime(ResearchHypothesis):
    """lookback defaults to 0: the pre-window contract, unchanged."""

    hypothesis_id = "test_point_in_time"
    version = 1
    display_name = "Test point in time"
    required_features = (FAST,)

    def _classify(self, values):
        # Reads as a plain mapping, exactly as before the window existed.
        return (
            ResearchState.BULLISH if values[FAST.key] > 0 else ResearchState.BEARISH
        ), (ReasonCode.FAST_ABOVE_SLOW,)


def rising(n=20):
    return make_series([10.0 + i * 0.5 for i in range(n)])


class TestWindowShape:
    def test_lookback_zero_is_current_only(self):
        w = window([{FAST.key: 5.0}], 0)
        assert w[FAST.key] == 5.0
        assert w.current(FAST) == 5.0
        assert w.lookback == 0

    def test_previous_observations_are_reachable(self):
        w = window([{FAST.key: 3.0}, {FAST.key: 2.0}, {FAST.key: 1.0}], 2)
        assert (w.past(FAST, 0), w.past(FAST, 1), w.past(FAST, 2)) == (3.0, 2.0, 1.0)

    def test_the_exact_window_boundary_is_reachable_and_no_further(self):
        w = window([{FAST.key: 3.0}, {FAST.key: 2.0}], 1)
        assert w.past(FAST, 1) == 2.0
        with pytest.raises(EvidenceError, match="exceeds the declared lookback"):
            w.past(FAST, 2)

    def test_row_count_must_match_the_lookback(self):
        with pytest.raises(EvidenceError, match="needs exactly"):
            window([{FAST.key: 1.0}], 1)

    def test_it_behaves_as_a_mapping_of_the_current_bar(self):
        w = window([{FAST.key: 3.0, SLOW.key: 9.0}, {FAST.key: 2.0, SLOW.key: 8.0}], 1)
        assert set(w) == {FAST.key, SLOW.key}
        assert dict(w) == {FAST.key: 3.0, SLOW.key: 9.0}  # current only

    def test_a_short_form_spec_resolves_against_the_window(self):
        w = window([{FAST.key: 3.0}], 0)
        assert w.past(FeatureSpec("sma", {"period": 2}), 0) == 3.0

    def test_an_undeclared_feature_is_refused(self):
        w = window([{FAST.key: 3.0}], 0)
        with pytest.raises(EvidenceError, match="not part of this hypothesis"):
            w.past(SLOW, 0)


class TestWindowIsStructurallyCausal:
    """Future data must be ABSENT, not merely forbidden by documentation."""

    def _w(self):
        return window([{FAST.key: 3.0}, {FAST.key: 2.0}], 1)

    def test_t_plus_one_is_unreachable(self):
        with pytest.raises(EvidenceError, match="must not be negative"):
            self._w().past(FAST, -1)

    def test_negative_indexing_cannot_wrap_into_the_future(self):
        # Python's negative indexing would silently return the OLDEST row;
        # rejecting negatives outright removes the escape entirely.
        for ago in (-1, -2, -99):
            with pytest.raises(EvidenceError, match="must not be negative"):
                self._w().past(FAST, ago)

    def test_an_absurd_lookback_request_is_refused(self):
        with pytest.raises(EvidenceError, match="exceeds the declared lookback"):
            self._w().past(FAST, 10_000)

    def test_a_non_integer_offset_is_refused(self):
        for ago in (1.0, "1", None, True):
            with pytest.raises(EvidenceError):
                self._w().past(FAST, ago)

    def test_dataset_length_is_unavailable(self):
        # len() is the FEATURE count. A hypothesis cannot learn how many bars
        # exist, so it cannot condition on the presence of future rows.
        evidence = build_evidence(rising(40), [FAST, SLOW])
        captured = {}

        class Peek(Crossing):
            hypothesis_id = "peek_len"
            def _classify(self, values):
                captured.setdefault("lengths", set()).add(len(values))
                return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)

        Peek().evaluate(evidence)
        assert captured["lengths"] == {2}  # two features, every bar

    def test_timestamps_are_unavailable(self):
        w = self._w()
        for attribute in ("timestamps", "timestamp", "index", "bars", "series"):
            assert not hasattr(w, attribute)

    def test_future_extrema_are_unavailable(self):
        # The window holds only its own rows; there is no collection of all
        # values to take a min or max over.
        w = window([{FAST.key: 3.0}, {FAST.key: 2.0}], 1)
        assert set(w.values()) == {3.0}  # current row only, not the history

    def test_the_window_is_read_only(self):
        w = self._w()
        with pytest.raises(TypeError):
            w[FAST.key] = 99.0

    def test_mutating_the_source_rows_cannot_change_the_window(self):
        rows = [{FAST.key: 3.0}, {FAST.key: 2.0}]
        w = window(rows, 1)
        rows[0][FAST.key] = 999.0
        rows[1] = {FAST.key: 888.0}
        assert w.past(FAST, 0) == 3.0
        assert w.past(FAST, 1) == 2.0


class TestInsufficientHistory:
    def test_a_bar_too_early_to_fill_the_window_is_insufficient_not_an_error(self):
        # The dataset simply starts somewhere; that is not a fault.
        observations = Crossing().evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert observations[0].state is ResearchState.INSUFFICIENT_DATA
        assert observations[0].reason_codes == (ReasonCode.WARMUP_INCOMPLETE,)

    def test_history_shortage_and_warm_up_are_reported_identically(self):
        observations = Crossing().evaluate(build_evidence(rising(), [FAST, SLOW]))
        early = [o for o in observations if o.state is ResearchState.INSUFFICIENT_DATA]
        assert all(o.reason_codes == (ReasonCode.WARMUP_INCOMPLETE,) for o in early)

    def test_the_first_fully_available_bar_is_classified(self):
        # SLOW is sma(3) (ready at index 2); lookback 1 needs index >= 1.
        observations = Crossing().evaluate(build_evidence(rising(), [FAST, SLOW]))
        ready = [
            index
            for index, o in enumerate(observations)
            if o.state is not ResearchState.INSUFFICIENT_DATA
        ]
        assert ready[0] == 3  # index 2 is ready, but its predecessor is not

    def test_a_lookback_longer_than_the_dataset_yields_all_insufficient(self):
        class Deep(Crossing):
            hypothesis_id = "deep"
            lookback = 500

        observations = Deep().evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert all(o.state is ResearchState.INSUFFICIENT_DATA for o in observations)

    def test_structural_problems_still_raise_rather_than_reporting_insufficient(self):
        with pytest.raises(HypothesisError, match="missing required feature"):
            Crossing().evaluate(build_evidence(rising(), [FAST]))


class TestLookbackIdentity:
    def _spec(self, lookback):
        return HypothesisSpec("demo", 1, "Demo", (FAST,), None, lookback)

    def test_lookback_participates_in_the_fingerprint(self):
        assert self._spec(0).fingerprint != self._spec(1).fingerprint
        assert self._spec(1).fingerprint != self._spec(3).fingerprint

    def test_changing_lookback_cannot_masquerade_as_the_original(self):
        original, changed = self._spec(1), self._spec(3)
        assert original.hypothesis_id == changed.hypothesis_id
        assert original.version == changed.version
        assert original.label != changed.label

    def test_lookback_appears_in_the_canonical_form(self):
        assert "lookback=3" in self._spec(3).canonical_form

    @pytest.mark.parametrize("lookback", [-1, 1.5, "1", True])
    def test_invalid_lookbacks_are_rejected(self, lookback):
        from src.strategies import SpecError

        with pytest.raises(SpecError):
            HypothesisSpec("demo", 1, "Demo", (FAST,), None, lookback)

    def test_the_observation_records_a_history_hypothesis_correctly(self):
        hypothesis = Crossing()
        observations = hypothesis.evaluate(build_evidence(rising(), [FAST, SLOW]))
        assert observations[-1].fingerprint == hypothesis.fingerprint
        assert observations[-1].timestamp == build_evidence(
            rising(), [FAST, SLOW]
        ).timestamps[-1]


class TestBackwardCompatibility:
    """Point-in-time hypotheses must be unaffected by the window."""

    def test_lookback_defaults_to_zero(self):
        assert PointInTime().spec.lookback == 0

    def test_a_point_in_time_hypothesis_reads_the_window_as_a_mapping(self):
        observations = PointInTime().evaluate(build_evidence(rising(), [FAST]))
        ready = [o for o in observations if o.state is not ResearchState.INSUFFICIENT_DATA]
        assert ready and all(o.state is ResearchState.BULLISH for o in ready)

    def test_the_shipped_point_in_time_hypotheses_still_work(self):
        from src.strategies import MomentumInTrendContext, TrendAlignment

        series = make_series([10.0 + i * 0.4 for i in range(80)])
        for factory in (TrendAlignment, MomentumInTrendContext):
            hypothesis = factory()
            assert hypothesis.spec.lookback == 0
            observations = hypothesis.evaluate(
                build_evidence(series, hypothesis.spec.required_features)
            )
            assert len(observations) == 80


class TestHistoryHypothesisCausality:
    @pytest.fixture
    def wavy(self):
        import math

        closes = [10.0 + 3.0 * math.sin(i / 5.0) + i * 0.05 for i in range(40)]
        return make_series(closes)

    def _runner(self, hypothesis):
        return lambda series: hypothesis.evaluate(
            build_evidence(series, hypothesis.spec.required_features)
        )

    def test_a_history_dependent_hypothesis_is_still_causal(self, wavy):
        assert_hypothesis_causal(self._runner(Crossing()), wavy, label="crossing")

    def test_the_shipped_crossover_is_causal(self, wavy):
        assert_hypothesis_causal(self._runner(TrendCrossover()), wavy, label="crossover")

    def test_it_is_deterministic(self, wavy):
        assert_hypothesis_deterministic(self._runner(Crossing()), wavy)

    def test_it_does_not_mutate_the_series(self, wavy):
        assert_series_unchanged(self._runner(Crossing()), wavy)

    def test_a_deep_lookback_is_still_causal(self, wavy):
        class Deep(Crossing):
            hypothesis_id = "deep_causal"
            lookback = 5

            def _classify(self, values):
                oldest = values.past(FAST, 5)
                newest = values.past(FAST, 0)
                return (
                    ResearchState.BULLISH if newest > oldest else ResearchState.BEARISH
                ), (ReasonCode.RELATIONSHIP_UNCHANGED,)

        assert_hypothesis_causal(self._runner(Deep()), wavy, label="deep")

    def test_a_hypothesis_reaching_past_its_declared_lookback_fails_loudly(self, wavy):
        class Greedy(Crossing):
            hypothesis_id = "greedy"
            lookback = 1

            def _classify(self, values):
                values.past(FAST, 2)  # beyond what it declared
                return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)

        with pytest.raises(EvidenceError, match="exceeds the declared lookback"):
            Greedy().evaluate(build_evidence(wavy, [FAST, SLOW]))


class TestWindowAlignment:
    """The window inherits EvidenceSet's alignment guarantees."""

    def test_symbol_mismatch_is_rejected_before_any_window_is_built(self):
        from src.features import sma
        from src.strategies import EvidenceSet

        with pytest.raises(EvidenceError, match="symbol"):
            EvidenceSet.from_features(
                [sma(rising(), 2), sma(make_series([10.0] * 20, symbol="OTHER"), 3)]
            )

    def test_interval_mismatch_is_rejected(self):
        from src.features import sma
        from src.strategies import EvidenceSet

        with pytest.raises(EvidenceError, match="interval"):
            EvidenceSet.from_features(
                [sma(rising(), 2), sma(make_series([10.0] * 20, interval="1h"), 3)]
            )

    def test_basis_mismatch_is_rejected(self):
        from src.features import sma
        from src.strategies import EvidenceSet

        adjusted = make_series([10.0] * 20, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        with pytest.raises(EvidenceError, match="basis"):
            EvidenceSet.from_features([sma(rising(), 2), sma(adjusted, 3)])

    def test_history_rows_come_from_consecutive_aligned_bars(self):
        """The window's rows must be T, T-1, ... in that order."""
        evidence = build_evidence(rising(), [FAST, SLOW])
        captured = []

        class Recorder(Crossing):
            hypothesis_id = "recorder"
            def _classify(self, values):
                captured.append((values.past(FAST, 0), values.past(FAST, 1)))
                return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)

        Recorder().evaluate(evidence)
        fast_values = evidence.features[FAST.key].values
        ready_indices = [
            i for i in range(len(evidence))
            if i >= 1 and all(
                evidence.features[k].values[j] is not None
                for k in (FAST.key, SLOW.key) for j in (i, i - 1)
            )
        ]
        expected = [(fast_values[i], fast_values[i - 1]) for i in ready_indices]
        assert captured == expected
