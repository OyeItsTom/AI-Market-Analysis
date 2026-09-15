"""Phase 12C: the JSONL line contract -- exact reconstruction, nothing more.

A stored line must reconstruct the *same* record: equal by dataclass
semantics, same enum types, same keys, same floats bit for bit. The store's
encoders are private; these tests reach them through the module because
the contract they pin is the store's, and the ledger tests then prove the
same through the public surface.
"""

from __future__ import annotations

import json
import math
import pathlib
from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from src.assessments.assessment import AssessmentReasonCode, AssessmentState
from src.data.models import Interval
from src.data.series import PriceBasis
from src.outcomes import (
    ArtifactKind,
    ArtifactOrigin,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeRecord,
)
from src.outcomes.store import (
    RECORD_TYPE_ARTIFACT,
    RECORD_TYPE_OUTCOME,
    SCHEMA_VERSION,
    _artifact_from_row,
    _artifact_row,
    _encode_line,
    _outcome_from_row,
    _outcome_row,
)
from src.strategies.research import ReasonCode, ResearchState

from test_outcomes_models import (
    EVALUATED_AT,
    FP64,
    RECORDED,
    T0,
    asmt_artifact,
    obs_artifact,
    record,
)

UTC = timezone.utc


def round_trip_artifact(artifact):
    line = _encode_line(_artifact_row(artifact))
    return _artifact_from_row(json.loads(line))


def round_trip_outcome(outcome):
    line = _encode_line(_outcome_row(outcome))
    return _outcome_from_row(json.loads(line))


# -- artifacts --------------------------------------------------------------------------


class TestArtifactRoundTrip:
    def test_observation_reconstructs_exactly(self):
        original = obs_artifact(reason_codes=(ReasonCode.FAST_ABOVE_SLOW, ReasonCode.WARMUP_INCOMPLETE))
        decoded = round_trip_artifact(original)
        assert type(decoded) is ObservationArtifact
        assert decoded == original
        assert decoded.artifact_key == original.artifact_key
        assert type(decoded.state) is ResearchState
        assert all(type(code) is ReasonCode for code in decoded.reason_codes)
        assert decoded.reason_codes == original.reason_codes
        assert isinstance(decoded.reason_codes, tuple)
        assert decoded.kind is ArtifactKind.OBSERVATION
        assert decoded.origin is ArtifactOrigin.SNAPSHOT
        assert decoded.interval is Interval.DAY_1 and decoded.basis is PriceBasis.RAW
        assert decoded.observation_bar_fingerprint == FP64
        assert (decoded.hypothesis_id, decoded.hypothesis_version, decoded.hypothesis_fingerprint) == (
            original.hypothesis_id, original.hypothesis_version, original.hypothesis_fingerprint)
        for stamp in (decoded.timestamp, decoded.data_cutoff, decoded.recorded_at):
            assert stamp.tzinfo is not None and stamp.utcoffset() is not None

    def test_assessment_reconstructs_exactly_including_conflicted(self):
        original = asmt_artifact(
            state=AssessmentState.CONFLICTED,
            reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,),
            basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
            interval=Interval.HOUR_1,
        )
        decoded = round_trip_artifact(original)
        assert type(decoded) is AssessmentArtifact
        assert decoded == original
        assert decoded.artifact_key == original.artifact_key
        assert type(decoded.state) is AssessmentState
        assert decoded.state is AssessmentState.CONFLICTED
        assert all(type(code) is AssessmentReasonCode for code in decoded.reason_codes)
        assert decoded.policy_fingerprint == original.policy_fingerprint
        assert decoded.basis is PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
        assert decoded.interval is Interval.HOUR_1

    def test_vocabularies_are_not_collapsed(self):
        """``bullish`` is stored as a string; the decoder must hand it back in
        the artifact kind's own enum, never the other kind's."""
        obs = round_trip_artifact(obs_artifact(state=ResearchState.BULLISH))
        asmt = round_trip_artifact(asmt_artifact(state=AssessmentState.BULLISH))
        assert type(obs.state) is ResearchState and type(asmt.state) is AssessmentState
        assert obs.state is not asmt.state

    @pytest.mark.parametrize("state", list(ResearchState))
    def test_every_research_state_survives(self, state):
        decoded = round_trip_artifact(obs_artifact(state=state))
        assert decoded.state is state

    @pytest.mark.parametrize("state", list(AssessmentState))
    def test_every_assessment_state_survives(self, state):
        decoded = round_trip_artifact(asmt_artifact(state=state))
        assert decoded.state is state

    @pytest.mark.parametrize("interval", list(Interval))
    def test_every_interval_survives(self, interval):
        assert round_trip_artifact(obs_artifact(interval=interval)).interval is interval

    @pytest.mark.parametrize("basis", list(PriceBasis))
    def test_every_basis_survives(self, basis):
        assert round_trip_artifact(obs_artifact(basis=basis)).basis is basis

    def test_a_second_round_trip_is_stable(self):
        once = round_trip_artifact(obs_artifact())
        twice = round_trip_artifact(once)
        assert twice == once
        assert _artifact_row(twice) == _artifact_row(once)


