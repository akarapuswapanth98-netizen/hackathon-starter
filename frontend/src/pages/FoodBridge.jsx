/**
 * FoodBridge AI demo page — dedicated /foodbridge route.
 * Reuses the existing api service layer + design system; never hard-codes
 * the backend origin (VITE_API_URL via api.js).
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import api from '../services/api'
import ErrorBanner from '../components/ErrorBanner'
// Code-split the heavy three.js scene so Home stays light (~bundle concern:
// three.js is ~1MB; lazy import keeps it out of the initial chunk).
const FoodbridgeScene = lazy(() => import('../components/foodbridge/FoodbridgeScene'))
import FallbackView from '../components/foodbridge/FallbackView'
import Hud from '../components/foodbridge/Hud'
import { classifyMatchError } from '../components/foodbridge/layout'
import { isWebGLAvailable, prefersReducedMotion } from '../components/foodbridge/webgl'

export default function FoodBridge() {
  const [restaurants, setRestaurants] = useState([])
  const [shelters, setShelters] = useState([])
  const [lots, setLots] = useState([])
  const [surplusId, setSurplusId] = useState('')
  const [radius, setRadius] = useState(10)
  const [bootLoading, setBootLoading] = useState(true)
  const [bootError, setBootError] = useState('')
  const [matching, setMatching] = useState(false)
  const [matchErrorKind, setMatchErrorKind] = useState('')
  const [matchError, setMatchError] = useState('')
  const [result, setResult] = useState(null)
  const [forceFallback, setForceFallback] = useState(null) // manual override

  const webgl = useMemo(() => isWebGLAvailable(), [])
  const reduced = useMemo(
    () => (typeof window !== 'undefined' ? prefersReducedMotion() : false),
    [],
  )
  const autoFallback = !webgl || reduced
  const useFallback = forceFallback !== null ? forceFallback : autoFallback

  const loadBase = useCallback(async () => {
    setBootLoading(true)
    setBootError('')
    try {
      const [r, s, l] = await Promise.all([
        api.foodbridgeRestaurants(),
        api.foodbridgeShelters(),
        api.foodbridgeSurplus(),
      ])
      setRestaurants(r.restaurants || [])
      setShelters(s.shelters || [])
      setLots(l.surplus || [])
      if ((l.surplus || []).length > 0) {
        const firstId = l.surplus[0].id
        setSurplusId((prev) => prev || firstId)
      }
    } catch (e) {
      setBootError(e.message || 'Failed to load FoodBridge data')
    } finally {
      setBootLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadBase()
  }, [loadBase])

  async function handleMatch() {
    setMatching(true)
    setMatchError('')
    setMatchErrorKind('')
    // Keep the previous result visible? No — clear so beams never show stale
    // allocations next to fresh HUD numbers.
    try {
      const res = await api.foodbridgeMatch({
        ...(surplusId ? { surplus_id: surplusId } : {}),
        requested_radius_km: Number(radius) || 10,
      })
      // HUD data is set immediately; the 3D replay animates after.
      setResult(res)
    } catch (e) {
      const { kind, message } = classifyMatchError(e)
      setMatchErrorKind(kind)
      setMatchError(message)
      setResult(null)
    } finally {
      setMatching(false)
    }
  }

  const restaurant = restaurants[0] || null
  const activeLot = lots.find((l) => l.id === surplusId) || lots[0] || null
  const replayNote = useMemo(() => {
    if (!result?.agent_events?.length) return ''
    return `Staged replay of ${result.agent_events.length} real events — backend returned them all at once on completion; order + timestamps preserved.`
  }, [result])

  return (
    <div>
      <header className="header">
        <div className="header-content">
          <div className="logo">🍲 FoodBridge <span>· 3D AI Demo · six-agent matching</span></div>
          <div className="health-bar">
            <a href="#/" className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '12px', textDecoration: 'none' }}>← Home (solve/chat)</a>
            <span className="badge badge-neutral">POST /api/foodbridge/match</span>
            {useFallback ? (
              <span className="badge badge-warning">2D fallback ({!webgl ? 'no WebGL' : 'reduced motion'})</span>
            ) : (
              <span className="badge badge-success">3D live</span>
            )}
          </div>
        </div>
      </header>

      <div className="container">
        <div className="card" style={{ background: 'linear-gradient(135deg, #ecfdf5 0%, #eff6ff 100%)', borderColor: '#a7f3d0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <strong>Green Leaf surplus → shelters A / B / C</strong>
              <div className="small" style={{ marginTop: '4px' }}>
                Orbit to explore · every beam, meal count and agent message comes from the live match response — nothing hard-coded.
                Scene spacing is illustrative; labels show actual km.
              </div>
            </div>
            <div className="flex gap-2" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
              <label className="small">
                Surplus lot{' '}
                <select
                  data-testid="fb-surplus-select"
                  value={surplusId}
                  onChange={(e) => setSurplusId(e.target.value)}
                  className="input"
                  style={{ width: '170px', padding: '6px' }}
                >
                  <option value="">(latest)</option>
                  {lots.map((l) => (
                    <option key={l.id} value={l.id}>{l.id} · {l.meal_count} meals</option>
                  ))}
                </select>
              </label>
              <label className="small">
                Radius (km){' '}
                <input
                  data-testid="fb-radius"
                  type="number"
                  min={1}
                  max={100}
                  value={radius}
                  onChange={(e) => setRadius(e.target.value)}
                  className="input"
                  style={{ width: '80px', padding: '6px' }}
                />
              </label>
              <button
                data-testid="fb-match-btn"
                onClick={handleMatch}
                disabled={matching || bootLoading}
                className="btn btn-primary"
              >
                {matching ? '⏳ Matching…' : '▶ Find Shelter Matches'}
              </button>
              <button
                data-testid="fb-view-toggle"
                className="btn btn-ghost"
                style={{ fontSize: '12px' }}
                onClick={() => setForceFallback(useFallback ? false : true)}
                title="Toggle between 3D scene and 2D fallback"
              >
                {useFallback ? 'Try 3D' : '2D view'}
              </button>
            </div>
          </div>
        </div>

        {bootError && (
          <div className="mt-3">
            <ErrorBanner error={bootError} onRetry={loadBase} onDismiss={() => setBootError('')} />
          </div>
        )}

        {bootLoading ? (
          <div className="card mt-3" style={{ textAlign: 'center' }}>
            <div className="loading-bar"><div className="loading-fill" /></div>
            <div className="small mt-2">Loading restaurants / shelters / surplus…</div>
          </div>
        ) : useFallback ? (
          <div className="mt-3" data-testid="fb-fallback-wrap">
            <FallbackView
              loading={matching}
              errorKind={matchErrorKind}
              errorMessage={matchError}
              result={result}
            />
          </div>
        ) : (
          <div className="mt-3">
            {(matchErrorKind || matchError) && (
              <div className="mb-3">
                <ErrorBanner error={`${matchErrorKind ? `[${matchErrorKind}] ` : ''}${matchError}`} onRetry={handleMatch} onDismiss={() => { setMatchError(''); setMatchErrorKind('') }} />
              </div>
            )}
            <div style={{ position: 'relative' }} data-testid="fb-scene-wrap">
              <Suspense fallback={<div className="card" style={{ textAlign: 'center' }}><div className="loading-bar"><div className="loading-fill" /></div><div className="small mt-2">Loading 3D engine…</div></div>}>
                <FoodbridgeScene
                  restaurant={restaurant}
                  shelters={shelters}
                surplusMeals={activeLot?.meal_count}
                allocation={result?.allocation || []}
                agentEvents={result?.agent_events || []}
                workflowStatus={result?.workflow_status}
                retryCount={result?.retry_count || 0}
                error={result?.error}
                initializing={matching}
                />
              </Suspense>
              {/* HUD renders instantly on response — never gated on replay */}
              <Hud loading={matching} result={result} replayNote={replayNote} />
            </div>
            {/* Text summary below scene for readability + tests */}
            {result?.summary && (
              <div className="card mt-3" data-testid="fb-page-summary">
                <div className="card-header">📝 AI summary (verbatim)</div>
                <div style={{ fontSize: '14px', lineHeight: 1.6 }}>{result.summary}</div>
                <div className="small mt-2">
                  workflow_status: <code data-testid="fb-page-status">{result.workflow_status}</code>
                  {' '}· retry_count: <code data-testid="fb-page-retry">{result.retry_count}</code>
                  {' '}· total: <code>{result.total_allocated}</code> · unallocated: <code>{result.unallocated}</code>
                </div>
              </div>
            )}
          </div>
        )}

        <footer style={{ marginTop: '24px', textAlign: 'center', color: 'var(--gray-400)', fontSize: '12px' }}>
          FoodBridge demo · data: <code>GET /api/foodbridge/restaurants|shelters|surplus</code> → <code>POST /api/foodbridge/match</code> ·
          events: <code>GET /api/foodbridge/agents/events?workflow_id=</code>
        </footer>
      </div>
    </div>
  )
}
