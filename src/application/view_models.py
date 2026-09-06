"""Read-only, fully-formatted records for the dashboard to render.

View models **format**; they never decide. A ``CONFLICTED`` badge is produced
because ``assessment.state`` says ``CONFLICTED``, not because this module
inspected the counts and drew its own conclusion. Re-deriving domain meaning in
the presentation layer is how a UI quietly becomes a second, disagreeing
implementation of the research rules.

They also hold the project's honest vocabulary. Three timing fields mean three
different things, and each has exactly one approved label:

======================================  ==================================
``MarketBar.timestamp``                 "Bar opened"
``ResearchObservation.evaluable_from``  "Earliest this could be worked out"
``ResearchAssessment.assessment_as_of`` "Earliest this assessment could exist"
``ResearchSnapshot.built_at``           "Snapshot built"
======================================  ==================================

None of them may be described as when data arrived, was published, or was
"live": this repository models no provider latency and no exchange calendar,
and the UI must not be the first place to imply otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.assessments import AssessmentState, ResearchAssessment
from src.data.series import PriceBasis
from src.features.base import FeatureSeries
from src.portfolio import PaperPosition, RiskDecision, RiskPolicy
from src.strategies.research import ResearchObservation, ResearchState

from .snapshot import ResearchSnapshot

# -- vocabulary ---------------------------------------------------------

LABEL_BAR_OPENED = "Bar opened"
LABEL_EVALUABLE_FROM = "Earliest this could be worked out"
LABEL_ASSESSMENT_AS_OF = "Earliest this assessment could exist"
LABEL_SNAPSHOT_BUILT = "Snapshot built"

TOOLTIP_BAR_OPENED = "The time this bar's period began. Not when the data arrived."
TOOLTIP_EVALUABLE_FROM = (
    "A timing convention: the bar's open time plus one interval. It is a bound, "
    "not a record of when anyone actually received the data."
)
TOOLTIP_ASSESSMENT_AS_OF = (
    "The latest of the contributing bounds. It does not mean the assessment was "
    "available at that moment."
)

#: Shown wherever an assessment appears.
RESEARCH_DISCLAIMER = (
    "Research information only — not a trading recommendation. "
    "Nothing here places an order or touches real money."
)

#: Shown on the paper panel, worded to stay true regardless of exactly how
#: Streamlit handles a browser reconnect.
PAPER_SESSION_WARNING = (
    "Paper positions are temporary. Nothing here is saved to disk. Restarting "
    "the dashboard, refreshing the browser tab, or losing the current session "
    "will reset the paper portfolio to empty. This is a research tool — no real "
    "money, no broker, no orders."
)

#: Kept because a future extension may legitimately pass an adjusted series;
#: the limitation must not vanish behind the UI if it ever does.
PIT_WARNING = (
    "Adjusted history is not point-in-time safe: its factors depend on corporate "
    "actions that happened after these bars."
)

WARMUP_NOTE = "warming up"

_STATE_TEXT: dict[AssessmentState, str] = {
    AssessmentState.BULLISH: "BULLISH",
    AssessmentState.BEARISH: "BEARISH",
    AssessmentState.NEUTRAL: "NEUTRAL",
    AssessmentState.CONFLICTED: "CONFLICTED",
    AssessmentState.INSUFFICIENT_DATA: "INSUFFICIENT DATA",
}

_RESEARCH_STATE_TEXT: dict[ResearchState, str] = {
    ResearchState.BULLISH: "BULLISH",
    ResearchState.BEARISH: "BEARISH",
    ResearchState.NEUTRAL: "NEUTRAL",
    ResearchState.INSUFFICIENT_DATA: "NOT ENOUGH HISTORY YET",
}


def _stamp(value: datetime | None) -> str:
    return "—" if value is None else value.strftime("%Y-%m-%d %H:%M %Z").strip()


def humanise_reason(code: object) -> str:
    """Turn a closed reason code into readable words.

    Purely lexical: underscores to spaces. It adds no meaning the code did not
    already carry, so it cannot overclaim.
    """
    return str(getattr(code, "value", code)).replace("_", " ")


# -- market -------------------------------------------------------------


@dataclass(frozen=True)
class MarketView:
    symbol: str
    interval: str
    basis: str
    source: str
    history_label: str
    bar_count: int
    latest_bar_opened: str
    snapshot_built: str
    is_adjusted: bool
    rows: tuple[tuple[str, ...], ...]
    columns: tuple[str, ...] = (
        "Bar opened",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    )

    @property
    def pit_warning(self) -> str | None:
        """Only present when the basis actually is adjusted."""
        return PIT_WARNING if self.is_adjusted else None

    @property
    def source_note(self) -> str:
        """Attributed to the snapshot, never to the assessment.

        Bars and series carry ``source``; observations and assessments do not,
        so the sentence is phrased as a fact about the build.
        """
        return f"Snapshot built from {self.source}"


def market_view(snapshot: ResearchSnapshot, *, recent: int = 30) -> MarketView:
    bars = snapshot.series.bars[-recent:] if len(snapshot.series) else ()
    rows = tuple(
        (
            _stamp(bar.timestamp),
            f"{bar.open:,.2f}",
            f"{bar.high:,.2f}",
            f"{bar.low:,.2f}",
            f"{bar.close:,.2f}",
            f"{bar.volume:,.0f}",
        )
        for bar in bars
    )
    return MarketView(
        symbol=snapshot.symbol,
        interval=snapshot.interval.value,
        basis=snapshot.basis.value,
        source=snapshot.source,
        history_label=snapshot.history_label,
        bar_count=snapshot.bar_count,
        latest_bar_opened=_stamp(snapshot.latest_bar_open),
        snapshot_built=_stamp(snapshot.built_at),
        is_adjusted=snapshot.basis is not PriceBasis.RAW,
        rows=rows,
    )


# -- features -----------------------------------------------------------


@dataclass(frozen=True)
class FeatureRow:
    """One computed indicator, named twice: readably and canonically."""

    name: str
    key: str
    value: str
    is_warming_up: bool


def _feature_label(series: FeatureSeries) -> str:
    """``SMA 20`` from the feature's own name and period.

    Formatting only: the words come from what the feature engine already
    recorded on the series, so this cannot describe a feature that was not the
    one computed. Anything without a plain ``period`` keeps its canonical key.
    """
    period = dict(series.params).get("period")
    if period is None:
        return series.name.upper()
    return f"{series.name.upper()} {period}"


def feature_rows(snapshot: ResearchSnapshot) -> tuple[FeatureRow, ...]:
    """Latest value per computed feature.

    A warm-up ``None`` is rendered as text, never as ``0`` -- a zero would be a
    number the feature engine never produced.
    """
    rows: list[FeatureRow] = []
    for key in sorted(snapshot.features):
        series = snapshot.features[key]
        latest = series.values[-1] if len(series.values) else None
        rows.append(
            FeatureRow(
                name=_feature_label(series),
                key=key,
                value=WARMUP_NOTE if latest is None else f"{latest:,.4f}",
                is_warming_up=latest is None,
            )
        )
    return tuple(rows)


# -- observations -------------------------------------------------------


@dataclass(frozen=True)
class ObservationView:
    display_name: str
    hypothesis_id: str
    version: int
    fingerprint: str
    state: str
    is_insufficient: bool
    reasons: tuple[str, ...]
    evaluable_from: str
    evidence: tuple[tuple[str, str], ...]

    @property
    def label(self) -> str:
        return f"{self.hypothesis_id}@v{self.version}#{self.fingerprint}"


def observation_views(
    observations: Sequence[ResearchObservation],
    display_names: dict[str, str] | None = None,
) -> tuple[ObservationView, ...]:
    names = display_names or {}
    return tuple(
        ObservationView(
            display_name=names.get(o.hypothesis_id, o.hypothesis_id),
            hypothesis_id=o.hypothesis_id,
            version=o.version,
            fingerprint=o.fingerprint,
            state=_RESEARCH_STATE_TEXT[o.state],
            is_insufficient=o.state is ResearchState.INSUFFICIENT_DATA,
            reasons=tuple(humanise_reason(c) for c in o.reason_codes),
            evaluable_from=_stamp(o.evaluable_from),
            evidence=tuple(
                (k, WARMUP_NOTE if v is None else f"{v:,.4f}")
                for k, v in sorted(o.evidence.items())
            ),
        )
        for o in observations
    )


# -- assessment ---------------------------------------------------------


@dataclass(frozen=True)
class AssessmentView:
    state: str
    is_conflicted: bool
    is_insufficient: bool
    bullish: int
    bearish: int
    neutral: int
    insufficient: int
    sufficient: int
    total: int
    minimum_required: int
    reasons: tuple[str, ...]
    assessment_as_of: str
    policy_fingerprint: str
    bullish_names: tuple[str, ...]
    bearish_names: tuple[str, ...]
    #: Settled bars behind this assessment, and the ensemble's warm-up floor.
    #: Carried so an INSUFFICIENT_DATA panel can name the actual shortage
    #: rather than only the count that fell short of the policy minimum.
    bar_count: int | None = None
    warmup_bars: int | None = None
    disclaimer: str = RESEARCH_DISCLAIMER

    @property
    def conflict_explanation(self) -> str | None:
        """Stated as disagreement, never as a probability or low confidence."""
        if not self.is_conflicted:
            return None
        return (
            f"{self.bullish} hypothesis/hypotheses classified bullish and "
            f"{self.bearish} classified bearish at this bar. The evidence "
            "disagrees. This is not a probability and not 'somewhere in between'."
        )

    @property
    def short_history_note(self) -> str | None:
        """Present only when the series itself is below the warm-up floor.

        Two different shortages can produce ``INSUFFICIENT_DATA`` and a reader
        needs to tell them apart: too few bars to compute the indicators at
        all, versus enough bars but too few hypotheses classifying to meet the
        policy minimum. This names the first one when it is actually the case.
        """
        if self.bar_count is None or self.warmup_bars is None:
            return None
        if self.bar_count >= self.warmup_bars:
            return None
        return (
            f"There are {self.bar_count} settled bars; this ensemble needs "
            f"{self.warmup_bars} before every hypothesis can classify. The "
            "indicators are still warming up, so this is a shortage of history "
            "rather than a fault."
        )

    @property
    def insufficient_explanation(self) -> str | None:
        if not self.is_insufficient:
            return None
        base = (
            f"{self.sufficient} of {self.total} hypotheses could classify; this "
            f"policy needs at least {self.minimum_required}."
        )
        note = self.short_history_note
        return base if note is None else f"{base} {note}"


def assessment_view(
    assessment: ResearchAssessment,
    observations: Sequence[ResearchObservation],
    minimum_required: int,
    display_names: dict[str, str] | None = None,
    *,
    bar_count: int | None = None,
    warmup_bars: int | None = None,
) -> AssessmentView:
    """Format an assessment. State comes from the record, never recomputed."""
    names = display_names or {}
    counts = assessment.counts

    def named(state: ResearchState) -> tuple[str, ...]:
        return tuple(
            names.get(o.hypothesis_id, o.hypothesis_id)
            for o in observations
            if o.state is state
        )

    return AssessmentView(
        state=_STATE_TEXT[assessment.state],
        is_conflicted=assessment.state is AssessmentState.CONFLICTED,
        is_insufficient=assessment.state is AssessmentState.INSUFFICIENT_DATA,
        bullish=counts.bullish,
        bearish=counts.bearish,
        neutral=counts.neutral,
        insufficient=counts.insufficient,
        sufficient=counts.sufficient,
        total=counts.total,
        minimum_required=minimum_required,
        reasons=tuple(humanise_reason(c) for c in assessment.reason_codes),
        assessment_as_of=_stamp(assessment.assessment_as_of),
        policy_fingerprint=assessment.policy_fingerprint,
        bullish_names=named(ResearchState.BULLISH),
        bearish_names=named(ResearchState.BEARISH),
        bar_count=bar_count,
        warmup_bars=warmup_bars,
    )


# -- optional research provenance ---------------------------------------


#: Wording for the optional provenance control. It states the limit of what the
#: note is, so the checkbox cannot read as attaching evidence to an action.
PROVENANCE_LABEL = (
    "A note about what you were looking at — it does not verify anything."
)
PROVENANCE_HELP = (
    "Attaches which hypothesis you had on screen to this paper position, as a "
    "note. Phase 5 preserves it; nothing authenticates it, and it does not "
    "authorise or justify the action."
)


@dataclass(frozen=True)
class ProvenanceChoice:
    """One selectable "what I was reading" note.

    Carries the identity values Phase 5's ``ResearchProvenance`` requires, so
    the dashboard can offer the choice without importing a domain type. It is
    an option in a list, not a decision: selecting one changes nothing about
    whether an action is allowed.
    """

    label: str
    hypothesis_id: str
    hypothesis_version: int
    hypothesis_fingerprint: str
    observation_timestamp: datetime


def provenance_choices(
    observations: Sequence[ResearchObservation],
    display_names: dict[str, str] | None = None,
) -> tuple[ProvenanceChoice, ...]:
    """Offer each observation in the current snapshot as a possible note."""
    names = display_names or {}
    return tuple(
        ProvenanceChoice(
            label=f"{names.get(o.hypothesis_id, o.hypothesis_id)} ({o.hypothesis_id})",
            hypothesis_id=o.hypothesis_id,
            hypothesis_version=o.version,
            hypothesis_fingerprint=o.fingerprint,
            observation_timestamp=o.timestamp,
        )
        for o in observations
    )


# -- paper --------------------------------------------------------------


@dataclass(frozen=True)
class PositionRow:
    position_id: str
    symbol: str
    notional: str
    opened_at: str
    closed_at: str


def position_rows(positions: Sequence[PaperPosition]) -> tuple[PositionRow, ...]:
    return tuple(
        PositionRow(
            position_id=p.position_id,
            symbol=p.symbol,
            notional=f"{p.notional:,}",
            opened_at=_stamp(p.opened_at),
            closed_at=_stamp(p.closed_at),
        )
        for p in positions
    )


@dataclass(frozen=True)
class PortfolioView:
    open_rows: tuple[PositionRow, ...]
    closed_rows: tuple[PositionRow, ...]
    total_open_notional: str
    open_position_count: int
    max_notional_per_position: str
    max_total_notional: str
    max_open_positions: int
    allow_duplicate_symbol: bool
    session_warning: str = PAPER_SESSION_WARNING


def portfolio_view(portfolio, policy: RiskPolicy) -> PortfolioView:
    return PortfolioView(
        open_rows=position_rows(portfolio.open_positions),
        closed_rows=position_rows(portfolio.closed_positions),
        total_open_notional=f"{portfolio.total_open_notional:,}",
        open_position_count=portfolio.open_position_count,
        max_notional_per_position=f"{policy.max_notional_per_position:,}",
        max_total_notional=f"{policy.max_total_notional:,}",
        max_open_positions=policy.max_open_positions,
        allow_duplicate_symbol=policy.allow_duplicate_symbol,
    )


@dataclass(frozen=True)
class DecisionView:
    approved: bool
    outcome: str
    intent_id: str
    policy_fingerprint: str
    reasons: tuple[str, ...]

    @property
    def note(self) -> str:
        """A rejection is a normal policy outcome, and it is retryable."""
        if self.approved:
            return "Approved and recorded in the paper portfolio."
        return (
            "Rejected by the risk policy. This is a normal outcome, not an error — "
            "you can try again with different values."
        )


def decision_view(decision: RiskDecision) -> DecisionView:
    return DecisionView(
        approved=decision.approved,
        outcome=decision.outcome.value.upper(),
        intent_id=decision.intent_id,
        policy_fingerprint=decision.policy_fingerprint,
        reasons=tuple(humanise_reason(c) for c in decision.reason_codes),
    )


# -- news ---------------------------------------------------------------


#: Wording for each association kind. The Yahoo phrasing is the whole point of
#: the enum: the payload names no ticker, so "returned for AAPL" is the
#: strongest true statement and "about AAPL" would be a claim nobody made.
_ASSOCIATION_TEXT: dict[str, str] = {
    "verified_source": "Filed by this company (identified by the SEC)",
    "queried_symbol": "Returned for {symbol} — the source named no ticker",
    "inferred": "Inferred association",
}

#: Labels for the timing facts. "Accepted by the SEC" is not "published to the
#: world", and the label says so rather than letting a reader assume.
LABEL_SOURCE_EVENT = "Accepted by the SEC"
LABEL_SOURCE_PUBLISHED = "Publisher's stated time"
LABEL_RETRIEVED = "Fetched by this dashboard"

TOOLTIP_SOURCE_EVENT = (
    "When EDGAR accepted the filing. It is the earliest instant it could have "
    "been available, not a record of when it reached the public."
)
TOOLTIP_RETRIEVED = (
    "When this dashboard fetched the record. It says nothing about when the "
    "source published it."
)

NEWS_DISCLAIMER = (
    "External information only — headlines and filing metadata as published by "
    "their sources. Nothing here is analysed, scored or turned into a view."
)


@dataclass(frozen=True)
class NewsRow:
    """One external record, formatted. Carries no judgement of any kind."""

    headline: str
    publisher: str
    source: str
    source_class: str
    is_official: bool
    association: str
    url: str
    source_time_label: str
    source_time: str
    retrieved_at: str
    availability_basis: str
    form: str = ""
    items: str = ""
    summary: str = ""


def news_rows(snapshot, *, recent: int = 50) -> tuple[NewsRow, ...]:
    """Format a NewsSnapshot's documents in the order the snapshot supplies.

    The order is not recomputed here: chronology belongs to the application
    layer, and re-sorting by source class in the view would be exactly the
    distortion that layer refuses.
    """
    rows: list[NewsRow] = []
    for document in snapshot.documents[:recent]:
        association = snapshot.association_for(document)
        wording = _ASSOCIATION_TEXT.get(
            getattr(association, "value", ""), "Association not recorded"
        ).format(symbol=snapshot.symbol)
        official = document.source_class.is_official
        rows.append(
            NewsRow(
                headline=document.headline,
                publisher=document.publisher,
                source=document.source,
                source_class="Official filing" if official else "News report",
                is_official=official,
                association=wording,
                url=document.canonical_url,
                source_time_label=(
                    LABEL_SOURCE_EVENT if official else LABEL_SOURCE_PUBLISHED
                ),
                source_time=_stamp(document.source_time),
                retrieved_at=_stamp(document.retrieved_at),
                availability_basis=document.availability_basis.value,
                form=getattr(document, "form", ""),
                items=", ".join(getattr(document, "items", ())),
                summary=document.summary,
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class SourceOutcomeRow:
    """One source's result, worded so a partial refresh cannot read as success."""

    source: str
    outcome: str
    is_healthy: bool
    detail: str
    counters: str


