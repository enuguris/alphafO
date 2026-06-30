import { useState, Component } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchPatternPerformance, fetchLiveAlerts, fetchBacktestTrades,
  runPatternBacktest, deleteBacktestRun,
  discoverPatterns, fetchDiscoverProgress, fetchDiscoveredPatterns,
  toggleDiscoveredPattern, deleteDiscoveredPattern, clearAllDiscovered,
  fetchDiscoveredChart,
} from '../api/client'
import { PatternChart } from '../components/PatternChart'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, ReferenceLine,
} from 'recharts'

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmtINR  = (n?: number | null) => n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const fmtPct  = (n?: number | null) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const fmtNum  = (n?: number | null, dp = 2) => n == null ? '—' : n.toFixed(dp)

const PATTERN_LABELS: Record<string, string> = {
  gap_fill: 'Gap Fill', oi_buildup: 'OI Buildup', iv_crush: 'IV Crush',
  max_pain: 'Max Pain', mean_reversion: 'Mean Reversion',
  pcr_divergence: 'PCR Divergence', vwap_oi: 'VWAP + OI',
  expiry_week: 'Expiry Week',
}
const PATTERN_DESC: Record<string, string> = {
  gap_fill:       'Fade opening gaps — 65–75% fill same day',
  oi_buildup:     'Price breakout confirmed by rising OI — new money entering',
  iv_crush:       'Sell options before earnings/events when IV is inflated',
  max_pain:       'Price gravitates to max-pain strike near expiry',
  mean_reversion: 'Bollinger squeeze → breakout after consolidation',
  pcr_divergence: 'PCR extreme → contrarian reversal signal',
  vwap_oi:        'VWAP reclaim with rising OI confirmation',
  expiry_week:    'Theta decay acceleration in final week before expiry',
}
const TF_LABEL: Record<string, string> = { '15m': '15m', '1h': '1h', '4h': '4h', daily: 'Daily' }

// ── Error boundary ────────────────────────────────────────────────────────────
class TabErrorBoundary extends Component<{ children: ReactNode }, { err: string | null }> {
  constructor(props: any) { super(props); this.state = { err: null } }
  static getDerivedStateFromError(e: Error) { return { err: e.message } }
  render() {
    if (this.state.err) return (
      <div style={{ padding: 24, background: 'rgba(239,83,80,0.08)', borderRadius: 8,
        border: '1px solid rgba(239,83,80,0.3)', color: 'var(--dn)', fontSize: 13 }}>
        <strong>Render error:</strong> {this.state.err}
        <button onClick={() => this.setState({ err: null })} className="tv-btn tv-btn-ghost"
          style={{ marginLeft: 12, fontSize: 11 }}>Retry</button>
      </div>
    )
    return this.props.children
  }
}

function EdgeBadge({ edge }: { edge: boolean | null }) {
  if (edge === null) return <span style={{ fontSize: 10, color: 'var(--txt3)' }}>Untested</span>
  if (edge) return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 3,
      background: 'rgba(38,166,154,0.12)', color: 'var(--up)', border: '1px solid rgba(38,166,154,0.35)' }}>
      ✓ EDGE
    </span>
  )
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 3,
      background: 'rgba(239,83,80,0.08)', color: 'var(--dn)', border: '1px solid rgba(239,83,80,0.25)' }}>
      ✗ No edge
    </span>
  )
}

// ── Trade waterfall chart ─────────────────────────────────────────────────────
function TradeWaterfall({ trades }: { trades: any[] }) {
  let cum = 0
  const data = trades.map((t, i) => {
    cum += t.net_pnl
    return { i: i + 1, pnl: t.net_pnl, cum, reason: t.exit_reason }
  })
  return (
    <ResponsiveContainer width="100%" height={160}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
        <XAxis dataKey="i" tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} />
        <YAxis tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} axisLine={false}
          tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
        <Tooltip
          contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', fontSize: 11 }}
          formatter={(v: any) => [`₹${Number(v).toLocaleString('en-IN')}`, 'Cumulative P&L']}
        />
        <ReferenceLine y={0} stroke="var(--border)" strokeWidth={1} />
        <Line type="monotone" dataKey="cum" stroke="var(--blue)" dot={false} strokeWidth={1.5} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── Backtest detail panel ─────────────────────────────────────────────────────
