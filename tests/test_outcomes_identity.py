"""Phase 12A: deterministic identity for artifacts, outcomes and source bars.

Identity is a SHA-256 over canonical JSON bytes -- the convention every
durable record in this project already uses -- rendered as the **full**
64-hex digest. A ledger key is never truncated for display convenience: the
16-hex form belongs to *specification* fingerprints (hypothesis, policy,
outcome spec), which are human-compared; a record key is machine-compared
for the life of the ledger.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.assessments import AssessmentReasonCode, AssessmentState
from src.data.models import Interval, MarketBar
from src.data.series import PriceBasis
from src.outcomes import (
    EVALUATION_VERSION,
    ArtifactOrigin,
    AssessmentArtifact,
    ObservationArtifact,
    OutcomeTrackingError,
    assessment_artifact_key,
    bar_fingerprint,
    bars_fingerprint,
    observation_artifact_key,
    outcome_key,
)
from src.strategies.research import ReasonCode, ResearchState

UTC = timezone.utc
T0 = datetime(2024, 1, 5, tzinfo=UTC)
FP64 = "c" * 64
HEX = set("0123456789abcdef")

REPO = Path(__file__).resolve().parent.parent


def is_key(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def obs_key(**overrides) -> str:
    fields = dict(
        symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW, timestamp=T0,
        hypothesis_id="trend_alignment", hypothesis_version=1,
        hypothesis_fingerprint="0011223344556677",
    )
    fields.update(overrides)
    return observation_artifact_key(**fields)


def asmt_key(**overrides) -> str:
    fields = dict(
        symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW, timestamp=T0,
        policy_fingerprint="fedcba9876543210",
    )
    fields.update(overrides)
    return assessment_artifact_key(**fields)


def obs_artifact(**overrides) -> ObservationArtifact:
    fields = dict(
        symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW, timestamp=T0,
        state=ResearchState.BULLISH, reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
        source="yfinance", data_cutoff=T0, recorded_at=T0 + timedelta(days=1),
        observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        hypothesis_id="trend_alignment", hypothesis_version=1,
        hypothesis_fingerprint="0011223344556677",
    )
    fields.update(overrides)
    return ObservationArtifact(**fields)


def asmt_artifact(**overrides) -> AssessmentArtifact:
    fields = dict(
        symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW, timestamp=T0,
        state=AssessmentState.BULLISH, reason_codes=(AssessmentReasonCode.UNANIMOUS_BULLISH,),
        source="yfinance", data_cutoff=T0, recorded_at=T0 + timedelta(days=1),
        observation_bar_fingerprint=FP64, origin=ArtifactOrigin.SNAPSHOT,
        policy_fingerprint="fedcba9876543210",
    )
    fields.update(overrides)
    return AssessmentArtifact(**fields)


def bar(**overrides) -> MarketBar:
    fields = dict(symbol="AAPL", timestamp=T0, open=100.0, high=110.0, low=95.0,
                  close=105.0, volume=1_000.0, interval=Interval.DAY_1, source="yfinance")
    fields.update(overrides)
    return MarketBar(**fields)


# -- artifact keys ---------------------------------------------------------------


class TestArtifactKeyFormat:
    def test_full_sha256_hex(self):
        assert is_key(obs_key())
        assert is_key(asmt_key())

    def test_deterministic_across_calls(self):
        assert obs_key() == obs_key()
        assert asmt_key() == asmt_key()

    def test_the_model_property_matches_the_function(self):
        assert obs_artifact().artifact_key == obs_key()
        assert asmt_artifact().artifact_key == asmt_key()

    def test_equivalent_objects_share_a_key(self):
        a = obs_artifact()
        b = obs_artifact(reason_codes=[ReasonCode.FAST_ABOVE_SLOW], interval="1d", basis="raw")
        assert a.artifact_key == b.artifact_key


class TestArtifactKeyIndependence:
    """State and audit values are claims about, or clocks around, the
    artifact; they are not the producer identity. A later ledger detects
    'same key, different claim' as a conflict precisely because the key does
    not absorb the claim."""

    def test_independent_of_state(self):
        bullish = obs_artifact(state=ResearchState.BULLISH)
        bearish = obs_artifact(state=ResearchState.BEARISH,
                               reason_codes=(ReasonCode.FAST_BELOW_SLOW,))
        assert bullish.artifact_key == bearish.artifact_key

    def test_assessment_independent_of_state(self):
        a = asmt_artifact(state=AssessmentState.BULLISH)
        b = asmt_artifact(state=AssessmentState.CONFLICTED,
                          reason_codes=(AssessmentReasonCode.CONFLICTING_DIRECTIONAL_EVIDENCE,))
        assert a.artifact_key == b.artifact_key

    def test_independent_of_reason_codes(self):
        a = obs_artifact(reason_codes=(ReasonCode.FAST_ABOVE_SLOW,))
        b = obs_artifact(reason_codes=(ReasonCode.FAST_ABOVE_SLOW, ReasonCode.MOMENTUM_ELEVATED))
        assert a.artifact_key == b.artifact_key

    def test_independent_of_recorded_at(self):
        a = obs_artifact(recorded_at=T0 + timedelta(days=1))
        b = obs_artifact(recorded_at=T0 + timedelta(days=9))
        assert a.artifact_key == b.artifact_key

    def test_independent_of_source(self):
        assert obs_artifact(source="yfinance").artifact_key == obs_artifact(source="alpaca").artifact_key

    def test_independent_of_data_cutoff(self):
        a = obs_artifact(timestamp=T0 - timedelta(days=2), data_cutoff=T0 - timedelta(days=2))
        b = obs_artifact(timestamp=T0 - timedelta(days=2), data_cutoff=T0)
        assert a.artifact_key == b.artifact_key

    def test_independent_of_bar_fingerprint(self):
        assert obs_artifact(observation_bar_fingerprint="a" * 64).artifact_key == \
            obs_artifact(observation_bar_fingerprint="b" * 64).artifact_key

    def test_independent_of_origin_enum_spelling(self):
        assert obs_artifact(origin="snapshot").artifact_key == \
            obs_artifact(origin=ArtifactOrigin.SNAPSHOT).artifact_key


class TestArtifactKeySensitivity:
    def test_changes_with_symbol(self):
        assert obs_key(symbol="AAPL") != obs_key(symbol="MSFT")
        assert obs_key(symbol="AAPL") != obs_key(symbol="aapl")  # no hidden folding

    def test_changes_with_interval(self):
        assert obs_key(interval="1d") != obs_key(interval="1wk")

    def test_changes_with_basis(self):
        assert obs_key(basis=PriceBasis.RAW) != obs_key(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)

    def test_changes_with_timestamp(self):
        assert obs_key(timestamp=T0) != obs_key(timestamp=T0 + timedelta(days=1))

    def test_changes_with_hypothesis_id(self):
        assert obs_key(hypothesis_id="a") != obs_key(hypothesis_id="b")

    def test_changes_with_hypothesis_version(self):
        assert obs_key(hypothesis_version=1) != obs_key(hypothesis_version=2)

    def test_changes_with_hypothesis_fingerprint(self):
        """A re-parameterised v1 is a different producer forever."""
        assert obs_key(hypothesis_fingerprint="0011223344556677") != \
            obs_key(hypothesis_fingerprint="0011223344556678")

    def test_assessment_changes_with_policy_fingerprint(self):
        assert asmt_key(policy_fingerprint="fedcba9876543210") != \
            asmt_key(policy_fingerprint="fedcba9876543211")

    def test_assessment_changes_with_market_point(self):
        base = asmt_key()
        assert base != asmt_key(symbol="MSFT")
        assert base != asmt_key(interval="1mo")
        assert base != asmt_key(basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED)
        assert base != asmt_key(timestamp=T0 + timedelta(days=1))

    def test_observation_and_assessment_never_collide(self):
        """Same market point; the kind is inside the payload."""
        assert obs_key() != asmt_key()
        assert obs_artifact().artifact_key != asmt_artifact().artifact_key


class TestArtifactKeyTimezones:
    def test_the_same_instant_in_another_zone_is_the_same_key(self):
        """Identity is over the instant, not the rendering. The producers
        normalise bar timestamps to UTC; a caller that did not is not a
        different claim."""
        plus_two = T0.astimezone(timezone(timedelta(hours=2)))
        assert plus_two == T0
        assert obs_key(timestamp=plus_two) == obs_key(timestamp=T0)
        assert asmt_key(timestamp=plus_two) == asmt_key(timestamp=T0)

    def test_naive_timestamp_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="timezone-aware"):
            obs_key(timestamp=datetime(2024, 1, 5))
        with pytest.raises(OutcomeTrackingError, match="timezone-aware"):
            asmt_key(timestamp=datetime(2024, 1, 5))


class TestArtifactKeyDelimiterResistance:
    """Canonical JSON, not delimiter-joined text: a value containing whatever
    separator a naive scheme would use cannot render like a different
    identity."""

    AWKWARD = [
        "trend@v1#abc", "a:b", "a|b", "a/b", "a\\b", 'a"b', "a,b", "{}", "[]",
        "münchen", "東京", "a\nb", " leading", "trailing ",
    ]

    @pytest.mark.parametrize("hypothesis_id", AWKWARD)
    def test_awkward_hypothesis_ids_are_distinct(self, hypothesis_id):
        assert obs_key(hypothesis_id=hypothesis_id) != obs_key(hypothesis_id="plain")
        assert is_key(obs_key(hypothesis_id=hypothesis_id))

    def test_moving_characters_across_fields_changes_the_key(self):
        """``id="a@v", fingerprint="1"`` vs ``id="a", fingerprint="@v1"`` render
        identically under naive ``id@vN#fp`` concatenation."""
        left = obs_key(hypothesis_id="a@v", hypothesis_fingerprint="1")
        right = obs_key(hypothesis_id="a", hypothesis_fingerprint="@v1")
        assert left != right

    def test_the_kind_field_cannot_be_forged_through_a_value(self):
        assert obs_key(hypothesis_id='","kind":"assessment') != asmt_key()

    def test_unicode_and_ascii_escapes_are_distinct(self):
        assert obs_key(hypothesis_id="münchen") != obs_key(hypothesis_id="m\\u00fcnchen")


