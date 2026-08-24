/**
 * The chat surface: streamed answers with inline, clickable citations.
 *
 * Streaming is the default path. Sources arrive before the first token, so the
 * reader can see what the answer will be based on while it is still being
 * written — which is also the honest ordering: retrieval genuinely happens
 * first.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Markdown from 'react-markdown'

import { ApiError } from '@/api/client'
import { streamMessage, type StreamSource } from '@/api/stream'
import type { AnalysisRun, Citation, Document, Message, Preset } from '@/api/types'
import { Button, EmptyState, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { ReportArtifact } from '@/features/analysis/ReportArtifact'
import {
  queryKeys,
  useConversations,
  useDocuments,
  useMessages,
  useModels,
  useTools,
  useUploadDocument,
  useVoiceCapabilities,
  useWorkspaces,
  useEnhanceDraft,
} from '@/hooks/queries'
import { ContextGauge } from '@/features/chat/ContextGauge'
import { ConversationHeader } from '@/features/chat/ConversationHeader'
import { ToolsModal } from '@/features/tools/ToolsModal'
import { PresetsModal } from '@/features/presets/PresetsModal'
import { SuggestionsBar } from '@/features/tasks/SuggestionsBar'
import { VoiceInput } from '@/features/voice/VoiceInput'
import { cn } from '@/lib/utils'
import { useWorkspaceStore } from '@/stores/workspace'

export function ChatView({
  workspaceId,
  conversationId,
  onUseDemoWorkspace,
  onOpenTask,
  onOpenAnalysis,
  onStartConversation,
  pendingQuestion,
  onPendingQuestionSent,
}: {
  workspaceId: string
  conversationId: string | null
  onUseDemoWorkspace?: () => void
  onOpenTask?: (taskId: string) => void
  onOpenAnalysis?: (documentId: string, run: AnalysisRun) => void
  /** Opens a new conversation, optionally seeded with a first question. */
  onStartConversation?: (question?: string) => void
  /** A question to ask as soon as this conversation opens. */
  pendingQuestion?: string | null
  onPendingQuestionSent?: () => void
}) {
  const { data: messages, isLoading } = useMessages(workspaceId, conversationId)
  const { data: documents } = useDocuments(workspaceId)
  const { data: voice } = useVoiceCapabilities()
  const { data: models } = useModels()
  const { data: conversations } = useConversations(workspaceId)
  const { data: workspaces } = useWorkspaces()

  // What is actually answering: the workspace's pin, or Auto when it has none.
  const pinned = workspaces?.find((w) => w.id === workspaceId)?.preferred_model ?? null
  const modelLabel = pinned
    ? (models?.models.find((m) => m.id === pinned)?.display_name ?? pinned)
    : 'Auto'
  const scopedDocumentIds = useWorkspaceStore((state) => state.scopedDocumentIds)
  const queryClient = useQueryClient()
  const upload = useUploadDocument(workspaceId)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [draft, setDraft] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [streamingSources, setStreamingSources] = useState<StreamSource[]>([])
  const [analysisDocumentName, setAnalysisDocumentName] = useState<string | null>(null)
  const [reportRunning, setReportRunning] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [presetsOpen, setPresetsOpen] = useState(false)
  // The preset attached to the next message. Held as the whole row rather than
  // the slug so the chip can name it; only the slug is ever sent.
  const [preset, setPreset] = useState<Preset | null>(null)
  // Held so the wand can be undone. Rewriting someone's question without a way
  // back is worse than not offering it.
  const [beforeEnhance, setBeforeEnhance] = useState<string | null>(null)
  const enhance = useEnhanceDraft(workspaceId)

  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Follow the conversation as it grows, including while tokens arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  // Abort an in-flight stream when the user navigates away, or the server
  // keeps generating into a response nobody is reading.
  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [conversationId])

  async function handleSend(explicit?: string) {
    const question = (explicit ?? draft).trim()
    if (!question || !conversationId || isStreaming) return

    if (!explicit) setDraft('')
    setError(null)
    setStreamingText('')
    setStreamingSources([])
    setAnalysisDocumentName(null)
    setReportRunning(false)
    setIsStreaming(true)

    // Show the user's message immediately rather than waiting for the round
    // trip — the request is already on its way.
    queryClient.setQueryData<Message[]>(queryKeys.messages(conversationId), (existing) => [
      ...(existing ?? []),
      {
        id: `pending-${Date.now()}`,
        conversation_id: conversationId,
        role: 'user',
        content: question,
        citations: [],
        failed: false,
        model_used: null,
        input_tokens: null,
        output_tokens: null,
        latency_ms: null,
        created_at: new Date().toISOString(),
      },
    ])

    const controller = new AbortController()
    abortRef.current = controller

    await streamMessage(
      workspaceId,
      conversationId,
      {
        content: question,
        ...(scopedDocumentIds.length > 0 && { document_ids: scopedDocumentIds }),
        // The slash command, never the prompt text: the instruction is read
        // from the row server-side.
        ...(preset && { preset_slug: preset.slug }),
      },
      {
        onSources: setStreamingSources,
        onToken: (text) => setStreamingText((current) => current + text),
        onAnalysisStarted: ({ document_name }) => {
          setAnalysisDocumentName(document_name)
        },
        onAnalysisCompleted: ({ document_id, run }) => {
          onOpenAnalysis?.(document_id, run)
        },
        onReportStarted: () => {
          setReportRunning(true)
        },
        onReportCompleted: () => {
          // The report is persisted on the assistant message; the refetch on
          // `done` renders it in place. Nothing to hold in transient state.
        },
        onDone: () => {
          setIsStreaming(false)
          setStreamingText('')
          setStreamingSources([])
          setAnalysisDocumentName(null)
          setReportRunning(false)
          // Refetch so the optimistic user message is replaced by the real
          // persisted pair, with ids and usage figures.
          void queryClient.invalidateQueries({
            queryKey: queryKeys.messages(conversationId),
          })
          void queryClient.invalidateQueries({
            queryKey: queryKeys.conversations(workspaceId),
          })
        },
        onError: (detail) => {
          setError(detail)
          setIsStreaming(false)
          setStreamingText('')
          setAnalysisDocumentName(null)
          setReportRunning(false)
        },
      },
      controller.signal,
    )
  }

  // A question chosen on the landing pane is sent once the conversation it
  // belongs to exists. Guarded by a ref so a re-render cannot send it twice.
  const sentPendingRef = useRef<string | null>(null)
  const startedPendingRef = useRef<string | null>(null)

  // A guided flow may arrive with only a pending question and no conversation
  // yet. Start one once, then let the send effect below deliver the question.
  useEffect(() => {
    if (!pendingQuestion || conversationId || isStreaming || !onStartConversation) return
    if (startedPendingRef.current === pendingQuestion) return
    startedPendingRef.current = pendingQuestion
    onStartConversation(pendingQuestion)
  }, [pendingQuestion, conversationId, isStreaming, onStartConversation])

  useEffect(() => {
    if (!pendingQuestion) startedPendingRef.current = null
  }, [pendingQuestion])

  useEffect(() => {
    if (!pendingQuestion || !conversationId || isStreaming) return
    if (sentPendingRef.current === conversationId) return
    sentPendingRef.current = conversationId
    onPendingQuestionSent?.()
    void handleSend(pendingQuestion)
    // handleSend is stable enough for this one-shot; re-running on its
    // identity would re-fire the question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, conversationId])

  const voiceFeedbackRef = useRef<HTMLDivElement>(null)

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) return
      setUploadError(null)
      for (const file of Array.from(files)) {
        try {
          await upload.mutateAsync(file)
        } catch (caught) {
          setUploadError(
            caught instanceof ApiError
              ? `${file.name}: ${caught.message}`
              : `${file.name}: upload failed.`,
          )
          break
        }
      }
    },
    [upload],
  )

  function submitDraft() {
    const question = draft.trim()
    if (!question || isStreaming) return
    if (!conversationId) {
      setDraft('')
      onStartConversation?.(question)
      return
    }
    void handleSend()
  }

  const conversation = conversations?.find((c) => c.id === conversationId) ?? null

  return (
    <div className="flex h-full flex-col">
      {conversation && (
        <ConversationHeader
          workspaceId={workspaceId}
          conversation={conversation}
          modelLabel={modelLabel}
        />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        {!conversationId ? (
          <StartHere
            workspaceId={workspaceId}
            onStart={onStartConversation}
            onUseDemoWorkspace={onUseDemoWorkspace}
            onOpenUpload={() => fileInputRef.current?.click()}
          />
        ) : isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-5 text-ink-muted" />
          </div>
        ) : (messages?.length ?? 0) === 0 && !isStreaming ? (
          <EmptyConversationState
            documents={documents?.items ?? []}
            onAsk={(question) => void handleSend(question)}
          />
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {messages?.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {isStreaming && (
              <StreamingBubble
                text={streamingText}
                sources={streamingSources}
                analysisDocumentName={analysisDocumentName}
                reportRunning={reportRunning}
              />
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border-subtle/80 bg-surface-raised/90 px-4 py-4 backdrop-blur-md sm:px-6">
        <div className="mx-auto max-w-3xl">
          <ContextGauge messages={messages} models={models?.models} />

          <SuggestionsBar workspaceId={workspaceId} onOpenTask={onOpenTask} />

          {error && (
            <div className="mb-3">
              <ErrorNotice message={error} />
            </div>
          )}
          {uploadError && (
            <div className="mb-3">
              <ErrorNotice message={uploadError} />
            </div>
          )}

          {beforeEnhance !== null && (
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs text-ink-muted">Question rewritten.</span>
              <button
                type="button"
                onClick={() => {
                  setDraft(beforeEnhance)
                  setBeforeEnhance(null)
                }}
                className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
              >
                Undo
              </button>
            </div>
          )}

          {preset && (
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong">
                /{preset.slug}
              </span>
              <button
                type="button"
                onClick={() => setPreset(null)}
                className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
              >
                Remove
              </button>
            </div>
          )}

          {scopedDocumentIds.length > 0 && (
            <p className="mb-2 text-xs text-ink-muted">
              Searching {scopedDocumentIds.length} selected document
              {scopedDocumentIds.length === 1 ? '' : 's'} only.
            </p>
          )}

          <div ref={voiceFeedbackRef} />

          {/* Two rows: the question gets the full width, and the controls that
              act on it sit beneath rather than squeezing it from both ends. */}
          <div className="rounded-2xl border border-border-subtle bg-surface px-2 pb-1.5 pt-2 shadow-[0_2px_12px_rgba(0,0,0,0.06)] focus-within:border-accent/40 focus-within:ring-2 focus-within:ring-accent/15">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submitDraft()
                }
              }}
              placeholder="Ask a question about your documents…"
              rows={1}
              disabled={isStreaming}
              className={cn(
                'block max-h-40 min-h-[38px] w-full resize-none border-0',
                'bg-transparent px-1.5 py-1 text-sm leading-relaxed text-ink',
                'placeholder:text-ink-muted/70 focus:outline-none focus:ring-0',
                'disabled:opacity-60',
              )}
            />

            <div className="mt-1 flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={upload.isPending || isStreaming}
                aria-label="Attach a document"
                title="Attach a document"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg text-base text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink disabled:opacity-50"
              >
                {upload.isPending ? <Spinner className="size-3.5" /> : '+'}
              </button>

              {conversationId && (
                <ToolsButton
                  workspaceId={workspaceId}
                  conversationId={conversationId}
                  onOpen={() => setToolsOpen(true)}
                />
              )}

              <button
                type="button"
                disabled={!draft.trim() || enhance.isPending || isStreaming}
                onClick={() => {
                  const original = draft
                  enhance.mutate(original, {
                    onSuccess: (result) => {
                      if (!result.changed) return
                      setBeforeEnhance(original)
                      setDraft(result.draft)
                    },
                  })
                }}
                aria-label="Improve this question"
                title="Improve this question"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg text-base text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink disabled:opacity-50"
              >
                {enhance.isPending ? <Spinner className="size-3.5" /> : '✦'}
              </button>

              <button
                type="button"
                onClick={() => setPresetsOpen(true)}
                aria-label="Presets"
                title="Presets"
                className="flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
              >
                <span className="text-base leading-none">/</span>
                Presets
              </button>

              <div className="flex-1" />

            {voice?.live_transcription && (
              <VoiceInput
                workspaceId={workspaceId}
                disabled={isStreaming}
                variant="icon"
                feedbackHost={voiceFeedbackRef}
                onTranscript={(text) =>
                  setDraft((current) => (current ? `${current} ${text}` : text))
                }
              />
            )}

              <button
                type="button"
                onClick={submitDraft}
                disabled={!draft.trim() || isStreaming}
                aria-label="Send"
                title="Send"
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
                  draft.trim() && !isStreaming
                    ? 'bg-accent text-white hover:bg-accent-strong'
                    : 'bg-surface-sunken text-ink-muted',
                )}
              >
                {isStreaming ? <Spinner className="size-3.5" /> : '↑'}
              </button>
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="sr-only"
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
            onChange={(e) => {
              void handleFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      {presetsOpen && (
        <PresetsModal
          onClose={() => setPresetsOpen(false)}
          onApply={(chosen) => {
            setPreset(chosen)
            setPresetsOpen(false)
          }}
        />
      )}

      {toolsOpen && conversationId && (
        <ToolsModal
          workspaceId={workspaceId}
          conversationId={conversationId}
          onClose={() => setToolsOpen(false)}
        />
      )}
    </div>
  )
}

/**
 * The landing pane when nothing is open yet.
 *
 * Previously a dead end: it said to start a conversation while the button to
 * do so lived in another column. It now starts one, and offers openings drawn
 * from the documents actually present — a suggested question that returns
 * "nothing here answers that" is worse than no suggestion at all.
 */
function StartHere({
  workspaceId,
  onStart,
  onUseDemoWorkspace,
  onOpenUpload,
}: {
  workspaceId: string
  onStart?: (question?: string) => void
  onUseDemoWorkspace?: () => void
  onOpenUpload?: () => void
}) {
  const { data: documents } = useDocuments(workspaceId)
  const ready = documents?.items.filter((doc) => doc.status === 'ready') ?? []

  if (!ready.length) {
    return (
      <div className="flex h-full justify-center overflow-y-auto px-4 py-10 sm:px-6">
        <div className="animate-in-slow my-auto w-full max-w-2xl space-y-6">
          <div className="space-y-2 text-center">
            <div
              className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-accent-soft text-2xl shadow-[0_6px_20px_rgba(40,90,50,0.1)]"
              aria-hidden="true"
            >
              ✨
            </div>
            <h2 className="font-display text-2xl font-semibold tracking-tight text-ink text-balance">
              Nothing to ask about yet
            </h2>
            <p className="text-sm leading-relaxed text-ink-muted text-balance">
              Grounded answers come from files in this Space. Start with demo data or
              upload your own documents to generate cited answers and computed analysis.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={onUseDemoWorkspace}
              className="group rounded-2xl border border-border-subtle/80 bg-surface-raised/90 p-4 text-left shadow-[0_1px_2px_rgba(30,50,30,0.04)] transition-all hover:-translate-y-0.5 hover:border-accent/35 hover:shadow-[0_8px_20px_rgba(40,90,50,0.08)]"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
                Start with demo workspace
              </p>
              <p className="mt-1.5 text-sm leading-snug text-ink">
                Open pre-seeded files and run a guided question flow in seconds.
              </p>
            </button>

            <button
              type="button"
              onClick={onOpenUpload}
              className="group rounded-2xl border border-border-subtle/80 bg-surface-raised/90 p-4 text-left shadow-[0_1px_2px_rgba(30,50,30,0.04)] transition-all hover:-translate-y-0.5 hover:border-accent/35 hover:shadow-[0_8px_20px_rgba(40,90,50,0.08)]"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
                Upload my files
              </p>
              <p className="mt-1.5 text-sm leading-snug text-ink">
                Add PDFs, docs, and spreadsheets to get cited answers and report-ready insights.
              </p>
            </button>
          </div>
        </div>
      </div>
    )
  }

  const spreadsheets = ready.filter(
    (doc) => doc.doc_type === 'xlsx' || doc.doc_type === 'csv',
  )
  const limited = buildOpenings(ready).slice(0, 6)

  return (
    <div className="flex h-full justify-center overflow-y-auto px-4 py-10 sm:px-6">
      <div className="animate-in-slow my-auto w-full max-w-lg space-y-7">
        <div className="space-y-3 text-center">
          <div
            className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-accent-soft text-2xl shadow-[0_6px_20px_rgba(40,90,50,0.1)]"
            aria-hidden="true"
          >
            🥑
          </div>
          <h2 className="font-display text-2xl font-semibold tracking-tight text-ink text-balance">
            What do you want to know?
          </h2>
          <p className="text-sm leading-relaxed text-ink-muted text-balance">
            {ready.length} document{ready.length === 1 ? '' : 's'} ready
            {spreadsheets.length > 0
              ? ` · ${spreadsheets.length} spreadsheet${spreadsheets.length === 1 ? '' : 's'} for analysis`
              : ''}
            . Suggestions match what you uploaded.
          </p>
        </div>

        <div className="animate-stagger space-y-2.5">
          {limited.map((opening) => (
            <button
              key={opening.question}
              type="button"
              onClick={() => onStart?.(opening.question)}
              className="group flex w-full items-start gap-3 rounded-2xl border border-border-subtle/80 bg-surface-raised/90 px-4 py-3.5 text-left shadow-[0_1px_2px_rgba(30,50,30,0.04)] transition-all hover:-translate-y-0.5 hover:border-accent/35 hover:shadow-[0_8px_20px_rgba(40,90,50,0.08)]"
            >
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-xs font-semibold text-accent-strong transition-colors group-hover:bg-accent group-hover:text-white">
                →
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[11px] font-semibold uppercase tracking-wide text-accent-strong">
                  {opening.label}
                  <span className="ml-2 font-medium normal-case tracking-normal text-ink-muted/70">
                    {opening.hint}
                  </span>
                </span>
                <span className="mt-0.5 block text-sm leading-snug text-ink">
                  {opening.question}
                </span>
              </span>
            </button>
          ))}
        </div>

        <div className="text-center">
          <Button variant="secondary" size="sm" onClick={() => onStart?.()}>
            Or start a blank conversation
          </Button>
        </div>
      </div>
    </div>
  )
}

function EmptyConversationState({
  documents,
  onAsk,
}: {
  documents: Document[]
  onAsk: (question: string) => void
}) {
  const ready = documents.filter((doc) => doc.status === 'ready')
  const processing = documents.filter(
    (doc) => doc.status === 'pending' || doc.status === 'processing',
  )

  if (!ready.length) {
    if (processing.length > 0) {
      return (
        <EmptyState
          icon={<span className="text-2xl">⏳</span>}
          title="Files are still getting ready"
          description={`Grounded answers start once processing finishes. ${processing.length} file${processing.length === 1 ? '' : 's'} ${processing.length === 1 ? 'is' : 'are'} still being prepared for retrieval or analysis.`}
        />
      )
    }

    return (
      <EmptyState
        icon={<span className="text-2xl">🥑</span>}
        title="Ask anything about this Space"
        description="Answers are grounded in your uploaded documents, with citations you can check. Upload a file or switch to a demo workspace to get started."
      />
    )
  }

  const openings = buildOpenings(ready).slice(0, 4)
  const spreadsheetCount = ready.filter(
    (doc) => doc.doc_type === 'xlsx' || doc.doc_type === 'csv',
  ).length

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-2xl border border-border-subtle/80 bg-surface-raised/90 px-5 py-4 shadow-[0_1px_2px_rgba(30,50,30,0.04)]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent-strong">
            Ready to ask
          </span>
          <p className="text-sm text-ink-muted">
            {ready.length} document{ready.length === 1 ? '' : 's'} ready
            {spreadsheetCount > 0
              ? `, including ${spreadsheetCount} spreadsheet${spreadsheetCount === 1 ? '' : 's'} for analysis.`
              : '.'}
          </p>
        </div>
      </div>

      <div className="space-y-2.5">
        {openings.map((opening) => (
          <button
            key={opening.question}
            type="button"
            onClick={() => onAsk(opening.question)}
            className="group flex w-full items-start gap-3 rounded-2xl border border-border-subtle/80 bg-surface-raised/90 px-4 py-3.5 text-left shadow-[0_1px_2px_rgba(30,50,30,0.04)] transition-all hover:-translate-y-0.5 hover:border-accent/35 hover:shadow-[0_8px_20px_rgba(40,90,50,0.08)]"
          >
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-xs font-semibold text-accent-strong transition-colors group-hover:bg-accent group-hover:text-white">
              →
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[11px] font-semibold uppercase tracking-wide text-accent-strong">
                {opening.label}
                <span className="ml-2 font-medium normal-case tracking-normal text-ink-muted/70">
                  {opening.hint}
                </span>
              </span>
              <span className="mt-0.5 block text-sm leading-snug text-ink">
                {opening.question}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function buildOpenings(ready: Document[]) {
  const spreadsheets = ready.filter(
    (doc) => doc.doc_type === 'xlsx' || doc.doc_type === 'csv',
  )
  const textDocs = ready.filter(
    (doc) => doc.doc_type !== 'xlsx' && doc.doc_type !== 'csv',
  )
  const policyLike = textDocs.find((doc) =>
    /policy|handbook|pto|leave|hr|process|sop/i.test(doc.filename),
  )
  const primaryText = policyLike ?? textDocs[0]
  const primarySheet = spreadsheets[0]
  const openings: { label: string; question: string; hint: string }[] = []

  if (primaryText) {
    openings.push({
      label: 'Open a file',
      hint: primaryText.filename,
      question: `What is in ${primaryText.filename}?`,
    })
  } else if (primarySheet) {
    openings.push({
      label: 'Open a file',
      hint: primarySheet.filename,
      question: `What columns and measures are in ${primarySheet.filename}?`,
    })
  }

  if (textDocs.length > 1) {
    openings.push({
      label: 'Across the corpus',
      hint: `${textDocs.length} documents`,
      question: `Summarise the key points across these ${textDocs.length} documents.`,
    })
  }

  if (policyLike || textDocs.some((doc) => /policy|handbook|hr/i.test(doc.filename))) {
    openings.push({
      label: 'Find a policy',
      hint: 'Cited answer',
      question: 'What policies does this Space define?',
    })
    if (policyLike && /pto|leave|vacation|time.?off/i.test(policyLike.filename)) {
      openings.push({
        label: 'Semantic check',
        hint: 'No shared keywords',
        question:
          "If I don't use all my paid days off this year, how many roll into next year?",
      })
    }
  } else if (textDocs.length > 0) {
    openings.push({
      label: 'Key takeaways',
      hint: 'Cited answer',
      question: `What are the most important rules or decisions in ${primaryText!.filename}?`,
    })
  }

  if (primarySheet) {
    openings.push({
      label: 'Analyse data',
      hint: primarySheet.filename,
      question: `What stands out in ${primarySheet.filename}?`,
    })

    openings.push({
      label: 'Executive report',
      hint: 'Template',
      question:
        'Create an executive summary with the top KPIs, biggest changes, and three risks to watch.',
    })
    openings.push({
      label: 'KPI review',
      hint: 'Template',
      question:
        'Generate a KPI report: trend, variance, potential root causes, and suggested follow-up actions.',
    })
    openings.push({
      label: 'Dashboard narrative',
      hint: 'Template',
      question:
        'Write a dashboard-style narrative with section headings: performance, anomalies, forecast, and actions.',
    })
  }

  return openings
}

/**
 * An assistant answer, rendered as the markdown the model actually writes.
 *
 * The models emit bold, italics and lists routinely, so rendering the raw
 * string left `**five days**` on screen — the exact figure a reader is looking
 * for, wrapped in punctuation. Markdown is rendered to React elements rather
 * than injected as HTML, so document text reaching this component through a
 * model response can never become markup.
 */
/**
 * Opens the tool picker, carrying the active count.
 *
 * The badge is the whole point of putting it here: enabled tools are spent
 * context on every message, so how many are on belongs next to the box where
 * messages are written, not buried in a settings screen.
 */
function ToolsButton({
  workspaceId,
  conversationId,
  onOpen,
}: {
  workspaceId: string
  conversationId: string
  onOpen: () => void
}) {
  const { data: selection } = useTools(workspaceId, conversationId)
  const count = selection?.enabled_count ?? 0

  return (
    <button
      type="button"
      onClick={onOpen}
      title="Tools and integrations"
      className="mb-1 flex shrink-0 items-center gap-1.5 self-end rounded-lg px-2 py-1.5 text-xs text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
    >
      <span>Tools</span>
      {count > 0 && (
        <span className="rounded-full bg-accent px-1.5 py-px text-[10px] font-medium text-white">
          {count}
        </span>
      )}
    </button>
  )
}

function AnswerBody({ content }: { content: string }) {
  return (
    <div className="space-y-3 text-[15px] leading-7 text-ink [&_blockquote]:border-l-2 [&_blockquote]:border-accent/40 [&_blockquote]:pl-4 [&_blockquote]:text-ink-muted [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-5 [&_li]:pl-1 [&_ol]:list-decimal [&_ol]:space-y-1.5 [&_ul]:list-disc [&_ul]:space-y-1.5">
      <Markdown
        components={{
          p: ({ children }) => <p>{children}</p>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          code: ({ children }) => (
            <code className="rounded-md bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.88em]">
              {children}
            </code>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="underline underline-offset-2"
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)

  async function copyAnswer() {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={cn('animate-in', isUser ? 'flex justify-end' : 'group flex gap-3')}>
      {!isUser && (
        <div
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-sm"
          aria-hidden="true"
        >
          🥑
        </div>
      )}
      <div className={cn(isUser ? 'max-w-[80%]' : 'min-w-0 flex-1')}>
        {!isUser && !message.failed && (
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-ink">Avocado</span>
            {message.model_used && (
              <span className="text-[11px] text-ink-muted">{message.model_used}</span>
            )}
          </div>
        )}
        <div
          className={cn(
            isUser && 'rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed',
            isUser
              ? 'bg-surface-sunken text-ink'
              : message.failed
                ? // Rendered as what it is — a turn that did not produce an
                  // answer — rather than as if the model had said this.
                  'rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-danger'
                : 'text-ink',
          )}
        >
          {message.failed && (
            <p className="mb-1 text-xs font-medium uppercase tracking-wide">
              Could not answer
            </p>
          )}
          {isUser || message.failed ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <AnswerBody content={message.content} />
          )}
        </div>

        {!isUser && !message.failed && message.report_artifact && (
          <ReportArtifact report={message.report_artifact} />
        )}

        {!isUser && !message.failed && (
          <div className="mt-4 space-y-3">
            {message.citations.length > 0 && (
              <CitationList citations={message.citations} />
            )}

            <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
              <button
                type="button"
                onClick={() => void copyAnswer()}
                className="rounded-md px-1.5 py-1 font-medium hover:bg-surface-sunken hover:text-ink"
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
              {message.latency_ms ? <span>{message.latency_ms}ms</span> : null}
              {message.output_tokens ? (
                <span>{message.output_tokens} tokens out</span>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-ink">
        Sources ({citations.length})
      </p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {citations.map((citation, index) => {
          const isOpen = expanded === citation.chunk_id
          const location = [
            citation.page && `page ${citation.page}`,
            citation.sheet && `sheet ${citation.sheet}`,
            citation.section && citation.section,
          ]
            .filter(Boolean)
            .join(' · ')

          return (
            <li key={citation.chunk_id}>
              <button
                onClick={() => setExpanded(isOpen ? null : citation.chunk_id)}
                aria-expanded={isOpen}
                className="h-full w-full rounded-xl border border-border-subtle bg-surface-raised px-3 py-2.5 text-left shadow-[0_1px_2px_rgba(30,50,30,0.03)] transition-colors hover:border-accent/40 hover:bg-accent-soft/30"
              >
                <div className="flex items-center gap-2">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-accent-soft text-[10px] font-semibold text-accent-strong">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">
                    {citation.document_name}
                  </span>
                  {location && (
                    <span className="shrink-0 text-[11px] text-ink-muted">{location}</span>
                  )}
                </div>

                {isOpen && (
                  <p className="mt-2 border-t border-border-subtle pt-2 text-xs leading-5 text-ink-muted">
                    {citation.snippet}
                  </p>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function StreamingBubble({
  text,
  sources,
  analysisDocumentName,
  reportRunning,
}: {
  text: string
  sources: StreamSource[]
  analysisDocumentName: string | null
  reportRunning: boolean
}) {
  return (
    <div className="animate-in flex gap-3">
      <div
        className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-sm"
        aria-hidden="true"
      >
        🥑
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-2 text-xs font-semibold text-ink">Avocado</p>
        {sources.length > 0 && (
          <p className="mb-3 flex items-center gap-2 text-xs text-ink-muted">
            <span className="size-1.5 animate-pulse-soft rounded-full bg-accent" />
            Read {sources.length} source{sources.length === 1 ? '' : 's'} · writing answer…
          </p>
        )}
        <div className="text-ink">
          {text ? (
            // Rendered the same way as a finished answer, so the text does not
            // visibly reflow the moment the stream completes.
            <div className="relative">
              <AnswerBody content={text} />
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse-soft bg-accent align-text-bottom" />
            </div>
          ) : (
            <div className="flex items-center gap-2 text-ink-muted">
              <Spinner className="size-3.5" />
              <span className="text-xs">
                {reportRunning
                  ? 'Computing KPIs across every dataset and composing the report…'
                  : analysisDocumentName
                    ? `Analyzing every row in ${analysisDocumentName}…`
                    : 'Thinking…'}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
