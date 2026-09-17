"""The frozen definition of Baseline Study v1.

Every research decision the study depends on is a constant in this module
and a field of :class:`StudyDefinition`, whose :attr:`~StudyDefinition.fingerprint`
covers all of them. There is deliberately no way to run "the baseline study
with a different universe" or "with a shorter window": that would be a
different study, and it must carry a different version and fingerprint so
its results can never be mistaken for these.

Why frozen, and why before any result exists
--------------------------------------------
A retrospective study has as many degrees of freedom as the researcher has
knobs, and every knob turned after seeing a result turns a description into
a fit. The universe, the dates, the horizons, the benchmark and the metrics
below were fixed before the first real bar was fetched (see
``docs/adr/0011-first-benchmarked-retrospective-study.md``), and the code
offers no override for any of them.

Windows (all UTC, half-open)
----------------------------
::

    [FETCH_START,       OBSERVATION_START)   warm-up only: never a study observation
    [OBSERVATION_START, OBSERVATION_END)     the study's classification window
    [OBSERVATION_END,   OUTCOME_DATA_END)    outcome-only buffer: never classified

Bars from 2025-01-01 through the outcome-data end are read solely to
measure forward outcomes of late-2024 observations. They are **not** a
held-out window; chronologically untouched data begins at
:data:`OUTCOME_DATA_END`.

Hypotheses and outcome specifications
-------------------------------------
The study measures the hypotheses the repository already has, unchanged, and
the same forward-return contract the Phase 12 ledger tracks (raw basis,
next-bar-open reference, future close; horizons 1, 5 and 20 bars). The
outcome specifications are constructed here rather than imported from the
orchestration tier, which this domain package must not see; a test at the
integration boundary pins their fingerprints to the tracked ones.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from src.assessments.policy import canonical_bytes
from src.data.models import Interval
from src.data.series import PriceBasis
from src.evaluation import OutcomeSpec
from src.strategies import (
    MomentumInTrendContext,
    ResearchHypothesis,
    TrendAlignment,
    TrendCrossover,
)
from src.strategies.spec import HypothesisSpec


class StudyDefinitionError(ValueError):
    """Raised when a study definition is malformed."""


#: Identity of the first study. A methodology change is a new version.
STUDY_ID: str = "baseline_study"
STUDY_VERSION: int = 1

#: Layout of the generated artifacts (manifest keys, CSV columns).
STUDY_SCHEMA_VERSION: int = 1

#: The universe, in reporting order. Five liquid US-listed ETFs across four
#: return drivers, all listed before 2005 and, to the best of the authors'
#: knowledge, unsplit within the window. Chosen for asset-class diversity
#: and raw-basis safety, not for how any hypothesis behaves on them.
UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "IWM", "TLT", "GLD")

INTERVAL: Interval = Interval.DAY_1
BASIS: PriceBasis = PriceBasis.RAW

FETCH_START: datetime = datetime(2014, 9, 1, tzinfo=timezone.utc)
OBSERVATION_START: datetime = datetime(2015, 1, 1, tzinfo=timezone.utc)
OBSERVATION_END: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc)
OUTCOME_DATA_END: datetime = datetime(2025, 3, 1, tzinfo=timezone.utc)

#: Forward horizons, in bars of the daily series.
HORIZONS: tuple[int, ...] = (1, 5, 20)

#: Settled bars every symbol must have before ``OBSERVATION_START``:
#: ``sma(50)`` needs 50 and ``trend_crossover`` reads one bar further back.
MINIMUM_WARMUP_BARS: int = 51

#: The current hypotheses, unchanged, in reporting order.
HYPOTHESES: tuple[type[ResearchHypothesis], ...] = (
    TrendAlignment,
    MomentumInTrendContext,
    TrendCrossover,
)

#: Names of the metric and benchmark conventions, so the fingerprint changes
#: if either is redefined. Their content is spelled out in
#: :data:`METRIC_NAMES` and :data:`DELTA_NAMES`.
METRIC_POLICY: str = "descriptive_v1"
BENCHMARK_POLICY: str = "matched_unconditional_v1"

#: Every number reported per result group, and nothing else.
METRIC_NAMES: tuple[str, ...] = (
    "sample_count",
    "mean_forward_return",
    "median_forward_return",
    "min_forward_return",
    "max_forward_return",
    "positive_count",
    "negative_count",
    "zero_count",
    "episode_count",
)

#: Descriptive differences from the matched unconditional row.
DELTA_NAMES: tuple[str, ...] = (
    "mean_delta_vs_matched_unconditional",
    "median_delta_vs_matched_unconditional",
)


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise StudyDefinitionError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise StudyDefinitionError(f"{label} must be timezone-aware")
    return value


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class StudyDefinition:
    """One complete, immutable research definition.

    Constructed once as :data:`BASELINE_STUDY_V1`; tests build small
    instances with short windows to exercise the engine offline. Every field
    is part of :attr:`fingerprint`.
    """

    study_id: str
    study_version: int
    study_schema_version: int
    symbols: tuple[str, ...]
    interval: Interval
    basis: PriceBasis
    fetch_start: datetime
    observation_start: datetime
    observation_end: datetime
    outcome_data_end: datetime
    hypotheses: tuple[type[ResearchHypothesis], ...]
    outcome_specs: tuple[OutcomeSpec, ...]
    minimum_warmup_bars: int
    metric_policy: str = METRIC_POLICY
    benchmark_policy: str = BENCHMARK_POLICY

    def __post_init__(self) -> None:
        set_ = object.__setattr__

        study_id = str(self.study_id).strip()
        if not study_id:
            raise StudyDefinitionError("study_id must not be empty")
        set_(self, "study_id", study_id)
        for name in ("study_version", "study_schema_version", "minimum_warmup_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise StudyDefinitionError(f"{name} must be a positive int, got {value!r}")

        symbols = tuple(str(symbol).strip().upper() for symbol in self.symbols)
        if not symbols or any(not symbol for symbol in symbols):
            raise StudyDefinitionError("symbols must be a non-empty tuple of non-blank symbols")
        if len(set(symbols)) != len(symbols):
            raise StudyDefinitionError(f"symbols must be unique, got {symbols}")
        set_(self, "symbols", symbols)

        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))

        fetch_start = _require_aware(self.fetch_start, "fetch_start")
        observation_start = _require_aware(self.observation_start, "observation_start")
        observation_end = _require_aware(self.observation_end, "observation_end")
        outcome_data_end = _require_aware(self.outcome_data_end, "outcome_data_end")
        if not fetch_start < observation_start < observation_end <= outcome_data_end:
            raise StudyDefinitionError(
                "windows must satisfy fetch_start < observation_start < observation_end "
                "<= outcome_data_end"
            )

        hypotheses = tuple(self.hypotheses)
        if not hypotheses:
            raise StudyDefinitionError("a study must name at least one hypothesis")
        for hypothesis in hypotheses:
            if not (isinstance(hypothesis, type) and issubclass(hypothesis, ResearchHypothesis)):
                raise StudyDefinitionError(
                    f"hypotheses must be ResearchHypothesis classes, got {hypothesis!r}"
                )
        specs = tuple(hypothesis().spec for hypothesis in hypotheses)
        ids = [spec.hypothesis_id for spec in specs]
        if len(set(ids)) != len(ids):
            raise StudyDefinitionError(f"hypothesis ids must be unique, got {ids}")
        set_(self, "hypotheses", hypotheses)
        set_(self, "_hypothesis_specs", specs)

        outcome_specs = tuple(self.outcome_specs)
        if not outcome_specs:
            raise StudyDefinitionError("a study must name at least one outcome specification")
        for spec in outcome_specs:
            if not isinstance(spec, OutcomeSpec):
                raise StudyDefinitionError(f"outcome_specs must contain OutcomeSpec, got {spec!r}")
            if spec.required_basis is not self.basis:
                raise StudyDefinitionError(
                    f"outcome specification {spec.label} requires basis "
                    f"{spec.required_basis.value!r} but the study is on {self.basis.value!r}"
                )
        horizons = [spec.horizon_bars for spec in outcome_specs]
        if len(set(horizons)) != len(horizons):
            raise StudyDefinitionError(f"outcome horizons must be unique, got {horizons}")
        set_(self, "outcome_specs", outcome_specs)

        for name in ("metric_policy", "benchmark_policy"):
            if not str(getattr(self, name)).strip():
                raise StudyDefinitionError(f"{name} must not be empty")

    # -- identity ------------------------------------------------------------

    @property
    def hypothesis_specs(self) -> tuple[HypothesisSpec, ...]:
        """Identity of every hypothesis, taken from the live classes."""
        return self._hypothesis_specs  # type: ignore[attr-defined]

    @property
    def horizons(self) -> tuple[int, ...]:
        return tuple(spec.horizon_bars for spec in self.outcome_specs)

    @property
    def label(self) -> str:
        return f"{self.study_id}_v{self.study_version}"

    def canonical_payload(self) -> dict[str, Any]:
        """The complete definition as plain JSON-able data.

        This is what the fingerprint is taken over, and what the manifest
        records; a human can diff two of these when two runs disagree.
        """
        return {
            "scheme": "research.study_definition",
            "scheme_version": 1,
            "study_id": self.study_id,
            "study_version": self.study_version,
            "study_schema_version": self.study_schema_version,
            "symbols": list(self.symbols),
            "interval": self.interval.value,
            "basis": self.basis.value,
            "fetch_start": _utc_iso(self.fetch_start),
            "observation_start": _utc_iso(self.observation_start),
            "observation_end": _utc_iso(self.observation_end),
            "outcome_data_end": _utc_iso(self.outcome_data_end),
            "minimum_warmup_bars": self.minimum_warmup_bars,
            "hypotheses": [
                {
                    "hypothesis_id": spec.hypothesis_id,
                    "version": spec.version,
                    "fingerprint": spec.fingerprint,
                    "canonical_form": spec.canonical_form,
                }
                for spec in self.hypothesis_specs
            ],
            "outcome_specs": [
                {
                    "horizon_bars": spec.horizon_bars,
                    "fingerprint": spec.fingerprint,
                    "canonical_form": spec.canonical_form,
                }
                for spec in self.outcome_specs
            ],
            "metric_policy": self.metric_policy,
            "metrics": list(METRIC_NAMES),
            "deltas": list(DELTA_NAMES),
            "benchmark_policy": self.benchmark_policy,
        }

    @property
    def fingerprint(self) -> str:
        """Full SHA-256 hex digest of the canonical payload.

        Uses the project's one canonical JSON form, so the identity of a study
        is built exactly the way every other durable identity is.
        """
        return hashlib.sha256(canonical_bytes(self.canonical_payload())).hexdigest()


def _outcome_specs(horizons: Sequence[int], basis: PriceBasis) -> tuple[OutcomeSpec, ...]:
    return tuple(OutcomeSpec(horizon_bars=horizon, required_basis=basis) for horizon in horizons)


#: The study. Frozen; see the module docstring.
BASELINE_STUDY_V1: StudyDefinition = StudyDefinition(
    study_id=STUDY_ID,
    study_version=STUDY_VERSION,
    study_schema_version=STUDY_SCHEMA_VERSION,
    symbols=UNIVERSE,
    interval=INTERVAL,
    basis=BASIS,
    fetch_start=FETCH_START,
    observation_start=OBSERVATION_START,
    observation_end=OBSERVATION_END,
    outcome_data_end=OUTCOME_DATA_END,
    hypotheses=HYPOTHESES,
    outcome_specs=_outcome_specs(HORIZONS, BASIS),
    minimum_warmup_bars=MINIMUM_WARMUP_BARS,
    metric_policy=METRIC_POLICY,
    benchmark_policy=BENCHMARK_POLICY,
)


__all__ = [
    "StudyDefinition",
    "StudyDefinitionError",
    "BASELINE_STUDY_V1",
    "STUDY_ID",
    "STUDY_VERSION",
    "STUDY_SCHEMA_VERSION",
    "UNIVERSE",
    "INTERVAL",
    "BASIS",
    "FETCH_START",
    "OBSERVATION_START",
    "OBSERVATION_END",
    "OUTCOME_DATA_END",
    "HORIZONS",
    "MINIMUM_WARMUP_BARS",
    "HYPOTHESES",
    "METRIC_POLICY",
    "BENCHMARK_POLICY",
    "METRIC_NAMES",
    "DELTA_NAMES",
]
