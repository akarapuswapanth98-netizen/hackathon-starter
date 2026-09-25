import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Home from './Home'

// Mock api client - keep contract
vi.mock('../services/api', () => ({
  default: {
    health: vi.fn().mockResolvedValue({ status: 'ok', llm_provider: 'mock', llm_model: 'test', rag_enabled: false, db_enabled: false }),
    solve: vi.fn().mockResolvedValue({ success: true, answer: 'mock answer', sources: [], metadata: {}, reasoning_steps: ['planner'] }),
    chat: vi.fn().mockResolvedValue({ reply: 'chat reply', provider: 'mock', model: 'm', sources: [] }),
    upload: vi.fn(),
  },
  api: {
    health: vi.fn(),
    solve: vi.fn(),
    chat: vi.fn(),
    upload: vi.fn(),
  }
}))

describe('Home - demo flow', () => {
  it('renders header and input area easy to modify', () => {
    render(<Home />)
    expect(screen.getByText(/Promptothon/)).toBeInTheDocument()
    expect(screen.getByText(/Problem \/ Query/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Solve \(Agentic\)/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Chat$/ })).toBeInTheDocument()
  })

  it('shows sample selector and keeps contract', () => {
    render(<Home />)
    expect(screen.getByDisplayValue(/Select a sample/)).toBeInTheDocument()
  })

  it('validates empty query shows error', async () => {
    render(<Home />)
    const btn = screen.getByText(/Solve \(Agentic\)/)
    fireEvent.click(btn)
    // ErrorBanner should appear
    expect(await screen.findByText(/Please enter a problem/)).toBeInTheDocument()
  })
})
