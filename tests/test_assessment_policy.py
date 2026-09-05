"""Assessment policy: structure, validation, and deterministic identity."""

import ast
import dataclasses
import itertools
import json
import pathlib
import subprocess
import sys

import pytest

from src.assessments import (
    AssessmentAggregationRule,
    AssessmentPolicy,
    HypothesisIdentity,
    PolicyError,
)
# A white-box helper, deliberately not part of the package's public surface:
# callers never need it to build or use an assessment.
from src.assessments.policy import canonical_bytes

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def ident(hid="trend_alignment", version=1, fingerprint="abc123"):
    return HypothesisIdentity(hid, version, fingerprint)


def policy(*identities, minimum=1, rule="directional_presence_v1"):
    identities = identities or (ident(),)
    return AssessmentPolicy(tuple(identities), minimum, rule)


class TestHypothesisIdentity:
    def test_a_valid_identity(self):
        entry = ident()
        assert entry.hypothesis_id == "trend_alignment"
        assert entry.version == 1
        assert entry.label == "trend_alignment@v1#abc123"

    @pytest.mark.parametrize("bad", ["", "   ", None, 5, b"x", 1.5])
    def test_malformed_hypothesis_id_is_refused(self, bad):
        with pytest.raises(PolicyError, match="hypothesis_id"):
            HypothesisIdentity(bad, 1, "abc")

    @pytest.mark.parametrize("bad", ["", "   ", None, 5, b"x"])
    def test_malformed_fingerprint_is_refused(self, bad):
        with pytest.raises(PolicyError, match="fingerprint"):
            HypothesisIdentity("h", 1, bad)

    @pytest.mark.parametrize("bad", [0, -1, -99])
    def test_version_below_one_is_refused(self, bad):
        with pytest.raises(PolicyError, match="version must be >= 1"):
            HypothesisIdentity("h", bad, "abc")

    @pytest.mark.parametrize("bad", [True, False])
    def test_bool_version_is_refused(self, bad):
        """isinstance(True, int) is True, so True would silently become v1."""
        with pytest.raises(PolicyError, match="got bool"):
            HypothesisIdentity("h", bad, "abc")

    @pytest.mark.parametrize("bad", [1.0, "1", None, [1]])
    def test_non_int_version_is_refused(self, bad):
        with pytest.raises(PolicyError, match="version must be an int"):
            HypothesisIdentity("h", bad, "abc")

    def test_it_is_frozen(self):
        with pytest.raises(Exception):
            ident().hypothesis_id = "other"


class TestAggregationRule:
    def test_exactly_one_member_exists(self):
        """Pinned deliberately. Adding a member must be a conscious act that
        fails this test and forces the versioning question to be asked."""
        assert [member.name for member in AssessmentAggregationRule] == [
            "DIRECTIONAL_PRESENCE_V1"
        ]
        assert (
            AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1.value
            == "directional_presence_v1"
        )

    def test_a_valid_bare_string_normalises(self):
        """Matches the repository's enum-coercion convention."""
        pol = policy(rule="directional_presence_v1")
        assert pol.aggregation_rule is AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1

    @pytest.mark.parametrize(
        "bad",
        [
            "plurality",
            "v1",
            "DIRECTIONAL_PRESENCE_V1",
            "",
            "directional_presence_v2",
            "majority",
        ],
    )
    def test_arbitrary_rule_strings_are_refused(self, bad):
        with pytest.raises(PolicyError, match="unknown aggregation_rule"):
            policy(rule=bad)

    @pytest.mark.parametrize("bad", [None, 1, True, 2.0, ["x"]])
    def test_non_rule_values_are_refused(self, bad):
        with pytest.raises(PolicyError):
            policy(rule=bad)

    def test_the_rule_is_required(self):
        with pytest.raises(TypeError):
            AssessmentPolicy((ident(),), 1)


