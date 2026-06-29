interface Props {
  trend: string        // bullish | bearish | ranging
  volatility: string   // high | normal | low
  adx: number
}

const TREND_COLOR: Record<string, string> = {
  bullish: 'var(--up)',
  bearish: 'var(--dn)',
  ranging: 'var(--orange)',
}
const TREND_ICON: Record<string, string> = {
  bullish: '▲', bearish: '▼', ranging: '↔',
}
const VOL_COLOR: Record<string, string> = {
  high: 'var(--dn)', normal: 'var(--txt2)', low: 'var(--up)',
}

export default function RegimeBadge({ trend, volatility, adx }: Props) {
  const tc = TREND_COLOR[trend] ?? 'var(--txt2)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', borderLeft: '1px solid var(--border)', height: '100%' }}>
      <div>
        <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', lineHeight: 1 }}>Regime</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 1 }}>
          <span style={{ fontSize: 9, color: tc }}>{TREND_ICON[trend]}</span>
          <span style={{ fontSize: 10, fontWeight: 700, color: tc, textTransform: 'capitalize' }}>{trend}</span>
          <span style={{ fontSize: 9, color: VOL_COLOR[volatility], fontWeight: 600 }}>· {volatility} vol</span>
        </div>
      </div>
      <div style={{ fontSize: 9, color: 'var(--txt3)', fontFamily: 'monospace' }}>
        ADX {adx.toFixed(0)}
      </div>
    </div>
  )
}
