/**
 * The HTTP client's auth behaviour.
 *
 * The case worth protecting is concurrent 401s: if each fires its own refresh,
 * they invalidate each other's refresh token and the user is logged out
 * mid-session for no visible reason.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, http, resolveBaseUrl, setSessionExpiredHandler, tokenStore } from './client'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  }
}

describe('tokenStore', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips and clears tokens', () => {
    tokenStore.set('a', 'r')
    expect(tokenStore.access).toBe('a')
    expect(tokenStore.refresh).toBe('r')

    tokenStore.clear()
    expect(tokenStore.access).toBeNull()
  })
})

describe('http', () => {
  beforeEach(() => {
    localStorage.clear()
    delete window.__AVOCADO_CONFIG__
    tokenStore.set('access-1', 'refresh-1')
  })

  it('attaches the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await http.get('/workspaces')

    const headers = fetchMock.mock.calls[0]?.[1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer access-1')
  })

  it('omits the token on anonymous requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)

    await http.post('/auth/login', { email: 'a@b.com' }, { anonymous: true })

    const headers = fetchMock.mock.calls[0]?.[1].headers as Headers
    expect(headers.get('Authorization')).toBeNull()
  })

  it('throws an ApiError carrying the problem details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(404, {
          type: 'https://avocado.dev/errors/not-found',
          title: 'Not Found',
          status: 404,
          detail: 'Document not found.',
        }),
      ),
    )

    await expect(http.get('/documents/x')).rejects.toThrowError(ApiError)
    await expect(http.get('/documents/x')).rejects.toThrowError('Document not found.')
  })

  it('exposes field errors from a 422', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          type: 'x',
          title: 'Validation Failed',
          status: 422,
          detail: 'Invalid.',
          errors: [{ field: 'email', message: 'not a valid email address' }],
        }),
      ),
    )

    try {
      await http.post('/auth/register', {}, { anonymous: true })
      expect.unreachable('should have thrown')
    } catch (error) {
      expect((error as ApiError).fieldErrors).toEqual({
        email: 'not a valid email address',
      })
    }
  })

  it('refreshes once on a 401 and retries the request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' }))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-2', refresh_token: 'refresh-2' }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await http.get<{ ok: boolean }>('/workspaces')

    expect(result).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(tokenStore.access).toBe('access-2')
  })

  it('shares one refresh across concurrent 401s', async () => {
    let refreshCalls = 0
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        return Promise.resolve(
          jsonResponse(200, { access_token: 'access-2', refresh_token: 'refresh-2' }),
        )
      }
      // Every protected call 401s the first time, succeeds after refresh.
      return Promise.resolve(
        tokenStore.access === 'access-2'
          ? jsonResponse(200, { ok: true })
          : jsonResponse(401, { detail: 'expired' }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    await Promise.all([
      http.get('/workspaces'),
      http.get('/models'),
      http.get('/auth/me'),
    ])

    // Three simultaneous 401s must produce exactly one refresh, or they
    // invalidate each other's token.
    expect(refreshCalls).toBe(1)
  })

  it('signals session expiry when the refresh itself fails', async () => {
    const onExpired = vi.fn()
    setSessionExpiredHandler(onExpired)

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve(
          url.endsWith('/auth/refresh')
            ? jsonResponse(401, { detail: 'invalid' })
            : jsonResponse(401, { detail: 'expired' }),
        ),
      ),
    )

    await expect(http.get('/workspaces')).rejects.toThrowError(ApiError)
    expect(onExpired).toHaveBeenCalled()
    expect(tokenStore.access).toBeNull()
  })

  it('prefers a runtime base url over the build-time default', async () => {
    window.__AVOCADO_CONFIG__ = { apiBaseUrl: 'https://demo.example.com/api/v1' }
    expect(resolveBaseUrl()).toBe('https://demo.example.com/api/v1')
  })
})
