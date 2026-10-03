"""N2 prospective provenance hardening: policy, verifier, collector gate, locking, identity.

Two layers, all offline and on temporary roots:

* the **pure verifier** (:func:`verify_provenance`) over synthetic,
  normalised metadata -- every reason code reachable by construction;
* the **real path**: the supported collector, the generic
  ``python -m src.cli.outcome_refresh`` pointed at the prospective ledger
  (the N2 threat, reproduced and detected), crashes, locks, collector
  identity and the health CLI.

The autouse guard fails any test that opens a socket, reaches yfinance,
constructs the default provider or touches the live ``data/prospective``.
"""

from __future__ import annotations

import ast
import io
import itertools
import os
import pathlib
import shlex
from dataclasses import fields, replace
from datetime import date, timedelta

import pytest

import src.application.prospective as prospective
from src.application.prospective import (
    ActivationRefused,
    activate,
    build_prospective_store,
    collect,
    health,
)
from src.cli import outcome_refresh
from src.cli.prospective import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from src.data.models import Interval
from src.data.series import PriceBasis
from src.outcomes import LedgerPartition
from src.prospective import (
    COLLECTION_V1,
    PROVENANCE_V1,
    ClaimMeta,
    CollectionStatus,
    OutcomeMeta,
    PartitionMeta,
    RepositoryProbeError,
    RunRecord,
    RunStart,
    RunStatus,
    SymbolRun,
    provenance_policy_for,
    unknown_report,
    verify_provenance,
)
from src.prospective import provenance as provenance_module
from src.prospective.records import RecordError, decode_run_log_line
from src.strategies.research import ResearchState
from tests.prospective_fixtures import (  # noqa: F401 - autouse guard
    COLLECTOR_SHA,
    LIVE_ROOT,
    M2_SHA,
    SPY_ONLY,
    VERSIONS,
    Clock,
    ProbeDouble,
    SessionProvider,
    build_matured_root,
    et,
    install_offline_guard,
    ny_midnight,
    offline_and_no_live_root,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
ACTIVATED_AT = et(2026, 10, 5, 15)
TUESDAY_RUN = et(2026, 10, 6, 7)
MONDAY_BAR = ny_midnight(date(2026, 10, 5))

#: The pinned identity of the provenance policy. A change is a new policy version.
#: B1 repair (backward-clock tolerance + rules frozen in text) replaced
#: cfa0742a0a626235eaf3768d495edc6740b148b358322086a6ffe53307bf3890.
PROVENANCE_V1_FINGERPRINT = "ca6a313324c199a3387ef11f0ff6404224b05afe7201e137ec079a3f3d70d117"
COLLECTION_V1_FINGERPRINT = "af5ce0d1f514b8da7f98baebdefbd202f6ba3677a66e63bfe55925348b7d06b8"

_IDS = itertools.count()


# == helpers ======================================================================================


def activated(tmp_path, *, definition=COLLECTION_V1, at=ACTIVATED_AT):
    store = build_prospective_store(tmp_path / "v1")
    activate(store, collector_git_commit=COLLECTOR_SHA, m2_preregistration_git_commit=M2_SHA,
             repository=ProbeDouble(), versions=VERSIONS, now=lambda: at, definition=definition)
    return store



def run(store, moment, *, provider=None, definition=COLLECTION_V1, repository=None, **kwargs):
    provider = provider if provider is not None else SessionProvider()
    built = []

    def factory():
        built.append(provider)
        return provider

    report = collect(store, provider_factory=factory, now=Clock(moment),
                     run_id_factory=lambda: f"run-{next(_IDS)}", definition=definition,
                     repository=repository if repository is not None else ProbeDouble(),
                     **kwargs)
    return report, built


def bypass(store, moment, *, symbols=("SPY",), interval="1d"):
    """The N2 threat: the generic Phase 12 refresh pointed at the prospective ledger."""
    out, err = io.StringIO(), io.StringIO()
    code = outcome_refresh.main(
        [*symbols, "--interval", interval, "--outcome-root", str(store.ledger_root)],
        provider=SessionProvider(), now=Clock(moment), stdout=out, stderr=err)
    return code, out.getvalue()


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def spy_ledger(store):
    return prospective.build_outcome_ledger(store.ledger_root)


SPY = LedgerPartition(symbol="SPY", interval=Interval.DAY_1, basis=PriceBasis.RAW)


def cli(argv, root, *, provider=None, now=None, repository=None):
    out, err = io.StringIO(), io.StringIO()
    kwargs = dict(root=root, stdout=out, stderr=err, versions=VERSIONS,
                  repository=repository if repository is not None else ProbeDouble())
    if provider is not None:
        kwargs["provider_factory"] = lambda: provider
    if now is not None:
        kwargs["now"] = Clock(now)
    code = main(argv, **kwargs)
    return code, out.getvalue().splitlines(), err.getvalue()


def parse(line):
    return dict(token.partition("=")[::2] for token in shlex.split(line))


def provenance_line(lines):
    [line] = [parse(l) for l in lines if l.startswith("provenance=")]
    return line


# == the policy ===================================================================================


class TestPolicy:
    def test_collection_v1_is_unchanged(self):
        assert COLLECTION_V1.fingerprint == COLLECTION_V1_FINGERPRINT
        assert "provenance" not in COLLECTION_V1.canonical_json()
        assert "claims_per_tail" not in COLLECTION_V1.canonical_form()
        assert COLLECTION_V1.claims_per_tail == 4

    def test_the_policy_fingerprint_is_pinned(self):
        assert PROVENANCE_V1.fingerprint == PROVENANCE_V1_FINGERPRINT
        assert len(PROVENANCE_V1.fingerprint) == 64

    def test_the_policy_is_derived_from_and_bound_to_collection_v1(self):
        policy = provenance_policy_for(COLLECTION_V1)
        assert policy == PROVENANCE_V1
        assert policy.policy_id == "prospective_provenance_v1" and policy.schema_version == 1
        assert policy.collection_fingerprint == COLLECTION_V1_FINGERPRINT
        assert policy.universe == ("SPY", "QQQ", "IWM", "TLT", "GLD")
        assert (policy.interval, policy.basis, policy.provider, policy.origin) == (
            "1d", "raw", "yfinance", "snapshot")
        assert policy.hypotheses == (
            ("trend_alignment", 1, "650add07184f8440"),
            ("momentum_in_trend_context", 1, "6589cb8021b76574"),
            ("trend_crossover", 1, "f1126ca778e6f7ce"),
        )
        assert policy.assessment_policy_fingerprint == "a829b9bde41c3332"
        assert policy.claims_per_tail == 4
        assert policy.outcome_horizons == (1, 5, 20)
        assert policy.evaluation_version == 1
        assert (policy.collection_window_start, policy.collection_window_end) == (
            "00:30", "09:00")
        assert policy.interrupted_run_treatment == "degraded_excluded"
        assert policy.interrupted_run_max_seconds == 3600
        assert policy.interrupted_run_backward_tolerance_seconds == 5

    def test_the_matching_rules_are_frozen_in_the_canonical_form(self):
        """N-R1: rules that were code-only are fingerprinted text now."""
        form = PROVENANCE_V1.canonical_form()
        assert form["interrupted_run_backward_tolerance_seconds"] == 5
        rule = form["interrupted_run_attribution_rule"]
        for phrase in ("interrupted_run_backward_tolerance_seconds",
                       "before the started_at of the next run-log entry",
                       "same America/New_York date", "interrupted_run_max_seconds",
                       "one clock reading and one tail", "at most claims_per_tail",
                       "outcomes share one clock reading", "anything else is invalid"):
            assert phrase in rule, phrase
        consistency = form["run_log_consistency_rule"]
        for phrase in ("run ids are unique", "same run_id and started_at",
                       "refusal record has no symbols",
                       "no ordering between started_at, built_at and finished_at"):
            assert phrase in consistency, phrase

    def test_canonical_json_is_sorted_and_deterministic(self):
        text = PROVENANCE_V1.canonical_json()
        assert text == provenance_policy_for(COLLECTION_V1).canonical_json()
        import json
        assert list(json.loads(text)) == sorted(json.loads(text))

    def test_any_rule_change_changes_the_fingerprint(self):
        assert replace(PROVENANCE_V1, interrupted_run_max_seconds=7200).fingerprint != \
            PROVENANCE_V1.fingerprint
        assert replace(PROVENANCE_V1,
                       interrupted_run_backward_tolerance_seconds=6).fingerprint != \
            PROVENANCE_V1.fingerprint
        assert replace(PROVENANCE_V1, interrupted_run_attribution_rule="x").fingerprint != \
            PROVENANCE_V1.fingerprint
        assert provenance_policy_for(SPY_ONLY).fingerprint != PROVENANCE_V1.fingerprint

    def test_the_vocabulary_is_operational_and_never_a_research_state(self):
        assert provenance_module.STATUSES == ("ok", "degraded", "invalid", "unknown")
        states = {state.value for state in ResearchState}
        vocabulary = set(provenance_module.REASONS) | set(provenance_module.STATUSES) | {
            status.value for status in RunStatus} | {s.value for s in CollectionStatus}
        assert not vocabulary & states
        assert {"unmatched_claim", "unmatched_outcome", "claim_outside_window",
                "outcome_outside_window", "pre_activation_claim", "late_claim",
                "unexpected_partition", "unexpected_source", "unexpected_origin",
                "unexpected_producer", "unexpected_outcome_spec", "artifact_count_mismatch",
                "missing_claimed_artifacts", "run_record_inconsistent",
                "collector_commit_mismatch"} <= set(provenance_module.INVALID_REASONS)
        assert provenance_module.DEGRADED_REASONS == ("interrupted_run",)
        assert {"not_activated", "collect_in_progress", "integrity_corrupt"} <= set(
            provenance_module.UNKNOWN_REASONS)

    def test_unknown_reports_only_use_the_vocabulary(self):
        assert unknown_report("collect_in_progress").status == "unknown"
        with pytest.raises(ValueError):
            unknown_report("bullish")


# == records ======================================================================================


class TestRunStart:
    def start(self, **overrides):
        values = dict(run_id="r1", started_at=TUESDAY_RUN,
                      collection_fingerprint=COLLECTION_V1.fingerprint,
                      provenance_policy_fingerprint=PROVENANCE_V1.fingerprint,
                      activated_at=ACTIVATED_AT, collector_git_commit=COLLECTOR_SHA,
                      universe=COLLECTION_V1.universe)
        values.update(overrides)
        return RunStart(**values)

    def test_round_trip_is_canonical(self):
        start = self.start()
        line = start.to_line()
        assert decode_run_log_line(line[:-1]) == start
        assert b'"schema":"prospective_run_start_v1"' in line

    def test_only_identities_and_one_clock(self):
        assert set(self.start().to_payload()) == RunStart.FIELDS
        assert RunStart.FIELDS == {
            "schema", "run_id", "started_at", "collection_fingerprint",
            "provenance_policy_fingerprint", "activated_at", "collector_git_commit",
            "universe"}

    @pytest.mark.parametrize("mutate", [
        lambda t: t.replace(b'"run_id":"r1"', b'"run_id":"r1","extra":1'),
        lambda t: t.replace(b'"run_id":"r1",', b""),
        lambda t: t.replace(b",", b", ", 1),
    ])
    def test_decoding_is_strict(self, mutate):
        raw = self.start().to_line()[:-1]
        with pytest.raises(RecordError):
            decode_run_log_line(mutate(raw))


# == the pure verifier ============================================================================


POLICY = provenance_policy_for(SPY_ONLY)
PRODUCERS = tuple(("observation", hid, version, fp) for hid, version, fp in POLICY.hypotheses) \
    + (("assessment", POLICY.assessment_policy_fingerprint),)


class Book:
    """A synthetic SPY-only collection: run log + ledger metadata, built run by run."""

    def __init__(self):
        self.log = []
        self.claims = []
        self.outcomes = []
        self.entries = {"SPY", "SPY/1d", "SPY/1d/raw", "SPY/1d/raw/artifacts.jsonl",
                        "SPY/1d/raw/outcomes.jsonl"}

    def claim(self, tail, recorded_at, producer=PRODUCERS[0], **overrides):
        values = dict(symbol="SPY", line=len(self.claims) + 1,
                      key=f"a-{tail.isoformat()}-{PRODUCERS.index(producer) if producer in PRODUCERS else 'x'}-{len(self.claims)}",
                      producer=producer, interval="1d", basis="raw", timestamp=tail,
                      data_cutoff=tail, recorded_at=recorded_at, source="yfinance",
                      origin="snapshot")
        values.update(overrides)
        claim = ClaimMeta(**values)
        self.claims.append(claim)
        return claim

    def outcome(self, claim, evaluated_at, horizon=1, **overrides):
        index = POLICY.outcome_horizons.index(horizon)
        values = dict(symbol="SPY", line=len(self.outcomes) + 1,
                      key=f"o-{claim.key}-{horizon}", artifact_key=claim.key,
                      spec_fingerprint=POLICY.outcome_spec_fingerprints[index],
                      horizon_bars=horizon, evaluation_version=1, evaluated_at=evaluated_at)
        values.update(overrides)
        outcome = OutcomeMeta(**values)
        self.outcomes.append(outcome)
        return outcome

    def start(self, run_id, started_at, **overrides):
        values = dict(run_id=run_id, started_at=started_at,
                      collection_fingerprint=SPY_ONLY.fingerprint,
                      provenance_policy_fingerprint=POLICY.fingerprint,
                      activated_at=ACTIVATED_AT, collector_git_commit=COLLECTOR_SHA,
                      universe=SPY_ONLY.universe)
        values.update(overrides)
        start = RunStart(**values)
        self.log.append(start)
        return start

    def record(self, run_id, started_at, symbol_run, **overrides):
        values = dict(run_id=run_id, started_at=started_at,
                      finished_at=started_at + timedelta(seconds=30),
                      run_status=RunStatus.COMPLETED,
                      collection_fingerprint=SPY_ONLY.fingerprint, activated_at=ACTIVATED_AT,
                      collector_git_commit=COLLECTOR_SHA, universe=SPY_ONLY.universe,
                      symbols=(symbol_run,))
        values.update(overrides)
        record = RunRecord(**values)
        self.log.append(record)
        return record

    def legit_run(self, run_id, started_at, tail, *, claims=4, outcomes_of=(),
                  status=CollectionStatus.OK):
        """One completed run that registered ``claims`` for ``tail`` and evaluated outcomes."""
        built_at = started_at + timedelta(seconds=5)
        self.start(run_id, started_at)
        new_claims = [self.claim(tail, built_at, PRODUCERS[i]) for i in range(claims)]
        new_outcomes = [self.outcome(c, built_at, h) for c, h in outcomes_of]
        symbol_run = SymbolRun(
            symbol="SPY", status=status, stage="done" if status in (
                CollectionStatus.OK, CollectionStatus.DUPLICATE_ALREADY_EXISTS,
                CollectionStatus.INSUFFICIENT_HISTORY) else "outcomes",
            built_at=built_at, tail=tail, bars=300,
            **({} if status not in (CollectionStatus.OK, CollectionStatus.DUPLICATE_ALREADY_EXISTS,
                                    CollectionStatus.INSUFFICIENT_HISTORY)
               else dict(artifacts_new=claims, artifacts_duplicate=0,
                         outcomes_new=len(new_outcomes), outcomes_present=0, pending=0,
                         ineligible=0, refused=0, out_of_window=0)))
        self.record(run_id, started_at, symbol_run)
        return new_claims, new_outcomes

    def verify(self, *, policy=POLICY, entries=None, **overrides):
        arguments = dict(
            activated_at=ACTIVATED_AT, collection_fingerprint=SPY_ONLY.fingerprint,
            collector_git_commit=COLLECTOR_SHA, run_log=tuple(self.log),
            ledger_entries=tuple(sorted(self.entries if entries is None else entries)),
            partitions=(PartitionMeta("SPY", tuple(self.claims), tuple(self.outcomes)),),
        )
        arguments.update(overrides)
        return verify_provenance(policy, **arguments)


def reasons(report):
    return dict(report.reasons)


TUE = ny_midnight(date(2026, 10, 6))
WED = ny_midnight(date(2026, 10, 7))


def two_legit_days():
    book = Book()
    monday, _ = book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR)
    book.legit_run("r2", et(2026, 10, 7, 7), TUE, outcomes_of=[(monday[0], 1)])
    return book, monday


