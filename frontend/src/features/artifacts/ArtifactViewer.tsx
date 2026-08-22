/**
 * The artifact viewer: what the assistant produced, at a chosen version.
 *
 * Named viewer, not panel: the right rail already has an ArtifactPanel that
 * predates this feature and shows analysis runs and tasks. Two components with
 * one name is how a working feature ends up wired to nothing.
 *
 * Versions are real history, not an undo stack — every one stays retrievable,
 * so the picker can jump back to what a document said three revisions ago.
 */

import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'

import { artifactApi } from '@/api/endpoints'
import type { Artifact } from '@/api/types'
import { Badge, Button, Spinner } from '@/components/ui/primitives'
import { useArtifact } from '@/hooks/queries'
import { ArtifactFrame } from './ArtifactFrame'
import { cn } from '@/lib/utils'

export function ArtifactViewer({
  workspaceId,
  artifact,
  onClose,
}: {
  workspaceId: string
  artifact: Artifact
  onClose: () => void
}) {
  // Which version is on screen. Starts at the one that was opened, and resets
  // when a different artifact is selected.
  const [viewingId, setViewingId] = useState(artifact.id)
  const [showSource, setShowSource] = useState(false)

  useEffect(() => {
    setViewingId(artifact.id)
    setShowSource(false)
  }, [artifact.id])

  const { data: detail, isLoading } = useArtifact(workspaceId, viewingId)

  if (isLoading || !detail) {
    return (
      <aside className="flex h-full w-full items-center justify-center border-l border-border-subtle bg-surface-raised">
        <Spinner className="size-5 text-ink-muted" />
      </aside>
    )
  }

  const versions = detail.versions
  const isLatest = detail.version === Math.max(...versions.map((v) => v.version))

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-border-subtle bg-surface-raised">
      <header className="flex items-center justify-between gap-2 border-b border-border-subtle px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">{detail.title}</p>
          <p className="truncate text-xs text-ink-muted">{detail.filename}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close artifact">
          ✕
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2">
        {versions.length > 1 ? (
          <label className="flex items-center gap-1.5">
            <span className="sr-only">Version</span>
            <select
              value={viewingId}
              onChange={(e) => setViewingId(e.target.value)}
              className="h-7 rounded-lg border border-border-subtle bg-surface px-2 text-xs text-ink"
            >
              {[...versions].reverse().map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version} · {version.author === 'ai' ? 'AI' : 'you'}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <Badge tone="neutral">v{detail.version}</Badge>
        )}

        {/* Says plainly that an older version is on screen, so an edit made
            from here is never a surprise. */}
        {!isLatest && <Badge tone="warning">older version</Badge>}

        <div className="ml-auto flex items-center gap-1">
          {detail.kind === 'html' && (
            <Button variant="ghost" size="sm" onClick={() => setShowSource((v) => !v)}>
              {showSource ? 'Preview' : 'Source'}
            </Button>
          )}
          <a
            href={artifactApi.downloadUrl(workspaceId, detail.id)}
            download={detail.filename}
            className="rounded-lg px-2.5 py-1 text-sm text-ink-muted transition-colors hover:text-ink"
          >
            Download
          </a>
        </div>
      </div>

      <div className={cn('min-h-0 flex-1', detail.kind === 'html' && !showSource ? 'p-3' : 'overflow-y-auto p-4')}>
        <ArtifactBody
          kind={detail.kind}
          content={detail.content ?? ''}
          title={detail.title}
          showSource={showSource}
        />
      </div>
    </aside>
  )
}

function ArtifactBody({
  kind,
  content,
  title,
  showSource,
}: {
  kind: Artifact['kind']
  content: string
  title: string
  showSource: boolean
}) {
  if (kind === 'html' && !showSource) {
    return <ArtifactFrame html={content} title={title} />
  }

  if (kind === 'markdown') {
    return (
      <div className="prose-sm max-w-none text-sm leading-relaxed text-ink [&_li]:ml-4 [&_li]:list-disc">
        <Markdown>{content}</Markdown>
      </div>
    )
  }

  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-surface-sunken p-3 font-mono text-xs text-ink">
      {content}
    </pre>
  )
}
