"""Phase 12B: evaluating a tracked artifact against settled bars.

``evaluate_artifact`` joins a Phase 12 artifact to Phase 4's measurement of
its market point and returns exactly one trusted ``OutcomeRecord`` or a
deterministic statement of why there is none. Everything here is
caller-supplied; the tests pin what is refused, what is pending, what is
measured, and -- most importantly -- that the numbers are Phase 4's and that
nothing after the horizon can reach them.

Settledness
-----------
Several tests move ``evaluated_at`` around ``future_timestamp``. They test
the record's **temporal sanity bound** only: bar timestamps are opens, so
``evaluated_at > future_timestamp`` is necessary and is not evidence that
the future bar had settled. Settled input is the caller's declaration (the
fetch layer's ``include_unsettled=False``); nothing in ``src.outcomes``
computes it, and these tests do not pretend otherwise.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from src.assessments.assessment import AssessmentReasonCode, AssessmentState
from src.data.models import Interval, MarketBar
from src.data.series import BarSeries, PriceBasis
from src.evaluation import EvaluationError, ForwardMeasurement, OutcomeSpec, OutcomeStatus, measure_forward
from src.outcomes import (
    EVALUATION_VERSION,
    ArtifactOrigin,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
    OutcomeTrackingError,
    RefusalReason,
    TrackingResult,
    TrackingStatus,
    bar_fingerprint,
    bars_fingerprint,
    evaluate_artifact,
    outcome_key,
)
from src.strategies.research import ReasonCode, ResearchState
from tests.evaluation_lookahead import perturb_after

UTC = timezone.utc
START = datetime(2024, 1, 1, tzinfo=UTC)
SOURCE = "yfinance"
POLICY_FP = "fedcba9876543210"


def bar(i, *, symbol="AAPL", interval="1d", source=SOURCE, start=START, step=None, **over):
    """Bar n (1-based): open n*100, high +90, low -10, close +50, volume 1000+i."""
    step = step or Interval.parse(interval).max_duration
    fields = dict(symbol=symbol, timestamp=start + step * i, open=(i + 1) * 100.0,
                  high=(i + 1) * 100.0 + 90.0, low=(i + 1) * 100.0 - 10.0,
                  close=(i + 1) * 100.0 + 50.0, volume=1000.0 + i, interval=interval, source=source)
    fields.update(over)
    return MarketBar(**fields)


def series(count=8, *, basis=PriceBasis.RAW, **over):
    return BarSeries.from_bars([bar(i, **over) for i in range(count)], basis=basis)


def observation_artifact(s, index=0, *, state=ResearchState.BULLISH, **over):
    b = s[index]
    fields = dict(
        symbol=s.symbol, interval=s.interval, basis=s.basis, timestamp=b.timestamp,
        state=state, reason_codes=(ReasonCode.FAST_ABOVE_SLOW,), source=s.source,
        data_cutoff=b.timestamp, recorded_at=b.timestamp + timedelta(hours=26),
        observation_bar_fingerprint=bar_fingerprint(b), origin=ArtifactOrigin.SNAPSHOT,
        hypothesis_id="trend_alignment", hypothesis_version=1,
        hypothesis_fingerprint="0011223344556677",
    )
    fields.update(over)
    return ObservationArtifact(**fields)


def assessment_artifact(s, index=0, *, state=AssessmentState.BULLISH, **over):
    b = s[index]
    codes = {
        AssessmentState.BULLISH: AssessmentReasonCode.UNANIMOUS_BULLISH,
        AssessmentState.BEARISH: AssessmentReasonCode.UNANIMOUS_BEARISH,
        AssessmentState.NEUTRAL: AssessmentReasonCode.UNANIMOUS_NEUTRAL,
        AssessmentState.CONFLICTED: AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,
        AssessmentState.INSUFFICIENT_DATA: AssessmentReasonCode.INSUFFICIENT_EVIDENCE,
    }
    fields = dict(
        symbol=s.symbol, interval=s.interval, basis=s.basis, timestamp=b.timestamp,
        state=state, reason_codes=(codes[state],), source=s.source,
        data_cutoff=b.timestamp, recorded_at=b.timestamp + timedelta(hours=26),
        observation_bar_fingerprint=bar_fingerprint(b), origin=ArtifactOrigin.SNAPSHOT,
        policy_fingerprint=POLICY_FP,
    )
    fields.update(over)
    return AssessmentArtifact(**fields)


LATER = START + timedelta(days=365)


def evaluate(artifact, s, spec=None, *, evaluated_at=LATER):
    return evaluate_artifact(artifact, s, spec or OutcomeSpec(horizon_bars=3), evaluated_at=evaluated_at)


def window(s, reference_index, horizon):
    return tuple(s.bars[reference_index: reference_index + horizon])


# -- a complete evaluation -----------------------------------------------------------------------


class TestCompleteObservation:
    def test_produces_exactly_one_outcome_record(self):
        s = series()
        result = evaluate(observation_artifact(s), s)
        assert result.status is TrackingStatus.EVALUATED
        assert result.is_evaluated
        assert isinstance(result.outcome, OutcomeRecord)
        assert result.refusal is None

    def test_the_numbers_are_phase_fours(self):
        s = series()
        artifact = observation_artifact(s)
        spec = OutcomeSpec(horizon_bars=3)
        result = evaluate(artifact, s, spec)
        phase4 = measure_forward(s, spec, symbol=s.symbol, interval=s.interval, basis=s.basis,
                                 timestamp=artifact.timestamp)
        assert result.measurement == phase4
        o = result.outcome
        assert (o.reference_timestamp, o.reference_price, o.future_timestamp, o.future_price,
                o.forward_return) == (phase4.reference_timestamp, phase4.reference_price,
                                      phase4.future_timestamp, phase4.future_price,
                                      phase4.outcome_value)

    def test_hand_computed_values(self):
        s = series()
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=3)).outcome
        assert o.reference_timestamp == s.timestamps[1]
        assert o.reference_price == 200.0          # bar 2 open
        assert o.future_timestamp == s.timestamps[3]
        assert o.future_price == 450.0             # bar 4 close
        assert o.forward_return == 450.0 / 200.0 - 1.0

    def test_horizon_one(self):
        s = series()
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=1)).outcome
        assert o.horizon_bars == 1
        assert o.reference_timestamp == o.future_timestamp == s.timestamps[1]
        assert o.forward_return == 250.0 / 200.0 - 1.0

    def test_the_record_embeds_the_artifact_and_the_spec(self):
        s = series()
        artifact = observation_artifact(s)
        spec = OutcomeSpec(horizon_bars=2)
        result = evaluate(artifact, s, spec, evaluated_at=LATER)
        o = result.outcome
        assert o.artifact is artifact
        assert o.spec_fingerprint == spec.fingerprint
        assert o.horizon_bars == 2
        assert o.evaluation_version == EVALUATION_VERSION
        assert o.evaluated_at == LATER
        assert result.spec is spec and result.artifact is artifact
        assert o.outcome_key == outcome_key(artifact_key=artifact.artifact_key,
                                            spec_fingerprint=spec.fingerprint,
                                            evaluation_version=EVALUATION_VERSION)

    def test_the_artifact_and_series_are_untouched(self):
        s = series()
        artifact = observation_artifact(s)
        before_artifact = dataclasses.astuple(artifact)
        before_series = tuple(s.bars)
        evaluate(artifact, s)
        assert dataclasses.astuple(artifact) == before_artifact
        assert tuple(s.bars) == before_series

    def test_deterministic(self):
        s = series()
        artifact = observation_artifact(s)
        first = evaluate(artifact, s)
        for _ in range(3):
            assert evaluate(artifact, s) == first

    def test_a_mid_series_artifact(self):
        s = series(10)
        artifact = observation_artifact(s, 4)
        o = evaluate(artifact, s, OutcomeSpec(horizon_bars=2)).outcome
        assert o.reference_timestamp == s.timestamps[5]
        assert o.reference_price == 600.0
        assert o.future_timestamp == s.timestamps[6]
        assert o.future_price == 750.0

    def test_directional_states_all_evaluate(self):
        s = series()
        for state in (ResearchState.BULLISH, ResearchState.BEARISH, ResearchState.NEUTRAL):
            result = evaluate(observation_artifact(s, state=state), s)
            assert result.status is TrackingStatus.EVALUATED, state
            assert result.outcome.artifact.state is state


# -- pending -----------------------------------------------------------------------------------------


class TestPending:
    def test_no_reference_bar_yet(self):
        s = series(4)
        artifact = observation_artifact(s, 3)
        result = evaluate(artifact, s)
        assert result.status is TrackingStatus.PENDING
        assert result.outcome is None
        assert result.measurement.status is OutcomeStatus.NO_REFERENCE_BAR
        assert result.refusal is None

    def test_partial_horizon(self):
        s = series(4)
        artifact = observation_artifact(s, 1)
        result = evaluate(artifact, s, OutcomeSpec(horizon_bars=3))
        assert result.status is TrackingStatus.PENDING
        assert result.outcome is None
        assert result.measurement.status is OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        assert result.measurement.reference_timestamp == s.timestamps[2]

    def test_pending_is_not_partially_measured(self):
        s = series(4)
        result = evaluate(observation_artifact(s, 1), s, OutcomeSpec(horizon_bars=3))
        assert result.measurement.future_price is None
        assert result.measurement.outcome_value is None

    def test_the_same_artifact_completes_once_the_bars_arrive(self):
        full = series(8)
        artifact = observation_artifact(full, 2)
        spec = OutcomeSpec(horizon_bars=3)
        assert evaluate(artifact, full.prefix(3), spec).status is TrackingStatus.PENDING
        assert evaluate(artifact, full.prefix(5), spec).status is TrackingStatus.PENDING
        assert evaluate(artifact, full.prefix(6), spec).status is TrackingStatus.EVALUATED


# -- ineligible ----------------------------------------------------------------------------------------


class TestIneligible:
    def test_insufficient_data_observation(self):
        s = series()
        result = evaluate(observation_artifact(s, state=ResearchState.INSUFFICIENT_DATA), s)
        assert result.status is TrackingStatus.INELIGIBLE
        assert result.outcome is None and result.measurement is None and result.refusal is None

    def test_insufficient_data_assessment(self):
        s = series()
        result = evaluate(assessment_artifact(s, state=AssessmentState.INSUFFICIENT_DATA), s)
        assert result.status is TrackingStatus.INELIGIBLE
        assert result.outcome is None

    def test_phase_four_is_not_consulted(self, monkeypatch):
        import src.outcomes.tracking as tracking

        def boom(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("measure_forward was called for an ineligible artifact")

        monkeypatch.setattr(tracking, "measure_forward", boom)
        s = series()
        result = evaluate(observation_artifact(s, state=ResearchState.INSUFFICIENT_DATA), s)
        assert result.status is TrackingStatus.INELIGIBLE

    def test_type_validation_still_precedes_the_short_circuit(self):
        # Ineligibility skips series *work*, not input validation: a
        # malformed call is a malformed call whatever the artifact says.
        s = series()
        ineligible = observation_artifact(s, state=ResearchState.INSUFFICIENT_DATA)
        with pytest.raises(OutcomeTrackingError, match="BarSeries"):
            evaluate(ineligible, list(s.bars))
        with pytest.raises(OutcomeTrackingError, match="OutcomeSpec"):
            evaluate(ineligible, s, "spec")
        with pytest.raises(OutcomeTrackingError, match="evaluated_at"):
            evaluate(ineligible, s, evaluated_at=None)

    def test_ineligibility_is_decided_from_the_artifact_alone(self):
        # Even a series that would otherwise be refused: no series work is done.
        s = series()
        other = series(source="other")
        result = evaluate(observation_artifact(s, state=ResearchState.INSUFFICIENT_DATA), other)
        assert result.status is TrackingStatus.INELIGIBLE


# -- source check ---------------------------------------------------------------------------------------


class TestSourceCheck:
    def test_identical_bars_from_another_provider_are_refused(self):
        s = series(source="yfinance")
        artifact = observation_artifact(s)
        relabelled = BarSeries.from_bars([b.with_source("alpaca") for b in s.bars], basis=s.basis)
        assert relabelled.values("close") == s.values("close")
        assert relabelled.timestamps == s.timestamps
        result = evaluate(artifact, relabelled)
        assert result.status is TrackingStatus.REFUSED
        assert result.refusal is RefusalReason.SOURCE_MISMATCH
        assert result.outcome is None and result.measurement is None

    def test_the_source_check_is_independent_of_the_bar_fingerprint(self):
        # bar_fingerprint deliberately excludes source; the refusal must come
        # from the source comparison, not from a fingerprint difference.
        s = series(source="yfinance")
        other = s[0].with_source("alpaca")
        assert bar_fingerprint(other) == bar_fingerprint(s[0])
        result = evaluate(observation_artifact(s), BarSeries.from_bars(
            [b.with_source("alpaca") for b in s.bars], basis=s.basis))
        assert result.refusal is RefusalReason.SOURCE_MISMATCH

    def test_the_source_check_precedes_measurement(self, monkeypatch):
        import src.outcomes.tracking as tracking

        def boom(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("measure_forward was called despite a source mismatch")

        monkeypatch.setattr(tracking, "measure_forward", boom)
        s = series(source="yfinance")
        result = evaluate(observation_artifact(s), series(source="alpaca"))
        assert result.refusal is RefusalReason.SOURCE_MISMATCH

    def test_source_mismatch_outranks_a_revised_bar(self):
        # Different provider AND different numbers: provenance is decided
        # first, so the refusal names the provider, not the revision.
        s = series(source="yfinance")
        other = BarSeries.from_bars([b.with_source("alpaca") for b in s.bars], basis=s.basis)
        result = evaluate(observation_artifact(s), revised(other, 0, close=150.25))
        assert result.refusal is RefusalReason.SOURCE_MISMATCH

    def test_source_comparison_is_exact(self):
        s = series(source="yfinance")
        result = evaluate(observation_artifact(s), series(source="YFinance"))
        assert result.refusal is RefusalReason.SOURCE_MISMATCH


# -- source-bar revision -----------------------------------------------------------------------------


def revised(s, index, **changes):
    bars = list(s.bars)
    bars[index] = dataclasses.replace(bars[index], **changes)
    return s.with_bars(bars)


class TestSourceBarRevision:
    @pytest.mark.parametrize("field, value", [
        ("open", 100.5), ("high", 191.0), ("low", 89.0), ("close", 150.25), ("volume", 1001.0),
    ])
    def test_a_revised_observation_bar_is_refused(self, field, value):
        s = series()
        artifact = observation_artifact(s)  # fingerprint of the original bar 0
        result = evaluate(artifact, revised(s, 0, **{field: value}))
        assert result.status is TrackingStatus.REFUSED
        assert result.refusal is RefusalReason.SOURCE_BAR_REVISED
        assert result.outcome is None and result.measurement is None

    def test_the_artifact_is_not_rebuilt(self):
        s = series()
        artifact = observation_artifact(s)
        before = artifact.observation_bar_fingerprint
        evaluate(artifact, revised(s, 0, close=150.25))
        assert artifact.observation_bar_fingerprint == before

    def test_revision_outranks_pending(self):
        # The premise is gone whether or not the future has arrived.
        s = series(2)
        artifact = observation_artifact(s, 1)  # last bar: would be NO_REFERENCE_BAR
        result = evaluate(artifact, revised(s, 1, close=250.5))
        assert result.refusal is RefusalReason.SOURCE_BAR_REVISED

    def test_a_revision_of_another_bar_is_not_a_source_bar_revision(self):
        # Revising bar 5 (outside the horizon) is invisible; revising bar 2
        # (inside it) changes the outcome's consumed-bars fingerprint but is
        # not a revision of the *claimed* bar.
        s = series()
        artifact = observation_artifact(s)
        spec = OutcomeSpec(horizon_bars=3)
        untouched = evaluate(artifact, s, spec).outcome
        assert evaluate(artifact, revised(s, 5, close=650.5), spec).outcome == untouched
        inside = evaluate(artifact, revised(s, 2, close=350.5), spec)
        assert inside.status is TrackingStatus.EVALUATED
        assert inside.outcome.consumed_bars_fingerprint != untouched.consumed_bars_fingerprint

    def test_a_stale_fingerprint_on_the_artifact_is_refused(self):
        s = series()
        artifact = observation_artifact(s, observation_bar_fingerprint="f" * 64)
        assert evaluate(artifact, s).refusal is RefusalReason.SOURCE_BAR_REVISED


# -- alignment: hard errors through Phase 4 ------------------------------------------------------------


class TestAlignmentErrors:
    def test_wrong_symbol(self):
        s = series(symbol="AAPL")
        with pytest.raises(OutcomeTrackingError, match="symbol 'AAPL' != 'MSFT'") as info:
            evaluate(observation_artifact(s), series(symbol="MSFT"))
        assert isinstance(info.value.__cause__, EvaluationError)

    def test_wrong_interval(self):
        s = series(interval="1d")
        with pytest.raises(OutcomeTrackingError, match="interval '1d' != '1h'"):
            evaluate(observation_artifact(s), series(interval="1h"))

    def test_raw_artifact_against_an_adjusted_series(self):
        raw = series(basis=PriceBasis.RAW)
        adjusted = series(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        artifact = observation_artifact(raw)
        # Same bars, same fingerprints -- only the basis differs.
        assert bar_fingerprint(adjusted[0]) == artifact.observation_bar_fingerprint
        # Artifact basis vs series basis (Phase 4 alignment) ...
        with pytest.raises(OutcomeTrackingError, match="basis 'raw' != 'split_and_dividend_adjusted'"):
            evaluate(artifact, adjusted, OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        # ... and spec basis vs series basis (Phase 4 series/spec check): never evaluated.
        with pytest.raises(OutcomeTrackingError, match="requires 'raw' prices but the series is"):
            evaluate(artifact, adjusted, OutcomeSpec(required_basis=PriceBasis.RAW))

    def test_adjusted_artifact_against_a_raw_series(self):
        raw = series(basis=PriceBasis.RAW)
        adjusted = series(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        artifact = observation_artifact(adjusted)
        with pytest.raises(OutcomeTrackingError, match="basis 'split_and_dividend_adjusted' != 'raw'"):
            evaluate(artifact, raw, OutcomeSpec(required_basis=PriceBasis.RAW))
        with pytest.raises(OutcomeTrackingError, match="requires 'split_and_dividend_adjusted' prices"):
            evaluate(artifact, raw, OutcomeSpec(required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))

    def test_a_matching_adjusted_basis_evaluates(self):
        adjusted = series(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        result = evaluate(observation_artifact(adjusted), adjusted,
                          OutcomeSpec(horizon_bars=2, required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
        assert result.status is TrackingStatus.EVALUATED
        assert result.outcome.artifact.basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED

    def test_the_artifact_timestamp_must_be_a_bar_of_the_series(self):
        s = series()
        artifact = observation_artifact(s, 2)
        without = s.with_bars(s.bars[:2] + s.bars[3:])
        with pytest.raises(OutcomeTrackingError, match="does not correspond to any bar"):
            evaluate(artifact, without)

    def test_nearest_bar_is_never_used(self):
        s = series()
        shifted = s.with_bars([b if i != 2 else dataclasses.replace(b, timestamp=b.timestamp + timedelta(seconds=1))
                               for i, b in enumerate(s.bars)])
        with pytest.raises(OutcomeTrackingError, match="never matches an approximate"):
            evaluate(observation_artifact(s, 2), shifted)

    def test_overlapping_intraday_bars_are_rejected(self):
        s = series(interval="1h", step=timedelta(minutes=30))
        with pytest.raises(OutcomeTrackingError, match="before the observation bar's period ends"):
            evaluate(observation_artifact(s), s)

    def test_the_phase_four_error_is_the_cause_not_swallowed(self):
        s = series(symbol="AAPL")
        with pytest.raises(OutcomeTrackingError) as info:
            evaluate(observation_artifact(s), series(symbol="MSFT"))
        assert isinstance(info.value.__cause__, EvaluationError)
        assert "market point does not describe this series" in str(info.value)


# -- input validation -----------------------------------------------------------------------------------


class TestInputs:
    def test_artifact_must_be_a_tracked_artifact(self):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="TrackedArtifact"):
            evaluate("artifact", s)

    def test_series_must_be_a_bar_series(self):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="BarSeries"):
            evaluate(observation_artifact(s), list(s.bars))

    def test_spec_must_be_an_outcome_spec(self):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="OutcomeSpec"):
            evaluate(observation_artifact(s), s, "spec")

    def test_evaluated_at_is_required_and_keyword_only(self):
        s = series()
        with pytest.raises(TypeError):
            evaluate_artifact(observation_artifact(s), s, OutcomeSpec())
        with pytest.raises(TypeError):
            evaluate_artifact(observation_artifact(s), s, OutcomeSpec(), LATER)

    @pytest.mark.parametrize("bad", [None, "2024-01-01", START.replace(tzinfo=None)])
    def test_evaluated_at_must_be_an_aware_datetime(self, bad):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="evaluated_at"):
            evaluate(observation_artifact(s), s, evaluated_at=bad)

    def test_evaluated_at_cannot_precede_recorded_at_for_any_status(self):
        s = series(4)
        artifact = observation_artifact(s, 3)  # would be PENDING
        with pytest.raises(OutcomeTrackingError, match="precedes recorded_at"):
            evaluate(artifact, s, evaluated_at=artifact.recorded_at - timedelta(seconds=1))
        assert evaluate(artifact, s, evaluated_at=artifact.recorded_at).status is TrackingStatus.PENDING


# -- evaluation clock: temporal sanity only, never settlement ---------------------------------------


class TestEvaluationClock:
    """These pin ``OutcomeRecord``'s bound ``evaluated_at > future_timestamp``.

    ``future_timestamp`` is the future bar's **open**; passing the bound
    proves the bar had opened, not that it had settled. Settlement is the
    caller's declaration about the series and is not computed here.
    """

    def _future_open(self, s, spec):
        # artifact at index 0: reference index 1, future index 1 + H - 1 = H
        return s.timestamps[spec.horizon_bars]

    def test_after_the_future_bars_open_is_accepted(self):
        s = series()
        spec = OutcomeSpec(horizon_bars=3)
        clock = self._future_open(s, spec) + timedelta(seconds=1)
        result = evaluate(observation_artifact(s), s, spec, evaluated_at=clock)
        assert result.status is TrackingStatus.EVALUATED
        assert result.outcome.evaluated_at == clock

    def test_at_the_future_bars_open_is_rejected(self):
        s = series()
        spec = OutcomeSpec(horizon_bars=3)
        with pytest.raises(OutcomeTrackingError, match="is not after the future bar's open"):
            evaluate(observation_artifact(s), s, spec, evaluated_at=self._future_open(s, spec))

    def test_before_the_future_bars_open_is_rejected(self):
        s = series()
        spec = OutcomeSpec(horizon_bars=3)
        with pytest.raises(OutcomeTrackingError, match="is not after the future bar's open"):
            evaluate(observation_artifact(s), s, spec,
                     evaluated_at=self._future_open(s, spec) - timedelta(hours=1))

    def test_an_impossible_clock_never_yields_a_partial_record(self):
        s = series()
        spec = OutcomeSpec(horizon_bars=3)
        with pytest.raises(OutcomeTrackingError):
            evaluate(observation_artifact(s), s, spec, evaluated_at=self._future_open(s, spec))
        # and the same inputs with a sane clock are fine: the refusal was the clock's
        assert evaluate(observation_artifact(s), s, spec).status is TrackingStatus.EVALUATED

    def test_a_horizon_knowable_at_the_cutoff_is_refused_by_the_record(self):
        # The artifact's data_cutoff is ahead of its bar: bar 0 claimed with
        # bars 0..3 already settled. A 3-bar horizon ends on bar 3 -- known at
        # registration -- so the record refuses: no retrospective outcomes.
        s = series()
        artifact = observation_artifact(s, 0, data_cutoff=s.timestamps[3],
                                        recorded_at=s.timestamps[3] + timedelta(hours=1))
        with pytest.raises(OutcomeTrackingError, match="would have been knowable"):
            evaluate(artifact, s, OutcomeSpec(horizon_bars=3))
        # A longer horizon that ends after the cutoff is prospective and fine.
        assert evaluate(artifact, s, OutcomeSpec(horizon_bars=4)).status is TrackingStatus.EVALUATED


# -- consumed bars ---------------------------------------------------------------------------------------


class TestConsumedBars:
    """``consumed_bars_fingerprint`` = ``bars_fingerprint`` of the horizon window:
    reference bar through future bar inclusive, exactly ``horizon_bars`` bars,
    in series order. The claimed bar is not in it."""

    @pytest.mark.parametrize("horizon", [1, 2, 3, 5, 7])
    def test_is_the_horizon_window(self, horizon):
        s = series(8)
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=horizon)).outcome
        assert o.consumed_bars_fingerprint == bars_fingerprint(window(s, 1, horizon))

    def test_window_starts_at_the_reference_bar_not_the_claimed_bar(self):
        s = series()
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=3)).outcome
        assert o.consumed_bars_fingerprint == bars_fingerprint(s.bars[1:4])
        assert o.consumed_bars_fingerprint != bars_fingerprint(s.bars[0:4])
        assert o.consumed_bars_fingerprint != bars_fingerprint(s.bars[0:3])

    def test_is_distinct_from_the_observation_bar_fingerprint(self):
        s = series()
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=1)).outcome
        assert o.consumed_bars_fingerprint != o.observation_bar_fingerprint
        assert o.observation_bar_fingerprint == bar_fingerprint(s[0])
        assert o.consumed_bars_fingerprint == bars_fingerprint((s[1],))

    def test_deterministic(self):
        s = series()
        artifact = observation_artifact(s)
        fps = {evaluate(artifact, s).outcome.consumed_bars_fingerprint for _ in range(5)}
        assert len(fps) == 1

    def test_horizon_sensitive(self):
        s = series()
        artifact = observation_artifact(s)
        fps = [evaluate(artifact, s, OutcomeSpec(horizon_bars=h)).outcome.consumed_bars_fingerprint
               for h in (1, 2, 3, 4)]
        assert len(set(fps)) == 4

    @pytest.mark.parametrize("index", [1, 2, 3])
    def test_changes_when_a_bar_inside_the_window_changes(self, index):
        s = series()
        artifact = observation_artifact(s)
        spec = OutcomeSpec(horizon_bars=3)  # window = bars 1..3
        before = evaluate(artifact, s, spec).outcome.consumed_bars_fingerprint
        after = evaluate(artifact, revised(s, index, volume=1.0), spec).outcome.consumed_bars_fingerprint
        assert after != before

    @pytest.mark.parametrize("index", [4, 5, 6, 7])
    def test_does_not_change_when_a_post_horizon_bar_changes(self, index):
        s = series()
        artifact = observation_artifact(s)
        spec = OutcomeSpec(horizon_bars=3)
        before = evaluate(artifact, s, spec).outcome
        after = evaluate(artifact, revised(s, index, close=1.0, low=0.5), spec).outcome
        assert after.consumed_bars_fingerprint == before.consumed_bars_fingerprint
        assert after == before

    def test_does_not_include_earlier_bars(self):
        s = series(10)
        artifact = observation_artifact(s, 4)
        spec = OutcomeSpec(horizon_bars=2)  # window = bars 5..6
        before = evaluate(artifact, s, spec).outcome
        for earlier in (0, 1, 2, 3):
            after = evaluate(artifact, revised(s, earlier, open=1.0, high=2.0, low=0.5,
                                               close=1.5, volume=7.0), spec).outcome
            assert after == before, earlier            # every measurement fact
            assert after.outcome_key == before.outcome_key
        assert before.consumed_bars_fingerprint == bars_fingerprint(window(s, 5, 2))

    def test_order_is_series_order(self):
        s = series()
        o = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=3)).outcome
        assert o.consumed_bars_fingerprint != bars_fingerprint(tuple(reversed(s.bars[1:4])))


# -- anti-lookahead: the existing harness, applied to tracking ----------------------------------------


def _facts(o: OutcomeRecord) -> tuple:
    return (o.reference_timestamp, o.reference_price, o.future_timestamp, o.future_price,
            o.forward_return, o.consumed_bars_fingerprint, o.outcome_key)


class TestAntiLookahead:
    @pytest.fixture
    def wobbly(self):
        closes = [10.0 + 4.0 * ((i * 7) % 11) / 11.0 + i * 0.2 for i in range(20)]
        bars = [MarketBar("AAPL", START + timedelta(days=i), c * 0.98, c * 1.05, c * 0.95, c,
                          1000.0 + i, "1d", SOURCE) for i, c in enumerate(closes)]
        return BarSeries.from_bars(bars, basis=PriceBasis.RAW)

    @pytest.mark.parametrize("horizon", [1, 2, 3, 5])
    def test_bars_after_the_horizon_cannot_change_an_outcome(self, wobbly, horizon):
        spec = OutcomeSpec(horizon_bars=horizon)
        for index in range(len(wobbly)):
            artifact = observation_artifact(wobbly, index)
            result = evaluate(artifact, wobbly, spec)
            if result.status is not TrackingStatus.EVALUATED:
                continue
            future_index = wobbly.timestamps.index(result.outcome.future_timestamp)
            if future_index >= len(wobbly) - 1:
                continue
            perturbed = evaluate(artifact, perturb_after(wobbly, future_index), spec)
            assert perturbed.status is TrackingStatus.EVALUATED
            assert _facts(perturbed.outcome) == _facts(result.outcome), (index, horizon)
            assert perturbed.outcome.artifact_key == result.outcome.artifact_key

    @pytest.mark.parametrize("horizon", [1, 2, 3, 5])
    def test_truncating_after_the_future_bar_changes_nothing(self, wobbly, horizon):
        spec = OutcomeSpec(horizon_bars=horizon)
        for index in range(len(wobbly)):
            artifact = observation_artifact(wobbly, index)
            result = evaluate(artifact, wobbly, spec)
            if result.status is not TrackingStatus.EVALUATED:
                continue
            future_index = wobbly.timestamps.index(result.outcome.future_timestamp)
            truncated = evaluate(artifact, wobbly.prefix(future_index + 1), spec)
            assert truncated.status is TrackingStatus.EVALUATED
            assert _facts(truncated.outcome) == _facts(result.outcome), (index, horizon)

    @pytest.mark.parametrize("horizon", [1, 2, 3, 5])
    def test_truncating_before_the_horizon_is_pending(self, wobbly, horizon):
        spec = OutcomeSpec(horizon_bars=horizon)
        for index in range(len(wobbly)):
            artifact = observation_artifact(wobbly, index)
            result = evaluate(artifact, wobbly, spec)
            if result.status is not TrackingStatus.EVALUATED:
                continue
            future_index = wobbly.timestamps.index(result.outcome.future_timestamp)
            short = evaluate(artifact, wobbly.prefix(future_index), spec)
            assert short.status is TrackingStatus.PENDING, (index, horizon)
            assert short.outcome is None
            assert short.artifact is artifact  # identity untouched

    def test_the_perturbation_really_changes_the_tail(self, wobbly):
        perturbed = perturb_after(wobbly, 5)
        assert perturbed.values("close")[:6] == wobbly.values("close")[:6]
        assert perturbed.values("close")[6:] != wobbly.values("close")[6:]


# -- assessment artifacts -------------------------------------------------------------------------------


class TestAssessmentArtifact:
    @pytest.mark.parametrize("state", [
        AssessmentState.BULLISH, AssessmentState.BEARISH,
        AssessmentState.NEUTRAL, AssessmentState.CONFLICTED,
    ])
    def test_every_evaluable_state_produces_an_outcome(self, state):
        s = series()
        result = evaluate(assessment_artifact(s, state=state), s)
        assert result.status is TrackingStatus.EVALUATED
        assert result.outcome.artifact.state is state
        assert result.outcome.forward_return == 450.0 / 200.0 - 1.0

    def test_insufficient_data_has_no_outcome(self):
        s = series()
        result = evaluate(assessment_artifact(s, state=AssessmentState.INSUFFICIENT_DATA), s)
        assert result.status is TrackingStatus.INELIGIBLE
        assert result.outcome is None

    def test_no_research_observation_is_fabricated(self, monkeypatch):
        import src.strategies.research as research
        import src.outcomes.tracking as tracking

        def boom(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a ResearchObservation was constructed")

        monkeypatch.setattr(research.ResearchObservation, "__init__", boom)
        assert "ResearchObservation" not in tracking.__dict__
        s = series()
        assert evaluate(assessment_artifact(s), s).status is TrackingStatus.EVALUATED
        assert evaluate(observation_artifact(s), s).status is TrackingStatus.EVALUATED

    def test_pending_and_refusals_apply_equally(self):
        s = series(4)
        assert evaluate(assessment_artifact(s, 3), s).status is TrackingStatus.PENDING
        assert evaluate(assessment_artifact(s), series(4, source="alpaca")).refusal \
            is RefusalReason.SOURCE_MISMATCH
        assert evaluate(assessment_artifact(s), revised(s, 0, close=1.0, low=0.5)).refusal \
            is RefusalReason.SOURCE_BAR_REVISED


# -- cross-kind consistency -----------------------------------------------------------------------------


class TestCrossKindConsistency:
    """The market does not know who asked: the same point under the same spec
    measures identically for an observation and an assessment artifact, while
    their identities -- and so their outcome keys -- differ."""

    @pytest.mark.parametrize("horizon", [1, 3, 5])
    def test_same_market_facts_different_keys(self, horizon):
        s = series(10)
        spec = OutcomeSpec(horizon_bars=horizon)
        obs = evaluate(observation_artifact(s, 2), s, spec).outcome
        asmt = evaluate(assessment_artifact(s, 2, state=AssessmentState.CONFLICTED), s, spec).outcome
        assert (obs.reference_timestamp, obs.reference_price, obs.future_timestamp,
                obs.future_price, obs.forward_return, obs.consumed_bars_fingerprint) == (
            asmt.reference_timestamp, asmt.reference_price, asmt.future_timestamp,
            asmt.future_price, asmt.forward_return, asmt.consumed_bars_fingerprint)
        assert obs.artifact_key != asmt.artifact_key
        assert obs.outcome_key != asmt.outcome_key
        assert obs.spec_fingerprint == asmt.spec_fingerprint

    def test_the_shared_measurement_is_phase_fours(self):
        s = series(10)
        spec = OutcomeSpec(horizon_bars=3)
        obs = evaluate(observation_artifact(s, 2), s, spec)
        asmt = evaluate(assessment_artifact(s, 2), s, spec)
        phase4 = measure_forward(s, spec, symbol="AAPL", interval="1d", basis=PriceBasis.RAW,
                                 timestamp=s.timestamps[2])
        assert obs.measurement == asmt.measurement == phase4


# -- the result model ---------------------------------------------------------------------------------


class TestTrackingResult:
    def test_frozen(self):
        s = series()
        result = evaluate(observation_artifact(s), s)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = TrackingStatus.PENDING

    def test_statuses_and_reasons_are_closed_vocabularies(self):
        assert {m.value for m in TrackingStatus} == {"evaluated", "pending", "ineligible", "refused"}
        assert {m.value for m in RefusalReason} == {"source_mismatch", "source_bar_revised"}

    def test_evaluated_requires_an_outcome_and_a_measurement(self):
        s = series()
        artifact = observation_artifact(s)
        with pytest.raises(OutcomeTrackingError, match="must carry"):
            TrackingResult(artifact, OutcomeSpec(), LATER, TrackingStatus.EVALUATED)

    def test_pending_cannot_carry_an_outcome(self):
        s = series()
        good = evaluate(observation_artifact(s), s)
        with pytest.raises(OutcomeTrackingError, match="must carry"):
            TrackingResult(good.artifact, good.spec, LATER, TrackingStatus.PENDING,
                           outcome=good.outcome, measurement=good.measurement)

    def test_pending_cannot_rest_on_an_evaluated_measurement(self):
        s = series()
        good = evaluate(observation_artifact(s), s)
        with pytest.raises(OutcomeTrackingError, match="cannot rest on"):
            TrackingResult(good.artifact, good.spec, LATER, TrackingStatus.PENDING,
                           measurement=good.measurement)

    def test_evaluated_cannot_rest_on_an_incomplete_measurement(self):
        s = series()
        good = evaluate(observation_artifact(s), s)
        incomplete = ForwardMeasurement(good.artifact.timestamp, 3, OutcomeStatus.NO_REFERENCE_BAR)
        with pytest.raises(OutcomeTrackingError, match="cannot rest on"):
            TrackingResult(good.artifact, good.spec, LATER, TrackingStatus.EVALUATED,
                           outcome=good.outcome, measurement=incomplete)

    def test_refused_requires_a_reason_and_nothing_else(self):
        s = series()
        artifact = observation_artifact(s)
        with pytest.raises(OutcomeTrackingError, match="must carry"):
            TrackingResult(artifact, OutcomeSpec(), LATER, TrackingStatus.REFUSED)
        with pytest.raises(OutcomeTrackingError, match="must carry"):
            TrackingResult(artifact, OutcomeSpec(), LATER, TrackingStatus.INELIGIBLE,
                           refusal=RefusalReason.SOURCE_MISMATCH)

    def test_the_outcome_must_embed_the_results_artifact(self):
        s = series()
        good = evaluate(observation_artifact(s), s)
        other = observation_artifact(s, hypothesis_id="other")
        with pytest.raises(OutcomeTrackingError, match="does not embed"):
            TrackingResult(other, good.spec, LATER, TrackingStatus.EVALUATED,
                           outcome=good.outcome, measurement=good.measurement)

    def test_the_clock_cannot_precede_recording_for_any_status(self):
        s = series(4)
        artifact = observation_artifact(s, 3)
        early = artifact.recorded_at - timedelta(seconds=1)
        pending = evaluate(artifact, s).measurement
        for status, fields in (
            (TrackingStatus.PENDING, {"measurement": pending}),
            (TrackingStatus.INELIGIBLE, {}),
            (TrackingStatus.REFUSED, {"refusal": RefusalReason.SOURCE_MISMATCH}),
        ):
            with pytest.raises(OutcomeTrackingError, match="precedes recorded_at"):
                TrackingResult(artifact, OutcomeSpec(horizon_bars=3), early, status, **fields)
        # at the recording instant is allowed, as for OutcomeRecord
        assert TrackingResult(artifact, OutcomeSpec(horizon_bars=3), artifact.recorded_at,
                              TrackingStatus.INELIGIBLE).evaluated_at == artifact.recorded_at

    def test_the_outcome_must_share_the_results_clock(self):
        s = series()
        good = evaluate(observation_artifact(s), s)
        with pytest.raises(OutcomeTrackingError, match="not at this result's"):
            TrackingResult(good.artifact, good.spec, LATER + timedelta(days=1),
                           TrackingStatus.EVALUATED, outcome=good.outcome,
                           measurement=good.measurement)

    def test_the_outcome_must_share_the_results_spec(self):
        s = series()
        good = evaluate(observation_artifact(s), s, OutcomeSpec(horizon_bars=3))
        with pytest.raises(OutcomeTrackingError, match="not this result's"):
            TrackingResult(good.artifact, OutcomeSpec(horizon_bars=2), LATER,
                           TrackingStatus.EVALUATED, outcome=good.outcome,
                           measurement=good.measurement)

    @pytest.mark.parametrize("bad", ["done", 1, None])
    def test_unknown_status_rejected(self, bad):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="status"):
            TrackingResult(observation_artifact(s), OutcomeSpec(), LATER, bad)

    def test_unknown_refusal_rejected(self):
        s = series()
        with pytest.raises(OutcomeTrackingError, match="refusal"):
            TrackingResult(observation_artifact(s), OutcomeSpec(), LATER, TrackingStatus.REFUSED,
                           refusal="bad data")

    def test_string_values_are_coerced(self):
        s = series()
        r = TrackingResult(observation_artifact(s), OutcomeSpec(), LATER, "refused", refusal="source_mismatch")
        assert r.status is TrackingStatus.REFUSED and r.refusal is RefusalReason.SOURCE_MISMATCH

    def test_describe_for_every_status(self):
        s = series(4)
        artifact = observation_artifact(s)
        assert "-> evaluated +1.250000" in evaluate(artifact, s).describe()
        assert "-> pending (no_reference_bar)" in evaluate(observation_artifact(s, 3), s).describe()
        assert "-> refused (source_mismatch)" in evaluate(artifact, series(4, source="x")).describe()
        assert "-> ineligible" in evaluate(
            observation_artifact(s, state=ResearchState.INSUFFICIENT_DATA), s).describe()
