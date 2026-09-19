"""Deterministic renderings of an :class:`~src.research.error_analysis.ErrorAnalysisResult`.

Four artifacts::

    manifest.json     identity, source lineage (pinned hashes), sibling hashes
    diagnostics.csv   one row per diagnostic cell, typed by ``row_type``
    episodes.csv      one row per episode
    report.md         the same facts as tables, plus the fixed limitations

Facts only. The report states counts, partitions, segment and episode
diagnostics and sign patterns, and labels the predeclared decision aids as
descriptive reading aids. It draws no research conclusion; that is the
human review gate's job, after a frozen real run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .error_analysis import (
    ROW_CLASS_SIGNS,
    ROW_CROSSOVER_EVENT,
    ROW_EPISODE_START,
    ROW_EPISODE_SUMMARY,
    ROW_GATE_CROSSTAB,
    ROW_GATE_PARTITION,
    ROW_SEGMENT_MATCHED,
    ROW_SEGMENT_STATE,
    SOURCE_ARTIFACT_NAMES,
    DiagnosticRow,
    ErrorAnalysisDefinition,
    ErrorAnalysisResult,
)
from .render import format_float, format_int, format_timestamp, render_csv

ARTIFACT_MANIFEST: str = "manifest.json"
ARTIFACT_DIAGNOSTICS: str = "diagnostics.csv"
ARTIFACT_EPISODES: str = "episodes.csv"
ARTIFACT_REPORT: str = "report.md"
ARTIFACT_NAMES: tuple[str, ...] = (
    ARTIFACT_MANIFEST, ARTIFACT_DIAGNOSTICS, ARTIFACT_EPISODES, ARTIFACT_REPORT,
)


def diagnostic_columns(horizons: Sequence[int]) -> tuple[str, ...]:
    columns = [
        "row_type", "hypothesis_id", "symbol", "asset_class", "state", "horizon_bars", "segment",
        "partition", "reason_signature", "momentum_state", "sampling_view", "count",
        "sample_count", "mean_forward_return", "median_forward_return", "min_forward_return",
        "max_forward_return", "positive_count", "negative_count", "zero_count", "episode_count",
        "mean_delta", "median_delta", "delta_reference", "length_min", "length_median",
        "length_max", "share_largest_episode", "share_three_largest", "mean_delta_sign",
        "median_delta_sign", "timestamp", "bars_since_previous_cross",
    ]
    for h in horizons:
        columns += [f"status_h{h}", f"return_h{h}"]
    return tuple(columns)


def episode_columns(horizons: Sequence[int]) -> tuple[str, ...]:
    columns = [
        "hypothesis_id", "hypothesis_version", "hypothesis_fingerprint", "symbol", "state",
        "reason_signature", "episode_index", "start_timestamp", "end_timestamp", "length",
    ]
    for h in horizons:
        columns += [f"start_status_h{h}", f"start_return_h{h}"]
    return tuple(columns)


#: Column layouts for the frozen horizons (1, 5, 20).
DIAGNOSTIC_COLUMNS: tuple[str, ...] = diagnostic_columns((1, 5, 20))
EPISODE_COLUMNS: tuple[str, ...] = episode_columns((1, 5, 20))

SEMANTIC_CONTRACT: tuple[str, ...] = (
    "The source vocabulary (src/strategies/research.py) defines BULLISH as \"this "
    "deterministic hypothesis classifies the supplied evidence as bullish-leaning\" and states "
    "that it does not mean \"buy\" or \"this will rise\"; BEARISH is the mirror. The states are "
    "structural classifications of the current SMA20/SMA50 configuration (and, for "
    "momentum_in_trend_context, RSI14 read against it); they promise nothing about forward "
    "direction.",
    "Accordingly, the Phase R observation on the equity ETFs is described here as: observed "
    "state-conditioned forward-return differences opposite to the colloquial directional "
    "connotation of the state names. It is not described as a wrong prediction, and this "
    "analysis does not reverse, rename or re-tune any state.",
)

LIMITATIONS: tuple[str, ...] = (
    "Every number here is a regrouping of the frozen Baseline Study v1 rows; no new market data "
    "was fetched and no forward return was computed.",
    "Forward windows overlap (up to 4 of 5 bars at h5 and 19 of 20 at h20); counts are not "
    "independent trials.",
    "episode_count, episode lengths and the episode-start view are descriptive reading aids; "
    "none is an effective sample size or an independence correction, and the episode-start view "
    "is a secondary sampling view, not a replacement for the Phase R results.",
    "The segment, episode-share and gate-partition decision aids are predeclared descriptive "
    "rules for the human review gate; they are not significance tests, confidence criteria, "
    "robustness proofs or acceptance thresholds, and no change is selected by them.",
    "Asset class is metadata for reading sign patterns; nothing is pooled by class and no "
    "class-specific parameter exists.",
    "The two level hypotheses share the SMA20/SMA50 relation; momentum_in_trend_context gates the "
    "same trend state with RSI14, so agreement between them is not independent confirmation.",
    "Crossover events are one bar each and few; their listing supports a later decision, not a "
    "conclusion here.",
    "RAW price basis, provider revisions/back-fills, the absence of an exchange calendar and the "
    "retrospective nature of the source study all carry over from Baseline Study v1.",
    "Data from 2025-03-01 onward was not read; the source rows end at 2024-12-31 and any later "
    "row is refused.",
    "Nothing here is a profitability, edge, accuracy or significance claim, and no hypothesis, "
    "threshold or feature was changed.",
)

_UTC = timezone.utc


def _blank(columns: Sequence[str]) -> dict[str, str]:
    return {c: "" for c in columns}


def diagnostic_rows(result: ErrorAnalysisResult) -> list[dict[str, str]]:
    columns = diagnostic_columns(result.definition.horizons)
    rows: list[dict[str, str]] = []
    for d in result.diagnostics:
        row = _blank(columns)
        row.update(
            row_type=d.row_type, hypothesis_id=d.hypothesis_id, symbol=d.symbol,
            asset_class=d.asset_class, state=d.state, horizon_bars=format_int(d.horizon_bars),
            segment=d.segment, partition=d.partition, reason_signature=d.reason_signature,
            momentum_state=d.momentum_state, sampling_view=d.sampling_view,
            count=format_int(d.count), episode_count=format_int(d.episode_count),
            mean_delta=format_float(d.mean_delta), median_delta=format_float(d.median_delta),
            delta_reference=d.delta_reference, length_min=format_int(d.length_min),
            length_median=format_float(d.length_median), length_max=format_int(d.length_max),
            share_largest_episode=format_float(d.share_largest_episode),
            share_three_largest=format_float(d.share_three_largest),
            mean_delta_sign=d.mean_delta_sign, median_delta_sign=d.median_delta_sign,
            timestamp=format_timestamp(d.timestamp),
            bars_since_previous_cross=format_int(d.bars_since_previous_cross),
        )
        if d.stats is not None:
            s = d.stats
            row.update(
                sample_count=format_int(s.sample_count),
                mean_forward_return=format_float(s.mean_forward_return),
                median_forward_return=format_float(s.median_forward_return),
                min_forward_return=format_float(s.min_forward_return),
                max_forward_return=format_float(s.max_forward_return),
                positive_count=format_int(s.positive_count),
                negative_count=format_int(s.negative_count),
                zero_count=format_int(s.zero_count),
            )
        for hv in d.returns:
            row[f"status_h{hv.horizon_bars}"] = hv.status
            row[f"return_h{hv.horizon_bars}"] = format_float(hv.outcome_value)
        rows.append(row)
    return rows


def episode_rows(result: ErrorAnalysisResult) -> list[dict[str, str]]:
    columns = episode_columns(result.definition.horizons)
    rows: list[dict[str, str]] = []
    for e in result.episodes:
        row = _blank(columns)
        row.update(
            hypothesis_id=e.hypothesis_id, hypothesis_version=format_int(e.hypothesis_version),
            hypothesis_fingerprint=e.hypothesis_fingerprint, symbol=e.symbol, state=e.state,
            reason_signature=e.reason_signature, episode_index=format_int(e.episode_index),
            start_timestamp=format_timestamp(e.start_timestamp),
            end_timestamp=format_timestamp(e.end_timestamp), length=format_int(e.length),
        )
        for hv in e.start_outcomes:
            row[f"start_status_h{hv.horizon_bars}"] = hv.status
            row[f"start_return_h{hv.horizon_bars}"] = format_float(hv.outcome_value)
        rows.append(row)
    return rows


def render_diagnostics_csv(result: ErrorAnalysisResult) -> str:
    return render_csv(diagnostic_columns(result.definition.horizons), diagnostic_rows(result))


def render_episodes_csv(result: ErrorAnalysisResult) -> str:
    return render_csv(episode_columns(result.definition.horizons), episode_rows(result))


def manifest_payload(
    result: ErrorAnalysisResult,
    *,
    git_commit: str,
    generated_at: datetime,
    diagnostics_sha256: str,
    episodes_sha256: str,
    report_sha256: str | None = None,
) -> dict[str, Any]:
    """Non-circular: hashes of the three siblings, never of the manifest itself."""
    if not isinstance(generated_at, datetime) or generated_at.tzinfo is None:
        raise ValueError("generated_at must be a timezone-aware datetime")
    definition: ErrorAnalysisDefinition = result.definition
    source = result.source_manifest
    return {
        "study_id": definition.study_id,
        "study_version": definition.study_version,
        "study_schema_version": definition.study_schema_version,
        "study_fingerprint": definition.fingerprint,
        "study_definition": definition.canonical_payload(),
        "git_commit": git_commit,
        "generated_at": format_timestamp(generated_at),
        "source": {
            "study_id": definition.source_study_id,
            "study_version": definition.source_study_version,
            "study_fingerprint": definition.source_study_fingerprint,
            "methodology_sha": definition.source_methodology_sha,
            "result_sha": definition.source_result_sha,
            "artifact_sha256": {n: definition.source_hashes[n] for n in SOURCE_ARTIFACT_NAMES},
            "source": source.get("source"),
            "retrieved_at": source.get("retrieved_at"),
            "observation_start": format_timestamp(definition.source_observation_start),
            "observation_end": format_timestamp(definition.source_observation_end),
            "observation_rows": result.observation_rows,
            "summary_rows_cross_checked": result.source_rows_checked,
        },
        "network": "none: no provider was constructed or called; every value is read from the frozen artifacts",
        "future_data": "untouched: no row on or after 2025-01-01 is accepted; data from 2025-03-01 onward was not read",
        "segments": [
            {"label": label, "start": format_timestamp(a), "end": format_timestamp(b)}
            for label, a, b in definition.segments
        ],
        "asset_classes": {s: definition.asset_classes[s] for s in definition.symbols},
        "diagnostics": list(definition.diagnostics),
        "row_types": list(definition.row_types),
        "decision_aids": {
            "segment_majority": definition.decision_aid_segment_majority,
            "episode_share": definition.decision_aid_episode_share,
            "kind": "predeclared descriptive decision aids; not statistical tests, not verdicts",
            "entries": [
                {"aid": a.aid, "hypothesis_id": a.hypothesis_id, "symbol": a.symbol,
                 "asset_class": a.asset_class, "state": a.state, "horizon_bars": a.horizon_bars,
                 **dict(a.detail)}
                for a in result.decision_aids
            ],
        },
        "counts": {
            "episodes": len(result.episodes),
            "diagnostic_rows": len(result.diagnostics),
        },
        "artifacts": {
            ARTIFACT_DIAGNOSTICS: {"sha256": diagnostics_sha256, "git_tracked": True},
            ARTIFACT_EPISODES: {"sha256": episodes_sha256, "git_tracked": True},
            ARTIFACT_REPORT: {"sha256": report_sha256, "git_tracked": True},
        },
        "semantic_contract": list(SEMANTIC_CONTRACT),
        "limitations": list(LIMITATIONS),
    }


def render_manifest(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


# -- report --------------------------------------------------------------------------------------


def _r(value: float | None) -> str:
    return "" if value is None else f"{value:+.6f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows]
    return lines


def _stats_cells(d: DiagnosticRow) -> list[Any]:
    s = d.stats
    if s is None:
        return ["", "", "", "", "", "", "", ""]
    return [s.sample_count, _r(s.mean_forward_return), _r(s.median_forward_return),
            _r(s.min_forward_return), _r(s.max_forward_return), s.positive_count,
            s.negative_count, s.zero_count]


def render_report(result: ErrorAnalysisResult, manifest: Mapping[str, Any]) -> str:
    definition = result.definition
    D = result.diagnostics
    lines: list[str] = [f"# Phase 13A — {definition.study_id} v{definition.study_version}", ""]

    lines += ["## Identity and lineage", ""]
    lines += [
        f"- study: `{definition.label}` (schema {definition.study_schema_version}); fingerprint "
        f"`{definition.fingerprint}`",
        f"- git commit: `{manifest['git_commit']}`; generated at: `{manifest['generated_at']}`",
        f"- source: `{definition.source_study_id}` v{definition.source_study_version}, fingerprint "
        f"`{definition.source_study_fingerprint}`, methodology `{definition.source_methodology_sha}`, "
        f"result `{definition.source_result_sha}`",
        f"- source artifacts verified by SHA-256: " + ", ".join(
            f"`{n}` `{definition.source_hashes[n]}`" for n in SOURCE_ARTIFACT_NAMES),
        f"- source rows: {result.observation_rows}; Phase R result rows recomputed and matched: "
        f"{result.source_rows_checked}",
        f"- observation window `[{format_timestamp(definition.source_observation_start)}, "
        f"{format_timestamp(definition.source_observation_end)})`; no later row accepted; data from "
        "2025-03-01 onward not read",
        "- network: none",
        "",
    ]

    lines += ["## D6 — Semantic contract", ""]
    lines += [f"- {s}" for s in SEMANTIC_CONTRACT] + [""]

    lines += ["## D1 — Episode structure", ""]
    lines += _table(
        ["hypothesis", "symbol", "class", "state", "observations", "episodes", "len min",
         "len median", "len max", "share largest", "share top 3"],
        [[d.hypothesis_id, d.symbol, d.asset_class, d.state, d.count, d.episode_count,
          d.length_min, _r(d.length_median).lstrip("+"), d.length_max,
          _r(d.share_largest_episode).lstrip("+"), _r(d.share_three_largest).lstrip("+")]
         for d in D if d.row_type == ROW_EPISODE_SUMMARY],
    )
    lines += ["", "### Episode-start sampling view (secondary; not a replacement, not an "
              "independence correction)", ""]
    lines += _table(
        ["hypothesis", "symbol", "state", "h", "episodes", "n", "mean", "median", "min", "max",
         "pos", "neg", "zero"],
        [[d.hypothesis_id, d.symbol, d.state, d.horizon_bars, d.episode_count, *_stats_cells(d)]
         for d in D if d.row_type == ROW_EPISODE_START],
    )
    lines.append("")

    lines += ["## D2 — Gate decomposition on common timestamps (trend_alignment × momentum_in_trend_context)", ""]
    lines += _table(
        ["symbol", "trend state", "momentum state", "count"],
        [[d.symbol, d.state, d.momentum_state, d.count] for d in D if d.row_type == ROW_GATE_CROSSTAB],
    )
    lines += ["", "Partitions of trend-directional bars by the momentum state at the same bar; "
              "deltas are against the parent trend state's own evaluated sample:", ""]
    lines += _table(
        ["symbol", "trend", "h", "partition", "reason signature", "n", "mean", "median", "min",
         "max", "pos", "neg", "zero", "mean delta", "median delta"],
        [[d.symbol, d.state, d.horizon_bars, d.partition,
          f"`{d.reason_signature}`" if d.reason_signature else "", *_stats_cells(d),
          _r(d.mean_delta), _r(d.median_delta)]
         for d in D if d.row_type == ROW_GATE_PARTITION],
    )
    lines.append("")

    lines += ["## D3 — Predeclared temporal segments", ""]
    lines += ["Segments: " + ", ".join(f"`{label}` [{format_timestamp(a)}, {format_timestamp(b)})"
                                        for label, a, b in definition.segments), ""]
    for hypothesis_id in definition.hypothesis_ids:
        lines += [f"### {hypothesis_id}", ""]
        lines += _table(
            ["symbol", "segment", "h", "state", "n", "episodes", "mean", "median", "min", "max",
             "pos", "neg", "zero", "mean delta", "median delta"],
            [[d.symbol, d.segment, d.horizon_bars, d.state, d.count, d.episode_count,
              *_stats_cells(d)[1:], _r(d.mean_delta), _r(d.median_delta)]
             for d in D if d.row_type in (ROW_SEGMENT_MATCHED, ROW_SEGMENT_STATE)
             and d.hypothesis_id == hypothesis_id],
        )
        lines.append("")

    lines += ["## D4 — Asset-class sign annotation (metadata only; nothing pooled)", ""]
    lines += _table(
        ["hypothesis", "state", "h", "class", "symbol", "n", "mean delta", "median delta",
         "mean sign", "median sign"],
        [[d.hypothesis_id, d.state, d.horizon_bars, d.asset_class, d.symbol or "(class signs)",
          d.count, _r(d.mean_delta), _r(d.median_delta), d.mean_delta_sign, d.median_delta_sign]
         for d in D if d.row_type == ROW_CLASS_SIGNS],
    )
    lines.append("")

    lines += ["## D5 — Crossover events", ""]
    events = [d for d in D if d.row_type == ROW_CROSSOVER_EVENT]
    headers = ["symbol", "timestamp", "state", "bars since previous cross"]
    headers += [f"h{h}" for h in definition.horizons]
    lines += _table(
        headers,
        [[d.symbol, format_timestamp(d.timestamp), d.state,
          "" if d.bars_since_previous_cross is None else d.bars_since_previous_cross,
          *[_r(hv.outcome_value) if hv.status == "evaluated" else hv.status for hv in d.returns]]
         for d in events],
    ) if events else ["(no directional crossover observations)"]
    lines.append("")

    lines += ["## Predeclared descriptive decision aids", ""]
    lines += ["These are reading aids for the review gate, computed for every symbol, state and "
              "horizon. They are not statistical tests, confidence criteria, robustness proofs or "
              "acceptance thresholds, and nothing is selected by them.", ""]
    lines += _table(
        ["aid", "hypothesis", "symbol", "class", "state", "h", "detail"],
        [[a.aid, a.hypothesis_id, a.symbol, a.asset_class, a.state, a.horizon_bars or "",
          "; ".join(f"{k}={_r(v) if isinstance(v, float) else v}" for k, v in a.detail.items())]
         for a in result.decision_aids],
    )
    lines.append("")

    lines += ["## Limitations", ""]
    lines += [f"- {l}" for l in LIMITATIONS] + [""]
    return "\n".join(lines)


#: Package-surface aliases, unambiguous beside the Phase R names.
ERROR_ANALYSIS_ARTIFACT_NAMES = ARTIFACT_NAMES
error_analysis_manifest_payload = manifest_payload
render_error_analysis_manifest = render_manifest
render_error_analysis_report = render_report

__all__ = [
    "ERROR_ANALYSIS_ARTIFACT_NAMES", "error_analysis_manifest_payload",
    "render_error_analysis_manifest", "render_error_analysis_report",
    "ARTIFACT_MANIFEST", "ARTIFACT_DIAGNOSTICS", "ARTIFACT_EPISODES", "ARTIFACT_REPORT",
    "ARTIFACT_NAMES", "DIAGNOSTIC_COLUMNS", "EPISODE_COLUMNS", "diagnostic_columns",
    "episode_columns", "SEMANTIC_CONTRACT", "LIMITATIONS", "diagnostic_rows", "episode_rows",
    "render_diagnostics_csv", "render_episodes_csv", "manifest_payload", "render_manifest",
    "render_report",
]
