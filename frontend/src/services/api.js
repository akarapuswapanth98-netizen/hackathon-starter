/**
 * Centralized API client - DO NOT scatter fetch calls.
 * Handles baseURL, timeout, errors, JSON parsing.
 * Env: VITE_API_URL
 */
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TIMEOUT = 30000 // 30s per spec

/** Normalize the backend's varying error shapes into {message, code}. */
export function parseErrorBody(data, status) {
  const d = data || {}
  // Structured object error (e.g. 409 {error: {code, message, surplus_id}})
  if (d.error && typeof d.error === 'object') {
    const bits = [d.error.message || d.error.code || 'Request failed']
    if (d.error.surplus_id) bits.push(`(surplus_id=${d.error.surplus_id})`)
    return { message: bits.join(' '), code: d.error.code || status }
  }
  if (typeof d.error === 'string') return { message: d.detail && typeof d.detail === 'string' ? `${d.error} — ${d.detail}` : d.error, code: status }
  // FastAPI validation array: {detail: [{loc, msg}]}
  if (Array.isArray(d.detail)) {
    const issues = d.detail.map((i) => {
      const loc = Array.isArray(i.loc) ? i.loc.filter((p) => p !== 'body').join('.') : ''
      return loc ? `${loc}: ${i.msg}` : (i.msg || 'invalid')
    })
    return { message: `Validation failed — ${issues.join('; ') || 'malformed request'}`, code: status }
  }
  if (typeof d.detail === 'string') return { message: d.detail, code: status }
  if (typeof d.message === 'string') return { message: d.message, code: status }
  return { message: `HTTP ${status}`, code: status }
}

async function request(path, { method = 'GET', body, headers = {}, timeout = TIMEOUT } = {}) {
  const controller = new AbortController()
  const t = setTimeout(() => controller.abort(), timeout)

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...headers },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    clearTimeout(t)
    const text = await res.text()
    let data
    try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }

    if (!res.ok) {
      // Error bodies vary by endpoint: AppError -> {error: str, detail: str},
      // 409 lot-conflict -> {error: {code, message, surplus_id}},
      // FastAPI validation -> {detail: [{loc, msg, ...}]}.
      // Always surface a readable string, never "[object Object]".
      const { message: msg, code: bodyCode } = parseErrorBody(data, res.status)
      const err = new Error(msg)
      // Preserve HTTP status + structured code for UI edge-state handling
      // (404 / 422 / 409 ...) without changing the message contract.
      err.status = res.status
      err.code = bodyCode || res.status
      err.data = data
      throw err
    }
    return data
  } catch (err) {
    clearTimeout(t)
    if (err.name === 'AbortError') {
      const timeoutErr = new Error(`Request timeout after ${timeout/1000}s - backend may be down`)
      timeoutErr.status = 'timeout'
      timeoutErr.code = 'timeout'
      throw timeoutErr
    }
    throw err
  }
}

export const api = {
  health: () => request('/api/health'),
  chat: (payload) => request('/api/chat', { method: 'POST', body: payload }),
  solve: (payload) => request('/api/solve', { method: 'POST', body: payload }),
  // --- FoodBridge (reuses BASE_URL / timeout / error handling above) ---
  foodbridgeRestaurants: () => request('/api/foodbridge/restaurants'),
  foodbridgeShelters: () => request('/api/foodbridge/shelters'),
  foodbridgeSurplus: (restaurant_id) =>
    request(restaurant_id ? `/api/foodbridge/surplus?restaurant_id=${encodeURIComponent(restaurant_id)}` : '/api/foodbridge/surplus'),
  foodbridgeCreateSurplus: (payload) => request('/api/foodbridge/surplus', { method: 'POST', body: payload }),
  foodbridgeMatch: (payload) => request('/api/foodbridge/match', { method: 'POST', body: payload }),
  foodbridgeEvents: (workflow_id) =>
    request(workflow_id ? `/api/foodbridge/agents/events?workflow_id=${encodeURIComponent(workflow_id)}` : '/api/foodbridge/agents/events'),
  upload: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const controller = new AbortController()
    const t = setTimeout(() => controller.abort(), TIMEOUT)
    try {
      const res = await fetch(`${BASE_URL}/api/upload`, { method: 'POST', body: form, signal: controller.signal })
      clearTimeout(t)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || 'Upload failed')
      return data
    } catch (e) {
      clearTimeout(t)
      if (e.name === 'AbortError') throw new Error('Upload timeout')
      throw e
    }
  },
}

export default api
