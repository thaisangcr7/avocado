import { describe, expect, it } from 'vitest'

import type { AnalysisTable } from '@/api/types'
import { extractChartSeries, summarizeSeries } from './chartUtils'

function table(columns: string[], rows: unknown[][]): AnalysisTable {
  return {
    name: 'result',
    columns,
    rows,
    total_rows: rows.length,
    truncated: false,
  }
}

describe('analysis chart inference', () => {
  it('uses a line chart for a dated series', () => {
    const series = extractChartSeries(
      table(
        ['month', 'revenue'],
        [
          ['2026-01', 100],
          ['2026-02', 125],
          ['2026-03', 150],
        ],
      ),
    )

    expect(series).toMatchObject({
      kind: 'line',
      categoryLabel: 'month',
      valueLabel: 'revenue',
    })
  })

  it('uses bars for category comparisons and computes useful metrics', () => {
    const series = extractChartSeries(
      table(
        ['region', 'revenue'],
        [
          ['East', 100],
          ['West', 250],
          ['North', 150],
        ],
      ),
    )

    expect(series?.kind).toBe('bar')
    expect(summarizeSeries(series!)).toMatchObject({
      total: 500,
      average: 500 / 3,
      highest: { label: 'West', value: 250 },
      lowest: { label: 'East', value: 100 },
      changePercent: 50,
    })
  })

  it('does not mistake mostly textual columns for metrics', () => {
    expect(
      extractChartSeries(
        table(
          ['policy', 'owner'],
          [
            ['Leave', 'People'],
            ['Travel', 'Finance'],
          ],
        ),
      ),
    ).toBeNull()
  })
})
