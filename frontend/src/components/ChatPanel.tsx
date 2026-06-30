import { useState, useRef, useEffect } from 'react'
import { api } from '../api/client'

interface Msg { role: 'user' | 'assistant'; content: string }

const STARTERS = [
  'Explain the Gap Fill pattern',
  'What is PCR divergence?',
  'How does Max Pain work?',
  'Best expiry day strategies?',
]

export default function ChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [msgs, setMsgs]   = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, loading])

  const send = async (text: string) => {
    if (!text.trim() || loading) return
    const userMsg: Msg = { role: 'user', content: text.trim() }
    const next = [...msgs, userMsg]
    setMsgs(next)
    setInput('')
    setLoading(true)
    try {
      const res = await api.post('/chat/', { messages: next })
      setMsgs(m => [...m, { role: 'assistant', content: res.data.content }])
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? 'Unknown error'
      setMsgs(m => [...m, { role: 'assistant', content: `Error: ${detail}` }])
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="flex flex-col border-l" style={{ width: 320, height: '100%', background: 'var(--bg2)', borderColor: 'var(--border)', flexShrink: 0 }}>
      {/* Header */}
      <div className="panel-hdr" style={{ justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: 'var(--blue)', fontSize: 14 }}>✦</span>
          <span>AlphaFO AI</span>
          <span className="badge badge-blue" style={{ marginLeft: 2 }}>Claude</span>
        </div>
        <button onClick={onClose} className="tv-btn tv-btn-ghost" style={{ padding: '2px 7px', fontSize: 14 }}>×</button>
      </div>

      {/* Messages */}
      <div className="flex-1 scroll-y" style={{ padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {msgs.length === 0 && (
          <div style={{ padding: '16px 0', textAlign: 'center' }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>✦</div>
            <p style={{ color: 'var(--txt2)', fontSize: 12, marginBottom: 12 }}>
              Ask me anything about NSE F&amp;O markets, patterns, or your signals.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {STARTERS.map(s => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="tv-btn tv-btn-ghost fade-up"
                  style={{ fontSize: 11, textAlign: 'left', justifyContent: 'flex-start' }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) => (
          <div key={i} className={`fade-up ${m.role === 'user' ? 'chat-user' : 'chat-ai'}`}
            style={{ borderRadius: 6, padding: '8px 10px', fontSize: 12, lineHeight: 1.55 }}>
            <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 4, color: m.role === 'user' ? 'var(--blue)' : 'var(--purple)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              {m.role === 'user' ? 'You' : 'AlphaFO AI'}
            </div>
            <div style={{ color: 'var(--txt)', whiteSpace: 'pre-wrap' }}>{m.content}</div>
          </div>
        ))}

        {loading && (
          <div className="chat-ai fade-up" style={{ borderRadius: 6, padding: '8px 10px' }}>
            <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 6, color: 'var(--purple)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>AlphaFO AI</div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[0, 0.2, 0.4].map((d, j) => (
                <div key={j} className="live-dot" style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--txt3)', animationDelay: `${d}s` }} />
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border)', display: 'flex', gap: 6 }}>
        <textarea
          className="tv-input flex-1"
          rows={2}
          placeholder="Ask about patterns, signals, Greeks…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
          }}
          style={{ resize: 'none', fontSize: 12 }}
        />
        <button
          className="tv-btn tv-btn-primary"
          onClick={() => send(input)}
          disabled={!input.trim() || loading}
          style={{ alignSelf: 'flex-end', padding: '6px 10px' }}
        >
          ↑
        </button>
      </div>

      {/* Footer note */}
      <div style={{ padding: '5px 10px 8px', textAlign: 'center', fontSize: 10, color: 'var(--txt3)' }}>
        Set Anthropic API key in Settings → AI Chat
      </div>
    </div>
  )
}
