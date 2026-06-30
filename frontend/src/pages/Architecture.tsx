import { useState } from 'react'

type NodeId =
  | 'frontend' | 'backend' | 'kite' | 'anthropic'
  | 'patterns' | 'risk' | 'options'
  | 'postgres' | 'redis' | 'celery'
  | 'nse' | 'yahoo'

interface NodeMeta {
  x: number; y: number; w: number; h: number
  label: string; sub: string; color: string; ext?: boolean
}

// ── Node layout ───────────────────────────────────────────────────────────────
// Backend is taller (spans Application tier) to reflect its hub role.
// Kite + Anthropic stack on the right as two external APIs.
const N: Record<NodeId, NodeMeta> = {
  frontend:  { x:130, y:22,  w:400, h:52,   label:'React Frontend',    sub:'10 pages · Zustand · WebSocket hub',                          color:'#5b9bff' },
  backend:   { x:28,  y:106, w:278, h:102,  label:'FastAPI Backend',   sub:'Python 3.12 · async · 10 API routes · WS broadcast hub',      color:'#26c6a0' },
  kite:      { x:368, y:106, w:264, h:46,   label:'Kite Connect',      sub:'Zerodha broker · live prices · OAuth daily',                  color:'#ffab40', ext:true },
  anthropic: { x:368, y:164, w:264, h:44,   label:'Anthropic Claude',  sub:'Claude Sonnet 4.6 · AI chat · pre-market briefing',           color:'#c084fc', ext:true },
  patterns:  { x:28,  y:232, w:164, h:76,   label:'Pattern Engine',    sub:'8 patterns · IV gate · composite confidence',                 color:'#9c71ff' },
  risk:      { x:220, y:232, w:152, h:76,   label:'Risk Gate',         sub:'4 circuit breakers · trailing stop',                          color:'#ff5252' },
  options:   { x:408, y:232, w:224, h:76,   label:'Options Engine',    sub:'chain · IV rank · max pain · regime',                         color:'#4fc3f7' },
  postgres:  { x:28,  y:340, w:164, h:74,   label:'PostgreSQL',        sub:'7 tables · Alembic migrations',                               color:'#b39ddb' },
  redis:     { x:220, y:340, w:152, h:74,   label:'Redis',             sub:'4 circuit-breaker keys · Celery broker',                      color:'#ff7043' },
  celery:    { x:408, y:340, w:224, h:74,   label:'Celery Workers',    sub:'14 scheduled tasks · Beat scheduler',                         color:'#26c6da' },
  nse:       { x:28,  y:450, w:256, h:56,   label:'NSE Market Data',   sub:'bhavcopy CSVs · PCR cache · FII OI · bhav replayer',          color:'#90a4ae' },
  yahoo:     { x:308, y:450, w:324, h:56,   label:'Yahoo Finance',     sub:'India VIX (^INDIAVIX) · OHLCV fallback when Kite offline',    color:'#81d4fa', ext:true },
}

// ── Connection definitions ────────────────────────────────────────────────────
// dur = seconds per dash cycle (lower = faster flow)
// w = stroke width, dash/gap = dash pattern
// fwd = true means forward connection, false = reverse (lighter, different dash)
interface Conn {
  id: string; d: string; color: string
  dur: number; w?: number; dash?: number; gap?: number
  label?: string; labelX?: number; labelY?: number
  reverse?: boolean
}

