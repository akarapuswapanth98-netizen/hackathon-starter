export default function ErrorBanner({ error, onRetry, onDismiss }) {
  if (!error) return null
  return (
    <div style={{ background: 'var(--danger-light)', border: '1px solid #fecaca', color: '#991b1b', padding: '14px', borderRadius: '12px', margin: '12px 0', display: 'flex', gap: '12px' }}>
      <div style={{ fontSize: '20px' }}>⚠️</div>
      <div style={{ flex: 1 }}>
        <strong>Error</strong> <span style={{ fontSize: '13px' }}>{error}</span>
        <div style={{ marginTop: '10px', display: 'flex', gap: '8px' }}>
          {onRetry && <button onClick={onRetry} className="btn" style={{ padding: '6px 14px', background: 'var(--danger)', color: 'white', borderRadius: '6px' }}>Retry</button>}
          {onDismiss && <button onClick={onDismiss} className="btn btn-secondary" style={{ padding: '6px 14px' }}>Dismiss</button>}
        </div>
        <div className="small" style={{ marginTop: '8px', color: '#7f1d1d' }}>No secrets exposed. Check backend logs. If missing key → set <code>LLM_API_KEY</code> in <code>backend/.env</code>.</div>
      </div>
    </div>
  )
}
