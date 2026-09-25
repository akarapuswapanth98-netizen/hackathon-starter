import { useState } from 'react'

export default function ResponseArea({ loading, answer, steps, meta }) {
  const [copied, setCopied] = useState(false)

  if (loading) {
    return (
      <div className="card" style={{ textAlign: 'center', background: 'var(--gray-50)' }}>
        <div style={{ fontSize: '20px', fontWeight: 700 }}>⏳ AI thinking...</div>
        <div className="small" style={{ marginTop: '4px' }}>Planner → Reasoner → Validator → Final</div>
        <div className="loading-bar" style={{ marginTop: '16px' }}>
          <div className="loading-fill" />
        </div>
        <div className="small mt-2">Workflow running via <code>backend/app/agents/workflow.py</code> — mock works without API key</div>
      </div>
    )
  }

  if (!answer) {
    return (
      <div className="card" style={{ borderStyle: 'dashed', background: 'var(--gray-50)', textAlign: 'center', color: 'var(--gray-600)' }}>
        <div style={{ fontSize: '28px' }}>💡</div>
        <strong>No result yet</strong>
        <div className="small">Enter a problem and hit <strong>Solve</strong> — try a sample from the dropdown.</div>
        <div className="small mt-2">Tip: Use <code>Ctrl+Enter</code> to run</div>
      </div>
    )
  }

  const isMock = answer.includes('[MOCK')
  const copy = async () => {
    await navigator.clipboard.writeText(answer)
    setCopied(true)
    setTimeout(()=>setCopied(false), 1500)
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {isMock && (
        <div style={{ background: '#fef3c7', borderBottom: '1px solid #fde68a', padding: '10px 16px', fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span><strong>⚠️ Demo Mode:</strong> Mock LLM — set <code>LLM_API_KEY</code> in <code>backend/.env</code> for real inference. Workflow wiring is real.</span>
        </div>
      )}
      <div style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--gray-200)' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>✅ Result <span className="badge badge-success">success</span></h3>
        <div className="flex gap-2">
          <button onClick={copy} className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '12px' }}>{copied ? '✓ Copied' : '⧉ Copy'}</button>
          <button onClick={()=> {
            const blob = new Blob([JSON.stringify({answer, steps, meta}, null, 2)], {type:'application/json'})
            const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href=url; a.download='result.json'; a.click()
          }} className="btn btn-ghost" style={{ fontSize: '12px' }}>⬇ JSON</button>
        </div>
      </div>
      <div style={{ padding: '16px' }}>
        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, lineHeight: '1.7', fontSize: '14px' }}>{answer}</pre>
        {steps?.length > 0 && (
          <details style={{ marginTop: '16px', background: 'var(--gray-50)', border: '1px solid var(--gray-200)', borderRadius: '8px', padding: '10px' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--primary)', fontWeight: 600, fontSize: '13px' }}>🔍 Reasoning steps ({steps.length}) — LangGraph</summary>
            <ol style={{ margin: '10px 0 0', paddingLeft: '20px' }}>{steps.map((s,i)=><li key={i} style={{ fontSize: '13px', color: 'var(--gray-600)', marginBottom: '4px' }}>{s}</li>)}</ol>
          </details>
        )}
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
