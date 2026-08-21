/**
 * Interactive charts built from analysis result tables.
 *
 * Prefer rendering the data we already have over a matplotlib PNG alone —
 * that is what makes an analysis result feel like a dashboard artifact
 * rather than a screenshot of a plot.
 */

import type { AnalysisTable } from '@/api/types'
import { extractChartSeries } from '@/features/analysis/chartUtils'
import { cn } from '@/lib/utils'

export function DataChart({
  table,
  className,
}: {
  table: AnalysisTable
  className?: string
}) {
  const series = extractChartSeries(table)
  if (!series) return null

  const width = 640
  const height = 260
  const pad = { top: 24, right: 16, bottom: 48, left: 48 }
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const values = series.points.map((point) => point.value)
  const rawMin = Math.min(...values, 0)
  const rawMax = Math.max(...values, 0)
  const range = Math.max(rawMax - rawMin, 1)
  const min = rawMin - range * 0.06
  const max = rawMax + range * 0.06
  const barGap = 6
  const barWidth = Math.max(
    8,
    (innerW - barGap * series.points.length) / series.points.length,
  )

  return (
    <div
      className={cn(
        'overflow-hidden rounded-2xl border border-border-subtle bg-surface',
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-border-subtle/80 px-4 py-2.5">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
          Chart
        </p>
        <p className="truncate text-xs text-ink-muted">{series.title}</p>
      </div>
      <div className="px-2 py-3">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full"
          role="img"
          aria-label={series.title}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const y = pad.top + innerH * (1 - tick)
            const value = min + (max - min) * tick
            return (
              <g key={tick}>
                <line
                  x1={pad.left}
                  x2={width - pad.right}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  className="text-border-subtle"
                  strokeWidth={1}
                />
                <text
                  x={pad.left - 8}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-ink-muted"
                  fontSize={10}
                >
                  {formatTick(value)}
                </text>
              </g>
            )
          })}

          {series.kind === 'line' ? (
            <LineSeries
              points={series.points}
              min={min}
              max={max}
              left={pad.left}
              top={pad.top}
              width={innerW}
              height={innerH}
              canvasHeight={height}
            />
          ) : (
            series.points.map((point, index) => {
              const x = pad.left + index * (barWidth + barGap) + barGap / 2
              const zeroY = pad.top + ((max - 0) / (max - min)) * innerH
              const valueY = pad.top + ((max - point.value) / (max - min)) * innerH
              const y = Math.min(zeroY, valueY)
              const barHeight = Math.max(Math.abs(zeroY - valueY), 1)
              return (
                <g key={`${point.label}-${index}`}>
                  <rect
                    x={x}
                    y={y}
                    width={barWidth}
                    height={barHeight}
                    rx={4}
                    className="fill-accent"
                    opacity={0.9}
                  >
                    <title>
                      {point.label}: {formatTick(point.value)}
                    </title>
                  </rect>
                  <text
                    x={x + barWidth / 2}
                    y={height - 12}
                    textAnchor="middle"
                    className="fill-ink-muted"
                    fontSize={9}
                  >
                    {truncateLabel(point.label, 10)}
                  </text>
                </g>
              )
            })
          )}
        </svg>
      </div>
    </div>
  )
}

function LineSeries({
  points,
  min,
  max,
  left,
  top,
  width,
  height,
  canvasHeight,
}: {
  points: { label: string; value: number }[]
  min: number
  max: number
  left: number
  top: number
  width: number
  height: number
  canvasHeight: number
}) {
  const coordinates = points.map((point, index) => ({
    ...point,
    x: left + (index / Math.max(points.length - 1, 1)) * width,
    y: top + ((max - point.value) / (max - min)) * height,
  }))
  const path = coordinates
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ')

  return (
    <>
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        className="text-accent"
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {coordinates.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          <circle
            cx={point.x}
            cy={point.y}
            r={4}
            className="fill-surface stroke-accent"
            strokeWidth={3}
          >
            <title>
              {point.label}: {formatTick(point.value)}
            </title>
          </circle>
          {(index === 0 || index === coordinates.length - 1 || index % 3 === 0) && (
            <text
              x={point.x}
              y={canvasHeight - 12}
              textAnchor={
                index === 0
                  ? 'start'
                  : index === coordinates.length - 1
                    ? 'end'
                    : 'middle'
              }
              className="fill-ink-muted"
              fontSize={9}
            >
              {truncateLabel(point.label, 12)}
            </text>
          )}
        </g>
      ))}
    </>
  )
}

function formatTick(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(1)
}

function truncateLabel(label: string, max: number): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label
}
