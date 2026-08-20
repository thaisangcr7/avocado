/**
 * What this team does, derived from what it has uploaded.
 *
 * §5's org knowledge layer: the difference between a pile of PDFs and a
 * queryable map of a team's policies and processes.
 */

import { useState } from 'react'

import type { DocumentKind } from '@/api/types'
import { DOCUMENT_KIND_LABEL } from '@/api/types'
import { Badge, Button, Card, EmptyState, Spinner } from '@/components/ui/primitives'
import { useKnowledgeMap } from '@/hooks/queries'
import { cn } from '@/lib/utils'

const KINDS: DocumentKind[] = ['policy', 'process', 'project', 'reference', 'other']

export function KnowledgeMapView({
  workspaceId,
  onClose,
}: {
  workspaceId: string
  onClose: () => void
}) {
  const [kind, setKind] = useState<DocumentKind | undefined>(undefined)
  const [topic, setTopic] = useState<string | undefined>(undefined)
  const { data, isLoading } = useKnowledgeMap(workspaceId, { kind, topic })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold text-ink">What this team does</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            Policies and processes, as classified from your documents.
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="mx-auto w-full max-w-3xl space-y-4 px-6 py-6">
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={kind === undefined} onClick={() => setKind(undefined)}>
            All
          </FilterChip>
          {KINDS.map((candidate) => {
            const count = data?.counts_by_kind[candidate] ?? 0
            if (count === 0) return null
            return (
              <FilterChip
                key={candidate}
                active={kind === candidate}
                onClick={() => setKind(kind === candidate ? undefined : candidate)}
              >
                {DOCUMENT_KIND_LABEL[candidate]} ({count})
              </FilterChip>
            )
          })}
        </div>

        {(data?.topics.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {data!.topics.map((candidate) => (
              <FilterChip
                key={candidate}
                active={topic === candidate}
                onClick={() => setTopic(topic === candidate ? undefined : candidate)}
              >
                #{candidate}
              </FilterChip>
            ))}
          </div>
        )}

        {(data?.documents.length ?? 0) === 0 ? (
          <EmptyState
            title="Nothing classified yet"
            description="Documents are tagged as they finish processing. Upload a policy or a process writeup to see it here."
          />
        ) : (
          <ul className="space-y-2">
            {data!.documents.map((document) => (
              <li key={document.document_id}>
                <Card className="p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={document.kind === 'policy' ? 'accent' : 'neutral'}>
                      {DOCUMENT_KIND_LABEL[document.kind]}
                    </Badge>
                    <p className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
                      {document.title || document.filename}
                    </p>
                    {document.effective_date && (
                      <span className="text-xs text-ink-muted">
                        effective {document.effective_date}
                      </span>
                    )}
                  </div>

                  {document.summary && (
                    <p className="mt-1.5 text-sm text-ink-muted">{document.summary}</p>
                  )}

                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-ink-muted/70">{document.filename}</span>
                    {document.topics.map((candidate) => (
                      <span
                        key={candidate}
                        className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[11px] text-ink-muted"
                      >
                        #{candidate}
                      </span>
                    ))}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}

        {(data?.unclassified_count ?? 0) > 0 && (
          <p className="text-xs text-ink-muted">
            {data!.unclassified_count} document
            {data!.unclassified_count === 1 ? '' : 's'} not yet classified.
          </p>
        )}
      </div>
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-full border px-2.5 py-1 text-xs transition-colors',
        active
          ? 'border-accent bg-accent-soft text-accent-strong'
          : 'border-border-subtle text-ink-muted hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}
