"""The pure engine of FUTURE_VALIDATION_V1: stop rule, population, statistics, categories.

Everything here is a function of caller-supplied, already-read evidence and
of the frozen :class:`~src.research.future_validation.FutureValidationDefinition`.
Nothing reads a clock, a file, a network or the environment.

Two levels, two input types
---------------------------
*Level 1* (:class:`ClaimStamp`, :class:`OutcomeStamp`, :class:`LevelOneEvidence`)
carries keys, producer identities, bar timestamps, horizons, spec fingerprints
and provenance exclusions -- no field can hold a state, a reason code, a price
or a return. The stop rule, the evidence clock, the matured-claim counts and the
cutoffs ``C_s`` are computed from Level 1 only, so ``status`` stays blind by
construction.

The evidence clock
------------------
E1 and F are measured on :func:`evidence_through`, the settlement time of the
latest legitimate post-activation claim bar in the frozen snapshot -- a
provider market date that the collector could only claim while it was
current. The host wall clock is never an input: setting it forward cannot
open the validation, and a collection that stops before 72 evidence-months
never reaches F.

*Level 3* (:class:`Observation`, :class:`Measurement`) adds the research state
and the forward return. It is supplied only by the runner, only after the
write-once unlock exists.

Benchmark reuse
---------------
:func:`describe_cell` is the Phase R ``matched_unconditional_v1`` computation
re-expressed over a session sequence: matched membership is "has a matured
value", state membership is "has a matured value and is in the state", the
statistics are Phase R's own :class:`~src.research.study.DescriptiveStats`
(``statistics.fmean`` / ``statistics.median`` over values in bar order),
episodes are Phase R's own :func:`~src.research.study.count_episodes`, and a
delta is the same subtraction. A test runs both on one synthetic study and
requires identical numbers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.data.models import Interval

from .future_validation import (
    CATEGORY_CONSISTENT,
    CATEGORY_INCONCLUSIVE,
    CATEGORY_INVALID,
    CATEGORY_MIXED,
    CATEGORY_REVERSED,
    FutureValidationDefinition,
    HypothesisIdentity,
)
from .render import format_float
from .study import DescriptiveStats, count_episodes


class FutureValidationError(ValueError):
    """Raised when evidence cannot honestly answer the definition."""


#: A daily bar's period: a bar settles at its timestamp plus one day.
DAILY_BAR_PERIOD: timedelta = Interval.DAY_1.max_duration

STATE_BULLISH = "bullish"
STATE_BEARISH = "bearish"


# -- calendar months -----------------------------------------------------------------------------


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FutureValidationError(f"{label} must be a timezone-aware datetime")
    return value


def _last_day_of_month(year: int, month: int) -> int:
    following = date(year + month // 12, month % 12 + 1, 1)
    return (following - timedelta(days=1)).day


def add_calendar_months(moment: datetime, months: int) -> datetime:
    """``moment`` in UTC plus ``months`` calendar months, the day clamped to the month's end.

    Never an approximation such as ``30 * months`` days: 2026-01-31 plus one
    month is 2026-02-28, 2028-02-29 plus 48 months is 2032-02-29, plus 72
    months is 2034-02-28. The time of day is kept. UTC has no DST, so an
    aware input in any zone yields the same instant.
    """
    utc = _require_aware(moment, "moment").astimezone(timezone.utc)
    if isinstance(months, bool) or not isinstance(months, int) or months < 0:
        raise FutureValidationError("months must be a non-negative int")
    index = utc.month - 1 + months
    year, month = utc.year + index // 12, index % 12 + 1
    day = min(utc.day, _last_day_of_month(year, month))
    return utc.replace(year=year, month=month, day=day)


def months_elapsed(activated_at: datetime, instant: datetime, months: int) -> bool:
    """Whether at least ``months`` calendar months have elapsed at ``instant``."""
    return _require_aware(instant, "instant") >= add_calendar_months(activated_at, months)


# -- Level 1 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimStamp:
    """One ledger artifact as Level-1 metadata. Assessment claims carry no hypothesis."""

    key: str
    symbol: str
    timestamp: datetime
    hypothesis_id: str | None = None
    hypothesis_version: int | None = None
    hypothesis_fingerprint: str | None = None


@dataclass(frozen=True)
class OutcomeStamp:
    """One ledger outcome as Level-1 metadata: no price, no return."""

    key: str
    artifact_key: str
    symbol: str
    horizon_bars: int
    spec_fingerprint: str
    evaluation_version: int


@dataclass(frozen=True)
class LevelOneEvidence:
    """Everything the stop rule may see."""

    activated_at: datetime
    claims: tuple[ClaimStamp, ...]
    outcomes: tuple[OutcomeStamp, ...]
    excluded_artifact_keys: frozenset[str] = frozenset()
    excluded_outcome_keys: frozenset[str] = frozenset()
    missed_sessions: Mapping[str, tuple[datetime, ...]] = field(default_factory=dict)


def is_reserved(timestamp: datetime, activated_at: datetime) -> bool:
    """A bar that settled at or before activation lies in the reserved interval."""
    return timestamp + DAILY_BAR_PERIOD <= activated_at


def _matches(claim: ClaimStamp, identity: HypothesisIdentity) -> bool:
    return (claim.hypothesis_id, claim.hypothesis_version, claim.hypothesis_fingerprint) == (
        identity.hypothesis_id, identity.version, identity.fingerprint)


def population_claims(
    definition: FutureValidationDefinition,
    evidence: LevelOneEvidence,
    symbol: str,
    identity: HypothesisIdentity,
) -> tuple[ClaimStamp, ...]:
    """Non-excluded, post-activation claims of ``identity`` on ``symbol``, in bar order."""
    found = [
        claim for claim in evidence.claims
        if claim.symbol == symbol and _matches(claim, identity)
        and claim.key not in evidence.excluded_artifact_keys
        and not is_reserved(claim.timestamp, evidence.activated_at)
    ]
    found.sort(key=lambda claim: claim.timestamp)
    stamps = [claim.timestamp for claim in found]
    if len(set(stamps)) != len(stamps):
        raise FutureValidationError(f"{symbol} {identity.hypothesis_id}: two claims for one bar")
    return tuple(found)


def evidence_through(evidence: LevelOneEvidence) -> datetime | None:
    """The evidence clock: when the latest legitimate post-activation claim bar settled.

    Over every claim of the frozen snapshot (any symbol, any producer) whose key
    the provenance report does not exclude and whose bar settles after
    activation; ``None`` when there is none. Bar timestamps and keys only.
    """
    settled = [
        claim.timestamp + DAILY_BAR_PERIOD for claim in evidence.claims
        if claim.key not in evidence.excluded_artifact_keys
        and not is_reserved(claim.timestamp, evidence.activated_at)
    ]
    return max(settled) if settled else None


def matured_artifact_keys(
    definition: FutureValidationDefinition, evidence: LevelOneEvidence, horizon_bars: int
) -> frozenset[str]:
    """Artifact keys with a non-excluded outcome under the horizon's frozen spec."""
    spec = definition.spec_fingerprint(horizon_bars)
    return frozenset(
        outcome.artifact_key for outcome in evidence.outcomes
        if outcome.horizon_bars == horizon_bars and outcome.spec_fingerprint == spec
        and outcome.evaluation_version == definition.evaluation_version
        and outcome.key not in evidence.excluded_outcome_keys
    )


