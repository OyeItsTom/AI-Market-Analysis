"""Hypothesis and feature identity: versioning, fingerprints, parameters."""

from __future__ import annotations

import subprocess
import sys

import pytest

from src.data.series import PriceBasis
from src.strategies import (
    FeatureSpec,
    HypothesisSpec,
    MomentumInTrendContext,
    ResearchHypothesis,
    ResearchState,
    SpecError,
    TrendAlignment,
    resolve_feature_spec,
)
from src.strategies.research import ReasonCode

RSI14 = FeatureSpec("rsi", {"period": 14, "field": "close"})
RSI7 = FeatureSpec("rsi", {"period": 7, "field": "close"})


class TestFeatureSpecIdentity:
    def test_canonical_key_includes_parameters(self):
        # Strings are quoted so they cannot render identically to another type.
        assert RSI14.key == "rsi(field='close',period=14)"

    def test_a_string_cannot_render_identically_to_a_bool(self):
        """Regression: ``True`` and ``"true"`` once produced the same key.

        Two materially different specifications sharing one canonical key is a
        canonicalization collision, and would give them one research identity.
        """
        assert FeatureSpec("x", {"p": True}).key != FeatureSpec("x", {"p": "true"}).key
        assert FeatureSpec("x", {"p": False}).key != FeatureSpec("x", {"p": "false"}).key

    def test_types_are_distinguishable_in_the_canonical_key(self):
        keys = {
            FeatureSpec("x", {"p": value}).key
            for value in (1, 1.0, True, "1", "1.0", "true")
        }
        assert len(keys) == 6, f"canonical keys collided: {sorted(keys)}"

    def test_different_periods_are_different_evidence(self):
        assert RSI14 != RSI7
        assert RSI14.key != RSI7.key

    def test_parameter_order_does_not_affect_identity(self):
        assert FeatureSpec("rsi", {"period": 14, "field": "close"}) == FeatureSpec(
            "rsi", {"field": "close", "period": 14}
        )

    def test_short_form_resolves_to_the_same_identity_as_the_full_form(self):
        # Otherwise the same computation would have two identities, and a spec
        # would never match the feature it describes.
        assert resolve_feature_spec(FeatureSpec("sma", {"period": 3})) == resolve_feature_spec(
            FeatureSpec("sma", {"period": 3, "field": "close"})
        )

    def test_matches_requires_every_parameter_to_agree(self):
        from src.features import rsi
        from tests.conftest import make_series

        feature = rsi(make_series([float(i) for i in range(1, 30)]), 14)
        assert RSI14.matches(feature) is True
        assert RSI7.matches(feature) is False

    def test_unsupported_parameter_types_are_rejected(self):
        with pytest.raises(SpecError, match="not a supported"):
            FeatureSpec("rsi", {"periods": [14, 7]}).key

    def test_empty_name_is_rejected(self):
        with pytest.raises(SpecError):
            FeatureSpec("  ")


class TestHypothesisIdentity:
    def _spec(self, **overrides):
        base = dict(
            hypothesis_id="demo",
            version=1,
            name="Demo",
            required_features=(RSI14,),
            required_basis=None,
        )
        base.update(overrides)
        return HypothesisSpec(**base)

    def test_id_and_version_are_stable_on_an_instance(self):
        hypothesis = TrendAlignment()
        assert hypothesis.spec.hypothesis_id == "trend_alignment"
        assert hypothesis.spec.version == 1
        assert hypothesis.spec is hypothesis.spec  # built once, never rebuilt

    def test_spec_is_immutable(self):
        spec = self._spec()
        with pytest.raises((AttributeError, TypeError)):
            spec.version = 2  # type: ignore[misc]

    def test_version_participates_in_identity(self):
        assert self._spec(version=1) != self._spec(version=2)
        assert self._spec(version=1).fingerprint != self._spec(version=2).fingerprint

    def test_v1_and_v2_are_different_hypotheses(self):
        assert self._spec(version=1).label != self._spec(version=2).label

    def test_parameters_participate_in_the_fingerprint(self):
        """The masquerade this exists to prevent.

        A v1 whose RSI period is quietly changed from 14 to 7 is a different
        research definition. If it kept the original fingerprint, every
        historical v1 result would be silently redefined.
        """
        original = self._spec(required_features=(RSI14,))
        tampered = self._spec(required_features=(RSI7,))
        assert original.hypothesis_id == tampered.hypothesis_id
        assert original.version == tampered.version
        assert original.fingerprint != tampered.fingerprint
        assert original.label != tampered.label

    def test_required_basis_participates_in_the_fingerprint(self):
        assert self._spec(required_basis=None).fingerprint != self._spec(
            required_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED
        ).fingerprint

    def test_feature_order_does_not_change_the_fingerprint(self):
        sma = FeatureSpec("sma", {"period": 20, "field": "close"})
        assert self._spec(required_features=(RSI14, sma)).fingerprint == self._spec(
            required_features=(sma, RSI14)
        ).fingerprint

    def test_canonical_form_is_human_readable(self):
        assert "demo|v1|" in self._spec().canonical_form

    def test_fingerprint_is_deterministic_across_processes(self):
        """Must not depend on PYTHONHASHSEED.

        Python's built-in hash() is randomised per process; using it for a
        persistent research identity would give a different answer on every
        run and every machine.
        """
        code = (
            "from src.strategies import FeatureSpec, HypothesisSpec;"
            "print(HypothesisSpec('demo', 1, 'Demo',"
            "(FeatureSpec('rsi', {'period': 14, 'field': 'close'}),)).fingerprint)"
        )
        results = set()
        for seed in ("0", "1", "12345"):
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                cwd=".",
            )
            results.add(proc.stdout.strip())
        assert len(results) == 1, f"fingerprint varied across processes: {results}"

    def test_two_versions_can_coexist(self):
        class DemoV1(ResearchHypothesis):
            hypothesis_id = "demo"; version = 1; display_name = "Demo"
            required_features = (RSI14,)
            def _classify(self, values):
                return ResearchState.NEUTRAL, (ReasonCode.MOMENTUM_MIDRANGE,)

        class DemoV2(DemoV1):
            version = 2

        v1, v2 = DemoV1(), DemoV2()
        assert v1.spec.hypothesis_id == v2.spec.hypothesis_id
        assert v1.fingerprint != v2.fingerprint
        assert {v1.label, v2.label} == {v1.label, v2.label}
        assert len({v1.label, v2.label}) == 2


