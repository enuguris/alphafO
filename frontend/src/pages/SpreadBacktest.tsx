import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────
interface LegDetail {
  label: string; action: 'BUY' | 'SELL'; opt_type: string; strike: number
  entry_price: number; exit_price: number; pnl_per_unit: number
}
interface Charges {
  brokerage: number; stt: number; exchange_fee: number
  sebi_fee: number; gst: number; stamp_duty: number; total: number
}
interface TradeRow {
  entry_date: string; exit_date: string; exit_reason: string; spot: number
  net_credit: number; spread_width: number; capital_used: number
  pnl: number; pnl_after_charges: number; pnl_on_capital_pct: number
  charges: Charges; hold_days: number; iv_rank: number; iv_pct: number
  reason: string; leg_details: LegDetail[]; legs: string[]
}
interface StrategyResult {
  strategy: string; lot_size?: number; trades: number
  win_rate?: number; profit_factor?: number; total_pnl?: number
  avg_credit?: number; avg_win?: number; avg_loss?: number
  avg_hold_days?: number; avg_capital_used?: number; avg_pnl_pct?: number
  total_charges?: number; max_drawdown?: number
  exit_counts?: { take_profit: number; stop_loss: number; expiry: number }
  equity_curve?: { date: string; equity: number }[]
  recent_trades?: TradeRow[]
}
interface UnderlyingResult {
  underlying: string; bars: number; step: number; lot_size?: number
  error?: string; strategies: StrategyResult[]
}
interface BacktestData {
  results: UnderlyingResult[]; run_at_ist: string
  from_date: string | null; to_date: string | null
  data_start: string | null; data_end: string | null; version: string
}
interface SavedMeta {
  id: string; name: string; from_date: string | null
  to_date: string | null; saved_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const STRATEGY_META: Record<string, { color: string; shortDesc: string }> = {
  BullPut:       { color: '#26c6a0', shortDesc: 'Sell ATM PE + Buy OTM PE (bullish credit)' },
  BearCall:      { color: '#ff7043', shortDesc: 'Sell ATM CE + Buy OTM CE (bearish credit)' },
  IronCondor:    { color: '#5b9bff', shortDesc: 'Sell OTM strangle + Buy wings (range/theta)' },
  BullCallDebit: { color: '#66bb6a', shortDesc: 'Buy ATM CE + Sell OTM CE (bullish, low IV)' },
  BearPutDebit:  { color: '#ef5350', shortDesc: 'Buy ATM PE + Sell OTM PE (bearish, low IV)' },
  IronButterfly: { color: '#ab47bc', shortDesc: 'Sell ATM straddle + wings (pin, high IV)' },
}
const ALL_STRATEGIES = Object.keys(STRATEGY_META)
const EXIT_COLOR: Record<string, string> = {
  take_profit: 'var(--up)', stop_loss: 'var(--dn)', expiry: 'var(--txt3)',
}
const pnlColor  = (v: number) => v >= 0 ? 'var(--up)' : 'var(--dn)'
const fmtRs     = (v: number, d = 1) => `₹${v >= 0 ? '+' : ''}${v.toFixed(d)}`
const fmtAbs    = (v: number) => `₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pctS      = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

function Sparkline({ data, color }: { data: { equity: number }[]; color: string }) {
  if (!data || data.length < 2) return null
  const vals = data.map(d => d.equity)
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1
  const W = 100, H = 28
  const pts = vals.map((v, i) =>
    `${((i / (vals.length - 1)) * W).toFixed(1)},${(H - ((v - min) / range) * H).toFixed(1)}`
  ).join(' ')
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 1, textTransform: 'uppercase', letterSpacing: '0.04em', whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: color ?? 'var(--txt)', fontFamily: 'monospace' }}>{value}</div>
    </div>
  )
}

// ── Trade detail (expanded) ───────────────────────────────────────────────────
function TradeDetail({ t, lot }: { t: TradeRow; lot: number }) {
  const [showReason, setShowReason] = useState(false)
  return (
    <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '12px 14px', margin: '4px 0' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--txt2)' }}>{t.entry_date} → {t.exit_date}</span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
          color: EXIT_COLOR[t.exit_reason],
          background: `color-mix(in srgb, ${EXIT_COLOR[t.exit_reason]} 12%, transparent)` }}>
          {t.exit_reason.replace('_', ' ').toUpperCase()}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--txt3)' }}>
          Spot ₹{t.spot.toLocaleString('en-IN')} · IV {t.iv_pct}% · IVR {(t.iv_rank * 100).toFixed(0)}% · {t.hold_days}d
        </span>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, marginBottom: 10 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['Leg', 'Action', 'Strike', 'Entry px', 'Exit px', 'P&L/unit', `P&L ×${lot}`].map(h => (
              <th key={h} style={{ padding: '3px 6px', textAlign: h.startsWith('P') || h === 'Strike' || h.includes('px') ? 'right' : 'left',
                color: 'var(--txt3)', fontWeight: 500, fontSize: 10 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(t.leg_details ?? []).map((leg, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--border2)' }}>
              <td style={{ padding: '4px 6px', fontFamily: 'monospace', fontWeight: 700, color: 'var(--txt)' }}>{leg.label}</td>
              <td style={{ padding: '4px 6px' }}>
                <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                  color: leg.action === 'SELL' ? 'var(--dn)' : 'var(--up)',
                  background: `color-mix(in srgb, ${leg.action === 'SELL' ? 'var(--dn)' : 'var(--up)'} 12%, transparent)` }}>
                  {leg.action}
                </span>
              </td>
              <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace' }}>₹{leg.strike.toLocaleString('en-IN')}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>₹{leg.entry_price.toFixed(2)}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>₹{leg.exit_price.toFixed(2)}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: pnlColor(leg.pnl_per_unit) }}>{fmtRs(leg.pnl_per_unit, 2)}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: pnlColor(leg.pnl_per_unit) }}>{fmtRs(leg.pnl_per_unit * lot, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        {[
          ['Net Credit/unit', `₹${t.net_credit.toFixed(2)}`, 'var(--up)'],
          ['Capital Used',    fmtAbs(t.capital_used),         'var(--txt)'],
          ['Gross P&L',       fmtRs(t.pnl * lot, 0),          pnlColor(t.pnl)],
          ['Charges',         `-₹${t.charges.total.toFixed(2)}`,'var(--dn)'],
          ['Net P&L',         fmtRs(t.pnl_after_charges * lot, 0), pnlColor(t.pnl_after_charges)],
          ['% on Capital',    pctS(t.pnl_on_capital_pct),     pnlColor(t.pnl_on_capital_pct)],
        ].map(([label, value, color]) => (
          <div key={label} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, padding: '6px 10px' }}>
            <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 1, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
            <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'monospace', color: color as string }}>{value}</div>
          </div>
        ))}
      </div>

      <details style={{ marginBottom: 6 }}>
        <summary style={{ fontSize: 10, color: 'var(--txt3)', cursor: 'pointer', userSelect: 'none' }}>
          Charges — Total ₹{t.charges.total.toFixed(2)}
        </summary>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, paddingLeft: 8, flexWrap: 'wrap', fontSize: 10, color: 'var(--txt3)' }}>
          {[['Brokerage', t.charges.brokerage], ['STT', t.charges.stt], ['Exchange', t.charges.exchange_fee],
            ['SEBI', t.charges.sebi_fee], ['GST', t.charges.gst], ['Stamp', t.charges.stamp_duty]].map(([l, v]) => (
            <span key={l as string}><span style={{ color: 'var(--txt2)' }}>{l}</span>: ₹{(v as number).toFixed(2)}</span>
          ))}
        </div>
      </details>

      <button onClick={() => setShowReason(v => !v)}
        style={{ fontSize: 10, color: 'var(--txt3)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>
        {showReason ? '▲ Hide reason' : '▼ Why this trade?'}
      </button>
      {showReason && (
        <div style={{ marginTop: 6, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 5,
          fontSize: 11, color: 'var(--txt2)', lineHeight: 1.6, borderLeft: '3px solid var(--border)' }}>
          {t.reason}
        </div>
      )}
    </div>
  )
}

// ── Strategy card ─────────────────────────────────────────────────────────────
function StrategyCard({ s, expanded, onToggle }: { s: StrategyResult; expanded: boolean; onToggle: () => void }) {
  const [expandedTrade, setExpandedTrade] = useState<number | null>(null)
  const meta = STRATEGY_META[s.strategy] ?? { color: '#aaa', shortDesc: '' }
  const lot  = s.lot_size ?? 1

  if (!s.trades) return (
    <div style={{ padding: '10px 14px', color: 'var(--txt3)', fontSize: 12, background: 'var(--bg2)',
      border: '1px solid var(--border)', borderRadius: 8 }}>
      {s.strategy}: no trades matched signal conditions in this date range
    </div>
  )

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg2)' }}>
      <div onClick={onToggle} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
        cursor: 'pointer', background: expanded ? 'var(--bg3)' : 'var(--bg2)',
        borderBottom: expanded ? '1px solid var(--border)' : 'none' }}>
        <div style={{ width: 3, height: 40, borderRadius: 2, background: meta.color, flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--txt)' }}>{s.strategy}</span>
            <span style={{ fontSize: 10, color: 'var(--txt3)' }}>{meta.shortDesc}</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 2 }}>
            {s.trades} trades · lot {lot} · avg {s.avg_hold_days}d · charges ₹{s.total_charges?.toFixed(0)}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <Stat label="Win Rate"     value={`${s.win_rate?.toFixed(1)}%`}
            color={(s.win_rate ?? 0) >= 60 ? 'var(--up)' : (s.win_rate ?? 0) >= 45 ? 'var(--orange)' : 'var(--dn)'} />
          <Stat label="Avg % Cap"    value={pctS(s.avg_pnl_pct ?? 0)} color={pnlColor(s.avg_pnl_pct ?? 0)} />
          <Stat label="Profit Factor" value={`${s.profit_factor?.toFixed(2)}x`}
            color={(s.profit_factor ?? 0) >= 1.5 ? 'var(--up)' : (s.profit_factor ?? 0) >= 1 ? 'var(--orange)' : 'var(--dn)'} />
          <Stat label="Net P&L"      value={fmtAbs(s.total_pnl ?? 0)} color={pnlColor(s.total_pnl ?? 0)} />
          <Sparkline data={s.equity_curve ?? []} color={meta.color} />
        </div>
        <span style={{ color: 'var(--txt3)', fontSize: 12, marginLeft: 6 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && (
        <div style={{ padding: '14px 16px' }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
            {[
              ['Avg Capital/trade', fmtAbs(s.avg_capital_used ?? 0)],
              ['Avg Credit/unit', `₹${s.avg_credit}`],
              ['Avg Win (net)', fmtRs((s.avg_win ?? 0) * lot, 0)],
              ['Avg Loss (net)', fmtRs((s.avg_loss ?? 0) * lot, 0)],
              ['Total Charges', `₹${s.total_charges?.toFixed(0)}`],
              ['Max Drawdown', fmtAbs(s.max_drawdown ?? 0)],
              ['TP exits', `${s.exit_counts?.take_profit}`],
              ['SL exits', `${s.exit_counts?.stop_loss}`],
              ['Expiry exits', `${s.exit_counts?.expiry}`],
            ].map(([label, value]) => (
              <div key={label} style={{ background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 5, padding: '6px 10px' }}>
                <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 2, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'monospace', color: 'var(--txt)' }}>{value}</div>
              </div>
            ))}
          </div>

          {s.exit_counts && s.trades > 0 && (() => {
            const tp = (s.exit_counts.take_profit / s.trades) * 100
            const sl = (s.exit_counts.stop_loss   / s.trades) * 100
            const ex = (s.exit_counts.expiry       / s.trades) * 100
            return (
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', height: 7, borderRadius: 3, overflow: 'hidden', gap: 1, marginBottom: 4 }}>
                  <div style={{ width: `${tp}%`, background: 'var(--up)' }} title={`TP ${tp.toFixed(0)}%`} />
                  <div style={{ width: `${sl}%`, background: 'var(--dn)' }} title={`SL ${sl.toFixed(0)}%`} />
                  <div style={{ width: `${ex}%`, background: 'var(--txt3)' }} title={`Expiry ${ex.toFixed(0)}%`} />
                </div>
                <div style={{ display: 'flex', gap: 10, fontSize: 9, color: 'var(--txt3)' }}>
                  <span><span style={{ color: 'var(--up)' }}>■</span> TP {tp.toFixed(0)}%</span>
                  <span><span style={{ color: 'var(--dn)' }}>■</span> SL {sl.toFixed(0)}%</span>
                  <span><span style={{ color: 'var(--txt3)' }}>■</span> Expiry {ex.toFixed(0)}%</span>
                </div>
              </div>
            )
          })()}

          <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Trades (last 20) — click to expand
          </div>
          {(s.recent_trades ?? []).slice().reverse().map((t, idx) => (
            <div key={idx}>
              <div onClick={() => setExpandedTrade(expandedTrade === idx ? null : idx)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', cursor: 'pointer',
                  borderRadius: 4, marginBottom: 2,
                  background: expandedTrade === idx ? 'var(--bg3)' : 'transparent',
                  border: `1px solid ${expandedTrade === idx ? 'var(--border)' : 'transparent'}` }}>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--txt3)', width: 68 }}>{t.entry_date}</span>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--txt3)', width: 68 }}>{t.exit_date}</span>
                <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, width: 76, textAlign: 'center',
                  color: EXIT_COLOR[t.exit_reason],
                  background: `color-mix(in srgb, ${EXIT_COLOR[t.exit_reason]} 12%, transparent)` }}>
                  {t.exit_reason.replace('_', ' ').toUpperCase()}
                </span>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--txt2)', width: 76 }}>₹{t.spot.toLocaleString('en-IN')}</span>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--up)', width: 52 }}>cr ₹{t.net_credit.toFixed(1)}</span>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--txt2)', width: 64 }}>cap ₹{(t.capital_used / 1000).toFixed(1)}k</span>
                <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: pnlColor(t.pnl_after_charges), width: 64 }}>
                  {fmtRs(t.pnl_after_charges * lot, 0)}
                </span>
                <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: pnlColor(t.pnl_on_capital_pct) }}>
                  {pctS(t.pnl_on_capital_pct)}
                </span>
                <span style={{ marginLeft: 'auto', color: 'var(--txt3)', fontSize: 10 }}>{expandedTrade === idx ? '▲' : '▼'}</span>
              </div>
              {expandedTrade === idx && <TradeDetail t={t} lot={lot} />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Summary table ─────────────────────────────────────────────────────────────
function SummaryTable({ data }: { data: BacktestData }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--border)' }}>
            <th style={{ padding: '7px 10px', textAlign: 'left', color: 'var(--txt3)', fontSize: 10, fontWeight: 600 }}>Strategy</th>
            {data.results.map(r =>
              ['Win%', 'PF', 'Avg%Cap', 'Net P&L', 'Charges', 'Trades'].map(h => (
                <th key={`${r.underlying}-${h}`} style={{ padding: '7px 6px', textAlign: 'right', color: 'var(--txt3)', fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  {r.underlying} {h}
                </th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {ALL_STRATEGIES.map(strat => (
            <tr key={strat} style={{ borderBottom: '1px solid var(--border2)' }}>
              <td style={{ padding: '7px 10px', fontWeight: 700, color: STRATEGY_META[strat]?.color }}>{strat}</td>
              {data.results.map(r => {
                const s = r.strategies.find(s => s.strategy === strat)
                if (!s?.trades) return ['–','–','–','–','–','0'].map((v, i) => (
                  <td key={i} style={{ padding: '6px 6px', textAlign: 'right', color: 'var(--txt3)', fontFamily: 'monospace', fontSize: 11 }}>{v}</td>
                ))
                return [
                  <td key="wr"  style={{ padding: '6px 6px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, fontSize: 11, color: s.win_rate! >= 60 ? 'var(--up)' : s.win_rate! >= 45 ? 'var(--orange)' : 'var(--dn)' }}>{s.win_rate?.toFixed(1)}%</td>,
                  <td key="pf"  style={{ padding: '6px 6px', textAlign: 'right', fontFamily: 'monospace', fontSize: 11, color: s.profit_factor! >= 1.5 ? 'var(--up)' : s.profit_factor! >= 1 ? 'var(--orange)' : 'var(--dn)' }}>{s.profit_factor?.toFixed(2)}x</td>,
                  <td key="ap"  style={{ padding: '6px 6px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, fontSize: 11, color: pnlColor(s.avg_pnl_pct ?? 0) }}>{pctS(s.avg_pnl_pct ?? 0)}</td>,
                  <td key="pnl" style={{ padding: '6px 6px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, fontSize: 11, color: pnlColor(s.total_pnl ?? 0) }}>{fmtAbs(s.total_pnl ?? 0)}</td>,
                  <td key="ch"  style={{ padding: '6px 6px', textAlign: 'right', fontFamily: 'monospace', fontSize: 11, color: 'var(--dn)' }}>₹{s.total_charges?.toFixed(0)}</td>,
                  <td key="tr"  style={{ padding: '6px 6px', textAlign: 'right', color: 'var(--txt2)', fontSize: 11 }}>{s.trades}</td>,
                ]
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function SpreadBacktest() {
  const [data,      setData]      = useState<BacktestData | null>(null)
  const [running,   setRunning]   = useState(false)
  const [runError,  setRunError]  = useState<string | null>(null)
  const [dataRange, setDataRange] = useState<{ data_start: string; data_end: string; bars: number } | null>(null)
  const [savedList, setSavedList] = useState<SavedMeta[]>([])
  const [saveName,  setSaveName]  = useState('')
  const [saving,    setSaving]    = useState(false)
  const [saveMsg,   setSaveMsg]   = useState<string | null>(null)
  const [expanded,  setExpanded]  = useState<Record<string, boolean>>({})
  const [activeUl,  setActiveUl]  = useState('NIFTY')
  const [fromDate,  setFromDate]  = useState('')
  const [toDate,    setToDate]    = useState('')
  const [showSaved, setShowSaved] = useState(false)

  // Load data range info + saved list on mount — NO backtest run
  useEffect(() => {
    api.get('/backtest/credit-spreads/data-range').then(r => setDataRange(r.data)).catch(() => {})
    api.get('/backtest/credit-spreads/saved').then(r => setSavedList(r.data.saved ?? [])).catch(() => {})
  }, [])

  const runBacktest = useCallback(async () => {
    setRunning(true); setRunError(null); setSaveMsg(null)
    try {
      const params = new URLSearchParams()
      if (fromDate) params.set('from_date', fromDate)
      if (toDate)   params.set('to_date',   toDate)
      const qs = params.toString() ? `?${params}` : ''
      const res = await api.post(`/backtest/credit-spreads/run${qs}`)
      setData(res.data)
      setSaveName('')
    } catch (e: any) {
      setRunError(e?.response?.data?.detail ?? e?.message ?? 'Backtest failed')
    } finally {
      setRunning(false)
    }
  }, [fromDate, toDate])

  const loadSaved = useCallback(async (id: string) => {
    setRunning(true); setRunError(null); setSaveMsg(null)
    try {
      const res = await api.get(`/backtest/credit-spreads/saved/${id}`)
      setData(res.data)
      setShowSaved(false)
    } catch (e: any) {
      setRunError('Failed to load saved run')
    } finally {
      setRunning(false)
    }
  }, [])

  const deleteSaved = useCallback(async (id: string) => {
    try {
      await api.delete(`/backtest/credit-spreads/saved/${id}`)
      setSavedList(prev => prev.filter(s => s.id !== id))
    } catch {}
  }, [])

  const saveResult = useCallback(async () => {
    if (!saveName.trim() || !data) return
    setSaving(true); setSaveMsg(null)
    try {
      const params = new URLSearchParams({ name: saveName.trim() })
      if (data.from_date) params.set('from_date', data.from_date)
      if (data.to_date)   params.set('to_date',   data.to_date)
      await api.post(`/backtest/credit-spreads/save?${params}`)
      setSaveMsg(`Saved as "${saveName.trim()}"`)
      setSaveName('')
      const r = await api.get('/backtest/credit-spreads/saved')
      setSavedList(r.data.saved ?? [])
    } catch (e: any) {
      setSaveMsg(e?.response?.data?.detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [saveName, data])

  const toggle = (key: string) => setExpanded(prev => ({ ...prev, [key]: !prev[key] }))
  const ulResult = data?.results.find(r => r.underlying === activeUl)
  const minDate = dataRange?.data_start
  const maxDate = dataRange?.data_end

  return (
    <div style={{ padding: '16px 20px', maxWidth: 1400, margin: '0 auto' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--txt)' }}>Credit Spread Backtest</h2>
          <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 2 }}>
            Bull Put · Bear Call · Iron Condor — P&L after all charges · 6% capital target per trade
          </div>
        </div>

        {/* Saved runs button */}
        <button onClick={() => setShowSaved(v => !v)} className="tv-btn tv-btn-ghost"
          style={{ padding: '5px 12px', fontSize: 11, position: 'relative' }}>
          Saved Runs {savedList.length > 0 && (
            <span style={{ marginLeft: 6, background: 'var(--up)', color: '#000', borderRadius: 10,
              fontSize: 9, padding: '1px 5px', fontWeight: 700 }}>{savedList.length}</span>
          )}
        </button>
      </div>

      {/* ── Available data notice ── */}
      {dataRange && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
          background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 7, marginBottom: 14, flexWrap: 'wrap' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--up)', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: 'var(--txt3)' }}>
            Historical bhav data available:
            <strong style={{ color: 'var(--txt2)', marginLeft: 5, fontFamily: 'monospace' }}>{dataRange.data_start}</strong>
            <span style={{ margin: '0 4px', color: 'var(--txt3)' }}>→</span>
            <strong style={{ color: 'var(--txt2)', fontFamily: 'monospace' }}>{dataRange.data_end}</strong>
            <span style={{ marginLeft: 8, color: 'var(--txt3)' }}>({dataRange.bars} bars)</span>
          </span>
          <span style={{ fontSize: 11, color: 'var(--orange)' }}>
            ⚠ Dates outside this window will return no results
          </span>
          <button onClick={() => { setFromDate(dataRange.data_start); setToDate(dataRange.data_end) }}
            style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--up)', background: 'none', border: 'none',
              cursor: 'pointer', textDecoration: 'underline', padding: 0 }}>
            Use full range
          </button>
        </div>
      )}

      {/* ── Run panel ── */}
      <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>Run New Backtest</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: 'var(--txt3)' }}>From</label>
          <input type="date" value={fromDate} min={minDate} max={maxDate}
            onChange={e => setFromDate(e.target.value)}
            style={{ fontSize: 11, padding: '5px 8px', borderRadius: 4, border: '1px solid var(--border)',
              background: 'var(--bg3)', color: 'var(--txt)', cursor: 'pointer' }} />
          <label style={{ fontSize: 11, color: 'var(--txt3)' }}>To</label>
          <input type="date" value={toDate} min={minDate} max={maxDate}
            onChange={e => setToDate(e.target.value)}
            style={{ fontSize: 11, padding: '5px 8px', borderRadius: 4, border: '1px solid var(--border)',
              background: 'var(--bg3)', color: 'var(--txt)', cursor: 'pointer' }} />
          <span style={{ fontSize: 10, color: 'var(--txt3)' }}>Leave blank to use all available data</span>
          <button onClick={runBacktest} disabled={running} className="tv-btn"
            style={{ padding: '6px 18px', fontSize: 12, fontWeight: 700, opacity: running ? 0.5 : 1 }}>
            {running ? '⌛ Running…' : '▶ Run Backtest'}
          </button>
        </div>
        {runError && (
          <div style={{ marginTop: 10, padding: '8px 12px', background: 'color-mix(in srgb, var(--dn) 10%, transparent)',
            border: '1px solid var(--dn)', borderRadius: 5, color: 'var(--dn)', fontSize: 11 }}>
            {runError}
          </div>
        )}
        {running && (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--txt3)' }}>
            Running backtest on historical bhav data — typically 15–30 seconds…
          </div>
        )}
      </div>

      {/* ── Saved runs panel ── */}
      {showSaved && (
        <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>Saved Runs</div>
          {savedList.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--txt3)' }}>No saved runs yet. Run a backtest and click Save.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {savedList.map(s => (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10,
                  padding: '7px 10px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 5 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--txt)' }}>{s.name}</div>
                    <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                      {s.from_date ?? 'all'} → {s.to_date ?? 'all'} · saved {s.saved_at}
                    </div>
                  </div>
                  <button onClick={() => loadSaved(s.id)} className="tv-btn"
                    style={{ padding: '4px 12px', fontSize: 11 }}>Load</button>
                  <button onClick={() => deleteSaved(s.id)}
                    style={{ padding: '4px 8px', fontSize: 11, background: 'none', border: '1px solid var(--border)',
                      borderRadius: 4, color: 'var(--dn)', cursor: 'pointer' }}>✕</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Results ── */}
      {!data && !running && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--txt3)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--txt2)', marginBottom: 6 }}>No results yet</div>
          <div style={{ fontSize: 12 }}>Set a date range above and click <strong>▶ Run Backtest</strong></div>
          {savedList.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12 }}>
              Or <button onClick={() => setShowSaved(true)}
                style={{ color: 'var(--up)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: 12 }}>
                load a saved run
              </button>
            </div>
          )}
        </div>
      )}

      {data && (
        <>
          {/* Result header + save controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 11, color: 'var(--txt3)' }}>
              Results for <strong style={{ color: 'var(--txt2)', fontFamily: 'monospace' }}>
                {data.from_date ?? dataRange?.data_start ?? '…'} → {data.to_date ?? dataRange?.data_end ?? '…'}
              </strong>
              <span style={{ marginLeft: 8 }}>· Run {data.run_at_ist}</span>
            </div>
            <div style={{ flex: 1 }} />
            {/* Save controls */}
            <input value={saveName} onChange={e => setSaveName(e.target.value)}
              placeholder="Name this run…"
              style={{ fontSize: 11, padding: '5px 10px', borderRadius: 4, border: '1px solid var(--border)',
                background: 'var(--bg2)', color: 'var(--txt)', width: 160 }} />
            <button onClick={saveResult} disabled={saving || !saveName.trim()} className="tv-btn"
              style={{ padding: '5px 12px', fontSize: 11, opacity: !saveName.trim() ? 0.4 : 1 }}>
              {saving ? '…' : '💾 Save'}
            </button>
            {saveMsg && <span style={{ fontSize: 11, color: saveMsg.includes('ailed') ? 'var(--dn)' : 'var(--up)' }}>{saveMsg}</span>}
          </div>

          {/* Summary */}
          <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, marginBottom: 16 }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700, color: 'var(--txt)' }}>
              Summary — Net P&L after charges · Avg % return on capital deployed
            </div>
            <SummaryTable data={data} />
          </div>

          {/* Underlying tabs */}
          <div style={{ display: 'flex', gap: 2, marginBottom: 14 }}>
            {data.results.map(r => (
              <button key={r.underlying} onClick={() => setActiveUl(r.underlying)}
                className={`tv-btn ${activeUl === r.underlying ? '' : 'tv-btn-ghost'}`}
                style={{ padding: '5px 16px', fontSize: 12, fontWeight: activeUl === r.underlying ? 700 : 400 }}>
                {r.underlying}
                {r.bars > 0 && <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--txt3)', fontWeight: 400 }}>{r.bars} bars</span>}
              </button>
            ))}
          </div>

          {/* Error for this underlying */}
          {ulResult?.error && (
            <div style={{ padding: '12px 14px', background: 'color-mix(in srgb, var(--orange) 10%, transparent)',
              border: '1px solid var(--orange)', borderRadius: 8, color: 'var(--orange)', fontSize: 12, marginBottom: 12 }}>
              {ulResult.error}
              {dataRange && (
                <div style={{ marginTop: 5, fontSize: 11, color: 'var(--txt2)' }}>
                  Valid range: <strong>{dataRange.data_start}</strong> → <strong>{dataRange.data_end}</strong>
                  <button onClick={() => { setFromDate(dataRange.data_start); setToDate(dataRange.data_end) }}
                    style={{ marginLeft: 8, fontSize: 11, color: 'var(--up)', background: 'none', border: 'none',
                      cursor: 'pointer', textDecoration: 'underline', padding: 0 }}>use this range</button>
                </div>
              )}
            </div>
          )}

          {/* Strategy cards */}
          {ulResult && !ulResult.error && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {ulResult.strategies.map(s => (
                <StrategyCard key={s.strategy} s={s}
                  expanded={!!expanded[`${activeUl}-${s.strategy}`]}
                  onToggle={() => toggle(`${activeUl}-${s.strategy}`)} />
              ))}
            </div>
          )}

          <div style={{ marginTop: 20, padding: '10px 14px', background: 'var(--bg2)', border: '1px solid var(--border)',
            borderRadius: 8, fontSize: 11, color: 'var(--txt3)', lineHeight: 1.7 }}>
            <strong style={{ color: 'var(--txt2)' }}>Methodology:</strong>{' '}
            One trade per strategy per 7-bar window. BullPut/BearCall: price vs 10-SMA. IronCondor: IV rank &gt; 40%.
            Target +6% on capital = max(nc×0.70, capital×6%). Stop −50% of max risk.
            Premiums via Black-Scholes on historical IV. Expiry = nearest Tuesday ≥ 7 DTE.
            Charges: brokerage ₹20/order, STT 0.1% sell-side, NSE 0.053%, GST 18%, SEBI fee, stamp duty.
          </div>
        </>
      )}

      {/* ── Intraday strangle backtest — REAL Kite 30-min candles ── */}
      <StrangleIntradaySection />
    </div>
  )
}

function StrangleIntradaySection() {
  const [data, setData]     = useState<any>(null)
  const [running, setRun]   = useState(false)
  const [err, setErr]       = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [sortAsc, setSortAsc] = useState(false)   // false = newest first
  const [fFrom, setFFrom] = useState('')
  const [fTo, setFTo] = useState('')

  useEffect(() => {
    api.get('/backtest/strangle-intraday').then(r => { if (r.data?.trades) setData(r.data) }).catch(() => {})
  }, [])

  const run = async () => {
    setRun(true); setErr(null)
    try {
      const r = await api.post('/backtest/strangle-intraday/run', {}, { timeout: 600000 })
      setData(r.data)
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? 'Run failed (Kite token valid today?)')
    } finally { setRun(false) }
  }

  // Date-range filter over the cached full run — instant, no re-fetch
  const allRows = data?.trade_rows ?? []
  const filtered = allRows.filter((t: any) =>
    (!fFrom || t.entry_date >= fFrom) && (!fTo || t.entry_date <= fTo))
  const rows = [...filtered].sort((a: any, b: any) =>
    sortAsc ? a.entry_date.localeCompare(b.entry_date) : b.entry_date.localeCompare(a.entry_date))
  const visible = showAll ? rows : rows.slice(0, 10)

  // Recompute summary stats over the filtered range (hold + stop variants)
  const stats = (key: 'net' | 'net_stop') => {
    const nets = filtered.map((t: any) => t[key] ?? t.net)
    if (!nets.length) return null
    const wins = nets.filter((n: number) => n > 0)
    const loss = nets.filter((n: number) => n <= 0)
    let eq = 0, peak = 0, dd = 0
    for (const t of [...filtered].sort((a: any, b: any) => a.entry_date.localeCompare(b.entry_date))) {
      eq += t[key] ?? t.net; peak = Math.max(peak, eq); dd = Math.min(dd, eq - peak)
    }
    return {
      n: nets.length,
      win: (wins.length / nets.length) * 100,
      pf: loss.length ? wins.reduce((a: number, b: number) => a + b, 0) / Math.abs(loss.reduce((a: number, b: number) => a + b, 0)) : 99,
      net: nets.reduce((a: number, b: number) => a + b, 0),
      avg: nets.reduce((a: number, b: number) => a + b, 0) / nets.length,
      worst: Math.min(...nets),
      dd: Math.abs(dd),
    }
  }
  const hold = stats('net')
  const stopV = stats('net_stop')
  const rangeActive = !!(fFrom || fTo)

  const dteOf = (t: any) => {
    try {
      return Math.round((new Date(t.expiry).getTime() - new Date(t.entry_date).getTime()) / 86400000)
    } catch { return null }
  }

  return (
    <div style={{ marginTop: 24, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--txt)' }}>🌙 Overnight Strangle — REAL Kite 30-min candles</span>
        <span style={{ fontSize: 10, color: 'var(--txt3)' }}>
          sell 2.8%-OTM PE + 2.4%-OTM CE on the monthly, exit next close · 1 lot NIFTY
        </span>
        {data?.run_at_ist && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>· run {data.run_at_ist}</span>}
        <button onClick={run} disabled={running} className="tv-btn"
          style={{ marginLeft: 'auto', padding: '5px 14px', fontSize: 11, fontWeight: 700, opacity: running ? 0.5 : 1 }}>
          {running ? '⌛ Fetching real candles (~3 min)…' : '▶ Run on real data'}
        </button>
      </div>

      {err && <div style={{ padding: '10px 14px', color: 'var(--dn)', fontSize: 11 }}>{err}</div>}
      {!data && !err && !running && (
        <div style={{ padding: '14px', fontSize: 11, color: 'var(--txt3)' }}>
          Not run yet today. Uses real Kite 30-minute option prices for active contracts —
          window is limited to the current monthly's lifetime (expired option data is not
          available from any free API).
        </div>
      )}

      {data?.trades > 0 && (
        <div style={{ padding: '12px 14px' }}>
          {/* Date-range filter — instant, works on the cached full run */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Range</span>
            <input type="date" value={fFrom} min={data.window?.from} max={data.window?.to}
              onChange={e => setFFrom(e.target.value)}
              style={{ fontSize: 11, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--txt)' }} />
            <span style={{ fontSize: 11, color: 'var(--txt3)' }}>→</span>
            <input type="date" value={fTo} min={data.window?.from} max={data.window?.to}
              onChange={e => setFTo(e.target.value)}
              style={{ fontSize: 11, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--txt)' }} />
            {rangeActive && (
              <>
                <span style={{ fontSize: 11, color: 'var(--txt2)' }}>{filtered.length} of {allRows.length} trades</span>
                <button onClick={() => { setFFrom(''); setFTo('') }}
                  style={{ fontSize: 11, color: 'var(--dn)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}>
                  Clear
                </button>
              </>
            )}
            <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--txt3)' }}>
              full data: {data.window?.from} → {data.window?.to}
            </span>
          </div>

          {hold && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
              {[
                ['Trades', String(hold.n), 'var(--txt)'],
                ['Win Rate', `${hold.win.toFixed(1)}%`, hold.win >= 60 ? 'var(--up)' : 'var(--orange)'],
                ['Profit Factor', `${hold.pf.toFixed(2)}x`, hold.pf >= 1.5 ? 'var(--up)' : hold.pf >= 1 ? 'var(--orange)' : 'var(--dn)'],
                ['Net P&L', `₹${Math.round(hold.net).toLocaleString('en-IN')}`, hold.net >= 0 ? 'var(--up)' : 'var(--dn)'],
                ['Avg / trade', `₹${Math.round(hold.avg).toLocaleString('en-IN')}`, hold.avg >= 0 ? 'var(--up)' : 'var(--dn)'],
                ['Worst day', `₹${Math.round(hold.worst).toLocaleString('en-IN')}`, 'var(--dn)'],
                ['Max DD', `₹${Math.round(hold.dd).toLocaleString('en-IN')}`, 'var(--dn)'],
              ].map(([l, v, c]) => (
                <div key={l as string} style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 5, padding: '6px 12px' }}>
                  <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{l}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'monospace', color: c as string }}>{v}</div>
                </div>
              ))}
            </div>
          )}

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th onClick={() => setSortAsc(a => !a)}
                  style={{ padding: '4px 8px', textAlign: 'left', color: 'var(--txt2)', fontWeight: 600,
                    fontSize: 10, cursor: 'pointer', userSelect: 'none' }}
                  title="Click to toggle sort order">
                  Entry {sortAsc ? '▲' : '▼'}
                </th>
                {['Exit', 'Expiry (DTE)', 'Spot', 'Strikes', 'PE in→out', 'CE in→out', 'Credit→Debit', 'Net P&L'].map(h => (
                  <th key={h} style={{ padding: '4px 8px', textAlign: ['Exit', 'Expiry (DTE)', 'Strikes'].includes(h) ? 'left' : 'right',
                    color: 'var(--txt3)', fontWeight: 500, fontSize: 10 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((t: any, i: number) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border2)' }}>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--txt3)' }}>{t.entry_date}</td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--txt3)' }}>{t.exit_date}</td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--orange)' }}>
                    {t.expiry}{dteOf(t) != null && <span style={{ color: 'var(--txt3)' }}> ({dteOf(t)}d)</span>}
                  </td>
                  <td style={{ padding: '4px 8px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>{t.spot?.toLocaleString('en-IN')}</td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--txt)' }}>{t.pe_strike}P / {t.ce_strike}C</td>
                  <td style={{ padding: '4px 8px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>{t.pe_in} → {t.pe_out}</td>
                  <td style={{ padding: '4px 8px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>{t.ce_in} → {t.ce_out}</td>
                  <td style={{ padding: '4px 8px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--txt2)' }}>₹{t.credit} → ₹{t.debit}</td>
                  <td style={{ padding: '4px 8px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700,
                    color: t.net >= 0 ? 'var(--up)' : 'var(--dn)' }}>
                    {t.net >= 0 ? '+' : ''}₹{t.net?.toLocaleString('en-IN')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 10 && (
            <button onClick={() => setShowAll(s => !s)}
              style={{ marginTop: 8, fontSize: 11, color: 'var(--up)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}>
              {showAll ? 'Show last 10' : `Show all ${rows.length} trades`}
            </button>
          )}
          {stopV && data.stop_variant && (
            <div style={{ marginTop: 10, padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 6, fontSize: 11, color: 'var(--txt2)' }}>
              <b>With 2× credit stop-loss{rangeActive ? ' (selected range)' : ''}:</b>{' '}
              win {stopV.win.toFixed(1)}% · PF {stopV.pf.toFixed(2)} ·
              net ₹{Math.round(stopV.net).toLocaleString('en-IN')} ·
              worst ₹{Math.round(stopV.worst).toLocaleString('en-IN')} ·
              maxDD ₹{Math.round(stopV.dd).toLocaleString('en-IN')}
              <span style={{ color: 'var(--txt3)' }}> — stop triggered on {filtered.filter((t: any) => t.stopped).length} of {filtered.length} trades</span>
            </div>
          )}
          {data.stop_spectrum && (
            <div style={{ marginTop: 10, padding: '10px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 6 }}>
                Stop-loss spectrum (full 21-month window) — exit when combined premium hits N× credit
              </div>
              <table style={{ borderCollapse: 'collapse', fontSize: 11 }}>
                <thead><tr>{['Stop level', 'Loss cap', 'Net P&L', 'PF', 'Worst day', 'Max DD', 'Triggered'].map(h => (
                  <th key={h} style={{ padding: '3px 12px 3px 0', textAlign: h === 'Stop level' || h === 'Loss cap' ? 'left' : 'right', color: 'var(--txt3)', fontWeight: 500, fontSize: 10 }}>{h}</th>
                ))}</tr></thead>
                <tbody>
                  <tr style={{ borderTop: '1px solid var(--border2)' }}>
                    <td style={{ padding: '3px 12px 3px 0', color: 'var(--txt2)' }}>No stop (hold)</td>
                    <td style={{ padding: '3px 12px 3px 0', color: 'var(--txt3)' }}>—</td>
                    <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--up)' }}>₹{data.net_pnl?.toLocaleString('en-IN')}</td>
                    <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace' }}>{data.profit_factor}</td>
                    <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--dn)' }}>₹{data.worst?.toLocaleString('en-IN')}</td>
                    <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--dn)' }}>₹{data.max_drawdown?.toLocaleString('en-IN')}</td>
                    <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', color: 'var(--txt3)' }}>—</td>
                  </tr>
                  {data.stop_spectrum.map((s: any) => (
                    <tr key={s.mult} style={{ borderTop: '1px solid var(--border2)' }}>
                      <td style={{ padding: '3px 12px 3px 0', fontFamily: 'monospace', color: 'var(--txt2)' }}>{s.mult}× credit</td>
                      <td style={{ padding: '3px 12px 3px 0', color: 'var(--txt3)' }}>{Math.round((parseFloat(s.mult) - 1) * 100)}% of premium</td>
                      <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: s.net_pnl >= data.net_pnl ? 'var(--up)' : 'var(--orange)' }}>₹{s.net_pnl?.toLocaleString('en-IN')}</td>
                      <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace' }}>{s.profit_factor}</td>
                      <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--dn)' }}>₹{s.worst?.toLocaleString('en-IN')}</td>
                      <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--dn)' }}>₹{s.max_drawdown?.toLocaleString('en-IN')}</td>
                      <td style={{ padding: '3px 12px 3px 0', textAlign: 'right', color: 'var(--txt3)' }}>{s.triggered}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ marginTop: 10, fontSize: 10, color: 'var(--txt3)', lineHeight: 1.6 }}>{data.note}</div>
        </div>
      )}
    </div>
  )
}
