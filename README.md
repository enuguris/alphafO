# ⚡ AlphaFO — NSE F&O Pattern Signal Engine

A production-ready system for recognising patterns in NSE Futures & Options data, generating entry/exit signals, backtesting strategies, and paper/live trading — with **capital protection as the top priority**.

## Key Features

- **8 proven F&O patterns** — each with quantitative confidence scoring and IV-rank gating
- **3–4% profit targets** per trade with **≤1% capital at risk** per position
- **Walk-forward backtesting** — bhav CSV replayer, Sharpe ratio, max drawdown, win rate
- **Statistical pattern discovery** — Mann-Whitney U test mines the bhav history for edges
- **Paper trading mode** — fully simulated with Black-Scholes pricing when Kite disconnected
- **Live trading (gated)** — only unlocked after 60 paper trades + 55% win rate + ≤10% drawdown
- **Circuit breakers** — daily/weekly loss limits auto-halt all trading (Redis-backed)
- **Trailing stop** — locks in 50% of profit when trade is up ≥30%
- **5 UI themes** — Dark, Midnight, High Contrast, Solarized, Light (persisted across sessions)
- **14 Celery scheduled jobs** — market data sync, signal scanning, EOD close, nightly backtests
- **Interactive architecture diagram** — drill-down from system overview to individual components

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                     BROWSER (React 18 + Vite)                      │
│  Dashboard · Options · Positions · Pattern Finder · Report         │
│  Paper Trading · Backtest · Settings · System Health · Architecture│
└──────────────────────┬─────────────────────────────────────────────┘
          REST API + WebSocket (ws://)
┌──────────────────────▼─────────────────────────────────────────────┐
│                  BACKEND  (FastAPI + Python 3.12)                   │
│                                                                    │
│  /api/v1/signals      /api/v1/trades       /api/v1/portfolio       │
│  /api/v1/backtest     /api/v1/options      /api/v1/dashboard       │
│  /api/v1/pattern-finder  /api/v1/settings  /api/v1/system          │
│  /api/v1/chat         /ws/signals          /ws/prices              │
│                                                                    │
│  ┌──────────────────┐   ┌──────────────┐   ┌───────────────────┐  │
│  │  Pattern Engine  │   │  Risk Gate   │   │  Options Engine   │  │
│  │  8 patterns      │   │  (Redis)     │   │  Black-Scholes    │  │
│  │  IV rank gate    │   │  daily P&L   │   │  IV rank, chain   │  │
│  │  Composite score │   │  heat limit  │   │  max pain         │  │
│  └──────────────────┘   └──────────────┘   └───────────────────┘  │
└──────┬───────────────────────┬─────────────────────┬──────────────┘
       │                       │                     │
┌──────▼──────┐   ┌────────────▼─────────┐  ┌───────▼──────────────┐
│ PostgreSQL   │   │       Redis           │  │  Celery + Beat        │
│ 7 tables     │   │  daily_pnl           │  │  14 scheduled tasks   │
│ Alembic ORM  │   │  daily_deployed      │  │  scan every 5 min     │
│              │   │  trading_halted      │  │  MTM every 2 min      │
│              │   │  kill_switch         │  │  EOD close 15:20 IST  │
└─────────────-┘   └──────────────────────┘  └───────────────────────┘
                                                        ↕
                                              ┌────────────────────┐
                                              │  Kite Connect      │
                                              │  Live prices WS    │
                                              │  Order API         │
                                              └────────────────────┘
```

For an interactive, animated version — open the **Architecture** tab in the app.

---

## Patterns

| Pattern | When It Works | Confidence Gate |
|---------|--------------|-----------------|
| **Gap Fill** | Pre-market gap ≥0.5% with OI > 20L | ≥72% (synthetic), ≥82% (real Kite) |
| **PCR Divergence** | PCR < 0.7 or > 1.3 signals institutional positioning | same |
| **Mean Reversion** | Bollinger Band squeeze break on 15m + 1h alignment | same |
| **OI Buildup** | OI increasing with price confirmation | same |
| **VWAP + OI** | Price rejects VWAP on high OI | same |
| **IV Crush** | Sell options before events when IV rank > 75% | same |
| **Max Pain Gravity** | Expiry week: price gravitates to max-pain strike | same |
| **Expiry Week Theta** | Theta decay harvest in final 2 days of weekly expiry | same |

---

## Celery Scheduled Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `scan_signals` | Every 5 min | Run all 8 patterns, insert signals, auto paper-trade ≥82% conf |
| `mtm_update` | Every 2 min | Mark-to-market all open trades + trailing stop logic |
| `settle_expired` | Every 10 min | Close trades whose options expired |
| `cleanup_stale_signals` | Every 15 min | Expire signals past valid_until |
| `generate_briefing` | 08:45 IST | AI pre-market briefing: PCR, FII, IV rank, expiry context |
| `reset_daily_pnl` | 09:15 IST daily | Clear Redis daily P&L + resync from DB |
| `eod_close_intraday` | 15:20 IST Mon–Fri | Force-close all intraday trades |
| `sync_market_data` | 16:15 IST Mon–Fri | Download NSE bhavcopy, bootstrap PCR cache |
| `run_nightly_backtests` | 16:00 daily | Walk-forward backtest all discovered patterns |
| `run_nightly_discovery` | 02:00 daily | Statistical pattern miner (Mann-Whitney U) |
| `reset_weekly_pnl` | Monday 09:15 | Clear weekly P&L tracking |

---

## Risk Rules (Non-Negotiable)

1. Max **1% capital** risk per trade (position sized by stop distance)
2. Max **3% portfolio heat** across all open trades simultaneously
3. **2% daily loss limit** — Redis circuit breaker halts all trading
4. **3% weekly loss limit** — Redis circuit breaker halts all trading
5. Live trading: human confirmation or explicit auto-trade opt-in
6. Stop-loss placed **immediately** after entry on live trades
7. **Trailing stop** activates at +30% gain, locks in 50% of profit

---

## Live-Trading Gate (Paper → Live)

Paper trading must achieve **all three** before live mode unlocks:
- ≥ 60 closed trades
- ≥ 55% win rate
- ≤ 10% maximum drawdown

---

## Quick Start

### Prerequisites
- Docker + Docker Compose

### 1. Clone and start
```bash
git clone <repo-url>
cd alphafO
docker compose up -d
```

This starts:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### 2. Add Kite Connect (Optional — live prices)
1. Create an app at https://kite.trade/
2. Add API key + secret in **Settings → Kite Connect**
3. Click the login URL shown to get a daily access token
4. Paste the `request_token` from the redirect URL → click **Save Request Token**

Without Kite Connect, the app uses Black-Scholes synthetic prices.

### 3. Set Anthropic key (Optional — AI Chat)
1. Get a key at https://console.anthropic.com/
2. Add it in **Settings → AI Chat**

---

## Project Structure

```
alphafO/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routers (signals, trades, portfolio, …)
│   │   ├── core/
│   │   │   ├── patterns/    # 8 pattern modules + base class + scanner
│   │   │   ├── backtest/    # Walk-forward engine + bhav CSV replayer
│   │   │   ├── options/     # Chain, IV rank, expiry, regime, strike selector
│   │   │   └── risk/        # Redis-backed gate (daily P&L, heat, kill switch)
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── workers/         # Celery tasks + beat schedule
│   │   └── main.py          # FastAPI app + lifespan + WebSocket hub
│   ├── alembic/             # DB migrations
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/           # React pages (Dashboard, Options, …, Architecture)
│       ├── components/      # ChatPanel, shared UI
│       ├── store/           # Zustand (mode, theme)
│       └── api/client.ts    # All API calls (axios)
├── docker-compose.yml
└── README.md
```

---

## Adding a New Pattern

1. Create `backend/app/core/patterns/my_pattern.py`
2. Subclass `AbstractPattern`
3. Implement `detect()` and `why_it_works()`
4. The scanner auto-discovers it

```python
from app.core.patterns.base import AbstractPattern, PatternSignal

class MyPattern(AbstractPattern):
    name = "my_pattern"
    version = "1.0"

    def detect(self, ohlcv, options_chain=None, underlying=""):
        # Your detection logic
        return [PatternSignal(...)]

    def why_it_works(self):
        return "The market mechanism behind this pattern..."
```

---

## Cloud Deployment

The Docker Compose configuration works unchanged on:
- **DigitalOcean** ($12–25/mo with managed DB)
- **AWS Lightsail** ($10–20/mo)
- **Railway.app** (push-to-deploy, $5–20/mo)

Set environment variables in the cloud dashboard — no code changes needed.

---

## Testing

```bash
# Run all API smoke tests (from backend container)
docker compose exec backend python -m pytest tests/ -v

# Manual end-to-end checks
# 1. GET /api/v1/system/health       → all components green
# 2. GET /api/v1/signals/            → active NIFTY/BANKNIFTY signals
# 3. GET /api/v1/portfolio/          → capital ≥ 0, deployed ≥ 0
# 4. GET /api/v1/dashboard/report    → Sharpe, drawdown populated
# 5. POST /api/v1/system/run-task/scan_signals → signals generated
```
