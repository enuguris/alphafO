import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchTrades, closeTrade, refreshMtm, createPriceSocket } from '../api/client'

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtINR  = (n?: number | null) => n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const fmtPrem = (n?: number | null) => n == null ? '—' : `₹${n?.toFixed(2)}`
const fmtPct  = (n?: number | null) => n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
const fmtDt   = (iso?: string | null) => {
  if (!iso) return '—'
  // Backend returns bare UTC strings (no Z). Append Z so the browser treats
  // them as UTC and converts to local time (IST) rather than interpreting as local.
  const utc = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
  return new Date(utc).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
const dte = (expiry?: string) => {
  if (!expiry) return null
  return Math.ceil((new Date(`${expiry.slice(0, 10)}T10:00:00Z`).getTime() - Date.now()) / 86400000)
}

// Rough Black-Scholes call/put pricer for live P&L estimation in browser
function bsPrice(S: number, K: number, T: number, r: number, sigma: number, type: 'CE' | 'PE'): number {
  if (T <= 0) return type === 'CE' ? Math.max(0, S - K) : Math.max(0, K - S)
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T))
  const d2 = d1 - sigma * Math.sqrt(T)
  const N = (x: number) => { // standard normal CDF
    const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911
    const sign = x < 0 ? -1 : 1; const ax = Math.abs(x)
    const t2 = 1 / (1 + p * ax)
    const poly = t2*(a1+t2*(a2+t2*(a3+t2*(a4+t2*a5))))
    return 0.5 * (1 + sign * (1 - poly * Math.exp(-ax * ax / 2)))
  }
  if (type === 'CE') return S * N(d1) - K * Math.exp(-r * T) * N(d2)
  return K * Math.exp(-r * T) * N(-d2) - S * N(-d1)
}

function livePrice(trade: any, spotPrices: Record<string, number>): number | null {
  const spot = spotPrices[trade.underlying?.toUpperCase()]
  if (!spot || !trade.strike || !trade.option_type || !trade.expiry_date) return null
  const daysLeft = dte(trade.expiry_date)
  if (daysLeft == null) return null
  const T = Math.max(0.003, daysLeft / 365)  // floor at ~1 day
  const price = bsPrice(spot, trade.strike, T, 0.07, 0.18, trade.option_type)
  return Math.max(0.05, Math.round(price * 100) / 100)
}

function livePnl(trade: any, current: number): number {
  const qty = trade.quantity ?? 1
  const entry = trade.entry_price ?? 0
  const charges = trade.charges_entry ?? 0
  if (trade.action === 'BUY') return (current - entry) * qty - charges
  return (entry - current) * qty - charges
}

const EXIT_LABEL: Record<string, string> = { target_hit: 'Target hit', stop_hit: 'Stop hit', manual: 'Manual', expiry_settlement: 'Expiry', eod: 'EOD', manual_close: 'Manual' }
const EXIT_COLOR: Record<string, string> = { target_hit: 'var(--up)', stop_hit: 'var(--dn)', manual: 'var(--txt2)', manual_close: 'var(--txt2)', expiry_settlement: 'var(--orange)' }

function pill(label: string, bg: string, color: string) {
  return <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: bg, color, border: `1px solid ${color}44`, whiteSpace: 'nowrap' }}>{label}</span>
}

function SummaryCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ padding: '10px 14px', background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)', minWidth: 110 }}>
      <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: color || 'var(--txt)', fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

// ── Trade detail panel ────────────────────────────────────────────────────────