class TestVerifier:
    def test_a_clean_collection_is_ok(self):
        book, _ = two_legit_days()
        report = book.verify()
        assert (report.status, report.findings) == ("ok", ())
        assert (report.claims_checked, report.outcomes_checked) == (8, 1)
        assert report.permits_collection and report.permits_validation

    def test_an_empty_activated_root_is_ok(self):
        report = Book().verify(entries=(), partitions=())
        assert report.status == "ok"

    def test_refusal_records_are_inert(self):
        book, _ = two_legit_days()
        book.record("refused", et(2026, 10, 7, 12), None, symbols=(),
                    run_status=RunStatus.OUTSIDE_COLLECTION_WINDOW,
                    collection_fingerprint="drifted")
        assert book.verify().status == "ok"

    # -- claims ---------------------------------------------------------------------------------

    def test_an_unmatched_claim_is_invalid(self):
        book, _ = two_legit_days()
        book.claim(WED, et(2026, 10, 8, 7, 30))
        report = book.verify()
        assert report.status == "invalid"
        assert reasons(report) == {"unmatched_claim": 1}
        assert report.first_finding.line == 9
        assert not report.permits_collection and not report.permits_validation

    def test_a_claim_outside_the_window_is_invalid(self):
        book, _ = two_legit_days()
        book.claim(WED, et(2026, 10, 7, 16))
        assert {"claim_outside_window", "unmatched_claim"} <= set(reasons(book.verify()))

    def test_a_pre_activation_claim_is_invalid(self):
        book, _ = two_legit_days()
        book.claim(ny_midnight(date(2026, 10, 2)), et(2026, 10, 5, 7))
        assert "pre_activation_claim" in reasons(book.verify())

    def test_a_late_claim_is_invalid(self):
        book, _ = two_legit_days()
        book.claim(MONDAY_BAR, et(2026, 10, 8, 7))
        assert "late_claim" in reasons(book.verify())

    @pytest.mark.parametrize("override, reason", [
        ({"source": "fake"}, "unexpected_source"),
        ({"origin": "replay"}, "unexpected_origin"),
        ({"producer": ("observation", "trend_alignment", 2, "650add07184f8440")},
         "unexpected_producer"),
        ({"producer": ("assessment", "0000000000000000")}, "unexpected_producer"),
        ({"interval": "1wk"}, "unexpected_partition"),
        ({"basis": "adjusted"}, "unexpected_partition"),
        ({"symbol": "QQQ"}, "unexpected_partition"),
    ])
    def test_a_matched_claim_with_a_wrong_identity_is_still_invalid(self, override, reason):
        book = Book()
        claims, _ = book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR)
        book.claims[0] = replace(claims[0], **override)
        report = book.verify()
        assert report.status == "invalid" and reason in reasons(report)

    def test_a_data_cutoff_that_is_not_the_tail_is_invalid(self):
        book = Book()
        claims, _ = book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR)
        book.claims[0] = replace(claims[0], data_cutoff=TUE)
        assert "claim_timestamp_convention" in reasons(book.verify())

    def test_a_claim_at_a_run_clock_but_another_tail_is_unmatched(self):
        book = Book()
        claims, _ = book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR, claims=3)
        book.claim(ny_midnight(date(2026, 10, 2)), claims[0].recorded_at, PRODUCERS[3])
        assert "unmatched_claim" in reasons(book.verify())

    # -- counts ---------------------------------------------------------------------------------

    def test_a_deleted_claim_is_missing(self):
        book, _ = two_legit_days()
        del book.claims[2]
        assert reasons(book.verify()) == {"missing_claimed_artifacts": 1}

    def test_a_claim_beyond_the_run_count_is_a_mismatch(self):
        book = Book()
        book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR, claims=3)
        book.log[-1] = replace(book.log[-1], symbols=(replace(book.log[-1].symbols[0],
                                                              artifacts_new=2),))
        assert reasons(book.verify()) == {"artifact_count_mismatch": 1}

    def test_a_duplicate_run_with_a_new_claim_is_a_mismatch(self):
        book = Book()
        book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR, claims=1,
                       status=CollectionStatus.DUPLICATE_ALREADY_EXISTS)
        book.log[-1] = replace(book.log[-1], symbols=(replace(book.log[-1].symbols[0],
                                                              artifacts_new=0),))
        assert "artifact_count_mismatch" in reasons(book.verify())

    def test_a_refresh_failure_is_bounded_not_counted(self):
        """N10: a refresh that raised has no counts; up to claims_per_tail is accepted."""
        book = Book()
        book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR, claims=2,
                       status=CollectionStatus.REFRESH_FAILURE)
        assert book.verify().status == "ok"

    def test_a_partition_that_vanished_is_missing(self):
        book, _ = two_legit_days()
        report = book.verify(entries=(), partitions=())
        assert {"missing_claimed_artifacts", "missing_claimed_outcomes"} <= set(reasons(report))

    # -- outcomes -------------------------------------------------------------------------------

    def test_an_unmatched_outcome_is_invalid(self):
        book, monday = two_legit_days()
        book.outcome(monday[1], et(2026, 10, 7, 7, 30))
        assert reasons(book.verify()) == {"unmatched_outcome": 1}

    def test_an_outcome_outside_the_window_is_invalid(self):
        book, monday = two_legit_days()
        book.outcome(monday[1], et(2026, 10, 7, 18))
        assert "outcome_outside_window" in reasons(book.verify())

    def test_an_outcome_of_an_unknown_artifact_is_unmatched(self):
        book, monday = two_legit_days()
        book.outcomes[0] = replace(book.outcomes[0], artifact_key="nobody")
        assert "unmatched_outcome" in reasons(book.verify())

    @pytest.mark.parametrize("override", [
        {"spec_fingerprint": "0000000000000000"},
        {"horizon_bars": 5},
        {"evaluation_version": 2},
    ])
    def test_a_wrong_outcome_spec_or_version_is_invalid(self, override):
        book, _ = two_legit_days()
        book.outcomes[0] = replace(book.outcomes[0], **override)
        assert "unexpected_outcome_spec" in reasons(book.verify())

    def test_a_deleted_outcome_is_missing(self):
        book, _ = two_legit_days()
        book.outcomes.clear()
        assert reasons(book.verify()) == {"missing_claimed_outcomes": 1}

    def test_an_outcome_beyond_the_run_count_is_a_mismatch(self):
        book, monday = two_legit_days()
        book.outcome(monday[1], book.outcomes[0].evaluated_at)
        assert reasons(book.verify()) == {"outcome_count_mismatch": 1}

    # -- partitions -----------------------------------------------------------------------------

    @pytest.mark.parametrize("entry", [
        "AAPL", "AAPL/1d/raw/artifacts.jsonl", "SPY/1wk", "SPY/1d/adjusted",
        "SPY/1d/raw/notes.txt", "stray.jsonl",
    ])
    def test_an_unexpected_ledger_entry_is_invalid(self, entry):
        book, _ = two_legit_days()
        report = book.verify(entries=book.entries | {entry})
        assert reasons(report) == {"unexpected_partition": 1}
        assert report.first_finding.component == f"ledger:{entry}"

    def test_file_browser_metadata_is_ignored(self):
        book, _ = two_legit_days()
        assert book.verify(entries=book.entries | {".DS_Store", "SPY/.DS_Store"}).status == "ok"

    # -- the run log ----------------------------------------------------------------------------

    def test_a_completed_record_without_its_start_is_inconsistent(self):
        book, _ = two_legit_days()
        del book.log[0]
        assert "run_record_inconsistent" in reasons(book.verify())

    def test_a_reused_run_id_is_inconsistent(self):
        book, _ = two_legit_days()
        book.record("r1", et(2026, 10, 7, 12), None, symbols=(),
                    run_status=RunStatus.OUTSIDE_COLLECTION_WINDOW)
        assert "run_record_inconsistent" in reasons(book.verify())

    def test_a_refusal_record_with_symbols_is_inconsistent(self):
        book, _ = two_legit_days()
        symbol_run = book.log[1].symbols[0]
        book.record("odd", et(2026, 10, 7, 12), symbol_run,
                    run_status=RunStatus.CONFIG_MISMATCH)
        assert "run_record_inconsistent" in reasons(book.verify())

    @pytest.mark.parametrize("override", [
        {"collection_fingerprint": "f" * 64},
        {"provenance_policy_fingerprint": "f" * 64},
        {"activated_at": et(2026, 10, 1, 15)},
        {"universe": ("SPY", "QQQ")},
    ])
    def test_a_run_start_that_disagrees_with_the_manifest_is_inconsistent(self, override):
        book, _ = two_legit_days()
        book.log[0] = replace(book.log[0], **override)
        assert "run_record_inconsistent" in reasons(book.verify())

    def test_a_run_start_outside_the_window_is_inconsistent(self):
        book = Book()
        book.start("x", et(2026, 10, 6, 12))
        assert "run_record_inconsistent" in reasons(book.verify())

    def test_a_persisted_collector_mismatch_is_invalid(self):
        book, _ = two_legit_days()
        book.log[2] = replace(book.log[2], collector_git_commit="d" * 40)
        assert "collector_commit_mismatch" in reasons(book.verify())
        book, _ = two_legit_days()
        book.log[1] = replace(book.log[1], collector_git_commit="d" * 40)
        assert "collector_commit_mismatch" in reasons(book.verify())

    # -- interrupted runs -----------------------------------------------------------------------

    def interrupted(self, *, orphans=2, gap=timedelta(seconds=5)):
        book = Book()
        book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR)
        started = et(2026, 10, 7, 7)
        book.start("crashed", started)
        orphan = [book.claim(TUE, started + gap, PRODUCERS[i]) for i in range(orphans)]
        return book, orphan

    def test_an_interrupted_run_with_valid_orphans_is_degraded(self):
        book, orphans = self.interrupted()
        report = book.verify()
        assert report.status == "degraded"
        assert reasons(report) == {"interrupted_run": 2}
        assert report.excluded_artifact_keys == {c.key for c in orphans}
        assert report.runs_interrupted == 1
        assert report.permits_collection and report.permits_validation

    def test_an_interrupted_run_without_orphans_is_ok(self):
        book = Book()
        book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR)
        book.start("crashed", et(2026, 10, 7, 7))
        report = book.verify()
        assert (report.status, report.runs_interrupted) == ("ok", 1)

    def test_orphan_outcomes_share_the_orphan_snapshot_clock(self):
        book, orphans = self.interrupted()
        monday = book.claims[0]
        book.outcome(monday, orphans[0].recorded_at)
        report = book.verify()
        assert report.status == "degraded"
        assert book.outcomes[0].key in report.excluded_outcome_keys

    def test_a_later_outcome_of_an_orphan_claim_is_excluded_too(self):
        book, orphans = self.interrupted()
        book.legit_run("r3", et(2026, 10, 8, 7), WED, outcomes_of=[(orphans[0], 1)])
        report = book.verify()
        assert report.status == "degraded"
        assert book.outcomes[-1].key in report.excluded_outcome_keys

    def test_a_run_start_does_not_bless_a_claim_after_the_next_entry(self):
        book, _ = self.interrupted(orphans=0)
        book.legit_run("r3", et(2026, 10, 7, 8), TUE)
        book.claim(TUE, et(2026, 10, 7, 8, 30), PRODUCERS[0], key="late-bypass")
        assert "unmatched_claim" in reasons(book.verify())

    def test_a_run_start_does_not_bless_a_claim_beyond_the_time_bound(self):
        book, _ = self.interrupted(orphans=1, gap=timedelta(hours=1, seconds=1))
        report = book.verify()
        assert report.status == "invalid" and reasons(report) == {"unmatched_claim": 1}

    def test_a_run_start_does_not_bless_a_claim_with_a_bad_record(self):
        book, _ = self.interrupted(orphans=0)
        book.claim(TUE, et(2026, 10, 7, 7, 0, 5), PRODUCERS[0], source="fake")
        assert {"unexpected_source", "unmatched_claim"} <= set(reasons(book.verify()))

    def test_a_run_start_does_not_bless_two_snapshots(self):
        book, _ = self.interrupted(orphans=1)
        book.claim(TUE, et(2026, 10, 7, 7, 0, 9), PRODUCERS[1])
        report = book.verify()
        assert report.status == "invalid" and reasons(report) == {"unmatched_claim": 2}

    def test_a_run_start_does_not_bless_more_than_one_tail_set(self):
        book, _ = self.interrupted(orphans=4)
        book.claim(TUE, book.claims[-1].recorded_at, ("assessment", "x" * 16))
        assert book.verify().status == "invalid"

    def test_an_orphan_outcome_at_another_clock_is_unmatched(self):
        book, orphans = self.interrupted()
        book.outcome(book.claims[0], orphans[0].recorded_at + timedelta(seconds=1))
        assert "unmatched_outcome" in reasons(book.verify())

    def test_a_deleted_completed_record_reads_as_a_crash(self):
        """Without a hash chain a removed *record* line is indistinguishable from a
        crash: its claims become degraded (excluded), never ok."""
        book, _ = two_legit_days()
        del book.log[3]
        report = book.verify()
        assert report.status == "degraded"
        assert len(report.excluded_artifact_keys) == 4


