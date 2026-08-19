/**
 * Microphone capture with a live amplitude signal.
 *
 * Two jobs, deliberately in one hook because they share the same MediaStream
 * and must be torn down together:
 *
 * - **Capture** via `MediaRecorder`, producing chunks for upload or streaming.
 * - **Amplitude** via an `AnalyserNode`, so the UI can show that the mic is
 *   actually hearing something. A recorder with no visible feedback is
 *   indistinguishable from a broken one.
 *
 * Every acquired resource — tracks, audio context, animation frame — is
 * released on stop and on unmount. A microphone left open is both a privacy
 * problem and a very visible one, since the browser keeps showing the
 * recording indicator.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderStatus = 'idle' | 'requesting' | 'recording' | 'error'

/** Sampled amplitude history driving the waveform, newest last. */
const WAVEFORM_BARS = 32

/** How often a chunk is emitted while streaming. Small enough to feel live. */
const TIMESLICE_MS = 250

export interface UseAudioRecorderOptions {
  /** Called with each chunk as it is produced — used for live streaming. */
  onChunk?: (chunk: Blob) => void
  /** Called once with the complete recording when capture stops. */
  onComplete?: (recording: Blob) => void
}

export function useAudioRecorder(options: UseAudioRecorderOptions = {}) {
  const { onChunk, onComplete } = options

  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [levels, setLevels] = useState<number[]>(() => new Array(WAVEFORM_BARS).fill(0))
  const [elapsedMs, setElapsedMs] = useState(0)

  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const frameRef = useRef<number | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startedAtRef = useRef<number>(0)

  // Held in refs so the animation loop and recorder callbacks always see the
  // latest handlers without being torn down and rebuilt on every render.
  const onChunkRef = useRef(onChunk)
  const onCompleteRef = useRef(onComplete)
  useEffect(() => {
    onChunkRef.current = onChunk
    onCompleteRef.current = onComplete
  }, [onChunk, onComplete])

  const releaseResources = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
    audioContextRef.current?.close().catch(() => {})
    audioContextRef.current = null
    // Stopping every track is what actually turns the microphone light off.
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    recorderRef.current = null
  }, [])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    } else {
      releaseResources()
      setStatus('idle')
    }
  }, [releaseResources])

  const start = useCallback(async () => {
    if (status === 'recording' || status === 'requesting') return

    setError(null)
    setStatus('requesting')
    chunksRef.current = []

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot record audio.')
      setStatus('error')
      return
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (caught) {
      // A refusal is a decision, not a fault — say so plainly and differently
      // from a device that is missing or already in use.
      const name = (caught as DOMException)?.name
      setError(
        name === 'NotAllowedError'
          ? 'Microphone access was denied. Allow it in your browser settings to use voice.'
          : name === 'NotFoundError'
            ? 'No microphone was found.'
            : 'Could not start the microphone.',
      )
      setStatus('error')
      return
    }

    streamRef.current = stream

    // --- amplitude ---------------------------------------------------------
    try {
      const audioContext = new AudioContext()
      audioContextRef.current = audioContext
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      audioContext.createMediaStreamSource(stream).connect(analyser)

      const samples = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        analyser.getByteTimeDomainData(samples)
        // Root-mean-square around the 128 midpoint gives a stable loudness
        // reading; peak alone flickers far too much to read.
        let sum = 0
        for (const sample of samples) {
          const centred = (sample - 128) / 128
          sum += centred * centred
        }
        const level = Math.min(1, Math.sqrt(sum / samples.length) * 3)

        setLevels((current) => [...current.slice(1), level])
        setElapsedMs(Date.now() - startedAtRef.current)
        frameRef.current = requestAnimationFrame(tick)
      }
      frameRef.current = requestAnimationFrame(tick)
    } catch {
      // Visualisation is a nicety; losing it must not stop the recording.
    }

    // --- capture -----------------------------------------------------------
    const mimeType = pickSupportedMimeType()
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorderRef.current = recorder

    recorder.ondataavailable = (event) => {
      if (event.data.size === 0) return
      chunksRef.current.push(event.data)
      onChunkRef.current?.(event.data)
    }

    recorder.onstop = () => {
      const recording = new Blob(chunksRef.current, {
        type: mimeType || 'audio/webm',
      })
      releaseResources()
      setStatus('idle')
      setLevels(new Array(WAVEFORM_BARS).fill(0))
      if (recording.size > 0) onCompleteRef.current?.(recording)
    }

    startedAtRef.current = Date.now()
    setElapsedMs(0)
    recorder.start(TIMESLICE_MS)
    setStatus('recording')
  }, [status, releaseResources])

  // Navigating away mid-recording must not leave the microphone open.
  useEffect(() => releaseResources, [releaseResources])

  return {
    status,
    error,
    levels,
    elapsedMs,
    isRecording: status === 'recording',
    start,
    stop,
    mimeType: pickSupportedMimeType() || 'audio/webm',
  }
}

/**
 * The first container this browser will actually record.
 *
 * Chrome and Firefox produce webm/opus; Safari only does mp4. Passing an
 * unsupported mimeType to MediaRecorder throws, so it has to be checked rather
 * than assumed.
 */
export function pickSupportedMimeType(): string | null {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ]
  if (typeof MediaRecorder === 'undefined') return null
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) ?? null
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}
