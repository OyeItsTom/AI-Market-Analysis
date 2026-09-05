"""The assessment record: direct-construction invariants and boundaries.

A public immutable record that a caller can construct directly must defend
what it can prove alone -- the Phase 5 lesson. These tests pin exactly which
invariants are intrinsic and which remain producer guarantees.
"""

import ast
import dataclasses
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src.assessments import (
    AssessmentCounts,
    AssessmentError,
    AssessmentInput,
    AssessmentPolicy,
    AssessmentReasonCode,
    AssessmentState,
    HypothesisIdentity,
    ResearchAssessment,
    assess,
)
from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ResearchState

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
AS_OF = T0 + timedelta(days=1)

B = ResearchState.BULLISH
BE = ResearchState.BEARISH
N = ResearchState.NEUTRAL
INS = ResearchState.INSUFFICIENT_DATA


def inp(hypothesis_id, state, *, version=1, fingerprint="fp1"):
    return AssessmentInput(hypothesis_id, version, fingerprint, state)


def counts_for(*inputs):
    tally = {state: 0 for state in ResearchState}
    for entry in inputs:
        tally[entry.state] += 1
    return AssessmentCounts(
        bullish=tally[B], bearish=tally[BE], neutral=tally[N], insufficient=tally[INS]
    )


def record(
    *inputs,
    state=AssessmentState.BULLISH,
    counts=None,
    reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,),
    timestamp=T0,
    assessment_as_of=AS_OF,
    policy_fingerprint="abcdef0123456789",
    symbol="AAPL",
    interval=Interval.DAY_1,
    basis=PriceBasis.RAW,
):
    inputs = inputs or (inp("a", B),)
    return ResearchAssessment(
        policy_fingerprint=policy_fingerprint,
        symbol=symbol,
        interval=interval,
        basis=basis,
        timestamp=timestamp,
        assessment_as_of=assessment_as_of,
        state=state,
        inputs=inputs,
        counts=counts_for(*inputs) if counts is None else counts,
        reason_codes=reason_codes,
    )


class TestAssessmentInput:
    def test_a_valid_input(self):
        entry = inp("a", B)
        assert entry.state is B
        assert entry.label == "a@v1#fp1"

    @pytest.mark.parametrize("bad", ["", "   ", None, 5])
    def test_malformed_identity_is_refused(self, bad):
        with pytest.raises(AssessmentError):
            AssessmentInput(bad, 1, "fp", B)
        with pytest.raises(AssessmentError):
            AssessmentInput("a", 1, bad, B)

    @pytest.mark.parametrize("bad", [True, 0, -1, 1.0, "1"])
    def test_malformed_version_is_refused(self, bad):
        with pytest.raises(AssessmentError, match="version"):
            AssessmentInput("a", bad, "fp", B)

    def test_an_unknown_state_is_refused(self):
        with pytest.raises(AssessmentError, match="unknown research state"):
            AssessmentInput("a", 1, "fp", "sideways")

    def test_it_stores_no_evidence_or_observation(self):
        """Identity plus state only; raw evidence stays on the observation."""
        fields = {f.name for f in dataclasses.fields(AssessmentInput)}
        assert fields == {"hypothesis_id", "version", "fingerprint", "state"}

    def test_it_is_frozen(self):
        with pytest.raises(Exception):
            inp("a", B).state = BE


class TestAssessmentCounts:
    def test_derived_values(self):
        counts = AssessmentCounts(2, 1, 3, 4)
        assert counts.sufficient == 6
        assert counts.directional == 3
        assert counts.total == 10

    def test_only_four_primitives_are_stored(self):
        """Derived totals cannot diverge from the numbers they summarise."""
        assert [f.name for f in dataclasses.fields(AssessmentCounts)] == [
            "bullish",
            "bearish",
            "neutral",
            "insufficient",
        ]

    @pytest.mark.parametrize("bad", [True, False])
    def test_bool_counts_are_refused(self, bad):
        with pytest.raises(AssessmentError, match="got bool"):
            AssessmentCounts(bad, 0, 0, 0)

    @pytest.mark.parametrize("bad", [1.0, "1", None])
    def test_non_int_counts_are_refused(self, bad):
        with pytest.raises(AssessmentError, match="must be an int"):
            AssessmentCounts(bad, 0, 0, 0)

    def test_negative_counts_are_refused(self):
        with pytest.raises(AssessmentError, match=">= 0"):
            AssessmentCounts(-1, 0, 0, 0)

    def test_it_is_frozen(self):
        with pytest.raises(Exception):
            AssessmentCounts(1, 0, 0, 0).bullish = 5


