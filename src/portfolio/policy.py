"""Deterministic risk limits and their auditable decision record.

A :class:`RiskPolicy` governs **new exposure**.  A :class:`RiskDecision`
records whether an intent was approved and, if not, every reason it was not.
Neither executes anything.

Limits are inclusive
--------------------
An intent exactly at a limit is APPROVED; only strictly exceeding it is
rejected.  "Maximum 1000" that refuses 1000 is a surprising contract, and with
``Decimal`` arithmetic the boundary is exact, so there is no floating-point
excuse for fudging it.

Closing is risk-reducing
------------------------
Opening limits govern opening. A valid close of an existing position is never
rejected for exposure reasons -- refusing to let someone reduce exposure
because their exposure is too high would be perverse. See
:meth:`RiskPolicy.evaluate`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal, localcontext
from enum import Enum
from typing import Sequence


#: Exposure arithmetic runs in this context, never the caller's ambient one.
#:
#: ``Decimal`` was chosen so limit comparisons are exact, but exactness is a
#: property of the *context*, not of the type: under ``getcontext().prec = 4``,
#: ``Decimal("999.999999999") + Decimal("0.5")`` rounds to ``1000`` and an
#: intent that genuinely breaches a 1000 limit is approved. The ambient context
#: is process-global and any unrelated library can set it, so the risk engine
#: pins its own instead of trusting whatever it inherits. Traps are cleared so
#: a caller who has armed ``Inexact`` or ``Overflow`` cannot turn a risk check
#: into an exception, and the exponent range is opened to the maximum so no
#: representable limit is unreachable.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN, traps=[])


def exact_add(left: Decimal, right: Decimal) -> Decimal:
    """Add two amounts free of the caller's ambient decimal context."""
    with localcontext(_EXACT):
        return left + right


class PolicyError(ValueError):
    """Raised when a risk policy is structurally invalid."""


