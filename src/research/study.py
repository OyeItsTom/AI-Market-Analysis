"""The study engine: windows, batch evaluation, grouping, descriptive metrics.

Pure. Given a :class:`~src.research.definition.StudyDefinition` and one
validated :class:`~src.data.series.BarSeries` per symbol, :func:`run_study`
returns an immutable :class:`StudyResult`. Nothing here reads a clock, a
file, a network or the environment, and nothing here computes a forward
return: every ``outcome_value`` is read off a Phase 4
:class:`~src.evaluation.outcome.EvaluatedOutcome`, every mean and median off
a Phase 4 :class:`~src.evaluation.metrics.StateMetrics`-equivalent
aggregation, and the only arithmetic of this module's own is a subtraction
(the deltas), a comparison (sign counts, min, max) and a run counter
(episodes).

What is measured
----------------
For each hypothesis and symbol, every bar of the observation window is
classified by the hypothesis exactly as the dashboard would classify its
latest bar, and each classification is evaluated under each outcome
specification against the same series. Results are grouped by
``hypothesis x symbol x horizon x state`` and described beside the
**matched unconditional** row -- the forward returns over exactly the
timestamps where that hypothesis' observation was evaluated, state ignored.
That row is Phase 4's ``all_evaluated`` for the same outcome list; it is the
one fair reference for a state-conditioned mean, because it shares the
identical timestamps, horizon, reference convention and price basis.

What is not measured
--------------------
No hit rate, no positive-return rate, no risk-adjusted ratio, no equity
curve, no cross-symbol pool, no p-value. The Phase 4 objects that carry a
directional hit rate are consulted only for the fields listed above; the
report layer never surfaces the rest. See :data:`OVERLAP_CAVEAT` and
:data:`RETROSPECTIVE_CAVEAT` for the two caveats every output must carry.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Sequence

from src.data.series import BarSeries
from src.evaluation import (
    EvaluatedOutcome,
    EvaluationSummary,
    OutcomeSpec,
    OutcomeStatus,
    evaluate_observations,
    summarize,
)
from src.strategies import ResearchHypothesis, ResearchObservation, ResearchState, build_evidence

from .definition import StudyDefinition


class StudyError(ValueError):
    """Raised when the supplied series cannot honestly answer the definition."""


#: Every layer that reports a sample count must carry this sentence.
OVERLAP_CAVEAT: str = (
    "Forward windows may overlap: at horizon 20, observations on adjacent daily "
    "bars can share 19 of 20 future bars. sample_count is not a number of "
    "independent statistical trials, and no p-value, confidence interval or "
    "significance test is computed."
)

#: The retrospective / vendor-revision caveat.
RETROSPECTIVE_CAVEAT: str = (
    "This study evaluates the historical dataset the provider returned at "
    "retrieval time. The provider may have revised or back-filled bars since the "
    "dates studied, so the study is reproducible against the fingerprinted "
    "retrieved dataset and does not establish what the provider displayed at any "
    "historical instant. Phase 12's prospective ledger serves that audit purpose."
)

#: Row types of the summary. A row's type is stated, never inferred from
#: which cells are blank.
ROW_COVERAGE: str = "coverage"
ROW_STATE: str = "state"
ROW_MATCHED_UNCONDITIONAL: str = "matched_unconditional"
ROW_NEUTRAL_REASON: str = "neutral_reason"

#: The ``state`` value of the matched unconditional row.
STATE_ALL: str = "all"

#: The evaluated states, in reporting order. ``INSUFFICIENT_DATA`` carries no
#: classification and appears in coverage only.
REPORTED_STATES: tuple[ResearchState, ...] = (
    ResearchState.BULLISH,
    ResearchState.BEARISH,
    ResearchState.NEUTRAL,
)


# -- descriptive statistics ----------------------------------------------------------------


@dataclass(frozen=True)
class DescriptiveStats:
    """The locked per-group numbers. Undefined is ``None``, never ``0.0``.

    ``mean_forward_return`` and ``median_forward_return`` are computed with
    the same standard-library functions as
    :class:`~src.evaluation.metrics.StateMetrics` (``statistics.fmean`` and
    ``statistics.median``); a test pins the two to agree. The counts partition
    ``sample_count`` exactly: every value is positive, negative or zero.
    """

    sample_count: int
    mean_forward_return: float | None
    median_forward_return: float | None
    min_forward_return: float | None
    max_forward_return: float | None
    positive_count: int
    negative_count: int
    zero_count: int

    def __post_init__(self) -> None:
        if self.positive_count + self.negative_count + self.zero_count != self.sample_count:
            raise StudyError(
                f"sign counts {self.positive_count}+{self.negative_count}+{self.zero_count} "
                f"do not partition sample_count {self.sample_count}"
            )

    @classmethod
    def over(cls, values: Sequence[float]) -> "DescriptiveStats":
        values = list(values)
        if not values:
            return cls(0, None, None, None, None, 0, 0, 0)
        return cls(
            sample_count=len(values),
            mean_forward_return=statistics.fmean(values),
            median_forward_return=statistics.median(values),
            min_forward_return=min(values),
            max_forward_return=max(values),
            positive_count=sum(1 for value in values if value > 0),
            negative_count=sum(1 for value in values if value < 0),
            zero_count=sum(1 for value in values if value == 0),
        )


def count_episodes(membership: Sequence[bool]) -> int:
    """Number of maximal runs of ``True`` in ``membership``.

    ``membership[i]`` says whether observation ``i`` of a symbol/hypothesis
    observation sequence belongs to the group. Adjacency is **observation-bar
    adjacency**: two members at positions ``i`` and ``i + 1`` continue one
    episode whatever the calendar gap between their bars, so a weekend never
    splits a run and a missing session never joins one.

    Descriptive only. An episode count is not an effective sample size, not
    an independent-trial count and not a statistical correction; it exists
    so that ``sample_count=900, episode_count=18`` can be read for what it is.
    """
    episodes = 0
    inside = False
    for member in membership:
        member = bool(member)
        if member and not inside:
            episodes += 1
        inside = member
    return episodes


def max_abs_single_bar_close_return(series: BarSeries) -> float | None:
    """Largest absolute close-to-close change between consecutive fetched bars.

    A raw-basis diagnostic: a split or a large distribution shows up here as
    a jump. It is reported so a reader can see it. Nothing is deleted,
    adjusted, winsorised or excluded because of it, and no threshold turns
    it into a pass or a fail. ``None`` when fewer than two bars exist.
    """
    closes = series.values("close")
    if len(closes) < 2:
        return None
    return max(abs(closes[index] / closes[index - 1] - 1.0) for index in range(1, len(closes)))


# -- windows ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowPartition:
    """How one symbol's fetched bars fall into the three half-open windows.

    ``warmup_bars + observation_bars + outcome_buffer_bars == len(series)``
    by construction; the observation bars are the contiguous index range
    ``[warmup_bars, warmup_bars + observation_bars)``.
    """

    symbol: str
    bars_fetched: int
    warmup_bars: int
    observation_bars: int
    outcome_buffer_bars: int

    @property
    def observation_start_index(self) -> int:
        return self.warmup_bars

    @property
    def observation_stop_index(self) -> int:
        return self.warmup_bars + self.observation_bars


def partition_series(definition: StudyDefinition, series: BarSeries) -> WindowPartition:
    """Validate ``series`` against the definition's windows and partition it.

    Raises :class:`StudyError` -- never adjusts -- when the series does not
    describe the study: wrong symbol, interval or basis; a bar outside
    ``[fetch_start, outcome_data_end)``; fewer warm-up bars than the
    definition requires; or no bar at all in the observation window. Moving
    the observation start to fit the data would be exactly the silent
    accommodation the definition exists to forbid.
    """
    if not isinstance(series, BarSeries):
        raise StudyError(f"expected a BarSeries, got {type(series).__name__}")
    if series.symbol not in definition.symbols:
        raise StudyError(f"{series.symbol!r} is not in the study universe {definition.symbols}")
    if series.interval is not definition.interval:
        raise StudyError(
            f"{series.symbol}: series interval {series.interval.value!r} is not the study "
            f"interval {definition.interval.value!r}"
        )
    if series.basis is not definition.basis:
        raise StudyError(
            f"{series.symbol}: series basis {series.basis.value!r} is not the study basis "
            f"{definition.basis.value!r}"
        )
    if len(series) == 0:
        raise StudyError(f"{series.symbol}: the series has no bars")

    timestamps = series.timestamps
    if timestamps[0] < definition.fetch_start or timestamps[-1] >= definition.outcome_data_end:
        raise StudyError(
            f"{series.symbol}: bars span {timestamps[0].isoformat()}..{timestamps[-1].isoformat()}, "
            f"outside the requested window [{definition.fetch_start.isoformat()}, "
            f"{definition.outcome_data_end.isoformat()}); a series outside its fetch window "
            "is not silently trimmed"
        )

    warmup = sum(1 for timestamp in timestamps if timestamp < definition.observation_start)
    observation = sum(
        1
        for timestamp in timestamps
        if definition.observation_start <= timestamp < definition.observation_end
    )
    buffer = len(timestamps) - warmup - observation

    if warmup < definition.minimum_warmup_bars:
        raise StudyError(
            f"{series.symbol}: only {warmup} bars precede the observation start "
            f"{definition.observation_start.isoformat()}; the study requires at least "
            f"{definition.minimum_warmup_bars}. The observation start is not moved to fit."
        )
    if observation == 0:
        raise StudyError(
            f"{series.symbol}: no bar falls in the observation window "
            f"[{definition.observation_start.isoformat()}, "
            f"{definition.observation_end.isoformat()})"
        )
    return WindowPartition(series.symbol, len(series), warmup, observation, buffer)


# -- result records --------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolCoverage:
    """What was fetched for one symbol and how it partitioned."""

    symbol: str
    bars_fetched: int
    warmup_bars: int
    observation_bars: int
    outcome_buffer_bars: int
    first_timestamp: datetime
    last_timestamp: datetime
    first_observation_timestamp: datetime
    last_observation_timestamp: datetime
    max_abs_single_bar_close_return: float | None


@dataclass(frozen=True)
class HorizonAccounting:
    """Phase 4 status counts for one hypothesis x symbol x horizon.

    ``evaluated + insufficient_future_data + no_reference_bar + ineligible``
    equals the hypothesis' ``total_observations``; Phase 4's own summary
    enforces it and this record repeats the check.
    """

    horizon_bars: int
    spec_fingerprint: str
    evaluated: int
    insufficient_future_data: int
    no_reference_bar: int
    ineligible: int

    @property
    def total(self) -> int:
        return (
            self.evaluated + self.insufficient_future_data + self.no_reference_bar + self.ineligible
        )


@dataclass(frozen=True)
class HypothesisCoverage:
    """Accounting for one hypothesis on one symbol over the observation window."""

    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    symbol: str
    total_observations: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    insufficient_data_count: int
    horizons: tuple[HorizonAccounting, ...]
    first_observation_timestamp: datetime
    last_observation_timestamp: datetime

    def __post_init__(self) -> None:
        states = (
            self.bullish_count + self.bearish_count + self.neutral_count
            + self.insufficient_data_count
        )
        if states != self.total_observations:
            raise StudyError(
                f"{self.hypothesis_id} {self.symbol}: state counts {states} do not account for "
                f"{self.total_observations} observations"
            )
        for horizon in self.horizons:
            if horizon.total != self.total_observations:
                raise StudyError(
                    f"{self.hypothesis_id} {self.symbol} h={horizon.horizon_bars}: statuses "
                    f"account for {horizon.total} of {self.total_observations} observations"
                )


@dataclass(frozen=True)
class ResultGroup:
    """One row of the results: a state group or its matched unconditional row.

    ``row_type`` is one of :data:`ROW_STATE`, :data:`ROW_MATCHED_UNCONDITIONAL`
    or :data:`ROW_NEUTRAL_REASON`. The deltas are ``None`` on the matched row
    (it is its own reference) and on an empty group.
    """

    row_type: str
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    symbol: str
    horizon_bars: int
    spec_fingerprint: str
    state: str
    reason_signature: str
    stats: DescriptiveStats
    episode_count: int
    mean_delta_vs_matched_unconditional: float | None
    median_delta_vs_matched_unconditional: float | None
    first_evaluated_timestamp: datetime | None
    last_evaluated_timestamp: datetime | None


@dataclass(frozen=True)
class HorizonOutcome:
    """One observation's outcome under one specification, as Phase 4 reported it."""

    horizon_bars: int
    spec_fingerprint: str
    status: OutcomeStatus
    outcome_value: float | None
    reference_timestamp: datetime | None
    future_timestamp: datetime | None


