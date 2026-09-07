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


# -- external feeds (Phase 9) -------------------------------------------

LABEL_FEED_PUBLISHED = "Publisher's stated publication time"
LABEL_FEED_UPDATED = "Publisher's stated update time"
LABEL_FEED_OBSERVED = "First seen by this dashboard"

TOOLTIP_FEED_UPDATED = (
    "The feed gave an update time and no publication time. It is shown as an "
    "update, because calling it a publication time would state something the "
    "publisher did not."
)
TOOLTIP_FEED_TRUST = (
    "This label comes from your own configuration file. Nothing about the feed "
    "has been verified by this dashboard."
)

FEEDS_DISCLAIMER = (
    "External feeds only — entries exactly as their publishers wrote them. "
    "Nothing here is analysed, scored, ranked or fact-checked, and nothing here "
    "reaches research, assessments or paper trading."
)

FEEDS_TRUST_DISCLAIMER = (
    "Trust labels are yours, not ours: they record how you described a feed when "
    "you added it. This dashboard does not verify that a feed is who it claims "
    "to be."
)

#: One approved phrase per availability basis. The vocabulary lives here so no
#: renderer can invent a friendlier word for a weaker claim.
_FEED_BASIS_LABEL = {
    "source_published": LABEL_FEED_PUBLISHED,
    "source_updated": LABEL_FEED_UPDATED,
    "system_observed": LABEL_FEED_OBSERVED,
    "unknown": "No usable time",
}


@dataclass(frozen=True)
class FeedItemRow:
    """One feed entry, formatted. Carries no judgement of any kind."""

    title: str
    publisher: str
    source_id: str
    source_name: str
    trust_label: str
    trust_class: str
    association: str
    url: str
    is_safe_url: bool
    source_time_label: str
    source_time: str
    retrieved_at: str
    availability_basis: str
    excerpt: str = ""
    symbols: str = ""
    revision: int = 1

    @property
    def is_revision(self) -> bool:
        """Whether the publisher has changed this entry since we first stored it."""
        return self.revision > 1

    @property
    def revision_note(self) -> str:
        if not self.is_revision:
            return ""
        return (
            f"Revision {self.revision}: the publisher changed this entry after we "
            "first stored it. Earlier versions are kept."
        )


