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
  const [zoom, setZoom]   = useState(1)          // 1 = full range
  const [center, setCenter] = useState<number | null>(null)  // null = centred on spot
  const svgRef = useRef<SVGSVGElement>(null)
  const dragRef = useRef<{ clientX: number; center: number } | null>(null)

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
    const fullLo = xs[0], fullHi = xs[xs.length - 1]
    // Visible price window from zoom + center
    const c = center ?? data.spot
    const half = ((fullHi - fullLo) / 2) / zoom
    let lo = c - half, hi = c + half
    if (lo < fullLo) { lo = fullLo; hi = Math.min(fullHi, fullLo + 2 * half) }
    if (hi > fullHi) { hi = fullHi; lo = Math.max(fullLo, fullHi - 2 * half) }
    // Y-range over visible points only (so zooming reveals vertical detail)
    const visIdx = xs.map((x, i) => i).filter(i => xs[i] >= lo && xs[i] <= hi)
    const idx = visIdx.length ? visIdx : xs.map((_, i) => i)
    const ys = [...idx.map(i => data.expiry_pnl[i]), ...idx.map(i => data.t0_pnl[i]), 0]
    const yMin = Math.min(...ys), yMax = Math.max(...ys)
    const yPad = (yMax - yMin || 1) * 0.08
    const y0 = yMin - yPad, y1 = yMax + yPad
    const px = (x: number) => PAD.l + ((x - lo) / (hi - lo)) * (W - PAD.l - PAD.r)
    const py = (y: number) => PAD.t + (1 - (y - y0) / (y1 - y0)) * (H - PAD.t - PAD.b)
    const path = (yy: number[]) => yy.map((y, i) => `${i ? 'L' : 'M'}${px(xs[i]).toFixed(1)},${py(y).toFixed(1)}`).join('')
    return { px, py, path, y0, y1, lo, hi }
  }, [data, zoom, center])

  // Wheel-to-zoom around the cursor (non-passive so we can preventDefault)
  useEffect(() => {
    const svg = svgRef.current
    if (!svg || !data || !geom) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = svg.getBoundingClientRect()
      const frac = Math.max(0, Math.min(1, (((e.clientX - rect.left) / rect.width) * W - PAD.l) / (W - PAD.l - PAD.r)))
      const cursorPrice = geom.lo + frac * (geom.hi - geom.lo)
      const nz = Math.max(1, Math.min(12, zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
      setZoom(nz)
      setCenter(nz <= 1.001 ? null : cursorPrice)
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [data, geom, zoom])

  if (err) return <div style={{ padding: 12, fontSize: 11, color: 'var(--dn)' }}>{err}</div>
  if (!data || !geom) return <div style={{ padding: 12, fontSize: 11, color: 'var(--txt3)' }}>Loading payoff…</div>

  const { px, py, path, lo, hi } = geom
  const xs = data.spots
  const zeroY = py(0)
  const zoomed = zoom > 1.001

  // Area fill above/below zero for the expiry curve
  const areaPath = `${path(data.expiry_pnl)} L${px(hi)},${zeroY} L${px(lo)},${zeroY} Z`

  const priceAtClientX = (clientX: number) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return null
    const frac = (((clientX - rect.left) / rect.width) * W - PAD.l) / (W - PAD.l - PAD.r)
    return lo + frac * (hi - lo)
  }

  const onMove = (e: React.MouseEvent) => {
    // Drag to pan
    if (dragRef.current) {
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      const dxFrac = ((e.clientX - dragRef.current.clientX) / rect.width) * W / (W - PAD.l - PAD.r)
      const span = hi - lo
      setCenter(dragRef.current.center - dxFrac * span)
      return
    }
    // Hover crosshair — nearest data index to the price under the cursor
    const p = priceAtClientX(e.clientX)
    if (p == null) return
    let best = 0, bd = Infinity
    for (let i = 0; i < xs.length; i++) { const d = Math.abs(xs[i] - p); if (d < bd) { bd = d; best = i } }
    setHoverI(best)
  }

  const onDown = (e: React.MouseEvent) => {
    if (!zoomed) return
    dragRef.current = { clientX: e.clientX, center: center ?? data.spot }
  }
  const onUp = () => { dragRef.current = null }
  const resetZoom = () => { setZoom(1); setCenter(null) }

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

      {/* Zoom controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: 10, color: 'var(--txt3)' }}>
        <button className="tv-btn" style={{ fontSize: 12, padding: '0 7px', lineHeight: 1.6 }}
          onClick={() => { setZoom(z => Math.min(12, z * 1.4)); }} title="Zoom in">＋</button>
        <button className="tv-btn" style={{ fontSize: 12, padding: '0 7px', lineHeight: 1.6 }}
          onClick={() => setZoom(z => Math.max(1, z / 1.4))} title="Zoom out">－</button>
        {zoomed && (
          <button className="tv-btn" style={{ fontSize: 10, padding: '1px 7px' }} onClick={resetZoom} title="Reset zoom">Reset ⤢</button>
        )}
        <span style={{ marginLeft: 4 }}>{zoomed ? `${zoom.toFixed(1)}× · scroll to zoom, drag to pan` : 'scroll to zoom'}</span>
      </div>

      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', maxWidth: 900, display: 'block', cursor: dragRef.current ? 'grabbing' : zoomed ? 'grab' : 'crosshair' }}
        onMouseMove={onMove} onMouseDown={onDown} onMouseUp={onUp}
        onMouseLeave={() => { setHoverI(null); dragRef.current = null }}>

        {/* Zero line */}
        <line x1={PAD.l} x2={W - PAD.r} y1={zeroY} y2={zeroY} stroke="var(--txt3)" strokeWidth={1} strokeDasharray="2,3" opacity={0.6} />

        {/* Profit/loss area (clipped by zero line via two clip rects) */}
        <defs>
          <clipPath id={`clip-up-${groupId}`}><rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={zeroY - PAD.t} /></clipPath>
          <clipPath id={`clip-dn-${groupId}`}><rect x={PAD.l} y={zeroY} width={W - PAD.l - PAD.r} height={H - PAD.b - zeroY} /></clipPath>
          <clipPath id={`clip-plot-${groupId}`}><rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} /></clipPath>
        </defs>
        <path d={areaPath} fill="var(--up)" opacity={0.10} clipPath={`url(#clip-up-${groupId})`} />
        <path d={areaPath} fill="var(--dn)" opacity={0.10} clipPath={`url(#clip-dn-${groupId})`} />

        {/* Curves — clipped to the plot area so they don't spill when zoomed */}
        <g clipPath={`url(#clip-plot-${groupId})`}>
          <path d={path(data.t0_pnl)} fill="none" stroke="var(--blue)" strokeWidth={1.5} strokeDasharray="5,4" opacity={0.85} />
          <path d={path(data.expiry_pnl)} fill="none" stroke="var(--txt)" strokeWidth={2} />
        </g>

        {/* Breakeven markers (only those in the visible window) */}
        {data.breakevens.filter(b => b >= lo && b <= hi).map(b => (
          <g key={b}>
            <line x1={px(b)} x2={px(b)} y1={PAD.t} y2={H - PAD.b} stroke="var(--orange)" strokeWidth={1} strokeDasharray="3,3" opacity={0.7} />
            <text x={px(b)} y={H - PAD.b + 12} textAnchor="middle" fontSize={9} fill="var(--orange)" fontFamily="monospace">
              BE {b.toLocaleString('en-IN')}
            </text>
          </g>
        ))}

        {/* OI walls — resistance (red) / support (green) vertical lines.
            Only NIFTY, in-range, top-2 per side, with collision-avoiding labels. */}
        {(() => {
          if ((data.underlying || '').toUpperCase() !== 'NIFTY' || !oiWalls?.expiries?.length) return null
          const legExp = data.legs?.[0]?.expiry
          const match = (legExp && oiWalls.expiries.find((e: any) => e.expiry === legExp)) || oiWalls.expiries[0]
          if (!match) return null
          const inRange = (s: number) => s >= lo && s <= hi
          // Top-2 biggest walls per side within the visible window. Label shows
          // the STRIKE (bold) with OI in millions underneath.
          const res = (match.resistance || []).filter((w: any) => inRange(w.strike))
            .sort((a: any, b: any) => b.coi - a.coi).slice(0, 2)
            .map((w: any) => ({ price: w.strike, oi: `${(w.coi / 1e6).toFixed(1)}M`, kind: 'R', color: 'rgba(239,83,80,0.95)' }))
          const sup = (match.support || []).filter((w: any) => inRange(w.strike))
            .sort((a: any, b: any) => b.poi - a.poi).slice(0, 2)
            .map((w: any) => ({ price: w.strike, oi: `${(w.poi / 1e6).toFixed(1)}M`, kind: 'S', color: 'rgba(38,166,154,0.95)' }))
          // Sort by x and assign staggered label rows (two text lines each)
          const walls = [...res, ...sup].map(w => ({ ...w, x: px(w.price) })).sort((a, b) => a.x - b.x)
          const rows: number[] = []
          const MINGAP = 42
          return walls.map((w, i) => {
            let row = 0
            while (row < rows.length && w.x - rows[row] < MINGAP) row++
            rows[row] = w.x
            const ly = PAD.t + 8 + row * 22
            return (
              <g key={i}>
                <line x1={w.x} x2={w.x} y1={ly + 6} y2={H - PAD.b}
                  stroke={w.color} strokeWidth={1} strokeDasharray="2,3" />
                <text x={w.x} y={ly} textAnchor="middle" fontSize={9} fontWeight={700} fill={w.color} fontFamily="monospace">
                  {w.kind} {w.price.toLocaleString('en-IN')}
                </text>
                <text x={w.x} y={ly + 9} textAnchor="middle" fontSize={7.5} fill={w.color} fontFamily="monospace" opacity={0.85}>
                  {w.oi}
                </text>
              </g>
            )
          })
        })()}

        {/* Current spot marker (only if visible) */}
        {data.spot >= lo && data.spot <= hi && <>
          <line x1={px(data.spot)} x2={px(data.spot)} y1={PAD.t} y2={H - PAD.b} stroke="var(--up)" strokeWidth={1.2} opacity={0.8} />
          <text x={px(data.spot)} y={PAD.t + 9} textAnchor="middle" fontSize={9} fill="var(--up)" fontFamily="monospace" fontWeight={700}>
            SPOT
          </text>
        </>}

        {/* Strike ticks with price labels (visible ones) */}
        {data.legs.filter(l => l.strike >= lo && l.strike <= hi).map((l, i) => (
          <g key={i}>
            <line x1={px(l.strike)} x2={px(l.strike)} y1={H - PAD.b - 5} y2={H - PAD.b} stroke="var(--txt2)" strokeWidth={1.5} />
            <text x={px(l.strike)} y={H - PAD.b - 7} textAnchor="middle" fontSize={7.5} fill="var(--txt3)" fontFamily="monospace">
              {l.strike.toLocaleString('en-IN')}{l.option_type}
            </text>
          </g>
        ))}

        {/* Y axis labels */}
        {[geom.y0, geom.y0 / 2, 0, geom.y1 / 2, geom.y1].filter((v, i, a) => a.indexOf(v) === i).map(v => (
          <text key={v} x={PAD.l - 6} y={py(v) + 3} textAnchor="end" fontSize={9} fill="var(--txt3)" fontFamily="monospace">
            {fmtK(v)}
          </text>
        ))}
        {/* X axis labels — span the visible window */}
        {[0, 0.25, 0.5, 0.75, 1].map(f => {
          const x = lo + f * (hi - lo)
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
