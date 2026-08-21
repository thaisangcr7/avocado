/**
 * Claude-style analysis artifact: summary, interactive chart, metrics,
 * data table, and inspectable code — one card that feels like a dashboard
 * panel rather than a raw API dump.
 */

import { useState } from 'react'
import Markdown from 'react-markdown'

import type { AnalysisMetric, AnalysisRun, AnalysisTable } from '@/api/types'
import { Badge, Card } from '@/components/ui/primitives'
import { AuthChartImage } from '@/features/analysis/AuthChartImage'
import { DataChart } from '@/features/analysis/DataChart'
import { VegaChart } from '@/features/analysis/VegaChart'
import { extractChartSeries, summarizeSeries } from '@/features/analysis/chartUtils'
import { cn } from '@/lib/utils'

export function AnalysisArtifact({ run }: { run: AnalysisRun }) {
  const [showCode, setShowCode] = useState(false)
  const [tab, setTab] = useState<'overview' | 'data' | 'method'>('overview')

  if (run.status === 'failed') {
    return (
      <Card className="border-danger/20 p-4">
        <div className="mb-2 flex items-center gap-2">
          <Badge tone="danger">failed</Badge>
          <span className="text-xs text-ink-muted">
            {run.attempt_count} attempt{run.attempt_count === 1 ? '' : 's'}
          </span>
        </div>
        <p className="text-sm text-danger">{run.error_message}</p>
        {run.generated_code && (
          <CodeBlock code={run.generated_code} label="Code that failed" />
        )}
      </Card>
    )
  }

  const tables = run.result_data.tables ?? []
  const scalars = run.result_data.scalars ?? {}
  const presentation = run.result_data.presentation
  const stdout = run.result_data.stdout
  const scalarEntries = Object.entries(scalars)
  const interactiveTable = tables.find((table) => extractChartSeries(table))
  const series = interactiveTable ? extractChartSeries(interactiveTable) : null
  const derived = series ? summarizeSeries(series) : null
  const fallbackMetrics: AnalysisMetric[] =
    scalarEntries.length > 0
      ? scalarEntries.slice(0, 6).map(([label, value]) => ({
          label,
          value: formatScalar(value),
          context: null,
          tone: 'neutral' as const,
        }))
      : derived
        ? [
            metric('Total', derived.total),
            metric('Average', derived.average),
            metric(`Highest · ${derived.highest.label}`, derived.highest.value, 'positive'),
            metric(`Lowest · ${derived.lowest.label}`, derived.lowest.value),
            ...(derived.changePercent === null
              ? []
              : [
                  metric(
                    'Change',
                    `${derived.changePercent >= 0 ? '+' : ''}${derived.changePercent.toFixed(1)}%`,
                    derived.changePercent >= 0 ? 'positive' : 'negative',
                  ),
                ]),
          ]
        : []
  const metrics = presentation?.metrics.length
    ? presentation.metrics
    : fallbackMetrics
  const visualizations = (presentation?.visualizations ?? []).flatMap((visual) => {
    const table = tables[visual.table_index]
    return table ? [{ visual, table }] : []
  })

  return (
    <Card className="animate-in overflow-hidden">
      <div className="border-b border-border-subtle bg-gradient-to-br from-accent-soft/80 to-surface-sunken/40 px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="success">
            {visualizations.length > 0 ? 'Interactive artifact' : 'Artifact'}
          </Badge>
          {run.model_used && <Badge tone="neutral">{run.model_used}</Badge>}
          {run.execution_ms !== null && (
            <span className="text-xs text-ink-muted">{run.execution_ms}ms</span>
          )}
          {run.attempt_count > 1 && (
            <span className="text-xs text-ink-muted">
              self-corrected after {run.attempt_count - 1} retry
            </span>
          )}
        </div>
        <h3 className="mt-2 font-display text-lg font-semibold tracking-tight text-ink text-balance">
          {run.question}
        </h3>
        {run.result_summary && (
          <div className="mt-2 text-sm leading-relaxed text-ink/90 [&_li]:ml-4 [&_li]:list-disc [&_p+p]:mt-2">
            <Markdown>{run.result_summary}</Markdown>
          </div>
        )}
      </div>

      <div className="border-b border-border-subtle px-4 pt-2">
        <nav className="flex gap-5" aria-label="Artifact sections">
          {(['overview', 'data', 'method'] as const).map((candidate) => (
            <button
              key={candidate}
              type="button"
              onClick={() => setTab(candidate)}
              aria-current={tab === candidate ? 'page' : undefined}
              className={cn(
                'border-b-2 px-0.5 py-2 text-xs font-semibold capitalize transition-colors',
                tab === candidate
                  ? 'border-accent text-accent-strong'
                  : 'border-transparent text-ink-muted hover:text-ink',
              )}
            >
              {candidate}
            </button>
          ))}
        </nav>
      </div>

      <div className="space-y-4 p-4 sm:p-5">
        {tab === 'overview' && (
          <>
        {metrics.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {metrics.map((item) => (
              <div
                key={item.label}
                className={cn(
                  'rounded-2xl border px-3 py-3',
                  item.tone === 'positive' && 'border-accent/20 bg-accent-soft/60',
                  item.tone === 'negative' && 'border-danger/20 bg-danger-soft/60',
                  item.tone === 'warning' && 'border-warning/20 bg-warning-soft/60',
                  item.tone === 'neutral' && 'border-border-subtle bg-surface-sunken/50',
                )}
              >
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                  {humanize(item.label)}
                </p>
                <p className="mt-1 font-display text-xl font-semibold tabular-nums text-ink">
                  {item.value}
                </p>
                {item.context && (
                  <p className="mt-1 text-[11px] leading-4 text-ink-muted">
                    {item.context}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {visualizations.length > 0
          ? visualizations.map(({ visual, table }, index) => (
              <VegaChart key={`${visual.title}-${index}`} visual={visual} table={table} />
            ))
          : interactiveTable && <DataChart table={interactiveTable} />}
          </>
        )}

        {tab === 'data' && (
          <>
            {tables.length > 0 ? (
              tables.map((table, index) => <ResultTable key={index} table={table} />)
            ) : (
              <p className="text-sm text-ink-muted">
                This analysis returned a single value rather than a table.
              </p>
            )}
          </>
        )}

        {tab === 'method' && (
          <div className="space-y-3">
            {run.chart_url && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-ink-muted">
                  Original sandbox plot
                </summary>
                <div className="mt-2 overflow-hidden rounded-2xl border border-border-subtle bg-surface p-3">
                  <AuthChartImage
                    runId={run.id}
                    alt={`Chart generated for: ${run.question}`}
                    className="max-h-[360px] w-full object-contain"
                  />
                </div>
              </details>
            )}
            {run.code_explanation && (
              <p className="text-sm leading-relaxed text-ink-muted">
                {run.code_explanation}
              </p>
            )}
          <button
            onClick={() => setShowCode((current) => !current)}
            aria-expanded={showCode}
            className="text-xs font-medium text-accent-strong hover:underline"
          >
            {showCode ? 'Hide' : 'Show'} the code that produced this
          </button>
          {showCode && run.generated_code && (
            <CodeBlock code={run.generated_code} />
          )}
            {stdout && stdout.trim() && (
              <details className="text-xs">
                <summary className="cursor-pointer font-medium text-ink-muted">
                  Raw execution output
                </summary>
                <pre className="mt-2 overflow-x-auto rounded-xl bg-surface-sunken p-3 text-ink">
                  {stdout}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function metric(
  label: string,
  value: unknown,
  tone: AnalysisMetric['tone'] = 'neutral',
): AnalysisMetric {
  return { label, value: formatScalar(value), context: null, tone }
}

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatScalar(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
  }
  if (value === null || value === undefined) return '—'
  return String(value)
}

function CodeBlock({ code, label }: { code: string; label?: string }) {
  return (
    <div className="mt-2">
      {label && <p className="mb-1 text-xs font-medium text-ink-muted">{label}</p>}
      <pre className="overflow-x-auto rounded-xl border border-border-subtle bg-surface-sunken p-3 text-xs leading-relaxed text-ink">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function ResultTable({ table }: { table: AnalysisTable }) {
  function downloadCsv() {
    const escape = (value: unknown) => {
      const text = value === null || value === undefined ? '' : String(value)
      return `"${text.replaceAll('"', '""')}"`
    }
    const csv = [
      table.columns.map(escape).join(','),
      ...table.rows.map((row) => row.map(escape).join(',')),
    ].join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${table.name || 'analysis-result'}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border-subtle">
      <div className="flex items-center justify-between border-b border-border-subtle bg-surface-sunken/60 px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
          Data
        </p>
        <p className="text-xs text-ink-muted">
          {table.rows.length}
          {table.truncated ? ` of ${table.total_rows.toLocaleString()}` : ''} rows
        </p>
        <button
          type="button"
          onClick={downloadCsv}
          className="ml-auto rounded-md px-2 py-1 text-xs font-medium text-accent-strong hover:bg-accent-soft"
        >
          Download CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="px-3 py-2 text-left text-xs font-semibold text-ink"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className={cn(
                  'border-t border-border-subtle',
                  rowIndex % 2 === 1 && 'bg-surface-sunken/30',
                )}
              >
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-3 py-1.5 text-ink">
                    {cell === null || cell === undefined ? (
                      <span className="text-ink-muted/50">—</span>
                    ) : (
                      String(cell)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
