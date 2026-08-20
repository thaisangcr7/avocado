/**
 * The HTTP client.
 *
 * Two things it handles that callers should never have to think about:
 *
 * - **Token refresh.** A 401 triggers one refresh attempt and one retry.
 *   Concurrent 401s share a single in-flight refresh rather than each firing
 *   their own, which would invalidate each other and log the user out.
 * - **Errors.** Every failure becomes an `ApiError` carrying the parsed
 *   problem details, so UI code can show `detail` without re-parsing.
 */

import type { ProblemDetail } from './types'

type RuntimeConfig = {
  apiBaseUrl?: string
}

declare global {
  interface Window {
    __AVOCADO_CONFIG__?: RuntimeConfig
  }
}

export function resolveBaseUrl() {
  const runtimeBaseUrl = window.__AVOCADO_CONFIG__?.apiBaseUrl?.trim()
  const buildBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
  return runtimeBaseUrl || buildBaseUrl || '/api/v1'
}

const BASE_URL = resolveBaseUrl()

const ACCESS_TOKEN_KEY = 'avocado.access_token'
const REFRESH_TOKEN_KEY = 'avocado.refresh_token'

export class ApiError extends Error {
  readonly status: number
  readonly problem: ProblemDetail | null

  constructor(status: number, problem: ProblemDetail | null, fallback: string) {
    super(problem?.detail ?? fallback)
    this.name = 'ApiError'
    this.status = status
    this.problem = problem
  }

  /** Field-level messages from a 422, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const error of this.problem?.errors ?? []) {
      out[error.field] = error.message
    }
    return out
  }
}

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_TOKEN_KEY, access)
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}

/** Called when refresh fails and the session is genuinely over. */
let onSessionExpired: (() => void) | null = null
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler
}

// Shared so that N concurrent 401s produce one refresh, not N.
let refreshInFlight: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    const refresh = tokenStore.refresh
    if (!refresh) return false
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
      if (!response.ok) return false
      const tokens = await response.json()
      tokenStore.set(tokens.access_token, tokens.refresh_token)
      return true
    } catch {
      return false
    } finally {
      // Cleared in a microtask so callers awaiting this promise all observe
      // the same result before the next refresh can start.
      queueMicrotask(() => {
        refreshInFlight = null
      })
    }
  })()

  return refreshInFlight
}

async function parseProblem(response: Response): Promise<ProblemDetail | null> {
  try {
    return (await response.json()) as ProblemDetail
  } catch {
    return null
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Skip the Authorization header (login, register, refresh). */
  anonymous?: boolean
  /** Send as-is rather than JSON-encoding — used for file uploads. */
  raw?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, anonymous, raw, headers, ...rest } = options

  const send = async (): Promise<Response> => {
    const finalHeaders = new Headers(headers)
    if (!anonymous) {
      const token = tokenStore.access
      if (token) finalHeaders.set('Authorization', `Bearer ${token}`)
    }
    if (body !== undefined && !raw) {
      finalHeaders.set('Content-Type', 'application/json')
    }
    return fetch(`${BASE_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: body === undefined ? undefined : raw ? (body as BodyInit) : JSON.stringify(body),
    })
  }

  let response = await send()

  if (response.status === 401 && !anonymous) {
    if (await refreshAccessToken()) {
      response = await send()
    } else {
      tokenStore.clear()
      onSessionExpired?.()
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await parseProblem(response),
      `Request failed with status ${response.status}`,
    )
  }

  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('json')) return (await response.blob()) as T
  return (await response.json()) as T
}

export const http = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

export { BASE_URL }
