import { useQuery } from '@tanstack/react-query'
import { fetchTrades, fetchPortfolio } from '../api/client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

export default function PaperTrading() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio', 'paper'], queryFn: () => fetchPortfolio('paper'), refetchInterval: 5000 })
  const { data: trades } = useQuery({ queryKey: ['trades', 'paper'], queryFn: () => fetchTrades('paper') })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Paper Trading</h1>

      {portfolio?.capital && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Virtual Capital', value: `₹${portfolio.capital?.toLocaleString('en-IN')}` },
            { label: 'Open Positions', value: portfolio.open_positions },
            { label: 'Win Rate', value: `${(portfolio.win_rate * 100)?.toFixed(1)}%`, color: portfolio.win_rate >= 0.55 ? 'text-green-400' : 'text-yellow-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className={`text-xl font-bold ${color || 'text-white'}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Promotion progress */}
      {portfolio?.total_trades !== undefined && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Live Trading Promotion Progress</h3>
          <div className="space-y-2">
            {[
              { label: 'Trades (need 60)', value: portfolio.total_trades, max: 60 },
            ].map(({ label, value, max }) => (
              <div key={label}>
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                  <span>{label}</span><span>{value}/{max}</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full">
                  <div className="h-2 bg-green-600 rounded-full transition-all" style={{ width: `${Math.min(100, value/max*100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trade log */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 text-sm font-semibold text-gray-300">Trade Journal</div>
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-400 text-xs">
            <tr>{['Instrument','Direction','Entry','Exit','P&L','Pattern','Status'].map(h => <th key={h} className="px-4 py-3 text-left">{h}</th>)}</tr>
          </thead>
          <tbody>
            {trades?.trades?.map((t: any) => (
              <tr key={t.id} className="border-t border-gray-800">
                <td className="px-4 py-3 font-mono text-xs text-white">{t.symbol}</td>
                <td className={`px-4 py-3 ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>{t.direction}</td>
                <td className="px-4 py-3 font-mono">₹{t.entry_price}</td>
                <td className="px-4 py-3 font-mono">{t.exit_price ? `₹${t.exit_price}` : '—'}</td>
                <td className={`px-4 py-3 font-mono ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{t.pnl ? `₹${t.pnl?.toFixed(0)}` : '—'}</td>
                <td className="px-4 py-3 text-xs text-gray-400">{t.pattern}</td>
                <td className="px-4 py-3 text-xs">{t.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!trades?.trades?.length && <div className="text-center text-gray-500 text-sm py-10">No paper trades yet. Execute signals from the Dashboard.</div>}
      </div>
    </div>
  )
}
