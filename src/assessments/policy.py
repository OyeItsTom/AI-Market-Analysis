"""The rule that combines research observations, and its deterministic identity.

An :class:`AssessmentPolicy` names an exact ensemble of hypotheses, how much
real evidence it needs, and *which* aggregation semantics apply.  It combines
nothing itself -- :func:`~src.assessments.aggregate.assess` does that -- but an
assessment is only interpretable alongside the policy that produced it, so the
policy carries a fingerprint.

Why the aggregation rule is part of the identity
------------------------------------------------
:class:`AssessmentAggregationRule` has exactly one member and is **not** a menu.
It exists so that material aggregation semantics cannot change while the policy
fingerprint stays the same.  Without it, ``BULLISH + NEUTRAL + NEUTRAL`` could
yield ``BULLISH`` under one release and ``NEUTRAL`` under the next, with both
assessments claiming the same policy identity -- and an archived record would
no longer say what produced it.

This is the same job :attr:`~src.strategies.spec.HypothesisSpec.version` does
for a hypothesis implementation: it does not let a caller *select* behaviour,
it records which behaviour applied.  A field whose purpose is versioned
auditability is complete at one member; a field whose purpose is behavioural
configuration would not be.  There is deliberately no registry, no plugin
mechanism, no aggregator hierarchy and no dispatch -- with one member there is
nothing to dispatch on, and a branch would be the first step towards the
configurability this design excludes.

**Never redefine an existing rule identity.**  Materially different semantics
require a new member (``directional_presence_v2``), which necessarily produces
a new fingerprint.

Canonical encoding
------------------
Identity strings are caller-supplied and may contain any character, so the
canonical form is **canonical JSON**, not delimiter-joined text.  Concatenating
``id@vN#fingerprint`` with separators would let a ``hypothesis_id`` containing
``@`` or ``#`` render identically to a different ensemble -- a fingerprint
collision between two genuinely different policies.  JSON quotes and escapes
every string, so the encoding is unambiguous for any input.  See
:func:`canonical_bytes` for the pinned serialization contract.

Determinism note
----------------
Fingerprints use SHA-256 over those bytes.  Python's built-in ``hash()`` is
randomised per process (PYTHONHASHSEED) and would produce a different identity
on every run -- useless for a record meant to outlive the process.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence


class PolicyError(ValueError):
    """Raised when an assessment policy is structurally malformed."""


class AssessmentAggregationRule(str, Enum):
    """Versioned identity of the state-reduction function. Not a menu.

    Exactly one member exists. See the module docstring for why that is
    correct rather than a smell, and why this is identity rather than
    configuration.
    """

    DIRECTIONAL_PRESENCE_V1 = "directional_presence_v1"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def _require_identity_text(value: object, label: str) -> str:
    """A non-empty, non-blank ``str``.

    Deliberately permits ``|``, ``@``, ``#``, quotes, backslashes and Unicode:
    banning delimiters to protect a fragile encoding would push an encoding
    problem onto callers. The canonical form is JSON instead, which is
    unambiguous for any string. Only genuinely absent identity is refused.
    """
    if not isinstance(value, str):
        raise PolicyError(f"{label} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise PolicyError(f"{label} must be a non-empty, non-blank str")
    return value


def _require_count(value: object, label: str, *, minimum: int) -> int:
    """A genuine ``int`` at or above ``minimum``.

    ``bool`` is rejected before the ``int`` check because ``isinstance(True,
    int)`` is ``True``: ``minimum_sufficient_observations=True`` would silently
    become 1.
    """
    if isinstance(value, bool):
        raise PolicyError(f"{label} must be an int, got bool")
    if not isinstance(value, int):
        raise PolicyError(f"{label} must be an int, got {type(value).__name__}")
    if value < minimum:
        raise PolicyError(f"{label} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class HypothesisIdentity:
    """Which hypothesis, at which version, with which implementation.

    All three parts are required. ``hypothesis_id`` alone is not an identity:
    a ``v1`` whose parameters were quietly changed has a different
    :attr:`~src.strategies.spec.HypothesisSpec.fingerprint`, and pinning only
    the id would let it present itself as the original.
    """

    hypothesis_id: str
    version: int
    fingerprint: str

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "hypothesis_id", _require_identity_text(self.hypothesis_id, "hypothesis_id"))
        set_(self, "fingerprint", _require_identity_text(self.fingerprint, "fingerprint"))
        set_(self, "version", _require_count(self.version, "version", minimum=1))

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.hypothesis_id, self.version, self.fingerprint)

    @property
    def label(self) -> str:
        """``id@v1#fingerprint`` -- for humans and messages, never for hashing."""
        return f"{self.hypothesis_id}@v{self.version}#{self.fingerprint}"

    def as_canonical(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
            "fingerprint": self.fingerprint,
        }


