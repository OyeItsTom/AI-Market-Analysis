"""Phase 13A: Error Analysis v1 -- diagnosis of the current hypotheses from
the frozen Baseline Study v1 artifacts, and nothing else.

What this is
------------
A pure, read-only, zero-network diagnostic. It consumes the exact bytes of
three frozen Phase R artifacts (``manifest.json``, ``summary.csv``,
``observations.csv``), refuses them unless their SHA-256 and identity match
the pinned source contract, re-derives the Phase R state rows from the raw
rows as an integrity cross-check, and then produces six predeclared
diagnostics:

    D1  episode structure (and a secondary episode-start sampling view)
    D2  trend-vs-momentum gate decomposition on common timestamps
    D3  predeclared two-year temporal segments
    D4  asset-class sign annotation (metadata only, no pooling)
    D5  crossover event listing
    D6  the semantic contract of the state vocabulary (report text)

What this is not
----------------
It changes no hypothesis, threshold, feature, basis, horizon, universe or
window. It computes no forward return: every ``return_h*`` value is read off
a frozen row. It performs no threshold search and no inferential statistics.
The "decision aids" it surfaces (a 4-of-5-segments sign count, an
episode-concentration share, a retained-vs-removed sign comparison) are
**predeclared descriptive reading aids** for the human review gate, not
significance tests, not robustness proofs and not effective-sample-size
corrections. Nothing here selects a Phase 13B change.

Episodes
--------
An episode is a maximal run of consecutive observation-bar positions with
the same hypothesis *state* (as in Phase R). Reason signatures are
descriptive metadata of the episode's first bar; a reason change inside a
NEUTRAL run does not split the episode.

Future data
-----------
Any observation on or after the frozen observation end (2025-01-01) is
refused outright -- it is not filtered, because the source contract says it
cannot be there. Data from 2025-03-01 onward is chronologically untouched
and stays that way.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.assessments.policy import canonical_bytes

from .study import DescriptiveStats, count_episodes


class ErrorAnalysisError(ValueError):
    """The source artifacts do not satisfy the contract, or a diagnostic
    could not be formed coherently. Always raised before any output."""


# -- identity ----------------------------------------------------------------------------------

STUDY_ID: str = "error_analysis"
STUDY_VERSION: int = 1
STUDY_SCHEMA_VERSION: int = 1

SOURCE_STUDY_ID: str = "baseline_study"
SOURCE_STUDY_VERSION: int = 1
SOURCE_STUDY_FINGERPRINT: str = (
    "1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261"
)
SOURCE_METHODOLOGY_SHA: str = "5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31"
SOURCE_RESULT_SHA: str = "3625e10656b6d11b40479a09d2c467e190480b2e"

SOURCE_MANIFEST: str = "manifest.json"
SOURCE_SUMMARY: str = "summary.csv"
SOURCE_OBSERVATIONS: str = "observations.csv"
SOURCE_ARTIFACT_NAMES: tuple[str, ...] = (SOURCE_MANIFEST, SOURCE_SUMMARY, SOURCE_OBSERVATIONS)

#: SHA-256 of the exact frozen bytes of the first (and only) Baseline Study
#: v1 live run. A different dataset is refused, never analysed.
SOURCE_HASHES: Mapping[str, str] = {
    SOURCE_MANIFEST: "d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf",
    SOURCE_SUMMARY: "cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee",
    SOURCE_OBSERVATIONS: "c2be1f66f10d7dc31debfaac76d67c850664166a65d1585bdd3769d0a228af76",
}

SOURCE_OBSERVATION_START: datetime = datetime(2015, 1, 1, tzinfo=timezone.utc)
SOURCE_OBSERVATION_END: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc)

UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "IWM", "TLT", "GLD")
HORIZONS: tuple[int, ...] = (1, 5, 20)

#: The hypotheses of the source study, copied from its identity.
HYPOTHESES: tuple[tuple[str, int, str], ...] = (
    ("trend_alignment", 1, "650add07184f8440"),
    ("momentum_in_trend_context", 1, "6589cb8021b76574"),
    ("trend_crossover", 1, "f1126ca778e6f7ce"),
)
TREND_ID: str = "trend_alignment"
MOMENTUM_ID: str = "momentum_in_trend_context"
CROSSOVER_ID: str = "trend_crossover"

#: Five equal two-calendar-year blocks, fixed before any segment number was
#: seen. Half-open in UTC; assignment uses the observation timestamp only.
SEGMENTS: tuple[tuple[str, datetime, datetime], ...] = (
    ("2015-2016", datetime(2015, 1, 1, tzinfo=timezone.utc), datetime(2017, 1, 1, tzinfo=timezone.utc)),
    ("2017-2018", datetime(2017, 1, 1, tzinfo=timezone.utc), datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ("2019-2020", datetime(2019, 1, 1, tzinfo=timezone.utc), datetime(2021, 1, 1, tzinfo=timezone.utc)),
    ("2021-2022", datetime(2021, 1, 1, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
    ("2023-2024", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
)

#: Descriptive metadata only. Nothing is pooled by class.
ASSET_CLASSES: Mapping[str, str] = {
    "SPY": "equity", "QQQ": "equity", "IWM": "equity", "TLT": "treasury", "GLD": "gold",
}

DIAGNOSTICS: tuple[str, ...] = (
    "D1_episode_structure",
    "D2_gate_decomposition",
    "D3_temporal_segmentation",
    "D4_class_signs",
    "D5_crossover_events",
    "D6_semantic_contract",
)

#: The only row types ``diagnostics.csv`` may carry.
ROW_EPISODE_SUMMARY = "episode_summary"
ROW_EPISODE_START = "episode_start"
ROW_GATE_CROSSTAB = "gate_crosstab"
ROW_GATE_PARTITION = "gate_partition"
ROW_SEGMENT_STATE = "segment_state"
ROW_SEGMENT_MATCHED = "segment_matched"
ROW_CLASS_SIGNS = "class_signs"
ROW_CROSSOVER_EVENT = "crossover_event"
ROW_TYPES: tuple[str, ...] = (
    ROW_EPISODE_SUMMARY, ROW_EPISODE_START, ROW_GATE_CROSSTAB, ROW_GATE_PARTITION,
    ROW_SEGMENT_STATE, ROW_SEGMENT_MATCHED, ROW_CLASS_SIGNS, ROW_CROSSOVER_EVENT,
)

#: Gate partitions of a trend-directional bar, by the momentum state at the
#: same timestamp. ``opposite`` is reported, never assumed impossible.
PARTITION_RETAINED = "retained"
PARTITION_REMOVED = "removed"
PARTITION_OPPOSITE = "opposite"
PARTITIONS: tuple[str, ...] = (PARTITION_RETAINED, PARTITION_REMOVED, PARTITION_OPPOSITE)

#: Per-group numbers, identical in definition to Phase R's metric set.
METRIC_NAMES: tuple[str, ...] = (
    "sample_count", "mean_forward_return", "median_forward_return",
    "min_forward_return", "max_forward_return", "positive_count", "negative_count",
    "zero_count", "episode_count",
)

#: Predeclared descriptive decision aids surfaced to the human review gate.
DECISION_AID_SEGMENT_MAJORITY: int = 4  # of the five segments
DECISION_AID_EPISODE_SHARE: float = 0.25  # share of a state's observations in one episode

STATE_ALL = "all"
DIRECTIONAL_STATES: tuple[str, ...] = ("bullish", "bearish")
REPORTED_STATES: tuple[str, ...] = ("bullish", "bearish", "neutral")
SOURCE_STATES: tuple[str, ...] = ("bullish", "bearish", "neutral", "insufficient_data")
EVALUATED = "evaluated"

_UTC = timezone.utc


def _utc_iso(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat()


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErrorAnalysisError(f"{label} must be a timezone-aware datetime, got {value!r}")
    return value


# -- definition --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorAnalysisDefinition:
    """The immutable Phase 13A contract. Every field is in the fingerprint.

    Constructed once as :data:`ERROR_ANALYSIS_V1`; tests build variants over
    synthetic source artifacts by replacing the source hashes and identity.
    """

    study_id: str
    study_version: int
    study_schema_version: int
    source_study_id: str
    source_study_version: int
    source_study_fingerprint: str
    source_methodology_sha: str
    source_result_sha: str
    source_hashes: Mapping[str, str]
    source_observation_start: datetime
    source_observation_end: datetime
    symbols: tuple[str, ...]
    hypotheses: tuple[tuple[str, int, str], ...]
    horizons: tuple[int, ...]
    segments: tuple[tuple[str, datetime, datetime], ...]
    asset_classes: Mapping[str, str]
    diagnostics: tuple[str, ...] = DIAGNOSTICS
    metric_names: tuple[str, ...] = METRIC_NAMES
    row_types: tuple[str, ...] = ROW_TYPES
    decision_aid_segment_majority: int = DECISION_AID_SEGMENT_MAJORITY
    decision_aid_episode_share: float = DECISION_AID_EPISODE_SHARE

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        for name in ("study_id", "source_study_id", "source_study_fingerprint",
                     "source_methodology_sha", "source_result_sha"):
            if not str(getattr(self, name)).strip():
                raise ErrorAnalysisError(f"{name} must not be empty")
        for name in ("study_version", "study_schema_version", "source_study_version",
                     "decision_aid_segment_majority"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ErrorAnalysisError(f"{name} must be a positive int, got {value!r}")
        hashes = dict(self.source_hashes)
        if set(hashes) != set(SOURCE_ARTIFACT_NAMES):
            raise ErrorAnalysisError(
                f"source_hashes must name exactly {list(SOURCE_ARTIFACT_NAMES)}, got {sorted(hashes)}"
            )
        for name, digest in hashes.items():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ErrorAnalysisError(f"source hash for {name} must be 64 hex characters")
        set_(self, "source_hashes", hashes)

        start = _require_aware(self.source_observation_start, "source_observation_start")
        end = _require_aware(self.source_observation_end, "source_observation_end")
        if not start < end:
            raise ErrorAnalysisError("source observation window must be non-empty")

        symbols = tuple(str(s).strip().upper() for s in self.symbols)
        if not symbols or len(set(symbols)) != len(symbols) or any(not s for s in symbols):
            raise ErrorAnalysisError("symbols must be a non-empty tuple of unique symbols")
        set_(self, "symbols", symbols)
        classes = {str(k).strip().upper(): str(v) for k, v in dict(self.asset_classes).items()}
        missing = [s for s in symbols if s not in classes]
        if missing:
            raise ErrorAnalysisError(f"asset_classes lacks {missing}")
        set_(self, "asset_classes", classes)

        hypotheses = tuple((str(h), int(v), str(f)) for h, v, f in self.hypotheses)
        ids = [h for h, _, _ in hypotheses]
        for required in (TREND_ID, MOMENTUM_ID, CROSSOVER_ID):
            if required not in ids:
                raise ErrorAnalysisError(f"hypotheses must include {required!r}")
        if len(set(ids)) != len(ids):
            raise ErrorAnalysisError("hypothesis ids must be unique")
        set_(self, "hypotheses", hypotheses)

        horizons = tuple(int(h) for h in self.horizons)
        if not horizons or len(set(horizons)) != len(horizons) or any(h < 1 for h in horizons):
            raise ErrorAnalysisError("horizons must be unique positive ints")
        set_(self, "horizons", horizons)

        segments = tuple((str(label), _require_aware(a, f"segment {label} start"),
                          _require_aware(b, f"segment {label} end")) for label, a, b in self.segments)
        if not segments:
            raise ErrorAnalysisError("at least one segment is required")
        for label, a, b in segments:
            if not a < b:
                raise ErrorAnalysisError(f"segment {label} must be non-empty")
        for (l1, _, b1), (l2, a2, _) in zip(segments, segments[1:]):
            if b1 != a2:
                raise ErrorAnalysisError(f"segments {l1} and {l2} must be contiguous")
        if segments[0][1] != start or segments[-1][2] != end:
            raise ErrorAnalysisError("segments must exactly cover the source observation window")
        if len({label for label, _, _ in segments}) != len(segments):
            raise ErrorAnalysisError("segment labels must be unique")
        set_(self, "segments", segments)

        if not (0 < float(self.decision_aid_episode_share) < 1):
            raise ErrorAnalysisError("decision_aid_episode_share must be in (0, 1)")
        if self.decision_aid_segment_majority > len(segments):
            raise ErrorAnalysisError("decision_aid_segment_majority exceeds the segment count")

    @property
    def label(self) -> str:
        return f"{self.study_id}_v{self.study_version}"

    @property
    def hypothesis_ids(self) -> tuple[str, ...]:
        return tuple(h for h, _, _ in self.hypotheses)

    def segment_of(self, timestamp: datetime) -> str:
        for label, start, end in self.segments:
            if start <= timestamp < end:
                return label
        raise ErrorAnalysisError(
            f"timestamp {timestamp.isoformat()} falls in no segment; it is outside the "
            "source observation window"
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "scheme": "research.error_analysis_definition",
            "scheme_version": 1,
            "study_id": self.study_id,
            "study_version": self.study_version,
            "study_schema_version": self.study_schema_version,
            "source": {
                "study_id": self.source_study_id,
                "study_version": self.source_study_version,
                "study_fingerprint": self.source_study_fingerprint,
                "methodology_sha": self.source_methodology_sha,
                "result_sha": self.source_result_sha,
                "hashes": {name: self.source_hashes[name] for name in SOURCE_ARTIFACT_NAMES},
                "observation_start": _utc_iso(self.source_observation_start),
                "observation_end": _utc_iso(self.source_observation_end),
            },
            "symbols": list(self.symbols),
            "hypotheses": [
                {"hypothesis_id": h, "version": v, "fingerprint": f} for h, v, f in self.hypotheses
            ],
            "horizons": list(self.horizons),
            "segments": [
                {"label": label, "start": _utc_iso(a), "end": _utc_iso(b)}
                for label, a, b in self.segments
            ],
            "asset_classes": {s: self.asset_classes[s] for s in self.symbols},
            "diagnostics": list(self.diagnostics),
            "metrics": list(self.metric_names),
            "row_types": list(self.row_types),
            "decision_aids": {
                "segment_majority": self.decision_aid_segment_majority,
                "episode_share": self.decision_aid_episode_share,
                "kind": "predeclared descriptive decision aids; not statistical tests",
            },
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_bytes(self.canonical_payload())).hexdigest()


ERROR_ANALYSIS_V1: ErrorAnalysisDefinition = ErrorAnalysisDefinition(
    study_id=STUDY_ID,
    study_version=STUDY_VERSION,
    study_schema_version=STUDY_SCHEMA_VERSION,
    source_study_id=SOURCE_STUDY_ID,
    source_study_version=SOURCE_STUDY_VERSION,
    source_study_fingerprint=SOURCE_STUDY_FINGERPRINT,
    source_methodology_sha=SOURCE_METHODOLOGY_SHA,
    source_result_sha=SOURCE_RESULT_SHA,
    source_hashes=SOURCE_HASHES,
    source_observation_start=SOURCE_OBSERVATION_START,
    source_observation_end=SOURCE_OBSERVATION_END,
    symbols=UNIVERSE,
    hypotheses=HYPOTHESES,
    horizons=HORIZONS,
    segments=SEGMENTS,
    asset_classes=ASSET_CLASSES,
)


# -- source rows -------------------------------------------------------------------------------


@dataclass(frozen=True)
class HorizonValue:
    horizon_bars: int
    status: str
    outcome_value: float | None


@dataclass(frozen=True)
class SourceRow:
    """One frozen observation row, typed. Returns are read, never computed."""

    position: int
    symbol: str
    timestamp: datetime
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    state: str
    reason_signature: str
    outcomes: tuple[HorizonValue, ...]

    def value(self, horizon: int) -> float | None:
        for outcome in self.outcomes:
            if outcome.horizon_bars == horizon:
                return outcome.outcome_value if outcome.status == EVALUATED else None
        raise ErrorAnalysisError(f"row has no horizon {horizon}")

    def status(self, horizon: int) -> str:
        for outcome in self.outcomes:
            if outcome.horizon_bars == horizon:
                return outcome.status
        raise ErrorAnalysisError(f"row has no horizon {horizon}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_timestamp(text: str, label: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ErrorAnalysisError(f"{label}: unparseable timestamp {text!r}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ErrorAnalysisError(f"{label}: timestamp {text!r} is not timezone-aware")
    return value


def verify_source_bytes(definition: ErrorAnalysisDefinition, texts: Mapping[str, str]) -> None:
    """Refuse anything but the exact frozen bytes."""
    if set(texts) != set(SOURCE_ARTIFACT_NAMES):
        raise ErrorAnalysisError(
            f"source artifacts must be exactly {list(SOURCE_ARTIFACT_NAMES)}, got {sorted(texts)}"
        )
    for name in SOURCE_ARTIFACT_NAMES:
        actual = sha256_text(texts[name])
        expected = definition.source_hashes[name]
        if actual != expected:
            raise ErrorAnalysisError(
                f"{name}: SHA-256 {actual} does not match the pinned source hash {expected}; "
                "this is not the frozen Baseline Study v1 artifact and will not be analysed"
            )


def verify_source_manifest(definition: ErrorAnalysisDefinition, text: str) -> dict[str, Any]:
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise ErrorAnalysisError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ErrorAnalysisError("manifest.json must be a JSON object")
    checks = (
        ("study_id", definition.source_study_id),
        ("study_version", definition.source_study_version),
        ("study_fingerprint", definition.source_study_fingerprint),
        ("git_commit", definition.source_methodology_sha),
        ("universe", list(definition.symbols)),
        ("observation_start", _utc_iso(definition.source_observation_start)),
        ("observation_end", _utc_iso(definition.source_observation_end)),
    )
    for key, expected in checks:
        if manifest.get(key) != expected:
            raise ErrorAnalysisError(
                f"manifest {key} is {manifest.get(key)!r}, expected {expected!r}"
            )
    hypotheses = [
        (h.get("hypothesis_id"), h.get("version"), h.get("fingerprint"))
        for h in manifest.get("hypotheses", [])
    ]
    if tuple(hypotheses) != definition.hypotheses:
        raise ErrorAnalysisError(
            f"manifest hypotheses {hypotheses} differ from the pinned {list(definition.hypotheses)}"
        )
    horizons = tuple(s.get("horizon_bars") for s in manifest.get("outcome_specs", []))
    if horizons != definition.horizons:
        raise ErrorAnalysisError(f"manifest horizons {horizons} differ from {definition.horizons}")
    return manifest


def observation_columns(horizons: Sequence[int]) -> tuple[str, ...]:
    columns = ["symbol", "timestamp", "hypothesis_id", "hypothesis_version",
               "hypothesis_fingerprint", "state", "reason_codes"]
    for h in horizons:
        columns += [f"status_h{h}", f"return_h{h}", f"reference_timestamp_h{h}", f"future_timestamp_h{h}"]
    return tuple(columns)


def parse_observations(definition: ErrorAnalysisDefinition, text: str) -> tuple[SourceRow, ...]:
    """Parse and validate every row. Nothing is dropped; anything wrong refuses."""
    reader = csv.DictReader(io.StringIO(text))
    expected = observation_columns(definition.horizons)
    if tuple(reader.fieldnames or ()) != expected:
        raise ErrorAnalysisError(
            f"observations.csv columns {reader.fieldnames} differ from the frozen layout {list(expected)}"
        )
    identities = {h: (v, f) for h, v, f in definition.hypotheses}
    rows: list[SourceRow] = []
    seen: set[tuple[str, str, str]] = set()
    for position, raw in enumerate(reader):
        label = f"observations.csv row {position + 2}"
        symbol = raw["symbol"]
        if symbol not in definition.symbols:
            raise ErrorAnalysisError(f"{label}: symbol {symbol!r} is not in the universe")
        timestamp = _parse_timestamp(raw["timestamp"], label)
        if timestamp >= definition.source_observation_end:
            raise ErrorAnalysisError(
                f"{label}: timestamp {raw['timestamp']} is on or after the frozen observation end "
                f"{_utc_iso(definition.source_observation_end)}; the source contract forbids it "
                "and it is refused rather than filtered"
            )
        if timestamp < definition.source_observation_start:
            raise ErrorAnalysisError(
                f"{label}: timestamp {raw['timestamp']} precedes the frozen observation start"
            )
        hypothesis_id = raw["hypothesis_id"]
        if hypothesis_id not in identities:
            raise ErrorAnalysisError(f"{label}: unknown hypothesis {hypothesis_id!r}")
        version, fingerprint = identities[hypothesis_id]
        if raw["hypothesis_version"] != str(version) or raw["hypothesis_fingerprint"] != fingerprint:
            raise ErrorAnalysisError(
                f"{label}: hypothesis identity {hypothesis_id}@v{raw['hypothesis_version']}"
                f"#{raw['hypothesis_fingerprint']} is not the pinned identity"
            )
        state = raw["state"]
        if state not in SOURCE_STATES:
            raise ErrorAnalysisError(f"{label}: unknown state {state!r}")
        key = (symbol, raw["timestamp"], hypothesis_id)
        if key in seen:
            raise ErrorAnalysisError(f"{label}: duplicate observation identity {key}")
        seen.add(key)
        outcomes = []
        for h in definition.horizons:
            status = raw[f"status_h{h}"]
            cell = raw[f"return_h{h}"]
            if status == EVALUATED:
                try:
                    value: float | None = float(cell)
                except ValueError as exc:
                    raise ErrorAnalysisError(f"{label}: return_h{h} {cell!r} is not a number") from exc
            else:
                if cell != "":
                    raise ErrorAnalysisError(f"{label}: status {status!r} must not carry a return")
                value = None
            if (state == "insufficient_data") != (status == "ineligible_observation"):
                raise ErrorAnalysisError(
                    f"{label}: state {state!r} is inconsistent with status_h{h} {status!r}"
                )
            outcomes.append(HorizonValue(h, status, value))
        rows.append(SourceRow(
            position=position, symbol=symbol, timestamp=timestamp, hypothesis_id=hypothesis_id,
            hypothesis_version=version, hypothesis_fingerprint=fingerprint, state=state,
            reason_signature=raw["reason_codes"], outcomes=tuple(outcomes),
        ))
    if not rows:
        raise ErrorAnalysisError("observations.csv carries no rows")
    return tuple(rows)


def _ordered(rows: Sequence[SourceRow], symbol: str, hypothesis_id: str) -> list[SourceRow]:
    """The observation sequence of one symbol/hypothesis, in bar order."""
    selected = [r for r in rows if r.symbol == symbol and r.hypothesis_id == hypothesis_id]
    selected.sort(key=lambda r: (r.timestamp, r.position))
    for a, b in zip(selected, selected[1:]):
        if a.timestamp == b.timestamp:
            raise ErrorAnalysisError(
                f"{symbol} {hypothesis_id}: two observations at {a.timestamp.isoformat()}"
            )
    return selected


def _delta(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None:
        return None
    return value - reference


# -- Phase R recomputation cross-check ----------------------------------------------------------


def _phase_r_rows(
    definition: ErrorAnalysisDefinition, rows: Sequence[SourceRow]
) -> dict[tuple, dict[str, Any]]:
    """Recompute the Phase R matched / state / neutral_reason rows from the raw rows."""
    out: dict[tuple, dict[str, Any]] = {}
    for symbol in definition.symbols:
        for hypothesis_id in definition.hypothesis_ids:
            sequence = _ordered(rows, symbol, hypothesis_id)
            for h in definition.horizons:
                evaluated = [r.status(h) == EVALUATED for r in sequence]
                matched = DescriptiveStats.over([r.value(h) for r, e in zip(sequence, evaluated) if e])
                out[(hypothesis_id, symbol, h, "matched_unconditional", STATE_ALL, "")] = {
                    "stats": matched, "episodes": count_episodes(evaluated),
                    "mean_delta": None, "median_delta": None,
                }
                for state in REPORTED_STATES:
                    members = [e and r.state == state for r, e in zip(sequence, evaluated)]
                    stats = DescriptiveStats.over([r.value(h) for r, m in zip(sequence, members) if m])
                    out[(hypothesis_id, symbol, h, "state", state, "")] = {
                        "stats": stats, "episodes": count_episodes(members),
                        "mean_delta": _delta(stats.mean_forward_return, matched.mean_forward_return),
                        "median_delta": _delta(stats.median_forward_return, matched.median_forward_return),
                    }
                signatures = sorted({r.reason_signature for r, e in zip(sequence, evaluated)
                                     if e and r.state == "neutral"})
                for signature in signatures:
                    members = [e and r.state == "neutral" and r.reason_signature == signature
                               for r, e in zip(sequence, evaluated)]
                    stats = DescriptiveStats.over([r.value(h) for r, m in zip(sequence, members) if m])
                    out[(hypothesis_id, symbol, h, "neutral_reason", "neutral", signature)] = {
                        "stats": stats, "episodes": count_episodes(members),
                        "mean_delta": _delta(stats.mean_forward_return, matched.mean_forward_return),
                        "median_delta": _delta(stats.median_forward_return, matched.median_forward_return),
                    }
    return out


def _cell_float(cell: str) -> float | None:
    return None if cell == "" else float(cell)


def verify_source_summary(
    definition: ErrorAnalysisDefinition, text: str, rows: Sequence[SourceRow]
) -> int:
    """Every frozen state row must equal its recomputation from the raw rows.

    Returns the number of result rows checked. A single disagreement refuses
    the source: the two artifacts would not describe the same run.
    """
    reader = csv.DictReader(io.StringIO(text))
    recomputed = _phase_r_rows(definition, rows)
    checked = 0
    seen: set[tuple] = set()
    for raw in reader:
        row_type = raw.get("row_type")
        if row_type == "coverage":
            continue
        if row_type not in ("state", "matched_unconditional", "neutral_reason"):
            raise ErrorAnalysisError(f"summary.csv carries unknown row_type {row_type!r}")
        key = (raw["hypothesis_id"], raw["symbol"], int(raw["horizon_bars"]), row_type,
               raw["state"], raw["reason_signature"])
        if key not in recomputed:
            raise ErrorAnalysisError(f"summary.csv row {key} has no counterpart in the raw rows")
        expected = recomputed[key]
        stats: DescriptiveStats = expected["stats"]
        pairs = (
            ("sample_count", stats.sample_count), ("mean_forward_return", stats.mean_forward_return),
            ("median_forward_return", stats.median_forward_return),
            ("min_forward_return", stats.min_forward_return),
            ("max_forward_return", stats.max_forward_return),
            ("positive_count", stats.positive_count), ("negative_count", stats.negative_count),
            ("zero_count", stats.zero_count), ("episode_count", expected["episodes"]),
            ("mean_delta_vs_matched_unconditional", expected["mean_delta"]),
            ("median_delta_vs_matched_unconditional", expected["median_delta"]),
        )
        for column, value in pairs:
            cell = raw[column]
            actual = int(cell) if isinstance(value, int) and cell != "" else _cell_float(cell)
            if actual != value:
                raise ErrorAnalysisError(
                    f"summary.csv {key} {column} is {cell!r} but recomputes to {value!r}; "
                    "the frozen summary and observations do not describe one run"
                )
        seen.add(key)
        checked += 1
    missing = set(recomputed) - seen
    if missing:
        raise ErrorAnalysisError(f"summary.csv lacks {len(missing)} recomputed rows, e.g. {sorted(missing)[0]}")
    return checked


# -- result records ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Episode:
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    symbol: str
    state: str
    reason_signature: str
    episode_index: int
    start_timestamp: datetime
    end_timestamp: datetime
    length: int
    start_outcomes: tuple[HorizonValue, ...]


@dataclass(frozen=True)
class DiagnosticRow:
    """One ``diagnostics.csv`` row. Unused cells are ``None``."""

    row_type: str
    hypothesis_id: str = ""
    symbol: str = ""
    asset_class: str = ""
    state: str = ""
    horizon_bars: int | None = None
    segment: str = ""
    partition: str = ""
    reason_signature: str = ""
    momentum_state: str = ""
    sampling_view: str = ""
    count: int | None = None
    stats: DescriptiveStats | None = None
    episode_count: int | None = None
    mean_delta: float | None = None
    median_delta: float | None = None
    delta_reference: str = ""
    length_min: int | None = None
    length_median: float | None = None
    length_max: int | None = None
    share_largest_episode: float | None = None
    share_three_largest: float | None = None
    mean_delta_sign: str = ""
    median_delta_sign: str = ""
    timestamp: datetime | None = None
    bars_since_previous_cross: int | None = None
    returns: tuple[HorizonValue, ...] = ()


@dataclass(frozen=True)
class DecisionAid:
    """A predeclared descriptive reading aid. Not a test, not a verdict."""

    aid: str
    hypothesis_id: str
    symbol: str
    asset_class: str
    state: str
    horizon_bars: int
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class ErrorAnalysisResult:
    definition: ErrorAnalysisDefinition
    source_manifest: Mapping[str, Any]
    source_rows_checked: int
    observation_rows: int
    episodes: tuple[Episode, ...]
    diagnostics: tuple[DiagnosticRow, ...]
    decision_aids: tuple[DecisionAid, ...]


# -- diagnostics -------------------------------------------------------------------------------


def reconstruct_episodes(
    definition: ErrorAnalysisDefinition, rows: Sequence[SourceRow]
) -> tuple[Episode, ...]:
    """Maximal same-state runs in bar order, per symbol and hypothesis."""
    episodes: list[Episode] = []
    for symbol in definition.symbols:
        for hypothesis_id, version, fingerprint in definition.hypotheses:
            sequence = _ordered(rows, symbol, hypothesis_id)
            index = 0
            start = 0
            while start < len(sequence):
                stop = start
                while stop + 1 < len(sequence) and sequence[stop + 1].state == sequence[start].state:
                    stop += 1
                first = sequence[start]
                episodes.append(Episode(
                    hypothesis_id=hypothesis_id, hypothesis_version=version,
                    hypothesis_fingerprint=fingerprint, symbol=symbol, state=first.state,
                    reason_signature=first.reason_signature, episode_index=index,
                    start_timestamp=first.timestamp, end_timestamp=sequence[stop].timestamp,
                    length=stop - start + 1, start_outcomes=first.outcomes,
                ))
                index += 1
                start = stop + 1
    return tuple(episodes)


def _sign(value: float | None) -> str:
    if value is None:
        return ""
    return "+" if value > 0 else "-" if value < 0 else "0"


def _episode_rows(definition, rows, episodes) -> list[DiagnosticRow]:
    out: list[DiagnosticRow] = []
    for symbol in definition.symbols:
        for hypothesis_id in definition.hypothesis_ids:
            for state in SOURCE_STATES:
                group = [e for e in episodes if e.symbol == symbol and e.hypothesis_id == hypothesis_id
                         and e.state == state]
                observations = sum(e.length for e in group)
                if not group:
                    continue
                lengths = sorted((e.length for e in group), reverse=True)
                out.append(DiagnosticRow(
                    row_type=ROW_EPISODE_SUMMARY, hypothesis_id=hypothesis_id, symbol=symbol,
                    asset_class=definition.asset_classes[symbol], state=state,
                    count=observations, episode_count=len(group),
                    length_min=lengths[-1], length_median=statistics.median(lengths),
                    length_max=lengths[0],
                    share_largest_episode=lengths[0] / observations,
                    share_three_largest=sum(lengths[:3]) / observations,
                ))
                if state == "insufficient_data":
                    continue
                for h in definition.horizons:
                    values = [
                        hv.outcome_value for e in group for hv in e.start_outcomes
                        if hv.horizon_bars == h and hv.status == EVALUATED
                    ]
                    out.append(DiagnosticRow(
                        row_type=ROW_EPISODE_START, hypothesis_id=hypothesis_id, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=state, horizon_bars=h,
                        sampling_view="episode_start", count=len(values),
                        stats=DescriptiveStats.over(values), episode_count=len(group),
                    ))
    return out


def _gate_rows(definition, rows) -> list[DiagnosticRow]:
    out: list[DiagnosticRow] = []
    for symbol in definition.symbols:
        trend = {r.timestamp: r for r in _ordered(rows, symbol, TREND_ID)}
        momentum = {r.timestamp: r for r in _ordered(rows, symbol, MOMENTUM_ID)}
        if set(trend) != set(momentum):
            raise ErrorAnalysisError(
                f"{symbol}: trend_alignment and momentum_in_trend_context do not share the same "
                f"timestamps ({len(trend)} vs {len(momentum)}); a common-timestamp comparison "
                "cannot silently drop a bar"
            )
        stamps = sorted(trend)
        # Complete cross-tab, every cell, including empty ones.
        for trend_state in SOURCE_STATES:
            for momentum_state in SOURCE_STATES:
                count = sum(1 for t in stamps if trend[t].state == trend_state
                            and momentum[t].state == momentum_state)
                out.append(DiagnosticRow(
                    row_type=ROW_GATE_CROSSTAB, hypothesis_id=TREND_ID, symbol=symbol,
                    asset_class=definition.asset_classes[symbol], state=trend_state,
                    momentum_state=momentum_state, count=count,
                ))
        for direction in DIRECTIONAL_STATES:
            parent = [t for t in stamps if trend[t].state == direction]
            opposite = "bearish" if direction == "bullish" else "bullish"

            def partition_of(t):
                m = momentum[t].state
                if m == direction:
                    return PARTITION_RETAINED
                if m == "neutral":
                    return PARTITION_REMOVED
                if m == opposite:
                    return PARTITION_OPPOSITE
                return "ineligible"  # momentum INSUFFICIENT_DATA at a trend-directional bar

            for h in definition.horizons:
                parent_eval = [t for t in parent if trend[t].status(h) == EVALUATED]
                parent_stats = DescriptiveStats.over([trend[t].value(h) for t in parent_eval])
                partitions: list[tuple[str, str, list]] = [(PARTITION_RETAINED, "", []),
                                                           (PARTITION_REMOVED, "", []),
                                                           (PARTITION_OPPOSITE, "", [])]
                by_signature: dict[str, list] = {}
                extra: list = []
                for t in parent_eval:
                    p = partition_of(t)
                    if p == PARTITION_RETAINED:
                        partitions[0][2].append(t)
                    elif p == PARTITION_REMOVED:
                        partitions[1][2].append(t)
                        by_signature.setdefault(momentum[t].reason_signature, []).append(t)
                    elif p == PARTITION_OPPOSITE:
                        partitions[2][2].append(t)
                    else:
                        extra.append(t)
                if extra:
                    raise ErrorAnalysisError(
                        f"{symbol} {direction} h{h}: {len(extra)} trend-directional bars have no "
                        "momentum classification; the source contract does not allow that"
                    )
                accounted = sum(len(p[2]) for p in partitions)
                if accounted != len(parent_eval):  # pragma: no cover - defensive
                    raise ErrorAnalysisError("gate partitions do not account for every parent bar")
                for signature in sorted(by_signature):
                    partitions.append((PARTITION_REMOVED, signature, by_signature[signature]))
                for name, signature, members in partitions:
                    stats = DescriptiveStats.over([trend[t].value(h) for t in members])
                    out.append(DiagnosticRow(
                        row_type=ROW_GATE_PARTITION, hypothesis_id=TREND_ID, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=direction,
                        horizon_bars=h, partition=name, reason_signature=signature,
                        count=stats.sample_count, stats=stats,
                        mean_delta=_delta(stats.mean_forward_return, parent_stats.mean_forward_return),
                        median_delta=_delta(stats.median_forward_return, parent_stats.median_forward_return),
                        delta_reference="parent_trend_state",
                    ))
    return out


def _segment_rows(definition, rows) -> list[DiagnosticRow]:
    out: list[DiagnosticRow] = []
    for hypothesis_id in definition.hypothesis_ids:
        for symbol in definition.symbols:
            sequence = _ordered(rows, symbol, hypothesis_id)
            for label, _, _ in definition.segments:
                inside = [definition.segment_of(r.timestamp) == label for r in sequence]
                for h in definition.horizons:
                    evaluated = [i and r.status(h) == EVALUATED for r, i in zip(sequence, inside)]
                    matched = DescriptiveStats.over([r.value(h) for r, e in zip(sequence, evaluated) if e])
                    out.append(DiagnosticRow(
                        row_type=ROW_SEGMENT_MATCHED, hypothesis_id=hypothesis_id, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=STATE_ALL,
                        horizon_bars=h, segment=label, count=matched.sample_count, stats=matched,
                        episode_count=count_episodes(evaluated),
                    ))
                    for state in REPORTED_STATES:
                        members = [e and r.state == state for r, e in zip(sequence, evaluated)]
                        stats = DescriptiveStats.over([r.value(h) for r, m in zip(sequence, members) if m])
                        out.append(DiagnosticRow(
                            row_type=ROW_SEGMENT_STATE, hypothesis_id=hypothesis_id, symbol=symbol,
                            asset_class=definition.asset_classes[symbol], state=state,
                            horizon_bars=h, segment=label, count=stats.sample_count, stats=stats,
                            episode_count=count_episodes(members),
                            mean_delta=_delta(stats.mean_forward_return, matched.mean_forward_return),
                            median_delta=_delta(stats.median_forward_return, matched.median_forward_return),
                            delta_reference="segment_matched_unconditional",
                        ))
    return out


def _class_rows(definition, phase_r) -> list[DiagnosticRow]:
    out: list[DiagnosticRow] = []
    classes = sorted({definition.asset_classes[s] for s in definition.symbols})
    for hypothesis_id in definition.hypothesis_ids:
        for state in REPORTED_STATES:
            for h in definition.horizons:
                signs: dict[str, list[tuple[str, str]]] = {c: [] for c in classes}
                for symbol in definition.symbols:
                    cell = phase_r[(hypothesis_id, symbol, h, "state", state, "")]
                    ms, ds = _sign(cell["mean_delta"]), _sign(cell["median_delta"])
                    signs[definition.asset_classes[symbol]].append((ms, ds))
                    out.append(DiagnosticRow(
                        row_type=ROW_CLASS_SIGNS, hypothesis_id=hypothesis_id, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=state, horizon_bars=h,
                        count=cell["stats"].sample_count, mean_delta=cell["mean_delta"],
                        median_delta=cell["median_delta"], delta_reference="matched_unconditional",
                        mean_delta_sign=ms, median_delta_sign=ds,
                    ))
                for asset_class in classes:
                    pairs = signs[asset_class]
                    out.append(DiagnosticRow(
                        row_type=ROW_CLASS_SIGNS, hypothesis_id=hypothesis_id, symbol="",
                        asset_class=asset_class, state=state, horizon_bars=h, count=len(pairs),
                        mean_delta_sign="".join(p[0] for p in pairs),
                        median_delta_sign="".join(p[1] for p in pairs),
                        delta_reference="matched_unconditional",
                    ))
    return out


def _crossover_rows(definition, rows) -> list[DiagnosticRow]:
    out: list[DiagnosticRow] = []
    for symbol in definition.symbols:
        sequence = _ordered(rows, symbol, CROSSOVER_ID)
        previous: int | None = None
        for index, row in enumerate(sequence):
            if row.state not in DIRECTIONAL_STATES:
                continue
            out.append(DiagnosticRow(
                row_type=ROW_CROSSOVER_EVENT, hypothesis_id=CROSSOVER_ID, symbol=symbol,
                asset_class=definition.asset_classes[symbol], state=row.state,
                timestamp=row.timestamp,
                bars_since_previous_cross=None if previous is None else index - previous,
                returns=row.outcomes,
            ))
            previous = index
    return out


def _decision_aids(definition, phase_r, diagnostics) -> list[DecisionAid]:
    """Predeclared descriptive reading aids, computed for every symbol so no
    favourable subset can be chosen later. No verdict is attached."""
    aids: list[DecisionAid] = []
    segment_rows = [d for d in diagnostics if d.row_type == ROW_SEGMENT_STATE]
    summary_rows = [d for d in diagnostics if d.row_type == ROW_EPISODE_SUMMARY]
    for hypothesis_id in (TREND_ID, MOMENTUM_ID):
        for symbol in definition.symbols:
            for state in DIRECTIONAL_STATES:
                for h in definition.horizons:
                    full = phase_r[(hypothesis_id, symbol, h, "state", state, "")]
                    full_mean, full_median = _sign(full["mean_delta"]), _sign(full["median_delta"])
                    cells = [d for d in segment_rows if d.hypothesis_id == hypothesis_id
                             and d.symbol == symbol and d.state == state and d.horizon_bars == h]
                    same_mean = sum(1 for d in cells if _sign(d.mean_delta) == full_mean and full_mean)
                    same_median = sum(1 for d in cells if _sign(d.median_delta) == full_median and full_median)
                    aids.append(DecisionAid(
                        aid="segment_sign_agreement", hypothesis_id=hypothesis_id, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=state, horizon_bars=h,
                        detail={
                            "full_window_mean_delta_sign": full_mean,
                            "full_window_median_delta_sign": full_median,
                            "segments": len(cells),
                            "segments_with_same_mean_sign": same_mean,
                            "segments_with_same_median_sign": same_median,
                            "majority_threshold": definition.decision_aid_segment_majority,
                        },
                    ))
                summary = [d for d in summary_rows if d.hypothesis_id == hypothesis_id
                           and d.symbol == symbol and d.state == state]
                if summary:
                    s = summary[0]
                    aids.append(DecisionAid(
                        aid="episode_concentration", hypothesis_id=hypothesis_id, symbol=symbol,
                        asset_class=definition.asset_classes[symbol], state=state, horizon_bars=0,
                        detail={
                            "observations": s.count, "episodes": s.episode_count,
                            "share_largest_episode": s.share_largest_episode,
                            "share_three_largest": s.share_three_largest,
                            "share_threshold": definition.decision_aid_episode_share,
                        },
                    ))
    partition_rows = [d for d in diagnostics if d.row_type == ROW_GATE_PARTITION and d.reason_signature == ""]
    for symbol in definition.symbols:
        for direction in DIRECTIONAL_STATES:
            for h in definition.horizons:
                cells = {d.partition: d for d in partition_rows if d.symbol == symbol
                         and d.state == direction and d.horizon_bars == h}
                aids.append(DecisionAid(
                    aid="gate_partition_signs", hypothesis_id=TREND_ID, symbol=symbol,
                    asset_class=definition.asset_classes[symbol], state=direction, horizon_bars=h,
                    detail={
                        "retained_n": cells[PARTITION_RETAINED].count,
                        "removed_n": cells[PARTITION_REMOVED].count,
                        "opposite_n": cells[PARTITION_OPPOSITE].count,
                        "retained_median_delta_sign": _sign(cells[PARTITION_RETAINED].median_delta),
                        "removed_median_delta_sign": _sign(cells[PARTITION_REMOVED].median_delta),
                        "retained_mean_delta_sign": _sign(cells[PARTITION_RETAINED].mean_delta),
                        "removed_mean_delta_sign": _sign(cells[PARTITION_REMOVED].mean_delta),
                    },
                ))
    return aids


def run_error_analysis(
    definition: ErrorAnalysisDefinition, texts: Mapping[str, str]
) -> ErrorAnalysisResult:
    """Verify the frozen source, cross-check it, and compute the diagnostics."""
    if not isinstance(definition, ErrorAnalysisDefinition):
        raise ErrorAnalysisError("expected an ErrorAnalysisDefinition")
    verify_source_bytes(definition, texts)
    manifest = verify_source_manifest(definition, texts[SOURCE_MANIFEST])
    rows = parse_observations(definition, texts[SOURCE_OBSERVATIONS])
    checked = verify_source_summary(definition, texts[SOURCE_SUMMARY], rows)
    phase_r = _phase_r_rows(definition, rows)

    episodes = reconstruct_episodes(definition, rows)
    if sum(e.length for e in episodes) != len(rows):  # pragma: no cover - defensive
        raise ErrorAnalysisError("episodes do not account for every observation")

    diagnostics: list[DiagnosticRow] = []
    diagnostics += _episode_rows(definition, rows, episodes)
    diagnostics += _gate_rows(definition, rows)
    diagnostics += _segment_rows(definition, rows)
    diagnostics += _class_rows(definition, phase_r)
    diagnostics += _crossover_rows(definition, rows)
    aids = _decision_aids(definition, phase_r, diagnostics)

    return ErrorAnalysisResult(
        definition=definition, source_manifest=manifest, source_rows_checked=checked,
        observation_rows=len(rows), episodes=episodes, diagnostics=tuple(diagnostics),
        decision_aids=tuple(aids),
    )


__all__ = [
    "ErrorAnalysisError", "ErrorAnalysisDefinition", "ERROR_ANALYSIS_V1",
    "STUDY_ID", "STUDY_VERSION", "STUDY_SCHEMA_VERSION",
    "SOURCE_STUDY_ID", "SOURCE_STUDY_VERSION", "SOURCE_STUDY_FINGERPRINT",
    "SOURCE_METHODOLOGY_SHA", "SOURCE_RESULT_SHA", "SOURCE_HASHES", "SOURCE_ARTIFACT_NAMES",
    "SOURCE_MANIFEST", "SOURCE_SUMMARY", "SOURCE_OBSERVATIONS",
    "SOURCE_OBSERVATION_START", "SOURCE_OBSERVATION_END", "UNIVERSE", "HORIZONS", "HYPOTHESES",
    "TREND_ID", "MOMENTUM_ID", "CROSSOVER_ID", "SEGMENTS", "ASSET_CLASSES", "DIAGNOSTICS",
    "ROW_TYPES", "ROW_EPISODE_SUMMARY", "ROW_EPISODE_START", "ROW_GATE_CROSSTAB",
    "ROW_GATE_PARTITION", "ROW_SEGMENT_STATE", "ROW_SEGMENT_MATCHED", "ROW_CLASS_SIGNS",
    "ROW_CROSSOVER_EVENT", "PARTITIONS", "PARTITION_RETAINED", "PARTITION_REMOVED",
    "PARTITION_OPPOSITE", "METRIC_NAMES", "DECISION_AID_SEGMENT_MAJORITY",
    "DECISION_AID_EPISODE_SHARE", "SourceRow", "HorizonValue", "Episode", "DiagnosticRow",
    "DecisionAid", "ErrorAnalysisResult", "sha256_text", "observation_columns",
    "verify_source_bytes", "verify_source_manifest", "verify_source_summary",
    "parse_observations", "reconstruct_episodes", "run_error_analysis",
]
