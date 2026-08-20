/**
 * Accepting an invitation.
 *
 * Reached from a link, so it has to work for three different visitors:
 *
 * - someone with no account, who sets a password and is signed in
 * - someone already signed in as the addressee, who just joins
 * - someone signed in as *somebody else*, who is told plainly rather than
 *   silently joining the wrong account
 *
 * The server decides all three; this page reads `requires_account` to ask for
 * the right thing up front instead of failing after the fact.
 */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, tokenStore } from '@/api/client'
import { authApi, invitationApi } from '@/api/endpoints'
import { ROLE_LABEL, type InvitationPreview } from '@/api/types'
import { Button, Card, ErrorNotice, Input, Spinner } from '@/components/ui/primitives'
import { queryKeys } from '@/hooks/queries'
import { useAuthStore } from '@/stores/auth'

export function InvitePage({ token }: { token: string }) {
  const [preview, setPreview] = useState<InvitationPreview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const currentUser = useAuthStore((state) => state.user)
  const setUser = useAuthStore((state) => state.setUser)
  const queryClient = useQueryClient()

  useEffect(() => {
    let cancelled = false
    invitationApi
      .preview(token)
      .then((result) => !cancelled && setPreview(result))
      .catch((error) =>
        !cancelled &&
        setLoadError(
          error instanceof ApiError
            ? error.message
            : 'This invitation could not be loaded.',
        ),
      )
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleAccept(event: React.FormEvent) {
    event.preventDefault()
    setSubmitError(null)
    setSubmitting(true)
    try {
      const tokens = await invitationApi.accept(token, {
        ...(preview?.requires_account && { password, full_name: fullName || undefined }),
      })
      tokenStore.set(tokens.access_token, tokens.refresh_token)

      // Everything cached belongs to whoever was signed in before.
      queryClient.clear()
      const me = await authApi.me()
      queryClient.setQueryData(queryKeys.me, me)
      setUser(me)
      window.history.replaceState({}, '', '/')
      window.location.reload()
    } catch (caught) {
      setSubmitError(
        caught instanceof ApiError ? caught.message : 'The invitation could not be accepted.',
      )
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="p-6 text-center">
          <p className="text-2xl" aria-hidden="true">
            🥑
          </p>
          <h1 className="mt-2 text-lg font-semibold text-ink">Invitation unavailable</h1>
          <p className="mt-1 text-sm text-ink-muted">{loadError}</p>
          <p className="mt-1 text-xs text-ink-muted">
            It may have been revoked, already used, or expired.
          </p>
          <Button className="mt-4" onClick={() => (window.location.href = '/')}>
            Go to Avocado
          </Button>
        </Card>
      </Shell>
    )
  }

  if (!preview) {
    return (
      <Shell>
        <div className="flex justify-center py-10">
          <Spinner className="size-6 text-ink-muted" />
        </div>
      </Shell>
    )
  }

  const signedInAsSomeoneElse =
    currentUser !== null && currentUser.email.toLowerCase() !== preview.email.toLowerCase()

  return (
    <Shell>
      <Card className="p-6">
        <h1 className="text-lg font-semibold text-ink">
          Join {preview.organization_name}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          You have been invited to the <strong className="text-ink">{preview.team_name}</strong>{' '}
          team as {ROLE_LABEL[preview.role].toLowerCase()}.
        </p>
        <p className="mt-2 text-xs text-ink-muted">Invitation sent to {preview.email}</p>

        {signedInAsSomeoneElse ? (
          <div className="mt-4 space-y-3">
            <ErrorNotice
              message={`You are signed in as ${currentUser!.email}, but this invitation was sent to ${preview.email}.`}
            />
            <Button
              variant="secondary"
              className="w-full"
              onClick={() => {
                useAuthStore.getState().signOut()
                window.location.reload()
              }}
            >
              Sign out and continue
            </Button>
          </div>
        ) : (
          <form onSubmit={handleAccept} className="mt-4 space-y-3">
            {preview.requires_account ? (
              <>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink">Your name</span>
                  <Input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    autoComplete="name"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink">
                    Choose a password
                  </span>
                  <Input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={12}
                    autoComplete="new-password"
                  />
                  <span className="mt-1 block text-xs text-ink-muted">
                    At least 12 characters
                  </span>
                </label>
              </>
            ) : currentUser === null ? (
              // The account exists but nobody is signed in. Accepting from the
              // link alone would make the invitation work as a password.
              <ErrorNotice message="You already have an account. Sign in first, then open this link again." />
            ) : null}

            {submitError && <ErrorNotice message={submitError} />}

            <Button
              type="submit"
              className="w-full"
              loading={submitting}
              disabled={!preview.requires_account && currentUser === null}
            >
              {preview.requires_account ? 'Create account and join' : 'Join team'}
            </Button>
          </form>
        )}
      </Card>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mb-2 text-3xl" aria-hidden="true">
            🥑
          </div>
          <p className="text-sm text-ink-muted">Avocado</p>
        </div>
        {children}
      </div>
    </div>
  )
}
