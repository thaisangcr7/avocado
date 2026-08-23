import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Conversation, ConversationPage } from '@/api/types'
import { HistoryPage } from './HistoryPage'

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1',
    workspace_id: 'w',
    user_id: 'u',
    task_id: null,
    title: 'Quarterly revenue',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-20T00:00:00Z',
    pinned: false,
    archived: false,
    message_count: 4,
    ...overrides,
  }
}

const listed = vi.fn()
const setFlags = vi.fn()
const renamed = vi.fn()

function page(rows: Conversation[], total = rows.length): ConversationPage {
  return { conversations: rows, total, limit: 20, offset: 0 }
}

let RESULT: ConversationPage = page([
  conversation(),
  conversation({ id: 'c2', title: 'Hiring plan', pinned: true, message_count: 1 }),
])

vi.mock('@/api/endpoints', () => ({
  historyApi: {
    list: (_workspaceId: string, params: unknown) => {
      listed(params)
      return Promise.resolve(RESULT)
    },
    setFlags: (_w: string, id: string, flags: unknown) => {
      setFlags(id, flags)
      return Promise.resolve(conversation({ id }))
    },
    exportMarkdown: () => Promise.resolve(new Blob(['# x'])),
    rate: () => Promise.resolve({ message: 'ok' }),
  },
  conversationApi: {
    rename: (_w: string, id: string, title: string) => {
      renamed(id, title)
      return Promise.resolve(conversation({ id, title }))
    },
    remove: () => Promise.resolve(),
  },
}))

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <HistoryPage workspaceId="w" onOpen={() => {}} />
    </QueryClientProvider>,
  )
}

describe('HistoryPage', () => {
  beforeEach(() => {
    listed.mockClear()
    setFlags.mockClear()
    renamed.mockClear()
    RESULT = page([
      conversation(),
      conversation({ id: 'c2', title: 'Hiring plan', pinned: true, message_count: 1 }),
    ])
  })

  it('shows a message count per row', async () => {
    renderPage()
    expect(await screen.findByText(/4 messages/)).toBeInTheDocument()
    // Singular, because "1 messages" is the kind of thing people notice.
    expect(screen.getByText(/1 message ·/)).toBeInTheDocument()
  })

  it('marks a pinned conversation', async () => {
    renderPage()
    await screen.findByText('Hiring plan')

    expect(screen.getByText('pinned')).toBeInTheDocument()
  })

  it('shows no status chip on an ordinary conversation', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    // Every chat is "completed" the moment it stops, so that chip would be
    // decoration on every row.
    expect(screen.queryByText(/completed/i)).not.toBeInTheDocument()
  })

  it('asks the server to search rather than filtering in the browser', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    await userEvent.type(screen.getByLabelText(/search history/i), 'revenue')

    // Paging exists, so the browser only ever holds one page — filtering here
    // would hide matches that are on another.
    await waitFor(() =>
      expect(listed).toHaveBeenCalledWith(expect.objectContaining({ search: 'revenue' })),
    )
  })

  it('goes back to the first page when the filter changes', async () => {
    RESULT = page([conversation()], 100)
    renderPage()
    await screen.findByText('Quarterly revenue')
    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(listed).toHaveBeenCalledWith(expect.objectContaining({ offset: 20 })))

    await userEvent.click(screen.getByRole('button', { name: /^pinned$/i }))

    // Otherwise a filter applied from page three shows an empty page three.
    await waitFor(() =>
      expect(listed).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, which: 'pinned' }),
      ),
    )
  })

  it('pins a conversation without touching whether it is archived', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    const [pin] = screen.getAllByRole('button', { name: /^pin$/i })
    await userEvent.click(pin!)

    await waitFor(() => expect(setFlags).toHaveBeenCalledWith('c1', { pinned: true }))
  })

  it('renames a conversation inline', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    const [rename] = screen.getAllByRole('button', { name: /^rename$/i })
    await userEvent.click(rename!)
    const field = screen.getByLabelText(/conversation title/i)
    await userEvent.clear(field)
    await userEvent.type(field, 'Q3 revenue{Enter}')

    await waitFor(() => expect(renamed).toHaveBeenCalledWith('c1', 'Q3 revenue'))
  })

  it('does not save a rename that changed nothing', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    const [rename] = screen.getAllByRole('button', { name: /^rename$/i })
    await userEvent.click(rename!)
    await userEvent.type(screen.getByLabelText(/conversation title/i), '{Enter}')

    expect(renamed).not.toHaveBeenCalled()
  })

  it('disables Previous on the first page', async () => {
    renderPage()
    await screen.findByText('Quarterly revenue')

    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
  })
})