def canonical_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to deterministic bytes.

    The exact contract, pinned so that a future edit cannot silently change
    every fingerprint in the project:

    * ``separators=(",", ":")`` -- no insignificant whitespace
    * ``ensure_ascii=True`` -- non-ASCII escapes to ``\\uXXXX``, so the bytes
      do not depend on the platform's default encoding
    * ``sort_keys=True`` -- mapping key order is fixed by content, not by
      insertion order
    * ``allow_nan=False`` -- ``NaN``/``Infinity`` are not valid JSON and would
      make the form non-portable; no float reaches this encoder anyway
    * UTF-8 -- fixed explicitly rather than inherited from the locale

    Lists preserve order, so any sequence that must be order-independent is
    sorted by the caller *before* it gets here.
    """
    return json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class AssessmentPolicy:
    """An exact hypothesis ensemble, an evidence minimum, and the rule identity.

    Every field is material and required; there is deliberately no default. A
    policy that did not have to name its aggregation semantics would let a
    caller record an assessment without ever deciding what it means.

    The ensemble is **exact** (not a minimum subset): every listed hypothesis
    must appear exactly once in the observations, and nothing else may
    participate. Policy identity therefore completely determines which
    hypotheses spoke, which is what makes an archived assessment reproducible.
    """

    hypotheses: tuple[HypothesisIdentity, ...]
    minimum_sufficient_observations: int
    aggregation_rule: AssessmentAggregationRule

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        try:
            rule = AssessmentAggregationRule(self.aggregation_rule)
        except ValueError:
            raise PolicyError(
                f"unknown aggregation_rule {self.aggregation_rule!r}; the only supported "
                f"rule is {AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1.value!r}"
            ) from None
        except TypeError:
            raise PolicyError(
                f"aggregation_rule must be an AssessmentAggregationRule, got "
                f"{type(self.aggregation_rule).__name__}"
            ) from None
        set_(self, "aggregation_rule", rule)

        if isinstance(self.hypotheses, (str, bytes)) or not isinstance(
            self.hypotheses, Sequence
        ):
            raise PolicyError(
                f"hypotheses must be a sequence of HypothesisIdentity, got "
                f"{type(self.hypotheses).__name__}"
            )
        ensemble = tuple(self.hypotheses)
        for entry in ensemble:
            if not isinstance(entry, HypothesisIdentity):
                raise PolicyError(
                    f"every hypothesis must be a HypothesisIdentity, got "
                    f"{type(entry).__name__}"
                )
        if not ensemble:
            raise PolicyError(
                "hypotheses must not be empty; a policy with no ensemble could never "
                "assess anything"
            )

        seen: set[tuple[str, int, str]] = set()
        for entry in ensemble:
            if entry.sort_key in seen:
                raise PolicyError(
                    f"duplicate hypothesis identity in the ensemble: {entry.label}"
                )
            seen.add(entry.sort_key)
        set_(self, "hypotheses", ensemble)

        minimum = _require_count(
            self.minimum_sufficient_observations,
            "minimum_sufficient_observations",
            minimum=1,
        )
        if minimum > len(ensemble):
            raise PolicyError(
                f"minimum_sufficient_observations {minimum} exceeds the ensemble size "
                f"{len(ensemble)}; that policy could never produce a sufficient "
                "assessment"
            )
        set_(self, "minimum_sufficient_observations", minimum)

    @property
    def sorted_hypotheses(self) -> tuple[HypothesisIdentity, ...]:
        """The ensemble in canonical order, so caller order cannot leak into identity."""
        return tuple(sorted(self.hypotheses, key=lambda entry: entry.sort_key))

    @property
    def canonical_form(self) -> str:
        """The exact string the fingerprint is taken over.

        JSON rather than delimiter-joined text: identity strings are
        caller-supplied and may contain any character (see the module
        docstring).
        """
        return canonical_bytes(
            {
                "aggregation_rule": self.aggregation_rule.value,
                "hypotheses": [entry.as_canonical() for entry in self.sorted_hypotheses],
                "minimum_sufficient_observations": self.minimum_sufficient_observations,
            }
        ).decode("ascii")

    @property
    def fingerprint(self) -> str:
        """Deterministic 16-hex-character digest of :attr:`canonical_form`.

        Stable across processes and machines. Changing any hypothesis id,
        version or fingerprint, the minimum, or the aggregation rule changes
        this value; permuting the same ensemble does not.

        It identifies a policy; it does not let you reconstruct one. Like the
        provenance in Phase 5, identity is **preserved, not authenticated**.
        """
        digest = hashlib.sha256(self.canonical_form.encode("utf-8")).hexdigest()
        return digest[:16]

    @property
    def label(self) -> str:
        return (
            f"{self.aggregation_rule.value}#{self.fingerprint} "
            f"({len(self.hypotheses)} hypotheses, min {self.minimum_sufficient_observations})"
        )


__all__ = [
    "AssessmentAggregationRule",
    "HypothesisIdentity",
    "AssessmentPolicy",
    "PolicyError",
    "canonical_bytes",
]
