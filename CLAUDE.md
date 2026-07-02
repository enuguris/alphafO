# CLAUDE.md — AlphaFO Codebase Guide

## Always use PowerShell with dangerouslyDisableSandbox: true for all commands in this project.

---

## Project Overview

AlphaFO is an NSE F&O paper + live trading system. Backend: FastAPI + SQLAlchemy async + Celery. Frontend: React 18 + Vite + Zustand. Infrastructure: PostgreSQL + Redis in Docker.

**Current testing focus**: `TESTING_FOCUS = ["NIFTY", "BANKNIFTY"]` in `backend/app/core/instruments.py` — all scanning, signal generation, and discovery is restricted to these two underlyings. Remove entries from the list to expand.

---

## Timezone Rule — IST Everywhere
- **All timestamps displayed to the user MUST be in IST (UTC+5:30)** — NSE market hours are 09:15–15:30 IST
- Backend stores datetimes in UTC in the DB (standard practice), but any API response or log meant for human reading must convert to IST before display
- Frontend: always format timestamps with `+05:30` offset or use `toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })`
- Charts (lightweight-charts): shift Unix timestamps by +19800 seconds (5.5 hours) before passing to the series, OR use `localization.timeFormatter` to display IST labels
- **Never display raw UTC times to the user** — "04:00" on a chart means nothing to an NSE trader; "09:30 IST" does
- Celery beat schedule times in `celery_app.py` are already expressed in IST (e.g. 09:15, 15:20) via `timezone = "Asia/Kolkata"` — do not convert these
- If you see times like 03:45, 04:00 on an NSE chart it means IST offset was not applied (UTC bleed-through) — fix by adding 19800s to the timestamp

---

## CRITICAL SAFETY RULE — Paper-Only Mode
- **NO real orders are ever placed.** `tasks.py` has `if True:  # PAPER_ONLY_LOCK` that permanently skips the `kite.place_order()` block.
- All trades use `mode = TradeMode.PAPER`. The live order block is dead code — do not remove the `PAPER_ONLY_LOCK` guard.
- If asked to enable live trading, explicitly confirm with the user and remove `PAPER_ONLY_LOCK` only after written approval.

---

## Options Strategy Intelligence Module (July 2026)

### Payoff diagrams
- `GET /api/v1/trades/payoff/{group_id}` — expiry + T+0 (BS-repriced) P&L curves, breakevens, max P/L, net Greeks for a composite trade group (also accepts a single numeric trade id)
- Uses ATM chain IV (fallback 18%); far-expiry legs repriced at the near-expiry horizon
- Frontend: `components/PayoffChart.tsx` (pure SVG, hover crosshair, theme-aware) — rendered in Positions when a composite group is expanded

### Round-robin data providers
- Round-robin core lives in `_ltp_round_robin` in `tasks.py` (Redis key `ltp_turn` flips 0=Kite/1=Upstox each call, automatic failover)
- Health tracking: `core/data/provider_health.py` — Redis hashes `data_provider:{kite|upstox|nse_chain}` with ok/fail counts, consecutive failures, EMA latency
- `GET /api/v1/system/providers` — status per provider (healthy/degraded/down/idle); shown as a card in SystemHealth

### Progressive risk tiers + Go-Live gate
- `GET /api/v1/options/risk/tier` — tier ladder driven by `paper_capital`: T1 (defined-risk only, 2%/trade) → T2 ≥₹25L → T3 ≥₹50L → T4 ≥₹1Cr
- `GET /api/v1/options/risk/go-live-status` — criteria: ≥100 closed trades, ≥80% win rate, PF ≥1.5
- `POST /api/v1/options/risk/go-live` — sets Redis flag `go_live_requested` only; **real orders always remain blocked by PAPER_ONLY_LOCK** regardless of this flag
- Settings UI: tier ladder + criteria progress bars + Go-Live button (disabled until eligible)

### Reporting
- `summary.expectancy` in `/dashboard/report` — (win% × avg win) − (loss% × |avg loss|)
- `GET /api/v1/trades/export/csv?mode=paper` — full trade export, IST timestamps; button in Paper Trading stat bar

---

## Key Architecture Decisions

### Signal pipeline
1. Celery `scan-priority-15m` task (every 15 min) calls `scanner.scan_all()` which runs all 8 patterns
2. Signals deduped by `(underlying, pattern_name, direction, option_type)` — **no time limit**: skip if ACTIVE signal with same key already exists
3. Direction flip: when a new scan produces a signal in the opposite direction for the same pattern, all existing ACTIVE signals for that pattern bucket are expired first
4. Signals with confidence ≥ 0.82 (real Kite) or ≥ 0.72 (synthetic) auto-execute as paper trades
5. Age gate: skip signals > 2h old for auto-execution