def matured_claim_counts(
    definition: FutureValidationDefinition, evidence: LevelOneEvidence
) -> dict[str, int]:
    """Per symbol: population trend_alignment claims with a matured primary-horizon outcome."""
    matured = matured_artifact_keys(definition, evidence, definition.primary_horizon_bars)
    return {
        symbol: sum(1 for claim in population_claims(
            definition, evidence, symbol, definition.primary_hypothesis) if claim.key in matured)
        for symbol in definition.symbols
    }


def cutoffs(
    definition: FutureValidationDefinition, evidence: LevelOneEvidence
) -> dict[str, datetime | None]:
    """``C_s`` per symbol: the latest population primary claim with a matured h20 outcome."""
    matured = matured_artifact_keys(definition, evidence, definition.primary_horizon_bars)
    result: dict[str, datetime | None] = {}
    for symbol in definition.symbols:
        stamps = [claim.timestamp for claim in population_claims(
            definition, evidence, symbol, definition.primary_hypothesis) if claim.key in matured]
        result[symbol] = max(stamps) if stamps else None
    return result


@dataclass(frozen=True)
class StopRuleEvaluation:
    """The Level-1 stop rule on the evidence clock. No research value is an input."""

    evidence_through: datetime | None
    activated_at: datetime
    e1_due: datetime
    e1_met: bool
    e2_counts: tuple[tuple[str, int], ...]
    e2_minimum: int
    e2_met: bool
    forced_due: datetime
    f_met: bool

    @property
    def unlockable(self) -> bool:
        return (self.e1_met and self.e2_met) or self.f_met

    @property
    def basis(self) -> str | None:
        if self.e1_met and self.e2_met:
            return "E1_and_E2"
        if self.f_met:
            return "F_forced_unlock"
        return None

    def to_payload(self) -> dict[str, Any]:
        return {
            "activated_at": _iso(self.activated_at),
            "basis": self.basis,
            "e1_due": _iso(self.e1_due),
            "e1_met": self.e1_met,
            "e2_counts": {symbol: count for symbol, count in self.e2_counts},
            "e2_met": self.e2_met,
            "e2_minimum": self.e2_minimum,
            "evidence_through": _iso(self.evidence_through),
            "f_met": self.f_met,
            "forced_due": _iso(self.forced_due),
            "unlockable": self.unlockable,
        }


