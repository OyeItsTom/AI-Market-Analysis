"""Prospective Collection v1 orchestration: activate, collect, health -- all offline.

Every test runs the real path (``build_snapshot`` -> ``refresh_outcomes`` ->
``JsonlOutcomeLedger``) against a temporary root with a session-shaped fake
provider and an injected clock. The autouse guard fails any test that opens
a socket, reaches yfinance, constructs the default provider or touches the
live ``data/prospective/v1``.
"""

from __future__ import annotations

import itertools
import json
import shutil
from dataclasses import replace
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
from src.data.provider import ProviderUnavailableError
from src.data.series import PriceBasis
from src.data.models import Interval
from src.outcomes import LedgerPartition
from src.prospective import COLLECTION_V1, CollectionStatus, RunStatus
from tests.prospective_fixtures import (  # noqa: F401 - autouse guard
    COLLECTOR_SHA,
    M2_SHA,
    SPY_ONLY,
    UTC,
    VERSIONS,
    Clock,
    ProbeDouble,
    build_matured_root,
    SessionProvider,
    et,
    install_offline_guard,
    ny_midnight,
    offline_and_no_live_root,
)

ACTIVATED_AT = et(2026, 10, 5, 15)      # Monday afternoon
TUESDAY_RUN = et(2026, 10, 6, 7)        # claims Monday 2026-10-05
MONDAY_BAR = ny_midnight(date(2026, 10, 5))


def activated(tmp_path, *, at=ACTIVATED_AT, definition=COLLECTION_V1):
    store = build_prospective_store(tmp_path / "v1")
    activate(store, collector_git_commit=COLLECTOR_SHA, m2_preregistration_git_commit=M2_SHA,
             repository=ProbeDouble(), versions=VERSIONS, now=lambda: at, definition=definition)
    return store


#: Run ids are unique across a test session, as uuid4 ids are in production.
_RUN_IDS = itertools.count()


def run(store, moment, provider=None, *, definition=COLLECTION_V1, clock=None,
        repository=None, **kwargs):
    provider = provider if provider is not None else SessionProvider()
    clock = clock if clock is not None else Clock(moment)
    built = []

    def factory():
        built.append(provider)
        return provider

    report = collect(store, provider_factory=factory, now=clock,
                     run_id_factory=lambda: f"run-{next(_RUN_IDS)}", definition=definition,
                     repository=repository if repository is not None else ProbeDouble(),
                     **kwargs)
    return report, built


def statuses(report):
    return [entry.status for entry in report.record.symbols]


def partition(symbol="SPY"):
    return LedgerPartition(symbol=symbol, interval=Interval.DAY_1, basis=PriceBasis.RAW)


def ledger(store):
    return prospective.build_outcome_ledger(store.ledger_root)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# -- activation -------------------------------------------------------------------------------


