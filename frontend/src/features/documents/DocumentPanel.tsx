/**
 * The document sidebar: upload, ingestion status, and retrieval scoping.
 *
 * Status is visible per document because ingestion is asynchronous — a user
 * who uploads a large PDF and immediately asks about it needs to see *why*
 * the answer is missing, not just get nothing.
 */

import { useCallback, useRef, useState, type DragEvent, type ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { Badge, Button, EmptyState, ErrorNotice, Spinner } from '@/components/ui/primitives'
import {
  useDeleteDocument,
  useDocuments,
  useReprocessDocument,
  useUploadDocument,
  useVoiceCapabilities,
} from '@/hooks/queries'
import { RecordingUploader } from '@/features/voice/RecordingUploader'
import { cn, formatBytes, formatRelativeTime } from '@/lib/utils'
import { useWorkspaceStore } from '@/stores/workspace'
import type { Document, DocumentStatus } from '@/api/types'

const STATUS_TONE: Record<DocumentStatus, 'neutral' | 'success' | 'warning' | 'danger'> = {
  pending: 'neutral',
  processing: 'warning',
  ready: 'success',
  failed: 'danger',
}

const TYPE_ICON: Record<string, string> = {
  pdf: '📕',
  docx: '📘',
  xlsx: '📊',
  csv: '📊',
  image: '🖼️',
  text: '📄',
  markdown: '📝',
  audio: '🎙️',
}

const MAX_CONCURRENT_UPLOADS = 3

/**
 * Files split by where they came from.
 *
 * A document dropped into a thread and one the whole team works from are
 * different things to a reader, even though retrieval treats them the same.
 * Collapsing them into one list is what makes a workspace's shelf feel like a
 * junk drawer as it fills.
 *
 * The split only appears when there is something on both sides — a heading
 * over a single group is noise.
 */
function DocumentStores({
  documents,
  conversationId,
  renderRow,
}: {
  documents: Document[]
  conversationId: string | null
  renderRow: (document: Document) => ReactNode
}) {
  const here = conversationId
    ? documents.filter((d) => d.conversation_id === conversationId)
    : []
  const rest = documents.filter((d) => !here.includes(d))

  if (!here.length) {
    return <ul className="space-y-1.5">{rest.map(renderRow)}</ul>
  }

  return (
    <div className="space-y-4">
      <section>
        <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
          In this conversation
        </h4>
        <ul className="space-y-1.5">{here.map(renderRow)}</ul>
      </section>

      {rest.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
            In this space
          </h4>
          <ul className="space-y-1.5">{rest.map(renderRow)}</ul>
        </section>
      )}
    </div>
  )
}

