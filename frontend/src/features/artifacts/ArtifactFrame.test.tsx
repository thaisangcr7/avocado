/**
 * The sandbox is the whole security model for artifacts, and it fails silently:
 * adding `allow-same-origin` would still render, still look right, and quietly
 * hand model-written script the access token in localStorage. So it is asserted
 * rather than assumed.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ArtifactFrame } from './ArtifactFrame'

function frameFor(html: string): HTMLIFrameElement {
  render(<ArtifactFrame html={html} title="Dashboard" />)
  return screen.getByTitle('Dashboard') as HTMLIFrameElement
}

describe('ArtifactFrame', () => {
  it('never grants the frame this origin', () => {
    const sandbox = frameFor('<html><body>hi</body></html>').getAttribute('sandbox') ?? ''
    expect(sandbox).not.toContain('allow-same-origin')
  })

  it('still allows scripts, or an interactive dashboard is just a picture', () => {
    const sandbox = frameFor('<html><body>hi</body></html>').getAttribute('sandbox') ?? ''
    expect(sandbox).toContain('allow-scripts')
  })

  it('renders through srcdoc rather than a same-origin URL', () => {
    const frame = frameFor('<html><body>hello</body></html>')
    expect(frame.getAttribute('srcdoc')).toContain('hello')
    expect(frame.getAttribute('src')).toBeNull()
  })

  it('puts a content policy in force before the document runs', () => {
    const srcdoc = frameFor('<html><head><title>x</title></head><body>hi</body></html>')
      .getAttribute('srcdoc')!

    // Inside <head>, and ahead of the document's own contents.
    expect(srcdoc).toContain('Content-Security-Policy')
    expect(srcdoc.indexOf('Content-Security-Policy')).toBeLessThan(srcdoc.indexOf('<title>'))
  })

  it('denies the frame the network, so a document cannot be exfiltrated', () => {
    const srcdoc = frameFor('<html><body>hi</body></html>').getAttribute('srcdoc')!
    expect(srcdoc).toContain("default-src 'none'")
  })

  it('still applies a policy to markup with no head element', () => {
    const srcdoc = frameFor('<div>fragment</div>').getAttribute('srcdoc')!
    expect(srcdoc).toContain('Content-Security-Policy')
    expect(srcdoc.indexOf('Content-Security-Policy')).toBeLessThan(srcdoc.indexOf('fragment'))
  })
})