const CONNS: Conn[] = [
  // ── Frontend ↔ Backend ────────────────────────────
  { id:'fe-be', color:'#5b9bff', dur:0.55, w:2,   dash:8, gap:5, label:'REST + WebSocket', labelX:230, labelY:92,
    d:'M330,74 C330,91 167,91 167,106' },
  { id:'be-fe', color:'#26c6a0', dur:0.65, w:1.4, dash:4, gap:6, reverse:true,
    d:'M171,106 C171,91 334,91 334,74' },

  // ── Backend ↔ Kite ────────────────────────────────
  { id:'be-kt', color:'#ffab40', dur:0.5,  w:2,   dash:7, gap:4, label:'live prices', labelX:345, labelY:124,
    d:'M306,124 L368,124' },
  { id:'kt-be', color:'#26c6a0', dur:0.65, w:1.4, dash:3, gap:6, reverse:true,
    d:'M368,132 L306,132' },

  // ── Backend ↔ Anthropic Claude ────────────────────
  { id:'be-ant', color:'#c084fc', dur:0.7, w:2,   dash:6, gap:5, label:'prompts', labelX:345, labelY:180,
    d:'M306,179 L368,179' },
  { id:'ant-be', color:'#c084fc', dur:0.85, w:1.4, dash:3, gap:7, reverse:true,
    d:'M368,185 L306,185' },

  // ── Celery → Anthropic (generate_briefing at 08:45) ───
  { id:'ce-ant', color:'#c084fc', dur:1.2, w:1.4, dash:5, gap:7,
    d:'M632,378 C648,310 648,218 632,208' },

  // ── Backend fans out to domain engines ───────────
  { id:'be-pa', color:'#9c71ff', dur:0.7, w:1.8, dash:6, gap:5,
    d:'M90,208 C72,220 88,226 110,232' },
  { id:'be-ri', color:'#ff5252', dur:0.7, w:1.8, dash:6, gap:5,
    d:'M167,208 C167,220 296,220 296,232' },
  { id:'be-op', color:'#4fc3f7', dur:0.7, w:1.8, dash:6, gap:5,
    d:'M248,208 C310,220 458,220 520,232' },

  // ── Kite → Options (live chain data) ─────────────
  { id:'kt-op', color:'#ffab40', dur:0.6, w:1.6, dash:6, gap:4,
    d:'M500,152 C500,195 520,210 520,232' },

  // ── Domain → Infrastructure (straight verticals) ─
  { id:'pa-pg', color:'#b39ddb', dur:0.85, w:1.8, dash:7, gap:5,
    d:'M110,308 L110,340' },
  { id:'ri-rd', color:'#ff7043', dur:0.75, w:1.8, dash:7, gap:5,
    d:'M296,308 L296,340' },
  { id:'op-ce', color:'#26c6da', dur:0.9,  w:1.8, dash:7, gap:5,
    d:'M520,308 L520,340' },

  // ── Redis ↔ Risk Gate (risk gate reads Redis flags) ─
  { id:'rd-ri', color:'#ff7043', dur:0.9, w:1.4, dash:5, gap:6,
    d:'M220,377 C204,360 212,322 220,308' },

  // ── NSE → Postgres (bhavcopy stored) ─────────────
  { id:'nse-pg', color:'#90a4ae', dur:1.2, w:1.4, dash:5, gap:7,
    d:'M96,450 C78,430 78,418 110,414' },
  // ── NSE → Celery (data sync task) ────────────────
  { id:'nse-ce', color:'#90a4ae', dur:1.1, w:1.4, dash:5, gap:7,
    d:'M264,456 C330,440 440,440 520,414' },

  // ── Yahoo → Backend (India VIX, cached 18h) ──────
  { id:'yh-be', color:'#81d4fa', dur:1.3, w:1.4, dash:5, gap:8, label:'VIX', labelX:408, labelY:366,
    d:'M420,450 C448,370 390,268 248,208' },
  // ── Yahoo → Patterns (OHLCV tier-2 for backtests) ─
  { id:'yh-pa', color:'#81d4fa', dur:1.4, w:1.4, dash:5, gap:8,
    d:'M308,472 C252,456 176,402 110,308' },
]

// ── Tier swimlane config ──────────────────────────────────────────────────────
const BANDS = [
  { label:'PRESENTATION',   y:10,  h:82,  color:'#5b9bff' },
  { label:'APPLICATION',    y:96,  h:120, color:'#26c6a0' },
  { label:'DOMAIN LOGIC',   y:220, h:106, color:'#9c71ff' },
  { label:'INFRASTRUCTURE', y:330, h:104, color:'#90a4ae' },
  { label:'DATA SOURCES',   y:438, h:82,  color:'#81d4fa' },
]

// ── Detail panel data ─────────────────────────────────────────────────────────
interface Detail {
  title: string; color: string; tagline: string
  overview: string; bullets: string[]; tech: string[]; connects: string[]
}

