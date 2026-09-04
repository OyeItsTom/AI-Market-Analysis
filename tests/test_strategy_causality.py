"""Causality, determinism and isolation for research hypotheses.

The most important file in Phase 3. A hypothesis observation at bar k must not
depend on anything after k -- verified as a property of the whole pipeline
(bars -> features -> evidence -> classification), not by reading the code.
"""

from __future__ import annotations

import pytest

from src.strategies import (
    FeatureSpec,
    MomentumInTrendContext,
    ReasonCode,
    ResearchHypothesis,
    ResearchObservation,
    ResearchState,
    TrendAlignment,
    build_evidence,
)
from tests.conftest import make_series
from tests.strategy_lookahead import (
    assert_hypothesis_causal,
    assert_hypothesis_deterministic,
    assert_observations_prefix_invariant,
    assert_observations_truncation_invariant,
    assert_series_unchanged,
)

SPEC = FeatureSpec("sma", {"period": 3, "field": "close"})


@pytest.fixture
def wavy():
    """Non-monotonic, so global extrema do not sit permanently in the prefix."""
    closes = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.15 for i in range(40)]
    return make_series(
        closes,
        highs=[c * 1.04 for c in closes],
        lows=[c * 0.96 for c in closes],
        volumes=[1000.0 + 50 * (i % 9) for i in range(len(closes))],
    )


def runner(hypothesis):
    """The full pipeline as one callable: bars in, observations out."""
    return lambda series: hypothesis.evaluate(
        build_evidence(series, hypothesis.spec.required_features)
    )


class Honest(ResearchHypothesis):
    hypothesis_id = "honest"
    version = 1
    display_name = "Honest reference hypothesis"
    required_features = (SPEC,)

    def _classify(self, values):
        value = values[SPEC.key]
        if value > 12:
            return ResearchState.BULLISH, (ReasonCode.FAST_ABOVE_SLOW,)
        if value < 11:
            return ResearchState.BEARISH, (ReasonCode.FAST_BELOW_SLOW,)
        return ResearchState.NEUTRAL, (ReasonCode.FAST_EQUALS_SLOW,)


SHIPPED = [
    ("trend_alignment", TrendAlignment),
    ("momentum_in_trend_context", MomentumInTrendContext),
    ("honest_reference", Honest),
]
IDS = [name for name, _ in SHIPPED]
FACTORIES = [factory for _, factory in SHIPPED]


class TestCausality:
    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_tail_perturbation_at_every_split(self, factory, wavy):
        assert_hypothesis_causal(runner(factory()), wavy, label=factory.hypothesis_id)

    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_truncation_invariance(self, factory, wavy):
        assert_observations_truncation_invariant(
            runner(factory()), wavy, label=factory.hypothesis_id
        )

    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_only_the_final_bar_changing_cannot_move_earlier_observations(
        self, factory, wavy
    ):
        assert_observations_prefix_invariant(
            runner(factory()), wavy, len(wavy) - 1, label=factory.hypothesis_id
        )


def _rebuild(hypothesis, observation, state):
    return ResearchObservation.build(
        hypothesis.spec,
        symbol=observation.symbol,
        interval=observation.interval,
        basis=observation.basis,
        timestamp=observation.timestamp,
        state=state,
        evidence=observation.evidence,
        reason_codes=observation.reason_codes,
    )


