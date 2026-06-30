/**
 * Interactive architecture diagram — click any node to drill into its internals.
 * Level 0: System overview with live data-flow animations.
 * Level 1: Internals of the clicked subsystem.
 * Level 2: Pattern / task / table details.
 */
import { useState, useEffect, useRef } from 'react'

/* ── Data ──────────────────────────────────────────────────────────── */
type SubNode = {
  id: string
  label: string
  icon: string
  tag?: string
  desc: string
  color: string
  drillable?: boolean
  children?: SubNode[]
}

type TopNode = {
  id: string
  label: string
  icon: string
  color: string
  accent: string
  desc: string
  row: number
  col: number
  children: SubNode[]
  connections: string[]
}

const NODES: TopNode[] = [
  {
    id: 'frontend',
    label: 'React Frontend',
    icon: '⚛',
    color: '#0d2137',
    accent: '#58a6ff',
    desc: 'Vite + React 18 SPA — 9 pages, Zustand stores, real-time WebSocket',
    row: 0, col: 0,
    connections: ['backend'],
    children: [
      { id: 'dashboard',  label: 'Dashboard',      icon: '📊', tag: '/', desc: 'Pre-market briefing, live signals, scanner controls, sector view', color: '#1f3a5f' },
      { id: 'options',    label: 'Options',         icon: '📈', tag: '/options', desc: 'Chain analysis, IV rank, max-pain, regime overlay', color: '#1f3a5f' },
      { id: 'positions',  label: 'Positions',       icon: '💼', tag: '/positions', desc: 'Live paper trades with MTM, trailing stop indicator', color: '#1f3a5f' },
      { id: 'patterns',   label: 'Pattern Finder',  icon: '🔍', tag: '/pattern-finder', desc: 'Walk-forward backtest, statistical discovery (Mann-Whitney)', color: '#1f3a5f' },
      { id: 'report',     label: 'Report',          icon: '📋', tag: '/report', desc: 'Sharpe ratio, max drawdown, win rate, equity curve', color: '#1f3a5f' },
      { id: 'paper',      label: 'Paper Trading',   icon: '📝', tag: '/paper', desc: 'Virtual trades, cumulative P&L chart, history log', color: '#1f3a5f' },
      { id: 'backtest',   label: 'Backtest',        icon: '⏪', tag: '/backtest', desc: 'Per-pattern backtests with equity curve + trade list', color: '#1f3a5f' },
      { id: 'settings',   label: 'Settings',        icon: '⚙', tag: '/settings', desc: 'Kite credentials, trading mode, Anthropic key, theme picker', color: '#1f3a5f' },
      { id: 'system',     label: 'System Health',   icon: '🖥', tag: '/system', desc: 'Component health, 14 Celery tasks, manual triggers', color: '#1f3a5f' },
    ],
  },
  {
    id: 'backend',
    label: 'FastAPI Backend',
    icon: '⚡',
    color: '#0d2a1a',
    accent: '#3fb950',
    desc: 'Python 3.12 async — SQLAlchemy, Alembic, WebSocket hub, Black-Scholes engine',
    row: 0, col: 1,
    connections: ['postgres', 'redis', 'celery', 'kite'],
    children: [
      { id: 'api-signals',    label: 'Signals API',       icon: '📡', tag: '/api/v1/signals', desc: 'CRUD, dedup, TESTING_FOCUS filter, nan-safe serialization', color: '#0d2a1a' },
      { id: 'api-trades',     label: 'Trades API',        icon: '💹', tag: '/api/v1/trades', desc: 'Open/close trades, MTM refresh, auto paper-trade execution', color: '#0d2a1a' },
      { id: 'api-portfolio',  label: 'Portfolio API',     icon: '💰', tag: '/api/v1/portfolio', desc: 'Capital tracking, heat sync, P&L curve', color: '#0d2a1a' },
      { id: 'api-options',    label: 'Options API',       icon: '🔢', tag: '/api/v1/options', desc: 'Chain, IV rank, max pain, event calendar, regime', color: '#0d2a1a' },
      { id: 'api-backtest',   label: 'Backtest API',      icon: '📉', tag: '/api/v1/backtest', desc: 'Walk-forward engine, IV rank gate, bhav CSV replayer', color: '#0d2a1a' },
      { id: 'api-dashboard',  label: 'Dashboard API',     icon: '🗂', tag: '/api/v1/dashboard', desc: 'Pre-market briefing, Sharpe, drawdown, discovered patterns', color: '#0d2a1a' },
      { id: 'api-patterns',   label: 'Pattern Finder API',icon: '🧬', tag: '/api/v1/pattern-finder', desc: 'Discover, backtest, toggle, delete discovered patterns', color: '#0d2a1a' },
      { id: 'api-system',     label: 'System API',        icon: '🔧', tag: '/api/v1/system', desc: 'Health checks, Celery schedule, manual task triggers', color: '#0d2a1a' },
      { id: 'api-chat',       label: 'AI Chat API',       icon: '🤖', tag: '/api/v1/chat', desc: 'Claude claude-sonnet-4-6 integration via Anthropic SDK', color: '#0d2a1a' },
      { id: 'ws',             label: 'WebSocket Hub',     icon: '⚡', tag: '/ws/*', desc: 'Real-time signal + price broadcast to all connected clients', color: '#0d2a1a', drillable: true },
      { id: 'pattern-engine', label: 'Pattern Engine',    icon: '🧠', tag: 'core/', desc: '8 built-in patterns + composite scorer + IV rank gate', color: '#1a3a1a', drillable: true,
        children: [
          { id: 'gap_fill',       label: 'Gap Fill',        icon: '📐', desc: 'Pre-market gap ≥0.5% with OI > 20L, target 70% fill', color: '#1a3a1a' },
          { id: 'pcr_div',        label: 'PCR Divergence',  icon: '📊', desc: 'PCR extremes (>1.3 or <0.7) signal institutional positioning', color: '#1a3a1a' },
          { id: 'mean_rev',       label: 'Mean Reversion',  icon: '↩', desc: 'Bollinger Band squeeze break on 15m + 1h alignment', color: '#1a3a1a' },
          { id: 'oi_buildup',     label: 'OI Buildup',      icon: '📈', desc: 'OI increasing with price confirmation — smart money flow', color: '#1a3a1a' },
          { id: 'vwap_oi',        label: 'VWAP + OI',       icon: '⚖', desc: 'Price rejects VWAP on high OI buildup', color: '#1a3a1a' },
          { id: 'iv_crush',       label: 'IV Crush',        icon: '📉', desc: 'Sell options before events when IV rank >75%', color: '#1a3a1a' },
          { id: 'max_pain',       label: 'Max Pain Gravity',icon: '🎯', desc: 'Expiry week: price gravitates to max-pain strike', color: '#1a3a1a' },
          { id: 'expiry_week',    label: 'Expiry Week',     icon: '📅', desc: 'Theta decay harvest in final 2 days of weekly expiry', color: '#1a3a1a' },
        ],
      },
      { id: 'risk-gate', label: 'Risk Gate', icon: '🛡', tag: 'core/risk/', desc: 'Redis-backed circuit breakers: daily P&L, portfolio heat, kill switch', color: '#1a1a3a' },
    ],
  },
  {
    id: 'kite',
    label: 'Kite Connect',
    icon: '🔌',
    color: '#2a1a0d',
    accent: '#e3b341',
    desc: 'Zerodha broker API — live prices via WebSocket ticker, order placement',
    row: 0, col: 2,
    connections: ['backend'],
    children: [
      { id: 'kite-ticker', label: 'KiteTicker',    icon: '📡', desc: 'WebSocket feed for real-time LTP of NIFTY + BANKNIFTY futures', color: '#2a1a0d' },
      { id: 'kite-api',    label: 'REST API',      icon: '🔗', desc: 'Instrument master, historical candles, order placement', color: '#2a1a0d' },
      { id: 'kite-auth',   label: 'OAuth Flow',    icon: '🔑', desc: 'Daily access token via request_token redirect URL', color: '#2a1a0d' },
      { id: 'kite-synth',  label: 'Synthetic Mode',icon: '🧪', desc: 'Black-Scholes synthetic prices when Kite not connected', color: '#2a1a0d' },
    ],
  },
  {
    id: 'postgres',
    label: 'PostgreSQL',
    icon: '🐘',
    color: '#1a1a35',
    accent: '#7b61ff',
    desc: 'Async SQLAlchemy ORM — Alembic migrations, 7 core tables',
    row: 1, col: 0,
    connections: [],
    children: [
      { id: 'tbl-signals',    label: 'signals',              icon: '📋', desc: 'Pattern signals with strike, premium, IV, DTE, confidence, status (ACTIVE/EXPIRED/EXECUTED)', color: '#1a1a35' },
      { id: 'tbl-trades',     label: 'trades',               icon: '💹', desc: 'Paper + live trades: entry/exit, MTM, stop-loss, trailing stop, charges, realized P&L', color: '#1a1a35' },
      { id: 'tbl-portfolio',  label: 'portfolio',            icon: '💼', desc: 'Capital, deployed heat, peak capital, max drawdown, weekly P&L, total trades', color: '#1a1a35' },
      { id: 'tbl-kite',       label: 'kite_config',          icon: '🔑', desc: 'Encrypted API key/secret + daily access token', color: '#1a1a35' },
      { id: 'tbl-disc',       label: 'discovered_patterns',  icon: '🧬', desc: 'Statistically-mined patterns with Mann-Whitney p-values and edge flags', color: '#1a1a35' },
      { id: 'tbl-bt-run',     label: 'pattern_backtest_runs',icon: '⏪', desc: 'Walk-forward backtest results: Sharpe, max drawdown, win rate, profit factor', color: '#1a1a35' },
      { id: 'tbl-bt-trade',   label: 'pattern_backtest_trades', icon: '📊', desc: 'Individual trades within each backtest run for drill-down analysis', color: '#1a1a35' },
    ],
  },
  {
    id: 'redis',
    label: 'Redis',
    icon: '🔴',
    color: '#2a0d0d',
    accent: '#ff4444',
    desc: 'In-memory store — risk circuit breakers, portfolio heat, kill switch',
    row: 1, col: 1,
    connections: [],
    children: [
      { id: 'r-pnl',      label: 'DAILY_PNL',       icon: '💰', desc: 'Running daily realized P&L — triggers halt at -2% of capital', color: '#2a0d0d' },
      { id: 'r-deployed', label: 'DAILY_DEPLOYED',   icon: '🔥', desc: 'Total capital deployed in open positions — max 3% of portfolio', color: '#2a0d0d' },
      { id: 'r-halt',     label: 'TRADING_HALTED',   icon: '🚫', desc: 'Boolean kill flag — set true by risk gate or manual kill switch', color: '#2a0d0d' },
      { id: 'r-kill',     label: 'KILL_SWITCH',      icon: '☠', desc: 'Permanent halt until manually reset — overrides all other gates', color: '#2a0d0d' },
    ],
  },
  {
    id: 'celery',
    label: 'Celery Workers',
    icon: '⚙',
    color: '#1a2a1a',
    accent: '#26a69a',
    desc: 'Redis-brokered task queue — 14 scheduled jobs, Celery Beat scheduler',
    row: 1, col: 2,
    connections: [],
    children: [
      { id: 'ct-scan',       label: 'scan_signals',          icon: '⚡', tag: '*/5 min', desc: 'Run all 8 patterns on NIFTY+BANKNIFTY, insert signals, auto paper-trade ≥82% conf', color: '#1a2a1a' },
      { id: 'ct-mtm',        label: 'mtm_update',            icon: '💹', tag: '*/2 min', desc: 'Mark-to-market all open trades with BS pricing + trailing stop logic', color: '#1a2a1a' },
      { id: 'ct-settle',     label: 'settle_expired',        icon: '⏰', tag: '*/10 min', desc: 'Close trades whose options have expired based on DTE', color: '#1a2a1a' },
      { id: 'ct-cleanup',    label: 'cleanup_stale_signals', icon: '🧹', tag: '*/15 min', desc: 'Expire ACTIVE signals past valid_until, remove old EXPIRED records', color: '#1a2a1a' },
      { id: 'ct-eod',        label: 'eod_close_intraday',    icon: '🔔', tag: '15:20 IST', desc: 'Force-close all intraday trades before broker auto-square-off', color: '#1a2a1a' },
      { id: 'ct-sync',       label: 'sync_market_data',      icon: '🌐', tag: '16:15 IST', desc: 'Download NSE bhavcopy, bootstrap PCR/max-pain cache', color: '#1a2a1a' },
      { id: 'ct-bt',         label: 'run_nightly_backtests', icon: '⏪', tag: '16:00 daily', desc: 'Walk-forward backtest all discovered patterns to validate edge', color: '#1a2a1a' },
      { id: 'ct-disc',       label: 'run_nightly_discovery', icon: '🔍', tag: '02:00 daily', desc: 'Statistical pattern miner (Mann-Whitney U) on bhav data', color: '#1a2a1a' },
      { id: 'ct-pnl',        label: 'reset_daily_pnl',       icon: '🔄', tag: '09:15 daily', desc: 'Clear daily P&L and deployed capital in Redis + resync from DB', color: '#1a2a1a' },
      { id: 'ct-weekly',     label: 'reset_weekly_pnl',      icon: '📅', tag: 'Mon 09:15', desc: 'Clear weekly P&L tracking in portfolio', color: '#1a2a1a' },
      { id: 'ct-briefing',   label: 'generate_briefing',     icon: '📰', tag: '08:45 IST', desc: 'Pre-market AI briefing: PCR, FII, IV rank, expiry context', color: '#1a2a1a' },
    ],
  },
]

