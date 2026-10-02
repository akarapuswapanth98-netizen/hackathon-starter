/**
 * 2D HUD overlay (DOM/CSS) shown on top of the 3D scene.
 * Appears immediately once the API response arrives — never blocked by the
 * 3D replay animation. All numbers are verbatim from the live response.
 */

export default function Hud({ loading, result, replayNote }) {
  if (loading) {
    return (
      <div data-testid="hud-loading" style={panel}>
        <strong>⏳ Workflow initializing…</strong>
        <div className="small" style={{ color: '#cbd5e1' }}>
          POST /api/foodbridge/match in flight — 3D replay starts when real agent_events arrive. Nothing faked.
        </div>
        <div className="loading-bar" style={{ marginTop: '10px', background: 'rgba(255,255,255,0.2)' }}>
          <div className="loading-fill" />
        </div>
      </div>
    )
  }

  if (!result) return null

  const retried = (result.retry_count || 0) > 0
  const failed = result.workflow_status === 'failed'
  const empty = !failed && (result.allocation || []).length === 0

  return (
    <div data-testid="hud" style={panel}>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span data-testid="hud-total" style={chip}>Total allocated: {result.total_allocated}</span>
        <span data-testid="hud-unallocated" style={{ ...chip, background: 'rgba(255,255,255,0.15)' }}>
          Unallocated: {result.unallocated}
        </span>
        <span data-testid="hud-status" style={{ ...chip, background: failed ? '#dc2626' : 'rgba(255,255,255,0.15)' }}>
          workflow_status: {result.workflow_status}
        </span>
        <span data-testid="hud-retry" style={{ ...chip, background: retried ? '#d97706' : 'rgba(255,255,255,0.15)' }}>
          retry_count: {result.retry_count}
        </span>
      </div>
      {retried && (
        <div data-testid="hud-retry-note" className="small" style={{ color: '#fde68a', marginTop: '6px' }}>
          ↻ Retry occurred ×{result.retry_count} — see Verification agent cue.
        </div>
      )}
      {failed && (
        <div data-testid="hud-failed" className="small" style={{ color: '#fecaca', marginTop: '6px' }}>
          ❌ Workflow failed — no beams drawn.
          {result.error?.code ? ` ${result.error.code}: ${result.error.message}` : ''}
        </div>
      )}
      {empty && (
        <div data-testid="hud-empty" className="small" style={{ color: '#fde68a', marginTop: '6px' }}>
          🔍 No matches found — allocation is empty.
        </div>
      )}
      {result.summary && (
        <div data-testid="hud-summary" style={{ marginTop: '8px', fontSize: '12.5px', lineHeight: 1.55, color: '#f1f5f9' }}>
          {result.summary}
        </div>
      )}
      {replayNote && (
        <div data-testid="hud-replay-note" className="small" style={{ color: '#94a3b8', marginTop: '6px' }}>
          {replayNote}
        </div>
      )}
    </div>
  )
}

const panel = {
  position: 'absolute',
  top: '12px',
  left: '12px',
  maxWidth: '380px',
  background: 'rgba(15, 23, 42, 0.88)',
  color: 'white',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: '12px',
  padding: '12px 14px',
  fontSize: '13px',
  zIndex: 5,
  backdropFilter: 'blur(6px)',
}

const chip = {
  display: 'inline-block',
  background: '#059669',
  borderRadius: '20px',
  padding: '3px 10px',
  fontSize: '12px',
  fontWeight: 700,
}
