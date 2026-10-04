"""FUTURE_VALIDATION_V1 runner: blind status, one-open run, crash completion, snapshots, locks.

Every root here is a temporary copy of a root collected through the unchanged
Prospective Collection v1 path (fake session provider, injected clocks). The
autouse firewall fails any test that reaches the network or creates
``data/prospective``.
"""

from __future__ import annotations

import io
import os
from datetime import date, timedelta, timezone

import pytest

import src.application.future_validation as runner
from src.application.future_validation import run, status
from src.application.prospective import collect, health
from src.cli.future_validation import main
from src.future_validation import (
    REPORT_NAME,
    RESULT_NAME,
    UNLOCK_NAME,
    ArtifactExists,
    ValidationArtifacts,
)
from src.prospective import ProspectiveStore
from src.research.future_validation import FUTURE_VALIDATION_V1
from src.research.future_validation_engine import (
    add_calendar_months,
    canonical_bytes,
    decode_canonical,
    render_report,
    sha256_hex,
)
from tests.future_validation_fixtures import (  # noqa: F401 - autouse firewall
    ACTIVATED_AT,
    AFTER_E1,
    AFTER_F,
    EVIDENCE_THROUGH,
    collect_sessions,
    copy_root,
    future_validation_firewall,
    root_templates,
    small_definition,
)
from tests.prospective_fixtures import (
    SPY_ONLY,
    Clock,
    ProbeDouble,
    SessionProvider,
    et,
    weekday_mornings,
)

SMALL = small_definition()


def store_of(root_templates, tmp_path, name="matured") -> ProspectiveStore:
    return ProspectiveStore(copy_root(root_templates, name, tmp_path))


def call_status(store, definition=SMALL, pinned=None):
    """Status takes no clock at all: E1 and F run on the evidence clock."""
    return status(store, definition=definition,
                  pinned_fingerprint=definition.fingerprint if pinned is None else pinned,
                  collection=SPY_ONLY)


def call_run(store, at=AFTER_E1, definition=SMALL, pinned=None, repository="probe"):
    return run(store, definition=definition,
               pinned_fingerprint=definition.fingerprint if pinned is None else pinned,
               collection=SPY_ONLY, now=lambda: at,
               repository=ProbeDouble() if repository == "probe" else repository)


def artifacts(store, definition=SMALL) -> ValidationArtifacts:
    return ValidationArtifacts(store.root, definition.validation_id, definition.fingerprint)


#: E1 two months after activation: the collected roots' one month of evidence never meets it.
NOT_YET = small_definition(stop_rule_minimum_calendar_months=2)


def files(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in sorted(path.rglob("*")) if p.is_file()}


def edit_unlock_and_repoint(written: ValidationArtifacts, edit) -> bytes:
    """Edit unlock.json canonically, point result.json at it, delete report.md."""
    unlock = decode_canonical(written.read(UNLOCK_NAME), "unlock")
    edit(unlock)
    os.chmod(written.path(UNLOCK_NAME), 0o644)
    written.path(UNLOCK_NAME).write_bytes(canonical_bytes(unlock))
    result = decode_canonical(written.read(RESULT_NAME), "result")
    result["unlock"]["sha256"] = sha256_hex(written.read(UNLOCK_NAME))
    for name in ("activated_at", "host_recorded_at"):
        result["unlock"][name] = unlock[name]
    os.chmod(written.path(RESULT_NAME), 0o644)
    written.path(RESULT_NAME).write_bytes(canonical_bytes(result))
    os.unlink(written.path(REPORT_NAME))
    return written.read(RESULT_NAME)


