"""Run Error Analysis v1 end to end: read the frozen source, verify, diagnose, write.

    frozen Baseline Study v1 artifacts -> src.research.run_error_analysis -> four files

This module **orchestrates**; it decides nothing about research and touches
no market data. There is no provider here, no clock other than the one
``generated_at`` reads, and no file access of its own: the frozen source is
read and the outputs are written through the research artifact store, the
one place the research tier opens files (ADR 0005).

Fail closed
-----------
The source directory must hold exactly the frozen artifacts with the pinned
SHA-256 values; anything else is refused before any diagnostic runs and
nothing is written. The output directory must not be, or lie inside, the
source directory, and a completed run is never overwritten. After the
outputs are written the source is re-read and re-hashed: an analysis that
changed its own input would be worthless, so the run proves it did not.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from src.research import (
    ERROR_ANALYSIS_ARTIFACT_NAMES,
    ERROR_ANALYSIS_V1,
    SOURCE_ARTIFACT_NAMES,
    ArtifactError,
    ErrorAnalysisDefinition,
    ErrorAnalysisResult,
    error_analysis_manifest_payload,
    read_artifacts,
    render_diagnostics_csv,
    render_episodes_csv,
    render_error_analysis_manifest,
    render_error_analysis_report,
    require_fresh,
    run_error_analysis,
    write_artifacts,
)
from src.research.error_analysis_render import (
    ARTIFACT_DIAGNOSTICS,
    ARTIFACT_EPISODES,
    ARTIFACT_MANIFEST,
    ARTIFACT_REPORT,
)

from . import study as baseline
from .errors import ApplicationError, FailureKind, classify
from .study import validate_git_commit

Clock = Callable[[], datetime]

#: Where the frozen Baseline Study v1 run lives when nothing is injected:
#: the study's own default output directory. Read-only here.
DEFAULT_ERROR_ANALYSIS_SOURCE: Path = baseline.DEFAULT_RESEARCH_ROOT / baseline.STUDY_LABEL

ERROR_ANALYSIS_LABEL: str = ERROR_ANALYSIS_V1.label


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ErrorAnalysisRun:
    """What one run produced and where it put it. Immutable.

    ``artifact_sha256`` holds the hash of every written file, the manifest
    included; the manifest itself records only its three siblings' hashes.
    """

    definition: ErrorAnalysisDefinition
    result: ErrorAnalysisResult
    git_commit: str
    generated_at: datetime
    source_dir: Path
    output_dir: Path
    source_sha256: Mapping[str, str]
    manifest: Mapping[str, object]
    artifact_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source_sha256", MappingProxyType(dict(self.source_sha256)))
        set_(self, "manifest", MappingProxyType(dict(self.manifest)))
        set_(self, "artifact_sha256", MappingProxyType(dict(self.artifact_sha256)))

    def path(self, artifact: str) -> Path:
        return self.output_dir / artifact


def _require_separate(source_dir: Path, output_dir: Path) -> None:
    source, output = source_dir.resolve(), output_dir.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ApplicationError(
            FailureKind.REQUEST,
            "output",
            f"output directory {output} must not be, contain or lie inside the frozen source "
            f"directory {source}",
        )


def _hashes(texts: Mapping[str, str]) -> dict[str, str]:
    return {name: sha256_text(texts[name]) for name in SOURCE_ARTIFACT_NAMES}


def run_error_analysis_study(
    *,
    git_commit: str,
    source_root: str | Path | None = None,
    out_root: str | Path | None = None,
    now: Clock = _utc_now,
    definition: ErrorAnalysisDefinition = ERROR_ANALYSIS_V1,
) -> ErrorAnalysisRun:
    """Read the frozen source, run the frozen diagnostics, write the four artifacts.

    ``source_root`` is the directory holding the frozen Baseline Study v1
    artifacts (default: the study's own output directory); ``out_root`` is
    the research root under which ``<label>/`` is created. ``definition`` is
    injectable only so offline tests can run the engine on synthetic
    artifacts; the CLI never passes it.
    """
    git_commit = validate_git_commit(git_commit)
    source_dir = DEFAULT_ERROR_ANALYSIS_SOURCE if source_root is None else Path(source_root)
    root = baseline.DEFAULT_RESEARCH_ROOT if out_root is None else Path(out_root)
    output_dir = root / definition.label

    step = "output"
    try:
        _require_separate(source_dir, output_dir)
        try:
            require_fresh(output_dir, ERROR_ANALYSIS_ARTIFACT_NAMES)
        except ArtifactError as exc:
            raise ApplicationError(FailureKind.REQUEST, step, str(exc)) from exc

        step = "source"
        try:
            texts = read_artifacts(source_dir, SOURCE_ARTIFACT_NAMES)
        except ArtifactError as exc:
            raise ApplicationError(FailureKind.REQUEST, step, str(exc)) from exc
        source_sha256 = _hashes(texts)

        step = "analysis"
        result = run_error_analysis(definition, texts)
        generated_at = now()

        step = "render"
        diagnostics_text = render_diagnostics_csv(result)
        episodes_text = render_episodes_csv(result)
        sha256 = {
            ARTIFACT_DIAGNOSTICS: sha256_text(diagnostics_text),
            ARTIFACT_EPISODES: sha256_text(episodes_text),
        }

        def payload(report_sha256: str | None) -> dict:
            return error_analysis_manifest_payload(
                result, git_commit=git_commit, generated_at=generated_at,
                diagnostics_sha256=sha256[ARTIFACT_DIAGNOSTICS],
                episodes_sha256=sha256[ARTIFACT_EPISODES], report_sha256=report_sha256,
            )

        report_text = render_error_analysis_report(result, payload(None))
        sha256[ARTIFACT_REPORT] = sha256_text(report_text)
        manifest = payload(sha256[ARTIFACT_REPORT])
        manifest_text = render_error_analysis_manifest(manifest)
        sha256[ARTIFACT_MANIFEST] = sha256_text(manifest_text)

        step = "output"
        write_artifacts(
            output_dir,
            {
                ARTIFACT_MANIFEST: manifest_text,
                ARTIFACT_DIAGNOSTICS: diagnostics_text,
                ARTIFACT_EPISODES: episodes_text,
                ARTIFACT_REPORT: report_text,
            },
            ERROR_ANALYSIS_ARTIFACT_NAMES,
        )

        step = "source"
        after = _hashes(read_artifacts(source_dir, SOURCE_ARTIFACT_NAMES))
        if after != source_sha256:  # pragma: no cover - would be a defect
            raise ApplicationError(
                FailureKind.DOMAIN, step,
                "the frozen source artifacts changed during the analysis; the run is not trustworthy",
            )
    except Exception as exc:  # re-raised as a classified ApplicationError
        raise classify(exc, step) from exc

    return ErrorAnalysisRun(
        definition=definition, result=result, git_commit=git_commit, generated_at=generated_at,
        source_dir=source_dir, output_dir=output_dir, source_sha256=source_sha256,
        manifest=manifest, artifact_sha256=sha256,
    )


__all__ = [
    "DEFAULT_ERROR_ANALYSIS_SOURCE",
    "ERROR_ANALYSIS_LABEL",
    "ErrorAnalysisRun",
    "run_error_analysis_study",
    "sha256_text",
]
