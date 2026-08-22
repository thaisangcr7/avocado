import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Conversation } from '@/api/types'
import { ConversationHeader } from './ConversationHeader'

const rename = vi.fn()

vi.mock('@/api/endpoints', () => ({
  conversationApi: {
    rename: (...args: unknown[]) => {
      rename(...args)
      return Promise.resolve({})
    },
  },
}))

const CONVERSATION = {
  id: 'c1',
  workspace_id: 'w1',
  user_id: null,
  task_id: null,
  title: 'Revenue by region',
  created_at: new Date().toISOString(),
} as Conversation

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ConversationHeader workspaceId="w1" conversation={CONVERSATION} modelLabel="Auto" />
    </QueryClientProvider>,
  )
}

describe('ConversationHeader', () => {
  beforeEach(() => rename.mockClear())

  it('shows the title and what is answering', () => {
    renderHeader()
    expect(screen.getByText('Revenue by region')).toBeInTheDocument()
    expect(screen.getByText('Auto')).toBeInTheDocument()
  })

  it('renames in place', async () => {
    renderHeader()
    await userEvent.click(screen.getByRole('button', { name: /revenue by region/i }))

    const field = screen.getByLabelText('Conversation title')
    await userEvent.clear(field)
    await userEvent.type(field, 'Q3 numbers{Enter}')

    await waitFor(() =>
      expect(rename).toHaveBeenCalledWith('w1', 'c1', 'Q3 numbers'),
    )
  })

  it('escape abandons the edit and restores the old title', async () => {
    renderHeader()
    await userEvent.click(screen.getByRole('button', { name: /revenue by region/i }))

    const field = screen.getByLabelText('Conversation title')
    await userEvent.clear(field)
    await userEvent.type(field, 'discarded{Escape}')

    expect(rename).not.toHaveBeenCalled()
    expect(screen.getByText('Revenue by region')).toBeInTheDocument()
  })

  it('an empty title is not saved', async () => {
    // Clearing the field and tabbing away should not leave a nameless thread.
    renderHeader()
    await userEvent.click(screen.getByRole('button', { name: /revenue by region/i }))
    await userEvent.clear(screen.getByLabelText('Conversation title'))
    await userEvent.tab()

    expect(rename).not.toHaveBeenCalled()
    expect(screen.getByText('Revenue by region')).toBeInTheDocument()
  })

  it('an unchanged title is not saved', async () => {
    // Opening the editor and clicking away is not an edit, and should not cost
    // a request or a rewritten timestamp.
    renderHeader()
    await userEvent.click(screen.getByRole('button', { name: /revenue by region/i }))
    await userEvent.tab()

    expect(rename).not.toHaveBeenCalled()
  })
})