class TestRecordStructuralInvariants:
    def test_a_valid_record(self):
        assert record().state is AssessmentState.BULLISH

    def test_empty_inputs_are_refused(self):
        with pytest.raises(AssessmentError, match="must not be empty"):
            ResearchAssessment(
                policy_fingerprint="abcdef0123456789",
                symbol="AAPL",
                interval=Interval.DAY_1,
                basis=PriceBasis.RAW,
                timestamp=T0,
                assessment_as_of=AS_OF,
                state=AssessmentState.NEUTRAL,
                inputs=(),
                counts=AssessmentCounts(0, 0, 0, 0),
                reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,),
            )

    def test_duplicate_identities_are_refused(self):
        with pytest.raises(AssessmentError, match="duplicate hypothesis identity"):
            record(inp("a", B), inp("a", B))

    def test_inputs_are_sorted_canonically(self):
        result = record(inp("c", B), inp("a", B), inp("b", B))
        assert [entry.hypothesis_id for entry in result.inputs] == ["a", "b", "c"]

    def test_a_caller_list_is_copied_defensively(self):
        inputs = [inp("a", B)]
        result = ResearchAssessment(
            policy_fingerprint="abcdef0123456789",
            symbol="AAPL",
            interval=Interval.DAY_1,
            basis=PriceBasis.RAW,
            timestamp=T0,
            assessment_as_of=AS_OF,
            state=AssessmentState.BULLISH,
            inputs=inputs,
            counts=AssessmentCounts(1, 0, 0, 0),
            reason_codes=[AssessmentReasonCode.UNANIMOUS_BULLISH],
        )
        inputs.append(inp("z", BE))
        assert len(result.inputs) == 1
        assert isinstance(result.inputs, tuple)
        assert isinstance(result.reason_codes, tuple)

    @pytest.mark.parametrize("bad", ["x", 5, None])
    def test_a_non_input_member_is_refused(self, bad):
        with pytest.raises(AssessmentError, match="AssessmentInput"):
            record(bad, counts=AssessmentCounts(1, 0, 0, 0))

    @pytest.mark.parametrize("bad", ["", "   ", None, 5, b"abc", 1.5])
    def test_a_missing_policy_fingerprint_is_refused(self, bad):
        with pytest.raises(AssessmentError, match="policy_fingerprint"):
            record(policy_fingerprint=bad)

    @pytest.mark.parametrize(
        "bad",
        [
            "hello world",           # not hex at all
            "NOTHEXNOTHEXNOTH",      # right length, wrong alphabet
            "ABCDEF0123456789",      # uppercase -- never produced
            "abcdef012345678",       # 15 chars
            "abcdef01234567890",     # 17 chars
            "zzzzzzzzzzzzzzzz",
            "../etc/passwd",
        ],
    )
    def test_a_fingerprint_no_policy_could_produce_is_refused(self, bad):
        """Regression: a non-empty string was previously enough.

        ``AssessmentPolicy.fingerprint`` always yields 16 lowercase hex
        characters, so an assessment carrying anything else names a policy that
        could never have produced it -- unauditable while looking auditable.
        """
        with pytest.raises(AssessmentError, match="lowercase hex"):
            record(policy_fingerprint=bad)

    def test_a_real_policy_fingerprint_is_accepted(self):
        pol = AssessmentPolicy(
            (HypothesisIdentity("a", 1, "fp1"),), 1, "directional_presence_v1"
        )
        assert record(policy_fingerprint=pol.fingerprint).policy_fingerprint == pol.fingerprint

    def test_every_produced_assessment_satisfies_the_stricter_rule(self):
        """The producer and the record must agree on the format."""
        from src.strategies.research import ReasonCode, ResearchObservation

        pol = AssessmentPolicy(
            (HypothesisIdentity("a", 1, "fp1"),), 1, "directional_presence_v1"
        )
        built = assess(
            [
                ResearchObservation(
                    "a", 1, "fp1", "AAPL", Interval.DAY_1, PriceBasis.RAW, T0, B,
                    {"v": 1.0}, (ReasonCode.FAST_ABOVE_SLOW,),
                )
            ],
            pol,
        )
        assert len(built.policy_fingerprint) == 16
        assert set(built.policy_fingerprint) <= set("0123456789abcdef")

    @pytest.mark.parametrize("bad", ["", "   ", None, 5])
    def test_a_missing_symbol_is_refused(self, bad):
        with pytest.raises(AssessmentError, match="symbol"):
            record(symbol=bad)

    def test_an_unknown_interval_is_refused(self):
        with pytest.raises(AssessmentError):
            record(interval="1day")

    def test_an_unknown_basis_is_refused(self):
        with pytest.raises(AssessmentError, match="price basis"):
            record(basis="nominal")

    def test_an_unknown_state_is_refused(self):
        with pytest.raises(AssessmentError, match="assessment state"):
            record(state="sideways")

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(AssessmentError, match="timezone-aware"):
            record(timestamp=datetime(2024, 1, 1))

    def test_a_naive_assessment_as_of_is_refused(self):
        with pytest.raises(AssessmentError, match="timezone-aware"):
            record(assessment_as_of=datetime(2024, 1, 2))

    def test_an_as_of_before_the_timestamp_is_refused(self):
        with pytest.raises(AssessmentError, match="precedes the bar timestamp"):
            record(assessment_as_of=T0 - timedelta(days=1))

    def test_an_as_of_equal_to_the_timestamp_is_allowed(self):
        assert record(assessment_as_of=T0).assessment_as_of == T0

    def test_it_is_frozen(self):
        with pytest.raises(Exception):
            record().state = AssessmentState.BEARISH


