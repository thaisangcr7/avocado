import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Message, ModelInfo } from '@/api/types'
import { ContextGauge, estimateContext } from './ContextGauge'

const MODEL: ModelInfo = {
  id: 'test-model',
  provider: 'test',
  display_name: 'Test',
  context_window: 100_000,
  max_output_tokens: 8192,
  input_cost_per_mtok: 1,
  output_cost_per_mtok: 1,
  supports_vision: false,
  tier: 'balanced',
}

function assistant(overrides: Partial<Message> = {}): Message {
  return {
    id: crypto.randomUUID(),
    conversation_id: 'c',
    role: 'assistant',
    content: 'answer',
    citations: [],
    failed: false,
    model_used: 'test-model',
    input_tokens: 10_000,
    output_tokens: 5_000,
    latency_ms: 100,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

function user(): Message {
  return {
    ...assistant(),
    role: 'user',
    model_used: null,
    input_tokens: null,
    output_tokens: null,
  }
}

describe('estimateContext', () => {
  it('counts the reply as well as the prompt', () => {
    // The next call carries both, so both are already spent.
    const estimate = estimateContext([assistant()], [MODEL])
    expect(estimate?.usedTokens).toBe(15_000)
    expect(estimate?.fractionLeft).toBeCloseTo(0.85)
  })

  it('reads the most recent turn, not the first', () => {
    const estimate = estimateContext(
      [assistant({ input_tokens: 1_000, output_tokens: 0 }), assistant({ input_tokens: 40_000 })],
      [MODEL],
    )
    expect(estimate?.usedTokens).toBe(45_000)
  })

  it('says nothing before anything has been sent', () => {
    // A user message alone carries no usage figures, so any number here would
    // be invented.
    expect(estimateContext([user()], [MODEL])).toBeNull()
    expect(estimateContext([], [MODEL])).toBeNull()
    expect(estimateContext(undefined, [MODEL])).toBeNull()
  })

  it('says nothing when the answering model is not in the catalogue', () => {
    const estimate = estimateContext([assistant({ model_used: 'retired-model' })], [MODEL])
    expect(estimate).toBeNull()
  })

  it('skips turns that never recorded usage', () => {
    const estimate = estimateContext(
      [assistant({ input_tokens: 20_000 }), assistant({ input_tokens: null })],
      [MODEL],
    )
    expect(estimate?.usedTokens).toBe(25_000)
  })

  it('never reports a negative remainder', () => {
    const estimate = estimateContext(
      [assistant({ input_tokens: 200_000, output_tokens: 50_000 })],
      [MODEL],
    )
    expect(estimate?.fractionLeft).toBe(0)
  })
})

describe('ContextGauge', () => {
  it('renders the remaining percentage', () => {
    render(<ContextGauge messages={[assistant()]} models={[MODEL]} />)
    expect(screen.getByText(/85/)).toBeInTheDocument()
    expect(screen.getByText(/left/i)).toBeInTheDocument()
  })

  it('renders nothing at all when there is nothing to say', () => {
    const { container } = render(<ContextGauge messages={[user()]} models={[MODEL]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the exact figures on hover rather than only a percentage', () => {
    render(<ContextGauge messages={[assistant()]} models={[MODEL]} />)
    expect(screen.getByTitle('15,000 of 100,000 tokens used')).toBeInTheDocument()
  })
})
