"""Run Baseline Study v1 end to end: fetch, fingerprint, evaluate, write.

    provider -> BarSeries (one per symbol) -> src.research.run_study -> four files

This module **orchestrates**; it decides nothing about research. The
universe, windows, horizons, hypotheses, metrics and benchmark are the
frozen :data:`~src.research.definition.BASELINE_STUDY_V1`, every number
comes from :func:`~src.research.study.run_study`, and every rendering from
:mod:`src.research.render`. What this layer owns is the same set of things
the snapshot builder owns: which provider, the settled-bars-only fetch, the
check that the source answered the request, the data fingerprints, the
clock, and the filesystem.

Fail-fast, whole-study
----------------------
A study of four of five symbols is a different study. If any symbol cannot
be fetched or does not satisfy the definition, nothing is written; the
error is raised as a classified :class:`~src.application.errors.ApplicationError`.
An output directory that already holds a study artifact is likewise
refused -- a frozen run is never overwritten by a later one; the operator
moves it aside deliberately. The files themselves are written by the
research package's artifact store (:mod:`src.research.artifacts`): as with
the Phase 12 ledger, this layer opens no file of its own (ADR 0005).

The commit SHA is **supplied by the operator** and recorded verbatim. This
layer does not run ``git``; the freeze procedure in
``docs/research_baseline_study.md`` is what ties the recorded SHA to the
committed methodology.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from src.data.provider import MarketDataProvider
from src.data.series import BarSeries
from src.outcomes import bars_fingerprint
from src.research import (
    ARTIFACT_MANIFEST,
    ARTIFACT_NAMES,
    ARTIFACT_OBSERVATIONS,
    ARTIFACT_REPORT,
    ARTIFACT_SUMMARY,
    BASELINE_STUDY_V1,
    SUMMARY_COLUMNS,
    ArtifactError,
    StudyDefinition,
    StudyResult,
    manifest_payload,
    observation_columns,
    observation_rows,
    render_csv,
    render_manifest,
    render_report,
    require_fresh,
    run_study,
    summary_rows,
    write_artifacts,
)
from .errors import ApplicationError, FailureKind, classify
from .snapshot import _require_answers_the_request

Clock = Callable[[], datetime]

#: Where generated studies land when no root is given: the repository's
#: ``data/research``, resolved from this file like every other local data
#: root, never from the working directory. Git-ignored.
DEFAULT_RESEARCH_ROOT: Path = Path(__file__).resolve().parents[2] / "data" / "research"

#: The frozen study's label, for callers that may not see the research package.
STUDY_LABEL: str = BASELINE_STUDY_V1.label

#: A full 40-hex-digit commit SHA. Abbreviated or upper-case values are
#: refused: the manifest must name one commit unambiguously.
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_git_commit(value: object) -> str:
    """Return ``value`` if it is a full lower-case hex SHA-1; raise ``ValueError``."""
    text = str(value).strip() if value is not None else ""
    if not _GIT_COMMIT.match(text):
        raise ValueError(
            f"--git-commit must be a full 40-character lower-case hex SHA, got {value!r}"
        )
    return text


def sha256_text(text: str) -> str:
    """SHA-256 over the exact UTF-8 bytes that are written to disk."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StudyRun:
    """What one run produced and where it put it. Immutable.

    ``artifact_sha256`` holds the hash of every written file, the manifest
    included; the manifest itself records only its three siblings' hashes.
    """

    definition: StudyDefinition
    result: StudyResult
    git_commit: str
    source: str
    retrieved_at: datetime
    generated_at: datetime
    output_dir: Path
    bars_fingerprints: Mapping[str, str]
    manifest: Mapping[str, object]
    artifact_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "bars_fingerprints", MappingProxyType(dict(self.bars_fingerprints)))
        set_(self, "manifest", MappingProxyType(dict(self.manifest)))
        set_(self, "artifact_sha256", MappingProxyType(dict(self.artifact_sha256)))

    def path(self, artifact: str) -> Path:
        return self.output_dir / artifact


def fetch_study_series(
    provider: MarketDataProvider, definition: StudyDefinition, symbol: str
) -> BarSeries:
    """One settled-bars-only fetch covering ``[fetch_start, outcome_data_end)``.

    The provider is asked exactly the definition's window; whether the bars
    it returns honour that window is checked by the research layer, which
    refuses rather than trims. A source with no bars for the symbol is a
    failure here: an empty series cannot answer the study.
    """
    bars = provider.get_bars(
        symbol,
        definition.fetch_start,
        definition.outcome_data_end,
        definition.interval,
        include_unsettled=False,
    )
    if not bars:
        raise ApplicationError(
            FailureKind.PROVIDER,
            "market data",
            f"{symbol}: the data source returned no {definition.interval.value} bars for "
            f"[{definition.fetch_start.isoformat()}, {definition.outcome_data_end.isoformat()})",
        )
    series = BarSeries.from_bars(bars, basis=definition.basis)
    _require_answers_the_request(series, symbol, definition.interval, provider)
    return series


