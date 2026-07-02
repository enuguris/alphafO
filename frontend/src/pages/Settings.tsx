import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { fetchAnthropicKeyStatus, saveAnthropicKey, deleteAnthropicKey, fetchRiskStatus, haltTrading, resumeTrading } from '../api/client'
import { useModeStore } from '../store/modeStore'
import { useThemeStore, THEMES } from '../store/themeStore'

const RISK_PARAMS = [
  ['Max Risk Per Trade',   '1%',    'Capped at 1% of capital per position'],
  ['Max Portfolio Heat',   '3%',    'Total capital at risk across all open trades'],
  ['Daily Loss Limit',     '2%',    'Auto-halt triggers if breached'],
  ['Weekly Loss Limit',    '3%',    'Weekly drawdown ceiling'],
  ['Paper Trades Needed',  '60',    'Minimum trades before live promotion'],
  ['Min Win Rate (Paper)', '55%',   'Required historical win rate'],
  ['Max Drawdown (Paper)', '10%',   'Maximum drawdown ceiling for paper accounts'],
]

const MODES = [
  { key: 'testing' as const, label: 'Testing',      desc: 'Pattern engine runs on synthetic data. No orders placed.', color: 'var(--txt2)' },
  { key: 'paper'   as const, label: 'Paper Trading', desc: 'Signals execute as virtual trades. Real Kite data when connected.', color: 'var(--orange)' },
  { key: 'live'    as const, label: 'Live',          desc: 'Real orders via Kite. Requires valid access token.', color: 'var(--dn)' },
]

type Status = { text: string; ok: boolean } | null

interface TestCheck { check: string; ok: boolean; detail: string }
interface TestResult { passed: boolean; summary: string; results: TestCheck[] }

