"""Deterministic descriptive aggregation over one partition of the outcome ledger.

    OutcomeReader + LedgerPartition + requested OutcomeSpecs  ->  OutcomeSummary

Phase 12E answers one operational question: *what completed, durable outcomes
does the ledger currently hold for each producer / state / source / spec /
evaluation-version group, and how complete is that sample?* It answers
nothing else. There is no hit rate, no ranking, no comparison across groups,
no significance and no trading interpretation; every number here is a count
or a plain descriptive statistic of ``forward_return`` values that Phase 4
measured and Phase 12B recorded. **Historical outcomes do not establish
future profitability**, and nothing in this module can be read as if they did.

Why every dimension is mandatory
--------------------------------
At one bar the ledger may hold three observation artifacts and one
assessment artifact, and all four measure the *same* market forward return.
Pooling them would turn one market movement into four apparent samples.
Producer, state, source, specification and evaluation version are therefore
all part of every group key, and there is no overall figure across groups.

Coverage is first-class
-----------------------
A summary of completed outcomes alone would hide how many claims never
completed. Every registered artifact is counted, per requested
specification, whether or not it has an outcome, so a group with registered
claims and zero completed outcomes still appears. Because ``PENDING``,
``REFUSED`` and ``OUT_OF_WINDOW`` are derived on each refresh and never
persisted, this module cannot say *why* a registered artifact has no
outcome; coverage means exactly "completed durable outcomes / registered
artifacts" and no cause is inferred.

Two group kinds, one reason
---------------------------
A registered artifact has no evaluation version -- only a completed
:class:`~src.outcomes.models.OutcomeRecord` does. Coverage groups are
therefore keyed without a version and answer "how many registered claims
have *any* completed outcome"; metric groups are keyed with one and carry
their own version-specific coverage against the same denominators, so a
partial re-evaluation under a new version can never borrow the coverage of
the old one. A zero-outcome group is its coverage group alone; no version is
invented for it.

Overlapping windows
-------------------
Consecutive claims share most of their forward window (daily claims at
h=20 overlap in 19 of 20 bars). Outcome samples may have overlapping
forward windows and are descriptive, not independent statistical trials
(:data:`OVERLAP_CAVEAT`). Nothing here deduplicates, corrects or infers.

Purity
------
Records are read through an :class:`~src.outcomes.ports.OutcomeReader`,
each partition iterator exactly once. Nothing here reads a clock, a file, a
network or the environment, nothing writes, and no price or return is
recomputed: the only number read off a record is ``forward_return``.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Iterable, Sequence

from src.assessments.assessment import AssessmentState
from src.evaluation import OutcomeSpec
from src.strategies.research import ResearchState

from .identity import OutcomeTrackingError, require_spec_fingerprint, require_text
from .models import (
    ArtifactKind,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
    TrackedArtifact,
)
from .ports import LedgerPartition, OutcomeReader

#: A descriptive display floor, not a statistical threshold. A metric group
#: with fewer completed outcomes than this reports ``sample_floor_met =
#: False``; its descriptive values are still reported, and reaching the floor
#: says nothing about independence or significance (see
#: :data:`OVERLAP_CAVEAT`). How to present a small sample is a later stage's
#: decision, not this one's.
MIN_SUMMARY_SAMPLES: int = 20

#: The caveat every consumer of a summary must carry with it.
OVERLAP_CAVEAT: str = (
    "Outcome samples may have overlapping forward windows and are descriptive, "
    "not independent statistical trials."
)


class OutcomeSummaryError(OutcomeTrackingError):
    """The summary could not be built as a coherent whole: a malformed request,
    or a reader whose records do not describe one consistent partition."""


# -- keys -------------------------------------------------------------------------------


_KIND_ORDER = {ArtifactKind.OBSERVATION: 0, ArtifactKind.ASSESSMENT: 1}


@dataclass(frozen=True)
class ProducerKey:
    """Who made the claim: one hypothesis (id, version, fingerprint) or one
    policy (fingerprint), together with the artifact kind. Structured, never
    a display string, so two producers can only be equal by being the same."""

    kind: ArtifactKind
    hypothesis_id: str | None = None
    hypothesis_version: int | None = None
    hypothesis_fingerprint: str | None = None
    policy_fingerprint: str | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        try:
            set_(self, "kind", ArtifactKind(self.kind))
        except ValueError:
            raise OutcomeSummaryError(f"unknown artifact kind {self.kind!r}") from None
        hypothesis = (self.hypothesis_id, self.hypothesis_version, self.hypothesis_fingerprint)
        if self.kind is ArtifactKind.OBSERVATION:
            if any(part is None for part in hypothesis) or self.policy_fingerprint is not None:
                raise OutcomeSummaryError(
                    "an observation producer is exactly a hypothesis (id, version, fingerprint)"
                )
            set_(self, "hypothesis_id", require_text(self.hypothesis_id, "hypothesis_id"))
            if isinstance(self.hypothesis_version, bool) or not isinstance(
                self.hypothesis_version, int
            ) or self.hypothesis_version < 1:
                raise OutcomeSummaryError(
                    f"hypothesis_version must be a positive int, got {self.hypothesis_version!r}"
                )
            set_(self, "hypothesis_fingerprint",
                 require_text(self.hypothesis_fingerprint, "hypothesis_fingerprint"))
        else:
            if any(part is not None for part in hypothesis) or self.policy_fingerprint is None:
                raise OutcomeSummaryError(
                    "an assessment producer is exactly a policy fingerprint"
                )
            set_(self, "policy_fingerprint",
                 require_spec_fingerprint(self.policy_fingerprint, "policy_fingerprint"))

    @classmethod
    def of_artifact(cls, artifact: TrackedArtifact) -> "ProducerKey":
        if isinstance(artifact, ObservationArtifact):
            return cls(
                kind=ArtifactKind.OBSERVATION,
                hypothesis_id=artifact.hypothesis_id,
                hypothesis_version=artifact.hypothesis_version,
                hypothesis_fingerprint=artifact.hypothesis_fingerprint,
            )
        if isinstance(artifact, AssessmentArtifact):
            return cls(kind=ArtifactKind.ASSESSMENT, policy_fingerprint=artifact.policy_fingerprint)
        raise OutcomeSummaryError(
            f"expected an ObservationArtifact or AssessmentArtifact, got {type(artifact).__name__}"
        )

    @property
    def label(self) -> str:
        if self.kind is ArtifactKind.OBSERVATION:
            return (f"{self.hypothesis_id}@v{self.hypothesis_version}"
                    f"#{self.hypothesis_fingerprint}")
        return f"policy#{self.policy_fingerprint}"

    @property
    def sort_key(self) -> tuple:
        """Observations before assessments, then the producer's own identity."""
        return (
            _KIND_ORDER[self.kind],
            self.hypothesis_id or "",
            self.hypothesis_version or 0,
            self.hypothesis_fingerprint or "",
            self.policy_fingerprint or "",
        )


