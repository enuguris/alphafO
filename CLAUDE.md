# CLAUDE.md — AlphaFO Codebase Guide

## Always use PowerShell with dangerouslyDisableSandbox: true for all commands in this project.

---

## Project Overview

AlphaFO is an NSE F&O paper + live trading system. Backend: FastAPI + SQLAlchemy async + Celery. Frontend: React 18 + Vite + Zustand. Infrastructure: PostgreSQL + Redis in Docker.

**Current testing focus**: `TESTING_FOCUS = ["NIFTY", "BANKNIFTY"]` in `backend/app/core/instruments.py` — all scanning, signal generation, and discovery is restricted to these two underlyings. Remove entries from the list to expand.

---

## Key Architecture Decisions

### Signal pipeline
1. Celery `scan-priority-15m` task (every 15 min) calls `scanner.scan_all()` which runs all 8 patterns
2. Signals deduped by `(underlying, pattern_name, direction, option_type)` — **no time limit**: skip if ACTIVE signal with same key already exists
3. Direction flip: when a new scan produces a signal in the opposite direction for the same pattern, all existing ACTIVE signals for that pattern bucket are expired first
4. Signals with confidence ≥ 0.82 (real Kite) or ≥ 0.72 (synthetic) auto-execute as paper trades
5. Age gate: skip signals > 2h old for auto-execution

### Risk gate (Redis)
- `DAILY_PNL_KEY` — running daily P&L, halts at -2% of capital
- `DAILY_DEPLOYED_KEY` — total deployed capital, caps at 3% portfolio heat (= ₹15,000 on ₹5L capital)
- `TRADING_HALTED_KEY` — boolean, set by circuit breakers
- `KILL_SWITCH_KEY` — permanent halt until manually reset
- `spot:{SYM}` — KiteTicker writes current LTP on every tick (TTL=1h); Celery MTM reads from here (cross-process, no in-memory state in worker)
- On startup: `_sync_portfolio_heat_from_db()` reloads deployed capital from open trades in DB
- **Risk params in `.env` are PERCENTAGES** (3.0 = 3%), not fractions. `gate.py` divides by 100. Wrong values cause cap of ₹150 instead of ₹15,000.

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

### Celery Beat — 15 tasks
- See `backend/app/workers/celery_app.py` for full schedule
- Key tasks: `scan-priority-15m` (*/15min), `mtm-update` (*/2min), `eod-close-intraday` (15:20 IST Mon-Fri), `generate-briefing` (08:45 IST Mon-Fri)
- Manual trigger via `POST /api/v1/system/run-task/{task_name}` — use beat schedule name (with hyphens, not underscores)
- `task_last_run:<label>` Redis key written after each task succeeds — shown in /system/schedule
- scan-all-1h, scan-eod, scan-premarket each write their **own** label key (not shared), passed via `task_label` kwarg in beat schedule

### Pattern classification
- `BUY_PATTERNS = {"gap_fill", "oi_buildup", "vwap_oi", "pcr_divergence", "mean_reversion", "max_pain"}` — directional patterns, buy ATM in signal direction
- `SELL_PATTERNS = {"iv_crush", "expiry_week"}` — direction-neutral premium sellers, sell OTM to collect theta
- `mean_reversion` / `max_pain`: directional (buy CE for long, buy PE for short) — do NOT put in SELL_PATTERNS or signal contradicts itself
- `expiry_week` generates `direction="short"` (strangle sell) — correctly in SELL_PATTERNS
- `_EXPIRY_SAFE = {"max_pain", "expiry_week"}` — these patterns are whitelisted from the event-risk block

### Trade action determination
- Auto-execution reads `sig.option_strategy` ("buy"/"sell") stored in the signals table — NOT `sig.direction`
- `direction="long"` + BUY_PATTERN → BUY CE; `direction="short"` + BUY_PATTERN → BUY PE
- `direction=any` + SELL_PATTERN → SELL (premium collection, direction-neutral)
- Old signals with wrong `option_strategy` self-correct on the next scan (dedup expires+recreates)

### Option pricing in signals
- `estimated_premium` = actual Black-Scholes price using `_bs_price()` (not delta*spot*0.02 approximation)
- Uses REAL expiry DTE from `selector.select()` (floored at 1 day) — not hardcoded dte=7
- Minimum premium filter: signals with `estimated_premium < ₹50` skip auto-execution (illiquid)

### Regime detection — real OHLCV
- `build_ohlcv_from_bhav(underlying)` reads 253 cached bhav files → real FUTIDX closing prices
- `_synthetic_ohlcv()` in options.py prefers bhav data, falls back to date-seeded random walk
- IV column in bhav-based OHLCV: uses India VIX history (`fetch_india_vix()`) merged by date via `pd.merge_asof`; falls back to flat 18% if VIX cache unavailable
- BANKNIFTY uses same VIX values as NIFTY (VIX only covers NIFTY index; close enough for regime detection)