class TestGoldenVectors:
    """Literal digests, pinned.

    Every other identity test checks a *relationship* (equal, different,
    sensitive to X) and would still pass if the payload quietly lost a field
    or the canonical form changed shape -- a mutation probe confirmed that
    removing ``kind`` and swapping canonical JSON for a delimiter join both
    survived the relational tests. A ledger key must be the same bytes
    forever, so these pin the bytes. If one of these changes, every stored
    key changes: bump ``scheme_version`` deliberately and re-pin, never
    "fix" the expected value.
    """

    OBSERVATION = "dc6da09c7cfeae5a730c5d7d1eb55f65f4ef268792683b9deffb60d2933ab6b7"
    ASSESSMENT = "d9d87d6885c560fff10bcd98521d589a73d8d6cc4e3a621fa23191c73f805a6e"
    OUTCOME = "b7198faed8c9e486bf1d8d40bab0bfdcd865a81d6d413f1295d1ea2eb0e0626c"
    BAR = "932857198f04ef67e7f752dd05c780252afcd14ed799c525283dc492947a12ed"
    BARS = "a859edec1a3ad94eb35442f2494fa67e4e0ab819e7ec39ec120bcc47dfa6da37"

    #: The exact bytes the observation vector is a SHA-256 of -- so the
    #: canonical form (sorted keys, no whitespace, ASCII, UTC ISO-8601,
    #: ``kind`` and ``scheme`` inside the payload) is readable here rather
    #: than reverse-engineered from a hash.
    OBSERVATION_BYTES = (
        b'{"basis":"raw","hypothesis_fingerprint":"0011223344556677",'
        b'"hypothesis_id":"trend_alignment","hypothesis_version":1,"interval":"1d",'
        b'"kind":"observation","scheme":"outcomes.artifact_key","scheme_version":1,'
        b'"symbol":"AAPL","timestamp":"2024-01-05T00:00:00+00:00"}'
    )

    def test_observation_artifact_key(self):
        assert obs_key() == self.OBSERVATION

    def test_observation_key_is_sha256_of_the_documented_bytes(self):
        import hashlib
        assert hashlib.sha256(self.OBSERVATION_BYTES).hexdigest() == self.OBSERVATION

    def test_assessment_artifact_key(self):
        assert asmt_key() == self.ASSESSMENT

    #: Non-ASCII input, so the ``ensure_ascii`` escaping (``m\\u00fcnchen``,
    #: ``\\u6771\\u4eac``) is pinned too: a canonical form that emitted raw
    #: UTF-8 would hash to different bytes.
    NON_ASCII = "958dd8840ed25f6929dc8a633157ba7081a0ee9645b1e8f63476ecacd6b5bc68"

    def test_non_ascii_identity_text_is_escaped_not_encoded(self):
        assert obs_key(hypothesis_id="m\u00fcnchen/\u6771\u4eac") == self.NON_ASCII

    def test_outcome_key(self):
        assert outcome_key(artifact_key=self.OBSERVATION, spec_fingerprint="0123456789abcdef",
                           evaluation_version=1) == self.OUTCOME

    def test_bar_fingerprint(self):
        assert bar_fingerprint(bar()) == self.BAR

    def test_bars_fingerprint(self):
        second = bar(timestamp=T0 + timedelta(days=1), open=0.1 + 0.2, source="alpaca")
        assert bars_fingerprint([bar(), second]) == self.BARS


