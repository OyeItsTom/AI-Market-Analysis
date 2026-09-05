"""PaperPortfolio: application semantics, invariants and retry behaviour."""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from decimal import getcontext, Inexact, Overflow, localcontext

from src.portfolio import (
    CloseIntent,
    OpenLongIntent,
    PaperPortfolio,
    PaperPosition,
    PortfolioError,
    PositionError,
    PositionStatus,
    ResearchProvenance,
    RiskPolicy,
    RiskReasonCode,
)

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def policy(**overrides):
    fields = dict(
        max_notional_per_position=Decimal("1000"),
        max_total_notional=Decimal("5000"),
        max_open_positions=3,
        allow_duplicate_symbol=False,
    )
    fields.update(overrides)
    return RiskPolicy(**fields)


def opening(intent_id, position_id, symbol="AAPL", notional="1000", day=1, provenance=None):
    return OpenLongIntent(
        intent_id, T0 + timedelta(days=day - 1), position_id=position_id,
        symbol=symbol, notional=Decimal(notional), research_provenance=provenance,
    )


def portfolio_with(*specs, pol=None):
    pol = pol or policy()
    book = PaperPortfolio()
    for spec in specs:
        book, _ = book.apply(opening(*spec), pol)
    return book


class TestOpenLong:
    def test_an_approved_open_creates_a_position(self):
        book, decision = PaperPortfolio().apply(opening("i1", "p1"), policy())
        assert decision.approved
        assert decision.intent_id == "i1"
        assert book.open_position_count == 1
        assert book.total_open_notional == Decimal("1000")

    def test_the_original_portfolio_is_never_mutated(self):
        original = PaperPortfolio()
        original.apply(opening("i1", "p1"), policy())
        assert original.open_position_count == 0
        assert original.positions == ()

    def test_the_position_derives_its_timestamp_from_the_intent(self):
        book, _ = PaperPortfolio().apply(opening("i1", "p1", day=5), policy())
        assert book.position("p1").opened_at == T0 + timedelta(days=4)

    def test_an_approved_intent_is_recorded_processed(self):
        book, _ = PaperPortfolio().apply(opening("i1", "p1"), policy())
        assert "i1" in book.processed_intent_ids

    def test_replaying_an_approved_intent_raises(self):
        book, _ = PaperPortfolio().apply(opening("i1", "p1"), policy())
        with pytest.raises(PortfolioError, match="already been applied"):
            book.apply(opening("i1", "p2"), policy())

    def test_a_recycled_position_id_raises(self):
        book = portfolio_with(("i1", "p1"))
        with pytest.raises(PortfolioError, match="already used"):
            book.apply(opening("i2", "p1", symbol="MSFT"), policy())

    def test_a_closed_position_id_still_cannot_be_recycled(self):
        book = portfolio_with(("i1", "p1"))
        book, _ = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        with pytest.raises(PortfolioError, match="already used"):
            book.apply(opening("i3", "p1", symbol="MSFT", day=3), policy())


class TestRejection:
    def _rejecting(self):
        book = portfolio_with(("i1", "p1", "AAPL", "1000"), ("i2", "p2", "MSFT", "1000", 2))
        pol = policy(max_total_notional=Decimal("2000"))
        return book, pol

    def test_a_rejected_decision_names_the_intent_it_refused(self):
        book, pol = self._rejecting()
        _, decision = book.apply(opening("i9", "p9", "TSLA", "1000", 3), pol)
        assert decision.intent_id == "i9"
        assert decision.policy_fingerprint == pol.fingerprint

    def test_a_rejection_returns_an_equal_portfolio(self):
        book, pol = self._rejecting()
        after, decision = book.apply(opening("i9", "p9", "TSLA", "1000", 3), pol)
        assert not decision.approved
        assert after == book

    def test_a_rejection_changes_nothing_at_all(self):
        book, pol = self._rejecting()
        after, _ = book.apply(opening("i9", "p9", "TSLA", "1000", 3), pol)
        assert after.positions == book.positions
        assert after.processed_intent_ids == book.processed_intent_ids
        assert after.total_open_notional == book.total_open_notional
        assert after.open_position_count == book.open_position_count

    def test_a_rejected_intent_is_not_recorded_processed(self):
        book, pol = self._rejecting()
        after, _ = book.apply(opening("i9", "p9", "TSLA", "1000", 3), pol)
        assert "i9" not in after.processed_intent_ids

    def test_a_rejected_intent_can_be_reconsidered_later(self):
        """The documented retry semantic: reject does not consume the id."""
        book, pol = self._rejecting()
        after, first = book.apply(opening("i9", "p9", "TSLA", "1000", 3), pol)
        assert not first.approved

        # The human closes something, then retries the same conceptual intent.
        after, _ = after.apply(CloseIntent("ic", T0 + timedelta(days=4), target_position_id="p1"), pol)
        retried, second = after.apply(opening("i9", "p9", "TSLA", "1000", 5), pol)
        assert second.approved
        assert retried.position("p9") is not None

    def test_a_structural_failure_leaves_the_portfolio_unchanged(self):
        book = portfolio_with(("i1", "p1"))
        with pytest.raises(PortfolioError):
            book.apply(opening("i2", "p1", symbol="MSFT"), policy())
        assert book.open_position_count == 1
        assert book.processed_intent_ids == ("i1",)


