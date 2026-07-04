import { useState } from 'react'
import { api } from '../api/client'

/**
 * Add a manual trade — mirror a position from the user's own broker account.
 * Tracking only: MTM with real prices, never auto-closed, excluded from
 * paper-strategy statistics.
 */

interface LegDraft {
  underlying: string; strike: string; option_type: string
  action: string; expiry_date: string; entry_price: string; lots: string
}

const EMPTY_LEG: LegDraft = {
  underlying: 'NIFTY', strike: '', option_type: 'PE',
  action: 'SELL', expiry_date: '', entry_price: '', lots: '1',
}

const inputStyle = {
  fontSize: 12, padding: '5px 8px', borderRadius: 4,
  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--txt)',
} as const

export default function ManualTradeModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [name, setName] = useState('Short Strangle')
  const [legs, setLegs] = useState<LegDraft[]>([{ ...EMPTY_LEG }])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const setLeg = (i: number, k: keyof LegDraft, v: string) =>
    setLegs(prev => prev.map((l, j) => j === i ? { ...l, [k]: v } : l))

  const submit = async () => {
    setErr(null)
    const parsed = []
    for (const l of legs) {
      if (!l.strike || !l.entry_price || !l.expiry_date) { setErr('Every leg needs strike, entry price and expiry date'); return }
      parsed.push({
        underlying: l.underlying, strike: parseFloat(l.strike), option_type: l.option_type,
        action: l.action, expiry_date: l.expiry_date, entry_price: parseFloat(l.entry_price),
        lots: parseInt(l.lots || '1'),
      })
    }
    setBusy(true)
    try {
      await api.post('/trades/manual', { name, legs: parsed })
      onAdded(); onClose()
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? 'Failed to add')
    } finally { setBusy(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 10,
          padding: 20, width: 720, maxWidth: '95vw', maxHeight: '85vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--txt)' }}>➕ Add Manual Trade</span>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none',
            color: 'var(--txt3)', fontSize: 16, cursor: 'pointer' }}>✕</button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--txt3)', marginBottom: 14 }}>
          Mirrors a position from YOUR broker account for tracking. The system marks it to market
          with real prices but will never close it or place any order.
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 10, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Strategy name</label>
          <input value={name} onChange={e => setName(e.target.value)} style={{ ...inputStyle, width: 240, display: 'block', marginTop: 4 }} />
        </div>

        {legs.map((l, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 8, flexWrap: 'wrap',
            padding: '10px 12px', background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
            {[
              ['Instrument', <select value={l.underlying} onChange={e => setLeg(i, 'underlying', e.target.value)} style={inputStyle}>
                <option>NIFTY</option><option>BANKNIFTY</option><option>FINNIFTY</option><option>MIDCPNIFTY</option></select>],
              ['Action', <select value={l.action} onChange={e => setLeg(i, 'action', e.target.value)} style={inputStyle}>
                <option>SELL</option><option>BUY</option></select>],
              ['Type', <select value={l.option_type} onChange={e => setLeg(i, 'option_type', e.target.value)} style={inputStyle}>
                <option>PE</option><option>CE</option></select>],
              ['Strike', <input value={l.strike} onChange={e => setLeg(i, 'strike', e.target.value)} placeholder="23600" style={{ ...inputStyle, width: 82 }} />],
              ['Expiry', <input type="date" value={l.expiry_date} onChange={e => setLeg(i, 'expiry_date', e.target.value)} style={inputStyle} />],
              ['Entry ₹', <input value={l.entry_price} onChange={e => setLeg(i, 'entry_price', e.target.value)} placeholder="66.05" style={{ ...inputStyle, width: 76 }} />],
              ['Lots', <input value={l.lots} onChange={e => setLeg(i, 'lots', e.target.value)} style={{ ...inputStyle, width: 46 }} />],
            ].map(([label, el], k) => (
              <div key={k}>
                <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', marginBottom: 3 }}>{label as string}</div>
                {el}
              </div>
            ))}
            {legs.length > 1 && (
              <button onClick={() => setLegs(prev => prev.filter((_, j) => j !== i))}
                style={{ background: 'none', border: 'none', color: 'var(--dn)', cursor: 'pointer', fontSize: 13, paddingBottom: 6 }}>✕</button>
            )}
          </div>
        ))}

        <button onClick={() => setLegs(prev => [...prev, { ...EMPTY_LEG, expiry_date: prev[prev.length-1]?.expiry_date ?? '' }])}
          className="tv-btn tv-btn-ghost" style={{ fontSize: 11, padding: '4px 12px', marginBottom: 14 }}>
          + Add leg
        </button>

        {err && <div style={{ color: 'var(--dn)', fontSize: 11, marginBottom: 10 }}>{err}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} className="tv-btn tv-btn-ghost" style={{ padding: '6px 16px', fontSize: 12 }}>Cancel</button>
          <button onClick={submit} disabled={busy} className="tv-btn tv-btn-primary" style={{ padding: '6px 18px', fontSize: 12, fontWeight: 700 }}>
            {busy ? 'Adding…' : 'Track Position'}
          </button>
        </div>
      </div>
    </div>
  )
}
