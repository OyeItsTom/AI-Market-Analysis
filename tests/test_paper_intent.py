"""PaperIntent, PaperAction and provenance: structural validation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.portfolio import (
    CloseIntent,
    IntentError,
    OpenLongIntent,
    PaperAction,
    PaperIntent,
    ResearchProvenance,
)

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def open_intent(**overrides):
    fields = dict(
        intent_id="i1", intent_created_at=T0, position_id="p1",
        symbol="AAPL", notional=Decimal("1000"),
    )
    fields.update(overrides)
    return OpenLongIntent(**fields)


class TestPaperAction:
    def test_exactly_two_actions_exist(self):
        assert {a.value for a in PaperAction} == {"open_long", "close"}

    @pytest.mark.parametrize(
        "forbidden",
        ["OPEN_SHORT", "SELL_SHORT", "BUY", "SELL", "PENDING", "FILLED",
         "PARTIALLY_FILLED", "CANCELLED"],
    )
    def test_execution_and_short_actions_do_not_exist(self, forbidden):
        """Long-only: a short is not representable, not merely rejected."""
        assert forbidden not in {a.name for a in PaperAction}


class TestOpenLongIntent:
    def test_a_valid_intent(self):
        intent = open_intent()
        assert intent.action is PaperAction.OPEN_LONG
        assert intent.notional == Decimal("1000")

    def test_symbol_follows_the_phase_1_contract(self):
        assert open_intent(symbol="  aapl ").symbol == "AAPL"

    @pytest.mark.parametrize("bad", ["", "   ", 123, None])
    def test_invalid_symbols_are_rejected(self, bad):
        with pytest.raises(IntentError):
            open_intent(symbol=bad)

    @pytest.mark.parametrize("field", ["intent_id", "position_id"])
    @pytest.mark.parametrize("bad", ["", "   ", 5, None])
    def test_invalid_identifiers_are_rejected(self, field, bad):
        with pytest.raises(IntentError):
            open_intent(**{field: bad})

    def test_float_notional_is_rejected_not_converted(self):
        """Decimal(0.1) would carry binary artefacts into exposure arithmetic."""
        with pytest.raises(IntentError, match="got float"):
            open_intent(notional=1000.0)

    def test_the_float_rejection_tells_the_caller_what_to_pass_instead(self):
        """The generic "not a Decimal" guard also rejects floats, so matching
        only "got float" cannot tell the float-specific branch from its
        fallback. The remedy in the message is the point of that branch."""
        with pytest.raises(IntentError, match="Converting a float") as exc:
            open_intent(notional=0.1)
        assert 'Decimal("0.1")' in str(exc.value)

    def test_bool_notional_is_rejected(self):
        with pytest.raises(IntentError, match="got bool"):
            open_intent(notional=True)

    @pytest.mark.parametrize(
        "bad", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"),
                Decimal("-Infinity")],
    )
    def test_non_positive_or_non_finite_notionals_are_rejected(self, bad):
        with pytest.raises(IntentError):
            open_intent(notional=bad)

    @pytest.mark.parametrize("bad", [1000, "1000", None])
    def test_non_decimal_notionals_are_rejected(self, bad):
        with pytest.raises(IntentError):
            open_intent(notional=bad)

    def test_a_naive_timestamp_is_rejected(self):
        with pytest.raises(IntentError, match="timezone-aware"):
            open_intent(intent_created_at=datetime(2024, 1, 1))

    def test_an_aware_timestamp_is_accepted(self):
        assert open_intent(intent_created_at=T0).intent_created_at == T0

    def test_it_is_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            open_intent().notional = Decimal("1")  # type: ignore[misc]


class TestCloseIntent:
    def test_a_valid_close(self):
        intent = CloseIntent("i2", T0, target_position_id="p1")
        assert intent.action is PaperAction.CLOSE

    def test_it_carries_no_notional_or_symbol_at_all(self):
        """The targeted position stays authoritative for both.

        These attributes are structurally absent, so a close cannot assert a
        size or symbol that disagrees with the position it closes.
        """
        intent = CloseIntent("i2", T0, target_position_id="p1")
        assert not hasattr(intent, "notional")
        assert not hasattr(intent, "symbol")

    @pytest.mark.parametrize("bad", ["", "   ", 7, None])
    def test_an_invalid_target_is_rejected(self, bad):
        with pytest.raises(IntentError):
            CloseIntent("i2", T0, target_position_id=bad)

    def test_a_naive_timestamp_is_rejected(self):
        with pytest.raises(IntentError, match="timezone-aware"):
            CloseIntent("i2", datetime(2024, 1, 1), target_position_id="p1")


class TestAbstractBase:
    def test_the_base_intent_cannot_be_constructed(self):
        with pytest.raises(IntentError, match="abstract"):
            PaperIntent("i1", T0)


class TestResearchProvenance:
    def test_it_is_optional(self):
        assert open_intent().research_provenance is None

    def test_it_is_preserved_verbatim(self):
        provenance = ResearchProvenance("momentum", 2, "abcdef0123456789", T0)
        intent = open_intent(research_provenance=provenance)
        assert intent.research_provenance == provenance
        assert intent.research_provenance.hypothesis_fingerprint == "abcdef0123456789"

    def test_arbitrary_provenance_is_accepted_not_authenticated(self):
        """Preserved, not authenticated — the Phase 4 boundary."""
        forged = ResearchProvenance("never_existed", 99, "0000000000000000", T0)
        assert open_intent(research_provenance=forged).research_provenance is forged

    def test_it_holds_no_research_state(self):
        provenance = ResearchProvenance("h", 1, "fp", T0)
        fields = set(provenance.__dataclass_fields__)
        assert "state" not in fields
        assert not any("bullish" in str(getattr(provenance, f)).lower() for f in fields)

    @pytest.mark.parametrize(
        ("field", "bad"),
        [("hypothesis_id", ""), ("hypothesis_fingerprint", "  "),
         ("hypothesis_version", 0), ("hypothesis_version", True),
         ("observation_timestamp", datetime(2024, 1, 1))],
    )
    def test_malformed_provenance_is_rejected(self, field, bad):
        fields = dict(hypothesis_id="h", hypothesis_version=1,
                      hypothesis_fingerprint="fp", observation_timestamp=T0)
        fields[field] = bad
        with pytest.raises(IntentError):
            ResearchProvenance(**fields)

    def test_a_wrong_provenance_type_is_rejected(self):
        with pytest.raises(IntentError, match="ResearchProvenance"):
            open_intent(research_provenance={"hypothesis_id": "h"})

    def test_it_is_immutable(self):
        provenance = ResearchProvenance("h", 1, "fp", T0)
        with pytest.raises((AttributeError, TypeError)):
            provenance.hypothesis_id = "other"  # type: ignore[misc]