class TestClose:
    def test_a_valid_close(self):
        book = portfolio_with(("i1", "p1"))
        after, decision = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        assert decision.approved
        assert decision.intent_id == "i2"
        assert after.position("p1").status is PositionStatus.CLOSED
        assert after.open_position_count == 0
        assert after.total_open_notional == Decimal("0")

    def test_the_closed_position_is_retained(self):
        book = portfolio_with(("i1", "p1"))
        after, _ = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        assert len(after.positions) == 1
        assert len(after.closed_positions) == 1

    def test_everything_about_the_opening_is_retained(self):
        provenance = ResearchProvenance("h", 1, "fp", T0)
        book, _ = PaperPortfolio().apply(opening("i1", "p1", provenance=provenance), policy())
        before = book.position("p1")
        after, _ = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        closed = after.position("p1")
        assert (closed.position_id, closed.symbol, closed.notional, closed.opened_at) == (
            before.position_id, before.symbol, before.notional, before.opened_at,
        )
        assert closed.research_provenance == provenance

    def test_closed_at_comes_from_the_close_intent(self):
        book = portfolio_with(("i1", "p1"))
        when = T0 + timedelta(days=9)
        after, _ = book.apply(CloseIntent("i2", when, target_position_id="p1"), policy())
        assert after.position("p1").closed_at == when

    def test_closing_an_unknown_position_raises(self):
        with pytest.raises(PortfolioError, match="unknown position"):
            PaperPortfolio().apply(CloseIntent("i1", T0, target_position_id="ghost"), policy())

    def test_closing_twice_raises(self):
        book = portfolio_with(("i1", "p1"))
        book, _ = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        # Asserts the PORTFOLIO-level message specifically. PaperPosition.closed()
        # also refuses, so a looser assertion would pass even with the
        # portfolio's own guard removed and could not distinguish the two.
        with pytest.raises(PortfolioError, match="no longer there"):
            book.apply(CloseIntent("i3", T0 + timedelta(days=2), target_position_id="p1"), policy())

    def test_the_position_refuses_a_double_close_independently(self):
        """Defence in depth: the record guards itself even outside a portfolio."""
        closed = PaperPosition("p1", "AAPL", Decimal("100"), T0).closed(T0)
        with pytest.raises(PositionError, match="double-count"):
            closed.closed(T0 + timedelta(days=1))

    def test_closing_before_the_open_raises(self):
        book = portfolio_with(("i1", "p1", "AAPL", "1000", 5))
        # Asserts the PORTFOLIO-level message. PaperPosition also refuses a
        # closed_at before opened_at, so matching only "precedes" would pass
        # even with the portfolio's own check removed.
        with pytest.raises(PortfolioError, match="the position's opened_at"):
            book.apply(CloseIntent("i2", T0, target_position_id="p1"), policy())

    def test_the_position_refuses_a_backwards_close_independently(self):
        """Defence in depth: the record enforces its own time ordering."""
        position = PaperPosition("p1", "AAPL", Decimal("100"), T0 + timedelta(days=5))
        with pytest.raises(PositionError, match="cannot close before it opened"):
            position.closed(T0)

    def test_a_failed_close_leaves_the_portfolio_unchanged(self):
        book = portfolio_with(("i1", "p1"))
        with pytest.raises(PortfolioError):
            book.apply(CloseIntent("i2", T0, target_position_id="ghost"), policy())
        assert book.open_position_count == 1