class TestActivation:
    def test_writes_only_the_lock_and_the_manifest(self, tmp_path):
        store = activated(tmp_path)
        assert sorted(files(store.root)) == ["activation.json", "collect.lock"]
        assert store.lock_path.read_bytes() == b""
        manifest = store.read_manifest()
        assert manifest.activated_at == ACTIVATED_AT
        assert manifest.collection_fingerprint == COLLECTION_V1.fingerprint
        assert manifest.collector_git_commit == COLLECTOR_SHA
        assert manifest.m2_preregistration_git_commit == M2_SHA
        assert manifest.hypothesis_fingerprints == {
            "trend_alignment": "650add07184f8440",
            "momentum_in_trend_context": "6589cb8021b76574",
            "trend_crossover": "f1126ca778e6f7ce",
        }
        assert manifest.dependency_versions == VERSIONS

    def test_activate_takes_no_provider_at_all(self):
        import inspect

        parameters = inspect.signature(activate).parameters
        assert not [name for name in parameters if "provider" in name]

    def test_double_activation_is_refused_and_changes_nothing(self, tmp_path):
        store = activated(tmp_path)
        before = files(store.root)
        with pytest.raises(ActivationRefused) as caught:
            activated(tmp_path, at=et(2026, 10, 9, 15))
        assert caught.value.reason == "already_activated"
        assert files(store.root) == before

    @pytest.mark.parametrize("kwargs, reason", [
        ({"m2_preregistration_git_commit": ""}, "invalid_commit"),
        ({"m2_preregistration_git_commit": "B" * 40}, "invalid_commit"),
        ({"collector_git_commit": "abc123"}, "invalid_commit"),
        ({"collector_git_commit": "c" * 40}, "collector_commit_mismatch"),
        ({"repository": ProbeDouble(clean=False)}, "dirty_repository"),
        ({"repository": ProbeDouble(ancestors=(COLLECTOR_SHA,))}, "m2_commit_not_in_history"),
        ({"definition": replace(COLLECTION_V1, warmup_bars=50)}, "config_mismatch"),
    ])
    def test_refusals_write_nothing(self, tmp_path, kwargs, reason):
        arguments = dict(collector_git_commit=COLLECTOR_SHA, m2_preregistration_git_commit=M2_SHA,
                         repository=ProbeDouble(), versions=VERSIONS, now=lambda: ACTIVATED_AT)
        arguments.update(kwargs)
        store = build_prospective_store(tmp_path / "v1")
        with pytest.raises(ActivationRefused) as caught:
            activate(store, **arguments)
        assert caught.value.reason == reason
        assert not store.root_exists()


# -- collection refusals before any provider ----------------------------------------------------


