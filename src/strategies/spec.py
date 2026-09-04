"""Canonical identity for features and research hypotheses.

Two identity problems are solved here, both of which are silent-corruption
risks if left to convention.

**Feature identity.**  A :class:`~src.features.base.FeatureSeries` carries a
``name`` and a ``params`` mapping, but nothing canonical to compare or record.
``"rsi"`` is not an identity: ``RSI(14)`` and ``RSI(7)`` are different
evidence, and a hypothesis that says it needs "rsi" would accept either.
:class:`FeatureSpec` gives every parameterisation one deterministic key.

**Hypothesis identity.**  A research record must be able to distinguish
``momentum_context v1`` from ``v2`` forever.  It must also distinguish a v1
whose RSI period was quietly changed from 14 to 7 -- otherwise old results are
silently redefined by new code.  :class:`HypothesisSpec` therefore folds the
required feature specifications into a deterministic
:attr:`~HypothesisSpec.fingerprint`.

Determinism note
----------------
Fingerprints use SHA-256 over a canonical string.  Python's built-in ``hash()``
is randomised per process (PYTHONHASHSEED) and would produce a different
"identity" on every run and every machine -- useless for a persistent record.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.data.series import PriceBasis
from src.features.base import FeatureSeries


class SpecError(ValueError):
    """Raised when a specification is malformed."""


def _canonical_value(value: Any) -> str:
    """Render a parameter value deterministically.

    Only simple, exactly-representable types are allowed. A float parameter
    renders via ``repr`` (shortest round-trip); a nested structure would make
    the canonical form ambiguous and is rejected rather than guessed at.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, PriceBasis):
        return f"basis:{value.value}"
    if isinstance(value, str):
        # Quoted (and escaped) so a string can never render identically to a
        # value of another type. Without this, ``True`` and ``"true"`` both
        # rendered as ``true`` and produced the same canonical key while being
        # different specifications.
        return repr(value)
    raise SpecError(
        f"parameter value {value!r} of type {type(value).__name__} is not a supported "
        "specification value; use int, float, bool, str or PriceBasis so the "
        "canonical key stays unambiguous"
    )


@dataclass(frozen=True)
class FeatureSpec:
    """Canonical identity of one parameterised feature.

    ``FeatureSpec("rsi", {"period": 14, "field": "close"})`` has the key
    ``rsi(field=close,period=14)``. Parameters are sorted, so key equality does
    not depend on the order they were written in.
    """

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        name = str(self.name).strip()
        if not name:
            raise SpecError("feature name must not be empty")
        set_(self, "name", name)
        # Stored as a sorted tuple of pairs: hashable, ordered, and therefore
        # usable as a dict key and comparable by value.
        set_(self, "params", tuple(sorted((str(k), v) for k, v in dict(self.params).items())))

    @property
    def key(self) -> str:
        """Deterministic canonical identity, stable across processes."""
        rendered = ",".join(f"{name}={_canonical_value(value)}" for name, value in self.params)
        return f"{self.name}({rendered})"

    def as_dict(self) -> dict[str, Any]:
        return {name: value for name, value in self.params}

    def matches(self, feature: FeatureSeries) -> bool:
        """``True`` if ``feature`` is exactly this specification.

        Compares the name *and* every parameter. A feature computed with a
        different period is a different piece of evidence, not a near-enough
        substitute.
        """
        if feature.name != self.name:
            return False
        return dict(self.params) == dict(feature.params)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.key


