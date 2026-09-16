"""Deterministic identity for tracked artifacts, outcomes and source bars.

Three keys, one construction: SHA-256 over canonical JSON bytes, rendered as
the **full 64-hex digest**.

Why full-length
---------------
This project truncates *specification* fingerprints to 16 hex characters
(hypothesis, policy, outcome spec): they are compared by people, appear in
labels, and name a definition that is also stored in code. A ledger key is
different -- it is compared by machine, for the life of a durable store,
against every other key ever written, and nothing else reconstructs it.
Reasoning and scanner fingerprints already use the full digest for the same
reason; ledger identity follows them, not the display convention.

Why canonical JSON
------------------
Delimiter-joined text (``id@vN#fp``) lets a ``hypothesis_id`` containing
``@`` or ``#`` render identically to a different identity. The assessment
layer solved this with :func:`~src.assessments.policy.canonical_bytes`; that
exact function is reused here rather than re-implemented, so a future change
to the project's canonical form cannot leave this package subtly different.

Every payload carries a ``scheme`` and ``scheme_version`` so that two keys
from different key schemes -- or a later revision of this one -- can never
be equal by accident.

Timestamps are rendered as UTC ISO-8601 so that identity is over the
*instant*: the same bar open expressed in another zone is the same bar.
Floats are rendered by the JSON encoder's shortest round-trip form, which is
platform-independent and exact.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Sequence

from src.assessments.policy import canonical_bytes
from src.data.models import Interval, MarketBar
from src.data.series import PriceBasis

#: Length of every ledger key produced here: the full SHA-256 hex digest.
KEY_HEX_LENGTH = 64

#: Length of a *specification* fingerprint (``OutcomeSpec.fingerprint``,
#: ``HypothesisSpec.fingerprint``, ``AssessmentPolicy.fingerprint``).
SPEC_FINGERPRINT_LENGTH = 16

_HEX_DIGITS = frozenset("0123456789abcdef")


class OutcomeTrackingError(ValueError):
    """Raised when an outcome-tracking record or identity is malformed."""


# -- shared validation -------------------------------------------------------------


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeTrackingError(f"{label} must be a non-empty, non-blank str, got {value!r}")
    return value


def require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OutcomeTrackingError(f"{label} must be an int, got {type(value).__name__}")
    if value < 1:
        raise OutcomeTrackingError(f"{label} must be >= 1, got {value}")
    return value


def require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise OutcomeTrackingError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OutcomeTrackingError(
            f"{label} must be timezone-aware; naive timestamps are ambiguous"
        )
    return value


def require_hex(value: object, label: str, length: int) -> str:
    """Exactly ``length`` lowercase hex characters -- the shape a digest has."""
    if not isinstance(value, str):
        raise OutcomeTrackingError(f"{label} must be a str, got {type(value).__name__}")
    if len(value) != length or not set(value) <= _HEX_DIGITS:
        raise OutcomeTrackingError(
            f"{label} must be {length} lowercase hex characters, got {value!r}"
        )
    return value


def require_key(value: object, label: str) -> str:
    return require_hex(value, label, KEY_HEX_LENGTH)


def require_spec_fingerprint(value: object, label: str) -> str:
    return require_hex(value, label, SPEC_FINGERPRINT_LENGTH)


# -- canonical rendering -----------------------------------------------------------------


def canonical_timestamp(value: datetime, label: str = "timestamp") -> str:
    """UTC ISO-8601 with offset. Identity is over the instant, not the zone."""
    return require_aware(value, label).astimezone(timezone.utc).isoformat()


def _canonical_float(value: float, label: str) -> float:
    """A finite float, with ``-0.0`` folded to ``0.0`` so the sign of zero
    cannot make two equal bars fingerprint differently."""
    number = float(value)
    if not math.isfinite(number):  # pragma: no cover - MarketBar already refuses
        raise OutcomeTrackingError(f"{label} must be finite, got {value!r}")
    return number + 0.0



def digest(payload: Any) -> str:
    """Full SHA-256 hex digest of the canonical JSON form of ``payload``."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# -- artifact identity ---------------------------------------------------------------------


def _market_point(
    symbol: object, interval: object, basis: object, timestamp: object
) -> dict[str, str]:
    try:
        interval_value = Interval.parse(interval).value
    except (ValueError, TypeError) as exc:
        raise OutcomeTrackingError(f"interval: {exc}") from None
    try:
        basis_value = PriceBasis(basis).value
    except ValueError:
        raise OutcomeTrackingError(f"unknown price basis {basis!r}") from None
    return {
        "symbol": require_text(symbol, "symbol"),
        "interval": interval_value,
        "basis": basis_value,
        "timestamp": canonical_timestamp(timestamp),
    }


