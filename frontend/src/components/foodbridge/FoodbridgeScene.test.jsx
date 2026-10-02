import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'

// Mock R3F + drei so jsdom (no WebGL) can mount the scene without crashing.
// Focus: data wiring, not pixels.
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }) => <div data-testid="mock-canvas">{children}</div>,
  useFrame: () => {},
}))

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  Html: ({ children }) => <div>{children}</div>,
}))

import FoodbridgeScene from './FoodbridgeScene'

const RESTAURANT = { id: 'rest-001', name: 'Green Leaf Restaurant', lat: 17.42, lon: 78.48 }
const SHELTERS = [
  { id: 'shelter-a', name: 'Shelter A', lat: 17.439, lon: 78.48 },
  { id: 'shelter-b', name: 'Shelter B', lat: 17.3775, lon: 78.48 },
  { id: 'shelter-c', name: 'Shelter C', lat: 17.42, lon: 78.5101 },
]

function evt(agent, detail, iso) {
  return { workflow_id: 'wf-1', agent, status: 'completed', detail, timestamp: iso }
}

const EVENTS = [
  evt('coordinator', 'workflow started', '2026-09-26T10:00:00.000Z'),
  evt('restaurant', 'offers 80 meals', '2026-09-26T10:00:00.300Z'),
  evt('shelter', '3 candidates', '2026-09-26T10:00:00.600Z'),
  evt('matching', 'allocated 80/80', '2026-09-26T10:00:01.000Z'),
  evt('logistics', '2 stops', '2026-09-26T10:00:01.200Z'),
  evt('verification', 'passed', '2026-09-26T10:00:01.500Z'),
]

const ALLOCATION = [
  { shelter_id: 'shelter-a', shelter_name: 'Shelter A', meals: 50, distance_km: 2.1, score: 0.9, breakdown: {} },
  { shelter_id: 'shelter-c', shelter_name: 'Shelter C', meals: 30, distance_km: 3.2, score: 0.8, breakdown: {} },
]

describe('FoodbridgeScene mount/unmount (data wiring, not pixels)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('mounts with restaurant + shelters and unmounts cleanly', () => {
    const { unmount } = render(
      <FoodbridgeScene restaurant={RESTAURANT} shelters={SHELTERS} surplusMeals={80} />,
    )
    expect(screen.getByTestId('foodbridge-scene')).toBeInTheDocument()
    expect(screen.getByTestId('mock-canvas')).toBeInTheDocument()
    expect(screen.getByTestId('scene-restaurant')).toHaveTextContent('Green Leaf Restaurant')
    expect(screen.getByTestId('scene-restaurant')).toHaveTextContent('80 meals')
    expect(screen.getByTestId('scene-shelter-shelter-a')).toHaveTextContent('Shelter A')
    expect(screen.getByTestId('scene-shelter-shelter-b')).toBeInTheDocument()
    expect(screen.getByTestId('scene-shelter-shelter-c')).toBeInTheDocument()
    unmount()
  })

  it('shows initializing state while the match POST is in flight (no faked data)', () => {
    render(
      <FoodbridgeScene restaurant={RESTAURANT} shelters={SHELTERS} surplusMeals={80} initializing />,
    )
    expect(screen.getByTestId('scene-initializing')).toHaveTextContent(/Workflow initializing/)
  })

  it('replays agent labels from real events and labels actual km', () => {
    render(
      <FoodbridgeScene
        restaurant={RESTAURANT}
        shelters={SHELTERS}
        surplusMeals={80}
        allocation={ALLOCATION}
        agentEvents={EVENTS}
        workflowStatus="completed"
        retryCount={0}
        animate={false}
      />,
    )
    // animate=false reveals all instantly (reduced-motion path)
    expect(screen.getByTestId('agent-label-matching')).toBeInTheDocument()
    expect(screen.getByTestId('agent-label-verification')).toBeInTheDocument()
    // allocation-driven shelter labels show real meals + real km
    expect(screen.getByTestId('scene-shelter-shelter-a')).toHaveTextContent('+50 meals')
    expect(screen.getByTestId('scene-shelter-shelter-a')).toHaveTextContent('2.1 km (actual)')
    expect(screen.getByTestId('scene-replay-note')).toHaveTextContent(/real events/)
  })

  it('shows failure marker and retry cue without crashing', () => {
    render(
      <FoodbridgeScene
        restaurant={RESTAURANT}
        shelters={SHELTERS}
        surplusMeals={80}
        allocation={[]}
        agentEvents={EVENTS}
        workflowStatus="failed"
        retryCount={2}
        error={{ code: 'VERIFICATION_FAILED', message: 'rejected' }}
        animate={false}
      />,
    )
    expect(screen.getByTestId('scene-failed')).toHaveTextContent(/Workflow failed/)
    expect(screen.getByTestId('agent-label-verification')).toHaveTextContent(/↻×2/)
  })

  it('shows empty-allocation state', () => {
    render(
      <FoodbridgeScene
        restaurant={RESTAURANT}
        shelters={SHELTERS}
        surplusMeals={80}
        allocation={[]}
        agentEvents={EVENTS}
        workflowStatus="completed"
        retryCount={0}
        animate={false}
      />,
    )
    expect(screen.getByTestId('scene-empty')).toHaveTextContent(/No matches found/)
  })

  it('cleans up replay timers on unmount', () => {
    const { unmount } = render(
      <FoodbridgeScene
        restaurant={RESTAURANT}
        shelters={SHELTERS}
        surplusMeals={80}
        allocation={ALLOCATION}
        agentEvents={EVENTS}
        workflowStatus="completed"
      />,
    )
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(() => unmount()).not.toThrow()
  })
})
