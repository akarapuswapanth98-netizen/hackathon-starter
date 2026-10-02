import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import FoodBridge from './FoodBridge'

const SUCCESS_RESULT = {
  success: true,
  workflow_id: 'wf-1',
  workflow_status: 'completed',
  allocation: [
    { shelter_id: 'shelter-a', shelter_name: 'Shelter A', meals: 50, distance_km: 2.1, score: 0.92, breakdown: {} },
    { shelter_id: 'shelter-c', shelter_name: 'Shelter C', meals: 30, distance_km: 3.2, score: 0.85, breakdown: {} },
  ],
  agent_events: [
    { workflow_id: 'wf-1', agent: 'coordinator', status: 'running', detail: 'workflow started', timestamp: '2026-09-26T10:00:00.000Z' },
    { workflow_id: 'wf-1', agent: 'matching', status: 'completed', detail: 'allocated 80/80 meals', timestamp: '2026-09-26T10:00:01.000Z' },
    { workflow_id: 'wf-1', agent: 'verification', status: 'completed', detail: 'passed', timestamp: '2026-09-26T10:00:02.000Z' },
  ],
  total_allocated: 80,
  unallocated: 0,
  summary: 'Allocated 80 meals to 2 shelters.',
  summary_source: 'deterministic',
  retry_count: 0,
  metadata: {},
  error: null,
}

vi.mock('../services/api', () => ({
  default: {
    foodbridgeRestaurants: vi.fn(),
    foodbridgeShelters: vi.fn(),
    foodbridgeSurplus: vi.fn(),
    foodbridgeMatch: vi.fn(),
  },
}))

import api from '../services/api'

describe('FoodBridge page integration (fallback path in jsdom)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.foodbridgeRestaurants.mockResolvedValue({
      restaurants: [{ id: 'rest-001', name: 'Green Leaf Restaurant', lat: 17.42, lon: 78.48 }],
    })
    api.foodbridgeShelters.mockResolvedValue({
      shelters: [
        { id: 'shelter-a', name: 'Shelter A', lat: 17.439, lon: 78.48 },
        { id: 'shelter-b', name: 'Shelter B', lat: 17.3775, lon: 78.48 },
      ],
    })
    api.foodbridgeSurplus.mockResolvedValue({
      surplus: [{ id: 'food-001', restaurant_id: 'rest-001', meal_count: 80 }],
    })
  })

  it('loads base data and runs match, showing real HUD data immediately', async () => {
    api.foodbridgeMatch.mockResolvedValue(SUCCESS_RESULT)
    render(<FoodBridge />)
    // wait for bootstrap
    await waitFor(() => expect(api.foodbridgeSurplus).toHaveBeenCalled())
    const btn = await screen.findByTestId('fb-match-btn')
    fireEvent.click(btn)
    await waitFor(() => expect(api.foodbridgeMatch).toHaveBeenCalled())
    // jsdom has no WebGL -> auto fallback renders the same real data
    await waitFor(() => expect(screen.getByTestId('fb-result')).toBeInTheDocument())
    expect(screen.getByTestId('fb-total')).toHaveTextContent('Total allocated: 80')
    expect(screen.getByTestId('fb-status')).toHaveTextContent('workflow_status: completed')
    expect(screen.getByTestId('fb-summary')).toHaveTextContent('Allocated 80 meals')
  })

  it('surfaces 404 edge state without crashing', async () => {
    const err = new Error('surplus_id=food-nope')
    err.status = 404
    api.foodbridgeMatch.mockRejectedValue(err)
    render(<FoodBridge />)
    await waitFor(() => expect(api.foodbridgeSurplus).toHaveBeenCalled())
    fireEvent.click(await screen.findByTestId('fb-match-btn'))
    await waitFor(() => expect(screen.getByTestId('fb-error-not_found')).toBeInTheDocument())
  })
})
