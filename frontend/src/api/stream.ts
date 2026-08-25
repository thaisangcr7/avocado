/**
 * Server-Sent Events for streaming chat turns.
 *
 * `EventSource` cannot be used: it only issues GETs and cannot set an
 * Authorization header. So this reads the `fetch` body stream and parses the
 * SSE framing directly.
 *
 * The parser buffers across chunk boundaries — a network chunk can split an
 * event mid-line, and treating each chunk as a complete frame silently drops
 * tokens under exactly the conditions streaming exists for.
 */

import { BASE_URL, tokenStore } from './client'
import type { AnalysisRun, Citation, ExecutiveReport } from './types'

export interface StreamSource {
  index: number
  document_id: string
  document_name: string
  score: number
}

export interface StreamHandlers {
  onSources?: (sources: StreamSource[]) => void
  onToken?: (text: string) => void
  onAnalysisStarted?: (analysis: {
    document_id: string
    document_name: string
  }) => void
  onAnalysisCompleted?: (analysis: {
    document_id: string
    document_name: string
    run: AnalysisRun
  }) => void
  onReportStarted?: () => void
  onReportCompleted?: (report: ExecutiveReport) => void
  onDone?: (result: { model: string; citations: Citation[]; grounded?: boolean }) => void
  onError?: (detail: string) => void
}

export async function streamMessage(
  workspaceId: string,
  conversationId: string,
  payload: { content: string; document_ids?: string[] },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `${BASE_URL}/workspaces/${workspaceId}/conversations/${conversationId}/messages/stream`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${tokenStore.access ?? ''}`,
      },
      body: JSON.stringify(payload),
      signal,
    },
  )

  if (!response.ok || !response.body) {
    handlers.onError?.('The response could not be started.')
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (frame: string) => {
    let event = 'message'
    const dataLines: string[] = []

    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (dataLines.length === 0) return

    let data: unknown
    try {
      data = JSON.parse(dataLines.join('\n'))
    } catch {
      return
    }

    switch (event) {
      case 'citations':
        handlers.onSources?.((data as { sources: StreamSource[] }).sources)
        break
      case 'token':
        handlers.onToken?.((data as { text: string }).text)
        break
      case 'analysis_started':
        handlers.onAnalysisStarted?.(
          data as { document_id: string; document_name: string },
        )
        break
      case 'analysis_completed':
        handlers.onAnalysisCompleted?.(
          data as {
            document_id: string
            document_name: string
            run: AnalysisRun
          },
        )
        break
      case 'report_started':
        handlers.onReportStarted?.()
        break
      case 'report_completed':
        handlers.onReportCompleted?.((data as { report: ExecutiveReport }).report)
        break
      case 'done':
        handlers.onDone?.(data as { model: string; citations: Citation[]; grounded?: boolean })
        break
      case 'error':
        handlers.onError?.((data as { detail: string }).detail)
        break
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Events are separated by a blank line. Anything after the last
      // separator is a partial event and stays buffered.
      let separator = buffer.indexOf('\n\n')
      while (separator !== -1) {
        dispatch(buffer.slice(0, separator))
        buffer = buffer.slice(separator + 2)
        separator = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer)
  } catch (error) {
    // An abort is the user navigating away, not a failure to report.
    if ((error as Error).name !== 'AbortError') {
      handlers.onError?.('The connection was interrupted.')
    }
  } finally {
    reader.releaseLock()
  }
}