/* ── Helpers ───────────────────────────────────────────────────────── */
const PULSE_COLORS = ['#58a6ff', '#3fb950', '#e3b341', '#7b61ff']

function usePulse() {
  const [offset, setOffset] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setOffset(o => (o + 1) % 100), 40)
    return () => clearInterval(t)
  }, [])
  return offset
}

/* ── Animated connection dot along a straight line ─────────────────── */
function FlowDot({ x1, y1, x2, y2, color, delay }: { x1: number; y1: number; x2: number; y2: number; color: string; delay: number }) {
  const [t, setT] = useState(delay % 1)
  useEffect(() => {
    let start: number
    const DURATION = 2200 + delay * 600
    const step = (ts: number) => {
      if (!start) start = ts
      const elapsed = (ts - start + delay * DURATION) % DURATION
      setT(elapsed / DURATION)
      raf = requestAnimationFrame(step)
    }
    let raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [delay])
  const cx = x1 + (x2 - x1) * t
  const cy = y1 + (y2 - y1) * t
  return <circle cx={cx} cy={cy} r={3.5} fill={color} opacity={0.9} />
}

/* ── Top-level node card ────────────────────────────────────────────── */
function TopCard({ node, onClick, highlighted }: { node: TopNode; onClick: () => void; highlighted: boolean }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        gridRow: node.row + 1,
        gridColumn: node.col + 1,
        padding: '16px 18px',
        borderRadius: 10,
        cursor: 'pointer',
        background: node.color,
        border: `2px solid ${highlighted || hover ? node.accent : 'rgba(255,255,255,0.06)'}`,
        boxShadow: hover ? `0 0 20px ${node.accent}44, 0 4px 24px rgba(0,0,0,0.4)` : '0 2px 8px rgba(0,0,0,0.3)',
        transform: hover ? 'translateY(-3px) scale(1.02)' : 'none',
        transition: 'all 0.2s ease',
        minHeight: 110,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 22 }}>{node.icon}</span>
        <span style={{ fontWeight: 700, fontSize: 13, color: node.accent }}>{node.label}</span>
      </div>
      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.55)', lineHeight: 1.5 }}>{node.desc}</div>
      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 4 }}>
        <span style={{ fontSize: 10, color: node.accent, opacity: 0.7 }}>{node.children.length} components</span>
        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginLeft: 'auto' }}>Click to expand →</span>
      </div>
    </div>
  )
}