export function DocumentPanel({
  workspaceId,
  conversationId,
  onSelectDocument,
  compactUpload = false,
}: {
  workspaceId: string
  /** Splits the list into this thread's files and the workspace's. */
  conversationId?: string | null
  onSelectDocument: (document: Document) => void
  /** Smaller drop zone when upload also lives in the chat composer. */
  compactUpload?: boolean
}) {
  const { data, isLoading } = useDocuments(workspaceId)
  const { data: voice } = useVoiceCapabilities()
  const upload = useUploadDocument(workspaceId)
  const remove = useDeleteDocument(workspaceId)
  const reprocess = useReprocessDocument(workspaceId)

  const { scopedDocumentIds, toggleScopedDocument, clearScopedDocuments } =
    useWorkspaceStore()

  const [dragging, setDragging] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const documents = data?.items ?? []
  const readyCount = documents.filter((doc) => doc.status === 'ready').length
  const processingCount = documents.filter(
    (doc) => doc.status === 'pending' || doc.status === 'processing',
  ).length
  const failedCount = documents.filter((doc) => doc.status === 'failed').length

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) return
      setUploadError(null)
      const pending = Array.from(files)
      const failures: string[] = []

      // A few parallel uploads are much faster than strict serial mode,
      // while still staying gentle on the API and queue.
      for (let index = 0; index < pending.length; index += MAX_CONCURRENT_UPLOADS) {
        const batch = pending.slice(index, index + MAX_CONCURRENT_UPLOADS)
        const results = await Promise.all(
          batch.map(async (file) => {
            try {
              await upload.mutateAsync(file)
              return null
            } catch (error) {
              return error instanceof ApiError
                ? `${file.name}: ${error.message}`
                : `${file.name}: upload failed.`
            }
          }),
        )

        failures.push(...results.filter((entry): entry is string => Boolean(entry)))
      }

      if (failures.length > 0) {
        const first = failures[0] ?? 'Upload failed.'
        setUploadError(
          failures.length > 1
            ? `${first} (${failures.length - 1} more failed)`
            : first,
        )
      }
    },
    [upload],
  )

  function handleDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    void handleFiles(event.dataTransfer.files)
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">
          {compactUpload ? 'Files' : 'Documents'}
        </h2>
        {scopedDocumentIds.length > 0 && (
          <button
            onClick={clearScopedDocuments}
            className="text-xs font-medium text-accent-strong hover:underline"
          >
            Clear scope ({scopedDocumentIds.length})
          </button>
        )}
      </div>

      <div className="p-3">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={cn(
            'rounded-2xl border-2 border-dashed text-center transition-all',
            compactUpload ? 'px-3 py-3' : 'px-4 py-7',
            dragging
              ? 'scale-[1.01] border-accent bg-accent-soft shadow-[0_0_0_4px_rgba(60,120,70,0.08)]'
              : 'border-border-subtle bg-surface-sunken/40 hover:border-accent/30 hover:bg-accent-soft/40',
          )}
        >
          <input
            ref={fileInput}
            type="file"
            multiple
            className="sr-only"
            onChange={(e) => {
              void handleFiles(e.target.files)
              e.target.value = ''
            }}
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
          />
          {!compactUpload && (
            <p className="text-2xl" aria-hidden="true">
              📎
            </p>
          )}
          <p className={cn('text-sm font-medium text-ink', !compactUpload && 'mt-2')}>
            {compactUpload ? 'Drop or ' : 'Drop files here, or '}
            <button
              onClick={() => fileInput.current?.click()}
              className="font-semibold text-accent-strong hover:underline"
            >
              browse
            </button>
          </p>
          {!compactUpload && (
            <p className="mt-1 text-xs text-ink-muted">
              PDF, Word, Excel, CSV, images, text
            </p>
          )}
          {upload.isPending && (
            <div className="mt-3 flex items-center justify-center gap-2 text-xs text-ink-muted">
              <Spinner className="size-3" />
              Uploading…
            </div>
          )}
        </div>

        {uploadError && (
          <div className="mt-3">
            <ErrorNotice message={uploadError} />
          </div>
        )}

        {voice?.enabled && (
          <div className="mt-3 border-t border-border-subtle pt-3">
            <p className="mb-2 text-xs font-medium text-ink-muted">
              Recordings
            </p>
            <RecordingUploader workspaceId={workspaceId} />
          </div>
        )}

        {documents.length > 0 && (
          <IngestionProgressSummary
            total={documents.length}
            ready={readyCount}
            processing={processingCount}
            failed={failedCount}
          />
        )}
      </div>

      <div className="px-3 pb-3">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="size-5 text-ink-muted" />
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload a spreadsheet to run analysis, or a document to ask questions about it."
          />
        ) : (
          <DocumentStores
            documents={documents}
            conversationId={conversationId ?? null}
            renderRow={(document) => (
              <DocumentRow
                key={document.id}
                document={document}
                scoped={scopedDocumentIds.includes(document.id)}
                onToggleScope={() => toggleScopedDocument(document.id)}
                onSelect={() => onSelectDocument(document)}
                onDelete={() => remove.mutate(document.id)}
                onReprocess={() => reprocess.mutate(document.id)}
              />
            )}
          />
        )}
      </div>
    </div>
  )
}