def feed_item_rows(snapshot, *, recent: int = 50) -> tuple[FeedItemRow, ...]:
    """Format a FeedSnapshot's items in the order the snapshot supplies.

    The order is not recomputed here. Chronology belongs to the application
    layer, and re-sorting by trust class in the view would let a label typed
    into a config file rearrange time.
    """
    from src.feeds.validation import is_safe_display_url

    rows: list[FeedItemRow] = []
    for item in snapshot.items[:recent]:
        definition = snapshot.definition_for(item.source_id)
        symbols = snapshot.symbols_for(item)
        rows.append(
            FeedItemRow(
                title=item.title,
                publisher=item.publisher,
                source_id=item.source_id,
                source_name=definition.display_name if definition else item.source_id,
                # Read from the item, never from today's configuration: renaming a
                # feed "official" now must not relabel what we stored last week.
                trust_label=item.declared_trust_class.label,
                trust_class=item.declared_trust_class.value,
                association=(
                    ", ".join(
                        f"From a feed configured for {symbol}" for symbol in symbols
                    )
                    if symbols
                    else "This feed is not configured for any symbol"
                ),
                url=item.canonical_url,
                is_safe_url=is_safe_display_url(item.canonical_url),
                source_time_label=_FEED_BASIS_LABEL.get(
                    item.availability_basis.value, "No usable time"
                ),
                source_time=_stamp(item.source_time),
                retrieved_at=_stamp(item.retrieved_at),
                availability_basis=item.availability_basis.value,
                excerpt=item.excerpt,
                symbols=", ".join(symbols),
                revision=item.revision,
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class FeedSourceRow:
    """One feed's result, worded so a partial refresh cannot read as success."""

    source_id: str
    source_name: str
    outcome: str
    is_healthy: bool
    detail: str
    counters: str
    trust_label: str = ""
    url_host: str = ""


@dataclass(frozen=True)
class FeedsView:
    built_at: str
    status: str
    is_partial: bool
    all_failed: bool
    is_configured: bool
    rows: tuple[FeedItemRow, ...]
    sources: tuple[FeedSourceRow, ...]
    item_count: int
    unconfigured_message: str = ""
    integrity_warning: str | None = None
    disclaimer: str = FEEDS_DISCLAIMER
    trust_disclaimer: str = FEEDS_TRUST_DISCLAIMER

    @property
    def status_note(self) -> str:
        if not self.is_configured:
            return "No feeds are configured, so nothing was fetched."
        if self.all_failed:
            return "No configured feed could be reached. Nothing below has been updated."
        if self.is_partial:
            return (
                "Partial refresh: at least one feed did not answer. What is shown may "
                "be missing entries from that feed."
            )
        return "Every configured feed answered."


def feeds_view(snapshot) -> FeedsView:
    """Format a FeedSnapshot. State and ordering come from the snapshot."""
    from src.feeds.identity import url_host

    status = snapshot.status.value
    sources = []
    for result in snapshot.source_results:
        definition = snapshot.definition_for(result.source_id)
        sources.append(
            FeedSourceRow(
                source_id=result.source_id,
                source_name=definition.display_name if definition else result.source_id,
                outcome=result.outcome.value.replace("_", " ").upper(),
                is_healthy=result.is_healthy,
                detail=result.detail,
                counters=result.counters.describe(),
                trust_label=(
                    definition.declared_trust_class.label if definition else ""
                ),
                url_host=url_host(definition.url) if definition else "",
            )
        )
    warning = (
        f"Some stored entries could not be read and were left untouched: "
        f"{snapshot.integrity.describe()}"
        if snapshot.has_integrity_warning
        else None
    )
    return FeedsView(
        built_at=_stamp(snapshot.built_at),
        status=status.replace("_", " ").upper(),
        is_partial=status == "partial",
        all_failed=status == "all_failed",
        is_configured=snapshot.is_configured,
        rows=feed_item_rows(snapshot),
        sources=tuple(sources),
        item_count=len(snapshot.items),
        unconfigured_message="" if snapshot.is_configured else _feeds_unconfigured(),
        integrity_warning=warning,
    )


def _feeds_unconfigured() -> str:
    from src.application.feeds import UNCONFIGURED_MESSAGE

    return UNCONFIGURED_MESSAGE


# -- market scanner (Phase 10) -------------------------------------------

SCANNER_DISCLAIMER = (
    "Research candidates only — symbols are ordered by the structure of the "
    "evidence, not by investment merit. Nothing here is a recommendation, a "
    "score or a prediction, and nothing here reaches paper trading."
)

SCANNER_EMPTY_HELP = (
    "The scanner is manual: nothing is fetched until you press Scan Market. It "
    "scans daily bars over the universe you select."
)

SCANNER_INTERVAL_NOTE = (
    "Market scans use daily bars. Weekly and monthly remain available in "
    "single-symbol Research."
)

SCANNER_ORDERING_NOTE = (
    "Ordered by evidence structure, then by how many hypotheses classified, then "
    "by data freshness. Position means how much there is to inspect — not that "
    "one symbol is a better investment than another."
)

#: One approved phrase per structural category. The vocabulary lives here so no
#: renderer can invent a more flattering word for a weaker finding.
_CATEGORY_LABEL = {
    "unanimous_directional": "Unanimous directional",
    "directional_with_neutral": "Directional with neutral",
    "conflicted": "Conflicted",
    "neutral": "Neutral",
    "not_assessable": "Not assessable",
}

#: Assessment states are research classifications. There is deliberately no
#: mapping to Buy or Sell: the moment "bullish" becomes "buy", a classification
#: has been turned into advice the system never made.
_ASSESSMENT_LABEL = {
    "bullish": "Bullish",
    "bearish": "Bearish",
    "conflicted": "Conflicted",
    "neutral": "Neutral",
    "insufficient_data": "Insufficient data",
}

#: Deterministic, generated from category identity -- never freeform prose and
#: never model-written. Each states a fact about how the hypotheses stood.
_WHY_SURFACED = {
    "unanimous_directional": "All classified hypotheses agree directionally",
    "directional_with_neutral": "Directional evidence alongside neutral observations",
    "conflicted": "Hypotheses conflict on direction",
    "neutral": "All classified hypotheses agree there is no direction",
    "not_assessable": "No assessment was produced",
}

_ELIGIBILITY_LABEL = {
    "no_data": "No data",
    "insufficient_evidence": "Insufficient evidence",
}

#: Operational failures, worded as what went wrong technically. Kept separate
#: from the research states above because "the provider was down" and "this
#: symbol had little to say" are different facts about different things.
_ERROR_LABEL = {
    "provider_unavailable": "Provider unavailable",
    "data_quality": "Data quality issue",
    "symbol_mismatch": "Symbol mismatch",
    "request_invalid": "Request invalid",
    "unexpected": "Unexpected scanner error",
}

_NO_DATA_DETAIL = "The provider returned no usable bars for this symbol."
_INSUFFICIENT_DETAIL = (
    "Too few hypotheses classified for a finding; the history is there but the "
    "ensemble is still warming up."
)


@dataclass(frozen=True)
class ScannerRowView:
    """One assessable symbol, formatted. Carries no judgement of any kind."""

    symbol: str
    category: str
    category_label: str
    assessment: str
    bullish: int
    bearish: int
    neutral: int
    why_surfaced: str
    latest_bar: str
    data_cutoff: str


@dataclass(frozen=True)
class ScannerIssueRowView:
    """One symbol with nothing to assess, or one that failed operationally.

    ``is_operational_failure`` is the field that keeps the two apart. A provider
    outage and a symbol the provider simply had no bars for are different facts,
    and a panel that called both "failed" would misreport the healthy case.
    """

    symbol: str
    status: str
    detail: str
    is_operational_failure: bool
    latest_bar: str
    data_cutoff: str


@dataclass(frozen=True)
class ScannerSummaryView:
    """Headline facts about one completed scan."""

    universe_id: str
    universe_display_name: str
    universe_as_of: str
    fingerprint_prefix: str
    interval: str
    symbols_total: int
    symbols_completed: int
    symbols_eligible: int
    symbols_no_data: int
    symbols_insufficient_evidence: int
    operational_failures: int
    status: str
    duration_seconds: float
    scan_started_at: str
    scan_completed_at: str
    policy_fingerprint_prefix: str


@dataclass(frozen=True)
class ScannerView:
    """One completed scan, ready to render."""

    summary: ScannerSummaryView
    rows: tuple[ScannerRowView, ...]
    issues: tuple[ScannerIssueRowView, ...]
    disclaimer: str = SCANNER_DISCLAIMER
    ordering_note: str = SCANNER_ORDERING_NOTE

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)

    @property
    def eligible_symbols(self) -> tuple[str, ...]:
        """Symbols a user may open in Research -- assessable ones only."""
        return tuple(row.symbol for row in self.rows)

    @property
    def status_note(self) -> str:
        if self.summary.operational_failures == 0:
            return "Every symbol was scanned without an operational error."
        if self.summary.operational_failures == self.summary.symbols_completed:
            return (
                "No symbol could be scanned. Nothing below reflects current "
                "market data."
            )
        return (
            f"{self.summary.operational_failures} of "
            f"{self.summary.symbols_completed} symbols could not be scanned. "
            "The rest completed normally."
        )


def scanner_view(snapshot) -> ScannerView:
    """Format a MarketScanSnapshot. Ordering comes from the scanner, not here.

    The assessable rows are taken from the locked ranking helper rather than
    re-sorted: chronology and evidence structure belong to the application
    layer, and re-ordering in the view would be a second, disagreeing
    implementation of the ranking rules.
    """
    from src.application.scanner import ranked_rows

    rows = tuple(_row_view(result) for result in ranked_rows(snapshot))
    issues = tuple(
        _issue_view(result)
        for result in snapshot.results
        if result.eligibility is None or not result.is_eligible
    )
    return ScannerView(summary=_summary_view(snapshot), rows=rows, issues=issues)


def _summary_view(snapshot) -> ScannerSummaryView:
    counters = snapshot.counters
    return ScannerSummaryView(
        universe_id=snapshot.universe_id,
        universe_display_name=snapshot.universe_display_name,
        universe_as_of=snapshot.universe_as_of.isoformat(),
        # A prefix for humans; the snapshot keeps the full digest.
        fingerprint_prefix=snapshot.universe_fingerprint[:12],
        interval=snapshot.interval.value,
        symbols_total=counters.symbols_total,
        symbols_completed=counters.symbols_completed,
        symbols_eligible=counters.symbols_eligible,
        symbols_no_data=counters.symbols_no_data,
        symbols_insufficient_evidence=counters.symbols_insufficient_evidence,
        operational_failures=counters.symbols_failed,
        status=snapshot.status.value.replace("_", " ").upper(),
        duration_seconds=round(snapshot.duration_seconds, 2),
        scan_started_at=_stamp(snapshot.scan_started_at),
        scan_completed_at=_stamp(snapshot.scan_completed_at),
        policy_fingerprint_prefix=snapshot.policy_fingerprint[:12],
    )


def _row_view(result) -> ScannerRowView:
    counts = result.counts
    category = result.category.value
    return ScannerRowView(
        symbol=result.symbol,
        category=category,
        category_label=_CATEGORY_LABEL[category],
        assessment=_ASSESSMENT_LABEL[result.state.value],
        bullish=counts.bullish,
        bearish=counts.bearish,
        neutral=counts.neutral,
        why_surfaced=_WHY_SURFACED[category],
        latest_bar=_stamp(result.latest_bar_open),
        data_cutoff=_stamp(result.data_cutoff),
    )


def _issue_view(result) -> ScannerIssueRowView:
    if result.is_operational_failure:
        status = _ERROR_LABEL[result.error_code.value]
        detail = result.error_detail or "No further detail was reported."
    else:
        status = _ELIGIBILITY_LABEL[result.eligibility.value]
        detail = (
            _NO_DATA_DETAIL
            if result.eligibility.value == "no_data"
            else _INSUFFICIENT_DETAIL
        )
    return ScannerIssueRowView(
        symbol=result.symbol,
        status=status,
        detail=detail,
        is_operational_failure=result.is_operational_failure,
        latest_bar=_stamp(result.latest_bar_open),
        data_cutoff=_stamp(result.data_cutoff),
    )


def universe_option_label(definition) -> str:
    """Selector label: name, size and vintage -- never the raw fingerprint.

    ``as_of`` is shown because a membership list captured on one date and
    scanned across years of history is survivorship-biased, and hiding the
    vintage would hide that.
    """
    symbols = definition.symbol_count
    plural = "symbol" if symbols == 1 else "symbols"
    return (
        f"{definition.display_name} — {symbols} {plural}, "
        f"as of {definition.as_of.isoformat()}"
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
    "FeedItemRow",
    "feed_item_rows",
    "FeedSourceRow",
    "FeedsView",
    "feeds_view",
    "FEEDS_DISCLAIMER",
    "FEEDS_TRUST_DISCLAIMER",
    "LABEL_FEED_PUBLISHED",
    "LABEL_FEED_UPDATED",
    "LABEL_FEED_OBSERVED",
    "TOOLTIP_FEED_UPDATED",
    "TOOLTIP_FEED_TRUST",
    "ScannerRowView",
    "ScannerIssueRowView",
    "ScannerSummaryView",
    "ScannerView",
    "scanner_view",
    "universe_option_label",
    "SCANNER_DISCLAIMER",
    "SCANNER_EMPTY_HELP",
    "SCANNER_INTERVAL_NOTE",
    "SCANNER_ORDERING_NOTE",
]
