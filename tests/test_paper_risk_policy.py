"""RiskPolicy identity, RiskDecision invariants and inclusive limit boundaries."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal

import pytest

from src.portfolio import (
    PolicyError,
    RiskDecision,
    RiskOutcome,
    RiskPolicy,
    RiskReasonCode,
    canonical_decimal,
)


def policy(**overrides):
    fields = dict(
        max_notional_per_position=Decimal("1000"),
        max_total_notional=Decimal("5000"),
        max_open_positions=3,
        allow_duplicate_symbol=False,
    )
    fields.update(overrides)
    return RiskPolicy(**fields)


def evaluate(pol, notional, *, symbol="AAPL", total=Decimal("0"), count=0, symbols=(),
             intent_id="i1"):
    return pol.evaluate_open(
        intent_id=intent_id, notional=notional, symbol=symbol, current_total_open=total,
        current_open_count=count, open_symbols=symbols,
    )


class TestPolicyValidation:
    def test_a_valid_policy(self):
        assert policy().max_open_positions == 3

    @pytest.mark.parametrize("field", ["max_notional_per_position", "max_total_notional"])
    @pytest.mark.parametrize(
        "bad", [1000.0, True, 1000, "1000", Decimal("0"), Decimal("-1"),
                Decimal("NaN"), Decimal("Infinity")],
    )
    def test_invalid_decimal_limits_are_rejected(self, field, bad):
        with pytest.raises(PolicyError):
            policy(**{field: bad})

    def test_float_limits_are_rejected_not_converted(self):
        with pytest.raises(PolicyError, match="got float"):
            policy(max_total_notional=5000.0)

    def test_bool_max_open_positions_is_rejected(self):
        """bool is an int subclass; a policy of `True` positions is nonsense."""
        with pytest.raises(PolicyError, match="got bool"):
            policy(max_open_positions=True)

    @pytest.mark.parametrize("bad", [0, -1, 2.0, "3", None])
    def test_invalid_max_open_positions_are_rejected(self, bad):
        with pytest.raises(PolicyError):
            policy(max_open_positions=bad)

    def test_zero_positions_is_rejected_with_a_reason(self):
        with pytest.raises(PolicyError, match="cannot approve anything"):
            policy(max_open_positions=0)

    @pytest.mark.parametrize("bad", [1, "yes", None])
    def test_a_non_bool_duplicate_flag_is_rejected(self, bad):
        with pytest.raises(PolicyError):
            policy(allow_duplicate_symbol=bad)

    def test_there_is_no_default_policy(self):
        """Every field must be given; a permissive default is not offered."""
        with pytest.raises(TypeError):
            RiskPolicy()  # type: ignore[call-arg]

    def test_it_is_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            policy().max_open_positions = 99  # type: ignore[misc]


class TestPolicyIdentity:
    def test_identical_policies_share_a_fingerprint(self):
        assert policy().fingerprint == policy().fingerprint

    @pytest.mark.parametrize(
        ("field", "value"),
        [("max_notional_per_position", Decimal("999")),
         ("max_total_notional", Decimal("4999")),
         ("max_open_positions", 4),
         ("allow_duplicate_symbol", True)],
    )
    def test_every_material_field_changes_identity(self, field, value):
        assert policy().fingerprint != policy(**{field: value}).fingerprint

    def test_semantically_equal_decimals_fingerprint_identically(self):
        """A policy is not changed by how its limit was typed."""
        a = RiskPolicy(Decimal("1000"), Decimal("5000"), 3, False)
        b = RiskPolicy(Decimal("1000.00"), Decimal("5.0E+3"), 3, False)
        c = RiskPolicy(Decimal("1.000E+3"), Decimal("5000.0000"), 3, False)
        assert a.fingerprint == b.fingerprint == c.fingerprint

    @pytest.mark.parametrize(
        ("a", "b"), [("100", "100.0"), ("100", "1E+2"), ("0.1", "0.10"),
                     ("0.1", "0.100000"), ("5000", "5.0E+3")],
    )
    def test_canonical_decimal_collapses_equal_forms(self, a, b):
        assert canonical_decimal(Decimal(a)) == canonical_decimal(Decimal(b))

    @pytest.mark.parametrize(("a", "b"), [("100", "101"), ("0.1", "0.2")])
    def test_canonical_decimal_distinguishes_different_values(self, a, b):
        assert canonical_decimal(Decimal(a)) != canonical_decimal(Decimal(b))

    def test_canonical_decimal_uses_a_bounded_exponent_form(self):
        """Deliberately exponent notation, not fixed point.

        An earlier version rendered fixed point, which is friendlier to read
        but grows one character per power of ten -- the amplification this
        form exists to avoid. The mantissa is normalised so equal values still
        agree.
        """
        assert canonical_decimal(Decimal("1E+2")) == "1E2"
        assert canonical_decimal(Decimal("100")) == "1E2"
        assert canonical_decimal(Decimal("123")) == "123E0"

    def test_the_bool_field_is_type_tagged(self):
        assert "bool:false" in policy().canonical_form

    def test_the_canonical_form_names_every_field(self):
        form = policy().canonical_form
        for token in ("max_notional_per_position=", "max_total_notional=",
                      "max_open_positions=", "allow_duplicate_symbol="):
            assert token in form

    def test_the_fingerprint_is_deterministic_across_processes(self):
        code = (
            "from decimal import Decimal;from src.portfolio import RiskPolicy;"
            "print(RiskPolicy(Decimal('1000'),Decimal('5000'),3,False).fingerprint)"
        )
        results = set()
        for seed in ("0", "1", "12345"):
            proc = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}, cwd=".",
            )
            results.add(proc.stdout.strip())
        assert len(results) == 1, f"fingerprint varied: {results}"


class TestInclusiveBoundaries:
    """An intent exactly at a limit is approved; only exceeding it is rejected."""

    def test_exact_per_position_limit_is_approved(self):
        assert evaluate(policy(), Decimal("1000")).approved

    def test_one_unit_above_per_position_is_rejected(self):
        decision = evaluate(policy(), Decimal("1000.01"))
        assert not decision.approved
        assert RiskReasonCode.POSITION_LIMIT in decision.reason_codes

    def test_exact_total_exposure_limit_is_approved(self):
        assert evaluate(policy(), Decimal("1000"), total=Decimal("4000")).approved

    def test_one_unit_above_total_exposure_is_rejected(self):
        decision = evaluate(policy(), Decimal("1000"), total=Decimal("4000.01"))
        assert RiskReasonCode.TOTAL_EXPOSURE_LIMIT in decision.reason_codes

    def test_exact_open_position_count_is_approved(self):
        # count 2 + this one == max 3
        assert evaluate(policy(), Decimal("100"), count=2).approved

    def test_one_above_the_position_count_is_rejected(self):
        decision = evaluate(policy(), Decimal("100"), count=3)
        assert RiskReasonCode.OPEN_POSITION_LIMIT in decision.reason_codes

    def test_the_mandatory_decimal_boundary(self):
        """Decimal("0.1") + Decimal("0.2") must not exceed Decimal("0.3").

        In binary floats 0.1 + 0.2 == 0.30000000000000004, which would reject
        an intent that exactly meets its limit.
        """
        assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
        pol = RiskPolicy(Decimal("1"), Decimal("0.3"), 5, True)
        assert evaluate(pol, Decimal("0.1"), total=Decimal("0.2")).approved

    def test_extreme_but_finite_decimals(self):
        pol = RiskPolicy(Decimal("1E+30"), Decimal("1E+30"), 5, True)
        assert evaluate(pol, Decimal("1E+29")).approved


class TestDuplicateSymbol:
    def test_a_duplicate_open_symbol_is_rejected_when_disallowed(self):
        decision = evaluate(policy(), Decimal("100"), symbol="AAPL", count=1, symbols=("AAPL",))
        assert RiskReasonCode.DUPLICATE_SYMBOL in decision.reason_codes

    def test_a_different_symbol_is_allowed(self):
        assert evaluate(policy(), Decimal("100"), symbol="MSFT", count=1, symbols=("AAPL",)).approved

    def test_duplicates_are_allowed_when_enabled(self):
        pol = policy(allow_duplicate_symbol=True)
        assert evaluate(pol, Decimal("100"), symbol="AAPL", count=1, symbols=("AAPL",)).approved


class TestAllViolationsReported:
    def test_every_violated_rule_is_returned(self):
        pol = RiskPolicy(Decimal("10"), Decimal("10"), 1, False)
        decision = pol.evaluate_open(
            intent_id="i1", notional=Decimal("100"), symbol="AAPL",
            current_total_open=Decimal("50"), current_open_count=5, open_symbols=("AAPL",),
        )
        assert set(decision.reason_codes) == {
            RiskReasonCode.POSITION_LIMIT, RiskReasonCode.TOTAL_EXPOSURE_LIMIT,
            RiskReasonCode.OPEN_POSITION_LIMIT, RiskReasonCode.DUPLICATE_SYMBOL,
        }

    def test_reason_order_is_stable_and_canonical(self):
        pol = RiskPolicy(Decimal("10"), Decimal("10"), 1, False)
        decision = pol.evaluate_open(
            intent_id="i1", notional=Decimal("100"), symbol="AAPL",
            current_total_open=Decimal("50"), current_open_count=5, open_symbols=("AAPL",),
        )
        assert decision.reason_codes == (
            RiskReasonCode.POSITION_LIMIT, RiskReasonCode.TOTAL_EXPOSURE_LIMIT,
            RiskReasonCode.OPEN_POSITION_LIMIT, RiskReasonCode.DUPLICATE_SYMBOL,
        )

    def test_evaluation_does_not_stop_at_the_first_violation(self):
        pol = RiskPolicy(Decimal("10"), Decimal("10"), 1, False)
        decision = evaluate(pol, Decimal("100"), total=Decimal("50"))
        assert len(decision.reason_codes) >= 2


class TestRiskDecision:
    def test_an_approval_carries_no_reasons(self):
        assert evaluate(policy(), Decimal("100")).reason_codes == ()

    def test_an_approval_with_reasons_is_refused(self):
        with pytest.raises(PolicyError, match="no reason codes"):
            RiskDecision(RiskOutcome.APPROVED, "fp", "i1", (RiskReasonCode.POSITION_LIMIT,))

    def test_a_rejection_without_reasons_is_refused(self):
        with pytest.raises(PolicyError, match="at least one reason"):
            RiskDecision(RiskOutcome.REJECTED, "fp", "i1", ())

    def test_it_records_the_policy_that_produced_it(self):
        pol = policy()
        assert evaluate(pol, Decimal("100")).policy_fingerprint == pol.fingerprint

    def test_it_is_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            evaluate(policy(), Decimal("100")).outcome = RiskOutcome.REJECTED  # type: ignore[misc]

    def test_reason_codes_are_a_closed_vocabulary(self):
        assert {c.value for c in RiskReasonCode} == {
            "position_limit", "total_exposure_limit",
            "open_position_limit", "duplicate_symbol",
        }

    def test_structural_faults_are_not_reason_codes(self):
        """Malformed input raises; it is never reported as a policy outcome."""
        for absent in ("INVALID_SIZE", "INVALID_DIRECTION", "UNKNOWN_POSITION"):
            assert absent not in {c.name for c in RiskReasonCode}


class TestCanonicalDecimalIsBoundedAndTotal:
    """Regression: canonicalisation must not amplify or overflow.

    ``format(d.normalize(), "f")`` produced one character per power of ten,
    so a valid ``Decimal("1E+100000")`` limit yielded a 100,001-char string;
    and ``normalize()`` raised ``decimal.Overflow`` past the context Emax, so a
    successfully validated policy could not compute its own fingerprint.
    """

    @pytest.mark.parametrize("exponent", [100, 10_000, 100_000, 1_000_000, 10**9])
    def test_output_length_does_not_grow_with_the_exponent(self, exponent):
        rendered = canonical_decimal(Decimal(f"1E+{exponent}"))
        assert len(rendered) < 40, f"canonical form grew to {len(rendered)} chars"

    @pytest.mark.parametrize("exponent", [100_000, 1_000_000, 10**9])
    def test_extreme_exponents_do_not_raise(self, exponent):
        for value in (Decimal(f"1E+{exponent}"), Decimal(f"1E-{exponent}")):
            assert canonical_decimal(value)

    def test_a_policy_with_an_extreme_limit_can_still_be_fingerprinted(self):
        extreme = Decimal("1E+1000000")
        pol = RiskPolicy(extreme, extreme, 1, True)
        assert len(pol.fingerprint) == 16  # no decimal.Overflow

    def test_length_is_bounded_by_significant_digits_not_magnitude(self):
        few = canonical_decimal(Decimal("1E+1000000"))
        many = canonical_decimal(Decimal("1234567890123456789"))
        assert len(few) < len(many)

    @pytest.mark.parametrize(
        "forms",
        [("100", "100.0", "1E+2", "0.01E+4", "+100.000"),
         ("0.1", "0.10", "1E-1", "0.100000"),
         ("0", "-0", "0.00", "0E+9")],
    )
    def test_every_spelling_of_one_value_renders_identically(self, forms):
        assert len({canonical_decimal(Decimal(f)) for f in forms}) == 1

    def test_different_values_still_differ(self):
        assert canonical_decimal(Decimal("100")) != canonical_decimal(Decimal("1000"))
        assert canonical_decimal(Decimal("1E+2")) != canonical_decimal(Decimal("1E+3"))

    def test_sign_is_preserved(self):
        assert canonical_decimal(Decimal("-100")) != canonical_decimal(Decimal("100"))

    def test_a_non_finite_decimal_is_refused(self):
        for bad in ("NaN", "Infinity", "-Infinity"):
            with pytest.raises(PolicyError, match="non-finite"):
                canonical_decimal(Decimal(bad))


class TestDecisionProvenance:
    """A decision must say what it judged, not merely what it concluded."""

    def test_it_records_the_intent(self):
        assert evaluate(policy(), Decimal("100"), intent_id="intent-42").intent_id == "intent-42"

    def test_it_records_the_policy(self):
        pol = policy()
        assert evaluate(pol, Decimal("100")).policy_fingerprint == pol.fingerprint

    def test_two_policies_are_distinguishable_from_their_decisions(self):
        """An APPROVED record must reveal whether the limits were strict."""
        strict = RiskPolicy(Decimal("1000"), Decimal("1000"), 1, False)
        loose = RiskPolicy(Decimal("1000000"), Decimal("1000000"), 99, True)
        a = strict.evaluate_open(intent_id="i1", notional=Decimal("100"), symbol="X",
                                 current_total_open=Decimal("0"), current_open_count=0,
                                 open_symbols=())
        b = loose.evaluate_open(intent_id="i1", notional=Decimal("100"), symbol="X",
                                current_total_open=Decimal("0"), current_open_count=0,
                                open_symbols=())
        assert a.approved and b.approved
        assert a.policy_fingerprint != b.policy_fingerprint

    @pytest.mark.parametrize("field", ["policy_fingerprint", "intent_id"])
    @pytest.mark.parametrize("bad", ["", "   ", None, 5])
    def test_missing_provenance_is_refused(self, field, bad):
        fields = dict(outcome=RiskOutcome.APPROVED, policy_fingerprint="fp", intent_id="i1")
        fields[field] = bad
        with pytest.raises(PolicyError, match="non-empty str"):
            RiskDecision(**fields)


class TestDecisionReasonCanonicalisation:
    """Ordering is a documented contract, so direct construction must honour it."""

    def test_reason_codes_are_sorted_into_canonical_order(self):
        decision = RiskDecision(
            RiskOutcome.REJECTED, "fp", "i1",
            (RiskReasonCode.DUPLICATE_SYMBOL, RiskReasonCode.POSITION_LIMIT),
        )
        assert decision.reason_codes == (
            RiskReasonCode.POSITION_LIMIT, RiskReasonCode.DUPLICATE_SYMBOL,
        )

    def test_duplicate_reason_codes_are_collapsed(self):
        decision = RiskDecision(
            RiskOutcome.REJECTED, "fp", "i1",
            (RiskReasonCode.POSITION_LIMIT, RiskReasonCode.POSITION_LIMIT),
        )
        assert decision.reason_codes == (RiskReasonCode.POSITION_LIMIT,)

    def test_a_mutable_reason_collection_is_frozen(self):
        codes = [RiskReasonCode.POSITION_LIMIT]
        decision = RiskDecision(RiskOutcome.REJECTED, "fp", "i1", codes)
        codes.append(RiskReasonCode.DUPLICATE_SYMBOL)
        assert decision.reason_codes == (RiskReasonCode.POSITION_LIMIT,)
        assert isinstance(decision.reason_codes, tuple)

    def test_an_invalid_reason_type_is_refused(self):
        """Pinned with a *valid* code alongside the bogus one.

        With only the bogus code, dropping the type check still raises --
        canonical filtering empties the tuple and the "a rejection needs at
        least one reason" invariant fires instead. That passes for the wrong
        reason. Keeping one valid code means the bogus value can only be
        caught by the type check itself.
        """
        with pytest.raises(ValueError, match="not_a_code"):
            RiskDecision(
                RiskOutcome.REJECTED, "fp", "i1",
                (RiskReasonCode.POSITION_LIMIT, "not_a_code"),
            )

    def test_an_unknown_code_is_not_silently_dropped(self):
        with pytest.raises(ValueError):
            RiskDecision(RiskOutcome.REJECTED, "fp", "i1", ("not_a_code",))


class TestCloseIsRiskReducing:
    def test_a_close_is_always_approved_by_policy(self):
        assert policy().evaluate_close(intent_id="i1").approved

    def test_it_carries_no_reason_codes(self):
        assert policy().evaluate_close(intent_id="i1").reason_codes == ()

    def test_it_records_the_intent_it_judged(self):
        assert policy().evaluate_close(intent_id="close-7").intent_id == "close-7"
