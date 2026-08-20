/**
 * Role comparison in the client.
 *
 * The client hides controls the server would refuse — a courtesy, not a
 * boundary. It still has to agree with the server's ordering, or it hides
 * things that would work and offers things that would not.
 */

import { describe, expect, it } from 'vitest'
import { ROLE_LABEL, ROLE_RANK, roleAtLeast, type Role } from './types'

describe('role ranking', () => {
  it('orders roles the way the server does', () => {
    expect(ROLE_RANK.org_admin).toBeGreaterThan(ROLE_RANK.team_admin)
    expect(ROLE_RANK.team_admin).toBeGreaterThan(ROLE_RANK.member)
    expect(ROLE_RANK.member).toBeGreaterThan(ROLE_RANK.viewer)
  })

  it.each([
    ['org_admin', 'team_admin', true],
    ['org_admin', 'org_admin', true],
    ['team_admin', 'member', true],
    ['member', 'team_admin', false],
    ['viewer', 'member', false],
    ['viewer', 'viewer', true],
  ] as [Role, Role, boolean][])('roleAtLeast(%s, %s) === %s', (role, minimum, expected) => {
    expect(roleAtLeast(role, minimum)).toBe(expected)
  })

  it('labels every role', () => {
    for (const role of Object.keys(ROLE_RANK) as Role[]) {
      expect(ROLE_LABEL[role]).toBeTruthy()
    }
  })

  it('offers only roles at or below the granter for each role', () => {
    // Mirrors the server rule: nobody may grant above their own role.
    const grantable = (actor: Role) =>
      (Object.keys(ROLE_RANK) as Role[]).filter((r) => ROLE_RANK[r] <= ROLE_RANK[actor])

    expect(grantable('team_admin').sort()).toEqual(['member', 'team_admin', 'viewer'])
    expect(grantable('org_admin')).toHaveLength(4)
    expect(grantable('viewer')).toEqual(['viewer'])
  })
})
