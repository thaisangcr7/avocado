/** Sign in / sign up. One screen, toggled — they share nearly all their form. */

import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, tokenStore } from '@/api/client'
import { authApi } from '@/api/endpoints'
import { Button, Card, ErrorNotice, Input } from '@/components/ui/primitives'
import { queryKeys } from '@/hooks/queries'
import { useAuthStore } from '@/stores/auth'

const MIN_PASSWORD_LENGTH = 12

export function AuthPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [organization, setOrganization] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)

  const setUser = useAuthStore((state) => state.setUser)
  const queryClient = useQueryClient()

  const isRegister = mode === 'register'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setFieldErrors({})
    setSubmitting(true)

    try {
      const tokens = isRegister
        ? await authApi.register({
            email,
            password,
            full_name: fullName || undefined,
            organization_name: organization,
          })
        : await authApi.login({ email, password })

      tokenStore.set(tokens.access_token, tokens.refresh_token)
      const user = await authApi.me()
      queryClient.setQueryData(queryKeys.me, user)
      setUser(user)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors)
      } else {
        setError('Could not reach the server. Is the API running?')
      }
      setSubmitting(false)
    }
  }

  async function handleTryDemo() {
    setError(null)
    setFieldErrors({})
    setSubmitting(true)

    try {
      const tokens = await authApi.demoSession()
      tokenStore.set(tokens.access_token, tokens.refresh_token)
      const user = await authApi.me()
      queryClient.setQueryData(queryKeys.me, user)
      setUser(user)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
      } else {
        setError('Could not start demo mode right now.')
      }
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-atmosphere-auth relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'url("data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%232d5a3d\' fill-opacity=\'0.06\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")',
        }}
      />

      <div className="animate-in-slow relative w-full max-w-md">
        <div className="mb-8 text-center">
          <div
            className="mx-auto mb-5 flex size-16 items-center justify-center rounded-3xl bg-accent-soft text-4xl shadow-[0_8px_28px_rgba(40,90,50,0.12)]"
            aria-hidden="true"
          >
            🥑
          </div>
          <h1 className="font-display text-4xl font-semibold tracking-tight text-ink">
            Avocado
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted text-balance">
            Your team&apos;s knowledge, ready to answer — with citations, or
            with real computed analysis.
          </p>
        </div>

        <Card className="p-6 sm:p-7">
          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <>
                <Field label="Your name" error={fieldErrors.full_name}>
                  <Input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Sang Thai"
                    autoComplete="name"
                  />
                </Field>
                <Field label="Organization" error={fieldErrors.organization_name}>
                  <Input
                    value={organization}
                    onChange={(e) => setOrganization(e.target.value)}
                    placeholder="Acme Inc"
                    required
                    autoComplete="organization"
                  />
                </Field>
              </>
            )}

            <Field label="Email" error={fieldErrors.email}>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                required
                autoComplete="email"
              />
            </Field>

            <Field
              label="Password"
              error={fieldErrors.password}
              hint={isRegister ? `At least ${MIN_PASSWORD_LENGTH} characters` : undefined}
            >
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={isRegister ? MIN_PASSWORD_LENGTH : undefined}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
              />
            </Field>

            {error && <ErrorNotice message={error} />}

            <Button type="submit" loading={submitting} className="w-full">
              {isRegister ? 'Create account' : 'Sign in'}
            </Button>

            {!isRegister && (
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                onClick={handleTryDemo}
                disabled={submitting}
              >
                Try demo instantly
              </Button>
            )}
          </form>
        </Card>

        <p className="mt-6 text-center text-sm text-ink-muted">
          {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
          <button
            type="button"
            onClick={() => {
              setMode(isRegister ? 'login' : 'register')
              setError(null)
              setFieldErrors({})
            }}
            className="font-semibold text-accent-strong hover:underline"
          >
            {isRegister ? 'Sign in' : 'Create one'}
          </button>
        </p>
      </div>
    </div>
  )
}

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-danger">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-muted">{hint}</span>
      ) : null}
    </label>
  )
}
