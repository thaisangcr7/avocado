/**
 * The microphone control and its live feedback.
 *
 * Speaking into a black box is unnerving, so while recording the user sees
 * three things: a waveform proving the mic is being heard, the elapsed time,
 * and the words as they are recognised.
 *
 * `variant="icon"` is for the chat composer: only the mic control is inlined.
 * Pass `feedbackHost` so the listening strip can render above the composer
 * row instead of stretching it.
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import { startDictation, type DictationSession } from '@/api/voice'
import { Button, Spinner } from '@/components/ui/primitives'
import { formatDuration, useAudioRecorder } from './useAudioRecorder'
import { cn } from '@/lib/utils'

/**
 * A drawn microphone rather than the emoji.
 *
 * An emoji renders in the platform's own colour and weight, so it sat in the
 * composer as a small colour photograph among monochrome controls, and changed
 * shape between operating systems. This inherits currentColor and the button's
 * hover and recording states with it.
 */
function MicGlyph({ recording }: { recording: boolean }) {
  if (recording) {
    return (
      <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true" fill="currentColor">
        <rect x="3" y="3" width="10" height="10" rx="2" />
      </svg>
    )
  }
  return (
    <svg
      viewBox="0 0 16 16"
      className="size-4"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      <rect x="6" y="1.75" width="4" height="7.5" rx="2" />
      <path d="M3.5 7v.75a4.5 4.5 0 0 0 9 0V7" />
      <path d="M8 12.25v2" />
    </svg>
  )
}

export function VoiceInput({
  workspaceId,
  onTranscript,
  disabled,
  variant = 'button',
  feedbackHost,
}: {
  workspaceId: string
  /** Called with committed text as it is recognised, to append to the input. */
  onTranscript: (text: string) => void
  disabled?: boolean
  variant?: 'button' | 'icon'
  /** When set with `variant="icon"`, listening UI portals here. */
  feedbackHost?: RefObject<HTMLElement | null>
}) {
  const [interim, setInterim] = useState('')
  const [streamError, setStreamError] = useState<string | null>(null)
  const [feedbackReady, setFeedbackReady] = useState(false)
  const sessionRef = useRef<DictationSession | null>(null)

  const handleChunk = useCallback((chunk: Blob) => {
    sessionRef.current?.send(chunk)
  }, [])

  const recorder = useAudioRecorder({ onChunk: handleChunk })
  const { isRecording, start, stop, levels, elapsedMs, status, error } = recorder

  const endSession = useCallback(() => {
    sessionRef.current?.stop()
    sessionRef.current?.close()
    sessionRef.current = null
    setInterim('')
  }, [])

  useEffect(() => {
    return () => {
      sessionRef.current?.close()
      sessionRef.current = null
    }
  }, [])

  // The host ref is often filled after first paint; re-check so the portal
  // can attach once the slot exists.
  useEffect(() => {
    setFeedbackReady(Boolean(feedbackHost?.current))
  }, [feedbackHost, isRecording])

  async function handleStart() {
    setStreamError(null)
    setInterim('')

    sessionRef.current = startDictation(workspaceId, {
      onInterim: setInterim,
      onFinal: (text) => {
        setInterim('')
        if (text.trim()) onTranscript(text.trim())
      },
      onError: (detail) => {
        setStreamError(detail)
        stop()
      },
    })

    await start()
  }

  function handleStop() {
    stop()
    endSession()
  }

  const message = streamError ?? error
  const busy = disabled || status === 'requesting'

  const feedback = (
    <>
      {isRecording && (
        <div className="mb-2 flex items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft px-3 py-2">
          <Waveform levels={levels} />
          <span className="shrink-0 font-mono text-xs tabular-nums text-accent-strong">
            {formatDuration(elapsedMs)}
          </span>
          <p className="min-w-0 flex-1 truncate text-sm text-ink-muted" aria-live="polite">
            {interim || 'Listening…'}
          </p>
        </div>
      )}
      {message && (
        <p role="alert" className="mb-2 text-xs text-danger">
          {message}
        </p>
      )}
    </>
  )

  const control =
    variant === 'icon' ? (
      <button
        type="button"
        disabled={busy}
        onClick={() => (isRecording ? handleStop() : void handleStart())}
        aria-label={isRecording ? 'Stop dictation' : 'Dictate a question'}
        aria-pressed={isRecording}
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-xl transition-colors',
          'disabled:cursor-not-allowed disabled:opacity-50',
          isRecording
            ? 'bg-danger-soft text-danger hover:bg-danger hover:text-white'
            : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
        )}
      >
        {status === 'requesting' ? (
          <Spinner className="size-3.5" />
        ) : (
          <MicGlyph recording={isRecording} />
        )}
      </button>
    ) : (
      <div className="flex flex-col gap-1.5">
        {feedback}
        <Button
          type="button"
          variant={isRecording ? 'danger' : 'secondary'}
          size="sm"
          disabled={busy}
          onClick={() => (isRecording ? handleStop() : void handleStart())}
          aria-label={isRecording ? 'Stop dictation' : 'Dictate a question'}
          aria-pressed={isRecording}
          className="self-start"
        >
          {status === 'requesting' ? (
            <Spinner className="size-3.5" />
          ) : (
            <span aria-hidden="true">{isRecording ? '■' : '🎙'}</span>
          )}
          {isRecording ? 'Stop' : 'Speak'}
        </Button>
      </div>
    )

  if (variant === 'icon') {
    const host = feedbackReady ? feedbackHost?.current : null
    return (
      <>
        {host ? createPortal(feedback, host) : null}
        {control}
      </>
    )
  }

  return control
}

function Waveform({ levels }: { levels: number[] }) {
  return (
    <div
      className="flex h-6 shrink-0 items-center gap-[2px]"
      aria-hidden="true"
      data-testid="waveform"
    >
      {levels.map((level, index) => (
        <span
          key={index}
          className={cn(
            'w-[3px] rounded-full bg-accent transition-[height] duration-75',
            level < 0.02 && 'opacity-30',
          )}
          style={{ height: `${Math.max(3, level * 24)}px` }}
        />
      ))}
    </div>
  )
}
