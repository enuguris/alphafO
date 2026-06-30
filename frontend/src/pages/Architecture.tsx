import { useState } from 'react'

type NodeId = 'frontend' | 'backend' | 'patterns' | 'risk' | 'options' | 'postgres' | 'redis' | 'celery' | 'kite' | 'nse'

interface Detail {
  title: string
  color: string
  tagline: string
  overview: string
  bullets: string[]
  tech: string[]
  connects: string[]
}

const DETAILS: Record<NodeId, Detail> = {
  frontend: {
    title: 'React Frontend', color: '#4488ff',
    tagline: '10 pages · Zustand · React Query · WebSocket',
    overview: 'Single-page application built with React 18 + Vite. Handles all user interaction from signal browsing to live trade management, with five switchable UI themes persisted in localStorage.',
    bullets: [
      'Dashboard — pre-market briefing (PCR, FII, IV rank), live signal feed, sector scanner',
      'Options — chain analysis, IV rank bar, max-pain overlay, regime badge',
      'Positions — open paper trades with real-time MTM, trailing-stop indicator, close button',
      'Pattern Finder — run walk-forward backtests, discover statistical edges via Mann-Whitney U',
      'Report — Sharpe ratio, max drawdown, win rate, equity curve, pattern breakdown',
      'Paper Trading — virtual trade history, cumulative P&L chart',
      'Backtest — per-pattern walk-forward with equity curve and trade list',
      'Settings — Kite credentials, trading mode, Anthropic API key, 5-theme picker',
      'System Health — component health grid, 14 Celery tasks, manual trigger buttons',
      'Architecture — this animated diagram',
      'Zustand stores: themeStore (dark/midnight/high-contrast/solarized/light), modeStore (paper/live/testing)',
      'React Query: smart cache with 30s stale-time for portfolio, signals, dashboard',
      'All API calls centralised in api/client.ts via axios targeting /api/v1/*',
    ],
    tech: ['React 18', 'Vite 5', 'TypeScript', 'Zustand', 'React Query', 'Recharts', 'Axios'],
    connects: ['FastAPI Backend — REST requests + WebSocket subscription'],
  },
  backend: {
    title: 'FastAPI Backend', color: '#26a69a',
    tagline: 'Python 3.12 · async SQLAlchemy · Black-Scholes · WebSocket hub',
    overview: 'Central async API server. Every trade, signal, and analytics request flows through here. Also acts as the WebSocket broadcast hub so all open browser tabs receive live signal and price updates simultaneously.',
    bullets: [
      '/api/v1/signals — list, create, expire; TESTING_FOCUS filter; nan/inf sanitisation',
      '/api/v1/trades — open/close paper trades, MTM refresh, auto-execution gate at ≥82% confidence',
      '/api/v1/portfolio — capital tracking, heat sync, cumulative P&L series',
      '/api/v1/backtest — walk-forward engine API with IV-rank gate',
      '/api/v1/options — chain, IV rank, max pain, event calendar, regime overlay',
      '/api/v1/dashboard — pre-market briefing + report (Sharpe, drawdown, win rate)',
      '/api/v1/pattern-finder — discover edges, run backtests, toggle/delete discovered patterns',
      '/api/v1/settings — Kite credentials, Anthropic key, Kite connection test',
      '/api/v1/system — health checks, Celery schedule, manual task trigger',
      '/api/v1/chat — routes messages to Claude Sonnet 4.6 via Anthropic SDK',
      '/ws/signals — broadcasts new signals to all connected clients in real time',
      '/ws/prices — rebroadcasts Kite LTP ticks to browser for live price display',
      'Black-Scholes engine computes synthetic option premiums when Kite is offline',
      'Startup lifespan: re-syncs Redis deployed-capital from DB open trades to survive restarts',
    ],
    tech: ['FastAPI', 'Python 3.12', 'SQLAlchemy 2 async', 'Alembic', 'Pydantic v2', 'Anthropic SDK', 'asyncpg'],
    connects: [
      'Frontend ← REST responses + WebSocket push',
      'PostgreSQL — async ORM reads/writes via SQLAlchemy',
      'Redis — circuit-breaker flag checks before every trade',
      'Celery — task dispatch via Redis broker',
      'Kite Connect — live prices and order placement',
    ],
  },
  patterns: {
    title: 'Pattern Engine', color: '#7b61ff',
    tagline: '8 patterns · IV rank gate · Composite confidence scorer',
    overview: 'The alpha-generation core. Eight independently pluggable pattern modules each implement a distinct market mechanism. The scanner runs all of them every 5 minutes and merges results through the composite confidence scorer before writing signals to DB.',
    bullets: [
      'Gap Fill — pre-market gap ≥0.5% with OI > 20L; 70% of gaps fill within session',
      'PCR Divergence — PCR < 0.7 (bearish extreme) or > 1.3 (bullish) signals institutional positioning',
      'Mean Reversion — Bollinger Band squeeze break confirmed on both 15m and 1h timeframes',
      'OI Buildup — open interest increasing alongside price confirmation = smart money accumulation',
      'VWAP + OI — price rejects VWAP level on high OI buildup = institutional defence',
      'IV Crush — sell options when IV rank > 75% ahead of scheduled events (results, RBI policy)',
      'Max Pain Gravity — expiry week: price gravitates to the strike where writers lose least',
      'Expiry Week Theta — harvest rapid theta decay in the final 48 hours of weekly expiry',
      'IV rank gate — each pattern requires IV rank above a per-pattern threshold before firing',
      'Composite scorer — multi-factor 0–1 confidence with weighted inputs (PCR, IV rank, OI trend)',
      'Auto-trade gate — ≥0.82 confidence (real Kite) or ≥0.72 (synthetic) triggers auto paper trade',
      'Signal dedup — (underlying, pattern, direction, option_type) within 1-hour window prevents floods',
      'Age gate — signals > 2h old are skipped at auto-execution time to avoid stale strikes',
    ],
    tech: ['Python', 'NumPy', 'SciPy', 'Black-Scholes', 'NSE bhavcopy data'],
    connects: ['FastAPI — scanner orchestrated by scan_signals Celery task', 'PostgreSQL — signals written to DB'],
  },
  risk: {
    title: 'Risk Gate', color: '#ef5350',
    tagline: 'Redis circuit breakers · Daily P&L · Portfolio heat · Kill switch',
    overview: 'Every trade order passes through the risk gate before execution. Four independent circuit breakers operate in Redis so they survive API restarts and are checked atomically without DB round-trips.',
    bullets: [
      'Daily P&L limit — if realized P&L drops below −2% of capital, TRADING_HALTED is set to "1" instantly',
      'Portfolio heat — total deployed capital across open positions capped at 3% of portfolio value',
      'Kill switch — KILL_SWITCH_KEY is a permanent halt; only cleared manually from the Settings page',
      'Trailing stop — at +30% gain the stop_loss is raised to entry + 50% of profit; locks in gains automatically',
      'Position sizing — 1% capital at risk per trade, sized by (entry − stop) / lot_size',
      'Startup re-sync — on container restart, open trades in DB are summed and written back to Redis',
      'Weekly loss ceiling — 3% weekly drawdown triggers the same TRADING_HALTED flag via Celery check',
    ],
    tech: ['Redis 7', 'redis-py async', 'Python'],
    connects: ['Redis — atomic read/write of all four circuit-breaker keys', 'FastAPI — checked before every auto-trade'],
  },
  options: {
    title: 'Options Engine', color: '#4fa3e0',
    tagline: 'Chain analysis · IV rank · Max pain · Regime classifier',
    overview: 'Options analytics layer. Provides IV rank, max-pain computation, expiry calendar, and regime classification — all of which feed into pattern confidence scores and the pre-market briefing.',
    bullets: [
      'Options chain — per-strike calls + puts: OI, IV, LTP, bid/ask pulled from Kite Connect API',
      'IV rank — current IV as a percentile of the 52-week IV range; key weight in composite confidence',
      'Max pain — strike at which total OI-weighted option writer loss is minimised; computed from bhavcopy OI',
      'Expiry calendar — weekly Thursday + monthly last-Thursday expiry for both NIFTY and BANKNIFTY',
      'Event calendar — upcoming results, RBI policy, index rebalancing flagged for IV Crush pattern',
      'Strike selector — ATM ± N strikes chosen based on signal direction, DTE, and lot size',
      'Regime — bullish / bearish / neutral classification using PCR + price vs VWAP + OI trend direction',
    ],
    tech: ['Python', 'Black-Scholes', 'Kite Connect API', 'NSE bhavcopy'],
    connects: ['Kite Connect — live chain data', 'FastAPI — analytics results served to Dashboard and Options pages'],
  },
  postgres: {
    title: 'PostgreSQL', color: '#9b8fff',
    tagline: '7 tables · SQLAlchemy async · Alembic migrations',
    overview: 'Primary relational store for all persistent state. Uses SQLAlchemy 2.0 async ORM with asyncpg driver. Alembic manages incremental schema migrations so the DB evolves without data loss.',
    bullets: [
      'signals — pattern signals: underlying, strike, expiry, premium, IV, DTE, direction, confidence, status (ACTIVE / EXPIRED / EXECUTED)',
      'trades — paper + live trades: entry/exit prices, MTM, stop_loss (updated by trailing stop), brokerage charges, realized P&L, notes',
      'portfolio — capital, peak_capital, max_drawdown_pct, weekly_pnl, total_trades; one row per mode (paper/live)',
      'kite_config — API key, API secret, daily access_token (rotated each Kite session)',
      'discovered_patterns — statistically-mined pattern edges with Mann-Whitney U p-values, sample sizes, has_edge flag',
      'pattern_backtest_runs — walk-forward results per pattern: Sharpe ratio, max drawdown, win rate, profit factor, date range',
      'pattern_backtest_trades — individual trades within each backtest run for drill-down analysis in Pattern Finder',
      'tradestatus enum in DB: OPEN, CLOSED, CANCELLED, PENDING, EXPIRED',
    ],
    tech: ['PostgreSQL 15', 'SQLAlchemy 2.0 async', 'asyncpg', 'Alembic'],
    connects: ['FastAPI — all async reads/writes', 'Celery — task results and discovered patterns written here'],
  },
  redis: {
    title: 'Redis', color: '#ff6b6b',
    tagline: 'Circuit breakers · Celery broker · Daily state',
    overview: 'In-memory store for real-time risk state and Celery task brokering. State resets daily at 09:15 IST. Because checks are in-memory, the risk gate adds zero DB latency to the trade path.',
    bullets: [
      'DAILY_PNL_KEY — running sum of realized P&L for the day; triggers TRADING_HALTED at −2% of capital',
      'DAILY_DEPLOYED_KEY — sum of entry_price × quantity for all open trades; capped at 3% heat limit',
      'TRADING_HALTED_KEY — boolean "1"/"0"; checked before every auto-trade; set by loss limits or kill switch',
      'KILL_SWITCH_KEY — permanent halt "1" until manually cleared from Settings; highest priority flag',
      'Celery broker — Redis queues all 14 Celery tasks and stores results (result_backend = Redis)',
      'On startup — _sync_portfolio_heat_from_db() reloads DAILY_DEPLOYED_KEY from DB open trades',
      'Daily reset — reset_daily_pnl Celery task clears PNL + DEPLOYED at 09:15 IST and re-syncs from DB',
    ],
    tech: ['Redis 7', 'redis-py async', 'Celery broker + result backend'],
    connects: ['Risk Gate — atomic flag reads/writes', 'Celery — message broker for all 14 tasks', 'FastAPI — startup heat sync'],
  },
  celery: {
    title: 'Celery Workers', color: '#26c6b0',
    tagline: '14 scheduled tasks · Redis broker · Celery Beat',
    overview: 'Distributed task queue with Celery Beat scheduler. Workers run independently of the FastAPI process so heavy tasks (scanning, backtesting, data download) never block API responses.',
    bullets: [
      'scan_signals (*/5 min) — runs all 8 patterns; deduplicates; auto-executes ≥82% confidence as paper trades',
      'mtm_update (*/2 min) — marks all open trades to market with Black-Scholes pricing; applies trailing stop',
      'settle_expired (*/10 min) — closes trades whose options have passed expiry date',
      'cleanup_stale_signals (*/15 min) — expires ACTIVE signals past valid_until; purges old EXPIRED records',
      'eod_close_intraday (15:20 IST Mon–Fri) — force-closes all intraday trades before broker auto-square-off',
      'sync_market_data (16:15 IST Mon–Fri) — downloads NSE bhavcopy; bootstraps PCR + max-pain cache',
      'run_nightly_backtests (16:00 daily) — walk-forward backtests all discovered patterns for edge validation',
      'run_nightly_discovery (02:00 daily) — Mann-Whitney U statistical miner on bhav history for new edges',
      'reset_daily_pnl (09:15 daily) — clears Redis P&L + deployed; resyncs heat from DB open trades',
      'reset_weekly_pnl (Monday 09:15) — clears weekly_pnl field in portfolio table',
      'generate_briefing (08:45 IST) — AI pre-market briefing: PCR, FII, IV rank, expiry events via Claude',
    ],
    tech: ['Celery 5', 'Celery Beat', 'Redis broker', 'Python 3.12'],
    connects: ['Redis — all task messages queued here; results stored here', 'PostgreSQL — task results written to DB', 'FastAPI — triggered on demand via POST /api/v1/system/run-task/{name}'],
  },
  kite: {
    title: 'Kite Connect', color: '#ff9800',
    tagline: 'Zerodha broker API · Live WebSocket · OAuth daily token',
    overview: 'Zerodha broker API for live market data and order execution. When disconnected, the system automatically falls back to Black-Scholes synthetic pricing so paper trading continues uninterrupted.',
    bullets: [
      'KiteTicker WebSocket — real-time LTP feed for NIFTY + BANKNIFTY futures and all tracked strikes',
      'Historical OHLCV — 15m / 1h / 4h / daily candle data for pattern detection across timeframes',
      'Instrument master — full F&O universe: lot sizes, expiry dates, strike step sizes for all underlyings',
      'Order placement — market + limit orders for live trading; gated behind paper-trading performance gate',
      'OAuth flow — daily access_token obtained by exchanging request_token from the Kite login redirect URL',
      'Synthetic fallback — when disconnected, Black-Scholes uses last-known IV to price options',
      'is_synthetic flag — signals have explanation starting with "[" for synthetic vs "[Weekly/Monthly …]" for real',
      'Connection test — /api/v1/settings/test-connection runs 5 sub-checks and returns per-check results',
    ],
    tech: ['kiteconnect-py', 'WebSocket', 'OAuth 2.0', 'REST API'],
    connects: ['FastAPI — all REST calls go through here', 'Pattern Engine — OHLCV data for detection', 'Options Engine — live chain data'],
  },
  nse: {
    title: 'NSE Market Data', color: '#888780',
    tagline: 'Bhavcopy CSVs · PCR cache · FII OI · Bhav replayer',
    overview: 'Offline NSE data pipeline. Daily bhavcopy CSV files form the backbone of backtesting, PCR computation, and IV rank history. 184+ dates are already cached and processed.',
    bullets: [
      'Bhavcopy CSV — NSE daily F&O settlement data: OI, volume, settlement price per strike per expiry',
      'PCR cache — put/call ratio computed per underlying per date; 184+ dates cached in pcr_NIFTY.csv etc.',
      'Max pain — strike minimising total OI-weighted option writer loss; recomputed from each bhav file',
      'FII OI (CCIL) — participant-wise open interest: FII, DII, proprietary; signals institutional positioning',
      'IV rank — historical IV per underlying stored from bhavcopy settlement prices; percentile vs 52-week range',
      'Bhav replayer — walk-forward backtest engine replays bhavcopy files as synthetic OHLCV for pattern testing',
      'Bootstrap — build_pcr_from_cached_bhav() processes all cached CSVs on first startup or on demand',
      'Sync task — sync_market_data Celery task downloads next bhavcopy at 16:15 IST after market close',
    ],
    tech: ['pandas', 'NSE bhavcopy format', 'CSV pipeline', 'SciPy (Mann-Whitney)'],
    connects: ['Celery sync_market_data — downloads at 16:15 IST', 'PostgreSQL — processed data stored here', 'Pattern Engine — bhav replayer feeds walk-forward backtests'],
  },
}

