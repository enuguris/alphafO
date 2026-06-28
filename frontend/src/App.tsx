import { useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtest from './pages/Backtest'
import PaperTrading from './pages/PaperTrading'
import Settings from './pages/Settings'
import ChatPanel from './components/ChatPanel'
import { useModeStore } from './store/modeStore'
import { useThemeStore } from './store/themeStore'

const NAV = [
  { to: '/',         label: 'Dashboard' },
  { to: '/paper',    label: 'Paper Trading' },
  { to: '/backtest', label: 'Backtest' },
  { to: '/settings', label: 'Settings' },
]

const MODE_COLOR: Record<string, string> = {
  live:    'var(--dn)',
  paper:   'var(--orange)',
  testing: 'var(--txt2)',
}

export default function App() {
  const mode = useModeStore(s => s.mode)
  const { theme, toggle } = useThemeStore()
  const [chatOpen, setChatOpen] = useState(false)
  const isDark = theme === 'dark'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* ── Top bar ──────────────────────────────────────────── */}
      <header style={{
        display: 'flex', alignItems: 'center', height: 40, flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg2)',
        boxShadow: 'var(--shadow)',
        zIndex: 10,
      }}>
        {/* Logo */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 7,
          padding: '0 16px', borderRight: '1px solid var(--border)', height: '100%',
        }}>
          <div style={{
            width: 24, height: 24, borderRadius: 5,
            background: 'var(--blue)', display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontWeight: 900, fontSize: 13, color: '#fff',
          }}>α</div>
          <span style={{ fontWeight: 800, fontSize: 13, color: 'var(--txt)', letterSpacing: '-0.3px' }}>AlphaFO</span>
        </div>

        {/* Nav links */}
        <nav style={{ display: 'flex', height: '100%' }}>
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === '/'} style={({ isActive }) => ({
              display: 'flex', alignItems: 'center',
              padding: '0 14px', height: '100%',
              fontSize: 12, fontWeight: isActive ? 600 : 400,
              textDecoration: 'none',
              color: isActive ? 'var(--txt)' : 'var(--txt2)',
              borderBottom: `2px solid ${isActive ? 'var(--blue)' : 'transparent'}`,
              borderRight: '1px solid var(--border)',
              transition: 'color 0.12s, border-color 0.12s',
            })}>
              {label}
            </NavLink>
          ))}
        </nav>

        <div style={{ flex: 1 }} />

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', borderLeft: '1px solid var(--border)' }}>

          {/* Mode badge */}
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
            background: `color-mix(in srgb, ${MODE_COLOR[mode]} 12%, transparent)`,
            color: MODE_COLOR[mode],
            border: `1px solid color-mix(in srgb, ${MODE_COLOR[mode]} 35%, transparent)`,
            letterSpacing: '0.06em',
          }}>
            {mode === 'live' && (
              <span className="live-dot" style={{
                display: 'inline-block', width: 5, height: 5,
                borderRadius: '50%', background: 'var(--dn)', marginRight: 5,
              }} />
            )}
            {mode.toUpperCase()}
          </span>

          {/* Dark/Light toggle */}
          <button
            onClick={toggle}
            className="tv-btn tv-btn-ghost"
            style={{ padding: '4px 8px', fontSize: 14, gap: 0 }}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? '☀' : '🌙'}
          </button>

          {/* AI Chat toggle */}
          <button
            onClick={() => setChatOpen(o => !o)}
            className="tv-btn"
            style={{
              padding: '4px 10px', fontSize: 11,
              background: chatOpen ? 'rgba(41,98,255,0.12)' : 'transparent',
              color: chatOpen ? 'var(--blue)' : 'var(--txt2)',
              border: `1px solid ${chatOpen ? 'rgba(41,98,255,0.35)' : 'var(--border2)'}`,
            }}
          >
            ✦ AI Chat
          </button>
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ flex: 1, overflow: 'auto' }}>
          <Routes>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/paper"    element={<PaperTrading />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
        <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
      </div>
    </div>
  )
}