def _require_writable(output_dir: Path) -> None:
    """A completed run is never overwritten; the operator moves it aside."""
    try:
        require_fresh(output_dir)
    except ArtifactError as exc:
        raise ApplicationError(FailureKind.REQUEST, "output", str(exc)) from exc


def run_baseline_study(
    provider: MarketDataProvider,
    *,
    git_commit: str,
    out_root: str | Path | None = None,
    now: Clock = _utc_now,
    definition: StudyDefinition = BASELINE_STUDY_V1,
) -> StudyRun:
    """Fetch every symbol, run the frozen study, write the four artifacts.

    ``now`` is read twice -- once before the first fetch (``retrieved_at``)
    and once after the study completes (``generated_at``) -- and nowhere
    else. ``definition`` is injectable so offline tests can run the engine
    end to end on short windows; the CLI never passes it.
    """
    git_commit = validate_git_commit(git_commit)
    root = DEFAULT_RESEARCH_ROOT if out_root is None else Path(out_root)
    output_dir = root / definition.label

    step = "output"
    try:
        _require_writable(output_dir)

        step = "market data"
        retrieved_at = now()
        series_by_symbol: dict[str, BarSeries] = {}
        for symbol in definition.symbols:
            series_by_symbol[symbol] = fetch_study_series(provider, definition, symbol)
        sources = {series.source for series in series_by_symbol.values()}
        if len(sources) != 1:
            raise ApplicationError(
                FailureKind.DOMAIN,
                step,
                f"the fetched series name different sources {sorted(sources)}; one study "
                "reads one source",
            )
        source = sources.pop()
        fingerprints = {
            symbol: bars_fingerprint(series.bars) for symbol, series in series_by_symbol.items()
        }

        step = "research"
        result = run_study(definition, series_by_symbol)
        generated_at = now()

        step = "render"
        summary_text = render_csv(SUMMARY_COLUMNS, summary_rows(result))
        observations_text = render_csv(
            observation_columns(definition.outcome_specs), observation_rows(result)
        )
        sha256 = {
            ARTIFACT_SUMMARY: sha256_text(summary_text),
            ARTIFACT_OBSERVATIONS: sha256_text(observations_text),
        }
        # The report is rendered from the manifest payload before the report's
        # own hash is known (it never prints that hash); the final manifest
        # then records the hashes of all three sibling files. The manifest's
        # own hash is not inside the manifest -- it is returned and printed.
        def payload(report_sha256: str | None) -> dict:
            return manifest_payload(
                result,
                git_commit=git_commit,
                source=source,
                retrieved_at=retrieved_at,
                generated_at=generated_at,
                bars_fingerprints=fingerprints,
                summary_sha256=sha256[ARTIFACT_SUMMARY],
                observations_sha256=sha256[ARTIFACT_OBSERVATIONS],
                report_sha256=report_sha256,
            )

        report_text = render_report(result, payload(None))
        sha256[ARTIFACT_REPORT] = sha256_text(report_text)
        manifest = payload(sha256[ARTIFACT_REPORT])
        manifest_text = render_manifest(manifest)
        sha256[ARTIFACT_MANIFEST] = sha256_text(manifest_text)

        step = "output"
        _require_writable(output_dir)
        write_artifacts(
            output_dir,
            {
                ARTIFACT_MANIFEST: manifest_text,
                ARTIFACT_SUMMARY: summary_text,
                ARTIFACT_OBSERVATIONS: observations_text,
                ARTIFACT_REPORT: report_text,
            },
        )
    except Exception as exc:  # re-raised as a classified ApplicationError
        raise classify(exc, step) from exc

    return StudyRun(
        definition=definition,
        result=result,
        git_commit=git_commit,
        source=source,
        retrieved_at=retrieved_at,
        generated_at=generated_at,
        output_dir=output_dir,
        bars_fingerprints=fingerprints,
        manifest=manifest,
        artifact_sha256=sha256,
    )


__all__ = [
    "DEFAULT_RESEARCH_ROOT",
    "STUDY_LABEL",
    "ARTIFACT_NAMES",
    "StudyRun",
    "validate_git_commit",
    "sha256_text",
    "fetch_study_series",
    "run_baseline_study",
]
