import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { NotificationList } from '@/api/types'
import { NotificationBell } from './NotificationBell'

const markRead = vi.fn()
const markAllRead = vi.fn()

let LIST: NotificationList = {
  unread: 2,
  notifications: [
    {
      id: 'n1',
      kind: 'schedule_ran',
      title: 'Overnight brief is ready',
      body: 'Three documents changed.',
      conversation_id: 'c1',
      read_at: null,
      created_at: '2026-08-23T09:00:00Z',
    },
    {
      id: 'n2',
      kind: 'schedule_failed',
      title: 'Weekly summary did not run',
      body: 'the model is on fire',
      conversation_id: null,
      read_at: null,
      created_at: '2026-08-22T09:00:00Z',
    },
  ],
}

vi.mock('@/api/endpoints', () => ({
  notificationApi: {
    list: () => Promise.resolve(LIST),
    markRead: (id: string) => {
      markRead(id)
      return Promise.resolve({ ...LIST, unread: LIST.unread - 1 })
    },
    markAllRead: () => {
      markAllRead()
      return Promise.resolve({ ...LIST, unread: 0 })
    },
  },
}))

function renderBell(onOpenConversation = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NotificationBell onOpenConversation={onOpenConversation} />
    </QueryClientProvider>,
  )
  return onOpenConversation
}

describe('NotificationBell', () => {
  beforeEach(() => {
    markRead.mockClear()
    markAllRead.mockClear()
  })

  it('shows how many are unread', async () => {
    renderBell()
    expect(await screen.findByLabelText(/2 unread/i)).toBeInTheDocument()
  })

  it('does not clear the count just for being opened', async () => {
    renderBell()
    await userEvent.click(await screen.findByLabelText(/notifications/i))

    // Seeing that something arrived is not the same as having read it.
    expect(markAllRead).not.toHaveBeenCalled()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('opens the thread a finished run produced', async () => {
    const onOpen = renderBell()
    await userEvent.click(await screen.findByLabelText(/notifications/i))

    await userEvent.click(screen.getByText(/overnight brief is ready/i))

    await waitFor(() => expect(markRead).toHaveBeenCalledWith('n1'))
    expect(onOpen).toHaveBeenCalledWith('c1')
  })

  it('marks a failure read without pretending there is a thread', async () => {
    const onOpen = renderBell()
    await userEvent.click(await screen.findByLabelText(/notifications/i))

    await userEvent.click(screen.getByText(/weekly summary did not run/i))

    await waitFor(() => expect(markRead).toHaveBeenCalledWith('n2'))
    // A failed run produced no conversation, so there is nowhere to go.
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('marks everything read on request', async () => {
    renderBell()
    await userEvent.click(await screen.findByLabelText(/notifications/i))

    await userEvent.click(screen.getByRole('button', { name: /mark all read/i }))

    await waitFor(() => expect(markAllRead).toHaveBeenCalled())
  })

  it('says what will appear when there is nothing yet', async () => {
    LIST = { unread: 0, notifications: [] }
    renderBell()
    await userEvent.click(await screen.findByLabelText(/notifications/i))

    expect(screen.getByText(/scheduled runs will show up here/i)).toBeInTheDocument()
  })
})
