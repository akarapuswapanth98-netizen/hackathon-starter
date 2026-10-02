import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ResponseArea from './ResponseArea'

describe('ResponseArea', () => {
  it('shows placeholder when no answer', () => {
    render(<ResponseArea answer="" loading={false} />)
    expect(screen.getByText(/No result yet/)).toBeInTheDocument()
  })
  it('shows loading state', () => {
    render(<ResponseArea loading={true} answer="" />)
    expect(screen.getByText(/AI thinking/)).toBeInTheDocument()
  })
  it('renders answer and demo banner for mock', () => {
    render(<ResponseArea answer="[MOCK gpt] hello" steps={['planner']} meta={{}} loading={false} />)
    expect(screen.getByText(/Demo Mode/)).toBeInTheDocument()
    expect(screen.getByText(/hello/)).toBeInTheDocument()
    expect(screen.getByText(/Agent steps/)).toBeInTheDocument()
  })
  it('renders real answer without demo banner', () => {
    render(<ResponseArea answer="Real answer" steps={[]} loading={false} />)
    expect(screen.queryByText(/Demo Mode/)).not.toBeInTheDocument()
    expect(screen.getByText(/Real answer/)).toBeInTheDocument()
  })
})
