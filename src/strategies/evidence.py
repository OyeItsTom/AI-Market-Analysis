"""Aligned feature evidence for hypothesis evaluation.

The failure this prevents
-------------------------
A hypothesis combining RSI at timestamp T with SMA at timestamp T+1 produces a
number.  It is a wrong number, and nothing about it looks wrong.  The same goes
for combining two symbols, two intervals, or a raw series with an adjusted one.

:class:`EvidenceSet` verifies alignment **once, at construction**, so that by
the time a hypothesis sees anything, misalignment is impossible rather than
merely unlikely.

Structural problems raise.  They are never reported as
``INSUFFICIENT_DATA`` -- that state is reserved for evidence that is
legitimately not there yet (warm-up), and using it for a bug would let a
corrupted study look like a cautious one.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Iterable, Iterator, Mapping

from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.features.base import FeatureSeries

from .spec import FeatureSpec


class EvidenceError(ValueError):
    """Raised when feature evidence is structurally unusable."""


def resolve_feature_spec(spec: FeatureSpec) -> FeatureSpec:
    """Return ``spec`` with every defaulted parameter filled in.

    ``sma(period=3)`` and ``sma(period=3, field="close")`` are the same
    computation, but as written they produce different canonical keys -- and a
    computed feature always records the full parameter set, so the short form
    would never match its own result. Resolving against the feature function's
    signature gives one identity per computation.

    Only parameters that actually reach the calculation are added; ``series``
    is excluded because it is the input, not a parameter of the definition.
    """
    factory = FEATURE_FACTORIES.get(spec.name)
    if factory is None:
        known = ", ".join(sorted(FEATURE_FACTORIES))
        raise EvidenceError(f"unknown feature {spec.name!r}; known features: {known}")

    signature = inspect.signature(factory)
    declared = spec.as_dict()
    unknown = set(declared) - set(signature.parameters)
    if unknown:
        raise EvidenceError(
            f"{spec.name}: unknown parameter(s) {sorted(unknown)}; "
            f"accepted: {sorted(n for n in signature.parameters if n != 'series')}"
        )

    resolved = dict(declared)
    for name, parameter in signature.parameters.items():
        if name == "series" or parameter.default is inspect.Parameter.empty:
            continue
        resolved.setdefault(name, parameter.default)

    missing = [
        name
        for name, parameter in signature.parameters.items()
        if name != "series"
        and parameter.default is inspect.Parameter.empty
        and name not in resolved
    ]
    if missing:
        raise EvidenceError(f"{spec.name}: missing required parameter(s) {missing}")

    return FeatureSpec(spec.name, resolved)


@dataclass(frozen=True)
class EvidenceSet:
    """A group of feature series proven to describe the same bars.

    Guarantees, checked at construction:

    * one symbol, one interval, one price basis across every feature
    * identical timestamps, in identical order, across every feature
    * each feature is keyed by its canonical :class:`FeatureSpec` key
    * no duplicate specifications

    Access is by ``(spec_key, index)``. There is deliberately no way to ask for
    "the whole series" from inside a hypothesis -- see :mod:`.base`.
    """

    symbol: str
    interval: Interval
    basis: PriceBasis
    timestamps: tuple[datetime, ...]
    features: Mapping[str, FeatureSeries]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "timestamps", tuple(self.timestamps))
        set_(self, "features", MappingProxyType(dict(self.features)))

        if not self.features:
            raise EvidenceError("an evidence set must contain at least one feature")

        for key, feature in self.features.items():
            if not isinstance(feature, FeatureSeries):
                raise EvidenceError(f"{key}: expected a FeatureSeries, got {type(feature).__name__}")
            mismatches = [
                f"{label} {theirs!r} != {ours!r}"
                for label, theirs, ours in (
                    ("symbol", feature.symbol, self.symbol),
                    ("interval", feature.interval.value, self.interval.value),
                    ("basis", feature.basis.value, self.basis.value),
                )
                if theirs != ours
            ]
            if mismatches:
                raise EvidenceError(
                    f"feature {key} does not describe the same series as the rest of the "
                    f"evidence: {'; '.join(mismatches)}"
                )
            if feature.timestamps != self.timestamps:
                raise EvidenceError(
                    f"feature {key} is not aligned with the rest of the evidence "
                    f"({len(feature.timestamps)} timestamps vs {len(self.timestamps)}); "
                    "combining features from different bars silently produces wrong values"
                )

    # -- construction ----------------------------------------------------

    @classmethod
    def from_features(cls, features: Iterable[FeatureSeries]) -> "EvidenceSet":
        """Build from computed features, taking metadata from the first."""
        features = list(features)
        if not features:
            raise EvidenceError("cannot build an evidence set from no features")
        first = features[0]
        if not isinstance(first, FeatureSeries):
            raise EvidenceError(f"expected FeatureSeries, got {type(first).__name__}")

        keyed: dict[str, FeatureSeries] = {}
        for feature in features:
            if not isinstance(feature, FeatureSeries):
                raise EvidenceError(f"expected FeatureSeries, got {type(feature).__name__}")
            key = FeatureSpec(feature.name, dict(feature.params)).key
            if key in keyed:
                raise EvidenceError(f"duplicate feature {key} in evidence")
            keyed[key] = feature

        return cls(
            symbol=first.symbol,
            interval=first.interval,
            basis=first.basis,
            timestamps=first.timestamps,
            features=keyed,
        )

    # -- access ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.timestamps)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.features))

    def has(self, spec: FeatureSpec) -> bool:
        return resolve_feature_spec(spec).key in self.features

    def value(self, spec: FeatureSpec, index: int) -> float | None:
        """One evidence value. ``None`` means warm-up, i.e. not yet defined."""
        spec = resolve_feature_spec(spec)
        feature = self.features.get(spec.key)
        if feature is None:
            raise EvidenceError(
                f"required feature {spec.key} is not present in this evidence set "
                f"(available: {', '.join(self.keys())})"
            )
        return feature.values[index]

    def snapshot(self, specs: Iterable[FeatureSpec], index: int) -> dict[str, float | None]:
        """Every requested value at one index, keyed canonically.

        This is the *only* thing a hypothesis receives. It is a plain mapping
        of the current bar's evidence: no series, no bars, no neighbouring
        indices, and therefore no way to look forward.
        """
        return {
            resolve_feature_spec(spec).key: self.value(spec, index) for spec in specs
        }

    def describe(self) -> str:
        return (
            f"{self.symbol} {self.interval.value} [{self.basis.value}] "
            f"{len(self.timestamps)} bars, features: {', '.join(self.keys())}"
        )


class EvidenceWindow(Mapping):
    """Read-only, strictly causal view of evidence ending at one bar.

    Covers ``[T - lookback ... T]`` and **nothing else**.  Future evidence is
    not merely forbidden here, it is structurally absent: the window holds a
    fixed tuple of rows that were copied out before the hypothesis ran, and
    exposes no way to ask for a later one.

    Deliberately withheld, each because it is a demonstrated cheat vector:

    * **timestamps** -- so a hypothesis cannot key off the final date;
    * **dataset length** -- ``len(window)`` is the number of *features*, never
      the number of bars, so "how much data exists" is unanswerable;
    * **any positive offset** -- :meth:`past` accepts ``0..lookback`` only;
    * **negative offsets** -- rejected, so Python's negative indexing cannot be
      used to wrap around into the future.

    Behaves as a ``Mapping`` of the **current** bar's values, so a
    point-in-time hypothesis reads ``values[spec.key]`` exactly as before and
    needs no change.
    """

    __slots__ = ("_rows", "_lookback")

    def __init__(
        self, rows: Iterable[Mapping[str, float]], lookback: int
    ) -> None:
        # rows[0] is the CURRENT bar; rows[n] is n bars earlier.
        frozen = tuple(dict(row) for row in rows)
        if len(frozen) != lookback + 1:
            raise EvidenceError(
                f"a window with lookback={lookback} needs exactly {lookback + 1} rows, "
                f"got {len(frozen)}"
            )
        object.__setattr__(self, "_rows", frozen)
        object.__setattr__(self, "_lookback", lookback)

    # -- Mapping over the CURRENT bar ------------------------------------

    def __getitem__(self, key: str) -> float:
        return self._rows[0][key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._rows[0])

    def __len__(self) -> int:
        """Number of features in the current row -- never the number of bars."""
        return len(self._rows[0])

    # -- bounded history -------------------------------------------------

    @property
    def lookback(self) -> int:
        return self._lookback

    def past(self, spec: FeatureSpec, ago: int) -> float:
        """Value of ``spec`` ``ago`` bars before the bar being classified.

        ``ago=0`` is the current bar; ``ago=lookback`` is the oldest bar in
        the window. Anything outside that range raises: a negative offset
        would be an attempt to read the future, and one beyond the declared
        lookback would be reading evidence the hypothesis never declared it
        needed.
        """
        if isinstance(ago, bool) or not isinstance(ago, int):
            raise EvidenceError(f"ago must be an int, got {type(ago).__name__}")
        if ago < 0:
            raise EvidenceError(
                f"ago must not be negative (got {ago}); a negative offset would ask "
                "for evidence after the bar being classified"
            )
        if ago > self._lookback:
            raise EvidenceError(
                f"ago={ago} exceeds the declared lookback of {self._lookback}; "
                "a hypothesis may only read the history it declared"
            )
        key = resolve_feature_spec(spec).key
        row = self._rows[ago]
        if key not in row:
            raise EvidenceError(
                f"{key} is not part of this hypothesis' required evidence "
                f"(available: {', '.join(sorted(row))})"
            )
        return row[key]

    def current(self, spec: FeatureSpec) -> float:
        """Value of ``spec`` at the bar being classified."""
        return self.past(spec, 0)

    def __setitem__(self, key, value):  # pragma: no cover - Mapping is read-only
        raise TypeError("EvidenceWindow is read-only")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EvidenceWindow lookback={self._lookback} features={sorted(self._rows[0])}>"


def build_evidence(series: BarSeries, specs: Iterable[FeatureSpec]) -> EvidenceSet:
    """Compute the requested features from ``series`` and align them.

    This is the seam between the feature engine and the research layer, and it
    lives **outside** hypothesis code on purpose: a hypothesis declares what it
    needs and is handed the result, so it can neither recompute a feature with
    different parameters nor reach the bars behind it.
    """
    specs = list(specs)
    if not specs:
        raise EvidenceError("build_evidence requires at least one FeatureSpec")

    computed: list[FeatureSeries] = []
    for spec in specs:
        spec = resolve_feature_spec(spec)
        factory = FEATURE_FACTORIES[spec.name]
        try:
            computed.append(factory(series, **spec.as_dict()))
        except TypeError as exc:
            raise EvidenceError(
                f"{spec.key}: parameters do not match the {spec.name} feature: {exc}"
            ) from exc
    return EvidenceSet.from_features(computed)


def _factories() -> dict:
    """Feature name -> callable. Built once; the mapping is never mutated."""
    from src.features import (
        atr,
        average_volume,
        ema,
        log_return,
        realized_volatility,
        relative_volume,
        rsi,
        simple_return,
        sma,
    )

    return {
        "simple_return": simple_return,
        "log_return": log_return,
        "sma": sma,
        "ema": ema,
        "rsi": rsi,
        "realized_volatility": realized_volatility,
        "atr": atr,
        "average_volume": average_volume,
        "relative_volume": relative_volume,
    }


#: Read-only: the research layer resolves feature names, it does not extend them.
FEATURE_FACTORIES: Mapping[str, object] = MappingProxyType(_factories())


__all__ = [
    "EvidenceSet",
    "EvidenceWindow",
    "EvidenceError",
    "build_evidence",
    "resolve_feature_spec",
    "FEATURE_FACTORIES",
]
