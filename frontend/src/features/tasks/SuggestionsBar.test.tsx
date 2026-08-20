/**
 * The suggestions bar.
 *
 * Dismissal is client-side because the server deliberately does not store
 * suggestions — so the behaviour worth guarding is that a dismissal sticks
 * across regeneration, which relies on the ids being content hashes.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { SuggestionsBar } from './SuggestionsBar'
import type { Suggestion, SuggestionsResponse } from '@/api/types'
import { queryKeys } from '@/hooks/queries'

const OVERDUE: Suggestion = {
  id: 'sug-overdue',
  kind: 'task_overdue',
  title: 'Ship the migration is overdue',
  detail: 'Was due two days ago',
  task_id: 'task-1',
  project_id: 'project-1',
  document_id: null,
  conversation_id: null,
  priority: 100,
}

const NEW_DOCUMENT: Suggestion = {
  id: 'sug-doc',
  kind: 'new_document',
  title: '3 new documents were added',
  detail: null,
  task_id: null,
  project_id: null,
  document_id: null,
  conversation_id: null,
  priority: 20,
}

function renderBar(items: Suggestion[], onOpenTask = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  const payload: SuggestionsResponse = {
    items,
    generated_at: new Date().toISOString(),
    cached: false,
    model_used: null,
  }
  queryClient.setQueryData(queryKeys.suggestions('w1'), payload)

  render(
    <QueryClientProvider client={queryClient}>
      <SuggestionsBar workspaceId="w1" onOpenTask={onOpenTask} />
    </QueryClientProvider>,
  )
  return { onOpenTask }
}

describe('SuggestionsBar', () => {
  it('renders nothing when there is nothing to say', () => {
    const { container } = render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
        }
      >
        <SuggestionsBar workspaceId="w1" />
      </QueryClientProvider>,
    )
    expect(container.querySelector('button')).toBeNull()
  })

  it('shows each nudge', async () => {
    renderBar([OVERDUE, NEW_DOCUMENT])
    expect(await screen.findByText(OVERDUE.title)).toBeInTheDocument()
    expect(screen.getByText(NEW_DOCUMENT.title)).toBeInTheDocument()
  })

  it('opens the task a nudge points at', async () => {
    const user = userEvent.setup()
    const { onOpenTask } = renderBar([OVERDUE])

    await user.click(await screen.findByText(OVERDUE.title))
    expect(onOpenTask).toHaveBeenCalledWith('task-1')
  })

  it('does not make an unactionable nudge clickable', async () => {
    renderBar([NEW_DOCUMENT])
    const chip = await screen.findByText(NEW_DOCUMENT.title)
    expect(chip).toBeDisabled()
  })

  it('remembers a dismissal, since the server stores none', async () => {
    const user = userEvent.setup()
    renderBar([OVERDUE, NEW_DOCUMENT])

    await user.click(await screen.findByRole('button', { name: /dismiss.*overdue/i }))

    await waitFor(() => expect(screen.queryByText(OVERDUE.title)).not.toBeInTheDocument())
    // The other nudge is untouched.
    expect(screen.getByText(NEW_DOCUMENT.title)).toBeInTheDocument()

    // Persisted, so it survives a reload — suggestion ids are content hashes,
    // so the same overdue task produces the same id tomorrow.
    const stored = JSON.parse(localStorage.getItem('avocado.dismissed_suggestions') ?? '[]')
    expect(stored).toContain(OVERDUE.id)
  })

  it('hides a nudge dismissed in an earlier session', async () => {
    localStorage.setItem('avocado.dismissed_suggestions', JSON.stringify([OVERDUE.id]))
    renderBar([OVERDUE, NEW_DOCUMENT])

    expect(await screen.findByText(NEW_DOCUMENT.title)).toBeInTheDocument()
    expect(screen.queryByText(OVERDUE.title)).not.toBeInTheDocument()
  })

  it('survives corrupt stored state rather than crashing', async () => {
    localStorage.setItem('avocado.dismissed_suggestions', 'not json')
    renderBar([OVERDUE])
    expect(await screen.findByText(OVERDUE.title)).toBeInTheDocument()
  })
})