class TestDelimiterJoinIsNotTheScheme:
    """For any single-character join, ``("a" + d + "b", "c")`` and
    ``("a", "b" + d + "c")`` render identically. Canonical JSON keeps the
    field boundary, so they never collide -- for every plausible delimiter."""

    @pytest.mark.parametrize("delimiter", ["|", ":", "/", "@", "#", ",", ";", " ", "\n", "\t", "\x00"])
    def test_values_that_straddle_a_field_boundary_never_collide(self, delimiter):
        left = obs_key(hypothesis_id=f"a{delimiter}b", hypothesis_fingerprint="c")
        right = obs_key(hypothesis_id="a", hypothesis_fingerprint=f"b{delimiter}c")
        assert left != right

    @pytest.mark.parametrize("delimiter", ["|", ":", "/", "@", "#", ","])
    def test_symbol_and_hypothesis_id_boundary_never_collides(self, delimiter):
        left = obs_key(symbol=f"A{delimiter}h", hypothesis_id="x")
        right = obs_key(symbol="A", hypothesis_id=f"h{delimiter}x")
        assert left != right


# -- outcome keys ------------------------------------------------------------------


class TestOutcomeKey:
    def test_full_sha256_hex(self):
        assert is_key(outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                                  evaluation_version=EVALUATION_VERSION))

    def test_deterministic(self):
        a = outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                        evaluation_version=1)
        b = outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                        evaluation_version=1)
        assert a == b

    def test_changes_with_artifact_key(self):
        assert outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                           evaluation_version=1) != \
            outcome_key(artifact_key=asmt_key(), spec_fingerprint="0123456789abcdef",
                        evaluation_version=1)

    def test_changes_with_spec_fingerprint(self):
        assert outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                           evaluation_version=1) != \
            outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdee",
                        evaluation_version=1)

    def test_changes_with_evaluation_version(self):
        """Keying on the version means a future measurement change produces
        new records beside the old, never over them."""
        assert outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                           evaluation_version=1) != \
            outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                        evaluation_version=2)

    def test_differs_from_its_own_artifact_key(self):
        assert outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                           evaluation_version=1) != obs_key()

    @pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "a" * 63, None, 1])
    def test_artifact_key_must_be_a_64_hex_key(self, bad):
        with pytest.raises(OutcomeTrackingError, match="artifact_key"):
            outcome_key(artifact_key=bad, spec_fingerprint="0123456789abcdef", evaluation_version=1)

    @pytest.mark.parametrize("bad", ["", "abc", "A" * 16, "a" * 64, None, 1])
    def test_spec_fingerprint_must_be_a_16_hex_fingerprint(self, bad):
        with pytest.raises(OutcomeTrackingError, match="spec_fingerprint"):
            outcome_key(artifact_key=obs_key(), spec_fingerprint=bad, evaluation_version=1)

    @pytest.mark.parametrize("bad", [0, -1, True, "1", 1.0, None])
    def test_evaluation_version_must_be_a_positive_int(self, bad):
        with pytest.raises(OutcomeTrackingError, match="evaluation_version"):
            outcome_key(artifact_key=obs_key(), spec_fingerprint="0123456789abcdef",
                        evaluation_version=bad)

    def test_result_facts_are_not_inputs(self):
        """The signature is the pin: prices, returns, states and clocks have
        no parameter to arrive through."""
        import inspect
        params = set(inspect.signature(outcome_key).parameters)
        assert params == {"artifact_key", "spec_fingerprint", "evaluation_version"}


