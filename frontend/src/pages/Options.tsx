import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchChain, fetchMaxPain, fetchIVRank, fetchRegime, fetchEvents } from '../api/client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts'
import IVRankGauge from '../components/IVRankGauge'
import OIWalls from '../components/OIWalls'

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']

const fmtINR = (n?: number | null) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

function PainBar({ data, maxPain }: { data: any[]; maxPain: number }) {
  if (!data?.length) return null
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <XAxis dataKey="strike" tick={{ fontSize: 9, fill: 'var(--txt2)' }} interval={2} />
        <YAxis hide />
        <ReferenceLine x={maxPain} stroke="var(--blue)" strokeWidth={2} strokeDasharray="4 2" label={{ value: `Max Pain ${maxPain}`, fill: 'var(--blue)', fontSize: 10, position: 'top' }} />
        <Tooltip
          contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11 }}
          formatter={(v: number, name: string) => [fmtINR(v), name === 'ce_loss' ? 'CE Loss' : 'PE Loss']}
        />
        <Bar dataKey="ce_loss" stackId="a" fill="rgba(239,83,80,0.6)" radius={[0, 0, 0, 0]} />
        <Bar dataKey="pe_loss" stackId="a" fill="rgba(38,166,154,0.6)" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function Options() {
  const [sym, setSym] = useState('NIFTY')
  const [tab, setTab] = useState('Chain')

  const { data: chain,   isLoading: chainLoading }   = useQuery({ queryKey: ['chain', sym],   queryFn: () => fetchChain(sym),   refetchInterval: 30000 })
  const { data: maxPain, isLoading: mpLoading }       = useQuery({ queryKey: ['maxpain', sym], queryFn: () => fetchMaxPain(sym), refetchInterval: 30000 })
  const { data: ivData }                              = useQuery({ queryKey: ['ivrank', sym],  queryFn: () => fetchIVRank(sym),  refetchInterval: 60000 })
  const { data: regime }                              = useQuery({ queryKey: ['regime', sym],  queryFn: () => fetchRegime(sym),  refetchInterval: 60000 })
  const { data: events }                              = useQuery({ queryKey: ['events'],       queryFn: fetchEvents })

  const chainRows: any[] = chain?.chain ?? []
  const painData: any[]  = maxPain?.pain_data ?? []
  const atm = chainRows.find(r => r.is_atm) ?? chainRows[Math.floor(chainRows.length / 2)]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Header bar ─────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--border)', background: 'var(--bg2)', flexShrink: 0 }}>
        {/* Symbol picker */}
        <div style={{ display: 'flex', gap: 1, padding: 6, borderRight: '1px solid var(--border)', alignItems: 'center' }}>
          {UNDERLYINGS.map(u => (
            <button
              key={u}
              onClick={() => setSym(u)}
              className="tv-btn"
              style={{
                padding: '3px 10px', fontSize: 11,
                background: sym === u ? 'rgba(41,98,255,0.15)' : 'transparent',
                color: sym === u ? 'var(--blue)' : 'var(--txt2)',
                border: `1px solid ${sym === u ? 'rgba(41,98,255,0.35)' : 'transparent'}`,
              }}
            >
              {u}
            </button>
          ))}
        </div>

        {/* IV Rank */}
        {ivData && (
          <div style={{ borderRight: '1px solid var(--border)' }}>
            <IVRankGauge
              ivRank={ivData.iv_rank ?? 0.5}
              currentIV={ivData.current_iv ?? 18}
              strategyBias={ivData.strategy_bias ?? 'spreads'}
            />
          </div>
        )}

        {/* Regime */}
        {regime && (
          <div style={{ padding: '8px 14px', borderRight: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Market Regime</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className={`badge ${regime.trend === 'bullish' ? 'badge-up' : regime.trend === 'bearish' ? 'badge-dn' : 'badge-warn'}`}>
                {regime.trend?.toUpperCase()}
              </span>
              <span className={`badge ${regime.volatility === 'high' ? 'badge-dn' : regime.volatility === 'low' ? 'badge-up' : 'badge-mute'}`}>
                {regime.volatility?.toUpperCase()} VOL
              </span>
              <span className="mono" style={{ fontSize: 10, color: 'var(--txt3)' }}>ADX {(regime.adx ?? 0).toFixed(0)}</span>
            </div>
            {regime.suitable_patterns?.length > 0 && (
              <div style={{ marginTop: 4, fontSize: 9, color: 'var(--txt3)' }}>
                Best: {regime.suitable_patterns.slice(0, 3).join(', ').replace(/_/g, ' ')}
              </div>
            )}
          </div>
        )}

        {/* Max Pain */}
        {maxPain && (
          <div style={{ padding: '8px 14px', borderRight: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Max Pain</div>
            <div className="mono" style={{ fontSize: 16, fontWeight: 800, color: 'var(--blue)' }}>{maxPain.max_pain_strike?.toLocaleString('en-IN')}</div>
            <div style={{ fontSize: 9, color: 'var(--txt3)' }}>
              PCR {(maxPain.pcr ?? 0).toFixed(2)} · OI {((maxPain.total_oi ?? 0) / 1e6).toFixed(1)}M
            </div>
          </div>
        )}

        {/* PCR */}
        {maxPain?.pcr != null && (
          <div style={{ padding: '8px 14px', borderRight: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>PCR</div>
            <div className="mono" style={{
              fontSize: 16, fontWeight: 800,
              color: maxPain.pcr > 1.3 ? 'var(--up)' : maxPain.pcr < 0.7 ? 'var(--dn)' : 'var(--txt)',
            }}>
              {maxPain.pcr.toFixed(2)}
            </div>
            <div style={{ fontSize: 9, color: maxPain.pcr > 1.3 ? 'var(--up)' : maxPain.pcr < 0.7 ? 'var(--dn)' : 'var(--txt3)' }}>
              {maxPain.pcr > 1.3 ? 'Bullish bias' : maxPain.pcr < 0.7 ? 'Bearish bias' : 'Neutral'}
            </div>
          </div>
        )}

        <div style={{ flex: 1 }} />

        {/* Events */}
        {events?.events?.length > 0 && (
          <div style={{ padding: '8px 14px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Upcoming Events</div>
            {events.events.slice(0, 2).map((e: any) => (
              <div key={e.name} style={{ fontSize: 10, color: 'var(--orange)', display: 'flex', gap: 6 }}>
                <span>⚠</span>
                <span>{e.name} — {e.date}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Tabs ───────────────────────────────────── */}
      <div className="tab-bar">
        {['Chain', 'Max Pain', 'OI Walls', 'IV Analysis', 'Greeks'].map(t => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {/* ── Content ────────────────────────────────── */}
      <div className="scroll-y" style={{ flex: 1, background: 'var(--bg)' }}>

        {/* ── Options Chain ── */}
        {tab === 'Chain' && (
          <div>
            {chainLoading && <div style={{ padding: 16, display: 'flex', gap: 8, flexDirection: 'column' }}>
              {[1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 34 }} />)}
            </div>}
            {!chainLoading && chainRows.length === 0 && (
              <div style={{ textAlign: 'center', padding: 48, color: 'var(--txt2)' }}>No chain data available.</div>
            )}
            {chainRows.length > 0 && (
              <table className="tv-table" style={{ tableLayout: 'fixed' }}>
                <thead>
                  <tr>
                    {/* CE side */}
                    <th style={{ textAlign: 'right', color: 'var(--dn)', width: '8%' }}>OI</th>
                    <th style={{ textAlign: 'right', color: 'var(--dn)', width: '7%' }}>Chg OI</th>
                    <th style={{ textAlign: 'right', color: 'var(--dn)', width: '7%' }}>IV%</th>
                    <th style={{ textAlign: 'right', color: 'var(--dn)', width: '7%' }}>Delta</th>
                    <th style={{ textAlign: 'right', color: 'var(--dn)', width: '8%' }}>LTP</th>
                    {/* Strike */}
                    <th style={{ textAlign: 'center', width: '10%', background: 'var(--bg3)', color: 'var(--txt)' }}>STRIKE</th>
                    {/* PE side */}
                    <th style={{ textAlign: 'left', color: 'var(--up)', width: '8%' }}>LTP</th>
                    <th style={{ textAlign: 'left', color: 'var(--up)', width: '7%' }}>Delta</th>
                    <th style={{ textAlign: 'left', color: 'var(--up)', width: '7%' }}>IV%</th>
                    <th style={{ textAlign: 'left', color: 'var(--up)', width: '7%' }}>Chg OI</th>
                    <th style={{ textAlign: 'left', color: 'var(--up)', width: '8%' }}>OI</th>
                  </tr>
                  <tr>
                    <th colSpan={5} style={{ textAlign: 'center', fontSize: 9, color: 'var(--dn)', padding: '3px 0', background: 'rgba(239,83,80,0.06)' }}>— CALLS (CE) —</th>
                    <th style={{ background: 'var(--bg3)' }} />
                    <th colSpan={5} style={{ textAlign: 'center', fontSize: 9, color: 'var(--up)', padding: '3px 0', background: 'rgba(38,166,154,0.06)' }}>— PUTS (PE) —</th>
                  </tr>
                </thead>
                <tbody>
                  {chainRows.map((row: any) => {
                    const isAtm = row.is_atm
                    const bg = isAtm ? 'rgba(41,98,255,0.07)' : undefined
                    const fmt = (n: number | null) => n == null ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
                    const fmtOI = (n: number | null) => n == null ? '—' : (n / 1e5).toFixed(1) + 'L'
                    return (
                      <tr key={row.strike} style={{ background: bg }}>
                        {/* CE */}
                        <td className="mono" style={{ color: 'var(--dn)', fontWeight: isAtm ? 700 : 400 }}>{fmtOI(row.ce_oi)}</td>
                        <td className="mono" style={{ fontSize: 10, color: (row.ce_oi_chg ?? 0) > 0 ? 'var(--dn)' : 'var(--up)' }}>
                          {row.ce_oi_chg != null ? `${row.ce_oi_chg > 0 ? '+' : ''}${fmtOI(row.ce_oi_chg)}` : '—'}
                        </td>
                        <td className="mono" style={{ color: 'var(--txt2)' }}>{row.ce_iv != null ? row.ce_iv.toFixed(1) : '—'}</td>
                        <td className="mono" style={{ color: 'var(--txt2)', fontSize: 10 }}>{row.ce_delta != null ? row.ce_delta.toFixed(2) : '—'}</td>
                        <td className="mono" style={{ fontWeight: 600, color: 'var(--dn)' }}>{row.ce_ltp != null ? row.ce_ltp.toFixed(1) : '—'}</td>
                        {/* Strike */}
                        <td className="mono" style={{ textAlign: 'center', fontWeight: isAtm ? 800 : 600, color: isAtm ? 'var(--blue)' : 'var(--txt)', background: 'var(--bg3)', fontSize: isAtm ? 13 : 12 }}>
                          {row.strike?.toLocaleString('en-IN')}
                          {isAtm && <div style={{ fontSize: 8, color: 'var(--blue)', lineHeight: 1 }}>ATM</div>}
                        </td>
                        {/* PE */}
                        <td className="mono" style={{ textAlign: 'left', fontWeight: 600, color: 'var(--up)' }}>{row.pe_ltp != null ? row.pe_ltp.toFixed(1) : '—'}</td>
                        <td className="mono" style={{ textAlign: 'left', color: 'var(--txt2)', fontSize: 10 }}>{row.pe_delta != null ? row.pe_delta.toFixed(2) : '—'}</td>
                        <td className="mono" style={{ textAlign: 'left', color: 'var(--txt2)' }}>{row.pe_iv != null ? row.pe_iv.toFixed(1) : '—'}</td>
                        <td className="mono" style={{ textAlign: 'left', fontSize: 10, color: (row.pe_oi_chg ?? 0) > 0 ? 'var(--up)' : 'var(--dn)' }}>
                          {row.pe_oi_chg != null ? `${row.pe_oi_chg > 0 ? '+' : ''}${fmtOI(row.pe_oi_chg)}` : '—'}
                        </td>
                        <td className="mono" style={{ textAlign: 'left', color: 'var(--up)', fontWeight: isAtm ? 700 : 400 }}>{fmtOI(row.pe_oi)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* ── Max Pain ── */}
        {tab === 'Max Pain' && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {mpLoading && <div className="skeleton" style={{ height: 200 }} />}
            {maxPain && (
              <>
                {/* Summary cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                  {[
                    { label: 'Max Pain Strike', val: maxPain.max_pain_strike?.toLocaleString('en-IN'), color: 'var(--blue)' },
                    { label: 'Put/Call Ratio',  val: maxPain.pcr?.toFixed(2), color: maxPain.pcr > 1.3 ? 'var(--up)' : maxPain.pcr < 0.7 ? 'var(--dn)' : 'var(--txt)' },
                    { label: 'Total CE OI',     val: ((maxPain.ce_oi_total ?? 0) / 1e5).toFixed(1) + 'L', color: 'var(--dn)' },
                    { label: 'Total PE OI',     val: ((maxPain.pe_oi_total ?? 0) / 1e5).toFixed(1) + 'L', color: 'var(--up)' },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="tv-card" style={{ padding: '10px 14px' }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
                      <div className="mono" style={{ fontSize: 16, fontWeight: 700, color }}>{val ?? '—'}</div>
                    </div>
                  ))}
                </div>

                {/* Pain chart */}
                <div className="tv-card" style={{ padding: 14 }}>
                  <div className="section-title" style={{ marginBottom: 8 }}>Writer Pain by Strike (CE + PE)</div>
                  <PainBar data={painData} maxPain={maxPain.max_pain_strike} />
                  <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 10 }}>
                    <span style={{ color: 'rgba(239,83,80,0.8)' }}>■ CE writer pain</span>
                    <span style={{ color: 'rgba(38,166,154,0.8)' }}>■ PE writer pain</span>
                    <span style={{ color: 'var(--blue)' }}>┆ Max pain strike</span>
                  </div>
                </div>

                <div className="tv-card" style={{ padding: 14, fontSize: 11, color: 'var(--txt2)', lineHeight: 1.7 }}>
                  <strong style={{ color: 'var(--txt)' }}>How to read max pain:</strong> Option writers (mostly institutions) are motivated to let expiry happen near the max pain strike — the price where they lose the least money. When spot is within 2% of max pain on expiry day, expect pinning behaviour. Retail buyers lose; writers profit.
                </div>
              </>
            )}
          </div>
        )}

        {/* ── OI Walls ── */}
        {tab === 'OI Walls' && <OIWalls />}

        {/* ── IV Analysis ── */}
        {tab === 'IV Analysis' && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {ivData && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                  {[
                    { label: 'Current IV',     val: `${(ivData.current_iv ?? 0).toFixed(1)}%`, color: 'var(--txt)' },
                    { label: 'IV Rank',        val: `${Math.round((ivData.iv_rank ?? 0) * 100)}`, color: ivData.iv_rank > 0.7 ? 'var(--dn)' : ivData.iv_rank < 0.3 ? 'var(--up)' : 'var(--orange)' },
                    { label: 'IV Percentile',  val: `${Math.round((ivData.iv_percentile ?? 0) * 100)}%`, color: 'var(--txt)' },
                    { label: 'Strategy Bias',  val: (ivData.strategy_bias ?? '').replace(/_/g, ' '), color: 'var(--blue)' },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="tv-card" style={{ padding: '10px 14px' }}>
                      <div style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
                      <div className="mono" style={{ fontSize: 15, fontWeight: 700, color, textTransform: 'capitalize' }}>{val}</div>
                    </div>
                  ))}
                </div>

                <div className="tv-card" style={{ padding: 14 }}>
                  <div className="section-title" style={{ marginBottom: 10 }}>IV Rank Interpretation</div>
                  {[
                    { range: 'IV Rank > 70 (High IV)',   action: 'Sell premium strategies: iron condors, credit spreads, covered calls. IV will mean-revert lower.', color: 'var(--dn)' },
                    { range: 'IV Rank 30–70 (Normal IV)', action: 'Directional spreads: debit spreads, calendar spreads. Fair premium on both sides.', color: 'var(--orange)' },
                    { range: 'IV Rank < 30 (Low IV)',    action: 'Buy options outright: long calls/puts, straddles before events. Cheap premium, high reward potential.', color: 'var(--up)' },
                  ].map(({ range, action, color }) => (
                    <div key={range} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                      <div style={{ width: 3, background: color, borderRadius: 2, flexShrink: 0 }} />
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 11, color, marginBottom: 3 }}>{range}</div>
                        <div style={{ fontSize: 11, color: 'var(--txt2)' }}>{action}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {regime && (
                  <div className="tv-card" style={{ padding: 14 }}>
                    <div className="section-title" style={{ marginBottom: 10 }}>Regime + IV Combination</div>
                    <div style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.8 }}>
                      <strong style={{ color: 'var(--txt)' }}>Current:</strong> {regime.trend} trend · {regime.volatility} realized volatility · IV Rank {Math.round((ivData.iv_rank ?? 0.5) * 100)}<br />
                      <strong style={{ color: 'var(--txt)' }}>Implication:</strong>{' '}
                      {regime.trend === 'ranging' && ivData.iv_rank > 0.7
                        ? 'Range-bound + high IV → ideal for iron condors. Sell both sides and collect theta.'
                        : regime.trend === 'bullish' && ivData.iv_rank < 0.3
                        ? 'Uptrend + cheap IV → buy calls or call debit spreads. Good risk/reward.'
                        : regime.trend === 'bearish' && ivData.iv_rank < 0.3
                        ? 'Downtrend + cheap IV → buy puts or put debit spreads.'
                        : regime.trend !== 'ranging' && ivData.iv_rank > 0.7
                        ? 'Trend + high IV → directional credit spreads in trend direction. Collect premium with tailwind.'
                        : 'Mixed signals. Use defined-risk spreads to limit exposure.'}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Greeks ── */}
        {tab === 'Greeks' && (
          <div style={{ padding: 16 }}>
            <div className="tv-card" style={{ overflow: 'hidden' }}>
              <div className="panel-hdr">ATM Options Greeks — {sym}</div>
              {atm ? (
                <table className="tv-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Contract</th>
                      <th>LTP</th>
                      <th>Delta</th>
                      <th>IV%</th>
                      <th>What It Means</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--dn)' }}>{sym} {atm.strike} CE</td>
                      <td className="mono">{atm.ce_ltp?.toFixed(1) ?? '—'}</td>
                      <td className="mono" style={{ color: 'var(--txt)' }}>{atm.ce_delta?.toFixed(2) ?? '—'}</td>
                      <td className="mono">{atm.ce_iv?.toFixed(1) ?? '—'}%</td>
                      <td style={{ textAlign: 'left', fontSize: 11, color: 'var(--txt2)' }}>Gains ₹{atm.ce_delta?.toFixed(2) ?? '?'} per ₹1 rise in {sym}</td>
                    </tr>
                    <tr>
                      <td style={{ textAlign: 'left', fontWeight: 700, color: 'var(--up)' }}>{sym} {atm.strike} PE</td>
                      <td className="mono">{atm.pe_ltp?.toFixed(1) ?? '—'}</td>
                      <td className="mono" style={{ color: 'var(--txt)' }}>{atm.pe_delta?.toFixed(2) ?? '—'}</td>
                      <td className="mono">{atm.pe_iv?.toFixed(1) ?? '—'}%</td>
                      <td style={{ textAlign: 'left', fontSize: 11, color: 'var(--txt2)' }}>Gains ₹{Math.abs(atm.pe_delta ?? 0).toFixed(2)} per ₹1 fall in {sym}</td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <div style={{ padding: 24, color: 'var(--txt2)', textAlign: 'center' }}>No chain data. Select an instrument above.</div>
              )}
            </div>

            <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
              {[
                { greek: 'Delta (Δ)', range: '0 to 1 for CE, -1 to 0 for PE', meaning: 'How much the option price moves per ₹1 move in the underlying. ATM ≈ 0.50. Deep ITM ≈ 1.0.' },
                { greek: 'Gamma (Γ)', range: 'Always positive', meaning: 'Rate of change of delta. Highest at ATM near expiry — your delta changes fastest here. Gamma risk spikes on 0DTE.' },
                { greek: 'Theta (Θ)', range: 'Always negative for buyers', meaning: 'Time decay — how much premium you lose per day just by holding. Sellers collect this. ATM theta accelerates in last 7 days.' },
                { greek: 'Vega (V)',  range: 'Always positive for buyers', meaning: 'Sensitivity to IV changes. Buy before events (low IV → high IV). Sell after events (IV crush). 1 vega = ₹ change per 1% IV move.' },
              ].map(({ greek, range, meaning }) => (
                <div key={greek} className="tv-card" style={{ padding: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
                    <span style={{ fontWeight: 700, color: 'var(--txt)' }}>{greek}</span>
                    <span style={{ fontSize: 9, color: 'var(--txt3)', fontFamily: 'monospace' }}>{range}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.6 }}>{meaning}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
