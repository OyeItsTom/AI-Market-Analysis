"""Combine aligned research observations into one assessment.

    ResearchObservation(s) -> AssessmentPolicy -> ResearchAssessment

This module reruns nothing.  It does not touch a hypothesis, a feature, a bar,
a provider or a clock: it consumes finished :class:`~src.strategies.research.ResearchObservation`
records and reduces them.  It reads no outcome, so no future information is in
scope to leak.

The rule: ``directional_presence_v1``
-------------------------------------
Exactly one aggregation rule exists, and this module implements it directly.
:func:`assess` *checks* ``policy.aggregation_rule`` and refuses anything it does
not implement, but it never *dispatches* on it: there is one reduction, not a
menu.  The check exists so a future identity cannot silently inherit these
semantics.  The policy records the rule identity so the fingerprint changes if
the semantics ever do (see :mod:`src.assessments.policy`)::

    1. validate structure                        -- any problem RAISES
    2. count bullish / bearish / neutral / insufficient
    3. sufficient = bullish + bearish + neutral
    4. sufficient < policy minimum  -> INSUFFICIENT_DATA
    5. bullish > 0 and bearish > 0  -> CONFLICTED
    6. bullish > 0                  -> BULLISH
    7. bearish > 0                  -> BEARISH
    8. otherwise                    -> NEUTRAL

Why directional presence and not majority
-----------------------------------------
``NEUTRAL`` in this repository overwhelmingly means *"my condition did not
fire"*, not *"I assert flatness"*: ``TrendAlignment`` reports it when the gap is
below its margin, ``MomentumInTrendContext`` when momentum is mid-range, and
``TrendCrossover`` whenever no crossover occurred -- which is nearly every bar,
since crossovers are rare events.  Under a majority or plurality rule those
abstentions would outvote a hypothesis that actually fired, and a real crossover
would be reported as ``NEUTRAL``.  Directional presence lets a firing hypothesis
be heard, and the counts and reason codes record exactly how thin or broad the
evidence was.

The trade-off is real and is not hidden: one directional hypothesis among
abstentions yields a directional state.  That is why :class:`~src.assessments.assessment.AssessmentCounts`
and the reason codes are mandatory parts of the record rather than decoration --
``BULLISH`` with ``bullish=1 neutral=2`` says exactly what happened.

Conflict has precedence over volume
-----------------------------------
Step 5 runs before steps 6-8, so any simultaneous bullish and bearish evidence
yields ``CONFLICTED`` no matter how much neutral evidence accompanies it.
``CONFLICTED`` represents *directional contradiction*, not a vote-count tie, and
abstentions cannot resolve a disagreement between two hypotheses that both
fired.
"""

from __future__ import annotations

from typing import Iterable

from src.strategies.research import ResearchObservation, ResearchState

from .assessment import (
    AssessmentCounts,
    AssessmentError,
    AssessmentInput,
    AssessmentReasonCode,
    AssessmentState,
    ResearchAssessment,
)
from .policy import AssessmentAggregationRule, AssessmentPolicy, HypothesisIdentity

#: The one rule this module implements. Checked at the top of :func:`assess`.
#:
#: This is a guard, not a dispatch table. Without it, adding a second member to
#: :class:`AssessmentAggregationRule` would leave ``assess`` silently applying
#: V1 semantics to a policy whose fingerprint claims the new identity -- the
#: exact silent redefinition the rule identity exists to prevent. The failure
#: would be invisible: the assessment would look well-formed and carry a
#: correct-looking fingerprint for semantics it never used.
_IMPLEMENTED_RULE = AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1


def _identity_of(observation: ResearchObservation) -> tuple[str, int, str]:
    return (observation.hypothesis_id, observation.version, observation.fingerprint)


def _require_observations(observations: Iterable[ResearchObservation]) -> tuple[
    ResearchObservation, ...
]:
    supplied = tuple(observations)
    for observation in supplied:
        if not isinstance(observation, ResearchObservation):
            raise AssessmentError(
                f"expected ResearchObservation records, got {type(observation).__name__}"
            )
    if not supplied:
        raise AssessmentError("at least one observation is required to assess")
    return supplied


