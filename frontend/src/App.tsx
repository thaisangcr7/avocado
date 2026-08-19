/** Routes between the auth screen and the workspace shell. */

import { useEffect } from 'react'

import { setSessionExpiredHandler, tokenStore } from '@/api/client'
import { AuthPage } from '@/features/auth/AuthPage'
import { WorkspaceShell } from '@/features/workspace/WorkspaceShell'
import { Spinner } from '@/components/ui/primitives'
import { useCurrentUser } from '@/hooks/queries'
import { useAuthStore } from '@/stores/auth'

export function App() {
  const { user, isAuthenticated, isLoading, setUser, signOut } = useAuthStore()
  const hasToken = Boolean(tokenStore.access)

  // Restore the session from a stored token on load.
  const { data, isError, isSuccess } = useCurrentUser(hasToken && !user)

  useEffect(() => {
    if (isSuccess && data) setUser(data)
  }, [isSuccess, data, setUser])

  useEffect(() => {
    // A token that no longer resolves to a user is not a session.
    if (isError) signOut()
  }, [isError, signOut])

  // Refresh failed downstream: end the session rather than leaving the UI
  // making requests that will all 401.
  useEffect(() => {
    setSessionExpiredHandler(signOut)
  }, [signOut])

  if (hasToken && isLoading && !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner className="size-6 text-ink-muted" />
      </div>
    )
  }

  return isAuthenticated && user ? <WorkspaceShell /> : <AuthPage />
}
