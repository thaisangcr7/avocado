import { useEffect, useRef, useState } from 'react'
import type { Result } from 'vega-embed'

import type { AnalysisTable, AnalysisVisualization } from '@/api/types'
import { Spinner } from '@/components/ui/primitives'
import { buildVegaSpec } from '@/features/analysis/vegaSpec'

export function VegaChart({
  visual,
  table,
}: {
  visual: AnalysisVisualization
  table: AnalysisTable
}) {
  const host = useRef<HTMLDivElement>(null)
  const result = useRef<Result | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')

    const element = host.current
    if (!element) return

    void import('vega-embed')
      .then(({ default: embed }) =>
        embed(element, buildVegaSpec(visual, table), {
          actions: {
            export: { svg: true, png: true },
            source: false,
            compiled: false,
            editor: false,
          },
          renderer: 'svg',
          mode: 'vega-lite',
          tooltip: true,
        }),
      )
      .then((embedded) => {
        if (cancelled) {
          embedded.finalize()
          return
        }
        result.current = embedded
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('failed')
      })

    return () => {
      cancelled = true
      result.current?.finalize()
      result.current = null
      element.replaceChildren()
    }
  }, [table, visual])

  return (
    <div className="relative min-h-80 overflow-hidden rounded-2xl border border-border-subtle bg-surface p-3">
      {status === 'loading' && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface/80">
          <Spinner className="size-5 text-ink-muted" />
        </div>
      )}
      {status === 'failed' && (
        <div className="flex min-h-72 items-center justify-center px-6 text-center text-sm text-ink-muted">
          This visualization could not be rendered. The computed data remains
          available in the Data tab.
        </div>
      )}
      <div
        ref={host}
        className={status === 'failed' ? 'hidden' : 'w-full [&_.vega-embed]:w-full [&_svg]:max-w-full'}
      />
    </div>
  )
}
