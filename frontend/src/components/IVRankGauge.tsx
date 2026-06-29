interface Props {
  ivRank: number        // 0-1
  currentIV: number     // percentage e.g. 18.5
  strategyBias: string  // sell_premium | buy_options | spreads
}

export default function IVRankGauge({ ivRank, currentIV, strategyBias }: Props) {
  const pct = Math.round(ivRank * 100)
  const color = ivRank > 0.7 ? 'var(--dn)' : ivRank < 0.3 ? 'var(--up)' : 'var(--orange)'
  const label = ivRank > 0.7 ? 'HIGH' : ivRank < 0.3 ? 'LOW' : 'NORMAL'
  const biasLabel: Record<string, string> = {
    sell_premium: 'Sell Premium',
    buy_options:  'Buy Options',
    spreads:      'Use Spreads',
  }

  return (
    <div style={{ padding: '8px 12px', minWidth: 180 }}>
      <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
        IV Rank
      </div>
      {/* Bar */}
      <div style={{ position: 'relative', height: 6, background: 'var(--bg3)', borderRadius: 3, marginBottom: 5 }}>
        {/* Zones */}
        <div style={{ position: 'absolute', left: 0, width: '30%', height: '100%', background: 'rgba(38,166,154,0.15)', borderRadius: '3px 0 0 3px' }} />
        <div style={{ position: 'absolute', right: 0, width: '30%', height: '100%', background: 'rgba(239,83,80,0.15)', borderRadius: '0 3px 3px 0' }} />
        {/* Indicator */}
        <div style={{
          position: 'absolute',
          left: `calc(${pct}% - 5px)`,
          top: -2, width: 10, height: 10,
          borderRadius: '50%',
          background: color,
          border: '2px solid var(--bg2)',
          transition: 'left 0.5s ease',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
          <span className="mono" style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{pct}</span>
          <span style={{ fontSize: 10, color: 'var(--txt3)' }}>IVR</span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 9, fontWeight: 700, color, letterSpacing: '0.08em' }}>{label}</div>
          <div style={{ fontSize: 9, color: 'var(--txt3)' }}>IV {currentIV.toFixed(1)}%</div>
        </div>
      </div>
      <div style={{ marginTop: 3, fontSize: 10, color, fontWeight: 600 }}>
        → {biasLabel[strategyBias] ?? strategyBias}
      </div>
    </div>
  )
}
