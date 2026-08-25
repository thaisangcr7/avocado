/**
 * SSE parsing.
 *
 * The case that matters is a network chunk splitting an event mid-frame:
 * treating each chunk as a complete event silently drops tokens under exactly
 * the conditions streaming exists for.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { streamMessage } from './stream'
import { tokenStore } from './client'

function bodyFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

function mockStream(chunks: string[], ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok,
      body: ok ? bodyFrom(chunks) : null,
    }),
  )
}

const HANDLERS = () => ({
  onSources: vi.fn(),
  onToken: vi.fn(),
  onDone: vi.fn(),
  onError: vi.fn(),
})

describe('streamMessage', () => {
  beforeEach(() => {
    tokenStore.set('access-token', 'refresh-token')
  })

  it('dispatches sources, tokens and done in order', async () => {
    const handlers = HANDLERS()
    mockStream([
      'event: citations\ndata: {"sources":[{"index":1,"document_id":"d1","document_name":"a.pdf","score":0.9}]}\n\n',
      'event: token\ndata: {"text":"Hello "}\n\n',
      'event: token\ndata: {"text":"world"}\n\n',
      'event: done\ndata: {"model":"claude-opus-5","citations":[],"grounded":true}\n\n',
    ])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onSources).toHaveBeenCalledWith([
      { index: 1, document_id: 'd1', document_name: 'a.pdf', score: 0.9 },
    ])
    expect(handlers.onToken).toHaveBeenCalledTimes(2)
    expect(handlers.onDone).toHaveBeenCalledWith({
      model: 'claude-opus-5',
      citations: [],
      grounded: true,
    })
    expect(handlers.onError).not.toHaveBeenCalled()
  })

  it('reassembles an event split across chunk boundaries', async () => {
    const handlers = HANDLERS()
    // The frame is cut in three places, including mid-JSON.
    mockStream(['event: tok', 'en\ndata: {"te', 'xt":"split"}\n\n'])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onToken).toHaveBeenCalledExactlyOnceWith('split')
  })

  it('handles several events arriving in one chunk', async () => {
    const handlers = HANDLERS()
    mockStream([
      'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n',
    ])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onToken).toHaveBeenCalledTimes(2)
    expect(handlers.onToken).toHaveBeenNthCalledWith(1, 'a')
    expect(handlers.onToken).toHaveBeenNthCalledWith(2, 'b')
  })

  it('surfaces a server-sent error event', async () => {
    const handlers = HANDLERS()
    mockStream(['event: error\ndata: {"detail":"The model is unavailable."}\n\n'])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onError).toHaveBeenCalledWith('The model is unavailable.')
  })

  it('reports a failed response instead of hanging', async () => {
    const handlers = HANDLERS()
    mockStream([], false)

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onError).toHaveBeenCalled()
    expect(handlers.onToken).not.toHaveBeenCalled()
  })

  it('ignores a malformed data payload rather than throwing', async () => {
    const handlers = HANDLERS()
    mockStream([
      'event: token\ndata: {not json}\n\n',
      'event: token\ndata: {"text":"ok"}\n\n',
    ])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    expect(handlers.onToken).toHaveBeenCalledExactlyOnceWith('ok')
  })

  it('sends the bearer token', async () => {
    const handlers = HANDLERS()
    mockStream(['event: done\ndata: {"model":"m","citations":[]}\n\n'])

    await streamMessage('w1', 'c1', { content: 'hi' }, handlers)

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    const init = call?.[1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe(
      'Bearer access-token',
    )
  })
})
