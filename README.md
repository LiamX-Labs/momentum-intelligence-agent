# Momentum Intelligence Agent

Autonomous AI-driven options trading system for S&P 500 stocks. Combines quantitative momentum screening, fundamental analysis, and a dual-model adversarial AI architecture to identify, debate, and execute short-term (7–21 day) options trades on the Alpaca paper trading platform.

## Architecture

```
                 ┌─────────────────────────────────┐
                 │        S&P 500 Universe          │
                 └──────────────┬──────────────────┘
                                │
   ┌────────────────────────────▼────────────────────────────────┐
   │  PHASE A — Core Trading Engine (Quantitative)               │
   │  • Alpaca market data (1d / 4h bars)                        │
   │  • Technical indicators (EMA 5/10/20/50, RSI 14, ATR)       │
   │  • Multi-lookback momentum scoring (1d to 20d windows)      │
   │  • Market regime classification (BULL / NEUTRAL / BEAR)     │
   │  • SPY relative strength + VIX integration                  │
   │  • Top 50 momentum candidates ranked & scored               │
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE B — Fundamental Intelligence                         │
   │  • Financials (growth, margins, valuation, quality scores)   │
   │  • Earnings (EPS surprises, next date, quarterly growth)    │
   │  • Catalysts / News (headline classification, sentiment)    │
   │  • Merged enriched profiles for each candidate              │
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE C — Dual-Model AI (Adversarial Debate)               │
   │                                                             │
   │  ┌───────────────────┐     ┌────────────────────┐          │
   │  │  K2 Analyst       │────▶│  Qwen Critic       │          │
   │  │  (Kimi K2-Instruct)│     │  (Qwen3-32B)       │          │
   │  │                   │     │                    │          │
   │  │  Builds thesis    │     │  Falsifies thesis  │          │
   │  │  Sets direction   │     │  Adjusts confidence│          │
   │  │  Estimates holding│     │  Scores risk       │          │
   │  └───────────────────┘     └─────────┬──────────┘          │
   │                                      │                      │
   │                              APPROVE or REJECT              │
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE R — Cycle Reporter                                   │
   │  • DeepSeek V3.2 generates natural language summary         │
   │  • Per-verdict rationale for every candidate                │
   │  • Cycle-level narrative of all decisions                   │
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE D — Deterministic Risk & Decision Engine             │
   │                                                             │
   │  12 Hard Gates (every gate is deterministic Python):        │
   │  ┌──────────────────────────────────────────────────────┐  │
   │  │ 1. AI: Qwen critic approval                          │  │
   │  │ 2. AI: K2 confidence threshold                       │  │
   │  │ 3. Momentum score threshold                          │  │
   │  │ 4. Final composite score ≥ 0.50                      │  │
   │  │ 5. Market regime exposure check                      │  │
   │  │ 6. Max open positions                                │  │
   │  │ 7. Position sizing / contract count                  │  │
   │  │ 8. Max risk per trade (1% of portfolio)              │  │
   │  │ 9. Portfolio premium exposure                        │  │
   │  │ 10. Symbol exposure concentration                    │  │
   │  │ 11. Earnings in holding period                       │  │
   │  │ 12. Qwen risk score check                            │  │
   │  └──────────────────────────────────────────────────────┘  │
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE E — Options Selector & Paper Execution               │
   │  • Option chain retrieval (Alpaca Trading API)              │
   │  • Contract selection (7 filters + scoring):                │
   │    - DTE range (7–21 days)                                  │
   │    - Minimum bid price ($0.15)                              │
   │    - Minimum open interest (100)                            │
   │    - Maximum bid/ask spread (10%)                           │
   │    - Strike proximity to underlying (≤10%)                  │
   │    - Delta target range (0.40–0.65)                         │
   │  • Position sizing (risk-based contract count)              │
   │  • Chunked order execution (500 contracts max per sub-order)│
   └──────────────┬──────────────────────────────────────────────┘
                  │
   ┌──────────────▼──────────────────────────────────────────────┐
   │  PHASE F — Position Monitoring & Auto-Exit                  │
   │                                                             │
   │  7 Exit Conditions:                                         │
   │  ┌──────────────────────────────────────────────────────┐  │
   │  │ 1. Stop-loss (momentum rank decay)                   │  │
   │  │ 2. Time stop (max holding days exceeded)             │  │
   │  │ 3. Profit target reached                             │  │
   │  │ 4. Momentum rank collapse                            │  │
   │  │ 5. Technical invalidation (EMA / RSI breakdown)      │  │
   │  │ 6. Thesis invalidation (conditions met)              │  │
   │  │ 7. Market regime hostility                           │  │
   │  └──────────────────────────────────────────────────────┘  │
   └─────────────────────────────────────────────────────────────┘
```

