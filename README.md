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

Paper-trade execution is not implemented. Phase 8 has not been started.

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
The research panel has no action control and the paper panel is never shown an
assessment, so nothing in the interface turns a classification into a position.
Paper state is session-only and is never written to disk.

```
streamlit run src/dashboard/app.py --server.address=127.0.0.1
```

It binds to the loopback interface only. See
**[docs/dashboard.md](docs/dashboard.md)**.

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
**[ADR 0001](docs/adr/0001-price-basis-and-corporate-actions.md)** (price basis
and corporate actions), **[ADR 0002](docs/adr/0002-outcome-evaluation-conventions.md)**
(outcome evaluation conventions),
**[ADR 0003](docs/adr/0003-paper-position-risk-engine.md)** (paper position and
risk engine), **[ADR 0004](docs/adr/0004-research-assessment.md)** (research
assessment), **[ADR 0005](docs/adr/0005-local-dashboard.md)** (local
dashboard).

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
needs no credentials at all.

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
curves, drawdown, Sharpe), buy/sell recommendations, ML/AI prediction, LLM or
news analysis, portfolio optimization, automated position sizing, and any form
of broker order execution — including live-money trading.

Phase 7's dashboard displays this pipeline; it does not extend it. It has no
scheduler, no background refresh, no persistence, no authentication and no
network exposure beyond the loopback interface.

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
