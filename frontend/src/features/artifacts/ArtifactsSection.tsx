/**
 * The rail entry for artifacts: what the assistant has produced here.
 *
 * Distinct from uploaded documents, which are what *you* brought in. Keeping
 * the two apart is what makes it obvious which is the source of an answer and
 * which is its output.
 */

import { useState } from 'react'

import type { Artifact } from '@/api/types'
import { Badge, Spinner } from '@/components/ui/primitives'
import { useArtifacts } from '@/hooks/queries'
import { ArtifactViewer } from './ArtifactViewer'

const KIND_LABEL: Record<Artifact['kind'], string> = {
  html: 'page',
  markdown: 'doc',
  code: 'code',
  chart: 'chart',
  table: 'table',
}

export function ArtifactsSection({ workspaceId }: { workspaceId: string }) {
  const { data: artifacts, isLoading } = useArtifacts(workspaceId)
  const [open, setOpen] = useState<Artifact | null>(null)

  if (isLoading) {
    return (
      <div className="flex justify-center py-3">
        <Spinner className="size-4 text-ink-muted" />
      </div>
    )
  }

  if (!artifacts?.length) {
    return (
      <p className="text-xs text-ink-muted">
        Nothing yet. Ask for a summary or run an analysis, and what it produces is
        kept here.
      </p>
    )
  }

  return (
    <>
      <ul className="space-y-1.5">
        {artifacts.slice(0, 6).map((artifact) => (
          <li key={artifact.id}>
            <button
              type="button"
              onClick={() => setOpen(artifact)}
              className="w-full rounded-lg border border-border-subtle bg-surface px-2.5 py-2 text-left transition-colors hover:border-accent/40 hover:bg-surface-sunken"
            >
              <div className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">
                  {artifact.title}
                </span>
                {artifact.version > 1 && <Badge tone="neutral">v{artifact.version}</Badge>}
              </div>
              <p className="mt-0.5 truncate text-[11px] text-ink-muted">
                {KIND_LABEL[artifact.kind]} · {artifact.filename}
              </p>
            </button>
          </li>
        ))}
      </ul>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={open.title}
          onClick={() => setOpen(null)}
        >
          <div
            className="h-[85vh] w-full max-w-4xl overflow-hidden rounded-2xl shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <ArtifactViewer
              workspaceId={workspaceId}
              artifact={open}
              onClose={() => setOpen(null)}
            />
          </div>
        </div>
      )}
    </>
  )
}
