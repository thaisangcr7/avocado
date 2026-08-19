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

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mb-3 text-4xl" aria-hidden="true">
            🥑
          </div>
          <h1 className="text-2xl font-semibold text-ink">Avocado</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Ask your team&apos;s documents anything.
          </p>
        </div>

        <Card className="p-6">
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
          </form>
        </Card>

        <p className="mt-5 text-center text-sm text-ink-muted">
          {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
          <button
            type="button"
            onClick={() => {
              setMode(isRegister ? 'login' : 'register')
              setError(null)
              setFieldErrors({})
            }}
            className="font-medium text-accent-strong hover:underline"
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
