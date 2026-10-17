"""Offline fixtures for Prospective Collection v1 tests.

A session-shaped provider (weekday bars stamped 00:00 America/New_York,
settled by the provider's own rule, with distinctive sentinel prices), a
settable clock, a repository probe double that satisfies the pinned M2A
binding, a synthetic dependency environment, and a guard that fails any test
that reaches the network, the real yfinance download or the live
``data/prospective/v1`` root. The guard also replaces the *default*
repository probe and dependency source with those doubles, so no test
depends on the checkout it runs in or the interpreter's installed packages;
tests of the real Git probe and dependency capture use temporary repositories
and synthetic distributions explicitly.
"""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.application.prospective import (
    current_dependency_environment as REAL_DEPENDENCY_ENVIRONMENT,
    default_repository_probe as REAL_DEFAULT_REPOSITORY_PROBE,
)
from src.data.models import Interval, MarketBar
from src.prospective import (
    COLLECTION_V1,
    M2A_BOUND_PATHS,
    M2A_PREREGISTRATION_COMMIT,
    DependencyEnvironment,
    RepositoryState,
)

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
REPO = Path(__file__).resolve().parent.parent
LIVE_ROOT = REPO / "data" / "prospective" / "v1"

COLLECTOR_SHA = "a" * 40
M2_SHA = M2A_PREREGISTRATION_COMMIT
PINNED_HASHES = {bound.path: bound.sha256 for bound in M2A_BOUND_PATHS}

#: A synthetic activation-time dependency environment (never the host's).
DEPENDENCIES = DependencyEnvironment(
    "CPython", "3.11.3",
    (("numpy", "2.3.4"), ("pandas", "3.0.5"), ("pip", "25.2"), ("yfinance", "1.7.0")),
)

#: Prices start here so any leaked price is recognisable in output.
SENTINEL_BASE = 7777.123456
SENTINEL_STEP = 0.731


def et(year, month, day, hour=0, minute=0, second=0) -> datetime:
    """An aware America/New_York wall-clock time."""
    return datetime(year, month, day, hour, minute, second, tzinfo=NY)


def ny_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=NY).astimezone(UTC)


class Clock:
    """A settable injected clock."""

    def __init__(self, value: datetime) -> None:
        self.value = value
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


class SessionProvider:
    """Weekday daily bars from 2024-01-02, stamped by ``stamp``, settled at ``end``.

    ``missing`` dates are not sessions (holidays, or a lagging feed). Prices
    ramp from the sentinel base; the provider records every call.
    """

    def __init__(self, *, name: str = "yfinance", missing=(), stamp=ny_midnight,
                 fail: Exception | None = None, empty: bool = False,
                 lag_until: date | None = None) -> None:
        self.name = name
        self.missing = set(missing)
        self.stamp = stamp
        self.fail = fail
        self.empty = empty
        self.lag_until = lag_until
        self.calls: list[dict] = []

    def get_bars(self, symbol, start, end, interval=Interval.DAY_1, *, include_unsettled=False):
        self.calls.append({"symbol": symbol, "start": start, "end": end,
                           "include_unsettled": include_unsettled})
        if self.fail is not None:
            raise self.fail
        if self.empty:
            return []
        bars = []
        day = date(2024, 1, 2)
        index = 0
        last_day = end.astimezone(NY).date()
        while day <= last_day:
            if day.weekday() < 5 and day not in self.missing and (
                self.lag_until is None or day <= self.lag_until
            ):
                stamp = self.stamp(day)
                price = SENTINEL_BASE + SENTINEL_STEP * index
                if start <= stamp and stamp + timedelta(days=1) <= end:
                    bars.append(MarketBar(
                        symbol=str(symbol).strip().upper(), timestamp=stamp,
                        open=price, high=price + 1.0, low=price - 1.0, close=price,
                        volume=1000.0, interval=Interval.DAY_1, source=self.name,
                    ))
                index += 1
            day += timedelta(days=1)
        return bars


