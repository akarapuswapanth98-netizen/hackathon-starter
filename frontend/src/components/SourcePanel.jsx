export default function SourcePanel({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="card" style={{ background: 'var(--gray-50)', marginTop: '12px' }}>
      <div className="card-header">📚 Sources / References ({sources.length}) — RAG</div>
      <div className="small" style={{ marginBottom: '10px' }}>Cited from retrieval — <code>backend/app/rag/service.py</code> · Enable with <code>RAG_ENABLED=true</code></div>
      {sources.map((s, i) => (
        <div key={i} style={{ background: 'white', border: '1px solid var(--gray-200)', borderRadius: '8px', padding: '12px', marginBottom: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong style={{ fontSize: '13px' }}>{s.id || `Source ${i+1}`}</strong>
            {s.score != null && <span className="badge badge-neutral">score {s.score}</span>}
          </div>
          <div style={{ color: 'var(--gray-600)', marginTop: '6px', fontSize: '13px', lineHeight: '1.5' }}>{s.preview || s.text || JSON.stringify(s).slice(0,180)}</div>
        </div>
      ))}
    </div>
  )
}
