import { create } from 'zustand'

type Mode = 'testing' | 'paper' | 'live'

interface ModeStore {
  mode: Mode
  setMode: (m: Mode) => void
}

export const useModeStore = create<ModeStore>(set => ({
  mode: 'testing',
  setMode: mode => set({ mode }),
}))
