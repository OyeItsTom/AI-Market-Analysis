"""Explicit paper intents — the only way a paper action can originate.

A :class:`PaperIntent` means *"a human explicitly recorded this hypothetical
action"*.  It is **not** an order, not an execution, and not something a
research classification can produce.

Structural separation from research
-----------------------------------
This package imports nothing from ``src.strategies`` or ``src.evaluation``.
A ``ResearchState`` is not in scope here, so no code in this module can turn
``BULLISH`` into an action -- that is not a rule a reviewer has to check, it is
an absence of the vocabulary needed to break it.  Research linkage travels as
:class:`ResearchProvenance`: plain identifier strings, preserved for audit and
never interpreted.

Two intents, not one
--------------------
``OPEN_LONG`` and ``CLOSE`` have genuinely different requirements, so they are
separate frozen records under a common base rather than one record with
optional fields.  A :class:`CloseIntent` has no ``notional`` and no ``symbol``
attribute *at all*, so a close cannot claim a size or a symbol that disagrees
with the position it targets -- the existing position stays authoritative.
That impossibility is structural; with one shared dataclass it would only have
been a validation rule.

There is no ``OPEN_SHORT``. Phase 5 is long-only, and a short is not
representable rather than rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class IntentError(ValueError):
    """Raised when an intent is structurally invalid.

    Distinct from a risk rejection: this means the intent is malformed, not
    that a policy declined a well-formed one.
    """


class PaperAction(str, Enum):
    """The complete set of paper actions. Long-only, deliberately."""

    OPEN_LONG = "open_long"
    CLOSE = "close"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def require_identifier(value: object, label: str) -> str:
    """Validate a caller-supplied identifier.

    Identifiers are always supplied by the caller: there is no ``uuid4()`` or
    clock-derived id anywhere in this domain, so the same inputs always
    produce the same records.
    """
    if not isinstance(value, str):
        raise IntentError(f"{label} must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise IntentError(f"{label} must not be empty or whitespace")
    return text


def require_symbol(value: object) -> str:
    """Validate a symbol, following the Phase 1 contract.

    Stripped and upper-cased, exactly as ``MarketBar`` does -- this is an
    established repository behaviour, not a new normalisation invented here.
    """
    if not isinstance(value, str):
        raise IntentError(f"symbol must be a str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise IntentError("symbol must not be empty or whitespace")
    return text.upper()


def require_notional(value: object, label: str = "notional") -> Decimal:
    """Validate a positive, finite :class:`~decimal.Decimal` amount.

    ``float`` is **rejected**, not converted. ``Decimal(0.1)`` would carry the
    binary artefact ``0.1000000000000000055511151231257827...`` into the
    exposure ledger, and a risk engine that rejects an intent exactly meeting
    its limit because of binary representation is worse than none. Callers
    pass ``Decimal("0.1")``.
    """
    if isinstance(value, bool):
        raise IntentError(f"{label} must be a Decimal, got bool")
    if isinstance(value, float):
        raise IntentError(
            f"{label} must be a Decimal, got float. Converting a float would carry "
            "binary floating-point artefacts into exposure arithmetic; pass "
            f'Decimal("{value}") explicitly.'
        )
    if not isinstance(value, Decimal):
        raise IntentError(f"{label} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise IntentError(f"{label} must be finite, got {value}")
    if value <= 0:
        raise IntentError(f"{label} must be > 0, got {value}")
    return value


def require_aware_timestamp(value: object, label: str) -> datetime:
    """Validate a caller-supplied timezone-aware timestamp.

    No clock is read anywhere in this domain. A naive timestamp is ambiguous
    and is refused rather than assumed to be UTC or local time, matching the
    Phase 1 invariant.
    """
    if not isinstance(value, datetime):
        raise IntentError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise IntentError(f"{label} must be timezone-aware; naive timestamps are ambiguous")
    return value


@dataclass(frozen=True)
class ResearchProvenance:
    """A neutral, optional record of which research an intent referenced.

    Deliberately plain strings. This package does not import
    ``ResearchObservation`` or ``ResearchState``, so a paper record can never
    hold a classification, and no code here can branch on one.

    **Preserved, not authenticated** -- exactly the Phase 4 boundary. These
    fields answer *"what does this record claim it referenced?"*, never *"is
    that claim true?"*. Nothing re-runs a hypothesis.
    """

    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    observation_timestamp: datetime

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "hypothesis_id", require_identifier(self.hypothesis_id, "hypothesis_id"))
        set_(
            self,
            "hypothesis_fingerprint",
            require_identifier(self.hypothesis_fingerprint, "hypothesis_fingerprint"),
        )
        if isinstance(self.hypothesis_version, bool) or not isinstance(
            self.hypothesis_version, int
        ):
            raise IntentError(
                f"hypothesis_version must be an int, got {type(self.hypothesis_version).__name__}"
            )
        if self.hypothesis_version < 1:
            raise IntentError(f"hypothesis_version must be >= 1, got {self.hypothesis_version}")
        set_(
            self,
            "observation_timestamp",
            require_aware_timestamp(self.observation_timestamp, "observation_timestamp"),
        )


@dataclass(frozen=True)
class PaperIntent:
    """Base for the explicit paper intents. Not instantiated directly."""

    intent_id: str
    intent_created_at: datetime

    def __post_init__(self) -> None:
        if type(self) is PaperIntent:
            raise IntentError(
                "PaperIntent is abstract; construct an OpenLongIntent or a CloseIntent"
            )
        set_ = object.__setattr__
        set_(self, "intent_id", require_identifier(self.intent_id, "intent_id"))
        set_(
            self,
            "intent_created_at",
            require_aware_timestamp(self.intent_created_at, "intent_created_at"),
        )

    @property
    def action(self) -> PaperAction:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class OpenLongIntent(PaperIntent):
    """A human's explicit intent to record a hypothetical long paper position.

    ``position_id`` is caller supplied so the resulting position is
    deterministically identified and a retry cannot silently create a second
    one.
    """

    position_id: str = ""
    symbol: str = ""
    notional: Decimal = Decimal(0)
    research_provenance: ResearchProvenance | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        set_ = object.__setattr__
        set_(self, "position_id", require_identifier(self.position_id, "position_id"))
        set_(self, "symbol", require_symbol(self.symbol))
        set_(self, "notional", require_notional(self.notional))
        if self.research_provenance is not None and not isinstance(
            self.research_provenance, ResearchProvenance
        ):
            raise IntentError(
                "research_provenance must be a ResearchProvenance or None, got "
                f"{type(self.research_provenance).__name__}"
            )

    @property
    def action(self) -> PaperAction:
        return PaperAction.OPEN_LONG


@dataclass(frozen=True)
class CloseIntent(PaperIntent):
    """A human's explicit intent to close an existing paper position.

    Carries no ``symbol`` and no ``notional``: the targeted
    :class:`~src.portfolio.position.PaperPosition` remains authoritative for
    both, so a close cannot assert a size or symbol that disagrees with what
    is actually open.
    """

    target_position_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "target_position_id",
            require_identifier(self.target_position_id, "target_position_id"),
        )

    @property
    def action(self) -> PaperAction:
        return PaperAction.CLOSE


__all__ = [
    "PaperAction",
    "PaperIntent",
    "OpenLongIntent",
    "CloseIntent",
    "ResearchProvenance",
    "IntentError",
    "require_identifier",
    "require_symbol",
    "require_notional",
    "require_aware_timestamp",
]