### MTM repricing in Celery
- Celery worker has no active KiteTicker WebSocket (separate process, no in-memory prices)
- Reads spot from Redis `spot:{SYM}` key (written by FastAPI's KiteTicker on every tick)
- BS fallback now reads ATM chain IV (not hardcoded 18%) for more accurate option repricing
- Falls back to in-process snapshot, then `BASE_PRICES` as last resort
- BASE_PRICES in instruments.py must be updated when NIFTY/BANKNIFTY levels shift significantly

### Redis deployed capital drift
- `record_deployed()` uses `incrbyfloat` which can drift due to floating-point imprecision
- `reset_daily_pnl()` at 9:15 IST resets to 0 then re-seeds from actual open trades in DB
- Manual fix: trigger `reset-daily-pnl` task from SystemHealth → Run button

### IV rank
- `get_iv_history(underlying)` returns 252 synthetic daily IV values spanning realistic range
- NIFTY: base=15.5%, lo≈10%, hi≈31% (lo=base*0.65, hi=base*2.0)
- Current IV comes from ATM chain (`chain_service.get_chain(underlying)`) not random synthetic
- IV fraction→percentage: `current_iv = raw_iv * 100 if raw_iv < 2.0 else raw_iv`
- `high_ivr = iv_rank >= 0.6`; low IVR → buy options; high IVR → sell OTM options

### Hedge leg (credit spread)
- SELL trades get an OTM BUY hedge to cap max loss
- Guard: `hedge_prem < premium * 0.85` — if hedge costs ≥85% of main, skip hedge (avoid debit spread)
- `_hedge_premium()` tries live chain LTP first, then BS with ATM chain IV (not fixed sigma=0.18)
- Trades 53+54 opened before this fix may show debit spread P&L (closed, can't retrofix)

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
3. GET /api/v1/portfolio/?mode=paper → capital > 0, win_rate computed from winning_trades/total_trades
4. GET /api/v1/dashboard/report     → summary has sharpe_ratio, max_drawdown_pct fields
5. GET /api/v1/dashboard/pre-market → pcr.NIFTY.pcr and pcr.BANKNIFTY.pcr not null; fii.net_cr present
6. POST /api/v1/system/run-task/scan-priority-15m → {"queued": true}   ← use hyphens!
7. Frontend: all 10 nav tabs render without error (check browser console)
8. Frontend: theme cycle works — click theme button, all 5 themes render correctly
9. GET /api/v1/system/schedule → scan-all-1h/eod/premarket show SEPARATE last_run timestamps
10. GET /api/v1/options/iv-rank/NIFTY → iv_rank between 0.1–0.9 (not stuck at 0 or 1)
11. GET /api/v1/options/risk/status → capital_deployed should be ≥ 0 (not negative from float drift)
12. After scan + 30s → GET /api/v1/trades/?mode=paper show new trades; check option_strategy matches action
13. GET /api/v1/options/regime/NIFTY → uses real bhav data (trend based on 253 days of actual prices)
14. Signals: max_pain/mean_reversion direction=short → option_type=PE, option_strategy=buy (not sell)
15. Settings page: Risk Controls section shows halt/resume buttons; POST /api/v1/options/risk/halt+resume work
```

### FII data gotchas
- `fii_fo.csv` cache path inside container: `/app/market_data/fii_fo.csv`
- NSE CSV has a title row before column headers — `_parse_fii_csv` skips the first line
- `fii_data["date"]` must use `latest.get("date")` not `latest.name` (pandas index)

### Sharpe ratio caveat
- Requires ≥ 10 trading days of closed trades (exits with `exit_time` set) to compute
- Capped at ±10 to prevent extreme values from tiny samples
- A very negative Sharpe with < 5 days simply means both trading days were losses — statistically meaningless

### asyncio in FastAPI async handlers
- Always use `asyncio.get_running_loop()` not deprecated `asyncio.get_event_loop()` (Python 3.10+)
- `get_event_loop()` raises DeprecationWarning inside FastAPI async context and may return wrong loop

### Backtest max_drawdown_pct
- Equity curve starts at `[0.0]`. Skip drawdown when `peak <= 0` to avoid division by near-zero
- Values in DB table `pattern_backtests` capped at 100.0 (were overflowing to 296 quadrillion before fix)
- DB table name is `pattern_backtests` not `pattern_backtest_runs`

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
│   ├── celery_app.py      # Beat schedule (15 tasks), task_label kwarg for unique last_run keys
│   └── tasks.py           # All task implementations, _hedge_premium (chain LTP first, then BS)
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
