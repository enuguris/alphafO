import { useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtest from './pages/Backtest'
import PaperTrading from './pages/PaperTrading'
import Positions from './pages/Positions'
import Options from './pages/Options'
import Settings from './pages/Settings'
import ChatPanel from './components/ChatPanel'
import LiveStatus from './components/LiveStatus'
import PatternFinder from './pages/PatternFinder'
import Report from './pages/Report'
import SystemHealth from './pages/SystemHealth'
import Architecture from './pages/Architecture'
import SpreadBacktest from './pages/SpreadBacktest'
import { useModeStore } from './store/modeStore'
import { useThemeStore, THEMES } from './store/themeStore'

const NAV = [
  { to: '/',                label: 'Dashboard' },
  { to: '/options',         label: 'Options' },
  { to: '/positions',       label: 'Positions' },
  { to: '/pattern-finder',  label: 'Pattern Finder' },
  { to: '/report',          label: 'Report' },
  { to: '/paper',           label: 'Paper Trading' },
  { to: '/backtest',        label: 'Backtest' },
  { to: '/settings',        label: 'Settings' },
  { to: '/system',          label: 'System' },
  { to: '/architecture',    label: 'Architecture' },
  { to: '/spread-backtest', label: 'Spread BT' },
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
  const [statusOpen, setStatusOpen] = useState(false)
  const themeInfo = THEMES.find(t => t.id === theme) ?? THEMES[0]
  const THEME_ICONS: Record<string, string> = {
    dark: '🌑', midnight: '🌌', 'high-contrast': '⬛', solarized: '🌊', light: '☀'
  }

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

          {/* Theme cycle button */}
          <button
            onClick={toggle}
            className="tv-btn tv-btn-ghost"
            style={{ padding: '4px 10px', fontSize: 11, gap: 4 }}
            title={`Current: ${themeInfo.name} — click to cycle themes`}
          >
            <span style={{ fontSize: 13 }}>{THEME_ICONS[theme]}</span>
            <span>{themeInfo.name}</span>
          </button>

          {/* Live Status toggle */}
          <button
            onClick={() => setStatusOpen(o => !o)}
            className="tv-btn tv-btn-ghost"
            style={{
              padding: '4px 10px', fontSize: 11,
              background: statusOpen ? 'rgba(38,198,160,0.12)' : 'transparent',
              color: statusOpen ? '#26c6a0' : 'var(--txt2)',
              border: `1px solid ${statusOpen ? 'rgba(38,198,160,0.35)' : 'var(--border2)'}`,
            }}
          >
            ◉ Live
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
            <Route path="/"           element={<Dashboard />} />
            <Route path="/options"    element={<Options />} />
            <Route path="/positions"  element={<Positions />} />
            <Route path="/pattern-finder" element={<PatternFinder />} />
            <Route path="/backtest"   element={<Backtest />} />
            <Route path="/report"     element={<Report />} />
            <Route path="/paper"      element={<PaperTrading />} />
            <Route path="/settings"   element={<Settings />} />
            <Route path="/system"     element={<SystemHealth />} />
            <Route path="/architecture" element={<Architecture />} />
            <Route path="/spread-backtest" element={<SpreadBacktest />} />
          </Routes>
        </div>
        <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
        {statusOpen && <LiveStatus onClose={() => setStatusOpen(false)} />}
      </div>
    </div>
  )
}
