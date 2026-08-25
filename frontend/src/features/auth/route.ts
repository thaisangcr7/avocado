/**
 * Demo-link routing.
 *
 * Kept apart from the page component so the module exports only a function —
 * mixing components and helpers in one file breaks React Fast Refresh.
 */

/**
 * True when the URL asks to open straight into the public demo, skipping the
 * sign-in screen. Both `/demo` and `?demo` are accepted: the path is what a
 * demo link looks like, and the query is what survives a host that serves the
 * app from a subdirectory.
 */
export function isDemoLocation(location: { pathname: string; search: string }): boolean {
  if (/^\/demo\/?$/.test(location.pathname)) return true
  return new URLSearchParams(location.search).has('demo')
}
