import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { App } from './App'
import { applyTheme, useThemeStore } from './stores/theme'
import './index.css'

// Before the first render, so the app never paints light and then flips.
applyTheme(useThemeStore.getState().choice)

// A user on `system` follows the OS when it changes mid-session.
window
  .matchMedia?.('(prefers-color-scheme: dark)')
  .addEventListener?.('change', () => {
    const { choice } = useThemeStore.getState()
    if (choice === 'system') applyTheme(choice)
  })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // A 4xx will not succeed on a retry; only transient failures are worth
      // repeating.
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status
        if (status && status >= 400 && status < 500) return false
        return failureCount < 2
      },
    },
  },
})

const container = document.getElementById('root')
if (!container) throw new Error('Root element #root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