class RiskOutcome(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class RiskReasonCode(str, Enum):
    """Closed vocabulary of policy rejection reasons.

    Only reasons this model actually evaluates. Structural faults --
    malformed size, unknown close target, duplicate id -- are **not** here:
    they raise, because domain corruption is not a policy outcome.
    """

    POSITION_LIMIT = "position_limit"
    TOTAL_EXPOSURE_LIMIT = "total_exposure_limit"
    OPEN_POSITION_LIMIT = "open_position_limit"
    DUPLICATE_SYMBOL = "duplicate_symbol"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Canonical reporting order for reason codes. Fixed so a dashboard and a test
#: see the same sequence regardless of the order rules happened to run in.
_REASON_ORDER = (
    RiskReasonCode.POSITION_LIMIT,
    RiskReasonCode.TOTAL_EXPOSURE_LIMIT,
    RiskReasonCode.OPEN_POSITION_LIMIT,
    RiskReasonCode.DUPLICATE_SYMBOL,
)


def canonical_decimal(value: Decimal) -> str:
    """Deterministic, bounded text for a Decimal, identical for equal values.

    ``Decimal("100")``, ``Decimal("100.0")``, ``Decimal("1E+2")`` and
    ``Decimal("0.01E+4")`` are the same amount and must fingerprint
    identically -- a policy is not changed by how its limit was typed.

    Built from the structural ``(sign, digits, exponent)`` triple with trailing
    zeros stripped, rather than from a fixed-point rendering. Two earlier
    approaches fail here:

    * ``format(d.normalize(), "f")`` materialises one character per power of
      ten, so a valid ``Decimal("1E+100000")`` limit produced a 100,001-char
      string -- unbounded output from a tiny input.
    * ``normalize()`` alone raises ``decimal.Overflow`` beyond the context's
      Emax, so ``Decimal("1E+1000000")`` made a *successfully validated* policy
      throw a non-domain exception when asked for its identity.

    Output length here is bounded by the number of significant digits, which
    is bounded by the literal the caller wrote. No context arithmetic is
    performed, so no overflow is possible.
    """
    if not value.is_finite():
        raise PolicyError(f"cannot canonicalise a non-finite Decimal: {value}")

    sign, digits, exponent = value.as_tuple()
    mantissa = list(digits)

    # Zero has many spellings (0, -0, 0.00, 0E+9); all are the same value.
    if not any(mantissa):
        return "0"

    while len(mantissa) > 1 and mantissa[-1] == 0:
        mantissa.pop()
        exponent += 1

    rendered = "".join(str(digit) for digit in mantissa)
    return f"{'-' if sign else ''}{rendered}E{exponent}"


def _require_limit(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise PolicyError(f"{label} must be a Decimal, got bool")
    if isinstance(value, float):
        raise PolicyError(
            f"{label} must be a Decimal, got float; pass Decimal(\"{value}\") explicitly "
            "so limit arithmetic stays exact"
        )
    if not isinstance(value, Decimal):
        raise PolicyError(f"{label} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise PolicyError(f"{label} must be finite, got {value}")
    if value <= 0:
        raise PolicyError(f"{label} must be > 0, got {value}")
    return value


@dataclass(frozen=True)
class RiskPolicy:
    """Immutable, fingerprinted risk limits. Every field must be given.

    There is deliberately **no default policy**: a policy that silently permits
    everything is worse than one that refuses to be constructed, because it
    looks like risk control while being none.
    """

    max_notional_per_position: Decimal
    max_total_notional: Decimal
    max_open_positions: int
    allow_duplicate_symbol: bool

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(
            self,
            "max_notional_per_position",
            _require_limit(self.max_notional_per_position, "max_notional_per_position"),
        )
        set_(self, "max_total_notional", _require_limit(self.max_total_notional, "max_total_notional"))

        if isinstance(self.max_open_positions, bool) or not isinstance(
            self.max_open_positions, int
        ):
            raise PolicyError(
                f"max_open_positions must be an int, got {type(self.max_open_positions).__name__}"
            )
        if self.max_open_positions < 1:
            raise PolicyError(
                f"max_open_positions must be >= 1, got {self.max_open_positions}; a policy "
                "permitting zero positions cannot approve anything and is not a usable "
                "paper-research configuration"
            )
        if not isinstance(self.allow_duplicate_symbol, bool):
            raise PolicyError(
                f"allow_duplicate_symbol must be a bool, got "
                f"{type(self.allow_duplicate_symbol).__name__}"
            )

    # -- identity --------------------------------------------------------

    @property
    def canonical_form(self) -> str:
        """The exact string the fingerprint is taken over. Human-readable so
        two disagreeing policies can be diffed rather than compared as hashes."""
        return (
            f"max_notional_per_position={canonical_decimal(self.max_notional_per_position)}"
            f"|max_total_notional={canonical_decimal(self.max_total_notional)}"
            f"|max_open_positions=int:{self.max_open_positions}"
            f"|allow_duplicate_symbol=bool:{'true' if self.allow_duplicate_symbol else 'false'}"
        )

    @property
    def fingerprint(self) -> str:
        """Deterministic 16-hex digest, stable across processes and machines.

        Python's ``hash()`` is randomised per process and is never used for
        identity anywhere in this repository.
        """
        return hashlib.sha256(self.canonical_form.encode("utf-8")).hexdigest()[:16]

    @property
    def label(self) -> str:
        return f"risk_policy#{self.fingerprint}"

    # -- evaluation ------------------------------------------------------

    def evaluate_open(
        self,
        *,
        intent_id: str,
        notional: Decimal,
        symbol: str,
        current_total_open: Decimal,
        current_open_count: int,
        open_symbols: Sequence[str],
    ) -> "RiskDecision":
        """Evaluate a well-formed OPEN_LONG against every rule.

        All rules are evaluated -- not short-circuited at the first violation --
        so a caller learns everything that is wrong at once. Reason codes are
        returned in :data:`_REASON_ORDER`.

        Limits are inclusive: rejection requires strictly exceeding them.
        """
        violations: set[RiskReasonCode] = set()

        if notional > self.max_notional_per_position:
            violations.add(RiskReasonCode.POSITION_LIMIT)
        if exact_add(current_total_open, notional) > self.max_total_notional:
            violations.add(RiskReasonCode.TOTAL_EXPOSURE_LIMIT)
        if current_open_count + 1 > self.max_open_positions:
            violations.add(RiskReasonCode.OPEN_POSITION_LIMIT)
        if not self.allow_duplicate_symbol and symbol in set(open_symbols):
            violations.add(RiskReasonCode.DUPLICATE_SYMBOL)

        if violations:
            return RiskDecision(
                outcome=RiskOutcome.REJECTED,
                policy_fingerprint=self.fingerprint,
                intent_id=intent_id,
                reason_codes=tuple(violations),
            )
        return RiskDecision(
            outcome=RiskOutcome.APPROVED,
            policy_fingerprint=self.fingerprint,
            intent_id=intent_id,
        )

    def evaluate_close(self, *, intent_id: str) -> "RiskDecision":
        """A structurally valid close is always approved by policy.

        Closing reduces exposure. Rejecting it because exposure is already at
        or over a limit would trap a portfolio in the state the limit exists to
        prevent. Structural problems -- unknown target, already closed, close
        before open -- still raise; they are handled before this is called.
        """
        return RiskDecision(
            outcome=RiskOutcome.APPROVED,
            policy_fingerprint=self.fingerprint,
            intent_id=intent_id,
        )


@dataclass(frozen=True)
class RiskDecision:
    """The auditable result of a policy evaluation. Executes nothing.

    Carries both halves of what it judged: ``intent_id`` (which intent) and
    ``policy_fingerprint`` (under which limits). Without the first, a detached
    ``REJECTED`` record cannot say what was refused; without the second, an
    ``APPROVED`` record cannot say whether the limits were strict or absurd.

    Reason codes are **canonicalised at construction** -- deduplicated and
    sorted into :data:`_REASON_ORDER` -- so every decision satisfies the
    documented ordering contract no matter how it was built, not only those
    produced by :meth:`RiskPolicy.evaluate_open`.
    """

    outcome: RiskOutcome
    policy_fingerprint: str
    intent_id: str
    reason_codes: tuple[RiskReasonCode, ...] = ()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "outcome", RiskOutcome(self.outcome))

        for label in ("policy_fingerprint", "intent_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise PolicyError(f"{label} must be a non-empty str, got {value!r}")
            set_(self, label, value.strip())

        supplied = {RiskReasonCode(code) for code in self.reason_codes}
        set_(self, "reason_codes", tuple(code for code in _REASON_ORDER if code in supplied))

        if self.outcome is RiskOutcome.APPROVED and self.reason_codes:
            raise PolicyError(
                "an APPROVED decision must carry no reason codes; a reason on an approval "
                "would read as a caveat the engine cannot substantiate"
            )
        if self.outcome is RiskOutcome.REJECTED and not self.reason_codes:
            raise PolicyError(
                "a REJECTED decision must carry at least one reason code; an unexplained "
                "rejection is not auditable"
            )

    @property
    def approved(self) -> bool:
        return self.outcome is RiskOutcome.APPROVED

    def describe(self) -> str:
        codes = ",".join(code.value for code in self.reason_codes) or "-"
        return (
            f"{self.outcome.value} [{codes}] intent={self.intent_id} "
            f"policy#{self.policy_fingerprint}"
        )


__all__ = [
    "RiskPolicy",
    "RiskDecision",
    "RiskOutcome",
    "RiskReasonCode",
    "PolicyError",
    "canonical_decimal",
]
