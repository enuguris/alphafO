import { useQuery } from '@tanstack/react-query'
import { fetchSignals, fetchPortfolio } from '../api/client'

const dirColor = (dir: string) => dir === 'long' ? 'text-green-400' : 'text-red-400'
const confidenceBadge = (score: number) => {
  if (score >= 0.8) return 'bg-green-700 text-green-100'
  if (score >= 0.6) return 'bg-yellow-700 text-yellow-100'
  return 'bg-gray-700 text-gray-300'
}

export default function Dashboard() {
  const { data: signals } = useQuery({ queryKey: ['signals'], queryFn: () => fetchSignals({ status: 'active' }), refetchInterval: 30000 })
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: () => fetchPortfolio(), refetchInterval: 5000 })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Signal Dashboard</h1>

      {/* Portfolio summary */}
      {portfolio && portfolio.capital && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Capital', value: `₹${portfolio.capital?.toLocaleString('en-IN')}` },
            { label: 'Daily P&L', value: `₹${portfolio.daily_pnl?.toLocaleString('en-IN')}`, color: portfolio.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
            { label: 'Win Rate', value: `${(portfolio.win_rate * 100)?.toFixed(1)}%` },
            { label: 'Portfolio Heat', value: `${portfolio.portfolio_heat_pct?.toFixed(1)}%`, color: portfolio.portfolio_heat_pct > 2 ? 'text-yellow-400' : 'text-green-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-gray-900 rounded-lg p-4 border border-gray-800">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className={`text-xl font-bold ${color || 'text-white'}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Signal cards */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-300">Active Signals</h2>
        {signals?.signals?.length === 0 && (
          <div className="text-gray-500 text-sm bg-gray-900 rounded-lg p-6 text-center">
            No active signals. Run signal detection or wait for market data.
          </div>
        )}
        {signals?.signals?.map((s: any) => (
          <div key={s.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-3">
              <span className="font-bold text-white">{s.underlying}</span>
              <span className={`font-semibold text-sm ${dirColor(s.direction)}`}>{s.direction?.toUpperCase()}</span>
              <span className={`text-xs px-2 py-0.5 rounded font-mono ${confidenceBadge(s.confidence_score)}`}>
                {(s.confidence_score * 100).toFixed(0)}% confidence
              </span>
              <span className="text-xs text-gray-500 ml-auto">{s.pattern_name?.replace(/_/g, ' ')}</span>
            </div>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div><span className="text-gray-500">Entry:</span> <span className="text-white font-mono">₹{s.entry_price}</span></div>
              <div><span className="text-gray-500">Target:</span> <span className="text-green-400 font-mono">₹{s.target_price}</span></div>
              <div><span className="text-gray-500">Stop:</span> <span className="text-red-400 font-mono">₹{s.stop_loss}</span></div>
            </div>
            <div className="text-xs text-gray-400 leading-relaxed border-t border-gray-800 pt-2">{s.explanation}</div>
            <div className="flex gap-2 pt-1">
              <button className="text-xs bg-green-700 hover:bg-green-600 text-white px-3 py-1 rounded">Paper Trade</button>
              <span className="text-xs text-gray-500 self-center">Expected: +{s.expected_return_pct}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