# -- bar fingerprints ------------------------------------------------------------------


class TestBarFingerprint:
    def test_full_sha256_hex(self):
        assert is_key(bar_fingerprint(bar()))

    def test_deterministic(self):
        assert bar_fingerprint(bar()) == bar_fingerprint(bar())

    @pytest.mark.parametrize("field,value", [
        ("open", 100.01), ("high", 110.01), ("low", 94.99), ("close", 105.01),
        ("volume", 1_001.0), ("timestamp", T0 + timedelta(minutes=1)),
        ("symbol", "MSFT"), ("interval", "1wk"),
    ])
    def test_one_field_changes_it(self, field, value):
        assert bar_fingerprint(bar(**{field: value})) != bar_fingerprint(bar())

    def test_source_is_provenance_not_bar_content(self):
        """Which provider delivered the bar is tracked on the artifact as
        ``source``; the fingerprint answers 'are these the same numbers?'."""
        assert bar_fingerprint(bar(source="yfinance")) == bar_fingerprint(bar(source="alpaca"))

    def test_the_same_instant_in_another_zone_is_the_same_bar(self):
        plus_two = T0.astimezone(timezone(timedelta(hours=2)))
        assert bar_fingerprint(bar(timestamp=plus_two)) == bar_fingerprint(bar(timestamp=T0))

    def test_integer_and_float_prices_that_are_equal_fingerprint_equally(self):
        """``MarketBar`` coerces to float; the fingerprint sees the coerced
        value, so ``100`` and ``100.0`` are one bar."""
        assert bar_fingerprint(bar(open=100)) == bar_fingerprint(bar(open=100.0))

    def test_float_representation_is_shortest_round_trip(self):
        """0.1 + 0.2 is not 0.3 and the fingerprint must not pretend it is."""
        assert bar_fingerprint(bar(open=0.1 + 0.2)) != bar_fingerprint(bar(open=0.3))
        assert bar_fingerprint(bar(open=1e-7)) == bar_fingerprint(bar(open=0.0000001))

    def test_negative_zero_volume_is_zero_volume(self):
        assert bar_fingerprint(bar(volume=-0.0)) == bar_fingerprint(bar(volume=0.0))

    def test_requires_a_market_bar(self):
        with pytest.raises(OutcomeTrackingError, match="MarketBar"):
            bar_fingerprint({"open": 1.0})  # type: ignore[arg-type]


