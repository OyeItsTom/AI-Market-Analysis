"""Manual paper actions for the dashboard.

Wraps the Phase 5 paper domain so the UI has one place to apply an intent, and
one place where identifiers and timestamps are minted.

**This module cannot see research.** It deliberately imports nothing from
``src.assessments``: an assessment is not in scope here, so no code path can
turn ``BULLISH`` into ``OPEN_LONG``. The human reads research elsewhere and
decides; the decision arrives here as a symbol and an amount.

Identifier lifecycle
--------------------
Streamlit reruns the whole script on every interaction. If identifiers were
minted while rendering, a rerun would produce new ones and Phase 5's
duplicate-intent protection -- which is keyed on ``intent_id`` -- would never
trigger. So identifiers are minted **once per form lifecycle**, held, and
reused until the submission they belong to is applied. See
:meth:`PaperSession.pending_open_ids`.

State is in memory only. Nothing here writes to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from src.portfolio import (
    CloseIntent,
    OpenLongIntent,
    PaperPortfolio,
    PaperPosition,
    ResearchProvenance,
    RiskDecision,
    RiskPolicy,
)

from .errors import ApplicationError, FailureKind, classify

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


#: The dashboard's fixed paper risk limits. Not user-editable in V1: a limit
#: editor beside a research panel invites relaxing a limit until an action is
#: approved, which is the opposite of what a risk policy is for.
DEFAULT_RISK_POLICY = RiskPolicy(
    max_notional_per_position=Decimal("10000"),
    max_total_notional=Decimal("50000"),
    max_open_positions=5,
    allow_duplicate_symbol=False,
)


def parse_notional(raw: object) -> Decimal:
    """Turn user input into the exact ``Decimal`` the paper domain requires.

    Parsed from ``str`` deliberately. ``Decimal(1000.1)`` from a float would
    carry a binary artefact into exposure arithmetic, which is exactly what
    Phase 5 refuses to do.
    """
    if isinstance(raw, Decimal):
        return raw
    text = str(raw).strip().replace(",", "")
    if not text:
        raise ApplicationError(
            FailureKind.REQUEST, "notional", "Enter an amount for the position."
        )
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise ApplicationError(
            FailureKind.REQUEST, "notional", f"{raw!r} is not a valid amount."
        ) from None


def build_provenance(
    *,
    hypothesis_id: str,
    hypothesis_version: int,
    hypothesis_fingerprint: str,
    observation_timestamp: datetime,
) -> ResearchProvenance:
    """Build Phase 5 provenance from plain values.

    Takes primitives rather than a ``ResearchObservation`` so this module still
    imports nothing from the research packages: the note records *what the
    human said they were reading*, and nothing here can reach a research object
    to check it. That is the point -- Phase 5's boundary is **preserved, not
    authenticated**, and a provenance note authorises nothing.
    """
    return ResearchProvenance(
        hypothesis_id=hypothesis_id,
        hypothesis_version=hypothesis_version,
        hypothesis_fingerprint=hypothesis_fingerprint,
        observation_timestamp=observation_timestamp,
    )


@dataclass(frozen=True)
class PendingIntentIds:
    """Identifiers minted once and reused across reruns of one form."""

    intent_id: str
    position_id: str


@dataclass
class PaperSession:
    """In-memory paper state for one dashboard session.

    Holds the current portfolio, the risk policy in force, and the most recent
    decision so the UI can display it. Mutation happens in exactly one place --
    :meth:`open_long` / :meth:`close_position` -- never in rendering code.
    """

    policy: RiskPolicy = DEFAULT_RISK_POLICY
    portfolio: PaperPortfolio = field(default_factory=PaperPortfolio)
    last_decision: RiskDecision | None = None
    last_error: str | None = None
    now: Clock = _utc_now
    _sequence: int = 0
    _pending_open: PendingIntentIds | None = None
    _pending_close_intent_id: str | None = None

    # -- identifier lifecycle -------------------------------------------
    def _next(self, prefix: str) -> str:
        """A readable, deterministic-per-session identifier.

        Not a UUID: no randomness is used anywhere in this project, and a
        sequence is reproducible in tests. Uniqueness is only required within
        one session's portfolio, which Phase 5 enforces anyway.
        """
        self._sequence += 1
        return f"{prefix}-{self._sequence}"

    def pending_open_ids(self) -> PendingIntentIds:
        """Identifiers for the open form, minted once and then held.

        Repeated calls during reruns return the same pair, so resubmitting the
        same form reaches Phase 5 with the same ``intent_id`` and is refused as
        a replay rather than applied twice.
        """
        if self._pending_open is None:
            self._pending_open = PendingIntentIds(
                intent_id=self._next("open"), position_id=self._next("pos")
            )
        return self._pending_open

    def pending_close_intent_id(self) -> str:
        if self._pending_close_intent_id is None:
            self._pending_close_intent_id = self._next("close")
        return self._pending_close_intent_id

    def _rotate_open_ids(self) -> None:
        self._pending_open = None

    def _rotate_close_id(self) -> None:
        self._pending_close_intent_id = None

    # -- actions ---------------------------------------------------------
    def open_long(
        self,
        symbol: str,
        notional: object,
        *,
        provenance: ResearchProvenance | None = None,
        ids: PendingIntentIds | None = None,
    ) -> RiskDecision:
        """Apply a human-initiated OPEN_LONG.

        ``provenance`` is an optional note about what the human was reading. It
        is **preserved, not authenticated** -- nothing verifies it, and it
        cannot authorise anything.

        ``ids`` is the pair the caller captured *before* the submission it is
        applying. Passing it explicitly is what makes Phase 5's replay
        protection a real backstop rather than a theoretical one: resubmitting
        a form that has already been applied arrives here with the same
        ``intent_id``, and ``PaperPortfolio.apply`` refuses it instead of
        creating a second position. Omitting it uses the session's current
        pending pair, which is the ordinary single-submission path.
        """
        ids = ids or self.pending_open_ids()
        amount = parse_notional(notional)
        try:
            intent = OpenLongIntent(
                ids.intent_id,
                self.now(),
                position_id=ids.position_id,
                symbol=(symbol or "").strip().upper(),
                notional=amount,
                research_provenance=provenance,
            )
            portfolio, decision = self.portfolio.apply(intent, self.policy)
        except Exception as exc:
            raise classify(exc, "paper action") from exc

        self.portfolio = portfolio
        self.last_decision = decision
        if decision.approved:
            # Consumed by Phase 5; a fresh id is needed for the next action.
            # A rejected intent id is NOT consumed, so it is deliberately kept
            # and the same intent can be retried once conditions change.
            self._rotate_open_ids()
        return decision

    def close_position(
        self, target_position_id: str, *, intent_id: str | None = None
    ) -> RiskDecision:
        """Apply a human-initiated CLOSE against an existing open position.

        ``intent_id`` is the id the caller captured before submission; see
        :meth:`open_long` for why passing it explicitly matters.
        """
        intent_id = intent_id or self.pending_close_intent_id()
        try:
            intent = CloseIntent(
                intent_id,
                self.now(),
                target_position_id=(target_position_id or "").strip(),
            )
            portfolio, decision = self.portfolio.apply(intent, self.policy)
        except Exception as exc:
            raise classify(exc, "paper action") from exc

        self.portfolio = portfolio
        self.last_decision = decision
        if decision.approved:
            self._rotate_close_id()
        return decision

    # -- read-only views -------------------------------------------------
    @property
    def open_positions(self) -> tuple[PaperPosition, ...]:
        return self.portfolio.open_positions

    @property
    def closed_positions(self) -> tuple[PaperPosition, ...]:
        return self.portfolio.closed_positions

    @property
    def closable_ids(self) -> tuple[str, ...]:
        """Position ids the user may close -- open ones only.

        Closed positions are absent from the selector, so a stale close is
        hard to request. Phase 5 still refuses one if it is somehow attempted.
        """
        return tuple(position.position_id for position in self.portfolio.open_positions)


__all__ = [
    "PaperSession",
    "PendingIntentIds",
    "DEFAULT_RISK_POLICY",
    "parse_notional",
    "build_provenance",
]