def _require_alignment(observations: tuple[ResearchObservation, ...]) -> None:
    """Every observation must describe exactly the same market decision point.

    Exact equality on all four axes; no tolerance window and no nearest-match.
    Mixing price bases is the sharpest of these -- ``RAW`` and
    ``SPLIT_AND_DIVIDEND_ADJUSTED`` numbers are denominated differently and
    must never be compared (ADR 0001).

    **Market-data source is not checked and cannot be**: ``ResearchObservation``
    carries no provider provenance, so two observations from different
    providers are indistinguishable here. Inventing ``source="unknown"`` or
    inferring a provider from a hypothesis id would be a fabricated guarantee;
    the honest fix is provenance in Phase 3, which Phase 6 does not touch.
    """
    first = observations[0]
    for observation in observations[1:]:
        mismatches = [
            f"{label} {theirs!r} != {ours!r}"
            for label, theirs, ours in (
                ("symbol", observation.symbol, first.symbol),
                ("interval", observation.interval.value, first.interval.value),
                ("basis", observation.basis.value, first.basis.value),
                ("timestamp", observation.timestamp, first.timestamp),
            )
            if theirs != ours
        ]
        if mismatches:
            raise AssessmentError(
                f"observations do not describe the same market point: "
                f"{'; '.join(mismatches)}. Assessment combines evidence about one "
                "decision point; it never aligns or converts across points."
            )


def _require_exact_ensemble(
    observations: tuple[ResearchObservation, ...], policy: AssessmentPolicy
) -> None:
    """The policy names an exact ensemble: each member exactly once, nothing else.

    Every failure is reported distinctly rather than collapsed into one
    message, because they mean different things. In particular a *fingerprint
    mismatch* is not merely an unexpected hypothesis: it is a known
    hypothesis/version whose implementation identity changed -- the silent
    redefinition ``HypothesisSpec.fingerprint`` exists to catch.
    """
    expected: dict[tuple[str, int, str], HypothesisIdentity] = {
        identity.sort_key: identity for identity in policy.hypotheses
    }
    expected_by_id_version: dict[tuple[str, int], HypothesisIdentity] = {
        (identity.hypothesis_id, identity.version): identity
        for identity in policy.hypotheses
    }

    seen: set[tuple[str, int, str]] = set()
    for observation in observations:
        identity = _identity_of(observation)
        if identity in seen:
            raise AssessmentError(
                f"duplicate hypothesis in the observations: {observation.label}. "
                "Duplicates are refused rather than deduplicated: silently collapsing "
                "them would hide a caller error, and counting them would inflate the "
                "evidence."
            )
        seen.add(identity)

        if identity in expected:
            continue

        pinned = expected_by_id_version.get((observation.hypothesis_id, observation.version))
        if pinned is not None:
            raise AssessmentError(
                f"hypothesis fingerprint mismatch for {observation.hypothesis_id} "
                f"v{observation.version}: policy pins {pinned.fingerprint!r} but the "
                f"observation carries {observation.fingerprint!r}. The same id and "
                "version with a different fingerprint is a re-parameterised "
                "hypothesis, not the pinned one."
            )
        raise AssessmentError(
            f"unexpected hypothesis {observation.label}: it is not in the policy "
            "ensemble. The ensemble is exact, so policy identity fully determines "
            "which hypotheses contributed."
        )

    missing = [expected[key].label for key in expected if key not in seen]
    if missing:
        raise AssessmentError(
            f"missing hypothesis in the observations: {', '.join(sorted(missing))}. "
            "A missing hypothesis is a structural error, not weak evidence: it is "
            "not reported as INSUFFICIENT_DATA."
        )


def _tally(observations: tuple[ResearchObservation, ...]) -> AssessmentCounts:
    counts = {state: 0 for state in ResearchState}
    for observation in observations:
        counts[observation.state] += 1
    return AssessmentCounts(
        bullish=counts[ResearchState.BULLISH],
        bearish=counts[ResearchState.BEARISH],
        neutral=counts[ResearchState.NEUTRAL],
        insufficient=counts[ResearchState.INSUFFICIENT_DATA],
    )


