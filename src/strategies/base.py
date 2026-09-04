"""The research hypothesis contract.

A hypothesis is a deterministic classifier over feature evidence.  It is not a
trading strategy, it issues no instructions, and Phase 3 measures nothing about
what happened afterwards.

Causality by construction
-------------------------
:meth:`ResearchHypothesis.evaluate` is a template method.  It validates the
evidence, then walks the bars in order calling the subclass hook
:meth:`~ResearchHypothesis._classify` with **one argument: an
:class:`~src.strategies.evidence.EvidenceWindow` covering
``[T - lookback ... T]`` and nothing else**.

A subclass therefore has no access to the bar series, to any bar after ``T``,
to the number of bars, or to the timestamps.  It cannot look forward, cannot
recompute a feature with different parameters, cannot reach a provider, and
cannot see how much data exists.  These are not rules a reviewer has to check
-- there is nothing in scope to violate them with.

The window behaves as a mapping of the **current** bar's values, so a
point-in-time hypothesis (``lookback = 0``, the default) reads
``values[spec.key]`` exactly as it always did.  History is opt-in: declare a
``lookback`` and read it with ``window.past(spec, ago)``.

What the base class enforces
----------------------------
* the evidence carries every required feature, with exactly the required
  parameters (a different RSI period is different evidence, not a substitute)
* the evidence matches the required price basis, when one is declared
* any warm-up (``None``) value **anywhere in the window** yields
  ``INSUFFICIENT_DATA`` -- the hook is not called at all, so a subclass can
  never accidentally treat a missing value as zero
* a bar too early in the dataset to fill the declared lookback also yields
  ``INSUFFICIENT_DATA``. That is a legitimate shortage of history, not a
  fault: a dataset simply starts somewhere. Structural problems still raise.
* every observation records the hypothesis identity, including its fingerprint
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from src.data.series import PriceBasis

from .evidence import EvidenceError, EvidenceSet, EvidenceWindow, resolve_feature_spec
from .research import ReasonCode, ResearchObservation, ResearchState
from .spec import FeatureSpec, HypothesisSpec, SpecError


class HypothesisError(ValueError):
    """Raised when a hypothesis cannot be evaluated against the given evidence."""


class ResearchHypothesis(ABC):
    """Base class for deterministic research hypotheses.

    Subclasses declare :attr:`hypothesis_id`, :attr:`version`,
    :attr:`display_name`, :attr:`required_features` and optionally
    :attr:`required_basis`, then implement :meth:`_classify`.
    """

    #: Stable slug. Never reused for a different research idea.
    hypothesis_id: str = ""

    #: Incremented whenever the classification logic changes. v1 and v2 are
    #: different hypotheses and must stay distinguishable forever.
    version: int = 0

    display_name: str = ""

    #: Exactly the evidence this hypothesis consumes. Short-form specs are
    #: resolved to their full parameter set, so identity is unambiguous.
    required_features: tuple[FeatureSpec, ...] = ()

    #: Price basis the evidence must be on, or None when basis-agnostic.
    required_basis: PriceBasis | None = None

    #: Bars of history before the classified bar that this hypothesis reads.
    #: 0 (the default) is point-in-time. Participates in identity.
    lookback: int = 0

    #: Every other value the classification logic depends on -- thresholds,
    #: dead-bands, bands. Read with :meth:`parameter`. These participate in
    #: identity, so changing one changes the fingerprint.
    parameters: Mapping[str, Any] = MappingProxyType({})

    def __init__(self) -> None:
        self._check_configuration_is_declared()
        resolved = tuple(resolve_feature_spec(spec) for spec in self.required_features)
        # Built once, in __init__, and never rebuilt: an instantiated
        # hypothesis has a fixed identity for its whole life.
        self._spec = HypothesisSpec(
            hypothesis_id=self.hypothesis_id,
            version=self.version,
            name=self.display_name,
            required_features=resolved,
            required_basis=self.required_basis,
            lookback=self.lookback,
            parameters=dict(self.parameters),
        )

    #: Attributes the framework itself defines; never configuration.
    _FRAMEWORK_ATTRIBUTES = frozenset(
        {
            "hypothesis_id", "version", "display_name", "required_features",
            "required_basis", "lookback", "parameters", "spec", "fingerprint",
            "label", "evaluate", "evaluate_at", "parameter",
        }
    )

    @classmethod
    def _check_configuration_is_declared(cls) -> None:
        """Refuse to build a hypothesis whose configuration is not in its identity.

        Any public class attribute that is not a framework field, not callable
        and not a :class:`FeatureSpec` is configuration the classification
        logic can read. If it is not declared in :attr:`parameters` it does not
        reach the fingerprint, and a hypothesis could change how it classifies
        while keeping the identity of the original -- exactly the masquerade
        the fingerprint exists to prevent.

        Checked at construction rather than trusted to review, because the
        failure is silent: nothing about a stale fingerprint looks wrong.
        """
        declared = set(dict(cls.parameters))
        undeclared = []
        for name in dir(cls):
            if name.startswith("_") or name in cls._FRAMEWORK_ATTRIBUTES:
                continue
            value = getattr(cls, name, None)
            if callable(value) or isinstance(value, (FeatureSpec, property)):
                continue
            if name not in declared:
                undeclared.append(name)
        if undeclared:
            raise SpecError(
                f"{cls.__name__}: configuration {sorted(undeclared)} is not declared in "
                "`parameters`, so it would not reach the hypothesis fingerprint. Two "
                "hypotheses differing only in that value would share one research "
                "identity while classifying differently. Declare it in `parameters` "
                "and read it with self.parameter(name)."
            )

    def parameter(self, name: str) -> Any:
        """Read a declared configuration value."""
        return self._spec.parameter(name)

    @property
    def spec(self) -> HypothesisSpec:
        """Immutable identity: id, version, features, basis, fingerprint."""
        return self._spec

    @property
    def fingerprint(self) -> str:
        return self._spec.fingerprint

    @property
    def label(self) -> str:
        return self._spec.label

    # -- public API ------------------------------------------------------

    def evaluate(self, evidence: EvidenceSet) -> tuple[ResearchObservation, ...]:
        """Classify every bar in ``evidence``, in order.

        Raises rather than degrading for any structural problem: missing
        required evidence, a wrong price basis, or a malformed evidence set.
        ``INSUFFICIENT_DATA`` is returned only for genuine warm-up.
        """
        self._require_usable(evidence)
        return tuple(
            self._observe(evidence, index) for index in range(len(evidence))
        )

    def evaluate_at(self, evidence: EvidenceSet, index: int) -> ResearchObservation:
        """Classify a single bar."""
        self._require_usable(evidence)
        if not 0 <= index < len(evidence):
            raise HypothesisError(
                f"index {index} out of range for {len(evidence)} bars of evidence"
            )
        return self._observe(evidence, index)

    # -- subclass hook ---------------------------------------------------

    @abstractmethod
    def _classify(
        self, values: EvidenceWindow
    ) -> tuple[ResearchState, Sequence[ReasonCode]]:
        """Classify one bar from a causal evidence window.

        ``values`` is an :class:`~src.strategies.evidence.EvidenceWindow`
        covering ``[T - lookback ... T]``. It behaves as a mapping of the
        current bar's values, so ``values[spec.key]`` reads the present, and
        ``values.past(spec, ago)`` reads ``ago`` bars back (``ago`` bounded by
        the declared lookback).

        Every value in the window is guaranteed to be a real number -- warm-up
        and insufficient history are handled by the caller, so there are no
        ``None`` cases to write.

        Must be a pure function of ``values``: no clock, no randomness, no
        state carried between calls. Two calls with equal input must return
        equal output.

        Returns the state and at least one reason code. An unexplained
        classification is not auditable.
        """

    # -- internals -------------------------------------------------------

    def _require_usable(self, evidence: EvidenceSet) -> None:
        if not isinstance(evidence, EvidenceSet):
            raise HypothesisError(
                f"{self.hypothesis_id}: expected an EvidenceSet, got "
                f"{type(evidence).__name__}; hypotheses consume aligned evidence, "
                "not raw bars or loose features"
            )

        missing = [spec.key for spec in self._spec.required_features if not evidence.has(spec)]
        if missing:
            raise HypothesisError(
                f"{self.label}: evidence is missing required feature(s) {missing}; "
                f"available: {list(evidence.keys())}. A hypothesis is not evaluated "
                "against substitute evidence."
            )

        if self.required_basis is not None and evidence.basis is not self.required_basis:
            raise HypothesisError(
                f"{self.label}: requires {self.required_basis.value!r} evidence but was "
                f"given {evidence.basis.value!r}. Basis conversion belongs to the data "
                "layer; this hypothesis will not silently reinterpret prices."
            )

    def _observe(self, evidence: EvidenceSet, index: int) -> ResearchObservation:
        specs = self._spec.required_features
        lookback = self._spec.lookback
        snapshot = evidence.snapshot(specs, index)

        # Rows for [T, T-1, ... T-lookback]. A bar too early in the dataset to
        # fill the window is a legitimate shortage of history, reported the
        # same way as warm-up.
        rows: list[dict[str, float | None]] = []
        insufficient = index < lookback
        if not insufficient:
            rows = [evidence.snapshot(specs, index - ago) for ago in range(lookback + 1)]
            insufficient = any(value is None for row in rows for value in row.values())

        if insufficient:
            state: ResearchState = ResearchState.INSUFFICIENT_DATA
            codes: Sequence[ReasonCode] = (ReasonCode.WARMUP_INCOMPLETE,)
        else:
            # The hook sees only the declared window -- no series, no future
            # index, no dataset length, no timestamps.
            state, codes = self._classify(EvidenceWindow(rows, lookback))
            state = ResearchState(state)
            codes = tuple(codes)
            if state is ResearchState.INSUFFICIENT_DATA:
                raise HypothesisError(
                    f"{self.label}: _classify returned INSUFFICIENT_DATA with complete "
                    "evidence. That state is reserved for warm-up and must not be used "
                    "to express an inconclusive classification -- use NEUTRAL."
                )
            if not codes:
                raise HypothesisError(
                    f"{self.label}: _classify returned no reason codes for state "
                    f"{state.value!r}"
                )

        return ResearchObservation.build(
            self._spec,
            symbol=evidence.symbol,
            interval=evidence.interval,
            basis=evidence.basis,
            timestamp=evidence.timestamps[index],
            state=state,
            evidence=snapshot,
            reason_codes=codes,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.label}>"


__all__ = ["ResearchHypothesis", "HypothesisError"]
