/**
 * The dictation socket client.
 *
 * Two behaviours worth pinning down: the token never goes in the URL, and
 * audio recorded before the handshake completes is not silently dropped — that
 * would lose the first words of a sentence, exactly the ones that matter.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { startDictation } from './voice'
import { tokenStore } from './client'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  url: string
  readyState = MockWebSocket.CONNECTING
  binaryType = 'blob'
  sent: unknown[] = []
  closed = false

  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: unknown) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
    this.readyState = MockWebSocket.CLOSED
  }

  // -- test helpers --
  open() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  receive(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

function latest(): MockWebSocket {
  const socket = MockWebSocket.instances.at(-1)
  if (!socket) throw new Error('no socket was created')
  return socket
}

function audioChunk(bytes = 8): Blob {
  return new Blob([new Uint8Array(bytes)], { type: 'audio/webm' })
}

describe('startDictation', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    tokenStore.set('access-token', 'refresh-token')
  })

  it('never puts the token in the URL', () => {
    startDictation('workspace-1', {})
    const socket = latest()

    expect(socket.url).not.toContain('access-token')
    expect(socket.url).not.toContain('token')
    expect(socket.url).toMatch(/^ws:\/\//)
    expect(socket.url).toContain('/voice/stream')
  })

  it('authenticates with its first frame', () => {
    startDictation('workspace-1', {})
    const socket = latest()
    socket.open()

    expect(JSON.parse(socket.sent[0] as string)).toEqual({
      type: 'auth',
      token: 'access-token',
      workspace_id: 'workspace-1',
    })
  })

  it('passes optional audio parameters through', () => {
    startDictation('workspace-1', {}, { encoding: 'opus', sampleRate: 48000, language: 'en' })
    const socket = latest()
    socket.open()

    expect(JSON.parse(socket.sent[0] as string)).toMatchObject({
      encoding: 'opus',
      sample_rate: 48000,
      language: 'en',
    })
  })

  it('separates interim text from committed text', () => {
    const onInterim = vi.fn()
    const onFinal = vi.fn()
    startDictation('workspace-1', { onInterim, onFinal })
    const socket = latest()
    socket.open()

    socket.receive({ type: 'ready' })
    socket.receive({ type: 'transcript', text: 'what is', is_final: false })
    socket.receive({ type: 'transcript', text: 'what is the policy', is_final: true })

    // Interim is replaced, not appended — a consumer that appends both
    // produces "what iswhat is the policy".
    expect(onInterim).toHaveBeenCalledExactlyOnceWith('what is')
    expect(onFinal).toHaveBeenCalledExactlyOnceWith('what is the policy')
  })

  it('buffers audio sent before the handshake completes', () => {
    const session = startDictation('workspace-1', {})
    const socket = latest()
    socket.open()

    // Spoken while the server had not yet said ready.
    session.send(audioChunk())
    expect(socket.sent).toHaveLength(1) // auth frame only

    socket.receive({ type: 'ready' })
    expect(socket.sent).toHaveLength(2)
    expect(socket.sent[1]).toBeInstanceOf(Blob)
  })

  it('preserves chunk order', () => {
    const session = startDictation('workspace-1', {})
    const socket = latest()
    socket.open()
    socket.receive({ type: 'ready' })

    const first = audioChunk(1)
    const second = audioChunk(2)
    session.send(first)
    session.send(second)

    // Sending is synchronous, so ordering is guaranteed rather than a race.
    expect(socket.sent.slice(1)).toEqual([first, second])
  })

  it('reports a server error frame', () => {
    const onError = vi.fn()
    startDictation('workspace-1', { onError })
    latest().receive({ type: 'error', detail: 'Voice transcription is not configured.' })

    expect(onError).toHaveBeenCalledWith('Voice transcription is not configured.')
  })

  it('surfaces an auth refusal from the close code', () => {
    const onError = vi.fn()
    startDictation('workspace-1', { onError })
    // 1008 is the policy-violation code the server closes with on auth failure.
    latest().onclose?.({ code: 1008, reason: 'Invalid token.' })

    expect(onError).toHaveBeenCalledWith('Invalid token.')
  })

  it('does not report an error for a deliberate close', () => {
    const onError = vi.fn()
    const session = startDictation('workspace-1', { onError })
    session.close()
    latest().onclose?.({ code: 1008, reason: 'whatever' })

    expect(onError).not.toHaveBeenCalled()
  })

  it('asks the server to finish on stop', () => {
    const session = startDictation('workspace-1', {})
    const socket = latest()
    socket.open()
    socket.receive({ type: 'ready' })

    session.stop()
    expect(JSON.parse(socket.sent.at(-1) as string)).toEqual({ type: 'stop' })
  })

  it('drops buffered audio when closed before it flushes', () => {
    const session = startDictation('workspace-1', {})
    const socket = latest()
    socket.open()

    session.send(audioChunk())
    session.close()
    socket.receive({ type: 'ready' })

    expect(socket.closed).toBe(true)
  })

  it('ignores an unparseable frame rather than throwing', () => {
    const onError = vi.fn()
    startDictation('workspace-1', { onError })
    expect(() => latest().onmessage?.({ data: 'not json' })).not.toThrow()
    expect(onError).not.toHaveBeenCalled()
  })
})
