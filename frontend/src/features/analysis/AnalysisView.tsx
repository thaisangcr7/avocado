/**
 * The analysis surface.
 *
 * The generated program is shown, not hidden. That is the whole point of the
 * feature: a computed answer you can check beats a plausible answer you
 * cannot. The code, the result and the chart are all part of one artifact.
 */

import { useState } from 'react'

import { ApiError } from '@/api/client'
import { analysisApi } from '@/api/endpoints'
import type { AnalysisRun, AnalysisTable, DocumentDetail } from '@/api/types'
import { Badge, Button, Card, EmptyState, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { useAnalysisRuns, useDocument, useRunAnalysis } from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'

const EXAMPLE_QUESTIONS = [
  'What is the total by category?',
  'Show the month-over-month trend',
  'Which rows are outliers?',
  'Summarise the distribution of the numeric columns',
]

export function AnalysisView({
  documentId,
  onClose,
}: {
  documentId: string
  onClose: () => void
}) {
  const { data: document, isLoading } = useDocument(documentId)
  const { data: history } = useAnalysisRuns(documentId)
  const runAnalysis = useRunAnalysis(documentId)

  const [question, setQuestion] = useState('')
  const [tableId, setTableId] = useState<string | undefined>(undefined)
  const [activeRun, setActiveRun] = useState<AnalysisRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    const text = question.trim()
    if (!text) return
    setError(null)
    try {
      const run = await runAnalysis.mutateAsync({ question: text, table_id: tableId })
      setActiveRun(run)
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'The analysis could not be run.',
      )
    }
  }

  if (isLoading || !document) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  const tables = document.tables ?? []

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold text-ink">{document.filename}</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            Ask a question and Avocado will write and run the code to answer it.
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="mx-auto w-full max-w-4xl space-y-6 px-6 py-6">
        <SchemaSummary document={document} />

        <Card className="p-4">
          {tables.length > 1 && (
            <label className="mb-3 block">
              <span className="mb-1.5 block text-sm font-medium text-ink">Sheet</span>
              <select
                value={tableId ?? tables[0]?.id}
                onChange={(e) => setTableId(e.target.value)}
                className="h-9 w-full rounded-lg border border-border-subtle bg-surface px-2 text-sm text-ink"
              >
                {tables.map((table) => (
                  <option key={table.id} value={table.id}>
                    {table.name} ({table.row_count} rows)
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink">Question</span>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void handleRun()
              }}
              rows={2}
              placeholder="What is total revenue by region?"
              className="w-full resize-y rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </label>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example}
                onClick={() => setQuestion(example)}
                className="rounded-full border border-border-subtle px-2.5 py-1 text-xs text-ink-muted transition-colors hover:border-accent hover:text-accent-strong"
              >
                {example}
              </button>
            ))}
          </div>

          {error && (
            <div className="mt-3">
              <ErrorNotice message={error} />
            </div>
          )}

          <div className="mt-3 flex items-center justify-between">
            <p className="text-xs text-ink-muted">
              Code runs in an isolated sandbox — no network, hard timeout.
            </p>
            <Button
              onClick={() => void handleRun()}
              loading={runAnalysis.isPending}
              disabled={!question.trim()}
            >
              Run analysis
            </Button>
          </div>
        </Card>

        {activeRun && <RunResult run={activeRun} />}

        {(history?.length ?? 0) > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink">Previous runs</h3>
            <ul className="space-y-1.5">
              {history!.map((run) => (
                <li key={run.id}>
                  <button
                    onClick={() => setActiveRun(run)}
                    className={cn(
                      'w-full rounded-lg border px-3 py-2 text-left transition-colors',
                      activeRun?.id === run.id
                        ? 'border-accent bg-accent-soft'
                        : 'border-border-subtle bg-surface-raised hover:bg-surface-sunken',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Badge tone={run.status === 'succeeded' ? 'success' : 'danger'}>
                        {run.status}
                      </Badge>
                      <span className="min-w-0 flex-1 truncate text-sm text-ink">
                        {run.question}
                      </span>
                      <span className="shrink-0 text-xs text-ink-muted">
                        {formatRelativeTime(run.created_at)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}

function SchemaSummary({ document }: { document: DocumentDetail }) {
  const table = document.tables?.[0]
  if (!table) {
    return (
      <EmptyState
        title="No analysable table"
        description="Analysis works on spreadsheets and CSV files."
      />
    )
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">{table.name}</h3>
        <span className="text-xs text-ink-muted">
          {table.row_count.toLocaleString()} rows × {table.column_count} columns
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {table.columns.map((column) => (
          <span
            key={column.name}
            className="rounded border border-border-subtle bg-surface-sunken px-2 py-1 text-xs"
            title={
              column.sample_values.length > 0
                ? `e.g. ${column.sample_values.slice(0, 3).join(', ')}`
                : undefined
            }
          >
            <span className="font-medium text-ink">{column.name}</span>
            <span className="ml-1.5 text-ink-muted">{column.dtype}</span>
          </span>
        ))}
      </div>
    </Card>
  )
}

function RunResult({ run }: { run: AnalysisRun }) {
  const [showCode, setShowCode] = useState(false)

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
  const stdout = run.result_data.stdout

  return (
    <Card className="animate-in overflow-hidden">
      <div className="border-b border-border-subtle bg-surface-sunken/50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="success">succeeded</Badge>
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
        <p className="mt-1.5 text-sm text-ink-muted">{run.question}</p>
      </div>

      <div className="space-y-4 p-4">
        {run.result_summary && (
          <p className="text-sm leading-relaxed text-ink">{run.result_summary}</p>
        )}

        {tables.map((table, index) => (
          <ResultTable key={index} table={table} />
        ))}

        {run.chart_url && (
          <div>
            <img
              src={analysisApi.chartUrl(run.id)}
              alt={`Chart generated for: ${run.question}`}
              className="max-w-full rounded-lg border border-border-subtle"
            />
          </div>
        )}

        {stdout && stdout.trim() && (
          <details className="text-xs">
            <summary className="cursor-pointer font-medium text-ink-muted">
              Output
            </summary>
            <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-sunken p-3 text-ink">
              {stdout}
            </pre>
          </details>
        )}

        <div>
          <button
            onClick={() => setShowCode((current) => !current)}
            aria-expanded={showCode}
            className="text-xs font-medium text-accent-strong hover:underline"
          >
            {showCode ? 'Hide' : 'Show'} the code that produced this
          </button>
          {showCode && run.generated_code && (
            <>
              {run.code_explanation && (
                <p className="mt-2 text-xs text-ink-muted">{run.code_explanation}</p>
              )}
              <CodeBlock code={run.generated_code} />
            </>
          )}
        </div>
      </div>
    </Card>
  )
}

function CodeBlock({ code, label }: { code: string; label?: string }) {
  return (
    <div className="mt-2">
      {label && <p className="mb-1 text-xs font-medium text-ink-muted">{label}</p>}
      <pre className="overflow-x-auto rounded-lg border border-border-subtle bg-surface-sunken p-3 text-xs leading-relaxed text-ink">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function ResultTable({ table }: { table: AnalysisTable }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle">
      <table className="w-full text-sm">
        <thead className="bg-surface-sunken">
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
            <tr key={rowIndex} className="border-t border-border-subtle">
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
      {table.truncated && (
        <p className="border-t border-border-subtle bg-surface-sunken px-3 py-1.5 text-xs text-ink-muted">
          Showing {table.rows.length} of {table.total_rows.toLocaleString()} rows.
        </p>
      )}
    </div>
  )
}
