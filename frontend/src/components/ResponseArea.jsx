import { useState } from 'react'

export function AgentTimeline({ trace, steps }) {
  const items = (trace && trace.length ? trace : (steps || []).map((s) => ({ node: 'step', output_summary: String(s) })))
  if (!items.length) return null
  return (
    <div style={{ marginTop: '16px' }}>
      <div style={{ fontWeight: 700, fontSize: '13px' }}>🧭 Agent steps ({items.length}) — live</div>
      <ol className="timeline">
        {items.map((t, i) => (
          <li key={i}>
            <strong>{t.node || 'step'}</strong> — {t.output_summary || t.input_summary || ''}
            {t.tool_name ? <span className="tool">🔧 {t.tool_name}</span> : null}
            {t.duration_ms != null ? <span className="ms">{t.duration_ms}ms</span> : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function ResponseArea({ loading, answer, steps, trace, meta }) {
  const [copied, setCopied] = useState(false)

  if (loading) {
    return (
      <div className="card" style={{ textAlign: 'center', background: 'var(--gray-50)' }}>
        <div style={{ fontSize: '20px', fontWeight: 700 }}>⏳ AI thinking...</div>
        <div className="small" style={{ marginTop: '4px' }}>Planner → Executor (tools) → Validator → Responder</div>
        <div className="loading-bar" style={{ marginTop: '16px' }}>
          <div className="loading-fill" />
        </div>
        {(trace?.length > 0 || steps?.length > 0) && <AgentTimeline trace={trace} steps={steps} />}
        <div className="small mt-2">Mock works without API key</div>
      </div>
    )
  }

  if (!answer) {
    return (
      <div className="card" style={{ borderStyle: 'dashed', background: 'var(--gray-50)', textAlign: 'center', color: 'var(--gray-600)' }}>
        <div style={{ fontSize: '28px' }}>💡</div>
        <strong>No result yet</strong>
        <div className="small">Enter a problem and hit <strong>Solve</strong> — or try an example.</div>
        <div className="small mt-2">Tip: Use <code>Ctrl+Enter</code> to run</div>
      </div>
    )
  }

  const isMock = answer.includes('[MOCK')
  const copy = async () => {
    await navigator.clipboard.writeText(answer)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {isMock && (
        <div style={{ background: '#fef3c7', borderBottom: '1px solid #fde68a', padding: '10px 16px', fontSize: '12px' }}>
          <span><strong>⚠️ Demo Mode:</strong> Mock LLM — set <code>LLM_API_KEY</code> for real inference.</span>
        </div>
      )}
      <div style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--gray-200)', flexWrap: 'wrap', gap: '8px' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>✅ Result <span className="badge badge-success">success</span></h3>
        <div className="flex gap-2">
          <button onClick={copy} className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '12px' }}>{copied ? '✓ Copied' : '⧉ Copy'}</button>
          <button onClick={() => {
            const blob = new Blob([JSON.stringify({ answer, steps, trace, meta }, null, 2)], { type: 'application/json' })
            const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'result.json'; a.click()
          }} className="btn btn-ghost" style={{ fontSize: '12px' }}>⬇ JSON</button>
        </div>
      </div>
      <div style={{ padding: '16px' }}>
        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, lineHeight: '1.7', fontSize: '14px' }}>{answer}</pre>
        <AgentTimeline trace={trace} steps={steps} />
        {meta && (
          <details style={{ marginTop: '12px' }}>
            <summary className="small" style={{ cursor: 'pointer' }}>Metadata</summary>
            <pre style={{ marginTop: '8px', background: 'var(--gray-100)', padding: '10px', borderRadius: '8px', fontSize: '11px', overflow: 'auto', maxHeight: '200px' }}>{JSON.stringify(meta, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  )
}
