import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTrades, fetchPortfolio } from '../api/client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, BarChart, Bar } from 'recharts'

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const TABS = ['Open', 'Closed', 'Promotion'] as const
type Tab = typeof TABS[number]

export default function PaperTrading() {
  const [tab, setTab] = useState<Tab>('Open')
  const { data: portfolio } = useQuery({ queryKey: ['portfolio', 'paper'], queryFn: () => fetchPortfolio('paper'), refetchInterval: 5000 })
  const { data: trades }    = useQuery({ queryKey: ['trades', 'paper'],    queryFn: () => fetchTrades('paper') })

  const list: any[] = trades?.trades ?? []
  const open   = list.filter(t => t.status === 'open')
  const closed = list.filter(t => t.status === 'closed')
  const totalPnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0)
  const winners = closed.filter(t => (t.pnl ?? 0) > 0).length
  const winRate = closed.length > 0 ? winners / closed.length : null

  const pnlCurve = closed.map((t, i) => ({
    i: i + 1,
    cum: closed.slice(0, i + 1).reduce((s, x) => s + (x.pnl ?? 0), 0),
    pnl: t.pnl ?? 0,
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Stat bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg2)', flexShrink: 0 }}>
        {[
          { label: 'Capital',      val: fmtINR(portfolio?.capital),   color: 'var(--txt)' },
          { label: 'Realised P&L', val: fmtINR(totalPnl),             color: totalPnl >= 0 ? 'var(--up)' : 'var(--dn)' },
          { label: 'Win Rate',     val: winRate != null ? `${(winRate * 100).toFixed(1)}%` : '—', color: (winRate ?? 0) >= 0.55 ? 'var(--up)' : 'var(--orange)' },
          { label: 'Open',         val: String(open.length),           color: 'var(--txt)' },
          { label: 'Closed',       val: String(closed.length),         color: 'var(--txt)' },
        ].map(({ label, val, color }) => (
          <div key={label} style={{ padding: '8px 16px', borderRight: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700, color }}>{val}</div>
          </div>
        ))}
        <div style={{ flex: 1 }} />
        <a href="/api/v1/trades/export/csv?mode=paper" download
          className="tv-btn tv-btn-ghost"
          style={{ alignSelf: 'center', marginRight: 12, padding: '5px 12px', fontSize: 11, textDecoration: 'none' }}>
          ⬇ Export CSV
        </a>
      </div>

      {/* Tabs */}
      <div className="tab-bar">
        {TABS.map(t => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t}
            {t === 'Open' && open.length > 0 && (
              <span className="badge badge-blue" style={{ marginLeft: 6 }}>{open.length}</span>
            )}
          </button>
        ))}
      </div>

      <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>
        {/* ── Open ── */}
        {tab === 'Open' && (
          open.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>No open positions.</div>
          ) : (
            <table className="tv-table">
              <thead><tr>
                <th style={{ textAlign: 'left' }}>Symbol</th>
                <th>Direction</th>
                <th>Entry</th>
                <th style={{ textAlign: 'left' }}>Pattern</th>
              </tr></thead>
              <tbody>
                {open.map((t: any) => (
                  <tr key={t.id}>
                    <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--txt)' }}>{t.symbol}</td>
                    <td><span className={`badge ${t.direction === 'long' ? 'badge-up' : 'badge-dn'}`}>{t.direction?.toUpperCase()}</span></td>
                    <td className="mono">{fmtINR(t.entry_price)}</td>
                    <td style={{ textAlign: 'left', color: 'var(--txt2)' }}>{t.pattern?.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {/* ── Closed ── */}
        {tab === 'Closed' && (
          <div>
            {pnlCurve.length > 1 && (
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Cumulative P&L</div>
                <ResponsiveContainer width="100%" height={90}>
                  <LineChart data={pnlCurve} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                    <XAxis dataKey="i" hide />
                    <YAxis hide domain={['auto', 'auto']} />
                    <ReferenceLine y={0} stroke="var(--border2)" />
                    <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11 }}
                      formatter={(v: number) => [fmtINR(v), 'Cum P&L']} />
                    <Line type="monotone" dataKey="cum" stroke="var(--blue)" strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {closed.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>No closed trades yet.</div>
            ) : (
              <table className="tv-table">
                <thead><tr>
                  <th style={{ textAlign: 'left' }}>Symbol</th>
                  <th>Dir</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>P&L</th>
                  <th>Return</th>
                  <th style={{ textAlign: 'left' }}>Pattern</th>
                  <th style={{ textAlign: 'left' }}>Exit</th>
                </tr></thead>
                <tbody>
                  {closed.map((t: any) => {
                    const pnl = t.pnl ?? 0
                    const ret = t.entry_price ? (pnl / t.entry_price * 100).toFixed(1) : null
                    const exitLabel: Record<string, string> = {
                      target_hit: 'Target', stop_hit: 'Stop', manual: 'Manual',
                      eod_close: 'EOD', expiry: 'Expiry', trailing_stop: 'Trail Stop',
                    }
                    const exitColor: Record<string, string> = {
                      target_hit: 'var(--up)', stop_hit: 'var(--dn)', manual: 'var(--txt2)',
                      eod_close: 'var(--txt3)', expiry: 'var(--txt3)', trailing_stop: 'var(--up)',
                    }
                    return (
                      <tr key={t.id}>
                        <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--txt)' }}>{t.symbol}</td>
                        <td><span className={`badge ${t.direction === 'long' ? 'badge-up' : 'badge-dn'}`}>{t.direction?.[0]?.toUpperCase()}</span></td>
                        <td className="mono">{fmtINR(t.entry_price)}</td>
                        <td className="mono muted">{t.exit_price ? fmtINR(t.exit_price) : '—'}</td>
                        <td className={`mono ${pnl >= 0 ? 'up' : 'dn'}`} style={{ fontWeight: 600 }}>{pnl >= 0 ? '+' : ''}{fmtINR(pnl)}</td>
                        <td className={`mono ${pnl >= 0 ? 'up' : 'dn'}`}>{ret ? `${pnl >= 0 ? '+' : ''}${ret}%` : '—'}</td>
                        <td style={{ textAlign: 'left', color: 'var(--txt2)', fontSize: 11 }}>{t.pattern?.replace(/_/g, ' ')}</td>
                        <td style={{ textAlign: 'left', fontSize: 10, color: t.exit_reason ? exitColor[t.exit_reason] ?? 'var(--txt3)' : 'var(--txt3)' }}>
                          {t.exit_reason ? (exitLabel[t.exit_reason] ?? t.exit_reason) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* ── Promotion ── */}
        {tab === 'Promotion' && (
          <div style={{ padding: 16, maxWidth: 600 }}>
            <div className="tv-card" style={{ padding: 16 }}>
              <div className="panel-hdr" style={{ padding: 0, borderBottom: 'none', marginBottom: 16 }}>Live Trading Promotion Criteria</div>
              <p style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 16 }}>
                Complete all requirements below to unlock real-capital live trading on AlphaFO.
              </p>
              {[
                { label: 'Paper Trades Completed', cur: portfolio?.total_trades ?? 0, req: 60, unit: '' },
                { label: 'Win Rate',               cur: Math.round((portfolio?.win_rate ?? 0) * 100), req: 55, unit: '%' },
                { label: 'Max Drawdown Under',     cur: 5, req: 10, unit: '%', inverse: true },
              ].map(({ label, cur, req, unit, inverse }) => {
                const done = inverse ? cur <= req : cur >= req
                const p    = Math.min(100, cur / req * 100)
                return (
                  <div key={label} style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
                      <span style={{ color: 'var(--txt2)' }}>{label}</span>
                      <span className="mono" style={{ color: done ? 'var(--up)' : 'var(--orange)', fontWeight: 600 }}>
                        {cur}{unit} / {req}{unit} {done ? '✓' : ''}
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
    </div>
  )
}
