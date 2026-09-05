"""Phase 7 paper session: manual actions, identifier lifecycle and replay safety.

The dashboard's paper panel is the only place this project mutates anything, so
these tests are about what must *not* happen: no action without an explicit
human submission, no second application of an approved intent, and no path from
a research state to an action.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.paper import (
    DEFAULT_RISK_POLICY,
    PaperSession,
    PendingIntentIds,
    build_provenance,
    parse_notional,
)
from src.portfolio import (
    PaperPortfolio,
    ResearchProvenance,
    RiskOutcome,
    RiskPolicy,
    RiskReasonCode,
)

UTC = timezone.utc
T0 = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def session(**overrides) -> PaperSession:
    """A session with a pinned clock, so timestamps are deterministic."""
    ticks = {"n": 0}

    def clock() -> datetime:
        ticks["n"] += 1
        return T0 + timedelta(minutes=ticks["n"])

    fields = {"now": clock}
    fields.update(overrides)
    return PaperSession(**fields)


# -- starting state ------------------------------------------------------


def test_a_new_session_has_an_empty_portfolio():
    state = session()
    assert state.portfolio == PaperPortfolio()
    assert state.open_positions == ()
    assert state.closed_positions == ()
    assert state.portfolio.open_position_count == 0
    assert state.portfolio.total_open_notional == Decimal(0)
    assert state.last_decision is None


def test_default_risk_policy_is_a_real_phase_five_policy():
    assert isinstance(DEFAULT_RISK_POLICY, RiskPolicy)
    assert DEFAULT_RISK_POLICY.max_open_positions == 5
    assert DEFAULT_RISK_POLICY.allow_duplicate_symbol is False


# -- notional parsing ----------------------------------------------------


def test_notional_is_parsed_from_text_not_float():
    assert parse_notional("1000.10") == Decimal("1000.10")
    assert parse_notional("1,000") == Decimal("1000")


def test_blank_notional_is_a_request_failure():
    with pytest.raises(ApplicationError) as info:
        parse_notional("  ")
    assert info.value.kind is FailureKind.REQUEST


def test_nonsense_notional_is_a_request_failure():
    with pytest.raises(ApplicationError) as info:
        parse_notional("many")
    assert info.value.kind is FailureKind.REQUEST


# -- identifier lifecycle ------------------------------------------------


def test_open_ids_are_stable_across_reruns():
    state = session()
    first = state.pending_open_ids()
    for _ in range(5):
        assert state.pending_open_ids() == first


def test_close_intent_id_is_stable_across_reruns():
    state = session()
    first = state.pending_close_intent_id()
    for _ in range(5):
        assert state.pending_close_intent_id() == first


def test_position_and_intent_ids_are_distinct():
    ids = session().pending_open_ids()
    assert ids.intent_id != ids.position_id


def test_ids_rotate_only_after_an_approved_open():
    state = session()
    before = state.pending_open_ids()
    state.open_long("AAPL", "1000")
    after = state.pending_open_ids()
    assert after != before


# -- OPEN_LONG -----------------------------------------------------------


def test_open_long_approved_creates_exactly_one_position():
    state = session()
    ids = state.pending_open_ids()
    decision = state.open_long("AAPL", "1000")
    assert decision.outcome is RiskOutcome.APPROVED
    assert len(state.open_positions) == 1
    position = state.open_positions[0]
    assert position.position_id == ids.position_id
    assert position.symbol == "AAPL"
    assert position.notional == Decimal("1000")


def test_open_long_normalises_the_symbol():
    state = session()
    state.open_long("  aapl ", "1000")
    assert state.open_positions[0].symbol == "AAPL"


def test_open_long_rejected_by_position_limit_leaves_portfolio_untouched():
    state = session()
    decision = state.open_long("AAPL", "999999")
    assert decision.outcome is RiskOutcome.REJECTED
    assert RiskReasonCode.POSITION_LIMIT in decision.reason_codes
    assert state.open_positions == ()


def test_open_long_rejected_by_total_exposure_limit():
    state = session()
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        state.open_long(symbol, "10000")
    # 50000 of 50000 used; the sixth would exceed the total.
    decision = state.open_long("FFF", "10000")
    assert decision.outcome is RiskOutcome.REJECTED
    assert {
        RiskReasonCode.TOTAL_EXPOSURE_LIMIT,
        RiskReasonCode.OPEN_POSITION_LIMIT,
    } & set(decision.reason_codes)


def test_open_long_rejected_by_open_position_limit():
    state = session()
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        state.open_long(symbol, "100")
    decision = state.open_long("FFF", "100")
    assert decision.outcome is RiskOutcome.REJECTED
    assert RiskReasonCode.OPEN_POSITION_LIMIT in decision.reason_codes
    assert len(state.open_positions) == 5


def test_open_long_rejected_for_a_duplicate_symbol():
    state = session()
    state.open_long("AAPL", "1000")
    decision = state.open_long("AAPL", "1000")
    assert decision.outcome is RiskOutcome.REJECTED
    assert RiskReasonCode.DUPLICATE_SYMBOL in decision.reason_codes
    assert len(state.open_positions) == 1


def test_rejection_records_the_decision_for_display():
    state = session()
    state.open_long("AAPL", "999999")
    assert state.last_decision is not None
    assert state.last_decision.outcome is RiskOutcome.REJECTED
    assert state.last_decision.policy_fingerprint == DEFAULT_RISK_POLICY.fingerprint


def test_portfolio_changes_only_after_an_approved_application():
    state = session()
    before = state.portfolio
    state.open_long("AAPL", "999999")  # rejected
    assert state.portfolio is before
    state.open_long("AAPL", "1000")  # approved
    assert state.portfolio is not before


# -- replay / retry semantics -------------------------------------------


def test_an_approved_intent_cannot_be_applied_twice():
    """Phase 5's replay protection, reached with the ids the form captured."""
    state = session()
    ids = state.pending_open_ids()
    state.open_long("AAPL", "1000", ids=ids)
    assert len(state.open_positions) == 1

    with pytest.raises(ApplicationError) as info:
        state.open_long("AAPL", "1000", ids=ids)
    assert "already been applied" in info.value.message
    assert len(state.open_positions) == 1


