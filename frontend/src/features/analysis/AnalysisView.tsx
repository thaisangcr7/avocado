/**
 * The analysis surface.
 *
 * The generated program is shown, not hidden. That is the whole point of the
 * feature: a computed answer you can check beats a plausible answer you
 * cannot. The result is rendered as a dashboard-style artifact.
 */

import { useEffect, useMemo, useState } from 'react'

import { ApiError } from '@/api/client'
import type { AnalysisRun, DocumentDetail } from '@/api/types'
import { Badge, Button, Card, EmptyState, ErrorNotice, Spinner } from '@/components/ui/primitives'
import { AnalysisArtifact } from '@/features/analysis/AnalysisArtifact'
import { useAnalysisRuns, useDocument, useRunAnalysis } from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'

export function AnalysisView({
  documentId,
  initialRun,
  onClose,
}: {
  documentId: string
  initialRun?: AnalysisRun | null
  onClose: () => void
}) {
  const { data: document, isLoading } = useDocument(documentId)
  const { data: history } = useAnalysisRuns(documentId)
  const runAnalysis = useRunAnalysis(documentId)

  const [question, setQuestion] = useState('')
  const [tableId, setTableId] = useState<string | undefined>(undefined)
  const [activeRun, setActiveRun] = useState<AnalysisRun | null>(initialRun ?? null)
  const [error, setError] = useState<string | null>(null)

  const exampleQuestions = useMemo(
    () => buildExampleQuestions(document ?? null, tableId),
    [document, tableId],
  )

  useEffect(() => {
    setActiveRun(initialRun ?? null)
  }, [documentId, initialRun])

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
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle/80 px-6 py-5">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-accent-strong">
            Analysis
          </p>
          <h2 className="mt-1 truncate font-display text-xl font-semibold tracking-tight text-ink">
            {document.filename}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
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
              <span className="mb-1.5 block text-sm font-medium text-ink">Table</span>
              <select
                value={tableId ?? tables[0]?.id ?? ''}
                onChange={(e) => setTableId(e.target.value || undefined)}
                className="h-9 w-full rounded-lg border border-border-subtle bg-surface px-2 text-sm"
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
              placeholder={
                exampleQuestions[0] ?? 'What is total revenue by region?'
              }
              className="w-full resize-y rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </label>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {exampleQuestions.map((example) => (
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

        {activeRun && <AnalysisArtifact run={activeRun} />}

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

function buildExampleQuestions(
  document: DocumentDetail | null,
  tableId: string | undefined,
): string[] {
  const tables = document?.tables ?? []
  const table =
    tables.find((candidate) => candidate.id === tableId) ?? tables[0] ?? null
  if (!table) {
    return [
      'What is the total by category?',
      'Show the month-over-month trend',
      'Which rows are outliers?',
    ]
  }

  const columns = table.columns.map((column) => column.name)
  const numeric = table.columns.filter((column) =>
    /int|float|double|number|decimal/i.test(column.dtype),
  )
  const categorical = table.columns.filter(
    (column) => !/int|float|double|number|decimal/i.test(column.dtype),
  )
  const dateLike = columns.find((name) =>
    /date|month|year|period|week/i.test(name),
  )
  const metric = numeric[0]?.name
  const group = categorical[0]?.name

  const questions: string[] = []
  if (metric && group) {
    questions.push(`What is the total ${metric} by ${group}?`)
  }
  if (metric && dateLike) {
    questions.push(`Show the ${metric} trend over ${dateLike}`)
  }
  if (metric) {
    questions.push(`Which rows have the highest ${metric}?`)
    questions.push(`Summarise the distribution of ${metric}`)
  }
  if (!questions.length) {
    questions.push(`Summarise the key patterns in ${table.name}`)
  }
  return questions.slice(0, 4)
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