@dataclass(frozen=True)
class HypothesisSpec:
    """Immutable identity of one research hypothesis.

    Attributes
    ----------
    hypothesis_id:
        Stable slug, e.g. ``"trend_alignment"``. Never reused for a different
        research idea.
    version:
        Integer, incremented whenever the classification logic changes.
        ``v1`` and ``v2`` are different hypotheses and must remain
        distinguishable in any historical record.
    name:
        Human-readable description.
    required_features:
        The exact evidence this hypothesis consumes.
    required_basis:
        The price basis the evidence must be on, or ``None`` when the
        hypothesis is basis-agnostic. See ``docs/research_framework.md``.
    lookback:
        How many bars of history before the classified bar the hypothesis
        reads. ``0`` means point-in-time. It participates in identity because
        it changes what the hypothesis is: a rule reading one prior bar and
        the same rule reading three are different research definitions, and a
        silent change from 1 to 3 must not masquerade as the original.
    parameters:
        Every other value the classification logic depends on -- thresholds,
        dead-bands, bands. These participate in identity for exactly the same
        reason the feature parameters do: a hypothesis whose RSI band moves
        from 55 to 90 classifies differently and is a different research
        definition, so it must not keep the original fingerprint.
    """

    hypothesis_id: str
    version: int
    name: str
    required_features: tuple[FeatureSpec, ...]
    required_basis: PriceBasis | None = None
    lookback: int = 0
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        hypothesis_id = str(self.hypothesis_id).strip()
        if not hypothesis_id:
            raise SpecError("hypothesis_id must not be empty")
        set_(self, "hypothesis_id", hypothesis_id)

        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise SpecError(f"version must be an int, got {type(self.version).__name__}")
        if self.version < 1:
            raise SpecError(f"version must be >= 1, got {self.version}")

        if not str(self.name).strip():
            raise SpecError("hypothesis name must not be empty")
        set_(self, "name", str(self.name).strip())

        features = tuple(self.required_features)
        if not features:
            raise SpecError(
                f"{hypothesis_id}: a hypothesis must declare the features it requires; "
                "one that declares none cannot have its evidence verified"
            )
        for spec in features:
            if not isinstance(spec, FeatureSpec):
                raise SpecError(f"required_features must contain FeatureSpec, got {spec!r}")
        keys = [spec.key for spec in features]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise SpecError(f"{hypothesis_id}: duplicate required features {sorted(duplicates)}")
        set_(self, "required_features", features)

        if self.required_basis is not None:
            set_(self, "required_basis", PriceBasis(self.required_basis))

        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int):
            raise SpecError(f"lookback must be an int, got {type(self.lookback).__name__}")
        if self.lookback < 0:
            raise SpecError(f"lookback must be >= 0, got {self.lookback}")

        # Sorted tuple of pairs: hashable, ordered, comparable by value.
        set_(self, "parameters", tuple(sorted(
            (str(name), value) for name, value in dict(self.parameters).items()
        )))

    @property
    def canonical_form(self) -> str:
        """The exact string the fingerprint is taken over.

        Human-readable on purpose: when two runs disagree, you can diff this
        rather than two opaque hashes.
        """
        features = ";".join(sorted(spec.key for spec in self.required_features))
        basis = self.required_basis.value if self.required_basis else "any"
        parameters = ",".join(
            f"{name}={_canonical_value(value)}" for name, value in self.parameters
        )
        return (
            f"{self.hypothesis_id}|v{self.version}|basis={basis}"
            f"|lookback={self.lookback}|params={parameters}|features={features}"
        )

    @property
    def fingerprint(self) -> str:
        """Deterministic 16-hex-character digest of :attr:`canonical_form`.

        Stable across processes, machines and Python versions. Two hypotheses
        sharing an id and version but differing in *any* required parameter
        have different fingerprints, so a silently re-parameterised ``v1``
        cannot present itself as the original.
        """
        digest = hashlib.sha256(self.canonical_form.encode("utf-8")).hexdigest()
        return digest[:16]

    @property
    def label(self) -> str:
        """``id@v1#fingerprint`` -- what belongs in a research record."""
        return f"{self.hypothesis_id}@v{self.version}#{self.fingerprint}"

    def parameter(self, name: str) -> Any:
        """Look up a declared configuration value."""
        for declared, value in self.parameters:
            if declared == name:
                return value
        known = ", ".join(name for name, _ in self.parameters) or "(none declared)"
        raise SpecError(
            f"{self.hypothesis_id}: parameter {name!r} is not declared; declared: {known}"
        )

    def feature_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.required_features)


__all__ = ["FeatureSpec", "HypothesisSpec", "SpecError"]