function TradeDetail({ t, currentPrice, pnl, onClose: onCollapse }: {
  t: any; currentPrice: number | null; pnl: number | null; onClose: () => void
}) {
  const isOpen  = t.status === 'open'
  const isHedge = (t.notes ?? '').includes('spread_leg:hedge')
  const displayPnl = isOpen ? pnl : (t.pnl ?? 0)

  const row = (label: string, value: React.ReactNode, mono = false) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 11, color: 'var(--txt3)', minWidth: 170 }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--txt)', fontFamily: mono ? 'monospace' : undefined, fontWeight: 600 }}>{value}</span>
    </div>
  )

  const dur = () => {
    if (!t.entry_time || !t.exit_time) return null
    const m = Math.round((new Date(t.exit_time).getTime() - new Date(t.entry_time).getTime()) / 60000)
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`
  }

  return (
    <div className="fade-up" style={{ background: 'var(--bg2)', borderBottom: '2px solid var(--border)', padding: '14px 20px 14px 32px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0 32px' }}>

        {/* Column 1 — Contract */}
        <div>
          <div style={{ fontSize: 10, color: 'var(--blue)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6, fontWeight: 700 }}>Contract</div>
          {row('NSE symbol', <span style={{ fontFamily: 'monospace', fontSize: 12, cursor: 'copy' }} title="Click to copy" onClick={() => navigator.clipboard?.writeText(t.symbol)}>{t.symbol} <span style={{ fontSize: 9, color: 'var(--txt3)' }}>📋</span></span>)}
          {row('Underlying', t.underlying)}
          {row('Option type', t.option_type ? pill(t.option_type, t.option_type === 'CE' ? 'rgba(41,98,255,0.12)' : 'rgba(233,30,99,0.12)', t.option_type === 'CE' ? 'var(--blue)' : '#e91e63') : '—')}
          {row('Strike', t.strike?.toLocaleString('en-IN') ?? '—', true)}
          {row('Expiry', t.expiry_display || t.expiry_date || '—')}
          {row('DTE remaining', dte(t.expiry_date) != null ? `${dte(t.expiry_date)} days` : '—')}
          {row('Lot size', t.lot_size ?? '—')}
          {row('Quantity (units)', t.quantity)}
          {isHedge && <div style={{ marginTop: 8 }}>{pill('HEDGE LEG — protecting main SELL', 'rgba(255,152,0,0.1)', 'var(--orange)')}</div>}
        </div>

        {/* Column 2 — Execution */}
        <div>
          <div style={{ fontSize: 10, color: 'var(--blue)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6, fontWeight: 700 }}>Execution</div>
          {row('Action', pill(t.action, t.action === 'BUY' ? 'rgba(38,166,154,0.12)' : 'rgba(239,83,80,0.12)', t.action === 'BUY' ? 'var(--up)' : 'var(--dn)'))}
          {row('Signal direction', t.direction ?? '—')}
          {row('Entry price', fmtPrem(t.entry_price), true)}
          {row('Entry time', fmtDt(t.entry_time))}
          {isOpen
            ? row('Live price (BS)', currentPrice != null
                ? <span style={{ fontFamily: 'monospace', color: 'var(--blue)', fontWeight: 700 }}>
                    {fmtPrem(currentPrice)}
                    <span style={{ fontSize: 9, color: 'var(--txt3)', marginLeft: 4 }}>live</span>
                  </span>
                : <span style={{ color: 'var(--txt3)' }}>computing…</span>)
            : row('Exit price', fmtPrem(t.exit_price), true)}
          {!isOpen && row('Exit time', fmtDt(t.exit_time))}
          {!isOpen && dur() && row('Held for', dur()!)}
          {!isOpen && t.exit_reason && row('Exit reason',
            <span style={{ fontWeight: 700, color: EXIT_COLOR[t.exit_reason] ?? 'var(--txt2)' }}>
              {EXIT_LABEL[t.exit_reason] ?? t.exit_reason}
            </span>)}
          {row('Target price', fmtPrem(t.target_price), true)}
          {row('Stop loss',
            <span style={{ fontFamily: 'monospace' }}>
              {fmtPrem(t.stop_loss)}
              {t.notes?.includes('trail_stop:') && (
                <span title="Trailing stop active — stop raised to lock in 50% of peak gain" style={{ marginLeft: 5, fontSize: 10, color: 'var(--up)', fontWeight: 700 }}>⟳ TRAILING</span>
              )}
            </span>
          )}
          {t.last_mtm_at && row('Last MTM refresh', fmtDt(t.last_mtm_at))}
        </div>

        {/* Column 3 — P&L */}
        <div>
          <div style={{ fontSize: 10, color: 'var(--blue)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6, fontWeight: 700 }}>P&L & Charges</div>
          {isOpen && row('Live unrealized P&L',
            <span style={{ fontFamily: 'monospace', fontSize: 15, fontWeight: 700, color: isHedge ? 'var(--txt3)' : (displayPnl ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>
              {isHedge ? '—' : fmtINR(displayPnl)}
            </span>)}
          {!isOpen && row('Gross P&L (before charges)',
            <span style={{ fontFamily: 'monospace', color: (t.gross_pnl ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)', fontWeight: 700 }}>{fmtINR(t.gross_pnl)}</span>)}
          {!isOpen && row('Net P&L (after charges)',
            <span style={{ fontFamily: 'monospace', fontSize: 15, fontWeight: 700, color: isHedge ? 'var(--txt3)' : (displayPnl ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>
              {isHedge ? '—' : fmtINR(displayPnl)}
            </span>)}
          {!isOpen && t.pnl_pct != null && !isHedge && row('Return on premium',
            <span style={{ fontFamily: 'monospace', color: (t.pnl_pct ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>{fmtPct(t.pnl_pct)}</span>)}
          <div style={{ height: 6 }} />
          {row('Entry charges paid', fmtPrem(t.charges_entry), true)}
          {!isOpen && t.charges_total != null && <>
            {row('Total charges', <span style={{ fontFamily: 'monospace', color: 'var(--dn)' }}>{fmtPrem(t.charges_total)}</span>)}
            {(t.charges_brokerage ?? 0) > 0 && row('  ↳ Brokerage', fmtPrem(t.charges_brokerage), true)}
            {(t.charges_stt ?? 0) > 0      && row('  ↳ STT', fmtPrem(t.charges_stt), true)}
            {(t.charges_gst ?? 0) > 0      && row('  ↳ GST (18%)', fmtPrem(t.charges_gst), true)}
            {(t.charges_txn ?? 0) > 0      && row('  ↳ Exchange txn', fmtPrem(t.charges_txn), true)}
            {(t.charges_sebi ?? 0) > 0     && row('  ↳ SEBI turnover', fmtPrem(t.charges_sebi), true)}
            {(t.charges_stamp ?? 0) > 0    && row('  ↳ Stamp duty', fmtPrem(t.charges_stamp), true)}
          </>}
          <div style={{ height: 6 }} />
          {row('Capital at risk', t.capital_at_risk_pct ? `${t.capital_at_risk_pct.toFixed(2)}% of portfolio` : '—')}
        </div>
      </div>
      <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end' }}>
        <button onClick={onCollapse} className="tv-btn" style={{ fontSize: 11, padding: '3px 12px' }}>Collapse ▲</button>
      </div>
    </div>
  )
}

// ── Trade row ─────────────────────────────────────────────────────────────────

function TradeRow({ t, spotPrices, onClose: closeFn }: {
  t: any; spotPrices: Record<string, number>; onClose: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const isOpen  = t.status === 'open'
  const isHedge = (t.notes ?? '').includes('spread_leg:hedge')

  const current = isOpen ? (livePrice(t, spotPrices) ?? t.current_price ?? t.entry_price) : t.exit_price
  const pnl     = isOpen
    ? (current != null ? livePnl(t, current) : (t.unrealized_pnl ?? 0))
    : (t.pnl ?? 0)

  const daysLeft = dte(t.expiry_date)
  const dteColor = daysLeft != null && daysLeft <= 2 ? 'var(--dn)' : daysLeft != null && daysLeft <= 5 ? 'var(--orange)' : 'var(--txt2)'

  // P&L % for display on closed trades
  const pnlPct = !isOpen ? t.pnl_pct : null

  return (
    <>
      <tr
        onClick={() => setOpen(o => !o)}
        style={{ borderBottom: open ? 'none' : '1px solid var(--border)', cursor: 'pointer',
          opacity: isHedge ? 0.55 : 1, background: open ? 'var(--bg2)' : undefined }}
        onMouseEnter={e => { if (!open) e.currentTarget.style.background = 'rgba(255,255,255,0.025)' }}
        onMouseLeave={e => { if (!open) e.currentTarget.style.background = '' }}
      >
        <td style={{ padding: '9px 6px 9px 12px', color: 'var(--txt3)', fontSize: 10, width: 14 }}>{open ? '▼' : '▶'}</td>
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11, fontWeight: isHedge ? 400 : 700, color: isHedge ? 'var(--txt3)' : 'var(--txt)' }}>
          {t.symbol}
          {isHedge && <span style={{ fontSize: 9, color: 'var(--orange)', marginLeft: 5 }}>HEDGE</span>}
        </td>
        <td style={{ padding: '9px 10px' }}>
          {t.option_type ? pill(t.option_type, t.option_type === 'CE' ? 'rgba(41,98,255,0.12)' : 'rgba(233,30,99,0.12)', t.option_type === 'CE' ? 'var(--blue)' : '#e91e63') : '—'}
        </td>
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', color: 'var(--txt2)', fontSize: 12 }}>{t.strike?.toLocaleString('en-IN') ?? '—'}</td>
        <td style={{ padding: '9px 10px' }}>
          {pill(t.action, t.action === 'BUY' ? 'rgba(38,166,154,0.12)' : 'rgba(239,83,80,0.12)', t.action === 'BUY' ? 'var(--up)' : 'var(--dn)')}
        </td>
        {/* Entry → current/exit */}
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 12 }}>
          <span style={{ color: 'var(--txt)' }}>{fmtPrem(t.entry_price)}</span>
          {current != null && (
            <span style={{ color: isOpen ? 'var(--blue)' : 'var(--txt3)' }}>
              {' → '}{fmtPrem(current)}
              {isOpen && <span style={{ fontSize: 9, color: 'var(--txt3)', marginLeft: 2 }}>●live</span>}
            </span>
          )}
        </td>
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', color: 'var(--txt3)', fontSize: 11 }}>{t.quantity}</td>
        {/* P&L */}
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontWeight: 700, fontSize: 13,
          color: isHedge ? 'var(--txt3)' : pnl >= 0 ? 'var(--up)' : 'var(--dn)' }}>
          {isHedge ? '—' : fmtINR(pnl)}
          {!isHedge && pnlPct != null && (
            <span style={{ fontSize: 10, fontWeight: 400, marginLeft: 4, color: pnlPct >= 0 ? 'var(--up)' : 'var(--dn)' }}>{fmtPct(pnlPct)}</span>
          )}
        </td>
        <td style={{ padding: '9px 10px', fontFamily: 'monospace', color: 'var(--txt3)', fontSize: 11 }}>
          {fmtPrem(isOpen ? (t.charges_entry ?? 0) : (t.charges_total ?? 0))}
        </td>
        <td style={{ padding: '9px 10px', color: 'var(--txt3)', fontSize: 10, whiteSpace: 'nowrap' }}>
          {isOpen ? fmtDt(t.entry_time) : fmtDt(t.exit_time)}
        </td>
        <td style={{ padding: '9px 10px' }}>
          {!isOpen && t.exit_reason
            ? <span style={{ fontSize: 10, fontWeight: 700, color: EXIT_COLOR[t.exit_reason] ?? 'var(--txt2)' }}>{EXIT_LABEL[t.exit_reason] ?? t.exit_reason}</span>
            : <span style={{ fontWeight: 700, color: dteColor, fontSize: 11 }}>{daysLeft != null ? `${daysLeft}d` : '—'}</span>}
        </td>
        <td style={{ padding: '9px 10px' }} onClick={e => e.stopPropagation()}>
          {isOpen && !isHedge && (
            <button onClick={() => { if (confirm(`Close ${t.symbol} at ₹${current?.toFixed(2)}?`)) closeFn(t.id) }}
              className="tv-btn" style={{ padding: '3px 10px', fontSize: 11, color: 'var(--dn)', border: '1px solid rgba(239,83,80,0.35)', background: 'rgba(239,83,80,0.08)' }}>
              Close
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr style={{ borderBottom: '2px solid var(--border)' }}>
          <td colSpan={12} style={{ padding: 0 }}>
            <TradeDetail t={t} currentPrice={current} pnl={isHedge ? null : pnl} onClose={() => setOpen(false)} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Live P&L bar ──────────────────────────────────────────────────────────────

function LivePnlBar({ trades, spotPrices }: { trades: any[]; spotPrices: Record<string, number> }) {
  const mainTrades = trades.filter(t => !(t.notes ?? '').includes('spread_leg:hedge'))
  const totalPnl = mainTrades.reduce((sum, t) => {
    const cur = livePrice(t, spotPrices) ?? t.current_price ?? t.entry_price
    return sum + (cur != null ? livePnl(t, cur) : (t.unrealized_pnl ?? 0))
  }, 0)

  const byUnderlying: Record<string, number> = {}
  for (const t of mainTrades) {
    const cur = livePrice(t, spotPrices) ?? t.current_price ?? t.entry_price
    const p = cur != null ? livePnl(t, cur) : (t.unrealized_pnl ?? 0)
    byUnderlying[t.underlying] = (byUnderlying[t.underlying] ?? 0) + p
  }

  const liveCount = Object.values(spotPrices).filter(v => v > 0).length

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '10px 14px', marginBottom: 12,
      background: 'var(--bg2)', borderRadius: 6, border: `1px solid ${totalPnl >= 0 ? 'rgba(38,166,154,0.3)' : 'rgba(239,83,80,0.3)'}` }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Unrealized P&L</div>
        <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'monospace', color: totalPnl >= 0 ? 'var(--up)' : 'var(--dn)', lineHeight: 1.1 }}>
          {fmtINR(totalPnl)}
        </div>
      </div>
      <div style={{ width: 1, height: 36, background: 'var(--border)' }} />
      {Object.entries(byUnderlying).map(([sym, p]) => (
        <div key={sym}>
          <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{sym}</div>
          <div style={{ fontFamily: 'monospace', fontWeight: 700, color: p >= 0 ? 'var(--up)' : 'var(--dn)', fontSize: 14 }}>{fmtINR(p)}</div>
        </div>
      ))}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: liveCount > 0 ? 'var(--up)' : 'var(--txt3)', animation: liveCount > 0 ? 'pulse 1.5s infinite' : 'none' }} />
        <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{liveCount > 0 ? 'Live prices via WebSocket' : 'Waiting for price feed…'}</span>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Positions() {
  const qc = useQueryClient()
  const [tab, setTab]           = useState<'open' | 'history'>('open')
  const [spotPrices, setSpotPrices] = useState<Record<string, number>>({})
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // WebSocket: live spot prices → used for BS repricing in browser
  useEffect(() => {
    const ws = createPriceSocket(ticks => {
      setSpotPrices(prev => {
        const next = { ...prev }
        for (const [sym, data] of Object.entries(ticks)) {
          if (data.ltp > 0) next[sym.toUpperCase()] = data.ltp
        }
        return next
      })
    })
    wsRef.current = ws
    return () => ws.close()
  }, [])

  // Server MTM refresh every 10s (updates DB prices, triggers auto-close on target/SL hit)
  const mtmRefresh = useQuery({
    queryKey: ['mtm-refresh'],
    queryFn: async () => {
      const data = await refreshMtm()
      setLastRefresh(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
      qc.setQueryData(['open-trades'], data)
      return data
    },
    refetchInterval: 10_000,
    enabled: tab === 'open',
  })

  const { data: openData, isLoading: openLoading } = useQuery({
    queryKey: ['open-trades'],
    queryFn: () => import('../api/client').then(m => m.fetchOpenTrades('paper')),
    staleTime: 5_000,
  })
  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['closed-trades'],
    queryFn: () => import('../api/client').then(m => m.fetchTrades('paper')),
    refetchInterval: 15_000,
  })

  const close = useMutation({
    mutationFn: (id: number) => closeTrade(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['open-trades'] })
      qc.invalidateQueries({ queryKey: ['closed-trades'] })
      qc.invalidateQueries({ queryKey: ['mtm-refresh'] })
    },
  })

  const openTrades:  any[] = openData?.trades ?? []
  const allTrades:   any[] = histData?.trades ?? []
  const closedTrades = allTrades.filter(t => t.status === 'closed')
  const mainClosed   = closedTrades.filter(t => !(t.notes ?? '').includes('spread_leg:hedge'))

  const winners      = mainClosed.filter(t => (t.pnl ?? 0) > 0)
  const losers       = mainClosed.filter(t => (t.pnl ?? 0) <= 0)
  const totalPnl     = mainClosed.reduce((s, t) => s + (t.pnl ?? 0), 0)
  const totalCharges = mainClosed.reduce((s, t) => s + (t.charges_total ?? 0), 0)
  const winRate      = mainClosed.length > 0 ? (winners.length / mainClosed.length) * 100 : 0
  const avgWin       = winners.length > 0 ? winners.reduce((s, t) => s + (t.pnl ?? 0), 0) / winners.length : 0
  const avgLoss      = losers.length > 0 ? Math.abs(losers.reduce((s, t) => s + (t.pnl ?? 0), 0) / losers.length) : 0
  const profitFactor = avgLoss > 0 ? (avgWin * winners.length) / (avgLoss * losers.length) : 0

  const displayTrades = tab === 'open' ? openTrades : closedTrades
  const COLS = tab === 'open'
    ? ['', 'Symbol', 'Type', 'Strike', 'Act', 'Entry → Live', 'Qty', 'Live P&L', 'Charges', 'Entry time', 'DTE', '']
    : ['', 'Symbol', 'Type', 'Strike', 'Act', 'Entry → Exit', 'Qty', 'Net P&L', 'Charges', 'Exit time', 'Reason', '']

  return (
    <div style={{ padding: '16px 20px', maxWidth: 1350, margin: '0 auto' }}>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--txt)' }}>Paper Trading</h2>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {lastRefresh && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>MTM {lastRefresh}</span>}
          {(['open', 'history'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} className={`tv-btn ${tab === t ? 'tv-btn-primary' : 'tv-btn-ghost'}`}
              style={{ fontSize: 11, padding: '4px 14px' }}>
              {t === 'open'
                ? `Open (${openTrades.filter(x => !(x.notes ?? '').includes('hedge')).length})`
                : `History (${mainClosed.length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Live P&L bar — open tab only */}
      {tab === 'open' && openTrades.filter(t => !(t.notes ?? '').includes('hedge')).length > 0 && (
        <LivePnlBar trades={openTrades} spotPrices={spotPrices} />
      )}

      {/* History stats */}
      {tab === 'history' && mainClosed.length > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
          <SummaryCard label="Net P&L" value={fmtINR(totalPnl)} color={totalPnl >= 0 ? 'var(--up)' : 'var(--dn)'} sub={`${mainClosed.length} trades`} />
          <SummaryCard label="Win Rate" value={`${winRate.toFixed(0)}%`} color={winRate >= 50 ? 'var(--up)' : 'var(--dn)'} sub={`${winners.length}W / ${losers.length}L`} />
          <SummaryCard label="Avg Winner" value={fmtINR(avgWin)} color="var(--up)" />
          <SummaryCard label="Avg Loser" value={`-${fmtINR(avgLoss)}`} color="var(--dn)" />
          <SummaryCard label="Profit Factor" value={profitFactor > 0 ? profitFactor.toFixed(2) : '—'}
            color={profitFactor >= 1.5 ? 'var(--up)' : profitFactor >= 1 ? 'var(--orange)' : 'var(--dn)'} sub="gross W / gross L" />
          <SummaryCard label="Total Charges" value={fmtINR(totalCharges)} color="var(--txt3)" sub="brok+STT+GST+txn" />
        </div>
      )}

      {tab === 'open' && openTrades.length === 0 && !openLoading && (
        <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 10 }}>
          Prices update live via WebSocket · Server MTM every 10s · hedge legs shown faded · click any row to drill in
        </div>
      )}

      {(openLoading || histLoading) && <div style={{ color: 'var(--txt2)', fontSize: 13 }}>Loading…</div>}

      {!openLoading && !histLoading && displayTrades.length === 0 && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--txt3)', fontSize: 13,
          background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {tab === 'open' ? 'No open positions. Signals ≥72% confidence are auto-traded in paper mode.' : 'No closed trades yet.'}
        </div>
      )}

      {displayTrades.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--border)', color: 'var(--txt3)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              {COLS.map((h, i) => (
                <th key={i} style={{ padding: '5px 10px', textAlign: 'left', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayTrades.map((t: any) => (
              <TradeRow key={t.id} t={t} spotPrices={spotPrices} onClose={(id) => close.mutate(id)} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
