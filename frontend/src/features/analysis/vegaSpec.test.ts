import { describe, expect, it } from 'vitest'

import type { AnalysisTable, AnalysisVisualization } from '@/api/types'
import { buildVegaSpec } from './vegaSpec'

const TABLE: AnalysisTable = {
  name: 'result',
  columns: ['month', 'revenue'],
  rows: [
    ['2026-01', 100],
    ['2026-02', 140],
  ],
  total_rows: 2,
  truncated: false,
}

const VISUAL: AnalysisVisualization = {
  title: 'Revenue trend',
  description: 'Monthly revenue',
  mark: 'line',
  table_index: 0,
  x: { field: 'month', type: 'temporal', title: 'Month', format: null },
  y: { field: 'revenue', type: 'quantitative', title: 'Revenue', format: '$,.0f' },
  color: null,
  interactive: true,
}

describe('Vega spec builder', () => {
  it('uses only computed table rows and constrained field bindings', () => {
    const spec = buildVegaSpec(VISUAL, TABLE)

    expect(spec.data).toEqual({
      values: [
        { month: '2026-01', revenue: 100 },
        { month: '2026-02', revenue: 140 },
      ],
    })
    expect(spec.mark).toMatchObject({ type: 'line' })
    expect(spec.encoding).toMatchObject({
      x: { field: 'month', type: 'temporal' },
      y: { field: 'revenue', type: 'quantitative' },
    })
    expect(spec.params).toBeDefined()
  })

  it('maps part-to-whole charts to theta and color', () => {
    const spec = buildVegaSpec(
      { ...VISUAL, mark: 'arc', interactive: false },
      TABLE,
    )

    expect(spec.encoding).toMatchObject({
      theta: { field: 'revenue' },
      color: { field: 'month' },
    })
  })
})