@dataclass(frozen=True)
class ObservationRow:
    """One hypothesis' classification of one observation-window bar, with its outcomes."""

    symbol: str
    timestamp: datetime
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    state: ResearchState
    reason_codes: tuple[str, ...]
    outcomes: tuple[HorizonOutcome, ...]


@dataclass(frozen=True)
class StudyResult:
    """Everything a run produced, in reporting order. Immutable."""

    definition: StudyDefinition
    symbols: tuple[SymbolCoverage, ...]
    coverage: tuple[HypothesisCoverage, ...]
    groups: tuple[ResultGroup, ...]
    observations: tuple[ObservationRow, ...]

    overlap_caveat: str = OVERLAP_CAVEAT
    retrospective_caveat: str = RETROSPECTIVE_CAVEAT


# -- the engine ------------------------------------------------------------------------------


def _delta(state_value: float | None, reference_value: float | None) -> float | None:
    if state_value is None or reference_value is None:
        return None
    return state_value - reference_value


def _reason_signature(observation: ResearchObservation) -> str:
    return ",".join(code.value for code in observation.reason_codes)


def _group(
    *,
    row_type: str,
    spec: OutcomeSpec,
    hypothesis_spec,
    symbol: str,
    state: str,
    reason_signature: str,
    pairs: Sequence[tuple[ResearchObservation, EvaluatedOutcome]],
    membership: Callable[[ResearchObservation, EvaluatedOutcome], bool],
    reference: DescriptiveStats | None,
) -> ResultGroup:
    """Describe the evaluated outcomes for which ``membership`` holds."""
    members = [membership(observation, outcome) for observation, outcome in pairs]
    values = [outcome.outcome_value for (_, outcome), member in zip(pairs, members) if member]
    stamps = [observation.timestamp for (observation, _), member in zip(pairs, members) if member]
    stats = DescriptiveStats.over(values)
    return ResultGroup(
        row_type=row_type,
        hypothesis_id=hypothesis_spec.hypothesis_id,
        hypothesis_version=hypothesis_spec.version,
        hypothesis_fingerprint=hypothesis_spec.fingerprint,
        symbol=symbol,
        horizon_bars=spec.horizon_bars,
        spec_fingerprint=spec.fingerprint,
        state=state,
        reason_signature=reason_signature,
        stats=stats,
        episode_count=count_episodes(members),
        mean_delta_vs_matched_unconditional=(
            None if reference is None
            else _delta(stats.mean_forward_return, reference.mean_forward_return)
        ),
        median_delta_vs_matched_unconditional=(
            None if reference is None
            else _delta(stats.median_forward_return, reference.median_forward_return)
        ),
        first_evaluated_timestamp=min(stamps) if stamps else None,
        last_evaluated_timestamp=max(stamps) if stamps else None,
    )