def evaluate_stop_rule(
    definition: FutureValidationDefinition,
    *,
    activated_at: datetime,
    evidence_through: datetime | None,
    matured_counts: Mapping[str, int],
) -> StopRuleEvaluation:
    """E1 (48 months) AND E2 (750 per primary symbol), OR F (72 months), on the evidence clock.

    There is no host-clock argument: with no legitimate evidence, neither E1 nor F is met.
    """
    _require_aware(activated_at, "activated_at")
    if evidence_through is not None:
        _require_aware(evidence_through, "evidence_through")
    counts = tuple((symbol, int(matured_counts.get(symbol, 0)))
                   for symbol in definition.primary_symbols)
    minimum = definition.stop_rule_minimum_matured_claims
    def elapsed(months: int) -> bool:
        return evidence_through is not None and months_elapsed(activated_at, evidence_through,
                                                               months)

    return StopRuleEvaluation(
        evidence_through=evidence_through,
        activated_at=activated_at,
        e1_due=add_calendar_months(activated_at, definition.stop_rule_minimum_calendar_months),
        e1_met=elapsed(definition.stop_rule_minimum_calendar_months),
        e2_counts=counts,
        e2_minimum=minimum,
        e2_met=all(count >= minimum for _, count in counts),
        forced_due=add_calendar_months(activated_at, definition.forced_unlock_calendar_months),
        f_met=elapsed(definition.forced_unlock_calendar_months),
    )


# -- Level 3 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One observation artifact's claim. Supplied only after the unlock."""

    key: str
    symbol: str
    timestamp: datetime
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    state: str


@dataclass(frozen=True)
class Measurement:
    """One outcome record's forward return. Supplied only after the unlock."""

    key: str
    artifact_key: str
    horizon_bars: int
    spec_fingerprint: str
    evaluation_version: int
    forward_return: float
    reference_timestamp: datetime
    future_timestamp: datetime


@dataclass(frozen=True)
class LevelThreeEvidence:
    level_one: LevelOneEvidence
    observations: tuple[Observation, ...]
    measurements: tuple[Measurement, ...]


# -- the Phase R cell, over a session sequence ---------------------------------------------------

#: One session position: (state of the population observation or None, matured value or None).
Position = tuple[str | None, float | None]


@dataclass(frozen=True)
class CellDescription:
    """A state group beside its matched unconditional group (Phase R semantics)."""

    state: str
    stats: DescriptiveStats
    episode_count: int
    matched: DescriptiveStats
    matched_episode_count: int
    mean_delta: float | None
    median_delta: float | None


