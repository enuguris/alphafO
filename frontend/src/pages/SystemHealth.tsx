/**
 * System Health page — shows component health, Celery schedule, and manual task triggers.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchSystemHealth, fetchSystemSchedule, runTask } from '../api/client'
import { useState } from 'react'

const OK   = { color: 'var(--up)',   label: '●' }
const FAIL = { color: 'var(--dn)',   label: '●' }
const NA   = { color: 'var(--txt2)', label: '○' }

function StatusDot({ ok }: { ok?: boolean }) {
  const s = ok === true ? OK : ok === false ? FAIL : NA
  return <span style={{ color: s.color, marginRight: 6 }}>{s.label}</span>
}

const CARD: React.CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: '14px 16px',
  marginBottom: 12,
}

const TASK_MAP: Record<string, string> = {
  'sync-market-data':           'sync_market_data',
  'cleanup-stale-signals':      'cleanup_stale_signals',
  'nightly-pattern-backtest':   'run_nightly_backtests',
  'nightly-pattern-discovery':  'run_nightly_discovery',
  'mtm-update':                 'mtm_update',
  'eod-close-intraday':         'eod_close_intraday',
}

export default function SystemHealth() {
  const { data: health, refetch: refetchHealth } = useQuery({
    queryKey: ['system-health'],
    queryFn: fetchSystemHealth,
    refetchInterval: 30_000,
  })
  const { data: schedule } = useQuery({
    queryKey: ['system-schedule'],
    queryFn: fetchSystemSchedule,
    staleTime: 60_000,
  })

  const [running, setRunning] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<{ task: string; msg: string; ok: boolean }[]>([])

  const triggerTask = async (beatName: string) => {
    const taskKey = TASK_MAP[beatName]
    if (!taskKey) return
    setRunning(beatName)
    try {
      const r = await runTask(taskKey)
      setMsgs(m => [{ task: beatName, msg: r.message || 'Queued', ok: true }, ...m.slice(0, 4)])
      setTimeout(() => refetchHealth(), 3000)
    } catch {
      setMsgs(m => [{ task: beatName, msg: 'Failed to queue', ok: false }, ...m.slice(0, 4)])
    }
    setRunning(null)
  }

  const comps = health?.components || {}

  return (
    <div style={{ padding: 20, maxWidth: 900, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>System Health</h2>
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 3, fontWeight: 600,
          background: health?.ok ? 'rgba(0,200,83,.12)' : 'rgba(255,77,79,.12)',
          color: health?.ok ? 'var(--up)' : 'var(--dn)',
          border: `1px solid ${health?.ok ? 'rgba(0,200,83,.3)' : 'rgba(255,77,79,.3)'}`,
        }}>
          {health?.ok ? 'ALL SYSTEMS OK' : 'DEGRADED'}
        </span>
        <span style={{ fontSize: 11, color: 'var(--txt2)', marginLeft: 'auto' }}>
          {health?.as_of ? new Date(health.as_of + 'Z').toLocaleTimeString() : ''}
        </span>
      </div>

      {/* Component status grid */}
      <div style={CARD}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--txt2)', marginBottom: 10 }}>COMPONENTS</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {Object.entries(comps).map(([name, c]: [string, any]) => (
            <div key={name} style={{ padding: '8px 12px', background: 'var(--bg)', borderRadius: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <StatusDot ok={c.ok} />
                <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'capitalize' }}>
                  {name.replace('_', ' ')}
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.5 }}>
                {name === 'redis' && c.ok && (
                  <>
                    <div>Daily P&L: <b style={{ color: (c.daily_pnl || 0) >= 0 ? 'var(--up)' : 'var(--dn)' }}>
                      ₹{(c.daily_pnl || 0).toLocaleString()}</b></div>
                    <div>Deployed: ₹{(c.deployed || 0).toLocaleString()}</div>
                    <div style={{ color: c.trading_halted ? 'var(--dn)' : 'var(--txt2)' }}>
                      {c.trading_halted ? '⚠ TRADING HALTED' : 'Trading active'}
                    </div>
                  </>
                )}
                {name === 'market_data' && c.ok && (
                  <>
                    <div>Bhav files: {c.bhav_files}</div>
                    <div>VIX: {c.vix_cache ? '✓' : '✗'} FII: {c.fii_cache ? '✓' : '✗'}</div>
                    <div>PCR: NF={c.pcr_nifty ? '✓' : '✗'} BNF={c.pcr_banknifty ? '✓' : '✗'}</div>
                  </>
                )}
                {name === 'ticker' && (
                  <>
                    <div>Mode: {c.mode}</div>
                    {c.nifty_ltp > 0 && <div>NIFTY: {c.nifty_ltp?.toLocaleString()}</div>}
                    <div>Symbols tracked: {c.symbols}</div>
                  </>
                )}
                {name === 'kite' && <div>{c.detail}</div>}
                {name === 'celery' && (
                  <div>{c.workers?.length > 0 ? `Workers: ${c.workers.length}` : c.detail}</div>
                )}
                {name === 'database' && <div>{c.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Task log */}
      {msgs.length > 0 && (
        <div style={{ ...CARD, marginBottom: 12 }}>
          {msgs.map((m, i) => (
            <div key={i} style={{ fontSize: 11, color: m.ok ? 'var(--up)' : 'var(--dn)', padding: '2px 0' }}>
              {m.ok ? '✓' : '✗'} {m.task}: {m.msg}
            </div>
          ))}
        </div>
      )}

      {/* Schedule table */}
      {schedule && (
        <div style={CARD}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--txt2)', marginBottom: 10 }}>
            CELERY BEAT SCHEDULE ({schedule.count} tasks)
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: 'var(--txt2)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Task</th>
                <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Description</th>
                <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Schedule</th>
                <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Last Run</th>
                <th style={{ padding: '4px 8px' }}></th>
              </tr>
            </thead>
            <tbody>
              {schedule.tasks?.map((t: any) => (
                <tr key={t.name} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '5px 8px', color: 'var(--txt)', fontFamily: 'monospace', fontSize: 10 }}>
                    {t.name}
                  </td>
                  <td style={{ padding: '5px 8px', color: 'var(--txt2)' }}>{t.description}</td>
                  <td style={{ padding: '5px 8px', color: 'var(--txt2)', fontFamily: 'monospace', fontSize: 10 }}>
                    {t.schedule}
                  </td>
                  <td style={{ padding: '5px 8px', color: 'var(--txt2)' }}>
                    {t.last_run ? new Date(t.last_run + 'Z').toLocaleTimeString() : '—'}
                  </td>
                  <td style={{ padding: '5px 8px' }}>
                    {TASK_MAP[t.name] && (
                      <button
                        className="tv-btn tv-btn-ghost"
                        style={{ fontSize: 10, padding: '2px 8px' }}
                        disabled={running === t.name}
                        onClick={() => triggerTask(t.name)}
                      >
                        {running === t.name ? '…' : '▶ Run'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
