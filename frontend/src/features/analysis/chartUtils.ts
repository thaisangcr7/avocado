/**
 * Helpers for turning analysis result tables into chart series.
 */

import type { AnalysisTable } from '@/api/types'

export type ChartPoint = { label: string; value: number }
export type ChartSeries = {
  title: string
  valueLabel: string
  categoryLabel: string
  kind: 'bar' | 'line'
  points: ChartPoint[]
}

function isNumeric(value: unknown): value is number {
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed)
  }
  return false
}

function toNumber(value: unknown): number {
  return typeof value === 'number' ? value : Number(value)
}

/** Pick a category column and a numeric series from a result table. */
export function extractChartSeries(table: AnalysisTable): ChartSeries | null {
  if (!table.columns.length || !table.rows.length) return null

  const numericIndexes = table.columns
    .map((_, index) => index)
    .filter((index) => {
      const populated = table.rows.filter(
        (row) => row[index] !== null && row[index] !== undefined && row[index] !== '',
      )
      if (!populated.length) return false
      return populated.filter((row) => isNumeric(row[index])).length / populated.length >= 0.8
    })

  if (!numericIndexes.length) return null

  const valueIndex = numericIndexes[numericIndexes.length - 1]!
  const temporalIndex = table.columns.findIndex(
    (column, index) =>
      index !== valueIndex &&
      /date|month|year|quarter|week|period|time/i.test(column),
  )
  const nonNumericIndex = table.columns.findIndex(
    (_, index) => index !== valueIndex && !numericIndexes.includes(index),
  )
  const labelCandidate =
    temporalIndex >= 0
      ? temporalIndex
      : nonNumericIndex >= 0
        ? nonNumericIndex
        : table.columns.findIndex((_, index) => index !== valueIndex)
  const labelIndex = labelCandidate === -1 ? 0 : labelCandidate

  const points: ChartPoint[] = table.rows
    .map((row) => {
      const raw = row[valueIndex]
      if (!isNumeric(raw)) return null
      const label = String(row[labelIndex] ?? '')
      return { label: label || 'Row', value: toNumber(raw) }
    })
    .filter((point): point is ChartPoint => point !== null)
    .slice(0, 24)

  if (points.length < 2) return null

  return {
    title: `${table.columns[valueIndex]} by ${table.columns[labelIndex]}`,
    valueLabel: table.columns[valueIndex]!,
    categoryLabel: table.columns[labelIndex]!,
    kind: temporalIndex >= 0 ? 'line' : 'bar',
    points,
  }
}

export function summarizeSeries(series: ChartSeries) {
  const values = series.points.map((point) => point.value)
  const total = values.reduce((sum, value) => sum + value, 0)
  const highest = series.points.reduce((best, point) =>
    point.value > best.value ? point : best,
  )
  const lowest = series.points.reduce((best, point) =>
    point.value < best.value ? point : best,
  )
  const first = values[0]!
  const last = values[values.length - 1]!
  const changePercent = first === 0 ? null : ((last - first) / Math.abs(first)) * 100

  return {
    total,
    average: total / values.length,
    highest,
    lowest,
    changePercent,
  }
}
