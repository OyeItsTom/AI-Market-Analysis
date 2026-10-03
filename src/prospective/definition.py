"""Prospective Collection v1: the frozen collection definition and its time rules.

``COLLECTION_V1`` is research configuration, frozen in code like
``BASELINE_STUDY_V1``: the universe, the interval and basis, the hypotheses
and assessment policy it expects to find, the outcome horizons, the
evaluation version, the reserved holdout start and the collection window.
Its fingerprint is written into the activation manifest once, and every
later collection run recomputes it and refuses on any difference. Nothing
machine-specific and no activation time is part of it.

The definition is *declared*, not derived: the hypothesis, policy and
outcome-spec fingerprints are literals here, and the application layer
checks them against the live code before it activates or collects. A
re-parameterised hypothesis therefore cannot slip into a running collection
by changing the definition along with it.

The time rules are pure functions of aware datetimes, evaluated in
``America/New_York`` whatever the machine's own timezone is:

* **collection window** -- ``00:30 <= ET time < 09:00``. A daily bar settles
  at local midnight ET (its timestamp plus one day), and a prospective claim
  must be recorded before the next session opens at 09:30 ET; the window
  keeps a 30-minute buffer after settlement and a 30-minute margin before
  the open.
* **timestamp convention** -- every daily bar must be stamped 00:00:00 ET.
  The settlement rule above depends on it, so a different convention is
  refused rather than reinterpreted.
* **activation boundary** -- a tail bar that settled at or before
  ``activated_at`` is pre-activation and is never claimed.
* **current tail** -- a tail is current only if no weekday lies strictly
  between its date and the run's ET date; otherwise a session (or a
  holiday the rule cannot tell from one) has passed since it settled, and
  claiming it now would be a late claim.
* **missed collection** -- settled post-activation bars between the last
  registered claim and the current tail that were never claimed.

No exchange calendar is introduced: the bars the provider returns are the
evidence of which sessions existed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from src.data.models import Interval

#: Exchange-local timezone every time rule is evaluated in.
NEW_YORK = ZoneInfo("America/New_York")

#: Inclusive start and exclusive end of the safe collection window, ET.
COLLECTION_WINDOW_START = time(0, 30)
COLLECTION_WINDOW_END = time(9, 0)

#: One daily bar's period: the provider's own settlement bound for ``1d``.
DAILY_BAR_PERIOD: timedelta = Interval.DAY_1.max_duration

#: A full 40-hex-digit lower-case commit SHA.
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class DefinitionError(ValueError):
    """A collection definition or a time-rule input is malformed."""


@dataclass(frozen=True)
class HypothesisPin:
    """One expected hypothesis identity: id, version and fingerprint."""

    hypothesis_id: str
    version: int
    fingerprint: str

    def canonical_form(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
        }


@dataclass(frozen=True)
class CollectionDefinition:
    """A frozen prospective collection. Immutable; identity is the fingerprint."""

    collection_id: str
    schema_version: int
    prospective_policy_version: int
    universe: tuple[str, ...]
    interval: str
    basis: str
    settled_only: bool
    provider: str
    hypotheses: tuple[HypothesisPin, ...]
    assessment_rule: str
    minimum_sufficient_observations: int
    policy_fingerprint: str
    outcome_horizons: tuple[int, ...]
    outcome_spec_fingerprints: tuple[str, ...]
    evaluation_version: int
    history_window_days: int
    warmup_bars: int
    holdout_start: date
    collection_timezone: str
    collection_window_start: str
    collection_window_end: str
    daily_bar_timestamp_convention: str

    def __post_init__(self) -> None:
        if not self.universe:
            raise DefinitionError("the universe must not be empty")
        if len(set(self.universe)) != len(self.universe):
            raise DefinitionError("the universe must not repeat a symbol")
        for symbol in self.universe:
            if not symbol or symbol != symbol.strip().upper():
                raise DefinitionError(f"universe symbol {symbol!r} is not normalised")
        if len(self.outcome_horizons) != len(self.outcome_spec_fingerprints):
            raise DefinitionError("every outcome horizon needs exactly one spec fingerprint")
        if len({pin.hypothesis_id for pin in self.hypotheses}) != len(self.hypotheses):
            raise DefinitionError("a hypothesis may be pinned only once")

    def canonical_form(self) -> dict[str, object]:
        """Plain, ordered-by-key data; the only input to the fingerprint."""
        return {
            "assessment_rule": self.assessment_rule,
            "basis": self.basis,
            "collection_id": self.collection_id,
            "collection_timezone": self.collection_timezone,
            "collection_window_end": self.collection_window_end,
            "collection_window_start": self.collection_window_start,
            "daily_bar_timestamp_convention": self.daily_bar_timestamp_convention,
            "evaluation_version": self.evaluation_version,
            "history_window_days": self.history_window_days,
            "holdout_start": self.holdout_start.isoformat(),
            "hypotheses": [pin.canonical_form() for pin in self.hypotheses],
            "interval": self.interval,
            "minimum_sufficient_observations": self.minimum_sufficient_observations,
            "outcome_horizons": list(self.outcome_horizons),
            "outcome_spec_fingerprints": list(self.outcome_spec_fingerprints),
            "policy_fingerprint": self.policy_fingerprint,
            "prospective_policy_version": self.prospective_policy_version,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "settled_only": self.settled_only,
            "universe": list(self.universe),
            "warmup_bars": self.warmup_bars,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_form(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)

    @property
    def fingerprint(self) -> str:
        """Full SHA-256 of the canonical JSON."""
        return hashlib.sha256(self.canonical_json().encode("ascii")).hexdigest()

    @property
    def hypothesis_fingerprints(self) -> dict[str, str]:
        return {pin.hypothesis_id: pin.fingerprint for pin in self.hypotheses}

    @property
    def claims_per_tail(self) -> int:
        """Claims one complete tail registers: one per hypothesis plus the assessment.

        Derived, not declared: it is not part of the canonical form, so the
        fingerprint is unaffected.
        """
        return len(self.hypotheses) + 1


COLLECTION_V1 = CollectionDefinition(
    collection_id="prospective_collection_v1",
    schema_version=1,
    prospective_policy_version=1,
    universe=("SPY", "QQQ", "IWM", "TLT", "GLD"),
    interval="1d",
    basis="raw",
    settled_only=True,
    provider="yfinance",
    hypotheses=(
        HypothesisPin("trend_alignment", 1, "650add07184f8440"),
        HypothesisPin("momentum_in_trend_context", 1, "6589cb8021b76574"),
        HypothesisPin("trend_crossover", 1, "f1126ca778e6f7ce"),
    ),
    assessment_rule="directional_presence_v1",
    minimum_sufficient_observations=2,
    policy_fingerprint="a829b9bde41c3332",
    outcome_horizons=(1, 5, 20),
    outcome_spec_fingerprints=("83e9dabf9b4e27de", "b586481caf972d58", "a040ca488aa3f51f"),
    evaluation_version=1,
    history_window_days=730,
    warmup_bars=51,
    holdout_start=date(2025, 3, 1),
    collection_timezone="America/New_York",
    collection_window_start="00:30",
    collection_window_end="09:00",
    daily_bar_timestamp_convention="00:00:00 America/New_York",
)


# -- time rules ----------------------------------------------------------------------------


def require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise DefinitionError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DefinitionError(f"{label} must be timezone-aware")
    return value


def in_collection_window(moment: datetime) -> bool:
    """Whether ``moment`` falls in ``00:30 <= ET time < 09:00``."""
    local = require_aware(moment, "moment").astimezone(NEW_YORK).time()
    return COLLECTION_WINDOW_START <= local < COLLECTION_WINDOW_END


def is_new_york_midnight(timestamp: datetime) -> bool:
    """Whether a daily bar is stamped exactly 00:00:00 America/New_York."""
    local = require_aware(timestamp, "timestamp").astimezone(NEW_YORK)
    return local.time() == time(0, 0)


def first_non_midnight(timestamps: Iterable[datetime]) -> datetime | None:
    """The first timestamp that breaks the daily convention, or ``None``."""
    for timestamp in timestamps:
        if not is_new_york_midnight(timestamp):
            return timestamp
    return None


def settles_at(bar_timestamp: datetime) -> datetime:
    """When a daily bar provably ends (the provider's own settlement rule)."""
    return require_aware(bar_timestamp, "bar_timestamp") + DAILY_BAR_PERIOD


def is_pre_activation(bar_timestamp: datetime, activated_at: datetime) -> bool:
    """A bar that settled at or before activation is never claimed."""
    return settles_at(bar_timestamp) <= require_aware(activated_at, "activated_at")


def _next_weekday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def is_current_tail(tail: datetime, moment: datetime) -> bool:
    """Whether claiming ``tail`` at ``moment`` is still prospective.

    The tail's ET date must be before the run's ET date, and the run's ET
    date must not be later than the first weekday after the tail. A later
    run date means a weekday has passed since the tail settled: a session
    (or a holiday this calendar-free rule cannot tell from one) may already
    have opened, so the claim would be late. Refusing on a holiday loses a
    claim; accepting a late one would contaminate the ledger.
    """
    tail_day = require_aware(tail, "tail").astimezone(NEW_YORK).date()
    run_day = require_aware(moment, "moment").astimezone(NEW_YORK).date()
    return tail_day < run_day <= _next_weekday(tail_day)


def missed_tails(
    series_timestamps: Iterable[datetime],
    registered: Iterable[datetime],
    *,
    activated_at: datetime,
    tail: datetime,
) -> tuple[datetime, ...]:
    """Settled post-activation bars after the last registered claim, before ``tail``.

    Operational metadata only: these bars existed (the provider returned
    them), settled after activation, and were never claimed. They are never
    claimed later. The floor is the last *registered* claim, so a gap is
    listed again in every run record that reaches this step -- a stale,
    failed or refused attempt included -- until a later claim is registered;
    bars at or before that claim are not listed after it. ``health``
    de-duplicates them by timestamp.
    """
    held = set(registered)
    floor = max(held) if held else None
    return tuple(
        timestamp
        for timestamp in series_timestamps
        if timestamp < tail
        and timestamp not in held
        and (floor is None or timestamp > floor)
        and not is_pre_activation(timestamp, activated_at)
    )


def validate_commit_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _COMMIT_SHA.fullmatch(value):
        raise DefinitionError(
            f"{label} must be a full 40-character lower-case hex commit SHA, got {value!r}"
        )
    return value


def new_york_date(moment: datetime) -> date:
    return require_aware(moment, "moment").astimezone(NEW_YORK).date()


__all__ = [
    "NEW_YORK",
    "COLLECTION_WINDOW_START",
    "COLLECTION_WINDOW_END",
    "DAILY_BAR_PERIOD",
    "DefinitionError",
    "HypothesisPin",
    "CollectionDefinition",
    "COLLECTION_V1",
    "require_aware",
    "in_collection_window",
    "is_new_york_midnight",
    "first_non_midnight",
    "settles_at",
    "is_pre_activation",
    "is_current_tail",
    "missed_tails",
    "validate_commit_sha",
    "new_york_date",
]