def _require_state(value: object, kind: ArtifactKind) -> ResearchState | AssessmentState:
    """The state in the vocabulary of its kind, and never the other one."""
    expected = ResearchState if kind is ArtifactKind.OBSERVATION else AssessmentState
    if not isinstance(value, expected):
        raise OutcomeSummaryError(
            f"a {kind.value} state must be a {expected.__name__}, got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True)
class CoverageGroupKey:
    """One requested specification × one producer × one state × one source.

    No evaluation version: registered artifacts have none.
    """

    spec_fingerprint: str
    producer: ProducerKey
    state: ResearchState | AssessmentState
    source: str

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "spec_fingerprint",
             require_spec_fingerprint(self.spec_fingerprint, "spec_fingerprint"))
        if not isinstance(self.producer, ProducerKey):
            raise OutcomeSummaryError(
                f"producer must be a ProducerKey, got {type(self.producer).__name__}"
            )
        set_(self, "state", _require_state(self.state, self.producer.kind))
        set_(self, "source", require_text(self.source, "source"))

    @property
    def sort_key(self) -> tuple:
        return (self.producer.sort_key, self.state.value, self.source)


@dataclass(frozen=True)
class MetricGroupKey:
    """A coverage key plus the evaluation version the completed outcomes carry."""

    coverage: CoverageGroupKey
    evaluation_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.coverage, CoverageGroupKey):
            raise OutcomeSummaryError(
                f"coverage must be a CoverageGroupKey, got {type(self.coverage).__name__}"
            )
        version = self.evaluation_version
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise OutcomeSummaryError(
                f"evaluation_version must be a positive int, got {version!r}"
            )

    # Read-through to the coverage key, so a consumer of either group reads
    # the same names.
    @property
    def spec_fingerprint(self) -> str:
        return self.coverage.spec_fingerprint

    @property
    def producer(self) -> ProducerKey:
        return self.coverage.producer

    @property
    def state(self) -> ResearchState | AssessmentState:
        return self.coverage.state

    @property
    def source(self) -> str:
        return self.coverage.source

    @property
    def sort_key(self) -> tuple:
        return (self.coverage.sort_key, self.evaluation_version)


