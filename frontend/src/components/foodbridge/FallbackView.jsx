/**
 * Non-3D fallback view — standard cards/timeline reusing the app's styling.
 * Renders the SAME real API data as the 3D scene; used when WebGL is
 * unavailable or prefers-reduced-motion is set. Handles every edge state.
 */

const KIND_COPY = {
  failure: { title: 'Request failed', badge: 'badge-danger' },
  timeout: { title: 'Request timed out', badge: 'badge-warning' },
  not_found: { title: 'Surplus not found (404)', badge: 'badge-warning' },
  unprocessable: { title: 'Malformed request (422)', badge: 'badge-warning' },
  conflict_allocated: { title: 'Lot already allocated (409)', badge: 'badge-warning' },
  conflict_in_progress: { title: 'Match already in progress (409)', badge: 'badge-warning' },
}

export default function FallbackView({ loading, errorKind, errorMessage, result }) {
  if (loading) {
    return (
      <div className="card" data-testid="fb-loading" style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '18px', fontWeight: 700 }}>⏳ Matching shelters…</div>
        <div className="muted">Contacting POST /api/foodbridge/match — replay starts when the real response arrives.</div>
        <div className="loading-bar" style={{ marginTop: '14px' }}>
          <div className="loading-fill" />
        </div>
      </div>
    )
  }

  if (errorKind || errorMessage) {
    const copy = KIND_COPY[errorKind] || KIND_COPY.failure
    return (
      <div className="card" data-testid={`fb-error-${errorKind || 'failure'}`}>
        <div className="card-header">⚠️ {copy.title}</div>
        <p className="muted" style={{ margin: '0 0 8px' }}>{errorMessage || 'The match request failed.'}</p>
        <span className={`badge ${copy.badge}`}>{errorKind || 'failure'}</span>
        <div className="small mt-2">
          {errorKind === 'timeout' && 'The backend did not respond in time. Retry or check backend logs.'}
          {errorKind === 'not_found' && 'Unknown surplus_id — pick a lot from GET /api/foodbridge/surplus.'}
          {errorKind === 'unprocessable' && 'The request body failed validation — check surplus_id / radius shape.'}
          {errorKind === 'conflict_allocated' && 'This lot was already consumed by an earlier match. Create a fresh lot via POST /api/foodbridge/surplus, then match again.'}
          {errorKind === 'conflict_in_progress' && 'Another match is already running for this lot. Wait for it to finish, then retry.'}
          {(!errorKind || errorKind === 'failure') && 'Check the backend is running and try again.'}
        </div>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="card" data-testid="fb-idle" style={{ borderStyle: 'dashed', textAlign: 'center', color: 'var(--gray-600)' }}>
        <div style={{ fontSize: '26px' }}>🍲</div>
        <strong>No match yet</strong>
        <div className="small">Hit “Find Shelter Matches” to run the six-agent workflow.</div>
      </div>
    )
  }

  const allocation = result.allocation || []
  const events = result.agent_events || []
  const isFailed = result.workflow_status === 'failed'
  const isEmpty = !isFailed && allocation.length === 0
  const retried = (result.retry_count || 0) > 0

  return (
    <div data-testid="fb-result">
      {isFailed && (
        <div className="card" data-testid="fb-failed" style={{ background: 'var(--danger-light)', borderColor: '#fecaca' }}>
          <div className="card-header" style={{ color: '#991b1b' }}>❌ Workflow failed — no meals routed</div>
          <div className="muted">
            {result.error?.code ? <strong>{result.error.code}: </strong> : null}
            {result.error?.message || 'The workflow reported failure. No beams drawn — nothing was allocated.'}
          </div>
          <div className="mt-2 flex gap-2" style={{ flexWrap: 'wrap' }}>
            <span className="badge badge-danger" data-testid="fb-status">workflow_status: {result.workflow_status}</span>
            <span className="badge badge-neutral" data-testid="fb-retry">retry_count: {result.retry_count}</span>
          </div>
        </div>
      )}

      {isEmpty && (
        <div className="card" data-testid="fb-empty" style={{ background: 'var(--warning-light)', borderColor: '#fde68a' }}>
          <div className="card-header">🔍 No matches found</div>
          <div className="muted">The workflow completed but the allocation array is empty — no shelter met the constraints for this lot.</div>
          <div className="mt-2 flex gap-2" style={{ flexWrap: 'wrap' }}>
            <span className="badge badge-warning" data-testid="fb-status">workflow_status: {result.workflow_status}</span>
            <span className="badge badge-neutral" data-testid="fb-retry">retry_count: {result.retry_count}</span>
          </div>
        </div>
      )}

      {!isFailed && !isEmpty && (
        <div className="card" data-testid="fb-success">
          <div className="card-header">✅ Match complete — {result.total_allocated} meals allocated</div>
          <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
            <span className="badge badge-success" data-testid="fb-total">Total allocated: {result.total_allocated}</span>
            <span className="badge badge-neutral" data-testid="fb-unallocated">Unallocated: {result.unallocated}</span>
            <span className="badge badge-neutral" data-testid="fb-status">workflow_status: {result.workflow_status}</span>
            <span className="badge badge-neutral" data-testid="fb-retry">retry_count: {result.retry_count}</span>
          </div>
          {retried && (
            <div className="mt-2" data-testid="fb-retried">
              <span className="badge badge-warning">↻ Retry occurred ×{result.retry_count} — verification re-ran matching</span>
            </div>
          )}
          {result.summary && (
            <div className="mt-3" data-testid="fb-summary" style={{ background: 'var(--gray-50)', border: '1px solid var(--gray-200)', borderRadius: '8px', padding: '10px', fontSize: '13px' }}>
              {result.summary}
            </div>
          )}
        </div>
      )}

      {/* Allocation cards — one per REAL allocation entry, never hard-coded */}
      {allocation.length > 0 && (
        <div className="mt-3" data-testid="fb-allocations">
          <div className="card-header">🏠 Allocations ({allocation.length})</div>
          <div style={{ display: 'grid', gap: '10px' }}>
            {allocation.map((a) => (
              <div key={a.shelter_id} className="card" data-testid={`fb-alloc-${a.shelter_id}`} style={{ padding: '12px' }}>
                <strong>{a.shelter_name}</strong>
                <div className="muted">{a.meals} meals · {Number(a.distance_km).toFixed(1)} km · score {Number(a.score).toFixed(3)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent timeline — verbatim details from agent_events */}
      {events.length > 0 && (
        <div className="card mt-3" data-testid="fb-timeline">
          <div className="card-header">🤖 Agent timeline ({events.length} events — staged replay of real events)</div>
          <ol style={{ margin: 0, paddingLeft: '20px' }}>
            {events.map((e, i) => (
              <li key={`${e.agent}-${i}`} data-testid={`fb-event-${e.agent}`} style={{ fontSize: '13px', marginBottom: '6px' }}>
                <strong>{e.agent}</strong> [{e.status}] — {e.detail}
                <div className="small">{new Date(e.timestamp).toLocaleString()}</div>
              </li>
            ))}
          </ol>
          {retried && (
            <div className="mt-2 small" data-testid="fb-retry-note">
              Verification shows a retry: retry_count={result.retry_count} (bounded re-run of matching).
            </div>
          )}
        </div>
      )}
    </div>
  )
}
