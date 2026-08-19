/**
 * The microphone button and its live feedback.
 *
 * Speaking into a black box is unnerving, so while recording the user sees
 * three things: a waveform proving the mic is being heard, the elapsed time,
 * and the words as they are recognised. Interim text is shown in a lighter
 * weight because it will be revised — presenting it identically to committed
 * text makes the transcript look like it is glitching.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { startDictation, type DictationSession } from '@/api/voice'
import { Button, Spinner } from '@/components/ui/primitives'
import { formatDuration, useAudioRecorder } from './useAudioRecorder'
import { cn } from '@/lib/utils'

export function VoiceInput({
  workspaceId,
  onTranscript,
  disabled,
}: {
  workspaceId: string
  /** Called with committed text as it is recognised, to append to the input. */
  onTranscript: (text: string) => void
  disabled?: boolean
}) {
  const [interim, setInterim] = useState('')
  const [streamError, setStreamError] = useState<string | null>(null)
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

  // A component unmounting mid-dictation must not leave a socket open.
  useEffect(() => {
    return () => {
      sessionRef.current?.close()
      sessionRef.current = null
    }
  }, [])

  async function handleStart() {
    setStreamError(null)
    setInterim('')

    sessionRef.current = startDictation(workspaceId, {
      onInterim: setInterim,
      onFinal: (text) => {
        // Final text supersedes whatever interim was showing; clearing it
        // first prevents the same words appearing twice for a frame.
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

  return (
    <div className="flex flex-col gap-1.5">
      {isRecording && (
        <div className="flex items-center gap-3 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2">
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
        <p role="alert" className="text-xs text-danger">
          {message}
        </p>
      )}

      <Button
        type="button"
        variant={isRecording ? 'danger' : 'secondary'}
        size="sm"
        disabled={disabled || status === 'requesting'}
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
          // A floor keeps the bars visible as a baseline rather than
          // collapsing the whole waveform to nothing between words.
          style={{ height: `${Math.max(3, level * 24)}px` }}
        />
      ))}
    </div>
  )
}