class TestBarsFingerprint:
    def test_full_sha256_hex(self):
        assert is_key(bars_fingerprint([bar()]))

    def test_deterministic_and_repeatable(self):
        bars = [bar(timestamp=T0 + timedelta(days=i), open=100.0 + i) for i in range(5)]
        first = bars_fingerprint(bars)
        assert all(bars_fingerprint(bars) == first for _ in range(3))
        assert bars_fingerprint(tuple(bars)) == first

    def test_one_bar_supported_and_differs_from_its_bar_fingerprint(self):
        single = bar()
        assert is_key(bars_fingerprint([single]))
        assert bars_fingerprint([single]) != bar_fingerprint(single)

    def test_order_sensitive(self):
        a, b = bar(timestamp=T0, open=100.0), bar(timestamp=T0 + timedelta(days=1), open=101.0)
        assert bars_fingerprint([a, b]) != bars_fingerprint([b, a])

    def test_one_changed_bar_changes_it(self):
        bars = [bar(timestamp=T0 + timedelta(days=i), open=100.0 + i) for i in range(5)]
        changed = list(bars)
        changed[2] = bar(timestamp=T0 + timedelta(days=2), open=102.0, close=105.5)
        assert bars_fingerprint(changed) != bars_fingerprint(bars)

    def test_length_matters(self):
        bars = [bar(timestamp=T0 + timedelta(days=i)) for i in range(3)]
        assert bars_fingerprint(bars) != bars_fingerprint(bars[:2])

    def test_empty_rejected(self):
        """A measurement consumed some bars; a fingerprint of none would let
        an outcome claim provenance it does not have."""
        with pytest.raises(OutcomeTrackingError, match="empty"):
            bars_fingerprint([])

    def test_non_bar_elements_rejected(self):
        with pytest.raises(OutcomeTrackingError, match="MarketBar"):
            bars_fingerprint([bar(), "not a bar"])  # type: ignore[list-item]

    def test_a_string_is_not_a_sequence_of_bars(self):
        with pytest.raises(OutcomeTrackingError):
            bars_fingerprint("bars")  # type: ignore[arg-type]


