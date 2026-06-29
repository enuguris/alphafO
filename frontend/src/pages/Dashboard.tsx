import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchSignals, fetchPortfolio, fetchTrades, runSignals, initPortfolio } from '../api/client'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, BarChart, Bar } from 'recharts'

// ─── Instrument catalogue ─────────────────────────────────────────────────────

const GROUPS = [
  { label: 'Indices',  items: [
    { sym: 'NIFTY', name: 'Nifty 50',     ltp: 24325.50, chg: 0.82,  vol: '142.3L', oi: '2.8Cr' },
    { sym: 'BANKNIFTY', name: 'Bank Nifty',  ltp: 52718.35, chg: 1.14,  vol: '98.7L',  oi: '1.9Cr' },
    { sym: 'FINNIFTY',  name: 'Fin Nifty',   ltp: 23481.20, chg: 0.65,  vol: '34.2L',  oi: '0.8Cr' },
    { sym: 'MIDCPNIFTY', name: 'Midcap Nifty', ltp: 12643.75, chg: -0.33, vol: '18.4L',  oi: '0.4Cr' },
  ]},
  { label: 'Banking', items: [
    { sym: 'HDFCBANK',  name: 'HDFC Bank',    ltp: 1842.60, chg: 1.22,  vol: '48.6L',  oi: '1.1Cr' },
    { sym: 'ICICIBANK', name: 'ICICI Bank',   ltp: 1374.90, chg: 2.08,  vol: '62.3L',  oi: '1.4Cr' },
    { sym: 'AXISBANK',  name: 'Axis Bank',    ltp: 1198.45, chg: -0.44, vol: '31.8L',  oi: '0.7Cr' },
    { sym: 'SBIN',      name: 'SBI',          ltp: 856.20,  chg: 0.91,  vol: '89.4L',  oi: '2.1Cr' },
    { sym: 'KOTAKBANK', name: 'Kotak Bank',   ltp: 2134.75, chg: 0.53,  vol: '22.1L',  oi: '0.5Cr' },
  ]},
  { label: 'IT', items: [
    { sym: 'TCS',     name: 'TCS',           ltp: 4286.30, chg: -0.71, vol: '18.4L',  oi: '0.4Cr' },
    { sym: 'INFY',    name: 'Infosys',        ltp: 1923.55, chg: 1.38,  vol: '41.7L',  oi: '0.9Cr' },
    { sym: 'WIPRO',   name: 'Wipro',          ltp: 614.80,  chg: -1.12, vol: '28.9L',  oi: '0.6Cr' },
    { sym: 'HCLTECH', name: 'HCL Tech',       ltp: 1887.45, chg: 0.29,  vol: '19.6L',  oi: '0.4Cr' },
  ]},
  { label: 'Energy', items: [
    { sym: 'RELIANCE', name: 'Reliance',      ltp: 2974.80, chg: 0.47,  vol: '54.2L',  oi: '1.2Cr' },
    { sym: 'ONGC',     name: 'ONGC',          ltp: 268.45,  chg: -0.83, vol: '112.6L', oi: '2.5Cr' },
    { sym: 'NTPC',     name: 'NTPC',          ltp: 384.20,  chg: 1.64,  vol: '78.3L',  oi: '1.7Cr' },
  ]},
  { label: 'Auto', items: [
    { sym: 'TATAMOTORS', name: 'Tata Motors', ltp: 978.65,  chg: 2.34,  vol: '93.8L',  oi: '2.1Cr' },
    { sym: 'MARUTI',     name: 'Maruti',      ltp: 12834.50, chg: 0.18,  vol: '8.4L',   oi: '0.2Cr' },
    { sym: 'BAJAJ-AUTO', name: 'Bajaj Auto',  ltp: 10246.70, chg: -0.62, vol: '6.2L',   oi: '0.1Cr' },
  ]},
  { label: 'Pharma', items: [
    { sym: 'SUNPHARMA', name: 'Sun Pharma',   ltp: 1834.20, chg: 0.76,  vol: '24.3L',  oi: '0.5Cr' },
    { sym: 'DRREDDY',   name: 'Dr Reddys',    ltp: 6482.35, chg: -1.24, vol: '9.8L',   oi: '0.2Cr' },
    { sym: 'CIPLA',     name: 'Cipla',        ltp: 1674.90, chg: 0.95,  vol: '18.7L',  oi: '0.4Cr' },
  ]},
]

