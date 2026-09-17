"""Phase R application orchestration, offline.

The critical path is real end to end -- injected provider -> BarSeries ->
Phase 2 features -> Phase 3 hypotheses -> Phase 4 evaluator -> Phase R
grouping -> renderers -> four files -- with nothing mocked but the source
of bars. Every test writes under ``tmp_path``; nothing touches the
network, the repository's ``data/`` tree, or a clock.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta

import pytest

from src.application import DEFAULT_RESEARCH_ROOT, run_baseline_study, validate_git_commit
from src.application.errors import ApplicationError, FailureKind
from src.application.study import ARTIFACT_NAMES, STUDY_LABEL, fetch_study_series, sha256_text
from src.data.models import Interval
from src.data.provider import MarketDataProvider, ProviderUnavailableError
from src.research import BASELINE_STUDY_V1, ARTIFACT_MANIFEST, ARTIFACT_OBSERVATIONS, ARTIFACT_REPORT, ARTIFACT_SUMMARY
from src.outcomes import bars_fingerprint
from tests.research_fixtures import UTC, synthetic_bars
from tests.test_research_definition import small_definition

REPO_DATA = DEFAULT_RESEARCH_ROOT.parent
GIT = "89abcdef0123456789abcdef0123456789abcdef"
CLOCK = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def clock_at(*instants: datetime):
    """A clock returning the given instants in turn, then repeating the last."""
    remaining = list(instants)

    def now() -> datetime:
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0]

    return now


class SyntheticProvider(MarketDataProvider):
    """Serves deterministic daily bars for any window and records every call."""

    name = "synthetic"

    def __init__(self, *, missing: str | None = None, failing: str | None = None,
                 mislabel: str | None = None, short_warmup: str | None = None):
        self.calls: list[dict] = []
        self.missing = missing
        self.failing = failing
        self.mislabel = mislabel
        self.short_warmup = short_warmup

    def get_bars(self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False):
        self.calls.append({"symbol": symbol, "start": start, "end": end,
                           "interval": Interval.parse(interval), "include_unsettled": include_unsettled})
        symbol = str(symbol).strip().upper()
        if symbol == self.failing:
            raise ProviderUnavailableError(f"{symbol}: upstream refused the request")
        if symbol == self.missing:
            return []
        if symbol == self.short_warmup:
            start = start + timedelta(days=100)
        served = "ZZZ" if symbol == self.mislabel else symbol
        phase = 0.7 * (sum(map(ord, symbol)) % 7)
        return synthetic_bars(served, start, end, phase=phase, source=self.name,
                              interval=Interval.parse(interval))

    def _fetch_bars(self, symbol, start, end, interval):  # pragma: no cover - not used
        raise AssertionError("get_bars is overridden")


@pytest.fixture
def definition():
    return small_definition()


@pytest.fixture
def run(tmp_path, definition):
    provider = SyntheticProvider()
    return run_baseline_study(provider, git_commit=GIT, out_root=tmp_path, now=clock_at(CLOCK),
                              definition=definition), provider


# -- the four files ---------------------------------------------------------------------------


class TestArtifacts:
    def test_exactly_four_files_in_the_labelled_directory(self, run, tmp_path, definition):
        result, _ = run
        assert result.output_dir == tmp_path / definition.label
        assert sorted(p.name for p in result.output_dir.iterdir()) == sorted(ARTIFACT_NAMES)
        assert result.path(ARTIFACT_MANIFEST).is_file()

    def test_file_hashes_match_the_manifest_and_the_run(self, run):
        result, _ = run
        for name in ARTIFACT_NAMES:
            digest = hashlib.sha256(result.path(name).read_bytes()).hexdigest()
            assert result.artifact_sha256[name] == digest
        manifest = json.loads(result.path(ARTIFACT_MANIFEST).read_text(encoding="utf-8"))
        assert manifest["artifacts"][ARTIFACT_SUMMARY]["sha256"] == result.artifact_sha256[ARTIFACT_SUMMARY]
        assert manifest["artifacts"][ARTIFACT_OBSERVATIONS]["sha256"] == result.artifact_sha256[ARTIFACT_OBSERVATIONS]
        assert manifest["artifacts"][ARTIFACT_REPORT]["sha256"] == result.artifact_sha256[ARTIFACT_REPORT]
        assert ARTIFACT_MANIFEST not in manifest["artifacts"]
        assert manifest == dict(result.manifest)
        # The manifest's own hash is returned (and printed), never stored inside it.
        assert result.artifact_sha256[ARTIFACT_MANIFEST] not in result.path(ARTIFACT_MANIFEST).read_text()

    def test_manifest_records_identity_data_and_clock(self, run, definition):
        result, provider = run
        manifest = dict(result.manifest)
        assert manifest["git_commit"] == GIT
        assert manifest["source"] == "synthetic"
        assert manifest["study_fingerprint"] == definition.fingerprint
        assert manifest["retrieved_at"] == manifest["generated_at"] == CLOCK.isoformat()
        for block in manifest["symbols"]:
            bars = provider.get_bars(block["symbol"], definition.fetch_start, definition.outcome_data_end)
            assert block["bars_fingerprint"] == bars_fingerprint(bars)
            assert block["bars_count"] == len(bars)
            assert block["warmup_bars"] >= definition.minimum_warmup_bars
            assert block["max_abs_single_bar_close_return"] > 0

    def test_the_report_and_csvs_are_the_rendered_result(self, run):
        result, _ = run
        report = result.path(ARTIFACT_REPORT).read_text(encoding="utf-8")
        assert report.startswith("# Phase R — engine_test v1")
        assert GIT in report
        rows = list(csv.DictReader(result.path(ARTIFACT_OBSERVATIONS).open(encoding="utf-8")))
        assert len(rows) == len(result.result.observations)
        summary = list(csv.DictReader(result.path(ARTIFACT_SUMMARY).open(encoding="utf-8")))
        assert summary[0]["row_type"] == "coverage"

    def test_the_provider_is_asked_exactly_the_definition_window(self, run, definition):
        _, provider = run
        assert [c["symbol"] for c in provider.calls] == list(definition.symbols)
        for call in provider.calls:
            assert call["start"] == definition.fetch_start
            assert call["end"] == definition.outcome_data_end
            assert call["interval"] is definition.interval
            assert call["include_unsettled"] is False


class TestDeterminism:
    def test_identical_inputs_and_clock_give_byte_identical_files(self, tmp_path, definition):
        first = run_baseline_study(SyntheticProvider(), git_commit=GIT, out_root=tmp_path / "a",
                                   now=clock_at(CLOCK), definition=definition)
        second = run_baseline_study(SyntheticProvider(), git_commit=GIT, out_root=tmp_path / "b",
                                    now=clock_at(CLOCK), definition=definition)
        for name in ARTIFACT_NAMES:
            assert first.path(name).read_bytes() == second.path(name).read_bytes(), name
        assert first.artifact_sha256 == second.artifact_sha256

    def test_a_different_clock_changes_only_the_timestamped_manifest_fields(self, tmp_path, definition):
        first = run_baseline_study(SyntheticProvider(), git_commit=GIT, out_root=tmp_path / "a",
                                   now=clock_at(CLOCK, CLOCK + timedelta(minutes=3)), definition=definition)
        later = run_baseline_study(SyntheticProvider(), git_commit=GIT, out_root=tmp_path / "b",
                                   now=clock_at(CLOCK + timedelta(days=1), CLOCK + timedelta(days=2)),
                                   definition=definition)
        for name in (ARTIFACT_SUMMARY, ARTIFACT_OBSERVATIONS):
            assert first.path(name).read_bytes() == later.path(name).read_bytes(), name
        a, b = dict(first.manifest), dict(later.manifest)
        # The report prints both instants, so its hash follows the clock too.
        assert {k for k in a if a[k] != b[k]} == {"retrieved_at", "generated_at", "artifacts"}
        assert {k for k in a["artifacts"] if a["artifacts"][k] != b["artifacts"][k]} == {ARTIFACT_REPORT}
        assert a["retrieved_at"] == CLOCK.isoformat()
        assert a["generated_at"] == (CLOCK + timedelta(minutes=3)).isoformat()
        # The report differs only where it prints those two instants.
        report_a = first.path(ARTIFACT_REPORT).read_text(encoding="utf-8").splitlines()
        report_b = later.path(ARTIFACT_REPORT).read_text(encoding="utf-8").splitlines()
        differing = [x for x, y in zip(report_a, report_b) if x != y]
        assert len(report_a) == len(report_b)
        assert differing == [line for line in report_a if line.startswith("- retrieved at:")]


# -- refusals -----------------------------------------------------------------------------------


class TestRefusals:
    def test_an_existing_run_is_never_overwritten(self, run, tmp_path, definition):
        result, _ = run
        before = {name: result.path(name).read_bytes() for name in ARTIFACT_NAMES}
        with pytest.raises(ApplicationError) as excinfo:
            run_baseline_study(SyntheticProvider(), git_commit=GIT, out_root=tmp_path,
                               now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.REQUEST
        assert "not overwritten" in excinfo.value.message
        assert {name: result.path(name).read_bytes() for name in ARTIFACT_NAMES} == before

    def test_a_provider_outage_writes_nothing(self, tmp_path, definition):
        with pytest.raises(ApplicationError) as excinfo:
            run_baseline_study(SyntheticProvider(failing="BBB"), git_commit=GIT, out_root=tmp_path,
                               now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.PROVIDER
        assert not (tmp_path / definition.label).exists()

    def test_a_symbol_with_no_bars_is_a_failure_of_the_whole_study(self, tmp_path, definition):
        with pytest.raises(ApplicationError) as excinfo:
            run_baseline_study(SyntheticProvider(missing="AAA"), git_commit=GIT, out_root=tmp_path,
                               now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.PROVIDER
        assert "no 1d bars" in excinfo.value.message
        assert not (tmp_path / definition.label).exists()

    def test_too_little_warmup_is_refused_not_accommodated(self, tmp_path, definition):
        with pytest.raises(ApplicationError) as excinfo:
            run_baseline_study(SyntheticProvider(short_warmup="AAA"), git_commit=GIT,
                               out_root=tmp_path, now=clock_at(CLOCK), definition=definition)
        assert excinfo.value.kind is FailureKind.DOMAIN
        assert "precede the observation start" in excinfo.value.message
        assert not (tmp_path / definition.label).exists()

    def test_a_mislabelled_series_is_refused(self, definition):
        with pytest.raises(ApplicationError) as excinfo:
            fetch_study_series(SyntheticProvider(mislabel="AAA"), definition, "AAA")
        assert excinfo.value.kind is FailureKind.DOMAIN

    @pytest.mark.parametrize("value", ["", "abc", "ccfa47d", GIT.upper(), GIT + "0", None, " " + GIT[:-1]])
    def test_git_commit_must_be_a_full_lowercase_sha(self, value):
        with pytest.raises(ValueError, match="40-character"):
            validate_git_commit(value)

    def test_git_commit_is_accepted_and_stripped(self):
        assert validate_git_commit(f" {GIT} ") == GIT


# -- defaults and the frozen study ----------------------------------------------------------------


class TestDefaults:
    def test_default_root_is_the_repository_data_research(self):
        assert DEFAULT_RESEARCH_ROOT == REPO_DATA / "research"
        assert DEFAULT_RESEARCH_ROOT.parent.name == "data"
        assert STUDY_LABEL == BASELINE_STUDY_V1.label == "baseline_study_v1"

    def test_the_frozen_study_asks_the_provider_exactly_its_window(self):
        """The frozen definition's fetch contract, without evaluating ten years
        of bars: the live run repeats exactly this call per symbol. (A full
        offline run of the frozen windows takes minutes because Phase 4
        rebuilds ``BarSeries.timestamps`` per measurement; the end-to-end path
        is exercised above on a short definition through the same code.)"""
        provider = SyntheticProvider()
        series = fetch_study_series(provider, BASELINE_STUDY_V1, "SPY")
        assert series.symbol == "SPY" and series.basis is BASELINE_STUDY_V1.basis
        assert series.interval is Interval.DAY_1 and series.source == "synthetic"
        assert series.timestamps[0] == datetime(2014, 9, 1, tzinfo=UTC)
        assert series.timestamps[-1] == datetime(2025, 2, 28, tzinfo=UTC)
        [call] = provider.calls
        assert call["symbol"] == "SPY"
        assert call["start"] == datetime(2014, 9, 1, tzinfo=UTC)
        assert call["end"] == datetime(2025, 3, 1, tzinfo=UTC)
        assert call["interval"] is Interval.DAY_1
        assert call["include_unsettled"] is False

    def test_the_frozen_study_is_the_default_definition(self, tmp_path):
        """Without ``definition`` the runner binds the frozen study; with a
        provider that cannot serve 2014 it fails on warm-up, and writes nothing."""
        with pytest.raises(ApplicationError) as excinfo:
            run_baseline_study(SyntheticProvider(short_warmup="SPY"), git_commit=GIT,
                               out_root=tmp_path, now=clock_at(CLOCK))
        assert excinfo.value.kind is FailureKind.DOMAIN
        assert "SPY: only" in excinfo.value.message
        assert not (tmp_path / STUDY_LABEL).exists()

    def test_the_default_root_is_redirected_under_pytest(self, tmp_path, definition):
        """The conftest guard: a run with no ``out_root`` lands in the test's
        ``tmp_path``, never in the repository's ``data/research``."""
        from src.application import study as application_study

        run = run_baseline_study(SyntheticProvider(), git_commit=GIT, now=clock_at(CLOCK),
                                 definition=definition)
        assert run.output_dir == application_study.DEFAULT_RESEARCH_ROOT / definition.label
        assert tmp_path in run.output_dir.parents
        assert not (REPO_DATA / "research").exists()

    def test_sha256_text_is_over_exact_bytes(self):
        assert sha256_text("a\n") == hashlib.sha256(b"a\n").hexdigest()
        assert sha256_text("a\n") != sha256_text("a\r\n")