class TestHarnessCatchesCheats:
    """The harness is only worth what it catches.

    Each of these overrides ``evaluate`` -- the framework's structural
    guarantee only constrains ``_classify``, so a subclass CAN cheat, and the
    harness must be what stops it. Every cheat below was executed against the
    harness during development; the global-minimum one initially survived and
    the perturbation was fixed because of it.
    """

    def _check_caught(self, hypothesis, wavy):
        with pytest.raises(AssertionError):
            assert_hypothesis_causal(runner(hypothesis), wavy)

    def test_length_based_cheat_is_caught(self, wavy):
        class LenCheat(Honest):
            hypothesis_id = "len_cheat"
            def evaluate(self, evidence):
                many = len(evidence) > 20
                return tuple(
                    _rebuild(self, o, ResearchState.BULLISH if many else ResearchState.BEARISH)
                    for o in ResearchHypothesis.evaluate(self, evidence)
                )
        self._check_caught(LenCheat(), wavy)

    def test_final_timestamp_cheat_is_caught(self, wavy):
        class TsCheat(Honest):
            hypothesis_id = "ts_cheat"
            def evaluate(self, evidence):
                last = evidence.timestamps[-1] if len(evidence) else None
                even = bool(last and last.day % 2 == 0)
                return tuple(
                    _rebuild(self, o, ResearchState.BULLISH if even else ResearchState.BEARISH)
                    for o in ResearchHypothesis.evaluate(self, evidence)
                )
        self._check_caught(TsCheat(), wavy)

    def test_next_bar_cheat_is_caught(self, wavy):
        class NextCheat(Honest):
            hypothesis_id = "next_cheat"
            def evaluate(self, evidence):
                values = evidence.features[SPEC.key].values
                out = []
                for index, observation in enumerate(ResearchHypothesis.evaluate(self, evidence)):
                    following = values[index + 1] if index + 1 < len(values) else None
                    state = (
                        ResearchState.BULLISH
                        if (following or 0) > (values[index] or 0)
                        else ResearchState.BEARISH
                    )
                    out.append(_rebuild(self, observation, state))
                return tuple(out)
        self._check_caught(NextCheat(), wavy)

    def test_global_maximum_cheat_is_caught(self, wavy):
        class MaxCheat(Honest):
            hypothesis_id = "max_cheat"
            def evaluate(self, evidence):
                seen = [v for v in evidence.features[SPEC.key].values if v is not None]
                peak = max(seen) if seen else 0.0
                return tuple(
                    _rebuild(self, o,
                             ResearchState.BULLISH
                             if (o.evidence.get(SPEC.key) or 0) >= peak * 0.9
                             else ResearchState.NEUTRAL)
                    for o in ResearchHypothesis.evaluate(self, evidence)
                )
        self._check_caught(MaxCheat(), wavy)

    def test_global_minimum_cheat_is_caught(self, wavy):
        """Regression.

        This one survived the first harness: the perturbation alternated
        up/down on every bar, which cancels under a moving average, so the
        minimum of the SMA evidence never moved. The perturbation now uses
        contiguous blocks.
        """
        class MinCheat(Honest):
            hypothesis_id = "min_cheat"
            def evaluate(self, evidence):
                seen = [v for v in evidence.features[SPEC.key].values if v is not None]
                floor = min(seen) if seen else 0.0
                return tuple(
                    _rebuild(self, o,
                             ResearchState.BULLISH
                             if (o.evidence.get(SPEC.key) or 0) <= floor * 1.1
                             else ResearchState.NEUTRAL)
                    for o in ResearchHypothesis.evaluate(self, evidence)
                )
        self._check_caught(MinCheat(), wavy)

    def test_future_row_existence_cheat_is_caught(self, wavy):
        class ExistsCheat(Honest):
            hypothesis_id = "exists_cheat"
            def evaluate(self, evidence):
                total = len(evidence)
                return tuple(
                    _rebuild(self, o,
                             ResearchState.BULLISH if index + 1 < total else ResearchState.NEUTRAL)
                    for index, o in enumerate(ResearchHypothesis.evaluate(self, evidence))
                )
        self._check_caught(ExistsCheat(), wavy)

    def test_off_by_one_window_including_the_next_bar_is_caught(self, wavy):
        """A window built one index too far forward must not slip through."""
        from src.strategies import EvidenceWindow

        class OffByOne(Honest):
            hypothesis_id = "off_by_one"
            lookback = 1

            def _classify(self, values):
                # Genuinely uses the (illegitimately supplied) next bar: rows
                # are [T+1, T], so past(...,0) is the FUTURE value.
                future, present = values.past(SPEC, 0), values.past(SPEC, 1)
                return (
                    ResearchState.BULLISH if future > present else ResearchState.BEARISH
                ), (ReasonCode.RELATIONSHIP_UNCHANGED,)

            def _observe(self, evidence, index):
                specs = self._spec.required_features
                ahead = min(index + 1, len(evidence) - 1)
                rows = [evidence.snapshot(specs, ahead), evidence.snapshot(specs, index)]
                if any(value is None for row in rows for value in row.values()):
                    return ResearchHypothesis._observe(self, evidence, index)
                state, codes = self._classify(EvidenceWindow(rows, 1))
                return ResearchObservation.build(
                    self.spec, symbol=evidence.symbol, interval=evidence.interval,
                    basis=evidence.basis, timestamp=evidence.timestamps[index],
                    state=state, evidence=rows[1], reason_codes=codes,
                )

        self._check_caught(OffByOne(), wavy)

    def test_a_retained_window_cannot_be_mutated_later(self, wavy):
        """A hypothesis keeping a reference must not be able to corrupt it."""
        stash = []

        class Stash(Honest):
            hypothesis_id = "stash"
            lookback = 1

            def _classify(self, values):
                stash.append(values)
                if len(stash) > 1:
                    with pytest.raises(TypeError):
                        stash[0][SPEC.key] = 999.0
                return ResearchState.NEUTRAL, (ReasonCode.RELATIONSHIP_UNCHANGED,)

        assert_hypothesis_causal(runner(Stash()), wavy)
        assert all(w[SPEC.key] != 999.0 for w in stash)

    def test_the_perturbation_moves_smoothed_statistics(self, wavy):
        """Pins the property that makes the min/max cheats detectable."""
        from tests.lookahead import perturb_tail

        def extremes(series):
            evidence = build_evidence(series, [SPEC])
            seen = [v for v in evidence.features[SPEC.key].values if v is not None]
            return min(seen), max(seen)

        before, after = extremes(wavy), extremes(perturb_tail(wavy, len(wavy) // 2))
        assert after[0] < before[0], "perturbed tail must lower the smoothed minimum"
        assert after[1] > before[1], "perturbed tail must raise the smoothed maximum"

    def test_an_honest_hypothesis_is_not_falsely_accused(self, wavy):
        assert_hypothesis_causal(runner(Honest()), wavy)


class TestDeterminismAndIsolation:
    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_repeated_runs_are_identical(self, factory, wavy):
        assert_hypothesis_deterministic(runner(factory()), wavy)

    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_evaluation_does_not_mutate_the_bars(self, factory, wavy):
        assert_series_unchanged(runner(factory()), wavy)

    @pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
    def test_evaluation_does_not_mutate_the_evidence(self, factory, wavy):
        hypothesis = factory()
        evidence = build_evidence(wavy, hypothesis.spec.required_features)
        before = {key: tuple(feature.values) for key, feature in evidence.features.items()}
        hypothesis.evaluate(evidence)
        after = {key: tuple(feature.values) for key, feature in evidence.features.items()}
        assert before == after

    def test_two_instances_agree(self, wavy):
        evidence = build_evidence(wavy, TrendAlignment().spec.required_features)
        first = [o.state for o in TrendAlignment().evaluate(evidence)]
        second = [o.state for o in TrendAlignment().evaluate(evidence)]
        assert first == second

    def test_a_hypothesis_cannot_recompute_features_with_other_parameters(self, wavy):
        """The hook receives values, not bars.

        ``_classify`` is handed an EvidenceWindow over the declared lookback.
        There is no series in scope, so a hypothesis cannot quietly compute an
        RSI(7) while declaring RSI(14), and nothing in the window exposes bars,
        timestamps or dataset size.
        """
        import inspect

        from src.strategies.evidence import EvidenceWindow

        signature = inspect.signature(ResearchHypothesis._classify)
        assert list(signature.parameters) == ["self", "values"]

        captured = {}

        class Capturing(Honest):
            hypothesis_id = "capturing"
            def _classify(self, values):
                captured["window"] = values
                captured["keys"] = set(values)
                captured["public"] = {
                    name for name in dir(values) if not name.startswith("_")
                }
                return ResearchState.NEUTRAL, (ReasonCode.FAST_EQUALS_SLOW,)

        Capturing().evaluate(build_evidence(wavy, [SPEC]))
        window = captured["window"]

        assert isinstance(window, EvidenceWindow)
        assert captured["keys"] == {SPEC.key}
        # Nothing that would let a hypothesis reach bars, dates or dataset size.
        assert captured["public"] <= {
            "past", "current", "lookback", "keys", "values", "items", "get",
        }
        for forbidden in ("timestamps", "bars", "series", "symbol", "features"):
            assert not hasattr(window, forbidden), f"window exposes {forbidden}"
        # len() is the feature count, never the number of bars.
        assert len(window) == 1


class TestNoProviderOrNetworkDependency:
    #: Modules a research hypothesis must never depend on.
    FORBIDDEN_IMPORTS = (
        "yfinance", "requests", "urllib", "http", "socket", "ssl",
        "anthropic", "openai", "src.data.provider", "src.data.providers",
    )

    def _imported_modules(self, path):
        """Every module imported by a file, via AST rather than substring match.

        Substring matching over source text is useless here: the modules'
        docstrings legitimately contain the word "provider" while stating that
        they never reach one.
        """
        import ast

        modules = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_strategy_modules_import_no_provider_or_network(self):
        import pathlib

        offenders = []
        for path in sorted(pathlib.Path("src/strategies").glob("*.py")):
            for module in self._imported_modules(path):
                root = module.split(".")[0]
                for forbidden in self.FORBIDDEN_IMPORTS:
                    if module == forbidden or module.startswith(forbidden + ".") or root == forbidden:
                        offenders.append(f"{path.name} imports {module}")
        assert not offenders, f"strategy code reaches outside its layer: {offenders}"

    def test_strategy_modules_depend_only_on_data_models_and_features(self):
        import pathlib

        allowed_prefixes = ("src.data.models", "src.data.series", "src.features")
        offenders = []
        for path in sorted(pathlib.Path("src/strategies").glob("*.py")):
            for module in self._imported_modules(path):
                if module.startswith("src.") and not module.startswith(allowed_prefixes):
                    offenders.append(f"{path.name} imports {module}")
        assert not offenders, (
            "the dependency direction is MarketBar -> BarSeries -> features -> "
            f"hypothesis; these break it: {offenders}"
        )

    def test_no_order_or_execution_vocabulary(self):
        import pathlib

        banned = ("place_order", "submit_order", "execute_trade",
                  "position_size", "stop_loss", "take_profit")
        offenders = [
            f"{path.name}: {needle}"
            for path in sorted(pathlib.Path("src/strategies").glob("*.py"))
            for needle in banned
            if needle in path.read_text()
        ]
        assert not offenders, f"execution vocabulary found: {offenders}"

    def test_evaluation_does_not_read_the_clock(self, wavy):
        """Determinism check: freezing nothing, the result must not vary."""
        hypothesis = TrendAlignment()
        evidence = build_evidence(wavy, hypothesis.spec.required_features)
        import time

        first = [o.state for o in hypothesis.evaluate(evidence)]
        time.sleep(0.01)
        assert [o.state for o in hypothesis.evaluate(evidence)] == first