class ProbeDouble:
    """A repository probe answering from fixed values; by default every check passes.

    ``origin_main`` defaults to ``head``. ``committed`` / ``working`` map a
    bound path to its SHA-256 at the M2A commit / in the working tree
    (default: the pinned hashes); ``unchanged`` is the commit-vs-HEAD diff
    answer. ``fail`` makes every call raise :class:`RepositoryProbeError`.
    """

    _DEFAULT = object()

    def __init__(self, *, head=COLLECTOR_SHA, clean=True, ancestors=(M2_SHA, COLLECTOR_SHA),
                 branch="main", origin_main=_DEFAULT, commits=(M2_SHA, COLLECTOR_SHA),
                 committed=None, working=None, unchanged=True, fail=False):
        self.head = head
        self.clean = clean
        self.ancestors = set(ancestors)
        self.branch = branch
        self.origin = head if origin_main is ProbeDouble._DEFAULT else origin_main
        self.commits = set(commits)
        self.committed = dict(PINNED_HASHES if committed is None else committed)
        self.working = dict(PINNED_HASHES if working is None else working)
        self.unchanged = unchanged
        self.fail = fail
        self.calls: list[str] = []

    def _call(self, name):
        self.calls.append(name)
        if self.fail:
            from src.prospective import RepositoryProbeError
            raise RepositoryProbeError(f"{name} failed")

    def repository_state(self) -> RepositoryState:
        self._call("repository_state")
        return RepositoryState(head=self.head, clean=self.clean)

    def is_ancestor_of_head(self, commit: str) -> bool:
        self._call("is_ancestor_of_head")
        return commit in self.ancestors

    def current_branch(self):
        self._call("current_branch")
        return self.branch

    def origin_main(self):
        self._call("origin_main")
        return self.origin

    def commit_exists(self, commit: str) -> bool:
        self._call("commit_exists")
        return commit in self.commits

    def blob_sha256(self, commit: str, path: str):
        self._call("blob_sha256")
        return self.committed.get(path) if commit in self.commits else None

    def working_file_sha256(self, path: str):
        self._call("working_file_sha256")
        return self.working.get(path)

    def paths_unchanged_since(self, commit: str, paths) -> bool:
        self._call("paths_unchanged_since")
        return self.unchanged

#: A one-symbol variant for multi-week simulations; same rules, smaller universe.
SPY_ONLY = replace(COLLECTION_V1, universe=("SPY",))


def weekday_mornings(first: date, count: int):
    """07:00 ET on ``count`` consecutive weekdays from ``first``."""
    day = first
    produced = 0
    while produced < count:
        if day.weekday() < 5:
            yield et(day.year, day.month, day.day, 7)
            produced += 1
        day += timedelta(days=1)


def build_matured_root(base: Path, sessions: int) -> Path:
    """An activated SPY-only root collected every weekday morning from 2026-10-06."""
    from src.application.prospective import activate, build_prospective_store, collect

    store = build_prospective_store(base / "v1")
    activate(store, collector_git_commit=COLLECTOR_SHA, server_main_git_commit=COLLECTOR_SHA,
             repository=ProbeDouble(), now=lambda: et(2026, 10, 5, 15),
             definition=SPY_ONLY)
    provider = SessionProvider()
    for number, moment in enumerate(weekday_mornings(date(2026, 10, 6), sessions)):
        report = collect(store, provider_factory=lambda: provider, now=Clock(moment),
                         run_id_factory=lambda: f"run-{number}", definition=SPY_ONLY,
                         repository=ProbeDouble())
        assert report.record.symbols_failed == 0
    return store.root


def install_offline_guard(monkeypatch) -> None:
    """No socket, no real yfinance download, no default provider; default probe,
    dependency source and import-path verdict are the passing doubles (never the
    checkout or the host)."""

    def refuse_connect(self, *args, **kwargs):
        raise AssertionError("network access attempted in an offline test")

    def refuse_download(*args, **kwargs):
        raise AssertionError("real yfinance download attempted")

    def refuse_provider():
        raise AssertionError("the default provider was constructed")

    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr("src.data.providers.yahoo._default_download", refuse_download)
    monkeypatch.setattr("src.application.prospective.default_provider", refuse_provider)
    for module in ("src.application.prospective", "src.application.future_validation",
                   "src.cli.prospective", "src.cli.future_validation"):
        monkeypatch.setattr(f"{module}.default_repository_probe", ProbeDouble)
    monkeypatch.setattr("src.application.prospective.current_dependency_environment",
                        lambda: DEPENDENCIES)
    monkeypatch.setattr("src.application.prospective.current_import_path_overrides",
                        lambda: ())


@pytest.fixture(autouse=True)
def offline_and_no_live_root(monkeypatch):
    """Every prospective test: offline, and the live root is never touched."""
    assert not LIVE_ROOT.exists(), "the live prospective root must not exist"
    install_offline_guard(monkeypatch)
    yield
    assert not LIVE_ROOT.exists(), "a test created the live prospective root"