class TestCountConservation:
    def test_counts_must_tally_the_inputs(self):
        with pytest.raises(AssessmentError, match="do not tally"):
            record(inp("a", B), counts=AssessmentCounts(5, 0, 0, 0))

    def test_a_count_of_a_state_not_present_is_refused(self):
        with pytest.raises(AssessmentError, match="do not tally"):
            record(inp("a", B), counts=AssessmentCounts(1, 1, 0, 0))

    def test_an_undercount_is_refused(self):
        with pytest.raises(AssessmentError, match="do not tally"):
            record(inp("a", B), inp("b", B), counts=AssessmentCounts(1, 0, 0, 0))

    def test_a_non_counts_object_is_refused(self):
        with pytest.raises(AssessmentError, match="AssessmentCounts"):
            record(inp("a", B), counts={"bullish": 1})

    def test_total_equals_the_input_count(self):
        result = record(inp("a", B), inp("b", N), inp("c", INS))
        assert result.counts.total == 3 == len(result.inputs)


class TestImpossibleStatesAreUnrepresentable:
    """State must agree with the evidence it claims to summarise."""

    def test_conflicted_without_bullish_is_refused(self):
        with pytest.raises(AssessmentError, match="CONFLICTED requires"):
            record(inp("a", BE), inp("b", N), state=AssessmentState.CONFLICTED)

    def test_conflicted_without_bearish_is_refused(self):
        with pytest.raises(AssessmentError, match="CONFLICTED requires"):
            record(inp("a", B), inp("b", N), state=AssessmentState.CONFLICTED)

    def test_bullish_without_bullish_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="BULLISH requires"):
            record(inp("a", N), state=AssessmentState.BULLISH)

    def test_bullish_with_bearish_evidence_is_refused(self):
        """A directional state may not hide a contradiction."""
        with pytest.raises(AssessmentError, match="BULLISH requires"):
            record(inp("a", B), inp("b", BE), state=AssessmentState.BULLISH)

    def test_bearish_without_bearish_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="BEARISH requires"):
            record(inp("a", N), state=AssessmentState.BEARISH)

    def test_bearish_with_bullish_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="BEARISH requires"):
            record(inp("a", B), inp("b", BE), state=AssessmentState.BEARISH)

    def test_neutral_with_bullish_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="NEUTRAL requires"):
            record(inp("a", B), inp("b", N), state=AssessmentState.NEUTRAL)

    def test_neutral_with_bearish_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="NEUTRAL requires"):
            record(inp("a", BE), inp("b", N), state=AssessmentState.NEUTRAL)

    def test_neutral_without_neutral_evidence_is_refused(self):
        with pytest.raises(AssessmentError, match="NEUTRAL requires"):
            record(inp("a", INS), state=AssessmentState.NEUTRAL)

    def test_insufficient_data_is_the_documented_trust_boundary(self):
        """Deliberately NOT rejected: whether INSUFFICIENT_DATA was correct
        depends on the policy minimum, which the record does not store. This
        is a producer guarantee of assess(), stated rather than hidden."""
        built = record(
            inp("a", B),
            inp("b", B),
            state=AssessmentState.INSUFFICIENT_DATA,
            reason_codes=(AssessmentReasonCode.INSUFFICIENT_EVIDENCE,),
        )
        assert built.state is AssessmentState.INSUFFICIENT_DATA

    def test_the_producer_never_emits_that_combination(self):
        """What direct construction cannot prove, assess() still guarantees."""
        pol = AssessmentPolicy(
            (HypothesisIdentity("a", 1, "fp1"), HypothesisIdentity("b", 1, "fp1")),
            2,
            "directional_presence_v1",
        )
        from src.strategies.research import ReasonCode, ResearchObservation

        observations = [
            ResearchObservation(
                name, 1, "fp1", "AAPL", Interval.DAY_1, PriceBasis.RAW, T0, B,
                {"v": 1.0}, (ReasonCode.FAST_ABOVE_SLOW,),
            )
            for name in ("a", "b")
        ]
        result = assess(observations, pol)
        assert result.state is AssessmentState.BULLISH
        assert result.counts.sufficient >= pol.minimum_sufficient_observations