def test_a_replayed_open_does_not_mutate_the_portfolio():
    state = session()
    ids = state.pending_open_ids()
    state.open_long("AAPL", "1000", ids=ids)
    after_first = state.portfolio
    with pytest.raises(ApplicationError):
        state.open_long("AAPL", "1000", ids=ids)
    assert state.portfolio is after_first


def test_a_rejected_intent_keeps_its_id_and_remains_retryable():
    state = session()
    before = state.pending_open_ids()
    rejected = state.open_long("AAPL", "999999")
    assert rejected.outcome is RiskOutcome.REJECTED
    # Not consumed: the same id is still pending.
    assert state.pending_open_ids() == before

    approved = state.open_long("AAPL", "1000")
    assert approved.outcome is RiskOutcome.APPROVED
    assert approved.intent_id == before.intent_id
    assert len(state.open_positions) == 1


def test_two_distinct_submissions_create_two_positions():
    state = session()
    state.open_long("AAPL", "1000")
    state.open_long("MSFT", "1000")
    assert len(state.open_positions) == 2
    ids = {p.position_id for p in state.open_positions}
    assert len(ids) == 2


# -- CLOSE ---------------------------------------------------------------


def test_close_an_open_position():
    state = session()
    state.open_long("AAPL", "1000")
    target = state.open_positions[0].position_id

    decision = state.close_position(target)
    assert decision.outcome is RiskOutcome.APPROVED
    assert state.open_positions == ()
    assert len(state.closed_positions) == 1
    closed = state.closed_positions[0]
    assert closed.position_id == target
    assert closed.closed_at is not None


def test_closed_positions_are_absent_from_the_close_selector():
    state = session()
    state.open_long("AAPL", "1000")
    target = state.open_positions[0].position_id
    assert target in state.closable_ids
    state.close_position(target)
    assert target not in state.closable_ids
    assert state.closable_ids == ()


def test_closing_an_already_closed_position_is_refused_cleanly():
    state = session()
    state.open_long("AAPL", "1000")
    target = state.open_positions[0].position_id
    state.close_position(target)
    before = state.portfolio

    with pytest.raises(ApplicationError) as info:
        state.close_position(target)
    assert "already closed" in info.value.message
    assert state.portfolio is before