class TestCloseIsNotBlockedByOpeningLimits:
    """Closing reduces exposure and must never be refused for exposure reasons."""

    def test_close_while_total_exposure_is_at_the_limit(self):
        book = portfolio_with(("i1", "p1", "AAPL", "1000"), ("i2", "p2", "MSFT", "1000", 2))
        pol = policy(max_total_notional=Decimal("2000"))
        # Opening is blocked...
        _, rejected = book.apply(opening("i8", "p8", "TSLA", "1000", 3), pol)
        assert RiskReasonCode.TOTAL_EXPOSURE_LIMIT in rejected.reason_codes
        # ...but closing is not.
        after, decision = book.apply(CloseIntent("i9", T0 + timedelta(days=3), target_position_id="p1"), pol)
        assert decision.approved
        assert after.total_open_notional == Decimal("1000")

    def test_close_while_the_open_position_limit_is_reached(self):
        book = portfolio_with(("i1", "p1", "AAPL", "100"), ("i2", "p2", "MSFT", "100", 2))
        pol = policy(max_open_positions=2)
        _, rejected = book.apply(opening("i8", "p8", "TSLA", "100", 3), pol)
        assert RiskReasonCode.OPEN_POSITION_LIMIT in rejected.reason_codes
        after, decision = book.apply(CloseIntent("i9", T0 + timedelta(days=3), target_position_id="p1"), pol)
        assert decision.approved

    def test_close_with_duplicate_symbol_policy_disabled(self):
        book = portfolio_with(("i1", "p1", "AAPL", "100"))
        pol = policy(allow_duplicate_symbol=False)
        after, decision = book.apply(CloseIntent("i9", T0 + timedelta(days=1), target_position_id="p1"), pol)
        assert decision.approved

    def test_close_while_a_position_exceeds_the_current_per_position_limit(self):
        book = portfolio_with(("i1", "p1", "AAPL", "1000"))
        tighter = policy(max_notional_per_position=Decimal("10"))
        after, decision = book.apply(CloseIntent("i9", T0 + timedelta(days=1), target_position_id="p1"), tighter)
        assert decision.approved
        assert after.total_open_notional == Decimal("0")


class TestDuplicateSymbolThroughThePortfolio:
    def test_an_open_symbol_blocks_a_second_open_when_disallowed(self):
        book = portfolio_with(("i1", "p1", "AAPL"))
        _, decision = book.apply(opening("i2", "p2", "AAPL", day=2), policy())
        assert RiskReasonCode.DUPLICATE_SYMBOL in decision.reason_codes

    def test_a_closed_symbol_does_not_block_a_new_open(self):
        book = portfolio_with(("i1", "p1", "AAPL"))
        book, _ = book.apply(CloseIntent("i2", T0 + timedelta(days=1), target_position_id="p1"), policy())
        after, decision = book.apply(opening("i3", "p3", "AAPL", day=3), policy())
        assert decision.approved
        assert after.open_position_count == 1

    def test_duplicates_are_kept_separate_when_allowed(self):
        pol = policy(allow_duplicate_symbol=True)
        book = PaperPortfolio()
        for n, pid in enumerate(("p1", "p2"), start=1):
            book, decision = book.apply(opening(f"i{n}", pid, "AAPL", day=n), pol)
            assert decision.approved
        assert book.open_position_count == 2
        assert {p.position_id for p in book.open_positions} == {"p1", "p2"}
        assert book.total_open_notional == Decimal("2000")


class TestInvariants:
    def test_exposure_equals_the_sum_of_open_positions(self):
        book = portfolio_with(("i1", "p1", "AAPL", "100"), ("i2", "p2", "MSFT", "250", 2))
        assert book.total_open_notional == sum(
            (p.notional for p in book.open_positions), Decimal(0)
        )

    def test_open_count_equals_the_number_of_open_positions(self):
        book = portfolio_with(("i1", "p1"), ("i2", "p2", "MSFT", "1000", 2))
        assert book.open_position_count == len(book.open_positions)

    def test_closed_positions_contribute_zero_exposure(self):
        book = portfolio_with(("i1", "p1", "AAPL", "100"), ("i2", "p2", "MSFT", "250", 2))
        after, _ = book.apply(CloseIntent("i3", T0 + timedelta(days=3), target_position_id="p1"), policy())
        assert after.total_open_notional == Decimal("250")
        assert after.position("p1").open_notional == Decimal(0)

    def test_duplicate_position_ids_cannot_be_constructed(self):
        position = PaperPosition("p1", "AAPL", Decimal("1"), T0)
        with pytest.raises(PortfolioError, match="duplicate position id"):
            PaperPortfolio(positions=(position, position))

    def test_duplicate_processed_intent_ids_cannot_be_constructed(self):
        with pytest.raises(PortfolioError, match="duplicate processed intent"):
            PaperPortfolio(processed_intent_ids=("i1", "i1"))

    def test_a_non_position_cannot_enter_the_portfolio(self):
        with pytest.raises(PortfolioError, match="PaperPosition"):
            PaperPortfolio(positions=("not a position",))

    @pytest.mark.parametrize("bad", [123, "", "   ", None])
    def test_direct_construction_validates_processed_intent_ids(self, bad):
        """Regression: apply() validated ids through the intent, but a
        directly-built portfolio could hold an id no valid intent could
        produce."""
        with pytest.raises(PortfolioError, match="processed intent id"):
            PaperPortfolio(processed_intent_ids=(bad,))

    def test_a_valid_processed_intent_id_is_accepted(self):
        assert PaperPortfolio(processed_intent_ids=("i1",)).processed_intent_ids == ("i1",)

    def test_a_non_intent_is_refused(self):
        with pytest.raises(PortfolioError, match="PaperIntent"):
            PaperPortfolio().apply("open it", policy())

    def test_a_non_policy_is_refused(self):
        with pytest.raises(PortfolioError, match="RiskPolicy"):
            PaperPortfolio().apply(opening("i1", "p1"), "be careful")


