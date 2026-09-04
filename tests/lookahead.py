"""Reusable anti-look-ahead harness.

The property under test
-----------------------
For any causal feature, the value at bar ``i`` may depend on bars ``0..i`` and
nothing else.  That gives a property which is far stronger than inspecting the
implementation, and which survives refactoring:

    Take a series A.  Build series B whose first ``k`` bars are byte-identical
    to A's but whose remaining bars are drastically different.  Every feature
    value at index ``< k`` must be EXACTLY equal between A and B.

If a calculation peeks forward -- a centred window, an off-by-one slice, a
"seed from the end" initialisation, a global sort -- the mutated tail leaks
backwards and the assertion fails.

Exact equality is used deliberately.  A causal feature does not merely produce
*similar* values when the future changes; it produces identical ones, because
it never read them. A tolerance here would hide precisely the bug being hunted.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable, Sequence

from src.data.models import MarketBar
from src.data.series import BarSeries
from src.features.base import FeatureSeries

FeatureFn = Callable[[BarSeries], FeatureSeries]


def perturb_tail(series: BarSeries, k: int, *, scale: float = 7.5) -> BarSeries:
    """Return a series identical to ``series`` for the first ``k`` bars.

    Every bar from ``k`` onward is replaced with radically different prices and
    volume, while remaining internally valid (high >= low, positive prices) so
    that the perturbed series is itself a legal ``BarSeries`` and the feature
    cannot reject it for unrelated reasons.

    The tail alternates between values far ABOVE and far BELOW the original
    range. Scaling the tail in one direction only would hide a whole class of
    leak: a feature using ``min(all_prices)`` survives an upward-only
    perturbation because the minimum stays in the prefix. Moving the tail in
    both directions changes every global statistic.
    """
    if not 0 <= k <= len(series):
        raise ValueError(f"k must be within 0..{len(series)}, got {k}")

    bars = list(series.bars[:k])
    for offset, bar in enumerate(series.bars[k:]):
        # Alternate far above / far below the original range.
        close = bar.close * scale if offset % 2 == 0 else bar.close / scale
        open_ = close * 0.9
        bars.append(
            MarketBar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=open_,
                high=max(open_, close) * 1.2,
                low=min(open_, close) * 0.8,
                close=close,
                volume=bar.volume * scale + 1_000.0,
                interval=bar.interval,
                source=bar.source,
            )
        )
    return series.with_bars(bars)


def assert_prefix_invariant(
    feature_fn: FeatureFn,
    series: BarSeries,
    k: int,
    *,
    label: str = "",
) -> None:
    """Assert ``feature_fn`` values before index ``k`` ignore everything after it."""
    perturbed = perturb_tail(series, k)

    original = feature_fn(series)
    mutated = feature_fn(perturbed)
    name = label or original.name

    assert len(original) == len(mutated) == len(series), (
        f"{name}: feature length changed with the tail "
        f"({len(original)} vs {len(mutated)} for {len(series)} bars)"
    )

    for index in range(k):
        assert original.timestamps[index] == mutated.timestamps[index], (
            f"{name}: timestamp at index {index} changed when only future bars were altered"
        )
        assert original.values[index] == mutated.values[index], (
            f"{name}: LOOK-AHEAD at index {index} (k={k}) -- value changed from "
            f"{original.values[index]!r} to {mutated.values[index]!r} when only bars "
            f"at index >= {k} were modified"
        )


def assert_causal_at_every_split(
    feature_fn: FeatureFn,
    series: BarSeries,
    *,
    label: str = "",
) -> None:
    """Run :func:`assert_prefix_invariant` at every possible split point.

    Stronger than a single split: an off-by-one that only leaks one bar
    backwards survives a coarse test but not this one.
    """
    for k in range(len(series) + 1):
        assert_prefix_invariant(feature_fn, series, k, label=label)


def assert_truncation_invariant(
    feature_fn: FeatureFn,
    series: BarSeries,
    *,
    label: str = "",
) -> None:
    """Assert ``feature(series[:k]) == feature(series)[:k]`` for every ``k``.

    This is the definition of causality, and it is strictly stronger than
    perturbing the tail. Tail perturbation keeps the series *length* and its
    *timestamps* intact, so a feature that leaks through either of those --
    ``len(prices)``, or reading ``timestamps[-1]`` -- passes it while being
    plainly non-causal. Truncation changes both, so it catches them.

    Run this alongside :func:`assert_causal_at_every_split`: perturbation
    catches value leaks, truncation catches shape leaks, and neither subsumes
    the other.
    """
    full = feature_fn(series)
    name = label or full.name

    for k in range(len(series) + 1):
        truncated = feature_fn(series.prefix(k))
        assert len(truncated) == k, (
            f"{name}: feature on a {k}-bar prefix produced {len(truncated)} values"
        )
        assert truncated.timestamps == full.timestamps[:k], (
            f"{name}: timestamps differ between a {k}-bar prefix and the full series"
        )
        assert truncated.values == full.values[:k], (
            f"{name}: LOOK-AHEAD -- values on a {k}-bar prefix differ from the first "
            f"{k} values of the full series. {truncated.values!r} != {full.values[:k]!r}. "
            "The feature depends on data beyond the bar it is describing."
        )


def assert_causal(feature_fn: FeatureFn, series: BarSeries, *, label: str = "") -> None:
    """Run every causality check. Use this rather than picking one."""
    assert_causal_at_every_split(feature_fn, series, label=label)
    assert_truncation_invariant(feature_fn, series, label=label)


def assert_input_unchanged(feature_fn: FeatureFn, series: BarSeries) -> None:
    """Assert the feature did not mutate the series it was given."""
    before_bars = tuple(series.bars)
    before_values = {
        field: series.values(field) for field in ("open", "high", "low", "close", "volume")
    }
    before_meta = (series.symbol, series.interval, series.source, series.basis)

    feature_fn(series)

    assert tuple(series.bars) == before_bars, "feature mutated the input bars"
    for field, values in before_values.items():
        assert series.values(field) == values, f"feature mutated input {field}"
    assert (series.symbol, series.interval, series.source, series.basis) == before_meta, (
        "feature mutated input metadata"
    )


def assert_deterministic(feature_fn: FeatureFn, series: BarSeries, *, runs: int = 3) -> None:
    """Assert repeated calls on identical input give identical output."""
    first = feature_fn(series)
    for _ in range(runs - 1):
        again = feature_fn(series)
        assert again.values == first.values, "feature is not deterministic"
        assert again.timestamps == first.timestamps, "feature timestamps are not deterministic"


__all__ = [
    "perturb_tail",
    "assert_prefix_invariant",
    "assert_causal_at_every_split",
    "assert_truncation_invariant",
    "assert_causal",
    "assert_input_unchanged",
    "assert_deterministic",
]
