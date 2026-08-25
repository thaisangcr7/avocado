import { describe, expect, it } from 'vitest'

import { isDemoLocation } from './route'

describe('isDemoLocation', () => {
  it('accepts the demo path', () => {
    expect(isDemoLocation({ pathname: '/demo', search: '' })).toBe(true)
    expect(isDemoLocation({ pathname: '/demo/', search: '' })).toBe(true)
  })

  it('accepts the demo query on any path', () => {
    expect(isDemoLocation({ pathname: '/', search: '?demo' })).toBe(true)
    expect(isDemoLocation({ pathname: '/', search: '?demo=1' })).toBe(true)
  })

  it('leaves every other location alone', () => {
    expect(isDemoLocation({ pathname: '/', search: '' })).toBe(false)
    expect(isDemoLocation({ pathname: '/demolition', search: '' })).toBe(false)
    expect(isDemoLocation({ pathname: '/invite/abc', search: '' })).toBe(false)
  })
})
