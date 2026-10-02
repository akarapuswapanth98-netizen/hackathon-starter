/**
 * Pure FoodBridge scene helpers — no three.js imports so they stay
 * unit-testable in jsdom. Every visual must derive from the live API
 * response; nothing here hard-codes shelter outcomes.
 */

export const AGENT_ORDER = [
  'coordinator',
  'restaurant',
  'shelter',
  'matching',
  'logistics',
  'verification',
]

export const AGENT_COLORS = {
  coordinator: '#2563eb',
  restaurant: '#059669',
  shelter: '#d97706',
  matching: '#7c3aed',
  logistics: '#0891b2',
  verification: '#dc2626',
}

export function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180
  const R = 6371
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

/**
 * Lay out shelters on a ground plane around the restaurant at origin.
 * Visual radius is illustrative (scaled arbitrarily); the label distance is
 * always the REAL distance_km from the allocation response when present,
 * else haversine computed from lat/lon. Never invent allocation quantities.
 */
export function layoutShelters({ restaurant, shelters = [], allocation = [] }) {
  const allocById = new Map((allocation || []).map((a) => [a.shelter_id, a]))
  const n = Math.max(shelters.length, 1)
  return shelters.map((s, i) => {
    const alloc = allocById.get(s.id)
    let realKm = null
    if (alloc && Number.isFinite(Number(alloc.distance_km))) {
      realKm = Number(alloc.distance_km)
    } else if (
      restaurant &&
      Number.isFinite(restaurant.lat) &&
      Number.isFinite(s.lat)
    ) {
      realKm = haversineKm(restaurant.lat, restaurant.lon, s.lat, s.lon)
    }
    // Illustrative visual spacing: spread evenly + scale modestly by real km.
    const angle = (i / n) * Math.PI * 2 + Math.PI / 6
    const visualRadius = 5 + Math.min(realKm ?? 3, 10) * 0.55
    return {
      shelter: s,
      allocation: alloc || null,
      realKm,
      position: [Math.cos(angle) * visualRadius, 0, Math.sin(angle) * visualRadius],
      angle,
    }
  })
}

/**
 * Agent positions: elevated arc above the scene, fixed order.
 */
export function layoutAgents() {
  return AGENT_ORDER.map((name, i) => {
    const t = AGENT_ORDER.length === 1 ? 0.5 : i / (AGENT_ORDER.length - 1)
    return {
      name,
      color: AGENT_COLORS[name] || '#4b5563',
      position: [-7.5 + t * 15, 3.4, -4.5],
    }
  })
}

/**
 * Build a staged replay schedule from REAL agent_events.
 * Preserves the backend's actual order; per-step delays are proportional to
 * the real timestamp deltas (clamped so the demo stays watchable). The
 * backend returns all events at once on completion — this is a replay, not
 * fake live progress.
 *
 * Returns [{ event, delayMs }] where delayMs is time to wait BEFORE showing
 * that step.
 */
export function buildReplaySchedule(agentEvents = [], { minStep = 450, maxStep = 1800 } = {}) {
  const events = [...(agentEvents || [])].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp),
  )
  if (events.length === 0) return []
  const first = new Date(events[0].timestamp).getTime()
  const last = new Date(events[events.length - 1].timestamp).getTime()
  const span = last - first
  return events.map((event, i) => {
    let delayMs
    if (i === 0) {
      delayMs = minStep
    } else {
      const prev = new Date(events[i - 1].timestamp).getTime()
      const cur = new Date(event.timestamp).getTime()
      const raw = cur - prev
      if (!Number.isFinite(raw) || span <= 0) {
        delayMs = minStep + 250
      } else {
        // Preserve relative spacing, scaled into [minStep, maxStep].
        const ratio = span > 0 ? raw / span : 0
        delayMs = Math.round(minStep + ratio * (maxStep - minStep))
        delayMs = Math.max(minStep, Math.min(maxStep, delayMs))
      }
    }
    return { event, delayMs }
  })
}

/** Total backend workflow span in ms, from real event timestamps. */
export function workflowSpanMs(agentEvents = []) {
  if (!agentEvents || agentEvents.length < 2) return 0
  const ts = agentEvents.map((e) => new Date(e.timestamp).getTime()).filter(Number.isFinite)
  if (ts.length < 2) return 0
  return Math.max(...ts) - Math.min(...ts)
}

/** Classify a thrown API error into UI edge states without guessing. */
export function classifyMatchError(err) {
  const msg = err?.message || 'Request failed'
  const status = err?.status ?? err?.code
  const code = typeof err?.code === 'string' ? err.code : ''
  if (status === 'timeout' || status === 408 || /timeout/i.test(msg)) {
    return { kind: 'timeout', message: msg }
  }
  // 409 lot lifecycle: re-match on a consumed lot, or a match already running.
  // err.code carries the structured backend code (SURPLUS_ALREADY_ALLOCATED /
  // SURPLUS_IN_PROGRESS); fall back to message sniffing for robustness.
  if (status === 409 || /ALREADY_ALLOCATED|IN_PROGRESS|already been allocated|already in progress/i.test(code + ' ' + msg)) {
    const kind = /IN_PROGRESS|already in progress/i.test(code + ' ' + msg) ? 'conflict_in_progress' : 'conflict_allocated'
    return { kind, message: msg }
  }
  if (status === 404 || /not found|surplus_id=/i.test(msg)) {
    return { kind: 'not_found', message: msg }
  }
  if (status === 422 || /malformed|validation|unprocessable/i.test(msg)) {
    return { kind: 'unprocessable', message: msg }
  }
  return { kind: 'failure', message: msg }
}
