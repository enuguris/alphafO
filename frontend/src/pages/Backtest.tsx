import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { fetchBacktests, runBacktest } from '../api/client'

const PATTERNS = [
  { key: 'gap_fill',       label: 'Gap Fill',       icon: '⇥', gradient: 'from-violet-600 to-purple-700' },
  { key: 'pcr_divergence', label: 'PCR Divergence', icon: '⇌', gradient: 'from-blue-600 to-cyan-700' },
  { key: 'mean_reversion', label: 'Mean Reversion', icon: '⟳', gradient: 'from-cyan-600 to-teal-700' },
  { key: 'oi_buildup',     label: 'OI Buildup',     icon: '↑', gradient: 'from-amber-600 to-orange-700' },
  { key: 'vwap_oi',        label: 'VWAP + OI',      icon: '⊛', gradient: 'from-teal-600 to-green-700' },
  { key: 'iv_crush',       label: 'IV Crush',       icon: '⤓', gradient: 'from-pink-600 to-rose-700' },
  { key: 'max_pain',       label: 'Max Pain',       icon: '◎', gradient: 'from-orange-600 to-red-700' },
  { key: 'expiry_week',    label: 'Expiry Week',    icon: '⏰', gradient: 'from-rose-600 to-pink-700' },
]

const INSTRUMENT_GROUPS = [
  { label: 'Indices',  items: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'] },
  { label: 'Banking',  items: ['HDFCBANK', 'ICICIBANK', 'AXISBANK', 'SBIN', 'KOTAKBANK'] },
  { label: 'IT',       items: ['TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM'] },
  { label: 'Energy',   items: ['RELIANCE', 'ONGC', 'NTPC', 'POWERGRID'] },
  { label: 'Auto',     items: ['TATAMOTORS', 'MARUTI', 'M&M', 'BAJAJ-AUTO'] },
  { label: 'Pharma',   items: ['SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB'] },
]

export default function Backtest() {
  const [form, setForm] = useState({
    underlying: 'NIFTY',
    start_date: '2023-01-01',
    end_date:   '2024-01-01',
    patterns:   PATTERNS.map(p => p.key),
    name:       'My Backtest',
  })
  const [selectedGroup, setSelectedGroup] = useState('Indices')

  const { data } = useQuery({ queryKey: ['backtests'], queryFn: fetchBacktests })
  const mutation = useMutation({ mutationFn: runBacktest })

  const togglePattern = (k: string) =>
    setForm(f => ({ ...f, patterns: f.patterns.includes(k) ? f.patterns.filter(x => x !== k) : [...f.patterns, k] }))

  const currentGroup = INSTRUMENT_GROUPS.find(g => g.label === selectedGroup)
  const results: any[] = data?.results ?? []

  return (
    <div className="px-6 py-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="rounded-2xl overflow-hidden relative px-6 py-5" style={{
        background: 'linear-gradient(135deg, #0d1b3e 0%, #1a0533 100%)',
        border: '1px solid rgba(56,189,248,0.2)',
      }}>
        <div className="absolute top-0 right-0 w-48 h-48 rounded-full opacity-15 pointer-events-none"
          style={{ background: 'radial-gradient(circle, #0ea5e9 0%, transparent 70%)', transform: 'translate(20%, -30%)' }} />
        <h1 className="text-2xl font-black text-white mb-1">🔬 Backtesting</h1>
        <p className="text-xs text-slate-400">Run historical simulations across instruments and pattern combinations</p>
      </div>

      {/* Config card */}
      <div className="rounded-2xl p-px" style={{ background: 'linear-gradient(135deg, rgba(56,189,248,0.3), rgba(139,92,246,0.2))' }}>
        <div className="bg-[#0f0f1e] rounded-2xl p-6 space-y-6">
          <h2 className="text-sm font-bold text-white">Configure Run</h2>

          {/* Row 1: name + dates */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Strategy Name', key: 'name', type: 'text', placeholder: 'e.g. NIFTY momentum' },
              { label: 'Start Date',    key: 'start_date', type: 'date', placeholder: '' },
              { label: 'End Date',      key: 'end_date',   type: 'date', placeholder: '' },
            ].map(({ label, key, type, placeholder }) => (
              <div key={key}>
                <label className="text-xs text-slate-400 block mb-1.5 font-medium">{label}</label>
                <input
                  type={type}
                  placeholder={placeholder}
                  value={(form as any)[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  className="w-full bg-white/[0.04] border border-white/[0.08] text-white rounded-xl px-3 py-2.5 text-sm outline-none focus:border-blue-500/60 hover:border-white/20 transition-colors"
                />
              </div>
            ))}
          </div>

          {/* Instrument pickers */}
          <div>
            <label className="text-xs text-slate-400 block mb-2 font-medium">Instrument</label>
            <div className="flex gap-3 flex-wrap">
              <select
                value={selectedGroup}
                onChange={e => {
                  setSelectedGroup(e.target.value)
                  const grp = INSTRUMENT_GROUPS.find(g => g.label === e.target.value)
                  if (grp) setForm(f => ({ ...f, underlying: grp.items[0] }))
                }}
                className="bg-white/[0.04] border border-white/[0.08] text-white text-sm rounded-xl px-3 py-2.5 outline-none cursor-pointer focus:border-blue-500/60 hover:border-white/20 transition-colors"
              >
                {INSTRUMENT_GROUPS.map(g => <option key={g.label} value={g.label}>{g.label}</option>)}
              </select>
              <select
                value={form.underlying}
                onChange={e => setForm(f => ({ ...f, underlying: e.target.value }))}
                className="bg-white/[0.04] border border-white/[0.08] text-white text-sm rounded-xl px-3 py-2.5 outline-none cursor-pointer focus:border-blue-500/60 hover:border-white/20 transition-colors"
              >
                {currentGroup?.items.map(sym => <option key={sym} value={sym}>{sym}</option>)}
              </select>
            </div>
          </div>

          {/* Pattern toggles */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <label className="text-xs text-slate-400 font-medium">Patterns</label>
              <span className="text-xs text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-full">
                {form.patterns.length}/{PATTERNS.length} selected
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {PATTERNS.map(({ key, label, icon, gradient }) => {
                const active = form.patterns.includes(key)
                return (
                  <button
                    key={key}
                    onClick={() => togglePattern(key)}
                    className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-sm transition-all ${
                      active
                        ? 'border-purple-500/40 text-white'
                        : 'border-white/[0.06] text-slate-500 hover:text-slate-300 hover:border-white/20'
                    }`}
                    style={active ? { background: 'linear-gradient(135deg, rgba(124,58,237,0.2), rgba(37,99,235,0.15))' } : {}}
                  >
                    <span className={`w-6 h-6 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center text-xs flex-shrink-0`}>
                      {icon}
                    </span>
                    <span className="text-xs truncate">{label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => mutation.mutate(form)}
              disabled={mutation.isPending || form.patterns.length === 0}
              className="font-bold text-white px-6 py-2.5 rounded-xl text-sm shadow-lg disabled:opacity-50 transition-all"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #2563eb)' }}
            >
              {mutation.isPending ? '⏳ Running…' : '🚀 Run Backtest'}
            </button>
            {mutation.isSuccess && <span className="text-emerald-400 text-sm">✅ Queued successfully</span>}
            {mutation.isError  && <span className="text-red-400 text-sm">❌ Failed to queue</span>}
          </div>
        </div>
      </div>

      {/* Results */}
      <div className="rounded-2xl overflow-hidden border border-white/[0.07] bg-[#0f0f1e]">
        <div className="px-5 py-4 border-b border-white/[0.06] flex items-center gap-2">
          <span className="text-sm font-bold text-white">Results</span>
          {results.length > 0 && (
            <span className="text-xs text-slate-500 bg-white/[0.04] px-2 py-0.5 rounded-full">{results.length} runs</span>
          )}
        </div>
        {results.length === 0 ? (
          <div className="text-center py-14">
            <div className="text-4xl mb-3">📊</div>
            <p className="text-slate-500">No backtest runs yet. Configure and run above.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  {['Name', 'Underlying', 'Return', 'Sharpe', 'Max DD', 'Win Rate', 'Trades'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-[11px] text-slate-500 font-semibold uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r: any) => (
                  <tr key={r.id} className="border-t border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 text-white font-medium text-xs">{r.name}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{r.underlying}</td>
                    <td className={`px-4 py-3 font-mono text-xs font-bold ${r.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {r.total_return_pct >= 0 ? '+' : ''}{r.total_return_pct?.toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-300">{r.sharpe_ratio?.toFixed(2)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-red-400">{r.max_drawdown_pct?.toFixed(1)}%</td>
                    <td className="px-4 py-3 font-mono text-xs text-amber-400">{r.win_rate?.toFixed(1)}%</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">{r.total_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
