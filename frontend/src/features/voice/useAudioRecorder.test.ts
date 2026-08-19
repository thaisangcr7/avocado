/**
 * Microphone capture.
 *
 * The behaviour that matters most is teardown: a microphone left open is a
 * privacy problem and a visibly broken one, since the browser keeps showing
 * the recording indicator.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

import { formatDuration, pickSupportedMimeType, useAudioRecorder } from './useAudioRecorder'

class MockMediaRecorder {
  static instances: MockMediaRecorder[] = []
  static supported = ['audio/webm;codecs=opus', 'audio/webm']

  static isTypeSupported(type: string) {
    return MockMediaRecorder.supported.includes(type)
  }

  state: 'inactive' | 'recording' = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  constructor(
    public stream: MediaStream,
    public options?: { mimeType?: string },
  ) {
    MockMediaRecorder.instances.push(this)
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    this.onstop?.()
  }

  emit(data: Blob) {
    this.ondataavailable?.({ data })
  }
}

function mockTrack() {
  return { stop: vi.fn(), kind: 'audio' }
}

function mockStream(tracks = [mockTrack()]) {
  return { getTracks: () => tracks } as unknown as MediaStream
}

function stubAudioContext() {
  const close = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal(
    'AudioContext',
    class {
      close = close
      createAnalyser() {
        return {
          fftSize: 0,
          frequencyBinCount: 128,
          getByteTimeDomainData: (array: Uint8Array) => array.fill(128),
        }
      }
      createMediaStreamSource() {
        return { connect: vi.fn() }
      }
    },
  )
  return { close }
}

describe('useAudioRecorder', () => {
  beforeEach(() => {
    MockMediaRecorder.instances = []
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  it('starts recording when permission is granted', async () => {
    stubAudioContext()
    const getUserMedia = vi.fn().mockResolvedValue(mockStream())
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    const { result } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())

    expect(result.current.isRecording).toBe(true)
    expect(result.current.error).toBeNull()
    // Echo cancellation and noise suppression matter for dictation accuracy.
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
  })

  it('explains a denied permission as a decision, not a fault', async () => {
    const denied = new DOMException('denied', 'NotAllowedError')
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(denied) },
    })

    const { result } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())

    expect(result.current.status).toBe('error')
    expect(result.current.error).toMatch(/denied/i)
    expect(result.current.isRecording).toBe(false)
  })

  it('distinguishes a missing microphone from a refused one', async () => {
    const missing = new DOMException('none', 'NotFoundError')
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(missing) },
    })

    const { result } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())

    expect(result.current.error).toMatch(/no microphone/i)
  })

  it('reports a browser that cannot record', async () => {
    vi.stubGlobal('navigator', { mediaDevices: undefined })

    const { result } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())

    expect(result.current.error).toMatch(/cannot record/i)
  })

  it('forwards each chunk as it is produced', async () => {
    stubAudioContext()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream()) },
    })
    const onChunk = vi.fn()

    const { result } = renderHook(() => useAudioRecorder({ onChunk }))
    await act(() => result.current.start())

    const chunk = new Blob(['audio'], { type: 'audio/webm' })
    act(() => MockMediaRecorder.instances[0]!.emit(chunk))

    expect(onChunk).toHaveBeenCalledWith(chunk)
  })

  it('ignores empty chunks', async () => {
    stubAudioContext()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream()) },
    })
    const onChunk = vi.fn()

    const { result } = renderHook(() => useAudioRecorder({ onChunk }))
    await act(() => result.current.start())
    act(() => MockMediaRecorder.instances[0]!.emit(new Blob([])))

    expect(onChunk).not.toHaveBeenCalled()
  })

  it('releases the microphone on stop', async () => {
    const { close } = stubAudioContext()
    const track = mockTrack()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream([track])) },
    })

    const { result } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())
    act(() => result.current.stop())

    // Stopping every track is what actually turns the recording indicator off.
    await waitFor(() => expect(track.stop).toHaveBeenCalled())
    expect(close).toHaveBeenCalled()
    expect(result.current.isRecording).toBe(false)
  })

  it('releases the microphone when the component unmounts mid-recording', async () => {
    stubAudioContext()
    const track = mockTrack()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream([track])) },
    })

    const { result, unmount } = renderHook(() => useAudioRecorder())
    await act(() => result.current.start())
    unmount()

    await waitFor(() => expect(track.stop).toHaveBeenCalled())
  })

  it('delivers the complete recording on stop', async () => {
    stubAudioContext()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream()) },
    })
    const onComplete = vi.fn()

    const { result } = renderHook(() => useAudioRecorder({ onComplete }))
    await act(() => result.current.start())
    act(() => MockMediaRecorder.instances[0]!.emit(new Blob(['audio-data'])))
    act(() => result.current.stop())

    expect(onComplete).toHaveBeenCalledOnce()
    expect(onComplete.mock.calls[0]![0]).toBeInstanceOf(Blob)
  })

  it('does not deliver an empty recording', async () => {
    stubAudioContext()
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mockStream()) },
    })
    const onComplete = vi.fn()

    const { result } = renderHook(() => useAudioRecorder({ onComplete }))
    await act(() => result.current.start())
    act(() => result.current.stop())

    expect(onComplete).not.toHaveBeenCalled()
  })
})

describe('pickSupportedMimeType', () => {
  it('picks the first container the browser supports', () => {
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
    expect(pickSupportedMimeType()).toBe('audio/webm;codecs=opus')
  })

  it('falls back to mp4 where webm is unavailable', () => {
    // Safari records mp4 only; passing an unsupported type would throw.
    MockMediaRecorder.supported = ['audio/mp4']
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
    expect(pickSupportedMimeType()).toBe('audio/mp4')
    MockMediaRecorder.supported = ['audio/webm;codecs=opus', 'audio/webm']
  })

  it('returns null where MediaRecorder does not exist', () => {
    vi.stubGlobal('MediaRecorder', undefined)
    expect(pickSupportedMimeType()).toBeNull()
  })
})

describe('formatDuration', () => {
  it.each([
    [0, '0:00'],
    [5_000, '0:05'],
    [65_000, '1:05'],
    [600_000, '10:00'],
  ])('formats %ims as %s', (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected)
  })
})
