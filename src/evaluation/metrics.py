"""Aggregate metrics over evaluated outcomes.

Every number here has an exact definition, stated on the field that produces
it.  Undefined metrics are ``None`` -- never ``0.0``, which would read as "the
mean return was zero" when the truth is "there were no such observations".

Accounting is complete by construction: ``total_observations`` equals the sum
of evaluated, ineligible, insufficient-future and no-reference counts.  A
summary that quietly dropped a category would fail its own invariant.

Overlapping horizons
--------------------
With ``horizon_bars > 1``, consecutive observations share most of their
forward window -- daily observations at H=20 overlap in 19 of 20 bars.  The
observations are therefore **not independent samples**.  No p-value,
confidence interval or significance test is computed here, because every
standard one assumes an independence this data does not have.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from src.data.models import Interval
from src.data.series import PriceBasis
from src.strategies.research import ResearchState

from .outcome import EvaluatedOutcome, OutcomeError, OutcomeStatus


@dataclass(frozen=True)
class StateMetrics:
    """Metrics for one group of evaluated outcomes.

    ``count`` is the number of **evaluated** outcomes in the group. When it is
    zero every other field is ``None``: a mean over nothing is undefined, not
    zero.

    ``positive_return_rate`` -- fraction with ``outcome_value > 0``.

    ``directional_hit_rate`` -- fraction classified in the correct direction:
    ``> 0`` for BULLISH, ``< 0`` for BEARISH. **Exactly zero counts as a miss
    for both.** ``None`` for non-directional groups, where the concept does
    not apply -- NEUTRAL is never scored as right or wrong.

    Note that for BULLISH the hit rate and the positive-return rate are the
    same quantity by definition; for BEARISH they are not complements whenever
    zero returns occur.
    """

    count: int
    mean_forward_return: float | None
    median_forward_return: float | None
    positive_return_rate: float | None
    directional_hit_rate: float | None = None

    @classmethod
    def over(
        cls, values: Sequence[float], *, state: ResearchState | None = None
    ) -> "StateMetrics":
        values = list(values)
        if not values:
            return cls(0, None, None, None, None)

        hit_rate: float | None = None
        if state is ResearchState.BULLISH:
            hit_rate = sum(1 for value in values if value > 0) / len(values)
        elif state is ResearchState.BEARISH:
            hit_rate = sum(1 for value in values if value < 0) / len(values)

        return cls(
            count=len(values),
            mean_forward_return=statistics.fmean(values),
            median_forward_return=statistics.median(values),
            positive_return_rate=sum(1 for value in values if value > 0) / len(values),
            directional_hit_rate=hit_rate,
        )


@dataclass(frozen=True)
class EvaluationSummary:
    """Immutable accounting and metrics for one evaluation run.

    ``unconditional_mean_forward_return`` is the benchmark: the mean forward
    return over **exactly the same evaluated sample**, ignoring the
    classification. It is the only fair comparison for a state-conditioned
    mean, because it shares the identical timestamps, horizon, reference
    convention and price basis. It is by construction equal to
    ``all_evaluated.mean_forward_return``; it is named separately so that a
    reader comparing a bullish mean against "the market" can see which sample
    that benchmark was taken over.
    """

    symbol: str
    interval: Interval
    basis: PriceBasis
    spec_fingerprint: str
    horizon_bars: int

    total_observations: int
    ineligible_observations: int
    eligible_observations: int
    evaluated_observations: int
    insufficient_future_data: int
    no_reference_bar: int
    observations_by_state: Mapping[ResearchState, int]

    all_evaluated: StateMetrics
    bullish: StateMetrics
    bearish: StateMetrics
    neutral: StateMetrics

    unconditional_mean_forward_return: float | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observations_by_state", MappingProxyType(dict(self.observations_by_state))
        )
        accounted = (
            self.evaluated_observations
            + self.ineligible_observations
            + self.insufficient_future_data
            + self.no_reference_bar
        )
        if accounted != self.total_observations:
            raise OutcomeError(
                f"accounting does not balance: {accounted} categorised vs "
                f"{self.total_observations} supplied. Every observation must appear in "
                "exactly one category; a missing one is a silently dropped record."
            )

    def describe(self) -> str:
        def render(value: float | None) -> str:
            return "n/a" if value is None else f"{value:+.6f}"

        return (
            f"{self.symbol} {self.interval.value} [{self.basis.value}] "
            f"h={self.horizon_bars} spec#{self.spec_fingerprint}\n"
            f"  observations: {self.total_observations} total, "
            f"{self.eligible_observations} eligible, {self.evaluated_observations} evaluated, "
            f"{self.ineligible_observations} ineligible, "
            f"{self.insufficient_future_data} insufficient future, "
            f"{self.no_reference_bar} no reference bar\n"
            f"  unconditional mean: {render(self.unconditional_mean_forward_return)}\n"
            f"  bullish n={self.bullish.count} mean={render(self.bullish.mean_forward_return)} "
            f"hit={render(self.bullish.directional_hit_rate)}\n"
            f"  bearish n={self.bearish.count} mean={render(self.bearish.mean_forward_return)} "
            f"hit={render(self.bearish.directional_hit_rate)}\n"
            f"  neutral n={self.neutral.count} mean={render(self.neutral.mean_forward_return)}"
        )


def summarize(outcomes: Sequence[EvaluatedOutcome]) -> EvaluationSummary:
    """Aggregate outcomes into an immutable summary.

    Every supplied outcome is counted. Unavailable ones are reported in their
    own categories rather than removed, so end-of-sample survivorship is
    visible on the face of the result.

    Trust boundary: this is a **pure aggregation layer over trusted evaluated
    records**. It checks that they come from one symbol, interval, basis and
    outcome specification, but it does not deduplicate -- passing the same
    record twice counts it twice. Deduplication belongs upstream, where
    :func:`~src.evaluation.evaluate.evaluate_observations` already rejects
    duplicate observation timestamps. Grouped or re-partitioned analyses may
    legitimately need to re-summarise the same records, so a blanket duplicate
    check here would be wrong.

    Results are permutation-invariant: the order of ``outcomes`` does not
    affect any count or metric.
    """
    outcomes = list(outcomes)
    if not outcomes:
        raise OutcomeError(
            "cannot summarise an empty outcome list; there is nothing to account for"
        )
    for outcome in outcomes:
        if not isinstance(outcome, EvaluatedOutcome):
            raise OutcomeError(f"expected EvaluatedOutcome, got {type(outcome).__name__}")

    first = outcomes[0]
    for outcome in outcomes:
        mismatches = [
            f"{label} {theirs!r} != {ours!r}"
            for label, theirs, ours in (
                ("symbol", outcome.symbol, first.symbol),
                ("interval", outcome.interval.value, first.interval.value),
                ("basis", outcome.basis.value, first.basis.value),
                ("spec", outcome.spec_fingerprint, first.spec_fingerprint),
            )
            if theirs != ours
        ]
        if mismatches:
            raise OutcomeError(
                f"cannot summarise outcomes from different evaluations: "
                f"{'; '.join(mismatches)}"
            )

    by_state: dict[ResearchState, int] = {state: 0 for state in ResearchState}
    for outcome in outcomes:
        by_state[outcome.observation_state] += 1

    evaluated = [o for o in outcomes if o.status is OutcomeStatus.EVALUATED]
    values_for = lambda state: [  # noqa: E731 - local alias keeps the table readable
        o.outcome_value for o in evaluated if o.observation_state is state
    ]
    all_values = [o.outcome_value for o in evaluated]

    all_metrics = StateMetrics.over(all_values)

    return EvaluationSummary(
        symbol=first.symbol,
        interval=first.interval,
        basis=first.basis,
        spec_fingerprint=first.spec_fingerprint,
        horizon_bars=first.horizon_bars,
        total_observations=len(outcomes),
        ineligible_observations=sum(
            1 for o in outcomes if o.status is OutcomeStatus.INELIGIBLE_OBSERVATION
        ),
        eligible_observations=sum(
            1 for o in outcomes if o.status is not OutcomeStatus.INELIGIBLE_OBSERVATION
        ),
        evaluated_observations=len(evaluated),
        insufficient_future_data=sum(
            1 for o in outcomes if o.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        ),
        no_reference_bar=sum(
            1 for o in outcomes if o.status is OutcomeStatus.NO_REFERENCE_BAR
        ),
        observations_by_state=by_state,
        all_evaluated=all_metrics,
        bullish=StateMetrics.over(values_for(ResearchState.BULLISH), state=ResearchState.BULLISH),
        bearish=StateMetrics.over(values_for(ResearchState.BEARISH), state=ResearchState.BEARISH),
        neutral=StateMetrics.over(values_for(ResearchState.NEUTRAL), state=ResearchState.NEUTRAL),
        unconditional_mean_forward_return=all_metrics.mean_forward_return,
    )


__all__ = ["EvaluationSummary", "StateMetrics", "summarize"]
