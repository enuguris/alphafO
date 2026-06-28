import { useState } from 'react'
import { api } from '../api/client'
import { useModeStore } from '../store/modeStore'

export default function Settings() {
  const { mode, setMode } = useModeStore()
  const [kite, setKite] = useState({ api_key: '', api_secret: '' })
  const [saved, setSaved] = useState('')

  const saveKite = async () => {
    await api.post('/settings/kite-credentials', kite)
    setSaved('Kite credentials saved.')
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      {/* Mode selector */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
        <h2 className="font-semibold text-gray-300">Trading Mode</h2>
        <div className="flex gap-2">
          {(['testing', 'paper', 'live'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)}
              className={`px-4 py-2 rounded text-sm font-medium ${mode === m ? 'bg-green-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500">Live trading requires 60+ paper trades with ≥55% win rate.</p>
      </div>

      {/* Kite credentials */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
        <h2 className="font-semibold text-gray-300">Zerodha Kite Connect</h2>
        <p className="text-xs text-gray-500">Required for real-time data in paper/live modes. Get from kite.trade developer console.</p>
        <div className="space-y-2">
          <input placeholder="API Key" className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
            value={kite.api_key} onChange={e => setKite(k => ({ ...k, api_key: e.target.value }))} />
          <input placeholder="API Secret" type="password" className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
            value={kite.api_secret} onChange={e => setKite(k => ({ ...k, api_secret: e.target.value }))} />
        </div>
        <button onClick={saveKite} className="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded text-sm">Save Credentials</button>
        {saved && <p className="text-green-400 text-xs">{saved}</p>}
      </div>

      {/* Risk parameters */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="font-semibold text-gray-300 mb-3">Risk Parameters (Read-only)</h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          {[
            ['Max Risk Per Trade', '1%'],
            ['Max Portfolio Heat', '3%'],
            ['Daily Loss Limit', '2%'],
            ['Weekly Loss Limit', '3%'],
            ['Paper Trades Needed', '60'],
            ['Min Win Rate (Paper)', '55%'],
          ].map(([label, val]) => (
            <div key={label} className="flex justify-between bg-gray-800 px-3 py-2 rounded">
              <span className="text-gray-400">{label}</span>
              <span className="text-white font-mono">{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
