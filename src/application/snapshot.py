"""Build one coherent research snapshot from a market-data provider.

    provider -> BarSeries -> features -> observations -> assessment -> Snapshot

This module **orchestrates**; it decides nothing about research. Every value it
produces comes from a Phase 1-6 public API, and the only rules it owns are the
dashboard's own configuration: which intervals are offered, how much history
each needs, and which hypotheses form the ensemble.

Why a snapshot is a single frozen object
----------------------------------------
The dashboard's worst failure would be showing fresh bars beside a stale
assessment. Building every component inside one call, from one fetched series,
and publishing the result as one immutable record makes that state
*unrepresentable* rather than merely unlikely: there is no code path that
updates one field.

If any step raises, nothing is published and the caller keeps its previous
snapshot (see :func:`build_snapshot`).

History windows are derived, not chosen
---------------------------------------
The ensemble needs :data:`WARMUP_BARS` settled bars before every hypothesis can
classify. A window is therefore looked up from the interval rather than typed
by a user: a two-year window is ample for daily bars but yields 24 monthly
bars, which would leave a monthly view permanently ``INSUFFICIENT_DATA``.
:data:`HISTORY_WINDOWS` is checked against that floor by test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from src.assessments import (
    AssessmentPolicy,
    HypothesisIdentity,
    ResearchAssessment,
    assess,
)
from src.data.models import Interval
from src.data.provider import MarketDataProvider
from src.data.series import BarSeries, PriceBasis
from src.features.base import FeatureSeries
from src.strategies import (
    MomentumInTrendContext,
    ResearchHypothesis,
    ResearchObservation,
    TrendAlignment,
    TrendCrossover,
    build_evidence,
)
from src.strategies.spec import FeatureSpec

from .errors import ApplicationError, FailureKind, classify

#: Intervals the dashboard offers. Deliberately no intraday: the development
#: provider keeps roughly 30 days of 1-minute history, which is fewer bars than
#: the ensemble needs, so an intraday view would be permanently insufficient.
SUPPORTED_INTERVALS: tuple[Interval, ...] = (
    Interval.DAY_1,
    Interval.WEEK_1,
    Interval.MONTH_1,
)

#: Settled bars the ensemble needs before every hypothesis can classify:
#: ``sma(50)`` produces its first value on bar 50, and ``trend_crossover``
#: declares ``lookback = 1``, so it needs a prior bar that also has one.
WARMUP_BARS: int = 51

#: Calendar window fetched per interval, sized from :data:`WARMUP_BARS`.
HISTORY_WINDOWS: Mapping[Interval, timedelta] = {
    Interval.DAY_1: timedelta(days=365 * 2),
    Interval.WEEK_1: timedelta(days=365 * 3),
    Interval.MONTH_1: timedelta(days=365 * 10),
}

#: Human wording for each window, shown so the user can see what was requested
#: without being able to edit it.
HISTORY_LABELS: Mapping[Interval, str] = {
    Interval.DAY_1: "2 years of daily bars",
    Interval.WEEK_1: "3 years of weekly bars",
    Interval.MONTH_1: "10 years of monthly bars",
}

#: The dashboard's fixed ensemble: every hypothesis the repository has.
#: Selecting a subset would be an unexplainable research choice.
ENSEMBLE: tuple[type[ResearchHypothesis], ...] = (
    TrendAlignment,
    MomentumInTrendContext,
    TrendCrossover,
)

#: How many of the three must actually classify for a directional result.
#: One would let a single hypothesis speak while two are still warming up;
#: three would make any warm-up produce ``INSUFFICIENT_DATA``.
MINIMUM_SUFFICIENT_OBSERVATIONS: int = 2

#: Phase 7 reads raw prices only. Adjustment needs corporate-action data the
#: dashboard has no source for, and offering the toggle without it would be a
#: control that cannot work.
BASIS: PriceBasis = PriceBasis.RAW

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_provider() -> MarketDataProvider:
    """The provider the dashboard uses when none is injected.

    Constructed here rather than in the UI so :mod:`src.dashboard` never has to
    import a data-layer module. Construction opens no connection; the network
    is touched only by an explicit Refresh.
    """
    from src.data.providers.yahoo import YahooFinanceProvider

    return YahooFinanceProvider()


#: Human names for the ensemble, keyed by hypothesis id, for the UI to label
#: panels with. Read from the classes themselves, never retyped.
def display_names() -> dict[str, str]:
    return {
        hypothesis.hypothesis_id: hypothesis.display_name for hypothesis in ENSEMBLE
    }


def build_ensemble() -> tuple[ResearchHypothesis, ...]:
    """Instantiate the fixed ensemble."""
    return tuple(hypothesis() for hypothesis in ENSEMBLE)


def deduplicate_specs(
    hypotheses: Sequence[ResearchHypothesis],
) -> tuple[FeatureSpec, ...]:
    """Collect required feature specs, keeping one per :attr:`FeatureSpec.key`.

    Necessary, not defensive: the three hypotheses request seven specs between
    them but share ``sma(20)``, ``sma(50)`` and ``rsi(14)``, and
    :func:`~src.strategies.evidence.build_evidence` **raises** on a duplicate
    rather than quietly collapsing it. Order is preserved so the computation
    order is deterministic.
    """
    unique: dict[str, FeatureSpec] = {}
    for hypothesis in hypotheses:
        for spec in hypothesis.spec.required_features:
            unique.setdefault(spec.key, spec)
    return tuple(unique.values())


def build_policy(hypotheses: Sequence[ResearchHypothesis]) -> AssessmentPolicy:
    """Pin the ensemble's *live* identities into an assessment policy.

    Identities are read from each hypothesis' current ``spec``, so a
    re-parameterised hypothesis changes the policy fingerprint instead of
    silently reusing the old one.
    """
    return AssessmentPolicy(
        tuple(
            HypothesisIdentity(
                hypothesis.spec.hypothesis_id,
                hypothesis.spec.version,
                hypothesis.fingerprint,
            )
            for hypothesis in hypotheses
        ),
        MINIMUM_SUFFICIENT_OBSERVATIONS,
        "directional_presence_v1",
    )


def _require_answers_the_request(
    series: BarSeries,
    symbol: str,
    interval: Interval,
    provider: MarketDataProvider,
) -> None:
    """Refuse a series that does not describe what was asked for.

    ``MarketDataProvider.get_bars`` is a template method that already checks
    this for a well-behaved adapter, but the snapshot's whole purpose is to be
    coherent, so it verifies its own contract rather than inheriting it. Without
    this, an adapter that ignored the request would produce a snapshot that
    contradicts itself -- ``interval`` and ``history_label`` describing weekly
    bars while ``series`` held daily ones -- and every number on the page would
    look entirely plausible.

    This is the same failure ``BarSeries`` exists to prevent one layer down, and
    it is refused for the same reason: a mislabelled series is not degraded
    research, it is wrong research that reads as normal.
    """
    requested = str(symbol).strip().upper()
    if series.symbol != requested:
        raise ApplicationError(
            FailureKind.DOMAIN,
            "market data",
            f"the data source returned {series.symbol!r} bars for a {requested!r} "
            "request; a snapshot must describe the symbol that was asked for",
        )
    if series.interval is not interval:
        raise ApplicationError(
            FailureKind.DOMAIN,
            "market data",
            f"the data source returned {series.interval.value!r} bars for a "
            f"{interval.value!r} request; the snapshot would describe a history "
            "window it does not hold",
        )
    # ``MarketDataProvider.name`` is documented as the value written into
    # ``MarketBar.source``, but nothing in Phase 1 checks the two agree --
    # ``get_bars`` validates symbol and interval only. The dashboard prints
    # "Snapshot built from <source>", so it is the layer that would publish a
    # false attribution, and it is therefore the layer that checks.
    if provider.name and series.source != provider.name:
        raise ApplicationError(
            FailureKind.DOMAIN,
            "market data",
            f"bars from provider {provider.name!r} are tagged "
            f"{series.source!r}; the snapshot would credit a source that was "
            "never queried",
        )


def history_window(interval: Interval) -> timedelta:
    """Fetch window for ``interval``. Raises for an unsupported interval."""
    interval = Interval.parse(interval)
    if interval not in HISTORY_WINDOWS:
        supported = ", ".join(i.value for i in SUPPORTED_INTERVALS)
        raise ApplicationError(
            FailureKind.REQUEST,
            "interval",
            f"{interval.value!r} is not offered by the dashboard; supported: {supported}",
        )
    return HISTORY_WINDOWS[interval]


@dataclass(frozen=True)
class ResearchSnapshot:
    """One coherent research build. Immutable, and never partially updated.

    Every field derives from the single ``series`` fetched in one
    :func:`build_snapshot` call, so "new bars with an old assessment" cannot
    occur.

    ``assessment`` is ``None`` in exactly one case: the series was too short
    for any hypothesis to be evaluated at all. That is a factual shortage of
    history, not a failure, and the snapshot still carries the bars and
    features so the user can see what *is* available.
    """

    symbol: str
    interval: Interval
    basis: PriceBasis
    source: str
    series: BarSeries
    features: Mapping[str, FeatureSeries]
    decision_index: int | None
    observations: tuple[ResearchObservation, ...]
    assessment: ResearchAssessment | None
    policy_fingerprint: str
    history_label: str
    built_at: datetime
    warmup_bars: int = WARMUP_BARS

    def __post_init__(self) -> None:
        if self.built_at.tzinfo is None or self.built_at.utcoffset() is None:
            raise ApplicationError(
                FailureKind.REQUEST, "snapshot", "built_at must be timezone-aware"
            )
        # A frozen dataclass holding a plain dict is only half-frozen: the
        # mapping would still be mutable through the "immutable" snapshot.
        # Publishing a read-only view closes that hole.
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))

    @property
    def bar_count(self) -> int:
        return len(self.series)

    @property
    def has_enough_history(self) -> bool:
        return self.bar_count >= self.warmup_bars

    @property
    def latest_bar_open(self) -> datetime | None:
        return self.series[-1].timestamp if len(self.series) else None


def build_snapshot(
    provider: MarketDataProvider,
    symbol: str,
    interval: Interval,
    *,
    now: Clock = _utc_now,
) -> ResearchSnapshot:
    """Fetch, compute and assess in one atomic operation.

    The snapshot is returned only when every stage succeeded; any failure
    raises :class:`~src.application.errors.ApplicationError` so the caller can
    keep whatever it was already showing. Nothing is published half-built.

    Only settled bars are requested. The in-progress bar is excluded because
    its values move, so an assessment built on it would not be reproducible --
    and the dashboard deliberately offers no control to include it.

    ``now`` is injected so tests are deterministic; no domain module reads a
    clock, and this layer is the only place one is read.
    """
    if not symbol or not symbol.strip():
        raise ApplicationError(
            FailureKind.REQUEST, "symbol", "Enter a symbol before refreshing."
        )

    interval = Interval.parse(interval)
    window = history_window(interval)
    built_at = now()
    start, end = built_at - window, built_at

    step = "market data"
    try:
        bars = provider.get_bars(
            symbol, start, end, interval, include_unsettled=False
        )
        series = BarSeries.from_bars(bars, basis=BASIS) if bars else None
        if series is not None:
            _require_answers_the_request(series, symbol, interval, provider)

        step = "features"
        hypotheses = build_ensemble()
        specs = deduplicate_specs(hypotheses)
        policy = build_policy(hypotheses)

        features: dict[str, FeatureSeries] = {}
        observations: tuple[ResearchObservation, ...] = ()
        assessment: ResearchAssessment | None = None
        decision_index: int | None = None

        if series is not None and len(series) >= 1:
            evidence = build_evidence(series, specs)
            # EvidenceSet.features is already keyed by canonical spec key and
            # is a read-only mapping; copy it rather than re-deriving anything.
            features = {spec.key: evidence.features[spec.key] for spec in specs}

            step = "research"
            decision_index = len(series) - 1
            observations = tuple(
                hypothesis.evaluate_at(evidence, decision_index)
                for hypothesis in hypotheses
            )

            step = "assessment"
            assessment = assess(observations, policy)

        return ResearchSnapshot(
            symbol=series.symbol if series is not None else symbol.strip().upper(),
            interval=interval,
            basis=BASIS,
            source=series.source if series is not None else provider.name,
            series=series
            if series is not None
            else BarSeries(
                symbol=symbol.strip().upper(),
                interval=interval,
                source=provider.name,
                basis=BASIS,
                bars=(),
            ),
            features=features,
            decision_index=decision_index,
            observations=observations,
            assessment=assessment,
            policy_fingerprint=policy.fingerprint,
            history_label=HISTORY_LABELS[interval],
            built_at=built_at,
        )
    except Exception as exc:  # re-raised as a classified ApplicationError
        raise classify(exc, step) from exc


__all__ = [
    "default_provider",
    "display_names",
    "SUPPORTED_INTERVALS",
    "WARMUP_BARS",
    "HISTORY_WINDOWS",
    "HISTORY_LABELS",
    "ENSEMBLE",
    "MINIMUM_SUFFICIENT_OBSERVATIONS",
    "BASIS",
    "ResearchSnapshot",
    "build_snapshot",
    "build_ensemble",
    "build_policy",
    "deduplicate_specs",
    "history_window",
]