class TestPolicyValidation:
    def test_a_valid_single_hypothesis_policy(self):
        pol = policy(minimum=1)
        assert len(pol.hypotheses) == 1
        assert pol.minimum_sufficient_observations == 1

    def test_a_valid_multi_hypothesis_policy(self):
        pol = policy(ident("a"), ident("b"), ident("c"), minimum=2)
        assert len(pol.hypotheses) == 3

    def test_an_empty_ensemble_is_refused(self):
        with pytest.raises(PolicyError, match="must not be empty"):
            AssessmentPolicy((), 1, "directional_presence_v1")

    def test_a_duplicate_identity_is_refused(self):
        with pytest.raises(PolicyError, match="duplicate hypothesis identity"):
            policy(ident("a"), ident("a"))

    def test_same_id_and_version_but_different_fingerprint_is_not_a_duplicate(self):
        pol = policy(ident("a", 1, "fp1"), ident("a", 1, "fp2"))
        assert len(pol.hypotheses) == 2

    @pytest.mark.parametrize("bad", ["x", ["a"], 5, None])
    def test_a_non_identity_member_is_refused(self, bad):
        with pytest.raises(PolicyError, match="HypothesisIdentity"):
            AssessmentPolicy((bad,), 1, "directional_presence_v1")

    @pytest.mark.parametrize("bad", [0, -1, -50])
    def test_minimum_below_one_is_refused(self, bad):
        with pytest.raises(PolicyError, match="must be >= 1"):
            policy(minimum=bad)

    @pytest.mark.parametrize("bad", [True, False])
    def test_bool_minimum_is_refused(self, bad):
        with pytest.raises(PolicyError, match="got bool"):
            policy(minimum=bad)

    @pytest.mark.parametrize("bad", [1.0, "2", None, [1]])
    def test_non_int_minimum_is_refused(self, bad):
        with pytest.raises(PolicyError, match="must be an int"):
            policy(minimum=bad)

    def test_a_minimum_above_the_ensemble_size_is_refused(self):
        """Unsatisfiable: that policy could never produce a sufficient assessment."""
        with pytest.raises(PolicyError, match="exceeds the ensemble size"):
            policy(ident("a"), ident("b"), minimum=3)

    def test_minimum_exactly_one_is_accepted(self):
        assert policy(ident("a"), ident("b"), minimum=1).minimum_sufficient_observations == 1

    def test_minimum_exactly_the_ensemble_size_is_accepted(self):
        assert policy(ident("a"), ident("b"), minimum=2).minimum_sufficient_observations == 2

    def test_nothing_is_silently_clamped(self):
        for bad in (0, 99):
            with pytest.raises(PolicyError):
                policy(ident("a"), ident("b"), minimum=bad)

    def test_the_policy_is_frozen(self):
        with pytest.raises(Exception):
            policy().minimum_sufficient_observations = 2

    def test_a_caller_list_is_copied_defensively(self):
        entries = [ident("a"), ident("b")]
        pol = AssessmentPolicy(entries, 1, "directional_presence_v1")
        entries.append(ident("c"))
        assert len(pol.hypotheses) == 2
        assert isinstance(pol.hypotheses, tuple)