class TestReasonCodes:
    def test_empty_reason_codes_are_refused(self):
        with pytest.raises(AssessmentError, match="at least one reason code"):
            record(reason_codes=())

    def test_duplicates_are_collapsed(self):
        result = record(
            reason_codes=(
                AssessmentReasonCode.UNANIMOUS_BULLISH,
                AssessmentReasonCode.UNANIMOUS_BULLISH,
            )
        )
        assert result.reason_codes == (AssessmentReasonCode.UNANIMOUS_BULLISH,)

    def test_they_are_reordered_canonically(self):
        result = record(
            inp("a", B),
            inp("b", INS),
            reason_codes=(
                AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
                AssessmentReasonCode.UNANIMOUS_BULLISH,
            ),
        )
        assert result.reason_codes == (
            AssessmentReasonCode.UNANIMOUS_BULLISH,
            AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
        )

    def test_ordering_is_enforced_by_the_record_not_only_the_producer(self):
        forward = record(
            inp("a", B),
            inp("b", INS),
            reason_codes=(
                AssessmentReasonCode.UNANIMOUS_BULLISH,
                AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
            ),
        )
        reversed_ = record(
            inp("a", B),
            inp("b", INS),
            reason_codes=(
                AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED,
                AssessmentReasonCode.UNANIMOUS_BULLISH,
            ),
        )
        assert forward.reason_codes == reversed_.reason_codes

    def test_the_full_vocabulary_is_reordered_canonically(self):
        """Uses every code, so canonicalisation cannot pass by luck.

        An earlier version of this suite pinned only two codes. Dropping
        canonicalisation leaves the codes in set-iteration order, which for
        ``str`` enums depends on PYTHONHASHSEED -- with two elements that
        matches canonical order about half the time, so the test caught the
        regression only sometimes. Across all eight the chance of accidental
        agreement is 1 in 8! and the check is effectively deterministic.
        """
        every = list(AssessmentReasonCode)
        result = record(inp("a", B), inp("b", INS), reason_codes=list(reversed(every)))
        assert list(result.reason_codes) == every

    def test_reason_codes_are_monotonic_in_the_canonical_order(self):
        every = list(AssessmentReasonCode)
        result = record(inp("a", B), inp("b", INS), reason_codes=list(reversed(every)))
        positions = [every.index(code) for code in result.reason_codes]
        assert positions == sorted(positions)

    def test_unanimous_is_scoped_to_the_sufficient_inputs(self):
        """``UNANIMOUS_*`` means unanimous among inputs that *classified*.

        ``BULLISH + BULLISH + INSUFFICIENT_DATA`` is ``UNANIMOUS_BULLISH``: the
        hypothesis that could not classify cast no vote to disagree with. The
        exclusion is never concealed -- the same assessment carries
        ``INSUFFICIENT_INPUTS_EXCLUDED`` and counts the excluded input.
        """
        from src.strategies.research import ReasonCode, ResearchObservation

        pol = AssessmentPolicy(
            tuple(HypothesisIdentity(name, 1, "fp1") for name in ("a", "b", "c")),
            2,
            "directional_presence_v1",
        )
        observations = [
            ResearchObservation(
                name, 1, "fp1", "AAPL", Interval.DAY_1, PriceBasis.RAW, T0, state,
                {"v": 1.0}, (ReasonCode.FAST_ABOVE_SLOW,),
            )
            for name, state in zip(("a", "b", "c"), (B, B, INS))
        ]
        built = assess(observations, pol)
        assert AssessmentReasonCode.UNANIMOUS_BULLISH in built.reason_codes
        assert AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED in built.reason_codes
        assert built.counts.insufficient == 1
        assert built.counts.total == 3
        assert len(built.inputs) == 3  # nothing dropped from the audit trail

    def test_an_unknown_reason_code_is_refused(self):
        with pytest.raises(AssessmentError):
            record(reason_codes=("looks_good",))

    def test_a_mutable_reason_collection_is_frozen(self):
        codes = [AssessmentReasonCode.UNANIMOUS_BULLISH]
        result = record(reason_codes=codes)
        codes.append(AssessmentReasonCode.INSUFFICIENT_EVIDENCE)
        assert result.reason_codes == (AssessmentReasonCode.UNANIMOUS_BULLISH,)