#: R-N1: unlock fields that are a function of the frozen snapshot; any edit must refuse.
DETERMINISTIC_UNLOCK_EDITS = {
    "activated_at": lambda u: u.__setitem__("activated_at", "2020-01-01T00:00:00+00:00"),
    "activation_manifest_sha256": lambda u: u.__setitem__("activation_manifest_sha256",
                                                          "0" * 64),
    "collection_fingerprint": lambda u: u.__setitem__("collection_fingerprint", "a" * 64),
    "provenance_policy_fingerprint": lambda u: u.__setitem__("provenance_policy_fingerprint",
                                                             "b" * 64),
    "runner_version": lambda u: u.__setitem__("runner_version", 2),
    "provenance_count": lambda u: u["provenance"].__setitem__("claims_checked", 1),
    "provenance_exclusions": lambda u: u["provenance"].__setitem__("excluded_artifact_keys", 3),
    "provenance_status": lambda u: u["provenance"].__setitem__("status", "degraded"),
    "stop_rule": lambda u: u["stop_rule"].__setitem__("evidence_through",
                                                      "2031-01-01T00:00:00+00:00"),
    "cutoff": lambda u: u["cutoffs"].__setitem__("SPY", "2026-10-07T04:00:00+00:00"),
}


def _pop(mapping, key):
    del mapping[key]


#: R-N2: canonical JSON of the wrong shape; each must refuse cleanly.
MALFORMED_RESULTS = {
    "unlock_list": lambda r: r.__setitem__("unlock", []),
    "unlock_null": lambda r: r.__setitem__("unlock", None),
    "unlock_string": lambda r: r.__setitem__("unlock", "unlock"),
    "unlock_missing": lambda r: _pop(r, "unlock"),
    "unlock_sha_number": lambda r: r["unlock"].__setitem__("sha256", 1),
    "categories_mapping": lambda r: r.__setitem__("categories", {"SPY": "mixed"}),
    "category_item_string": lambda r: r.__setitem__("categories", ["SPY"]),
    "category_item_number": lambda r: r.__setitem__("categories", [[1, "mixed"]]),
    "category_item_arity": lambda r: r.__setitem__("categories", [["SPY", "mixed", "x"]]),
    "primary_string": lambda r: r.__setitem__("primary", "SPY"),
    "primary_row_list": lambda r: r.__setitem__("primary", [[]]),
    "primary_category_number": lambda r: r["primary"][0].__setitem__("category", 5),
    "cutoffs_list": lambda r: r.__setitem__("cutoffs", []),
    "cutoff_number": lambda r: r["primary"][0].__setitem__("cutoff", 5),
    "coverage_mapping": lambda r: r["secondary"]["G_coverage"].__setitem__("rows", {}),
    "coverage_string": lambda r: r["secondary"].__setitem__("G_coverage", "coverage"),
}


# -- status ---------------------------------------------------------------------------------------


