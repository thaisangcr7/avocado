import type {
  AnalysisTable,
  AnalysisVisualization,
  VisualizationEncoding,
} from '@/api/types'

type VegaSpec = Record<string, unknown>

function encoding(
  value: VisualizationEncoding,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    field: value.field,
    type: value.type,
    ...(value.title ? { title: value.title } : {}),
    ...(value.format ? { axis: { format: value.format } } : {}),
    ...extra,
  }
}

/**
 * Convert Avocado's constrained, validated contract into Vega-Lite.
 * No model-provided expression, transform, URL, or JavaScript reaches Vega.
 */
export function buildVegaSpec(
  visual: AnalysisVisualization,
  table: AnalysisTable,
): VegaSpec {
  const values = table.rows.map((row) =>
    Object.fromEntries(table.columns.map((column, index) => [column, row[index]])),
  )
  const tooltip = table.columns.slice(0, 12).map((field) => ({ field }))

  const base: VegaSpec = {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
    title: {
      text: visual.title,
      ...(visual.description ? { subtitle: visual.description } : {}),
      anchor: 'start',
      fontSize: 15,
      subtitleFontSize: 11,
      subtitleColor: '#637168',
    },
    width: 'container',
    height: 300,
    autosize: { type: 'fit', contains: 'padding' },
    data: { values },
    config: {
      background: 'transparent',
      view: { stroke: null },
      axis: {
        labelColor: '#5b685f',
        titleColor: '#263d2e',
        domainColor: '#d8e1da',
        gridColor: '#e7ece8',
        tickColor: '#d8e1da',
        labelFont: 'Figtree',
        titleFont: 'Figtree',
      },
      legend: {
        labelColor: '#5b685f',
        titleColor: '#263d2e',
        labelFont: 'Figtree',
        titleFont: 'Figtree',
      },
      range: {
        category: [
          '#337a4d',
          '#e4a832',
          '#4f79a7',
          '#a85f72',
          '#6e8b57',
          '#8b6dad',
          '#d47845',
        ],
      },
    },
  }

  if (visual.mark === 'arc') {
    return {
      ...base,
      mark: { type: 'arc', innerRadius: 55, stroke: '#fff', strokeWidth: 2 },
      encoding: {
        theta: encoding(visual.y, { stack: true }),
        color: encoding(visual.x, { legend: { orient: 'bottom' } }),
        tooltip,
      },
    }
  }

  const isContinuous = ['line', 'area', 'point'].includes(visual.mark)
  const mark =
    visual.mark === 'bar'
      ? { type: 'bar', cornerRadiusEnd: 4 }
      : visual.mark === 'line'
        ? { type: 'line', point: { filled: true, size: 55 }, strokeWidth: 3 }
        : visual.mark === 'area'
          ? { type: 'area', line: true, opacity: 0.35 }
          : { type: visual.mark, filled: true, size: 75 }

  return {
    ...base,
    mark,
    encoding: {
      x: encoding(visual.x, {
        axis: {
          labelAngle: visual.x.type === 'nominal' ? -25 : 0,
          labelLimit: 120,
        },
        ...(visual.mark === 'bar' ? { sort: '-y' } : {}),
      }),
      y: encoding(visual.y, { scale: { zero: visual.mark === 'bar' } }),
      ...(visual.color
        ? { color: encoding(visual.color, { legend: { orient: 'bottom' } }) }
        : { color: { value: '#337a4d' } }),
      tooltip,
    },
    ...(visual.interactive && isContinuous
      ? {
          params: [
            {
              name: 'zoom',
              select: { type: 'interval', encodings: ['x'] },
              bind: 'scales',
            },
          ],
        }
      : {}),
  }
}
