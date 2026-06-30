/**
 * LiveStatus — compact real-time activity panel.
 * Shows what the system is currently doing: prices, open trades, signals,
 * risk gate state, last scan, and a rolling activity log.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api/client'

interface HealthData {
  ok: boolean
  components: {
    ticker:  { ok: boolean; nifty_ltp: number; symbols: number; mode: string }
    redis:   { ok: boolean; daily_pnl: number; deployed: number; trading_halted: boolean }
    kite:    { ok: boolean; detail: string }
    celery:  { ok: boolean }
    database: { ok: boolean }
  }
}

interface DataStatus { mode: string; source_label: string; market_open: boolean; market_time_ist: string; kite_configured: boolean; ltp_sample: { ltp?: number; error?: string } | null }
interface Trade { id: number; underlying: string; symbol: string; action: string; entry_price: number; unrealized_pnl: number | null; stop_loss: number; notes: string | null }
interface LogEntry { ts: string; msg: string; kind: 'trade' | 'signal' | 'scan' | 'risk' | 'info' | 'error' }

const fmt = (n: number | null | undefined, dec = 2) =>
  n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(dec)

const fmtRs = (n: number | null | undefined) =>
  n == null ? '—' : `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}${n < 0 ? ' loss' : ''}`

function dot(ok: boolean | undefined) {
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
      background: ok ? '#26c6a0' : '#ff5252',
      boxShadow: ok ? '0 0 4px #26c6a066' : '0 0 4px #ff525266',
    }} />
  )
}

export default function LiveStatus({ onClose }: { onClose: () => void }) {
  const [health,   setHealth]   = useState<HealthData | null>(null)
  const [trades,   setTrades]   = useState<Trade[]>([])
  const [sigCount, setSigCount] = useState<number | null>(null)
  const [status,   setStatus]   = useState<DataStatus | null>(null)
  const [portfolio, setPortfolio] = useState<{ capital_current: number; daily_pnl: number; weekly_pnl: number; deployed_capital: number } | null>(null)
  const [notifPerm, setNotifPerm] = useState<NotificationPermission>('default')
  const prevHalted = useRef(false)
  const [log, setLog]           = useState<LogEntry[]>([])
  const [scanning, setScanning] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())
  const prevTradeIds = useRef<Set<number>>(new Set())
  const prevSigCount = useRef<number | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  // Request browser notification permission on mount
  useEffect(() => {
    if ('Notification' in window) {
      setNotifPerm(Notification.permission)
      if (Notification.permission === 'default') {
        Notification.requestPermission().then(p => setNotifPerm(p))
      }
    }
  }, [])

  const pushNotif = useCallback((title: string, body: string, icon = '📊') => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification(`AlphaFO ${icon} ${title}`, { body, icon: '/favicon.ico', silent: false })
    }
  }, [])

  const addLog = useCallback((msg: string, kind: LogEntry['kind'] = 'info') => {
    const ts = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setLog(prev => [{ ts, msg, kind }, ...prev].slice(0, 40))
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [h, t, s, st, p] = await Promise.all([
        api.get('/system/health').then(r => r.data),
        api.get('/trades/', { params: { mode: 'paper', status: 'open' } }).then(r => r.data),
        api.get('/signals/').then(r => r.data),
        api.get('/settings/data-status').then(r => r.data),
        api.get('/portfolio/', { params: { mode: 'paper' } }).then(r => r.data),
      ])

      setHealth(h)
      setStatus(st)
      setPortfolio(p)
      setLastRefresh(new Date())

      // Detect new trades
      const newTrades: Trade[] = t.trades ?? []
      const currentIds = new Set(newTrades.map((x: Trade) => x.id))
      newTrades.forEach((tr: Trade) => {
        if (!prevTradeIds.current.has(tr.id)) {
          const msg = `${tr.underlying} ${tr.symbol} ${tr.action} @ ₹${tr.entry_price}`
          addLog(`New trade: ${msg}`, 'trade')
          pushNotif('Trade Opened', msg, '📈')
        }
      })
      prevTradeIds.current = currentIds
      setTrades(newTrades)

      // Detect new signals
      const cnt = s.count ?? 0
      if (prevSigCount.current !== null && cnt > prevSigCount.current) {
        const diff = cnt - prevSigCount.current
        addLog(`${diff} new signal(s) — total active: ${cnt}`, 'signal')
        if (diff > 0) pushNotif('New Signals', `${diff} new signal(s) generated`, '🔔')
      }
      prevSigCount.current = cnt
      setSigCount(cnt)

      // Risk alerts — only fire notification on state change
      const halted = h?.components?.redis?.trading_halted
      if (halted && !prevHalted.current) {
        addLog('⚠ TRADING HALTED — daily loss limit hit', 'risk')
        pushNotif('Trading Halted', 'Daily loss limit reached — all auto-trading stopped', '🚨')
      }
      prevHalted.current = !!halted

      // Kite token stale warning
      if (st?.kite_configured === false) {
        addLog('Kite token missing/expired — running on synthetic data', 'risk')
      }
    } catch {
      addLog('Refresh error — backend unreachable', 'error')
    }
  }, [addLog])

  // Poll every 5 s
  useEffect(() => {
    addLog('Live status started', 'info')
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh, addLog])

  const triggerScan = async () => {
    setScanning(true)
    addLog('Manual scan triggered…', 'scan')
    try {
      const r = await api.post('/system/run-task/scan-priority-15m')
      addLog(`Scan queued (task ${r.data.task_id?.slice(0, 8)}…)`, 'scan')
    } catch {
      addLog('Scan trigger failed', 'error')
    }
    setTimeout(() => { setScanning(false); refresh() }, 12000)
  }

  const triggerMtm = async () => {
    addLog('MTM refresh triggered…', 'info')
    try {
      const r = await api.post('/trades/refresh-mtm')
      addLog(`MTM done — ${r.data.count} trades, unrealised ₹${(r.data.total_unrealized_pnl ?? 0).toFixed(0)}`, 'info')
      await refresh()
    } catch { addLog('MTM refresh failed', 'error') }
  }

  const halted = health?.components?.redis?.trading_halted
  const allOk  = health?.ok

  const KIND_COLOR: Record<string, string> = {
    trade:  '#26c6a0',
    signal: '#9c71ff',
    scan:   '#4fc3f7',
    risk:   '#ff5252',
    info:   'var(--txt3)',
    error:  '#ff5252',
  }

  return (
    <div style={{
      position: 'fixed', top: 44, right: 0, width: 340, bottom: 0,
      background: 'var(--bg2)', borderLeft: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column',
      zIndex: 200, fontFamily: '-apple-system,BlinkMacSystemFont,sans-serif',
      boxShadow: '-4px 0 20px rgba(0,0,0,0.25)',
    }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--txt)', letterSpacing: '.05em', flex: 1 }}>
          LIVE STATUS
        </span>
        <span style={{ fontSize: 9, color: 'var(--txt3)' }}>
          {lastRefresh.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
        {dot(allOk)}
        <button onClick={onClose} className="tv-btn tv-btn-ghost"
          style={{ padding: '2px 8px', fontSize: 11 }}>✕</button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 0 }}>

        {/* ── Kite token warning ── */}
        {status?.kite_configured === false && (
          <div style={{
            background: 'rgba(255,82,82,0.10)', borderBottom: '1px solid #ff525244',
            padding: '8px 14px', display: 'flex', gap: 8, alignItems: 'flex-start',
          }}>
            <span style={{ fontSize: 15, flexShrink: 0 }}>⚠</span>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ff5252' }}>Kite Token Expired</div>
              <div style={{ fontSize: 10, color: 'var(--txt2)', marginTop: 2 }}>
                Go to Settings → paste today's request_token to restore live data.
                Running on synthetic prices until then.
              </div>
            </div>
          </div>
        )}

        {/* ── Browser notification prompt ── */}
        {notifPerm === 'default' && (
          <div style={{
            background: 'rgba(156,113,255,0.08)', borderBottom: '1px solid #9c71ff33',
            padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 11, color: '#9c71ff', flex: 1 }}>Enable notifications for trade alerts?</span>
            <button className="tv-btn" style={{ fontSize: 10, padding: '3px 10px' }}
              onClick={() => Notification.requestPermission().then(p => setNotifPerm(p))}>
              Allow
            </button>
          </div>
        )}

        {/* ── Mode + market ── */}
        <Section label="SESSION">
          <Row label="Mode"   value={<Pill color={status?.mode === 'paper' ? '#ffab40' : status?.mode === 'live' ? '#26c6a0' : '#4fc3f7'}>{(status?.mode ?? '…').toUpperCase()}</Pill>} />
          <Row label="Data"   value={<Pill color="#5b9bff">{status?.source_label ?? '…'}</Pill>} />
          <Row label="Market" value={
            <span style={{ color: status?.market_open ? '#26c6a0' : '#ff7043', fontWeight: 700, fontSize: 11 }}>
              {status?.market_open ? '● OPEN' : '○ CLOSED'} {status?.market_time_ist ?? ''}
            </span>
          } />
        </Section>

        {/* ── Live prices ── */}
        <Section label="LIVE PRICES">
          <Row label="NIFTY"     value={<Price val={health?.components?.ticker?.nifty_ltp} />} />
          <Row label="Symbols"   value={`${health?.components?.ticker?.symbols ?? '—'} tracked`} />
          <Row label="Kite"      value={<span style={{ display:'flex', gap:5, alignItems:'center' }}>{dot(health?.components?.kite?.ok)}<span style={{fontSize:11,color:'var(--txt2)'}}>{health?.components?.kite?.detail ?? '—'}</span></span>} />
        </Section>

        {/* ── Risk gate ── */}
        <Section label="RISK GATE">
          <Row label="Daily P&L"  value={
            <span style={{ color: (health?.components?.redis?.daily_pnl ?? 0) >= 0 ? '#26c6a0' : '#ff5252', fontWeight: 700, fontSize: 12 }}>
              {fmt(health?.components?.redis?.daily_pnl)} ₹
            </span>
          } />
          <Row label="Deployed"   value={`₹${(health?.components?.redis?.deployed ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
          <Row label="Circuit"    value={
            halted
              ? <span style={{ color:'#ff5252', fontWeight:800, fontSize:11 }}>⚠ HALTED</span>
              : <span style={{ color:'#26c6a0', fontWeight:700, fontSize:11 }}>● Active</span>
          } />
        </Section>

        {/* ── Portfolio ── */}
        <Section label="PAPER PORTFOLIO">
          <Row label="Capital"    value={`₹${(portfolio?.capital_current ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
          <Row label="Daily P&L"  value={<span style={{ color:(portfolio?.daily_pnl ?? 0) >= 0 ? '#26c6a0':'#ff5252', fontWeight:700 }}>{fmtRs(portfolio?.daily_pnl)}</span>} />
          <Row label="Weekly P&L" value={<span style={{ color:(portfolio?.weekly_pnl ?? 0) >= 0 ? '#26c6a0':'#ff5252' }}>{fmtRs(portfolio?.weekly_pnl)}</span>} />
        </Section>

        {/* ── Open trades ── */}
        <Section label={`OPEN TRADES (${trades.length})`}>
          {trades.length === 0
            ? <div style={{ padding:'6px 0', color:'var(--txt3)', fontSize:11 }}>No open positions</div>
            : trades.filter(t => !(t.notes || '').startsWith('spread_leg:hedge')).map(tr => (
              <div key={tr.id} style={{
                padding: '6px 0', borderBottom: '1px solid var(--border)',
                display: 'flex', flexDirection: 'column', gap: 2,
              }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                  <span style={{ fontSize:11, fontWeight:700, color:'var(--txt)' }}>
                    {tr.underlying} {tr.action}
                  </span>
                  <span style={{ fontSize:11, fontWeight:700, color: (tr.unrealized_pnl ?? 0) >= 0 ? '#26c6a0' : '#ff5252' }}>
                    {fmt(tr.unrealized_pnl)} ₹
                  </span>
                </div>
                <div style={{ fontSize:10, color:'var(--txt3)' }}>
                  {tr.symbol} · entry ₹{tr.entry_price} · SL ₹{tr.stop_loss}
                </div>
              </div>
            ))
          }
        </Section>

        {/* ── Signals ── */}
        <Section label="SIGNALS">
          <Row label="Active" value={
            <span style={{ fontSize:13, fontWeight:800, color:'#9c71ff' }}>{sigCount ?? '…'}</span>
          } />
          <Row label="Workers" value={<span style={{ display:'flex', gap:5, alignItems:'center' }}>{dot(health?.components?.celery?.ok)}<span style={{fontSize:11,color:'var(--txt2)'}}>Celery {health?.components?.celery?.ok ? 'running' : 'down'}</span></span>} />
        </Section>

        {/* ── Actions ── */}
        <Section label="ACTIONS">
          <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
            <button className="tv-btn" onClick={triggerScan} disabled={scanning}
              style={{ fontSize:11, padding:'5px 12px', opacity: scanning ? 0.6 : 1 }}>
              {scanning ? '⟳ Scanning…' : '⚡ Run Scan'}
            </button>
            <button className="tv-btn tv-btn-ghost" onClick={triggerMtm}
              style={{ fontSize:11, padding:'5px 12px' }}>
              ↻ MTM Refresh
            </button>
            <button className="tv-btn tv-btn-ghost" onClick={() => { addLog('Manual refresh', 'info'); refresh() }}
              style={{ fontSize:11, padding:'5px 12px' }}>
              ↺ Refresh
            </button>
          </div>
        </Section>

        {/* ── Activity log ── */}
        <div style={{ borderTop:'1px solid var(--border)', padding:'8px 14px 4px', flexShrink:0 }}>
          <div style={{ fontSize:9, fontWeight:800, color:'var(--txt3)', letterSpacing:'.08em', marginBottom:6 }}>ACTIVITY LOG</div>
        </div>
        <div ref={logRef} style={{ flex:1, overflowY:'auto', padding:'0 14px 14px', minHeight:100 }}>
          {log.length === 0
            ? <div style={{ color:'var(--txt3)', fontSize:11 }}>No activity yet…</div>
            : log.map((e, i) => (
              <div key={i} style={{ display:'flex', gap:8, padding:'3px 0', borderBottom:'1px solid var(--border)', opacity: i > 15 ? 0.4 : 1 }}>
                <span style={{ fontSize:9, color:'var(--txt3)', flexShrink:0, paddingTop:1 }}>{e.ts}</span>
                <span style={{ fontSize:11, color: KIND_COLOR[e.kind] ?? 'var(--txt2)', lineHeight:1.4 }}>{e.msg}</span>
              </div>
            ))
          }
        </div>

      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '10px 14px' }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--txt3)', letterSpacing: '.08em', marginBottom: 7 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0' }}>
      <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{label}</span>
      <span style={{ fontSize: 11, color: 'var(--txt)', fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function Pill({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 3,
      background: `${color}18`, color, border: `1px solid ${color}44`,
      letterSpacing: '.06em',
    }}>{children}</span>
  )
}

function Price({ val }: { val: number | undefined }) {
  if (!val) return <span style={{ color: 'var(--txt3)' }}>—</span>
  return (
    <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--txt)', fontVariantNumeric: 'tabular-nums' }}>
      ₹{val.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
    </span>
  )
}
