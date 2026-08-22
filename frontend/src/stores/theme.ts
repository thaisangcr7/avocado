/**
 * Light, dark, or whatever the machine says.
 *
 * The choice is written to the document element rather than held only in React
 * state, so the paint that happens before hydration is already the right one.
 * `system` stores no attribute at all and lets the media query decide, which
 * means a user who has never chosen still follows their OS when it changes.
 */

import { create } from 'zustand'

export type ThemeChoice = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'avocado.theme'

function prefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

export function resolveTheme(choice: ThemeChoice): 'light' | 'dark' {
  return choice === 'system' ? (prefersDark() ? 'dark' : 'light') : choice
}

export function applyTheme(choice: ThemeChoice): void {
  document.documentElement.setAttribute('data-theme', resolveTheme(choice))
}

function stored(): ThemeChoice {
  const value = localStorage.getItem(STORAGE_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

interface ThemeState {
  choice: ThemeChoice
  setChoice: (choice: ThemeChoice) => void
}

export const useThemeStore = create<ThemeState>((set) => ({
  choice: stored(),
  setChoice: (choice) => {
    localStorage.setItem(STORAGE_KEY, choice)
    applyTheme(choice)
    set({ choice })
  },
}))