class TestNoTradingOrScoringSemantics:
    def test_the_record_has_no_score_or_confidence_field(self):
        fields = {f.name for f in dataclasses.fields(ResearchAssessment)}
        for forbidden in (
            "score",
            "confidence",
            "probability",
            "strength",
            "weight",
            "action",
            "recommendation",
        ):
            assert forbidden not in fields

    def test_no_record_carries_price_cash_or_pnl_fields(self):
        for record_type in (
            ResearchAssessment,
            AssessmentInput,
            AssessmentCounts,
            AssessmentPolicy,
            HypothesisIdentity,
        ):
            fields = {f.name for f in dataclasses.fields(record_type)}
            for forbidden in ("price", "quantity", "cash", "pnl", "nav", "cost", "notional"):
                assert forbidden not in fields

    def test_assessment_state_is_not_a_paper_action(self):
        assert [member.name for member in AssessmentState] == [
            "BULLISH",
            "BEARISH",
            "NEUTRAL",
            "CONFLICTED",
            "INSUFFICIENT_DATA",
        ]
        for forbidden in ("OPEN_LONG", "OPEN_SHORT", "CLOSE", "BUY", "SELL", "HOLD"):
            assert forbidden not in AssessmentState.__members__

    def test_research_state_was_not_modified(self):
        """Phase 6 adds CONFLICTED to its own enum, never to Phase 3's."""
        assert [member.name for member in ResearchState] == [
            "BULLISH",
            "BEARISH",
            "NEUTRAL",
            "INSUFFICIENT_DATA",
        ]

    def test_all_public_records_are_frozen(self):
        for record_type in (
            ResearchAssessment,
            AssessmentInput,
            AssessmentCounts,
            AssessmentPolicy,
            HypothesisIdentity,
        ):
            assert record_type.__dataclass_params__.frozen


