"""Offline fixtures for Prospective Collection v1 tests.

A session-shaped provider (weekday bars stamped 00:00 America/New_York,
settled by the provider's own rule, with distinctive sentinel prices), a
settable clock, a repository probe double, and a guard that fails any test
that reaches the network, the real yfinance download or the live
``data/prospective/v1`` root.
"""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.data.models import Interval, MarketBar
from src.prospective import COLLECTION_V1, RepositoryState

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
REPO = Path(__file__).resolve().parent.parent
LIVE_ROOT = REPO / "data" / "prospective" / "v1"

COLLECTOR_SHA = "a" * 40
M2_SHA = "b" * 40

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
    """A repository probe answering from fixed values."""

    def __init__(self, *, head=COLLECTOR_SHA, clean=True, ancestors=(M2_SHA, COLLECTOR_SHA)):
        self.head = head
        self.clean = clean
        self.ancestors = set(ancestors)

    def repository_state(self) -> RepositoryState:
        return RepositoryState(head=self.head, clean=self.clean)

    def is_ancestor_of_head(self, commit: str) -> bool:
        return commit in self.ancestors


VERSIONS = {"python": "3.11.3", "yfinance": "1.7.0", "pandas": "3.0.5"}

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
    activate(store, collector_git_commit=COLLECTOR_SHA, m2_preregistration_git_commit=M2_SHA,
             repository=ProbeDouble(), versions=VERSIONS, now=lambda: et(2026, 10, 5, 15),
             definition=SPY_ONLY)
    provider = SessionProvider()
    for number, moment in enumerate(weekday_mornings(date(2026, 10, 6), sessions)):
        report = collect(store, provider_factory=lambda: provider, now=Clock(moment),
                         run_id_factory=lambda: f"run-{number}", definition=SPY_ONLY)
        assert report.record.symbols_failed == 0
    return store.root


def install_offline_guard(monkeypatch) -> None:
    """No socket, no real yfinance download, no default provider."""

    def refuse_connect(self, *args, **kwargs):
        raise AssertionError("network access attempted in an offline test")

    def refuse_download(*args, **kwargs):
        raise AssertionError("real yfinance download attempted")

    def refuse_provider():
        raise AssertionError("the default provider was constructed")

    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr("src.data.providers.yahoo._default_download", refuse_download)
    monkeypatch.setattr("src.application.prospective.default_provider", refuse_provider)


@pytest.fixture(autouse=True)
def offline_and_no_live_root(monkeypatch):
    """Every prospective test: offline, and the live root is never touched."""
    assert not LIVE_ROOT.exists(), "the live prospective root must not exist"
    install_offline_guard(monkeypatch)
    yield
    assert not LIVE_ROOT.exists(), "a test created the live prospective root"