# -- outcomes ----------------------------------------------------------------------------


class TestOutcomeRoundTrip:
    def test_outcome_reconstructs_exactly(self):
        original = record()
        decoded = round_trip_outcome(original)
        assert type(decoded) is OutcomeRecord
        assert decoded == original
        assert decoded.artifact == original.artifact
        assert type(decoded.artifact) is type(original.artifact)
        assert decoded.outcome_key == original.outcome_key
        assert decoded.artifact_key == original.artifact_key
        assert decoded.consumed_bars_fingerprint == original.consumed_bars_fingerprint
        assert decoded.evaluation_version == original.evaluation_version
        assert decoded.spec_fingerprint == original.spec_fingerprint
        assert decoded.horizon_bars == original.horizon_bars
        assert decoded.reference_price == original.reference_price
        assert decoded.future_price == original.future_price
        assert decoded.forward_return == original.forward_return
        assert math.copysign(1.0, decoded.forward_return) == math.copysign(1.0, original.forward_return)

    def test_outcome_over_an_assessment_artifact(self):
        original = record(artifact=asmt_artifact(state=AssessmentState.NEUTRAL,
                                                 reason_codes=(AssessmentReasonCode.UNANIMOUS_NEUTRAL,)))
        decoded = round_trip_outcome(original)
        assert decoded == original
        assert type(decoded.artifact) is AssessmentArtifact
        assert decoded.outcome_key == original.outcome_key

    def test_the_price_invariant_survives_reconstruction(self):
        """``forward_return == future / reference - 1`` is checked by the
        domain on construction with exact float equality; decoding a stored
        record must reconstruct a record that passes it."""
        prices = [(100.0, 105.0), (3.3, 3.1), (0.1, 0.3), (123456.789, 123456.788),
                  (1e-7, 3e-7), (1e15, 1e15 + 1.0), (7.0, 7.0)]
        for reference, future in prices:
            original = record(reference_price=reference, future_price=future,
                              forward_return=future / reference - 1.0)
            decoded = round_trip_outcome(original)
            assert decoded.forward_return == original.forward_return
            assert decoded.forward_return == future / reference - 1.0


# -- floats --------------------------------------------------------------------------------


FLOATS = [
    0.0, 0.1 + 0.2, 1e-7, 1e-300, 1e300, 123.456, 4.2e15, 1.0000000000000002,
    -0.049999999999999996, 0.050000000000000044, 179.95, 0.30000000000000004,
]


