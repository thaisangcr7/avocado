import { describe, expect, it } from 'vitest'
import { inviteTokenFromLocation } from './route'

describe('inviteTokenFromLocation', () => {
  it('extracts the token from an invite link', () => {
    expect(inviteTokenFromLocation('/invite/qMBwjaqma7BMRbWk6v5xaw3')).toBe(
      'qMBwjaqma7BMRbWk6v5xaw3',
    )
  })

  it('tolerates a trailing slash', () => {
    expect(inviteTokenFromLocation('/invite/abc123/')).toBe('abc123')
  })

  it('accepts the urlsafe-base64 alphabet the server issues', () => {
    const token = '3SDFvvoSDA85-rdXIbZIpOaFMHRZMRVxQdgD511shMk'
    expect(inviteTokenFromLocation(`/invite/${token}`)).toBe(token)
  })

  it.each(['/', '/workspaces', '/invite', '/invite/', '/invite/a/b', '/other/abc'])(
    'returns null for %s',
    (path) => {
      expect(inviteTokenFromLocation(path)).toBeNull()
    },
  )
})
