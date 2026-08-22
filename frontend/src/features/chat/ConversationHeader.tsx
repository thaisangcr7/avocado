/**
 * The bar above a conversation: which thread this is, and what is answering it.
 *
 * The pane had no header at all, so an open thread showed no title, offered no
 * way to rename itself, and gave a model choice no home. Titles are generated
 * from the first question, which makes renaming them the common case rather
 * than an edge one — so the title edits in place instead of hiding behind a
 * menu.
 */

import { useEffect, useRef, useState } from 'react'

import type { Conversation } from '@/api/types'
import { useRenameConversation } from '@/hooks/queries'
import { cn } from '@/lib/utils'

export function ConversationHeader({
  workspaceId,
  conversation,
  modelLabel,
}: {
  workspaceId: string
  conversation: Conversation
  modelLabel: string
}) {
  const rename = useRenameConversation(workspaceId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conversation.title)
  const inputRef = useRef<HTMLInputElement>(null)

  // A rename elsewhere, or switching threads, must not leave a stale draft.
  useEffect(() => {
    setDraft(conversation.title)
    setEditing(false)
  }, [conversation.id, conversation.title])

  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  function commit() {
    const title = draft.trim()
    setEditing(false)
    if (!title || title === conversation.title) {
      setDraft(conversation.title)
      return
    }
    rename.mutate({ conversationId: conversation.id, title })
  }

  return (
    <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border-subtle/80 px-4 py-2.5 sm:px-6">
      <div className="min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') {
                setDraft(conversation.title)
                setEditing(false)
              }
            }}
            aria-label="Conversation title"
            className="w-full max-w-md rounded-lg border border-accent/40 bg-surface px-2 py-0.5 text-sm font-medium text-ink focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            title="Rename this conversation"
            className={cn(
              'max-w-full truncate rounded-lg px-2 py-0.5 text-sm font-medium text-ink',
              'transition-colors hover:bg-surface-sunken',
            )}
          >
            {conversation.title}
          </button>
        )}
        <p className="px-2 text-xs text-ink-muted">{modelLabel}</p>
      </div>
    </header>
  )
}
