/**
 * "Here's where we left off."
 *
 * §11's whole point: returning to a task after two days on something else
 * should not start from a blank chat. The summary is labelled when it is a
 * deterministic fallback rather than model-written, so the reader is never led
 * to believe more synthesis happened than actually did.
 */

import type { TaskResume } from '@/api/types'
import { Badge, Button, Card, Spinner } from '@/components/ui/primitives'
import { useTaskResume } from '@/hooks/queries'
import { formatRelativeTime } from '@/lib/utils'

export function TaskResumePanel({
  workspaceId,
  taskId,
  onOpenThread,
  onClose,
}: {
  workspaceId: string
  taskId: string
  onOpenThread: (conversationId: string) => void
  onClose: () => void
}) {
  const { data, isLoading, isError } = useTaskResume(workspaceId, taskId)

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center">
        <p className="text-sm text-ink-muted">This task could not be opened.</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold text-ink">{data.task.title}</h2>
          <TaskMeta resume={data} />
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="mx-auto w-full max-w-3xl space-y-4 px-6 py-6">
        <Card className="p-4">
          <div className="mb-2 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">Where you left off</h3>
            {!data.synthesized && (
              // Said plainly rather than passed off as synthesis.
              <Badge tone="neutral">not summarised</Badge>
            )}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
            {data.summary}
          </p>
        </Card>

        {data.task.notes && (
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold text-ink">Notes</h3>
            <p className="whitespace-pre-wrap text-sm text-ink-muted">{data.task.notes}</p>
          </Card>
        )}

        <Button onClick={() => onOpenThread(data.conversation_id)}>
          {data.message_count > 0 ? 'Continue the thread' : 'Start the thread'}
        </Button>
      </div>
    </div>
  )
}

function TaskMeta({ resume }: { resume: TaskResume }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
      <Badge tone={resume.task.status === 'blocked' ? 'danger' : 'neutral'}>
        {resume.task.status.replace('_', ' ')}
      </Badge>
      {resume.task.due_date && <span>due {resume.task.due_date}</span>}
      <span>
        {resume.message_count} message{resume.message_count === 1 ? '' : 's'}
      </span>
      {resume.last_activity_at && (
        <span>last active {formatRelativeTime(resume.last_activity_at)}</span>
      )}
    </div>
  )
}
