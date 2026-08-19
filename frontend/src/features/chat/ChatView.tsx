/**
 * The chat surface: streamed answers with inline, clickable citations.
 *
 * Streaming is the default path. Sources arrive before the first token, so the
 * reader can see what the answer will be based on while it is still being
 * written — which is also the honest ordering: retrieval genuinely happens
 * first.
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { streamMessage, type StreamSource } from '@/api/stream'
import type { Citation, Message } from '@/api/types'
import { Badge, Button, EmptyState, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { queryKeys, useMessages, useVoiceCapabilities } from '@/hooks/queries'
import { VoiceInput } from '@/features/voice/VoiceInput'
import { cn } from '@/lib/utils'
import { useWorkspaceStore } from '@/stores/workspace'

export function ChatView({
  workspaceId,
  conversationId,
}: {
  workspaceId: string
  conversationId: string | null
}) {
  const { data: messages, isLoading } = useMessages(workspaceId, conversationId)
  const { data: voice } = useVoiceCapabilities()
  const scopedDocumentIds = useWorkspaceStore((state) => state.scopedDocumentIds)
  const queryClient = useQueryClient()

  const [draft, setDraft] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [streamingSources, setStreamingSources] = useState<StreamSource[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  async function handleSend() {
    const question = draft.trim()
    if (!question || !conversationId || isStreaming) return

    setDraft('')
    setError(null)
    setStreamingText('')
    setStreamingSources([])
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
      },
      {
        onSources: setStreamingSources,
        onToken: (text) => setStreamingText((current) => current + text),
        onDone: () => {
          setIsStreaming(false)
          setStreamingText('')
          setStreamingSources([])
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
        },
      },
      controller.signal,
    )
  }

  if (!conversationId) {
    return (
      <EmptyState
        title="No conversation selected"
        description="Start a new conversation to ask a question about this workspace."
      />
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-5 text-ink-muted" />
          </div>
        ) : (messages?.length ?? 0) === 0 && !isStreaming ? (
          <EmptyState
            icon={<span className="text-3xl">🥑</span>}
            title="Ask anything about this workspace"
            description="Answers are grounded in your uploaded documents, with citations you can check."
          />
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            {messages?.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {isStreaming && (
              <StreamingBubble text={streamingText} sources={streamingSources} />
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border-subtle bg-surface-raised px-6 py-4">
        <div className="mx-auto max-w-3xl">
          {error && (
            <div className="mb-3">
              <ErrorNotice message={error} />
            </div>
          )}

          {scopedDocumentIds.length > 0 && (
            <p className="mb-2 text-xs text-ink-muted">
              Searching {scopedDocumentIds.length} selected document
              {scopedDocumentIds.length === 1 ? '' : 's'} only.
            </p>
          )}

          <div className="flex gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends; Shift+Enter is a newline. Standard for chat.
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void handleSend()
                }
              }}
              placeholder="Ask a question about your documents…"
              rows={1}
              disabled={isStreaming}
              className={cn(
                'min-h-[42px] max-h-40 flex-1 resize-y rounded-lg border border-border-subtle',
                'bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted/70',
                'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
                'disabled:bg-surface-sunken',
              )}
            />
            <Button
              onClick={() => void handleSend()}
              loading={isStreaming}
              disabled={!draft.trim()}
              className="self-end"
            >
              Send
            </Button>
          </div>

          {/* Hidden entirely when the server has no STT configured, rather
              than offered as a button that fails when pressed. */}
          {voice?.live_transcription && (
            <div className="mt-2">
              <VoiceInput
                workspaceId={workspaceId}
                disabled={isStreaming}
                onTranscript={(text) =>
                  setDraft((current) => (current ? `${current} ${text}` : text))
                }
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('animate-in', isUser ? 'flex justify-end' : '')}>
      <div className={cn(isUser ? 'max-w-[80%]' : 'w-full')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'bg-accent text-white'
              : 'border border-border-subtle bg-surface-raised text-ink',
          )}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>

        {!isUser && (
          <div className="mt-2 space-y-2">
            {message.citations.length > 0 && (
              <CitationList citations={message.citations} />
            )}

            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
              {/* Always shown, so a user on Auto knows which model answered. */}
              {message.model_used && <Badge tone="neutral">{message.model_used}</Badge>}
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
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-ink-muted">
        Sources ({citations.length})
      </p>
      <ul className="space-y-1.5">
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
                className="w-full rounded-lg border border-border-subtle bg-surface-sunken/60 px-3 py-2 text-left transition-colors hover:bg-surface-sunken"
              >
                <div className="flex items-center gap-2">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded bg-accent-soft text-[10px] font-semibold text-accent-strong">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">
                    {citation.document_name}
                  </span>
                  {location && (
                    <span className="shrink-0 text-[11px] text-ink-muted">{location}</span>
                  )}
                  <span className="shrink-0 text-[11px] text-ink-muted/70">
                    {(citation.score * 100).toFixed(0)}%
                  </span>
                </div>

                {isOpen && (
                  <p className="mt-2 border-t border-border-subtle pt-2 text-xs leading-relaxed text-ink-muted">
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

function StreamingBubble({ text, sources }: { text: string; sources: StreamSource[] }) {
  return (
    <div className="animate-in w-full">
      {sources.length > 0 && (
        <p className="mb-2 text-xs text-ink-muted">
          Reading {sources.length} source{sources.length === 1 ? '' : 's'}…
        </p>
      )}
      <div className="rounded-2xl border border-border-subtle bg-surface-raised px-4 py-3 text-sm leading-relaxed text-ink">
        {text ? (
          <p className="whitespace-pre-wrap">
            {text}
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom" />
          </p>
        ) : (
          <div className="flex items-center gap-2 text-ink-muted">
            <Spinner className="size-3.5" />
            <span className="text-xs">Thinking…</span>
          </div>
        )}
      </div>
    </div>
  )
}