/* ── Sub-node card in detail view ───────────────────────────────────── */
function SubCard({ sub, accent, onClick, delay }: { sub: SubNode; accent: string; onClick?: () => void; delay: number }) {
  const [visible, setVisible] = useState(false)
  const [hover, setHover] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), delay * 60)
    return () => clearTimeout(t)
  }, [delay])

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '12px 14px',
        borderRadius: 8,
        background: sub.color,
        border: `1px solid ${hover && onClick ? accent : 'rgba(255,255,255,0.08)'}`,
        cursor: onClick ? 'pointer' : 'default',
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(12px)',
        transition: 'opacity 0.3s ease, transform 0.3s ease, border-color 0.15s, box-shadow 0.15s',
        boxShadow: hover && onClick ? `0 0 12px ${accent}33` : 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 16 }}>{sub.icon}</span>
        <span style={{ fontWeight: 600, fontSize: 12, color: '#e6edf3' }}>{sub.label}</span>
        {sub.tag && (
          <span style={{ fontSize: 9, background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.4)', padding: '1px 5px', borderRadius: 3, fontFamily: 'monospace', marginLeft: 'auto' }}>
            {sub.tag}
          </span>
        )}
        {sub.drillable && <span style={{ marginLeft: 'auto', fontSize: 10, color: accent }}>▸</span>}
      </div>
      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)', lineHeight: 1.5 }}>{sub.desc}</div>
    </div>
  )
}

