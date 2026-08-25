/** Routes between the auth screen and the workspace shell. */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { setSessionExpiredHandler, tokenStore } from '@/api/client'
import { authApi } from '@/api/endpoints'
import { AuthPage } from '@/features/auth/AuthPage'
import { isDemoLocation } from '@/features/auth/route'
import { InvitePage } from '@/features/invitations/InvitePage'
import { inviteTokenFromLocation } from '@/features/invitations/route'
import { WorkspaceShell } from '@/features/workspace/WorkspaceShell'
import { Spinner } from '@/components/ui/primitives'
import { queryKeys, useCurrentUser } from '@/hooks/queries'
import { useAuthStore } from '@/stores/auth'

export function App() {
  const { user, isAuthenticated, isLoading, setUser, signOut } = useAuthStore()
  const hasToken = Boolean(tokenStore.access)
  const queryClient = useQueryClient()

  // A demo link opens into a live workspace rather than a sign-in form: the
  // first thing a viewer should see is the product working, not a password
  // field they have no password for.
  const wantsDemo = isDemoLocation(window.location)
  const [demoRefused, setDemoRefused] = useState(false)

  // Invitation links are the one route that has to work for a visitor with no
  // account, so it is resolved before the authentication gate below.
  const inviteToken = inviteTokenFromLocation(window.location.pathname)

  // Restore the session from a stored token on load.
  const { data, isError, isSuccess } = useCurrentUser(hasToken && !user)

  useEffect(() => {
    if (isSuccess && data) setUser(data)
  }, [isSuccess, data, setUser])

  useEffect(() => {
    if (!wantsDemo || hasToken || isAuthenticated || demoRefused) return
    let abandoned = false

    void (async () => {
      try {
        const tokens = await authApi.demoSession()
        tokenStore.set(tokens.access_token, tokens.refresh_token)
        const demoUser = await authApi.me()
        if (abandoned) return
        queryClient.setQueryData(queryKeys.me, demoUser)
        setUser(demoUser)
      } catch {
        // Demo mode off, or the API is down. Fall back to the sign-in screen
        // rather than holding a spinner over a session that is not coming.
        if (!abandoned) setDemoRefused(true)
      }
    })()

    return () => {
      abandoned = true
    }
  }, [wantsDemo, hasToken, isAuthenticated, demoRefused, queryClient, setUser])

  useEffect(() => {
    // A token that no longer resolves to a user is not a session.
    if (isError) signOut()
  }, [isError, signOut])

  // Refresh failed downstream: end the session rather than leaving the UI
  // making requests that will all 401.
  useEffect(() => {
    setSessionExpiredHandler(signOut)
  }, [signOut])

  if (inviteToken) {
    return <InvitePage token={inviteToken} />
  }

  if (wantsDemo && !isAuthenticated && !demoRefused) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner className="size-6 text-ink-muted" />
      </div>
    )
  }

  if (hasToken && isLoading && !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner className="size-6 text-ink-muted" />
      </div>
    )
  }

  return isAuthenticated && user ? <WorkspaceShell /> : <AuthPage />
}