class TestStatus:
    def test_not_activated_root_creates_nothing(self, tmp_path):
        store = ProspectiveStore(tmp_path / "absent" / "v1")
        report = call_status(store)
        assert report.activation == "not_activated" and not report.unlockable
        assert not (tmp_path / "absent").exists()

    def test_the_default_live_root_is_never_created(self):
        report = status()
        assert report.activation == "not_activated"
        outcome = run(now=lambda: AFTER_E1)
        assert outcome.outcome == "refused" and outcome.detail == ("not_activated",)

    def test_before_e1_on_the_evidence_clock_the_stop_rule_is_not_met(
            self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        report = call_status(store, definition=NOT_YET)
        assert (report.activation, report.validity, report.provenance_status) == (
            "activated", "ok", "ok")
        assert report.e1_met is False and report.e2_met is True and not report.unlockable
        assert report.evidence_through == EVIDENCE_THROUGH
        assert report.e1_due == add_calendar_months(ACTIVATED_AT, 2)
        assert dict(report.e2_counts)["SPY"] == 24 - 20

    def test_after_e1_the_root_is_unlockable(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        report = call_status(store)
        assert report.e1_met and report.e2_met and report.unlockable
        assert not report.unlock_exists and not report.result_exists

    def test_status_writes_nothing(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        before = files(store.root)
        call_status(store)
        assert files(store.root) == before

    def test_status_never_reaches_level_three(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)

        def forbidden(*args, **kwargs):
            raise AssertionError("status read Level-3 evidence")

        monkeypatch.setattr(runner, "_level_three_evidence", forbidden)
        monkeypatch.setattr(runner, "build_result", forbidden)
        report = call_status(store)
        assert report.unlockable

    def test_status_fields_are_level_one(self):
        names = set(runner.StatusReport.__dataclass_fields__)
        for forbidden in ("state", "states", "return", "returns", "mean", "median", "sign",
                          "episodes", "episode_count", "category", "categories", "cutoffs",
                          "price"):
            assert forbidden not in names
        assert {"e1_met", "e2_counts", "e2_met", "f_met", "unlockable", "result_exists",
                "provenance_status", "validity"} <= names

    def test_a_definition_mismatch_is_reported(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        report = call_status(store, pinned="0" * 64)
        assert report.definition_identity == "mismatch"
        assert report.validity == "invalid" and not report.unlockable

    def test_the_frozen_definition_on_the_spy_only_root_is_an_identity_mismatch(
            self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        report = status(store)  # FUTURE_VALIDATION_V1 vs COLLECTION_V1
        assert report.validity == "invalid"
        assert "manifest_collection_fingerprint" in report.identity_mismatches


# -- run --------------------------------------------------------------------------------------------


class TestRun:
    def test_refused_before_the_stop_rule_writes_nothing(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        before = files(store.root)
        outcome = call_run(store, at=et(2036, 1, 4, 12), definition=NOT_YET)
        assert (outcome.outcome, outcome.detail) == ("refused", ("not_unlockable",))
        assert not outcome.categories
        assert files(store.root) == before
        assert not (store.root / "validation").exists()

    def test_one_run_writes_unlock_result_and_report_once(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        outcome = call_run(store)
        assert outcome.outcome == "complete" and outcome.categories == (("SPY", "mixed"),)
        written = artifacts(store)
        for name in (UNLOCK_NAME, RESULT_NAME, REPORT_NAME):
            assert written.exists(name)
        result = decode_canonical(written.read(RESULT_NAME), "result")
        assert written.read(REPORT_NAME) == render_report(result).encode()
        assert sorted(p.name for p in written.directory.iterdir()) == sorted(
            [UNLOCK_NAME, RESULT_NAME, REPORT_NAME])  # no temporary file left behind
        report = call_status(store)
        assert report.unlock_exists and report.result_exists

    def test_unlock_records_the_snapshot_and_no_research_value(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        raw = artifacts(store).read(UNLOCK_NAME)
        unlock = decode_canonical(raw, "unlock")
        assert set(unlock) == runner.UNLOCK_FIELDS
        assert unlock["validation_fingerprint"] == SMALL.fingerprint
        assert unlock["collection_fingerprint"] == SPY_ONLY.fingerprint
        assert unlock["stop_rule"]["basis"] == "E1_and_E2"
        assert unlock["runner_repository"] == {"clean": True, "head": "a" * 40}
        paths = {f["path"]: f for f in unlock["snapshot"]["files"]}
        assert paths["activation.json"]["match"] == "exact"
        assert paths["runs.jsonl"]["match"] == "prefix"
        assert "ledger/SPY/1d/raw/artifacts.jsonl" in paths
        assert "ledger/SPY/1d/raw/outcomes.jsonl" in paths
        assert set(unlock["cutoffs"]) == {"SPY"}
        text = raw.decode().lower()
        for forbidden in ("bullish", "bearish", "neutral", "forward_return", "mean", "median",
                          "category", "price", "delta"):
            assert forbidden not in text

    def test_a_second_run_verifies_and_never_replaces(self, root_templates, tmp_path,
                                                      monkeypatch):
        store = store_of(root_templates, tmp_path)
        first = call_run(store)
        before = files(artifacts(store).directory)
        writes = []
        monkeypatch.setattr(runner.ValidationArtifacts, "write_once",
                            lambda self, name, data: writes.append(name))
        again = call_run(store, at=et(2031, 5, 1, 12))
        assert again.outcome == "already_complete"
        assert again.categories == first.categories
        assert again.result_sha256 == first.result_sha256
        assert files(artifacts(store).directory) == before and writes == []

    def test_a_missing_report_is_rendered_from_the_result(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        report = artifacts(store).path(REPORT_NAME)
        expected = report.read_bytes()
        os.unlink(report)
        assert call_run(store).outcome == "already_complete"
        assert report.read_bytes() == expected

    def test_a_tampered_report_or_result_is_refused(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        report = artifacts(store).path(REPORT_NAME)
        os.chmod(report, 0o644)
        report.write_bytes(report.read_bytes() + b"edit\n")
        assert call_run(store).detail == ("report_mismatch",)
        result = artifacts(store).path(RESULT_NAME)
        original = result.read_bytes()
        result.write_bytes(original.replace(b"mixed", b"MIXED"))
        assert call_run(store).detail[0] == "result_corrupt"
        result.write_bytes(original + b" ")
        assert call_run(store).detail[0] == "result_corrupt"

    @pytest.mark.parametrize("field", ["category", "metric", "cutoff", "coverage", "ratio"])
    def test_a_canonical_tamper_with_the_report_deleted_is_refused(
            self, root_templates, tmp_path, field):
        """N1: the review's reproducer -- a schema-valid edit plus a deleted report."""
        store = store_of(root_templates, tmp_path)
        call_run(store)
        written = artifacts(store)
        result = decode_canonical(written.read(RESULT_NAME), "result")
        row = result["primary"][0]
        if field == "category":
            row["category"] = "directionally_consistent"
            result["categories"] = [["SPY", "directionally_consistent"]]
        elif field == "metric":
            row["mean_delta"] = -0.125
        elif field == "cutoff":
            result["cutoffs"]["SPY"] = row["cutoff"] = "2026-10-01T04:00:00+00:00"
        elif field == "coverage":
            result["secondary"]["G_coverage"]["rows"][0]["missed_sessions_at_or_before_cutoff"] = 9
        else:
            row["abs_mean_delta_ratio_vs_reference"] = 0.5
        original = written.read(RESULT_NAME)
        os.chmod(written.path(RESULT_NAME), 0o644)
        written.path(RESULT_NAME).write_bytes(canonical_bytes(result))
        os.unlink(written.path(REPORT_NAME))
        outcome = call_run(store)
        assert (outcome.outcome, outcome.detail, outcome.categories) == (
            "refused", ("result_mismatch",), ())
        assert not written.exists(REPORT_NAME)
        written.path(RESULT_NAME).write_bytes(original)  # the genuine result verifies again
        assert call_run(store).outcome == "already_complete"

    def test_a_result_naming_another_unlock_is_refused(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        written = artifacts(store)
        result = decode_canonical(written.read(RESULT_NAME), "result")
        result["unlock"]["sha256"] = "0" * 64
        os.chmod(written.path(RESULT_NAME), 0o644)
        written.path(RESULT_NAME).write_bytes(canonical_bytes(result))
        assert call_run(store).detail == ("result_unlock_mismatch",)

    @pytest.mark.parametrize("field", list(DETERMINISTIC_UNLOCK_EDITS))
    def test_an_edited_deterministic_unlock_field_is_refused(self, root_templates, tmp_path,
                                                             field):
        """R-N1: an unlock edit, re-pointed by the result, with the report deleted."""
        store = store_of(root_templates, tmp_path)
        call_run(store)
        written = artifacts(store)
        result = edit_unlock_and_repoint(written, DETERMINISTIC_UNLOCK_EDITS[field])
        outcome = call_run(store)
        assert (outcome.outcome, outcome.detail) == (
            "refused", ("result_unverifiable", "unlock_metadata_mismatch"))
        assert written.read(RESULT_NAME) == result and not written.exists(REPORT_NAME)

    @pytest.mark.parametrize("field", list(DETERMINISTIC_UNLOCK_EDITS))
    def test_an_edited_unlock_is_never_completed(self, root_templates, tmp_path, monkeypatch,
                                                 field):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        written = artifacts(store)
        unlock = decode_canonical(written.read(UNLOCK_NAME), "unlock")
        DETERMINISTIC_UNLOCK_EDITS[field](unlock)
        os.chmod(written.path(UNLOCK_NAME), 0o644)
        written.path(UNLOCK_NAME).write_bytes(canonical_bytes(unlock))
        assert call_run(store).detail == ("unlock_metadata_mismatch",)
        assert not written.exists(RESULT_NAME) and not written.exists(REPORT_NAME)

    @pytest.mark.parametrize("field", sorted(runner.UNLOCK_INFORMATIONAL_FIELDS))
    def test_informational_unlock_fields_are_recorded_not_verified(self, root_templates,
                                                                   tmp_path, field):
        """host_recorded_at and runner_repository describe the opening host; they decide
        nothing and cannot be re-derived, so a consistent edit is not detectable."""
        store = store_of(root_templates, tmp_path)
        first = call_run(store)
        value = ("2000-01-01T00:00:00+00:00" if field == "host_recorded_at"
                 else {"clean": False, "head": "b" * 40})
        edit_unlock_and_repoint(artifacts(store), lambda unlock: unlock.__setitem__(field, value))
        again = call_run(store)
        assert again.outcome == "already_complete" and again.categories == first.categories

    @pytest.mark.parametrize("edit", [
        lambda u: u.__setitem__("host_recorded_at", "yesterday"),
        lambda u: u.__setitem__("host_recorded_at", "2026-10-05T12:00:00"),
        lambda u: u.__setitem__("host_recorded_at", None),
        lambda u: u.__setitem__("runner_repository", []),
        lambda u: u.__setitem__("runner_repository", {"clean": "yes", "head": "a"}),
        lambda u: u.__setitem__("snapshot", []),
        lambda u: u["snapshot"]["files"].append({"path": "../escape", "length": 0,
                                                 "match": "prefix", "sha256": "0" * 64}),
        lambda u: u["snapshot"]["files"][0].__setitem__("length", "12"),
    ], ids=["host_text", "host_naive", "host_null", "repo_list", "repo_types",
            "snapshot_list", "snapshot_escape", "snapshot_length_text"])
    def test_a_malformed_unlock_is_corrupt_not_a_crash(self, root_templates, tmp_path,
                                                       monkeypatch, edit):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        written = artifacts(store)
        unlock = decode_canonical(written.read(UNLOCK_NAME), "unlock")
        edit(unlock)
        os.chmod(written.path(UNLOCK_NAME), 0o644)
        written.path(UNLOCK_NAME).write_bytes(canonical_bytes(unlock))
        assert call_run(store).detail == ("unlock_corrupt",)
        assert not written.exists(RESULT_NAME)

    @pytest.mark.parametrize("name", list(MALFORMED_RESULTS))
    def test_a_malformed_result_is_refused_not_a_crash(self, root_templates, tmp_path, name):
        """R-N2: a canonical result of the wrong shape refuses cleanly and writes nothing."""
        store = store_of(root_templates, tmp_path)
        call_run(store)
        written = artifacts(store)
        result = decode_canonical(written.read(RESULT_NAME), "result")
        MALFORMED_RESULTS[name](result)
        os.chmod(written.path(RESULT_NAME), 0o644)
        written.path(RESULT_NAME).write_bytes(canonical_bytes(result))
        os.unlink(written.path(REPORT_NAME))
        tampered = written.read(RESULT_NAME)
        outcome = call_run(store)
        assert outcome.outcome == "refused" and outcome.categories == ()
        assert outcome.detail[0] in ("result_corrupt", "result_mismatch"), outcome.detail
        assert written.read(RESULT_NAME) == tampered and not written.exists(REPORT_NAME)
        assert main(["run"], root=store.root, now=lambda: AFTER_E1, repository=ProbeDouble(),
                    definition=SMALL, pinned_fingerprint=SMALL.fingerprint,
                    collection=SPY_ONLY, stdout=io.StringIO()) == 2

    def test_verification_refuses_when_the_frozen_prefix_is_gone(self, root_templates,
                                                                 tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        ledger = store.root / "ledger" / "SPY" / "1d" / "raw" / "outcomes.jsonl"
        ledger.write_bytes(ledger.read_bytes()[:-40])
        assert call_run(store).detail == ("result_unverifiable", "snapshot_mismatch")

    def test_another_definition_cannot_occupy_the_frozen_opening(self, root_templates,
                                                                 tmp_path):
        """N2: artifacts live under the definition's own fingerprint."""
        store = store_of(root_templates, tmp_path)
        variant = small_definition(minimum_bullish_episodes=1, stop_rule_minimum_matured_claims=1)
        assert call_run(store, definition=variant).outcome == "complete"
        assert artifacts(store, variant).directory != artifacts(store).directory
        assert artifacts(store).directory.name == SMALL.fingerprint
        assert not artifacts(store).exists(UNLOCK_NAME)
        assert call_run(store).outcome == "complete"
        assert call_status(store).result_exists

    def test_write_once_never_replaces(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        with pytest.raises(ArtifactExists):
            artifacts(store).write_once(UNLOCK_NAME, b"{}\n")
        with pytest.raises(ArtifactExists):
            artifacts(store).write_once(RESULT_NAME, b"{}\n")

    def test_forced_unlock_on_the_evidence_clock_then_adequacy_decides(
            self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        stalled = small_definition(stop_rule_minimum_matured_claims=10_000,
                                   minimum_bullish_episodes=8)
        assert call_run(store, at=AFTER_F, definition=stalled).detail == ("not_unlockable",)
        forced = small_definition(stop_rule_minimum_matured_claims=10_000,
                                  minimum_bullish_episodes=8, forced_unlock_calendar_months=1)
        assert call_run(store, at=ACTIVATED_AT, definition=forced).categories == (
            ("SPY", "inconclusive_insufficient_sample"),)
        unlock = decode_canonical(artifacts(store, forced).read(UNLOCK_NAME), "unlock")
        assert unlock["stop_rule"]["basis"] == "F_forced_unlock"
        assert unlock["stop_rule"]["evidence_through"] == EVIDENCE_THROUGH.astimezone(
            timezone.utc).isoformat()

    def test_a_definition_mismatch_refuses_before_anything(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        before = files(store.root)
        outcome = call_run(store, pinned="0" * 64)
        assert outcome.detail[:2] == ("definition_mismatch", "validation_fingerprint")
        assert files(store.root) == before

    def test_validation_files_do_not_disturb_collection(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        call_run(store)
        collect_sessions(store, list(weekday_mornings(date(2026, 11, 9), 2)), prefix="later")
        assert health(store, definition=SPY_ONLY).provenance.status == "ok"


# -- the host clock decides nothing ---------------------------------------------------------------

HOST_TIMES = {
    "activation": ACTIVATED_AT,
    "plus_one_day": ACTIVATED_AT + timedelta(days=1),
    "plus_one_year": ACTIVATED_AT + timedelta(days=365),
    "plus_ten_years": ACTIVATED_AT + timedelta(days=3653),
    "backward_one_year": ACTIVATED_AT - timedelta(days=365),
}


class TestHostClockIsNotAuthoritative:
    def test_status_takes_no_clock(self):
        import inspect

        assert "now" not in inspect.signature(status).parameters

    @pytest.mark.parametrize("host", list(HOST_TIMES), ids=str)
    def test_a_stalled_collection_never_opens_whatever_the_host_says(
            self, root_templates, tmp_path, host):
        store = store_of(root_templates, tmp_path)
        before = files(store.root)
        outcome = call_run(store, at=HOST_TIMES[host], definition=NOT_YET)
        assert outcome.detail == ("not_unlockable",)
        assert files(store.root) == before

    def test_the_frozen_definition_cannot_be_opened_by_a_ten_year_host_clock(
            self, root_templates, tmp_path):
        # 72 months on the host clock, ~1 month of evidence: F is not met (B1 reproducer).
        store = store_of(root_templates, tmp_path)
        strict = small_definition(stop_rule_minimum_matured_claims=10_000,
                                  stop_rule_minimum_calendar_months=48,
                                  forced_unlock_calendar_months=72)
        outcome = call_run(store, at=ACTIVATED_AT + timedelta(days=3653), definition=strict)
        assert outcome.detail == ("not_unlockable",)
        assert outcome.status.f_met is False and outcome.status.e1_met is False

    @pytest.mark.parametrize("host", list(HOST_TIMES), ids=str)
    def test_an_unlockable_opening_is_identical_but_for_host_metadata(
            self, root_templates, tmp_path, host):
        reference = store_of(root_templates, tmp_path / "reference")
        call_run(reference, at=ACTIVATED_AT)
        store = store_of(root_templates, tmp_path / "host")
        assert call_run(store, at=HOST_TIMES[host]).outcome == "complete"
        one = decode_canonical(artifacts(reference).read(UNLOCK_NAME), "unlock")
        two = decode_canonical(artifacts(store).read(UNLOCK_NAME), "unlock")
        assert two["host_recorded_at"] == HOST_TIMES[host].astimezone(timezone.utc).isoformat()
        one.pop("host_recorded_at"), two.pop("host_recorded_at")
        assert one == two
        first = decode_canonical(artifacts(reference).read(RESULT_NAME), "result")
        second = decode_canonical(artifacts(store).read(RESULT_NAME), "result")
        for payload in (first, second):
            payload["unlock"].pop("host_recorded_at"), payload["unlock"].pop("sha256")
        assert first == second


# -- crash after unlock -------------------------------------------------------------------------


class Crash(BaseException):
    pass


def crash_after_unlock(store, monkeypatch):
    real = runner.build_result

    def crashing(*args, **kwargs):
        raise Crash()

    monkeypatch.setattr(runner, "build_result", crashing)
    with pytest.raises(Crash):
        call_run(store)
    monkeypatch.setattr(runner, "build_result", real)
    assert artifacts(store).exists(UNLOCK_NAME) and not artifacts(store).exists(RESULT_NAME)


class TestCrashAfterUnlock:
    def test_completion_is_the_same_result_and_ignores_later_data(
            self, root_templates, tmp_path, monkeypatch):
        clean = store_of(root_templates, tmp_path / "clean")
        call_run(clean)
        expected = files(artifacts(clean).directory)

        crashed = store_of(root_templates, tmp_path / "crashed")
        crash_after_unlock(crashed, monkeypatch)
        # collection continues and appends to the run log and the ledger
        collect_sessions(crashed, list(weekday_mornings(date(2026, 11, 9), 3)),
                         prefix="later")
        before_unlock = artifacts(crashed).read(UNLOCK_NAME)
        outcome = call_run(crashed, at=et(2031, 1, 5, 12))  # a later clock changes nothing
        assert outcome.outcome == "completed_after_unlock"
        assert artifacts(crashed).read(UNLOCK_NAME) == before_unlock
        assert files(artifacts(crashed).directory) == expected

    def test_a_modified_prefix_is_refused(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        ledger = store.root / "ledger" / "SPY" / "1d" / "raw" / "outcomes.jsonl"
        data = bytearray(ledger.read_bytes())
        data[10] = ord("X") if data[10] != ord("X") else ord("Y")
        ledger.write_bytes(bytes(data))
        outcome = call_run(store)
        assert outcome.detail == ("snapshot_mismatch",)
        assert not artifacts(store).exists(RESULT_NAME)

    def test_a_truncated_input_is_refused(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        run_log = store.root / "runs.jsonl"
        run_log.write_bytes(run_log.read_bytes()[:-50])
        assert call_run(store).detail == ("snapshot_mismatch",)

    def test_a_vanished_input_is_refused(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        os.unlink(store.root / "ledger" / "SPY" / "1d" / "raw" / "artifacts.jsonl")
        assert call_run(store).detail == ("snapshot_mismatch",)

    def test_a_changed_manifest_is_refused(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        manifest = store.root / "activation.json"
        manifest.write_bytes(manifest.read_bytes() + b" ")
        assert call_run(store).detail == ("snapshot_mismatch",)

    def test_a_corrupt_unlock_is_refused_never_replaced(self, root_templates, tmp_path,
                                                        monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        unlock = artifacts(store).path(UNLOCK_NAME)
        unlock.write_bytes(unlock.read_bytes()[:-2] + b"\n")
        assert call_run(store).detail == ("unlock_corrupt",)
        assert not artifacts(store).exists(RESULT_NAME)

    def test_status_after_a_crash_reports_the_unlock(self, root_templates, tmp_path,
                                                     monkeypatch):
        store = store_of(root_templates, tmp_path)
        crash_after_unlock(store, monkeypatch)
        report = call_status(store)
        assert report.unlock_exists and not report.result_exists


# -- locking --------------------------------------------------------------------------------------


class TestLocking:
    def test_a_running_collector_blocks_status_and_run(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        before = files(store.root)
        with store.exclusive_lock():
            assert call_status(store).activation == "collect_in_progress"
            assert call_run(store).detail == ("collect_in_progress",)
        assert files(store.root) == before

    def test_the_collector_cannot_mutate_while_the_snapshot_is_captured(
            self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        real = runner.capture
        reports = []

        def capture_while_a_collector_tries(root):
            reports.append(collect(store, provider_factory=SessionProvider,
                                   now=Clock(et(2026, 11, 9, 7)), definition=SPY_ONLY,
                                   repository=ProbeDouble(), lock_timeout=0))
            return real(root)

        monkeypatch.setattr(runner, "capture", capture_while_a_collector_tries)
        before = files(store.root)
        call_status(store)
        assert reports[0].outcome == "locked" and reports[0].record is None
        assert files(store.root) == before

    def test_status_and_health_share_the_lock(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        with store.shared_lock():
            assert call_status(store).validity == "ok"
            assert health(store, definition=SPY_ONLY).status == "active"


# -- provenance -----------------------------------------------------------------------------------


class TestProvenance:
    def test_degraded_evidence_is_excluded_everywhere(self, root_templates, tmp_path):
        clean = call_status(store_of(root_templates, tmp_path / "a"))
        store = store_of(root_templates, tmp_path / "b", "degraded")
        report = call_status(store)
        assert (report.provenance_status, report.validity) == ("degraded", "ok")
        assert report.excluded_artifact_keys == 2
        # the crashed tail's trend_alignment claim is excluded from the matured count
        assert dict(report.e2_counts)["SPY"] == dict(clean.e2_counts)["SPY"] - 1
        outcome = call_run(store)
        assert outcome.outcome == "complete"
        result = decode_canonical(artifacts(store).read(RESULT_NAME), "result")
        primary = result["primary"][0]
        assert primary["matched_unconditional_count"] == dict(report.e2_counts)["SPY"]
        unlock = decode_canonical(artifacts(store).read(UNLOCK_NAME), "unlock")
        assert unlock["provenance"]["status"] == "degraded"
        assert unlock["provenance"]["excluded_artifact_keys"] == 2

    def test_invalid_provenance_refuses_and_writes_nothing(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        (store.root / "ledger" / "SPY" / "1d" / "raw" / "foreign.jsonl").write_bytes(b"{}\n")
        report = call_status(store)
        assert (report.provenance_status, report.validity, report.unlockable) == (
            "invalid", "invalid", False)
        assert report.e1_met is None  # no stop rule over unreconciled evidence
        before = files(store.root)
        outcome = call_run(store)
        assert outcome.detail[0] == "validity_invalid"
        assert files(store.root) == before

    def test_unreadable_evidence_is_unknown_provenance_and_refused(self, root_templates,
                                                                   tmp_path):
        store = store_of(root_templates, tmp_path)
        with open(store.root / "runs.jsonl", "ab") as handle:
            handle.write(b"{torn")
        report = call_status(store)
        assert (report.provenance_status, report.integrity) == ("unknown", "run_log_corrupt")
        assert not report.unlockable
        assert call_run(store).detail[:2] == ("validity_invalid", "run_log_corrupt")

    def test_a_symbolic_link_in_the_ledger_is_refused(self, root_templates, tmp_path):
        store = store_of(root_templates, tmp_path)
        os.symlink(tmp_path, store.root / "ledger" / "QQQ")
        assert call_status(store).integrity == "unsupported_entry"
        assert call_run(store).detail == ("unsupported_entry",)

    def test_a_live_configuration_mismatch_refuses(self, root_templates, tmp_path, monkeypatch):
        store = store_of(root_templates, tmp_path)
        monkeypatch.setattr(runner, "live_configuration_mismatches", lambda d: ("hypotheses",))
        report = call_status(store)
        assert report.validity == "invalid" and "live_hypotheses" in report.identity_mismatches
        assert call_run(store).detail[0] == "validity_invalid"


def test_frozen_definition_is_the_runner_default():
    import inspect

    for function in (status, run):
        parameters = inspect.signature(function).parameters
        assert parameters["definition"].default is FUTURE_VALIDATION_V1
