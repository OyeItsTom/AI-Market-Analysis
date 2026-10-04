"""Offline fixtures for FUTURE_VALIDATION_V1 tests.

* an autouse firewall: no socket, no real yfinance, no default provider, and
  neither ``data/prospective`` nor its ``v1`` root may exist before or after;
* :class:`Book`, a synthetic evidence builder for the pure engine (Level 1
  and Level 3 from one description, weekday sessions from 2026-10-05);
* :func:`small_definition`, a SPY-only variant of the frozen definition over
  the SPY-only collection, with small thresholds so a real collected root can
  reach the stop rule in a few dozen sessions;
* session-cached real roots (collected through the unchanged M1/N2 path with
  the session-shaped fake provider), copied per test.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src.prospective import provenance_policy_for
from src.research.future_validation import FUTURE_VALIDATION_V1, REFERENCES
from src.research.future_validation_engine import (
    ClaimStamp,
    LevelOneEvidence,
    LevelThreeEvidence,
    Measurement,
    Observation,
    OutcomeStamp,
)
from tests.prospective_fixtures import (
    COLLECTOR_SHA,
    M2_SHA,
    REPO,
    SPY_ONLY,
    UTC,
    VERSIONS,
    Clock,
    ProbeDouble,
    SessionProvider,
    et,
    install_offline_guard,
    ny_midnight,
    weekday_mornings,
)

PROSPECTIVE_DATA = REPO / "data" / "prospective"
ACTIVATED_AT = et(2026, 10, 5, 15)  # Monday afternoon ET; the Monday bar settles after it

#: A value no legitimate synthetic return uses: if it appears anywhere, excluded evidence leaked.
LEAK = 1234.5


@pytest.fixture(autouse=True)
def future_validation_firewall(monkeypatch):
    assert not PROSPECTIVE_DATA.exists(), "data/prospective must not exist"
    install_offline_guard(monkeypatch)
    yield
    assert not PROSPECTIVE_DATA.exists(), "a test created data/prospective"


# -- synthetic evidence ---------------------------------------------------------------------------


def session(index: int, first: date = date(2026, 10, 5)) -> datetime:
    """The ``index``-th weekday bar (00:00 ET, as UTC) from ``first``."""
    day = first
    seen = -1
    while True:
        if day.weekday() < 5:
            seen += 1
            if seen == index:
                return ny_midnight(day)
        day += timedelta(days=1)


TREND = FUTURE_VALIDATION_V1.primary_hypothesis
MOMENTUM = FUTURE_VALIDATION_V1.secondary_hypotheses[0]


class Book:
    """Describe claims per session; get matching Level-1 and Level-3 evidence."""

    def __init__(self, definition=FUTURE_VALIDATION_V1, activated_at: datetime = ACTIVATED_AT):
        self.definition = definition
        self.activated_at = activated_at
        self.claims: list[ClaimStamp] = []
        self.outcomes: list[OutcomeStamp] = []
        self.observations: list[Observation] = []
        self.measurements: list[Measurement] = []
        self.excluded_artifacts: set[str] = set()
        self.excluded_outcomes: set[str] = set()
        self.missed: dict[str, set[datetime]] = {}

    def add(self, symbol: str, index: int, state: str = "bullish", *, identity=TREND,
            returns: dict[int, float] | None = None, excluded: bool = False,
            excluded_outcomes: bool = False, timestamp: datetime | None = None,
            reference_offset: timedelta = timedelta(days=1)) -> str:
        stamp = session(index) if timestamp is None else timestamp
        key = f"{symbol}|{identity.hypothesis_id}|{stamp.isoformat()}"
        self.claims.append(ClaimStamp(key=key, symbol=symbol, timestamp=stamp,
                                      hypothesis_id=identity.hypothesis_id,
                                      hypothesis_version=identity.version,
                                      hypothesis_fingerprint=identity.fingerprint))
        self.observations.append(Observation(key=key, symbol=symbol, timestamp=stamp,
                                             hypothesis_id=identity.hypothesis_id,
                                             hypothesis_version=identity.version,
                                             hypothesis_fingerprint=identity.fingerprint,
                                             state=state))
        if excluded:
            self.excluded_artifacts.add(key)
        for horizon, value in (returns or {}).items():
            outcome_key = f"{key}|h{horizon}"
            spec = self.definition.spec_fingerprint(horizon)
            self.outcomes.append(OutcomeStamp(key=outcome_key, artifact_key=key, symbol=symbol,
                                              horizon_bars=horizon, spec_fingerprint=spec,
                                              evaluation_version=1))
            self.measurements.append(Measurement(
                key=outcome_key, artifact_key=key, horizon_bars=horizon, spec_fingerprint=spec,
                evaluation_version=1, forward_return=value,
                reference_timestamp=stamp + reference_offset,
                future_timestamp=stamp + reference_offset + timedelta(days=horizon)))
            if excluded or excluded_outcomes:
                self.excluded_outcomes.add(outcome_key)
        return key

    def trend(self, symbol: str, index: int, state: str = "bullish", value: float | None = 0.01,
              **kwargs) -> str:
        returns = kwargs.pop("returns", None)
        if returns is None:
            returns = {} if value is None else {20: value, 5: value / 4}
        return self.add(symbol, index, state, returns=returns, **kwargs)

    def assessment(self, symbol: str, index: int) -> None:
        stamp = session(index)
        self.claims.append(ClaimStamp(key=f"{symbol}|assessment|{stamp.isoformat()}",
                                      symbol=symbol, timestamp=stamp))

    def miss(self, symbol: str, index: int) -> None:
        self.missed.setdefault(symbol, set()).add(session(index))

    def level_one(self) -> LevelOneEvidence:
        return LevelOneEvidence(
            activated_at=self.activated_at, claims=tuple(self.claims),
            outcomes=tuple(self.outcomes),
            excluded_artifact_keys=frozenset(self.excluded_artifacts),
            excluded_outcome_keys=frozenset(self.excluded_outcomes),
            missed_sessions={s: tuple(sorted(v)) for s, v in self.missed.items()})

    def level_three(self) -> LevelThreeEvidence:
        return LevelThreeEvidence(level_one=self.level_one(),
                                  observations=tuple(self.observations),
                                  measurements=tuple(self.measurements))


def episodes(book: Book, symbol: str, start: int, pattern: str, *, bull: float = 0.03,
             other: float = 0.01) -> int:
    """Write ``pattern`` from session ``start``: B bullish, R bearish, N neutral, M missed,
    X excluded bullish, A assessment only, U bullish unmatured. Returns the next index."""
    index = start
    for char in pattern:
        if char == "B":
            book.trend(symbol, index, "bullish", bull)
        elif char == "R":
            book.trend(symbol, index, "bearish", other)
        elif char == "N":
            book.trend(symbol, index, "neutral", other)
        elif char == "M":
            book.miss(symbol, index)
        elif char == "X":
            book.trend(symbol, index, "bullish", LEAK, excluded=True)
        elif char == "A":
            book.assessment(symbol, index)
        elif char == "U":
            book.trend(symbol, index, "bullish", None)
        else:  # pragma: no cover - test typo
            raise ValueError(char)
        index += 1
    return index


# -- a small SPY-only definition for real collected roots -----------------------------------------


def small_definition(**overrides):
    """FUTURE_VALIDATION_V1 restricted to the SPY-only collection, small thresholds.

    The collected roots hold about one month of evidence (24 sessions from
    2026-10-06), so E1 is 0 months (met by any evidence) and F is 2 months (not
    met); a test that needs F sets ``forced_unlock_calendar_months=1``.
    """
    fields = dict(
        primary_symbols=("SPY",),
        secondary_symbols=(),
        references=(REFERENCES[0],),
        collection_fingerprint=SPY_ONLY.fingerprint,
        provenance_policy_fingerprint=provenance_policy_for(SPY_ONLY).fingerprint,
        stop_rule_minimum_matured_claims=3,
        stop_rule_minimum_calendar_months=0,
        forced_unlock_calendar_months=2,
        minimum_bullish_episodes=1,
        secondary_analyses=tuple(
            replace(a, symbols=tuple(s for s in a.symbols if s == "SPY"))
            for a in FUTURE_VALIDATION_V1.secondary_analyses),
    )
    fields.update(overrides)
    return replace(FUTURE_VALIDATION_V1, **fields)


#: Host clocks: metadata only. Neither may change unlockability (the evidence clock decides).
AFTER_E1 = et(2030, 10, 6, 12)
AFTER_F = et(2032, 10, 6, 12)
#: The collected roots' evidence clock: the last claimed bar (2026-11-05) settles at
#: 2026-11-06 00:00 ET.
EVIDENCE_THROUGH = et(2026, 11, 6)
SESSIONS = 24


def _activate(store):
    from src.application.prospective import activate

    activate(store, collector_git_commit=COLLECTOR_SHA, m2_preregistration_git_commit=M2_SHA,
             repository=ProbeDouble(), versions=VERSIONS, now=lambda: ACTIVATED_AT,
             definition=SPY_ONLY)


def collect_sessions(store, mornings, provider=None, *, prefix="run") -> None:
    from src.application.prospective import collect

    provider = provider or SessionProvider()
    for number, moment in enumerate(mornings):
        report = collect(store, provider_factory=lambda: provider, now=Clock(moment),
                         run_id_factory=lambda n=number: f"{prefix}-{n}", definition=SPY_ONLY,
                         repository=ProbeDouble())
        assert report.record is not None and report.record.symbols_failed == 0, report


def crash_after_two_claims(store) -> None:
    """A real crash mid-run: the process dies after two of SPY's four registrations."""
    import src.application.prospective as prospective

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

    prospective.build_outcome_ledger = crashing
    try:
        with pytest.raises(Crash):
            prospective.collect(store, provider_factory=SessionProvider, now=Clock(
                et(2026, 10, 6, 7)), run_id_factory=lambda: "crashed", definition=SPY_ONLY,
                repository=ProbeDouble())
    finally:
        prospective.build_outcome_ledger = real


