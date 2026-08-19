/**
 * Record a meeting, or upload one, and have it become searchable.
 *
 * Distinct from dictation: this persists. The transcript becomes a document in
 * the workspace, answerable through the same retrieval path as any file, which
 * is why the status here mirrors the document pipeline's.
 */

import { useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { voiceApi } from '@/api/voice'
import type { VoiceRecording } from '@/api/types'
import { Badge, Button, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { queryKeys, useVoiceRecordings } from '@/hooks/queries'
import { formatRelativeTime } from '@/lib/utils'
import { formatDuration, useAudioRecorder } from './useAudioRecorder'

const STATUS_TONE = {
  pending: 'neutral',
  processing: 'warning',
  ready: 'success',
  failed: 'danger',
} as const

export function RecordingUploader({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient()
  const { data: recordings } = useVoiceRecordings(workspaceId)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const upload = useCallback(
    async (blob: Blob, filename: string) => {
      setUploadError(null)
      setUploading(true)
      try {
        await voiceApi.upload(workspaceId, blob, filename)
        // Both lists change: a new recording, and eventually a new document.
        await queryClient.invalidateQueries({
          queryKey: queryKeys.voiceRecordings(workspaceId),
        })
        await queryClient.invalidateQueries({
          queryKey: queryKeys.documents(workspaceId),
        })
      } catch (error) {
        setUploadError(
          error instanceof ApiError ? error.message : 'The recording could not be uploaded.',
        )
      } finally {
        setUploading(false)
      }
    },
    [workspaceId, queryClient],
  )

  const handleComplete = useCallback(
    (blob: Blob) => {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-')
      const extension = blob.type.includes('mp4') ? 'm4a' : 'webm'
      void upload(blob, `recording-${stamp}.${extension}`)
    },
    [upload],
  )

  const recorder = useAudioRecorder({ onComplete: handleComplete })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant={recorder.isRecording ? 'danger' : 'secondary'}
          onClick={() => (recorder.isRecording ? recorder.stop() : void recorder.start())}
          disabled={uploading || recorder.status === 'requesting'}
        >
          <span aria-hidden="true">{recorder.isRecording ? '■' : '⏺'}</span>
          {recorder.isRecording ? `Stop (${formatDuration(recorder.elapsedMs)})` : 'Record'}
        </Button>

        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
        >
          Upload audio
        </Button>

        {uploading && <Spinner className="size-3.5 text-ink-muted" />}

        <input
          ref={fileInput}
          type="file"
          accept=".mp3,.wav,.m4a,.webm,.ogg,.flac,audio/*"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file, file.name)
            event.target.value = ''
          }}
        />
      </div>

      {recorder.error && <ErrorNotice message={recorder.error} />}
      {uploadError && <ErrorNotice message={uploadError} />}

      {(recordings?.length ?? 0) > 0 && (
        <ul className="space-y-1.5">
          {recordings!.map((recording) => (
            <RecordingRow key={recording.id} recording={recording} />
          ))}
        </ul>
      )}
    </div>
  )
}

function RecordingRow({ recording }: { recording: VoiceRecording }) {
  const busy =
    recording.transcript_status === 'pending' ||
    recording.transcript_status === 'processing'

  return (
    <li className="rounded-lg bg-surface-sunken/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={STATUS_TONE[recording.transcript_status]}>
          {busy && <Spinner className="size-2.5" />}
          {recording.transcript_status}
        </Badge>
        {recording.duration_seconds !== null && (
          <span className="text-xs text-ink-muted">
            {formatDuration(recording.duration_seconds * 1000)}
          </span>
        )}
        <span className="text-xs text-ink-muted/70">
          {formatRelativeTime(recording.created_at)}
        </span>
      </div>

      {recording.transcript_status === 'failed' && recording.error_message && (
        <p className="mt-1 text-xs text-danger">{recording.error_message}</p>
      )}

      {recording.transcript && (
        <p className="mt-1 line-clamp-2 text-xs text-ink-muted">{recording.transcript}</p>
      )}
    </li>
  )
}
