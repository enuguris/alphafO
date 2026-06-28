import { useState } from 'react'
import { api } from '../api/client'
import { useModeStore } from '../store/modeStore'

const RISK_PARAMS = [
  ['Max Risk Per Trade',   '1%',    'Capped at 1% of capital per position'],
  ['Max Portfolio Heat',   '3%',    'Total capital at risk across all open trades'],
  ['Daily Loss Limit',     '2%',    'Auto-halt triggers if breached'],
  ['Weekly Loss Limit',    '3%',    'Weekly drawdown ceiling'],
  ['Paper Trades Needed',  '60',    'Minimum trades for live promotion'],
  ['Min Win Rate (Paper)', '55%',   'Required historical win rate'],
  ['Max Drawdown (Paper)', '10%',   'Maximum drawdown ceiling for paper accounts'],
]

const MODE_DESCRIPTIONS: Record<string, { title: string; desc: string; accent: string }> = {
  testing: {
    title: 'Testing',
    desc:  'No capital at risk. Uses synthetic/seed data. Safe for development.',
    accent: 'border-slate-600/40 bg-slate-800/20 text-slate-300',
  },
  paper: {
    title: 'Paper Trading',
    desc:  'Virtual ₹5,00,000 capital. Live market data. Real signals, no real money.',
    accent: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  },
  live: {
    title: 'Live',
    desc:  'Real capital. Requires 60+ paper trades with ≥55% win rate. Handle with care.',
    accent: 'border-red-500/30 bg-red-500/10 text-red-300',
  },
}

export default function Settings() {
  const { mode, setMode } = useModeStore()
  const [kite, setKite]   = useState({ api_key: '', api_secret: '' })
  const [saved, setSaved] = useState('')
  const [saving, setSaving] = useState(false)

  const saveKite = async () => {
    setSaving(true)
    try {
      await api.post('/settings/kite-credentials', kite)
      setSaved('Credentials saved.')
    } catch {
      setSaved('Failed to save — check API key format.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="px-6 py-6 space-y-5 max-w-2xl">
      <h1 className="text-xl font-bold text-white">Settings</h1>

      {/* Mode selector */}
      <div className="bg-[#0f0f1e] border border-white/[0.07] rounded-xl p-5 space-y-3">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Trading Mode</h2>
        <div className="grid grid-cols-3 gap-3">
          {(['testing', 'paper', 'live'] as const).map(m => {
            const meta = MODE_DESCRIPTIONS[m]
            const active = mode === m
            return (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`text-left p-3 rounded-xl border transition-all ${
                  active ? meta.accent : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04] text-slate-500'
                }`}
              >
                <div className={`text-sm font-semibold mb-1 ${active ? '' : 'text-slate-400'}`}>{meta.title}</div>
                <div className={`text-[10px] leading-relaxed ${active ? 'opacity-80' : 'text-slate-600'}`}>{meta.desc}</div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Kite credentials */}
      <div className="bg-[#0f0f1e] border border-white/[0.07] rounded-xl p-5 space-y-4">
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Zerodha Kite Connect</h2>
          <p className="text-xs text-slate-600 mt-1">Required for real-time market data. Get from <span className="text-indigo-400">kite.trade</span> developer console.</p>
        </div>
        <div className="space-y-2.5">
          <div>
            <label className="text-xs text-slate-500 block mb-1">API Key</label>
            <input
              placeholder="e.g. he5cfq90ki9uafui"
              className="w-full bg-white/[0.04] border border-white/[0.08] text-slate-200 placeholder-slate-700 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-indigo-500/50 font-mono"
              value={kite.api_key}
              onChange={e => setKite(k => ({ ...k, api_key: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">API Secret</label>
            <input
              type="password"
              placeholder="API secret from Kite console"
              className="w-full bg-white/[0.04] border border-white/[0.08] text-slate-200 placeholder-slate-700 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-indigo-500/50 font-mono"
              value={kite.api_secret}
              onChange={e => setKite(k => ({ ...k, api_secret: e.target.value }))}
            />
          </div>
        </div>

        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2.5 text-xs text-amber-400 leading-relaxed">
          Access tokens expire daily. After saving credentials, re-authenticate via the Kite OAuth flow to get a fresh access token. Paste the <code className="font-mono bg-amber-500/15 px-1 rounded">request_token</code> from the redirect URL into the backend to generate a session.
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={saveKite}
            disabled={saving || !kite.api_key}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            {saving ? 'Saving…' : 'Save Credentials'}
          </button>
          {saved && <span className={`text-xs ${saved.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>{saved}</span>}
        </div>
      </div>

      {/* Risk parameters */}
      <div className="bg-[#0f0f1e] border border-white/[0.07] rounded-xl p-5">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Risk Parameters</h2>
        <div className="space-y-1">
          {RISK_PARAMS.map(([label, val, desc]) => (
            <div key={label} className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/[0.02]">
              <div className="flex-1">
                <div className="text-xs text-slate-300">{label}</div>
                <div className="text-[10px] text-slate-600">{desc}</div>
              </div>
              <span className="font-mono text-sm text-indigo-400 font-semibold">{val}</span>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-slate-700 mt-3">Parameters are configured via the <code className="font-mono">.env</code> file.</p>
      </div>
    </div>
  )
}
