import { useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtest from './pages/Backtest'
import PaperTrading from './pages/PaperTrading'
import Settings from './pages/Settings'
import ChatPanel from './components/ChatPanel'
import { useModeStore } from './store/modeStore'

const NAV = [
  { to: '/',         label: 'Dashboard',     icon: '▤' },
  { to: '/paper',    label: 'Paper Trading',  icon: '◈' },
  { to: '/backtest', label: 'Backtest',       icon: '⊡' },
  { to: '/settings', label: 'Settings',       icon: '⊙' },
]

const MODE_COLOR: Record<string, string> = {
  live:    '#ef5350',
  paper:   '#ff9800',
  testing: '#787b86',
}

export default function App() {
  const mode = useModeStore(s => s.mode)
  const [chatOpen, setChatOpen] = useState(false)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* ── Top bar ── */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: 0,
        height: 38, flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg2)',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderRight: '1px solid var(--border)', height: '100%' }}>
          <span style={{ fontWeight: 900, fontSize: 15, color: '#2962ff', letterSpacing: '-0.5px' }}>α</span>
          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--txt)', letterSpacing: '-0.3px' }}>AlphaFO</span>
        </div>

        {/* Nav */}
        <nav style={{ display: 'flex', height: '100%' }}>
          {NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={({ isActive }) => ({
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '0 14px', height: '100%',
                fontSize: 12, fontWeight: 500, textDecoration: 'none',
                color: isActive ? 'var(--txt)' : 'var(--txt2)',
                borderBottom: isActive ? '2px solid var(--blue)' : '2px solid transparent',
                borderRight: '1px solid var(--border)',
                transition: 'all 0.12s',
              })}
            >
              <span style={{ fontSize: 11, opacity: 0.7 }}>{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px', borderLeft: '1px solid var(--border)' }}>
          {/* Mode badge */}
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 3,
            background: `${MODE_COLOR[mode]}22`, color: MODE_COLOR[mode],
            border: `1px solid ${MODE_COLOR[mode]}44`, letterSpacing: '0.06em',
          }}>
            {mode === 'live' && <span className="live-dot" style={{ display: 'inline-block', width: 5, height: 5, borderRadius: '50%', background: 'var(--dn)', marginRight: 4 }} />}
            {mode.toUpperCase()}
          </span>

          {/* AI Chat toggle */}
          <button
            onClick={() => setChatOpen(o => !o)}
            className="tv-btn"
            style={{
              padding: '4px 10px', fontSize: 11, gap: 5,
              background: chatOpen ? 'rgba(41,98,255,0.15)' : 'transparent',
              color: chatOpen ? 'var(--blue)' : 'var(--txt2)',
              border: `1px solid ${chatOpen ? 'rgba(41,98,255,0.4)' : 'var(--border2)'}`,
            }}
          >
            <span>✦</span>
            <span>AI Chat</span>
          </button>
        </div>
      </header>

      {/* ── Body: content + chat panel ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Page content */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          <Routes>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/paper"    element={<PaperTrading />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>

        {/* Chat panel */}
        <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
      </div>
    </div>
  )
}
