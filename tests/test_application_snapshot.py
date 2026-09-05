"""Phase 7 application layer: history policy, refresh flow and snapshot atomicity.

Every test here runs offline against a fake provider and an injected clock, so
the suite is deterministic and never reaches the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.snapshot import (
    BASIS,
    ENSEMBLE,
    HISTORY_LABELS,
    HISTORY_WINDOWS,
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    SUPPORTED_INTERVALS,
    WARMUP_BARS,
    ResearchSnapshot,
    build_ensemble,
    build_policy,
    build_snapshot,
    deduplicate_specs,
    history_window,
)
from src.assessments import AssessmentAggregationRule, AssessmentState
from src.data.models import Interval, MarketBar
from src.data.provider import MarketDataProvider, ProviderUnavailableError
from src.data.series import PriceBasis
from src.data.validation import ValidationError
from src.strategies.research import ResearchState

UTC = timezone.utc
CLOCK_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def clock() -> datetime:
    return CLOCK_NOW


class RecordingProvider(MarketDataProvider):
    """Returns a deterministic ramp and records exactly how it was called."""

    name = "fake"

    def __init__(self, count: int = 80, *, step: float = 1.0, base: float = 100.0):
        self.count = count
        self.step = step
        self.base = base
        self.calls: list[dict] = []

    def get_bars(
        self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False
    ):
        self.calls.append(
            {
                "symbol": symbol,
                "start": start,
                "end": end,
                "interval": interval,
                "include_unsettled": include_unsettled,
            }
        )
        origin = datetime(2020, 1, 1, tzinfo=UTC)
        parsed = Interval.parse(interval)
        return [
            MarketBar(
                symbol=str(symbol).strip().upper(),
                timestamp=origin + parsed.max_duration * index,
                open=self.base + self.step * index,
                high=self.base + self.step * index + 1,
                low=self.base + self.step * index - 1,
                close=self.base + self.step * index,
                volume=1_000.0,
                interval=parsed,
                source=self.name,
            )
            for index in range(self.count)
        ]

    def _fetch_bars(self, symbol, start, end, interval):  # pragma: no cover
        raise NotImplementedError


class ExplodingProvider(MarketDataProvider):
    name = "boom"

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def get_bars(self, *args, **kwargs):
        self.calls += 1
        raise self.exc

    def _fetch_bars(self, symbol, start, end, interval):  # pragma: no cover
        raise NotImplementedError


# -- interval and history policy ----------------------------------------


def test_supported_intervals_are_exactly_daily_weekly_monthly():
    assert SUPPORTED_INTERVALS == (Interval.DAY_1, Interval.WEEK_1, Interval.MONTH_1)


def test_no_intraday_interval_is_offered():
    intraday = {
        Interval.MINUTE_1,
        Interval.MINUTE_5,
        Interval.MINUTE_15,
        Interval.MINUTE_30,
        Interval.HOUR_1,
    }
    assert intraday.isdisjoint(set(SUPPORTED_INTERVALS))


@pytest.mark.parametrize(
    "interval, days",
    [
        (Interval.DAY_1, 365 * 2),
        (Interval.WEEK_1, 365 * 3),
        (Interval.MONTH_1, 365 * 10),
    ],
)
def test_history_windows_are_two_three_and_ten_years(interval, days):
    assert history_window(interval) == timedelta(days=days)


def test_every_supported_interval_has_a_window_and_a_label():
    assert set(HISTORY_WINDOWS) == set(SUPPORTED_INTERVALS)
    assert set(HISTORY_LABELS) == set(SUPPORTED_INTERVALS)


@pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
def test_window_covers_the_warmup_floor_by_whole_periods(interval):
    """The deterministic form of the warm-up check.

    ``Interval.max_duration`` is the domain's own **upper bound** on how long
    one bar's period can last, so ``window / max_duration`` is a guaranteed
    lower bound on how many periods the window spans -- no bars-per-year
    estimate is involved. Requiring twice the warm-up floor leaves room for the
    non-trading periods a calendar window inevitably contains.
    """
    periods = history_window(interval) // interval.max_duration
    assert periods >= 2 * WARMUP_BARS, (
        f"{interval.value}: window spans at most {periods} periods, which is not a "
        f"comfortable margin over the {WARMUP_BARS}-bar warm-up floor"
    )


@pytest.mark.parametrize(
    "interval, conservative_bars_per_year",
    [
        # Deliberately below the real figures (about 252 / 52 / 12): the test
        # must not fail if a year is unusually short of sessions.
        (Interval.DAY_1, 240),
        (Interval.WEEK_1, 50),
        (Interval.MONTH_1, 12),
    ],
)
def test_window_covers_the_warmup_floor_in_real_bars(
    interval, conservative_bars_per_year
):
    """Secondary check, in the units a reader actually thinks in."""
    years = history_window(interval).days / 365
    expected_bars = years * conservative_bars_per_year
    assert expected_bars >= 2 * WARMUP_BARS


def test_unsupported_interval_is_a_request_failure():
    with pytest.raises(ApplicationError) as info:
        history_window(Interval.HOUR_1)
    assert info.value.kind is FailureKind.REQUEST


def test_warmup_floor_is_fifty_one():
    assert WARMUP_BARS == 51


# -- ensemble, dedup and policy -----------------------------------------


def test_ensemble_is_exactly_the_three_repository_hypotheses():
    assert [h.hypothesis_id for h in ENSEMBLE] == [
        "trend_alignment",
        "momentum_in_trend_context",
        "trend_crossover",
    ]


def test_seven_requested_specs_deduplicate_to_three():
    hypotheses = build_ensemble()
    requested = sum(len(h.spec.required_features) for h in hypotheses)
    unique = deduplicate_specs(hypotheses)
    assert requested == 7
    assert len(unique) == 3


def test_dedup_keys_are_the_three_shared_indicators():
    keys = {spec.key for spec in deduplicate_specs(build_ensemble())}
    assert keys == {
        "sma(field='close',period=20)",
        "sma(field='close',period=50)",
        "rsi(field='close',period=14)",
    }


def test_dedup_is_keyed_on_spec_key_not_object_identity():
    """Distinct FeatureSpec objects with the same key collapse to one."""
    hypotheses = build_ensemble()
    specs = deduplicate_specs(hypotheses)
    keys = [spec.key for spec in specs]
    assert len(keys) == len(set(keys))


def test_policy_minimum_is_two():
    assert MINIMUM_SUFFICIENT_OBSERVATIONS == 2
    assert build_policy(build_ensemble()).minimum_sufficient_observations == 2


def test_policy_uses_the_live_identities_of_the_three_hypotheses():
    hypotheses = build_ensemble()
    policy = build_policy(hypotheses)
    assert [entry.hypothesis_id for entry in policy.hypotheses] == [
        h.hypothesis_id for h in hypotheses
    ]
    assert [entry.fingerprint for entry in policy.hypotheses] == [
        h.fingerprint for h in hypotheses
    ]


def test_policy_aggregation_rule_is_directional_presence_v1():
    rule = build_policy(build_ensemble()).aggregation_rule
    assert rule is AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1


# -- refresh flow --------------------------------------------------------


def test_empty_symbol_does_not_fetch():
    provider = RecordingProvider()
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "", Interval.DAY_1, now=clock)
    assert provider.calls == []
    assert info.value.kind is FailureKind.REQUEST


def test_whitespace_symbol_does_not_fetch():
    provider = RecordingProvider()
    with pytest.raises(ApplicationError):
        build_snapshot(provider, "   ", Interval.DAY_1, now=clock)
    assert provider.calls == []


def test_refresh_always_calls_the_provider():
    provider = RecordingProvider()
    build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
def test_provider_is_called_with_settled_bars_only(interval):
    provider = RecordingProvider()
    build_snapshot(provider, "AAPL", interval, now=clock)
    assert provider.calls[0]["include_unsettled"] is False


@pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
def test_fetch_window_matches_the_interval_policy(interval):
    provider = RecordingProvider()
    build_snapshot(provider, "AAPL", interval, now=clock)
    call = provider.calls[0]
    assert call["end"] == CLOCK_NOW
    assert call["start"] == CLOCK_NOW - history_window(interval)
    assert call["interval"] is interval


def test_snapshot_is_raw_basis_only():
    snapshot = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.basis is PriceBasis.RAW
    assert snapshot.series.basis is PriceBasis.RAW
    assert BASIS is PriceBasis.RAW


def test_snapshot_is_frozen():
    snapshot = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    with pytest.raises(Exception):
        snapshot.symbol = "OTHER"


def test_snapshot_features_mapping_is_read_only():
    """Regression: a frozen dataclass around a plain dict is only half-frozen."""
    snapshot = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    with pytest.raises(TypeError):
        snapshot.features["sma(field='close',period=20)"] = None


def test_built_at_is_timezone_aware_and_comes_from_the_injected_clock():
    snapshot = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.built_at == CLOCK_NOW
    assert snapshot.built_at.tzinfo is not None


def test_snapshot_rejects_a_naive_built_at():
    with pytest.raises(ApplicationError):
        ResearchSnapshot(
            symbol="AAPL",
            interval=Interval.DAY_1,
            basis=PriceBasis.RAW,
            source="fake",
            series=None,
            features={},
            decision_index=None,
            observations=(),
            assessment=None,
            policy_fingerprint="x",
            history_label="x",
            built_at=datetime(2026, 1, 1),
        )


def test_deterministic_given_a_fixed_provider_and_clock():
    first = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    second = build_snapshot(RecordingProvider(), "AAPL", Interval.DAY_1, now=clock)
    assert first.built_at == second.built_at
    assert first.assessment.state is second.assessment.state
    assert first.assessment.assessment_as_of == second.assessment.assessment_as_of
    assert first.policy_fingerprint == second.policy_fingerprint
    assert [o.state for o in first.observations] == [o.state for o in second.observations]


# -- coherence -----------------------------------------------------------


def test_snapshot_components_all_derive_from_one_series():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    series = snapshot.series
    assert snapshot.symbol == series.symbol
    assert snapshot.source == series.source
    assert snapshot.interval is series.interval
    for feature in snapshot.features.values():
        assert feature.timestamps == series.timestamps
    for observation in snapshot.observations:
        assert observation.symbol == series.symbol
        assert observation.basis is series.basis


def test_all_observations_share_one_decision_point():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    stamps = {observation.timestamp for observation in snapshot.observations}
    assert len(stamps) == 1
    assert stamps.pop() == snapshot.series[snapshot.decision_index].timestamp


def test_decision_index_is_the_latest_settled_bar():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.decision_index == snapshot.bar_count - 1


def test_assessment_is_built_from_exactly_those_observations():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    assessed = {(i.hypothesis_id, i.version, i.fingerprint) for i in snapshot.assessment.inputs}
    observed = {
        (o.hypothesis_id, o.version, o.fingerprint) for o in snapshot.observations
    }
    assert assessed == observed
    assert snapshot.assessment.counts.total == len(snapshot.observations) == 3


def test_policy_fingerprint_on_snapshot_matches_the_assessment():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.policy_fingerprint == snapshot.assessment.policy_fingerprint


def test_features_are_the_three_deduplicated_specs():
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    assert set(snapshot.features) == {
        "sma(field='close',period=20)",
        "sma(field='close',period=50)",
        "rsi(field='close',period=14)",
    }


# -- history length ------------------------------------------------------


def test_zero_bars_is_not_an_error():
    snapshot = build_snapshot(RecordingProvider(0), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.bar_count == 0
    assert snapshot.assessment is None
    assert snapshot.observations == ()
    assert snapshot.decision_index is None
    assert snapshot.has_enough_history is False
    assert snapshot.latest_bar_open is None


def test_zero_bars_keeps_the_requested_symbol_and_provider_name():
    snapshot = build_snapshot(RecordingProvider(0), "aapl", Interval.DAY_1, now=clock)
    assert snapshot.symbol == "AAPL"
    assert snapshot.source == "fake"


@pytest.mark.parametrize("count", [1, 5, 25, 49, 50])
def test_short_history_is_research_not_failure(count):
    """1-50 bars must reach the domain, not be rejected by the application."""
    snapshot = build_snapshot(RecordingProvider(count), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.bar_count == count
    assert snapshot.has_enough_history is False
    assert len(snapshot.observations) == 3
    assert snapshot.assessment is not None


def test_very_short_history_yields_insufficient_data_from_the_domain():
    snapshot = build_snapshot(RecordingProvider(5), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.assessment.state is AssessmentState.INSUFFICIENT_DATA
    assert all(
        o.state is ResearchState.INSUFFICIENT_DATA for o in snapshot.observations
    )


def test_fifty_bars_still_leaves_the_crossover_hypothesis_warming_up():
    """The floor is 51 because trend_crossover needs a prior settled sma(50)."""
    snapshot = build_snapshot(RecordingProvider(50), "AAPL", Interval.DAY_1, now=clock)
    by_id = {o.hypothesis_id: o.state for o in snapshot.observations}
    assert by_id["trend_crossover"] is ResearchState.INSUFFICIENT_DATA


def test_fifty_one_bars_lets_every_hypothesis_classify():
    snapshot = build_snapshot(RecordingProvider(51), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.has_enough_history is True
    assert all(
        o.state is not ResearchState.INSUFFICIENT_DATA for o in snapshot.observations
    )
    assert snapshot.assessment.counts.sufficient == 3


# -- failure atomicity ---------------------------------------------------


def test_provider_error_is_classified_as_provider():
    provider = ExplodingProvider(ProviderUnavailableError("upstream down"))
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.PROVIDER
    assert info.value.step == "market data"


def test_validation_error_is_classified_as_data_quality():
    provider = ExplodingProvider(ValidationError("bad bars"))
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.DATA_QUALITY


def test_plain_value_error_is_classified_as_request():
    provider = ExplodingProvider(ValueError("bad request"))
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.REQUEST


def test_unexpected_exception_is_classified_as_unexpected():
    provider = ExplodingProvider(RuntimeError("kaboom"))
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.UNEXPECTED


def test_failure_before_assessment_publishes_no_partial_snapshot(monkeypatch):
    """A build that dies after fetching must return nothing at all."""
    import src.application.snapshot as module

    def explode(observations, policy):
        raise RuntimeError("assessment blew up")

    monkeypatch.setattr(module, "assess", explode)
    provider = RecordingProvider(80)
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.step == "assessment"
    assert provider.calls, "the provider was reached before the failure"


def test_caller_keeps_the_previous_snapshot_when_a_refresh_fails():
    """The atomicity contract, exercised the way the dashboard uses it."""
    good = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    current = good
    try:
        current = build_snapshot(
            ExplodingProvider(ProviderUnavailableError("down")),
            "AAPL",
            Interval.DAY_1,
            now=clock,
        )
    except ApplicationError:
        pass
    assert current is good


def test_feature_failure_is_reported_at_the_feature_step(monkeypatch):
    import src.application.snapshot as module

    def explode(series, specs):
        raise RuntimeError("features blew up")

    monkeypatch.setattr(module, "build_evidence", explode)
    with pytest.raises(ApplicationError) as info:
        build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    assert info.value.step == "features"


# -- adversarial: a snapshot must describe what was requested ------------


class RogueProvider(MarketDataProvider):
    """A mis-written adapter that ignores the requested symbol and interval."""

    name = "rogue"

    def __init__(self, symbol: str, interval: Interval, count: int = 80):
        self.symbol = symbol
        self.interval = interval
        self.count = count

    def get_bars(
        self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False
    ):
        origin = datetime(2020, 1, 1, tzinfo=UTC)
        return [
            MarketBar(
                symbol=self.symbol,
                timestamp=origin + self.interval.max_duration * index,
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
                interval=self.interval,
                source=self.name,
            )
            for index in range(self.count)
        ]

    def _fetch_bars(self, symbol, start, end, interval):  # pragma: no cover
        raise NotImplementedError


def test_a_series_for_the_wrong_symbol_is_refused():
    """Regression: the snapshot answered a question nobody asked.

    A snapshot built from MSFT bars under an AAPL request was fully
    self-consistent and entirely wrong.
    """
    provider = RogueProvider("MSFT", Interval.DAY_1)
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.DOMAIN
    assert "MSFT" in info.value.message and "AAPL" in info.value.message


def test_a_series_for_the_wrong_interval_is_refused():
    """Regression: the snapshot contradicted itself.

    Daily bars returned for a weekly request produced a snapshot whose
    ``interval`` and ``history_label`` announced weekly history while its
    ``series`` held daily bars.
    """
    provider = RogueProvider("AAPL", Interval.DAY_1)
    with pytest.raises(ApplicationError) as info:
        build_snapshot(provider, "AAPL", Interval.WEEK_1, now=clock)
    assert info.value.kind is FailureKind.DOMAIN
    assert "1d" in info.value.message and "1wk" in info.value.message


def test_a_mismatched_series_publishes_no_snapshot():
    """The refusal is atomic like every other failure."""
    previous = build_snapshot(RecordingProvider(80), "AAPL", Interval.DAY_1, now=clock)
    current = previous
    try:
        current = build_snapshot(
            RogueProvider("MSFT", Interval.DAY_1), "AAPL", Interval.DAY_1, now=clock
        )
    except ApplicationError:
        pass
    assert current is previous


def test_a_correctly_answered_request_still_builds():
    """The guard must not reject the ordinary case."""
    snapshot = build_snapshot(
        RogueProvider("AAPL", Interval.WEEK_1), "aapl", Interval.WEEK_1, now=clock
    )
    assert snapshot.symbol == "AAPL"
    assert snapshot.interval is Interval.WEEK_1
    assert snapshot.series.interval is Interval.WEEK_1


@pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
def test_every_snapshot_agrees_with_its_own_series(interval):
    """The invariant the guard protects, stated directly."""
    snapshot = build_snapshot(RecordingProvider(80), "AAPL", interval, now=clock)
    assert snapshot.interval is snapshot.series.interval
    assert snapshot.symbol == snapshot.series.symbol
    assert snapshot.source == snapshot.series.source
    assert snapshot.history_label == HISTORY_LABELS[snapshot.series.interval]


class ImposterProvider(RecordingProvider):
    """Tags its bars with a source other than its own name."""

    name = "honest"

    def get_bars(self, *args, **kwargs):
        bars = super().get_bars(*args, **kwargs)
        return [bar.with_source("IMPOSTER") for bar in bars]


def test_bars_credited_to_a_provider_that_was_never_queried_are_refused():
    """Regression: the market panel would have published a false attribution.

    ``MarketDataProvider.name`` is documented as the value written into
    ``MarketBar.source``, but Phase 1 validates only symbol and interval, so a
    mis-written adapter could make the dashboard say "Snapshot built from
    IMPOSTER" for data it fetched from somewhere else.
    """
    with pytest.raises(ApplicationError) as info:
        build_snapshot(ImposterProvider(60), "AAPL", Interval.DAY_1, now=clock)
    assert info.value.kind is FailureKind.DOMAIN
    assert "IMPOSTER" in info.value.message and "honest" in info.value.message


def test_the_snapshot_source_is_the_provider_that_was_queried():
    snapshot = build_snapshot(RecordingProvider(60), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.source == "fake"
    assert snapshot.series.source == "fake"


# -- the warm-up floor is an ensemble requirement, not a hard law -------


def test_fifty_bars_can_already_produce_a_directional_assessment():
    """The 51-bar floor is where *every* hypothesis can classify.

    Documented behaviour, asserted so the wording and the code cannot drift:
    two hypotheses reach the policy minimum of two on bar 50, so an assessment
    is legitimately reachable one bar before the floor.
    """
    snapshot = build_snapshot(RecordingProvider(50), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.has_enough_history is False
    assert snapshot.assessment.state is not AssessmentState.INSUFFICIENT_DATA
    assert snapshot.assessment.counts.sufficient == MINIMUM_SUFFICIENT_OBSERVATIONS


@pytest.mark.parametrize("count", [1, 25, 48, 49])
def test_below_fifty_bars_no_hypothesis_can_classify(count):
    snapshot = build_snapshot(RecordingProvider(count), "AAPL", Interval.DAY_1, now=clock)
    assert snapshot.assessment.state is AssessmentState.INSUFFICIENT_DATA
    assert snapshot.assessment.counts.sufficient == 0


def test_the_documented_boundary_matches_the_implementation():
    """The exact bar count at which an assessment first becomes possible."""
    first_directional = next(
        count
        for count in range(1, 60)
        if build_snapshot(
            RecordingProvider(count), "AAPL", Interval.DAY_1, now=clock
        ).assessment.state
        is not AssessmentState.INSUFFICIENT_DATA
    )
    assert first_directional == 50
    full = next(
        count
        for count in range(1, 60)
        if build_snapshot(
            RecordingProvider(count), "AAPL", Interval.DAY_1, now=clock
        ).assessment.counts.sufficient
        == 3
    )
    assert full == WARMUP_BARS == 51
