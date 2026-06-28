import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'dark' | 'light'

interface ThemeStore {
  theme: Theme
  toggle: () => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    set => ({
      theme: 'dark',
      toggle: () => set(s => {
        const next = s.theme === 'dark' ? 'light' : 'dark'
        document.documentElement.setAttribute('data-theme', next)
        return { theme: next }
      }),
    }),
    { name: 'alphafO-theme' }
  )
)

// Apply on load
const saved = localStorage.getItem('alphafO-theme')
const initial = saved ? (JSON.parse(saved)?.state?.theme ?? 'dark') : 'dark'
document.documentElement.setAttribute('data-theme', initial)