# == B1: host wall clock stepping backward ======================================================


class SteppingClock:
    """The first read returns ``first``; every later read returns ``first - back``."""

    def __init__(self, first, back):
        self.first, self.back, self.reads = first, back, 0

    def __call__(self):
        self.reads += 1
        return self.first if self.reads == 1 else self.first - self.back


TOLERANCE = timedelta(seconds=PROVENANCE_V1.interrupted_run_backward_tolerance_seconds)


class TestBackwardClock:
    """A legitimate run must survive a backward wall-clock step; nothing else may profit."""

    T = et(2026, 10, 6, 7, 30, 0).replace(microsecond=250000)

    @pytest.mark.parametrize("back", [
        timedelta(microseconds=1),
        timedelta(milliseconds=2),
        TOLERANCE,
        timedelta(minutes=10),                     # still inside the window
    ], ids=["1us", "2ms", "tolerance", "10min"])
    def test_a_completed_run_survives_a_backward_step(self, tmp_path, back):
        store = activated(tmp_path)
        clock = SteppingClock(self.T, back)
        report = collect(store, provider_factory=SessionProvider, now=clock,
                         run_id_factory=lambda: "stepped", repository=ProbeDouble())
        assert report.outcome == "completed"
        record = report.record
        assert all(s.built_at < record.started_at for s in record.symbols)  # really stepped
        assert record.finished_at < record.started_at
        verdict = health(store).provenance
        assert (verdict.status, verdict.findings) == ("ok", ())
        later, built = run(store, et(2026, 10, 7, 7))
        assert later.outcome == "completed" and len(built) == 1
        assert health(store).provenance.status == "ok"

    def test_microsecond_clock_readings_round_trip_exactly(self, tmp_path):
        store = activated(tmp_path)
        moment = et(2026, 10, 6, 7, 0, 0).replace(microsecond=123457)
        report, _ = run(store, moment)
        [spy] = [s for s in report.record.symbols if s.symbol == "SPY"]
        recorded = {a.recorded_at for a in spy_ledger(store).iter_artifacts(SPY)}
        assert recorded == {spy.built_at} and spy.built_at.microsecond == 123457
        assert store.read_run_log()[-1].symbols[0].built_at == spy.built_at
        assert health(store).provenance.status == "ok"

    def test_an_interrupted_run_with_a_stepped_clock_is_degraded(self, tmp_path, monkeypatch):
        store = activated(tmp_path)
        real = prospective.build_outcome_ledger

        class Crash(BaseException):
            pass

        def crashing(root):
            ledger = real(root)
            original = ledger.register_artifact
            written = []

            def register(artifact):
                if len(written) == 2:
                    raise Crash()
                written.append(artifact)
                return original(artifact)

            ledger.register_artifact = register
            return ledger

        monkeypatch.setattr(prospective, "build_outcome_ledger", crashing)
        with pytest.raises(Crash):
            collect(store, provider_factory=SessionProvider,
                    now=SteppingClock(self.T, timedelta(milliseconds=2)),
                    run_id_factory=lambda: "crashed", repository=ProbeDouble())
        monkeypatch.setattr(prospective, "build_outcome_ledger", real)
        start = store.read_run_log()[-1]
        orphans = list(spy_ledger(store).iter_artifacts(SPY))
        assert all(a.recorded_at < start.started_at for a in orphans)
        verdict = health(store).provenance
        assert verdict.status == "degraded"
        assert dict(verdict.reasons) == {"interrupted_run": 2}

    def test_a_bypass_after_a_stepped_legitimate_run_is_still_invalid(self, tmp_path):
        store = activated(tmp_path)
        collect(store, provider_factory=SessionProvider,
                now=SteppingClock(self.T, timedelta(milliseconds=2)),
                run_id_factory=lambda: "stepped", repository=ProbeDouble())
        bypass(store, et(2026, 10, 7, 7, 30))
        verdict = health(store).provenance
        assert verdict.status == "invalid"
        assert {"unmatched_claim", "unmatched_outcome"} <= set(dict(verdict.reasons))


