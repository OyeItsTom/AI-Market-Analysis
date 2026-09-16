"""Phase R: the first benchmarked retrospective research study.

This package turns the machinery that already exists -- Phase 2 features,
Phase 3 hypotheses, Phase 4 outcome evaluation -- on a **fixed** universe and
a **fixed** historical period, and describes what the current hypotheses did
there relative to a matched unconditional benchmark. It adds no hypothesis,
tunes nothing, simulates no trade and infers nothing:

    BarSeries -> build_evidence -> hypothesis.evaluate -> evaluate_observations
              -> summarize -> descriptive groups -> renderable result

Everything a study run depends on is written down once, in
:data:`~src.research.definition.BASELINE_STUDY_V1`, and covered by its
fingerprint. A different universe, window, horizon or hypothesis set is a
different study version, never a parameter.

**A retrospective description is not a prediction, a track record or a
profitability claim.** See ``docs/research_baseline_study.md``.
"""

from .artifacts import (
    ARTIFACT_NAMES,
    ArtifactError,
    existing_artifacts,
    require_fresh,
    write_artifacts,
)
from .definition import (
    BASELINE_STUDY_V1,
    BENCHMARK_POLICY,
    METRIC_POLICY,
    STUDY_ID,
    STUDY_SCHEMA_VERSION,
    STUDY_VERSION,
    StudyDefinition,
    StudyDefinitionError,
)
from .render import (
    ARTIFACT_MANIFEST,
    ARTIFACT_OBSERVATIONS,
    ARTIFACT_REPORT,
    ARTIFACT_SUMMARY,
    LIMITATIONS,
    OBSERVATION_COLUMNS,
    SUMMARY_COLUMNS,
    manifest_payload,
    observation_columns,
    observation_rows,
    render_csv,
    render_manifest,
    render_report,
    summary_rows,
)
from .study import (
    OVERLAP_CAVEAT,
    RETROSPECTIVE_CAVEAT,
    ROW_COVERAGE,
    ROW_MATCHED_UNCONDITIONAL,
    ROW_NEUTRAL_REASON,
    ROW_STATE,
    STATE_ALL,
    DescriptiveStats,
    HorizonAccounting,
    HorizonOutcome,
    HypothesisCoverage,
    ObservationRow,
    ResultGroup,
    StudyError,
    StudyResult,
    SymbolCoverage,
    WindowPartition,
    count_episodes,
    max_abs_single_bar_close_return,
    partition_series,
    run_study,
)

__all__ = [
    "ARTIFACT_NAMES",
    "ArtifactError",
    "existing_artifacts",
    "require_fresh",
    "write_artifacts",
    "BASELINE_STUDY_V1",
    "BENCHMARK_POLICY",
    "METRIC_POLICY",
    "STUDY_ID",
    "STUDY_SCHEMA_VERSION",
    "STUDY_VERSION",
    "StudyDefinition",
    "StudyDefinitionError",
    "ARTIFACT_MANIFEST",
    "ARTIFACT_OBSERVATIONS",
    "ARTIFACT_REPORT",
    "ARTIFACT_SUMMARY",
    "LIMITATIONS",
    "OBSERVATION_COLUMNS",
    "SUMMARY_COLUMNS",
    "manifest_payload",
    "observation_columns",
    "observation_rows",
    "render_csv",
    "render_manifest",
    "render_report",
    "summary_rows",
    "OVERLAP_CAVEAT",
    "RETROSPECTIVE_CAVEAT",
    "ROW_COVERAGE",
    "ROW_MATCHED_UNCONDITIONAL",
    "ROW_NEUTRAL_REASON",
    "ROW_STATE",
    "STATE_ALL",
    "DescriptiveStats",
    "HorizonAccounting",
    "HorizonOutcome",
    "HypothesisCoverage",
    "ObservationRow",
    "ResultGroup",
    "StudyError",
    "StudyResult",
    "SymbolCoverage",
    "WindowPartition",
    "count_episodes",
    "max_abs_single_bar_close_return",
    "partition_series",
    "run_study",
]