def observation_artifact_key(
    *,
    symbol: str,
    interval: Interval | str,
    basis: PriceBasis | str,
    timestamp: datetime,
    hypothesis_id: str,
    hypothesis_version: int,
    hypothesis_fingerprint: str,
) -> str:
    """Identity of one hypothesis' claim about one bar.

    The producer triple ``(id, version, fingerprint)`` is inside the key, so a
    re-parameterised hypothesis is a different producer forever. The *state*
    is deliberately absent: a hypothesis makes exactly one claim per bar, and
    a second, different claim under the same key is a conflict for the ledger
    to detect, not a second artifact.
    """
    payload = {
        "scheme": "outcomes.artifact_key",
        "scheme_version": 1,
        "kind": "observation",
        **_market_point(symbol, interval, basis, timestamp),
        "hypothesis_id": require_text(hypothesis_id, "hypothesis_id"),
        "hypothesis_version": require_positive_int(hypothesis_version, "hypothesis_version"),
        "hypothesis_fingerprint": require_text(hypothesis_fingerprint, "hypothesis_fingerprint"),
    }
    return digest(payload)


def assessment_artifact_key(
    *,
    symbol: str,
    interval: Interval | str,
    basis: PriceBasis | str,
    timestamp: datetime,
    policy_fingerprint: str,
) -> str:
    """Identity of one policy's combined claim about one bar.

    The policy fingerprint already covers the ensemble (each hypothesis'
    id, version and fingerprint), the minimum and the aggregation rule.
    ``assessment_as_of`` is a clock reading and is not identity.
    """
    payload = {
        "scheme": "outcomes.artifact_key",
        "scheme_version": 1,
        "kind": "assessment",
        **_market_point(symbol, interval, basis, timestamp),
        "policy_fingerprint": require_spec_fingerprint(policy_fingerprint, "policy_fingerprint"),
    }
    return digest(payload)


# -- outcome identity ----------------------------------------------------------------------


def outcome_key(*, artifact_key: str, spec_fingerprint: str, evaluation_version: int) -> str:
    """Identity of one measurement of one artifact.

    Three inputs and no more. Prices, returns, timestamps and clocks are
    *results*; keying on them would let the same measurement be stored twice
    whenever a result differed, which is exactly the duplicate a ledger must
    refuse. Keying on ``evaluation_version`` means a future change to the
    measurement produces new records beside the old, never over them.
    """
    payload = {
        "scheme": "outcomes.outcome_key",
        "scheme_version": 1,
        "artifact_key": require_key(artifact_key, "artifact_key"),
        "spec_fingerprint": require_spec_fingerprint(spec_fingerprint, "spec_fingerprint"),
        "evaluation_version": require_positive_int(evaluation_version, "evaluation_version"),
    }
    return digest(payload)


# -- source-bar identity -------------------------------------------------------------------


def _bar_payload(bar: object, label: str) -> dict[str, Any]:
    if not isinstance(bar, MarketBar):
        raise OutcomeTrackingError(f"{label} must be a MarketBar, got {type(bar).__name__}")
    # ``source`` is provenance -- which provider delivered the numbers -- and
    # is tracked on the artifact. The fingerprint answers "are these the same
    # numbers for the same bar?", so it covers what the bar *is*.
    return {
        "symbol": bar.symbol,
        "interval": bar.interval.value,
        "timestamp": canonical_timestamp(bar.timestamp, f"{label}.timestamp"),
        "open": _canonical_float(bar.open, f"{label}.open"),
        "high": _canonical_float(bar.high, f"{label}.high"),
        "low": _canonical_float(bar.low, f"{label}.low"),
        "close": _canonical_float(bar.close, f"{label}.close"),
        "volume": _canonical_float(bar.volume, f"{label}.volume"),
    }


def bar_fingerprint(bar: MarketBar) -> str:
    """Fingerprint of one bar's content, so a later revision of the bar an
    artifact was derived from is detectable."""
    payload = {
        "scheme": "outcomes.bar_fingerprint",
        "scheme_version": 1,
        **_bar_payload(bar, "bar"),
    }
    return digest(payload)


def bars_fingerprint(bars: Sequence[MarketBar]) -> str:
    """Order-sensitive fingerprint of the exact bars a measurement consumed.

    Empty input is refused: a measurement read *some* bars, and a fingerprint
    of none would let a record claim provenance it does not have.
    """
    if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
        raise OutcomeTrackingError(
            f"bars must be a sequence of MarketBar, got {type(bars).__name__}"
        )
    if not bars:
        raise OutcomeTrackingError("bars must not be empty; a measurement consumed bars")
    payload = {
        "scheme": "outcomes.bars_fingerprint",
        "scheme_version": 1,
        "count": len(bars),
        "bars": [_bar_payload(bar, f"bars[{index}]") for index, bar in enumerate(bars)],
    }
    return digest(payload)


__all__ = [
    "OutcomeTrackingError",
    "KEY_HEX_LENGTH",
    "SPEC_FINGERPRINT_LENGTH",
    "observation_artifact_key",
    "assessment_artifact_key",
    "outcome_key",
    "bar_fingerprint",
    "bars_fingerprint",
    "digest",
    "canonical_timestamp",
    "require_text",
    "require_positive_int",
    "require_aware",
    "require_hex",
    "require_key",
    "require_spec_fingerprint",
]