/* ── Main Architecture component ────────────────────────────────────── */
export default function Architecture() {
  const [selected, setSelected] = useState<TopNode | null>(null)
  const [drillSub, setDrillSub] = useState<SubNode | null>(null)
  const [exiting, setExiting] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Animated SVG connections at level 0
  const CONN_META = [
    { from: 'frontend', to: 'backend',  color: PULSE_COLORS[0] },
    { from: 'backend',  to: 'postgres', color: PULSE_COLORS[3] },
    { from: 'backend',  to: 'redis',    color: PULSE_COLORS[2] },
    { from: 'backend',  to: 'celery',   color: PULSE_COLORS[2] },
    { from: 'kite',     to: 'backend',  color: PULSE_COLORS[1] },
  ]

  // Card grid positions (in pixels for SVG overlay) — relative to a 780×260 viewport
  const CARD_POS: Record<string, { x: number; y: number }> = {
    frontend: { x: 130, y: 65 },
    backend:  { x: 390, y: 65 },
    kite:     { x: 650, y: 65 },
    postgres: { x: 130, y: 195 },
    redis:    { x: 390, y: 195 },
    celery:   { x: 650, y: 195 },
  }

  function navigateTo(node: TopNode) {
    setExiting(true)
    setTimeout(() => { setSelected(node); setDrillSub(null); setExiting(false) }, 200)
  }
  function drillInto(sub: SubNode) {
    if (!sub.drillable && !sub.children) return
    setExiting(true)
    setTimeout(() => { setDrillSub(sub); setExiting(false) }, 200)
  }
  function goBack() {
    setExiting(true)
    setTimeout(() => {
      if (drillSub) { setDrillSub(null) }
      else { setSelected(null) }
      setExiting(false)
    }, 200)
  }

  const viewStyle: React.CSSProperties = {
    opacity: exiting ? 0 : 1,
    transform: exiting ? 'scale(0.97)' : 'scale(1)',
    transition: 'opacity 0.2s, transform 0.2s',
  }

  const currentItems = drillSub?.children ?? selected?.children ?? []

  return (
    <div
      ref={containerRef}
      style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg)', overflow: 'hidden' }}
    >
      {/* ── Header ── */}
      <div style={{
        padding: '12px 20px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg2)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        {selected && (
          <button onClick={goBack} className="tv-btn tv-btn-ghost" style={{ fontSize: 11, padding: '3px 10px' }}>
            ← Back
          </button>
        )}
        <div style={{ display: 'flex', align: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--txt3)' }}>AlphaFO</span>
          {selected && <><span style={{ color: 'var(--txt3)', fontSize: 11 }}>›</span><span style={{ fontSize: 11, color: selected.accent, fontWeight: 600 }}>{selected.label}</span></>}
          {drillSub  && <><span style={{ color: 'var(--txt3)', fontSize: 11 }}>›</span><span style={{ fontSize: 11, color: 'var(--txt2)' }}>{drillSub.label}</span></>}
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--txt3)' }}>
          {!selected ? '6 subsystems — click any to explore internals' : `${currentItems.length} components`}
        </div>
      </div>

      {/* ── Body ── */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        {/* ── Level 0: System overview ── */}
        {!selected && (
          <div style={viewStyle}>
            <SystemOverview onSelect={navigateTo} />
          </div>
        )}

        {/* ── Level 1 / 2: Subsystem detail ── */}
        {selected && (
          <div style={viewStyle}>
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <span style={{ fontSize: 28 }}>{(drillSub ?? selected).icon}</span>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15, color: (drillSub ? 'var(--txt)' : selected.accent) }}>
                    {(drillSub ?? selected).label}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--txt2)', marginTop: 2 }}>{(drillSub ?? selected).desc}</div>
                </div>
              </div>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: currentItems.length <= 4 ? '1fr 1fr' : 'repeat(3, 1fr)',
              gap: 10,
            }}>
              {currentItems.map((sub, i) => (
                <SubCard
                  key={sub.id}
                  sub={sub}
                  accent={selected.accent}
                  delay={i}
                  onClick={sub.drillable || sub.children ? () => drillInto(sub) : undefined}
                />
              ))}
            </div>

            {/* Connections info for backend */}
            {selected.id === 'backend' && !drillSub && (
              <div style={{ marginTop: 20, padding: '14px 16px', background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--txt2)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  Key connections
                </div>
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                  {[
                    { label: 'PostgreSQL', color: '#7b61ff', detail: '7 tables via SQLAlchemy async' },
                    { label: 'Redis',      color: '#ff4444', detail: 'Risk gate circuit breakers' },
                    { label: 'Celery',     color: '#26a69a', detail: 'Task dispatch + result fetch' },
                    { label: 'Kite',       color: '#e3b341', detail: 'Live prices + order API' },
                  ].map(c => (
                    <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: c.color }} />
                      <span style={{ fontSize: 11, fontWeight: 600, color: c.color }}>{c.label}</span>
                      <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{c.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── System Overview (Level 0) ──────────────────────────────────────── */
function SystemOverview({ onSelect }: { onSelect: (n: TopNode) => void }) {
  const [dotPhase, setDotPhase] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setDotPhase(p => (p + 1) % 200), 30)
    return () => clearInterval(t)
  }, [])

  // SVG connection lines — positions in a 780 × 290 viewBox
  const POS: Record<string, [number, number]> = {
    frontend: [130, 70],
    backend:  [390, 70],
    kite:     [650, 70],
    postgres: [130, 220],
    redis:    [390, 220],
    celery:   [650, 220],
  }

  const CONNS: [string, string, string, number][] = [
    ['frontend', 'backend',  '#58a6ff', 0],
    ['backend',  'postgres', '#7b61ff', 0.3],
    ['backend',  'redis',    '#ff4444', 0.6],
    ['backend',  'celery',   '#26a69a', 0.1],
    ['kite',     'backend',  '#e3b341', 0.5],
    ['backend',  'backend',  '#26a69a', 0],
  ]

  return (
    <div>
      {/* Title */}
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--txt)', marginBottom: 4 }}>AlphaFO — System Architecture</div>
        <div style={{ fontSize: 12, color: 'var(--txt3)' }}>NSE F&O Pattern Engine · Paper & Live Trading · Python + React</div>
      </div>

      {/* SVG overlay for connection lines */}
      <div style={{ position: 'relative' }}>
        <svg
          viewBox="0 0 780 290"
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 0 }}
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            {CONNS.map(([f, t, color], i) => (
              <linearGradient key={i} id={`grad${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={color} stopOpacity="0.15" />
                <stop offset="50%" stopColor={color} stopOpacity="0.5" />
                <stop offset="100%" stopColor={color} stopOpacity="0.15" />
              </linearGradient>
            ))}
          </defs>

          {/* Static dashed lines */}
          {CONNS.filter(c => c[0] !== c[1]).map(([f, t, color], i) => {
            const [x1, y1] = POS[f], [x2, y2] = POS[t]
            return (
              <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={color} strokeWidth={1.5} strokeOpacity={0.2}
                strokeDasharray="6 4"
              />
            )
          })}

          {/* Animated flow dots */}
          {CONNS.filter(c => c[0] !== c[1]).map(([f, t, color, delay], i) => {
            const [x1, y1] = POS[f], [x2, y2] = POS[t]
            const pct = ((dotPhase + (delay as number) * 200) % 200) / 200
            const cx = x1 + (x2 - x1) * pct
            const cy = y1 + (y2 - y1) * pct
            return (
              <g key={i}>
                <circle cx={cx} cy={cy} r={4} fill={color} opacity={0.85} />
                <circle cx={cx} cy={cy} r={7} fill={color} opacity={0.15} />
              </g>
            )
          })}
        </svg>

        {/* Node grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gridTemplateRows: 'auto auto', gap: 16, position: 'relative', zIndex: 1 }}>
          {NODES.map(node => (
            <TopCard key={node.id} node={node} onClick={() => onSelect(node)} highlighted={false} />
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{ marginTop: 24, display: 'flex', gap: 20, justifyContent: 'center', flexWrap: 'wrap' }}>
        {[
          { color: '#58a6ff', label: 'HTTP + WebSocket' },
          { color: '#7b61ff', label: 'SQLAlchemy ORM' },
          { color: '#ff4444', label: 'Redis circuit breaker' },
          { color: '#26a69a', label: 'Celery task queue' },
          { color: '#e3b341', label: 'Kite Connect API' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ display: 'inline-block', width: 20, height: 2, background: color, borderRadius: 1, opacity: 0.7 }} />
            <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Data flow summary */}
      <div style={{ marginTop: 20, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {[
          { icon: '⚡', label: 'Signal Flow', desc: 'Celery scans patterns every 5 min → signals stored in DB → WebSocket pushes to all browser clients', color: '#58a6ff' },
          { icon: '🛡', label: 'Risk Flow', desc: 'Every trade checks Redis gate: daily P&L < 2%, portfolio heat < 3%, kill switch off', color: '#ff4444' },
          { icon: '📊', label: 'Data Flow', desc: 'NSE bhavcopy → PCR/max-pain cache → bhav replayer for backtesting → bhav-bootstrapped IV rank', color: '#e3b341' },
        ].map(({ icon, label, desc, color }) => (
          <div key={label} style={{ padding: '12px 14px', background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', gap: 7, alignItems: 'center', marginBottom: 5 }}>
              <span>{icon}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color }}>{label}</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--txt3)', lineHeight: 1.5 }}>{desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
