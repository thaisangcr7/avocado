/**
 * Proactive nudges, above the chat input.
 *
 * Dismissal is remembered client-side because the server deliberately does not
 * store suggestions — they are a digest, not a record (§5). Suggestion ids are
 * content hashes, so a dismissal survives regeneration: the same overdue task
 * produces the same id tomorrow.
 */

import { useCallback, useState } from 'react'

import type { Suggestion, SuggestionKind } from '@/api/types'
import { Spinner } from '@/components/ui/primitives'
import { useSuggestions } from '@/hooks/queries'
import { cn } from '@/lib/utils'

const DISMISSED_KEY = 'avocado.dismissed_suggestions'

const KIND_ICON: Record<SuggestionKind, string> = {
  task_overdue: '🔴',
  task_due: '🟡',
  task_blocked: '⛔',
  failed_document: '⚠️',
  unfinished_thread: '💬',
  new_document: '📄',
}

const KIND_TONE: Record<SuggestionKind, string> = {
  task_overdue: 'border-danger/30 bg-danger-soft',
  task_due: 'border-warning/30 bg-warning-soft',
  task_blocked: 'border-danger/30 bg-danger-soft',
  failed_document: 'border-warning/30 bg-warning-soft',
  unfinished_thread: 'border-border-subtle bg-surface-sunken',
  new_document: 'border-border-subtle bg-surface-sunken',
}

function loadDismissed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? '[]'))
  } catch {
    return new Set()
  }
}

export function SuggestionsBar({
  workspaceId,
  onOpenTask,
  onOpenConversation,
}: {
  workspaceId: string
  onOpenTask?: (taskId: string) => void
  onOpenConversation?: (conversationId: string) => void
}) {
  const { data, isLoading } = useSuggestions(workspaceId)
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed)

  const dismiss = useCallback((id: string) => {
    setDismissed((current) => {
      const next = new Set(current)
      next.add(id)
      // Capped so a long-lived browser does not accumulate ids forever.
      const stored = [...next].slice(-200)
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(stored))
      return new Set(stored)
    })
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-1 py-1 text-xs text-ink-muted">
        <Spinner className="size-3" />
        Checking what needs attention…
      </div>
    )
  }

  const visible = (data?.items ?? []).filter((s) => !dismissed.has(s.id))
  if (visible.length === 0) return null

  return (
    <div className="mb-2">
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {visible.map((suggestion) => (
          <SuggestionChip
            key={suggestion.id}
            suggestion={suggestion}
            onDismiss={() => dismiss(suggestion.id)}
            onOpen={() => {
              if (suggestion.task_id) onOpenTask?.(suggestion.task_id)
              else if (suggestion.conversation_id)
                onOpenConversation?.(suggestion.conversation_id)
            }}
          />
        ))}
      </div>
    </div>
  )
}

function SuggestionChip({
  suggestion,
  onDismiss,
  onOpen,
}: {
  suggestion: Suggestion
  onDismiss: () => void
  onOpen: () => void
}) {
  const actionable = Boolean(suggestion.task_id || suggestion.conversation_id)

  return (
    <div
      className={cn(
        'flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
        KIND_TONE[suggestion.kind],
      )}
    >
      <span aria-hidden="true" className="text-xs">
        {KIND_ICON[suggestion.kind]}
      </span>

      <button
        type="button"
        onClick={onOpen}
        disabled={!actionable}
        title={suggestion.detail ?? undefined}
        className={cn(
          'max-w-64 truncate text-xs text-ink',
          actionable ? 'hover:underline' : 'cursor-default',
        )}
      >
        {suggestion.title}
      </button>

      <button
        type="button"
        onClick={onDismiss}
        aria-label={`Dismiss: ${suggestion.title}`}
        className="shrink-0 text-ink-muted hover:text-ink"
      >
        ×
      </button>
    </div>
  )
}