const ALL_ITEMS = GROUPS.flatMap(g => g.items)

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const chgStr = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

const PATTERN_COLORS: Record<string, string> = {
  gap_fill: '#7b61ff', pcr_divergence: '#2962ff', mean_reversion: '#00bcd4',
  oi_buildup: '#ff9800', vwap_oi: '#26a69a', iv_crush: '#e91e63',
  max_pain: '#ff5722', expiry_week: '#9c27b0',
}

// ─── Screener watchlist row ───────────────────────────────────────────────────

function WatchRow({ item, selected, onSelect }: {
  item: typeof ALL_ITEMS[0]; selected: boolean; onSelect: () => void
}) {
  const up = item.chg >= 0
  return (
    <tr onClick={onSelect} className={selected ? 'selected' : ''}>
      <td>
        <div style={{ fontWeight: 700, color: 'var(--txt)', fontSize: 12 }}>{item.sym}</div>
        <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{item.name}</div>
      </td>
      <td className="mono" style={{ color: 'var(--txt)', fontWeight: 600 }}>{item.ltp.toLocaleString('en-IN')}</td>
      <td className={`mono ${up ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>{chgStr(item.chg)}</td>
      <td className="mono muted">{item.vol}</td>
      <td className="mono muted">{item.oi}</td>
    </tr>
  )
}

// ─── Signal card (screener style) ────────────────────────────────────────────

function SignalRow({ s }: { s: any }) {
  const [exp, setExp] = useState(false)
  const isLong = s.direction === 'long'
  const conf = Math.round((s.confidence_score ?? 0) * 100)
  const pColor = PATTERN_COLORS[s.pattern_name] ?? 'var(--txt2)'

  return (
    <div className="fade-up" style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        onClick={() => setExp(e => !e)}
        style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', cursor: 'pointer' }}
        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
        onMouseLeave={e => (e.currentTarget.style.background = '')}
      >
        {/* Direction stripe */}
        <div style={{ width: 3, height: 36, borderRadius: 2, background: isLong ? 'var(--up)' : 'var(--dn)', flexShrink: 0 }} />

        {/* Pattern badge */}
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
          background: `${pColor}22`, color: pColor, border: `1px solid ${pColor}44`,
          whiteSpace: 'nowrap', minWidth: 90, textAlign: 'center',
        }}>
          {s.pattern_name?.replace(/_/g, ' ').toUpperCase()}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ fontWeight: 700, color: 'var(--txt)' }}>{s.underlying}</span>
            <span className={`badge ${isLong ? 'badge-up' : 'badge-dn'}`}>{s.direction?.toUpperCase()}</span>
          </div>
          <div className="conf-bar" style={{ width: 80, marginTop: 5 }}>
            <div className="progress-fill" style={{ width: `${conf}%`, background: conf >= 75 ? 'var(--up)' : conf >= 55 ? 'var(--orange)' : 'var(--txt3)' }} />
          </div>
        </div>

        {/* Prices */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0 16px', textAlign: 'right' }}>
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

        {/* Option contract */}
        {s.strike && (
          <div style={{ textAlign: 'right', minWidth: 80 }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)' }}>Contract</div>
            <div className="mono" style={{ fontSize: 11, fontWeight: 700, color: s.option_type === 'CE' ? 'var(--dn)' : 'var(--up)' }}>
              {s.strike?.toLocaleString('en-IN')} {s.option_type}
            </div>
            <div style={{ fontSize: 9, color: 'var(--txt3)' }}>{s.option_strategy?.toUpperCase()}</div>
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

        {/* Expected return */}
        <div style={{ textAlign: 'right', minWidth: 50 }}>
          <div style={{ fontSize: 10, color: 'var(--txt3)' }}>Exp.</div>
          <div className="mono up" style={{ fontWeight: 700, fontSize: 13 }}>+{s.expected_return_pct?.toFixed(1)}%</div>
        </div>

        <span style={{ color: 'var(--txt3)', fontSize: 11 }}>{exp ? '▲' : '▼'}</span>
      </div>

      {exp && (
        <div className="fade-up" style={{ padding: '0 12px 12px 25px' }}>
          <p style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.6, marginBottom: s.regime_trend ? 10 : 0 }}>
            {s.explanation}
          </p>
          {(s.regime_trend || s.delta != null) && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
              {s.regime_trend && (
                <span className={`badge ${s.regime_trend === 'bullish' ? 'badge-up' : s.regime_trend === 'bearish' ? 'badge-dn' : 'badge-warn'}`}>
                  {s.regime_trend} regime
                </span>
              )}
              {s.regime_volatility && (
                <span className="badge badge-mute">{s.regime_volatility} vol</span>
              )}
              {s.estimated_premium != null && (
                <span className="badge badge-mute">Premium ₹{s.estimated_premium?.toFixed(0)}</span>
              )}
              {s.max_loss != null && (
                <span className="badge badge-dn">Max loss ₹{s.max_loss?.toFixed(0)}</span>
              )}
              {s.vega != null && (
                <span className="badge badge-blue">Vega {s.vega?.toFixed(2)}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Mini equity sparkline ────────────────────────────────────────────────────

function EquitySparkline({ capital, pnl }: { capital: number; pnl: number }) {
  const data = Array.from({ length: 20 }, (_, i) => ({
    i, v: capital - pnl * 20 + (pnl / 20) * i * (0.8 + Math.random() * 0.4),
  }))
  return (
    <ResponsiveContainer width="100%" height={50}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="#2962ff" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#2962ff" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke="#2962ff" strokeWidth={1.5} fill="url(#sg)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
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

// ─── Tabs helper ─────────────────────────────────────────────────────────────

function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="tab-bar">
      {tabs.map(t => (
        <button key={t} className={`tab-btn ${active === t ? 'active' : ''}`} onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const qc = useQueryClient()
  const [selectedSym, setSelectedSym] = useState('NIFTY')
  const [group, setGroup] = useState('Indices')
  const [mainTab, setMainTab] = useState('Signals')
  const [scanning, setScanning] = useState(false)
  const [sortCol, setSortCol] = useState('chg')
  const [sortDir, setSortDir] = useState<'asc'|'desc'>('desc')

  const selected = ALL_ITEMS.find(i => i.sym === selectedSym) ?? ALL_ITEMS[0]
  const currentGroup = GROUPS.find(g => g.label === group)

  const { data: signals, isLoading: sigLoading } = useQuery({
    queryKey: ['signals', selectedSym],
    queryFn: () => fetchSignals({ status: 'active', underlying: selectedSym }),
    refetchInterval: 30000,
  })
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: fetchPortfolio, refetchInterval: 10000 })
  const { data: trades }    = useQuery({ queryKey: ['trades'],    queryFn: () => fetchTrades('paper') })

  const scanMutation = useMutation({
    mutationFn: () => { setScanning(true); return runSignals(selectedSym) },
    onSettled: () => { setScanning(false); qc.invalidateQueries({ queryKey: ['signals'] }) },
  })
  const initMutation = useMutation({
    mutationFn: initPortfolio,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })

  const signalList: any[] = signals?.signals ?? []
  const tradeList: any[]  = trades?.trades ?? []
  const hasPF = portfolio?.capital != null

  // Sort watchlist
  const sortedItems = [...(currentGroup?.items ?? [])].sort((a, b) => {
    const av = (a as any)[sortCol] ?? 0
    const bv = (b as any)[sortCol] ?? 0
    return sortDir === 'desc' ? bv - av : av - bv
  })
  const toggleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }
  const sortArrow = (col: string) => sortCol === col ? (sortDir === 'desc' ? ' ▼' : ' ▲') : ''

  // P&L chart data
  const closedTrades = tradeList.filter(t => t.status === 'closed')
  const pnlData = closedTrades.map((t, i) => ({ i: i + 1, pnl: t.pnl ?? 0 }))

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Left: Watchlist ───────────────────────────── */}
      <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>
        {/* Group tabs */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 1, padding: 6, borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
          {GROUPS.map(g => (
            <button
              key={g.label}
              onClick={() => { setGroup(g.label); setSelectedSym(g.items[0].sym) }}
              className="tv-btn"
              style={{
                padding: '3px 8px', fontSize: 10,
                background: group === g.label ? 'rgba(41,98,255,0.15)' : 'transparent',
                color: group === g.label ? 'var(--blue)' : 'var(--txt2)',
                border: `1px solid ${group === g.label ? 'rgba(41,98,255,0.35)' : 'transparent'}`,
              }}
            >
              {g.label}
            </button>
          ))}
        </div>

        {/* Dropdown instrument selector (mobile-friendly alternative) */}
        <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
          <select
            className="tv-select"
            style={{ width: '100%' }}
            value={selectedSym}
            onChange={e => setSelectedSym(e.target.value)}
          >
            {GROUPS.map(g => (
              <optgroup key={g.label} label={g.label}>
                {g.items.map(i => (
                  <option key={i.sym} value={i.sym}>{i.sym} — {i.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        {/* Table */}
        <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>
          <table className="tv-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort('sym')} style={{ textAlign: 'left' }}>Symbol{sortArrow('sym')}</th>
                <th onClick={() => toggleSort('ltp')}>LTP{sortArrow('ltp')}</th>
                <th onClick={() => toggleSort('chg')}>Chg%{sortArrow('chg')}</th>
                <th onClick={() => toggleSort('vol')}>Vol{sortArrow('vol')}</th>
                <th>OI</th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map(item => (
                <WatchRow
                  key={item.sym}
                  item={item}
                  selected={selectedSym === item.sym}
                  onSelect={() => setSelectedSym(item.sym)}
                />
              ))}
            </tbody>
          </table>
        </div>

        {/* Selected instrument detail bar */}
        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border)', background: 'var(--bg2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontWeight: 700, color: 'var(--txt)' }}>{selected.sym}</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 800, color: selected.chg >= 0 ? 'var(--up)' : 'var(--dn)', lineHeight: 1.2 }}>
                {selected.ltp.toLocaleString('en-IN')}
              </div>
              <div className="mono" style={{ fontSize: 11, color: selected.chg >= 0 ? 'var(--up)' : 'var(--dn)' }}>
                {chgStr(selected.chg)}
              </div>
            </div>
            <button
              onClick={() => scanMutation.mutate()}
              disabled={scanning}
              className="tv-btn tv-btn-primary"
              style={{ fontSize: 11 }}
            >
              {scanning ? '…' : '⚡ Scan'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Right: Main panel ─────────────────────────── */}
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
              <StatTile label="Heat" value={`${(portfolio.portfolio_heat_pct ?? 0).toFixed(1)}%`} sub={`${portfolio.open_positions ?? 0} open`} />
              <div style={{ flex: 1, padding: '4px 12px', display: 'flex', alignItems: 'center' }}>
                <div style={{ width: '100%' }}>
                  <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Equity (30d)</div>
                  <EquitySparkline capital={portfolio.capital} pnl={portfolio.daily_pnl ?? 0} />
                </div>
              </div>
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

        {/* Tab bar */}
        <Tabs
          tabs={['Signals', 'Portfolio', 'Trades', 'Patterns']}
          active={mainTab}
          onChange={setMainTab}
        />

        {/* Tab content */}
        <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>

          {/* ── Signals ── */}
          {mainTab === 'Signals' && (
            <div>
              {/* Toolbar */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg2)' }}>
                <span style={{ color: 'var(--txt2)', fontSize: 12 }}>
                  Showing signals for <strong style={{ color: 'var(--txt)' }}>{selectedSym}</strong>
                </span>
                {signalList.length > 0 && (
                  <span className="badge badge-blue">{signalList.length} active</span>
                )}
                <div style={{ flex: 1 }} />
                <button className="tv-btn tv-btn-primary" style={{ fontSize: 11 }} onClick={() => scanMutation.mutate()} disabled={scanning}>
                  {scanning ? '⏳ Scanning…' : `⚡ Scan ${selectedSym}`}
                </button>
              </div>

              {sigLoading && (
                <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 56 }} />)}
                </div>
              )}

              {!sigLoading && signalList.length === 0 && (
                <div style={{ textAlign: 'center', padding: '48px 24px' }}>
                  <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.3 }}>◉</div>
                  <p style={{ color: 'var(--txt2)', marginBottom: 6 }}>No signals for {selectedSym}</p>
                  <p style={{ color: 'var(--txt3)', fontSize: 11 }}>Click ⚡ Scan to run pattern detection</p>
                </div>
              )}

              {signalList.map((s: any) => <SignalRow key={s.id} s={s} />)}
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
                  {/* Stat grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                    {[
                      { label: 'Capital',       val: fmtINR(portfolio.capital),                                              color: 'var(--txt)' },
                      { label: 'Day P&L',        val: fmtINR(portfolio.daily_pnl),                                           color: (portfolio.daily_pnl??0)>=0 ? 'var(--up)' : 'var(--dn)' },
                      { label: 'Total Trades',   val: String(portfolio.total_trades ?? 0),                                   color: 'var(--txt)' },
                      { label: 'Win Rate',       val: `${((portfolio.win_rate??0)*100).toFixed(1)}%`,                        color: (portfolio.win_rate??0)>=0.55 ? 'var(--up)' : 'var(--orange)' },
                      { label: 'Open Positions', val: String(portfolio.open_positions ?? 0),                                 color: 'var(--txt)' },
                      { label: 'Portfolio Heat', val: `${(portfolio.portfolio_heat_pct??0).toFixed(1)}%`,                    color: 'var(--txt)' },
                    ].map(({ label, val, color }) => (
                      <div key={label} className="tv-card" style={{ padding: '10px 14px' }}>
                        <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, color }}>{val}</div>
                      </div>
                    ))}
                  </div>

                  {/* Promotion checklist */}
                  <div className="tv-card" style={{ padding: 14 }}>
                    <div className="panel-hdr" style={{ marginBottom: 12, padding: 0, borderBottom: 'none', fontSize: 11 }}>
                      Live Promotion Criteria
                    </div>
                    {[
                      { label: 'Paper Trades',  cur: portfolio.total_trades ?? 0, req: 60 },
                      { label: 'Win Rate ≥55%', cur: Math.round((portfolio.win_rate??0)*100), req: 55, unit: '%' },
                    ].map(({ label, cur, req, unit }) => {
                      const done = cur >= req
                      const p = Math.min(100, cur / req * 100)
                      return (
                        <div key={label} style={{ marginBottom: 10 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: 'var(--txt2)' }}>{label}</span>
                            <span className="mono" style={{ color: done ? 'var(--up)' : 'var(--orange)' }}>
                              {cur}{unit ?? ''} / {req}{unit ?? ''} {done ? '✓' : ''}
                            </span>
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
              {/* P&L bar chart */}
              {pnlData.length > 0 && (
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Trade P&L History</div>
                  <ResponsiveContainer width="100%" height={80}>
                    <BarChart data={pnlData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                      <Bar dataKey="pnl" fill="var(--up)" radius={[2, 2, 0, 0]}
                        label={false}
                        style={{ fill: 'var(--up)' }}
                      />
                      <ReferenceLine y={0} stroke="var(--border2)" />
                      <Tooltip
                        contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11 }}
                        formatter={(v: number) => [fmtINR(v), 'P&L']}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {tradeList.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>No trades yet.</div>
              ) : (
                <table className="tv-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Symbol</th>
                      <th>Dir</th>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>P&L</th>
                      <th>Return</th>
                      <th style={{ textAlign: 'left' }}>Pattern</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tradeList.map((t: any) => {
                      const pnl = t.pnl ?? 0
                      const ret = t.entry_price ? (pnl / t.entry_price * 100).toFixed(1) : null
                      return (
                        <tr key={t.id}>
                          <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--txt)' }}>{t.symbol}</td>
                          <td><span className={`badge ${t.direction==='long' ? 'badge-up' : 'badge-dn'}`}>{t.direction?.toUpperCase()}</span></td>
                          <td className="mono">{fmtINR(t.entry_price)}</td>
                          <td className="mono muted">{t.exit_price ? fmtINR(t.exit_price) : '—'}</td>
                          <td className={`mono ${pnl >= 0 ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>
                            {t.status === 'closed' ? `${pnl >= 0 ? '+' : ''}${fmtINR(pnl)}` : '—'}
                          </td>
                          <td className={`mono ${pnl >= 0 ? 'up' : 'dn'}`}>{ret ? `${pnl >= 0 ? '+' : ''}${ret}%` : '—'}</td>
                          <td style={{ textAlign: 'left', color: 'var(--txt2)', fontSize: 11 }}>{t.pattern?.replace(/_/g, ' ')}</td>
                          <td><span className={`badge ${t.status === 'open' ? 'badge-blue' : 'badge-mute'}`}>{t.status}</span></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
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
                        <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: `${color}22`, color, border: `1px solid ${color}44`, marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                          {key}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 4 }}>
                        <strong style={{ color: 'var(--txt2)' }}>Triggers when:</strong> {when}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--txt2)' }}>
                        <strong>Edge:</strong> {edge}
                      </div>
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