## The Adversarial AI Design

The core innovation is the **K2 ↔ Qwen adversarial debate**:

| Role | Model | Function |
|------|-------|----------|
| **K2 Analyst** | Kimi K2-Instruct | Receives raw evidence (momentum, fundamentals, earnings, catalysts, regime). Builds a trading thesis: direction (CALL/PUT), confidence score, invalidation conditions, expected holding days. |
| **Qwen Critic** | Qwen3-32B | Receives the **same raw evidence PLUS K2's thesis**. Its job is to **falsify** the trade, not confirm it. Outputs: APPROVE/REJECT recommendation, adjusted confidence, risk score, concerns, contradictions. |

**Neither model ever triggers orders.** The LLMs only produce structured opinions. All trade decisions pass through Python deterministic gates. All option contract selection is deterministic.

### The Bypass System (configurable in `config/config.yaml`)

Under `demo:`:
- `qwen_advisory_only`: When `true`, Qwen's REJECT becomes a logged warning rather than a block. When `false`, Qwen's REJECT blocks the trade.
- `override_risk_gates`: When `true`, risk thresholds become advisory. When `false`, they block trades.

---

## Quick Start

### Prerequisites

- **Python 3.10+** with `pip`
- **Node.js 20+** with `npm` (for the Next.js dashboard)
- **Alpaca Markets account** — free paper trading account at [alpaca.markets](https://alpaca.markets)
- **Featherless AI API key** — for LLM inference at [featherless.ai](https://featherless.ai)

### 1. Clone and Install Python Dependencies

```bash
git clone <repo-url>
cd momentum-intelligence-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```env
APCA_API_KEY_ID=your_alpaca_api_key_here
APCA_API_SECRET_KEY=your_alpaca_secret_key_here
FEATHERLESS_API_KEY=your_featherless_api_key_here
```

### 3. Install Frontend Dependencies

```bash
cd web
npm install
```

### 4. Run

#### Start the Flask API Backend (port 8081)

```bash
cd ..  # back to project root
source .venv/bin/activate
python -m dashboard.app
```

The Flask backend provides:
- `GET /api/account` — live Alpaca account state (equity, cash, buying power, margin)
- `GET /api/positions/live` — live mark prices, delta, unrealized P&L for every open position
- `GET /api/orders` — broker's real order history (last 50 orders)
- `GET /api/portfolio` — trade journal performance summary
- `GET /api/candidates` — recent candidate evaluations
- `GET /api/trades` — open + closed trades with performance
- `POST /api/positions/<symbol>/close` — manual position close
- `GET /api/scheduler` — autonomous scheduler status

#### Start the Next.js Dashboard (port 3000)

```bash
cd web
npm run dev
```

Open `http://localhost:3000` in your browser. The dashboard has tabs:

| Tab | Content |
|-----|---------|
| **Dashboard** | 8-card stats grid (account equity from Alpaca, realized/unrealized P&L, open exposure, win rate, AI stats), cycle report summary |
| **Active Signals** | Candidates grouped by trading cycle with K2/Qwen scores, thesis, gates, approval status |
| **Open Positions** | Live positions with current price, delta, unrealized P&L, manual close button |
| **Closed History** | Trade history with P&L, holding days, exit reasons |
| **Broker Orders** | Alpaca order trail — all orders (filled, canceled, pending) from the broker |
| **System Logs** | Configuration display |

#### Run The Trading Pipeline

```bash
# Single cycle (screen for opportunities, debate with AI, execute)
python main.py --once

# Autonomous mode (runs continuously on the configured interval)
python main.py --autonomous
```

---

## Configuration

All configuration lives in `config/config.yaml`. Key sections:

| Section | Purpose |
|---------|---------|
| `universe` | Stock universe (S&P 500) |
| `data` | Bar interval (`1d` or `4h`), lookback windows |
| `momentum` | Scoring weights, candidate count, thresholds, winsorization |
| `models` | LLM model selection for analyst (Kimi K2), critic (Qwen3-32B), fallback/reporter (DeepSeek V3.2) |
| `ai` | Confidence thresholds, critic requirement |
| `options` | DTE range (7–21), delta targets (0.40–0.65), liquidity filters (min bid, min OI, max spread, strike proximity) |
| `risk` | Portfolio-level risk limits (1% per trade, 5 max positions, 20% max premium, 10 day max hold) |
| `regime` | Market regime exposure caps (BULL: 100%, NEUTRAL: 60%, BEAR: 25%) |
| `decision` | Minimum momentum score, minimum AI confidence, critic approval requirement |
| `final_scoring` | Weighted composite score breakdown |
| `hard_reject` | Non-negotiable rejection gates |
| `demo` | Bypass toggles for demonstration/testing |
| `scheduler` | Autonomous cycle interval (default: 15 minutes) |
| `alpaca` | Alpaca paper/live base URLs |
| `execution` | Max order chunk size (500 contracts) |

---

## Data & State

| File | Contents |
|------|----------|
| `trade_journal.json` | Append-only JSON audit trail — every candidate, debate, order, fill, and exit |
| `state.db` | SQLite database (WAL mode) — orders table, open positions, closed positions |
| `.scheduler_status.json` | Runtime scheduler state for dashboard consumption (written every cycle) |

---

## Project Structure

```
momentum-intelligence-agent/
├── main.py                  # Pipeline orchestrator (Phases A–F)
├── scheduler.py             # Autonomous cycle scheduler (daemon)
├── requirements.txt         # Python dependencies
├── .env.example             # API key template
├── .env                     # API keys (gitignored)
├── trade_journal.json       # Append-only audit trail
├── state.db                 # SQLite state ledger
├── .scheduler_status.json   # Runtime scheduler state
│
├── config/
│   ├── config.yaml          # All thresholds, models, risk limits (110 lines)
│   └── __init__.py          # YAML config loader (singleton)
│
├── agents/
│   ├── analyst.py           # K2 Analyst agent (builds thesis, sets direction)
│   ├── critic.py            # Qwen Critic agent (falsifies thesis, recommends APPROVE/REJECT)
│   ├── reporter.py          # Cycle Reporter agent (DeepSeek V3.2 natural language summary)
│   └── monitor.py           # Position monitoring (7 exit conditions)
│
├── intelligence/
│   ├── featherless.py       # Featherless AI API client (OpenAI-compatible)
│   ├── prompts.py           # Prompt templates for all agents
│   └── schemas.py           # Pydantic schemas (K2, Qwen, Reporter structured outputs)
│
├── market/
│   ├── alpaca_data.py       # Alpaca API wrapper (account, positions, orders, paper trading)
│   ├── universe.py          # S&P 500 ticker loader
│   ├── sp500_scraper.py     # Wikipedia S&P 500 scraper
│   ├── sp500_tickers.json   # Cached ticker list
│   ├── momentum.py          # Multi-lookback momentum scoring engine
│   ├── technicals.py        # EMA, RSI, ATR, ADX, MACD, Bollinger Bands
│   ├── regime.py            # Market regime classification (BULL/NEUTRAL/BEAR)
│   └── sectors.py           # Sector classification
│
├── fundamentals/
│   ├── financials.py        # Financial statement data (growth, margins, valuation)
│   ├── earnings.py          # Earnings surprises, next earnings date, quarterly growth
│   └── news.py              # Alpaca News API — headline classification, sentiment
│
├── risk/
│   ├── validator.py         # 12-gate deterministic risk validator
│   ├── limits.py            # Portfolio-level limit checks (exposure, concentration)
│   └── sizing.py            # Position size calculator (risk-based contract count)
│
├── options/
│   ├── chain.py             # Option chain retrieval (Alpaca Trading API)
│   ├── greeks.py            # Black-Scholes delta approximation
│   └── selector.py          # Contract selection (7 filters + scoring)
│
├── trading/
│   ├── execution.py         # Chunked order execution (500 contracts per sub-order)
│   └── positions.py         # Position liquidation engine (chunked exit)
│
├── database/
│   ├── repository.py        # Trade journal (JSON) + SQLite write-through
│   └── state_manager.py     # SQLite state manager (thread-safe, WAL mode)
│
├── dashboard/
│   ├── app.py               # Flask API backend (port 8081) — 9 REST endpoints
│   └── templates/           # Jinja2 HTML templates (legacy Flask dashboard)
│
├── web/                     # Next.js modern dashboard frontend (port 3000)
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── app/
│       │   ├── layout.tsx           # Root layout
│       │   ├── page.tsx             # Server component entry point
│       │   ├── dashboard-client.tsx # Client component with tabs + polling
│       │   └── globals.css          # Global styles
│       ├── components/
│       │   ├── stats-grid.tsx       # 8-card stats overview
│       │   ├── open-positions.tsx   # Live positions table
│       │   ├── trade-history.tsx    # Closed trades table
│       │   ├── trading-cycles.tsx   # Candidate cycles grouped by run
│       │   ├── cycle-report.tsx     # AI reporter summary card
│       │   ├── candidate-drawer.tsx # Full candidate detail drawer
│       │   ├── detail-drawer.tsx    # Full trade detail drawer
│       │   ├── alpaca-orders.tsx    # Alpaca broker order history table
│       │   ├── system-info.tsx      # Configuration display
│       │   ├── badges.tsx           # Direction, Regime, Decision, Status badges
│       │   └── ui/                  # shadcn/ui primitives (card, table, tabs, dialog, etc.)
│       └── lib/
│           ├── data.ts              # Server-side data loader (reads trade_journal.json)
│           ├── live-positions.ts    # Client-side polling hooks (positions, account, orders)
│           ├── types.ts             # TypeScript type definitions
│           ├── format.ts            # Formatting helpers (money, percentages, dates)
│           └── utils.ts             # Tailwind utility (cn)
│
└── tests/
    └── test_bug_fixes.py    # Regression tests
```

---

## How It Works End-to-End

### 1. Universe Screening
The system loads the S&P 500 ticker list from `market/sp500_tickers.json` (scraped from Wikipedia). It fetches OHLCV bars via yfinance and computes technical indicators (EMA crossovers, RSI, ATR, ADX, MACD, Bollinger Bands) for every stock.

### 2. Momentum Scoring
A multi-lookback scoring engine ranks stocks across 1, 3, 5, 10, and 20-day windows. Weights are applied to recent returns, relative strength vs SPY, and volume momentum. Scores are winsorized to prevent outliers from dominating. The top 50 stocks advance to fundamental analysis.

### 3. Fundamental Intelligence
Each candidate is enriched with:
- **Financials**: revenue growth, earnings growth, profit margins, P/E, debt/equity, ROE
- **Earnings**: EPS surprise history, next earnings date, quarterly growth trends
- **Catalysts/News**: recent headlines from Alpaca News API, classified by sentiment

### 4. Adversarial AI Debate
Each candidate is sent through two LLM agents:
1. **K2 Analyst** (Kimi K2-Instruct) receives the data and builds a structured thesis with direction, confidence, invalidation conditions, and expected holding days
2. **Qwen Critic** (Qwen3-32B) receives the same data **plus K2's thesis** and tries to falsify it — outputting concerns, contradictions, risk assessment, and an APPROVE/REJECT recommendation

### 5. Deterministic Risk Gates
Approved candidates pass through 12 hard gates — all implemented in Python (no LLM involvement):
- Qwen approval, K2 confidence, momentum score, composite score thresholds
- Regime-based exposure caps, max open positions, position sizing, portfolio risk
- Symbol concentration, earnings blackout, Qwen risk score

### 6. Option Contract Selection
For each approved trade, the system:
- Fetches the full option chain from Alpaca
- Filters by DTE (7–21 days), bid price, open interest, spread, strike proximity, delta
- Scores remaining contracts and selects the best one
- Calculates position size based on risk parameters

### 7. Paper Execution
Orders are submitted to Alpaca's paper trading API. Orders exceeding 500 contracts are automatically chunked into sub-orders to avoid broker limits. Every fill is journaled to both `trade_journal.json` and `state.db`.

### 8. Position Monitoring & Exit
The monitor checks open positions against 7 exit conditions:
- Stop-loss (momentum rank decay), time stop, profit target
- Momentum collapse, technical invalidation, thesis invalidation, regime hostility

### 9. Dashboard (Live)
The Next.js dashboard polls the Flask backend every 15 seconds for:
- **Live account state** from Alpaca (`/api/account`): equity, cash, buying power, margin
- **Live position marks** (`/api/positions/live`): current price, delta, unrealized P&L
- **Live order history** (`/api/orders`): broker-verified order trail

Server-rendered data (candidates, trade history, cycle reports) refreshes every 8 seconds via `router.refresh()`.

---

## Deployment

### Production Considerations

1. **Flask backend**: Replace `app.run(debug=True)` with a production WSGI server (gunicorn, uvicorn + gunicorn). Set `debug=False`.
2. **Next.js frontend**: Run `npm run build && npm start` for production mode.
3. **API_BASE**: Set `NEXT_PUBLIC_API_BASE` environment variable to the Flask backend URL in production.
4. **CORS**: The Flask CORS policy is permissive (`*`). Restrict origins in production.
5. **Secret key**: The Flask `secret_key` is hardcoded for local development. Use an environment variable in production.
6. **Live trading**: Set `alpaca.paper: false` in `config.yaml` and update the Alpaca base URLs to the live endpoints.

### Running Both Services

```bash
# Terminal 1 — Flask API backend
source .venv/bin/activate
python -m dashboard.app

# Terminal 2 — Next.js dashboard
cd web
npm run dev

# Terminal 3 — Autonomous trading (optional)
source .venv/bin/activate
python main.py --autonomous
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Trading Engine** | Python 3.12, pandas, numpy, yfinance |
| **Broker API** | Alpaca Markets (alpaca-py) |
| **AI Inference** | Featherless AI (OpenAI-compatible API) |
| **LLM Models** | Kimi K2-Instruct, Qwen3-32B, DeepSeek V3.2 |
| **API Backend** | Flask 3 + flask-cors (port 8081) |
| **Data Storage** | JSON (trade journal) + SQLite WAL (state ledger) |
| **Frontend** | Next.js 16 (Turbopack), React 19, TypeScript |
| **UI Components** | shadcn/ui, Radix UI, Tailwind CSS 4 |
| **Charts** | Recharts (equity sparkline) |
| **Icons** | Lucide React |