export default function Settings() {
  const { mode, setMode } = useModeStore()
  const { theme, setTheme } = useThemeStore()

  // Kite state
  const [apiKey,       setApiKey]       = useState('')
  const [apiSecret,    setApiSecret]    = useState('')
  const [requestToken, setRequestToken] = useState('')
  const [credStatus,   setCredStatus]   = useState<Status>(null)
  const [tokenStatus,  setTokenStatus]  = useState<Status>(null)
  const [savingCreds,  setSavingCreds]  = useState(false)
  const [generatingToken, setGeneratingToken] = useState(false)
  const [testing,      setTesting]      = useState(false)
  const [testResult,   setTestResult]   = useState<TestResult | null>(null)

  // Saved state loaded from DB
  const [savedInfo, setSavedInfo] = useState<{
    api_key: string; has_secret: boolean; token_valid: boolean; token_date: string | null
  } | null>(null)

  // Risk controls state
  const [riskStatus,   setRiskStatus]   = useState<{ halted: boolean; daily_pnl: number; capital_deployed: number; capital: number; params?: Record<string, number> } | null>(null)
  const [riskBusy,     setRiskBusy]     = useState(false)
  const [haltReason,   setHaltReason]   = useState('manual halt from UI')
  // Dynamic risk params
  const [riskParams, setRiskParams] = useState<Record<string, number> | null>(null)
  const [editingParams, setEditingParams] = useState<Record<string, string>>({})
  const [paramSaving, setParamSaving] = useState(false)
  const [paramStatus, setParamStatus] = useState<Status>(null)

  // Upstox state
  const [upApiKey,        setUpApiKey]        = useState('')
  const [upApiSecret,     setUpApiSecret]     = useState('')
  const [upAuthCode,      setUpAuthCode]      = useState('')
  const [upRedirectUri,   setUpRedirectUri]   = useState('https://127.0.0.1')
  const [upSavingCreds,   setUpSavingCreds]   = useState(false)
  const [upGenToken,      setUpGenToken]      = useState(false)
  const [upTestingConn,   setUpTestingConn]   = useState(false)
  const [upCredStatus,    setUpCredStatus]    = useState<Status>(null)
  const [upTokenStatus,   setUpTokenStatus]   = useState<Status>(null)
  const [upTestResult,    setUpTestResult]    = useState<TestResult | null>(null)
  const [upSavedInfo,     setUpSavedInfo]     = useState<{
    api_key: string; has_secret: boolean; token_valid: boolean; token_date: string | null
  } | null>(null)

  // Go-Live + risk tier state
  const [tier,    setTier]    = useState<any>(null)
  const [goLive,  setGoLive]  = useState<any>(null)
  const [glBusy,  setGlBusy]  = useState(false)

  // Anthropic key state
  const [anthropicKey,        setAnthropicKey]        = useState('')
  const [anthropicHasKey,     setAnthropicHasKey]     = useState(false)
  const [anthropicSaving,     setAnthropicSaving]     = useState(false)
  const [anthropicStatus,     setAnthropicStatus]     = useState<Status>(null)

  useEffect(() => {
    api.get('/settings/kite-credentials')
      .then(r => { setSavedInfo(r.data); if (r.data.api_key) setApiKey(r.data.api_key) })
      .catch(() => {})
    api.get('/settings/upstox-credentials')
      .then(r => { setUpSavedInfo(r.data); if (r.data.api_key) setUpApiKey(r.data.api_key) })
      .catch(() => {})
    fetchAnthropicKeyStatus()
      .then(r => setAnthropicHasKey(r.has_key))
      .catch(() => {})
    fetchRiskStatus()
      .then(r => { setRiskStatus(r); if (r.params) { setRiskParams(r.params); const init: Record<string, string> = {}; Object.entries(r.params).forEach(([k,v]) => { init[k] = String(v) }); setEditingParams(init) } })
      .catch(() => {})
    api.get('/options/risk/tier').then(r => setTier(r.data)).catch(() => {})
    api.get('/options/risk/go-live-status').then(r => setGoLive(r.data)).catch(() => {})
  }, [])

  const toggleGoLive = async () => {
    if (!goLive) return
    const next = !goLive.go_live_requested
    if (next && !window.confirm('Request Go-Live? Real orders remain blocked by PAPER_ONLY_LOCK — this only records intent.')) return
    setGlBusy(true)
    try {
      await api.post('/options/risk/go-live', { enable: next })
      const r = await api.get('/options/risk/go-live-status')
      setGoLive(r.data)
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? 'Failed')
    } finally { setGlBusy(false) }
  }

  const saveAnthropicKeyHandler = async () => {
    if (!anthropicKey) return
    setAnthropicSaving(true); setAnthropicStatus(null)
    try {
      await saveAnthropicKey(anthropicKey)
      setAnthropicHasKey(true)
      setAnthropicKey('')
      setAnthropicStatus({ text: 'API key saved and encrypted in the database.', ok: true })
    } catch (e: any) {
      setAnthropicStatus({ text: e?.response?.data?.detail ?? 'Failed to save key.', ok: false })
    } finally {
      setAnthropicSaving(false)
    }
  }

  const removeAnthropicKeyHandler = async () => {
    if (!window.confirm('Remove the stored Anthropic API key?')) return
    try {
      await deleteAnthropicKey()
      setAnthropicHasKey(false)
      setAnthropicStatus({ text: 'API key removed.', ok: true })
    } catch {
      setAnthropicStatus({ text: 'Failed to remove key.', ok: false })
    }
  }

  const saveCreds = async () => {
    if (!apiKey || !apiSecret) return
    setSavingCreds(true); setCredStatus(null)
    try {
      await api.post('/settings/kite-credentials', { api_key: apiKey, api_secret: apiSecret })
      setCredStatus({ text: 'Credentials saved. API secret is encrypted in the database.', ok: true })
      setApiSecret('')  // clear from UI after save
      const r = await api.get('/settings/kite-credentials')
      setSavedInfo(r.data)
    } catch (e: any) {
      setCredStatus({ text: e?.response?.data?.detail ?? 'Failed to save credentials.', ok: false })
    } finally {
      setSavingCreds(false)
    }
  }

  const openLoginUrl = async () => {
    try {
      const r = await api.get('/settings/kite-login-url')
      window.open(r.data.login_url, '_blank')
    } catch (e: any) {
      setCredStatus({ text: e?.response?.data?.detail ?? 'Could not generate login URL. Save credentials first.', ok: false })
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await api.get('/settings/kite-test')
      setTestResult(r.data)
    } catch (e: any) {
      setTestResult({
        passed: false,
        summary: e?.response?.data?.detail ?? 'Connection test failed.',
        results: [],
      })
    } finally {
      setTesting(false)
    }
  }

  const upSaveCreds = async () => {
    if (!upApiKey || !upApiSecret) return
    setUpSavingCreds(true); setUpCredStatus(null)
    try {
      await api.post('/settings/upstox-credentials', { api_key: upApiKey, api_secret: upApiSecret })
      setUpCredStatus({ text: 'Credentials saved. Open login URL to authenticate.', ok: true })
      setUpApiSecret('')
      const r = await api.get('/settings/upstox-credentials')
      setUpSavedInfo(r.data)
    } catch (e: any) {
      setUpCredStatus({ text: e?.response?.data?.detail ?? 'Failed to save credentials.', ok: false })
    } finally { setUpSavingCreds(false) }
  }

  const upOpenLoginUrl = async () => {
    try {
      const r = await api.get('/settings/upstox-login-url')
      window.open(r.data.login_url, '_blank')
    } catch (e: any) {
      setUpCredStatus({ text: e?.response?.data?.detail ?? 'Save credentials first.', ok: false })
    }
  }

  const upGenerateToken = async () => {
    if (!upAuthCode) return
    setUpGenToken(true); setUpTokenStatus(null)
    try {
      const r = await api.post('/settings/upstox-token', { auth_code: upAuthCode, redirect_uri: upRedirectUri })
      setUpTokenStatus({ text: `${r.data.message} Valid until midnight today.`, ok: true })
      setUpAuthCode('')
      const info = await api.get('/settings/upstox-credentials')
      setUpSavedInfo(info.data)
    } catch (e: any) {
      setUpTokenStatus({ text: e?.response?.data?.detail ?? 'Token exchange failed.', ok: false })
    } finally { setUpGenToken(false) }
  }

  const upTestConnection = async () => {
    setUpTestingConn(true); setUpTestResult(null)
    try {
      const r = await api.get('/settings/upstox-test')
      setUpTestResult(r.data)
    } catch (e: any) {
      setUpTestResult({ passed: false, summary: e?.response?.data?.detail ?? 'Test failed.', results: [] })
    } finally { setUpTestingConn(false) }
  }

  const doHalt = async () => {
    if (!window.confirm(`Halt all automated trading?\nReason: "${haltReason}"`)) return
    setRiskBusy(true)
    try {
      await haltTrading(haltReason)
      const r = await fetchRiskStatus()
      setRiskStatus(r)
    } finally { setRiskBusy(false) }
  }

  const doResume = async () => {
    setRiskBusy(true)
    try {
      await resumeTrading()
      const r = await fetchRiskStatus()
      setRiskStatus(r)
    } finally { setRiskBusy(false) }
  }

  const saveRiskParamsHandler = async () => {
    setParamSaving(true); setParamStatus(null)
    try {
      const updates: Record<string, number> = {}
      Object.entries(editingParams).forEach(([k, v]) => { const n = parseFloat(v); if (!isNaN(n)) updates[k] = n })
      const r = await api.put('/options/risk/params', updates)
      setRiskParams(r.data.params)
      setParamStatus({ text: 'Risk parameters saved and active immediately.', ok: true })
    } catch (e: any) {
      setParamStatus({ text: e?.response?.data?.detail ?? 'Save failed.', ok: false })
    } finally { setParamSaving(false) }
  }

  const resetRiskParamsHandler = async () => {
    if (!window.confirm('Reset all risk parameters to .env defaults?')) return
    try {
      const r = await api.delete('/options/risk/params')
      setRiskParams(r.data.params)
      const init: Record<string, string> = {}; Object.entries(r.data.params).forEach(([k,v]) => { init[k] = String(v) }); setEditingParams(init)
      setParamStatus({ text: 'Reset to defaults.', ok: true })
    } catch { setParamStatus({ text: 'Reset failed.', ok: false }) }
  }

  const generateToken = async () => {
    if (!requestToken) return
    setGeneratingToken(true); setTokenStatus(null)
    try {
      const r = await api.post('/settings/kite-token', { request_token: requestToken })
      setTokenStatus({ text: `${r.data.message} Valid until midnight today.`, ok: true })
      setRequestToken('')
      const info = await api.get('/settings/kite-credentials')
      setSavedInfo(info.data)
    } catch (e: any) {
      setTokenStatus({ text: e?.response?.data?.detail ?? 'Token exchange failed.', ok: false })
    } finally {
      setGeneratingToken(false)
    }
  }

  return (
    <div className="scroll-y" style={{ height: '100%', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 700, margin: '0 auto', padding: '20px 20px 40px' }}>

        {/* ── Appearance ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Appearance — Theme</div>
          <div className="form-section">
            <div className="form-section-body">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
                {THEMES.map(t => (
                  <div
                    key={t.id}
                    className={`theme-card${theme === t.id ? ' active' : ''}`}
                    onClick={() => setTheme(t.id)}
                  >
                    <div
                      className="swatch"
                      style={{
                        background: `linear-gradient(135deg, ${t.bg} 50%, ${t.bg2} 50%)`,
                        border: `2px solid ${t.accent}`,
                      }}
                    />
                    <div className="t-name">{t.name}</div>
                    <div className="t-desc">{t.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ── Trading Mode ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Trading Mode</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {MODES.map(({ key, label, desc, color }) => {
              const active = mode === key
              return (
                <button key={key} onClick={() => setMode(key)} style={{
                  padding: '12px 14px', borderRadius: 6, cursor: 'pointer', textAlign: 'left',
                  border: `1px solid ${active ? color : 'var(--border)'}`,
                  background: active ? `color-mix(in srgb, ${color} 8%, var(--bg2))` : 'var(--bg2)',
                  transition: 'all 0.15s',
                }}>
                  <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 5, color: active ? color : 'var(--txt2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {key === 'live' && <span className="live-dot" style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--dn)' }} />}
                    {label}
                    {active && <span style={{ marginLeft: 'auto', fontSize: 9 }}>ACTIVE</span>}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', lineHeight: 1.5 }}>{desc}</div>
                </button>
              )
            })}
          </div>
        </section>

        {/* ── Zerodha Kite Connect ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Zerodha Kite Connect</div>
          <div className="form-section">

            {/* Step 1: Save credentials */}
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <div style={{ width: 18, height: 18, borderRadius: '50%', background: savedInfo?.has_secret ? 'var(--up)' : 'var(--border2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', fontWeight: 700, flexShrink: 0 }}>1</div>
                <span style={{ fontWeight: 600, color: 'var(--txt)', fontSize: 12 }}>Save API Credentials</span>
                {savedInfo?.has_secret && <span className="badge badge-up" style={{ marginLeft: 'auto' }}>✓ Saved</span>}
              </div>
              <p style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 12 }}>
                Get your API key and secret from the <span style={{ color: 'var(--blue)' }}>kite.trade</span> developer console.
                The secret is stored <strong style={{ color: 'var(--txt)' }}>encrypted</strong> in the database.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>API Key</div>
                  <input className="tv-input mono" placeholder="he5cfq90ki9uafui" value={apiKey}
                    onChange={e => setApiKey(e.target.value)} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    API Secret {savedInfo?.has_secret && <span style={{ color: 'var(--up)' }}>(already saved)</span>}
                  </div>
                  <input type="password" className="tv-input mono" placeholder={savedInfo?.has_secret ? '••••••••••••• (update to change)' : 'API secret'}
                    value={apiSecret} onChange={e => setApiSecret(e.target.value)} />
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveCreds} disabled={savingCreds || !apiKey || !apiSecret} className="tv-btn tv-btn-primary">
                  {savingCreds ? 'Saving…' : 'Save Credentials'}
                </button>
                {credStatus && (
                  <span style={{ fontSize: 11, color: credStatus.ok ? 'var(--up)' : 'var(--dn)' }}>{credStatus.text}</span>
                )}
              </div>
            </div>

            {/* Step 2: Generate login URL */}
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', opacity: savedInfo?.has_secret ? 1 : 0.4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div style={{ width: 18, height: 18, borderRadius: '50%', background: savedInfo?.token_valid ? 'var(--up)' : 'var(--border2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', fontWeight: 700, flexShrink: 0 }}>2</div>
                <span style={{ fontWeight: 600, color: 'var(--txt)', fontSize: 12 }}>Daily Authentication</span>
                {savedInfo?.token_valid
                  ? <span className="badge badge-up" style={{ marginLeft: 'auto' }}>✓ Token valid today ({savedInfo.token_date})</span>
                  : <span className="badge badge-warn" style={{ marginLeft: 'auto' }}>Token required</span>}
              </div>
              <p style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 10 }}>
                Kite access tokens expire at midnight every day. Click the button to open the Zerodha login page,
                then paste the <code style={{ fontFamily: 'monospace', background: 'var(--bg3)', padding: '1px 4px', borderRadius: 3 }}>request_token</code> from
                the redirect URL below to generate a new access token.
              </p>
              <button
                onClick={openLoginUrl}
                disabled={!savedInfo?.has_secret}
                className="tv-btn tv-btn-ghost"
                style={{ marginBottom: 12 }}
              >
                ↗ Open Kite Login Page
              </button>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Request Token (from redirect URL)
                  </div>
                  <input
                    className="tv-input mono"
                    placeholder="Paste request_token from kite.zerodha.com redirect URL"
                    value={requestToken}
                    onChange={e => setRequestToken(e.target.value)}
                    disabled={!savedInfo?.has_secret}
                  />
                </div>
                <button
                  onClick={generateToken}
                  disabled={generatingToken || !requestToken || !savedInfo?.has_secret}
                  className="tv-btn tv-btn-primary"
                >
                  {generatingToken ? 'Saving Access Token…' : 'Save Request Token'}
                </button>
              </div>
              {tokenStatus && (
                <div style={{ marginTop: 10, fontSize: 11, padding: '8px 10px', borderRadius: 4,
                  color: tokenStatus.ok ? 'var(--up)' : 'var(--dn)',
                  background: tokenStatus.ok ? 'rgba(38,166,154,0.08)' : 'rgba(239,83,80,0.08)',
                  border: `1px solid ${tokenStatus.ok ? 'rgba(38,166,154,0.2)' : 'rgba(239,83,80,0.2)'}`,
                }}>
                  {tokenStatus.text}
                </div>
              )}

              {/* How to find the request_token */}
              <details style={{ marginTop: 12 }}>
                <summary style={{ fontSize: 10, color: 'var(--txt3)', cursor: 'pointer', userSelect: 'none' }}>
                  How do I find the request_token?
                </summary>
                <div style={{ fontSize: 11, color: 'var(--txt2)', marginTop: 8, lineHeight: 1.7, paddingLeft: 4 }}>
                  After logging in, Zerodha redirects to your app's redirect URL like:<br />
                  <code style={{ fontFamily: 'monospace', fontSize: 10, background: 'var(--bg3)', padding: '2px 6px', borderRadius: 3, display: 'inline-block', marginTop: 4 }}>
                    https://127.0.0.1/?request_token=<strong>AbCdEf1234...</strong>&action=login&status=success
                  </code><br />
                  Copy the value after <code style={{ fontFamily: 'monospace', fontSize: 10 }}>request_token=</code> and paste it above.
                </div>
              </details>
            </div>

            {/* Status summary + Test Connection */}
            <div style={{ padding: '10px 16px', background: 'var(--bg3)', display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
              {[
                { label: 'API Key',     ok: !!savedInfo?.api_key,    val: savedInfo?.api_key ? `${savedInfo.api_key.slice(0,6)}…` : 'Not set' },
                { label: 'API Secret',  ok: !!savedInfo?.has_secret,  val: savedInfo?.has_secret ? 'Encrypted in DB' : 'Not set' },
                { label: 'Access Token',ok: !!savedInfo?.token_valid, val: savedInfo?.token_valid ? `Valid (${savedInfo.token_date})` : 'Expired / not set' },
              ].map(({ label, ok, val }) => (
                <div key={label}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
                  <div style={{ fontSize: 11, color: ok ? 'var(--up)' : 'var(--dn)', fontWeight: 600 }}>{val}</div>
                </div>
              ))}
              <button
                onClick={testConnection}
                disabled={testing || !savedInfo?.token_valid}
                className="tv-btn tv-btn-primary"
                style={{ marginLeft: 'auto', minWidth: 160 }}
                title={!savedInfo?.token_valid ? 'Generate a valid access token first' : 'Run live connection test'}
              >
                {testing
                  ? <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ display: 'inline-block', width: 10, height: 10, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
                      Testing…
                    </span>
                  : '⚡ Test Connection'}
              </button>
            </div>

            {/* Test result panel */}
            {testResult && (
              <div style={{
                margin: '0', padding: '14px 16px',
                background: testResult.passed ? 'rgba(38,166,154,0.06)' : 'rgba(239,83,80,0.06)',
                borderTop: `1px solid ${testResult.passed ? 'rgba(38,166,154,0.2)' : 'rgba(239,83,80,0.2)'}`,
              }}>
                {/* Summary line */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: testResult.results.length ? 12 : 0 }}>
                  <span style={{ fontSize: 18 }}>{testResult.passed ? '✓' : '✗'}</span>
                  <span style={{ fontWeight: 700, fontSize: 12, color: testResult.passed ? 'var(--up)' : 'var(--dn)' }}>
                    {testResult.summary}
                  </span>
                </div>

                {/* Per-check breakdown */}
                {testResult.results.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {testResult.results.map((r, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 10, alignItems: 'flex-start',
                        padding: '7px 10px', borderRadius: 4,
                        background: r.ok ? 'rgba(38,166,154,0.06)' : 'rgba(239,83,80,0.06)',
                        border: `1px solid ${r.ok ? 'rgba(38,166,154,0.15)' : 'rgba(239,83,80,0.15)'}`,
                      }}>
                        <span style={{ fontSize: 13, lineHeight: 1, marginTop: 1, flexShrink: 0, color: r.ok ? 'var(--up)' : 'var(--dn)' }}>
                          {r.ok ? '✓' : '✗'}
                        </span>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)', marginBottom: 2 }}>{r.check}</div>
                          <div style={{ fontSize: 11, color: 'var(--txt2)', lineHeight: 1.5 }}>{r.detail}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* ── Upstox ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Upstox API (LTP Round-Robin)</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

              {/* Status badge */}
              {upSavedInfo && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, color: 'var(--txt2)' }}>
                    API Key: <strong>{upSavedInfo.api_key || '—'}</strong>
                  </span>
                  <span style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 4,
                    background: upSavedInfo.token_valid ? 'var(--up)' : 'var(--orange)',
                    color: '#fff', fontWeight: 600,
                  }}>
                    {upSavedInfo.token_valid ? `TOKEN VALID (${upSavedInfo.token_date})` : 'NO TOKEN'}
                  </span>
                </div>
              )}

              {/* Step 1 — credentials */}
              <div>
                <div style={{ fontWeight: 600, color: 'var(--txt)', marginBottom: 6 }}>Step 1 — API Credentials</div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                  <input className="form-input" placeholder="API Key (client_id)" value={upApiKey}
                    onChange={e => setUpApiKey(e.target.value)} style={{ flex: 1 }} />
                  <input className="form-input" placeholder="API Secret" type="password" value={upApiSecret}
                    onChange={e => setUpApiSecret(e.target.value)} style={{ flex: 1 }} />
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="tv-btn" onClick={upSaveCreds} disabled={upSavingCreds || !upApiKey || !upApiSecret}>
                    {upSavingCreds ? 'Saving…' : 'Save Credentials'}
                  </button>
                  <button className="tv-btn" onClick={upOpenLoginUrl} disabled={!upSavedInfo?.api_key}>
                    Open Login URL
                  </button>
                </div>
                {upCredStatus && (
                  <div style={{ marginTop: 6, fontSize: 12, color: upCredStatus.ok ? 'var(--up)' : 'var(--dn)' }}>
                    {upCredStatus.text}
                  </div>
                )}
              </div>

              {/* Step 2 — auth code → token */}
              <div>
                <div style={{ fontWeight: 600, color: 'var(--txt)', marginBottom: 4 }}>Step 2 — Exchange Auth Code</div>
                <div style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 6 }}>
                  After login, copy the <code>code</code> param from the redirect URL (e.g. <code>https://127.0.0.1/?code=ABC123…</code>)
                </div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                  <input className="form-input" placeholder="Auth code from redirect URL" value={upAuthCode}
                    onChange={e => setUpAuthCode(e.target.value)} style={{ flex: 2 }} />
                  <input className="form-input" placeholder="Redirect URI" value={upRedirectUri}
                    onChange={e => setUpRedirectUri(e.target.value)} style={{ flex: 1 }} />
                </div>
                <button className="tv-btn" onClick={upGenerateToken} disabled={upGenToken || !upAuthCode}>
                  {upGenToken ? 'Generating…' : 'Generate Access Token'}
                </button>
                {upTokenStatus && (
                  <div style={{ marginTop: 6, fontSize: 12, color: upTokenStatus.ok ? 'var(--up)' : 'var(--dn)' }}>
                    {upTokenStatus.text}
                  </div>
                )}
              </div>

              {/* Test */}
              <div>
                <button className="tv-btn" onClick={upTestConnection} disabled={upTestingConn || !upSavedInfo?.token_valid}>
                  {upTestingConn ? 'Testing…' : 'Test Upstox Connection'}
                </button>
                {upTestResult && (
                  <div style={{ marginTop: 8, padding: 10, background: 'var(--bg2)', borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, color: upTestResult.passed ? 'var(--up)' : 'var(--dn)', marginBottom: 6 }}>
                      {upTestResult.passed ? '✓ Connected' : '✗ Failed'}
                    </div>
                    {upTestResult.results.map((r, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 4, fontSize: 12 }}>
                        <span style={{ color: r.ok ? 'var(--up)' : 'var(--dn)', minWidth: 12 }}>{r.ok ? '✓' : '✗'}</span>
                        <strong style={{ minWidth: 120 }}>{r.check}</strong>
                        <span style={{ color: 'var(--txt2)' }}>{r.detail}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ fontSize: 11, color: 'var(--txt2)', borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                When both Kite and Upstox tokens are valid, LTP calls alternate between them 50/50 to share rate-limit load.
                NSE option chain (jugaad-data) is used only when both APIs are unavailable.
              </div>
            </div>
          </div>
        </section>

        {/* ── AI Chat ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">AI Chat (Claude)</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--txt)', marginBottom: 3 }}>Anthropic API Key</div>
                  <div style={{ fontSize: 11, color: 'var(--txt2)' }}>
                    Powers the <strong style={{ color: 'var(--blue)' }}>✦ AI Chat</strong> panel.
                    Stored <strong style={{ color: 'var(--txt)' }}>encrypted</strong> in the database — never in plain text.
                  </div>
                </div>
                {anthropicHasKey && (
                  <span className="badge badge-up">✓ Key saved</span>
                )}
              </div>

              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    API Key {anthropicHasKey && <span style={{ color: 'var(--up)' }}>(already saved — paste new to rotate)</span>}
                  </div>
                  <input
                    type="password"
                    className="tv-input mono"
                    placeholder={anthropicHasKey ? '••••••••••••• (paste new key to rotate)' : 'sk-ant-api03-…'}
                    value={anthropicKey}
                    onChange={e => setAnthropicKey(e.target.value)}
                  />
                </div>
                <button
                  onClick={saveAnthropicKeyHandler}
                  disabled={anthropicSaving || !anthropicKey}
                  className="tv-btn tv-btn-primary"
                >
                  {anthropicSaving ? 'Saving…' : anthropicHasKey ? 'Rotate Key' : 'Save Key'}
                </button>
                {anthropicHasKey && (
                  <button
                    onClick={removeAnthropicKeyHandler}
                    className="tv-btn"
                    style={{ color: 'var(--dn)', border: '1px solid rgba(239,83,80,0.35)' }}
                  >
                    Remove
                  </button>
                )}
              </div>

              {anthropicStatus && (
                <div style={{ fontSize: 11, padding: '7px 10px', borderRadius: 4,
                  color: anthropicStatus.ok ? 'var(--up)' : 'var(--dn)',
                  background: anthropicStatus.ok ? 'rgba(38,166,154,0.08)' : 'rgba(239,83,80,0.08)',
                  border: `1px solid ${anthropicStatus.ok ? 'rgba(38,166,154,0.2)' : 'rgba(239,83,80,0.2)'}`,
                }}>
                  {anthropicStatus.text}
                </div>
              )}

              <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                Get your key at <span style={{ color: 'var(--blue)' }}>console.anthropic.com</span> → API Keys.
                Chat model: claude-haiku-4-5 (fast, ~₹0.08/msg). Briefing model: claude-sonnet-4-6.
              </div>
            </div>
          </div>
        </section>

        {/* ── Risk Controls ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Risk Controls</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {riskStatus && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 4 }}>
                  {[
                    { label: 'Daily P&L', val: `₹${riskStatus.daily_pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, color: riskStatus.daily_pnl >= 0 ? 'var(--up)' : 'var(--dn)' },
                    { label: 'Deployed', val: `₹${riskStatus.capital_deployed.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, color: 'var(--txt)' },
                    { label: 'Status', val: riskStatus.halted ? '⚠ HALTED' : '✓ Active', color: riskStatus.halted ? 'var(--dn)' : 'var(--up)' },
                  ].map(({ label, val, color }) => (
                    <div key={label} style={{ background: 'var(--bg)', borderRadius: 5, padding: '8px 10px', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</div>
                      <div style={{ fontFamily: 'monospace', fontWeight: 700, color }}>{val}</div>
                    </div>
                  ))}
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Halt reason</div>
                  <input
                    className="tv-input"
                    value={haltReason}
                    onChange={e => setHaltReason(e.target.value)}
                    placeholder="manual halt from UI"
                  />
                </div>
                <button onClick={doHalt} disabled={riskBusy || riskStatus?.halted} className="tv-btn" style={{ color: 'var(--dn)', border: '1px solid rgba(239,83,80,0.35)', whiteSpace: 'nowrap' }}>
                  ⏹ Halt Trading
                </button>
                <button onClick={doResume} disabled={riskBusy || !riskStatus?.halted} className="tv-btn tv-btn-primary" style={{ whiteSpace: 'nowrap' }}>
                  ▶ Resume Trading
                </button>
              </div>
              <div style={{ fontSize: 10, color: 'var(--txt3)' }}>
                Halt stops all auto-execution immediately. Resume clears the halt flag. Kill switch (permanent) requires Redis key deletion.
              </div>
            </div>
          </div>
        </section>

        {/* ── Risk Tier + Go-Live gate ── */}
        <section style={{ marginBottom: 20 }}>
          <div className="section-title">Risk Tier & Go-Live Readiness</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

              {/* Tier ladder */}
              {tier && (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 8 }}>
                    Corpus <b style={{ fontFamily: 'monospace' }}>₹{tier.corpus?.toLocaleString('en-IN')}</b> →
                    <b style={{ color: 'var(--blue)', marginLeft: 5 }}>{tier.tier_name}</b>
                    {tier.next_tier_at && (
                      <span style={{ color: 'var(--txt3)', marginLeft: 8 }}>
                        next tier at ₹{tier.next_tier_at.toLocaleString('en-IN')}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {tier.ladder?.map((t: any) => (
                      <div key={t.tier} style={{ flex: 1, padding: '8px 10px', borderRadius: 5,
                        background: t.active ? 'rgba(41,98,255,0.10)' : 'var(--bg)',
                        border: `1px solid ${t.active ? 'var(--blue)' : 'var(--border)'}` }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: t.active ? 'var(--blue)' : 'var(--txt2)' }}>{t.name}</div>
                        <div style={{ fontSize: 9, color: 'var(--txt3)', marginTop: 3 }}>
                          ≥₹{(t.min_corpus / 100000).toFixed(0)}L · risk {t.max_risk_pct}%/trade · heat {t.max_heat_pct}%
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Go-Live criteria */}
              {goLive && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--txt)' }}>Go-Live Criteria</span>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
                      color: goLive.eligible ? 'var(--up)' : 'var(--orange)',
                      background: goLive.eligible ? 'rgba(38,166,154,0.12)' : 'rgba(255,152,0,0.12)' }}>
                      {goLive.eligible ? 'ELIGIBLE' : 'NOT YET ELIGIBLE'}
                    </span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                    {Object.entries(goLive.criteria || {}).map(([key, c]: [string, any]) => (
                      <div key={key} style={{ background: 'var(--bg)', borderRadius: 5, padding: '8px 10px',
                        border: `1px solid ${c.pass ? 'rgba(38,166,154,0.4)' : 'var(--border)'}` }}>
                        <div style={{ fontSize: 9, color: 'var(--txt3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>
                          {key.replace(/_/g, ' ')}
                        </div>
                        <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 13,
                          color: c.pass ? 'var(--up)' : 'var(--txt)' }}>
                          {c.actual} <span style={{ fontSize: 10, color: 'var(--txt3)', fontWeight: 400 }}>/ {c.required} req.</span>
                          <span style={{ marginLeft: 5 }}>{c.pass ? '✓' : '✗'}</span>
                        </div>
                        {/* progress bar */}
                        <div style={{ height: 4, borderRadius: 2, background: 'var(--border)', marginTop: 5, overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 2, background: c.pass ? 'var(--up)' : 'var(--orange)',
                            width: `${Math.min(100, (c.actual / c.required) * 100)}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
                    <button onClick={toggleGoLive} disabled={glBusy || (!goLive.eligible && !goLive.go_live_requested)}
                      className="tv-btn"
                      style={{ padding: '6px 16px', fontWeight: 700,
                        color: goLive.go_live_requested ? 'var(--dn)' : 'var(--txt2)',
                        border: `1px solid ${goLive.go_live_requested ? 'rgba(239,83,80,0.5)' : 'var(--border2)'}`,
                        opacity: (!goLive.eligible && !goLive.go_live_requested) ? 0.45 : 1 }}>
                      {goLive.go_live_requested ? '⏹ Withdraw Go-Live Request' : '🔒 Request Go-Live'}
                    </button>
                    <span style={{ fontSize: 10, color: 'var(--txt3)', flex: 1 }}>{goLive.note}</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Risk Parameters (dynamic) ── */}
        <section>
          <div className="section-title">Risk Appetite Controls</div>
          <div className="form-section">
            <div className="form-section-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {riskParams ? (
                <>
                  {[
                    { key: 'max_portfolio_heat', label: 'Max Portfolio Heat (%)', desc: 'Total % of capital that can be deployed at once (e.g. 10 = 10%)' },
                    { key: 'max_daily_loss_pct', label: 'Daily Loss Limit (%)', desc: 'Auto-halt when daily P&L loss exceeds this % of capital' },
                    { key: 'max_risk_per_trade', label: 'Max Risk Per Trade (%)', desc: 'Max capital risked per individual trade position' },
                    { key: 'paper_capital', label: 'Paper Capital (₹)', desc: 'Total virtual capital for paper trading' },
                    { key: 'max_concurrent_trades', label: 'Max Concurrent Trades', desc: 'Maximum number of open positions at any time' },
                  ].map(({ key, label, desc }) => (
                    <div key={key} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
                        <div style={{ fontSize: 10, color: 'var(--txt3)', marginBottom: 4 }}>{desc}</div>
                      </div>
                      <input
                        className="tv-input"
                        style={{ width: 100, textAlign: 'right' }}
                        value={editingParams[key] ?? String(riskParams[key] ?? '')}
                        onChange={e => setEditingParams(p => ({ ...p, [key]: e.target.value }))}
                      />
                    </div>
                  ))}
                  <div style={{ display: 'flex', gap: 8, paddingTop: 4 }}>
                    <button onClick={saveRiskParamsHandler} disabled={paramSaving} className="tv-btn tv-btn-primary">
                      {paramSaving ? 'Saving...' : 'Save Parameters'}
                    </button>
                    <button onClick={resetRiskParamsHandler} className="tv-btn" style={{ color: 'var(--txt2)' }}>
                      Reset to Defaults
                    </button>
                  </div>
                  {paramStatus && (
                    <div style={{ fontSize: 11, color: paramStatus.ok ? 'var(--up)' : 'var(--dn)', padding: '4px 0' }}>
                      {paramStatus.text}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: 'var(--txt3)', marginTop: 4 }}>
                    Changes take effect immediately — no restart needed. With NIFTY lot size 65 @ ~₹200 premium = ₹13,000/lot.
                    Set Max Portfolio Heat to ≥10% (₹50,000) to allow 3-4 concurrent NIFTY trades.
                  </div>
                </>
              ) : (
                <div style={{ color: 'var(--txt3)', fontSize: 12 }}>Loading risk parameters...</div>
              )}
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
