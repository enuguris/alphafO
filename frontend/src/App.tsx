import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtest from './pages/Backtest'
import PaperTrading from './pages/PaperTrading'
import Settings from './pages/Settings'
import { useModeStore } from './store/modeStore'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 rounded text-sm font-medium transition-colors ${isActive ? 'bg-green-600 text-white' : 'text-gray-400 hover:text-white'}`

export default function App() {
  const mode = useModeStore(s => s.mode)
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-6">
        <span className="text-green-400 font-bold text-lg tracking-tight">⚡ AlphaFO</span>
        <span className={`text-xs px-2 py-0.5 rounded font-mono ${
          mode === 'live' ? 'bg-red-600' : mode === 'paper' ? 'bg-yellow-600' : 'bg-gray-700'
        } text-white`}>{mode.toUpperCase()}</span>
        <nav className="flex gap-1 ml-4">
          <NavLink to="/" className={navClass}>Dashboard</NavLink>
          <NavLink to="/backtest" className={navClass}>Backtest</NavLink>
          <NavLink to="/paper" className={navClass}>Paper Trading</NavLink>
          <NavLink to="/settings" className={navClass}>Settings</NavLink>
        </nav>
      </header>
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/paper" element={<PaperTrading />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
