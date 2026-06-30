import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchSignals, fetchPortfolio, fetchTrades, runSignals, initPortfolio,
  scanAll, fetchInstruments, fetchSectors, fetchDataStatus,
  createSignalSocket, createPriceSocket, fetchPreMarket, fetchPatternPerf,
} from '../api/client'
import { useModeStore } from '../store/modeStore'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, BarChart, Bar, Cell } from 'recharts'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Instrument {
  sym: string; name: string; sector: string
  lot_size: number; base_price: number; expiry_type: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const chgStr = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

const PATTERN_COLORS: Record<string, string> = {
  gap_fill: '#7b61ff', pcr_divergence: '#2962ff', mean_reversion: '#00bcd4',
  oi_buildup: '#ff9800', vwap_oi: '#26a69a', iv_crush: '#e91e63',
  max_pain: '#ff5722', expiry_week: '#9c27b0',
}

const TF_LABEL: Record<string, string> = {
  '15m': '15 min', '1h': '1 hr', '4h': '4 hr', 'daily': 'Daily',
}
const TF_COLOR: Record<string, string> = {
  '15m': 'var(--dn)', '1h': 'var(--orange)', '4h': 'var(--blue)', 'daily': 'var(--up)',
}

// ─── Watchlist row ────────────────────────────────────────────────────────────

function WatchRow({ inst, ltp, chg, selected, onSelect }: {
  inst: Instrument; ltp: number; chg: number; selected: boolean; onSelect: () => void
}) {
  const up = chg >= 0
  return (
    <tr onClick={onSelect} className={selected ? 'selected' : ''}>
      <td>
        <div style={{ fontWeight: 700, color: 'var(--txt)', fontSize: 12 }}>{inst.sym}</div>
        <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{inst.name}</div>
      </td>
      <td className="mono" style={{ color: 'var(--txt)', fontWeight: 600 }}>{ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
      <td className={`mono ${up ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>{chgStr(chg)}</td>
      <td style={{ fontSize: 10, color: 'var(--txt3)' }}>{inst.lot_size}L</td>
    </tr>
  )
}

// ─── Trade Quality scorer ─────────────────────────────────────────────────────

function tradeQuality(s: any, spot: number): { score: number; grade: string; color: string; factors: { icon: string; label: string; detail: string; good: boolean }[] } {
  const isCE = s.option_type === 'CE'
  const isPE = s.option_type === 'PE'
  const strike = s.strike ?? 0
  const ivRank = s.iv_rank ?? 0.5
  const dte = s.expiry_dte ?? 7
  const theta = s.theta ?? 0        // negative number, daily decay per unit
  const delta = Math.abs(s.delta ?? 0.3)
  const regime = s.regime_trend ?? 'ranging'
  const entryPremium = s.entry_price ?? 0

  const factors: { icon: string; label: string; detail: string; good: boolean }[] = []
  let score = 0

  // ── 1. Moneyness (25 pts) ──
  let moneynessScore = 0
  let moneynessDetail = ''
  if (spot > 0 && strike > 0) {
    const pctFromStrike = isCE
      ? (spot - strike) / spot * 100   // positive = ITM for CE
      : (strike - spot) / spot * 100   // positive = ITM for PE
    if (pctFromStrike >= 0) {
      moneynessScore = 18; moneynessDetail = `ITM by ${Math.abs(pctFromStrike).toFixed(1)}% — intrinsic value supports premium`
    } else if (pctFromStrike >= -1) {
      moneynessScore = 25; moneynessDetail = `Near ATM (${Math.abs(pctFromStrike).toFixed(1)}% OTM) — highest gamma, best leverage`
    } else if (pctFromStrike >= -2) {
      moneynessScore = 20; moneynessDetail = `${Math.abs(pctFromStrike).toFixed(1)}% OTM — reasonable entry, needs ${Math.abs(pctFromStrike).toFixed(1)}% move`
    } else if (pctFromStrike >= -4) {
      moneynessScore = 12; moneynessDetail = `${Math.abs(pctFromStrike).toFixed(1)}% OTM — needs a significant move`
    } else {
      moneynessScore = 4; moneynessDetail = `Deep OTM (${Math.abs(pctFromStrike).toFixed(1)}%) — low probability, lottery ticket territory`
    }
    factors.push({ icon: '◎', label: 'Moneyness', detail: moneynessDetail, good: moneynessScore >= 18 })
  } else {
    moneynessScore = 12
    factors.push({ icon: '◎', label: 'Moneyness', detail: 'Spot price unavailable — cannot assess moneyness', good: false })
  }
  score += moneynessScore

  // ── 2. IV environment (25 pts) — buying options when IV is low = good ──
  let ivScore = 0
  let ivDetail = ''
  const ivPct = ivRank * 100
  if (ivPct < 20) { ivScore = 25; ivDetail = `IV rank ${ivPct.toFixed(0)}% — cheap premium, ideal to buy options` }
  else if (ivPct < 40) { ivScore = 20; ivDetail = `IV rank ${ivPct.toFixed(0)}% — fair premium, acceptable to buy` }
  else if (ivPct < 60) { ivScore = 12; ivDetail = `IV rank ${ivPct.toFixed(0)}% — elevated IV, you're paying up for options` }
  else if (ivPct < 80) { ivScore = 6; ivDetail = `IV rank ${ivPct.toFixed(0)}% — high IV, premium is expensive` }
  else { ivScore = 2; ivDetail = `IV rank ${ivPct.toFixed(0)}% — very high IV, significant IV crush risk on any pullback` }
  score += ivScore
  factors.push({ icon: '〜', label: 'IV environment', detail: ivDetail, good: ivScore >= 18 })

  // ── 3. Time decay burden (25 pts) ──
  let dteScore = 0
  let dteDetail = ''
  const dailyDecayPct = entryPremium > 0 ? Math.abs(theta) / entryPremium * 100 : 0
  if (dte >= 10 && dte <= 21) { dteScore = 25; dteDetail = `${dte} DTE — sweet spot: enough time for move, theta not brutal yet` }
  else if (dte >= 5 && dte < 10) { dteScore = 18; dteDetail = `${dte} DTE — theta accelerating (≈${dailyDecayPct.toFixed(1)}%/day of premium), needs quick move` }
  else if (dte >= 22 && dte <= 45) { dteScore = 18; dteDetail = `${dte} DTE — plenty of time but you're paying for it in theta` }
  else if (dte >= 2 && dte < 5) { dteScore = 8; dteDetail = `${dte} DTE — very high theta risk (≈${dailyDecayPct.toFixed(1)}%/day), needs move today` }
  else if (dte < 2) { dteScore = 2; dteDetail = `Expiring ${dte === 1 ? 'tomorrow' : 'today'} — extreme gamma/theta, binary bet only` }
  else { dteScore = 12; dteDetail = `${dte} DTE — long-dated, slow movement in premium` }
  score += dteScore
  factors.push({ icon: '⏱', label: 'Time to expiry', detail: dteDetail, good: dteScore >= 18 })

  // ── 4. Regime alignment (25 pts) ──
  let regimeScore = 0
  let regimeDetail = ''
  const aligned = (isCE && regime === 'bullish') || (isPE && regime === 'bearish')
  const opposed = (isCE && regime === 'bearish') || (isPE && regime === 'bullish')
  if (aligned) { regimeScore = 25; regimeDetail = `${regime} regime aligns with ${s.option_type} — trend is in your favour` }
  else if (opposed) { regimeScore = 5; regimeDetail = `${regime} regime opposes ${s.option_type} — you're trading against the trend` }
  else { regimeScore = 13; regimeDetail = `Ranging market — directional option needs a catalyst to work` }
  score += regimeScore
  factors.push({ icon: '⟳', label: 'Regime alignment', detail: regimeDetail, good: regimeScore >= 18 })

  // Grade
  let grade: string, color: string
  if (score >= 78) { grade = 'Strong entry'; color = 'var(--up)' }
  else if (score >= 58) { grade = 'Fair entry'; color = 'var(--orange)' }
  else if (score >= 38) { grade = 'Weak entry'; color = '#ff9800' }
  else { grade = 'Poor entry'; color = 'var(--dn)' }

  return { score, grade, color, factors }
}

function TradeQualityPanel({ s, spot }: { s: any; spot: number }) {
  const { score, grade, color, factors } = tradeQuality(s, spot)
  const barW = `${score}%`

  return (
    <div style={{ margin: '10px 0', padding: 10, borderRadius: 6, background: 'var(--bg3)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Entry Quality</div>
          <div style={{ height: 6, borderRadius: 3, background: 'var(--bg2)', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: barW, background: color, borderRadius: 3, transition: 'width 0.6s ease' }} />
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div className="mono" style={{ fontSize: 20, fontWeight: 700, color, lineHeight: 1 }}>{score}</div>
          <div style={{ fontSize: 10, color, fontWeight: 600 }}>{grade}</div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {factors.map((f, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', fontSize: 11 }}>
            <span style={{ color: f.good ? 'var(--up)' : 'var(--dn)', flexShrink: 0, width: 14 }}>{f.good ? '✓' : '✗'}</span>
            <span style={{ color: 'var(--txt2)', flexShrink: 0, minWidth: 110 }}>{f.label}</span>
            <span style={{ color: 'var(--txt3)', lineHeight: 1.4 }}>{f.detail}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Signal card ─────────────────────────────────────────────────────────────

function SignalRow({ s, spot = 0 }: { s: any; spot?: number }) {
  const [exp, setExp] = useState(false)
  const isLong = s.direction === 'long'
  const conf = Math.round((s.confidence_score ?? 0) * 100)
  const pColor = PATTERN_COLORS[s.pattern_name] ?? 'var(--txt2)'
  const tf = s.timeframe || 'daily'

  return (
    <div className="fade-up" style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        onClick={() => setExp(e => !e)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', cursor: 'pointer' }}
        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
        onMouseLeave={e => (e.currentTarget.style.background = '')}
      >
        {/* Direction stripe */}
        <div style={{ width: 3, height: 36, borderRadius: 2, background: isLong ? 'var(--up)' : 'var(--dn)', flexShrink: 0 }} />

        {/* Timeframe badge */}
        <span style={{
          fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 2,
          background: `${TF_COLOR[tf]}22`, color: TF_COLOR[tf],
          border: `1px solid ${TF_COLOR[tf]}44`, whiteSpace: 'nowrap',
        }}>{TF_LABEL[tf] ?? tf}</span>

        {/* Pattern badge */}
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
          background: `${pColor}22`, color: pColor, border: `1px solid ${pColor}44`,
          whiteSpace: 'nowrap', minWidth: 80, textAlign: 'center',
        }}>{s.pattern_name?.replace(/_/g, ' ').toUpperCase()}</span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 700, color: 'var(--txt)' }}>{s.underlying}</span>
            <span className={`badge ${isLong ? 'badge-up' : 'badge-dn'}`}>{s.direction?.toUpperCase()}</span>
            {/* Contract: OPTIONS show strike+type, FUTURES show FUT — always visible */}
            {s.option_type ? (
              <span className="mono" style={{
                fontSize: 11, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                background: s.option_type === 'CE' ? 'rgba(41,98,255,0.12)' : 'rgba(233,30,99,0.10)',
                color: s.option_type === 'CE' ? 'var(--blue)' : '#e91e63',
                border: `1px solid ${s.option_type === 'CE' ? 'rgba(41,98,255,0.3)' : 'rgba(233,30,99,0.3)'}`,
                whiteSpace: 'nowrap',
              }}>
                {(s.strike ?? 0).toLocaleString('en-IN')} {s.option_type}
                {s.expiry_dte != null && <span style={{ fontWeight: 400, opacity: 0.75 }}> · {s.expiry_dte}d</span>}
              </span>
            ) : (
              <span className="mono" style={{
                fontSize: 11, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                background: 'rgba(255,152,0,0.10)', color: 'var(--orange)',
                border: '1px solid rgba(255,152,0,0.3)', whiteSpace: 'nowrap',
              }}>FUT</span>
            )}
            {s.option_strategy && (
              <span style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {s.option_strategy}
              </span>
            )}
          </div>
          <div className="conf-bar" style={{ width: 80, marginTop: 5 }}>
            <div className="progress-fill" style={{ width: `${conf}%`, background: conf >= 75 ? 'var(--up)' : conf >= 55 ? 'var(--orange)' : 'var(--txt3)' }} />
          </div>
        </div>

        {/* Prices */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0 14px', textAlign: 'right' }}>
          {[
            { label: 'Entry',  val: fmtINR(s.entry_price),  color: 'var(--txt)' },
            { label: 'Target', val: fmtINR(s.target_price), color: 'var(--up)' },
            { label: 'Stop',   val: fmtINR(s.stop_loss),    color: 'var(--dn)' },
          ].map(({ label, val, color }) => (
            <div key={label}>
              <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{label}</div>
              <div className="mono" style={{ color, fontWeight: 600, fontSize: 12 }}>{val}</div>
            </div>
          ))}
        </div>

        {/* Option contract + expiry */}
        {s.strike && (
          <div style={{ textAlign: 'right', minWidth: 110 }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>Contract</div>
            <div className="mono" style={{ fontSize: 11, fontWeight: 700, color: s.option_type === 'CE' ? 'var(--blue)' : '#e91e63' }}>
              {s.strike?.toLocaleString('en-IN')} {s.option_type}
            </div>
            <div style={{ fontSize: 9, color: 'var(--txt3)' }}>{s.option_strategy?.toUpperCase()}</div>
            {/* Expiry date — full date + DTE */}
            {s.expiry_display && (
              <div style={{ marginTop: 3, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 1 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--blue)', whiteSpace: 'nowrap' }}>
                  {s.expiry_display}
                </div>
                <div style={{
                  fontSize: 9, padding: '0 4px', borderRadius: 2,
                  background: (s.expiry_dte ?? 99) <= 2
                    ? 'rgba(239,83,80,0.15)' : 'rgba(41,98,255,0.12)',
                  color: (s.expiry_dte ?? 99) <= 2 ? 'var(--dn)' : 'var(--txt2)',
                  fontWeight: 700,
                }}>
                  {s.expiry_series === 'weekly' ? 'WK' : 'MO'} · {s.expiry_dte}d
                </div>
              </div>
            )}
          </div>
        )}

        {/* Greeks */}
        {s.delta != null && (
          <div style={{ textAlign: 'right', minWidth: 70 }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>Δ / θ / IV</div>
            <div className="mono" style={{ fontSize: 10, color: 'var(--txt)' }}>
              {s.delta?.toFixed(2)} / {s.theta?.toFixed(1)} / {s.iv_at_signal?.toFixed(1)}%
            </div>
            {s.iv_rank != null && (
              <div style={{ fontSize: 9, color: s.iv_rank > 0.7 ? 'var(--dn)' : s.iv_rank < 0.3 ? 'var(--up)' : 'var(--orange)' }}>
                IVR {Math.round(s.iv_rank * 100)}
              </div>
            )}
          </div>
        )}

        {/* Confidence + expected return */}
        <div style={{ textAlign: 'right', minWidth: 52 }}>
          <div style={{ fontSize: 10, color: 'var(--txt3)' }}>Conf.</div>
          <div className="mono" style={{ fontWeight: 700, fontSize: 13, color: conf >= 75 ? 'var(--up)' : 'var(--orange)' }}>{conf}%</div>
          <div className="mono up" style={{ fontSize: 10 }}>+{s.expected_return_pct?.toFixed(1)}%</div>
        </div>

        <span style={{ color: 'var(--txt3)', fontSize: 11 }}>{exp ? '▲' : '▼'}</span>
      </div>

      {exp && (
        <div className="fade-up" style={{ padding: '0 12px 12px 25px' }}>
          {/* Trade quality score */}
          {s.option_type && <TradeQualityPanel s={s} spot={spot} />}
          {/* Full instrument symbol — copyable */}
          {s.instrument && s.instrument !== s.underlying && (
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontSize: 10, color: 'var(--txt3)' }}>Trade: </span>
              <span
                className="mono"
                title="Click to copy"
                onClick={e => { e.stopPropagation(); navigator.clipboard?.writeText(s.instrument) }}
                style={{
                  fontSize: 12, fontWeight: 700, color: 'var(--txt)',
                  cursor: 'copy', padding: '1px 6px', borderRadius: 3,
                  background: 'var(--bg3)', border: '1px solid var(--border)',
                  userSelect: 'all',
                }}
              >{s.instrument}</span>
              {s.expiry_display && (
                <span style={{ fontSize: 10, color: 'var(--txt3)', marginLeft: 6 }}>
                  expires {s.expiry_display}
                </span>
              )}
            </div>
          )}
          <p style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.6, marginBottom: 8 }}>
            {s.explanation}
          </p>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {s.regime_trend && (
              <span className={`badge ${s.regime_trend === 'bullish' ? 'badge-up' : s.regime_trend === 'bearish' ? 'badge-dn' : 'badge-warn'}`}>
                {s.regime_trend} regime
              </span>
            )}
            {s.regime_volatility && <span className="badge badge-mute">{s.regime_volatility} vol</span>}
            {s.estimated_premium != null && <span className="badge badge-mute">Premium ₹{s.estimated_premium?.toFixed(0)}</span>}
            {s.max_loss != null && <span className="badge badge-dn">Max loss ₹{s.max_loss?.toFixed(0)}</span>}
            {s.lot_size != null && <span className="badge badge-mute">Lot {s.lot_size}</span>}
            {s.vega != null && <span className="badge badge-blue">Vega {s.vega?.toFixed(2)}</span>}
            {s.max_pain_strike && <span className="badge badge-warn">Max pain {s.max_pain_strike?.toLocaleString('en-IN')}</span>}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Stat tile ────────────────────────────────────────────────────────────────

function StatTile({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ padding: '10px 14px', borderRight: '1px solid var(--border)' }}>
      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: color || 'var(--txt)' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="tab-bar">
      {tabs.map(t => (
        <button key={t} className={`tab-btn ${active === t ? 'active' : ''}`} onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  )
}

function EquitySparkline({ capital, pnl }: { capital: number; pnl: number }) {
  const data = Array.from({ length: 20 }, (_, i) => ({
    i, v: capital - pnl * 20 + (pnl / 20) * i * (0.8 + Math.random() * 0.4),
  }))
  return (
    <ResponsiveContainer width="100%" height={50}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2962ff" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#2962ff" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke="#2962ff" strokeWidth={1.5} fill="url(#sg)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ─── Live alert toast ─────────────────────────────────────────────────────────

function SignalToast({ sig, onDismiss }: { sig: any; onDismiss: () => void }) {
  useEffect(() => { const t = setTimeout(onDismiss, 8000); return () => clearTimeout(t) }, [])
  const isLong = sig.direction === 'long'
  const pColor = PATTERN_COLORS[sig.pattern_name] ?? 'var(--blue)'
  return (
    <div className="fade-up" style={{
      position: 'fixed', bottom: 20, right: 20, zIndex: 9999,
      background: 'var(--bg2)', border: `1px solid ${pColor}55`,
      borderLeft: `3px solid ${pColor}`, borderRadius: 6,
      padding: '10px 14px', minWidth: 260, maxWidth: 320,
      boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <div className="live-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--up)', flexShrink: 0 }} />
        <span style={{ fontSize: 11, fontWeight: 700, color: pColor }}>{sig.pattern_name?.replace(/_/g, ' ').toUpperCase()}</span>
        <span className={`badge ${isLong ? 'badge-up' : 'badge-dn'}`} style={{ marginLeft: 'auto' }}>{sig.direction?.toUpperCase()}</span>
        <button onClick={onDismiss} style={{ background: 'none', border: 'none', color: 'var(--txt3)', cursor: 'pointer', fontSize: 14, padding: 0 }}>×</button>
      </div>
      <div style={{ fontWeight: 700, color: 'var(--txt)', marginBottom: 2 }}>
        {sig.underlying} {sig.timeframe && <span style={{ fontSize: 10, color: TF_COLOR[sig.timeframe], fontWeight: 400 }}>({TF_LABEL[sig.timeframe]})</span>}
      </div>
      {sig.strike && (
        <div style={{ fontSize: 11, color: 'var(--txt2)' }}>
          {sig.strike?.toLocaleString('en-IN')} {sig.option_type} · {sig.option_strategy}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 3 }}>
        Conf. {Math.round(sig.confidence_score * 100)}% · +{sig.expected_return_pct?.toFixed(1)}% target
      </div>
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function Dashboard() {
  const qc = useQueryClient()
  const { mode, syncFromBackend } = useModeStore()
  const [selectedSym, setSelectedSym] = useState('NIFTY')
  const [sector, setSector] = useState('Index')
  const [mainTab, setMainTab] = useState('Signals')
  const [scanning, setScanning] = useState(false)
  const [scanningAll, setScanningAll] = useState(false)
  const [tfFilter, setTfFilter] = useState<string>('all')
  const [liveSignals, setLiveSignals] = useState<any[]>([])
  const [toasts, setToasts] = useState<any[]>([])
  const [livePrices, setLivePrices] = useState<Record<string, { ltp: number; chg: number }>>({})
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const priceWsRef = useRef<WebSocket | null>(null)

  // Request browser notification permission on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // Sync mode from backend on mount
  useEffect(() => { syncFromBackend() }, [])

  // ── API queries ──────────────────────────────────────────────────────────────
  const { data: instrData } = useQuery({
    queryKey: ['instruments'],
    queryFn: () => fetchInstruments(),
    staleTime: 60_000,
  })
  const { data: sectorsData } = useQuery({
    queryKey: ['sectors'],
    queryFn: fetchSectors,
    staleTime: 60_000,
  })
  const { data: signals, isLoading: sigLoading } = useQuery({
    queryKey: ['signals', selectedSym, tfFilter],
    queryFn: () => fetchSignals({ status: 'active', underlying: selectedSym, limit: 50 }),
    refetchInterval: 30_000,
  })
  const { data: portfolio }   = useQuery({ queryKey: ['portfolio', mode], queryFn: () => fetchPortfolio(mode === 'live' ? 'live' : 'paper'), refetchInterval: 10_000 })
  const { data: trades }      = useQuery({ queryKey: ['trades'],      queryFn: () => fetchTrades('paper') })
  const { data: dataStatus }  = useQuery({ queryKey: ['dataStatus'],  queryFn: fetchDataStatus,  refetchInterval: 60_000, staleTime: 30_000 })
  const { data: preMarket, isLoading: pmLoading } = useQuery({ queryKey: ['preMarket'], queryFn: fetchPreMarket, staleTime: 120_000, refetchInterval: 300_000 })
  const { data: patternPerf } = useQuery({ queryKey: ['patternPerf'], queryFn: fetchPatternPerf, staleTime: 60_000 })

  // ── Mutations ──────────────────────────────────────────────────────────────
  const scanMutation = useMutation({
    mutationFn: () => { setScanning(true); return runSignals(selectedSym) },
    onSettled: () => { setScanning(false); qc.invalidateQueries({ queryKey: ['signals'] }) },
  })
  const FOCUS_SYMS = ['NIFTY', 'BANKNIFTY']
  const scanAllMutation = useMutation({
    mutationFn: () => { setScanningAll(true); return scanAll(FOCUS_SYMS, ['15m', '1h', '4h', 'daily']) },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['signals'] })
      setScanningAll(false)
    },
    onError: () => setScanningAll(false),
  })
  const initMutation = useMutation({
    mutationFn: initPortfolio,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })

  // ── WebSocket: live signals ───────────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const ws = createSignalSocket(
        (msg) => {
          if (msg.type === 'initial_signals') {
            setLiveSignals(msg.signals || [])
            setWsConnected(true)
          } else if (msg.type === 'new_signal') {
            const sig = msg.signal
            setLiveSignals(prev => [sig, ...prev.slice(0, 99)])
            setToasts(prev => [...prev, { ...sig, _id: Date.now() }])
            qc.invalidateQueries({ queryKey: ['signals'] })
            // Browser notification for high-confidence signals
            if (sig.confidence_score >= 0.72 && 'Notification' in window && Notification.permission === 'granted') {
              new Notification(`AlphaFO: ${sig.underlying} ${sig.direction.toUpperCase()}`, {
                body: `${sig.pattern_name.replace(/_/g, ' ')} — ${Math.round(sig.confidence_score * 100)}% confidence\n${sig.instrument ?? ''}`,
                icon: '/favicon.ico',
              })
            }
          } else if (msg.type === 'ping') {
            setWsConnected(true)
          }
        },
        () => {
          setWsConnected(false)
          setTimeout(connect, 3000) // reconnect
        }
      )
      wsRef.current = ws
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  // ── WebSocket: live prices ────────────────────────────────────────────────
  useEffect(() => {
    const ws = createPriceSocket((ticks) => setLivePrices(prev => ({ ...prev, ...ticks })))
    priceWsRef.current = ws
    return () => ws.close()
  }, [])

  // ── Derived data ──────────────────────────────────────────────────────────
  const instruments: Instrument[] = instrData?.instruments || []
  const sectors: string[] = sectorsData?.sectors || []
  const sectorInstruments = instruments.filter(i => i.sector === sector)

  const allSignals: any[] = signals?.signals ?? []
  const filteredSignals = tfFilter === 'all' ? allSignals : allSignals.filter(s => s.timeframe === tfFilter)
  const tradeList: any[] = trades?.trades ?? []
  const hasPF = portfolio?.capital != null

  const selectedInst = instruments.find(i => i.sym === selectedSym)
  const selectedPrice = livePrices[selectedSym]
  const ltp   = selectedPrice?.ltp  ?? selectedInst?.base_price ?? 0
  const chgPct = selectedPrice?.chg ?? 0

  const closedTrades = tradeList.filter(t => t.status === 'closed')
  const pnlData = closedTrades.map((t, i) => ({ i: i + 1, pnl: t.pnl ?? 0 }))

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Live signal toasts ─────────────────────────────── */}
      <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.slice(-3).map(t => (
          <SignalToast key={t._id} sig={t} onDismiss={() => setToasts(prev => prev.filter(x => x._id !== t._id))} />
        ))}
      </div>

      {/* ── Left: Watchlist ───────────────────────────────── */}
      <div style={{ width: 280, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>

        {/* WS status + scan-all */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div className={wsConnected ? 'live-dot' : ''} style={{
              width: 6, height: 6, borderRadius: '50%',
              background: wsConnected ? (dataStatus?.data_source?.startsWith('kite') ? 'var(--up)' : 'var(--orange)') : 'var(--txt3)',
              flexShrink: 0,
            }} />
            <span style={{ fontSize: 10, color: wsConnected ? (dataStatus?.data_source?.startsWith('kite') ? 'var(--up)' : 'var(--orange)') : 'var(--txt3)' }}>
              {!wsConnected ? 'OFFLINE' : (dataStatus?.source_label ?? 'CONNECTING…')}
            </span>
          </div>
          {/* Mode pill */}
          <span style={{
            fontSize: 9, padding: '1px 5px', borderRadius: 2, fontWeight: 700, letterSpacing: '0.05em',
            background: mode === 'live' ? 'rgba(239,83,80,0.15)' : mode === 'paper' ? 'rgba(255,152,0,0.12)' : 'rgba(150,150,150,0.1)',
            color: mode === 'live' ? 'var(--dn)' : mode === 'paper' ? 'var(--orange)' : 'var(--txt3)',
            border: `1px solid ${mode === 'live' ? 'rgba(239,83,80,0.3)' : mode === 'paper' ? 'rgba(255,152,0,0.3)' : 'rgba(150,150,150,0.2)'}`,
          }}>{mode.toUpperCase()}</span>
          <div style={{ flex: 1 }} />
          <button
            className="tv-btn tv-btn-primary"
            style={{ fontSize: 10, padding: '3px 8px' }}
            onClick={() => scanAllMutation.mutate()}
            disabled={scanningAll}
          >
            {scanningAll ? '⏳ Scanning…' : '⚡ Scan NF+BNF'}
          </button>
        </div>

        {/* Sector tabs */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 1, padding: '4px 6px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
          {(sectors.length ? sectors : ['Index', 'Banking', 'IT', 'Energy', 'Auto', 'Pharma']).map(s => (
            <button
              key={s}
              onClick={() => { setSector(s); const first = instruments.find(i => i.sector === s); if (first) setSelectedSym(first.sym) }}
              className="tv-btn"
              style={{
                padding: '2px 6px', fontSize: 9,
                background: sector === s ? 'rgba(41,98,255,0.15)' : 'transparent',
                color: sector === s ? 'var(--blue)' : 'var(--txt2)',
                border: `1px solid ${sector === s ? 'rgba(41,98,255,0.35)' : 'transparent'}`,
              }}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Symbol dropdown */}
        <div style={{ padding: '5px 7px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
          <select
            className="tv-select"
            style={{ width: '100%', fontSize: 11 }}
            value={selectedSym}
            onChange={e => setSelectedSym(e.target.value)}
          >
            {(sectors.length ? sectors : ['Index', 'Banking', 'IT', 'Energy', 'Auto', 'Pharma']).map(s => (
              <optgroup key={s} label={s}>
                {instruments.filter(i => i.sector === s).map(i => (
                  <option key={i.sym} value={i.sym}>{i.sym} — {i.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        {/* Instrument table */}
        <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>
          {sectorInstruments.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', color: 'var(--txt3)', fontSize: 11 }}>Loading…</div>
          ) : (
            <table className="tv-table">
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>Symbol</th>
                  <th>LTP</th>
                  <th>Chg%</th>
                  <th>Lot</th>
                </tr>
              </thead>
              <tbody>
                {sectorInstruments.map(inst => {
                  const price = livePrices[inst.sym]
                  return (
                    <WatchRow
                      key={inst.sym}
                      inst={inst}
                      ltp={price?.ltp ?? inst.base_price}
                      chg={price?.chg ?? 0}
                      selected={selectedSym === inst.sym}
                      onSelect={() => setSelectedSym(inst.sym)}
                    />
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Selected instrument bar */}
        <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border)', background: 'var(--bg2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 1 }}>
                <span style={{ fontWeight: 700, color: 'var(--txt)', fontSize: 12 }}>{selectedSym}</span>
                {dataStatus && (
                  <span style={{
                    fontSize: 9, padding: '1px 4px', borderRadius: 2, fontWeight: 700, letterSpacing: '0.05em',
                    background: dataStatus.data_source?.startsWith('kite') ? 'rgba(38,166,154,0.12)' : 'rgba(255,152,0,0.15)',
                    color: dataStatus.data_source?.startsWith('kite') ? 'var(--up)' : 'var(--orange)',
                    border: `1px solid ${dataStatus.data_source?.startsWith('kite') ? 'rgba(38,166,154,0.3)' : 'rgba(255,152,0,0.35)'}`,
                  }}>{dataStatus.source_label ?? 'SIM'}</span>
                )}
              </div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 800, color: chgPct >= 0 ? 'var(--up)' : 'var(--dn)', lineHeight: 1.1 }}>
                {ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
              </div>
              <div className="mono" style={{ fontSize: 11, color: chgPct >= 0 ? 'var(--up)' : 'var(--dn)' }}>{chgStr(chgPct)}</div>
            </div>
            <button
              onClick={() => scanMutation.mutate()}
              disabled={scanning}
              className="tv-btn tv-btn-primary"
              style={{ fontSize: 11 }}
            >
              {scanning ? '…' : `⚡ Scan`}
            </button>
          </div>
        </div>
      </div>

      {/* ── Right panel ───────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Portfolio stat bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg2)', flexShrink: 0 }}>
          {hasPF ? (
            <>
              <StatTile label="Portfolio" value={fmtINR(portfolio.capital)} />
              <StatTile
                label="Day P&L"
                value={fmtINR(portfolio.daily_pnl)}
                color={(portfolio.daily_pnl ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)'}
                sub={`${((portfolio.daily_pnl ?? 0) / portfolio.capital * 100).toFixed(2)}%`}
              />
              <StatTile
                label="Win Rate"
                value={`${((portfolio.win_rate ?? 0) * 100).toFixed(1)}%`}
                color={(portfolio.win_rate ?? 0) >= 0.55 ? 'var(--up)' : 'var(--orange)'}
                sub={`${portfolio.total_trades ?? 0} trades`}
              />
              <StatTile label="Open" value={String(portfolio.open_positions ?? 0)} sub="positions" />
              <div style={{ flex: 1, padding: '4px 12px', display: 'flex', alignItems: 'center' }}>
                <div style={{ width: '100%' }}>
                  <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Equity (30d)
                  </div>
                  <EquitySparkline capital={portfolio.capital} pnl={portfolio.daily_pnl ?? 0} />
                </div>
              </div>
              {/* Live signals badge */}
              {liveSignals.length > 0 && (
                <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', borderLeft: '1px solid var(--border)' }}>
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Live</div>
                    <div className="mono" style={{ fontWeight: 700, color: 'var(--blue)', fontSize: 16 }}>{liveSignals.length}</div>
                    <div style={{ fontSize: 9, color: 'var(--txt3)' }}>signals</div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{ padding: '0 16px', display: 'flex', alignItems: 'center', gap: 12, height: 60 }}>
              <span style={{ color: 'var(--txt2)', fontSize: 12 }}>No paper portfolio. </span>
              <button className="tv-btn tv-btn-primary" style={{ fontSize: 11 }} onClick={() => initMutation.mutate()} disabled={initMutation.isPending}>
                + Init Portfolio
              </button>
            </div>
          )}
        </div>

        <Tabs tabs={['Signals', 'Portfolio', 'Trades', 'Patterns', 'Briefing']} active={mainTab} onChange={setMainTab} />

        <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>

          {/* ── Signals ── */}
          {mainTab === 'Signals' && (
            <div>
              {/* Toolbar: timeframe filter + actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: 'var(--txt2)' }}>
                  <strong style={{ color: 'var(--txt)' }}>{selectedSym}</strong> · {filteredSignals.length} signal{filteredSignals.length !== 1 ? 's' : ''}
                </span>

                {/* Timeframe filter pills */}
                <div style={{ display: 'flex', gap: 4 }}>
                  {['all', '15m', '1h', '4h', 'daily'].map(tf => (
                    <button
                      key={tf}
                      onClick={() => setTfFilter(tf)}
                      className="tv-btn"
                      style={{
                        padding: '2px 7px', fontSize: 10,
                        background: tfFilter === tf ? (tf === 'all' ? 'rgba(41,98,255,0.15)' : `${TF_COLOR[tf]}22`) : 'transparent',
                        color: tfFilter === tf ? (tf === 'all' ? 'var(--blue)' : TF_COLOR[tf]) : 'var(--txt3)',
                        border: `1px solid ${tfFilter === tf ? (tf === 'all' ? 'rgba(41,98,255,0.4)' : `${TF_COLOR[tf]}55`) : 'transparent'}`,
                      }}
                    >
                      {tf === 'all' ? 'All TF' : TF_LABEL[tf]}
                    </button>
                  ))}
                </div>

                <div style={{ flex: 1 }} />
                <button className="tv-btn tv-btn-primary" style={{ fontSize: 11 }} onClick={() => scanMutation.mutate()} disabled={scanning}>
                  {scanning ? '⏳…' : `⚡ ${selectedSym}`}
                </button>
                <button
                  className="tv-btn"
                  style={{ fontSize: 11, color: 'var(--blue)', border: '1px solid rgba(41,98,255,0.35)' }}
                  onClick={() => scanAllMutation.mutate()}
                  disabled={scanningAll}
                >
                  {scanningAll ? '⏳ Scanning all…' : '⚡ Scan All Stocks'}
                </button>
              </div>

              {/* Scan result summary */}
              {scanAllMutation.data && (
                <div className="fade-up" style={{ padding: '6px 12px', background: 'rgba(41,98,255,0.06)', borderBottom: '1px solid var(--border)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, color: 'var(--txt2)' }}>
                    ✓ Scanned <strong style={{ color: 'var(--txt)' }}>{scanAllMutation.data.symbols_scanned}</strong> instruments
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--txt2)' }}>
                    Found <strong style={{ color: 'var(--blue)' }}>{scanAllMutation.data.signals_found}</strong> signals
                    ({scanAllMutation.data.signals_new} new)
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--txt3)' }}>in {scanAllMutation.data.duration_ms}ms</span>
                  <span style={{ fontSize: 11, color: 'var(--txt3)' }}>TF: {scanAllMutation.data.timeframes?.join(', ')}</span>
                </div>
              )}

              {sigLoading && (
                <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 56 }} />)}
                </div>
              )}

              {!sigLoading && filteredSignals.length === 0 && (
                <div style={{ textAlign: 'center', padding: '48px 24px' }}>
                  <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.3 }}>◉</div>
                  <p style={{ color: 'var(--txt2)', marginBottom: 6 }}>No signals for {selectedSym} {tfFilter !== 'all' ? `(${TF_LABEL[tfFilter]})` : ''}</p>
                  <p style={{ color: 'var(--txt3)', fontSize: 11 }}>Click ⚡ Scan or ⚡ Scan All Stocks</p>
                </div>
              )}

              {filteredSignals.map((s: any) => <SignalRow key={s.id} s={s} spot={livePrices[s.underlying]?.ltp ?? 0} />)}
            </div>
          )}

          {/* ── Portfolio ── */}
          {mainTab === 'Portfolio' && (
            <div style={{ padding: 16 }}>
              {!hasPF ? (
                <div style={{ textAlign: 'center', padding: 48 }}>
                  <p style={{ color: 'var(--txt2)', marginBottom: 12 }}>No portfolio initialised.</p>
                  <button className="tv-btn tv-btn-primary" onClick={() => initMutation.mutate()}>Init Paper Portfolio (₹5,00,000)</button>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                    {[
                      { label: 'Capital',       val: fmtINR(portfolio.capital),                               color: 'var(--txt)' },
                      { label: 'Day P&L',        val: fmtINR(portfolio.daily_pnl),                            color: (portfolio.daily_pnl??0)>=0 ? 'var(--up)' : 'var(--dn)' },
                      { label: 'Deployed',       val: fmtINR(portfolio.capital_deployed),                     color: 'var(--orange)' },
                      { label: 'Total Trades',   val: String(portfolio.total_trades ?? 0),                    color: 'var(--txt)' },
                      { label: 'Win Rate',       val: `${((portfolio.win_rate??0)*100).toFixed(1)}%`,         color: (portfolio.win_rate??0)>=0.55 ? 'var(--up)' : 'var(--orange)' },
                      { label: 'Open Positions', val: String(portfolio.open_positions ?? 0),                  color: 'var(--txt)' },
                    ].map(({ label, val, color }) => (
                      <div key={label} className="tv-card" style={{ padding: '10px 14px' }}>
                        <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, color }}>{val}</div>
                      </div>
                    ))}
                  </div>
                  <div className="tv-card" style={{ padding: 14 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt2)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Live Promotion Criteria</div>
                    {[
                      { label: 'Paper Trades ≥60', cur: portfolio.total_trades ?? 0, req: 60 },
                      { label: 'Win Rate ≥55%',    cur: Math.round((portfolio.win_rate??0)*100), req: 55, unit: '%' },
                    ].map(({ label, cur, req, unit }) => {
                      const done = cur >= req
                      const p = Math.min(100, cur / req * 100)
                      return (
                        <div key={label} style={{ marginBottom: 10 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: 'var(--txt2)' }}>{label}</span>
                            <span className="mono" style={{ color: done ? 'var(--up)' : 'var(--orange)' }}>{cur}{unit ?? ''} / {req}{unit ?? ''} {done ? '✓' : ''}</span>
                          </div>
                          <div className="progress-track">
                            <div className="progress-fill" style={{ width: `${p}%`, background: done ? 'var(--up)' : 'var(--orange)' }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Trades ── */}
          {mainTab === 'Trades' && (
            <div>
              {pnlData.length > 0 && (
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Trade P&L History</div>
                  <ResponsiveContainer width="100%" height={90}>
                    <BarChart data={pnlData} margin={{ top: 4, right: 8, bottom: 0, left: 48 }}>
                      <YAxis
                        tick={{ fontSize: 9, fill: 'var(--txt3)' }}
                        tickLine={false} axisLine={false}
                        tickFormatter={(v: number) => `₹${Math.abs(v) >= 1000 ? `${(v/1000).toFixed(0)}k` : v}`}
                        width={44}
                      />
                      <ReferenceLine y={0} stroke="var(--border2)" strokeWidth={1} />
                      <Tooltip
                        contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11 }}
                        formatter={(v: number) => [fmtINR(v), 'P&L']}
                        labelFormatter={(i: number) => `Trade #${i}`}
                      />
                      <Bar dataKey="pnl" radius={[2, 2, 0, 0]} maxBarSize={18}>
                        {pnlData.map((d, idx) => (
                          <Cell key={idx} fill={d.pnl >= 0 ? 'var(--up)' : 'var(--dn)'} fillOpacity={0.85} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              {tradeList.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>
                  No trades yet. Run a scan and high-confidence signals auto-place paper trades.
                </div>
              ) : (
                <table className="tv-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Instrument</th>
                      <th>Dir</th>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>P&L</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tradeList.map((t: any) => {
                      const pnl = t.pnl ?? 0
                      return (
                        <tr key={t.id}>
                          <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--txt)' }}>{t.symbol || t.underlying}</td>
                          <td><span className={`badge ${t.direction==='long'||t.action==='BUY' ? 'badge-up' : 'badge-dn'}`}>{t.action || t.direction?.toUpperCase()}</span></td>
                          <td className="mono">{fmtINR(t.entry_price)}</td>
                          <td className="mono muted">{t.exit_price ? fmtINR(t.exit_price) : '—'}</td>
                          <td className={`mono ${pnl >= 0 ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>
                            {t.status === 'closed' ? `${pnl >= 0 ? '+' : ''}${fmtINR(pnl)}` : '—'}
                          </td>
                          <td><span className={`badge ${t.status === 'open' ? 'badge-blue' : 'badge-mute'}`}>{t.status}</span></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* ── Briefing ── */}
          {mainTab === 'Briefing' && (
            <div style={{ padding: 12 }}>
              {pmLoading ? (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--txt3)' }}>Loading briefing…</div>
              ) : preMarket ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {/* Session header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 11, color: 'var(--txt2)' }}>{preMarket.session?.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{preMarket.session?.time_ist}</span>
                    {preMarket.session?.is_market_hours && <span className="badge badge-up" style={{ marginLeft: 'auto' }}>MARKET OPEN</span>}
                  </div>

                  {/* VIX + Market row */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                    {/* VIX */}
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>India VIX</div>
                      {preMarket.vix?.level != null ? (
                        <>
                          <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: preMarket.vix.level < 16 ? 'var(--up)' : preMarket.vix.level > 20 ? 'var(--dn)' : 'var(--orange)' }}>
                            {preMarket.vix.level.toFixed(2)}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--txt2)', marginTop: 4 }}>{preMarket.vix.signal}</div>
                        </>
                      ) : <div style={{ color: 'var(--txt3)', fontSize: 11 }}>—</div>}
                    </div>

                    {/* NIFTY */}
                    {(['NIFTY', 'BANKNIFTY'] as const).map(sym => {
                      const m = preMarket.market?.[sym]
                      return (
                        <div key={sym} className="tv-card" style={{ padding: 12 }}>
                          <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{sym}</div>
                          {m ? (
                            <>
                              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                                <span className="mono" style={{ fontSize: 16, fontWeight: 700, color: 'var(--txt)' }}>{m.last.toLocaleString('en-IN')}</span>
                                <span className={`mono ${m.chg_pct >= 0 ? 'up' : 'dn'}`} style={{ fontSize: 11 }}>{m.chg_pct >= 0 ? '+' : ''}{m.chg_pct.toFixed(2)}%</span>
                              </div>
                              <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 4 }}>
                                <span style={{ color: m.trend === 'bullish' ? 'var(--up)' : m.trend === 'bearish' ? 'var(--dn)' : 'var(--txt2)', textTransform: 'uppercase', fontWeight: 700 }}>{m.trend}</span>
                                {' · '}RSI {m.rsi} · HV {m.hv20}%
                              </div>
                            </>
                          ) : <div style={{ color: 'var(--txt3)', fontSize: 11 }}>—</div>}
                        </div>
                      )
                    })}
                  </div>

                  {/* PCR + FII row */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    {/* PCR */}
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Put-Call Ratio</div>
                      {Object.entries(preMarket.pcr ?? {}).map(([sym, d]: [string, any]) => (
                        <div key={sym} style={{ marginBottom: 6 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                            <span style={{ fontSize: 10, color: 'var(--txt2)', fontWeight: 700 }}>{sym}</span>
                            <span className="mono" style={{ fontSize: 14, fontWeight: 700, color: d.pcr > 1.0 ? 'var(--up)' : 'var(--dn)' }}>{d.pcr?.toFixed(3)}</span>
                            {d.max_pain && <span style={{ fontSize: 10, color: 'var(--txt3)' }}>MP {d.max_pain.toLocaleString('en-IN')}</span>}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--txt2)' }}>{d.signal}</div>
                        </div>
                      ))}
                      {!Object.keys(preMarket.pcr ?? {}).length && <div style={{ color: 'var(--txt3)', fontSize: 11 }}>No PCR data yet</div>}
                    </div>

                    {/* FII */}
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>FII F&O Net</div>
                      {preMarket.fii ? (
                        <>
                          <div className="mono" style={{ fontSize: 18, fontWeight: 700, color: preMarket.fii.net_cr > 0 ? 'var(--up)' : 'var(--dn)' }}>
                            {preMarket.fii.net_cr > 0 ? '+' : ''}{preMarket.fii.net_cr.toLocaleString('en-IN')} Cr
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--txt2)', marginTop: 4 }}>{preMarket.fii.signal}</div>
                          {preMarket.fii.date && <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 2 }}>as of {preMarket.fii.date}</div>}
                        </>
                      ) : <div style={{ color: 'var(--txt3)', fontSize: 11 }}>No FII data yet</div>}
                    </div>
                  </div>

                  {/* Key levels */}
                  {Object.keys(preMarket.key_levels ?? {}).length > 0 && (
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Key Levels</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                        {Object.entries(preMarket.key_levels).map(([sym, kl]: [string, any]) => (
                          <div key={sym}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--blue)', marginBottom: 4 }}>{sym}</div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px', fontSize: 11 }}>
                              {[
                                ['R2', kl.resistance_2, 'var(--dn)'],
                                ['R1', kl.resistance_1, 'var(--dn)'],
                                ['ATM', kl.atm_strike, 'var(--txt)'],
                                ['Pivot', kl.pivot, 'var(--orange)'],
                                ['S1', kl.support_1, 'var(--up)'],
                                ['S2', kl.support_2, 'var(--up)'],
                              ].map(([lbl, val, col]) => (
                                <div key={lbl as string} style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: 'var(--txt3)' }}>{lbl}</span>
                                  <span className="mono" style={{ color: col as string, fontWeight: 600 }}>{(val as number).toLocaleString('en-IN')}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* AI Briefing from Claude (generated at 08:45 IST) */}
                  {preMarket?.ai_briefing && (
                    <div className="tv-card" style={{ padding: 14, borderLeft: '3px solid #c084fc' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                        <span style={{ fontSize: 10, color: '#c084fc', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.07em' }}>✦ AI Pre-Market Briefing</span>
                        {preMarket.ai_briefing_date && (
                          <span style={{ fontSize: 9, color: 'var(--txt3)', marginLeft: 'auto' }}>{preMarket.ai_briefing_date}</span>
                        )}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--txt2)', lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>
                        {preMarket.ai_briefing}
                      </div>
                    </div>
                  )}

                  {/* Recommended patterns */}
                  {(preMarket.recommended_patterns ?? []).length > 0 && (
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Best Patterns Today</div>
                      {preMarket.recommended_patterns.map((p: any, i: number) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: i < preMarket.recommended_patterns.length - 1 ? '1px solid var(--border)' : 'none' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, minWidth: 70, color: 'var(--blue)' }}>{p.underlying}</span>
                          <span className={`badge ${p.direction === 'long' ? 'badge-up' : 'badge-dn'}`} style={{ fontSize: 9 }}>{p.direction?.toUpperCase()}</span>
                          <span style={{ flex: 1, fontSize: 11, color: 'var(--txt)' }}>{p.display_name}</span>
                          <span style={{ fontSize: 10, color: 'var(--txt3)' }}>WR {(p.win_rate * 100).toFixed(0)}%</span>
                          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--up)' }}>{p.alignment_score.toFixed(2)}★</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Paper trade summary */}
                  {preMarket.paper_summary && (
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Paper Trade Summary</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                        {[
                          ['Open Trades', preMarket.paper_summary.open_trades, false],
                          ['Unrealized P&L', fmtINR(preMarket.paper_summary.unrealized_pnl), preMarket.paper_summary.unrealized_pnl >= 0],
                          ['Closed Today', preMarket.paper_summary.closed_today, false],
                          ['Realized Today', fmtINR(preMarket.paper_summary.realized_today), preMarket.paper_summary.realized_today >= 0],
                        ].map(([lbl, val, isUp]) => (
                          <div key={lbl as string}>
                            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{lbl}</div>
                            <div className="mono" style={{ fontSize: 14, fontWeight: 700, color: typeof isUp === 'boolean' ? (isUp ? 'var(--up)' : 'var(--dn)') : 'var(--txt)' }}>{String(val)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Pattern performance leaderboard */}
                  {(patternPerf?.patterns ?? []).length > 0 && (
                    <div className="tv-card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Paper Trade Leaderboard</div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                        <thead>
                          <tr style={{ color: 'var(--txt3)', fontSize: 10 }}>
                            <th style={{ textAlign: 'left', padding: '2px 0' }}>Symbol</th>
                            <th style={{ textAlign: 'right' }}>Trades</th>
                            <th style={{ textAlign: 'right' }}>WR%</th>
                            <th style={{ textAlign: 'right' }}>P&L</th>
                          </tr>
                        </thead>
                        <tbody>
                          {patternPerf.patterns.map((p: any, i: number) => (
                            <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                              <td style={{ padding: '4px 0', fontWeight: 700, color: 'var(--txt)' }}>{p.underlying}</td>
                              <td className="mono" style={{ textAlign: 'right', color: 'var(--txt2)' }}>{p.total}</td>
                              <td className="mono" style={{ textAlign: 'right', color: p.win_rate >= 0.55 ? 'var(--up)' : 'var(--dn)' }}>{(p.win_rate * 100).toFixed(0)}%</td>
                              <td className="mono" style={{ textAlign: 'right', color: p.total_pnl >= 0 ? 'var(--up)' : 'var(--dn)', fontWeight: 600 }}>{fmtINR(p.total_pnl)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--txt3)', fontSize: 12 }}>
                  Briefing data unavailable. Check backend connection.
                </div>
              )}
            </div>
          )}

          {/* ── Patterns ── */}
          {mainTab === 'Patterns' && (
            <div style={{ padding: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                {[
                  { key: 'gap_fill',       name: 'Gap Fill',        when: 'Opens >0.8% gap from prev close', edge: 'NSE gaps fill 65–75% of the time intraday' },
                  { key: 'pcr_divergence', name: 'PCR Divergence',  when: 'PCR >1.3 or <0.7 with price move', edge: 'Extreme PCR forces market maker delta hedging' },
                  { key: 'mean_reversion', name: 'Mean Reversion',  when: 'BB width bottom 20% of 30 days', edge: 'Volatility is mean-reverting; squeezes always expand' },
                  { key: 'oi_buildup',     name: 'OI Buildup',      when: 'Price breakout + OI rise >15%', edge: 'Confirms new capital, not just short covering' },
                  { key: 'vwap_oi',        name: 'VWAP + OI',       when: 'Price reclaims VWAP with rising OI', edge: 'VWAP is institutional benchmark; reclaim triggers algos' },
                  { key: 'iv_crush',       name: 'IV Crush',        when: 'Post-event IV > 1.5x HV', edge: 'IV reverts to HV after events; sell premium' },
                  { key: 'max_pain',       name: 'Max Pain',        when: 'Spot ±2% from max pain strike', edge: 'Option writers defend max pain on expiry' },
                  { key: 'expiry_week',    name: 'Expiry Week',     when: 'Thu/Fri of expiry week', edge: 'Gamma acceleration + pinning behaviour' },
                ].map(({ key, name, when, edge }) => {
                  const color = PATTERN_COLORS[key] ?? 'var(--txt2)'
                  return (
                    <div key={key} className="tv-card fade-up" style={{ padding: 14 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <div style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} />
                        <span style={{ fontWeight: 700, color: 'var(--txt)' }}>{name}</span>
                        <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: `${color}22`, color, border: `1px solid ${color}44`, marginLeft: 'auto' }}>
                          {key}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 4 }}>
                        <strong style={{ color: 'var(--txt2)' }}>Triggers when:</strong> {when}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--txt2)' }}><strong>Edge:</strong> {edge}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