# -- cross-process determinism --------------------------------------------------------


SNIPPET = r"""
from datetime import datetime, timezone, timedelta
from src.data.models import Interval, MarketBar
from src.data.series import PriceBasis
from src.outcomes import (observation_artifact_key, assessment_artifact_key,
                          outcome_key, bar_fingerprint, bars_fingerprint)
T0 = datetime(2024, 1, 5, tzinfo=timezone.utc)
ok = observation_artifact_key(symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW,
                              timestamp=T0, hypothesis_id="trend@v1#x", hypothesis_version=1,
                              hypothesis_fingerprint="0011223344556677")
ak = assessment_artifact_key(symbol="AAPL", interval=Interval.DAY_1, basis=PriceBasis.RAW,
                             timestamp=T0, policy_fingerprint="fedcba9876543210")
b = MarketBar(symbol="AAPL", timestamp=T0, open=0.1 + 0.2, high=110.0, low=95.0,
              close=105.0, volume=1000.0, interval="1d", source="t")
c = MarketBar(symbol="AAPL", timestamp=T0 + timedelta(days=1), open=101.0, high=110.0,
              low=95.0, close=105.0, volume=1000.0, interval="1d", source="t")
print(ok, ak, outcome_key(artifact_key=ok, spec_fingerprint="0123456789abcdef",
                          evaluation_version=1), bar_fingerprint(b), bars_fingerprint([b, c]))
"""


def _keys_in_subprocess(seed: str) -> list[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(REPO)}
    completed = subprocess.run(
        [sys.executable, "-c", SNIPPET], cwd=REPO, env=env,
        capture_output=True, text=True, timeout=60, check=True,
    )
    return completed.stdout.split()


def test_keys_are_identical_under_different_hash_seeds():
    """SHA-256 over canonical bytes owes nothing to ``hash()``, dict insertion
    order, locale or object addresses. Two fresh interpreters with different
    ``PYTHONHASHSEED`` values must agree with each other and with this one."""
    here = [
        obs_key(hypothesis_id="trend@v1#x"),
        asmt_key(),
        outcome_key(artifact_key=obs_key(hypothesis_id="trend@v1#x"),
                    spec_fingerprint="0123456789abcdef", evaluation_version=1),
        bar_fingerprint(bar(open=0.1 + 0.2, source="t")),
        bars_fingerprint([bar(open=0.1 + 0.2, source="t"),
                          bar(timestamp=T0 + timedelta(days=1), open=101.0, source="t")]),
    ]
    assert _keys_in_subprocess("1") == here
    assert _keys_in_subprocess("4242") == here