def _build(base: Path, *, degraded: bool) -> Path:
    from src.application.prospective import build_prospective_store

    store = build_prospective_store(base / "v1")
    _activate(store)
    mornings = list(weekday_mornings(date(2026, 10, 6), SESSIONS))
    if degraded:
        crash_after_two_claims(store)
        mornings[0] = et(2026, 10, 6, 8)  # the same, still-current tail completes
    collect_sessions(store, mornings)
    return store.root


@pytest.fixture(scope="session")
def root_templates(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        install_offline_guard(patch)
        base = tmp_path_factory.mktemp("future_validation_templates")
        templates = {
            "matured": _build(base / "matured", degraded=False),
            "degraded": _build(base / "degraded", degraded=True),
        }
    return templates


def copy_root(templates, name: str, tmp_path: Path) -> Path:
    target = tmp_path / name / "v1"
    shutil.copytree(templates[name], target)
    return target


__all__ = [
    "ACTIVATED_AT", "AFTER_E1", "AFTER_F", "EVIDENCE_THROUGH", "LEAK", "MOMENTUM", "PROSPECTIVE_DATA", "SESSIONS",
    "TREND", "UTC", "Book", "collect_sessions", "copy_root", "crash_after_two_claims",
    "episodes", "future_validation_firewall", "root_templates", "session", "small_definition",
]
