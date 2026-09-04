"""OutcomeSpec: identity, canonicalization and horizon arithmetic."""

from __future__ import annotations

import subprocess
import sys

import pytest

from src.data.series import PriceBasis
from src.evaluation import (
    OutcomeError,
    OutcomeSpec,
    OutcomeType,
    PriceField,
    ReferenceConvention,
)


class TestIdentity:
    def _spec(self, **overrides):
        base = dict(
            outcome_type=OutcomeType.FORWARD_RETURN,
            horizon_bars=5,
            reference=ReferenceConvention.NEXT_BAR_OPEN,
            future_field=PriceField.CLOSE,
            required_basis=PriceBasis.RAW,
        )
        base.update(overrides)
        return OutcomeSpec(**base)

    def test_identical_specs_share_a_fingerprint(self):
        assert self._spec().fingerprint == self._spec().fingerprint

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("horizon_bars", 20),
            ("future_field", PriceField.OPEN),
            ("required_basis", PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED),
        ],
    )
    def test_every_material_field_changes_identity(self, field, value):
        assert self._spec().fingerprint != self._spec(**{field: value}).fingerprint

    def test_horizon_5_and_20_are_different_evaluations(self):
        """Changing the horizon must not masquerade as the same definition."""
        assert self._spec(horizon_bars=5).fingerprint != self._spec(
            horizon_bars=20
        ).fingerprint

    def test_the_canonical_form_names_every_field(self):
        form = self._spec().canonical_form
        for token in ("type=", "horizon_bars=", "reference=", "future_field=", "basis="):
            assert token in form

    def test_types_are_distinguishable_in_the_canonical_form(self):
        # An enum and a string with the same text must not collide.
        form = self._spec(future_field=PriceField.CLOSE).canonical_form
        assert "PriceField:close" in form

    def test_fingerprint_is_deterministic_across_processes(self):
        code = (
            "from src.evaluation import OutcomeSpec;"
            "print(OutcomeSpec(horizon_bars=5).fingerprint)"
        )
        results = set()
        for seed in ("0", "1", "12345"):
            proc = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}, cwd=".",
            )
            results.add(proc.stdout.strip())
        assert len(results) == 1, f"fingerprint varied across processes: {results}"

    def test_the_spec_is_immutable(self):
        spec = self._spec()
        with pytest.raises((AttributeError, TypeError)):
            spec.horizon_bars = 99  # type: ignore[misc]


class TestHorizonArithmetic:
    """The reference bar counts as bar one of the horizon."""

    @pytest.mark.parametrize(("horizon", "offset"), [(1, 0), (2, 1), (5, 4), (20, 19)])
    def test_future_offset_is_horizon_minus_one(self, horizon, offset):
        assert OutcomeSpec(horizon_bars=horizon).future_offset() == offset

    def test_horizon_one_ends_on_the_reference_bar(self):
        assert OutcomeSpec(horizon_bars=1).future_offset() == 0

    @pytest.mark.parametrize("horizon", [0, -1, 1.5, "5", True])
    def test_invalid_horizons_are_rejected(self, horizon):
        with pytest.raises(OutcomeError):
            OutcomeSpec(horizon_bars=horizon)

    def test_the_description_states_the_counting_convention(self):
        description = OutcomeSpec(horizon_bars=5).describe()
        assert "counting the reference bar as bar 1" in description


class TestDefaults:
    def test_defaults_are_the_documented_conventions(self):
        spec = OutcomeSpec()
        assert spec.outcome_type is OutcomeType.FORWARD_RETURN
        assert spec.reference is ReferenceConvention.NEXT_BAR_OPEN
        assert spec.future_field is PriceField.CLOSE
        assert spec.required_basis is PriceBasis.RAW
        assert spec.horizon_bars == 1
