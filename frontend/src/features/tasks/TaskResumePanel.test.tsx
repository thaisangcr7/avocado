/**
 * The resume panel.
 *
 * §11's promise is that returning to a task starts with where you left off.
 * The property worth guarding is honesty: a deterministic fallback must be
 * labelled, so the reader is never led to believe more synthesis happened
 * than actually did.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { TaskResumePanel } from './TaskResumePanel'
import type { TaskResume } from '@/api/types'
import { queryKeys } from '@/hooks/queries'

const BASE: TaskResume = {
  task: {
    id: 'task-1',
    project_id: 'project-1',
    workspace_id: 'w1',
    assignee_id: 'user-1',
    title: 'Ship the migration',
    notes: 'Coordinate with the platform team.',
    status: 'in_progress',
    due_date: '2026-03-01',
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-02-01T10:00:00Z',
  },
  conversation_id: 'conv-1',
  summary: 'You were working out the migration timing; March was agreed.',
  message_count: 6,
  last_activity_at: '2026-02-01T10:00:00Z',
  synthesized: true,
}

function renderPanel(resume: TaskResume, handlers: { onOpenThread?: () => void } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  queryClient.setQueryData(queryKeys.taskResume('w1', 'task-1'), resume)

  const onOpenThread = handlers.onOpenThread ?? vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <TaskResumePanel
        workspaceId="w1"
        taskId="task-1"
        onOpenThread={onOpenThread}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  )
  return { onOpenThread }
}

describe('TaskResumePanel', () => {
  it('leads with where the work stood', async () => {
    renderPanel(BASE)
    expect(await screen.findByText(/where you left off/i)).toBeInTheDocument()
    expect(screen.getByText(BASE.summary)).toBeInTheDocument()
  })

  it('shows the task and its state', async () => {
    renderPanel(BASE)
    expect(await screen.findByText('Ship the migration')).toBeInTheDocument()
    expect(screen.getByText(/due 2026-03-01/)).toBeInTheDocument()
    expect(screen.getByText(/6 messages/)).toBeInTheDocument()
  })

  it('labels a summary that was not actually synthesised', async () => {
    renderPanel({ ...BASE, synthesized: false })
    expect(await screen.findByText(/not summarised/i)).toBeInTheDocument()
  })

  it('does not label a genuine synthesis', async () => {
    renderPanel(BASE)
    await screen.findByText(BASE.summary)
    expect(screen.queryByText(/not summarised/i)).not.toBeInTheDocument()
  })

  it('offers to start the thread when nothing has been said', async () => {
    renderPanel({ ...BASE, message_count: 0, last_activity_at: null, synthesized: false })
    expect(await screen.findByRole('button', { name: /start the thread/i })).toBeInTheDocument()
  })

  it('offers to continue an existing thread', async () => {
    const user = userEvent.setup()
    const { onOpenThread } = renderPanel(BASE)

    await user.click(await screen.findByRole('button', { name: /continue the thread/i }))
    expect(onOpenThread).toHaveBeenCalledWith('conv-1')
  })

  it('shows the task notes when there are any', async () => {
    renderPanel(BASE)
    expect(await screen.findByText(/coordinate with the platform team/i)).toBeInTheDocument()
  })
})
