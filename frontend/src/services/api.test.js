import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from './api'

// Mock fetch globally
global.fetch = vi.fn()

describe('api client - central contract', () => {
  beforeEach(() => vi.resetAllMocks())

  it('health calls GET /api/health', async () => {
    fetch.mockResolvedValue({ ok: true, text: async () => JSON.stringify({ status: 'ok', llm_provider: 'mock' }) })
    const res = await api.health()
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/health'), expect.any(Object))
    expect(res.status).toBe('ok')
  })

  it('solve sends query/context per contract and parses success', async () => {
    const mock = { success: true, answer: 'hello', sources: [], metadata: {}, confidence: null, reasoning_steps: [] }
    fetch.mockResolvedValue({ ok: true, text: async () => JSON.stringify(mock) })
    const res = await api.solve({ query: 'test', context: 'ctx', use_rag: false, use_agents: true })
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.query).toBe('test')
    expect(body.context).toBe('ctx')
    expect(res.success).toBe(true)
    expect(res.confidence).toBe(null)
  })

  it('handles timeout error', async () => {
    fetch.mockImplementation(() => new Promise((_, rej) => {
      const e = new Error('AbortError'); e.name = 'AbortError'; setTimeout(()=>rej(e), 5)
    }))
    // Use very short timeout
    const { default: apiMod } = await import('./api.js')
    // api module uses global fetch, timeout handled via AbortController - we test error mapping
    await expect(api.health()).rejects.toThrow()
  }, 10000)

  it('upload uses FormData to /api/upload', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ filename: 'a.txt', saved_as: 'x.txt' }) })
    const file = new File(['hi'], 'a.txt', { type: 'text/plain' })
    const res = await api.upload(file)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/upload'), expect.objectContaining({ method: 'POST' }))
    expect(res.filename).toBe('a.txt')
  })

  it('throws on HTTP error with detail', async () => {
    fetch.mockResolvedValue({ ok: false, text: async () => JSON.stringify({ detail: 'RAG disabled' }) })
    await expect(api.chat({ message: 'hi', use_rag: true })).rejects.toThrow('RAG disabled')
  })

  it('parses 409 object error into readable message + structured code', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({ success: false, error: { code: 'SURPLUS_ALREADY_ALLOCATED', message: 'Surplus lot food-001 has already been allocated', surplus_id: 'food-001' } }),
    })
    const err = await api.foodbridgeMatch({ surplus_id: 'food-001' }).catch((e) => e)
    expect(err.message).toContain('has already been allocated')
    expect(err.message).toContain('food-001')
    expect(err.message).not.toContain('[object Object]')
    expect(err.status).toBe(409)
    expect(err.code).toBe('SURPLUS_ALREADY_ALLOCATED')
  })

  it('parses FastAPI 422 array detail into readable message', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({ detail: [{ type: 'greater_than', loc: ['body', 'requested_radius_km'], msg: 'Input should be greater than 0' }] }),
    })
    const err = await api.foodbridgeMatch({ requested_radius_km: -5 }).catch((e) => e)
    expect(err.message).toContain('requested_radius_km')
    expect(err.status).toBe(422)
  })
})