const DETAILS: Record<NodeId, Detail> = {
  frontend: {
    title:'React Frontend', color:'#5b9bff',
    tagline:'10 pages · Zustand · React Query · 5 UI themes · WebSocket client',
    overview:'Single-page application built with React 18 + Vite. Handles all user interaction from signal browsing to live trade management. Five switchable themes (dark, midnight, high-contrast, solarized, light) are persisted to localStorage.',
    bullets:[
      'Dashboard — pre-market briefing (PCR, FII, India VIX, IV rank), live signal feed, multi-timeframe scanner',
      'Options — live options chain, IV rank bar, max-pain overlay, event calendar, regime badge',
      'Positions — open paper trades with real-time MTM, trailing-stop indicator, one-click close',
      'Pattern Finder — walk-forward backtests, statistical edge discovery (Mann-Whitney U)',
      'Report — Sharpe ratio, max drawdown, max consecutive losses, avg hold time, equity curve',
      'Paper Trading — virtual trade history with cumulative P&L chart',
      'Backtest — per-pattern walk-forward with equity curve and trade-level drill-down',
      'Settings — Kite credentials, trading mode, Anthropic API key, 5-theme picker',
      'System Health — component health grid, 14 Celery tasks, manual task triggers',
      'Architecture — this animated diagram',
      'Zustand: themeStore (5 themes), modeStore (paper / live / testing)',
      'React Query: 30s stale-time, background refetch on window focus',
      'All API calls centralised in api/client.ts via axios targeting /api/v1/* and /ws/*',
    ],
    tech:['React 18', 'Vite 5', 'TypeScript', 'Zustand', 'React Query', 'Recharts', 'Axios'],
    connects:['FastAPI Backend — REST + WebSocket subscriptions (/ws/signals, /ws/prices)'],
  },

  backend: {
    title:'FastAPI Backend', color:'#26c6a0',
    tagline:'Python 3.12 · async SQLAlchemy · Black-Scholes · WebSocket broadcast hub',
    overview:'Central async API server and WebSocket hub. Every trade, signal, and analytics request flows through here. Fetches India VIX from Yahoo Finance and routes AI chat requests to Anthropic Claude API. Also re-syncs Redis circuit-breaker state on every container restart.',
    bullets:[
      '/api/v1/signals — list, create, expire; TESTING_FOCUS filter; nan/inf sanitisation via _safe_dict()',
      '/api/v1/trades — open/close paper trades, MTM refresh, auto-execution gate at ≥82% confidence',
      '/api/v1/portfolio — capital tracking, heat sync, cumulative P&L time series',
      '/api/v1/backtest — walk-forward engine API with per-pattern IV-rank gate',
      '/api/v1/options — chain, IV rank, max pain, event calendar, regime overlay',
      '/api/v1/dashboard — pre-market briefing (PCR + FII + India VIX + IV rank) + performance report',
      '/api/v1/pattern-finder — discover edges, run backtests, toggle/delete discovered patterns',
      '/api/v1/settings — Kite credentials, Anthropic key, 5-check Kite connection test',
      '/api/v1/system — health checks, Celery schedule with last-run times, manual task trigger',
      '/api/v1/chat — routes user messages to Claude Sonnet 4.6 via Anthropic SDK; streams response',
      '/ws/signals — broadcasts new signals to all connected clients simultaneously',
      '/ws/prices — rebroadcasts Kite LTP ticks to browser for live price display',
      'Black-Scholes engine: synthetic option premiums + greeks when Kite is offline',
      'Startup lifespan: _sync_portfolio_heat_from_db() re-syncs Redis heat from DB open trades',
    ],
    tech:['FastAPI', 'Python 3.12', 'SQLAlchemy 2 async', 'Alembic', 'Pydantic v2', 'Anthropic SDK', 'asyncpg'],
    connects:[
      'Frontend ← REST responses + WebSocket push',
      'PostgreSQL — async ORM reads/writes',
      'Redis — circuit-breaker flag checks before every trade',
      'Celery — task dispatch via Redis broker',
      'Kite Connect — live prices and order placement',
      'Anthropic Claude — AI chat responses via Claude Sonnet 4.6',
      'Yahoo Finance — India VIX (^INDIAVIX) fetched daily, cached 18h',
    ],
  },

  kite: {
    title:'Kite Connect', color:'#ffab40',
    tagline:'Zerodha broker API · Live WebSocket ticker · Daily OAuth token rotation',
    overview:'Zerodha broker API for live market data and order execution. When disconnected the system falls back automatically: tier-2 is Yahoo Finance OHLCV, tier-3 is NSE bhav replayer. Paper trading continues uninterrupted in both fallback modes.',
    bullets:[
      'KiteTicker WebSocket — real-time LTP feed for NIFTY + BANKNIFTY futures and all tracked strikes',
      'Historical OHLCV — 15m / 1h / 4h / daily candles for multi-timeframe pattern detection (tier-1)',
      'Instrument master — full F&O universe: lot sizes, expiry dates, strike step sizes',
      'Order placement — market + limit orders; gated behind paper-trading performance threshold',
      'OAuth flow — daily access_token exchanged from request_token in Kite login redirect URL',
      'Synthetic fallback — when disconnected, Black-Scholes uses last-known IV to price all options',
      'is_synthetic detection — real signals: explanation starts "[Weekly/Monthly …]"; synthetic starts "["',
      'Connection test — /api/v1/settings/test-connection runs 5 independent sub-checks',
    ],
    tech:['kiteconnect-py', 'WebSocket', 'OAuth 2.0', 'REST API'],
    connects:[
      'FastAPI Backend — price ticks rebroadcast to /ws/prices, order placement',
      'Options Engine — live option chain data (OI, IV, LTP per strike)',
    ],
  },

  anthropic: {
    title:'Anthropic Claude', color:'#c084fc',
    tagline:'Claude Sonnet 4.6 · AI chat assistant · Pre-market briefing generation',
    overview:'Anthropic API is used in two places. (1) /api/v1/chat proxies all user messages to Claude Sonnet 4.6 for the AI Chat panel — responds with market analysis, strategy explanations, and trade ideas. (2) The generate_briefing Celery task calls Claude every morning at 08:45 IST with the day\'s PCR, FII OI, India VIX, and IV rank to produce a structured pre-market briefing.',
    bullets:[
      'AI Chat — /api/v1/chat streams Claude Sonnet 4.6 responses; the model has context on all 8 patterns, risk rules, and current portfolio state',
      'Pre-market briefing — generate_briefing Celery task at 08:45 IST; prompt includes: PCR, FII data, India VIX, IV rank, upcoming expiry events',
      'Claude Sonnet 4.6 (claude-sonnet-4-6) — fast, cost-efficient for real-time chat while retaining strong reasoning for market analysis',
      'Anthropic SDK (Python) — async client used in backend; API key stored in kite_config table',
      'No function calling used — briefing format enforced by structured prompt with section headers',
      'Fallback — if Anthropic API key is not set, /api/v1/chat returns a 400 with a setup instruction',
      'Token budget — briefing prompts are kept under 1500 tokens; chat prompts truncate history at 10 turns',
    ],
    tech:['Anthropic SDK', 'Claude Sonnet 4.6', 'Python', 'async streaming'],
    connects:[
      'FastAPI Backend — chat route proxies user messages; receives structured briefings',
      'Celery Workers — generate_briefing task calls Claude at 08:45 IST daily',
    ],
  },

  patterns: {
    title:'Pattern Engine', color:'#9c71ff',
    tagline:'8 patterns · IV rank gate · Composite confidence scorer · Walk-forward backtest',
    overview:'Alpha-generation core. Eight independently pluggable pattern modules each implement a distinct market mechanism. Runs every 5 min via Celery. Historical OHLCV priority: Kite → Yahoo Finance → NSE bhav replayer.',
    bullets:[
      'Gap Fill — pre-market gap ≥0.5% + OI > 20L; ~70% of NSE gaps fill within session',
      'PCR Divergence — PCR < 0.7 (extreme bearish) or > 1.3 (extreme bullish) = institutional flow',
      'Mean Reversion — Bollinger Band squeeze break confirmed on 15m and 1h simultaneously',
      'OI Buildup — open interest increasing alongside price = smart money accumulation',
      'VWAP + OI — price rejects VWAP on high OI = institutional price level defence',
      'IV Crush — sell options when IV rank > 75% before scheduled events (results, RBI)',
      'Max Pain Gravity — expiry week: price gravitates toward strike with least writer loss',
      'Expiry Week Theta — harvest theta decay in final 48h of weekly F&O expiry',
      'IV rank gate — each pattern requires IV rank ≥ per-pattern threshold before firing',
      'Composite scorer — 0–1 confidence: PCR + IV rank + OI trend + directional filters',
      'Auto-trade gate — ≥0.82 (real Kite) or ≥0.72 (synthetic) triggers auto paper trade',
      'Signal dedup — (underlying, pattern, direction, option_type) within 1h window',
      'Age gate — signals > 2h old are skipped at auto-execution to avoid stale strikes',
    ],
    tech:['Python', 'NumPy', 'SciPy', 'Black-Scholes', 'yfinance (OHLCV fallback)', 'NSE bhavcopy'],
    connects:[
      'FastAPI — scanner orchestrated by scan_signals Celery task every 5 min',
      'PostgreSQL — signals written to DB after dedup',
      'Yahoo Finance — tier-2 OHLCV via fetch_yfinance() when Kite unavailable',
      'NSE Market Data — bhav replayer (tier-3) for walk-forward backtests',
    ],
  },

  risk: {
    title:'Risk Gate', color:'#ff5252',
    tagline:'4 Redis circuit breakers · Daily P&L limit · Portfolio heat cap · Kill switch',
    overview:'Every trade order passes through the risk gate before execution. Four independent circuit breakers live in Redis — no DB round-trips on the hot path. State re-syncs from DB on every startup.',
    bullets:[
      'DAILY_PNL — realized P&L < −2% of capital → TRADING_HALTED set to "1" immediately',
      'Portfolio heat — total deployed capital (entry_price × quantity) capped at 3% of portfolio',
      'Kill switch — KILL_SWITCH_KEY permanent halt until manually cleared from Settings page',
      'Trailing stop — at +30% gain, stop_loss raised to entry + 50% of profit; locks in gains',
      'Position sizing — 1% capital at risk per trade; sized by (entry − stop) / lot_size',
      'Startup re-sync — _sync_portfolio_heat_from_db() writes open-trade heat back to Redis',
      'Weekly ceiling — 3% weekly drawdown triggers TRADING_HALTED via Celery weekly check',
    ],
    tech:['Redis 7', 'redis-py async', 'Python'],
    connects:[
      'Redis — atomic reads of DAILY_PNL, DAILY_DEPLOYED, TRADING_HALTED, KILL_SWITCH',
      'FastAPI — gate checked before every auto-trade',
    ],
  },

  options: {
    title:'Options Engine', color:'#4fc3f7',
    tagline:'Options chain · IV rank · Max pain · Regime classifier · Strike selector',
    overview:'Options analytics layer. IV rank, max-pain, expiry calendar, and regime classification feed into pattern confidence scores and the pre-market briefing. Live chain data comes from Kite Connect.',
    bullets:[
      'Options chain — per-strike calls + puts: OI, IV, LTP, bid/ask from Kite Connect REST API',
      'IV rank — current IV as percentile of 52-week range; primary weight in composite confidence scorer',
      'Max pain — strike minimising total OI-weighted option writer loss; computed from NSE bhavcopy OI',
      'Expiry calendar — weekly Thursday + monthly last-Thursday for NIFTY and BANKNIFTY',
      'Event calendar — results dates, RBI policy, index rebalancing flagged for IV Crush pattern',
      'Strike selector — ATM ± N strikes based on signal direction, DTE, and lot size constraints',
      'Regime — bullish/bearish/neutral: PCR + price vs VWAP + OI trend must all agree',
    ],
    tech:['Python', 'Black-Scholes', 'Kite Connect API', 'NSE bhavcopy'],
    connects:[
      'Kite Connect — live option chain data (OI, IV, LTP per strike)',
      'FastAPI — analytics served to Dashboard and Options pages',
    ],
  },

  postgres: {
    title:'PostgreSQL', color:'#b39ddb',
    tagline:'7 tables · SQLAlchemy 2 async · asyncpg · Alembic migrations',
    overview:'Primary relational store for all persistent state. SQLAlchemy 2.0 async ORM with asyncpg driver. Alembic manages incremental schema migrations — the DB schema evolves without data loss.',
    bullets:[
      'signals — strike, expiry, premium, IV, DTE, direction, confidence, explanation, valid_until, status',
      'trades — entry/exit prices, MTM, stop_loss (updated by trailing stop), brokerage, realized P&L',
      'portfolio — capital_initial, capital_current, peak_capital, max_drawdown_pct, weekly_pnl, total_trades; one row per mode',
      'kite_config — API key, API secret, daily access_token, anthropic_api_key',
      'discovered_patterns — Mann-Whitney U p-values, sample size, effect size, has_edge bool',
      'pattern_backtest_runs — Sharpe, max drawdown, win rate, profit factor, date range per pattern',
      'pattern_backtest_trades — individual simulated trades per run for Pattern Finder drill-down',
      'TradeStatus enum: OPEN, CLOSED, CANCELLED, PENDING, EXPIRED (uppercase in DB)',
      'Portfolio mode: lowercase varchar "paper" or "live" (NOT a DB enum)',
    ],
    tech:['PostgreSQL 15', 'SQLAlchemy 2 async', 'asyncpg', 'Alembic'],
    connects:[
      'FastAPI — all async reads and writes',
      'Celery — task results, discovered patterns, backtest runs stored here',
    ],
  },

  redis: {
    title:'Redis', color:'#ff7043',
    tagline:'4 circuit-breaker keys · Celery broker · Daily P&L state · Zero-latency risk checks',
    overview:'In-memory store for real-time risk state and Celery task brokering. State resets at 09:15 IST daily. All risk checks are in-memory — zero DB latency on the trade hot path.',
    bullets:[
      'DAILY_PNL_KEY — running sum of realized P&L; compared against −2% capital limit on every trade',
      'DAILY_DEPLOYED_KEY — sum of entry_price × quantity for all open trades; capped at 3% heat',
      'TRADING_HALTED_KEY — "1"/"0"; highest-priority check before every auto-trade',
      'KILL_SWITCH_KEY — permanent halt "1"; only cleared manually from Settings page',
      'Celery broker — Redis queues all 14 task messages; stores task results (result_backend)',
      'Startup — _sync_portfolio_heat_from_db() reloads DAILY_DEPLOYED_KEY from DB open trades',
      'Daily reset — reset_daily_pnl Celery task clears PNL + DEPLOYED at 09:15 IST; resyncs',
    ],
    tech:['Redis 7', 'redis-py async', 'Celery broker + result backend'],
    connects:[
      'Risk Gate — atomic flag reads on every trade decision',
      'Celery — message broker for all 14 tasks; result storage',
      'FastAPI — startup heat sync',
    ],
  },

  celery: {
    title:'Celery Workers', color:'#26c6da',
    tagline:'14 scheduled tasks · Celery Beat · Redis broker · Runs independently of FastAPI',
    overview:'Distributed task queue running independently of FastAPI. Heavy jobs (scanning, backtesting, data sync) never block API responses. Celery Beat provides cron-like scheduling. generate_briefing calls Anthropic Claude API every morning.',
    bullets:[
      'scan_signals (*/5 min) — runs all 8 patterns; deduplicates; auto-executes ≥82% conf as paper trades',
      'mtm_update (*/2 min) — marks all open trades to market; applies trailing stop at +30% gain',
      'settle_expired (*/10 min) — closes trades whose options have passed expiry date',
      'cleanup_stale_signals (*/15 min) — expires ACTIVE signals past valid_until; purges EXPIRED records',
      'eod_close_intraday (15:20 IST Mon–Fri) — force-closes intraday trades before auto-square-off',
      'sync_market_data (16:15 IST Mon–Fri) — downloads NSE bhavcopy; bootstraps PCR + max-pain cache',
      'run_nightly_backtests (16:00 daily) — walk-forward backtests all discovered patterns',
      'run_nightly_discovery (02:00 daily) — Mann-Whitney U miner on bhav history for new edges',
      'reset_daily_pnl (09:15 daily) — clears Redis P&L + deployed capital; resyncs heat from DB',
      'reset_weekly_pnl (Monday 09:15) — clears weekly_pnl field in portfolio table',
      'generate_briefing (08:45 IST) — calls Anthropic Claude with PCR, FII, India VIX, IV rank data',
    ],
    tech:['Celery 5', 'Celery Beat', 'Redis broker', 'Python 3.12', 'Anthropic SDK'],
    connects:[
      'Redis — all task messages queued here; results stored here',
      'PostgreSQL — patterns, backtest runs, briefings stored here',
      'FastAPI — triggered on demand via POST /api/v1/system/run-task/{name}',
      'Anthropic Claude — generate_briefing sends market data and gets structured briefing text',
      'NSE Market Data — bhavcopy downloaded and processed by sync_market_data',
    ],
  },

  nse: {
    title:'NSE Market Data', color:'#90a4ae',
    tagline:'Bhavcopy CSVs · PCR cache · FII OI (CCIL) · Bhav replayer (tier-3 OHLCV)',
    overview:'Offline NSE data pipeline. Daily bhavcopy CSV files form the backbone of backtesting, PCR computation, and IV rank history. 184+ dates already cached. The bhav replayer is the tier-3 OHLCV source when both Kite Connect and Yahoo Finance are unavailable.',
    bullets:[
      'Bhavcopy CSV — NSE daily F&O settlement: OI, volume, settlement price per strike per expiry',
      'PCR cache — put/call ratio per underlying per date; 184+ dates in pcr_NIFTY.csv etc.',
      'Max pain — strike minimising total OI-weighted writer loss; recomputed from each bhav file',
      'FII OI (CCIL) — participant-wise OI: FII, DII, proprietary; signals institutional positioning',
      'IV rank — historical IV from bhavcopy settlement prices; 52-week percentile rank',
      'Bhav replayer — tier-3 synthetic OHLCV for walk-forward backtests (slowest, most reliable)',
      'Bootstrap — build_pcr_from_cached_bhav() processes all cached CSVs on demand',
      'Sync — sync_market_data Celery task downloads next bhavcopy at 16:15 IST after market close',
    ],
    tech:['pandas', 'NSE bhavcopy format', 'CSV pipeline', 'SciPy Mann-Whitney'],
    connects:[
      'Celery sync_market_data — bhavcopy downloaded and processed at 16:15 IST',
      'PostgreSQL — processed PCR / IV rank / max-pain data stored here',
      'Pattern Engine — bhav replayer provides tier-3 OHLCV for walk-forward backtests',
    ],
  },

  yahoo: {
    title:'Yahoo Finance', color:'#81d4fa',
    tagline:'India VIX (^INDIAVIX) · OHLCV tier-2 fallback · yfinance 0.2.40+ · Free tier',
    overview:'Free market data API with two distinct roles. (1) Sole free source of India VIX via ^INDIAVIX ticker — fetched daily, cached 18h. (2) Tier-2 OHLCV source when Kite Connect is not configured, enabling pattern discovery without a broker subscription. Data priority: Kite → Yahoo → NSE bhav replayer.',
    bullets:[
      'India VIX — ^INDIAVIX downloaded daily; cached in market_data/india_vix.csv with 18h TTL',
      'OHLCV tier-2 — when Kite is not configured, yfinance provides historical candles for backtesting',
      'Ticker map — NIFTY→^NSEI, BANKNIFTY→^NSEBANK, FINNIFTY→NIFTY_FIN_SERVICE.NS, stocks→SYM.NS',
      'Interval limits — 60 days of 15m candles, 730 days of 1h, 1825 days of daily OHLCV',
      'OI / IV gap — Yahoo Finance does NOT carry open interest or option IV; bhavcopy fills those',
      'Source tag — backtest run records tagged source="yahoo" vs "kite" vs "synthetic"',
      'Multi-level column handling — yfinance sometimes returns multi-level DataFrame columns; code flattens',
      'Lazy import — yfinance imported only when Kite is unavailable; no overhead when Kite is connected',
    ],
    tech:['yfinance 0.2.40+', 'pandas', 'Python', 'NSE ticker map'],
    connects:[
      'FastAPI Backend — India VIX via fetch_india_vix(), cached 18h in market_data/india_vix.csv',
      'Pattern Engine — OHLCV via fetch_yfinance() called from get_historical_data() as tier-2 source',
      'Celery — sync_market_data also triggers VIX refresh alongside bhavcopy download',
    ],
  },
}

