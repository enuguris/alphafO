import { create } from 'zustand'
import { api } from '../api/client'

type Mode = 'testing' | 'paper' | 'live'

interface ModeStore {
  mode: Mode
  setMode: (m: Mode) => Promise<void>
  syncFromBackend: () => Promise<void>
}

export const useModeStore = create<ModeStore>(set => ({
  mode: 'testing',

  setMode: async (mode) => {
    set({ mode })
    try {
      await api.put('/settings/mode', { mode })
    } catch {
      // mode is still updated locally even if backend call fails
    }
  },

  syncFromBackend: async () => {
    try {
      const r = await api.get('/settings/data-status')
      if (r.data?.mode) set({ mode: r.data.mode })
    } catch {}
  },
}))
