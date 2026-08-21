/**
 * Authenticated chart image.
 *
 * Charts are behind the same Bearer auth as every other endpoint. A bare
 * <img src> cannot send that header, so the browser used to show a broken
 * image. Fetch as a blob with the HTTP client, then display via object URL.
 */

import { useEffect, useState } from 'react'

import { analysisApi } from '@/api/endpoints'
import { Spinner } from '@/components/ui/primitives'

export function AuthChartImage({
  runId,
  alt,
  className,
}: {
  runId: string
  alt: string
  className?: string
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false

    void analysisApi
      .fetchChart(runId)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [runId])

  if (failed) {
    return (
      <p className="rounded-xl border border-border-subtle bg-surface-sunken px-3 py-2 text-xs text-ink-muted">
        Chart could not be loaded.
      </p>
    )
  }

  if (!url) {
    return (
      <div className="flex h-40 items-center justify-center rounded-xl border border-border-subtle bg-surface-sunken/50">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  return <img src={url} alt={alt} className={className} />
}
