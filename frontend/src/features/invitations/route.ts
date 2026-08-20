/**
 * Invitation link routing.
 *
 * Kept apart from the page component so the module exports only a function —
 * mixing components and helpers in one file breaks React Fast Refresh.
 */

/** The invite token in a URL, or null when this is not an invitation link. */
export function inviteTokenFromLocation(pathname: string): string | null {
  const match = /^\/invite\/([A-Za-z0-9_-]+)\/?$/.exec(pathname)
  return match ? match[1]! : null
}
