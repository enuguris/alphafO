import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis,
  Tooltip, Legend, ReferenceLine,
} from 'recharts'
import { api } from '../api/client'

/**
 * Visualizes the persistent market-watch snapshots (Celery task, every 15 min
 * on trading days): NIFTY + BANKNIFTY intraday lines and the paper book's
 * net unrealized P&L. Day selector covers the 7-day Redis retention.
 */

function lastNDays(n: number): string[] {
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.now() - i * 86400000)
    // IST date
    const ist = new Date(d.getTime() + 5.5 * 3600000)
    const dow = ist.getUTCDay()
    if (dow === 0 || dow === 6) continue // skip weekends
    out.push(ist.toISOString().slice(0, 10))
  }
  return out
}

export default function MarketWatchPanel() {
  const days = useMemo(() => lastNDays(9), [])
  const [day, setDay] = useState(days[0])
  const [open, setOpen] = useState(true)

  const { data, isLoading } = useQuery({
    queryKey: ['market-watch', day],
    queryFn: async () => (await api.get(`/system/market-watch?day=${day}`)).data,
    refetchInterval: day === days[0] ? 60_000 : false,  // live only for today
  })

  const rows = useMemo(() => {
    const snaps = data?.snapshots ?? []
    return snaps.map((s: any) => ({
      t: s.ts_ist,
      nifty: s.nifty ? parseFloat(s.nifty) : null,
      banknifty: s.banknifty ? parseFloat(s.banknifty) : null,
      bookPnl: Object.values(s.open_groups ?? {}).reduce((a: number, v: any) => a + (v ?? 0), 0)
             + (s.closed_today?.net ?? 0),
      closedNet: s.closed_today?.net ?? 0,
      closedGroups: s.closed_today?.groups ?? 0,
      violations: s.integrity_violations,
      real: s.real_ticks,
    }))
  }, [data])

  const anySynthetic = rows.some((r: any) => r.real === false)
  const lastRow = rows[rows.length - 1]

  return (
    <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, marginBottom: 14 }}>
      <div onClick={() => setOpen(o => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', cursor: 'pointer' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)' }}>📈 Market Watch</span>
        <span style={{ fontSize: 10, color: 'var(--txt3)' }}>15-min snapshots · 7-day history</span>
        {lastRow && (
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--txt2)', marginLeft: 6 }}>
            last {lastRow.t}: N {lastRow.nifty?.toLocaleString('en-IN')} · B {lastRow.banknifty?.toLocaleString('en-IN')} ·
            book <b style={{ color: lastRow.bookPnl >= 0 ? 'var(--up)' : 'var(--dn)' }}>
              ₹{Math.round(lastRow.bookPnl).toLocaleString('en-IN')}</b>
          </span>
        )}
        <select value={day} onClick={e => e.stopPropagation()} onChange={e => setDay(e.target.value)}
          style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 7px', borderRadius: 4,
            border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--txt)' }}>
          {days.map(d => <option key={d} value={d}>{d === days[0] ? `${d} (today)` : d}</option>)}
        </select>
        <span style={{ color: 'var(--txt3)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ padding: '4px 10px 12px' }}>
          {isLoading && <div style={{ fontSize: 11, color: 'var(--txt3)', padding: 12 }}>Loading…</div>}
          {!isLoading && rows.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--txt3)', padding: 12 }}>
              No snapshots for {day} — recording started 03 Jul 2026; snapshots only during market hours.
            </div>
          )}
          {rows.length > 0 && (
            <>
              <ResponsiveContainer width="100%" height={190}>
                <ComposedChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <XAxis dataKey="t" tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} axisLine={false} />
                  {/* left axis: book P&L */}
                  <YAxis yAxisId="pnl" tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} axisLine={false}
                    width={44} tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}k`} />
                  {/* right axis: NIFTY */}
                  <YAxis yAxisId="idx" orientation="right" domain={['auto', 'auto']}
                    tick={{ fontSize: 9, fill: 'var(--txt3)' }} tickLine={false} axisLine={false} width={52} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 11 }}
                    formatter={(v: any, name: any) => {
                      if (name === 'Book P&L') return [`₹${Math.round(v).toLocaleString('en-IN')}`, name]
                      return [Number(v).toLocaleString('en-IN'), name]
                    }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine yAxisId="pnl" y={0} stroke="var(--txt3)" strokeDasharray="2 3" />
                  <Area yAxisId="pnl" dataKey="bookPnl" name="Book P&L" type="monotone"
                    stroke="var(--orange)" fill="var(--orange)" fillOpacity={0.12} strokeWidth={1.5} dot={false} />
                  <Line yAxisId="idx" dataKey="nifty" name="NIFTY" type="monotone"
                    stroke="var(--blue)" strokeWidth={1.5} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
              <div style={{ display: 'flex', gap: 14, fontSize: 10, color: 'var(--txt3)', padding: '2px 6px', flexWrap: 'wrap' }}>
                <span>BANKNIFTY {rows[0].banknifty?.toLocaleString('en-IN')} → {lastRow.banknifty?.toLocaleString('en-IN')}</span>
                <span>Closed today: {lastRow.closedGroups} groups, ₹{Math.round(lastRow.closedNet).toLocaleString('en-IN')}</span>
                {lastRow.violations != null && (
                  <span style={{ color: lastRow.violations > 0 ? 'var(--dn)' : 'var(--up)' }}>
                    integrity: {lastRow.violations > 0 ? `${lastRow.violations} VIOLATIONS` : 'clean'}
                  </span>
                )}
                {anySynthetic && <span style={{ color: 'var(--dn)' }}>⚠ some snapshots had synthetic spot (ticker down)</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
