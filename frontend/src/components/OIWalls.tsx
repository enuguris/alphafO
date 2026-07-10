import { useQuery } from '@tanstack/react-query'
import { fetchOIWalls } from '../api/client'

/**
 * NIFTY OI-wall panel — real support/resistance from option OI concentration,
 * across the next 6 expiries. Data captured twice daily (am 09:20 / pm 15:25 IST)
 * by the snapshot_oi_walls task; this view refreshes every 60s to pick up the
 * latest snapshot. Resistance = strikes with highest call OI; support = highest
 * put OI. Δ arrows show walls building (writers defending) or unwinding.
 */

const M = (n: number) => (n / 1e6).toFixed(2) + 'M'

function WallRow({ strike, oi, maxOi, side, delta, spot }: {
  strike: number; oi: number; maxOi: number; side: 'R' | 'S'; delta?: number; spot: number
}) {
  const pct = maxOi > 0 ? (oi / maxOi) * 100 : 0
  const color = side === 'R' ? 'var(--dn)' : 'var(--up)'
  const dist = (((strike - spot) / spot) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, padding: '2px 0' }}>
      <div className="mono" style={{ width: 52, fontWeight: 700, color, textAlign: 'right' }}>
        {strike.toLocaleString('en-IN')}
      </div>
      <div style={{ flex: 1, background: 'var(--bg3)', borderRadius: 3, height: 14, position: 'relative', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, opacity: 0.35 }} />
        <div className="mono" style={{ position: 'absolute', left: 6, top: 0, lineHeight: '14px', fontSize: 10, color: 'var(--txt)' }}>
          {M(oi)}
        </div>
      </div>
      <div className="mono" style={{ width: 46, fontSize: 9, color: 'var(--txt3)', textAlign: 'right' }}>
        {dist >= 0 ? '+' : ''}{dist.toFixed(1)}%
      </div>
      <div className="mono" style={{ width: 40, fontSize: 10, textAlign: 'right', color: delta && Math.abs(delta) > 0.3 ? (delta > 0 ? color : 'var(--txt3)') : 'transparent' }}>
        {delta != null && Math.abs(delta) > 0.05 ? `${delta > 0 ? '▲' : '▼'}${Math.abs(delta).toFixed(1)}` : ''}
      </div>
    </div>
  )
}

function ExpiryCard({ exp, spot }: { exp: any; spot: number }) {
  const moves: Record<number, { c: number; p: number }> = {}
  for (const m of exp.wall_moves_vs_prev ?? []) moves[m.strike] = { c: m.d_call_oi_m, p: m.d_put_oi_m }
  const maxR = Math.max(...(exp.resistance ?? []).map((w: any) => w.coi), 1)
  const maxS = Math.max(...(exp.support ?? []).map((w: any) => w.poi), 1)
  const d = new Date(exp.expiry)
  const label = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' })

  return (
    <div className="tv-card" style={{ padding: 12, minWidth: 300, flex: '1 1 300px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--txt)' }}>{label}</div>
        <div className="mono" style={{ fontSize: 9, color: 'var(--txt3)' }}>{exp.expiry}</div>
      </div>
      <div style={{ fontSize: 9, color: 'var(--dn)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Resistance (Call OI)</div>
      {(exp.resistance ?? []).map((w: any) => (
        <WallRow key={'r' + w.strike} strike={w.strike} oi={w.coi} maxOi={maxR} side="R" delta={moves[w.strike]?.c} spot={spot} />
      ))}
      <div style={{ borderTop: '1px dashed var(--border)', margin: '6px 0', textAlign: 'center', fontSize: 9, color: 'var(--blue)' }}>
        spot {spot?.toLocaleString('en-IN')}
      </div>
      <div style={{ fontSize: 9, color: 'var(--up)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Support (Put OI)</div>
      {(exp.support ?? []).map((w: any) => (
        <WallRow key={'s' + w.strike} strike={w.strike} oi={w.poi} maxOi={maxS} side="S" delta={moves[w.strike]?.p} spot={spot} />
      ))}
    </div>
  )
}

export default function OIWalls() {
  const { data, isLoading } = useQuery({ queryKey: ['oiwalls'], queryFn: fetchOIWalls, refetchInterval: 60000 })

  if (isLoading) return <div style={{ padding: 16 }}><div className="skeleton" style={{ height: 200 }} /></div>
  if (!data || data.status === 'no_snapshot_yet' || !data.expiries?.length) {
    return (
      <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>
        No OI-wall snapshot yet. Captured automatically at 09:20 &amp; 15:25 IST on trading days.
      </div>
    )
  }

  return (
    <div style={{ padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontSize: 12, color: 'var(--txt2)' }}>
          <b style={{ color: 'var(--txt)' }}>NIFTY OI Walls</b> — real support/resistance from OI concentration, next {data.expiries.length} expiries
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--txt3)' }}>
          {data.slot?.toUpperCase()} snapshot · {data.day} {data.ts_ist} · spot {data.spot?.toLocaleString('en-IN')}
          {data.prev_slot && <span> · Δ vs {data.prev_slot}</span>}
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {data.expiries.map((exp: any) => (
          <ExpiryCard key={exp.expiry} exp={exp} spot={data.spot} />
        ))}
      </div>
      <div className="tv-card" style={{ padding: 12, marginTop: 10, fontSize: 10, color: 'var(--txt2)', lineHeight: 1.7 }}>
        <b style={{ color: 'var(--txt)' }}>How to read:</b> Bars = OI size at each strike. <span style={{ color: 'var(--dn)' }}>Red = resistance</span> (call writers defend above),
        <span style={{ color: 'var(--up)' }}> green = support</span> (put writers defend below). Δ arrows show change vs the previous snapshot in millions —
        <b> ▲ growing wall</b> = writers adding, level strengthening; <b> ▼ unwinding</b> = writers covering, level may break. The strikes with the biggest
        OI are where price tends to gravitate / stall into expiry.
      </div>
    </div>
  )
}