function IngestionProgressSummary({
  total,
  ready,
  processing,
  failed,
}: {
  total: number
  ready: number
  processing: number
  failed: number
}) {
  const progress = total > 0 ? Math.round((ready / total) * 100) : 0

  return (
    <section className="mt-3 rounded-xl border border-border-subtle/80 bg-surface px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-muted">
          Ingest progress
        </p>
        <p className="text-xs font-medium text-ink-muted">{ready}/{total} ready</p>
      </div>

      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div
          className="h-full rounded-full bg-accent transition-all"
          style={{ width: `${progress}%` }}
          aria-hidden="true"
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent-strong">
          Ready: {ready}
        </span>
        {processing > 0 && (
          <span className="rounded-full bg-warning-soft px-2 py-0.5 font-medium text-warning">
            Processing: {processing}
          </span>
        )}
        {failed > 0 && (
          <span className="rounded-full bg-danger-soft px-2 py-0.5 font-medium text-danger">
            Failed: {failed}
          </span>
        )}
      </div>

      <p className="mt-2 text-xs text-ink-muted">
        {processing > 0
          ? 'Files are still indexing. As soon as they turn ready, answers can cite them.'
          : ready > 0
            ? 'Ready to ask in chat now. Suggestions in the center pane adapt to these files.'
            : 'No file is ready yet. Upload a document or spreadsheet to begin.'}
      </p>
    </section>
  )
}

function DocumentRow({
  document,
  scoped,
  onToggleScope,
  onSelect,
  onDelete,
  onReprocess,
}: {
  document: Document
  scoped: boolean
  onToggleScope: () => void
  onSelect: () => void
  onDelete: () => void
  onReprocess: () => void
}) {
  const isAnalysable = document.doc_type === 'xlsx' || document.doc_type === 'csv'
  const busy = document.status === 'pending' || document.status === 'processing'

  return (
    <li
      className={cn(
        'group rounded-lg border px-3 py-2.5 transition-colors',
        scoped
          ? 'border-accent bg-accent-soft'
          : 'border-transparent bg-surface-sunken/60 hover:bg-surface-sunken',
      )}
    >
      <div className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={scoped}
          onChange={onToggleScope}
          className="mt-1 size-3.5 accent-[var(--color-accent)]"
          aria-label={`Limit questions to ${document.filename}`}
        />

        <span className="text-base leading-none" aria-hidden="true">
          {TYPE_ICON[document.doc_type] ?? '📄'}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink" title={document.filename}>
            {document.filename}
          </p>

          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge tone={STATUS_TONE[document.status]}>
              {busy && <Spinner className="size-2.5" />}
              {document.status}
            </Badge>
            <span className="text-xs text-ink-muted">
              {formatBytes(document.size_bytes)}
            </span>
            {document.status === 'ready' && document.chunk_count > 0 && (
              <span className="text-xs text-ink-muted">
                {document.chunk_count} chunk{document.chunk_count === 1 ? '' : 's'}
              </span>
            )}
            <span className="text-xs text-ink-muted/70">
              {formatRelativeTime(document.created_at)}
            </span>
          </div>

          {document.status === 'failed' && document.error_message && (
            <p className="mt-1.5 text-xs text-danger">{document.error_message}</p>
          )}

          <div className="mt-2 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            {isAnalysable && document.status === 'ready' && (
              <Button size="sm" variant="secondary" onClick={onSelect} className="h-6 px-2 text-xs">
                Analyse
              </Button>
            )}
            {document.status === 'failed' && (
              <Button size="sm" variant="secondary" onClick={onReprocess} className="h-6 px-2 text-xs">
                Retry
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onDelete} className="h-6 px-2 text-xs">
              Delete
            </Button>
          </div>
        </div>
      </div>
    </li>
  )
}
