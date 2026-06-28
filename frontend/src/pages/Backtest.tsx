import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { fetchBacktests, runBacktest } from '../api/client'

const PATTERNS = ['pcr_divergence', 'oi_buildup', 'max_pain', 'iv_crush', 'gap_fill', 'expiry_week', 'mean_reversion', 'vwap_oi']
const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY']

export default function Backtest() {
  const [form, setForm] = useState({ underlying: 'NIFTY', start_date: '2023-01-01', end_date: '2024-01-01', patterns: PATTERNS, name: 'My Backtest' })
  const { data } = useQuery({ queryKey: ['backtests'], queryFn: fetchBacktests })
  const mutation = useMutation({ mutationFn: runBacktest })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Backtesting</h1>

      {/* Run form */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <h2 className="font-semibold text-gray-300">New Backtest Run</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Underlying</label>
            <select className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
              value={form.underlying} onChange={e => setForm(f => ({ ...f, underlying: e.target.value }))}>
              {UNDERLYINGS.map(u => <option key={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Strategy Name</label>
            <input className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
              value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Start Date</label>
            <input type="date" className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
              value={form.start_date} onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">End Date</label>
            <input type="date" className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm"
              value={form.end_date} onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} />
          </div>
        </div>
        <button
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending}
          className="bg-green-600 hover:bg-green-500 text-white px-5 py-2 rounded text-sm font-medium disabled:opacity-50">
          {mutation.isPending ? 'Running...' : 'Run Backtest'}
        </button>
        {mutation.isSuccess && <p className="text-green-400 text-sm">Backtest queued ✓</p>}
      </div>

      {/* Results table */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-400 text-xs">
            <tr>{['Name','Underlying','Return','Sharpe','Drawdown','Win Rate','Trades'].map(h => <th key={h} className="px-4 py-3 text-left">{h}</th>)}</tr>
          </thead>
          <tbody>
            {data?.results?.map((r: any) => (
              <tr key={r.id} className="border-t border-gray-800 hover:bg-gray-800/50">
                <td className="px-4 py-3 text-white">{r.name}</td>
                <td className="px-4 py-3">{r.underlying}</td>
                <td className={`px-4 py-3 font-mono ${r.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>{r.total_return_pct?.toFixed(1)}%</td>
                <td className="px-4 py-3 font-mono">{r.sharpe_ratio?.toFixed(2)}</td>
                <td className="px-4 py-3 font-mono text-red-400">{r.max_drawdown_pct?.toFixed(1)}%</td>
                <td className="px-4 py-3 font-mono">{r.win_rate?.toFixed(1)}%</td>
                <td className="px-4 py-3 font-mono">{r.total_trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.results?.length && <div className="text-center text-gray-500 text-sm py-10">No backtest runs yet.</div>}
      </div>
    </div>
  )
}
