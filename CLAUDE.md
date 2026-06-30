# CLAUDE.md — AlphaFO Codebase Guide

## Always use PowerShell with dangerouslyDisableSandbox: true for all commands in this project.

---

## Project Overview

AlphaFO is an NSE F&O paper + live trading system. Backend: FastAPI + SQLAlchemy async + Celery. Frontend: React 18 + Vite + Zustand. Infrastructure: PostgreSQL + Redis in Docker.

**Current testing focus**: `TESTING_FOCUS = ["NIFTY", "BANKNIFTY"]` in `backend/app/core/instruments.py` — all scanning, signal generation, and discovery is restricted to these two underlyings. Remove entries from the list to expand.

---

## Key Architecture Decisions

### Signal pipeline
1. Celery `scan_signals` task (every 5 min) calls `scanner.scan_all()` which runs all 8 patterns
2. Signals deduped by `(underlying, pattern_name, direction, option_type)` within 1 hour window in DB
3. Signals with confidence ≥ 0.82 (real Kite) or ≥ 0.72 (synthetic) auto-execute as paper trades
4. `is_synthetic` detection: `signal.explanation.startswith("[")` — real signals always start with `[Weekly/Monthly expiry ...]`
5. Age gate: skip signals > 2h old for auto-execution

### Risk gate (Redis)
- `DAILY_PNL_KEY` — running daily P&L, halts at -2% of capital
- `DAILY_DEPLOYED_KEY` — total deployed capital, caps at 3% portfolio heat
- `TRADING_HALTED_KEY` — boolean, set by circuit breakers
- `KILL_SWITCH_KEY` — permanent halt until manually reset
- On startup: `_sync_portfolio_heat_from_db()` reloads deployed capital from open trades in DB

### Trade lifecycle
- Status enum (Python + DB): `OPEN → CLOSED | CANCELLED | PENDING | EXPIRED`
- Mode enum (Python): `TradeMode.PAPER | TradeMode.LIVE` (uppercase in DB)
- Portfolio mode stored as lowercase varchar: `'paper'`, `'live'` (NOT the TradeMode enum)
- Trailing stop: at +30% gain, `stop_loss` raised to `entry_price + (current - entry_price) * 0.50`

### Theme system
- 5 themes: `dark`, `midnight`, `high-contrast`, `solarized`, `light`
- Stored in localStorage key `alphafO-theme` as Zustand persisted state
- Applied via `document.documentElement.setAttribute('data-theme', theme)`
- CSS vars in `frontend/src/index.css` under `[data-theme="..."]` selectors

### Celery Beat — 14 tasks
- See `backend/app/workers/celery_app.py` for full schedule
- Key tasks: `scan-signals` (*/5min), `mtm-update` (*/2min), `eod-close-intraday` (15:20 IST Mon-Fri)
- Manual trigger via `POST /api/v1/system/run-task/{task_name}`

---

## Common Pitfalls

### PostgreSQL enum changes
- `ALTER TYPE <enum> ADD VALUE IF NOT EXISTS 'VALUE'` must run in **separate transactions**
- Never add multiple values in one `ALTER TYPE` statement

### Signal serialization
- Signals can have `nan`/`inf` float fields (IV, greeks) — always use `_safe_dict()` in `signals.py`
- `ValueError: Out of range float values are not JSON compliant` = forgot to sanitize

### Portfolio mode query
- Portfolio table stores mode as lowercase `'paper'` / `'live'` varchar
- Use `WHERE mode='paper'` NOT `WHERE mode='PAPER'`

### PCR / Market data
- PCR cache files live at `backend/app/market_data/bhav/pcr_NIFTY.csv` etc.
- Bootstrap from existing bhav files: call `build_pcr_from_cached_bhav("NIFTY")`
- FII cache (`fii_fo.csv`) populates via background NSE download — may take time

### Black-Scholes pricing
- `_bs_price(S, K, T, r, sigma, option_type)` in `scanner.py` / pattern files
- Returns synthetic option premium when Kite not connected
- T in years: `dte / 365.0`

---

## End-to-End Test Checklist

Run these after any change before committing:

```
1. GET /api/v1/system/health        → all 6 components green (db, redis, kite, ticker, celery, market_data)
2. GET /api/v1/signals/             → returns only NIFTY/BANKNIFTY signals, no nan/inf in response
3. GET /api/v1/portfolio/?mode=paper → capital > 0, deployed >= 0
4. GET /api/v1/dashboard/report     → summary has sharpe_ratio, max_drawdown_pct fields
5. GET /api/v1/dashboard/pre-market → pcr_nifty and pcr_banknifty not null
6. POST /api/v1/system/run-task/scan_signals → {"queued": true}
7. Frontend: all 10 nav tabs render without error (check browser console)
8. Frontend: theme cycle works — click theme button, all 5 themes render correctly
```

---

## Directory Reference

```
backend/app/
├── api/v1/
│   ├── signals.py         # _safe_dict(), TESTING_FOCUS filter
│   ├── trades.py          # auto paper-trade, MTM, close
│   ├── portfolio.py       # capital tracking
│   ├── backtest.py        # walk-forward engine API
│   ├── options.py         # chain, IV rank, max pain
│   ├── dashboard.py       # pre-market, report (Sharpe, drawdown)
│   ├── pattern_finder.py  # discover, backtest, toggle
│   ├── settings.py        # Kite creds, Anthropic key
│   ├── system.py          # health, schedule, manual task trigger
│   └── chat.py            # Claude API integration
├── core/
│   ├── patterns/          # 8 pattern modules (gap_fill, pcr_divergence, …)
│   ├── scanner.py         # orchestrates all patterns, IV rank gate
│   ├── instruments.py     # TESTING_FOCUS list, full F&O universe
│   ├── backtest/          # walk-forward engine + market_data (bhav replayer, PCR)
│   ├── options/           # chain_service, expiry, regime, strike_selector, event_calendar
│   └── risk/gate.py       # Redis circuit breaker helpers
├── models/
│   ├── trades.py          # Trade, TradeStatus, TradeMode enums
│   ├── portfolio.py       # Portfolio model
│   ├── kite_config.py     # KiteConfig
│   └── discovered_pattern.py  # DiscoveredPattern, PatternBacktestRun
├── workers/
│   ├── celery_app.py      # Beat schedule (14 tasks)
│   └── tasks.py           # All task implementations
└── main.py                # FastAPI app, lifespan, WS hub, _sync_portfolio_heat_from_db

frontend/src/
├── pages/
│   ├── Dashboard.tsx      # pre-market, signals, scanner
│   ├── Options.tsx        # chain, IV rank, regime
│   ├── Positions.tsx      # open paper trades with MTM
│   ├── PatternFinder.tsx  # backtest UI + discovery
│   ├── Report.tsx         # Sharpe, drawdown, equity curve
│   ├── PaperTrading.tsx   # trade history + P&L chart
│   ├── Backtest.tsx       # per-pattern backtest UI
│   ├── Settings.tsx       # Kite, mode, theme picker (5 themes)
│   ├── SystemHealth.tsx   # health grid, Celery schedule, manual triggers
│   └── Architecture.tsx   # interactive drill-down architecture diagram
├── store/
│   ├── themeStore.ts      # 5 themes: dark|midnight|high-contrast|solarized|light
│   └── modeStore.ts       # paper|live|testing mode
├── api/client.ts          # all API calls (axios)
└── index.css              # CSS vars for all 5 themes, .tv-btn base fix
```

---

## Git Workflow

Always commit after changes with a descriptive message. Push after any significant feature or bugfix:

```bash
git add -A
git commit -m "feat: description"
git push origin main
```
