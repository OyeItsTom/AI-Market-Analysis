"""Phase R anti-lookahead, proved over the whole study function.

The Phase 2/3/4 harnesses already prove each layer causal in isolation; these
tests re-apply their two properties -- post-horizon perturbation and
truncation invariance -- to :func:`run_study` end to end, and add the two
window-specific properties the study introduces: buffer bars can change
outcomes but never classifications, and buffer bars never become
observations.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from src.data.series import BarSeries, PriceBasis
from src.evaluation import OutcomeStatus
from src.research import run_study
from tests.evaluation_lookahead import perturb_after
from tests.research_fixtures import series_for, synthetic_bars, synthetic_series
from tests.test_research_definition import small_definition


@pytest.fixture(scope="module")
def definition():
    return small_definition()


@pytest.fixture(scope="module")
def baseline(definition):
    return run_study(definition, series_for(definition))


def rows_by_key(result):
    return {(o.symbol, o.hypothesis_id, o.timestamp): o for o in result.observations}


def classification(row):
    return (row.state, row.reason_codes)


def outcome_at(row, horizon):
    return next(h for h in row.outcomes if h.horizon_bars == horizon)


def test_a_bars_after_an_observations_horizon_do_not_change_its_row(definition, baseline):
    """Property A: perturb every bar strictly after a row's future bar; the row is unchanged."""
    original = series_for(definition)
    series = original["AAA"]
    stamps = list(series.timestamps)
    before = rows_by_key(baseline)

    # A handful of observations spread through the window, at the longest horizon.
    horizon = max(definition.horizons)
    sample = [o for o in baseline.observations if o.symbol == "AAA"][::30]
    for row in sample:
        future = outcome_at(row, horizon).future_timestamp
        if future is None:
            continue
        index = stamps.index(future)
        if index >= len(series) - 1:
            continue
        mutated = run_study(definition, {**original, "AAA": perturb_after(series, index)})
        after = rows_by_key(mutated)
        for hypothesis_id in {c.hypothesis_id for c in baseline.coverage}:
            key = ("AAA", hypothesis_id, row.timestamp)
            assert after[key] == before[key], (
                f"LOOK-AHEAD: {key} changed when only bars after {future.isoformat()} moved"
            )


def test_b_truncating_after_sufficient_future_bars_preserves_earlier_rows(definition, baseline):
    """Property B: rows whose future bar survives a truncation are identical."""
    original = series_for(definition)
    series = original["AAA"]
    stamps = list(series.timestamps)
    before = rows_by_key(baseline)
    horizon = max(definition.horizons)

    for cut_days in (5, 12, 25):
        # Truncate ``cut_days`` bars before the end of the buffer.
        cut = len(series) - cut_days
        truncated = run_study(definition, {**original, "AAA": series.prefix(cut)})
        after = rows_by_key(truncated)
        for key, row in before.items():
            if key[0] != "AAA":
                continue
            future = outcome_at(row, horizon).future_timestamp
            if future is not None and stamps.index(future) < cut:
                assert after[key] == row, f"LOOK-AHEAD: {key} changed under truncation at {cut}"
            else:
                # Its longest-horizon outcome is now unavailable -- reported, not dropped.
                assert key in after
                assert classification(after[key]) == classification(row)
                assert outcome_at(after[key], horizon).status in (
                    OutcomeStatus.INSUFFICIENT_FUTURE_DATA, OutcomeStatus.NO_REFERENCE_BAR,
                    OutcomeStatus.EVALUATED,
                )


def test_c_buffer_bars_change_outcomes_but_never_classifications(definition, baseline):
    """Property C: replacing every buffer bar leaves every classification alone."""
    original = series_for(definition)
    series = original["AAA"]
    stamps = list(series.timestamps)
    last_observation = max(t for t in stamps if t < definition.observation_end)
    perturbed = perturb_after(series, stamps.index(last_observation))
    assert perturbed.timestamps == series.timestamps

    mutated = run_study(definition, {**original, "AAA": perturbed})
    before, after = rows_by_key(baseline), rows_by_key(mutated)
    assert set(before) == set(after)

    changed_outcomes = 0
    for key, row in before.items():
        assert classification(after[key]) == classification(row), (
            f"LOOK-AHEAD: buffer bars changed the classification at {key}"
        )
        if key[0] == "AAA" and after[key].outcomes != row.outcomes:
            changed_outcomes += 1
    # Late-2024-style observations legitimately read the buffer for their outcomes.
    assert changed_outcomes > 0
    # Coverage and state counts are untouched by the buffer's values.
    for old, new in zip(baseline.coverage, mutated.coverage):
        assert (old.bullish_count, old.bearish_count, old.neutral_count, old.insufficient_data_count) == (
            new.bullish_count, new.bearish_count, new.neutral_count, new.insufficient_data_count,
        )


def test_d_buffer_bars_never_become_observations(definition, baseline):
    """Property D: no row is stamped in the buffer or the warm-up, whatever the data."""
    for row in baseline.observations:
        assert definition.observation_start <= row.timestamp < definition.observation_end

    # Even a buffer full of extreme bars produces exactly the same observation set.
    original = series_for(definition)
    series = original["AAA"]
    stamps = list(series.timestamps)
    last_observation = max(t for t in stamps if t < definition.observation_end)
    mutated = run_study(
        definition, {**original, "AAA": perturb_after(series, stamps.index(last_observation), scale=40.0)}
    )
    assert [(o.symbol, o.hypothesis_id, o.timestamp) for o in mutated.observations] == [
        (o.symbol, o.hypothesis_id, o.timestamp) for o in baseline.observations
    ]
    for symbol in mutated.symbols:
        assert symbol.last_observation_timestamp < definition.observation_end
        assert symbol.first_observation_timestamp >= definition.observation_start


def test_warmup_bars_feed_features_but_are_never_observations(definition, baseline):
    """Changing warm-up bars may change early classifications (they are evidence)
    but never adds or removes an observation."""
    original = series_for(definition)
    bars = synthetic_bars("AAA", definition.fetch_start, definition.outcome_data_end, phase=2.5)
    warm_index = sum(1 for b in bars if b.timestamp < definition.observation_start)
    changed = list(original["AAA"].bars)
    changed[:warm_index] = bars[:warm_index]
    mutated = run_study(definition, {**original, "AAA": BarSeries.from_bars(changed, basis=PriceBasis.RAW)})
    assert [o.timestamp for o in mutated.observations if o.symbol == "AAA"] == [
        o.timestamp for o in baseline.observations if o.symbol == "AAA"
    ]
    assert mutated.symbols[0].warmup_bars == baseline.symbols[0].warmup_bars


def test_a_series_that_stops_inside_the_buffer_is_still_the_same_study(definition, baseline):
    """The buffer is an allowance, not a requirement: fewer buffer bars only
    change which late rows are evaluable."""
    original = series_for(definition)
    shorter = synthetic_series(definition, "AAA", end=definition.observation_end + timedelta(days=3))
    mutated = run_study(definition, {**original, "AAA": shorter})
    assert mutated.symbols[0].outcome_buffer_bars == 3
    assert mutated.symbols[0].observation_bars == baseline.symbols[0].observation_bars
    for old, new in zip(baseline.coverage, mutated.coverage):
        if old.symbol != "AAA":
            continue
        assert new.total_observations == old.total_observations
        h20 = next(h for h in new.horizons if h.horizon_bars == 20)
        assert h20.insufficient_future_data > 0
        assert h20.evaluated + h20.insufficient_future_data + h20.no_reference_bar + h20.ineligible == new.total_observations
