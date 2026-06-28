import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchBacktests, runBacktest } from '../api/client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

const PATTERNS = [
  { key: 'gap_fill',       label: 'Gap Fill',       color: '#7b61ff' },
  { key: 'pcr_divergence', label: 'PCR Divergence', color: '#2962ff' },
  { key: 'mean_reversion', label: 'Mean Reversion', color: '#00bcd4' },
  { key: 'oi_buildup',     label: 'OI Buildup',     color: '#ff9800' },
  { key: 'vwap_oi',        label: 'VWAP + OI',      color: '#26a69a' },
  { key: 'iv_crush',       label: 'IV Crush',       color: '#e91e63' },
  { key: 'max_pain',       label: 'Max Pain',       color: '#ff5722' },
  { key: 'expiry_week',    label: 'Expiry Week',    color: '#9c27b0' },
]

const GROUPS = [
  { label: 'Indices',  items: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'] },
  { label: 'Banking',  items: ['HDFCBANK', 'ICICIBANK', 'AXISBANK', 'SBIN', 'KOTAKBANK'] },
  { label: 'IT',       items: ['TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM'] },
  { label: 'Energy',   items: ['RELIANCE', 'ONGC', 'NTPC', 'POWERGRID'] },
  { label: 'Auto',     items: ['TATAMOTORS', 'MARUTI', 'M&M', 'BAJAJ-AUTO'] },
  { label: 'Pharma',   items: ['SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB'] },
]

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const fmtPct = (n?: number | null) =>
  n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

export default function Backtest() {
  const qc = useQueryClient()
  const [group, setGroup] = useState('Indices')
  const [form, setForm] = useState({
    underlying: 'NIFTY',
    start_date: '2023-01-01',
    end_date:   '2024-01-01',
    patterns:   PATTERNS.map(p => p.key),
    name:       'My Backtest',
  })
  const [selected, setSelected] = useState<any>(null)

  const { data } = useQuery({ queryKey: ['backtests'], queryFn: fetchBacktests })
  const mutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backtests'] }),
  })

  const togglePattern = (k: string) =>
    setForm(f => ({
      ...f,
      patterns: f.patterns.includes(k) ? f.patterns.filter(x => x !== k) : [...f.patterns, k],
    }))

  const results: any[] = data?.results ?? []
  const currentGroup   = GROUPS.find(g => g.label === group)

  const equityCurve = selected?.equity_curve?.map((v: number, i: number) => ({ i, v })) ?? []

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Left: Config ─────────────────────────────────── */}
      <div style={{ width: 320, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', overflow: 'hidden' }}>
        <div className="panel-hdr">Configure Backtest</div>
        <div className="scroll-y" style={{ flex: 1, padding: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* Strategy name */}
          <div>
            <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Strategy Name</div>
            <input
              className="tv-input"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. NIFTY momentum"
            />
          </div>

          {/* Instrument */}
          <div>
            <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Instrument</div>
            {/* Group chips */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
              {GROUPS.map(g => (
                <button
                  key={g.label}
                  className="tv-btn"
                  onClick={() => { setGroup(g.label); setForm(f => ({ ...f, underlying: g.items[0] })) }}
                  style={{
                    padding: '2px 8px', fontSize: 10,
                    background: group === g.label ? 'rgba(41,98,255,0.15)' : 'transparent',
                    color: group === g.label ? 'var(--blue)' : 'var(--txt2)',
                    border: `1px solid ${group === g.label ? 'rgba(41,98,255,0.35)' : 'transparent'}`,
                  }}
                >
                  {g.label}
                </button>
              ))}
            </div>
            <select
              className="tv-select"
              style={{ width: '100%' }}
              value={form.underlying}
              onChange={e => setForm(f => ({ ...f, underlying: e.target.value }))}
            >
              {currentGroup?.items.map(sym => (
                <option key={sym} value={sym}>{sym}</option>
              ))}
            </select>
          </div>

          {/* Date range */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: 'Start Date', key: 'start_date' },
              { label: 'End Date',   key: 'end_date' },
            ].map(({ label, key }) => (
              <div key={key}>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
                <input
                  type="date"
                  className="tv-input"
                  value={(form as any)[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                />
              </div>
            ))}
          </div>

          {/* Patterns */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Patterns</div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="tv-btn tv-btn-ghost" style={{ padding: '2px 7px', fontSize: 10 }}
                  onClick={() => setForm(f => ({ ...f, patterns: PATTERNS.map(p => p.key) }))}>All</button>
                <button className="tv-btn tv-btn-ghost" style={{ padding: '2px 7px', fontSize: 10 }}
                  onClick={() => setForm(f => ({ ...f, patterns: [] }))}>None</button>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {PATTERNS.map(({ key, label, color }) => {
                const on = form.patterns.includes(key)
                return (
                  <button
                    key={key}
                    onClick={() => togglePattern(key)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 8px', borderRadius: 4, cursor: 'pointer',
                      background: on ? `${color}14` : 'transparent',
                      border: `1px solid ${on ? `${color}44` : 'var(--border)'}`,
                      transition: 'all 0.12s', textAlign: 'left',
                    }}
                  >
                    <div style={{ width: 8, height: 8, borderRadius: 2, background: on ? color : 'var(--border2)', flexShrink: 0, transition: 'background 0.12s' }} />
                    <span style={{ fontSize: 12, color: on ? 'var(--txt)' : 'var(--txt2)', fontWeight: on ? 600 : 400 }}>{label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Run button */}
          <button
            className="tv-btn tv-btn-primary"
            style={{ width: '100%', justifyContent: 'center', padding: '9px 0' }}
            disabled={mutation.isPending || form.patterns.length === 0}
            onClick={() => mutation.mutate(form)}
          >
            {mutation.isPending ? '⏳ Running…' : '▶ Run Backtest'}
          </button>

          {mutation.isError && (
            <div style={{ fontSize: 11, color: 'var(--dn)', padding: '8px 10px', background: 'rgba(239,83,80,0.08)', borderRadius: 4, border: '1px solid rgba(239,83,80,0.2)' }}>
              Failed to run backtest. Check backend logs.
            </div>
          )}
        </div>
      </div>

      {/* ── Right: Results ────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {selected ? (
          /* Detail view */
          <>
            <div className="toolbar">
              <button className="tv-btn tv-btn-ghost" style={{ fontSize: 11 }} onClick={() => setSelected(null)}>← Back</button>
              <span style={{ fontWeight: 700, color: 'var(--txt)' }}>{selected.name}</span>
              <span style={{ color: 'var(--txt2)', fontSize: 11 }}>{selected.underlying}</span>
              <span className="badge badge-mute">{selected.start_date} – {selected.end_date}</span>
            </div>

            <div className="scroll-y" style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Stat row */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
                {[
                  { label: 'Total Return',  val: fmtPct(selected.total_return_pct),  color: (selected.total_return_pct ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)' },
                  { label: 'Win Rate',      val: `${((selected.win_rate ?? 0) * 100).toFixed(1)}%`, color: (selected.win_rate ?? 0) >= 0.55 ? 'var(--up)' : 'var(--orange)' },
                  { label: 'Max Drawdown',  val: `${(selected.max_drawdown_pct ?? 0).toFixed(1)}%`,  color: 'var(--dn)' },
                  { label: 'Sharpe',        val: (selected.sharpe_ratio ?? 0).toFixed(2),             color: 'var(--txt)' },
                  { label: 'Total Trades',  val: String(selected.total_trades ?? 0),                  color: 'var(--txt)' },
                ].map(({ label, val, color }) => (
                  <div key={label} className="tv-card" style={{ padding: '10px 12px' }}>
                    <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
                    <div className="mono" style={{ fontSize: 15, fontWeight: 700, color }}>{val}</div>
                  </div>
                ))}
              </div>

              {/* Equity curve */}
              {equityCurve.length > 1 && (
                <div className="tv-card" style={{ padding: 14 }}>
                  <div className="section-title">Equity Curve</div>
                  <ResponsiveContainer width="100%" height={140}>
                    <LineChart data={equityCurve} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                      <XAxis dataKey="i" hide />
                      <YAxis hide domain={['auto', 'auto']} />
                      <ReferenceLine y={100} stroke="var(--border2)" strokeDasharray="3 3" />
                      <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11 }}
                        formatter={(v: number) => [`${v.toFixed(1)}`, 'Index']} />
                      <Line type="monotone" dataKey="v" stroke="var(--blue)" strokeWidth={1.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Pattern breakdown */}
              {selected.pattern_breakdown && (
                <div className="tv-card" style={{ overflow: 'hidden' }}>
                  <div className="panel-hdr">Pattern Breakdown</div>
                  <table className="tv-table">
                    <thead>
                      <tr>
                        <th style={{ textAlign: 'left' }}>Pattern</th>
                        <th>Trades</th>
                        <th>Win Rate</th>
                        <th>Avg Return</th>
                        <th>Net P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(selected.pattern_breakdown).map(([key, v]: any) => (
                        <tr key={key}>
                          <td style={{ textAlign: 'left' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 6, height: 6, borderRadius: 1, background: PATTERNS.find(p => p.key === key)?.color ?? 'var(--txt3)' }} />
                              <span style={{ color: 'var(--txt)' }}>{key.replace(/_/g, ' ')}</span>
                            </div>
                          </td>
                          <td className="mono">{v.trades ?? '—'}</td>
                          <td className={`mono ${(v.win_rate ?? 0) >= 0.5 ? 'up' : 'dn'}`}>{v.win_rate != null ? `${(v.win_rate * 100).toFixed(1)}%` : '—'}</td>
                          <td className={`mono ${(v.avg_return ?? 0) >= 0 ? 'up' : 'dn'}`}>{v.avg_return != null ? fmtPct(v.avg_return) : '—'}</td>
                          <td className={`mono ${(v.net_pnl ?? 0) >= 0 ? 'up' : 'dn'}`}>{v.net_pnl != null ? fmtINR(v.net_pnl) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        ) : (
          /* List view */
          <>
            <div className="panel-hdr">
              Backtest Results
              {results.length > 0 && <span className="badge badge-blue">{results.length}</span>}
            </div>

            {mutation.isPending && (
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 56 }} />)}
              </div>
            )}

            {!mutation.isPending && results.length === 0 && (
              <div style={{ textAlign: 'center', padding: '48px 24px' }}>
                <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.25 }}>◉</div>
                <p style={{ color: 'var(--txt2)', marginBottom: 4 }}>No backtests yet</p>
                <p style={{ color: 'var(--txt3)', fontSize: 11 }}>Configure a run on the left and click ▶ Run Backtest</p>
              </div>
            )}

            {results.length > 0 && (
              <div className="scroll-y" style={{ flex: 1 }}>
                <table className="tv-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Name</th>
                      <th style={{ textAlign: 'left' }}>Instrument</th>
                      <th>Period</th>
                      <th>Return</th>
                      <th>Win Rate</th>
                      <th>Max DD</th>
                      <th>Sharpe</th>
                      <th>Trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r: any) => (
                      <tr key={r.id} onClick={() => setSelected(r)}>
                        <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--txt)' }}>{r.name}</td>
                        <td style={{ textAlign: 'left' }}>
                          <span className="badge badge-mute">{r.underlying}</span>
                        </td>
                        <td className="muted" style={{ fontSize: 11 }}>{r.start_date?.slice(0,7)} – {r.end_date?.slice(0,7)}</td>
                        <td className={`mono ${(r.total_return_pct ?? 0) >= 0 ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>
                          {fmtPct(r.total_return_pct)}
                        </td>
                        <td className={`mono ${(r.win_rate ?? 0) >= 0.55 ? 'up' : 'dn'}`}>
                          {r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : '—'}
                        </td>
                        <td className="mono dn">{r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : '—'}</td>
                        <td className="mono">{r.sharpe_ratio?.toFixed(2) ?? '—'}</td>
                        <td className="mono muted">{r.total_trades ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