@dataclass(frozen=True)
class NewsView:
    symbol: str
    built_at: str
    status: str
    is_partial: bool
    all_failed: bool
    rows: tuple[NewsRow, ...]
    sources: tuple[SourceOutcomeRow, ...]
    official_count: int
    secondary_count: int
    integrity_warning: str | None = None
    cik_map_note: str = ""
    disclaimer: str = NEWS_DISCLAIMER

    @property
    def status_note(self) -> str:
        if self.all_failed:
            return "No source could be reached. Nothing below has been updated."
        if self.is_partial:
            return (
                "Partial refresh: at least one source did not answer. What is shown "
                "may be missing records from that source."
            )
        return "Every configured source answered."


def news_view(snapshot) -> NewsView:
    """Format a NewsSnapshot. State and ordering come from the snapshot."""
    status = snapshot.status.value
    sources = tuple(
        SourceOutcomeRow(
            source=result.source,
            outcome=result.outcome.value.replace("_", " ").upper(),
            is_healthy=result.is_healthy,
            detail=result.detail,
            counters=result.counters.describe(),
        )
        for result in snapshot.source_results
    )
    warning = (
        f"Some stored records could not be read and were left untouched: "
        f"{snapshot.integrity.describe()}"
        if snapshot.has_integrity_warning
        else None
    )
    return NewsView(
        symbol=snapshot.symbol,
        built_at=_stamp(snapshot.built_at),
        status=status.replace("_", " ").upper(),
        is_partial=status == "partial",
        all_failed=status == "all_failed",
        rows=news_rows(snapshot),
        sources=sources,
        official_count=len(snapshot.official),
        secondary_count=len(snapshot.secondary),
        integrity_warning=warning,
        cik_map_note=(
            f"SEC ticker map vintage: {snapshot.cik_map_last_modified}. It maps "
            "tickers as they are today and is not evidence of a historical mapping."
            if snapshot.cik_map_last_modified
            else ""
        ),
    )


