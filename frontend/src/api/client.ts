import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1' })

// ── Signals ────────────────────────────────────────────────────────────────
export const fetchSignals   = (params?: object)      => api.get('/signals/', { params }).then(r => r.data)
export const runSignals     = (underlying: string)   => api.post('/signals/run', null, { params: { underlying } }).then(r => r.data)

// ── Portfolio / Trades ─────────────────────────────────────────────────────
export const fetchPortfolio = (mode = 'paper')       => api.get('/portfolio/', { params: { mode } }).then(r => r.data)
export const fetchPnL       = (mode = 'paper', days = 30) => api.get('/portfolio/pnl', { params: { mode, days } }).then(r => r.data)
export const initPortfolio  = ()                     => api.post('/portfolio/init').then(r => r.data)
export const fetchTrades    = (mode = 'paper')       => api.get('/trades/', { params: { mode } }).then(r => r.data)

// ── Backtest ───────────────────────────────────────────────────────────────
export const runBacktest    = (data: object)         => api.post('/backtest/run', data).then(r => r.data)
export const fetchBacktests = ()                     => api.get('/backtest/results').then(r => r.data)

// ── Options analytics ─────────────────────────────────────────────────────
export const fetchRegime    = (underlying: string)   => api.get(`/options/regime/${underlying}`).then(r => r.data)
export const fetchIVRank    = (underlying: string)   => api.get(`/options/iv-rank/${underlying}`).then(r => r.data)
export const fetchChain     = (underlying: string)   => api.get(`/options/chain/${underlying}`).then(r => r.data)
export const fetchMaxPain   = (underlying: string)   => api.get(`/options/max-pain/${underlying}`).then(r => r.data)
export const fetchEvents    = ()                     => api.get('/options/events').then(r => r.data)

// ── Chat ──────────────────────────────────────────────────────────────────
export const sendChat       = (messages: object[])   => api.post('/chat/', { messages }).then(r => r.data)
