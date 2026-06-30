import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1' })

// ── Signals ────────────────────────────────────────────────────────────────
export const fetchSignals   = (params?: object)      => api.get('/signals/', { params }).then(r => r.data)
export const runSignals     = (underlying: string)   => api.post('/signals/run', null, { params: { underlying } }).then(r => r.data)
export const scanAll        = (symbols?: string[], timeframes?: string[]) =>
  api.post('/signals/scan-all', { symbols, timeframes }).then(r => r.data)

// ── Portfolio / Trades ─────────────────────────────────────────────────────
export const fetchPortfolio = (mode = 'live')        => api.get('/portfolio/', { params: { mode } }).then(r => r.data)
export const fetchPnL       = (mode = 'live', days = 30) => api.get('/portfolio/pnl', { params: { mode, days } }).then(r => r.data)
export const initPortfolio  = ()                     => api.post('/portfolio/init').then(r => r.data)
export const fetchTrades     = (mode = 'live')       => api.get('/trades/', { params: { mode } }).then(r => r.data)
export const fetchOpenTrades = (mode = 'live')       => api.get('/trades/', { params: { mode, status: 'open' } }).then(r => r.data)
export const closeTrade      = (id: number)          => api.post(`/trades/${id}/close`).then(r => r.data)
export const refreshMtm      = ()                    => api.post('/trades/refresh-mtm').then(r => r.data)

// ── Backtest ───────────────────────────────────────────────────────────────
export const runBacktest    = (data: object)         => api.post('/backtest/run', data).then(r => r.data)
export const fetchBacktests = ()                     => api.get('/backtest/results').then(r => r.data)

// ── Options analytics ─────────────────────────────────────────────────────
export const fetchRegime    = (underlying: string)   => api.get(`/options/regime/${underlying}`).then(r => r.data)
export const fetchIVRank    = (underlying: string)   => api.get(`/options/iv-rank/${underlying}`).then(r => r.data)
export const fetchChain     = (underlying: string)   => api.get(`/options/chain/${underlying}`).then(r => r.data)
export const fetchMaxPain   = (underlying: string)   => api.get(`/options/max-pain/${underlying}`).then(r => r.data)
export const fetchEvents    = ()                     => api.get('/options/events').then(r => r.data)

// ── Instruments ───────────────────────────────────────────────────────────
export const fetchInstruments = (sector?: string)   => api.get('/instruments/', { params: sector ? { sector } : {} }).then(r => r.data)
export const fetchSectors     = ()                  => api.get('/instruments/sectors').then(r => r.data)

// ── Settings / Data status ────────────────────────────────────────────────
export const fetchDataStatus         = () => api.get('/settings/data-status').then(r => r.data)
export const fetchAnthropicKeyStatus = () => api.get('/settings/anthropic-key').then(r => r.data)
export const saveAnthropicKey        = (key: string) => api.post('/settings/anthropic-key', { api_key: key }).then(r => r.data)
export const deleteAnthropicKey      = () => api.delete('/settings/anthropic-key').then(r => r.data)

// ── Chat ──────────────────────────────────────────────────────────────────
export const sendChat       = (messages: object[])   => api.post('/chat/', { messages }).then(r => r.data)

// ── Pattern Finder ────────────────────────────────────────────────────────────
export const fetchPatternPerformance = ()             => api.get('/pattern-finder/performance').then(r => r.data)
export const fetchPatternRuns        = (p?: object)   => api.get('/pattern-finder/runs', { params: p }).then(r => r.data)
export const fetchBacktestTrades     = (id: number)   => api.get(`/pattern-finder/trades/${id}`).then(r => r.data)
export const fetchLiveAlerts         = ()             => api.get('/pattern-finder/live-alerts').then(r => r.data)
export const runPatternBacktest       = (body: object) => api.post('/pattern-finder/run', body).then(r => r.data)
export const deleteBacktestRun        = (id: number)   => api.delete(`/pattern-finder/runs/${id}`).then(r => r.data)
export const discoverPatterns         = (body: object) => api.post('/pattern-finder/discover', body).then(r => r.data)
export const fetchDiscoverProgress    = ()             => api.get('/pattern-finder/discover/progress').then(r => r.data)
export const fetchDiscoveredPatterns  = (p?: object)   => api.get('/pattern-finder/discovered', { params: p }).then(r => r.data)
export const toggleDiscoveredPattern  = (id: number)   => api.patch(`/pattern-finder/discovered/${id}/toggle`).then(r => r.data)
export const deleteDiscoveredPattern  = (id: number)   => api.delete(`/pattern-finder/discovered/${id}`).then(r => r.data)
export const clearAllDiscovered       = ()             => api.delete('/pattern-finder/discovered/all').then(r => r.data)
export const fetchDiscoveredChart     = (id: number)   => api.get(`/pattern-finder/discovered/${id}/chart`).then(r => r.data)

// ── Dashboard ─────────────────────────────────────────────────────────────
export const fetchPreMarket           = ()             => api.get('/dashboard/pre-market').then(r => r.data)
export const fetchPatternPerf         = ()             => api.get('/dashboard/pattern-performance').then(r => r.data)
export const fetchReport              = ()             => api.get('/dashboard/report').then(r => r.data)

// ── System ────────────────────────────────────────────────────────────────
export const fetchSystemHealth   = () => api.get('/system/health').then(r => r.data)
export const fetchSystemSchedule = () => api.get('/system/schedule').then(r => r.data)
export const runTask             = (name: string) => api.post(`/system/run-task/${name}`).then(r => r.data)
export const purgeDashboard      = () => api.delete('/dashboard/purge-junk-trades').then(r => r.data)

export const fetchRiskStatus  = () => api.get('/options/risk/status').then(r => r.data)
export const haltTrading      = (reason: string) => api.post('/options/risk/halt', { reason }).then(r => r.data)
export const resumeTrading    = () => api.post('/options/risk/resume').then(r => r.data)

// ── WebSocket helpers ─────────────────────────────────────────────────────
const WS_BASE = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`

export function createSignalSocket(onMessage: (data: any) => void, onError?: () => void) {
  const ws = new WebSocket(`${WS_BASE}/signals`)
  ws.onmessage = e => { try { onMessage(JSON.parse(e.data)) } catch {} }
  ws.onerror   = () => onError?.()
  ws.onclose   = () => onError?.()
  return ws
}

export function createPriceSocket(onTick: (ticks: Record<string, {ltp: number; chg: number}>) => void) {
  const ws = new WebSocket(`${WS_BASE}/prices`)
  ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'price_tick') onTick(msg.ticks)
    } catch {}
  }
  return ws
}