__all__ = [
    "MarketView",
    "market_view",
    "FeatureRow",
    "feature_rows",
    "ObservationView",
    "observation_views",
    "AssessmentView",
    "assessment_view",
    "PositionRow",
    "position_rows",
    "PortfolioView",
    "portfolio_view",
    "DecisionView",
    "decision_view",
    "ProvenanceChoice",
    "provenance_choices",
    "PROVENANCE_LABEL",
    "PROVENANCE_HELP",
    "NewsRow",
    "news_rows",
    "NewsView",
    "news_view",
    "SourceOutcomeRow",
    "NEWS_DISCLAIMER",
    "LABEL_SOURCE_EVENT",
    "LABEL_SOURCE_PUBLISHED",
    "LABEL_RETRIEVED",
    "TOOLTIP_SOURCE_EVENT",
    "TOOLTIP_RETRIEVED",
    "humanise_reason",
    "RESEARCH_DISCLAIMER",
    "PAPER_SESSION_WARNING",
    "PIT_WARNING",
    "WARMUP_NOTE",
    "LABEL_BAR_OPENED",
    "LABEL_EVALUABLE_FROM",
    "LABEL_ASSESSMENT_AS_OF",
    "LABEL_SNAPSHOT_BUILT",
    "TOOLTIP_BAR_OPENED",
    "TOOLTIP_EVALUABLE_FROM",
    "TOOLTIP_ASSESSMENT_AS_OF",
]