class TestPolicyFingerprint:
    def test_it_is_sixteen_lowercase_hex_characters(self):
        fingerprint = policy().fingerprint
        assert len(fingerprint) == 16
        assert all(char in "0123456789abcdef" for char in fingerprint)

    def test_the_same_semantic_policy_agrees(self):
        assert (
            policy(ident("a"), ident("b"), minimum=2).fingerprint
            == policy(ident("a"), ident("b"), minimum=2).fingerprint
        )

    def test_ensemble_permutation_does_not_change_identity(self):
        a, b, c = ident("a"), ident("b"), ident("c")
        fingerprints = {
            AssessmentPolicy(order, 2, "directional_presence_v1").fingerprint
            for order in itertools.permutations((a, b, c))
        }
        assert len(fingerprints) == 1

    def test_changing_a_hypothesis_id_changes_identity(self):
        assert policy(ident("a")).fingerprint != policy(ident("z")).fingerprint

    def test_changing_a_version_changes_identity(self):
        assert policy(ident("a", 1)).fingerprint != policy(ident("a", 2)).fingerprint

    def test_changing_a_hypothesis_fingerprint_changes_identity(self):
        assert (
            policy(ident("a", 1, "fp1")).fingerprint
            != policy(ident("a", 1, "fp2")).fingerprint
        )

    def test_changing_the_minimum_changes_identity(self):
        one = policy(ident("a"), ident("b"), minimum=1)
        two = policy(ident("a"), ident("b"), minimum=2)
        assert one.fingerprint != two.fingerprint

    def test_the_aggregation_rule_appears_in_the_canonical_form(self):
        """The amendment's core requirement: aggregation semantics are part of
        policy identity, so a future rule cannot masquerade as this one."""
        assert "directional_presence_v1" in policy().canonical_form
        assert "aggregation_rule" in policy().canonical_form

    def test_the_ensemble_and_minimum_appear_in_the_canonical_form(self):
        form = policy(ident("trend_alignment", 3, "ff00"), minimum=1).canonical_form
        assert "trend_alignment" in form and "ff00" in form
        assert "minimum_sufficient_observations" in form

    def test_the_fingerprint_is_deterministic_across_hash_seeds(self):
        """Python's hash() is PYTHONHASHSEED-randomised; identity must not be."""
        script = (
            "from src.assessments import AssessmentPolicy, HypothesisIdentity;"
            "print(AssessmentPolicy((HypothesisIdentity('b',2,'z'),"
            "HypothesisIdentity('a',1,'y')),2,'directional_presence_v1').fingerprint)"
        )
        seen = set()
        for seed in ("0", "1", "12345"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0, result.stderr
            seen.add(result.stdout.strip())
        assert len(seen) == 1


class TestCanonicalEncodingIsUnambiguous:
    """Identity strings are caller-supplied and may contain any character.

    A delimiter-joined canonical form (``id@vN#fp|id@vN#fp``) would let a
    hypothesis_id containing ``@`` or ``#`` render identically to a different
    ensemble -- two genuinely different policies sharing one fingerprint. JSON
    quotes and escapes every string, so no input can forge structure.
    """

    HOSTILE = [
        "a|b",
        "a@b",
        "a#b",
        "a;b",
        "a=b",
        "a:b",
        "a,b",
        'a"b',
        "a\\b",
        "a'b",
        "a\nb",
        "a\tb",
        "a@v1#b",
        "trend@v1#fp1|momentum@v1#fp2",
        "é中文",
        "\U0001f600",
        "a b",
        "  a  ",
        "[]{}",
        "null",
    ]

    @pytest.mark.parametrize("hostile", HOSTILE)
    def test_hostile_identity_strings_are_accepted_and_encoded_safely(self, hostile):
        """Accepted, not banned: refusing delimiters would push an encoding
        problem onto callers. The encoding is what must be unambiguous."""
        pol = policy(ident(hostile, 1, "fp"))
        other = policy(ident("plain", 1, "fp"))
        assert pol.fingerprint != other.fingerprint
        json.loads(pol.canonical_form)  # still structurally valid JSON

    def test_every_hostile_string_yields_a_distinct_identity(self):
        fingerprints = {policy(ident(h, 1, "fp")).fingerprint for h in self.HOSTILE}
        assert len(fingerprints) == len(self.HOSTILE)

    def test_a_delimiter_forgery_cannot_collide(self):
        """The classic attack: one id impersonating a two-hypothesis ensemble."""
        forged = policy(ident("a@v1#x|b", 1, "y"))
        genuine = policy(ident("a", 1, "x"), ident("b", 1, "y"))
        assert forged.canonical_form != genuine.canonical_form
        assert forged.fingerprint != genuine.fingerprint

    def test_prefix_and_suffix_ambiguity_cannot_collide(self):
        assert (
            policy(ident("ab", 1, "c")).fingerprint
            != policy(ident("a", 1, "bc")).fingerprint
        )

    def test_field_values_cannot_swap_positions(self):
        assert policy(ident("x", 1, "y")).fingerprint != policy(ident("y", 1, "x")).fingerprint

    def test_unicode_encoding_is_pinned_not_locale_dependent(self):
        raw = canonical_bytes({"k": "é中"})
        raw.decode("ascii")  # ensure_ascii=True -> pure ASCII bytes
        assert b"\\u00e9" in raw

    def test_mapping_key_order_does_not_affect_bytes(self):
        assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})

    def test_list_order_is_preserved(self):
        """Order-independence comes from sorting before encoding, not from the
        encoder silently reordering sequences."""
        assert canonical_bytes([1, 2]) != canonical_bytes([2, 1])

    def test_no_insignificant_whitespace(self):
        assert b" " not in canonical_bytes({"a": 1, "b": [1, 2]})

    def test_non_finite_floats_are_refused(self):
        """NaN/Infinity are not valid JSON and would not be portable."""
        with pytest.raises(ValueError):
            canonical_bytes({"x": float("nan")})

    def test_two_ensembles_differing_only_in_size_differ(self):
        assert policy(ident("a")).fingerprint != policy(ident("a"), ident("b")).fingerprint


class TestNoDeadConfiguration:
    """conflict_mode was rejected: a switch with one position is not a choice.

    aggregation_rule is the opposite -- it offers no choice but changes the
    fingerprint whenever semantics change. Identity, not configuration.
    """

    def _code_names(self):
        names = set()
        for path in sorted(pathlib.Path("src/assessments").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.arg):
                    names.add(node.arg)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.add(node.name)
        return names

    @pytest.mark.parametrize(
        "forbidden", ["conflict_mode", "voting_mode", "aggregation_mode", "weights", "weight"]
    )
    def test_no_configuration_knobs_exist(self, forbidden):
        assert forbidden not in self._code_names()

    def test_the_policy_has_exactly_three_material_fields(self):
        assert [f.name for f in dataclasses.fields(AssessmentPolicy)] == [
            "hypotheses",
            "minimum_sufficient_observations",
            "aggregation_rule",
        ]

    def test_no_field_carries_a_default(self):
        """Material semantics must be stated, following RiskPolicy's precedent."""
        for field in dataclasses.fields(AssessmentPolicy):
            assert field.default is dataclasses.MISSING
            assert field.default_factory is dataclasses.MISSING

    def test_the_encoder_is_not_part_of_the_public_package_api(self):
        """``canonical_bytes`` is an implementation detail of policy identity.

        Nothing outside ``policy.py`` needs it to construct, use or evaluate an
        assessment, so it is not re-exported. Keeping it out of the package
        surface means the encoding can change without being a breaking change.
        """
        import src.assessments as package

        assert "canonical_bytes" not in package.__all__
        assert not hasattr(package, "canonical_bytes")