class TestFloatRoundTrip:
    @pytest.mark.parametrize("value", FLOATS, ids=repr)
    def test_json_shortest_round_trip_is_exact(self, value):
        text = json.dumps(value, allow_nan=False)
        assert json.loads(text) == value
        assert repr(json.loads(text)) == repr(value)
        assert "." in text or "e" in text, "floats are written as floats"

    def test_negative_zero_survives_with_its_sign(self):
        """The domain accepts ``-0.0`` as a forward return (it equals ``0.0``);
        the store must not turn it into something else."""
        decoded = json.loads(json.dumps(-0.0))
        assert decoded == 0.0 and math.copysign(1.0, decoded) == -1.0

    @pytest.mark.parametrize("forward_return", [-0.5, -0.049999999999999996, 0.0,
                                                0.050000000000000044, 2.0])
    def test_forward_return_sign_and_value_survive(self, forward_return):
        reference = 100.0
        future = (forward_return + 1.0) * reference
        original = record(reference_price=reference, future_price=future,
                          forward_return=future / reference - 1.0)
        decoded = round_trip_outcome(original)
        assert decoded.forward_return == original.forward_return
        assert repr(decoded.forward_return) == repr(original.forward_return)
        assert decoded.future_price == future

    def test_no_decimal_formatting_or_rounding_anywhere(self):
        original = record(reference_price=0.1, future_price=0.30000000000000004,
                          forward_return=0.30000000000000004 / 0.1 - 1.0)
        line = _encode_line(_outcome_row(original)).decode()
        assert '"reference_price":0.1' in line
        assert '"future_price":0.30000000000000004' in line
        assert f'"forward_return":{original.forward_return!r}' in line

    def test_random_price_pairs_keep_the_domain_invariant_exactly(self):
        """Beyond the fixed set: seeded, deterministic, wide magnitude range.
        Every reconstructed record must pass ``OutcomeRecord``'s own exact
        ``future / reference - 1`` check, which is the store's contract."""
        import random

        rng = random.Random(20240105)
        for _ in range(400):
            reference = rng.uniform(1e-6, 1e6) * rng.choice([1.0, 1e-3, 1e3])
            future = reference * rng.uniform(0.2, 5.0)
            original = record(reference_price=reference, future_price=future,
                              forward_return=future / reference - 1.0)
            decoded = round_trip_outcome(original)
            assert decoded == original
            assert decoded.forward_return == original.forward_return
            assert decoded.reference_price == reference and decoded.future_price == future

    def test_subnormal_and_extreme_finite_floats_survive(self):
        for value in (5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, -1.7976931348623157e308):
            assert json.loads(json.dumps(value)) == value
            assert repr(json.loads(json.dumps(value))) == repr(value)

    def test_nan_and_infinity_are_never_written(self):
        for bad in (math.nan, math.inf):
            with pytest.raises(ValueError):
                _encode_line({"x": bad})


# -- timestamps ------------------------------------------------------------------------------


class _FoldZone(tzinfo):
    """A zone whose offset falls back one hour at 02:00 on 2024-01-05, so
    01:xx on that day is ambiguous and ``fold`` selects the offset.
    Self-contained: the test does not depend on the machine's tz database."""

    def utcoffset(self, dt):
        if dt.year == 2024 and dt.month == 1 and dt.day == 5 and dt.hour == 1:
            return timedelta(hours=1) if dt.fold == 0 else timedelta(hours=0)
        if (dt.year, dt.month, dt.day) < (2024, 1, 5) or (
            dt.year == 2024 and dt.month == 1 and dt.day == 5 and dt.hour < 1
        ):
            return timedelta(hours=1)
        return timedelta(hours=0)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "Fold"


