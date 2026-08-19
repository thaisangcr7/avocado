import { describe, expect, it, vi } from 'vitest'
import { cn, formatBytes, formatCurrency, formatRelativeTime } from './utils'

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('a', 'b')).toBe('a b')
  })

  it('lets a later Tailwind utility win over an earlier one', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })

  it('drops falsey values', () => {
    expect(cn('a', false, undefined, null, 'b')).toBe('a b')
  })
})

describe('formatBytes', () => {
  it.each([
    [512, '512 B'],
    [1024, '1.0 KB'],
    [1536, '1.5 KB'],
    [1024 * 1024, '1.0 MB'],
    [1024 * 1024 * 15, '15 MB'],
  ])('formats %i as %s', (input, expected) => {
    expect(formatBytes(input)).toBe(expected)
  })
})

describe('formatRelativeTime', () => {
  it('describes recent times relatively', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T12:00:00Z'))

    expect(formatRelativeTime('2026-01-01T11:59:30Z')).toBe('just now')
    expect(formatRelativeTime('2026-01-01T11:30:00Z')).toBe('30m ago')
    expect(formatRelativeTime('2026-01-01T09:00:00Z')).toBe('3h ago')
    expect(formatRelativeTime('2025-12-30T12:00:00Z')).toBe('2d ago')

    vi.useRealTimers()
  })

  it('returns an empty string for an unparseable date', () => {
    expect(formatRelativeTime('not a date')).toBe('')
  })
})

describe('formatCurrency', () => {
  it('does not render sub-cent costs as $0.00', () => {
    // Per-call costs are routinely below a cent; rounding hides them entirely.
    expect(formatCurrency(0.0003)).toBe('<$0.01')
  })

  it('formats larger amounts normally', () => {
    expect(formatCurrency(0)).toBe('$0.00')
    expect(formatCurrency(1.5)).toBe('$1.50')
  })
})