// ─────────────────────────────────────────────────────────────────────────────

export default function Architecture() {
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [hovered,  setHovered]  = useState<NodeId | null>(null)
  const detail = selected ? DETAILS[selected] : null

  return (
    <div style={{ display:'flex', height:'100%', background:'var(--bg)', overflow:'hidden' }}>

      {/* ── Diagram ──────────────────────────────────────────────────────────── */}
      <div style={{ flex:1, overflow:'auto', padding:'14px 10px 14px 14px', minWidth:0 }}>

        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <span style={{ fontSize:13, fontWeight:700, color:'var(--txt)' }}>AlphaFO — System Architecture</span>
          <span style={{ fontSize:11, color:'var(--txt3)' }}>· click any component for details</span>
          {selected && (
            <button onClick={() => setSelected(null)} className="tv-btn tv-btn-ghost"
              style={{ marginLeft:'auto', fontSize:11, padding:'2px 10px' }}>✕ close</button>
          )}
        </div>

        <svg viewBox="0 0 660 524" width="100%"
          style={{ display:'block', maxHeight:'calc(100vh - 80px)' }}
          aria-label="AlphaFO system architecture">

          <defs>
            {/* Arrowhead marker — inherits connection colour via context-stroke */}
            <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M1.5,1.5 L8,5 L1.5,8.5" fill="none" stroke="context-stroke"
                strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
            </marker>

            {/* Glow filter for selected node */}
            <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>

            {/* Per-node gradient fills — idle + selected variants */}
            {(Object.keys(N) as NodeId[]).map(id => {
              const c = N[id].color
              return (
                <g key={id}>
                  <linearGradient id={`gi-${id}`} x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stopColor={c} stopOpacity="0.16"/>
                    <stop offset="100%" stopColor={c} stopOpacity="0.05"/>
                  </linearGradient>
                  <linearGradient id={`gs-${id}`} x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stopColor={c} stopOpacity="0.30"/>
                    <stop offset="100%" stopColor={c} stopOpacity="0.12"/>
                  </linearGradient>
                </g>
              )
            })}
          </defs>

          {/* ── CSS keyframes for flowing dashes ─────────────────────────────── */}
          <style>{`
            @keyframes dash-flow { 100% { stroke-dashoffset: -12; } }
            @keyframes ring-pulse {
              0%,100% { stroke-opacity:0.5; stroke-width:2; }
              50%      { stroke-opacity:1;   stroke-width:2.8; }
            }
            .sel-ring { animation: ring-pulse 1.4s ease-in-out infinite; }
            .arch-node { cursor: pointer; }
            .arch-node:hover .arch-body { filter: brightness(1.06); }
          `}</style>

          {/* ── Tier swimlane bands ───────────────────────────────────────────── */}
          {BANDS.map(b => (
            <g key={b.label}>
              {/* Band fill */}
              <rect x="10" y={b.y} width="642" height={b.h} rx="7"
                fill={b.color} fillOpacity="0.05"
                stroke={b.color} strokeOpacity="0.12" strokeWidth="1"/>
              {/* Left accent bar */}
              <rect x="10" y={b.y} width="4" height={b.h} rx="2"
                fill={b.color} fillOpacity="0.5"/>
              {/* Tier label */}
              <text x="648" y={b.y + 13} textAnchor="start"
                fill={b.color} fillOpacity="0.4" fontSize="8" fontWeight="800"
                fontFamily="-apple-system,BlinkMacSystemFont,sans-serif"
                letterSpacing="0.09em">{b.label}</text>
            </g>
          ))}

          {/* ── Horizontal tier dividers ──────────────────────────────────────── */}
          {[92, 218, 328, 436].map(y => (
            <line key={y} x1="20" y1={y} x2="642" y2={y}
              stroke="#2a2e39" strokeWidth="0.6" strokeDasharray="2 6"/>
          ))}

          {/* ── Connection lines (animated flowing dashes) ───────────────────── */}
          {CONNS.map(c => {
            const dashArr = `${c.dash ?? 7} ${c.gap ?? 5}`
            const totalDash = (c.dash ?? 7) + (c.gap ?? 5)
            return (
              <g key={c.id}>
                {/* Static directional arrow (faint) */}
                <path d={c.d} fill="none" stroke={c.color}
                  strokeWidth="1" strokeOpacity="0.18" markerEnd="url(#arr)"/>

                {/* Animated dashed flow line */}
                <path d={c.d} fill="none" stroke={c.color}
                  strokeWidth={c.w ?? 1.8}
                  strokeOpacity={c.reverse ? 0.45 : 0.82}
                  style={{
                    strokeDasharray: dashArr,
                    strokeDashoffset: 0,
                    animation: `dash-flow ${c.dur}s linear infinite`,
                    animationTimingFunction: 'linear',
                  } as React.CSSProperties}
                />

                {/* Inline label */}
                {c.label && c.labelX != null && c.labelY != null && (() => {
                  const lw = c.label.length * 6.2 + 14
                  return (
                    <g>
                      <rect x={(c.labelX) - lw/2} y={(c.labelY) - 11}
                        width={lw} height={14} rx="3"
                        fill="var(--bg2)" fillOpacity="0.92"
                        stroke={c.color} strokeOpacity="0.3" strokeWidth="0.8"/>
                      <text x={c.labelX} y={c.labelY} textAnchor="middle"
                        fill={c.color} fillOpacity="0.82" fontSize="9" fontWeight="700"
                        fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">{c.label}</text>
                    </g>
                  )
                })()}
              </g>
            )
          })}

          {/* ── Nodes ─────────────────────────────────────────────────────────── */}
          {(Object.entries(N) as [NodeId, NodeMeta][]).map(([id, n]) => {
            const isSel = selected === id
            const isHov = hovered === id
            const active = isSel || isHov
            const midY   = n.y + n.h / 2
            const gradId = active ? `gs-${id}` : `gi-${id}`
            return (
              <g key={id} className="arch-node"
                onClick={() => setSelected(isSel ? null : id)}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}>

                {/* Pulsing selection ring */}
                {isSel && (
                  <rect x={n.x-4} y={n.y-4} width={n.w+8} height={n.h+8}
                    rx="10" fill="none" stroke={n.color}
                    filter="url(#glow)" className="sel-ring"/>
                )}

                {/* Node body — gradient fill */}
                <rect className="arch-body"
                  x={n.x} y={n.y} width={n.w} height={n.h} rx="7"
                  fill={`url(#${gradId})`}
                  stroke={n.color}
                  strokeWidth={active ? 1.8 : 0.9}
                  strokeOpacity={active ? 0.9 : 0.38}
                />

                {/* Top accent stripe */}
                <rect x={n.x+1} y={n.y+1} width={n.w-2} height="3" rx="1.5"
                  fill={n.color} fillOpacity={active ? 0.9 : 0.55}/>

                {/* Primary label */}
                <text x={n.x + n.w/2} y={midY - (n.h > 60 ? 8 : 6)}
                  textAnchor="middle" fill={n.color} fillOpacity="0.95"
                  fontSize="12" fontWeight="700"
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                  {n.label}
                </text>

                {/* Sub-label */}
                <text x={n.x + n.w/2} y={midY + (n.h > 60 ? 8 : 10)}
                  textAnchor="middle" fill={n.color} fillOpacity="0.46"
                  fontSize={n.w < 180 ? 8.5 : 10}
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                  {n.sub}
                </text>

                {/* "external" badge */}
                {n.ext && (
                  <text x={n.x + n.w - 7} y={n.y + n.h - 5}
                    textAnchor="end" fill={n.color} fillOpacity="0.38"
                    fontSize="8" fontWeight="600"
                    fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                    external
                  </text>
                )}
              </g>
            )
          })}

          {/* ── Small legend row ──────────────────────────────────────────────── */}
          <g transform="translate(20,510)">
            <text x="0" y="10" fill="#636670" fontSize="9" fontFamily="-apple-system,sans-serif" fontWeight="600">LEGEND:</text>
            {/* Primary flow */}
            <line x1="58" y1="6" x2="90" y2="6" stroke="#5b9bff" strokeWidth="2" strokeDasharray="7 5"/>
            <text x="94" y="10" fill="#636670" fontSize="9" fontFamily="-apple-system,sans-serif">primary flow</text>
            {/* Response */}
            <line x1="162" y1="6" x2="194" y2="6" stroke="#26c6a0" strokeWidth="1.4" strokeDasharray="4 6" opacity="0.7"/>
            <text x="198" y="10" fill="#636670" fontSize="9" fontFamily="-apple-system,sans-serif">response / reverse</text>
            {/* External */}
            <rect x="302" y="1" width="32" height="12" rx="2" fill="#c084fc" fillOpacity="0.1" stroke="#c084fc" strokeOpacity="0.4" strokeWidth="0.8"/>
            <text x="340" y="10" fill="#636670" fontSize="9" fontFamily="-apple-system,sans-serif">= external API</text>
          </g>

        </svg>
      </div>

      {/* ── Detail side panel ─────────────────────────────────────────────────── */}
      {detail && selected && (
        <div style={{
          width:352, flexShrink:0,
          borderLeft:'1px solid var(--border)',
          background:'var(--bg2)',
          overflow:'auto',
          padding:'18px 20px',
          display:'flex', flexDirection:'column', gap:16,
        }}>

          {/* Header */}
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:5 }}>
              <span style={{
                display:'inline-block', width:10, height:10,
                borderRadius:'50%', background:N[selected].color, flexShrink:0,
              }}/>
              <span style={{ fontWeight:800, fontSize:15, color:'var(--txt)', flex:1 }}>{detail.title}</span>
              {N[selected].ext && (
                <span style={{
                  fontSize:9, fontWeight:700, padding:'2px 7px', borderRadius:3,
                  background:`${N[selected].color}18`, color:N[selected].color,
                  border:`1px solid ${N[selected].color}44`,
                }}>EXTERNAL</span>
              )}
            </div>
            <div style={{ fontSize:11, color:N[selected].color, opacity:0.8, fontWeight:600, marginBottom:10 }}>
              {detail.tagline}
            </div>
            <div style={{ fontSize:12, color:'var(--txt2)', lineHeight:1.7 }}>{detail.overview}</div>
          </div>

          {/* Accent divider */}
          <div style={{ height:2, borderRadius:1, background:`linear-gradient(90deg,${N[selected].color}60,transparent)` }}/>

          {/* Responsibilities */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.09em', marginBottom:10 }}>
              Responsibilities
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
              {detail.bullets.map((b, i) => (
                <div key={i} style={{ display:'flex', gap:8, alignItems:'flex-start' }}>
                  <span style={{
                    flexShrink:0, marginTop:2, width:5, height:5, borderRadius:'50%',
                    background:N[selected].color, opacity:0.7, display:'inline-block',
                  }}/>
                  <span style={{ fontSize:11, color:'var(--txt2)', lineHeight:1.6 }}>{b}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Connects to */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.09em', marginBottom:10 }}>
              Connects to
            </div>
            {detail.connects.map((c, i) => (
              <div key={i} style={{
                fontSize:11, color:'var(--txt2)', padding:'6px 0',
                borderBottom:'1px solid var(--border)', lineHeight:1.55,
              }}>{c}</div>
            ))}
          </div>

          {/* Technology */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.09em', marginBottom:10 }}>
              Technology
            </div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
              {detail.tech.map(t => (
                <span key={t} style={{
                  fontSize:10, padding:'3px 9px', borderRadius:4, fontWeight:600,
                  background:`${N[selected].color}16`,
                  color:N[selected].color,
                  border:`1px solid ${N[selected].color}38`,
                }}>{t}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
