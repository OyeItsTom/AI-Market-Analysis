# AI Market Analysis

An educational, evidence-driven quantitative market-research and
**paper-trading** platform.

> **This system does not execute real-money trades.** It is a research and
> learning project. Nothing in it is investment advice, and no part of it is
> production-ready.

## Status

**Phase 1 — Market Data Foundation: implemented.**
**Phase 2 — Research data semantics + feature engine: implemented.**
**Phase 3 — Research hypothesis framework + CI: implemented.**
**Phase 4 — Causal outcome evaluation: implemented.**
**Phase 5 — Paper position + risk engine: implemented.**
**Phase 6 — Research assessment: implemented.**
**Phase 7 — Local research dashboard: implemented.**
**Phase 8 — News and company announcements: implemented.**
**Phase 9 — External RSS/Atom feeds: implemented.**
**Phase 10 — Market universe + multi-stock scanner: implemented.**
**Phase 11A — Grounded AI explanation of research evidence: implemented
(optional).**

Paper-trade execution is not implemented. Telegram is deferred — see
[ADR 0007](docs/adr/0007-external-feeds.md).

Phase 3 expresses research *hypotheses* that classify evidence. It contains no
trading logic and measures nothing about outcomes — a classification is not a
recommendation, and no profitability is claimed or measured.

Phase 5 records **manually entered** hypothetical positions and enforces
deterministic exposure limits on them. It is long-only, has no prices, no cash,
no P&L and no execution of any kind: a "position" there is a notional amount a
human chose to write down, not a trade. A research classification cannot
create one — the two are separated by construction, not by convention.

Phase 7 adds a **localhost-only** Streamlit interface for reading the existing
pipeline, plus a manual paper panel. It introduces no research rule and no new
capability: every state and count on screen was produced by a Phase 1-6 module.
The research panel has no paper-action control and the paper panel is never
shown an assessment, so nothing in the interface turns a classification into a
position.
Paper state is session-only and is never written to disk.

```
streamlit run src/dashboard/app.py --server.address=127.0.0.1
```

It binds to the loopback interface only. See
**[docs/dashboard.md](docs/dashboard.md)**.

Phase 8 adds an auditable **external-information layer**: official SEC filings
and reported news, recorded with honest provenance and timing. It **records but
does not interpret** — no sentiment, no score, no classifier. News is a separate
snapshot that never changes a `ResearchAssessment` and never opens a paper
position. Symbols are supported where the SEC ticker map resolves a CIK; EDGAR
needs a contact address in `SEC_USER_AGENT` (see `.env.example`), and Yahoo news
works without it. See **[docs/news.md](docs/news.md)**.

Phase 9 adds **external RSS/Atom feeds** you configure yourself. Copy
`config/external_feeds.example.json` to `config/external_feeds.local.json`
(git-ignored) and press *Refresh feeds*; only feeds listed there are ever
fetched, and no link inside an entry is followed. Like Phase 8 it **records but
does not interpret**, and it reaches neither research nor paper trading. Trust
labels are your own and are shown as such — nothing verifies that a feed belongs
to whoever it claims to. An Atom `updated` with no `published` is recorded as an
*update* time, never relabelled as a publication. Telegram is **deferred** —
input and output — for the reasons in the ADR. Zero new dependencies. See
**[docs/feeds.md](docs/feeds.md)**.

Phase 10 adds a **market scanner**: a *Market Overview* tab that scans a bounded
universe of symbols you configure yourself. Copy
`config/universes.example.json` to `config/universes.local.json` (git-ignored)
and press *Scan Market*; nothing is scanned until you do, and the example file
is never loaded automatically. Results are ordered by the **structure of the
research evidence** — there is no score, no confidence and no direction
preference, and position means how much there is to inspect rather than which
symbol is a better investment. Scans are daily-only, serial and manual;
selecting a result only sets the Research symbol and fetches nothing. News and
feeds reach neither the ordering nor the results, and the panel exposes no paper
action. Zero new dependencies. See **[docs/scanner.md](docs/scanner.md)**.

Phase 11A adds an **optional grounded AI explanation** of the research evidence
already on screen. Below the assessment, an *Explain with AI* button sends a
bounded view of that evidence — symbol, interval, assessment state and counts,
each hypothesis's classification, reason codes, latest bar time and recorded
evidence values — to an external AI provider, and shows the answer only after
it has been validated against the evidence it was given: every statement must
cite evidence that exists, trading vocabulary is refused, and a rejected answer
is shown as its rejection rather than in part. The deterministic research
owns the assessment; the model only puts it into words, and it can neither
predict, recommend, nor reach a paper action. It is off unless both
`ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` are set (see `.env.example`; there is
no default model), and with them unset the dashboard is unchanged. Nothing is
explained automatically, one click asks at most once, and raw market history,
news, feeds, scanner results and paper positions are never sent. See
**[docs/reasoning.md](docs/reasoning.md)**.

