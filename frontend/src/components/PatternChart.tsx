import { useState, useRef, useEffect } from 'react'

interface Bar {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  fired: boolean
}

interface PatternChartProps {
  bars: Bar[]
  occurrences: string[]
  underlying: string
  timeframe: string
  dataSource: string
  nOccurrences: number
  features: string[]
  explanation: string
  direction: string
  winRateStat: number | null
}

const PAD = { l: 58, r: 10, t: 10, b: 22 }
const CHART_H = 260
const VOL_H   = 36
const TOTAL_H = PAD.t + CHART_H + VOL_H + PAD.b

const ZOOM_OPTIONS = [
  { label: '3M',  bars: 65  },
  { label: '6M',  bars: 130 },
  { label: '1Y',  bars: 252 },
  { label: '2Y',  bars: 500 },
  { label: 'All', bars: 9999 },
]

export function PatternChart({
  bars, occurrences, underlying, timeframe,
  dataSource, nOccurrences, features, explanation, direction, winRateStat,
}: PatternChartProps) {
  const containerRef  = useRef<HTMLDivElement>(null)
  const [width, setWidth]   = useState(860)
  const [zoom, setZoom]     = useState(252)
  const [hovered, setHovered] = useState<number | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(e => setWidth(Math.floor(e[0].contentRect.width)))
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  const visibleBars = bars.slice(-Math.min(zoom, bars.length))
  const occSet = new Set(occurrences)

  const innerW = width - PAD.l - PAD.r
  const bw     = Math.max(1, Math.floor(innerW / visibleBars.length) - 1)
  const bx     = (i: number) => PAD.l + i * (bw + 1)
  const bcx    = (i: number) => bx(i) + bw / 2

  // Price scale
  const allLows  = visibleBars.map(b => b.low)
  const allHighs = visibleBars.map(b => b.high)
  const minP = Math.min(...allLows)  * 0.9995
  const maxP = Math.max(...allHighs) * 1.0005
  const pRange = maxP - minP || 1
  const py = (p: number) => PAD.t + CHART_H - ((p - minP) / pRange) * CHART_H

  // Volume scale
  const maxVol = Math.max(...visibleBars.map(b => b.volume || 0), 1)
  const vy = (v: number) => PAD.t + CHART_H + VOL_H - ((v || 0) / maxVol) * VOL_H

  // Y-axis ticks
  const nTicks = 5
  const yTicks = Array.from({ length: nTicks }, (_, i) => minP + (pRange * i / (nTicks - 1)))

  // X-axis: one label every ~7 visible positions
  const xEvery = Math.max(1, Math.round(visibleBars.length / 7))

  const hovBar = hovered != null ? visibleBars[hovered] : null

  const fmtPrice = (p: number) =>
    p >= 10000 ? `${(p / 1000).toFixed(1)}k` : p.toFixed(0)

  return (
    <div style={{ fontSize: 12 }}>
      {/* Top bar: stats + zoom controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--txt2)', fontSize: 11 }}>
            <strong style={{ color: 'var(--txt)' }}>{underlying}</strong>
            <span style={{ marginLeft: 6, color: 'var(--txt3)' }}>{timeframe}</span>
          </span>
          <span style={{ fontSize: 10, color: 'var(--txt3)' }}>
            {nOccurrences} occurrences / {bars.length} bars · {dataSource}
          </span>
          {winRateStat != null && (
            <span style={{ fontSize: 10, color: 'var(--blue-text)' }}>
              stat WR {(winRateStat * 100).toFixed(1)}%
            </span>
          )}
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 3,
            background: direction === 'long' ? 'rgba(38,166,154,0.15)' : 'rgba(239,83,80,0.15)',
            color: direction === 'long' ? 'var(--up)' : 'var(--dn)',
          }}>
            {direction === 'long' ? '▲ BUY CE' : '▼ BUY PE'}
          </span>
        </div>

        {/* Zoom */}
        <div style={{ display: 'flex', gap: 3 }}>
          {ZOOM_OPTIONS.map(o => (
            <button
              key={o.label}
              onClick={() => setZoom(o.bars)}
              style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
                background: zoom === o.bars ? 'rgba(41,98,255,0.15)' : 'transparent',
                color: zoom === o.bars ? 'var(--blue-text)' : 'var(--txt3)',
                border: `1px solid ${zoom === o.bars ? 'rgba(41,98,255,0.4)' : 'var(--border)'}`,
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {/* Features */}
      {features.length > 0 && (
        <div style={{ marginBottom: 8, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {features.map((f, i) => (
            <span key={i} style={{
              fontSize: 10, padding: '1px 7px', borderRadius: 3,
              background: 'rgba(41,98,255,0.08)',
              color: 'var(--blue-text)',
              border: '1px solid rgba(41,98,255,0.2)',
            }}>{f}</span>
          ))}
          {explanation && (
            <span style={{ fontSize: 10, color: 'var(--txt3)', marginLeft: 4, alignSelf: 'center' }}>
              {explanation}
            </span>
          )}
        </div>
      )}

      {/* OHLCV hover info */}
      <div style={{ height: 16, marginBottom: 4, fontSize: 10, color: 'var(--txt2)', fontFamily: 'monospace', display: 'flex', gap: 10 }}>
        {hovBar ? (
          <>
            <span>{hovBar.timestamp}</span>
            <span>O <strong>{hovBar.open.toFixed(0)}</strong></span>
            <span>H <strong>{hovBar.high.toFixed(0)}</strong></span>
            <span>L <strong>{hovBar.low.toFixed(0)}</strong></span>
            <span>C <strong style={{ color: hovBar.close >= hovBar.open ? 'var(--up)' : 'var(--dn)' }}>{hovBar.close.toFixed(0)}</strong></span>
            <span>Vol <strong>{hovBar.volume >= 1e6 ? `${(hovBar.volume / 1e6).toFixed(1)}M` : hovBar.volume >= 1e3 ? `${(hovBar.volume / 1e3).toFixed(0)}K` : hovBar.volume}</strong></span>
            {hovBar.fired && <span style={{ color: 'var(--blue-text)', fontWeight: 700 }}>● Pattern fired</span>}
          </>
        ) : (
          <span style={{ color: 'var(--txt3)' }}>Hover over candles to inspect · Blue highlights = pattern occurrences</span>
        )}
      </div>

      {/* SVG Chart */}
      <div ref={containerRef} style={{ width: '100%' }}>
        <svg
          width={width}
          height={TOTAL_H}
          style={{ display: 'block' }}
          onMouseLeave={() => setHovered(null)}
        >
          {/* Y gridlines */}
          {yTicks.map((p, i) => (
            <line key={i}
              x1={PAD.l} y1={py(p)} x2={width - PAD.r} y2={py(p)}
              stroke="var(--border)" strokeWidth={1} strokeDasharray="3 5" opacity={0.7}
            />
          ))}

          {/* Volume/chart separator */}
          <line
            x1={PAD.l} y1={PAD.t + CHART_H} x2={width - PAD.r} y2={PAD.t + CHART_H}
            stroke="var(--border2)" strokeWidth={1}
          />

          {/* Candles + volume */}
          {visibleBars.map((bar, i) => {
            const x   = bx(i)
            const cx  = bcx(i)
            const isGreen  = bar.close >= bar.open
            const color    = isGreen ? 'var(--up)' : 'var(--dn)'
            const bodyTop  = py(Math.max(bar.open, bar.close))
            const bodyBot  = py(Math.min(bar.open, bar.close))
            const bodyH    = Math.max(1, bodyBot - bodyTop)
            const isOcc    = bar.fired || occSet.has(bar.timestamp)
            const isHov    = hovered === i

            return (
              <g key={i} onMouseEnter={() => setHovered(i)} style={{ cursor: 'crosshair' }}>
                {/* Occurrence column highlight */}
                {isOcc && (
                  <rect x={x} y={PAD.t} width={Math.max(bw, 1) + 1} height={CHART_H}
                        fill="rgba(41,98,255,0.13)" />
                )}
                {/* Hover column */}
                {isHov && (
                  <rect x={x} y={PAD.t} width={Math.max(bw, 1) + 1} height={CHART_H + VOL_H}
                        fill="rgba(255,255,255,0.05)" />
                )}
                {/* High-low wick */}
                <line x1={cx} y1={py(bar.high)} x2={cx} y2={py(bar.low)}
                      stroke={color} strokeWidth={1} />
                {/* Candle body */}
                <rect x={x} y={bodyTop} width={Math.max(1, bw)} height={bodyH}
                      fill={color} opacity={0.92} />
                {/* Occurrence dot above wick */}
                {isOcc && bw >= 3 && (
                  <circle cx={cx} cy={py(bar.high) - 5} r={2.5} fill="var(--blue-text)" />
                )}
                {/* Volume bar */}
                {bar.volume > 0 && (
                  <rect x={x} y={vy(bar.volume)} width={Math.max(1, bw)}
                        height={PAD.t + CHART_H + VOL_H - vy(bar.volume)}
                        fill={color} opacity={0.35} />
                )}
              </g>
            )
          })}

          {/* Hover crosshair */}
          {hovered != null && hovBar && (
            <>
              <line x1={bcx(hovered)} y1={PAD.t} x2={bcx(hovered)} y2={PAD.t + CHART_H}
                    stroke="var(--txt3)" strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
              <line x1={PAD.l} y1={py(hovBar.close)} x2={width - PAD.r} y2={py(hovBar.close)}
                    stroke="var(--txt3)" strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
              {/* Price label on Y axis */}
              <rect x={0} y={py(hovBar.close) - 8} width={PAD.l - 3} height={16}
                    fill="var(--bg3)" rx={2} />
              <text x={PAD.l - 5} y={py(hovBar.close) + 4} textAnchor="end"
                    fontSize={9} fill="var(--txt)" fontWeight={700}>
                {hovBar.close.toFixed(0)}
              </text>
            </>
          )}

          {/* Y-axis labels */}
          {yTicks.map((p, i) => (
            <text key={i} x={PAD.l - 5} y={py(p) + 3} textAnchor="end"
                  fontSize={9} fill="var(--txt3)">
              {fmtPrice(p)}
            </text>
          ))}

          {/* X-axis labels */}
          {visibleBars.map((bar, i) => i % xEvery !== 0 ? null : (
            <text key={bar.timestamp} x={bcx(i)} y={TOTAL_H - 4}
                  textAnchor="middle" fontSize={9} fill="var(--txt3)">
              {bar.timestamp.slice(5)}
            </text>
          ))}

          {/* Y-axis left border */}
          <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + CHART_H + VOL_H}
                stroke="var(--border2)" strokeWidth={1} />
        </svg>
      </div>

      {/* Legend */}
      <div style={{ marginTop: 6, fontSize: 10, color: 'var(--txt3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <span>
          <span style={{ display: 'inline-block', width: 8, height: 8, background: 'rgba(41,98,255,0.3)', marginRight: 4, verticalAlign: 'middle', borderRadius: 1 }} />
          Pattern fired ({nOccurrences}×)
        </span>
        <span>
          <span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--up)', marginRight: 4, verticalAlign: 'middle' }} />
          Bullish bar
        </span>
        <span>
          <span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--dn)', marginRight: 4, verticalAlign: 'middle' }} />
          Bearish bar
        </span>
      </div>
    </div>
  )
}
