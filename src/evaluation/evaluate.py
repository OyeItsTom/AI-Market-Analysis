"""Causal evaluation of research observations against subsequent bars.

Causality contract
------------------
For an observation at bar ``i`` with ``horizon_bars = H``::

    reference_index = i + 1
    future_index    = reference_index + H - 1

The evaluation reads bar ``i+1``'s open and bar ``future_index``'s chosen
price, and **nothing after** ``future_index``.  Changing or truncating bars
beyond that index cannot alter an already-computed outcome -- verified as a
property in ``tests/evaluation_lookahead.py``, not merely asserted here.

Why ``evaluable_from`` is deliberately not used
-----------------------------------------------
Phase 3 exposes ``ResearchObservation.evaluable_from`` as a timing *bound*
(``timestamp + interval.max_duration``).  It must **not** be used to find the
reference bar.  ``max_duration`` is an upper bound, so for a monthly series an
observation on the 1 Feb bar has ``evaluable_from`` of 3 Mar, while the next
bar opens 1 Mar; selecting "the first bar at or after ``evaluable_from``"
would silently skip March and use April.  The reference is chosen by **bar
count**, which is correct for every interval and consistent with the bar-count
horizon.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Sequence

from src.data.models import Interval
from src.data.series import BarSeries
from src.strategies.research import ResearchObservation, ResearchState

from .outcome import (
    EvaluatedOutcome,
    OutcomeError,
    OutcomeSpec,
    OutcomeStatus,
    PriceField,
    ReferenceConvention,
)

#: Intervals whose spacing in UTC is an exact physical duration, so a
#: too-close next bar is provably malformed. Calendar/session intervals
#: (1d, 1wk, 1mo) are excluded: a daylight-saving transition changes the UTC
#: offset of a session-local midnight, and months vary in length, so their
#: UTC spacing legitimately varies. ``max_duration`` is an upper bound for
#: those and must not be used as a lower bound either.
_EXACT_SPACING_INTERVALS: frozenset[Interval] = frozenset(
    {
        Interval.MINUTE_1,
        Interval.MINUTE_5,
        Interval.MINUTE_15,
        Interval.MINUTE_30,
        Interval.HOUR_1,
    }
)


class EvaluationError(ValueError):
    """Raised when observations and bars cannot be evaluated together."""


def evaluate_observations(
    observations: Sequence[ResearchObservation],
    series: BarSeries,
    spec: OutcomeSpec,
) -> tuple[EvaluatedOutcome, ...]:
    """Evaluate every observation against ``series`` under ``spec``.

    Returns exactly one :class:`EvaluatedOutcome` per supplied observation, in
    **the caller's order** -- observations are not sorted, and a permuted input
    produces a correspondingly permuted output. Each record is independently
    correct regardless of ordering, and
    :func:`~src.evaluation.metrics.summarize` is permutation-invariant, so
    ordering affects the output tuple only.

    Observations that cannot be evaluated are represented with an explicit
    status rather than removed -- silently dropping them is how end-of-sample
    survivorship enters a study.

    Structure is validated; provenance is not authenticated. See
    :class:`~src.evaluation.outcome.EvaluatedOutcome`.

    Raises
    ------
    EvaluationError
        Structural mismatch: wrong type, wrong symbol/interval/basis, an
        observation whose timestamp is not a bar in this series, or bars
        spaced closer than a fixed-duration interval allows.
    """
    if not isinstance(series, BarSeries):
        raise EvaluationError(
            f"expected a BarSeries, got {type(series).__name__}; evaluation consumes "
            "validated series, not loose bars"
        )
    if not isinstance(spec, OutcomeSpec):
        raise EvaluationError(f"expected an OutcomeSpec, got {type(spec).__name__}")

    if series.basis is not spec.required_basis:
        raise EvaluationError(
            f"outcome specification requires {spec.required_basis.value!r} prices but the "
            f"series is {series.basis.value!r}. Basis conversion belongs to the data "
            "layer; evaluation will not silently reinterpret prices."
        )
    if spec.reference is not ReferenceConvention.NEXT_BAR_OPEN:  # pragma: no cover
        raise EvaluationError(f"unsupported reference convention {spec.reference!r}")

    # Timestamp -> index. BarSeries guarantees unique, strictly increasing
    # timestamps, so this mapping is total and unambiguous.
    index_of = {timestamp: index for index, timestamp in enumerate(series.timestamps)}
    if len(index_of) != len(series.timestamps):  # pragma: no cover - BarSeries invariant
        raise EvaluationError("series contains duplicate timestamps")

    # One observation per bar. A repeated timestamp would be counted twice in
    # the summary, silently inflating every denominator -- including the
    # directional hit rates -- so it is refused rather than averaged in.
    seen: dict = {}
    for position, observation in enumerate(observations):
        if not isinstance(observation, ResearchObservation):
            raise EvaluationError(
                f"expected a ResearchObservation, got {type(observation).__name__}"
            )
        if observation.timestamp in seen:
            raise EvaluationError(
                f"observation {position} repeats the timestamp "
                f"{observation.timestamp.isoformat()} already supplied at position "
                f"{seen[observation.timestamp]}; a hypothesis produces one observation "
                "per bar, and a duplicate would be counted twice in every metric"
            )
        seen[observation.timestamp] = position

    return tuple(
        _evaluate_one(observation, series, spec, index_of)
        for observation in observations
    )


def _evaluate_one(
    observation: ResearchObservation,
    series: BarSeries,
    spec: OutcomeSpec,
    index_of: dict,
) -> EvaluatedOutcome:
    if not isinstance(observation, ResearchObservation):
        raise EvaluationError(
            f"expected a ResearchObservation, got {type(observation).__name__}"
        )

    _require_alignment(observation, series, spec)

    # Exact timestamp match only. A "nearest bar" search would quietly evaluate
    # an observation against a bar it does not describe.
    observation_index = index_of.get(observation.timestamp)
    if observation_index is None:
        raise EvaluationError(
            f"observation at {observation.timestamp.isoformat()} does not correspond to "
            f"any bar in this {series.symbol} {series.interval.value} series; evaluation "
            "never matches an approximate or nearest timestamp"
        )

    def record(status: OutcomeStatus, **fields) -> EvaluatedOutcome:
        return EvaluatedOutcome(
            hypothesis_id=observation.hypothesis_id,
            hypothesis_version=observation.version,
            hypothesis_fingerprint=observation.fingerprint,
            symbol=observation.symbol,
            interval=observation.interval,
            basis=observation.basis,
            observation_timestamp=observation.timestamp,
            observation_state=observation.state,
            spec_fingerprint=spec.fingerprint,
            horizon_bars=spec.horizon_bars,
            status=status,
            **fields,
        )

    # An observation with no substantive classification has nothing to
    # evaluate. It is still recorded so total accounting stays honest.
    if observation.state is ResearchState.INSUFFICIENT_DATA:
        return record(OutcomeStatus.INELIGIBLE_OBSERVATION)

    reference_index = observation_index + 1
    if reference_index >= len(series):
        return record(OutcomeStatus.NO_REFERENCE_BAR)

    _require_causal_spacing(observation, series, observation_index, reference_index)

    future_index = reference_index + spec.future_offset()
    if future_index >= len(series):
        # The reference bar exists but the full horizon does not. This is not a
        # zero return, not a loss and not a win.
        return record(
            OutcomeStatus.INSUFFICIENT_FUTURE_DATA,
            reference_timestamp=series.timestamps[reference_index],
            reference_price=series[reference_index].open,
        )

    reference_price = series[reference_index].open
    future_price = getattr(series[future_index], PriceField(spec.future_field).value)

    if reference_price == 0:  # pragma: no cover - impossible for a validated series
        raise EvaluationError(
            f"reference price at {series.timestamps[reference_index].isoformat()} is zero; "
            "a forward return is undefined. Validated series cannot contain "
            "non-positive prices, so this indicates corrupted input."
        )

    return record(
        OutcomeStatus.EVALUATED,
        reference_timestamp=series.timestamps[reference_index],
        future_timestamp=series.timestamps[future_index],
        reference_price=reference_price,
        future_price=future_price,
        outcome_value=future_price / reference_price - 1.0,
    )


def _require_alignment(
    observation: ResearchObservation, series: BarSeries, spec: OutcomeSpec
) -> None:
    mismatches = [
        f"{label} {theirs!r} != {ours!r}"
        for label, theirs, ours in (
            ("symbol", observation.symbol, series.symbol),
            ("interval", observation.interval.value, series.interval.value),
            ("basis", observation.basis.value, series.basis.value),
        )
        if theirs != ours
    ]
    if mismatches:
        raise EvaluationError(
            f"observation does not describe this series: {'; '.join(mismatches)}"
        )
    if observation.basis is not spec.required_basis:
        raise EvaluationError(
            f"observation basis {observation.basis.value!r} does not match the outcome "
            f"specification's required basis {spec.required_basis.value!r}"
        )


def _require_causal_spacing(
    observation: ResearchObservation,
    series: BarSeries,
    observation_index: int,
    reference_index: int,
) -> None:
    """Reject a reference bar that starts before the observation bar can end.

    ``BarSeries`` validates that timestamps strictly increase, but not that
    bars do not *overlap*: two bars labelled ``1h`` thirty minutes apart are
    accepted. For such a series the "next" bar would begin before the
    observation bar's data was complete -- look-ahead.

    Only applied to intervals whose UTC spacing is an exact physical duration.
    See :data:`_EXACT_SPACING_INTERVALS`.
    """
    interval = series.interval
    if interval not in _EXACT_SPACING_INTERVALS:
        return

    exact: timedelta = interval.max_duration  # exact for intraday intervals
    spacing = series.timestamps[reference_index] - series.timestamps[observation_index]
    if spacing < exact:
        raise EvaluationError(
            f"bars labelled {interval.value!r} are only {spacing} apart at "
            f"{series.timestamps[observation_index].isoformat()}; the next bar would begin "
            f"before the observation bar's period ends. Expected at least {exact}."
        )


__all__ = ["evaluate_observations", "EvaluationError"]
