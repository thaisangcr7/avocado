/**
 * History — a page, not a sidebar list.
 *
 * The sidebar answers "what was I just doing". This answers "where is that
 * thing from three weeks ago", which needs search, a filter and pagination
 * rather than a scroll.
 *
 * There is deliberately no status chip. Every chat is complete the moment it
 * stops, so "Completed" on every row would be decoration. Pinned and archived
 * are real states and are the ones shown.
 */

import { useEffect, useState } from 'react'

import { historyApi } from '@/api/endpoints'
import type { Conversation, HistoryFilter } from '@/api/types'
import { Badge, Button, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { useDeleteConversation, useHistory, useRenameConversation, useSetConversationFlags } from '@/hooks/queries'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 20

const FILTERS: { value: HistoryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'pinned', label: 'Pinned' },
  { value: 'archived', label: 'Archived' },
]

export function HistoryPage({
  workspaceId,
  onOpen,
}: {
  workspaceId: string
  onOpen: (conversationId: string) => void
}) {
  const [which, setWhich] = useState<HistoryFilter>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)

  // Any change to what is being asked for starts again at the first page —
  // otherwise a search from page three shows an empty page three.
  useEffect(() => setPage(0), [which, search])

  const { data, isLoading, isError } = useHistory(workspaceId, which, search, page * PAGE_SIZE, PAGE_SIZE)
  const flags = useSetConversationFlags(workspaceId)
  const remove = useDeleteConversation(workspaceId)

  const rows = data?.conversations ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-border-subtle px-6 py-4">
        <h1 className="text-base font-semibold text-ink">History</h1>
        <p className="mt-0.5 text-xs text-ink-muted">
          {total} conversation{total === 1 ? '' : 's'}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-6 py-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles…"
          aria-label="Search history"
          className="min-w-48 flex-1 rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
        />
        <div className="flex gap-1">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              onClick={() => setWhich(option.value)}
              className={cn(
                'rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
                which === option.value
                  ? 'bg-accent-soft text-accent-strong'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isError && (
          <div className="p-6">
            <ErrorNotice message="History could not be loaded." />
          </div>
        )}
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner className="size-5 text-ink-muted" />
          </div>
        ) : rows.length === 0 ? (
          <p className="py-12 text-center text-sm text-ink-muted">Nothing matches that.</p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {rows.map((conversation) => (
              <HistoryRow
                key={conversation.id}
                workspaceId={workspaceId}
                conversation={conversation}
                onOpen={() => onOpen(conversation.id)}
                onPin={() =>
                  flags.mutate({
                    conversationId: conversation.id,
                    pinned: !conversation.pinned,
                  })
                }
                onArchive={() =>
                  flags.mutate({
                    conversationId: conversation.id,
                    archived: !conversation.archived,
                  })
                }
                onDelete={() => remove.mutate(conversation.id)}
              />
            ))}
          </ul>
        )}
      </div>

      <footer className="flex items-center justify-between gap-3 border-t border-border-subtle px-6 py-3">
        <p className="text-xs text-ink-muted">
          Page {page + 1} of {pages}
        </p>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
          >
            Previous
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={page + 1 >= pages}
            onClick={() => setPage((current) => current + 1)}
          >
            Next
          </Button>
        </div>
      </footer>
    </div>
  )
}

function HistoryRow({
  workspaceId,
  conversation,
  onOpen,
  onPin,
  onArchive,
  onDelete,
}: {
  workspaceId: string
  conversation: Conversation
  onOpen: () => void
  onPin: () => void
  onArchive: () => void
  onDelete: () => void
}) {
  const rename = useRenameConversation(workspaceId)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(conversation.title)

  async function download() {
    const blob = await historyApi.exportMarkdown(workspaceId, conversation.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${conversation.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.md`
    link.click()
    URL.revokeObjectURL(url)
  }

  function commit() {
    setEditing(false)
    const next = title.trim()
    if (next && next !== conversation.title) {
      rename.mutate({ conversationId: conversation.id, title: next })
    } else {
      setTitle(conversation.title)
    }
  }

  return (
    <li className="flex items-center gap-3 px-6 py-3 hover:bg-surface-sunken/50">
      <div className="min-w-0 flex-1">
        {editing ? (
          <input
            autoFocus
            value={title}
            aria-label="Conversation title"
            onChange={(e) => setTitle(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') {
                setTitle(conversation.title)
                setEditing(false)
              }
            }}
            className="w-full rounded border border-accent bg-surface px-2 py-1 text-sm text-ink focus:outline-none"
          />
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            <button onClick={onOpen} className="truncate text-sm font-medium text-ink hover:underline">
              {conversation.title}
            </button>
            {conversation.pinned && <Badge tone="accent">pinned</Badge>}
            {conversation.archived && <Badge tone="neutral">archived</Badge>}
          </div>
        )}
        <p className="mt-0.5 text-xs text-ink-muted">
          {conversation.message_count != null && (
            <>
              {conversation.message_count} message
              {conversation.message_count === 1 ? '' : 's'} ·{' '}
            </>
          )}
          {new Date(conversation.updated_at).toLocaleDateString()}
        </p>
      </div>

      <div className="flex shrink-0 gap-1">
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          Rename
        </Button>
        <Button variant="ghost" size="sm" onClick={onPin}>
          {conversation.pinned ? 'Unpin' : 'Pin'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onArchive}>
          {conversation.archived ? 'Restore' : 'Archive'}
        </Button>
        <Button variant="ghost" size="sm" onClick={download}>
          Download
        </Button>
        <Button variant="ghost" size="sm" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </li>
  )
}