const NODE_META: Record<NodeId, { x: number; y: number; w: number; h: number; label: string; sub: string; color: string }> = {
  frontend: { x: 190, y: 28,  w: 280, h: 52, label: 'React frontend',    sub: '10 pages · Zustand · WS',       color: '#4488ff' },
  backend:  { x: 128, y: 140, w: 304, h: 52, label: 'FastAPI backend',   sub: 'Python 3.12 · async · WS hub',   color: '#26a69a' },
  kite:     { x: 488, y: 140, w: 152, h: 52, label: 'Kite Connect',      sub: 'Zerodha · live prices',          color: '#ff9800' },
  patterns: { x: 28,  y: 252, w: 165, h: 78, label: 'Pattern engine',    sub: '8 patterns · IV gate',           color: '#7b61ff' },
  risk:     { x: 223, y: 252, w: 155, h: 78, label: 'Risk gate',         sub: 'circuit breakers · Redis',       color: '#ef5350' },
  options:  { x: 408, y: 252, w: 165, h: 78, label: 'Options engine',    sub: 'chain · IV rank · max pain',     color: '#4fa3e0' },
  postgres: { x: 28,  y: 380, w: 165, h: 78, label: 'PostgreSQL',        sub: '7 tables · Alembic',             color: '#9b8fff' },
  redis:    { x: 223, y: 380, w: 155, h: 78, label: 'Redis',             sub: 'circuit breakers · broker',      color: '#ff6b6b' },
  celery:   { x: 408, y: 380, w: 192, h: 78, label: 'Celery workers',    sub: '14 tasks · Beat scheduler',      color: '#26c6b0' },
  nse:      { x: 128, y: 502, w: 304, h: 52, label: 'NSE market data',   sub: 'bhavcopy · PCR · FII · bhav replayer', color: '#888780' },
}

