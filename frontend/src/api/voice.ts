/**
 * Voice API: recordings over HTTP, live dictation over a WebSocket.
 *
 * The socket authenticates by sending its token as the first message rather
 * than putting it in the URL. `WebSocket` cannot set an Authorization header,
 * and a query parameter would put a bearer token into access logs, proxy
 * history and browser history.
 */

import { BASE_URL, http, tokenStore } from './client'
import type { VoiceCapabilities, VoiceRecording, VoiceUploadResult } from './types'

export const voiceApi = {
  capabilities: () => http.get<VoiceCapabilities>('/voice/capabilities'),

  list: (workspaceId: string) =>
    http.get<VoiceRecording[]>(`/workspaces/${workspaceId}/voice`),

  get: (workspaceId: string, recordingId: string) =>
    http.get<VoiceRecording>(`/workspaces/${workspaceId}/voice/${recordingId}`),

  upload: (workspaceId: string, recording: Blob, filename: string) => {
    const form = new FormData()
    form.append('file', recording, filename)
    return http.post<VoiceUploadResult>(`/workspaces/${workspaceId}/voice`, form, {
      raw: true,
    })
  },

  remove: (workspaceId: string, recordingId: string) =>
    http.delete<{ message: string }>(`/workspaces/${workspaceId}/voice/${recordingId}`),
}

export interface DictationHandlers {
  onReady?: () => void
  /** Interim text — replaces the previous interim, never appended to it. */
  onInterim?: (text: string) => void
  /** Committed text — safe to append. */
  onFinal?: (text: string) => void
  onError?: (detail: string) => void
  onClose?: () => void
}

export interface DictationSession {
  /** Push an audio chunk. Ignored once the socket is closing. */
  send: (chunk: Blob) => void
  /** Ask the server to finish and flush the last utterance. */
  stop: () => void
  close: () => void
}

function socketUrl(): string {
  // BASE_URL may be relative ("/api/v1"), so resolve against the page origin
  // and swap the scheme — ws for http, wss for https.
  const base = new URL(BASE_URL, window.location.origin)
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  base.pathname = `${base.pathname.replace(/\/$/, '')}/voice/stream`
  return base.toString()
}

export function startDictation(
  workspaceId: string,
  handlers: DictationHandlers,
  options: { encoding?: string; sampleRate?: number; language?: string } = {},
): DictationSession {
  const socket = new WebSocket(socketUrl())
  socket.binaryType = 'arraybuffer'

  // Audio recorded before the socket finished opening would otherwise be
  // dropped — the first words of a sentence, exactly the ones that matter.
  const pending: Blob[] = []
  let ready = false
  let closing = false

  socket.onopen = () => {
    socket.send(
      JSON.stringify({
        type: 'auth',
        token: tokenStore.access ?? '',
        workspace_id: workspaceId,
        ...(options.encoding && { encoding: options.encoding }),
        ...(options.sampleRate && { sample_rate: options.sampleRate }),
        ...(options.language && { language: options.language }),
      }),
    )
  }

  socket.onmessage = (event) => {
    let message: { type: string; text?: string; is_final?: boolean; detail?: string }
    try {
      message = JSON.parse(event.data)
    } catch {
      return
    }

    switch (message.type) {
      case 'ready': {
        ready = true
        handlers.onReady?.()
        // Flush whatever was spoken while the handshake was in flight.
        for (const chunk of pending.splice(0)) forward(chunk)
        break
      }
      case 'transcript':
        if (message.is_final) handlers.onFinal?.(message.text ?? '')
        else handlers.onInterim?.(message.text ?? '')
        break
      case 'done':
        handlers.onClose?.()
        socket.close()
        break
      case 'error':
        handlers.onError?.(message.detail ?? 'Transcription failed.')
        break
    }
  }

  socket.onerror = () => {
    if (!closing) handlers.onError?.('The dictation connection failed.')
  }

  socket.onclose = (event) => {
    // 1008 is the policy-violation code the server uses for auth failures.
    if (!closing && event.code === 1008) {
      handlers.onError?.(event.reason || 'Dictation was refused.')
    }
    handlers.onClose?.()
  }

  function forward(chunk: Blob) {
    if (socket.readyState !== WebSocket.OPEN) return
    // The Blob goes out as-is. Converting via `await chunk.arrayBuffer()`
    // first would make this async, and two chunks awaiting concurrently can
    // then reach the socket out of order — which garbles the audio.
    socket.send(chunk)
  }

  return {
    send(chunk: Blob) {
      if (closing) return
      if (ready) forward(chunk)
      else pending.push(chunk)
    },
    stop() {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'stop' }))
      }
    },
    close() {
      closing = true
      pending.length = 0
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close()
      }
    },
  }
}
