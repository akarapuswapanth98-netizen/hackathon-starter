/**
 * Centralized API client - DO NOT scatter fetch calls.
 * Handles baseURL, timeout, errors, JSON parsing.
 * Env: VITE_API_URL
 */
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TIMEOUT = 30000 // 30s per spec

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
      const msg = data.detail || data.error || data.message || `HTTP ${res.status}`
      throw new Error(msg)
    }
    return data
  } catch (err) {
    clearTimeout(t)
    if (err.name === 'AbortError') throw new Error(`Request timeout after ${timeout/1000}s - backend may be down`)
    throw err
  }
}

export const api = {
  health: () => request('/api/health'),
  chat: (payload) => request('/api/chat', { method: 'POST', body: payload }),
  solve: (payload) => request('/api/solve', { method: 'POST', body: payload }),
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