class TestPackageBoundaries:
    """Structural separation, verified through the AST.

    A substring scan would flag the very docstrings that state these
    guarantees -- the module prose legitimately names PaperIntent and
    EvaluatedOutcome while explaining that neither is used.
    """

    ASSESSMENT_FILES = sorted(pathlib.Path("src/assessments").glob("*.py"))

    def _imports(self, path):
        modules = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def _code_names(self, path):
        names = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        return names

    @pytest.mark.parametrize(
        "forbidden",
        ["src.portfolio", "src.evaluation", "src.backtesting", "src.signals"],
    )
    def test_the_assessment_package_imports_no_forbidden_module(self, forbidden):
        for path in self.ASSESSMENT_FILES:
            for module in self._imports(path):
                assert not (
                    module == forbidden or module.startswith(forbidden + ".")
                ), f"{path.name} imports {module}"

    def test_it_imports_no_network_database_or_model_library(self):
        roots = {
            "requests",
            "urllib",
            "http",
            "socket",
            "sqlite3",
            "sqlalchemy",
            "openai",
            "anthropic",
            "yfinance",
            "alpaca",
        }
        for path in self.ASSESSMENT_FILES:
            for module in self._imports(path):
                assert module.split(".")[0] not in roots, f"{path.name} imports {module}"

    def test_only_stdlib_and_existing_project_types_are_imported(self):
        allowed_project = {
            "src.data.models",
            "src.data.series",
            "src.strategies.research",
        }
        for path in self.ASSESSMENT_FILES:
            for module in self._imports(path):
                if module.startswith("src.") or module.startswith("."):
                    assert (
                        module in allowed_project or module.startswith(".")
                    ), f"{path.name} imports {module}"

    @pytest.mark.parametrize(
        "token",
        [
            "PaperIntent",
            "PaperAction",
            "OpenLongIntent",
            "CloseIntent",
            "PaperPortfolio",
            "PaperPosition",
            "RiskPolicy",
            "OPEN_LONG",
            "EvaluatedOutcome",
            "EvaluationSummary",
            "OutcomeSpec",
        ],
    )
    def test_no_forbidden_concept_appears_in_executable_code(self, token):
        for path in self.ASSESSMENT_FILES:
            assert token not in self._code_names(path), f"{path.name} references {token}"

    def test_the_documentation_still_states_the_guarantees(self):
        """Guards the AST tests themselves: if the prose vanished, the checks
        above would pass vacuously."""
        text = "".join(path.read_text() for path in self.ASSESSMENT_FILES)
        assert "PaperIntent" in text
        assert "src.portfolio" in text
        assert "src.evaluation" in text

    def test_no_conversion_to_a_paper_action_exists(self):
        for path in self.ASSESSMENT_FILES:
            names = self._code_names(path)
            for forbidden in (
                "to_paper_intent",
                "as_paper_intent",
                "assessment_to_intent",
                "to_action",
                "suggested_action",
            ):
                assert forbidden not in names

    def test_no_public_type_exposes_a_conversion_method(self):
        for record_type in (ResearchAssessment, AssessmentState, AssessmentPolicy):
            for attribute in dir(record_type):
                lowered = attribute.lower()
                assert "intent" not in lowered
                assert "paper" not in lowered

    def test_the_portfolio_package_does_not_import_assessments(self):
        for path in sorted(pathlib.Path("src/portfolio").glob("*.py")):
            for module in self._imports(path):
                assert not module.startswith("src.assessments"), f"{path.name}"
