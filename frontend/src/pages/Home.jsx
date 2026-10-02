import { useState, useEffect } from 'react'
import api from '../services/api'
import ErrorBanner from '../components/ErrorBanner'
import ResponseArea from '../components/ResponseArea'
import SourcePanel from '../components/SourcePanel'
import FileUpload from '../components/FileUpload'

// Sample presets - TOMORROW: replace with problem-specific examples
const SAMPLES = [
  { label: 'Select a sample...', query: '', context: '' },
  { label: '📄 Document Q&A (RAG)', query: 'Summarize the key risks in the uploaded policy document', context: 'For compliance team, bullet points, cite sources' },
  { label: '📊 Data Prediction', query: 'Predict customer churn for next quarter using the CSV', context: 'Dataset has tenure, monthly charges, churn label' },
  { label: '💬 General LLM', query: 'Explain how LangGraph improves agent reliability vs plain LLM calls', context: 'Concise, for hackathon judges, 3 bullets' },
]

export default function Home() {
  const [query, setQuery] = useState('')
  const [context, setContext] = useState('')
  const [useRag, setUseRag] = useState(false)
  const [useAgents, setUseAgents] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [steps, setSteps] = useState([])
  const [trace, setTrace] = useState([])
  const [meta, setMeta] = useState(null)
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState('')
  const [sampleIdx, setSampleIdx] = useState(0)
  const [dark, setDark] = useState(false)

  useEffect(() => {
    try { document.documentElement.dataset.theme = dark ? 'dark' : '' } catch { /* ignore */ }
  }, [dark])

  // Auto-check health on mount - helps judge see backend is live
  useEffect(() => { checkHealth() }, [])

  // Keyboard: Ctrl+Enter to solve
  useEffect(() => {
    const h = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handleSolve() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  async function checkHealth() {
    setHealthError('')
    try {
      const h = await api.health()
      setHealth(h)
    } catch (e) {
      setHealthError(e.message)
    }
  }

  function applySample(idx) {
    setSampleIdx(idx)
    const s = SAMPLES[idx]
    if (s.query) {
      setQuery(s.query)
      setContext(s.context)
    }
  }

  function clearAll() {
    setQuery(''); setContext(''); setAnswer(''); setSources([]); setSteps([]); setTrace([]); setMeta(null); setError('')
  }

  function tryExample() {
    const s = SAMPLES[1]
    setQuery(s.query); setContext(s.context); setSampleIdx(1)
  }

  async function handleSolve() {
    if (!query.trim()) { setError('Please enter a problem / query'); return }
    if (query.length > 8000) { setError('Query too long (max 8000 chars)'); return }
    setLoading(true); setError(''); setAnswer(''); setSources([]); setSteps([]); setTrace([]); setMeta(null)
    try {
      // API CONTRACT: {query, context, use_rag, use_agents} -> {success, answer, sources, metadata, reasoning_steps, steps}
      const res = await api.solve({ query, context, use_rag: useRag, use_agents: useAgents })
      setAnswer(res.answer)
      setSources(res.sources || [])
      setSteps(res.reasoning_steps || [])
      setTrace(res.steps || [])
      setMeta({ ...res.metadata, total_duration_ms: res.total_duration_ms, token_estimate: res.token_estimate })
    } catch (e) {
      setError(e.message)
    } finally { setLoading(false) }
  }

  async function handleSolveLive() {
    if (!query.trim()) { setError('Please enter a problem / query'); return }
    setLoading(true); setError(''); setAnswer(''); setSources([]); setSteps([]); setTrace([]); setMeta(null)
    try {
      const base = import.meta.env.VITE_API_URL || 'http://localhost:8000'
      const res = await fetch(`${base}/api/solve/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, context, use_rag: useRag, use_agents: useAgents }),
      })
      if (!res.ok || !res.body) throw new Error(`Stream failed: HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      const liveTrace = []
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() || ''
        for (const p of parts) {
          const line = p.trim()
          if (!line.startsWith('data:')) continue
          try {
            const evt = JSON.parse(line.slice(5).trim())
            if (evt.type === 'step' && evt.step) {
              liveTrace.push(evt.step)
              setTrace([...liveTrace])
              setSteps([...liveTrace.map((t) => `${t.node}: ${t.output_summary || ''}`)])
            } else if (evt.type === 'final') {
              setAnswer(evt.answer || '')
              setSources(evt.sources || [])
              setTrace(evt.trace || liveTrace)
              setMeta({ total_duration_ms: evt.total_duration_ms })
            }
          } catch { /* ignore partial */ }
        }
      }
    } catch (e) {
      setError(e.message)
    } finally { setLoading(false) }
  }

  async function handleChat() {
    if (!query.trim()) { setError('Please enter a message'); return }
    setLoading(true); setError(''); setTrace([])
    try {
      const res = await api.chat({ message: query, use_rag: useRag })
      setAnswer(res.reply)
      setSources(res.sources || [])
      setMeta({ provider: res.provider, model: res.model, ...res.meta })
      setSteps([])
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  const isMock = health && health.llm_provider === 'mock'

  return (
    <div>
      {/* Header - sticky, demo-ready */}
      <header className="header">
        <div className="header-content">
          <div className="logo">⚡ Promptothon <span>· AI Starter · Hackathon Mode</span></div>
          <div className="health-bar">
            {health ? (
              <>
                <span className="badge badge-success"><span className="status-dot ok" /> Backend OK</span>
                <span className="badge badge-neutral">{health.llm_provider} / {health.llm_model}</span>
                <span className={health.rag_enabled ? 'badge badge-warning' : 'badge badge-neutral'}>RAG {health.rag_enabled ? 'ON' : 'OFF'}</span>
                <span className={health.db_enabled ? 'badge badge-success' : 'badge badge-neutral'}>DB {health.db_enabled ? 'ON' : 'OFF'}</span>
                {isMock && <span className="badge badge-warning">Demo Mode</span>}
              </>
            ) : (
              <span className="badge badge-neutral">Checking...</span>
            )}
            <button className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '12px' }} onClick={checkHealth}>↻ Health</button>
            <button className="btn btn-ghost" style={{ padding: '6px 12px', fontSize: '12px' }} onClick={() => setDark((d) => !d)}>{dark ? '☀️ Light' : '🌙 Dark'}</button>
          </div>
        </div>
        {healthError && <div className="container" style={{ paddingTop: 0 }}><ErrorBanner error={healthError} onDismiss={()=>setHealthError('')} /></div>}
      </header>

      <div className="container">
        {/* Top banner - easy to edit tomorrow */}
        <div className="card" style={{ background: 'linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%)', borderColor: '#bfdbfe' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <strong>Ready for problem reveal</strong> <span className="muted">— Adapt this starter in hours</span>
              <div className="small" style={{ marginTop: '4px' }}>React + FastAPI + LangGraph (optional) + RAG (optional) · API: <code>POST /api/solve</code> · Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to solve</div>
            </div>
            <div className="flex gap-2">
              <button className="btn btn-secondary" style={{ padding: '8px 14px' }} onClick={tryExample}>✨ Try an example</button>
              <select value={sampleIdx} onChange={e=>applySample(Number(e.target.value))} className="input" style={{ width: '220px', padding: '8px' }}>
                {SAMPLES.map((s,i)=><option key={i} value={i}>{s.label}</option>)}
              </select>
              <button className="btn btn-ghost" onClick={clearAll}>Clear</button>
            </div>
          </div>
        </div>

        <div className="grid-2 mt-4">
          {/* Left: Input */}
          <div className="card">
            <div className="card-header">📝 Input — Problem / Query *</div>
            <textarea
              value={query}
              onChange={e=>setQuery(e.target.value)}
              placeholder="Paste problem statement after reveal... e.g., 'Summarize policy docs with citations' or 'Classify tickets'"
              rows={6}
              className="textarea"
              style={{ fontSize: '15px' }}
            />
            <div className="flex" style={{ justifyContent: 'space-between', marginTop: '6px' }}>
              <span className="small">{query.length} chars</span>
              <span className="small">Ctrl+Enter to run</span>
            </div>

            <div className="card-header mt-3">📋 Extra Context (optional)</div>
            <textarea
              value={context}
              onChange={e=>setContext(e.target.value)}
              placeholder="Constraints, data notes, user type, output format... - TOMORROW: tailor this field"
              rows={3}
              className="textarea"
            />

            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center', marginTop: '12px', padding: '12px', background: 'var(--gray-50)', borderRadius: '8px', border: '1px solid var(--gray-200)' }}>
              <label style={{ display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px', fontWeight: 600 }}>
                <input type="checkbox" checked={useAgents} onChange={e=>setUseAgents(e.target.checked)} /> Use Agent Workflow
              </label>
              <label style={{ display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px', fontWeight: 600 }}>
                <input type="checkbox" checked={useRag} onChange={e=>setUseRag(e.target.checked)} /> Use RAG
              </label>
              <span className="small">RAG needs <code>RAG_ENABLED=true</code></span>
            </div>

            <FileUpload onUploaded={(r)=> setMeta(prev=>({...prev, upload:r}))} onError={setError} />

            <div className="flex gap-2 mt-3">
              <button onClick={handleSolve} disabled={loading} className="btn btn-primary" style={{ flex: 1, padding: '14px', fontSize: '16px', justifyContent: 'center' }}>
                {loading ? '⏳ Solving...' : '▶ Solve (Agentic)'}
              </button>
              <button onClick={handleSolveLive} disabled={loading} className="btn btn-secondary" style={{ padding: '14px 16px' }} title="Stream agent steps live via SSE">⚡ Live</button>
              <button onClick={handleChat} disabled={loading} className="btn btn-secondary" style={{ padding: '14px 20px' }}>Chat</button>
            </div>
            <div className="small mt-2">Primary demo: <strong>Solve</strong> (planner → executor/tools → validator). <strong>Live</strong> streams steps via SSE. Fallback: Chat.</div>
          </div>

          {/* Right: Output */}
          <div>
            <ErrorBanner error={error} onDismiss={()=>setError('')} onRetry={handleSolve} />
            <ResponseArea loading={loading} answer={answer} steps={steps} trace={trace} meta={meta} />
            <SourcePanel sources={sources} />
            {/* Helpers for demo */}
            <div className="card mt-3" style={{ background: 'var(--gray-50)' }}>
              <div className="card-header">🎯 Demo Tips</div>
              <ul className="muted" style={{ margin: 0, paddingLeft: '18px', fontSize: '13px' }}>
                <li>Keep problem ≤ 2 min — show workflow steps.</li>
                <li>If RAG: upload PDF first, then Solve with Use RAG ON.</li>
                <li>Backup video ready if backend sleeps.</li>
                <li>For judges: architecture `docs/architecture.md` + sources panel.</li>
              </ul>
            </div>
          </div>
        </div>

        <footer style={{ marginTop: '24px', textAlign: 'center', color: 'var(--gray-400)', fontSize: '12px' }}>
          Demo mode clearly labeled · Real LLM when <code>LLM_API_KEY</code> set · Easy to modify: <code>frontend/src/pages/Home.jsx</code> · See <code>docs/customization-guide.md</code>
        </footer>
      </div>
    </div>
  )
}