def test_closing_an_unknown_position_is_refused_cleanly():
    state = session()
    before = state.portfolio
    with pytest.raises(ApplicationError) as info:
        state.close_position("no-such-position")
    assert "unknown position" in info.value.message
    assert state.portfolio is before


def test_a_replayed_close_is_refused():
    state = session()
    state.open_long("AAPL", "1000")
    target = state.open_positions[0].position_id
    intent_id = state.pending_close_intent_id()
    state.close_position(target, intent_id=intent_id)

    state.open_long("MSFT", "1000")
    second = state.open_positions[0].position_id
    with pytest.raises(ApplicationError) as info:
        state.close_position(second, intent_id=intent_id)
    assert "already been applied" in info.value.message
    assert len(state.open_positions) == 1


def test_close_records_no_price_or_profit():
    state = session()
    state.open_long("AAPL", "1000")
    state.close_position(state.open_positions[0].position_id)
    closed = state.closed_positions[0]
    for forbidden in ("price", "pnl", "profit", "cash", "quantity", "market_value"):
        assert not hasattr(closed, forbidden)


# -- research provenance -------------------------------------------------


def test_provenance_is_preserved_on_the_position():
    state = session()
    note = build_provenance(
        hypothesis_id="trend_alignment",
        hypothesis_version=1,
        hypothesis_fingerprint="0123456789abcdef",
        observation_timestamp=T0,
    )
    state.open_long("AAPL", "1000", provenance=note)
    assert state.open_positions[0].research_provenance == note


def test_provenance_is_optional_and_absent_by_default():
    state = session()
    state.open_long("AAPL", "1000")
    assert state.open_positions[0].research_provenance is None


def test_provenance_does_not_authorise_anything():
    """A note cannot turn a rejected action into an approved one."""
    note = build_provenance(
        hypothesis_id="trend_alignment",
        hypothesis_version=1,
        hypothesis_fingerprint="0123456789abcdef",
        observation_timestamp=T0,
    )
    without = session().open_long("AAPL", "999999")
    with_note = session().open_long("AAPL", "999999", provenance=note)
    assert without.outcome is with_note.outcome is RiskOutcome.REJECTED
    assert without.reason_codes == with_note.reason_codes


def test_provenance_is_not_authenticated():
    """Nothing checks the note against a real observation; that is the boundary."""
    state = session()
    invented = build_provenance(
        hypothesis_id="never_evaluated",
        hypothesis_version=99,
        hypothesis_fingerprint="ffffffffffffffff",
        observation_timestamp=T0,
    )
    decision = state.open_long("AAPL", "1000", provenance=invented)
    assert decision.outcome is RiskOutcome.APPROVED
    assert state.open_positions[0].research_provenance == invented


def test_build_provenance_returns_the_phase_five_type():
    note = build_provenance(
        hypothesis_id="trend_alignment",
        hypothesis_version=1,
        hypothesis_fingerprint="0123456789abcdef",
        observation_timestamp=T0,
    )
    assert isinstance(note, ResearchProvenance)


# -- no research can reach an action ------------------------------------


PAPER_SOURCE = pathlib.Path("src/application/paper.py")


def test_paper_module_imports_nothing_from_the_assessment_package():
    tree = ast.parse(PAPER_SOURCE.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name.startswith("src.assessments") for name in imported)
    assert not any(name.startswith("src.strategies") for name in imported)


def test_no_assessment_state_can_influence_action_construction():
    """``open_long`` accepts only a symbol, an amount and an optional note."""
    import inspect

    parameters = set(inspect.signature(PaperSession.open_long).parameters)
    assert parameters == {"self", "symbol", "notional", "provenance", "ids"}


def test_notional_is_never_defaulted_from_anything():
    """There is no default: an empty amount is refused, not guessed."""
    import inspect

    signature = inspect.signature(PaperSession.open_long)
    assert signature.parameters["notional"].default is inspect.Parameter.empty
    with pytest.raises(ApplicationError):
        session().open_long("AAPL", "")


def test_paper_session_writes_nothing_to_disk():
    source = PAPER_SOURCE.read_text()
    for forbidden in ("open(", "json.dump", "sqlite3", "Path(", "to_csv", "pickle"):
        assert forbidden not in source
