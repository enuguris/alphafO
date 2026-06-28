# ⚡ AlphaFO — NSE F&O Pattern Signal Engine

A production-ready system for recognizing patterns in NSE Futures & Options data, generating entry/exit signals, backtesting strategies, and paper/live trading — with **capital protection as the top priority**.

## Key Features
- **8 proven F&O patterns** with clear explanations of *why* each works
- **3–4% profit targets** per trade with **≤1% capital at risk**
- **Backtesting engine** with Sharpe, drawdown, win rate metrics
- **Paper trading mode** — fully simulated with real market data
- **Live trading (gated)** — only unlocked after 60 paper trades + 55% win rate
- **Circuit breakers** — daily/weekly loss limits halt all trading automatically
- **Scalable plugin architecture** — drop a new `.py` file to add a pattern

---

## Workflow

```
Market Data (NSE Bhavcopy / Kite Connect)
         │
         ▼
Pattern Recognition Engine
 ├── PCR Divergence
 ├── OI Buildup Breakout
 ├── Max Pain Gravity
 ├── IV Crush
 ├── VWAP + OI Momentum
 ├── Mean Reversion (BB Squeeze)
 ├── Gap Fill
 └── Expiry Week Theta
         │
         ▼
Signal Generator (confidence filter, R:R check)
         │
         ▼
Risk Manager (position sizing, portfolio heat, guardrails)
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Paper Trade  Backtest
    │
    ▼ (after 60 trades + 55% win rate)
Live Trade (Kite Connect)
```

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│              FRONTEND (React)            │
│  Dashboard | Backtest | Paper | Settings │
└──────────────┬──────────────────────────┘
               │ REST API + WebSocket
┌──────────────▼──────────────────────────┐
│           BACKEND (FastAPI)              │
│  /api/v1/signals  /api/v1/trades         │
│  /api/v1/backtest /api/v1/portfolio      │
│  /ws/signals      /ws/portfolio          │
└──┬───────────┬────────────┬─────────────┘
   │           │            │
   ▼           ▼            ▼
PostgreSQL   Redis      Celery Workers
(trades,    (cache,     (data sync,
 signals,    pub/sub)    signal runs,
 backtests)              backtests)
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Git

### 1. Clone and Configure
```bash
git clone https://github.com/YOUR_USERNAME/alphafO.git
cd alphafO
make setup      # creates .env from template
# Edit .env if needed (defaults work for local testing)
```

### 2. Start Everything
```bash
make dev
```
This starts:
- **Backend API**: http://localhost:8000
- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### 3. Load Historical Data
Without Kite Connect, load NSE Bhavcopy CSVs:
```bash
# Download NSE F&O historical data
# Place CSVs in: data/nse/NIFTY.csv, data/nse/BANKNIFTY.csv
# Format: timestamp,open,high,low,close,volume,oi,iv
```

### 4. Add Kite Connect (Optional)
1. Create an app at https://kite.trade/
2. Add credentials via Settings page or `.env`
3. Visit the login URL shown after saving credentials
4. Enter access token in Settings

---

## Trading Modes

| Mode | Description |
|------|-------------|
| **Testing** | Signal detection + backtesting only. No orders. |
| **Paper** | Simulated trades with virtual ₹5,00,000 capital. |
| **Live** | Real orders via Kite Connect. Gated by paper trading performance. |

### Promotion to Live
Paper trading must achieve:
- ≥ 60 closed trades
- ≥ 55% win rate
- ≤ 10% maximum drawdown

---

## Risk Rules (Non-Negotiable)
1. Max **1% capital** risk per trade
2. Max **3% portfolio heat** simultaneously
3. **2% daily loss limit** — all trading stops
4. **3% weekly loss limit** — all trading stops
5. Live trading: human confirmation or explicit auto-trade opt-in
6. Stop-loss order placed **immediately** after entry on live trades

---

## Adding a New Pattern
1. Create `backend/app/core/patterns/my_pattern.py`
2. Subclass `AbstractPattern`
3. Implement `detect()` and `why_it_works()`
4. That's it — the registry auto-discovers it

```python
from app.core.patterns.base import AbstractPattern, PatternSignal

class MyPattern(AbstractPattern):
    name = "my_pattern"
    version = "1.0"

    def detect(self, ohlcv, options_chain=None, underlying=""):
        # Your logic here
        return [PatternSignal(...)]

    def why_it_works(self):
        return "Explanation of the market mechanism..."
```

---

## Cloud Deployment
The same Docker Compose configuration works on:
- **DigitalOcean** ($12–25/mo with managed DB)
- **AWS Lightsail** ($10–20/mo)
- **Railway.app** (push to deploy, $5–20/mo)

Just set environment variables in the cloud dashboard — no code changes needed.

---

## Project Structure
See `PROJECT_PLAN.md` for full directory tree and architecture decisions.

---

## Kite Connect Setup
1. Go to https://kite.trade/ → Login with Zerodha
2. Developer → Create App → "Connect"
3. Note API Key and Secret
4. Enter in AlphaFO Settings page
5. Click the login URL to get daily access token

