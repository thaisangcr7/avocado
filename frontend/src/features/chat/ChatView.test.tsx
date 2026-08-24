/**
 * Chat rendering.
 *
 * The behaviour worth guarding: citations must be visible and inspectable, and
 * the model that answered must always be shown — an answer whose provenance
 * is invisible is the thing this product exists to avoid.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ChatView } from './ChatView'
import type { Document, Message, Paginated } from '@/api/types'
import { queryKeys } from '@/hooks/queries'

const CITED_MESSAGE: Message = {
  id: 'm2',
  conversation_id: 'c1',
  role: 'assistant',
  content: 'Employees may work from home three days per week. [1]',
  citations: [
    {
      document_id: 'd1',
      document_name: 'handbook.pdf',
      chunk_id: 'chunk-1',
      snippet: 'Remote work policy: up to three days per week from home.',
      score: 0.87,
      page: 4,
      sheet: null,
      section: null,
    },
  ],
  failed: false,
  model_used: 'claude-opus-5',
  input_tokens: 900,
  output_tokens: 40,
  latency_ms: 1200,
  created_at: '2026-01-01T12:00:00Z',
}

const USER_MESSAGE: Message = {
  id: 'm1',
  conversation_id: 'c1',
  role: 'user',
  content: 'How many days can I work from home?',
  citations: [],
  failed: false,
  model_used: null,
  input_tokens: null,
  output_tokens: null,
  latency_ms: null,
  created_at: '2026-01-01T11:59:00Z',
}

const READY_DOCUMENTS: Paginated<Document> = {
  items: [
    {
      id: 'd1',
      workspace_id: 'w1',
      conversation_id: null,
      filename: 'employee-handbook.pdf',
      content_type: 'application/pdf',
      doc_type: 'pdf',
      size_bytes: 1024,
      status: 'ready',
      error_message: null,
      page_count: 12,
      chunk_count: 8,
      doc_metadata: {},
      created_at: '2026-01-01T11:00:00Z',
      updated_at: '2026-01-01T11:01:00Z',
    },
    {
      id: 'd2',
      workspace_id: 'w1',
      conversation_id: null,
      filename: 'revenue_by_region.csv',
      content_type: 'text/csv',
      doc_type: 'csv',
      size_bytes: 2048,
      status: 'ready',
      error_message: null,
      page_count: null,
      chunk_count: 4,
      doc_metadata: {},
      created_at: '2026-01-01T11:00:00Z',
      updated_at: '2026-01-01T11:01:00Z',
    },
  ],
  next_cursor: null,
  has_more: false,
}

const PROCESSING_DOCUMENTS: Paginated<Document> = {
  items: [
    {
      id: 'd3',
      workspace_id: 'w1',
      conversation_id: null,
      filename: 'large-policy-pack.pdf',
      content_type: 'application/pdf',
      doc_type: 'pdf',
      size_bytes: 4096,
      status: 'processing',
      error_message: null,
      page_count: null,
      chunk_count: 0,
      doc_metadata: {},
      created_at: '2026-01-01T11:00:00Z',
      updated_at: '2026-01-01T11:01:00Z',
    },
  ],
  next_cursor: null,
  has_more: false,
}

function renderChat(
  messages: Message[],
  conversationId: string | null = 'c1',
  documents?: Paginated<Document>,
) {
  const queryClient = new QueryClient({
    // staleTime keeps the seeded cache from being refetched, so `fetch` calls
    // in these tests are the ones the component itself made.
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  if (conversationId) {
    queryClient.setQueryData(queryKeys.messages(conversationId), messages)
  }
  if (documents) {
    queryClient.setQueryData(queryKeys.documents('w1'), documents)
  }

  return render(
    <QueryClientProvider client={queryClient}>
      <ChatView workspaceId="w1" conversationId={conversationId} />
    </QueryClientProvider>,
  )
}

describe('ChatView', () => {
  it('says what is missing when there is nothing to ask about', () => {
    // No documents in the fixture, so the landing pane points at the gap that
    // actually blocks the user rather than at the conversation list.
    renderChat([], null)
    expect(screen.getByText(/nothing to ask about yet/i)).toBeInTheDocument()
  })

  it('renders both sides of a turn', () => {
    renderChat([USER_MESSAGE, CITED_MESSAGE])
    expect(screen.getByText(USER_MESSAGE.content)).toBeInTheDocument()
    expect(screen.getByText(CITED_MESSAGE.content)).toBeInTheDocument()
  })

  it('always shows which model answered', () => {
    renderChat([CITED_MESSAGE])
    expect(screen.getByText('claude-opus-5')).toBeInTheDocument()
  })

  it('lists sources and reveals the snippet on demand', async () => {
    const user = userEvent.setup()
    renderChat([CITED_MESSAGE])

    expect(screen.getByText('Sources (1)')).toBeInTheDocument()
    expect(screen.getByText('handbook.pdf')).toBeInTheDocument()
    expect(screen.getByText('page 4')).toBeInTheDocument()

    // The retrieved text is collapsed until asked for.
    expect(screen.queryByText(/up to three days per week/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /handbook\.pdf/i }))
    expect(screen.getByText(/up to three days per week/i)).toBeInTheDocument()
  })

  it('renders a failed turn as a failure, not as an answer', () => {
    renderChat([
      USER_MESSAGE,
      {
        ...CITED_MESSAGE,
        content: 'No LLM provider is configured.',
        citations: [],
        failed: true,
        model_used: null,
      },
    ])
    expect(screen.getByText(/could not answer/i)).toBeInTheDocument()
    expect(screen.getByText('No LLM provider is configured.')).toBeInTheDocument()
  })

  it('shows no source list when the answer cited nothing', () => {
    renderChat([{ ...CITED_MESSAGE, citations: [] }])
    expect(screen.queryByText(/^Sources/)).not.toBeInTheDocument()
  })

  it('invites a first question when the thread is empty', () => {
    renderChat([])
    expect(screen.getByText(/ask anything about this space/i)).toBeInTheDocument()
  })

  it('shows processing guidance when files are still ingesting', () => {
    renderChat([], 'c1', PROCESSING_DOCUMENTS)
    expect(screen.getByText(/files are still getting ready/i)).toBeInTheDocument()
    expect(screen.getByText(/still being prepared/i)).toBeInTheDocument()
  })

  it('shows ready-to-ask openings when documents are available in an empty thread', () => {
    renderChat([], 'c1', READY_DOCUMENTS)
    expect(screen.getByText(/ready to ask/i)).toBeInTheDocument()
    expect(screen.getByText(/what policies does this space define\?/i)).toBeInTheDocument()
    expect(screen.getByText(/create an executive summary with the top kpis/i)).toBeInTheDocument()
  })

  it('keeps send disabled until something is typed', async () => {
    const user = userEvent.setup()
    renderChat([])

    const send = screen.getByRole('button', { name: /send/i })
    expect(send).toBeDisabled()

    await user.type(screen.getByPlaceholderText(/ask a question/i), 'hello')
    expect(send).toBeEnabled()
  })

  it('sends on Enter and inserts a newline on Shift+Enter', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, body: null })
    vi.stubGlobal('fetch', fetchMock)

    const streamCalls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/stream')).length

    renderChat([])
    const input = screen.getByPlaceholderText(/ask a question/i)

    await user.type(input, 'line one{Shift>}{Enter}{/Shift}line two')
    expect(streamCalls()).toBe(0)
    expect(input).toHaveValue('line one\nline two')

    await user.type(input, '{Enter}')
    expect(streamCalls()).toBe(1)
  })
})