class TestConfigurationParticipatesInIdentity:
    """Regression: thresholds read by _classify once bypassed the fingerprint.

    Two hypotheses sharing id, version, features and lookback but differing in
    a dead-band classified differently on 41 of 90 bars while presenting the
    identical persistent identity.
    """

    def _spec(self, **parameters):
        return HypothesisSpec("demo", 1, "Demo", (RSI14,), None, 0, parameters)

    def test_a_declared_parameter_changes_the_fingerprint(self):
        assert self._spec(margin=0.001).fingerprint != self._spec(margin=0.25).fingerprint

    def test_parameter_order_does_not_change_the_fingerprint(self):
        assert HypothesisSpec(
            "demo", 1, "D", (RSI14,), None, 0, {"a": 1, "b": 2}
        ).fingerprint == HypothesisSpec(
            "demo", 1, "D", (RSI14,), None, 0, {"b": 2, "a": 1}
        ).fingerprint

    def test_parameters_appear_in_the_canonical_form(self):
        assert "margin=0.001" in self._spec(margin=0.001).canonical_form

    def test_an_undeclared_parameter_lookup_fails_loudly(self):
        with pytest.raises(SpecError, match="not declared"):
            self._spec(margin=0.1).parameter("missing")

    def test_undeclared_configuration_is_refused_at_construction(self):
        """The guard that makes this impossible to forget."""

        class Sloppy(ResearchHypothesis):
            hypothesis_id = "sloppy"; version = 1; display_name = "Sloppy"
            required_features = (RSI14,)
            threshold = 55.0  # configuration, not declared in `parameters`

            def _classify(self, values):
                return ResearchState.NEUTRAL, (ReasonCode.MOMENTUM_MIDRANGE,)

        with pytest.raises(SpecError, match="not declared in `parameters`"):
            Sloppy()

    def test_declaring_it_makes_the_hypothesis_constructible(self):
        class Tidy(ResearchHypothesis):
            hypothesis_id = "tidy"; version = 1; display_name = "Tidy"
            required_features = (RSI14,)
            parameters = {"threshold": 55.0}

            def _classify(self, values):
                return ResearchState.NEUTRAL, (ReasonCode.MOMENTUM_MIDRANGE,)

        assert Tidy().spec.parameter("threshold") == 55.0

    def test_feature_spec_class_constants_are_not_mistaken_for_configuration(self):
        # FeatureSpec attributes are already covered by required_features.
        assert TrendAlignment().fingerprint  # constructs without complaint

    @pytest.mark.parametrize(
        "factory", [TrendAlignment, MomentumInTrendContext]
    )
    def test_shipped_hypotheses_declare_their_thresholds(self, factory):
        assert dict(factory().spec.parameters), f"{factory.__name__} declares no parameters"

    def test_a_retuned_shipped_hypothesis_cannot_keep_its_identity(self):
        class Retuned(TrendAlignment):
            parameters = {"margin": 0.25}

        assert Retuned().hypothesis_id == TrendAlignment().hypothesis_id
        assert Retuned().spec.version == TrendAlignment().spec.version
        assert Retuned().fingerprint != TrendAlignment().fingerprint


class TestSpecValidation:
    def test_a_hypothesis_must_declare_its_features(self):
        with pytest.raises(SpecError, match="must declare"):
            HypothesisSpec("demo", 1, "Demo", ())

    def test_duplicate_required_features_are_rejected(self):
        with pytest.raises(SpecError, match="duplicate"):
            HypothesisSpec("demo", 1, "Demo", (RSI14, RSI14))

    @pytest.mark.parametrize("version", [0, -1, 1.5, "1", True])
    def test_invalid_versions_are_rejected(self, version):
        with pytest.raises(SpecError):
            HypothesisSpec("demo", version, "Demo", (RSI14,))

    def test_empty_id_or_name_is_rejected(self):
        with pytest.raises(SpecError):
            HypothesisSpec("  ", 1, "Demo", (RSI14,))
        with pytest.raises(SpecError):
            HypothesisSpec("demo", 1, "  ", (RSI14,))

    def test_required_features_must_be_specs(self):
        with pytest.raises(SpecError, match="FeatureSpec"):
            HypothesisSpec("demo", 1, "Demo", ("rsi",))


class TestShippedHypotheses:
    @pytest.mark.parametrize("factory", [TrendAlignment, MomentumInTrendContext])
    def test_they_declare_stable_identity(self, factory):
        first, second = factory(), factory()
        assert first.fingerprint == second.fingerprint
        assert first.label == second.label

    def test_the_two_examples_are_distinguishable(self):
        assert TrendAlignment().fingerprint != MomentumInTrendContext().fingerprint

    @pytest.mark.parametrize("factory", [TrendAlignment, MomentumInTrendContext])
    def test_required_features_are_fully_resolved(self, factory):
        for spec in factory().spec.required_features:
            assert spec == resolve_feature_spec(spec)
