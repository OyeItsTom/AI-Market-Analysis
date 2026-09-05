"""Aggregation: alignment, exact ensemble, the locked V1 table, and timing."""

import ast
import itertools
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.assessments import (
    AssessmentAggregationRule,
    AssessmentError,
    AssessmentPolicy,
    AssessmentReasonCode,
    AssessmentState,
    HypothesisIdentity,
    assess,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

B = ResearchState.BULLISH
BE = ResearchState.BEARISH
N = ResearchState.NEUTRAL
INS = ResearchState.INSUFFICIENT_DATA


def obs(
    hypothesis_id,
    state,
    *,
    version=1,
    fingerprint="fp1",
    symbol="AAPL",
    interval=Interval.DAY_1,
    basis=PriceBasis.RAW,
    timestamp=T0,
):
    return ResearchObservation(
        hypothesis_id=hypothesis_id,
        version=version,
        fingerprint=fingerprint,
        symbol=symbol,
        interval=interval,
        basis=basis,
        timestamp=timestamp,
        state=state,
        evidence={"value": 1.0},
        reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
    )


def policy_for(*names, minimum=1, version=1, fingerprint="fp1"):
    return AssessmentPolicy(
        tuple(HypothesisIdentity(name, version, fingerprint) for name in names),
        minimum,
        "directional_presence_v1",
    )


def run(states, *, minimum=1):
    """Assess ``states`` against an ensemble sized to match."""
    names = [chr(ord("a") + index) for index in range(len(states))]
    observations = [obs(name, state) for name, state in zip(names, states)]
    return assess(observations, policy_for(*names, minimum=minimum))


class TestAlignment:
    """Every observation must describe exactly the same market decision point."""

    def test_exactly_aligned_observations_assess(self):
        result = assess([obs("a", B), obs("b", B)], policy_for("a", "b"))
        assert result.state is AssessmentState.BULLISH

    def test_symbol_mismatch_raises(self):
        with pytest.raises(AssessmentError, match="symbol"):
            assess([obs("a", B), obs("b", B, symbol="MSFT")], policy_for("a", "b"))

    def test_interval_mismatch_raises(self):
        with pytest.raises(AssessmentError, match="interval"):
            assess(
                [obs("a", B), obs("b", B, interval=Interval.HOUR_1)],
                policy_for("a", "b"),
            )

    def test_basis_mismatch_raises(self):
        """RAW and adjusted prices are denominated differently (ADR 0001)."""
        with pytest.raises(AssessmentError, match="basis"):
            assess(
                [obs("a", B), obs("b", B, basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)],
                policy_for("a", "b"),
            )

    def test_timestamp_mismatch_raises(self):
        with pytest.raises(AssessmentError, match="timestamp"):
            assess(
                [obs("a", B), obs("b", B, timestamp=T0 + timedelta(days=1))],
                policy_for("a", "b"),
            )

    @pytest.mark.parametrize("delta", [timedelta(microseconds=1), timedelta(days=1)])
    def test_no_tolerance_window_exists(self, delta):
        with pytest.raises(AssessmentError, match="timestamp"):
            assess([obs("a", B), obs("b", B, timestamp=T0 + delta)], policy_for("a", "b"))

    def test_equal_instants_at_different_offsets_are_aligned(self):
        """Aware datetimes compare by instant, which is the existing semantics."""
        shifted = T0.astimezone(timezone(timedelta(hours=5)))
        assert shifted == T0
        result = assess(
            [obs("a", B), obs("b", B, timestamp=shifted)], policy_for("a", "b")
        )
        assert result.state is AssessmentState.BULLISH

    def test_several_mismatches_are_all_reported(self):
        with pytest.raises(AssessmentError) as exc:
            assess(
                [obs("a", B), obs("b", B, symbol="MSFT", interval=Interval.HOUR_1)],
                policy_for("a", "b"),
            )
        assert "symbol" in str(exc.value) and "interval" in str(exc.value)


class TestExactEnsemble:
    """The policy pins an exact ensemble: each member once, nothing else."""

    def test_a_missing_hypothesis_raises_rather_than_weakening_evidence(self):
        with pytest.raises(AssessmentError, match="missing hypothesis"):
            assess([obs("a", B)], policy_for("a", "b"))

    def test_a_missing_hypothesis_is_not_insufficient_data(self):
        with pytest.raises(AssessmentError) as exc:
            assess([obs("a", B)], policy_for("a", "b"))
        assert "structural error, not weak evidence" in str(exc.value)

    def test_an_unexpected_hypothesis_raises(self):
        with pytest.raises(AssessmentError, match="unexpected hypothesis"):
            assess([obs("a", B), obs("z", B)], policy_for("a"))

    def test_a_duplicate_identity_raises(self):
        with pytest.raises(AssessmentError, match="duplicate hypothesis"):
            assess([obs("a", B), obs("a", B)], policy_for("a"))

    def test_a_duplicate_is_not_silently_deduplicated(self):
        with pytest.raises(AssessmentError) as exc:
            assess([obs("a", B), obs("a", N)], policy_for("a"))
        assert "deduplicated" in str(exc.value)

    def test_a_fingerprint_mismatch_is_reported_distinctly(self):
        """Same id and version with a different fingerprint is a
        re-parameterised hypothesis, not an unrelated one."""
        with pytest.raises(AssessmentError, match="fingerprint mismatch") as exc:
            assess([obs("a", B, fingerprint="other")], policy_for("a"))
        assert "unexpected hypothesis" not in str(exc.value)
        assert "re-parameterised" in str(exc.value)

    def test_a_version_mismatch_is_reported_as_unexpected(self):
        with pytest.raises(AssessmentError, match="unexpected hypothesis"):
            assess([obs("a", B, version=2)], policy_for("a"))

    def test_an_empty_observation_set_raises(self):
        with pytest.raises(AssessmentError, match="at least one observation"):
            assess([], policy_for("a"))

    @pytest.mark.parametrize("bad", ["x", 5, None])
    def test_a_non_observation_raises(self, bad):
        with pytest.raises(AssessmentError, match="ResearchObservation"):
            assess([bad], policy_for("a"))

    @pytest.mark.parametrize("bad", ["policy", None, 5])
    def test_a_non_policy_raises(self, bad):
        with pytest.raises(AssessmentError, match="AssessmentPolicy"):
            assess([obs("a", B)], bad)


class TestLockedDecisionTableV1:
    """The executable definition of ``directional_presence_v1``.

    Changing any expectation here changes the meaning of that rule identity.
    Materially different semantics require a new identity, not an edit.
    """

    @pytest.mark.parametrize(
        "state,expected",
        [
            (B, AssessmentState.BULLISH),
            (BE, AssessmentState.BEARISH),
            (N, AssessmentState.NEUTRAL),
            (INS, AssessmentState.INSUFFICIENT_DATA),
        ],
    )
    def test_n1(self, state, expected):
        assert run((state,)).state is expected

    @pytest.mark.parametrize(
        "states,minimum,expected",
        [
            ((B, B), 1, AssessmentState.BULLISH),
            ((BE, BE), 1, AssessmentState.BEARISH),
            ((N, N), 1, AssessmentState.NEUTRAL),
            ((B, BE), 1, AssessmentState.CONFLICTED),
            ((B, N), 1, AssessmentState.BULLISH),
            ((BE, N), 1, AssessmentState.BEARISH),
            ((B, INS), 1, AssessmentState.BULLISH),
            ((B, INS), 2, AssessmentState.INSUFFICIENT_DATA),
            ((N, INS), 1, AssessmentState.NEUTRAL),
            ((INS, INS), 1, AssessmentState.INSUFFICIENT_DATA),
        ],
    )
    def test_n2(self, states, minimum, expected):
        assert run(states, minimum=minimum).state is expected

    @pytest.mark.parametrize(
        "states,minimum,expected",
        [
            ((B, B, INS), 2, AssessmentState.BULLISH),
            ((N, N, INS), 2, AssessmentState.NEUTRAL),
            ((B, BE, N), 1, AssessmentState.CONFLICTED),
            ((B, BE, INS), 2, AssessmentState.CONFLICTED),
            ((B, N, N), 1, AssessmentState.BULLISH),
            ((BE, N, N), 1, AssessmentState.BEARISH),
            ((INS, INS, INS), 1, AssessmentState.INSUFFICIENT_DATA),
            ((B, INS, INS), 2, AssessmentState.INSUFFICIENT_DATA),
            ((N, N, N), 3, AssessmentState.NEUTRAL),
        ],
    )
    def test_n3(self, states, minimum, expected):
        assert run(states, minimum=minimum).state is expected

    def test_n5_conflict_survives_a_neutral_majority(self):
        """CONFLICTED is directional contradiction, not a vote-count tie."""
        assert run((B, BE, N, N, N), minimum=1).state is AssessmentState.CONFLICTED

    # -- the semantic locks named in the architecture ----------------------
    def test_bullish_with_two_neutrals_is_bullish(self):
        assert run((B, N, N)).state is AssessmentState.BULLISH

    def test_bearish_with_two_neutrals_is_bearish(self):
        assert run((BE, N, N)).state is AssessmentState.BEARISH

    def test_bullish_and_bearish_with_neutral_is_conflicted(self):
        assert run((B, BE, N)).state is AssessmentState.CONFLICTED

    def test_all_neutral_is_neutral_never_insufficient(self):
        """The rule that killed `minimum_directional`: neutrals are sufficient."""
        assert run((N, N, N)).state is AssessmentState.NEUTRAL

    def test_one_bullish_and_two_insufficient_below_minimum(self):
        assert run((B, INS, INS), minimum=2).state is AssessmentState.INSUFFICIENT_DATA

    def test_two_neutral_and_one_insufficient_at_minimum(self):
        assert run((N, N, INS), minimum=2).state is AssessmentState.NEUTRAL

    def test_no_plurality_rule_is_applied(self):
        """Under plurality this would be NEUTRAL; V1 lets a firing hypothesis
        be heard rather than letting abstentions outvote it."""
        assert run((B, N, N, N, N), minimum=1).state is AssessmentState.BULLISH


class TestMinimumSemantics:
    def test_exactly_at_the_minimum_is_sufficient(self):
        assert run((B, B, INS), minimum=2).state is AssessmentState.BULLISH

    def test_one_below_the_minimum_is_insufficient(self):
        assert run((B, INS, INS), minimum=2).state is AssessmentState.INSUFFICIENT_DATA

    def test_neutral_counts_toward_the_minimum(self):
        assert run((N, N, INS), minimum=2).state is AssessmentState.NEUTRAL

    def test_insufficient_does_not_count_toward_the_minimum(self):
        assert run((N, INS, INS), minimum=2).state is AssessmentState.INSUFFICIENT_DATA

    def test_all_sufficient_meets_any_valid_minimum(self):
        for minimum in (1, 2, 3):
            assert run((B, N, N), minimum=minimum).state is AssessmentState.BULLISH


class TestCountsAndReasons:
    def test_counts_tally_every_input_including_insufficient(self):
        result = run((B, BE, N, INS), minimum=1)
        assert (result.counts.bullish, result.counts.bearish) == (1, 1)
        assert (result.counts.neutral, result.counts.insufficient) == (1, 1)
        assert result.counts.sufficient == 3
        assert result.counts.total == 4 == len(result.inputs)

    def test_insufficient_inputs_are_retained_not_dropped(self):
        result = run((B, INS), minimum=1)
        assert len(result.inputs) == 2
        assert any(entry.state is INS for entry in result.inputs)

    @pytest.mark.parametrize(
        "states,minimum,expected",
        [
            ((B, B), 1, AssessmentReasonCode.UNANIMOUS_BULLISH),
            ((BE, BE), 1, AssessmentReasonCode.UNANIMOUS_BEARISH),
            ((N, N), 1, AssessmentReasonCode.UNANIMOUS_NEUTRAL),
            ((B, N), 1, AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL),
            ((BE, N), 1, AssessmentReasonCode.DIRECTIONAL_BEARISH_WITH_NEUTRAL),
            ((B, BE), 1, AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE),
            ((B, INS), 2, AssessmentReasonCode.INSUFFICIENT_EVIDENCE),
        ],
    )
    def test_primary_reason_code(self, states, minimum, expected):
        assert expected in run(states, minimum=minimum).reason_codes

    def test_exclusion_is_recorded_whenever_insufficient_inputs_exist(self):
        result = run((B, B, INS), minimum=2)
        assert AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED in result.reason_codes

    def test_no_exclusion_code_when_every_input_classified(self):
        result = run((B, B), minimum=1)
        assert AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED not in result.reason_codes

    def test_the_all_insufficient_case_reports_insufficient_evidence(self):
        result = run((INS, INS), minimum=1)
        assert AssessmentReasonCode.INSUFFICIENT_EVIDENCE in result.reason_codes
        assert AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED in result.reason_codes

    def test_no_majority_reason_code_exists(self):
        """1 of 2 is not a majority; a code claiming one would be false."""
        names = [member.name for member in AssessmentReasonCode]
        assert not any("MAJORITY" in name for name in names)

    def test_no_confidence_or_strength_vocabulary_exists(self):
        names = " ".join(member.name for member in AssessmentReasonCode).lower()
        for word in ("confidence", "strength", "probability", "strong", "weak", "score"):
            assert word not in names


class TestTiming:
    def test_assessment_as_of_is_the_max_evaluable_from(self):
        observations = [obs("a", B), obs("b", N)]
        result = assess(observations, policy_for("a", "b"))
        assert result.assessment_as_of == max(o.evaluable_from for o in observations)

    def test_it_is_later_than_the_bar_timestamp(self):
        """Bar timestamp is bar OPEN time; the evidence needs the completed bar."""
        result = run((B,))
        assert result.assessment_as_of > result.timestamp

    def test_it_equals_timestamp_plus_the_interval_bound(self):
        result = run((B,))
        assert result.assessment_as_of == T0 + Interval.DAY_1.max_duration

    @pytest.mark.parametrize("interval", [Interval.DAY_1, Interval.WEEK_1, Interval.MONTH_1])
    def test_the_existing_timing_convention_is_preserved(self, interval):
        """No new timing model: evaluable_from is used exactly as Phase 3 defines it."""
        observations = [obs("a", B, interval=interval)]
        result = assess(observations, policy_for("a"))
        assert result.assessment_as_of == observations[0].evaluable_from

    def test_plain_aligned_observations_share_one_evaluable_from(self):
        """Why ``max`` looks redundant for ordinary input.

        ``evaluable_from`` is ``timestamp + interval.max_duration``, a pure
        function of two fields alignment forces to be equal, so for stock
        ``ResearchObservation`` records ``max``, ``min`` and "the first one"
        coincide. That is *why* the reduction needs its own test rather than
        relying on ordinary cases -- see the test below.
        """
        observations = [
            obs("a", B),
            obs("b", N, timestamp=T0.astimezone(timezone(timedelta(hours=5)))),
            obs("c", BE),
        ]
        bounds = [observation.evaluable_from for observation in observations]
        assert max(bounds) == min(bounds) == bounds[0]

    def test_the_latest_bound_wins_when_they_differ(self):
        """The combined classification cannot exist until every input could.

        ``evaluable_from`` is a property, so a subclass can compute a different
        bound while still passing ``isinstance`` and every alignment check.
        That makes ``max`` observably different from ``min`` or "the first
        one", which is the contract this pins: taking anything but the latest
        bound would claim the assessment existed before one of its own inputs.
        """

        class LateObservation(ResearchObservation):
            @property
            def evaluable_from(self):
                return super().evaluable_from + timedelta(days=30)

        late = LateObservation(
            "b", 1, "fp1", "AAPL", Interval.DAY_1, PriceBasis.RAW, T0, N,
            {"value": 1.0}, (ReasonCode.FAST_ABOVE_SLOW,),
        )
        early = obs("a", B)
        bounds = [early.evaluable_from, late.evaluable_from]
        assert max(bounds) != min(bounds)  # the reduction is now observable

        for order in ([early, late], [late, early]):
            result = assess(order, policy_for("a", "b"))
            assert result.assessment_as_of == max(bounds)
            assert result.assessment_as_of != min(bounds)

    def test_input_order_cannot_change_the_timing(self):
        observations = [obs("a", B), obs("b", N), obs("c", BE)]
        seen = {
            assess(order, policy_for("a", "b", "c")).assessment_as_of
            for order in itertools.permutations(observations)
        }
        assert len(seen) == 1

    def test_no_wall_clock_is_read(self):
        """AST, so docstrings mentioning these names do not create false hits."""
        forbidden = {
            "now",
            "utcnow",
            "today",
            "time",
            "monotonic",
            "uuid4",
            "uuid1",
            "random",
            "choice",
            "randint",
            "shuffle",
            "seed",
        }
        for path in sorted(pathlib.Path("src/assessments").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (
                        func.attr
                        if isinstance(func, ast.Attribute)
                        else func.id
                        if isinstance(func, ast.Name)
                        else ""
                    )
                    assert name not in forbidden, f"{path.name}:{node.lineno} calls {name}"


class TestDeterminism:
    def test_repeated_calls_are_identical(self):
        observations = [obs("a", B), obs("b", N)]
        pol = policy_for("a", "b")
        assert assess(observations, pol) == assess(observations, pol)

    def test_input_permutation_produces_an_identical_record(self):
        observations = [obs("a", B), obs("b", N), obs("c", BE)]
        pol = policy_for("a", "b", "c")
        records = {assess(order, pol) for order in itertools.permutations(observations)}
        assert len(records) == 1

    def test_inputs_are_stored_in_canonical_order(self):
        observations = [obs("c", B), obs("a", N), obs("b", BE)]
        result = assess(observations, policy_for("a", "b", "c"))
        assert [entry.hypothesis_id for entry in result.inputs] == ["a", "b", "c"]

    def test_a_caller_list_mutated_afterwards_does_not_change_the_record(self):
        observations = [obs("a", B), obs("b", N)]
        result = assess(observations, policy_for("a", "b"))
        observations.append(obs("z", BE))
        assert len(result.inputs) == 2

    def test_the_record_carries_the_policy_fingerprint(self):
        pol = policy_for("a", "b")
        assert assess([obs("a", B), obs("b", N)], pol).policy_fingerprint == pol.fingerprint

    def test_two_policies_differing_only_in_minimum_are_distinguishable(self):
        observations = [obs("a", B), obs("b", N)]
        one = assess(observations, policy_for("a", "b", minimum=1))
        two = assess(observations, policy_for("a", "b", minimum=2))
        assert one.state is two.state
        assert one.policy_fingerprint != two.policy_fingerprint


class TestOnlyOneRuleIsImplemented:
    """One reduction, not a menu -- and no future identity may inherit it.

    An earlier version of this class asserted that ``aggregate.py`` never
    mentions the enum at all. That constrained syntax rather than semantics,
    and worse, it forbade exactly the guard below: with no check, adding a
    second enum member would leave ``assess`` applying V1 semantics to a policy
    whose fingerprint claims the new identity, silently. These tests pin the
    domain rule instead.
    """

    def test_a_policy_naming_an_unimplemented_rule_is_refused(self):
        """Simulates the future developer who adds a rule and forgets the
        reduction. The assessment must not be produced under V1 semantics."""
        from enum import Enum

        import src.assessments.policy as policy_module

        class FutureRule(str, Enum):
            DIRECTIONAL_PRESENCE_V1 = "directional_presence_v1"
            PLURALITY_V2 = "plurality_v2"

        original = policy_module.AssessmentAggregationRule
        policy_module.AssessmentAggregationRule = FutureRule
        try:
            future = policy_module.AssessmentPolicy(
                (policy_module.HypothesisIdentity("a", 1, "fp1"),), 1, "plurality_v2"
            )
            with pytest.raises(AssessmentError, match="plurality_v2"):
                assess([obs("a", B)], future)
        finally:
            policy_module.AssessmentAggregationRule = original

    def test_the_implemented_rule_is_the_locked_one(self):
        from src.assessments.aggregate import _IMPLEMENTED_RULE

        assert _IMPLEMENTED_RULE is AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1

    def test_the_supported_rule_still_assesses(self):
        assert assess([obs("a", B)], policy_for("a")).state is AssessmentState.BULLISH

    def test_there_is_no_dispatch_table_or_registry(self):
        """A guard compares; a menu maps. Neither a dict of rules nor an
        if/elif chain over rule members may appear."""
        source = pathlib.Path("src/assessments/aggregate.py").read_text()
        tree = ast.parse(source)
        rule_comparisons = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                segment = ast.dump(node)
                if "_IMPLEMENTED_RULE" in segment or "aggregation_rule" in segment:
                    rule_comparisons += 1
        assert rule_comparisons <= 1, "more than one rule comparison suggests dispatch"
        assert "REGISTRY" not in source and "RULES = {" not in source
