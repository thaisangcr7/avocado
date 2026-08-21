/**
 * Renders a whole-workspace executive report: a KPI strip, then one section
 * per theme with a status badge, narrative, and the computed charts it binds
 * to. Charts reuse the analysis `VegaChart` by adapting the report's computed
 * series into the visualization/table shape that renderer already speaks.
 */

import type {
  AnalysisTable,
  AnalysisVisualization,
  ExecutiveReport,
  ReportChart,
  ReportKpi,
  ReportSection,
  ReportSeries,
  ReportStatus,
} from '@/api/types'
import { VegaChart } from '@/features/analysis/VegaChart'
import { cn } from '@/lib/utils'

const STATUS_BADGE: Record<ReportStatus, { label: string; className: string }> = {
  on_course: { label: 'On course', className: 'bg-accent-soft text-accent-strong' },
  watch: { label: 'Watch', className: 'bg-warning-soft text-warning' },
  off_course: { label: 'Off course', className: 'bg-danger-soft text-danger' },
  neutral: { label: 'Steady', className: 'bg-surface-sunken text-ink-muted' },
}

const KPI_BAR: Record<ReportKpi['tone'], string> = {
  positive: 'bg-success',
  negative: 'bg-danger',
  warning: 'bg-warning',
  neutral: 'bg-accent',
}

export function ReportArtifact({ report }: { report: ExecutiveReport }) {
  const seriesByKey = new Map(report.series.map((series) => [series.key, series]))

  return (
    <div className="animate-in mt-3 overflow-hidden rounded-2xl border border-border-subtle bg-surface-raised">
      <header className="border-b border-border-subtle px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <p className="font-display text-lg font-semibold tracking-tight text-ink text-balance">
            {report.title}
          </p>
          <StatusBadge status={report.heading_status} />
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-muted text-balance">
          {report.thesis}
        </p>
      </header>

      {report.kpis.length > 0 && (
        <div className="grid gap-px bg-border-subtle sm:grid-cols-2 lg:grid-cols-3">
          {report.kpis.map((kpi, index) => (
            <div key={index} className="relative bg-surface-raised px-4 py-3">
              <span
                className={cn('absolute inset-x-0 top-0 h-0.5', KPI_BAR[kpi.tone])}
                aria-hidden="true"
              />
              <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                {kpi.label}
              </p>
              <p className="mt-1 font-mono text-xl font-semibold tabular-nums text-ink">
                {kpi.value}
              </p>
              {kpi.context && (
                <p className="mt-0.5 text-xs leading-snug text-ink-muted">{kpi.context}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="divide-y divide-border-subtle">
        {report.sections.map((section, index) => (
          <SectionBlock key={index} section={section} seriesByKey={seriesByKey} />
        ))}
      </div>

      {report.limits.length > 0 && (
        <div className="border-t border-border-subtle bg-surface-sunken/50 px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
            Limits
          </p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-ink-muted">
            {report.limits.map((limit, index) => (
              <li key={index}>{limit}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function SectionBlock({
  section,
  seriesByKey,
}: {
  section: ReportSection
  seriesByKey: Map<string, ReportSeries>
}) {
  const charts = section.charts.filter((chart) => seriesByKey.has(chart.series_key))

  return (
    <section className="px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-semibold text-ink">{section.title}</h3>
        <StatusBadge status={section.status} />
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{section.narrative}</p>

      {charts.length > 0 && (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {charts.map((chart, index) => {
            const series = seriesByKey.get(chart.series_key)
            if (!series) return null
            return (
              <div key={index}>
                <p className="mb-1 text-xs font-medium text-ink">{chart.title}</p>
                <VegaChart visual={toVisual(chart)} table={toTable(series)} />
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function StatusBadge({ status }: { status: ReportStatus }) {
  const badge = STATUS_BADGE[status]
  return (
    <span
      className={cn(
        'shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide',
        badge.className,
      )}
    >
      {badge.label}
    </span>
  )
}

function toVisual(chart: ReportChart): AnalysisVisualization {
  return {
    title: chart.title,
    description: chart.description,
    mark: chart.mark,
    table_index: 0,
    x: chart.x,
    y: chart.y,
    color: chart.color,
    interactive: true,
  }
}

function toTable(series: ReportSeries): AnalysisTable {
  return {
    name: series.title,
    columns: series.columns,
    rows: series.rows,
    total_rows: series.rows.length,
    truncated: false,
  }
}
