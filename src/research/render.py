"""Deterministic renderings of a :class:`~src.research.study.StudyResult`.

Four artifacts, one result::

    manifest.json      the reproducibility record (identity, windows, data fingerprints)
    summary.csv        one row per result group and per coverage cell
    observations.csv   one row per symbol x observation bar x hypothesis, with outcomes
    report.md          the same facts as tables, with the fixed limitations

Every function here is a pure function of its arguments and renders in a
fixed column order with a fixed number format, so two runs of one result
produce byte-identical CSV and report text. Floats are written with
``repr`` (shortest round-trip), timestamps as UTC ISO-8601, and a missing
value as the empty string -- never ``0``, ``nan`` or ``None``.

The report contains **facts only**. It states what was defined, what was
fetched, what was counted and what was measured; it does not say what any
of it means. Interpretation is a human's job, written separately after the
frozen run, in the vocabulary ``docs/research_baseline_study.md`` permits.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.evaluation import OutcomeSpec

from .definition import DELTA_NAMES, METRIC_NAMES, StudyDefinition
from .study import (
    ROW_COVERAGE,
    ROW_MATCHED_UNCONDITIONAL,
    ROW_NEUTRAL_REASON,
    ROW_STATE,
    HypothesisCoverage,
    ResultGroup,
    StudyResult,
    SymbolCoverage,
)

ARTIFACT_MANIFEST: str = "manifest.json"
ARTIFACT_SUMMARY: str = "summary.csv"
ARTIFACT_OBSERVATIONS: str = "observations.csv"
ARTIFACT_REPORT: str = "report.md"

#: Fixed column order of ``summary.csv``. ``row_type`` says which columns a
#: row populates; the rest are empty strings, never inferred.
SUMMARY_COLUMNS: tuple[str, ...] = (
    "row_type",
    "hypothesis_id",
    "hypothesis_version",
    "hypothesis_fingerprint",
    "symbol",
    "horizon_bars",
    "spec_fingerprint",
    "state",
    "reason_signature",
    *METRIC_NAMES,
    *DELTA_NAMES,
    "first_evaluated_timestamp",
    "last_evaluated_timestamp",
    # coverage rows only
    "total_observations",
    "bullish_count",
    "bearish_count",
    "neutral_count",
    "insufficient_data_count",
    "evaluated",
    "insufficient_future_data",
    "no_reference_bar",
    "ineligible",
    "bars_fetched",
    "warmup_bars",
    "observation_bars",
    "outcome_buffer_bars",
)

#: The fixed part of ``observations.csv``; four columns per horizon follow.
OBSERVATION_BASE_COLUMNS: tuple[str, ...] = (
    "symbol",
    "timestamp",
    "hypothesis_id",
    "hypothesis_version",
    "hypothesis_fingerprint",
    "state",
    "reason_codes",
)


def observation_columns(specs: Sequence[OutcomeSpec]) -> tuple[str, ...]:
    columns = list(OBSERVATION_BASE_COLUMNS)
    for spec in specs:
        h = spec.horizon_bars
        columns += [
            f"status_h{h}", f"return_h{h}", f"reference_timestamp_h{h}", f"future_timestamp_h{h}",
        ]
    return tuple(columns)


#: Column order of ``observations.csv`` for the frozen study's horizons
#: (1, 5, 20); :func:`observation_columns` derives it for any definition.
OBSERVATION_COLUMNS: tuple[str, ...] = observation_columns(
    tuple(OutcomeSpec(horizon_bars=h) for h in (1, 5, 20))
)

#: The limitations every report carries, verbatim, whatever the numbers say.
LIMITATIONS: tuple[str, ...] = (
    "Overlapping forward windows: at horizon 20, observations on adjacent daily bars "
    "share up to 19 of 20 future bars.",
    "sample_count is a count of overlapping observations, not of independent statistical "
    "trials; episode_count is descriptive and is not an effective sample size.",
    "RAW price basis: prices are as traded, with no split or dividend adjustment.",
    "Dividends and other corporate actions appear in raw prices as discontinuities; "
    "max_abs_single_bar_close_return is reported per symbol so any such jump is visible, "
    "and nothing was removed, adjusted or winsorised because of it.",
    "The provider may have revised or back-filled historical bars; results are reproducible "
    "against the fingerprinted dataset retrieved at retrieved_at, not against what the "
    "provider showed at any historical instant.",
    "No exchange calendar: horizons are counted in bars of the fetched series, and missing "
    "sessions are neither detected nor filled.",
    "The three hypotheses share the SMA20/SMA50 structure (momentum_in_trend_context adds "
    "RSI14; trend_crossover derives transitions from the same pair), so they are not "
    "independent confirmations of one another and no combined score is computed.",
    "Crossover states are transitions and may be sparse; small groups are reported with "
    "their counts, not smoothed or pooled.",
    "This is a retrospective study of one retrieved dataset; it differs in purpose from the "
    "prospective Phase 12 ledger, which records claims at the time they were made.",
    "No transaction costs, spreads, fills, positions or capital are modelled; a forward "
    "return is a property of the market, not of a strategy.",
    "Nothing here is a profitability, edge, accuracy or performance claim.",
    "No inferential statistics: no p-value, confidence interval, significance test or "
    "hit rate is computed or implied.",
)

_UTC = timezone.utc


# -- cell formatting -------------------------------------------------------------------------


def format_timestamp(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(_UTC).isoformat()


def format_float(value: float | None) -> str:
    return "" if value is None else repr(float(value))


def format_int(value: int | None) -> str:
    return "" if value is None else str(int(value))


def _blank_row(columns: Sequence[str]) -> dict[str, str]:
    return {column: "" for column in columns}


# -- summary.csv -----------------------------------------------------------------------------


def _group_row(group: ResultGroup) -> dict[str, str]:
    row = _blank_row(SUMMARY_COLUMNS)
    stats = group.stats
    row.update(
        row_type=group.row_type,
        hypothesis_id=group.hypothesis_id,
        hypothesis_version=format_int(group.hypothesis_version),
        hypothesis_fingerprint=group.hypothesis_fingerprint,
        symbol=group.symbol,
        horizon_bars=format_int(group.horizon_bars),
        spec_fingerprint=group.spec_fingerprint,
        state=group.state,
        reason_signature=group.reason_signature,
        sample_count=format_int(stats.sample_count),
        mean_forward_return=format_float(stats.mean_forward_return),
        median_forward_return=format_float(stats.median_forward_return),
        min_forward_return=format_float(stats.min_forward_return),
        max_forward_return=format_float(stats.max_forward_return),
        positive_count=format_int(stats.positive_count),
        negative_count=format_int(stats.negative_count),
        zero_count=format_int(stats.zero_count),
        episode_count=format_int(group.episode_count),
        mean_delta_vs_matched_unconditional=format_float(
            group.mean_delta_vs_matched_unconditional
        ),
        median_delta_vs_matched_unconditional=format_float(
            group.median_delta_vs_matched_unconditional
        ),
        first_evaluated_timestamp=format_timestamp(group.first_evaluated_timestamp),
        last_evaluated_timestamp=format_timestamp(group.last_evaluated_timestamp),
    )
    return row


def _coverage_rows(
    coverage: HypothesisCoverage, symbol: SymbolCoverage
) -> list[dict[str, str]]:
    rows = []
    for horizon in coverage.horizons:
        row = _blank_row(SUMMARY_COLUMNS)
        row.update(
            row_type=ROW_COVERAGE,
            hypothesis_id=coverage.hypothesis_id,
            hypothesis_version=format_int(coverage.hypothesis_version),
            hypothesis_fingerprint=coverage.hypothesis_fingerprint,
            symbol=coverage.symbol,
            horizon_bars=format_int(horizon.horizon_bars),
            spec_fingerprint=horizon.spec_fingerprint,
            total_observations=format_int(coverage.total_observations),
            bullish_count=format_int(coverage.bullish_count),
            bearish_count=format_int(coverage.bearish_count),
            neutral_count=format_int(coverage.neutral_count),
            insufficient_data_count=format_int(coverage.insufficient_data_count),
            evaluated=format_int(horizon.evaluated),
            insufficient_future_data=format_int(horizon.insufficient_future_data),
            no_reference_bar=format_int(horizon.no_reference_bar),
            ineligible=format_int(horizon.ineligible),
            bars_fetched=format_int(symbol.bars_fetched),
            warmup_bars=format_int(symbol.warmup_bars),
            observation_bars=format_int(symbol.observation_bars),
            outcome_buffer_bars=format_int(symbol.outcome_buffer_bars),
        )
        rows.append(row)
    return rows


def summary_rows(result: StudyResult) -> list[dict[str, str]]:
    """Coverage rows first (hypothesis x symbol x horizon), then every result group."""
    symbols = {symbol.symbol: symbol for symbol in result.symbols}
    rows: list[dict[str, str]] = []
    for coverage in result.coverage:
        rows.extend(_coverage_rows(coverage, symbols[coverage.symbol]))
    rows.extend(_group_row(group) for group in result.groups)
    return rows


# -- observations.csv ------------------------------------------------------------------------


def observation_rows(result: StudyResult) -> list[dict[str, str]]:
    columns = observation_columns(result.definition.outcome_specs)
    rows: list[dict[str, str]] = []
    for observation in result.observations:
        row = _blank_row(columns)
        row.update(
            symbol=observation.symbol,
            timestamp=format_timestamp(observation.timestamp),
            hypothesis_id=observation.hypothesis_id,
            hypothesis_version=format_int(observation.hypothesis_version),
            hypothesis_fingerprint=observation.hypothesis_fingerprint,
            state=observation.state.value,
            reason_codes=",".join(observation.reason_codes),
        )
        for outcome in observation.outcomes:
            h = outcome.horizon_bars
            row[f"status_h{h}"] = outcome.status.value
            row[f"return_h{h}"] = format_float(outcome.outcome_value)
            row[f"reference_timestamp_h{h}"] = format_timestamp(outcome.reference_timestamp)
            row[f"future_timestamp_h{h}"] = format_timestamp(outcome.future_timestamp)
        rows.append(row)
    return rows


# -- csv ----------------------------------------------------------------------------------------


def render_csv(columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> str:
    """RFC-4180-style CSV with ``\\n`` line endings and exactly ``columns``."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    for row in rows:
        unknown = set(row) - set(columns)
        if unknown:
            raise ValueError(f"row carries columns {sorted(unknown)} that are not in the layout")
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


