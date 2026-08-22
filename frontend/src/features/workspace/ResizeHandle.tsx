/**
 * A drag handle for a side panel, with the width remembered.
 *
 * The panel holds documents, artifacts and knowledge — things people read
 * rather than glance at — so a fixed width is a guess that is wrong for
 * somebody. The width persists because re-dragging it on every visit is worse
 * than the fixed width it replaced.
 *
 * Pointer events rather than mouse events, so a trackpad, a pen and a touch
 * screen all work; capture keeps the drag alive when the cursor outruns the
 * handle.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

const MIN = 280
const MAX = 780
const STEP = 24

export function useResizableWidth(storageKey: string, fallback: number) {
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(storageKey))
    return Number.isFinite(stored) && stored >= MIN && stored <= MAX ? stored : fallback
  })

  // Accepts an updater as well as a value, so a caller that derives the next
  // width from the current one is not reading a captured stale copy. Repeated
  // key presses within one render would otherwise all compute from the same
  // starting width and collapse into a single step.
  const set = useCallback(
    (next: number | ((previous: number) => number)) => {
      setWidth((previous) => {
        const raw = typeof next === 'function' ? next(previous) : next
        const clamped = Math.min(MAX, Math.max(MIN, Math.round(raw)))
        localStorage.setItem(storageKey, String(clamped))
        return clamped
      })
    },
    [storageKey],
  )

  return [width, set] as const
}

export function ResizeHandle({
  width,
  onResize,
  label,
}: {
  width: number
  onResize: (next: number | ((previous: number) => number)) => void
  label: string
}) {
  const [dragging, setDragging] = useState(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  useEffect(() => {
    if (!dragging) return
    // While dragging, the pointer is regularly over the text on either side,
    // and without this every drag selects a paragraph on the way past.
    const previous = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    return () => {
      document.body.style.userSelect = previous
    }
  }, [dragging])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={MIN}
      aria-valuemax={MAX}
      tabIndex={0}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        startX.current = e.clientX
        startWidth.current = width
        setDragging(true)
      }}
      onPointerMove={(e) => {
        if (!dragging) return
        // The panel is on the right, so dragging left widens it.
        onResize(startWidth.current + (startX.current - e.clientX))
      }}
      onPointerUp={(e) => {
        e.currentTarget.releasePointerCapture(e.pointerId)
        setDragging(false)
      }}
      onKeyDown={(e) => {
        // Keyboard-resizable, because a pointer-only control is unusable for
        // anyone who does not have one.
        if (e.key === 'ArrowLeft') onResize((previous) => previous + STEP)
        if (e.key === 'ArrowRight') onResize((previous) => previous - STEP)
      }}
      className={cn(
        'group hidden w-1.5 shrink-0 cursor-col-resize touch-none lg:block',
        'focus-visible:outline-none',
      )}
    >
      <div
        className={cn(
          'mx-auto h-full w-px transition-colors',
          dragging ? 'bg-accent' : 'bg-transparent group-hover:bg-accent/50',
          'group-focus-visible:bg-accent',
        )}
      />
    </div>
  )
}