interface Conn { id: string; d: string; color: string; dur: number; label?: string; reverse?: boolean }

const CONNECTIONS: Conn[] = [
  { id: 'fe-be',  d: 'M330,80 L280,140',           color: '#4488ff', dur: 1.8, label: 'REST + WS' },
  { id: 'be-fe',  d: 'M284,140 L334,80',           color: '#26a69a', dur: 2.2, label: '' },
  { id: 'be-kt',  d: 'M432,166 L488,166',           color: '#ff9800', dur: 1.5, label: 'live prices' },
  { id: 'kt-be',  d: 'M488,172 L432,172',           color: '#26a69a', dur: 1.9, label: '' },
  { id: 'be-pa',  d: 'M190,192 L111,252',           color: '#7b61ff', dur: 2.0 },
  { id: 'be-ri',  d: 'M280,192 L301,252',           color: '#ef5350', dur: 1.6 },
  { id: 'be-op',  d: 'M366,192 L491,252',           color: '#4fa3e0', dur: 1.8 },
  { id: 'pa-pg',  d: 'M111,330 L111,380',           color: '#9b8fff', dur: 1.4 },
  { id: 'ri-rd',  d: 'M301,330 L301,380',           color: '#ff6b6b', dur: 1.2 },
  { id: 'op-ce',  d: 'M491,330 L504,380',           color: '#26c6b0', dur: 1.6 },
  { id: 'ce-be',  d: 'M600,419 Q648,280 432,172',   color: '#26c6b0', dur: 2.6, label: 'task results' },
  { id: 'nse-pg', d: 'M200,502 Q148,462 111,458',   color: '#888780', dur: 2.2 },
  { id: 'nse-ce', d: 'M360,502 Q430,462 504,458',   color: '#888780', dur: 2.0 },
  { id: 'rd-be',  d: 'M301,380 Q220,300 215,192',   color: '#ef5350', dur: 2.0, label: 'gate check' },
]