class TestBackwardClockVerifier:
    """The same rules on synthetic metadata, each sensitive to one removed invariant."""

    def stepped_run(self, *, built_offset, finished_offset):
        book = Book()
        started = et(2026, 10, 6, 7, 30)
        built = started + built_offset
        book.start("r1", started)
        for producer in PRODUCERS:
            book.claim(MONDAY_BAR, built, producer)
        symbol_run = SymbolRun(symbol="SPY", status=CollectionStatus.OK, stage="done",
                               built_at=built, tail=MONDAY_BAR, bars=300, artifacts_new=4,
                               artifacts_duplicate=0, outcomes_new=0, outcomes_present=0,
                               pending=0, ineligible=0, refused=0, out_of_window=0)
        book.record("r1", started, symbol_run, finished_at=started + finished_offset)
        return book

    def test_built_at_before_started_at_is_ok(self):
        book = self.stepped_run(built_offset=-timedelta(milliseconds=2),
                                finished_offset=timedelta(seconds=1))
        assert book.verify().status == "ok"

    def test_finished_at_before_started_at_is_ok(self):
        book = self.stepped_run(built_offset=-timedelta(milliseconds=3),
                                finished_offset=-timedelta(milliseconds=2))
        assert book.verify().status == "ok"

    def test_built_at_after_finished_at_is_ok(self):
        book = self.stepped_run(built_offset=timedelta(seconds=2),
                                finished_offset=timedelta(seconds=1))
        assert book.verify().status == "ok"

    def test_a_stepped_run_still_requires_exact_attribution(self):
        book = self.stepped_run(built_offset=-timedelta(milliseconds=2),
                                finished_offset=timedelta(seconds=1))
        book.claim(TUE, et(2026, 10, 7, 7, 30), PRODUCERS[0])          # unrelated clock
        assert dict(book.verify().reasons) == {"unmatched_claim": 1}

    # -- the interrupted-run tolerance, attacked ------------------------------------------------

    def crashed(self):
        book = Book()
        book.legit_run("r0", et(2026, 10, 6, 7), MONDAY_BAR)
        self.started = et(2026, 10, 7, 7)
        book.start("crashed", self.started)
        return book

    def test_an_orphan_just_inside_the_tolerance_is_degraded(self):
        book = self.crashed()
        book.claim(TUE, self.started - TOLERANCE, PRODUCERS[0])
        book.claim(TUE, self.started - TOLERANCE, PRODUCERS[1])
        report = book.verify()
        assert report.status == "degraded"
        assert len(report.excluded_artifact_keys) == 2

    def test_an_orphan_one_millisecond_before_its_run_start_is_degraded(self):
        book = self.crashed()
        book.claim(TUE, self.started - timedelta(milliseconds=1), PRODUCERS[0])
        assert book.verify().status == "degraded"

    def test_an_orphan_beyond_the_tolerance_is_invalid(self):
        book = self.crashed()
        book.claim(TUE, self.started - TOLERANCE - timedelta(microseconds=1), PRODUCERS[0])
        report = book.verify()
        assert report.status == "invalid" and dict(report.reasons) == {"unmatched_claim": 1}

    def test_the_tolerance_never_reaches_a_completed_run(self):
        """A record a few seconds before a *completed* run's start is not attributed."""
        book = Book()
        claims, _ = book.legit_run("r1", et(2026, 10, 6, 7), MONDAY_BAR, claims=3)
        book.claim(MONDAY_BAR, et(2026, 10, 6, 7) - timedelta(seconds=2), PRODUCERS[3])
        report = book.verify()
        assert report.status == "invalid" and "unmatched_claim" in dict(report.reasons)

    def test_within_tolerance_but_after_the_next_entry_is_invalid(self):
        book = self.crashed()
        book.legit_run("r2", self.started + timedelta(seconds=30), TUE)
        book.claim(TUE, self.started + timedelta(seconds=40), PRODUCERS[0], key="bypass")
        assert book.verify().status == "invalid"

    def test_within_tolerance_with_a_wrong_tail_is_invalid(self):
        book = self.crashed()
        book.claim(MONDAY_BAR, self.started - timedelta(seconds=1), PRODUCERS[0])
        assert book.verify().status == "invalid"          # Monday is late for a Wednesday run

    def test_within_tolerance_with_a_wrong_producer_is_invalid(self):
        book = self.crashed()
        book.claim(TUE, self.started - timedelta(seconds=1),
                   ("observation", "trend_alignment", 9, "650add07184f8440"))
        report = book.verify()
        assert report.status == "invalid"
        assert {"unexpected_producer", "unmatched_claim"} <= set(dict(report.reasons))

    def test_within_tolerance_but_two_clocks_is_invalid(self):
        book = self.crashed()
        book.claim(TUE, self.started - timedelta(seconds=1), PRODUCERS[0])
        book.claim(TUE, self.started + timedelta(seconds=1), PRODUCERS[1])
        assert book.verify().status == "invalid"

    def test_no_tolerated_record_is_ever_ok(self):
        for offset in (timedelta(0), timedelta(seconds=1), TOLERANCE):
            book = self.crashed()
            book.claim(TUE, self.started - offset, PRODUCERS[0])
            assert book.verify().status == "degraded", offset


