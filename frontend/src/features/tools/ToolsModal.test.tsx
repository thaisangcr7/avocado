import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ToolSelection } from '@/api/types'
import { ToolsModal } from './ToolsModal'

const SELECTION: ToolSelection = {
  enabled_count: 1,
  context_cost_tokens: 420,
  tools: [
    {
      slug: 'data-explorer',
      name: 'Data explorer',
      description: 'Ask questions of a spreadsheet.',
      category: 'analytics',
      kind: 'builtin',
      context_cost_tokens: 420,
      enabled: true,
      connected: true,
    },
    {
      slug: 'issue-tracker',
      name: 'Issue tracker',
      description: 'Look up issues and sprints.',
      category: 'engineering',
      kind: 'placeholder',
      context_cost_tokens: 800,
      enabled: false,
      connected: false,
    },
  ],
}

const setEnabled = vi.fn()

vi.mock('@/api/endpoints', () => ({
  toolApi: {
    list: () => Promise.resolve(SELECTION),
    setEnabled: (...args: unknown[]) => {
      setEnabled(...args)
      return Promise.resolve(SELECTION)
    },
  },
  modelApi: {
    list: () =>
      Promise.resolve({
        models: [{ id: 'm', provider: 'p', display_name: 'M', context_window: 200_000 }],
      }),
  },
}))

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ToolsModal workspaceId="w" conversationId="c" onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('ToolsModal', () => {
  beforeEach(() => setEnabled.mockClear())

  it('lists tools with what each costs', async () => {
    renderModal()
    expect(await screen.findByText('Data explorer')).toBeInTheDocument()
    expect(screen.getByText(/420 tokens of context/)).toBeInTheDocument()
  })

  it('says a tool is not connected rather than hiding it', async () => {
    renderModal()
    expect(await screen.findByText('Issue tracker')).toBeInTheDocument()
    expect(screen.getByText(/not connected/i)).toBeInTheDocument()
  })

  it('will not let an unconnected tool be switched on', async () => {
    // It would put a tool in front of the model that reports success it never
    // had, so the control is disabled rather than failing on submit.
    renderModal()
    const toggle = await screen.findByRole('switch', { name: /enable issue tracker/i })
    expect(toggle).toBeDisabled()

    await userEvent.click(toggle)
    expect(setEnabled).not.toHaveBeenCalled()
  })

  it('toggles a connected tool', async () => {
    renderModal()
    const toggle = await screen.findByRole('switch', { name: /disable data explorer/i })
    await userEvent.click(toggle)
    await waitFor(() => expect(setEnabled).toHaveBeenCalledWith('w', 'c', []))
  })

  it('states that enabled tools spend context whether or not they are used', async () => {
    renderModal()
    expect(await screen.findByText(/spent whether or not they are used/i)).toBeInTheDocument()
  })

  it('filters by search', async () => {
    renderModal()
    await screen.findByText('Data explorer')
    await userEvent.type(screen.getByPlaceholderText(/search integrations/i), 'issue')

    expect(screen.queryByText('Data explorer')).not.toBeInTheDocument()
    expect(screen.getByText('Issue tracker')).toBeInTheDocument()
  })

  it('filters by category', async () => {
    renderModal()
    await screen.findByText('Data explorer')
    await userEvent.click(screen.getByRole('button', { name: 'Engineering' }))

    expect(screen.queryByText('Data explorer')).not.toBeInTheDocument()
    expect(screen.getByText('Issue tracker')).toBeInTheDocument()
  })
})
