"""A compact, Baseline-shaped synthetic artifact set for the Phase 13A tests.

Builds ``manifest.json``, ``summary.csv`` and ``observations.csv`` texts that
obey the Phase R layouts and identity checks, over two symbols (one equity,
one treasury), ten years of dates concentrated around the segment
boundaries, every source state, several episodes, weekend gaps, retained and
removed momentum bars with two removal reason signatures, a dead-band
sliver, crossover events and h1/h5/h20 values. Returns are deterministic
arithmetic, identical across hypotheses at the same market point (as in the
real data), and carry no Phase R result number.

``summary.csv`` is computed here independently of the engine (simple
recount / mean / median / episode logic) so that the engine's source
cross-check is tested against a second implementation.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.research import ERROR_ANALYSIS_V1, ErrorAnalysisDefinition
from src.research.error_analysis import SOURCE_MANIFEST, SOURCE_OBSERVATIONS, SOURCE_SUMMARY
from src.research.render import SUMMARY_COLUMNS, render_csv

UTC = timezone.utc
SYMBOLS = ("SPY", "TLT")
HYPS = (("trend_alignment", 1, "650add07184f8440"),
        ("momentum_in_trend_context", 1, "6589cb8021b76574"),
        ("trend_crossover", 1, "f1126ca778e6f7ce"))
SPECS = ((1, "83e9dabf9b4e27de"), (5, "b586481caf972d58"), (20, "a040ca488aa3f51f"))
FAKE_SOURCE_FINGERPRINT = "f" * 64
FAKE_METHODOLOGY_SHA = "a" * 40
FAKE_RESULT_SHA = "b" * 40

MID = "momentum_midrange"
CONTRA_UP = "fast_above_slow,momentum_depressed,momentum_contradicts_trend"
CONTRA_DOWN = "fast_below_slow,momentum_elevated,momentum_contradicts_trend"


def business_days(start: datetime, count: int, *, backwards: bool = False) -> list[datetime]:
    days: list[datetime] = []
    cursor = start
    step = timedelta(days=-1 if backwards else 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += step
    return sorted(days)


def fixture_dates() -> list[datetime]:
    """Six business days at the start and six before the end of each segment."""
    bounds = [datetime(y, 1, 1, tzinfo=UTC) for y in (2015, 2017, 2019, 2021, 2023, 2025)]
    dates: list[datetime] = []
    for start, end in zip(bounds, bounds[1:]):
        dates += business_days(start, 6)
        dates += business_days(end - timedelta(days=1), 6, backwards=True)
    return sorted(set(dates))


def fake_return(symbol: str, index: int, horizon: int) -> float:
    """Deterministic, symbol/point/horizon-specific, with zeros and both signs."""
    seed = (index * 7 + horizon * 13 + sum(map(ord, symbol))) % 23
    if seed == 0:
        return 0.0
    return ((seed - 11) / 1000.0) * (horizon ** 0.5)


def state_pattern(symbol: str, index: int) -> tuple[str, str, str, str, str, str]:
    """(trend state, trend reasons, momentum state, momentum reasons, cross state, cross reasons)."""
    cycle = (index + (3 if symbol == "TLT" else 0)) % 12
    if cycle < 5:
        trend, treason = "bullish", "fast_above_slow"
        if cycle in (1, 2):
            mom, mreason = "bullish", "fast_above_slow,momentum_elevated,momentum_confirms_trend"
        elif cycle == 3:
            mom, mreason = "neutral", CONTRA_UP
        else:
            mom, mreason = "neutral", MID
    elif cycle < 9:
        trend, treason = "bearish", "fast_below_slow"
        if cycle in (5, 6):
            mom, mreason = "bearish", "fast_below_slow,momentum_depressed,momentum_confirms_trend"
        elif cycle == 7:
            mom, mreason = "neutral", CONTRA_DOWN
        else:
            mom, mreason = "neutral", MID
    else:
        trend, treason = "neutral", "trend_margin_below_threshold"
        mom, mreason = ("bullish", "fast_above_slow,momentum_elevated,momentum_confirms_trend") if cycle == 9 \
            else ("neutral", MID)
    if cycle == 0:
        cross, creason = "bullish", "crossed_above,fast_above_slow"
    elif cycle == 5:
        cross, creason = "bearish", "crossed_below,fast_below_slow"
    else:
        cross, creason = "neutral", "relationship_unchanged"
    return trend, treason, mom, mreason, cross, creason


def build_rows(symbols=SYMBOLS, *, insufficient_first: int = 0, short_tail: int = 0):
    """Observation rows as dicts keyed by the Phase R observation columns."""
    dates = fixture_dates()
    rows = []
    for symbol in symbols:
        for hid, ver, fp in HYPS:
            for index, ts in enumerate(dates):
                trend, treason, mom, mreason, cross, creason = state_pattern(symbol, index)
                state, reasons = {"trend_alignment": (trend, treason),
                                  "momentum_in_trend_context": (mom, mreason),
                                  "trend_crossover": (cross, creason)}[hid]
                if hid == "trend_crossover" and index < insufficient_first:
                    state, reasons = "insufficient_data", "warmup_incomplete"
                row = {"symbol": symbol, "timestamp": ts.isoformat(), "hypothesis_id": hid,
                       "hypothesis_version": str(ver), "hypothesis_fingerprint": fp,
                       "state": state, "reason_codes": reasons}
                for h, _ in SPECS:
                    if state == "insufficient_data":
                        status, value = "ineligible_observation", ""
                    elif index >= len(dates) - short_tail and h > 1:
                        status, value = "insufficient_future_data", ""
                    else:
                        status, value = "evaluated", repr(fake_return(symbol, index, h))
                    ref = (ts + timedelta(days=1)).isoformat() if status != "ineligible_observation" else ""
                    fut = (ts + timedelta(days=h)).isoformat() if status == "evaluated" else ""
                    row[f"status_h{h}"] = status
                    row[f"return_h{h}"] = value
                    row[f"reference_timestamp_h{h}"] = ref
                    row[f"future_timestamp_h{h}"] = fut
                rows.append(row)
    return rows


OBS_COLUMNS = ("symbol", "timestamp", "hypothesis_id", "hypothesis_version", "hypothesis_fingerprint",
               "state", "reason_codes") + tuple(
    c for h, _ in SPECS for c in (f"status_h{h}", f"return_h{h}", f"reference_timestamp_h{h}", f"future_timestamp_h{h}")
)


def _episodes(flags):
    n, inside = 0, False
    for f in flags:
        if f and not inside:
            n += 1
        inside = f
    return n


def _desc(vals):
    if not vals:
        return {"sample_count": "0", "mean_forward_return": "", "median_forward_return": "",
                "min_forward_return": "", "max_forward_return": "", "positive_count": "0",
                "negative_count": "0", "zero_count": "0"}
    return {"sample_count": str(len(vals)), "mean_forward_return": repr(statistics.fmean(vals)),
            "median_forward_return": repr(statistics.median(vals)), "min_forward_return": repr(min(vals)),
            "max_forward_return": repr(max(vals)), "positive_count": str(sum(1 for v in vals if v > 0)),
            "negative_count": str(sum(1 for v in vals if v < 0)), "zero_count": str(sum(1 for v in vals if v == 0))}


def build_summary_rows(rows, symbols=SYMBOLS):
    """An independent recomputation of the Phase R summary rows for the fixture."""
    out = []
    for symbol in symbols:
        for hid, ver, fp in HYPS:
            seq = sorted((r for r in rows if r["symbol"] == symbol and r["hypothesis_id"] == hid),
                         key=lambda r: r["timestamp"])
            for h, spec_fp in SPECS:
                base = {c: "" for c in SUMMARY_COLUMNS}
                base.update(hypothesis_id=hid, hypothesis_version=str(ver), hypothesis_fingerprint=fp,
                            symbol=symbol, horizon_bars=str(h), spec_fingerprint=spec_fp)
                cov = dict(base, row_type="coverage",
                           total_observations=str(len(seq)),
                           bullish_count=str(sum(r["state"] == "bullish" for r in seq)),
                           bearish_count=str(sum(r["state"] == "bearish" for r in seq)),
                           neutral_count=str(sum(r["state"] == "neutral" for r in seq)),
                           insufficient_data_count=str(sum(r["state"] == "insufficient_data" for r in seq)),
                           evaluated=str(sum(r[f"status_h{h}"] == "evaluated" for r in seq)),
                           insufficient_future_data=str(sum(r[f"status_h{h}"] == "insufficient_future_data" for r in seq)),
                           no_reference_bar="0",
                           ineligible=str(sum(r[f"status_h{h}"] == "ineligible_observation" for r in seq)),
                           bars_fetched=str(len(seq) + 60), warmup_bars="60", observation_bars=str(len(seq)),
                           outcome_buffer_bars="0")
                out.append(cov)
                ev = [r[f"status_h{h}"] == "evaluated" for r in seq]
                vals_all = [float(r[f"return_h{h}"]) for r, e in zip(seq, ev) if e]
                d_all = _desc(vals_all)
                stamps = [r["timestamp"] for r, e in zip(seq, ev) if e]
                out.append(dict(base, row_type="matched_unconditional", state="all", **d_all,
                                episode_count=str(_episodes(ev)),
                                first_evaluated_timestamp=min(stamps) if stamps else "",
                                last_evaluated_timestamp=max(stamps) if stamps else ""))
                m_all = statistics.fmean(vals_all) if vals_all else None
                md_all = statistics.median(vals_all) if vals_all else None

                def group(row_type, state, signature, members):
                    vals = [float(r[f"return_h{h}"]) for r, m in zip(seq, members) if m]
                    st = [r["timestamp"] for r, m in zip(seq, members) if m]
                    d = _desc(vals)
                    md = repr(statistics.fmean(vals) - m_all) if vals else ""
                    dd = repr(statistics.median(vals) - md_all) if vals else ""
                    return dict(base, row_type=row_type, state=state, reason_signature=signature, **d,
                                episode_count=str(_episodes(members)),
                                mean_delta_vs_matched_unconditional=md,
                                median_delta_vs_matched_unconditional=dd,
                                first_evaluated_timestamp=min(st) if st else "",
                                last_evaluated_timestamp=max(st) if st else "")

                for state in ("bullish", "bearish", "neutral"):
                    out.append(group("state", state, "", [e and r["state"] == state for r, e in zip(seq, ev)]))
                for sig in sorted({r["reason_codes"] for r, e in zip(seq, ev) if e and r["state"] == "neutral"}):
                    out.append(group("neutral_reason", "neutral", sig,
                                     [e and r["state"] == "neutral" and r["reason_codes"] == sig for r, e in zip(seq, ev)]))
    return out


def build_manifest(symbols=SYMBOLS, **overrides) -> dict:
    manifest = {
        "study_id": "baseline_study", "study_version": 1, "study_schema_version": 1,
        "study_fingerprint": FAKE_SOURCE_FINGERPRINT, "git_commit": FAKE_METHODOLOGY_SHA,
        "source": "synthetic", "retrieved_at": "2026-01-01T00:00:00+00:00",
        "generated_at": "2026-01-01T00:01:00+00:00",
        "interval": "1d", "basis": "raw", "universe": list(symbols),
        "observation_start": "2015-01-01T00:00:00+00:00", "observation_end": "2025-01-01T00:00:00+00:00",
        "fetch_start": "2014-09-01T00:00:00+00:00", "outcome_data_end": "2025-03-01T00:00:00+00:00",
        "hypotheses": [{"hypothesis_id": h, "version": v, "fingerprint": f, "canonical_form": f"{h}|v{v}"}
                       for h, v, f in HYPS],
        "outcome_specs": [{"horizon_bars": h, "fingerprint": f, "canonical_form": f"h={h}"} for h, f in SPECS],
        "symbols": [{"symbol": s, "bars_fingerprint": hashlib.sha256(s.encode()).hexdigest(),
                     "bars_count": 120, "warmup_bars": 60, "observation_bars": 60, "outcome_buffer_bars": 0,
                     "max_abs_single_bar_close_return": 0.05} for s in symbols],
    }
    manifest.update(overrides)
    return manifest


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_texts(symbols=SYMBOLS, *, rows=None, manifest=None, summary_rows=None) -> dict[str, str]:
    rows = build_rows(symbols) if rows is None else rows
    summary_rows = build_summary_rows(rows, symbols) if summary_rows is None else summary_rows
    manifest = build_manifest(symbols) if manifest is None else manifest
    return {
        SOURCE_MANIFEST: json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        SOURCE_SUMMARY: render_csv(SUMMARY_COLUMNS, summary_rows),
        SOURCE_OBSERVATIONS: render_csv(OBS_COLUMNS, rows),
    }


def definition_for(texts: dict[str, str], symbols=SYMBOLS, **overrides) -> ErrorAnalysisDefinition:
    """The frozen definition re-pointed at the synthetic source (hashes + identity)."""
    fields = dict(
        source_hashes={name: sha256(text) for name, text in texts.items()},
        source_study_fingerprint=FAKE_SOURCE_FINGERPRINT,
        source_methodology_sha=FAKE_METHODOLOGY_SHA,
        source_result_sha=FAKE_RESULT_SHA,
        symbols=tuple(symbols),
    )
    fields.update(overrides)
    return replace(ERROR_ANALYSIS_V1, **fields)


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def write_source(directory, texts: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (directory / name).write_bytes(text.encode("utf-8"))


__all__ = ["UTC", "SYMBOLS", "HYPS", "SPECS", "MID", "CONTRA_UP", "CONTRA_DOWN", "OBS_COLUMNS",
           "fixture_dates", "fake_return", "state_pattern", "build_rows", "build_summary_rows",
           "build_manifest", "build_texts", "definition_for", "sha256", "parse_csv", "write_source"]
