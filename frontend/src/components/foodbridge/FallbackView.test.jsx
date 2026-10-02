import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FallbackView from './FallbackView'

function evt(agent, detail, iso, status = 'completed') {
  return { workflow_id: 'wf-1', agent, status, detail, timestamp: iso }
}

const BASE_EVENTS = [
  evt('coordinator', 'workflow started', '2026-09-26T10:00:00.000Z', 'running'),
  evt('restaurant', 'Green Leaf Restaurant offers 80 cooked_meals (vegetarian), expires in 5.0h', '2026-09-26T10:00:00.400Z'),
  evt('shelter', '3 candidate shelter(s) within 10.0 km (dropped: 0 out-of-radius, 0 incompatible, 0 unusable)', '2026-09-26T10:00:00.900Z'),
  evt('matching', 'scored 3 shelter(s); allocated 80/80 meals to 2 shelter(s); 0 unallocated', '2026-09-26T10:00:01.500Z'),
  evt('logistics', '2 delivery stop(s), ~5.3 km total', '2026-09-26T10:00:01.800Z'),
  evt('verification', 'passed: 2 allocation(s), 80/80 meals within all constraints', '2026-09-26T10:00:02.100Z'),
  evt('coordinator', 'match completed: 80 meals allocated, 0 unallocated', '2026-09-26T10:00:02.400Z'),
]

export const SUCCESS_RESULT = {
  success: true,
  workflow_id: 'wf-1',
  workflow_status: 'completed',
  allocation: [
    { shelter_id: 'shelter-a', shelter_name: 'Shelter A - Govt. Higher Secondary School', meals: 50, distance_km: 2.1, score: 0.92, breakdown: {} },
    { shelter_id: 'shelter-c', shelter_name: 'Shelter C - Night Shelter Trust', meals: 30, distance_km: 3.2, score: 0.85, breakdown: {} },
  ],
  agent_events: BASE_EVENTS,
  total_allocated: 80,
  unallocated: 0,
  summary: 'Allocated 80 meals to 2 shelters. Van route ~5.3 km.',
  summary_source: 'deterministic',
  retry_count: 0,
  metadata: {},
  error: null,
}

describe('FallbackView', () => {
  it('renders successful match with totals, status, retry and verbatim summary', () => {
    render(<FallbackView result={SUCCESS_RESULT} />)
    expect(screen.getByTestId('fb-result')).toBeInTheDocument()
    expect(screen.getByTestId('fb-total')).toHaveTextContent('Total allocated: 80')
    expect(screen.getByTestId('fb-unallocated')).toHaveTextContent('Unallocated: 0')
    expect(screen.getByTestId('fb-status')).toHaveTextContent('workflow_status: completed')
    expect(screen.getByTestId('fb-retry')).toHaveTextContent('retry_count: 0')
    expect(screen.getByTestId('fb-summary')).toHaveTextContent('Allocated 80 meals to 2 shelters. Van route ~5.3 km.')
    // allocations driven by response, not hard-coded
    expect(screen.getByTestId('fb-alloc-shelter-a')).toHaveTextContent('50 meals')
    expect(screen.getByTestId('fb-alloc-shelter-c')).toHaveTextContent('30 meals')
    // timeline shows real agent messages verbatim
    expect(screen.getByTestId('fb-event-matching')).toHaveTextContent('allocated 80/80 meals')
    expect(screen.getByTestId('fb-event-verification')).toHaveTextContent('passed: 2 allocation(s)')
  })

  it('renders loading state', () => {
    render(<FallbackView loading />)
    expect(screen.getByTestId('fb-loading')).toHaveTextContent(/Matching shelters/)
  })

  it('renders generic API failure', () => {
    render(<FallbackView errorKind="failure" errorMessage="Backend may be down" />)
    expect(screen.getByTestId('fb-error-failure')).toHaveTextContent('Backend may be down')
  })

  it('renders timeout state', () => {
    render(<FallbackView errorKind="timeout" errorMessage="Request timeout after 30s - backend may be down" />)
    const el = screen.getByTestId('fb-error-timeout')
    expect(el).toHaveTextContent(/timed out/i)
    expect(el).toHaveTextContent('Request timeout after 30s')
  })

  it('renders 404 unknown surplus_id', () => {
    render(<FallbackView errorKind="not_found" errorMessage="surplus_id=food-nope" />)
    const el = screen.getByTestId('fb-error-not_found')
    expect(el).toHaveTextContent(/404/)
    expect(el).toHaveTextContent('surplus_id=food-nope')
  })

  it('renders 422 malformed request', () => {
    render(<FallbackView errorKind="unprocessable" errorMessage="requested_radius_km validation failed" />)
    const el = screen.getByTestId('fb-error-unprocessable')
    expect(el).toHaveTextContent(/422/)
    expect(el).toHaveTextContent('validation failed')
  })

  it('renders failed workflow with no silent empty scene', () => {
    const failed = {
      ...SUCCESS_RESULT,
      success: false,
      workflow_status: 'failed',
      allocation: [],
      total_allocated: 0,
      unallocated: 80,
      error: { code: 'VERIFICATION_FAILED', message: 'Allocation rejected by verification (1 issue(s))', details: [] },
    }
    render(<FallbackView result={failed} />)
    const el = screen.getByTestId('fb-failed')
    expect(el).toHaveTextContent(/Workflow failed/)
    expect(el).toHaveTextContent('VERIFICATION_FAILED')
    expect(screen.getByTestId('fb-status')).toHaveTextContent('workflow_status: failed')
  })

  it('renders empty allocation as no-matches-found', () => {
    const empty = { ...SUCCESS_RESULT, allocation: [], total_allocated: 0, unallocated: 80 }
    render(<FallbackView result={empty} />)
    expect(screen.getByTestId('fb-empty')).toHaveTextContent(/No matches found/)
    expect(screen.queryByTestId('fb-alloc-shelter-a')).not.toBeInTheDocument()
  })

  it('visibly indicates retry_count > 0', () => {
    const retried = { ...SUCCESS_RESULT, retry_count: 2 }
    render(<FallbackView result={retried} />)
    expect(screen.getByTestId('fb-retry')).toHaveTextContent('retry_count: 2')
    expect(screen.getByTestId('fb-retried')).toHaveTextContent(/Retry occurred/)
    expect(screen.getByTestId('fb-retry-note')).toHaveTextContent('retry_count=2')
  })

  it('renders 409 already-allocated with fresh-lot guidance', () => {
    render(<FallbackView errorKind="conflict_allocated" errorMessage="Surplus lot food-001 has already been allocated (surplus_id=food-001)" />)
    const el = screen.getByTestId('fb-error-conflict_allocated')
    expect(el).toHaveTextContent(/already allocated/)
    expect(el).toHaveTextContent(/fresh lot/)
  })

  it('renders 409 in-progress distinctly', () => {
    render(<FallbackView errorKind="conflict_in_progress" errorMessage="Another match is already in progress for lot food-001" />)
    const el = screen.getByTestId('fb-error-conflict_in_progress')
    expect(el).toHaveTextContent(/already in progress/i)
  })
})