class TestTimestampRoundTrip:
    def test_stored_as_utc_with_explicit_offset(self):
        line = _encode_line(_artifact_row(obs_artifact())).decode()
        assert '"timestamp":"2024-01-05T00:00:00+00:00"' in line
        assert '"recorded_at":"2024-01-06T02:00:00+00:00"' in line

    def test_a_non_utc_aware_input_reconstructs_to_an_equal_record(self):
        plus5 = timezone(timedelta(hours=5))
        original = obs_artifact(
            timestamp=T0.astimezone(plus5),
            data_cutoff=T0.astimezone(plus5),
            recorded_at=RECORDED.astimezone(plus5),
        )
        decoded = round_trip_artifact(original)
        assert decoded == original, "aware datetimes compare by instant"
        assert decoded.artifact_key == original.artifact_key
        assert decoded.timestamp.utcoffset() == timedelta(0), "stored normalised to UTC"
        assert decoded.timestamp == T0
        line = _encode_line(_artifact_row(original)).decode()
        assert "+05:00" not in line

    def test_a_non_utc_outcome_reconstructs_to_an_equal_record(self):
        minus8 = timezone(timedelta(hours=-8))
        original = record(
            evaluated_at=EVALUATED_AT.astimezone(minus8),
            reference_timestamp=(T0 + timedelta(days=1)).astimezone(minus8),
            future_timestamp=(T0 + timedelta(days=7)).astimezone(minus8),
        )
        decoded = round_trip_outcome(original)
        assert decoded == original
        assert decoded.outcome_key == original.outcome_key
        assert decoded.evaluated_at.utcoffset() == timedelta(0)

    def test_microseconds_survive(self):
        original = obs_artifact(recorded_at=RECORDED + timedelta(microseconds=123456))
        decoded = round_trip_artifact(original)
        assert decoded.recorded_at == original.recorded_at
        assert decoded.recorded_at.microsecond == 123456

    def test_a_dst_fold_input_round_trips_to_the_same_instant(self):
        """PEP 495: an aware datetime in a fold compares *unequal* across
        zones, so dataclass equality with the original is not available for
        this input by Python's own rules. What is available -- and what
        identity is over -- is the instant: the fold=1 reading is stored as
        the UTC instant it denotes, keys agree, and the stored record is
        stable under a further round trip."""
        zone = _FoldZone()
        ambiguous_first = datetime(2024, 1, 5, 1, 30, tzinfo=zone, fold=0)   # 00:30Z
        ambiguous_second = datetime(2024, 1, 5, 1, 30, tzinfo=zone, fold=1)  # 01:30Z
        assert ambiguous_first.astimezone(UTC) != ambiguous_second.astimezone(UTC)

        for reading in (ambiguous_first, ambiguous_second):
            original = obs_artifact(timestamp=reading, data_cutoff=reading,
                                    recorded_at=reading + timedelta(days=1))
            decoded = round_trip_artifact(original)
            assert decoded.timestamp == reading.astimezone(UTC)
            assert decoded.artifact_key == original.artifact_key
            assert round_trip_artifact(decoded) == decoded
        first = round_trip_artifact(obs_artifact(timestamp=ambiguous_first,
                                                 data_cutoff=ambiguous_first))
        second = round_trip_artifact(obs_artifact(timestamp=ambiguous_second,
                                                  data_cutoff=ambiguous_second))
        assert first.artifact_key != second.artifact_key, "the two readings are two bars"


# -- envelope and golden bytes ------------------------------------------------------------