function BacktestDetail({ bt, onClose }: { bt: any; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['backtest-trades', bt.id],
    queryFn: () => fetchBacktestTrades(bt.id),
    enabled: !!bt.id,
  })
  const trades: any[] = data?.trades ?? []
  const winners = trades.filter(t => (t.net_pnl ?? 0) > 0)
  const losers  = trades.filter(t => (t.net_pnl ?? 0) <= 0)

  const exitCounts = trades.reduce((acc, t) => {
    acc[t.exit_reason] = (acc[t.exit_reason] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <div style={{ padding: '16px 20px', background: 'var(--bg)', borderTop: '2px solid var(--blue)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <span style={{ fontWeight: 700, fontSize: 14 }}>
            {bt.underlying} · {PATTERN_LABELS[bt.pattern_name] || bt.pattern_name} · {TF_LABEL[bt.timeframe]}
          </span>
          <span style={{ marginLeft: 10, fontSize: 11, color: 'var(--txt3)' }}>
            {bt.date_from} → {bt.date_to} · {bt.bars_tested} bars · {bt.data_source === 'real' ? '🟢 Real data' : '🟡 Synthetic'}
          </span>
        </div>
        <button onClick={onClose} className="tv-btn tv-btn-ghost" style={{ fontSize: 11, padding: '3px 12px' }}>Close ✕</button>
      </div>

      {isLoading
        ? <div style={{ color: 'var(--txt3)', fontSize: 12 }}>Loading trades…</div>
        : <>
          {/* Equity curve */}
          {trades.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Equity Curve</div>
              <TradeWaterfall trades={trades} />
            </div>
          )}

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
            {[
              ['Trades', bt.trades_taken, undefined],
              ['Win Rate', fmtPct(bt.win_rate), (bt.win_rate || 0) >= 0.52 ? 'var(--up)' : 'var(--dn)'],
              ['Profit Factor', fmtNum(bt.profit_factor), (bt.profit_factor || 0) >= 1.3 ? 'var(--up)' : 'var(--dn)'],
              ['Net P&L', fmtINR(bt.total_net_pnl), (bt.total_net_pnl || 0) >= 0 ? 'var(--up)' : 'var(--dn)'],
              ['Avg Winner', fmtINR(bt.avg_winner), 'var(--up)'],
              ['Avg Loser', fmtINR(bt.avg_loser), 'var(--dn)'],
              ['Max DD', `${(bt.max_drawdown_pct || 0).toFixed(1)}%`, (bt.max_drawdown_pct || 0) > 20 ? 'var(--dn)' : 'var(--txt2)'],
              ['Sharpe', fmtNum(bt.sharpe_ratio), (bt.sharpe_ratio || 0) >= 1 ? 'var(--up)' : 'var(--txt2)'],
              ['Avg Hold', `${(bt.avg_holding_bars || 0).toFixed(0)} bars`, undefined],
            ].map(([label, value, color]) => (
              <div key={String(label)} style={{ padding: '8px 12px', background: 'var(--bg2)', borderRadius: 5, border: '1px solid var(--border)', minWidth: 90 }}>
                <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'monospace', color: String(color || 'var(--txt)') }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Exit reason breakdown */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 14, fontSize: 11 }}>
            {Object.entries(exitCounts).map(([reason, count]) => (
              <span key={reason} style={{ color: reason === 'target' ? 'var(--up)' : reason === 'stop' ? 'var(--dn)' : 'var(--txt3)' }}>
                {reason}: <strong>{count as number}</strong>
              </span>
            ))}
          </div>

          {/* Trade table */}
          {trades.length > 0 && (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)', color: 'var(--txt3)', fontSize: 9, textTransform: 'uppercase' }}>
                    {['Date', 'Dir', 'Type', 'Strike', 'Spot', 'Entry', 'Exit', 'Hold', 'Net P&L', 'Exit Reason', 'IV', 'Conf'].map(h => (
                      <th key={h} style={{ padding: '4px 8px', textAlign: 'left', fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)' }}>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--txt2)', fontSize: 10 }}>{t.signal_date}</td>
                      <td style={{ padding: '4px 8px', color: t.direction === 'long' ? 'var(--up)' : 'var(--dn)', fontWeight: 700 }}>{t.direction === 'long' ? '▲' : '▼'}</td>
                      <td style={{ padding: '4px 8px', color: t.option_type === 'CE' ? 'var(--blue)' : '#e91e63', fontWeight: 700 }}>{t.option_type}</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{t.strike?.toLocaleString('en-IN')}</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--txt2)' }}>{t.spot_at_entry?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>₹{t.entry_price}</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>₹{t.exit_price?.toFixed(2)}</td>
                      <td style={{ padding: '4px 8px', color: 'var(--txt3)' }}>{t.holding_bars}d</td>
                      <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontWeight: 700, color: (t.net_pnl ?? 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>
                        {fmtINR(t.net_pnl)}
                      </td>
                      <td style={{ padding: '4px 8px', color: t.exit_reason === 'target' ? 'var(--up)' : t.exit_reason === 'stop' ? 'var(--dn)' : 'var(--txt3)', fontWeight: 600, fontSize: 10 }}>
                        {t.exit_reason}
                      </td>
                      <td style={{ padding: '4px 8px', color: 'var(--txt3)' }}>{t.iv_at_entry?.toFixed(1)}%</td>
                      <td style={{ padding: '4px 8px', color: 'var(--txt3)' }}>{((t.confidence || 0) * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      }
    </div>
  )
}

// ── Pattern performance card ──────────────────────────────────────────────────
function PatternCard({ bt, onDrill }: { bt: any; onDrill: (bt: any) => void }) {
  const wr = bt.win_rate || 0
  const pf = bt.profit_factor || 0
  return (
    <tr
      onClick={() => onDrill(bt)}
      style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer',
        background: bt.has_edge ? 'rgba(38,166,154,0.03)' : undefined }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.025)'}
      onMouseLeave={e => e.currentTarget.style.background = bt.has_edge ? 'rgba(38,166,154,0.03)' : ''}
    >
      <td style={{ padding: '9px 12px', fontWeight: 700, fontSize: 12 }}>
        {bt.underlying}
        <span style={{ marginLeft: 6, fontSize: 10, color: bt.data_source === 'real' ? 'var(--up)' : 'var(--orange)' }}>
          {bt.data_source === 'real' ? '● real' : '● synthetic'}
        </span>
      </td>
      <td style={{ padding: '9px 12px' }}>
        <div style={{ fontWeight: 600, fontSize: 12 }}>{PATTERN_LABELS[bt.pattern_name] || bt.pattern_name}</div>
        <div style={{ fontSize: 10, color: 'var(--txt3)' }}>{PATTERN_DESC[bt.pattern_name] || ''}</div>
      </td>
      <td style={{ padding: '9px 8px', color: 'var(--txt3)', fontSize: 11 }}>{TF_LABEL[bt.timeframe]}</td>
      <td style={{ padding: '9px 8px', fontFamily: 'monospace', color: 'var(--txt2)', fontSize: 11 }}>{bt.trades_taken}</td>
      <td style={{ padding: '9px 8px', fontFamily: 'monospace', fontWeight: 700,
        color: wr >= 0.60 ? 'var(--up)' : wr >= 0.52 ? '#8bc34a' : 'var(--dn)', fontSize: 13 }}>
        {fmtPct(bt.win_rate)}
      </td>
      <td style={{ padding: '9px 8px', fontFamily: 'monospace', fontWeight: 700,
        color: pf >= 2.0 ? 'var(--up)' : pf >= 1.3 ? '#8bc34a' : 'var(--dn)', fontSize: 13 }}>
        {fmtNum(bt.profit_factor)}
      </td>
      <td style={{ padding: '9px 8px', fontFamily: 'monospace', color: (bt.total_net_pnl || 0) >= 0 ? 'var(--up)' : 'var(--dn)', fontWeight: 700 }}>
        {fmtINR(bt.total_net_pnl)}
      </td>
      <td style={{ padding: '9px 8px', fontFamily: 'monospace', color: 'var(--txt3)', fontSize: 11 }}>
        {fmtNum(bt.sharpe_ratio)}
      </td>
      <td style={{ padding: '9px 8px', color: (bt.max_drawdown_pct || 0) > 25 ? 'var(--dn)' : 'var(--txt3)', fontSize: 11 }}>
        {(bt.max_drawdown_pct || 0).toFixed(1)}%
      </td>
      <td style={{ padding: '9px 12px' }}>
        <EdgeBadge edge={bt.has_edge} />
      </td>
      <td style={{ padding: '9px 8px', fontSize: 10, color: 'var(--txt3)' }}>▶ Drill</td>
    </tr>
  )
}

// ── Live alerts ───────────────────────────────────────────────────────────────
function LiveAlerts() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['live-alerts'],
    queryFn: fetchLiveAlerts,
    refetchInterval: 30_000,
  })
  const alerts: any[] = data?.alerts ?? []

  if (isLoading) return <div style={{ color: 'var(--txt3)', fontSize: 12, padding: 16 }}>Loading alerts…</div>
  if (alerts.length === 0) return (
    <div style={{ padding: 32, textAlign: 'center', color: 'var(--txt3)', fontSize: 13,
      background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)' }}>
      No active signals in the last 6 hours. Run a scan from the Dashboard to generate signals.
    </div>
  )

  const proven = alerts.filter(a => a.has_edge)
  const rest   = alerts.filter(a => !a.has_edge)

  return (
    <div>
      {proven.length > 0 && (
        <div style={{ marginBottom: 12, padding: '7px 12px', background: 'rgba(38,166,154,0.08)', borderRadius: 5, border: '1px solid rgba(38,166,154,0.3)', fontSize: 11 }}>
          <strong style={{ color: 'var(--up)' }}>✓ {proven.length} signal{proven.length > 1 ? 's' : ''} match patterns with proven historical edge</strong>
          {' — '}these are being auto-executed as paper trades.
        </div>
      )}
      {[...proven, ...rest].map(a => (
        <div key={a.signal_id} style={{
          marginBottom: 8, padding: '12px 16px',
          background: 'var(--bg2)', borderRadius: 6,
          border: `1px solid ${a.has_edge ? 'rgba(38,166,154,0.35)' : 'var(--border)'}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontWeight: 700, fontSize: 13 }}>{a.underlying}</span>
              <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--txt2)' }}>{PATTERN_LABELS[a.pattern_name] || a.pattern_name}</span>
              {a.option_type && (
                <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 700,
                  color: a.option_type === 'CE' ? 'var(--blue)' : '#e91e63' }}>
                  {a.option_type} {a.strike?.toLocaleString('en-IN')}
                </span>
              )}
              {a.expiry_display && <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--txt3)' }}>{a.expiry_display}</span>}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12 }}>
                ₹{a.estimated_premium?.toFixed(2)}
              </span>
              <span style={{ fontSize: 10, fontWeight: 700, color: (a.confidence || 0) >= 0.8 ? 'var(--up)' : 'var(--orange)' }}>
                {((a.confidence || 0) * 100).toFixed(0)}% conf
              </span>
              <EdgeBadge edge={a.has_edge} />
            </div>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: 'var(--txt3)', lineHeight: 1.4 }}>{a.explanation}</div>
          {a.backtest && (
            <div style={{ marginTop: 6, display: 'flex', gap: 16, fontSize: 10, color: 'var(--txt3)' }}>
              <span>Historical: <strong style={{ color: (a.backtest.win_rate || 0) >= 0.52 ? 'var(--up)' : 'var(--dn)' }}>{fmtPct(a.backtest.win_rate)}</strong> WR</span>
              <span>PF: <strong style={{ color: (a.backtest.profit_factor || 0) >= 1.3 ? 'var(--up)' : 'var(--dn)' }}>{fmtNum(a.backtest.profit_factor)}</strong></span>
              <span>Net P&L: <strong>{fmtINR(a.backtest.total_net_pnl)}</strong></span>
              <span style={{ color: a.backtest.data_source === 'real' ? 'var(--up)' : 'var(--orange)' }}>
                {a.backtest.data_source === 'real' ? '● Real data' : '● Synthetic'}
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const ALL_INSTRUMENTS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX',
  'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']
const ALL_PATTERNS = Object.keys(PATTERN_LABELS)
const ALL_TFS = ['daily', '1h', '4h', '15m']

export default function PatternFinder() {
  const qc = useQueryClient()
  const [tab, setTab]   = useState<'performance' | 'alerts' | 'discovered'>('alerts')
  const [drillBt, setDrillBt] = useState<any | null>(null)
  const [tradesDpId, setTradesDpId] = useState<number | null>(null)
  const [chartDpId, setChartDpId] = useState<number | null>(null)
  const [selInst, setSelInst] = useState<string[]>(['NIFTY', 'BANKNIFTY'])
  const [selPat,  setSelPat]  = useState<string[]>(ALL_PATTERNS)
  const [selTf,   setSelTf]   = useState<string[]>(['daily', '1h'])
  const [sortBy,  setSortBy]  = useState<'profit_factor' | 'win_rate' | 'total_net_pnl'>('profit_factor')
  const [showOnlyEdge, setShowOnlyEdge] = useState(false)

  const { data: perfData, isLoading: perfLoading } = useQuery({
    queryKey: ['pattern-performance'],
    queryFn: fetchPatternPerformance,
    refetchInterval: 60_000,
    enabled: tab === 'performance',
  })

  const { data: discData, isLoading: discLoading } = useQuery({
    queryKey: ['discovered-patterns'],
    queryFn: () => fetchDiscoveredPatterns({ only_active: false }),
    refetchInterval: 30_000,
    enabled: tab === 'discovered',
  })

  const { data: chartData, isFetching: chartLoading } = useQuery({
    queryKey: ['pattern-chart', chartDpId],
    queryFn: () => fetchDiscoveredChart(chartDpId!),
    enabled: chartDpId != null,
    staleTime: 5 * 60_000,
  })

  const [discInst, setDiscInst] = useState<string[]>(['NIFTY', 'BANKNIFTY'])
  const [discTf,   setDiscTf]   = useState<string[]>(['daily', '1h'])
  const [discovering, setDiscovering] = useState(false)

  // Fetch once on mount to resume in-progress discovery from a previous session.
  // Only poll (every 1.5s) when the user actively clicked Discover in this session.
  const { data: discProgress } = useQuery({
    queryKey: ['discover-progress'],
    queryFn:  fetchDiscoverProgress,
    staleTime: 30_000,
    refetchInterval: discovering ? 1500 : false,
    refetchOnWindowFocus: false,
    refetchOnMount: true,
  })

  // Auto-resume polling if a discovery was already running on the server
  if (!discovering && discProgress?.running) {
    setDiscovering(true)
  }

  // Stop polling once the backend reports done
  if (discovering && discProgress && !discProgress.running && discProgress.pct === 100) {
    setDiscovering(false)
    setTimeout(() => qc.invalidateQueries({ queryKey: ['discovered-patterns'] }), 500)
  }

  const discoverMut = useMutation({
    mutationFn: () => discoverPatterns({ underlyings: discInst, timeframes: discTf }),
    onSuccess: () => { setDiscovering(true); qc.invalidateQueries({ queryKey: ['discover-progress'] }) },
    onError: (e: any) => console.error('Discovery failed:', e?.response?.data ?? e?.message ?? e),
  })

  const toggleMut = useMutation({
    mutationFn: (id: number) => toggleDiscoveredPattern(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovered-patterns'] }),
  })

  const delDiscMut = useMutation({
    mutationFn: (id: number) => deleteDiscoveredPattern(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovered-patterns'] }),
  })

  const clearAllMut = useMutation({
    mutationFn: clearAllDiscovered,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovered-patterns'] })
      qc.invalidateQueries({ queryKey: ['discover-progress'] })
    },
  })

  const runMut = useMutation({
    mutationFn: () => runPatternBacktest({
      underlyings: selInst,
      patterns:    selPat,
      timeframes:  selTf,
    }),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['pattern-performance'] }), 2000)
    },
  })

  const delMut = useMutation({
    mutationFn: (id: number) => deleteBacktestRun(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pattern-performance'] }),
  })

  const rows: any[] = (perfData?.patterns ?? []).filter((b: any) => {
    if (showOnlyEdge && !b.has_edge) return false
    return true
  }).sort((a: any, b: any) => (b[sortBy] || 0) - (a[sortBy] || 0))

  const toggle = (arr: string[], set: (v: string[]) => void, val: string) =>
    set(arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val])

  return (
    <div style={{ padding: '16px 20px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Pattern Finder</h2>
          <div style={{ fontSize: 11, color: 'var(--txt3)', marginTop: 2 }}>
            Walk-forward backtest on 1yr historical data · auto-runs nightly at 16:00 IST ·
            proven patterns auto-execute as paper trades on live signals
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {([
            ['alerts',     `Live Alerts`],
            ['performance',`Performance (${rows.length})`],
            ['discovered', `Auto-Discovered${discData?.with_edge ? ` (${discData.with_edge} edge)` : ''}`],
          ] as [string, string][]).map(([t, label]) => (
            <button key={t} onClick={() => setTab(t as any)}
              className={`tv-btn ${tab === t ? 'tv-btn-primary' : 'tv-btn-ghost'}`}
              style={{ fontSize: 11, padding: '4px 14px' }}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Live Alerts tab ────────────────────────────────────────────────── */}
      {tab === 'alerts' && <LiveAlerts />}

      {/* ── Performance tab ───────────────────────────────────────────────── */}
      {tab === 'performance' && (
        <>
          {/* Run backtest controls */}
          <div style={{ padding: '14px 16px', background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)', marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt2)', marginBottom: 10 }}>Run Backtest</div>

            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Instruments</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {ALL_INSTRUMENTS.map(s => (
                    <button key={s} onClick={() => toggle(selInst, setSelInst, s)}
                      className="tv-btn" style={{ fontSize: 10, padding: '2px 8px',
                        background: selInst.includes(s) ? 'rgba(41,98,255,0.15)' : undefined,
                        color: selInst.includes(s) ? 'var(--blue-text)' : 'var(--txt3)',
                        border: `1px solid ${selInst.includes(s) ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
                      }}>{s}</button>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Timeframes</div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {ALL_TFS.map(tf => (
                    <button key={tf} onClick={() => toggle(selTf, setSelTf, tf)}
                      className="tv-btn" style={{ fontSize: 10, padding: '2px 8px',
                        background: selTf.includes(tf) ? 'rgba(41,98,255,0.15)' : undefined,
                        color: selTf.includes(tf) ? 'var(--blue-text)' : 'var(--txt3)',
                        border: `1px solid ${selTf.includes(tf) ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
                      }}>{TF_LABEL[tf]}</button>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Patterns:</div>
              {ALL_PATTERNS.map(p => (
                <button key={p} onClick={() => toggle(selPat, setSelPat, p)}
                  className="tv-btn" style={{ fontSize: 10, padding: '2px 8px',
                    background: selPat.includes(p) ? 'rgba(41,98,255,0.15)' : undefined,
                    color: selPat.includes(p) ? 'var(--blue-text)' : 'var(--txt3)',
                    border: `1px solid ${selPat.includes(p) ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
                  }}>{PATTERN_LABELS[p]}</button>
              ))}
            </div>

            <button
              onClick={() => runMut.mutate()}
              disabled={runMut.isPending || selInst.length === 0 || selPat.length === 0 || selTf.length === 0}
              className="tv-btn tv-btn-primary"
              style={{ fontSize: 11, padding: '5px 18px' }}
            >
              {runMut.isPending ? 'Running…' : `▶ Run Backtest (${selInst.length}×${selPat.length}×${selTf.length} combos)`}
            </button>
            {runMut.isSuccess && (
              <span style={{ marginLeft: 10, fontSize: 11, color: 'var(--up)' }}>
                ✓ Queued — results appear in the table as they complete
              </span>
            )}
          </div>

          {/* Filter controls */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
            <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input type="checkbox" checked={showOnlyEdge} onChange={e => setShowOnlyEdge(e.target.checked)} />
              Show only proven edge
            </label>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: 'var(--txt3)' }}>Sort:</span>
            {(['profit_factor', 'win_rate', 'total_net_pnl'] as const).map(s => (
              <button key={s} onClick={() => setSortBy(s)} className="tv-btn"
                style={{ fontSize: 10, padding: '2px 8px',
                  background: sortBy === s ? 'rgba(41,98,255,0.12)' : undefined,
                  color: sortBy === s ? 'var(--blue-text)' : 'var(--txt3)',
                }}>
                {s === 'profit_factor' ? 'Profit Factor' : s === 'win_rate' ? 'Win Rate' : 'Net P&L'}
              </button>
            ))}
          </div>

          {perfLoading && <div style={{ color: 'var(--txt3)', fontSize: 13, padding: 20 }}>Loading pattern performance…</div>}

          {!perfLoading && rows.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--txt3)', fontSize: 13,
              background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
              No backtest results yet. Select instruments and patterns above and click Run Backtest.
              <br /><span style={{ fontSize: 11, marginTop: 6, display: 'block' }}>
                Backtests also run automatically every evening at 16:00 IST.
              </span>
            </div>
          )}

          {rows.length > 0 && (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)', fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {['Instrument', 'Pattern', 'TF', 'Trades', 'Win Rate', 'Profit Factor', 'Net P&L (1yr)', 'Sharpe', 'Max DD', 'Edge', ''].map((h, i) => (
                      <th key={i} style={{ padding: '5px 12px', textAlign: 'left', fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((bt: any) => (
                    <PatternCard key={bt.id} bt={bt} onDrill={setDrillBt} />
                  ))}
                </tbody>
              </table>

              {/* Proof badge summary */}
              <div style={{ marginTop: 12, fontSize: 11, color: 'var(--txt3)' }}>
                Edge criteria: Win Rate ≥ 52% AND Profit Factor ≥ 1.3 AND ≥10 trades ·
                <span style={{ color: 'var(--up)', marginLeft: 4 }}>{rows.filter((r: any) => r.has_edge).length} proven</span> /
                <span style={{ color: 'var(--dn)', marginLeft: 4 }}>{rows.filter((r: any) => !r.has_edge).length} no edge</span>
              </div>
            </>
          )}

          {/* Drill-down detail */}
          {drillBt && (
            <div style={{ marginTop: 16, borderRadius: 8, overflow: 'hidden', border: '2px solid var(--blue)' }}>
              <BacktestDetail bt={drillBt} onClose={() => setDrillBt(null)} />
            </div>
          )}
        </>
      )}

      {/* ── Auto-Discovered tab ───────────────────────────────────────── */}
      {tab === 'discovered' && (
        <>
          {/* Run controls */}
          <div style={{ padding: '14px 16px', background: 'var(--bg2)', borderRadius: 6, border: '1px solid var(--border)', marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt2)', marginBottom: 8 }}>
              Auto-Discover Patterns
              <span style={{ fontWeight: 400, color: 'var(--txt3)', marginLeft: 8 }}>
                Statistical miner + decision tree — no predefined hypotheses required
              </span>
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Instruments</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {ALL_INSTRUMENTS.map(s => (
                    <button key={s} onClick={() => {
                      setDiscInst(prev => prev.includes(s) ? prev.filter(v => v !== s) : [...prev, s])
                    }} className="tv-btn" style={{
                      fontSize: 10, padding: '2px 8px',
                      background: discInst.includes(s) ? 'rgba(41,98,255,0.15)' : undefined,
                      color:      discInst.includes(s) ? 'var(--blue-text)' : 'var(--txt3)',
                      border:    `1px solid ${discInst.includes(s) ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
                    }}>{s}</button>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Timeframes</div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {ALL_TFS.map(tf => (
                    <button key={tf} onClick={() => {
                      setDiscTf(prev => prev.includes(tf) ? prev.filter(v => v !== tf) : [...prev, tf])
                    }} className="tv-btn" style={{
                      fontSize: 10, padding: '2px 8px',
                      background: discTf.includes(tf) ? 'rgba(41,98,255,0.15)' : undefined,
                      color:      discTf.includes(tf) ? 'var(--blue-text)' : 'var(--txt3)',
                      border:    `1px solid ${discTf.includes(tf) ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
                    }}>{TF_LABEL[tf]}</button>
                  ))}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  onClick={() => discoverMut.mutate()}
                  disabled={discoverMut.isPending || discovering || discInst.length === 0}
                  className="tv-btn tv-btn-primary"
                  style={{ fontSize: 11, padding: '5px 18px' }}
                >
                  {discoverMut.isPending ? 'Queuing…' : discovering ? 'Running…' : `🔍 Discover Patterns (${discInst.length} instruments)`}
                </button>
                {(discData?.count ?? 0) > 0 && (
                  <button
                    onClick={() => {
                      if (window.confirm(`Delete all ${discData?.count} discovered patterns and their backtests? This cannot be undone.`)) {
                        clearAllMut.mutate()
                      }
                    }}
                    disabled={clearAllMut.isPending || discovering}
                    className="tv-btn"
                    style={{ fontSize: 11, padding: '5px 14px', color: 'var(--dn)', border: '1px solid rgba(239,83,80,0.35)' }}
                  >
                    {clearAllMut.isPending ? 'Clearing…' : '⊘ Clear All'}
                  </button>
                )}
                {discoverMut.isError && (
                  <span style={{ fontSize: 11, color: 'var(--dn)' }}>
                    ✗ {(discoverMut.error as any)?.response?.data?.detail ?? (discoverMut.error as any)?.message ?? 'Unknown error'}
                  </span>
                )}
              </div>

              {/* Progress bar — visible while discovering */}
              {(discovering || (discProgress?.running)) && (
                <div style={{ maxWidth: 520 }}>
                  <div style={{
                    height: 4, borderRadius: 2, background: 'var(--border2)',
                    overflow: 'hidden', marginBottom: 5,
                  }}>
                    <div style={{
                      height: '100%', borderRadius: 2,
                      background: 'linear-gradient(90deg, rgba(41,98,255,0.7), rgba(41,98,255,1))',
                      width: `${discProgress?.pct ?? 2}%`,
                      transition: 'width 0.6s ease',
                      minWidth: 8,
                    }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--txt3)' }}>
                    <span style={{ maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {discProgress?.step || 'Starting…'}
                    </span>
                    <span style={{ flexShrink: 0, marginLeft: 8 }}>
                      {discProgress?.pct ?? 0}%
                      {discProgress?.found ? ` · ${discProgress.found} patterns found` : ''}
                      {discProgress?.with_edge ? ` · ${discProgress.with_edge} with edge` : ''}
                    </span>
                  </div>
                </div>
              )}

              {/* Done state */}
              {!discovering && discProgress?.pct === 100 && !discProgress?.running && (
                <span style={{ fontSize: 11, color: 'var(--up)' }}>
                  ✓ Discovery complete — {discProgress.with_edge ?? 0} patterns with edge (auto-runs nightly at 16:30 IST)
                </span>
              )}
            </div>
            <div style={{ marginTop: 8, fontSize: 10, color: 'var(--txt3)', lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--txt2)' }}>How it works:</strong>{' '}
              <strong>Statistical miner</strong> tests every combination of ~30 market features (RSI, VWAP, BB, volume, IV rank, OI change, etc.)
              and finds which combos produce statistically significant positive returns (p &lt; 0.05, WR ≥ 52%).{' '}
              <strong>Decision tree</strong> trains on your existing paper trade outcomes to learn which conditions at entry predicted winners vs losers.
              Discovered patterns are walk-forward backtested before being allowed to auto-execute.
            </div>
          </div>

          {/* Results */}
          {discLoading && <div style={{ color: 'var(--txt3)', fontSize: 12, padding: 16 }}>Loading discovered patterns…</div>}

          {!discLoading && (discData?.patterns ?? []).length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--txt3)', fontSize: 13,
              background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
              No discovered patterns yet. Click "Discover Patterns" above or wait for the nightly run at 16:30 IST.
            </div>
          )}

          {(discData?.patterns ?? []).length > 0 && (
            <TabErrorBoundary>
              {/* Summary */}
              <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
                {[
                  ['Total found', discData?.count ?? 0, undefined],
                  ['With proven edge', discData?.with_edge ?? 0, 'var(--up)'],
                  ['Statistical', discData?.statistical ?? 0, 'var(--blue-text)'],
                  ['Decision tree', discData?.decision_tree ?? 0, 'var(--orange)'],
                ].map(([label, val, color]) => (
                  <div key={String(label)} style={{ padding: '8px 14px', background: 'var(--bg2)', borderRadius: 5, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: String(color || 'var(--txt)') }}>{val}</div>
                  </div>
                ))}
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)', fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {['Pattern Name', 'Source', 'Conditions', 'Samples', 'Stat WR', 'BT WR', 'BT PF', 'BT P&L', 'Edge', 'Active', ''].map((h, i) => (
                      <th key={i} style={{ padding: '5px 10px', textAlign: 'left', fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(discData.patterns as any[]).map((dp: any) => (<>
                    <tr key={dp.id} style={{
                      borderBottom: (chartDpId === dp.id || tradesDpId === dp.id) ? 'none' : '1px solid var(--border)',
                      opacity: dp.active ? 1 : 0.45,
                      background: chartDpId === dp.id ? 'rgba(41,98,255,0.05)' : tradesDpId === dp.id ? 'rgba(41,98,255,0.05)' : dp.has_edge ? 'rgba(38,166,154,0.03)' : undefined,
                    }}>
                      <td style={{ padding: '8px 10px', minWidth: 200 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: dp.direction === 'long' ? 'var(--up)' : 'var(--dn)', marginBottom: 2 }}>
                          {dp.display_name || dp.underlying}
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                          {TF_LABEL[dp.timeframe] || dp.timeframe} · {dp.explanation?.replace(/^(BUY CE|BUY PE) when: /i, '')}
                        </div>
                      </td>
                      <td style={{ padding: '8px 8px' }}>
                        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3,
                          background: dp.source === 'statistical' ? 'rgba(41,98,255,0.1)' : 'rgba(255,152,0,0.1)',
                          color: dp.source === 'statistical' ? 'var(--blue-text)' : 'var(--orange)',
                          border: `1px solid ${dp.source === 'statistical' ? 'rgba(41,98,255,0.3)' : 'rgba(255,152,0,0.3)'}`,
                          fontWeight: 700,
                        }}>
                          {dp.source === 'statistical' ? 'STAT' : 'DT'}
                        </span>
                      </td>
                      <td style={{ padding: '8px 8px', maxWidth: 260 }}>
                        <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                          {(Array.isArray(dp.features) ? dp.features : String(dp.features || '').split(' ').filter(Boolean)).map((f: string, fi: number) => (
                            <span key={`${f}-${fi}`} style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2,
                              background: 'rgba(41,98,255,0.12)', color: 'var(--blue-text)',
                              border: '1px solid rgba(41,98,255,0.25)' }}>
                              {f}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace', color: 'var(--txt3)', fontSize: 11 }}>{dp.n_samples}</td>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace', fontWeight: 700,
                        color: (dp.win_rate || 0) >= 0.52 ? 'var(--up)' : 'var(--dn)', fontSize: 12 }}>
                        {fmtPct(dp.win_rate)}
                      </td>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace',
                        color: dp.last_backtest_win_rate == null ? 'var(--txt3)'
                          : (dp.last_backtest_win_rate || 0) >= 0.52 ? 'var(--up)' : 'var(--dn)', fontSize: 12 }}>
                        {dp.last_backtest_win_rate != null ? fmtPct(dp.last_backtest_win_rate) : '—'}
                      </td>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace',
                        color: dp.last_backtest_profit_factor == null ? 'var(--txt3)'
                          : (dp.last_backtest_profit_factor || 0) >= 1.3 ? 'var(--up)' : 'var(--dn)', fontSize: 12 }}>
                        {dp.last_backtest_profit_factor != null ? fmtNum(dp.last_backtest_profit_factor) : '—'}
                      </td>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace',
                        color: dp.last_backtest_net_pnl == null ? 'var(--txt3)'
                          : (dp.last_backtest_net_pnl || 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>
                        {dp.last_backtest_net_pnl != null ? fmtINR(dp.last_backtest_net_pnl) : '—'}
                      </td>
                      <td style={{ padding: '8px 8px' }}>
                        <EdgeBadge edge={dp.has_edge ? true : dp.last_backtest_trades == null ? null : false} />
                      </td>
                      <td style={{ padding: '8px 8px' }}>
                        <button
                          onClick={() => toggleMut.mutate(dp.id)}
                          className="tv-btn"
                          style={{ fontSize: 10, padding: '2px 8px',
                            color: dp.active ? 'var(--up)' : 'var(--txt3)',
                            border: `1px solid ${dp.active ? 'rgba(38,166,154,0.4)' : 'var(--border)'}` }}
                        >
                          {dp.active ? 'ON' : 'OFF'}
                        </button>
                      </td>
                      <td style={{ padding: '8px 8px', whiteSpace: 'nowrap' }}>
                        <button
                          onClick={() => setChartDpId(chartDpId === dp.id ? null : dp.id)}
                          className="tv-btn"
                          style={{ fontSize: 10, padding: '2px 8px', marginRight: 4,
                            color: chartDpId === dp.id ? 'var(--up)' : 'var(--txt2)',
                            border: `1px solid ${chartDpId === dp.id ? 'rgba(38,166,154,0.4)' : 'var(--border)'}`,
                          }}
                        >▦ Chart</button>
                        {dp.backtest_id != null && (
                          <button
                            onClick={() => {
                              if (tradesDpId === dp.id) {
                                setTradesDpId(null)
                                setDrillBt(null)
                              } else {
                                setTradesDpId(dp.id)
                                setDrillBt({
                                  id: dp.backtest_id,
                                  underlying: dp.underlying,
                                  pattern_name: dp.pattern_slug,
                                  timeframe: dp.timeframe,
                                  date_from: '—', date_to: '—',
                                  bars_tested: '—',
                                  data_source: 'real',
                                })
                              }
                            }}
                            className="tv-btn"
                            style={{ fontSize: 10, padding: '2px 8px', marginRight: 4,
                              color: tradesDpId === dp.id ? 'var(--up)' : 'var(--blue-text)',
                              border: `1px solid ${tradesDpId === dp.id ? 'rgba(38,166,154,0.4)' : 'transparent'}`,
                            }}
                          >▶ Trades</button>
                        )}
                        <button onClick={() => delDiscMut.mutate(dp.id)} className="tv-btn"
                          style={{ fontSize: 10, padding: '2px 6px', color: 'var(--dn)' }}>✕</button>
                      </td>
                    </tr>
                    {chartDpId === dp.id && (
                      <tr key={`chart-${dp.id}`}>
                        <td colSpan={12} style={{ padding: 0, borderBottom: '2px solid var(--border2)', background: 'var(--bg2)' }}>
                          <div style={{ padding: '14px 16px' }}>
                            {chartLoading ? (
                              <div style={{ textAlign: 'center', padding: 32, color: 'var(--txt3)' }}>
                                <div className="spin" style={{ display: 'inline-block', width: 18, height: 18, border: '2px solid var(--border2)', borderTopColor: 'var(--blue)', borderRadius: '50%', marginBottom: 8 }} />
                                <div style={{ fontSize: 11 }}>Fetching historical data…</div>
                              </div>
                            ) : chartData ? (
                              <PatternChart
                                bars={chartData.bars}
                                occurrences={chartData.occurrences}
                                underlying={chartData.underlying}
                                timeframe={chartData.timeframe}
                                dataSource={chartData.data_source}
                                nOccurrences={chartData.n_occurrences}
                                features={chartData.features}
                                explanation={chartData.explanation}
                                direction={chartData.direction}
                                winRateStat={chartData.win_rate_stat}
                              />
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    )}
                    {tradesDpId === dp.id && drillBt && (
                      <tr key={`trades-${dp.id}`}>
                        <td colSpan={12} style={{ padding: 0, borderBottom: '2px solid var(--border2)', background: 'var(--bg2)' }}>
                          <BacktestDetail bt={drillBt} onClose={() => { setTradesDpId(null); setDrillBt(null) }} />
                        </td>
                      </tr>
                    )}
                  </>))}
                </tbody>
              </table>
              <div style={{ marginTop: 10, fontSize: 10, color: 'var(--txt3)', lineHeight: 1.6 }}>
                <strong>Stat WR</strong> = win rate on historical bars (pure statistics, no option simulation) ·
                <strong> BT WR / PF</strong> = walk-forward option backtest (same engine as manual patterns) ·
                Toggle <strong>OFF</strong> to stop a pattern auto-executing without deleting it.
                Patterns auto-rediscover every weekday at 16:30 IST.
              </div>
            </TabErrorBoundary>
          )}

        </>
      )}
    </div>
  )
}