## Target architecture

```
Market Data  →  Validation  →  Normalized OHLCV  →  Feature Engine
     →  Strategy Engines  →  Backtesting  →  Evaluation
     →  Risk Engine  →  Signal Engine  →  Paper Trading  →  Dashboard
```

Phase 1 covers the first three boxes.

## What exists today

```
src/data/
├── models.py            MarketBar, Interval — the canonical OHLCV record
├── provider.py          MarketDataProvider abstract base + error types
├── normalization.py     vendor records → MarketBar
├── validation.py        per-bar and per-series validation rules
├── storage.py           CsvBarStore — local CSV cache under data/raw/
├── series.py            BarSeries + PriceBasis — the safe research unit
├── corporate_actions.py splits and cash dividends
├── adjustment.py        explicit raw → adjusted transform
├── sessions.py          gap contract (exchange calendar DEFERRED)
└── providers/
    ├── yahoo.py         yfinance adapter (development / fallback source)
    └── alpaca.py        architectural stub

src/strategies/          research hypothesis framework (no trading logic)
├── spec.py              FeatureSpec / HypothesisSpec + deterministic fingerprint
├── research.py          ResearchState, ReasonCode, ResearchObservation
├── evidence.py          EvidenceSet + causal EvidenceWindow
├── base.py              ResearchHypothesis contract (causal by construction)
└── hypotheses.py        three example hypotheses (2 point-in-time, 1 history)

src/portfolio/           paper position + risk domain (PAPER ONLY, no execution)
├── intent.py            PaperIntent (OpenLong/Close) + optional provenance
├── policy.py            RiskPolicy (+ fingerprint), RiskDecision
├── position.py          immutable PaperPosition
└── portfolio.py         immutable PaperPortfolio + apply()

src/assessments/         combined research classification (no trading semantics)
├── policy.py            AssessmentPolicy + aggregation-rule identity
├── assessment.py        AssessmentState, counts, reason codes, ResearchAssessment
└── aggregate.py         assess() — directional_presence_v1

src/evaluation/          outcome evaluation (no trading simulation)
├── outcome.py           OutcomeSpec + immutable EvaluatedOutcome
├── evaluate.py          causal evaluation against subsequent bars
└── metrics.py           EvaluationSummary + benchmark

src/features/            pure feature functions over BarSeries
├── base.py              FeatureSeries, warm-up and timing semantics
├── returns.py           simple and log returns
├── trend.py             SMA, EMA
├── momentum.py          Wilder RSI
├── volatility.py        realized volatility, ATR
└── volume.py            average and relative volume
```

Documentation: **[docs/market_data.md](docs/market_data.md)** (Phase 1),
**[docs/feature_engine.md](docs/feature_engine.md)** (Phase 2),
**[docs/research_framework.md](docs/research_framework.md)** (Phase 3),
**[docs/research_evaluation.md](docs/research_evaluation.md)** (Phase 4),
**[docs/paper_risk_engine.md](docs/paper_risk_engine.md)** (Phase 5),
**[docs/research_assessment.md](docs/research_assessment.md)** (Phase 6),
**[docs/dashboard.md](docs/dashboard.md)** (Phase 7),
**[docs/news.md](docs/news.md)** (Phase 8),
**[docs/feeds.md](docs/feeds.md)** (Phase 9),
**[docs/scanner.md](docs/scanner.md)** (Phase 10),
**[docs/reasoning.md](docs/reasoning.md)** (Phase 11A),
**[ADR 0001](docs/adr/0001-price-basis-and-corporate-actions.md)** (price basis
and corporate actions), **[ADR 0002](docs/adr/0002-outcome-evaluation-conventions.md)**
(outcome evaluation conventions),
**[ADR 0003](docs/adr/0003-paper-position-risk-engine.md)** (paper position and
risk engine), **[ADR 0004](docs/adr/0004-research-assessment.md)** (research
assessment), **[ADR 0005](docs/adr/0005-local-dashboard.md)** (local
dashboard), **[ADR 0006](docs/adr/0006-news-and-announcements.md)** (news and
announcements), **[ADR 0007](docs/adr/0007-external-feeds.md)** (external
feeds), **[ADR 0008](docs/adr/0008-market-scanner.md)** (market universe and
scanner), **[ADR 0009](docs/adr/0009-grounded-reasoning.md)** (grounded AI
explanation).