class TestImmutability:
    def test_the_portfolio_is_frozen(self):
        book = portfolio_with(("i1", "p1"))
        with pytest.raises((AttributeError, TypeError)):
            book.positions = ()  # type: ignore[misc]

    def test_collections_are_tuples_not_lists(self):
        book = portfolio_with(("i1", "p1"))
        assert isinstance(book.positions, tuple)
        assert isinstance(book.processed_intent_ids, tuple)

    def test_mutating_the_caller_list_afterwards_changes_nothing(self):
        positions = [PaperPosition("p1", "AAPL", Decimal("100"), T0)]
        book = PaperPortfolio(positions=positions)
        positions.append(PaperPosition("p2", "MSFT", Decimal("999"), T0))
        assert book.open_position_count == 1
        assert book.total_open_notional == Decimal("100")

    def test_a_position_cannot_be_mutated(self):
        book = portfolio_with(("i1", "p1"))
        with pytest.raises((AttributeError, TypeError)):
            book.position("p1").notional = Decimal("1")  # type: ignore[misc]

    def test_closing_returns_a_new_position_object(self):
        position = PaperPosition("p1", "AAPL", Decimal("100"), T0)
        closed = position.closed(T0 + timedelta(days=1))
        assert position.is_open and not closed.is_open
        assert position is not closed

    def test_closing_an_already_closed_position_raises(self):
        closed = PaperPosition("p1", "AAPL", Decimal("100"), T0).closed(T0)
        with pytest.raises(PositionError, match="already"):
            closed.closed(T0 + timedelta(days=1))


class TestDeterminism:
    def test_identical_inputs_give_identical_results(self):
        results = []
        for _ in range(3):
            book, decision = PaperPortfolio().apply(opening("i1", "p1"), policy())
            results.append((book, decision))
        assert results[0] == results[1] == results[2]

    def test_a_rejection_is_deterministic(self):
        book = portfolio_with(("i1", "p1", "AAPL", "1000"))
        pol = policy(max_total_notional=Decimal("1000"))
        first = book.apply(opening("i2", "p2", "MSFT", "1000", 2), pol)
        second = book.apply(opening("i2", "p2", "MSFT", "1000", 2), pol)
        assert first == second