# -- groups -----------------------------------------------------------------------------


def _require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OutcomeSummaryError(f"{label} must be a non-negative int, got {value!r}")
    return value


def _fraction(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator``, or ``None`` when there is no denominator.
    Never ``NaN``: "no artifacts" is not "zero coverage". The only division
    in this module; forward returns are never recomputed."""
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class OutcomeCoverageGroup:
    """How complete the sample is for one coverage key. Always present when
    the group has at least one registered artifact, outcomes or not.

    ``artifacts_completed`` counts registered artifacts that have at least
    one completed durable outcome under this specification, under *any*
    evaluation version. It is a count of claims, never of outcome records,
    so it cannot exceed ``artifacts_evaluable``. Per-version completion is
    on each :class:`OutcomeMetricGroup`. The timestamp span covers every
    registered artifact in the group.
    """

    key: CoverageGroupKey
    horizon_bars: int
    artifacts_registered: int
    artifacts_evaluable: int
    artifacts_completed: int
    first_artifact_timestamp: datetime
    last_artifact_timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.key, CoverageGroupKey):
            raise OutcomeSummaryError(
                f"key must be a CoverageGroupKey, got {type(self.key).__name__}"
            )
        _require_count(self.horizon_bars, "horizon_bars")
        if self.horizon_bars < 1:
            raise OutcomeSummaryError(f"horizon_bars must be >= 1, got {self.horizon_bars}")
        _require_count(self.artifacts_registered, "artifacts_registered")
        _require_count(self.artifacts_evaluable, "artifacts_evaluable")
        _require_count(self.artifacts_completed, "artifacts_completed")
        if self.artifacts_registered < 1:
            raise OutcomeSummaryError("a coverage group exists only for registered artifacts")
        if self.artifacts_evaluable > self.artifacts_registered:
            raise OutcomeSummaryError("artifacts_evaluable cannot exceed artifacts_registered")
        if self.artifacts_completed > self.artifacts_evaluable:
            raise OutcomeSummaryError("artifacts_completed cannot exceed artifacts_evaluable")
        if self.last_artifact_timestamp < self.first_artifact_timestamp:
            raise OutcomeSummaryError("last_artifact_timestamp precedes first_artifact_timestamp")

    @property
    def raw_coverage_fraction(self) -> float | None:
        """Artifacts with any completed outcome / registered artifacts."""
        return _fraction(self.artifacts_completed, self.artifacts_registered)

    @property
    def evaluable_coverage_fraction(self) -> float | None:
        """Artifacts with any completed outcome / evaluable registered artifacts."""
        return _fraction(self.artifacts_completed, self.artifacts_evaluable)


@dataclass(frozen=True)
class OutcomeMetricGroup:
    """Descriptive statistics of the completed outcomes under one metric key.

    Exists only when at least one outcome completed under this key: a group
    with no outcomes has no evaluation version to be keyed by, and is
    represented by its coverage group alone.

    ``sample_count`` is both the number of outcome records and the number
    of distinct artifacts measured under this version (an outcome key is
    unique per artifact, specification and version). ``artifacts_registered``
    and ``artifacts_evaluable`` are the coverage group's denominators, so
    the coverage fractions here are *this version's* -- a partial
    re-evaluation under a new version shows its own, smaller coverage. The
    timestamp span covers only the artifacts measured under this version.
    """

    key: MetricGroupKey
    horizon_bars: int
    artifacts_registered: int
    artifacts_evaluable: int
    sample_count: int
    positive_count: int
    negative_count: int
    zero_count: int
    mean_forward_return: float
    median_forward_return: float
    min_forward_return: float
    max_forward_return: float
    first_artifact_timestamp: datetime
    last_artifact_timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.key, MetricGroupKey):
            raise OutcomeSummaryError(
                f"key must be a MetricGroupKey, got {type(self.key).__name__}"
            )
        _require_count(self.horizon_bars, "horizon_bars")
        if self.horizon_bars < 1:
            raise OutcomeSummaryError(f"horizon_bars must be >= 1, got {self.horizon_bars}")
        _require_count(self.artifacts_registered, "artifacts_registered")
        _require_count(self.artifacts_evaluable, "artifacts_evaluable")
        _require_count(self.sample_count, "sample_count")
        _require_count(self.positive_count, "positive_count")
        _require_count(self.negative_count, "negative_count")
        _require_count(self.zero_count, "zero_count")
        if self.sample_count < 1:
            raise OutcomeSummaryError("a metric group exists only for completed outcomes")
        if not (self.sample_count <= self.artifacts_evaluable <= self.artifacts_registered):
            raise OutcomeSummaryError(
                "sample_count cannot exceed artifacts_evaluable, which cannot exceed "
                "artifacts_registered"
            )
        if self.positive_count + self.negative_count + self.zero_count != self.sample_count:
            raise OutcomeSummaryError("sign counts must account for every sample")
        for name, value in (
            ("mean_forward_return", self.mean_forward_return),
            ("median_forward_return", self.median_forward_return),
            ("min_forward_return", self.min_forward_return),
            ("max_forward_return", self.max_forward_return),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise OutcomeSummaryError(f"{name} must be a finite number, got {value!r}")
        # The median is an element or the exact midpoint of two, so it always
        # lies within the range; the mean is not pinned the same way because a
        # correctly rounded ``fmean`` of identical values can differ from them
        # by one ulp.
        if not (self.min_forward_return <= self.median_forward_return
                <= self.max_forward_return):
            raise OutcomeSummaryError("median must lie between min and max")
        if self.last_artifact_timestamp < self.first_artifact_timestamp:
            raise OutcomeSummaryError("last_artifact_timestamp precedes first_artifact_timestamp")

    @property
    def raw_coverage_fraction(self) -> float | None:
        """This version's measured artifacts / registered artifacts."""
        return _fraction(self.sample_count, self.artifacts_registered)

    @property
    def evaluable_coverage_fraction(self) -> float | None:
        """This version's measured artifacts / evaluable registered artifacts."""
        return _fraction(self.sample_count, self.artifacts_evaluable)

    @property
    def sample_floor_met(self) -> bool:
        """Whether ``sample_count`` reaches :data:`MIN_SUMMARY_SAMPLES`, the
        descriptive display floor. A flag, not a filter, and not a statement
        of statistical sufficiency: the values are reported either way, and
        the samples may overlap."""
        return self.sample_count >= MIN_SUMMARY_SAMPLES


@dataclass(frozen=True)
class OutcomeSummary:
    """One partition's coverage and completed-outcome groups, in a fixed order.

    Groups are ordered by requested specification, then artifact kind,
    producer identity, state, source and (for metric groups) evaluation
    version -- never by the order the reader returned records. There is no
    figure across groups: no overall return, no ranking, no best anything.
    """

    partition: LedgerPartition
    specs: tuple[OutcomeSpec, ...]
    coverage_groups: tuple[OutcomeCoverageGroup, ...]
    metric_groups: tuple[OutcomeMetricGroup, ...]

    #: Carried on the type so no consumer can receive a summary without it.
    overlap_caveat: ClassVar[str] = OVERLAP_CAVEAT

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if not isinstance(self.partition, LedgerPartition):
            raise OutcomeSummaryError(
                f"partition must be a LedgerPartition, got {type(self.partition).__name__}"
            )
        set_(self, "specs", tuple(self.specs))
        set_(self, "coverage_groups", tuple(self.coverage_groups))
        set_(self, "metric_groups", tuple(self.metric_groups))
        for spec in self.specs:
            if not isinstance(spec, OutcomeSpec):
                raise OutcomeSummaryError(f"specs must be OutcomeSpec, got {type(spec).__name__}")
        for group in self.coverage_groups:
            if not isinstance(group, OutcomeCoverageGroup):
                raise OutcomeSummaryError(
                    f"coverage_groups must be OutcomeCoverageGroup, got {type(group).__name__}"
                )
        for group in self.metric_groups:
            if not isinstance(group, OutcomeMetricGroup):
                raise OutcomeSummaryError(
                    f"metric_groups must be OutcomeMetricGroup, got {type(group).__name__}"
                )

    # -- operational totals, all derived ---------------------------------------------

    @property
    def artifacts_registered(self) -> int:
        """Distinct registered artifacts in the partition (each artifact is
        counted once, however many specifications were requested)."""
        if not self.specs:
            return 0
        first = self.specs[0].fingerprint
        return sum(g.artifacts_registered for g in self.coverage_groups
                   if g.key.spec_fingerprint == first)

    @property
    def outcomes_completed(self) -> int:
        """Completed durable outcome *records* under the requested
        specifications, every version counted -- an operational total, not
        a sample size (one record per artifact, specification and version)."""
        return sum(g.sample_count for g in self.metric_groups)

    def metric_groups_for(self, key: CoverageGroupKey) -> tuple[OutcomeMetricGroup, ...]:
        """The completed metric groups (one per evaluation version, possibly
        none) that belong to one coverage group."""
        if not isinstance(key, CoverageGroupKey):
            raise OutcomeSummaryError(
                f"key must be a CoverageGroupKey, got {type(key).__name__}"
            )
        return tuple(g for g in self.metric_groups if g.key.coverage == key)


# -- the summary --------------------------------------------------------------------------


def summarize_outcomes(
    reader: OutcomeReader,
    partition: LedgerPartition,
    specs: Sequence[OutcomeSpec],
) -> OutcomeSummary:
    """Coverage and descriptive metrics for one partition under the requested specs.

    1. **Request.** ``partition`` is a :class:`~src.outcomes.ports.LedgerPartition`;
       ``specs`` is a non-empty sequence of distinct :class:`OutcomeSpec` on
       the partition's basis, kept in the caller's order.
    2. **Artifacts.** ``reader.iter_artifacts(partition)`` once. Every record
       must be a tracked artifact of this partition; a key seen twice raises.
    3. **Outcomes.** ``reader.iter_outcomes(partition)`` once. Every record must
       be an outcome of this partition, under a key seen once, embedding an
       artifact that is registered with exactly that content. Outcomes under
       specifications that were not requested are then ignored; an outcome
       under a requested specification must carry that specification's
       ``horizon_bars``.
    4. **Coverage.** One group per registered (producer, state, source) × each
       requested specification, counting registered and evaluable artifacts
       and completed outcomes.
    5. **Metrics.** One group per (coverage key, evaluation version) with at
       least one completed outcome: sign counts and mean / median / min / max
       of ``forward_return``, read as stored and never recomputed, with the
       coverage group's denominators so the version's own coverage is visible.

    Raises
    ------
    OutcomeSummaryError
        A malformed request, or a reader whose records do not describe one
        consistent partition (foreign record, duplicate key, orphan or
        mismatched outcome, horizon contradiction).
    """
    if not isinstance(partition, LedgerPartition):
        raise OutcomeSummaryError(
            f"partition must be a LedgerPartition, got {type(partition).__name__}"
        )
    requested = _require_specs(specs, partition)
    by_fingerprint = {spec.fingerprint: spec for spec in requested}
    position = {spec.fingerprint: index for index, spec in enumerate(requested)}

    artifacts = _load_artifacts(reader.iter_artifacts(partition), partition)
    outcomes = _load_outcomes(reader.iter_outcomes(partition), partition, artifacts)

    # -- coverage: every registered artifact, under every requested spec ----------
    registered: dict[CoverageGroupKey, list[TrackedArtifact]] = {}
    for artifact in artifacts.values():
        producer = ProducerKey.of_artifact(artifact)
        for spec in requested:
            key = CoverageGroupKey(spec_fingerprint=spec.fingerprint, producer=producer,
                                   state=artifact.state, source=artifact.source)
            registered.setdefault(key, []).append(artifact)

    # Completion is counted per *artifact*: an artifact measured under two
    # evaluation versions is one completed claim, so coverage never exceeds 1.
    completed: dict[CoverageGroupKey, set[str]] = {}
    measured: dict[MetricGroupKey, list[OutcomeRecord]] = {}
    for outcome in outcomes.values():
        spec = by_fingerprint.get(outcome.spec_fingerprint)
        if spec is None:
            continue  # durable, but outside the requested scope
        if outcome.horizon_bars != spec.horizon_bars:
            raise OutcomeSummaryError(
                f"outcome {outcome.outcome_key} carries horizon_bars={outcome.horizon_bars} "
                f"under spec#{spec.fingerprint}, whose horizon is {spec.horizon_bars}"
            )
        artifact = outcome.artifact
        coverage_key = CoverageGroupKey(
            spec_fingerprint=spec.fingerprint, producer=ProducerKey.of_artifact(artifact),
            state=artifact.state, source=artifact.source,
        )
        key = MetricGroupKey(coverage=coverage_key, evaluation_version=outcome.evaluation_version)
        completed.setdefault(coverage_key, set()).add(outcome.artifact_key)
        measured.setdefault(key, []).append(outcome)

    # Requested-specification order first, then each key's own order; the
    # reader's order plays no part.
    coverage_groups = tuple(
        _coverage_group(key, by_fingerprint[key.spec_fingerprint], members,
                        len(completed.get(key, ())))
        for key, members in sorted(
            registered.items(),
            key=lambda item: (position[item[0].spec_fingerprint], item[0].sort_key),
        )
    )
    metric_groups = tuple(
        _metric_group(key, by_fingerprint[key.spec_fingerprint], registered[key.coverage], members)
        for key, members in sorted(
            measured.items(),
            key=lambda item: (position[item[0].spec_fingerprint], item[0].sort_key),
        )
    )
    return OutcomeSummary(partition=partition, specs=requested,
                          coverage_groups=coverage_groups, metric_groups=metric_groups)


# -- steps ------------------------------------------------------------------------------


def _require_specs(specs: object, partition: LedgerPartition) -> tuple[OutcomeSpec, ...]:
    if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
        raise OutcomeSummaryError(
            f"specs must be a sequence of OutcomeSpec, got {type(specs).__name__}"
        )
    checked = tuple(specs)
    if not checked:
        raise OutcomeSummaryError(
            "specs must not be empty; a summary needs a specification to cover"
        )
    seen: set[str] = set()
    for spec in checked:
        if not isinstance(spec, OutcomeSpec):
            raise OutcomeSummaryError(
                f"every spec must be an OutcomeSpec, got {type(spec).__name__}"
            )
        if spec.required_basis is not partition.basis:
            raise OutcomeSummaryError(
                f"spec {spec.label} requires {spec.required_basis.value!r} prices but the "
                f"partition is {partition.basis.value!r}"
            )
        if spec.fingerprint in seen:
            raise OutcomeSummaryError(f"duplicate outcome specification {spec.label}")
        seen.add(spec.fingerprint)
    return checked


def _load_artifacts(
    records: Iterable[TrackedArtifact], partition: LedgerPartition
) -> dict[str, TrackedArtifact]:
    held: dict[str, TrackedArtifact] = {}
    for record in records:
        if not isinstance(record, TrackedArtifact):
            raise OutcomeSummaryError(
                f"iter_artifacts yielded {type(record).__name__}, not a TrackedArtifact"
            )
        if not partition.contains(record):
            raise OutcomeSummaryError(
                f"artifact {record.artifact_key} belongs to "
                f"{LedgerPartition.of_artifact(record).label}, not to {partition.label}"
            )
        key = record.artifact_key
        if key in held:
            raise OutcomeSummaryError(f"iter_artifacts yielded artifact {key} twice")
        held[key] = record
    return held


def _load_outcomes(
    records: Iterable[OutcomeRecord], partition: LedgerPartition,
    artifacts: dict[str, TrackedArtifact],
) -> dict[str, OutcomeRecord]:
    held: dict[str, OutcomeRecord] = {}
    for record in records:
        if not isinstance(record, OutcomeRecord):
            raise OutcomeSummaryError(
                f"iter_outcomes yielded {type(record).__name__}, not an OutcomeRecord"
            )
        if not partition.contains(record.artifact):
            raise OutcomeSummaryError(
                f"outcome {record.outcome_key} belongs to "
                f"{LedgerPartition.of_outcome(record).label}, not to {partition.label}"
            )
        key = record.outcome_key
        if key in held:
            raise OutcomeSummaryError(f"iter_outcomes yielded outcome {key} twice")
        registered = artifacts.get(record.artifact_key)
        if registered is None:
            raise OutcomeSummaryError(
                f"outcome {key} embeds artifact {record.artifact_key}, which iter_artifacts "
                "did not return; a summary covers only registered claims"
            )
        if registered != record.artifact:
            raise OutcomeSummaryError(
                f"outcome {key} embeds artifact {record.artifact_key} with content that "
                "differs from the registered artifact"
            )
        held[key] = record
    return held


def _span(artifacts: Sequence[TrackedArtifact]) -> tuple[datetime, datetime]:
    stamps = [artifact.timestamp for artifact in artifacts]
    return min(stamps), max(stamps)


def _coverage_group(
    key: CoverageGroupKey, spec: OutcomeSpec, members: Sequence[TrackedArtifact], completed: int
) -> OutcomeCoverageGroup:
    first, last = _span(members)
    return OutcomeCoverageGroup(
        key=key,
        horizon_bars=spec.horizon_bars,
        artifacts_registered=len(members),
        artifacts_evaluable=sum(1 for artifact in members if artifact.is_evaluable),
        artifacts_completed=completed,
        first_artifact_timestamp=first,
        last_artifact_timestamp=last,
    )


def _metric_group(
    key: MetricGroupKey, spec: OutcomeSpec, registered: Sequence[TrackedArtifact],
    members: Sequence[OutcomeRecord],
) -> OutcomeMetricGroup:
    returns = [outcome.forward_return for outcome in members]
    first, last = _span([outcome.artifact for outcome in members])
    return OutcomeMetricGroup(
        key=key,
        horizon_bars=spec.horizon_bars,
        artifacts_registered=len(registered),
        artifacts_evaluable=sum(1 for artifact in registered if artifact.is_evaluable),
        sample_count=len(returns),
        positive_count=sum(1 for value in returns if value > 0.0),
        negative_count=sum(1 for value in returns if value < 0.0),
        # ``-0.0 == 0.0``, so a negative zero is a zero, never a negative.
        zero_count=sum(1 for value in returns if value == 0.0),
        mean_forward_return=statistics.fmean(returns),
        median_forward_return=statistics.median(returns),
        min_forward_return=min(returns),
        max_forward_return=max(returns),
        first_artifact_timestamp=first,
        last_artifact_timestamp=last,
    )


__all__ = [
    "MIN_SUMMARY_SAMPLES",
    "OVERLAP_CAVEAT",
    "OutcomeSummaryError",
    "ProducerKey",
    "CoverageGroupKey",
    "MetricGroupKey",
    "OutcomeCoverageGroup",
    "OutcomeMetricGroup",
    "OutcomeSummary",
    "summarize_outcomes",
]