# == the real path ===============================================================================


class TestSupportedCollection:
    def test_supported_collection_is_ok_and_reported_by_health(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        run(store, et(2026, 10, 6, 8))           # duplicate
        run(store, et(2026, 10, 7, 7))           # Tuesday + Monday h1 outcomes
        report = health(store)
        assert report.provenance.status == "ok"
        assert report.provenance.claims_checked == 40
        assert report.provenance.outcomes_checked == 20
        code, lines, _ = cli(["health"], store.root)
        assert code == EXIT_OK
        assert provenance_line(lines)["provenance"] == "ok"
        assert provenance_line(lines)["provenance_policy_fingerprint"] == \
            PROVENANCE_V1.fingerprint

    def test_matured_collection_is_ok(self, tmp_path):
        with pytest.MonkeyPatch.context() as patch:
            install_offline_guard(patch)
            root = build_matured_root(tmp_path, 24)
        report = health(build_prospective_store(root), definition=SPY_ONLY)
        assert report.provenance.status == "ok"
        assert dict(report.symbols[0].outcomes_matured)[20] > 0

    def test_a_completed_run_is_preceded_by_its_run_start(self, tmp_path):
        store = activated(tmp_path)
        report, _ = run(store, TUESDAY_RUN)
        start, record = store.read_run_log()
        assert isinstance(start, RunStart) and record == report.record
        assert (start.run_id, start.started_at) == (record.run_id, record.started_at)
        assert start.provenance_policy_fingerprint == PROVENANCE_V1.fingerprint

    def test_the_run_start_is_durable_before_the_provider_exists(self, tmp_path):
        store = activated(tmp_path)
        seen = []

        def factory():
            seen.append([type(e).__name__ for e in store.read_run_log()])
            return SessionProvider()

        collect(store, provider_factory=factory, now=Clock(TUESDAY_RUN),
                repository=ProbeDouble())
        assert seen == [["RunStart"]]

    def test_a_crash_after_run_start_before_the_provider_leaves_ok_provenance(self, tmp_path):
        store = activated(tmp_path)

        class Crash(BaseException):
            pass

        def factory():
            raise Crash()

        with pytest.raises(Crash):
            collect(store, provider_factory=factory, now=Clock(TUESDAY_RUN),
                    repository=ProbeDouble())
        report = health(store)
        assert (report.provenance.status, report.runs_interrupted) == ("ok", 1)
        assert not store.ledger_exists()
        later, _ = run(store, et(2026, 10, 6, 8))
        assert later.outcome == "completed"

    def test_a_config_mismatch_refusal_does_not_poison_provenance(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        run(store, et(2026, 10, 6, 8), definition=replace(COLLECTION_V1, universe=("SPY",)))
        assert health(store).provenance.status == "ok"


class TestGenericBypass:
    """N2: ``python -m src.cli.outcome_refresh ... --outcome-root <prospective ledger>``."""

    def test_a_bypass_inside_the_window_is_detected_and_blocks_collection(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        code, _ = bypass(store, et(2026, 10, 7, 7, 30))      # inside 00:30-09:00 ET
        assert code == 0
        report = health(store)
        assert report.provenance.status == "invalid"
        assert {"unmatched_claim", "unmatched_outcome"} <= set(dict(report.provenance.reasons))
        assert report.provenance.first_finding.symbol == "SPY"

        before = files(store.ledger_root)
        refused, built = run(store, et(2026, 10, 8, 7))
        assert refused.outcome == "provenance_invalid"
        assert built == [] and refused.record.symbols == ()
        assert files(store.ledger_root) == before
        assert store.read_run_log()[-1].run_status is RunStatus.PROVENANCE_INVALID

    def test_a_bypass_outside_the_window_is_detected(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        before = len(list(spy_ledger(store).iter_artifacts(SPY)))
        bypass(store, et(2026, 10, 7, 18))          # Wednesday evening: claims Tuesday
        assert len(list(spy_ledger(store).iter_artifacts(SPY))) == before + 4
        found = dict(health(store).provenance.reasons)
        assert {"claim_outside_window", "outcome_outside_window", "unmatched_claim",
                "unmatched_outcome"} <= set(found)

    def test_a_bypass_that_writes_nothing_raises_no_false_alarm(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        before = files(store.ledger_root)
        bypass(store, et(2026, 10, 6, 18))          # Tuesday's bar has not settled yet
        assert files(store.ledger_root) == before
        assert health(store).provenance.status == "ok"

    def test_a_bypass_before_any_supported_run_is_detected(self, tmp_path):
        store = activated(tmp_path)
        bypass(store, et(2026, 10, 6, 6))
        report = health(store)
        assert report.provenance.status == "invalid"
        assert dict(report.provenance.reasons)["unmatched_claim"] == 4
        refused, built = run(store, TUESDAY_RUN)
        assert (refused.outcome, built) == ("provenance_invalid", [])

    def test_a_bypass_on_another_interval_creates_an_unexpected_partition(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        (store.ledger_root / "SPY" / "1wk" / "raw").mkdir(parents=True)
        report = health(store)
        assert report.provenance.status == "invalid"
        assert "unexpected_partition" in dict(report.provenance.reasons)

    def test_a_bypass_symbol_outside_the_universe_is_detected(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        bypass(store, et(2026, 10, 7, 7, 30), symbols=("AAPL",))
        report = health(store)
        assert report.provenance.status == "invalid"
        assert report.provenance.first_finding.component.startswith("ledger:AAPL")

    def test_the_cli_reports_and_exits_without_leaking(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        bypass(store, et(2026, 10, 7, 7, 30))
        code, lines, err = cli(["health"], store.root)
        assert code == EXIT_FAILED
        fields_ = provenance_line(lines)
        assert fields_["provenance"] == "invalid"
        assert "unmatched_claim:" in fields_["provenance_reasons"]
        assert fields_["provenance_symbol"] == "SPY"
        text = "\n".join(lines) + err
        assert "7777" not in text
        for artifact in spy_ledger(store).iter_artifacts(SPY):
            assert f"={artifact.state.value}" not in text
        code, lines, _ = cli(["collect"], store.root, provider=SessionProvider(),
                             now=et(2026, 10, 8, 7))
        assert code == EXIT_REFUSED
        summary = parse(lines[-1])
        assert (summary["run_status"], summary["provenance"]) == ("provenance_invalid",
                                                                    "invalid")

    def test_nothing_is_repaired_deleted_or_rewritten(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        bypass(store, et(2026, 10, 7, 7, 30))
        before = files(store.ledger_root)
        for _ in range(2):
            health(store)
            run(store, et(2026, 10, 8, 7))
        assert files(store.ledger_root) == before


class TestDeletionsAndCorruption:
    def test_a_deleted_ledger_line_is_invalid(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        path = store.ledger_root / "SPY" / "1d" / "raw" / "artifacts.jsonl"
        path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:3]))
        report = health(store)
        assert dict(report.provenance.reasons) == {"missing_claimed_artifacts": 1}
        refused, built = run(store, et(2026, 10, 7, 7))
        assert (refused.outcome, built) == ("provenance_invalid", [])

    def test_a_deleted_outcome_line_is_invalid(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        run(store, et(2026, 10, 7, 7))
        path = store.ledger_root / "QQQ" / "1d" / "raw" / "outcomes.jsonl"
        path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:-1]))
        assert dict(health(store).provenance.reasons) == {"missing_claimed_outcomes": 1}

    def test_a_deleted_run_start_line_is_invalid(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        lines = store.run_log_path.read_bytes().splitlines(keepends=True)
        store.run_log_path.write_bytes(b"".join(lines[1:]))
        report = health(store)
        assert report.provenance.status == "invalid"
        assert "run_record_inconsistent" in dict(report.provenance.reasons)

    def test_a_corrupt_run_log_is_unknown_and_never_appended_to(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        store.run_log_path.write_bytes(store.run_log_path.read_bytes() + b'{"torn"')
        corrupt = store.run_log_path.read_bytes()
        report = health(store)
        assert (report.status, report.provenance.status) == ("corrupt", "unknown")
        assert dict(report.provenance.reasons) == {"integrity_corrupt": 1}
        refused, built = run(store, et(2026, 10, 7, 7))
        assert (refused.outcome, refused.record, built) == ("corrupt_run_log", None, [])
        assert store.run_log_path.read_bytes() == corrupt
        code, lines, _ = cli(["collect"], store.root, provider=SessionProvider(),
                             now=et(2026, 10, 7, 7))
        assert code == EXIT_REFUSED
        assert parse(lines[0]) == {"collect": "refused", "reason": "corrupt_run_log"}
        assert store.run_log_path.read_bytes() == corrupt


class TestInterruptedRun:
    def test_a_crash_after_ledger_writes_is_degraded_and_collection_continues(self, tmp_path,
                                                                              monkeypatch):
        store = activated(tmp_path)
        real = prospective.build_outcome_ledger

        class Crash(BaseException):
            pass

        def crashing(root):
            ledger = real(root)
            original = ledger.register_artifact
            written = []

            def register(artifact):
                if len(written) == 3:
                    raise Crash()
                written.append(artifact)
                return original(artifact)

            ledger.register_artifact = register
            return ledger

        monkeypatch.setattr(prospective, "build_outcome_ledger", crashing)
        with pytest.raises(Crash):
            run(store, TUESDAY_RUN)
        monkeypatch.setattr(prospective, "build_outcome_ledger", real)

        report = health(store)
        assert report.provenance.status == "degraded"
        assert dict(report.provenance.reasons) == {"interrupted_run": 3}
        assert len(report.provenance.excluded_artifact_keys) == 3
        assert report.runs_interrupted == 1
        code, lines, _ = cli(["health"], store.root)
        assert code == EXIT_FAILED and provenance_line(lines)["provenance"] == "degraded"

        resumed, built = run(store, et(2026, 10, 6, 8))
        assert resumed.outcome == "completed" and len(built) == 1
        assert resumed.provenance.status == "degraded"
        assert health(store).provenance.status == "degraded"


# == N14: collector identity =====================================================================


class TestCollectorIdentity:
    @pytest.mark.parametrize("repository, outcome", [
        (ProbeDouble(head="d" * 40), "collector_commit_mismatch"),
        (ProbeDouble(clean=False), "dirty_collector_tree"),
        (ProbeDouble(head="d" * 40, clean=False), "dirty_collector_tree"),
    ])
    def test_a_foreign_collector_makes_no_provider_call(self, tmp_path, repository, outcome):
        store = activated(tmp_path)
        provider = SessionProvider()
        report, built = run(store, TUESDAY_RUN, provider=provider, repository=repository)
        assert report.outcome == outcome
        assert built == [] and provider.calls == []
        assert not store.ledger_exists()
        assert [type(e).__name__ for e in store.read_run_log()] == ["RunRecord"]
        assert report.record.symbols == ()
        assert health(store).runs_refused_collector == 1
        assert health(store).provenance.status == "ok"

    def test_an_uninspectable_repository_is_refused(self, tmp_path):
        class Broken(ProbeDouble):
            def repository_state(self):
                raise RepositoryProbeError("git missing")

        store = activated(tmp_path)
        report, built = run(store, TUESDAY_RUN, repository=Broken())
        assert (report.outcome, built) == ("collector_unverified", [])

    def test_switching_branch_after_activation_is_refused_through_the_cli(self, tmp_path):
        store = activated(tmp_path)
        provider = SessionProvider()
        code, lines, _ = cli(["collect"], store.root, provider=provider,
                             now=TUESDAY_RUN, repository=ProbeDouble(head="e" * 40))
        assert code == EXIT_REFUSED
        assert parse(lines[-1])["run_status"] == "collector_commit_mismatch"
        assert provider.calls == []

    def test_the_default_probe_is_the_real_repository_and_refuses_a_fake_commit(self, tmp_path):
        """Without an injected probe the collector inspects this repository, whose
        HEAD is not the fixture's collector commit: refused, no provider."""
        store = activated(tmp_path)
        built = []
        report = collect(store, provider_factory=lambda: built.append(1),
                         now=Clock(TUESDAY_RUN))
        assert report.outcome in ("collector_commit_mismatch", "dirty_collector_tree")
        assert built == []


# == N4: locking ==================================================================================


class TestLocking:
    def test_activation_creates_the_lock_and_health_creates_nothing(self, tmp_path):
        store = activated(tmp_path)
        assert store.lock_exists()
        before = files(store.root)
        assert health(store).provenance.status == "ok"
        assert files(store.root) == before
        assert sorted(p.name for p in store.root.iterdir()) == ["activation.json",
                                                                "collect.lock"]

    def test_health_during_an_exclusive_collect_is_in_progress_not_corrupt(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        with store.exclusive_lock():
            report = health(store)
            code, lines, _ = cli(["health"], store.root)
        assert (report.status, report.integrity) == ("collect_in_progress", "unknown")
        assert dict(report.provenance.reasons) == {"collect_in_progress": 1}
        assert report.corrupt_component is None
        assert code == EXIT_REFUSED
        assert provenance_line(lines)["provenance"] == "unknown"

    def test_health_called_mid_collection_sees_in_progress(self, tmp_path):
        store = activated(tmp_path)
        seen = []

        def factory():
            seen.append(health(store).status)
            return SessionProvider()

        collect(store, provider_factory=factory, now=Clock(TUESDAY_RUN),
                repository=ProbeDouble())
        assert seen == ["collect_in_progress"]
        assert health(store).provenance.status == "ok"

    def test_collect_waits_through_a_short_shared_lock(self, tmp_path):
        store = activated(tmp_path)
        reader = store.shared_lock()
        reader.__enter__()
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            reader.__exit__(None, None, None)

        report, built = run(store, TUESDAY_RUN, lock_sleep=sleep)
        assert report.outcome == "completed" and len(built) == 1
        assert sleeps == [0.25]

    def test_collect_times_out_safely_after_the_bounded_wait(self, tmp_path):
        store = activated(tmp_path)
        clock = {"t": 1000.0}
        waited = []

        def sleep(seconds):
            waited.append(seconds)
            clock["t"] += seconds

        with store.shared_lock():
            report, built = run(store, TUESDAY_RUN, lock_monotonic=lambda: clock["t"],
                                lock_sleep=sleep)
        assert (report.outcome, report.record, built) == ("locked", None, [])
        assert sum(waited) == pytest.approx(30.0)
        assert store.read_run_log() == ()

    def test_the_default_wait_is_thirty_seconds(self):
        import inspect
        assert inspect.signature(collect).parameters["lock_timeout"].default == 30.0

    def test_a_missing_lock_fails_closed_and_is_never_recreated(self, tmp_path):
        store = activated(tmp_path)
        store.lock_path.unlink()
        report, built = run(store, TUESDAY_RUN)
        assert (report.outcome, report.record, built) == ("lock_missing", None, [])
        status = health(store)
        assert (status.status, status.provenance.status) == ("lock_missing", "unknown")
        code, _, _ = cli(["health"], store.root)
        assert code == EXIT_FAILED
        assert not store.lock_exists()
        assert store.read_run_log() == ()

    def test_a_failed_lock_creation_leaves_no_manifest(self, tmp_path, monkeypatch):
        store = build_prospective_store(tmp_path / "v1")
        real_open = os.open

        def failing(path, *args, **kwargs):
            if str(path).endswith("collect.lock"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("src.prospective.store.os.open", failing)
        with pytest.raises(ActivationRefused) as caught:
            activate(store, collector_git_commit=COLLECTOR_SHA,
                     m2_preregistration_git_commit=M2_SHA, repository=ProbeDouble(),
                     versions=VERSIONS, now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "activation_write_failed"
        monkeypatch.setattr("src.prospective.store.os.open", real_open)
        assert not store.manifest_path.exists()
        report, built = run(store, TUESDAY_RUN)
        assert (report.outcome, built) == ("not_activated", [])

    def test_a_failed_manifest_write_after_the_lock_is_not_activated(self, tmp_path,
                                                                     monkeypatch):
        store = build_prospective_store(tmp_path / "v1")
        real_open = os.open

        def failing(path, *args, **kwargs):
            if str(path).endswith("activation.json"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("src.prospective.store.os.open", failing)
        with pytest.raises(ActivationRefused) as caught:
            activate(store, collector_git_commit=COLLECTOR_SHA,
                     m2_preregistration_git_commit=M2_SHA, repository=ProbeDouble(),
                     versions=VERSIONS, now=lambda: ACTIVATED_AT)
        assert caught.value.reason == "activation_write_failed"
        monkeypatch.setattr("src.prospective.store.os.open", real_open)
        assert sorted(p.name for p in store.root.iterdir()) == ["collect.lock"]
        assert health(store).status == "not_activated"
        with pytest.raises(ActivationRefused) as again:
            activate(store, collector_git_commit=COLLECTOR_SHA,
                     m2_preregistration_git_commit=M2_SHA, repository=ProbeDouble(),
                     versions=VERSIONS, now=lambda: ACTIVATED_AT)
        assert again.value.reason == "already_activated"


# == blindness and architecture ==================================================================


SRC = REPO / "src"
PROVENANCE_PY = SRC / "prospective" / "provenance.py"
APPLICATION_PY = SRC / "application" / "prospective.py"

PROHIBITED = {
    "state", "reason_codes", "forward_return", "reference_price", "future_price",
    "positive_count", "negative_count", "zero_count", "mean_forward_return",
    "median_forward_return", "is_evaluable", "assessment", "observations", "close", "open",
    "high", "low", "volume", "hit_rate",
}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path, name):
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _attributes(node):
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


class TestBlindness:
    def test_the_provenance_module_names_no_research_field(self):
        module = _tree(PROVENANCE_PY)
        assert not _attributes(module) & PROHIBITED
        names = {n.id for n in ast.walk(module) if isinstance(n, ast.Name)}
        assert not names & {"ResearchState", "AssessmentState", "summarize_outcomes"}

    def test_the_provenance_module_depends_on_its_package_only(self):
        for node in ast.walk(_tree(PROVENANCE_PY)):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                assert node.module in {"__future__", "collections", "dataclasses", "datetime",
                                       "typing", "hashlib", "json"}, node.module
            if isinstance(node, ast.Import):
                assert {a.name for a in node.names} <= {"hashlib", "json"}

    def test_the_metadata_types_cannot_carry_a_claim_or_a_measurement(self):
        for cls in (ClaimMeta, OutcomeMeta, PartitionMeta):
            assert not {f.name for f in fields(cls)} & PROHIBITED, cls.__name__

    @pytest.mark.parametrize("name, allowed", [
        ("_claim_meta", {"kind", "value", "hypothesis_id", "hypothesis_version",
                         "hypothesis_fingerprint", "policy_fingerprint", "symbol",
                         "artifact_key", "interval", "basis", "timestamp", "data_cutoff",
                         "recorded_at", "source", "origin"}),
        ("_outcome_meta", {"artifact", "symbol", "outcome_key", "artifact_key",
                           "spec_fingerprint", "horizon_bars", "evaluation_version",
                           "evaluated_at"}),
    ])
    def test_metadata_extraction_reads_only_allowlisted_attributes(self, name, allowed):
        assert _attributes(_function(APPLICATION_PY, name)) <= allowed

    def test_matured_health_after_a_bypass_leaks_no_value(self, tmp_path):
        with pytest.MonkeyPatch.context() as patch:
            install_offline_guard(patch)
            root = build_matured_root(tmp_path, 24)
        store = build_prospective_store(root)
        out, err = io.StringIO(), io.StringIO()
        outcome_refresh.main(["SPY", "--interval", "1d", "--outcome-root",
                              str(store.ledger_root)], provider=SessionProvider(),
                             now=Clock(et(2026, 11, 9, 7, 45)), stdout=out, stderr=err)
        report = health(store, definition=SPY_ONLY)
        assert report.provenance.status == "invalid"
        lines = [*prospective_cli_lines(report)]
        text = "\n".join(lines)
        values = set()
        ledger = spy_ledger(store)
        for outcome in ledger.iter_outcomes(SPY):
            for number in (outcome.forward_return, outcome.reference_price, outcome.future_price):
                values.update({repr(number), f"{number:.6f}", f"{number:.4f}"})
        for artifact in ledger.iter_artifacts(SPY):
            values.add(f"={artifact.state.value}")
        assert values
        assert not [value for value in values if value in text]
        assert "7777" not in text


def prospective_cli_lines(report):
    from src.cli.prospective import format_health
    return format_health(report)


def test_the_live_root_is_absent():
    assert not LIVE_ROOT.exists()
    assert not (REPO / "data" / "prospective").exists()
