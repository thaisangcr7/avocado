/**
 * Tools and integrations.
 *
 * The list is the obvious part. The part that matters is the cost line: every
 * enabled tool's schema is sent with every request whether or not the model
 * calls it, so switching several on quietly eats the context window and answers
 * get vaguer with no visible cause. That is stated here rather than left to be
 * discovered.
 */

import { useMemo, useState } from 'react'

import type { Tool, ToolCategory } from '@/api/types'
import { Badge, Button, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { useModels, useSetTools, useTools } from '@/hooks/queries'
import { cn } from '@/lib/utils'

const CATEGORIES: { value: ToolCategory | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'analytics', label: 'Analytics' },
  { value: 'engineering', label: 'Engineering' },
  { value: 'knowledge', label: 'Knowledge' },
  { value: 'admin', label: 'Admin' },
  { value: 'data', label: 'Data' },
]

/** Past roughly a tenth of the window, schemas crowd out the conversation. */
const WARN_FRACTION = 0.1

export function ToolsModal({
  workspaceId,
  conversationId,
  onClose,
}: {
  workspaceId: string
  conversationId: string
  onClose: () => void
}) {
  const { data: selection, isLoading } = useTools(workspaceId, conversationId)
  const { data: catalog } = useModels()
  const setTools = useSetTools(workspaceId, conversationId)

  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<ToolCategory | 'all'>('all')

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (selection?.tools ?? []).filter((tool) => {
      if (category !== 'all' && tool.category !== category) return false
      if (!needle) return true
      return (
        tool.name.toLowerCase().includes(needle) ||
        tool.description.toLowerCase().includes(needle)
      )
    })
  }, [selection?.tools, query, category])

  // Measured against the smallest window on offer, so the warning is honest for
  // whichever model the conversation ends up using rather than only the largest.
  const smallestWindow = useMemo(() => {
    const windows = (catalog?.models ?? []).map((m) => m.context_window).filter(Boolean)
    return windows.length ? Math.min(...windows) : null
  }, [catalog])

  const cost = selection?.context_cost_tokens ?? 0
  const crowded = smallestWindow != null && cost > smallestWindow * WARN_FRACTION

  function toggle(tool: Tool) {
    if (!selection || !tool.connected) return
    const next = selection.tools
      .filter((t) => (t.slug === tool.slug ? !t.enabled : t.enabled))
      .map((t) => t.slug)
    setTools.mutate(next)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Tools and integrations"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border-subtle bg-surface-raised shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">Tools and integrations</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>

        <div className="space-y-3 border-b border-border-subtle px-5 py-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search integrations…"
            className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
          <div className="flex flex-wrap gap-1">
            {CATEGORIES.map((option) => (
              <button
                key={option.value}
                onClick={() => setCategory(option.value)}
                className={cn(
                  'rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
                  category === option.value
                    ? 'bg-accent-soft text-accent-strong'
                    : 'text-ink-muted hover:text-ink',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex justify-center py-10">
              <Spinner className="size-5 text-ink-muted" />
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {visible.map((tool) => (
                <ToolCard key={tool.slug} tool={tool} onToggle={() => toggle(tool)} />
              ))}
              {visible.length === 0 && (
                <p className="col-span-full py-8 text-center text-sm text-ink-muted">
                  Nothing matches that.
                </p>
              )}
            </div>
          )}
        </div>

        <footer className="space-y-2 border-t border-border-subtle px-5 py-3">
          {setTools.isError && (
            <ErrorNotice message="That tool could not be switched on." />
          )}
          <div className="flex items-center justify-between gap-3">
            <p className={cn('text-xs', crowded ? 'text-warning' : 'text-ink-muted')}>
              {selection?.enabled_count ?? 0} enabled ·{' '}
              <span className="font-medium">~{cost.toLocaleString()}</span> tokens of
              context, spent whether or not they are used.
              {crowded && ' That is a large share of a smaller model’s window.'}
            </p>
            <Button size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
}

function ToolCard({ tool, onToggle }: { tool: Tool; onToggle: () => void }) {
  return (
    <div
      className={cn(
        'rounded-xl border p-3 transition-colors',
        tool.enabled ? 'border-accent/40 bg-accent-soft/40' : 'border-border-subtle bg-surface',
        !tool.connected && 'opacity-70',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-sm font-medium text-ink">{tool.name}</p>
            {/* Shown rather than hidden: this is the shape of what is coming,
                and hiding it would make the registry look emptier than it is. */}
            {!tool.connected && <Badge tone="neutral">not connected</Badge>}
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{tool.description}</p>
          <p className="mt-1.5 text-[11px] text-ink-muted/80">
            ~{tool.context_cost_tokens.toLocaleString()} tokens of context
          </p>
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={tool.enabled}
          aria-label={`${tool.enabled ? 'Disable' : 'Enable'} ${tool.name}`}
          disabled={!tool.connected}
          onClick={onToggle}
          title={tool.connected ? undefined : 'Not connected yet'}
          className={cn(
            'mt-0.5 h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors',
            tool.enabled ? 'bg-accent' : 'bg-border-subtle',
            !tool.connected && 'cursor-not-allowed',
          )}
        >
          <span
            className={cn(
              'block size-4 rounded-full bg-white transition-transform',
              tool.enabled && 'translate-x-4',
            )}
          />
        </button>
      </div>
    </div>
  )
}
