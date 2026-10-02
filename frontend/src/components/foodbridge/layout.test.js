import { describe, it, expect } from 'vitest'
import { classifyMatchError, buildReplaySchedule } from './layout'

describe('classifyMatchError', () => {
  it('maps 409 already-allocated via structured code', () => {
    const err = new Error('Surplus lot food-001 has already been allocated (surplus_id=food-001)')
    err.status = 409
    err.code = 'SURPLUS_ALREADY_ALLOCATED'
    expect(classifyMatchError(err).kind).toBe('conflict_allocated')
  })
  it('maps 409 in-progress distinctly', () => {
    const err = new Error('Another match is already in progress for lot food-001')
    err.status = 409
    err.code = 'SURPLUS_IN_PROGRESS'
    expect(classifyMatchError(err).kind).toBe('conflict_in_progress')
  })
  it('keeps 404/422/timeout mapping', () => {
    expect(classifyMatchError(Object.assign(new Error('x'), { status: 404 })).kind).toBe('not_found')
    expect(classifyMatchError(Object.assign(new Error('x'), { status: 422 })).kind).toBe('unprocessable')
    expect(classifyMatchError(Object.assign(new Error('timeout'), { status: 'timeout' })).kind).toBe('timeout')
  })
})

describe('buildReplaySchedule live shape', () => {
  it('preserves order of the 7 real backend events', () => {
    const base = Date.parse('2026-09-26T12:01:22.808Z')
    const agents = ['coordinator', 'restaurant', 'shelter', 'matching', 'logistics', 'verification', 'coordinator']
    const events = agents.map((a, i) => ({
      workflow_id: 'w', agent: a, status: 'completed', detail: `${a} detail`,
      timestamp: new Date(base + [0, 3, 6, 9, 11, 12, 300][i]).toISOString(),
    }))
    const sched = buildReplaySchedule(events)
    expect(sched.map((s) => s.event.agent)).toEqual(agents)
    expect(sched.every((s) => s.delayMs >= 450 && s.delayMs <= 1800)).toBe(true)
  })
})
