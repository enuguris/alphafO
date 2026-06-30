import { useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

type NodeId =
  | 'frontend' | 'backend' | 'kite'
  | 'patterns' | 'risk' | 'options'
  | 'postgres' | 'redis' | 'celery'
  | 'nse' | 'yahoo'

interface NodeMeta {
  x: number; y: number; w: number; h: number
  label: string; sub: string; color: string; ext?: boolean
}

interface Conn {
  id: string; d: string; color: string; dur: number
  r?: number; label?: string; labelX?: number; labelY?: number
}

// ─── Visual layout ────────────────────────────────────────────────────────────

const N: Record<NodeId, NodeMeta> = {
  frontend: { x:130, y:22,  w:400, h:54,  label:'React Frontend',   sub:'10 pages · Zustand · WebSocket hub',             color:'#4488ff' },
  backend:  { x:28,  y:118, w:282, h:58,  label:'FastAPI Backend',  sub:'Python 3.12 · async · 10 API routes',             color:'#26a69a' },
  kite:     { x:370, y:118, w:262, h:58,  label:'Kite Connect',     sub:'Zerodha · live prices · OAuth daily token',        color:'#ff9800', ext:true },
  patterns: { x:28,  y:226, w:164, h:72,  label:'Pattern Engine',   sub:'8 patterns · IV gate · composite score',           color:'#7b61ff' },
  risk:     { x:220, y:226, w:152, h:72,  label:'Risk Gate',        sub:'circuit breakers · trailing stop',                 color:'#ef5350' },
  options:  { x:408, y:226, w:224, h:72,  label:'Options Engine',   sub:'chain · IV rank · max pain · regime',              color:'#4fa3e0' },
  postgres: { x:28,  y:342, w:164, h:72,  label:'PostgreSQL',       sub:'7 tables · Alembic migrations',                   color:'#9b8fff' },
  redis:    { x:220, y:342, w:152, h:72,  label:'Redis',            sub:'4 circuit breakers · Celery broker',               color:'#ff6b6b' },
  celery:   { x:408, y:342, w:224, h:72,  label:'Celery Workers',   sub:'14 scheduled tasks · Celery Beat',                color:'#26c6b0' },
  nse:      { x:28,  y:458, w:258, h:56,  label:'NSE Market Data',  sub:'bhavcopy · PCR cache · FII OI · bhav replayer',   color:'#888780' },
  yahoo:    { x:308, y:458, w:324, h:56,  label:'Yahoo Finance',    sub:'India VIX (^INDIAVIX) · OHLCV fallback tier-2',   color:'#7ecaff', ext:true },
}

// ─── Connection paths ─────────────────────────────────────────────────────────

const CONNS: Conn[] = [
  // Frontend ↔ Backend (S-curves, slightly offset)
  {
    id:'fe-be', color:'#4488ff', dur:1.7,
    d:'M330,76 C330,97 169,97 169,118',
    label:'REST + WebSocket', labelX:220, labelY:94,
  },
  {
    id:'be-fe', color:'#26a69a', dur:2.1,
    d:'M173,118 C173,97 334,97 334,76',
  },

  // Backend ↔ Kite (horizontal pair, offset)
  {
    id:'be-kt', color:'#ff9800', dur:1.4,
    d:'M310,140 L370,140',
    label:'live prices', labelX:338, labelY:133,
  },
  {
    id:'kt-be', color:'#26a69a', dur:1.8,
    d:'M370,150 L310,150',
  },

  // Backend → Domain engines (fan out)
  { id:'be-pa', color:'#7b61ff', dur:2.0, d:'M90,176 C70,204 90,218 110,226' },
  { id:'be-ri', color:'#ef5350', dur:1.6, d:'M169,176 C169,204 296,204 296,226' },
  { id:'be-op', color:'#4fa3e0', dur:1.9, d:'M248,176 C310,204 460,204 520,226' },

  // Kite → Options (live chain data)
  { id:'kt-op', color:'#ff9800', dur:1.3, d:'M501,176 L520,226' },

  // Domain → Infrastructure (straight verticals)
  { id:'pa-pg', color:'#9b8fff', dur:1.3, d:'M110,298 L110,342' },
  { id:'ri-rd', color:'#ff6b6b', dur:1.1, d:'M296,298 L296,342' },
  { id:'op-ce', color:'#26c6b0', dur:1.5, d:'M520,298 L520,342' },

  // Redis → Risk Gate (risk gate reads Redis flags; curves left between the two)
  {
    id:'rd-ri', color:'#ff4444', dur:1.9, r:2.5,
    d:'M220,378 C200,356 212,314 220,298',
  },

  // NSE → PostgreSQL + Celery (batch data flow upward)
  { id:'nse-pg', color:'#888780', dur:2.2, r:2.8, d:'M90,458 C70,432 76,418 110,414' },
  { id:'nse-ce', color:'#888780', dur:2.0, r:2.8, d:'M262,466 C330,440 440,440 520,414' },

  // Yahoo → Backend (India VIX — daily fetch, cached 18h)
  {
    id:'yh-be', color:'#7ecaff', dur:2.5, r:2.8,
    d:'M420,458 C450,360 390,260 248,176',
    label:'VIX', labelX:404, labelY:360,
  },

  // Yahoo → Pattern Engine (OHLCV tier-2 for walk-forward backtests)
  { id:'yh-pa', color:'#7ecaff', dur:2.8, r:2.8, d:'M308,480 C250,458 174,410 110,298' },
]

// ─── Tier bands ───────────────────────────────────────────────────────────────

const BANDS = [
  { label:'PRESENTATION',   y:10,  h:88,  color:'#4488ff' },
  { label:'APPLICATION',    y:102, h:100, color:'#26a69a' },
  { label:'DOMAIN LOGIC',   y:206, h:106, color:'#7b61ff' },
  { label:'INFRASTRUCTURE', y:316, h:110, color:'#888780' },
  { label:'DATA SOURCES',   y:430, h:94,  color:'#7ecaff' },
]

// ─── Detail panel content ─────────────────────────────────────────────────────

interface Detail {
  title: string; color: string; tagline: string
  overview: string; bullets: string[]; tech: string[]; connects: string[]
}

const DETAILS: Record<NodeId, Detail> = {
  frontend: {
    title:'React Frontend', color:'#4488ff',
    tagline:'10 pages · Zustand · React Query · 5 themes · WebSocket',
    overview:'SPA built with React 18 + Vite. Handles all user interaction from signal browsing to live trade management. Five switchable UI themes (dark, midnight, high-contrast, solarized, light) persisted in localStorage.',
    bullets:[
      'Dashboard — pre-market briefing (PCR, FII, India VIX, IV rank), live signal feed, multi-timeframe sector scanner',
      'Options — live chain analysis, IV rank bar, max-pain overlay, event calendar, regime badge',
      'Positions — open paper trades with real-time MTM, trailing-stop indicator, one-click close',
      'Pattern Finder — run walk-forward backtests, discover statistical edges via Mann-Whitney U test',
      'Report — Sharpe ratio, max drawdown, max consecutive losses, avg hold time, equity curve',
      'Paper Trading — full virtual trade history with cumulative P&L chart',
      'Backtest — per-pattern walk-forward with equity curve and individual trade drill-down',
      'Settings — Kite credentials, trading mode selector, Anthropic API key, 5-theme picker grid',
      'System Health — component health grid, 14 Celery tasks with last-run timestamps, manual triggers',
      'Architecture — this animated diagram',
      'Zustand: themeStore (5 themes), modeStore (paper / live / testing)',
      'React Query: 30s stale-time; background refetch on window focus for portfolio and signals',
      'api/client.ts centralises all axios calls targeting /api/v1/* and /ws/* endpoints',
    ],
    tech:['React 18', 'Vite 5', 'TypeScript', 'Zustand', 'React Query', 'Recharts', 'Axios'],
    connects:['FastAPI Backend — all REST requests + WebSocket subscriptions (/ws/signals, /ws/prices)'],
  },

  backend: {
    title:'FastAPI Backend', color:'#26a69a',
    tagline:'Python 3.12 · async SQLAlchemy · Black-Scholes · WebSocket hub',
    overview:'Central async API server and WebSocket broadcast hub. Every trade, signal, and analytics request flows through here. Also fetches India VIX from Yahoo Finance (^INDIAVIX) and includes it in the pre-market briefing.',
    bullets:[
      '/api/v1/signals — list, create, expire; TESTING_FOCUS filter; nan/inf sanitisation via _safe_dict()',
      '/api/v1/trades — open/close paper trades, MTM refresh, auto-execution gate at ≥82% confidence',
      '/api/v1/portfolio — capital tracking, heat sync, cumulative P&L time series',
      '/api/v1/backtest — walk-forward engine API with per-pattern IV-rank gate',
      '/api/v1/options — chain, IV rank, max pain, event calendar, regime overlay',
      '/api/v1/dashboard — pre-market briefing (PCR + FII + India VIX + IV rank) + full performance report',
      '/api/v1/pattern-finder — discover edges, run backtests, toggle/delete discovered patterns',
      '/api/v1/settings — Kite credentials, Anthropic key, 5-check Kite connection test',
      '/api/v1/system — health checks, Celery schedule with last-run times, manual task trigger',
      '/api/v1/chat — routes messages to Claude Sonnet 4.6 via Anthropic SDK',
      '/ws/signals — broadcasts new signals to ALL connected clients simultaneously',
      '/ws/prices — rebroadcasts Kite LTP ticks to browser for live price display',
      'Black-Scholes engine: synthetic option premiums + greeks when Kite is offline',
      'Startup lifespan: re-syncs Redis deployed-capital from DB open trades to survive restarts',
    ],
    tech:['FastAPI', 'Python 3.12', 'SQLAlchemy 2 async', 'Alembic', 'Pydantic v2', 'Anthropic SDK', 'asyncpg'],
    connects:[
      'Frontend ← REST responses + WebSocket push',
      'PostgreSQL — async ORM reads/writes via SQLAlchemy',
      'Redis — circuit-breaker flag checks before every trade',
      'Celery — task dispatch via Redis broker',
      'Kite Connect — live prices and order placement',
      'Yahoo Finance — India VIX (^INDIAVIX) fetched daily, cached 18h in market_data/india_vix.csv',
    ],
  },

  kite: {
    title:'Kite Connect', color:'#ff9800',
    tagline:'Zerodha broker API · Live WebSocket ticker · Daily OAuth token',
    overview:'Zerodha broker API for live market data and order execution. When disconnected the system falls back automatically to Black-Scholes synthetic pricing (tier-2: Yahoo Finance OHLCV, tier-3: NSE bhav replayer), so paper trading continues without interruption.',
    bullets:[
      'KiteTicker WebSocket — real-time LTP feed for NIFTY + BANKNIFTY futures and all tracked option strikes',
      'Historical OHLCV — 15m / 1h / 4h / daily candles for multi-timeframe pattern detection (tier-1 source)',
      'Instrument master — full F&O universe: lot sizes, expiry dates, strike step sizes for all underlyings',
      'Order placement — market + limit orders for live trading; gated behind paper-trading performance threshold',
      'OAuth flow — daily access_token obtained by exchanging request_token from Kite login redirect URL',
      'Synthetic fallback — when disconnected, Black-Scholes uses last-known IV to price all options',
      'is_synthetic flag — real signals have explanation "[Weekly/Monthly expiry …]"; synthetic starts with "["',
      'Connection test — /api/v1/settings/test-connection runs 5 independent sub-checks with breakdown',
    ],
    tech:['kiteconnect-py', 'WebSocket', 'OAuth 2.0', 'REST API'],
    connects:[
      'FastAPI Backend — all REST calls, price ticks rebroadcast to /ws/prices, order placement',
      'Options Engine — live option chain data (OI, IV, LTP per strike)',
    ],
  },

  patterns: {
    title:'Pattern Engine', color:'#7b61ff',
    tagline:'8 patterns · IV rank gate · Composite confidence scorer · Walk-forward backtesting',
    overview:'Alpha-generation core. Eight independently pluggable pattern modules each implement a distinct market mechanism. Data priority for OHLCV: Kite Connect → Yahoo Finance → NSE bhav replayer.',
    bullets:[
      'Gap Fill — pre-market gap ≥0.5% + OI > 20L; ~70% of gaps fill within the same session',
      'PCR Divergence — PCR < 0.7 (bearish extreme) or > 1.3 (bullish) signals institutional positioning',
      'Mean Reversion — Bollinger Band squeeze break confirmed on both 15m and 1h timeframes',
      'OI Buildup — open interest increasing alongside price confirmation = smart money accumulation',
      'VWAP + OI — price rejects VWAP level on high OI buildup = institutional level defence',
      'IV Crush — sell options when IV rank > 75% ahead of scheduled events (results, RBI policy)',
      'Max Pain Gravity — expiry week: price gravitates to strike where option writers lose least',
      'Expiry Week Theta — harvest rapid theta decay in the final 48 hours of weekly expiry',
      'IV rank gate — each pattern requires IV rank above a per-pattern threshold before firing',
      'Composite scorer — 0–1 confidence: PCR weight + IV rank + OI trend + directional filters',
      'Auto-trade gate — ≥0.82 confidence (real Kite) or ≥0.72 (synthetic) triggers auto paper trade',
      'Signal dedup — (underlying, pattern, direction, option_type) within 1-hour window prevents floods',
      'Age gate — signals older than 2 hours are skipped at auto-execution time to avoid stale strikes',
    ],
    tech:['Python', 'NumPy', 'SciPy', 'Black-Scholes', 'Yahoo Finance (yfinance)', 'NSE bhavcopy'],
    connects:[
      'FastAPI — scanner orchestrated by scan_signals Celery task every 5 min',
      'PostgreSQL — signals written to DB after dedup check',
      'Yahoo Finance — tier-2 OHLCV via fetch_yfinance() when Kite unavailable; 60d 15m, 730d 1h, 1825d daily',
      'NSE Market Data — bhav replayer (tier-3) for walk-forward backtests when both Kite and Yahoo fail',
    ],
  },

  risk: {
    title:'Risk Gate', color:'#ef5350',
    tagline:'4 Redis circuit breakers · Daily P&L limit · Portfolio heat · Kill switch',
    overview:'Every trade order passes through the risk gate before execution. Four independent circuit breakers live in Redis — no DB round-trips on the hot path. All checks are atomic.',
    bullets:[
      'DAILY_PNL — realized P&L drops below −2% of capital → TRADING_HALTED set to "1" immediately',
      'Portfolio heat — total deployed capital (entry_price × quantity) across all open positions capped at 3%',
      'Kill switch — KILL_SWITCH_KEY is permanent halt "1" until manually cleared from the Settings page',
      'Trailing stop — at +30% gain, stop_loss raised to entry + 50% of profit; locks in gains automatically',
      'Position sizing — 1% capital at risk per trade, sized by (entry − stop) / lot_size to determine quantity',
      'Startup re-sync — on container restart, open trades in DB are summed and written back to Redis to restore heat',
      'Weekly loss ceiling — 3% weekly drawdown triggers the same TRADING_HALTED flag via Celery weekly check',
    ],
    tech:['Redis 7', 'redis-py async', 'Python'],
    connects:[
      'Redis — atomic reads of DAILY_PNL, DAILY_DEPLOYED, TRADING_HALTED, KILL_SWITCH before every trade',
      'FastAPI — gate checked before every auto-trade decision',
    ],
  },

  options: {
    title:'Options Engine', color:'#4fa3e0',
    tagline:'Options chain · IV rank · Max pain · Regime classifier',
    overview:'Options analytics layer. IV rank, max-pain, expiry calendar, and regime classification all feed into pattern confidence scores and the pre-market briefing. Live chain data comes from Kite Connect.',
    bullets:[
      'Options chain — per-strike calls + puts: OI, IV, LTP, bid/ask from Kite Connect REST API',
      'IV rank — current IV as percentile of 52-week high/low range; primary weight in composite confidence scorer',
      'Max pain — strike minimising total OI-weighted option writer loss; computed from NSE bhavcopy OI',
      'Expiry calendar — weekly Thursday + monthly last-Thursday for NIFTY and BANKNIFTY',
      'Event calendar — results dates, RBI policy meetings, index rebalancing flagged for IV Crush pattern',
      'Strike selector — ATM ± N strikes chosen based on signal direction, DTE, and lot size constraints',
      'Regime — bullish / bearish / neutral: requires PCR + price vs VWAP + OI trend to agree',
    ],
    tech:['Python', 'Black-Scholes', 'Kite Connect API', 'NSE bhavcopy'],
    connects:[
      'Kite Connect — live option chain data input',
      'FastAPI — analytics results served to Dashboard and Options pages',
    ],
  },

  postgres: {
    title:'PostgreSQL', color:'#9b8fff',
    tagline:'7 tables · SQLAlchemy 2 async · Alembic migrations',
    overview:'Primary relational store for all persistent state. SQLAlchemy 2.0 async ORM with asyncpg driver. Alembic manages incremental schema migrations.',
    bullets:[
      'signals — strike, expiry, premium, IV, DTE, direction, confidence, explanation, valid_until, status',
      'trades — entry/exit prices, MTM, stop_loss (updated by trailing stop), brokerage, realized P&L, notes',
      'portfolio — capital_initial, capital_current, peak_capital, max_drawdown_pct, weekly_pnl, total_trades; one row per mode',
      'kite_config — API key, API secret, daily access_token (rotated each Kite session)',
      'discovered_patterns — Mann-Whitney U p-values, sample size, effect size, has_edge flag',
      'pattern_backtest_runs — Sharpe, max drawdown, win rate, profit factor, trade count, date range',
      'pattern_backtest_trades — individual simulated trades per run for Pattern Finder drill-down',
      'TradeStatus enum in DB: OPEN, CLOSED, CANCELLED, PENDING, EXPIRED (uppercase)',
      'Portfolio mode stored as lowercase varchar: "paper" or "live" (NOT a DB enum)',
    ],
    tech:['PostgreSQL 15', 'SQLAlchemy 2 async', 'asyncpg', 'Alembic'],
    connects:[
      'FastAPI — all async reads and writes',
      'Celery — task results and discovered patterns stored here',
    ],
  },

  redis: {
    title:'Redis', color:'#ff6b6b',
    tagline:'4 circuit-breaker keys · Celery broker · Daily P&L state',
    overview:'In-memory store for real-time risk state and Celery task brokering. State resets daily at 09:15 IST. All risk checks are in-memory — zero DB latency on the trade hot path.',
    bullets:[
      'DAILY_PNL_KEY — running sum of realized P&L; compared against −2% limit on every trade',
      'DAILY_DEPLOYED_KEY — sum of entry_price × quantity for all open trades; capped at 3% portfolio heat',
      'TRADING_HALTED_KEY — "1"/"0"; checked before every auto-trade; set by loss limits or risk violations',
      'KILL_SWITCH_KEY — permanent halt "1" until manually cleared from Settings; highest priority check',
      'Celery broker — Redis queues all 14 Celery tasks and stores task results (result_backend = Redis)',
      'On startup — _sync_portfolio_heat_from_db() reloads DAILY_DEPLOYED_KEY from DB open trades',
      'Daily reset — reset_daily_pnl Celery task clears PNL + DEPLOYED at 09:15 IST then re-syncs from DB',
    ],
    tech:['Redis 7', 'redis-py async', 'Celery broker + result backend'],
    connects:[
      'Risk Gate — atomic flag reads on every trade decision',
      'Celery — message broker for all 14 tasks; result storage',
      'FastAPI — startup heat sync from DB open trades',
    ],
  },

  celery: {
    title:'Celery Workers', color:'#26c6b0',
    tagline:'14 scheduled tasks · Celery Beat · Redis broker',
    overview:'Distributed task queue running independently of FastAPI. Heavy jobs (scanning, backtesting, data sync) never block API responses. Celery Beat provides the cron-like schedule.',
    bullets:[
      'scan_signals (*/5 min) — runs all 8 patterns; deduplicates; auto-executes ≥82% confidence as paper trades',
      'mtm_update (*/2 min) — marks all open trades to market with Black-Scholes; applies trailing stop',
      'settle_expired (*/10 min) — closes trades whose options have passed their expiry date',
      'cleanup_stale_signals (*/15 min) — expires ACTIVE signals past valid_until; purges old EXPIRED records',
      'eod_close_intraday (15:20 IST Mon–Fri) — force-closes intraday trades before broker auto-square-off',
      'sync_market_data (16:15 IST Mon–Fri) — downloads NSE bhavcopy; bootstraps PCR + max-pain cache',
      'run_nightly_backtests (16:00 daily) — walk-forward backtests all discovered patterns for edge validation',
      'run_nightly_discovery (02:00 daily) — Mann-Whitney U statistical miner on bhav history for new edges',
      'reset_daily_pnl (09:15 daily) — clears Redis P&L + deployed capital; re-syncs heat from DB open trades',
      'reset_weekly_pnl (Monday 09:15) — clears weekly_pnl field in portfolio table',
      'generate_briefing (08:45 IST) — AI pre-market briefing: PCR, FII, India VIX, IV rank via Claude Sonnet 4.6',
    ],
    tech:['Celery 5', 'Celery Beat', 'Redis broker', 'Python 3.12'],
    connects:[
      'Redis — all task messages queued here; task results stored here',
      'PostgreSQL — patterns, backtest runs, briefing data written here',
      'FastAPI — triggered on demand via POST /api/v1/system/run-task/{name}',
      'NSE Market Data — bhavcopy downloaded and processed by sync_market_data at 16:15 IST',
    ],
  },

  nse: {
    title:'NSE Market Data', color:'#888780',
    tagline:'Bhavcopy CSVs · PCR cache · FII OI · Bhav replayer (tier-3 OHLCV)',
    overview:'Offline NSE data pipeline. Daily bhavcopy CSV files form the backbone of backtesting, PCR computation, and IV rank history. 184+ dates already cached and processed.',
    bullets:[
      'Bhavcopy CSV — NSE daily F&O settlement: OI, volume, settlement price per strike per expiry',
      'PCR cache — put/call ratio per underlying per date; 184+ dates cached in pcr_NIFTY.csv etc.',
      'Max pain — strike minimising total OI-weighted option writer loss; recomputed from each bhav file',
      'FII OI (CCIL) — participant-wise OI: FII, DII, proprietary; signals institutional positioning',
      'IV rank — historical IV from bhavcopy settlement prices; percentile rank vs 52-week range',
      'Bhav replayer — tier-3 OHLCV: replays bhavcopy files as synthetic OHLCV for walk-forward backtests',
      'Bootstrap — build_pcr_from_cached_bhav() processes all cached CSVs on first startup or on demand',
      'Sync task — sync_market_data Celery task downloads next bhavcopy at 16:15 IST after market close',
    ],
    tech:['pandas', 'NSE bhavcopy format', 'CSV pipeline', 'SciPy Mann-Whitney'],
    connects:[
      'Celery sync_market_data — bhavcopy downloaded and processed at 16:15 IST',
      'PostgreSQL — processed PCR / IV rank / max-pain data stored here',
      'Pattern Engine — bhav replayer provides tier-3 OHLCV for walk-forward backtests',
    ],
  },

  yahoo: {
    title:'Yahoo Finance', color:'#7ecaff',
    tagline:'India VIX (^INDIAVIX) · OHLCV tier-2 fallback · yfinance 0.2.40+ · Free tier',
    overview:'Free market data API with two distinct roles. (1) Sole free source of India VIX history via ^INDIAVIX — fetched daily and cached 18h. (2) Tier-2 OHLCV source when Kite Connect is not configured, enabling pattern discovery without a broker subscription. Data priority: Kite → Yahoo → NSE bhav replayer.',
    bullets:[
      'India VIX — ^INDIAVIX ticker downloaded from Yahoo Finance; cached in market_data/india_vix.csv with 18h TTL',
      'OHLCV tier-2 fallback — when Kite is not configured, yfinance provides historical candle data for backtesting',
      'NSE ticker mapping — NIFTY→^NSEI, BANKNIFTY→^NSEBANK, FINNIFTY→NIFTY_FIN_SERVICE.NS, stocks→SYM.NS',
      'Interval limits — 60 days of 15m candles, 730 days of 1h candles, 1825 days of daily OHLCV',
      'OI / IV gap — Yahoo Finance does NOT carry open interest or option IV; NSE bhavcopy fills those gaps',
      'Source tag — backtest run records are tagged source="yahoo" vs "kite" vs "synthetic" for traceability',
      'Multi-level column flattening — yfinance sometimes returns multi-level DataFrame columns; code handles this',
      'Lazy import — yfinance is imported only when Kite is unavailable; no overhead when Kite is connected',
    ],
    tech:['yfinance 0.2.40+', 'pandas', 'Python', 'NSE ticker map'],
    connects:[
      'FastAPI Backend — India VIX fetched via fetch_india_vix(), cached 18h in market_data/india_vix.csv',
      'Pattern Engine — OHLCV data via fetch_yfinance() called from get_historical_data() as tier-2 source',
      'Celery — sync_market_data task also triggers VIX refresh alongside bhavcopy download',
    ],
  },
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function Architecture() {
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [hovered, setHovered] = useState<NodeId | null>(null)
  const detail = selected ? DETAILS[selected] : null

  return (
    <div style={{ display:'flex', height:'100%', background:'var(--bg)', overflow:'hidden' }}>

      {/* ── Diagram pane ─────────────────────────────────────────────────────── */}
      <div style={{ flex:1, overflow:'auto', padding:'14px 10px 14px 14px', minWidth:0 }}>

        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <span style={{ fontSize:13, fontWeight:700, color:'var(--txt)' }}>AlphaFO — System Architecture</span>
          <span style={{ fontSize:11, color:'var(--txt3)' }}>· click any component for details</span>
          {selected && (
            <button onClick={() => setSelected(null)} className="tv-btn tv-btn-ghost"
              style={{ marginLeft:'auto', fontSize:11, padding:'2px 10px' }}>✕ close</button>
          )}
        </div>

        <svg viewBox="0 0 660 530" width="100%"
          style={{ display:'block', maxHeight:'calc(100vh - 80px)' }}
          aria-label="AlphaFO system architecture">

          <defs>
            {/* Context-stroke arrow marker — inherits path colour automatically */}
            <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">
              <path d="M2,1.5 L8,5 L2,8.5" fill="none" stroke="context-stroke"
                strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
            </marker>

            {/* Glow filter for selected node ring */}
            <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>

            {/* Path defs for animateMotion particles */}
            {CONNS.map(c => <path key={`pd-${c.id}`} id={`p-${c.id}`} d={c.d} fill="none"/>)}
          </defs>

          <style>{`
            @keyframes ring-pulse {
              0%,100% { stroke-opacity:0.5; stroke-width:2; }
              50%      { stroke-opacity:1;   stroke-width:2.8; }
            }
            .sel-ring { animation: ring-pulse 1.4s ease-in-out infinite; }
            .arch-node { cursor: pointer; }
          `}</style>

          {/* ── Tier swimlane bands ───────────────────────────────────────────── */}
          {BANDS.map(b => (
            <g key={b.label}>
              <rect x="10" y={b.y} width="642" height={b.h} rx="6"
                fill={b.color} fillOpacity="0.04"
                stroke={b.color} strokeOpacity="0.10" strokeWidth="1"/>
              <text x="646" y={b.y + 13} textAnchor="start"
                fill={b.color} fillOpacity="0.38" fontSize="8.5" fontWeight="700"
                fontFamily="-apple-system,BlinkMacSystemFont,sans-serif"
                letterSpacing="0.07em">{b.label}</text>
            </g>
          ))}

          {/* ── Connections ───────────────────────────────────────────────────── */}
          {CONNS.map(c => (
            <g key={c.id}>
              {/* Dashed track */}
              <path d={c.d} fill="none" stroke={c.color}
                strokeWidth="1.2" strokeOpacity="0.15" strokeDasharray="5 4"/>
              {/* Arrow line */}
              <path d={c.d} fill="none" stroke={c.color}
                strokeWidth="1.2" strokeOpacity="0.28" markerEnd="url(#arr)"/>

              {/* 3 staggered particles — grow-in, travel, shrink-out */}
              {[0, 0.34, 0.67].map((off, i) => (
                <circle key={i} r={c.r ?? 3.5} fill={c.color}>
                  <animateMotion dur={`${c.dur}s`} repeatCount="indefinite"
                    begin={`${off * c.dur}s`} calcMode="linear">
                    <mpath href={`#p-${c.id}`}/>
                  </animateMotion>
                  {/* Opacity: emerge → full → sustain → fade */}
                  <animate attributeName="opacity"
                    values="0;0;0.9;0.9;0" keyTimes="0;0.08;0.22;0.80;1"
                    dur={`${c.dur}s`} repeatCount="indefinite" begin={`${off * c.dur}s`}/>
                  {/* Radius: tiny → full → full → tiny */}
                  <animate attributeName="r"
                    values={`1;${(c.r ?? 3.5) * 0.6};${c.r ?? 3.5};${c.r ?? 3.5};1`}
                    keyTimes="0;0.08;0.22;0.80;1"
                    dur={`${c.dur}s`} repeatCount="indefinite" begin={`${off * c.dur}s`}/>
                </circle>
              ))}

              {/* Inline label with backing rect */}
              {c.label && c.labelX != null && c.labelY != null && (() => {
                const w = c.label.length * 6 + 12
                return (
                  <g>
                    <rect x={(c.labelX ?? 0) - w/2} y={(c.labelY ?? 0) - 11}
                      width={w} height={14} rx="3"
                      fill="var(--bg2)" fillOpacity="0.88"/>
                    <text x={c.labelX} y={c.labelY} textAnchor="middle"
                      fill={c.color} fillOpacity="0.72" fontSize="9" fontWeight="600"
                      fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">{c.label}</text>
                  </g>
                )
              })()}
            </g>
          ))}

          {/* ── Nodes ─────────────────────────────────────────────────────────── */}
          {(Object.entries(N) as [NodeId, NodeMeta][]).map(([id, n]) => {
            const isSel = selected === id
            const isHov = hovered === id
            const midY  = n.y + n.h / 2
            return (
              <g key={id} className="arch-node"
                onClick={() => setSelected(isSel ? null : id)}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}>

                {/* Pulsing glow ring when selected */}
                {isSel && (
                  <rect x={n.x-4} y={n.y-4} width={n.w+8} height={n.h+8}
                    rx="10" fill="none" stroke={n.color}
                    filter="url(#glow)" className="sel-ring"/>
                )}

                {/* Node body */}
                <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="6"
                  fill={n.color}
                  fillOpacity={isSel ? 0.24 : isHov ? 0.18 : 0.09}
                  stroke={n.color}
                  strokeWidth={isSel || isHov ? 1.8 : 0.9}
                  strokeOpacity={isSel || isHov ? 0.90 : 0.36}
                />

                {/* Primary label */}
                <text x={n.x + n.w/2} y={midY - 7}
                  textAnchor="middle" fill={n.color} fillOpacity="0.95"
                  fontSize="12" fontWeight="700"
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                  {n.label}
                </text>

                {/* Sub-label */}
                <text x={n.x + n.w/2} y={midY + 9}
                  textAnchor="middle" fill={n.color} fillOpacity="0.46"
                  fontSize={n.w < 180 ? 9 : 10}
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                  {n.sub}
                </text>

                {/* External badge */}
                {n.ext && (
                  <text x={n.x + n.w - 6} y={n.y + n.h - 5}
                    textAnchor="end" fill={n.color} fillOpacity="0.35"
                    fontSize="8" fontWeight="600"
                    fontFamily="-apple-system,BlinkMacSystemFont,sans-serif">
                    external
                  </text>
                )}
              </g>
            )
          })}

          {/* ── Horizontal tier dividers ──────────────────────────────────────── */}
          {[100, 204, 316, 430].map(y => (
            <line key={y} x1="18" y1={y} x2="642" y2={y}
              stroke="#2a2e39" strokeWidth="0.6" strokeDasharray="3 6"/>
          ))}
        </svg>
      </div>

      {/* ── Detail side panel ─────────────────────────────────────────────────── */}
      {detail && selected && (
        <div style={{
          width:352, flexShrink:0,
          borderLeft:'1px solid var(--border)',
          background:'var(--bg2)',
          overflow:'auto',
          padding:'16px 18px',
          display:'flex', flexDirection:'column', gap:16,
        }}>

          {/* Header */}
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:5 }}>
              <span style={{
                display:'inline-block', width:10, height:10,
                borderRadius:'50%', flexShrink:0, background:N[selected].color,
              }}/>
              <span style={{ fontWeight:800, fontSize:15, color:'var(--txt)' }}>{detail.title}</span>
              {N[selected].ext && (
                <span style={{
                  fontSize:9, fontWeight:700, padding:'1px 6px', borderRadius:3,
                  background:`${N[selected].color}1a`, color:N[selected].color,
                  border:`1px solid ${N[selected].color}44`, letterSpacing:'0.05em',
                }}>EXTERNAL</span>
              )}
            </div>
            <div style={{ fontSize:11, color:N[selected].color, opacity:0.8, fontWeight:600, marginBottom:10 }}>
              {detail.tagline}
            </div>
            <div style={{ fontSize:12, color:'var(--txt2)', lineHeight:1.68 }}>
              {detail.overview}
            </div>
          </div>

          {/* Responsibilities */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:8 }}>
              Responsibilities
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:5 }}>
              {detail.bullets.map((b, i) => (
                <div key={i} style={{ display:'flex', gap:7, alignItems:'flex-start' }}>
                  <span style={{ color:N[selected].color, fontSize:12, marginTop:1, flexShrink:0 }}>›</span>
                  <span style={{ fontSize:11, color:'var(--txt2)', lineHeight:1.58 }}>{b}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Connections */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:8 }}>
              Connects to
            </div>
            {detail.connects.map((c, i) => (
              <div key={i} style={{
                fontSize:11, color:'var(--txt2)', padding:'5px 0',
                borderBottom:'1px solid var(--border)', lineHeight:1.55,
              }}>{c}</div>
            ))}
          </div>

          {/* Technology */}
          <div>
            <div style={{ fontSize:9.5, fontWeight:800, color:'var(--txt3)',
              textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:8 }}>
              Technology
            </div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:5 }}>
              {detail.tech.map(t => (
                <span key={t} style={{
                  fontSize:10, padding:'2px 8px', borderRadius:3, fontWeight:600,
                  background:`${N[selected].color}18`,
                  color:N[selected].color,
                  border:`1px solid ${N[selected].color}40`,
                }}>{t}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
