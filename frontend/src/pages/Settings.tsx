import { useState } from 'react'
import { api } from '../api/client'
import { useModeStore } from '../store/modeStore'
import { useThemeStore } from '../store/themeStore'

const RISK_PARAMS = [
  ['Max Risk Per Trade',   '1%',    'Capped at 1% of capital per position'],
  ['Max Portfolio Heat',   '3%',    'Total capital at risk across all open trades'],
  ['Daily Loss Limit',     '2%',    'Auto-halt triggers if breached'],
  ['Weekly Loss Limit',    '3%',    'Weekly drawdown ceiling'],
  ['Paper Trades Needed',  '60',    'Minimum trades before live promotion'],
  ['Min Win Rate (Paper)', '55%',   'Required historical win rate'],
  ['Max Drawdown (Paper)', '10%',   'Maximum drawdown ceiling for paper accounts'],
]

const MODES = [
  {
    key: 'testing' as const,
    label: 'Testing',
    desc: 'No capital at risk. Uses synthetic/seed data. Safe for development.',
    color: 'var(--txt2)',
  },
  {
    key: 'paper' as const,
    label: 'Paper Trading',
    desc: 'Virtual ₹5,00,000 capital. Live market data. Real signals, no real money.',
    color: 'var(--orange)',
  },
  {
    key: 'live' as const,
    label: 'Live',
    desc: 'Real capital. Requires 60+ paper trades with ≥55% win rate.',
    color: 'var(--dn)',
  },
]

export default function Settings() {
  const { mode, setMode } = useModeStore()
  const { theme, toggle } = useThemeStore()
  const [kite, setKite]   = useState({ api_key: '', api_secret: '' })
  const [saved, setSaved] = useState('')
  const [saving, setSaving] = useState(false)

  const saveKite = async () => {
    setSaving(true)
    try {
      await api.post('/settings/kite-credentials', kite)
      setSaved('Credentials saved successfully.')
    } catch {
      setSaved('Failed to save — check API key format.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="scroll-y" style={{ height: '100%', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 680, margin: '0 auto', padding: '20px 20px 40px' }}>

        {/* ── Appearance ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Appearance</div>
          <div className="form-section">
            <div className="form-section-body">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--txt)', marginBottom: 3 }}>
                    {theme === 'dark' ? 'Dark Mode' : 'Light Mode'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--txt2)' }}>
                    {theme === 'dark'
                      ? 'TradingView dark terminal — easy on the eyes for long sessions'
                      : 'Bright screener style — great for daytime trading'}
                  </div>
                </div>
                <button onClick={toggle} className="tv-btn tv-btn-ghost" style={{ minWidth: 120, justifyContent: 'center' }}>
                  {theme === 'dark' ? '☀ Light Mode' : '🌙 Dark Mode'}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ── Trading Mode ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Trading Mode</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {MODES.map(({ key, label, desc, color }) => {
              const active = mode === key
              return (
                <button
                  key={key}
                  onClick={() => setMode(key)}
                  style={{
                    padding: '12px 14px', borderRadius: 6, cursor: 'pointer', textAlign: 'left',
                    border: `1px solid ${active ? color : 'var(--border)'}`,
                    background: active ? `color-mix(in srgb, ${color} 8%, var(--bg2))` : 'var(--bg2)',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 5, color: active ? color : 'var(--txt2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {key === 'live' && (
                      <span className="live-dot" style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--dn)' }} />
                    )}
                    {label}
                    {active && <span style={{ marginLeft: 'auto', fontSize: 9 }}>ACTIVE</span>}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', lineHeight: 1.5 }}>{desc}</div>
                </button>
              )
            })}
          </div>
        </section>

        {/* ── Zerodha Kite Connect ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Zerodha Kite Connect</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <p style={{ fontSize: 11, color: 'var(--txt2)', margin: 0 }}>
                Required for real-time market data. Get credentials from the <span style={{ color: 'var(--blue)' }}>kite.trade</span> developer console.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>API Key</div>
                  <input className="tv-input mono" placeholder="he5cfq90ki9uafui" value={kite.api_key}
                    onChange={e => setKite(k => ({ ...k, api_key: e.target.value }))} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>API Secret</div>
                  <input type="password" className="tv-input mono" placeholder="API secret" value={kite.api_secret}
                    onChange={e => setKite(k => ({ ...k, api_secret: e.target.value }))} />
                </div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--orange)', background: 'rgba(255,152,0,0.08)', border: '1px solid rgba(255,152,0,0.2)', borderRadius: 4, padding: '8px 12px', lineHeight: 1.6 }}>
                Access tokens expire daily. Re-authenticate via the Kite OAuth flow after saving credentials.
                Paste the <code style={{ fontFamily: 'monospace', background: 'rgba(255,152,0,0.12)', padding: '1px 4px', borderRadius: 3 }}>request_token</code> from the redirect URL into the backend to generate a session.
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveKite} disabled={saving || !kite.api_key} className="tv-btn tv-btn-primary">
                  {saving ? 'Saving…' : 'Save Credentials'}
                </button>
                {saved && (
                  <span style={{ fontSize: 11, color: saved.startsWith('Failed') ? 'var(--dn)' : 'var(--up)' }}>{saved}</span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ── AI Chat ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">AI Chat (Claude)</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <p style={{ fontSize: 11, color: 'var(--txt2)', margin: 0 }}>
                Powers the <strong style={{ color: 'var(--blue)' }}>✦ AI Chat</strong> panel. Add your key to <code style={{ fontFamily: 'monospace' }}>.env</code> and restart backend.
              </p>
              <div style={{ background: 'var(--bg3)', borderRadius: 4, padding: '10px 12px', fontFamily: 'monospace', fontSize: 12, color: 'var(--up)', border: '1px solid var(--border2)' }}>
                ANTHROPIC_API_KEY=sk-ant-api03-...
              </div>
              <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                Get your key at <span style={{ color: 'var(--blue)' }}>console.anthropic.com</span> → API Keys. Model: claude-sonnet-4-6. Cost: ~$3/M input tokens.
              </div>
            </div>
          </div>
        </section>

        {/* ── Risk Parameters ── */}
        <section>
          <div className="section-title">Risk Parameters</div>
          <div className="form-section" style={{ overflow: 'hidden' }}>
            <table className="tv-table">
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>Parameter</th>
                  <th style={{ textAlign: 'left' }}>Description</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {RISK_PARAMS.map(([label, val, desc]) => (
                  <tr key={label}>
                    <td style={{ textAlign: 'left', fontWeight: 600, color: 'var(--txt)' }}>{label}</td>
                    <td style={{ textAlign: 'left', color: 'var(--txt2)' }}>{desc}</td>
                    <td className="mono" style={{ color: 'var(--blue)', fontWeight: 700 }}>{val}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--txt3)' }}>
              Parameters are configured via the <code style={{ fontFamily: 'monospace' }}>.env</code> file.
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
