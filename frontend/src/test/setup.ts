import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom implements no layout, so these are absent rather than no-ops.
// Components legitimately call them; stubbing keeps that from failing tests
// for a reason that has nothing to do with the behaviour under test.
Element.prototype.scrollIntoView = vi.fn()
Element.prototype.scrollTo = vi.fn()

globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
