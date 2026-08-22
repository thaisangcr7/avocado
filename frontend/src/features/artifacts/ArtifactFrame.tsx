/**
 * Renders model-authored HTML without giving it this origin.
 *
 * An artifact is markup a model wrote after reading the user's documents. It is
 * untrusted input that happens to look like a web page, and the two obvious
 * ways to display it are both wrong:
 *
 *   - `dangerouslySetInnerHTML` executes it as part of this app. Any script in
 *     it would read `localStorage`, and the access token lives there.
 *   - An iframe pointed at a same-origin URL is no better; same origin is the
 *     whole problem.
 *
 * So it goes into `srcdoc` with a `sandbox` attribute that withholds
 * `allow-same-origin`. The frame gets an opaque origin: scripts run, which is
 * what makes a dashboard interactive, but they can reach neither this page's
 * DOM, its storage, nor its cookies. `allow-scripts` without
 * `allow-same-origin` is the specific pair that buys interactivity without
 * access — granting both together would silently undo the sandbox.
 */

import { useMemo } from 'react'

/** Everything withheld unless named. Notably absent: allow-same-origin. */
const SANDBOX = ['allow-scripts', 'allow-popups', 'allow-forms', 'allow-modals'].join(' ')

// The frame cannot reach the network either: a dashboard that phones home with
// the contents of a document would be an exfiltration path, and nothing here
// needs to load remotely.
const CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  "img-src data: blob:",
  "font-src data:",
].join('; ')

export function ArtifactFrame({ html, title }: { html: string; title: string }) {
  const document = useMemo(() => {
    const meta = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`
    // Injected after <head> when there is one, so the policy is in force before
    // anything in the document runs. Prepended otherwise.
    return /<head[^>]*>/i.test(html)
      ? html.replace(/<head[^>]*>/i, (match) => `${match}${meta}`)
      : `${meta}${html}`
  }, [html])

  return (
    <iframe
      srcDoc={document}
      sandbox={SANDBOX}
      title={title}
      className="h-full w-full rounded-lg border border-border-subtle bg-white"
      // referrerPolicy is belt and braces: with no network access there is
      // nothing to send a referrer to.
      referrerPolicy="no-referrer"
    />
  )
}