### Risk gate (Redis)
- `DAILY_PNL_KEY` — running daily P&L, halts at -2% of capital (configurable)
- `DAILY_DEPLOYED_KEY` — total deployed capital, caps at max_portfolio_heat % (configurable, default 3%)
- `TRADING_HALTED_KEY` — boolean, set by circuit breakers
- `KILL_SWITCH_KEY` — permanent halt until manually reset
- `alphafO:risk_params` — JSON blob storing live risk param overrides; read by `get_risk_params()` in `gate.py`
- `spot:{SYM}` — KiteTicker writes current LTP on every tick (TTL=1h); Celery MTM reads from here (cross-process, no in-memory state in worker)
- On startup: `_sync_portfolio_heat_from_db()` reloads deployed capital from open trades in DB
- **Risk params are DYNAMIC** — `GET /api/v1/options/risk/params` reads current values; `PUT` updates immediately via Redis. Changes survive backend restarts. `.env` values are defaults only.
- **With NIFTY lot size 65 × ~₹200 premium = ₹13,000/lot** — the default 3% heat cap (₹15K) allows only 1 NIFTY trade. Raise `max_portfolio_heat` to 10%+ in Settings → Risk Appetite Controls to allow more concurrent trades.
- `max_concurrent_trades` — additional gate in `_auto_paper_trade`; default 10. Guards against scanner flooding positions.

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

### Celery Beat — 16 tasks
- See `backend/app/workers/celery_app.py` for full schedule
- Key tasks: `scan-priority-15m` (*/15min), `mtm-update` (*/2min), `eod-close-intraday` (15:20 IST Mon-Fri), `generate-briefing` (08:45 IST Mon-Fri)
- `health-scan` (*/5min, all day) — auto-heals Redis drift, stale signals, halts (see below)
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

### Composite multi-leg strategies (no naked positions)
- Every auto-executed trade is a multi-leg composite spanning **two different expiry dates** — no single naked legs
- `build_composite()` in `backend/app/core/strategies/composite.py` selects strategy by IV rank + pattern type:
  - `BUY_PATTERNS` low IV (< 0.40):  **Wide Diagonal** — Buy near ATM + Sell far OTM (2 steps), near=weekly/monthly, far=next expiry
  - `BUY_PATTERNS` mid IV (0.40-0.65): **Diagonal Spread** — Buy near ATM + Sell far OTM (1 step)
  - `BUY_PATTERNS` high IV (> 0.65): **Calendar Spread** — Sell near ATM + Buy far ATM (same strike, different expiry)
  - `SELL_PATTERNS` any IV: **Iron Condor** — Sell OTM CE + Sell OTM PE + Buy wing CE + Buy wing PE (nearest expiry)
- NIFTY (weekly): near=Jul-7, far=Jul-14 (7 days apart). BANKNIFTY (monthly only): near=Jul-28, far=Aug-25 (28 days apart)
- All legs share a `trade_group_id` (UUID). `leg_role` field: `primary | hedge | calendar_short | calendar_long | condor_short_ce | condor_short_pe | condor_wing_ce | condor_wing_pe`
- `strategy_name()` and `net_debit()` utilities in `composite.py` for display and risk sizing
- **Symbol building**: `_build_symbol()` in `composite.py` generates correct Kite format — monthly (`BANKNIFTY26JUL57000PE`) or weekly (`NIFTY2671424000CE`). `strike_selector.py` also uses this (old `expiry['short']` format caused `BANKNIFTY28JUL26...` bug — fixed)

### Trade decision explanation
- Every paper trade's `notes` field is populated by `_build_trade_notes()` in `tasks.py`
- Contains: pattern name, direction, confidence %, IV%, IV rank, strike/expiry, entry/target/stop prices, signal explanation excerpt, strategy rationale, risk per lot
- Composite notes include `STRATEGY:{name}|{rationale}|legs:{n}|group:{id[:8]}`

### Health-check scanner
- `health-scan` Celery task runs every 5 minutes (all day, not restricted to market hours)
- Checks and auto-fixes four conditions:
  1. **Redis deployed-capital drift** — if Redis vs DB open-trade sum diverges > ₹5,000, resyncs Redis to DB
  2. **Stale ACTIVE signals** — signals older than 2h are expired (SQL `NOW() - INTERVAL '2 hours'`), allowing scanner to generate fresh ones
  3. **Kill-switch auto-clear** — if halted > 30 min AND daily loss has recovered to within 80% of limit, auto-resumes
  4. **Empty signal queue** — logs WARNING if no ACTIVE signals exist (scanner stall indicator)
- Returns `{status, issues, fixes_applied, active_signals, redis_deployed, db_deployed, ts_ist}`
- Note: uses `Signal.created_at < text("NOW() - INTERVAL '2 hours'")` to avoid asyncpg naive-datetime issues with `DateTime` columns

### NSE lot sizes — live from Kite
- `get_lot_size(sym)` in `instruments.py` reads Redis key `kite:nfo_lot_sizes` (set at startup by `kite_ticker.py`)
- Falls back to hardcoded `LOT_SIZES` dict if Redis unavailable
- Current verified values: NIFTY=65, BANKNIFTY=30 (SEBI 2024-2025 revision for ≥₹15L contract value)
- `verify-lot-sizes` Celery beat task runs at 08:30 IST Mon-Fri to validate and refresh