def _require_matches_phase_four(
    matched: ResultGroup, summary: EvaluationSummary, state_groups: Sequence[ResultGroup]
) -> None:
    """The matched row *is* Phase 4's ``all_evaluated``; the states partition it."""
    reference = summary.all_evaluated
    if (
        matched.stats.sample_count != reference.count
        or matched.stats.mean_forward_return != reference.mean_forward_return
        or matched.stats.median_forward_return != reference.median_forward_return
        or matched.stats.mean_forward_return != summary.unconditional_mean_forward_return
    ):  # pragma: no cover - would be a defect in this module
        raise StudyError(
            f"{matched.hypothesis_id} {matched.symbol} h={matched.horizon_bars}: the matched "
            "unconditional row disagrees with Phase 4's all_evaluated summary"
        )
    if sum(group.stats.sample_count for group in state_groups) != reference.count:
        raise StudyError(  # pragma: no cover - would be a defect in this module
            f"{matched.hypothesis_id} {matched.symbol} h={matched.horizon_bars}: state groups "
            "do not partition the matched unconditional sample"
        )


def run_study(
    definition: StudyDefinition, series_by_symbol: Mapping[str, BarSeries]
) -> StudyResult:
    """Run ``definition`` over the supplied series and return the result.

    ``series_by_symbol`` must hold exactly the definition's symbols; a missing
    or extra symbol is refused, because a study of four of five symbols is
    a different study. Processing order is the definition's.
    """
    if not isinstance(definition, StudyDefinition):
        raise StudyError(f"expected a StudyDefinition, got {type(definition).__name__}")
    supplied = {str(symbol).strip().upper() for symbol in series_by_symbol}
    expected = set(definition.symbols)
    if supplied != expected:
        raise StudyError(
            f"series were supplied for {sorted(supplied)} but the study universe is "
            f"{list(definition.symbols)}; every symbol, and only those, must be present"
        )
    lookup = {str(symbol).strip().upper(): series for symbol, series in series_by_symbol.items()}

    hypotheses: tuple[ResearchHypothesis, ...] = tuple(cls() for cls in definition.hypotheses)

    symbols: list[SymbolCoverage] = []
    coverage: list[HypothesisCoverage] = []
    groups: list[ResultGroup] = []
    observation_rows: list[ObservationRow] = []

    for symbol in definition.symbols:
        series = lookup[symbol]
        partition = partition_series(definition, series)
        start, stop = partition.observation_start_index, partition.observation_stop_index
        timestamps = series.timestamps
        symbols.append(
            SymbolCoverage(
                symbol=symbol,
                bars_fetched=partition.bars_fetched,
                warmup_bars=partition.warmup_bars,
                observation_bars=partition.observation_bars,
                outcome_buffer_bars=partition.outcome_buffer_bars,
                first_timestamp=timestamps[0],
                last_timestamp=timestamps[-1],
                first_observation_timestamp=timestamps[start],
                last_observation_timestamp=timestamps[stop - 1],
                max_abs_single_bar_close_return=max_abs_single_bar_close_return(series),
            )
        )

        for hypothesis in hypotheses:
            hypothesis_spec = hypothesis.spec
            # Evidence over the whole fetched series: warm-up bars feed the
            # features, buffer bars feed the outcomes. Feature causality
            # (Phase 2) means a buffer bar cannot reach a classification.
            evidence = build_evidence(series, hypothesis_spec.required_features)
            all_observations = hypothesis.evaluate(evidence)
            if len(all_observations) != len(series):  # pragma: no cover - Phase 3 invariant
                raise StudyError("a hypothesis must produce one observation per bar")
            observations = all_observations[start:stop]

            by_state = {state: 0 for state in ResearchState}
            for observation in observations:
                by_state[observation.state] += 1

            per_horizon: list[tuple[OutcomeSpec, tuple[EvaluatedOutcome, ...], EvaluationSummary]] = []
            for spec in definition.outcome_specs:
                outcomes = evaluate_observations(observations, series, spec)
                per_horizon.append((spec, outcomes, summarize(outcomes)))

            coverage.append(
                HypothesisCoverage(
                    hypothesis_id=hypothesis_spec.hypothesis_id,
                    hypothesis_version=hypothesis_spec.version,
                    hypothesis_fingerprint=hypothesis_spec.fingerprint,
                    symbol=symbol,
                    total_observations=len(observations),
                    bullish_count=by_state[ResearchState.BULLISH],
                    bearish_count=by_state[ResearchState.BEARISH],
                    neutral_count=by_state[ResearchState.NEUTRAL],
                    insufficient_data_count=by_state[ResearchState.INSUFFICIENT_DATA],
                    horizons=tuple(
                        HorizonAccounting(
                            horizon_bars=spec.horizon_bars,
                            spec_fingerprint=spec.fingerprint,
                            evaluated=summary.evaluated_observations,
                            insufficient_future_data=summary.insufficient_future_data,
                            no_reference_bar=summary.no_reference_bar,
                            ineligible=summary.ineligible_observations,
                        )
                        for spec, _, summary in per_horizon
                    ),
                    first_observation_timestamp=observations[0].timestamp,
                    last_observation_timestamp=observations[-1].timestamp,
                )
            )

            for spec, outcomes, summary in per_horizon:
                pairs = tuple(zip(observations, outcomes))
                evaluated = lambda _o, outcome: outcome.status is OutcomeStatus.EVALUATED  # noqa: E731

                matched = _group(
                    row_type=ROW_MATCHED_UNCONDITIONAL, spec=spec, hypothesis_spec=hypothesis_spec,
                    symbol=symbol, state=STATE_ALL, reason_signature="", pairs=pairs,
                    membership=evaluated, reference=None,
                )
                state_groups = [
                    _group(
                        row_type=ROW_STATE, spec=spec, hypothesis_spec=hypothesis_spec,
                        symbol=symbol, state=state.value, reason_signature="", pairs=pairs,
                        membership=lambda o, out, s=state: evaluated(o, out) and o.state is s,
                        reference=matched.stats,
                    )
                    for state in REPORTED_STATES
                ]
                _require_matches_phase_four(matched, summary, state_groups)

                signatures = sorted(
                    {
                        _reason_signature(observation)
                        for observation, outcome in pairs
                        if evaluated(observation, outcome)
                        and observation.state is ResearchState.NEUTRAL
                    }
                )
                neutral_groups = [
                    _group(
                        row_type=ROW_NEUTRAL_REASON, spec=spec, hypothesis_spec=hypothesis_spec,
                        symbol=symbol, state=ResearchState.NEUTRAL.value,
                        reason_signature=signature, pairs=pairs,
                        membership=lambda o, out, sig=signature: (
                            evaluated(o, out)
                            and o.state is ResearchState.NEUTRAL
                            and _reason_signature(o) == sig
                        ),
                        reference=matched.stats,
                    )
                    for signature in signatures
                ]
                groups.append(matched)
                groups.extend(state_groups)
                groups.extend(neutral_groups)

            for index, observation in enumerate(observations):
                observation_rows.append(
                    ObservationRow(
                        symbol=symbol,
                        timestamp=observation.timestamp,
                        hypothesis_id=hypothesis_spec.hypothesis_id,
                        hypothesis_version=hypothesis_spec.version,
                        hypothesis_fingerprint=hypothesis_spec.fingerprint,
                        state=observation.state,
                        reason_codes=tuple(code.value for code in observation.reason_codes),
                        outcomes=tuple(
                            HorizonOutcome(
                                horizon_bars=spec.horizon_bars,
                                spec_fingerprint=spec.fingerprint,
                                status=outcomes[index].status,
                                outcome_value=outcomes[index].outcome_value,
                                reference_timestamp=outcomes[index].reference_timestamp,
                                future_timestamp=outcomes[index].future_timestamp,
                            )
                            for spec, outcomes, _ in per_horizon
                        ),
                    )
                )

    return StudyResult(
        definition=definition,
        symbols=tuple(symbols),
        coverage=tuple(coverage),
        groups=tuple(groups),
        observations=tuple(observation_rows),
    )


__all__ = [
    "StudyError",
    "OVERLAP_CAVEAT",
    "RETROSPECTIVE_CAVEAT",
    "ROW_COVERAGE",
    "ROW_STATE",
    "ROW_MATCHED_UNCONDITIONAL",
    "ROW_NEUTRAL_REASON",
    "STATE_ALL",
    "REPORTED_STATES",
    "DescriptiveStats",
    "count_episodes",
    "max_abs_single_bar_close_return",
    "WindowPartition",
    "partition_series",
    "SymbolCoverage",
    "HorizonAccounting",
    "HypothesisCoverage",
    "ResultGroup",
    "HorizonOutcome",
    "ObservationRow",
    "StudyResult",
    "run_study",
]