class TestArchitecturalBoundary:
    FORBIDDEN = ("src.strategies", "src.evaluation", "src.backtesting", "src.signals",
                 "yfinance", "requests", "urllib", "http", "socket", "sqlite3",
                 "anthropic", "openai", "random", "uuid", "secrets")

    def _imports(self, path):
        modules = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_the_paper_domain_imports_no_research_or_execution_module(self):
        """Structural separation: ResearchState is not in scope here at all."""
        offenders = []
        for path in sorted(pathlib.Path("src/portfolio").glob("*.py")):
            for module in self._imports(path):
                root = module.split(".")[0]
                for forbidden in self.FORBIDDEN:
                    if module == forbidden or module.startswith(forbidden + ".") or root == forbidden:
                        offenders.append(f"{path.name} imports {module}")
        assert not offenders, f"paper domain reaches outside its layer: {offenders}"

    def test_it_depends_only_on_the_standard_library(self):
        offenders = [
            f"{path.name}: {module}"
            for path in sorted(pathlib.Path("src/portfolio").glob("*.py"))
            for module in self._imports(path)
            if module.startswith("src.")
        ]
        assert not offenders, f"unexpected src dependency: {offenders}"

    def _code_names(self, path):
        """Every name and dotted attribute actually referenced by the CODE.

        Uses the AST, so docstrings and comments are excluded. Those
        legitimately mention ``ResearchState`` and ``uuid4()`` while stating
        that neither is used -- a substring scan would flag the very prose
        that documents the guarantee.
        """
        names = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                parts, current = [node.attr], node.value
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                names.add(".".join(reversed(parts)))
        return names

    def test_no_research_vocabulary_is_referenced_by_the_code(self):
        """A paper record can never hold or branch on a classification."""
        for path in sorted(pathlib.Path("src/portfolio").glob("*.py")):
            names = self._code_names(path)
            for token in ("ResearchState", "ResearchObservation", "EvaluatedOutcome"):
                assert token not in names, f"{path.name} code references {token}"

    def test_the_code_reads_no_clock_and_no_randomness(self):
        for path in sorted(pathlib.Path("src/portfolio").glob("*.py")):
            names = self._code_names(path)
            for token in ("datetime.now", "datetime.utcnow", "time.time",
                          "uuid.uuid4", "uuid4", "random.random", "secrets.token_hex"):
                assert token not in names, f"{path.name} code uses {token}"

    def test_the_prose_that_broke_the_naive_check_is_still_present(self):
        """Regression on the test, not the code.

        An earlier version of these two tests scanned raw source text and
        failed on the docstrings that promise the guarantee. Pin that the
        documentation is there and that the AST check tolerates it.
        """
        text = pathlib.Path("src/portfolio/intent.py").read_text()
        assert "ResearchState" in text  # in prose
        assert "uuid4" in text  # in prose

    def test_no_price_or_pnl_fields_exist(self):
        from src.portfolio import PaperPosition as P

        fields = set(P.__dataclass_fields__)
        for forbidden in ("reference_price", "entry_price", "exit_price", "fill_price",
                          "market_price", "price", "quantity", "pnl", "cash", "cost"):
            assert forbidden not in fields


class TestExposureIgnoresTheAmbientDecimalContext:
    """Regression: exactness is a property of the context, not of Decimal.

    ``decimal`` precision is process-global. Under ``getcontext().prec = 4``,
    ``Decimal("999.999999999") + Decimal("0.5")`` rounds to exactly ``1000``,
    so an intent whose true total is 1000.499999999 passed a 1000 limit. Any
    unrelated library in the process can set that global, so the engine pins
    its own context rather than trusting what it inherits.
    """

    @pytest.fixture(autouse=True)
    def _restore_context(self):
        saved = getcontext().prec
        saved_traps = dict(getcontext().traps)
        yield
        getcontext().prec = saved
        for k, v in saved_traps.items():
            getcontext().traps[k] = v

    def _near_limit(self):
        pol = RiskPolicy(Decimal("1000"), Decimal("1000"), 9, True)
        book, _ = PaperPortfolio().apply(
            opening("s1", "p1", "AAA", "999.999999999"), pol)
        return book, pol, opening("s2", "p2", "BBB", "0.5")

    @pytest.mark.parametrize("prec", [28, 10, 6, 4, 2, 1])
    def test_a_narrow_ambient_precision_cannot_hide_a_breach(self, prec):
        book, pol, probe = self._near_limit()
        getcontext().prec = prec
        _, decision = book.apply(probe, pol)
        assert not decision.approved, f"limit breach approved at prec={prec}"
        assert RiskReasonCode.TOTAL_EXPOSURE_LIMIT in decision.reason_codes

    @pytest.mark.parametrize("prec", [28, 6, 2, 1])
    def test_reported_exposure_is_not_rounded_by_the_caller(self, prec):
        book, _, _ = self._near_limit()
        getcontext().prec = prec
        assert book.total_open_notional == Decimal("999.999999999")

    @pytest.mark.parametrize("trap", [Inexact, Overflow])
    def test_a_hostile_trap_cannot_turn_a_risk_check_into_an_exception(self, trap):
        book, pol, probe = self._near_limit()
        getcontext().traps[trap] = True
        _, decision = book.apply(probe, pol)  # must not raise
        assert not decision.approved

    def test_the_inclusive_boundary_still_holds_exactly(self):
        pol = RiskPolicy(Decimal("1000"), Decimal("1000"), 9, True)
        book, _ = PaperPortfolio().apply(opening("a", "pa", "A", "600"), pol)
        _, at = book.apply(opening("b", "pb", "B", "400"), pol)
        _, over = book.apply(opening("c", "pc", "C", "400.000000001"), pol)
        assert at.approved
        assert not over.approved
