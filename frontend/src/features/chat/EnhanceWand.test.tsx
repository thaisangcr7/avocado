/**
 * The prompt wand.
 *
 * Rewriting someone's question in place is a destructive edit to text they
 * typed. The undo is the part that makes it acceptable, so it is what these
 * guard — along with staying out of the way when the model changed nothing.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatView } from './ChatView'
import { queryKeys } from '@/hooks/queries'

const rewrite = vi.fn()

vi.mock('@/api/endpoints', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    enhanceApi: {
      rewrite: (_w: string, draft: string) => rewrite(draft),
    },
  }
})

function renderChat() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  queryClient.setQueryData(queryKeys.messages('c1'), [])
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatView workspaceId="w1" conversationId="c1" />
    </QueryClientProvider>,
  )
}

describe('the prompt wand', () => {
  beforeEach(() => rewrite.mockReset())

  it('is disabled until something is typed', async () => {
    renderChat()
    expect(screen.getByRole('button', { name: /improve this question/i })).toBeDisabled()
  })

  it('replaces the draft and offers a way back', async () => {
    rewrite.mockResolvedValue({
      draft: 'What is our remote work policy?',
      original: 'remote work',
      changed: true,
    })
    renderChat()
    const input = screen.getByPlaceholderText(/ask a question/i)
    await userEvent.type(input, 'remote work')

    await userEvent.click(screen.getByRole('button', { name: /improve this question/i }))

    await waitFor(() => expect(input).toHaveValue('What is our remote work policy?'))
    await userEvent.click(screen.getByRole('button', { name: /undo/i }))
    expect(input).toHaveValue('remote work')
  })

  it('says nothing when the model changed nothing', async () => {
    rewrite.mockResolvedValue({
      draft: 'What is our refund policy?',
      original: 'What is our refund policy?',
      changed: false,
    })
    renderChat()
    await userEvent.type(screen.getByPlaceholderText(/ask a question/i), 'What is our refund policy?')

    await userEvent.click(screen.getByRole('button', { name: /improve this question/i }))

    // No undo offered, because nothing was undone.
    await waitFor(() => expect(rewrite).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument()
  })
})