### The core idea

Strategies, backtests and risk code depend on `MarketBar` and
`MarketDataProvider` — never on a vendor SDK. A vendor's column names,
timezone quirks and error types stop at its adapter. Swapping Yahoo for
Alpaca, or replaying a stored dataset, changes one class and nothing else.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

```python
from datetime import datetime, timezone

from src.data import CsvBarStore, Interval, SeriesKey
from src.data.providers import YahooFinanceProvider

provider = YahooFinanceProvider()
bars = provider.get_bars(
    "AAPL",
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 3, 1, tzinfo=timezone.utc),
    Interval.DAY_1,
)

store = CsvBarStore()
store.write(bars)  # only settled bars; pass include_unsettled=True for the forming one
cached = store.read(SeriesKey("AAPL", Interval.DAY_1, "yfinance"))
```

## Data sources

| Provider | Status | Notes |
| --- | --- | --- |
| Yahoo (`yfinance`) | working | Development / fallback only. Unofficial endpoint, delayed, rate-limited, short intraday history. **Raw/unadjusted prices — corporate actions are not modelled, so a split looks like an extreme return.** Not market-grade. |
| Alpaca | stub | Interface only. Needs `alpaca-py` and **paper-trading** credentials from the environment. See `docs/market_data.md`. |

## Configuration and secrets

Copy `.env.example` to `.env` and fill in your own values. `.env` is
git-ignored; API keys never belong in code, in logs or in commits. Phase 1
needs no credentials at all, and neither do the Phase 9 external feeds — they
read public feeds over HTTPS and carry no credentials of any kind.

Your feed list lives in `config/external_feeds.local.json` (git-ignored, copied
from `config/external_feeds.example.json`). Ingested feed entries live in
`data/feeds/`, also git-ignored — downloaded third-party content is never
committed.

Your scan universes live in `config/universes.local.json` (git-ignored, copied
from `config/universes.example.json`). The example is a template and is never
loaded automatically: with no local file the scanner has no universe and scans
nothing.

The Phase 11A AI explanation needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`,
both required together and both optional for everything else. With either missing, blank or malformed the
feature is simply off. The key is read only inside
`src/application/reasoning_composition.py`, never by a dashboard module, and
never appears on screen or in session state.

Downloaded market data lives in `data/raw/` and `data/processed/`, both
git-ignored — datasets are never committed.

## Testing

```bash
pytest -q
```

The suite runs entirely offline: provider tests inject fake responses and
storage tests use temporary directories.

**Supported Python version: 3.11.** CI (`.github/workflows/tests.yml`) runs
`compileall`, an import check and the full suite on pushes to `main` and on
pull requests.

## Not implemented (by design, for later phases)

Economic simulation (trades, fills, costs, slippage, cash balances, equity
curves, drawdown, Sharpe), buy/sell recommendations, ML prediction, AI
prediction, target prices, automated trading decisions, LLM analysis of news or
feeds, portfolio optimization, automated position sizing, and any form of
broker order execution — including live-money trading.

What **is** implemented on the AI side is narrower than any of those: Phase 11A's
optional, grounded LLM explanation of deterministic research evidence. It
explains an assessment the pipeline already made; it does not make one,
forecast anything, or recommend anything. This is not an AI trading bot.

Phase 7's dashboard displays this pipeline; it does not extend it. It has no
scheduler, no background refresh, no persistence, no authentication and no
network exposure beyond the loopback interface.

Phase 8 stores external information locally, but interprets none of it. It has
no sentiment analysis, no LLM, no article-body storage, no scraping, no
scheduler and no route from a headline to a research state or a paper action.

Phase 5 introduces `PaperPosition`, so "positions" above means *simulated
economic positions*: Phase 5 tracks nominal exposure only. It has no prices, so
nothing is marked to market and no profit or loss exists to compute. Position
size is supplied by the human, never derived.

The Phase 2 feature engine computes indicators as *research inputs*. The
Phase 3 framework classifies that evidence into research states. Phase 4
measures what happened *after* a classification without simulating any trade.
Phase 6 combines several classifications into one assessment — with counts, not
confidence, and no path to a paper action. None of them produce trading signals,
predictions, or any claim about profitability.