# -- manifest.json -----------------------------------------------------------------------------


def manifest_payload(
    result: StudyResult,
    *,
    git_commit: str,
    source: str,
    retrieved_at: datetime,
    generated_at: datetime,
    bars_fingerprints: Mapping[str, str],
    summary_sha256: str,
    observations_sha256: str,
    report_sha256: str | None = None,
) -> dict[str, Any]:
    """The manifest as plain data. Key order is fixed by :func:`render_manifest`.

    ``retrieved_at`` and ``generated_at`` are the only inputs that vary
    between two runs of the same definition on the same data; everything
    else is a function of the definition, the bars and the code (the report
    prints both instants, so its recorded hash follows them).

    Hash model, non-circular: the manifest records the SHA-256 of the exact
    bytes of ``summary.csv``, ``observations.csv`` and ``report.md``. It does
    not, and cannot, contain its own hash; the command prints that, and a
    reader verifies the manifest file externally. The report is rendered
    from a payload with ``report_sha256`` still unset -- the report never
    prints its own hash -- and the final manifest is built once it is known.
    """
    definition = result.definition
    for label, value in (("retrieved_at", retrieved_at), ("generated_at", generated_at)):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be a timezone-aware datetime, got {value!r}")
    missing = [symbol for symbol in definition.symbols if symbol not in bars_fingerprints]
    if missing:
        raise ValueError(f"bars_fingerprints is missing {missing}")
    first_spec = definition.outcome_specs[0]
    return {
        "study_id": definition.study_id,
        "study_version": definition.study_version,
        "study_schema_version": definition.study_schema_version,
        "study_fingerprint": definition.fingerprint,
        "study_definition": definition.canonical_payload(),
        "git_commit": git_commit,
        "source": source,
        "interval": definition.interval.value,
        "basis": definition.basis.value,
        "universe": list(definition.symbols),
        "fetch_start": format_timestamp(definition.fetch_start),
        "observation_start": format_timestamp(definition.observation_start),
        "observation_end": format_timestamp(definition.observation_end),
        "outcome_data_end": format_timestamp(definition.outcome_data_end),
        "window_semantics": {
            "warmup": "[fetch_start, observation_start): feature warm-up only, never a study observation",
            "observation": "[observation_start, observation_end): the classification window",
            "outcome_buffer": "[observation_end, outcome_data_end): read only to measure forward outcomes of earlier observations; never classified",
            "untouched_future_begins": format_timestamp(definition.outcome_data_end),
        },
        "hypotheses": [
            {
                "hypothesis_id": spec.hypothesis_id,
                "version": spec.version,
                "fingerprint": spec.fingerprint,
                "canonical_form": spec.canonical_form,
            }
            for spec in definition.hypothesis_specs
        ],
        "outcome_specs": [
            {
                "horizon_bars": spec.horizon_bars,
                "fingerprint": spec.fingerprint,
                "canonical_form": spec.canonical_form,
            }
            for spec in definition.outcome_specs
        ],
        "evaluation_conventions": {
            "reference": first_spec.reference.value,
            "future_field": first_spec.future_field.value,
            "outcome_type": first_spec.outcome_type.value,
            "horizon_semantics": "reference bar is bar 1 of the horizon; future = bar (i + horizon_bars)",
        },
        "metric_policy": definition.metric_policy,
        "metrics": list(METRIC_NAMES),
        "deltas": list(DELTA_NAMES),
        "benchmark_policy": definition.benchmark_policy,
        "benchmark_definition": (
            "matched unconditional: all EVALUATED forward returns at exactly the timestamps "
            "where the same hypothesis produced an evaluable observation on the same symbol "
            "and horizon, state ignored (Phase 4 all_evaluated)"
        ),
        "symbols": [
            {
                "symbol": symbol.symbol,
                "bars_fingerprint": bars_fingerprints[symbol.symbol],
                "bars_count": symbol.bars_fetched,
                "first_timestamp": format_timestamp(symbol.first_timestamp),
                "last_timestamp": format_timestamp(symbol.last_timestamp),
                "warmup_bars": symbol.warmup_bars,
                "observation_bars": symbol.observation_bars,
                "outcome_buffer_bars": symbol.outcome_buffer_bars,
                "first_observation_timestamp": format_timestamp(symbol.first_observation_timestamp),
                "last_observation_timestamp": format_timestamp(symbol.last_observation_timestamp),
                "max_abs_single_bar_close_return": symbol.max_abs_single_bar_close_return,
            }
            for symbol in result.symbols
        ],
        "retrieved_at": format_timestamp(retrieved_at),
        "generated_at": format_timestamp(generated_at),
        "artifacts": {
            ARTIFACT_SUMMARY: {"sha256": summary_sha256, "git_tracked": True},
            ARTIFACT_OBSERVATIONS: {
                "sha256": observations_sha256,
                "git_tracked": False,
                "note": "generated raw audit artifact; kept under data/research/ and excluded from Git",
            },
            ARTIFACT_REPORT: {"sha256": report_sha256, "git_tracked": True},
        },
        "overlap_caveat": result.overlap_caveat,
        "retrospective_caveat": result.retrospective_caveat,
        "limitations": list(LIMITATIONS),
    }


