"""Causal testing harness for outcome evaluation.

Phase 3 protected hypothesis *generation* from future leakage. This protects
outcome *evaluation* separately: an evaluator that peeks past its own horizon
would produce numbers that look like forward returns and are not.

Two properties, mirroring the Phase 2/3 philosophy because neither subsumes
the other:

1. **Post-horizon perturbation** -- for an outcome ending at future index
   ``F``, replacing every bar strictly after ``F`` must not change it.
2. **Truncation invariance** -- evaluating against a series truncated
   immediately after ``F`` must give the identical record.

Truncation changes the series *length* and removes later *timestamps*, which
perturbation preserves; perturbation changes later *values*, which truncation
removes entirely. A cheat visible to one may be invisible to the other.

Outcomes are compared by full value, so a cheat that alters only the status or
the recorded prices is caught as readily as one that alters the return.
"""

from __future__ import annotations

from typing import Callable, Sequence

from src.data.models import MarketBar
from src.data.series import BarSeries
from src.evaluation.outcome import EvaluatedOutcome

EvaluateFn = Callable[[BarSeries], Sequence[EvaluatedOutcome]]


def _comparable(outcome: EvaluatedOutcome) -> tuple:
    """The full value of an outcome record, for exact comparison."""
    return (
        outcome.hypothesis_id,
        outcome.hypothesis_version,
        outcome.hypothesis_fingerprint,
        outcome.symbol,
        outcome.interval,
        outcome.basis,
        outcome.observation_timestamp,
        outcome.observation_state,
        outcome.spec_fingerprint,
        outcome.horizon_bars,
        outcome.status,
        outcome.reference_timestamp,
        outcome.future_timestamp,
        outcome.reference_price,
        outcome.future_price,
        outcome.outcome_value,
    )


def perturb_after(series: BarSeries, index: int, *, scale: float = 9.0) -> BarSeries:
    """Return a series identical up to and including ``index``, wild after it.

    The tail is replaced with two contiguous blocks -- one far above the
    original range, one far below -- rather than alternating bar by bar. An
    alternating pattern cancels under any averaging, which was shown in Phase 3
    to hide cheats that read smoothed global statistics.
    """
    if not -1 <= index < len(series):
        raise ValueError(f"index {index} out of range for {len(series)} bars")

    bars = list(series.bars[: index + 1])
    tail = series.bars[index + 1:]
    boundary = max(1, len(tail) // 2)
    for offset, bar in enumerate(tail):
        close = bar.close * scale if offset < boundary else bar.close / scale
        open_ = close * 0.95
        bars.append(
            MarketBar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=open_,
                high=max(open_, close) * 1.1,
                low=min(open_, close) * 0.9,
                close=close,
                volume=bar.volume * scale + 1.0,
                interval=bar.interval,
                source=bar.source,
            )
        )
    return series.with_bars(bars)


def assert_outcome_ignores_bars_after_horizon(
    evaluate: EvaluateFn, series: BarSeries, *, label: str = ""
) -> None:
    """Every outcome must be unchanged by bars after its own future bar."""
    original = list(evaluate(series))
    timestamps = list(series.timestamps)

    for outcome in original:
        if outcome.future_timestamp is None:
            continue
        future_index = timestamps.index(outcome.future_timestamp)
        if future_index >= len(series) - 1:
            continue  # nothing after it to perturb

        mutated = {
            _comparable(o)[6]: o for o in evaluate(perturb_after(series, future_index))
        }
        after = mutated.get(outcome.observation_timestamp)
        assert after is not None, f"{label}: observation disappeared after perturbation"
        assert _comparable(outcome) == _comparable(after), (
            f"{label}: LOOK-AHEAD -- the outcome for "
            f"{outcome.observation_timestamp.isoformat()} (future bar "
            f"{outcome.future_timestamp.isoformat()}, index {future_index}) changed when "
            f"only bars after index {future_index} were modified."
        )


def assert_outcome_survives_truncation(
    evaluate: EvaluateFn, series: BarSeries, *, label: str = ""
) -> None:
    """Truncating immediately after the future bar must not change an outcome."""
    original = list(evaluate(series))
    timestamps = list(series.timestamps)

    for outcome in original:
        if outcome.future_timestamp is None:
            continue
        future_index = timestamps.index(outcome.future_timestamp)

        truncated = {
            o.observation_timestamp: o
            for o in evaluate(series.prefix(future_index + 1))
        }
        after = truncated.get(outcome.observation_timestamp)
        assert after is not None, (
            f"{label}: observation {outcome.observation_timestamp.isoformat()} vanished "
            f"when the series was truncated after its own future bar"
        )
        assert _comparable(outcome) == _comparable(after), (
            f"{label}: LOOK-AHEAD -- the outcome for "
            f"{outcome.observation_timestamp.isoformat()} changed when the series was "
            f"truncated immediately after its future bar. It depends on data it should "
            f"not have read."
        )


def assert_evaluation_causal(
    evaluate: EvaluateFn, series: BarSeries, *, label: str = ""
) -> None:
    """Run both causality properties. Use this one."""
    assert_outcome_ignores_bars_after_horizon(evaluate, series, label=label)
    assert_outcome_survives_truncation(evaluate, series, label=label)


def assert_evaluation_deterministic(
    evaluate: EvaluateFn, series: BarSeries, *, runs: int = 3
) -> None:
    first = [_comparable(o) for o in evaluate(series)]
    for _ in range(runs - 1):
        assert [_comparable(o) for o in evaluate(series)] == first, (
            "evaluation is not deterministic"
        )


__all__ = [
    "perturb_after",
    "assert_outcome_ignores_bars_after_horizon",
    "assert_outcome_survives_truncation",
    "assert_evaluation_causal",
    "assert_evaluation_deterministic",
]