class TestRefusedRuns:
    def test_not_activated_touches_nothing(self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        report, built = run(store, TUESDAY_RUN)
        assert (report.outcome, report.record, built) == ("not_activated", None, [])
        assert not store.root_exists()

    def test_an_invalid_manifest_is_refused(self, tmp_path):
        store = activated(tmp_path)
        store.manifest_path.write_bytes(b"{}\n")
        report, built = run(store, TUESDAY_RUN)
        assert (report.outcome, report.record, built) == ("invalid_manifest", None, [])
        assert sorted(files(store.root)) == ["activation.json", "collect.lock"]

    @pytest.mark.parametrize("moment", [
        et(2026, 10, 6, 0, 29, 59), et(2026, 10, 6, 9, 0, 0), et(2026, 10, 6, 16, 30),
        et(2026, 10, 5, 23, 59, 59),
    ])
    def test_outside_the_window_no_provider_no_claim_one_record(self, tmp_path, moment):
        store = activated(tmp_path)
        report, built = run(store, moment)
        assert report.outcome == "outside_collection_window"
        assert built == []
        assert report.record.run_status is RunStatus.OUTSIDE_COLLECTION_WINDOW
        assert report.record.symbols == ()
        assert not store.ledger_exists()
        assert len(list(store.iter_runs())) == 1

    def test_fingerprint_drift_is_refused_before_any_provider(self, tmp_path):
        store = activated(tmp_path)
        drifted = replace(COLLECTION_V1, universe=("SPY", "QQQ"))
        report, built = run(store, TUESDAY_RUN, definition=drifted)
        assert report.outcome == "config_mismatch"
        assert built == [] and not store.ledger_exists()
        assert report.record.collection_fingerprint == drifted.fingerprint

    def test_live_code_drift_is_refused(self, tmp_path, monkeypatch):
        store = activated(tmp_path)
        monkeypatch.setattr(prospective, "live_configuration_mismatches",
                            lambda definition=COLLECTION_V1: ("hypotheses",))
        report, built = run(store, TUESDAY_RUN)
        assert report.outcome == "config_mismatch" and built == []

    def test_a_held_lock_refuses_without_provider_or_record(self, tmp_path):
        store = activated(tmp_path)
        with store.exclusive_lock():
            report, built = run(store, TUESDAY_RUN, lock_timeout=0)
        assert (report.outcome, report.record, built) == ("locked", None, [])
        assert list(store.iter_runs()) == []
        assert not store.ledger_exists()


# -- collection --------------------------------------------------------------------------------


class TestCollection:
    def test_first_post_activation_tail_is_claimed_for_every_symbol(self, tmp_path):
        store = activated(tmp_path)
        provider = SessionProvider()
        report, built = run(store, TUESDAY_RUN, provider)
        assert report.outcome == "completed" and len(built) == 1
        assert statuses(report) == [CollectionStatus.OK] * 5
        assert [c["symbol"] for c in provider.calls] == ["SPY", "QQQ", "IWM", "TLT", "GLD"]
        assert all(c["include_unsettled"] is False for c in provider.calls)
        for entry in report.record.symbols:
            assert entry.tail == MONDAY_BAR
            assert (entry.artifacts_new, entry.pending, entry.missed_tails) == (4, 12, ())
        artifacts = list(ledger(store).iter_artifacts(partition("SPY")))
        assert {a.timestamp for a in artifacts} == {MONDAY_BAR}
        assert {a.recorded_at for a in artifacts} == {TUESDAY_RUN}

    def test_the_dashboard_ledger_is_never_used(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        assert store.ledger_root == tmp_path / "v1" / "ledger"
        assert sorted(p.name for p in store.ledger_root.iterdir()) == sorted(
            COLLECTION_V1.universe)
        assert prospective.DEFAULT_PROSPECTIVE_ROOT.parts[-3:] == ("data", "prospective", "v1")
        assert "outcomes" not in prospective.DEFAULT_PROSPECTIVE_ROOT.parts

    def test_pre_activation_tail_writes_no_ledger(self, tmp_path):
        store = activated(tmp_path, at=et(2026, 10, 6, 0, 10))  # Monday settled at 00:00
        report, _ = run(store, TUESDAY_RUN)
        assert statuses(report) == [CollectionStatus.PRE_ACTIVATION] * 5
        assert not store.ledger_exists()
        assert report.record.symbols_pre_activation == 5 and report.record.symbols_failed == 0

    def test_a_repeat_run_is_a_duplicate_and_changes_no_ledger_byte(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        before = files(store.ledger_root)
        report, _ = run(store, et(2026, 10, 6, 8))
        assert statuses(report) == [CollectionStatus.DUPLICATE_ALREADY_EXISTS] * 5
        assert files(store.ledger_root) == before
        assert len(list(store.iter_runs())) == 2

    def test_missed_days_are_reported_and_never_claimed(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)                       # claims Mon 10-05
        report, _ = run(store, et(2026, 10, 9, 7))    # Fri: claims Thu 10-08
        tue, wed, thu = (ny_midnight(date(2026, 10, d)) for d in (6, 7, 8))
        for entry in report.record.symbols:
            assert entry.status is CollectionStatus.OK
            assert entry.tail == thu
            assert entry.missed_tails == (tue, wed)
        claimed = {a.timestamp for a in ledger(store).iter_artifacts(partition())}
        assert claimed == {MONDAY_BAR, thu}

    def test_a_stale_unclaimed_tail_is_never_claimed_late(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        before = files(store.ledger_root)
        # Thursday morning, but the feed stops at Tuesday: Wednesday's session passed.
        report, _ = run(store, et(2026, 10, 8, 7), SessionProvider(lag_until=date(2026, 10, 6)))
        assert statuses(report) == [CollectionStatus.STALE_TAIL] * 5
        assert all(e.tail == ny_midnight(date(2026, 10, 6)) for e in report.record.symbols)
        assert files(store.ledger_root) == before
        assert report.record.symbols_failed == 5

    def test_a_held_tail_from_a_lagging_feed_is_only_a_duplicate(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        report, _ = run(store, et(2026, 10, 7, 7), SessionProvider(lag_until=date(2026, 10, 5)))
        assert statuses(report) == [CollectionStatus.DUPLICATE_ALREADY_EXISTS] * 5

    @staticmethod
    def _crash_after_two_spy_claims(store, monkeypatch):
        """A real crash: the process dies after two of SPY's four registrations.

        The run start is durable, the completed run record never is, and the
        two orphan claims are exactly what the collector wrote.
        """
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
            run(store, TUESDAY_RUN)
        monkeypatch.setattr(prospective, "build_outcome_ledger", real)
        assert len(list(ledger(store).iter_artifacts(partition("SPY")))) == 2

    def test_a_partial_tail_is_never_completed_late(self, tmp_path, monkeypatch):
        store = activated(tmp_path)
        self._crash_after_two_spy_claims(store, monkeypatch)
        before = files(store.ledger_root)
        report, _ = run(store, et(2026, 10, 7, 7), SessionProvider(lag_until=date(2026, 10, 5)))
        assert report.provenance.status == "degraded"
        assert statuses(report) == [CollectionStatus.STALE_TAIL] * 5
        assert files(store.ledger_root) == before

    def test_a_partial_tail_is_completed_while_still_current(self, tmp_path, monkeypatch):
        store = activated(tmp_path)
        self._crash_after_two_spy_claims(store, monkeypatch)
        report, _ = run(store, et(2026, 10, 6, 8))
        assert report.provenance.status == "degraded"
        assert statuses(report) == [CollectionStatus.OK] * 5
        assert (report.record.symbols[0].artifacts_new,
                report.record.symbols[0].artifacts_duplicate) == (2, 2)
        assert all((e.artifacts_new, e.artifacts_duplicate) == (4, 0)
                   for e in report.record.symbols[1:])

    def test_holiday_after_an_unclaimed_friday_is_refused_conservatively(self, tmp_path):
        store = activated(tmp_path, at=et(2026, 10, 9, 1))  # before Friday settles
        holiday = date(2026, 10, 12)
        report, _ = run(store, et(2026, 10, 13, 7), SessionProvider(missing={holiday}))
        assert statuses(report) == [CollectionStatus.STALE_TAIL] * 5
        assert not store.ledger_exists()

    def test_weekend_runs_claim_friday_then_repeat_it(self, tmp_path):
        store = activated(tmp_path, at=et(2026, 10, 9, 1))
        saturday, _ = run(store, et(2026, 10, 10, 7))
        sunday, _ = run(store, et(2026, 10, 11, 7))
        monday, _ = run(store, et(2026, 10, 12, 7))
        assert statuses(saturday) == [CollectionStatus.OK] * 5
        assert statuses(sunday) == statuses(monday) == [
            CollectionStatus.DUPLICATE_ALREADY_EXISTS] * 5

    def test_a_non_midnight_timestamp_convention_is_refused(self, tmp_path):
        store = activated(tmp_path)
        utc_midnight = SessionProvider(
            stamp=lambda day: ny_midnight(day).replace(hour=0, minute=0) + timedelta(hours=1))
        report, _ = run(store, TUESDAY_RUN, utc_midnight)
        assert statuses(report) == [CollectionStatus.TIMESTAMP_CONVENTION] * 5
        assert not store.ledger_exists()

    def test_provider_failure_and_empty_snapshot(self, tmp_path):
        store = activated(tmp_path)
        report, _ = run(store, TUESDAY_RUN,
                        SessionProvider(fail=ProviderUnavailableError("upstream refused 7777.12")))
        assert statuses(report) == [CollectionStatus.PROVIDER_FAILURE] * 5
        assert report.record.symbols[0].error_class == "ApplicationError.provider"
        assert "7777" not in store.run_log_path.read_text()
        report, _ = run(store, TUESDAY_RUN, SessionProvider(empty=True))
        assert statuses(report) == [CollectionStatus.NO_SETTLED_BAR] * 5
        assert not store.ledger_exists()

    def test_a_provider_that_is_not_the_frozen_one_is_refused(self, tmp_path):
        store = activated(tmp_path)
        report, _ = run(store, TUESDAY_RUN, SessionProvider(name="fake"))
        assert statuses(report) == [CollectionStatus.CONFIG_MISMATCH] * 5
        assert not store.ledger_exists()

    def test_the_window_closing_mid_run_stops_later_symbols(self, tmp_path):
        store = activated(tmp_path)
        clock = Clock(et(2026, 10, 6, 8, 59, 59))

        class Closing(SessionProvider):
            def get_bars(self, symbol, *args, **kwargs):
                bars = super().get_bars(symbol, *args, **kwargs)
                if symbol == "QQQ":
                    clock.set(et(2026, 10, 6, 9, 0, 0))
                return bars

        report, _ = run(store, None, Closing(), clock=clock)
        assert statuses(report) == [CollectionStatus.OK, CollectionStatus.OK] + [
            CollectionStatus.OUTSIDE_COLLECTION_WINDOW] * 3
        assert all(entry.stage == "window" for entry in report.record.symbols[2:])
        assert not (store.ledger_root / "IWM").exists()

    def test_a_corrupt_partition_refuses_the_whole_run_and_is_left_untouched(self, tmp_path):
        """Provenance cannot be established over an unreadable partition, so the
        run is refused before any provider exists (N2), not collected around it."""
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        path = store.ledger_root / "SPY" / "1d" / "raw" / "artifacts.jsonl"
        path.write_bytes(path.read_bytes() + b'{"torn"')
        corrupt = path.read_bytes()
        report, built = run(store, et(2026, 10, 7, 7))
        assert report.outcome == "provenance_unknown" and built == []
        assert report.record.symbols == ()
        assert report.provenance.reasons == (("integrity_corrupt", 1),)
        assert path.read_bytes() == corrupt

    def test_a_refresh_failure_is_classified(self, tmp_path, monkeypatch):
        store = activated(tmp_path)

        def boom(*args, **kwargs):
            raise RuntimeError("conflict at 7777.123456")

        monkeypatch.setattr(prospective, "refresh_outcomes", boom)
        report, _ = run(store, TUESDAY_RUN)
        assert statuses(report) == [CollectionStatus.REFRESH_FAILURE] * 5
        assert report.record.symbols[0].error_class == "RuntimeError"
        assert "7777" not in store.run_log_path.read_text()

    def test_an_unexpected_defect_still_leaves_a_record(self, tmp_path, monkeypatch):
        store = activated(tmp_path)

        def defect(*args, **kwargs):
            raise TypeError("bug")

        monkeypatch.setattr(prospective, "build_snapshot", defect)
        report, _ = run(store, TUESDAY_RUN)
        assert statuses(report) == [CollectionStatus.UNEXPECTED_FAILURE] * 5
        assert len(list(store.iter_runs())) == 1

    def test_run_record_is_written_once_per_attempt_and_carries_identity(self, tmp_path):
        store = activated(tmp_path)
        report, _ = run(store, TUESDAY_RUN)
        [record] = list(store.iter_runs())
        assert record == report.record
        assert record.collection_fingerprint == COLLECTION_V1.fingerprint
        assert record.activated_at == ACTIVATED_AT
        assert record.collector_git_commit == COLLECTOR_SHA
        assert record.universe == COLLECTION_V1.universe


# -- maturation, health and blindness ---------------------------------------------------------


@pytest.fixture(scope="module")
def matured_template(tmp_path_factory):
    """SPY collected every weekday morning for 26 sessions: h1/h5/h20 outcomes exist.

    Built once per module under the same offline guard; each test gets a copy.
    """
    with pytest.MonkeyPatch.context() as patch:
        install_offline_guard(patch)
        return build_matured_root(tmp_path_factory.mktemp("matured"), 26)


@pytest.fixture
def matured(matured_template, tmp_path):
    shutil.copytree(matured_template, tmp_path / "v1")
    return build_prospective_store(tmp_path / "v1")


class TestHealth:
    def test_absent_root_is_not_activated_and_stays_absent(self, tmp_path):
        store = build_prospective_store(tmp_path / "v1")
        report = health(store)
        assert report.status == "not_activated"
        assert (report.root_exists, report.ledger_exists, report.integrity) == (False, False, "ok")
        assert not store.root_exists()

    def test_activated_without_runs(self, tmp_path):
        report = health(activated(tmp_path))
        assert report.status == "active"
        assert report.manifest_fingerprint_match and report.live_configuration_match
        assert report.runs_total == 0 and report.last_run is None
        assert all(s.claims_total == 0 and s.pending == 0 for s in report.symbols)

    def test_counts_after_maturation(self, matured):
        report = health(matured, definition=SPY_ONLY)
        assert report.status == "active" and report.integrity == "ok"
        [spy] = report.symbols
        assert spy.tails_registered == 26 and spy.claims_total == 104
        assert spy.claims_evaluable + spy.claims_insufficient == 104
        matured_counts = dict(spy.outcomes_matured)
        assert matured_counts == {1: 4 * 25, 5: 4 * 21, 20: 4 * 6}
        assert spy.pending == spy.claims_evaluable * 3 - sum(matured_counts.values())
        assert spy.missed_dates == ()
        assert report.runs_total == 26 and report.last_success == report.last_run

    def test_missed_dates_are_reported(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        run(store, et(2026, 10, 9, 7))
        report = health(store)
        assert [s.missed_dates for s in report.symbols] == [
            (date(2026, 10, 6), date(2026, 10, 7))] * 5

    def test_corruption_is_reported_with_component_and_line(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        path = store.ledger_root / "QQQ" / "1d" / "raw" / "outcomes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not json\n")
        report = health(store)
        assert report.status == "corrupt"
        assert (report.corrupt_component, report.corrupt_line) == ("ledger:QQQ", 1)
        assert [s.readable for s in report.symbols] == [True, False, True, True, True]

    def test_corrupt_run_log(self, tmp_path):
        store = activated(tmp_path)
        run(store, TUESDAY_RUN)
        store.run_log_path.write_bytes(store.run_log_path.read_bytes() + b"{")
        report = health(store)
        # line 1 is the run start, line 2 the completed record, line 3 the torn tail
        assert (report.status, report.corrupt_component, report.corrupt_line) == (
            "corrupt", "run_log", 3)
        assert report.provenance.status == "unknown"

    def test_config_mismatch(self, tmp_path):
        store = activated(tmp_path)
        assert health(store, definition=replace(COLLECTION_V1, universe=("SPY",))).status == \
            "config_mismatch"

    def test_health_never_builds_a_snapshot_or_provider(self, matured, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("health reached the provider path")

        monkeypatch.setattr(prospective, "build_snapshot", refuse)
        monkeypatch.setattr(prospective, "refresh_outcomes", refuse)
        before = files(matured.root)
        assert health(matured, definition=SPY_ONLY).status == "active"
        assert files(matured.root) == before


class TestBlindness:
    """Values that exist in the ledger never appear in any Level-1 surface."""

    def leaked_values(self, store):
        values = set()
        source = ledger(store)
        for outcome in source.iter_outcomes(partition()):
            for number in (outcome.forward_return, outcome.reference_price, outcome.future_price):
                values.update({repr(number), f"{number:.6f}", f"{number:.4f}", str(number)})
        for artifact in source.iter_artifacts(partition()):
            values.add(getattr(artifact.state, "value", str(artifact.state)))
        return values

    def test_run_log_carries_no_price_return_or_state(self, matured):
        text = matured.run_log_path.read_text()
        leaked = self.leaked_values(matured)
        assert leaked
        assert not [value for value in leaked if value in text]
        assert "7777" not in text and "forward_return" not in text
        for line in text.splitlines():
            assert '"state"' not in line and "reason_codes" not in line

    def test_health_report_carries_no_price_return_or_state(self, matured):
        report = health(matured, definition=SPY_ONLY)
        text = repr(report)
        assert not [value for value in self.leaked_values(matured) if value in text]
        assert "7777" not in text

    def test_run_log_numbers_are_all_counts(self, matured):
        for line in matured.run_log_path.read_text().splitlines():
            payload = json.loads(line)
            stack = [payload]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                else:
                    assert not isinstance(value, float)