def render_manifest(payload: Mapping[str, Any]) -> str:
    """Pretty, sorted, ASCII JSON with a trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


# -- report.md ---------------------------------------------------------------------------------


def _r(value: float | None) -> str:
    return "" if value is None else f"{value:+.6f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def render_report(result: StudyResult, manifest: Mapping[str, Any]) -> str:
    """Facts and tables only; see the module docstring."""
    definition: StudyDefinition = result.definition
    lines: list[str] = [f"# Phase R — {definition.study_id} v{definition.study_version}", ""]

    lines += ["## Study definition", ""]
    lines += [
        f"- study: `{definition.label}` (schema {definition.study_schema_version})",
        f"- study fingerprint: `{definition.fingerprint}`",
        f"- interval: `{definition.interval.value}`; basis: `{definition.basis.value}`",
        f"- horizons (bars): {', '.join(str(h) for h in definition.horizons)}",
        f"- metric policy: `{definition.metric_policy}`; benchmark policy: "
        f"`{definition.benchmark_policy}`",
        "- benchmark: " + str(manifest["benchmark_definition"]),
        "",
    ]

    lines += ["## Reproducibility", ""]
    lines += [
        f"- git commit: `{manifest['git_commit']}`",
        f"- source: `{manifest['source']}`",
        f"- retrieved at: `{manifest['retrieved_at']}`; generated at: `{manifest['generated_at']}`",
        f"- summary.csv sha256: `{manifest['artifacts'][ARTIFACT_SUMMARY]['sha256']}`",
        f"- observations.csv sha256: `{manifest['artifacts'][ARTIFACT_OBSERVATIONS]['sha256']}` "
        "(generated raw audit artifact; kept under data/research/ and excluded from Git)",
        "",
    ]

    lines += ["## Universe and period", ""]
    lines += [
        f"- universe (in order): {', '.join(definition.symbols)}",
        f"- fetch start: `{format_timestamp(definition.fetch_start)}` (warm-up only before the "
        "observation start)",
        f"- observation window: `[{format_timestamp(definition.observation_start)}, "
        f"{format_timestamp(definition.observation_end)})`",
        f"- outcome-only buffer: `[{format_timestamp(definition.observation_end)}, "
        f"{format_timestamp(definition.outcome_data_end)})` — read solely to measure forward "
        "outcomes of earlier observations; never classified",
        f"- chronologically untouched data begins at `{format_timestamp(definition.outcome_data_end)}`",
        "",
    ]
    lines += _table(
        ["symbol", "bars fetched", "warm-up", "observation", "buffer", "first bar", "last bar",
         "max abs 1-bar close return", "bars fingerprint"],
        [
            [
                s.symbol, s.bars_fetched, s.warmup_bars, s.observation_bars, s.outcome_buffer_bars,
                format_timestamp(s.first_timestamp), format_timestamp(s.last_timestamp),
                _r(s.max_abs_single_bar_close_return),
                f"`{manifest['symbols'][index]['bars_fingerprint']}`",
            ]
            for index, s in enumerate(result.symbols)
        ],
    )
    lines.append("")

    lines += ["## Hypotheses", ""]
    lines += _table(
        ["hypothesis", "version", "fingerprint", "canonical form"],
        [[s.hypothesis_id, s.version, f"`{s.fingerprint}`", f"`{s.canonical_form}`"]
         for s in definition.hypothesis_specs],
    )
    lines.append("")

    lines += ["## Evaluation protocol", ""]
    conventions = manifest["evaluation_conventions"]
    lines += [
        f"- outcome type: `{conventions['outcome_type']}`; reference: `{conventions['reference']}`; "
        f"future field: `{conventions['future_field']}`",
        f"- {conventions['horizon_semantics']}",
        "- states reported: bullish, bearish, neutral; insufficient_data is accounted for in "
        "coverage only",
        "- every observation in the window receives one Phase 4 status per horizon: evaluated, "
        "insufficient_future_data, no_reference_bar or ineligible_observation",
        "",
    ]
    lines += _table(
        ["horizon", "spec fingerprint", "canonical form"],
        [[s.horizon_bars, f"`{s.fingerprint}`", f"`{s.canonical_form}`"]
         for s in definition.outcome_specs],
    )
    lines.append("")

    lines += ["## Coverage", ""]
    lines += _table(
        ["hypothesis", "symbol", "observations", "bullish", "bearish", "neutral",
         "insufficient_data", "horizon", "evaluated", "insufficient_future", "no_reference",
         "ineligible"],
        [
            [c.hypothesis_id, c.symbol, c.total_observations, c.bullish_count, c.bearish_count,
             c.neutral_count, c.insufficient_data_count, h.horizon_bars, h.evaluated,
             h.insufficient_future_data, h.no_reference_bar, h.ineligible]
            for c in result.coverage
            for h in c.horizons
        ],
    )
    lines.append("")

    lines += ["## Results by hypothesis", ""]
    lines += [f"> {result.overlap_caveat}", ""]
    headers = ["symbol", "horizon", "state", "n", "mean", "median", "min", "max", "pos", "neg",
               "zero", "episodes", "mean delta vs matched", "median delta vs matched"]
    for spec in definition.hypothesis_specs:
        lines += [f"### {spec.hypothesis_id} v{spec.version} `{spec.fingerprint}`", ""]
        rows = [
            [g.symbol, g.horizon_bars, g.state, g.stats.sample_count,
             _r(g.stats.mean_forward_return), _r(g.stats.median_forward_return),
             _r(g.stats.min_forward_return), _r(g.stats.max_forward_return),
             g.stats.positive_count, g.stats.negative_count, g.stats.zero_count,
             g.episode_count, _r(g.mean_delta_vs_matched_unconditional),
             _r(g.median_delta_vs_matched_unconditional)]
            for g in result.groups
            if g.hypothesis_id == spec.hypothesis_id
            and g.row_type in (ROW_MATCHED_UNCONDITIONAL, ROW_STATE)
        ]
        lines += _table(headers, rows)
        lines.append("")

    lines += ["## NEUTRAL reason-code breakdown", ""]
    neutral_headers = ["hypothesis", "symbol", "horizon", "reason signature", "n", "mean",
                       "median", "min", "max", "pos", "neg", "zero", "episodes",
                       "mean delta vs matched", "median delta vs matched"]
    neutral_rows = [
        [g.hypothesis_id, g.symbol, g.horizon_bars, f"`{g.reason_signature}`",
         g.stats.sample_count, _r(g.stats.mean_forward_return), _r(g.stats.median_forward_return),
         _r(g.stats.min_forward_return), _r(g.stats.max_forward_return),
         g.stats.positive_count, g.stats.negative_count, g.stats.zero_count, g.episode_count,
         _r(g.mean_delta_vs_matched_unconditional), _r(g.median_delta_vs_matched_unconditional)]
        for g in result.groups
        if g.row_type == ROW_NEUTRAL_REASON
    ]
    lines += _table(neutral_headers, neutral_rows) if neutral_rows else ["(no evaluated NEUTRAL observations)"]
    lines.append("")

    lines += ["## Limitations", ""]
    lines += [f"- {limitation}" for limitation in LIMITATIONS]
    lines += ["", f"> {result.retrospective_caveat}", ""]
    return "\n".join(lines)


__all__ = [
    "ARTIFACT_MANIFEST",
    "ARTIFACT_SUMMARY",
    "ARTIFACT_OBSERVATIONS",
    "ARTIFACT_REPORT",
    "SUMMARY_COLUMNS",
    "OBSERVATION_BASE_COLUMNS",
    "OBSERVATION_COLUMNS",
    "observation_columns",
    "LIMITATIONS",
    "format_timestamp",
    "format_float",
    "format_int",
    "summary_rows",
    "observation_rows",
    "render_csv",
    "manifest_payload",
    "render_manifest",
    "render_report",
]