function cx(id: NodeId) { const n = NODE_META[id]; return n.x + n.w / 2 }
function cy(id: NodeId) { const n = NODE_META[id]; return n.y + n.h / 2 }

export default function Architecture() {
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [hovered, setHovered] = useState<NodeId | null>(null)
  const detail = selected ? DETAILS[selected] : null

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--bg)', overflow: 'hidden' }}>

      {/* ── Diagram pane ── */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 12px 16px 16px', minWidth: 0 }}>

        <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--txt)' }}>AlphaFO — System Architecture</span>
          <span style={{ fontSize: 11, color: 'var(--txt3)' }}>Click any component to explore</span>
          {selected && (
            <button
              onClick={() => setSelected(null)}
              className="tv-btn tv-btn-ghost"
              style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 10px' }}
            >✕ Close panel</button>
          )}
        </div>

        <svg
          viewBox="0 0 660 574"
          width="100%"
          style={{ display: 'block', maxHeight: 'calc(100vh - 80px)' }}
          role="img"
          aria-label="AlphaFO system architecture diagram"
        >
          <defs>
            {/* ── Arrow marker ── */}
            <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </marker>

            {/* ── Glow filter for selected node ── */}
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>

            {/* ── Path defs for animateMotion ── */}
            {CONNECTIONS.map(c => (
              <path key={`p-${c.id}`} id={`p-${c.id}`} d={c.d} fill="none"/>
            ))}
          </defs>

          {/* ── SVG animation styles ── */}
          <style>{`
            .arch-node { cursor: pointer; transition: opacity 0.15s; }
            .arch-node:hover rect { filter: brightness(1.2); }
            .arch-node-bg { rx: 6; }
            @keyframes arch-pulse {
              0%,100% { stroke-opacity: 0.6; }
              50%      { stroke-opacity: 1; }
            }
            .arch-selected-ring { animation: arch-pulse 1.4s ease-in-out infinite; }
          `}</style>

          {/* ── Connection lines ── */}
          {CONNECTIONS.map(c => (
            <g key={c.id}>
              {/* Static dashed track */}
              <path d={c.d} fill="none" stroke={c.color} strokeWidth="1.2" strokeOpacity="0.18" strokeDasharray="5 4"/>
              {/* Solid arrow */}
              <path d={c.d} fill="none" stroke={c.color} strokeWidth="1.2" strokeOpacity="0.35" markerEnd="url(#arr)"/>

              {/* Animated flow particles (3 staggered) */}
              {[0, 0.33, 0.66].map((offset, i) => (
                <circle key={i} r="3.5" fill={c.color} opacity="0.85">
                  <animateMotion dur={`${c.dur}s`} repeatCount="indefinite" begin={`${offset * c.dur}s`} calcMode="linear">
                    <mpath href={`#p-${c.id}`}/>
                  </animateMotion>
                </circle>
              ))}

              {/* Connection label */}
              {c.label && (() => {
                const mid = c.d.includes('Q')
                  ? { x: parseFloat(c.d.split('Q')[1].split(' ')[0]) - 10, y: parseFloat(c.d.split('Q')[1].split(' ')[1]) }
                  : { x: (parseFloat(c.d.split('M')[1]) + parseFloat(c.d.split('L')[1])) / 2, y: (parseFloat(c.d.split('M')[1].split(',')[1]) + parseFloat(c.d.split('L')[1].split(',')[1])) / 2 - 6 }
                return (
                  <text x={mid.x} y={mid.y} textAnchor="middle" fill={c.color} opacity="0.65"
                    fontSize="9" fontFamily="-apple-system,sans-serif">{c.label}</text>
                )
              })()}
            </g>
          ))}

          {/* ── Nodes ── */}
          {(Object.entries(NODE_META) as [NodeId, typeof NODE_META[NodeId]][]).map(([id, n]) => {
            const isSel = selected === id
            const isHov = hovered === id
            return (
              <g
                key={id}
                className="arch-node"
                onClick={() => setSelected(isSel ? null : id)}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}
              >
                {/* Selected ring */}
                {isSel && (
                  <rect
                    x={n.x - 3} y={n.y - 3}
                    width={n.w + 6} height={n.h + 6}
                    rx="9" fill="none"
                    stroke={n.color} strokeWidth="2.5"
                    className="arch-selected-ring"
                  />
                )}
                {/* Node body */}
                <rect
                  x={n.x} y={n.y} width={n.w} height={n.h} rx="6"
                  fill={n.color}
                  fillOpacity={isHov || isSel ? 0.28 : 0.14}
                  stroke={n.color}
                  strokeWidth={isHov || isSel ? 1.5 : 0.8}
                  strokeOpacity={isHov || isSel ? 0.9 : 0.4}
                />
                {/* Label */}
                <text
                  x={n.x + n.w / 2} y={n.y + (n.h > 60 ? 24 : 21)}
                  textAnchor="middle"
                  fill={n.color} fillOpacity={0.95}
                  fontSize="12" fontWeight="600"
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif"
                >{n.label}</text>
                <text
                  x={n.x + n.w / 2} y={n.y + (n.h > 60 ? 40 : 37)}
                  textAnchor="middle"
                  fill={n.color} fillOpacity="0.55"
                  fontSize="10"
                  fontFamily="-apple-system,BlinkMacSystemFont,sans-serif"
                >{n.sub}</text>
              </g>
            )
          })}

          {/* ── Tier labels ── */}
          {[
            { y: 54,  label: 'presentation' },
            { y: 166, label: 'application' },
            { y: 291, label: 'domain' },
            { y: 419, label: 'infrastructure' },
            { y: 528, label: 'data sources' },
          ].map(({ y, label }) => (
            <text key={label} x="640" y={y} textAnchor="end"
              fill="#636670" fontSize="9" fontFamily="-apple-system,sans-serif"
              fontStyle="italic">{label}</text>
          ))}

          {/* ── Horizontal tier dividers ── */}
          {[112, 228, 356, 474].map(y => (
            <line key={y} x1="20" y1={y} x2="640" y2={y}
              stroke="#2a2e39" strokeWidth="0.5" strokeDasharray="3 5"/>
          ))}
        </svg>
      </div>

      {/* ── Detail panel ── */}
      {detail && (
        <div style={{
          width: 348, flexShrink: 0,
          borderLeft: '1px solid var(--border)',
          background: 'var(--bg2)',
          overflow: 'auto',
          padding: '16px 18px',
          display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          {/* Header */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                background: NODE_META[selected!].color, flexShrink: 0,
              }}/>
              <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--txt)' }}>{detail.title}</span>
            </div>
            <div style={{ fontSize: 11, color: NODE_META[selected!].color, opacity: 0.85, fontWeight: 500, marginBottom: 8 }}>
              {detail.tagline}
            </div>
            <div style={{ fontSize: 12, color: 'var(--txt2)', lineHeight: 1.65 }}>{detail.overview}</div>
          </div>

          {/* Responsibilities */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
              Responsibilities
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {detail.bullets.map((b, i) => (
                <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start' }}>
                  <span style={{ color: NODE_META[selected!].color, fontSize: 11, marginTop: 1, flexShrink: 0 }}>›</span>
                  <span style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.55 }}>{b}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Connects to */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
              Connects to
            </div>
            {detail.connects.map((c, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--txt2)', padding: '4px 0', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
                {c}
              </div>
            ))}
          </div>

          {/* Tech stack */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
              Technology
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {detail.tech.map(t => (
                <span key={t} style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 3, fontWeight: 500,
                  background: `${NODE_META[selected!].color}1a`,
                  color: NODE_META[selected!].color,
                  border: `1px solid ${NODE_META[selected!].color}44`,
                }}>{t}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
