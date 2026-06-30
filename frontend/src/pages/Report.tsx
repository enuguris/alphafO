import { useQuery } from '@tanstack/react-query'
import { fetchReport } from '../api/client'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine, Cell,
} from 'recharts'

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const fmtPct = (n: number) => `${(n * 100).toFixed(1)}%`
const pnlColor = (n: number) => n >= 0 ? 'var(--up)' : 'var(--dn)'

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="tv-card" style={{ padding: '12px 14px' }}>
      <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
      <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: color ?? 'var(--txt)' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export default function Report() {
  const { data: report, isLoading, refetch } = useQuery({
    queryKey: ['report'],
    queryFn: fetchReport,
    staleTime: 60_000,
  })

  if (isLoading) return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--txt3)' }}>
      Loading report…
    </div>
  )

  if (!report) return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--txt3)' }}>
      No data yet. Run some paper trades first.
    </div>
  )

  const s = report.summary
  const hasTrades = s.total_trades > 0

  return (
    <div className="scroll-y" style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--txt)' }}>Performance Report</div>
          <div style={{ fontSize: 11, color: 'var(--txt3)' }}>
            NIFTY + BANKNIFTY · Paper trading · {report.generated_at?.slice(0, 10)}
          </div>
        </div>
        <button className="tv-btn tv-btn-ghost" style={{ marginLeft: 'auto', fontSize: 11 }} onClick={() => refetch()}>
          ↺ Refresh
        </button>
      </div>

      {/* Summary stats — row 1 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <StatCard label="Total Trades" value={String(s.total_trades)} sub={`${s.winners}W / ${s.losers}L`} />
        <StatCard label="Win Rate" value={fmtPct(s.win_rate)} color={s.win_rate >= 0.55 ? 'var(--up)' : s.win_rate >= 0.45 ? 'var(--orange)' : 'var(--dn)'} sub={`PF ${s.profit_factor?.toFixed(2) ?? '—'}`} />
        <StatCard label="Total P&L" value={fmtINR(s.total_pnl)} color={pnlColor(s.total_pnl)} sub={`Charges: ${fmtINR(s.total_charges)}`} />
        <StatCard label="Avg per Trade" value={fmtINR(s.avg_pnl)} color={pnlColor(s.avg_pnl)} sub={`W: ${fmtINR(s.avg_winner)} / L: ${fmtINR(s.avg_loser)}`} />
      </div>
      {/* Summary stats — row 2 (risk metrics) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <StatCard
          label="Sharpe Ratio"
          value={s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : '—'}
          color={s.sharpe_ratio == null ? undefined : s.sharpe_ratio >= 1 ? 'var(--up)' : s.sharpe_ratio >= 0 ? 'var(--orange)' : 'var(--dn)'}
          sub="Annualised (252d)"
        />
        <StatCard
          label="Max Drawdown"
          value={s.max_drawdown_pct != null ? `${s.max_drawdown_pct.toFixed(1)}%` : '—'}
          color={s.max_drawdown_pct == null ? undefined : s.max_drawdown_pct < 5 ? 'var(--up)' : s.max_drawdown_pct < 15 ? 'var(--orange)' : 'var(--dn)'}
          sub="Peak to trough"
        />
        <StatCard
          label="Max Consec Losses"
          value={s.max_consec_losses != null ? String(s.max_consec_losses) : '—'}
          color={s.max_consec_losses == null ? undefined : s.max_consec_losses <= 2 ? 'var(--up)' : s.max_consec_losses <= 4 ? 'var(--orange)' : 'var(--dn)'}
          sub="In a row"
        />
        <StatCard
          label="Avg Hold Time"
          value={s.avg_hold_hours != null ? `${s.avg_hold_hours}h` : '—'}
          sub="Per closed trade"
        />
      </div>

      {!hasTrades && (
        <div className="tv-card" style={{ padding: 32, textAlign: 'center', color: 'var(--txt3)' }}>
          No closed paper trades yet. Trades will appear here after market hours once signals are auto-executed and closed.
        </div>
      )}

      {hasTrades && (
        <>
          {/* Equity curve */}
          {report.equity_curve?.length > 0 && (
            <div className="tv-card" style={{ padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>Equity Curve (Cumulative P&L)</div>
              <ResponsiveContainer width="100%" height={160}>
                <AreaChart data={report.equity_curve}>
                  <defs>
                    <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--up)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--up)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', fontSize: 11 }}
                    formatter={(v: any) => [fmtINR(v), '']}
                  />
                  <ReferenceLine y={0} stroke="var(--border)" />
                  <Area dataKey="cumulative" stroke="var(--up)" fill="url(#pnlGrad)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Underlying + pattern breakdown */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {/* By underlying */}
            <div className="tv-card" style={{ padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>By Underlying</div>
              {Object.entries(report.by_underlying ?? {}).map(([sym, d]: [string, any]) => (
                <div key={sym} style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, color: 'var(--blue)' }}>{sym}</span>
                    <span className="mono" style={{ color: pnlColor(d.total_pnl), fontWeight: 700 }}>{fmtINR(d.total_pnl)}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--txt2)' }}>
                    <span>{d.trades} trades</span>
                    <span style={{ color: d.win_rate >= 0.55 ? 'var(--up)' : 'var(--dn)' }}>{fmtPct(d.win_rate)} WR</span>
                    <span>avg {fmtINR(d.avg_pnl)}</span>
                  </div>
                </div>
              ))}
              {!Object.keys(report.by_underlying ?? {}).length && (
                <div style={{ color: 'var(--txt3)', fontSize: 11 }}>No data yet</div>
              )}
            </div>

            {/* By timeframe */}
            <div className="tv-card" style={{ padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>By Timeframe</div>
              {(report.by_timeframe ?? []).map((d: any) => (
                <div key={d.timeframe} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ minWidth: 42, fontSize: 11, fontWeight: 700, color: 'var(--orange)' }}>{d.timeframe}</span>
                  <span style={{ fontSize: 11, color: 'var(--txt3)' }}>{d.trades} trades</span>
                  <span style={{ fontSize: 11, color: d.win_rate >= 0.55 ? 'var(--up)' : 'var(--dn)' }}>{fmtPct(d.win_rate)} WR</span>
                  <span className="mono" style={{ marginLeft: 'auto', color: pnlColor(d.total_pnl), fontWeight: 600, fontSize: 11 }}>{fmtINR(d.total_pnl)}</span>
                </div>
              ))}
              {!(report.by_timeframe ?? []).length && (
                <div style={{ color: 'var(--txt3)', fontSize: 11 }}>No data yet</div>
              )}
            </div>
          </div>

          {/* Pattern breakdown */}
          <div className="tv-card" style={{ padding: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 10 }}>Pattern Performance</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr style={{ color: 'var(--txt3)', fontSize: 10, borderBottom: '1px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 0' }}>Pattern</th>
                  <th style={{ textAlign: 'right' }}>Trades</th>
                  <th style={{ textAlign: 'right' }}>Win Rate</th>
                  <th style={{ textAlign: 'right' }}>Avg P&L</th>
                  <th style={{ textAlign: 'right' }}>Total P&L</th>
                  <th style={{ textAlign: 'right' }}>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {(report.by_pattern ?? []).map((p: any) => {
                  const working = p.win_rate >= 0.55 && p.avg_pnl > 0
                  const neutral = p.win_rate >= 0.5 || p.avg_pnl > 0
                  return (
                    <tr key={p.pattern} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 0', fontWeight: 600, color: 'var(--txt)' }}>
                        {p.pattern.replace(/_/g, ' ')}
                        <div style={{ fontSize: 9, color: 'var(--txt3)' }}>{p.underlying?.join(', ')}</div>
                      </td>
                      <td className="mono" style={{ textAlign: 'right', color: 'var(--txt2)' }}>{p.trades}</td>
                      <td className="mono" style={{ textAlign: 'right', color: p.win_rate >= 0.55 ? 'var(--up)' : 'var(--dn)', fontWeight: 600 }}>{fmtPct(p.win_rate)}</td>
                      <td className="mono" style={{ textAlign: 'right', color: pnlColor(p.avg_pnl) }}>{fmtINR(p.avg_pnl)}</td>
                      <td className="mono" style={{ textAlign: 'right', color: pnlColor(p.total_pnl), fontWeight: 700 }}>{fmtINR(p.total_pnl)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, fontWeight: 700,
                          background: working ? 'rgba(38,166,154,0.15)' : neutral ? 'rgba(255,152,0,0.15)' : 'rgba(239,83,80,0.15)',
                          color: working ? 'var(--up)' : neutral ? 'var(--orange)' : 'var(--dn)',
                        }}>
                          {working ? '✓ WORKING' : neutral ? '~ MIXED' : '✗ NOT WORKING'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {!(report.by_pattern ?? []).length && (
              <div style={{ color: 'var(--txt3)', fontSize: 11, padding: '8px 0' }}>No pattern data yet</div>
            )}
          </div>

          {/* Best / worst trades */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              { label: 'Best Trades', trades: report.best_trades ?? [], up: true },
              { label: 'Worst Trades', trades: report.worst_trades ?? [], up: false },
            ].map(({ label, trades: tlist, up }) => (
              <div key={label} className="tv-card" style={{ padding: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 8 }}>{label}</div>
                {tlist.map((t: any, i: number) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                    <span style={{ color: 'var(--txt3)', minWidth: 14 }}>{i + 1}.</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, color: 'var(--txt)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {t.underlying} {t.strike} {t.option_type}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                        {t.exit_reason?.replace('_', ' ')} · {t.exit_time?.slice(0, 10)}
                      </div>
                    </div>
                    <span className="mono" style={{ fontWeight: 700, color: pnlColor(t.realized_pnl) }}>{fmtINR(t.realized_pnl)}</span>
                  </div>
                ))}
                {!tlist.length && <div style={{ color: 'var(--txt3)', fontSize: 11 }}>None yet</div>}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Open trades */}
      {(report.open_trades ?? []).length > 0 && (
        <div className="tv-card" style={{ padding: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 8 }}>
            Open Positions ({report.open_trades.length})
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: 'var(--txt3)', fontSize: 10, borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 0' }}>Contract</th>
                <th style={{ textAlign: 'right' }}>Entry</th>
                <th style={{ textAlign: 'right' }}>Current</th>
                <th style={{ textAlign: 'right' }}>Target</th>
                <th style={{ textAlign: 'right' }}>Stop</th>
                <th style={{ textAlign: 'right' }}>Unreal P&L</th>
                <th style={{ textAlign: 'right' }}>Days</th>
              </tr>
            </thead>
            <tbody>
              {report.open_trades.map((t: any) => (
                <tr key={t.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 0' }}>
                    <span style={{ fontWeight: 700 }}>{t.underlying}</span>
                    <span style={{ color: t.option_type === 'CE' ? 'var(--blue)' : '#e91e63', marginLeft: 4 }}>
                      {t.strike} {t.option_type}
                    </span>
                    <div style={{ fontSize: 9, color: 'var(--txt3)' }}>{t.expiry_display}</div>
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--txt2)' }}>₹{t.entry_price?.toFixed(1)}</td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--txt)' }}>₹{t.current_price?.toFixed(1)}</td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--up)', fontSize: 10 }}>₹{t.target_price?.toFixed(1)}</td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--dn)', fontSize: 10 }}>₹{t.stop_loss?.toFixed(1)}</td>
                  <td className="mono" style={{ textAlign: 'right', fontWeight: 700, color: pnlColor(t.unrealized_pnl) }}>{fmtINR(t.unrealized_pnl)}</td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--txt3)' }}>{t.days_held}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Discovered patterns */}
      <div className="tv-card" style={{ padding: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 8 }}>
          Discovered Patterns ({report.discovered_patterns?.length ?? 0})
          <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--txt3)', marginLeft: 8 }}>
            statistically mined from NIFTY + BANKNIFTY historical data
          </span>
        </div>
        {(report.discovered_patterns ?? []).length === 0 ? (
          <div style={{ color: 'var(--txt3)', fontSize: 11 }}>
            No patterns discovered yet. Run pattern discovery from the Pattern Finder page.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: 'var(--txt3)', fontSize: 10, borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 0' }}>Pattern</th>
                <th style={{ textAlign: 'right' }}>TF</th>
                <th style={{ textAlign: 'right' }}>Dir</th>
                <th style={{ textAlign: 'right' }}>Mined WR</th>
                <th style={{ textAlign: 'right' }}>Effect</th>
                <th style={{ textAlign: 'right' }}>Edge</th>
              </tr>
            </thead>
            <tbody>
              {report.discovered_patterns.map((dp: any) => (
                <tr key={dp.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 0' }}>
                    <div style={{ fontWeight: 600, color: 'var(--blue)' }}>{dp.underlying}</div>
                    <div style={{ fontSize: 9, color: 'var(--txt3)', marginTop: 1 }}>{dp.features?.join(' + ')}</div>
                  </td>
                  <td style={{ textAlign: 'right', color: 'var(--orange)' }}>{dp.timeframe}</td>
                  <td style={{ textAlign: 'right' }}>
                    <span className={`badge ${dp.direction === 'long' ? 'badge-up' : 'badge-dn'}`} style={{ fontSize: 9 }}>
                      {dp.direction?.toUpperCase()}
                    </span>
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: (dp.win_rate ?? 0) >= 0.55 ? 'var(--up)' : 'var(--dn)' }}>
                    {fmtPct(dp.win_rate ?? 0)}
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--txt2)' }}>{dp.effect_size?.toFixed(3)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {dp.has_edge === true  ? <span style={{ color: 'var(--up)',    fontSize: 10, fontWeight: 700 }}>✓ EDGE</span>
                   : dp.has_edge === false ? <span style={{ color: 'var(--dn)',    fontSize: 10 }}>✗ NO EDGE</span>
                   :                        <span style={{ color: 'var(--txt3)',   fontSize: 10 }}>UNTESTED</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

    </div>
  )
}