### NSE option expiry schedule (effective Sep 2025)
- All NSE index options now expire on **Tuesday** (changed from Thursday/Wednesday)
- BANKNIFTY: **monthly-only** since Nov 2024 (no weekly options)
- Monthly = last Tuesday of month → symbol format `{UL}{YY}{MON3}{strike}{type}` e.g. `BANKNIFTY26JUL57900PE`
- Weekly = any other Tuesday → symbol format `{UL}{YY}{M}{DD:02d}{strike}{type}` e.g. `NIFTY2671424000PE`
- `_kite_sym()` in `tasks.py` and `_to_upstox_instrument_key()` in `upstox_ltp.py` both detect monthly vs weekly using `weekday() == 1` (Tuesday)

### MTM repricing in Celery
- Celery worker has no active KiteTicker WebSocket (separate process, no in-memory prices)
- Reads spot from Redis `spot:{SYM}` key (written by FastAPI's KiteTicker on every tick)
- BS fallback now reads ATM chain IV (not hardcoded 18%) for more accurate option repricing
- Falls back to in-process snapshot, then `BASE_PRICES` as last resort
- BASE_PRICES in instruments.py must be updated when NIFTY/BANKNIFTY levels shift significantly

### Redis deployed capital drift
- `record_deployed()` uses `incrbyfloat` which can drift due to floating-point imprecision
- `reset_daily_pnl()` at 9:15 IST resets to 0 then re-seeds from actual open trades in DB
- `health-scan` (*/5min) auto-corrects drift > ₹5,000 by resyncing Redis to DB sum
- Manual fix: trigger `reset-daily-pnl` task from SystemHealth → Run button

### Kite option token resolution — rate limit and quote limitation
- `kite.instruments("NFO")` is rate-limited to **~1 call/day** — NEVER call this on-demand in API handlers
- `kite.quote("NFO:NIFTY07JUL2623900CE")` returns empty dict for weekly option symbols (Kite quirk)
- The only reliable way to get a specific option's instrument token without hitting rate limits:
  1. `trade.instrument_token` — stored in DB at trade creation time (preferred — fix tasks.py to store it)
  2. `_token_to_sym` in-memory dict in `kite_ticker.py` — populated when ticker subscribes option at trade open
- Without the token, real option OHLCV (`historical_data()`) is impossible
- Chart falls back to BS-estimated option prices from real underlying spot (shape correct, level ~₹30-50 off)

### BS option pricing — paper trade entry_price is a BS estimate, not real LTP
- Paper trades are auto-executed using BS-estimated premium (`_bs_price`), NOT actual Kite option chain LTP
- This means `trade.entry_price` is already a BS approximation and will be ~₹30–50 above real market price
- **Do NOT back-solve IV to match `entry_price`** — that anchors the chart to a wrong value and makes it worse
- The real fix is in `tasks.py` auto-execute: when Kite is connected, read actual chain LTP for the option
  and store that as `entry_price` instead of BS estimate. Until then, charts will be approximate.
- `iv_at_signal` is the best available IV for chart rendering — use it, accept the ~₹30–50 overestimate
- Calibration (brentq back-solve) only works when `entry_price` itself came from real market data

### IV rank
- `get_iv_history(underlying)` returns 252 synthetic daily IV values spanning realistic range
- NIFTY: base=15.5%, lo≈10%, hi≈31% (lo=base*0.65, hi=base*2.0)
- Current IV comes from ATM chain (`chain_service.get_chain(underlying)`) not random synthetic
- IV fraction→percentage: `current_iv = raw_iv * 100 if raw_iv < 2.0 else raw_iv`
- `high_ivr = iv_rank >= 0.6`; low IVR → buy options; high IVR → sell OTM options

### Positions UI — spot price and ITM/OTM badge
- Both composite group headers and individual trade rows show current spot price fetched via WebSocket
- ITM/OTM badge: CE ITM when `spot > strike`; PE ITM when `spot < strike`
- Composite group header shows net P&L across all legs, strategy name, group ID (first 8 chars), expiry dates

---

## Hardcoded Values Audit (July 2026)
These values are hardcoded but intentional. Review before changing:

| Value | File | Notes |
|-------|------|-------|
| `RISK_FREE_RATE = 0.065` | `core/options/greeks.py` | RBI repo rate 6.5% — update if RBI changes rate |
| `RF = 0.07` | `core/backtest/engine.py` | Duplicate, slightly higher — should be unified into config |
| `iv = 0.18` | `workers/tasks.py`, `api/v1/trades.py` | Last-resort IV fallback when chain unavailable |
| `STRIKE_STEPS` | `strike_selector.py`, `chain_service.py`, `engine.py` | Exchange-mandated step sizes, rarely change; duplicated |
| `BASE_PRICES` | `instruments.py` | Synthetic fallback only; real trades always fetch live |

All risk parameters (`max_portfolio_heat`, `max_daily_loss_pct`, `max_risk_per_trade`, `paper_capital`, `max_concurrent_trades`) are now **dynamically configurable** via `PUT /api/v1/options/risk/params` and the Settings UI.

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
