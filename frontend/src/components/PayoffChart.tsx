import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, fetchOIWalls } from '../api/client'

/**
 * Interactive payoff diagram for a composite trade group.
 * Fetches GET /trades/payoff/{groupId} — expiry curve + T+0 (BS) curve,
 * breakevens, max P/L, net Greeks. Pure SVG, theme-aware via CSS vars.
 */

interface PayoffData {
  underlying: string; spot: number; iv_used: number; horizon_days: number
  legs: { role: string; action: string; option_type: string; strike: number
          entry_price: number; quantity: number; expiry: string; dte: number }[]
  spots: number[]; expiry_pnl: number[]; t0_pnl: number[]
  breakevens: number[]; max_profit: number; max_loss: number
  net_greeks: { delta: number; gamma: number; theta: number; vega: number }
  charges_entry_total: number; current_pnl: number; note: string
}

const W = 720, H = 260, PAD = { l: 58, r: 14, t: 14, b: 30 }

export default function PayoffChart({ groupId }: { groupId: string }) {
  const [data, setData]   = useState<PayoffData | null>(null)
  const [err, setErr]     = useState<string | null>(null)
  const [hoverI, setHoverI] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // OI walls (NIFTY) — refetched every 60s so the overlay tracks new snapshots
  const { data: oiWalls } = useQuery({
    queryKey: ['oiwalls'], queryFn: fetchOIWalls, refetchInterval: 60000,
  })

  useEffect(() => {
    let live = true
    api.get(`/trades/payoff/${groupId}`)
      .then(r => { if (live) setData(r.data) })
      .catch(e => { if (live) setErr(e?.response?.data?.detail ?? 'Failed to load payoff') })
    return () => { live = false }
  }, [groupId])

  const geom = useMemo(() => {
    if (!data) return null
    const xs = data.spots
    const all = [...data.expiry_pnl, ...data.t0_pnl, 0]
    const yMin = Math.min(...all), yMax = Math.max(...all)
    const yPad = (yMax - yMin || 1) * 0.08
    const y0 = yMin - yPad, y1 = yMax + yPad
    const px = (x: number) => PAD.l + ((x - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - PAD.l - PAD.r)
    const py = (y: number) => PAD.t + (1 - (y - y0) / (y1 - y0)) * (H - PAD.t - PAD.b)
    const path = (ys: number[]) => ys.map((y, i) => `${i ? 'L' : 'M'}${px(xs[i]).toFixed(1)},${py(y).toFixed(1)}`).join('')
    return { px, py, path, y0, y1 }
  }, [data])

  if (err) return <div style={{ padding: 12, fontSize: 11, color: 'var(--dn)' }}>{err}</div>
  if (!data || !geom) return <div style={{ padding: 12, fontSize: 11, color: 'var(--txt3)' }}>Loading payoff…</div>

  const { px, py, path } = geom
  const xs = data.spots
  const zeroY = py(0)

  // Area fill above/below zero for the expiry curve
  const areaPath = `${path(data.expiry_pnl)} L${px(xs[xs.length - 1])},${zeroY} L${px(xs[0])},${zeroY} Z`

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const fx = ((e.clientX - rect.left) / rect.width) * W
    const frac = (fx - PAD.l) / (W - PAD.l - PAD.r)
    const i = Math.round(frac * (xs.length - 1))
    setHoverI(i >= 0 && i < xs.length ? i : null)
  }

  const hover = hoverI != null ? {
    x: xs[hoverI], exp: data.expiry_pnl[hoverI], t0: data.t0_pnl[hoverI],
  } : null

  const fmtK = (v: number) => Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)

  return (
    <div style={{ padding: '10px 4px' }}>
      {/* Stats strip */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 8, fontSize: 10, color: 'var(--txt3)' }}>
        <span>Spot <strong style={{ color: 'var(--txt)', fontFamily: 'monospace' }}>₹{data.spot.toLocaleString('en-IN')}</strong></span>
        <span>Max Profit <strong style={{ color: 'var(--up)', fontFamily: 'monospace' }}>₹{fmtK(data.max_profit)}</strong></span>
        <span>Max Loss <strong style={{ color: 'var(--dn)', fontFamily: 'monospace' }}>₹{fmtK(data.max_loss)}</strong></span>
        <span>Breakeven{data.breakevens.length > 1 ? 's' : ''} <strong style={{ color: 'var(--orange)', fontFamily: 'monospace' }}>
          {data.breakevens.map(b => `₹${b.toLocaleString('en-IN')}`).join(' / ') || '—'}</strong></span>
        <span>Δ <strong style={{ fontFamily: 'monospace', color: 'var(--txt2)' }}>{data.net_greeks.delta.toFixed(2)}</strong></span>
        <span>Θ/day <strong style={{ fontFamily: 'monospace', color: data.net_greeks.theta >= 0 ? 'var(--up)' : 'var(--dn)' }}>₹{data.net_greeks.theta.toFixed(1)}</strong></span>
        <span>Vega <strong style={{ fontFamily: 'monospace', color: 'var(--txt2)' }}>{data.net_greeks.vega.toFixed(1)}</strong></span>
        <span>IV used <strong style={{ fontFamily: 'monospace', color: 'var(--txt2)' }}>{data.iv_used}%</strong></span>
        <span>Horizon <strong style={{ fontFamily: 'monospace', color: 'var(--txt2)' }}>{data.horizon_days}d</strong></span>
      </div>

      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: 900, display: 'block', cursor: 'crosshair' }}
        onMouseMove={onMove} onMouseLeave={() => setHoverI(null)}>

        {/* Zero line */}
        <line x1={PAD.l} x2={W - PAD.r} y1={zeroY} y2={zeroY} stroke="var(--txt3)" strokeWidth={1} strokeDasharray="2,3" opacity={0.6} />

        {/* Profit/loss area (clipped by zero line via two clip rects) */}
        <defs>
          <clipPath id={`clip-up-${groupId}`}><rect x={0} y={0} width={W} height={zeroY} /></clipPath>
          <clipPath id={`clip-dn-${groupId}`}><rect x={0} y={zeroY} width={W} height={H - zeroY} /></clipPath>
        </defs>
        <path d={areaPath} fill="var(--up)" opacity={0.10} clipPath={`url(#clip-up-${groupId})`} />
        <path d={areaPath} fill="var(--dn)" opacity={0.10} clipPath={`url(#clip-dn-${groupId})`} />

        {/* T+0 curve (dashed) */}
        <path d={path(data.t0_pnl)} fill="none" stroke="var(--blue)" strokeWidth={1.5} strokeDasharray="5,4" opacity={0.85} />
        {/* Expiry curve */}
        <path d={path(data.expiry_pnl)} fill="none" stroke="var(--txt)" strokeWidth={2} />

        {/* Breakeven markers */}
        {data.breakevens.map(b => (
          <g key={b}>
            <line x1={px(b)} x2={px(b)} y1={PAD.t} y2={H - PAD.b} stroke="var(--orange)" strokeWidth={1} strokeDasharray="3,3" opacity={0.7} />
            <text x={px(b)} y={H - PAD.b + 12} textAnchor="middle" fontSize={9} fill="var(--orange)" fontFamily="monospace">
              BE {b.toLocaleString('en-IN')}
            </text>
          </g>
        ))}

        {/* OI walls — resistance (red) / support (green) vertical lines.
            Only for NIFTY, only walls within the visible price range. */}
        {(() => {
          if ((data.underlying || '').toUpperCase() !== 'NIFTY' || !oiWalls?.expiries?.length) return null
          const legExp = data.legs?.[0]?.expiry
          const match = (legExp && oiWalls.expiries.find((e: any) => e.expiry === legExp)) || oiWalls.expiries[0]
          if (!match) return null
          const lo = xs[0], hi = xs[xs.length - 1]
          const inRange = (s: number) => s >= lo && s <= hi
          const lines: any[] = []
          for (const w of match.resistance || []) {
            if (!inRange(w.strike)) continue
            lines.push(
              <g key={'r' + w.strike}>
                <line x1={px(w.strike)} x2={px(w.strike)} y1={PAD.t + 14} y2={H - PAD.b}
                  stroke="rgba(239,83,80,0.85)" strokeWidth={1} strokeDasharray="2,3" />
                <text x={px(w.strike)} y={PAD.t + 20} textAnchor="middle" fontSize={8}
                  fill="rgba(239,83,80,0.95)" fontFamily="monospace">R{(w.coi / 1e6).toFixed(1)}M</text>
              </g>
            )
          }
          for (const w of match.support || []) {
            if (!inRange(w.strike)) continue
            lines.push(
              <g key={'s' + w.strike}>
                <line x1={px(w.strike)} x2={px(w.strike)} y1={PAD.t + 14} y2={H - PAD.b}
                  stroke="rgba(38,166,154,0.85)" strokeWidth={1} strokeDasharray="2,3" />
                <text x={px(w.strike)} y={PAD.t + 20} textAnchor="middle" fontSize={8}
                  fill="rgba(38,166,154,0.95)" fontFamily="monospace">S{(w.poi / 1e6).toFixed(1)}M</text>
              </g>
            )
          }
          return lines
        })()}

        {/* Current spot marker */}
        <line x1={px(data.spot)} x2={px(data.spot)} y1={PAD.t} y2={H - PAD.b} stroke="var(--up)" strokeWidth={1.2} opacity={0.8} />
        <text x={px(data.spot)} y={PAD.t + 9} textAnchor="middle" fontSize={9} fill="var(--up)" fontFamily="monospace" fontWeight={700}>
          SPOT
        </text>

        {/* Strike ticks */}
        {data.legs.map((l, i) => (
          <g key={i}>
            <line x1={px(l.strike)} x2={px(l.strike)} y1={H - PAD.b - 5} y2={H - PAD.b} stroke="var(--txt3)" strokeWidth={1.5} />
          </g>
        ))}

        {/* Y axis labels */}
        {[geom.y0, geom.y0 / 2, 0, geom.y1 / 2, geom.y1].filter((v, i, a) => a.indexOf(v) === i).map(v => (
          <text key={v} x={PAD.l - 6} y={py(v) + 3} textAnchor="end" fontSize={9} fill="var(--txt3)" fontFamily="monospace">
            {fmtK(v)}
          </text>
        ))}
        {/* X axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map(f => {
          const x = xs[Math.round(f * (xs.length - 1))]
          return <text key={f} x={px(x)} y={H - 4} textAnchor="middle" fontSize={9} fill="var(--txt3)" fontFamily="monospace">
            {Math.round(x).toLocaleString('en-IN')}
          </text>
        })}

        {/* Hover crosshair + tooltip */}
        {hover && (
          <g>
            <line x1={px(hover.x)} x2={px(hover.x)} y1={PAD.t} y2={H - PAD.b} stroke="var(--txt2)" strokeWidth={0.8} opacity={0.5} />
            <circle cx={px(hover.x)} cy={py(hover.exp)} r={3.5} fill="var(--txt)" />
            <circle cx={px(hover.x)} cy={py(hover.t0)} r={3} fill="var(--blue)" />
            <g transform={`translate(${px(hover.x) > W - 190 ? px(hover.x) - 178 : px(hover.x) + 10},${PAD.t + 6})`}>
              <rect width={168} height={52} rx={5} fill="var(--bg)" stroke="var(--border)" />
              <text x={9} y={15} fontSize={10} fill="var(--txt3)" fontFamily="monospace">
                Spot {Math.round(hover.x).toLocaleString('en-IN')}
              </text>
              <text x={9} y={29} fontSize={10} fontFamily="monospace" fill={hover.exp >= 0 ? 'var(--up)' : 'var(--dn)'}>
                At expiry: ₹{hover.exp.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </text>
              <text x={9} y={43} fontSize={10} fontFamily="monospace" fill={hover.t0 >= 0 ? 'var(--up)' : 'var(--dn)'}>
                Today (T+0): ₹{hover.t0.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </text>
            </g>
          </g>
        )}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 9, color: 'var(--txt3)', flexWrap: 'wrap' }}>
        <span><span style={{ display: 'inline-block', width: 16, borderTop: '2px solid var(--txt)', verticalAlign: 'middle', marginRight: 4 }} />At expiry ({data.horizon_days}d)</span>
        <span><span style={{ display: 'inline-block', width: 16, borderTop: '2px dashed var(--blue)', verticalAlign: 'middle', marginRight: 4 }} />Today (T+0, BS)</span>
        <span style={{ color: 'var(--orange)' }}>┊ Breakeven</span>
        <span style={{ color: 'var(--up)' }}>│ Current spot</span>
        <span>▎ Strikes</span>
        {(data.underlying || '').toUpperCase() === 'NIFTY' && oiWalls?.expiries?.length && (
          <span><span style={{ color: 'rgba(239,83,80,0.95)' }}>┊R</span> / <span style={{ color: 'rgba(38,166,154,0.95)' }}>┊S</span> OI walls</span>
        )}
        <span style={{ marginLeft: 'auto', fontStyle: 'italic' }}>{data.note}</span>
      </div>
    </div>
  )
}