class TestLineContract:
    def test_every_line_carries_schema_version_and_record_type(self):
        artifact_row = json.loads(_encode_line(_artifact_row(obs_artifact())))
        outcome_row = json.loads(_encode_line(_outcome_row(record())))
        assert artifact_row["schema_version"] == SCHEMA_VERSION == 1
        assert outcome_row["schema_version"] == SCHEMA_VERSION
        assert artifact_row["record_type"] == RECORD_TYPE_ARTIFACT == "artifact"
        assert outcome_row["record_type"] == RECORD_TYPE_OUTCOME == "outcome"
        assert "schema_version" not in outcome_row["artifact"]
        assert "record_type" not in outcome_row["artifact"]

    def test_domain_records_carry_no_schema_version(self):
        for obj in (obs_artifact(), asmt_artifact(), record()):
            assert not hasattr(obj, "schema_version")

    def test_line_is_compact_sorted_ascii_and_newline_terminated(self):
        line = _encode_line(_artifact_row(obs_artifact(source="yfinanceé\n")))
        assert line.endswith(b"\n") and line.count(b"\n") == 1
        text = line.decode("ascii")
        assert ": " not in text and ", " not in text
        assert "\\u00e9" in text and "\\n" in text
        keys = list(json.loads(text))
        assert keys == sorted(keys)

    def test_reconstructed_keys_match_stored_keys(self):
        row = json.loads(_encode_line(_outcome_row(record())))
        decoded = _outcome_from_row(row)
        assert row["outcome_key"] == decoded.outcome_key
        assert row["artifact_key"] == decoded.artifact_key == row["artifact"]["artifact_key"]

    GOLDEN_ARTIFACT = (
        '{"artifact_key":"dc6da09c7cfeae5a730c5d7d1eb55f65f4ef268792683b9deffb60d2933ab6b7",'
        '"basis":"raw","data_cutoff":"2024-01-05T00:00:00+00:00",'
        '"hypothesis_fingerprint":"0011223344556677","hypothesis_id":"trend_alignment",'
        '"hypothesis_version":1,"interval":"1d","kind":"observation",'
        '"observation_bar_fingerprint":"' + "a" * 64 + '","origin":"snapshot",'
        '"reason_codes":["fast_above_slow"],"record_type":"artifact",'
        '"recorded_at":"2024-01-06T02:00:00+00:00","schema_version":1,"source":"yfinance",'
        '"state":"bullish","symbol":"AAPL","timestamp":"2024-01-05T00:00:00+00:00"}\n'
    )
    GOLDEN_OUTCOME = (
        '{"artifact":{"artifact_key":"dc6da09c7cfeae5a730c5d7d1eb55f65f4ef268792683b9deffb60d2933ab6b7",'
        '"basis":"raw","data_cutoff":"2024-01-05T00:00:00+00:00",'
        '"hypothesis_fingerprint":"0011223344556677","hypothesis_id":"trend_alignment",'
        '"hypothesis_version":1,"interval":"1d","kind":"observation",'
        '"observation_bar_fingerprint":"' + "a" * 64 + '","origin":"snapshot",'
        '"reason_codes":["fast_above_slow"],"recorded_at":"2024-01-06T02:00:00+00:00",'
        '"source":"yfinance","state":"bullish","symbol":"AAPL",'
        '"timestamp":"2024-01-05T00:00:00+00:00"},'
        '"artifact_key":"dc6da09c7cfeae5a730c5d7d1eb55f65f4ef268792683b9deffb60d2933ab6b7",'
        '"consumed_bars_fingerprint":"' + "b" * 64 + '",'
        '"evaluated_at":"2024-02-05T02:00:00+00:00","evaluation_version":1,'
        '"forward_return":0.050000000000000044,"future_price":105.0,'
        '"future_timestamp":"2024-01-12T00:00:00+00:00","horizon_bars":5,'
        '"outcome_key":"b7198faed8c9e486bf1d8d40bab0bfdcd865a81d6d413f1295d1ea2eb0e0626c",'
        '"record_type":"outcome","reference_price":100.0,'
        '"reference_timestamp":"2024-01-06T00:00:00+00:00","schema_version":1,'
        '"spec_fingerprint":"0123456789abcdef"}\n'
    )

    def test_line_bytes_do_not_depend_on_hash_seed_or_process(self):
        """Sorted keys make the bytes a function of the record alone. Proven
        across processes with different ``PYTHONHASHSEED`` values."""
        import hashlib
        import os
        import subprocess
        import sys

        code = (
            "import sys; sys.path.insert(0, 'tests')\n"
            "from test_outcomes_models import obs_artifact, asmt_artifact, record\n"
            "from src.outcomes.store import _encode_line, _artifact_row, _outcome_row\n"
            "import hashlib\n"
            "print(hashlib.sha256(_encode_line(_artifact_row(obs_artifact()))"
            " + _encode_line(_outcome_row(record(artifact=asmt_artifact())))).hexdigest())\n"
        )
        repo = pathlib.Path(__file__).resolve().parent.parent
        digests = set()
        for seed in ("0", "1", "4242"):
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=repo, capture_output=True, text=True,
                env={**os.environ, "PYTHONHASHSEED": seed}, check=True,
            )
            digests.add(result.stdout.strip())
        local = hashlib.sha256(
            _encode_line(_artifact_row(obs_artifact()))
            + _encode_line(_outcome_row(record(artifact=asmt_artifact())))
        ).hexdigest()
        assert digests == {local}, digests

    def test_golden_storage_bytes_schema_v1(self):
        """Pins the *storage* schema, not domain identity: the field set, its
        sorted order, the compact separators and the value spellings a v1
        line has. A change here is a schema change and needs a version bump;
        the keys inside are the 12A identities and are pinned by their own
        golden vectors."""
        assert _encode_line(_artifact_row(obs_artifact())) == self.GOLDEN_ARTIFACT.encode("ascii")
        assert _encode_line(_outcome_row(record())) == self.GOLDEN_OUTCOME.encode("ascii")
        assert _artifact_from_row(json.loads(self.GOLDEN_ARTIFACT)) == obs_artifact()
        assert _outcome_from_row(json.loads(self.GOLDEN_OUTCOME)) == record()