def _reduce_state(counts: AssessmentCounts, policy: AssessmentPolicy) -> AssessmentState:
    """The locked ``directional_presence_v1`` reduction. See the module docstring."""
    if counts.sufficient < policy.minimum_sufficient_observations:
        return AssessmentState.INSUFFICIENT_DATA
    if counts.bullish > 0 and counts.bearish > 0:
        return AssessmentState.CONFLICTED
    if counts.bullish > 0:
        return AssessmentState.BULLISH
    if counts.bearish > 0:
        return AssessmentState.BEARISH
    return AssessmentState.NEUTRAL


def _derive_reasons(
    state: AssessmentState, counts: AssessmentCounts
) -> tuple[AssessmentReasonCode, ...]:
    """Facts about the counts, never judgements about their weight."""
    codes: list[AssessmentReasonCode] = []

    if state is AssessmentState.INSUFFICIENT_DATA:
        codes.append(AssessmentReasonCode.INSUFFICIENT_EVIDENCE)
    elif state is AssessmentState.CONFLICTED:
        codes.append(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE)
    elif state is AssessmentState.BULLISH:
        codes.append(
            AssessmentReasonCode.UNANIMOUS_BULLISH
            if counts.neutral == 0
            else AssessmentReasonCode.DIRECTIONAL_BULLISH_WITH_NEUTRAL
        )
    elif state is AssessmentState.BEARISH:
        codes.append(
            AssessmentReasonCode.UNANIMOUS_BEARISH
            if counts.neutral == 0
            else AssessmentReasonCode.DIRECTIONAL_BEARISH_WITH_NEUTRAL
        )
    else:
        codes.append(AssessmentReasonCode.UNANIMOUS_NEUTRAL)

    # Additive, and it means what it says: those observations did not take part
    # in the state reduction. They are still recorded in `inputs` and counted in
    # `counts.insufficient` -- nothing is dropped from the audit trail.
    if counts.insufficient > 0:
        codes.append(AssessmentReasonCode.INSUFFICIENT_INPUTS_EXCLUDED)

    return tuple(codes)


def assess(
    observations: Iterable[ResearchObservation], policy: AssessmentPolicy
) -> ResearchAssessment:
    """Combine aligned observations into one :class:`ResearchAssessment`.

    Deterministic and order-invariant: observations are canonicalised by
    hypothesis identity, so the same set in any order yields an identical
    record. No clock is read, nothing is random, and nothing is fetched.

    Refuses any policy whose ``aggregation_rule`` is not the rule implemented
    here, so a future identity can never inherit these semantics by accident.

    Raises :class:`~src.assessments.assessment.AssessmentError` for every
    structural problem -- misalignment, a missing or unexpected hypothesis, a
    duplicate, a fingerprint mismatch. Structural invalidity never becomes a
    research state.
    """
    if not isinstance(policy, AssessmentPolicy):
        raise AssessmentError(
            f"expected an AssessmentPolicy, got {type(policy).__name__}"
        )
    if policy.aggregation_rule is not _IMPLEMENTED_RULE:
        raise AssessmentError(
            f"this module implements {_IMPLEMENTED_RULE.value!r}, but the policy "
            f"specifies {policy.aggregation_rule.value!r}. A new rule identity needs "
            "its own reduction; applying these semantics under that identity would "
            "silently misattribute the result."
        )

    supplied = _require_observations(observations)
    _require_alignment(supplied)
    _require_exact_ensemble(supplied, policy)

    counts = _tally(supplied)
    state = _reduce_state(counts, policy)
    reason_codes = _derive_reasons(state, counts)

    first = supplied[0]
    # The combined classification cannot logically exist until every
    # contributing classification could. `max` is the only safe reduction; see
    # the ResearchAssessment docs for what this bound does and does not mean.
    assessment_as_of = max(observation.evaluable_from for observation in supplied)

    return ResearchAssessment(
        policy_fingerprint=policy.fingerprint,
        symbol=first.symbol,
        interval=first.interval,
        basis=first.basis,
        timestamp=first.timestamp,
        assessment_as_of=assessment_as_of,
        state=state,
        inputs=tuple(
            AssessmentInput(
                hypothesis_id=observation.hypothesis_id,
                version=observation.version,
                fingerprint=observation.fingerprint,
                state=observation.state,
            )
            for observation in supplied
        ),
        counts=counts,
        reason_codes=reason_codes,
    )


__all__ = ["assess"]
