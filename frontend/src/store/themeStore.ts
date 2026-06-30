import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'dark' | 'light' | 'midnight' | 'solarized' | 'high-contrast'

export const THEMES: { id: Theme; name: string; desc: string; bg: string; bg2: string; accent: string }[] = [
  { id: 'dark',          name: 'Dark',          desc: 'TradingView terminal',     bg: '#131722', bg2: '#1e222d', accent: '#2962ff' },
  { id: 'midnight',      name: 'Midnight',      desc: 'Deep navy / GitHub dark',  bg: '#0d1117', bg2: '#161b22', accent: '#58a6ff' },
  { id: 'high-contrast', name: 'High Contrast', desc: 'OLED black, vivid colors', bg: '#000000', bg2: '#0f0f0f', accent: '#4488ff' },
  { id: 'solarized',     name: 'Solarized',     desc: 'Warm teal dark palette',   bg: '#002b36', bg2: '#073642', accent: '#268bd2' },
  { id: 'light',         name: 'Light',         desc: 'Screener.in style',        bg: '#f0f3fa', bg2: '#ffffff', accent: '#1a56db' },
]

interface ThemeStore {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    set => ({
      theme: 'dark',
      setTheme: (t: Theme) => {
        applyTheme(t)
        set({ theme: t })
      },
      toggle: () => set(s => {
        const idx = THEMES.findIndex(x => x.id === s.theme)
        const next = THEMES[(idx + 1) % THEMES.length].id
        applyTheme(next)
        return { theme: next }
      }),
    }),
    { name: 'alphafO-theme' }
  )
)

// Apply saved theme on page load
const saved = localStorage.getItem('alphafO-theme')
const initial: Theme = saved ? (JSON.parse(saved)?.state?.theme ?? 'dark') : 'dark'
applyTheme(initial)
