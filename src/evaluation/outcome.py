"""Outcome specification and the immutable evaluated record.

Phase 3 answered *"what did a hypothesis classify at each evidence point?"*.
This layer answers a strictly separate question:

    "Given a research observation, what happened AFTERWARDS, under a precisely
     defined outcome contract?"

It does **not** answer "would this have made money". There is no simulated
position, no cost, no trade and no equity curve anywhere in Phase 4 -- a
forward return is a property of the market, not of a strategy.

The timing problem this exists to solve
---------------------------------------
``MarketBar.timestamp`` is the bar's **open** time (a Phase 1 invariant).  A
research observation at bar ``i`` is derived from bar ``i``'s *completed*
OHLCV, so it could not have been known at bar ``i``'s open.  Using bar ``i``'s
open as a reference price would place the reference *before* the information
that produced the observation existed -- look-ahead bias that looks perfectly
reasonable in a spreadsheet.

Hence the reference is the **open of bar i+1**. See
``docs/adr/0002-outcome-evaluation-conventions.md``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ResearchState


class OutcomeError(ValueError):
    """Raised when an outcome specification or evaluation is malformed."""


class OutcomeType(str, Enum):
    """What is being measured after the observation."""

    #: ``future_price / reference_price - 1``. Arithmetic, not logarithmic,
    #: not annualised, and expressed as a fraction (0.05, never 5).
    FORWARD_RETURN = "forward_return"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ReferenceConvention(str, Enum):
    """Which price starts the measurement.

    ``NEXT_BAR_OPEN`` is an **analytical convention**, not a claim that a real
    order could fill exactly there. OHLC bars carry no order book, no spread,
    no queue position, no latency and no partial fills.
    """

    NEXT_BAR_OPEN = "next_bar_open"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class PriceField(str, Enum):
    """Which price of a bar is read."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OutcomeStatus(str, Enum):
    """Why an outcome does or does not have a value.

    Every supplied observation produces a record with one of these. Nothing is
    silently dropped: an observation that cannot be evaluated is *evidence
    about the sample*, and removing it is how end-of-sample survivorship
    creeps into a study.
    """

    #: A finite forward return was computed.
    EVALUATED = "evaluated"

    #: The observation is the final bar of the series, so bar ``i+1`` -- the
    #: reference bar -- does not exist.
    NO_REFERENCE_BAR = "no_reference_bar"

    #: The reference bar exists but the full requested horizon does not.
    INSUFFICIENT_FUTURE_DATA = "insufficient_future_data"

    #: The observation carried no substantive classification
    #: (``ResearchState.INSUFFICIENT_DATA``), so there is nothing to evaluate.
    #: It is still recorded, so total accounting stays honest.
    INELIGIBLE_OBSERVATION = "ineligible_observation"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def _canonical(value: object) -> str:
    """Render a specification value deterministically and type-distinguishably.

    Follows the Phase 3 identity philosophy (``src/strategies/spec.py``):
    a canonical human-readable string, hashed with SHA-256. Python's built-in
    ``hash()`` is randomised per process and is never used for identity.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Enum):
        return f"{type(value).__name__}:{value.value}"
    if isinstance(value, str):
        return repr(value)
    if value is None:
        return "none"
    raise OutcomeError(f"unsupported specification value {value!r}")


@dataclass(frozen=True)
class OutcomeSpec:
    """An immutable, fingerprinted definition of "what happened afterwards".

    Horizon semantics -- stated exactly, because off-by-one here silently
    changes every number downstream::

        observation_index = i
        reference_index   = i + 1
        future_index      = reference_index + horizon_bars - 1

    **The reference bar counts as bar one of the horizon.** So
    ``horizon_bars=1`` is a one-bar outcome beginning at the next bar's open
    and ending at that same bar's close; ``horizon_bars=5`` is a five-bar
    outcome beginning at the next bar open and ending at the close of the
    fifth bar, counting the reference bar as bar one.

    Horizons are counted in **bars of the supplied series**, never translated
    into calendar days: this system has no exchange calendar, so "five bars"
    is the only statement it can make honestly.
    """

    outcome_type: OutcomeType = OutcomeType.FORWARD_RETURN
    horizon_bars: int = 1
    reference: ReferenceConvention = ReferenceConvention.NEXT_BAR_OPEN
    future_field: PriceField = PriceField.CLOSE
    required_basis: PriceBasis = PriceBasis.RAW

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "outcome_type", OutcomeType(self.outcome_type))
        set_(self, "reference", ReferenceConvention(self.reference))
        set_(self, "future_field", PriceField(self.future_field))
        set_(self, "required_basis", PriceBasis(self.required_basis))

        if isinstance(self.horizon_bars, bool) or not isinstance(self.horizon_bars, int):
            raise OutcomeError(
                f"horizon_bars must be an int, got {type(self.horizon_bars).__name__}"
            )
        if self.horizon_bars < 1:
            raise OutcomeError(
                f"horizon_bars must be >= 1, got {self.horizon_bars}; a horizon of 0 "
                "would end before the reference bar it starts at"
            )

    @property
    def canonical_form(self) -> str:
        """The exact string the fingerprint is taken over. Human-readable so
        two disagreeing runs can be diffed rather than compared as hashes."""
        parts = (
            ("type", self.outcome_type),
            ("horizon_bars", self.horizon_bars),
            ("reference", self.reference),
            ("future_field", self.future_field),
            ("basis", self.required_basis),
        )
        return "|".join(f"{name}={_canonical(value)}" for name, value in parts)

    @property
    def fingerprint(self) -> str:
        """Deterministic 16-hex digest, stable across processes and machines."""
        return hashlib.sha256(self.canonical_form.encode("utf-8")).hexdigest()[:16]

    @property
    def label(self) -> str:
        return f"{self.outcome_type.value}(h={self.horizon_bars})#{self.fingerprint}"

    def future_offset(self) -> int:
        """Bars from the reference bar to the future bar. ``horizon_bars - 1``."""
        return self.horizon_bars - 1

    def describe(self) -> str:
        return (
            f"{self.outcome_type.value}: reference={self.reference.value}, "
            f"future={self.future_field.value} of bar {self.horizon_bars} counting the "
            f"reference bar as bar 1, basis={self.required_basis.value}"
        )


@dataclass(frozen=True)
class EvaluatedOutcome:
    """One observation's outcome. Immutable and self-describing.

    Carries enough provenance to reconstruct the evaluation without consulting
    any mutable external state: which hypothesis (id, version, fingerprint)
    produced the observation, what it classified, which bars were used, and
    under which outcome specification.

    Trust boundary
    --------------
    Provenance here is **preserved, not authenticated**. Evaluation validates
    the *structure* of an observation -- symbol, interval, basis and that its
    timestamp is a real bar -- but it does not re-run the hypothesis, so it
    cannot verify that the recorded fingerprint corresponds to a real
    hypothesis or that the state is one that hypothesis would actually have
    produced. A hand-built observation is evaluated and its claimed identity
    is copied verbatim.

    That is deliberate: Phase 3 production and Phase 4 evaluation are
    separated on purpose, and re-deriving the observation would defeat the
    separation. It means these fields answer *"what does this record claim it
    came from?"* and not *"is that claim true?"*.
    """

    # -- hypothesis provenance
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str

    # -- observation
    symbol: str
    interval: Interval
    basis: PriceBasis
    observation_timestamp: datetime
    observation_state: ResearchState

    # -- outcome specification
    spec_fingerprint: str
    horizon_bars: int

    # -- result
    status: OutcomeStatus
    reference_timestamp: datetime | None = None
    future_timestamp: datetime | None = None
    reference_price: float | None = None
    future_price: float | None = None
    outcome_value: float | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "observation_state", ResearchState(self.observation_state))
        set_(self, "status", OutcomeStatus(self.status))

        if self.status is OutcomeStatus.EVALUATED:
            missing = [
                name
                for name in (
                    "reference_timestamp", "future_timestamp",
                    "reference_price", "future_price", "outcome_value",
                )
                if getattr(self, name) is None
            ]
            if missing:
                raise OutcomeError(
                    f"an EVALUATED outcome must carry {missing}; a record claiming to be "
                    "evaluated with missing values is not auditable"
                )
            if not math.isfinite(float(self.outcome_value)):
                raise OutcomeError(
                    f"an EVALUATED outcome must be a finite number, got "
                    f"{self.outcome_value!r}"
                )
        else:
            if self.outcome_value is not None:
                raise OutcomeError(
                    f"status {self.status.value!r} must not carry an outcome value; "
                    "an unavailable outcome is not a zero result"
                )
            # A record must not describe bars its own status says were never
            # reached. "No reference bar" carrying a reference price, or
            # "insufficient future data" carrying a future price, is
            # self-contradictory and would mislead anyone auditing the record
            # later -- exactly what this type exists to prevent.
            forbidden = {
                OutcomeStatus.NO_REFERENCE_BAR: (
                    "reference_timestamp", "reference_price",
                    "future_timestamp", "future_price",
                ),
                OutcomeStatus.INELIGIBLE_OBSERVATION: (
                    "reference_timestamp", "reference_price",
                    "future_timestamp", "future_price",
                ),
                # An insufficient-future record legitimately keeps the
                # reference bar it did find; it must not claim a future one.
                OutcomeStatus.INSUFFICIENT_FUTURE_DATA: (
                    "future_timestamp", "future_price",
                ),
            }[self.status]
            populated = [name for name in forbidden if getattr(self, name) is not None]
            if populated:
                raise OutcomeError(
                    f"status {self.status.value!r} must not carry {populated}; the record "
                    "would describe bars its own status says were never reached"
                )

    @property
    def is_evaluated(self) -> bool:
        return self.status is OutcomeStatus.EVALUATED

    @property
    def is_directional(self) -> bool:
        return self.observation_state.is_directional

    @property
    def label(self) -> str:
        return f"{self.hypothesis_id}@v{self.hypothesis_version}#{self.hypothesis_fingerprint}"

    def describe(self) -> str:
        value = "n/a" if self.outcome_value is None else f"{self.outcome_value:+.6f}"
        return (
            f"{self.label} {self.symbol} {self.interval.value} [{self.basis.value}] "
            f"{self.observation_timestamp.isoformat()} {self.observation_state.value} "
            f"-> {self.status.value} {value}"
        )


__all__ = [
    "OutcomeSpec",
    "EvaluatedOutcome",
    "OutcomeStatus",
    "OutcomeType",
    "ReferenceConvention",
    "PriceField",
    "OutcomeError",
]
