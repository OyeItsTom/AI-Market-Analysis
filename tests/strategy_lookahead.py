"""Causal testing harness for research hypotheses.

Extends the Phase 2 philosophy from features to whole hypotheses, and tests
the **full pipeline** -- bars, feature computation, evidence assembly and
classification -- rather than the ``_classify`` hook alone.  Testing the hook
would prove nothing about a subclass that overrides ``evaluate``.

Two properties, because the Phase 2 review proved that either alone has blind
spots:

1. **Tail perturbation** -- observations before index ``k`` must be unchanged
   when bars after ``k`` are replaced with radically different ones.
2. **Truncation invariance** -- ``run(series[:k])`` must equal
   ``run(series)[:k]``.  Truncation changes the series *length* and removes
   future *timestamps*, neither of which perturbation alters, so it catches
   cheats that perturbation cannot see.

Observations are compared by value: state, reason codes, evidence and
timestamp all participate, so a cheat that changes only the explanation is
caught as readily as one that changes the verdict.
"""

from __future__ import annotations

from typing import Callable, Sequence

from src.data.series import BarSeries
from src.strategies.research import ResearchObservation

from .lookahead import perturb_tail

RunFn = Callable[[BarSeries], Sequence[ResearchObservation]]


def _comparable(observation: ResearchObservation) -> tuple:
    """The full value of an observation, for exact comparison."""
    return (
        observation.hypothesis_id,
        observation.version,
        observation.fingerprint,
        observation.symbol,
        observation.interval,
        observation.basis,
        observation.timestamp,
        observation.state,
        tuple(sorted(observation.evidence.items())),
        observation.reason_codes,
    )


def assert_observations_prefix_invariant(
    run: RunFn, series: BarSeries, k: int, *, label: str = ""
) -> None:
    """Observations before ``k`` must ignore every bar from ``k`` onward."""
    original = list(run(series))
    mutated = list(run(perturb_tail(series, k)))

    assert len(original) == len(mutated) == len(series), (
        f"{label}: observation count changed with the tail "
        f"({len(original)} vs {len(mutated)} for {len(series)} bars)"
    )
    for index in range(k):
        before, after = _comparable(original[index]), _comparable(mutated[index])
        assert before == after, (
            f"{label}: LOOK-AHEAD at index {index} (k={k}) -- the observation changed "
            f"when only bars at index >= {k} were modified.\n  before: {before}\n"
            f"  after:  {after}"
        )


def assert_observations_truncation_invariant(
    run: RunFn, series: BarSeries, *, label: str = ""
) -> None:
    """``run(series[:k])`` must equal ``run(series)[:k]`` for every ``k``."""
    full = [_comparable(observation) for observation in run(series)]

    for k in range(len(series) + 1):
        truncated = [_comparable(observation) for observation in run(series.prefix(k))]
        assert len(truncated) == k, (
            f"{label}: a {k}-bar prefix produced {len(truncated)} observations"
        )
        assert truncated == full[:k], (
            f"{label}: LOOK-AHEAD -- observations on a {k}-bar prefix differ from the "
            f"first {k} observations of the full series. The hypothesis depends on "
            "evidence beyond the bar it is classifying."
        )


def assert_hypothesis_causal(run: RunFn, series: BarSeries, *, label: str = "") -> None:
    """Run every causality check at every split point. Use this one."""
    for k in range(len(series) + 1):
        assert_observations_prefix_invariant(run, series, k, label=label)
    assert_observations_truncation_invariant(run, series, label=label)


def assert_hypothesis_deterministic(run: RunFn, series: BarSeries, *, runs: int = 3) -> None:
    """Repeated evaluation of identical input must give identical output."""
    first = [_comparable(observation) for observation in run(series)]
    for _ in range(runs - 1):
        again = [_comparable(observation) for observation in run(series)]
        assert again == first, "hypothesis evaluation is not deterministic"


def assert_series_unchanged(run: RunFn, series: BarSeries) -> None:
    """Evaluation must not mutate the bars it was given."""
    before_bars = tuple(series.bars)
    before_values = {
        field: series.values(field) for field in ("open", "high", "low", "close", "volume")
    }
    before_meta = (series.symbol, series.interval, series.source, series.basis)

    run(series)

    assert tuple(series.bars) == before_bars, "evaluation mutated the input bars"
    for field, values in before_values.items():
        assert series.values(field) == values, f"evaluation mutated input {field}"
    assert (series.symbol, series.interval, series.source, series.basis) == before_meta


__all__ = [
    "assert_observations_prefix_invariant",
    "assert_observations_truncation_invariant",
    "assert_hypothesis_causal",
    "assert_hypothesis_deterministic",
    "assert_series_unchanged",
]