def _delta(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None:
        return None
    return value - reference


def describe_cell(sequence: Sequence[Position], state: str) -> CellDescription:
    """Phase R ``_group`` for the state and its matched row, over ``sequence`` in order."""
    matched_members = [value is not None for _, value in sequence]
    members = [value is not None and observed == state for observed, value in sequence]
    matched = DescriptiveStats.over([value for _, value in sequence if value is not None])
    stats = DescriptiveStats.over(
        [value for (_, value), member in zip(sequence, members) if member])
    return CellDescription(
        state=state,
        stats=stats,
        episode_count=count_episodes(members),
        matched=matched,
        matched_episode_count=count_episodes(matched_members),
        mean_delta=_delta(stats.mean_forward_return, matched.mean_forward_return),
        median_delta=_delta(stats.median_forward_return, matched.median_forward_return),
    )


def episode_start_values(sequence: Sequence[Position], state: str) -> list[float]:
    """The value at the first member of each maximal member run (episode-start view)."""
    values: list[float] = []
    inside = False
    for observed, value in sequence:
        member = value is not None and observed == state
        if member and not inside:
            values.append(value)  # type: ignore[arg-type]
        inside = member
    return values


# -- categories ----------------------------------------------------------------------------------

RELATION_SAME = "same_sign"
RELATION_OPPOSITE = "opposite_sign"
RELATION_ZERO_OR_UNDEFINED = "zero_or_undefined"


def sign_relation(value: float | None, reference: float) -> str:
    if value is None or value == 0:
        return RELATION_ZERO_OR_UNDEFINED
    return RELATION_SAME if (value > 0) == (reference > 0) else RELATION_OPPOSITE


def classify(
    *,
    valid: bool,
    adequate: bool,
    mean_delta: float | None,
    median_delta: float | None,
    reference_mean_delta: float,
    reference_median_delta: float,
) -> str:
    """The per-symbol category. These six inputs are the only ones that exist."""
    if not valid:
        return CATEGORY_INVALID
    if not adequate:
        return CATEGORY_INCONCLUSIVE
    mean = sign_relation(mean_delta, reference_mean_delta)
    median = sign_relation(median_delta, reference_median_delta)
    if mean == median == RELATION_SAME:
        return CATEGORY_CONSISTENT
    if mean == median == RELATION_OPPOSITE:
        return CATEGORY_REVERSED
    return CATEGORY_MIXED


def magnitude_ratio(value: float | None, reference: float) -> float | None:
    """``abs(value) / abs(reference)``; descriptive only. The reference is never zero."""
    if reference == 0:
        raise FutureValidationError("a frozen reference delta is zero")
    if value is None:
        return None
    return abs(value) / abs(reference)


# -- the analysis --------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


class _SymbolView:
    """The frozen evidence of one symbol, restricted to the cutoff."""

    def __init__(self, definition: FutureValidationDefinition, evidence: LevelThreeEvidence,
                 symbol: str, cutoff: datetime | None) -> None:
        self.definition = definition
        self.symbol = symbol
        self.cutoff = cutoff
        level_one = evidence.level_one
        self.level_one = level_one
        activated_at = level_one.activated_at
        registered = {c.timestamp for c in level_one.claims if c.symbol == symbol}
        missed = set(level_one.missed_sessions.get(symbol, ())) - registered
        self.missed = tuple(sorted(
            t for t in missed if not is_reserved(t, activated_at)
            and (cutoff is not None and t <= cutoff)))
        self.positions: tuple[datetime, ...] = () if cutoff is None else tuple(sorted(
            t for t in registered | missed
            if not is_reserved(t, activated_at) and t <= cutoff))
        self.observations = {o.key: o for o in evidence.observations if o.symbol == symbol}
        specs = dict(definition.outcome_spec_fingerprints)
        self.measurements: dict[tuple[str, int], Measurement] = {}
        for m in evidence.measurements:
            if m.artifact_key not in self.observations \
                    or m.key in level_one.excluded_outcome_keys \
                    or specs.get(m.horizon_bars) != m.spec_fingerprint \
                    or m.evaluation_version != definition.evaluation_version:
                continue
            if (m.artifact_key, m.horizon_bars) in self.measurements:
                raise FutureValidationError(f"{symbol}: two outcomes for one claim and horizon")
            self.measurements[(m.artifact_key, m.horizon_bars)] = m
        self.integrity_findings: list[str] = []

    def claims(self, identity: HypothesisIdentity) -> dict[datetime, Observation]:
        """Population observations of ``identity`` at or before the cutoff, by bar."""
        out: dict[datetime, Observation] = {}
        if self.cutoff is None:
            return out
        for stamp in population_claims(self.definition, self.level_one, self.symbol, identity):
            if stamp.timestamp > self.cutoff:
                continue
            observation = self.observations.get(stamp.key)
            if observation is None:
                raise FutureValidationError(
                    f"{self.symbol}: Level-1 claim {stamp.key} has no Level-3 observation")
            out[stamp.timestamp] = observation
        return out

    def sequence(self, identity: HypothesisIdentity, horizon: int) -> list[Position]:
        by_bar = self.claims(identity)
        sequence: list[Position] = []
        for position in self.positions:
            observation = by_bar.get(position)
            if observation is None:
                sequence.append((None, None))
                continue
            measurement = self.measurements.get((observation.key, horizon))
            if measurement is not None:
                self._check(observation, measurement)
            sequence.append((observation.state,
                             None if measurement is None else measurement.forward_return))
        return sequence

    def _check(self, observation: Observation, measurement: Measurement) -> None:
        """Lookahead / measurement integrity: the reference bar follows the claim bar."""
        if not (observation.timestamp < measurement.reference_timestamp
                <= measurement.future_timestamp):
            self.integrity_findings.append(f"lookahead:{observation.key}:{measurement.key}")
        value = measurement.forward_return
        if not isinstance(value, float) or value != value or value in (
                float("inf"), float("-inf")):
            self.integrity_findings.append(f"non_finite:{measurement.key}")


def _stats_payload(stats: DescriptiveStats) -> dict[str, Any]:
    return {
        "count": stats.sample_count,
        "max": stats.max_forward_return,
        "mean": stats.mean_forward_return,
        "median": stats.median_forward_return,
        "min": stats.min_forward_return,
    }


def _cell_payload(cell: CellDescription, *, hypothesis_id: str, horizon: int,
                  scope: str | None = None) -> dict[str, Any]:
    payload = {
        "episode_count": cell.episode_count,
        "horizon_bars": horizon,
        "hypothesis_id": hypothesis_id,
        "matched_unconditional": _stats_payload(cell.matched),
        "mean_delta": cell.mean_delta,
        "median_delta": cell.median_delta,
        "state": cell.state,
        "state_group": _stats_payload(cell.stats),
    }
    if scope is not None:
        payload["scope"] = scope
    return payload


@dataclass(frozen=True)
class PrimaryResult:
    symbol: str
    cutoff: datetime | None
    cell: CellDescription
    adequate: bool
    valid: bool
    integrity_findings: tuple[str, ...]
    category: str
    abs_mean_delta_ratio: float | None
    abs_median_delta_ratio: float | None


def primary_result(definition: FutureValidationDefinition, evidence: LevelThreeEvidence,
                   symbol: str, cutoff: datetime | None) -> PrimaryResult:
    """The primary cell, adequacy and category of one primary symbol."""
    view = _SymbolView(definition, evidence, symbol, cutoff)
    cell = describe_cell(view.sequence(definition.primary_hypothesis,
                                       definition.primary_horizon_bars),
                         definition.primary_state)
    reference = definition.reference(symbol)
    adequate = cell.episode_count >= definition.minimum_bullish_episodes
    symbol_valid = not view.integrity_findings
    return PrimaryResult(
        symbol=symbol,
        cutoff=cutoff,
        cell=cell,
        adequate=adequate,
        valid=symbol_valid,
        integrity_findings=tuple(view.integrity_findings),
        category=classify(
            valid=symbol_valid, adequate=adequate,
            mean_delta=cell.mean_delta, median_delta=cell.median_delta,
            reference_mean_delta=reference.mean_delta,
            reference_median_delta=reference.median_delta,
        ),
        abs_mean_delta_ratio=magnitude_ratio(cell.mean_delta, reference.mean_delta),
        abs_median_delta_ratio=magnitude_ratio(cell.median_delta, reference.median_delta),
    )


def secondary_results(definition: FutureValidationDefinition, evidence: LevelThreeEvidence,
                      cutoff_by_symbol: Mapping[str, datetime | None]) -> dict[str, Any]:
    """Every frozen secondary analysis. Descriptive only; never read by :func:`classify`."""
    out: dict[str, Any] = {}
    for analysis in definition.secondary_analyses:
        rows: list[dict[str, Any]] = []
        for symbol in analysis.symbols:
            view = _SymbolView(definition, evidence, symbol, cutoff_by_symbol.get(symbol))
            if analysis.view == "coverage_accounting":
                rows.append(_coverage(definition, evidence, view))
                continue
            for hypothesis_id in analysis.hypothesis_ids:
                identity = definition.hypothesis(hypothesis_id)
                for horizon in analysis.horizons:
                    sequence = view.sequence(identity, horizon)
                    for state in analysis.states:
                        if analysis.view == "episode_start":
                            values = episode_start_values(sequence, state)
                            rows.append({
                                "episode_count": len(values), "horizon_bars": horizon,
                                "hypothesis_id": hypothesis_id, "state": state,
                                "symbol": symbol,
                                "values": _stats_payload(DescriptiveStats.over(values)),
                            })
                        elif analysis.view.startswith("observation_level_by_utc_calendar_year"):
                            years = sorted({t.astimezone(timezone.utc).year
                                            for t in view.positions})
                            for year in years:
                                subsequence = [
                                    item for t, item in zip(view.positions, sequence)
                                    if t.astimezone(timezone.utc).year == year]
                                row = _cell_payload(describe_cell(subsequence, state),
                                                    hypothesis_id=hypothesis_id,
                                                    horizon=horizon, scope=str(year))
                                row["symbol"] = symbol
                                rows.append(row)
                        else:
                            row = _cell_payload(describe_cell(sequence, state),
                                                hypothesis_id=hypothesis_id, horizon=horizon)
                            row["symbol"] = symbol
                            rows.append(row)
        out[analysis.analysis_id] = {"description": analysis.description,
                                     "descriptive_only": True, "rows": rows}
    return out


def _coverage(definition: FutureValidationDefinition, evidence: LevelThreeEvidence,
              view: _SymbolView) -> dict[str, Any]:
    """Coverage at or before the cutoff only: nothing after C_s can change a v1 number."""
    level_one = evidence.level_one
    symbol = view.symbol
    identity = definition.primary_hypothesis
    cutoff = view.cutoff
    every = [c for c in level_one.claims if c.symbol == symbol and _matches(c, identity)]
    reserved = sum(1 for c in every if is_reserved(c.timestamp, level_one.activated_at))
    excluded = sum(1 for c in every if c.key in level_one.excluded_artifact_keys
                   and not is_reserved(c.timestamp, level_one.activated_at)
                   and cutoff is not None and c.timestamp <= cutoff)
    observations = view.claims(identity)
    insufficient = sum(1 for o in observations.values() if o.state == "insufficient_data")
    matured = sum(1 for o in observations.values()
                  if (o.key, definition.primary_horizon_bars) in view.measurements)
    return {
        "claims_degraded_excluded_at_or_before_cutoff": excluded,
        "claims_in_population_at_or_before_cutoff": len(observations),
        "claims_insufficient_history": insufficient,
        "claims_matured_h20": matured,
        "claims_reserved_interval_excluded": reserved,
        "claims_unmatured_h20_at_or_before_cutoff": len(observations) - matured - insufficient,
        "cutoff": _iso(cutoff),
        "missed_sessions_at_or_before_cutoff": len(view.missed),
        "symbol": symbol,
    }


# -- result ----------------------------------------------------------------------------------------

LIMITATIONS: tuple[str, ...] = (
    "Raw price basis: dividends and other distributions appear as discontinuities.",
    "No exchange calendar: sessions are the bars the provider returned; a holiday is not a "
    "missed session.",
    "An unmatured claim at or before the cutoff (pending, refused after a bar revision, or "
    "outside the fetched history) is not distinguishable per claim from the ledger and is "
    "counted together.",
    "Degraded evidence was excluded, not repaired; exclusions shrink the sample.",
    "The retrospective reference describes 2015-2024 under one retrieved dataset; the "
    "prospective period is a different market period.",
)


def build_result(
    definition: FutureValidationDefinition,
    evidence: LevelThreeEvidence,
    *,
    unlock: Mapping[str, Any],
    unlock_sha256: str,
) -> dict[str, Any]:
    """The deterministic result payload. Cutoffs come from the unlock, never recomputed."""
    recorded = unlock["cutoffs"]
    cutoff_by_symbol = {symbol: (None if recorded[symbol] is None
                                 else datetime.fromisoformat(recorded[symbol]))
                        for symbol in definition.symbols}
    if {s: _iso(c) for s, c in cutoffs(definition, evidence.level_one).items()} != dict(recorded):
        raise FutureValidationError("the evidence's cutoffs differ from the unlock's")
    primaries = [primary_result(definition, evidence, symbol, cutoff_by_symbol[symbol])
                 for symbol in definition.primary_symbols]
    primary_rows = []
    for item in primaries:
        reference = definition.reference(item.symbol)
        cell = item.cell
        primary_rows.append({
            "abs_mean_delta_ratio_vs_reference": item.abs_mean_delta_ratio,
            "abs_median_delta_ratio_vs_reference": item.abs_median_delta_ratio,
            "adequacy": {"adequate": item.adequate,
                         "bullish_episode_count": cell.episode_count,
                         "minimum_bullish_episodes": definition.minimum_bullish_episodes},
            "bullish_episode_count": cell.episode_count,
            "bullish_mean_h20": cell.stats.mean_forward_return,
            "bullish_median_h20": cell.stats.median_forward_return,
            "bullish_observation_count": cell.stats.sample_count,
            "category": item.category,
            "cutoff": _iso(item.cutoff),
            "integrity_findings": list(item.integrity_findings),
            "matched_unconditional_count": cell.matched.sample_count,
            "matched_unconditional_mean_h20": cell.matched.mean_forward_return,
            "matched_unconditional_median_h20": cell.matched.median_forward_return,
            "mean_delta": cell.mean_delta,
            "mean_sign_relation": sign_relation(cell.mean_delta, reference.mean_delta),
            "median_delta": cell.median_delta,
            "median_sign_relation": sign_relation(cell.median_delta, reference.median_delta),
            "retrospective_reference": reference.canonical_form(),
            "symbol": item.symbol,
        })
    return {
        "basis": definition.basis,
        "benchmark_policy": definition.benchmark_policy,
        "categories": [[item.symbol, item.category] for item in primaries],
        "collection_fingerprint": definition.collection_fingerprint,
        "cutoffs": {s: _iso(c) for s, c in cutoff_by_symbol.items()},
        "disclosures": list(definition.disclosures),
        "limitations": list(LIMITATIONS),
        "primary": primary_rows,
        "primary_horizon_bars": definition.primary_horizon_bars,
        "primary_hypothesis": definition.primary_hypothesis.canonical_form(),
        "primary_state": definition.primary_state,
        "primary_statistical_view": definition.primary_statistical_view,
        "provenance_policy_fingerprint": definition.provenance_policy_fingerprint,
        "question": definition.question,
        "reference_source": definition.reference_source.canonical_form(),
        "runner_version": definition.runner_version,
        "schema": definition.result_schema,
        "secondary": secondary_results(definition, evidence, cutoff_by_symbol),
        "unlock": {
            "activated_at": unlock["activated_at"],
            "basis": unlock["stop_rule"]["basis"],
            "evidence_through": unlock["stop_rule"]["evidence_through"],
            "provenance_status": unlock["provenance"]["status"],
            "sha256": unlock_sha256,
            "snapshot_identity": unlock["snapshot"]["identity"],
            "host_recorded_at": unlock["host_recorded_at"],
        },
        "validation_fingerprint": definition.fingerprint,
        "validation_id": definition.validation_id,
    }


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Canonical JSON (sorted keys, compact, ASCII, no NaN) plus a final newline."""
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_canonical(raw: bytes, label: str) -> dict[str, Any]:
    """A JSON object whose bytes are exactly :func:`canonical_bytes` of itself, or refuse."""
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FutureValidationError(f"{label} is not ASCII JSON") from exc
    if not isinstance(payload, dict) or canonical_bytes(payload) != raw:
        raise FutureValidationError(f"{label} bytes are not canonical")
    return payload


# -- report --------------------------------------------------------------------------------------


def _value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def render_report(result: Mapping[str, Any]) -> str:
    """A deterministic Markdown rendering of ``result.json``. Nothing is computed here."""
    lines: list[str] = [
        f"# {result['validation_id']} result",
        "",
        "A research comparison of forward returns only. Each primary symbol has its own "
        "category; there is no combined result.",
        "",
        f"- validation fingerprint: `{result['validation_fingerprint']}`",
        f"- collection fingerprint: `{result['collection_fingerprint']}`",
        f"- provenance policy fingerprint: `{result['provenance_policy_fingerprint']}`",
        f"- activated at: {result['unlock']['activated_at']}",
        f"- evidence through: {result['unlock']['evidence_through']} "
        f"(basis {result['unlock']['basis']}, provenance {result['unlock']['provenance_status']})",
        f"- unlock recorded at (host clock, metadata only): {result['unlock']['host_recorded_at']}",
        f"- unlock sha256: `{result['unlock']['sha256']}`",
        f"- input snapshot identity: `{result['unlock']['snapshot_identity']}`",
        "",
        "## Question",
        "",
        result["question"],
        "",
        "## Primary categories (per symbol, side by side)",
        "",
        "| symbol | category | cutoff C_s |",
        "|---|---|---|",
    ]
    for row in result["primary"]:
        lines.append(f"| {row['symbol']} | {row['category']} | {_value(row['cutoff'])} |")
    lines += ["", "## Primary statistics (trend_alignment, bullish, h20, raw)", "",
              "| symbol | metric | prospective | retrospective reference |", "|---|---|---|---|"]
    for row in result["primary"]:
        reference = row["retrospective_reference"]
        pairs = (
            ("bullish observations", row["bullish_observation_count"],
             reference["bullish_sample_count"]),
            ("bullish episodes", row["bullish_episode_count"],
             reference["bullish_episode_count"]),
            ("bullish mean", row["bullish_mean_h20"], reference["bullish_mean"]),
            ("bullish median", row["bullish_median_h20"], reference["bullish_median"]),
            ("matched unconditional count", row["matched_unconditional_count"],
             reference["matched_sample_count"]),
            ("matched unconditional mean", row["matched_unconditional_mean_h20"],
             reference["matched_mean"]),
            ("matched unconditional median", row["matched_unconditional_median_h20"],
             reference["matched_median"]),
            ("mean delta", row["mean_delta"], reference["mean_delta"]),
            ("median delta", row["median_delta"], reference["median_delta"]),
        )
        for name, prospective, retrospective in pairs:
            lines.append(f"| {row['symbol']} | {name} | {_value(prospective)} | "
                         f"{_value(retrospective)} |")
    lines += ["", "## Adequacy, sign relations and descriptive magnitude ratios", "",
              "Magnitude ratios are descriptive only and never affect a category.", "",
              "| symbol | episodes | adequate | mean sign | median sign | abs mean ratio | "
              "abs median ratio | integrity findings |",
              "|---|---|---|---|---|---|---|---|"]
    for row in result["primary"]:
        lines.append(
            f"| {row['symbol']} | {row['adequacy']['bullish_episode_count']} | "
            f"{row['adequacy']['adequate']} | {row['mean_sign_relation']} | "
            f"{row['median_sign_relation']} | "
            f"{_value(row['abs_mean_delta_ratio_vs_reference'])} | "
            f"{_value(row['abs_median_delta_ratio_vs_reference'])} | "
            f"{len(row['integrity_findings'])} |")
    lines += ["", "## Secondary analyses (descriptive only; they cannot change a category)", ""]
    for analysis_id, block in result["secondary"].items():
        lines += [f"### {analysis_id}", "", block["description"], ""]
        for row in block["rows"]:
            cells = ", ".join(f"{key}={_value(value) if not isinstance(value, dict) else _flat(value)}"
                              for key, value in sorted(row.items()))
            lines.append(f"- {cells}")
        lines.append("")
    lines += ["## Disclosures", ""]
    lines += [f"- {item}" for item in result["disclosures"]]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in result["limitations"]]
    lines.append("")
    return "\n".join(lines)


def _flat(mapping: Mapping[str, Any]) -> str:
    return "{" + ", ".join(f"{key}: {_value(value)}" for key, value in sorted(mapping.items())) \
        + "}"


__all__ = [
    "FutureValidationError",
    "DAILY_BAR_PERIOD",
    "add_calendar_months",
    "months_elapsed",
    "ClaimStamp",
    "OutcomeStamp",
    "LevelOneEvidence",
    "is_reserved",
    "evidence_through",
    "population_claims",
    "matured_artifact_keys",
    "matured_claim_counts",
    "cutoffs",
    "StopRuleEvaluation",
    "evaluate_stop_rule",
    "Observation",
    "Measurement",
    "LevelThreeEvidence",
    "CellDescription",
    "describe_cell",
    "episode_start_values",
    "sign_relation",
    "classify",
    "magnitude_ratio",
    "PrimaryResult",
    "primary_result",
    "secondary_results",
    "LIMITATIONS",
    "build_result",
    "canonical_bytes",
    "sha256_hex",
    "decode_canonical",
    "render_report",
]
