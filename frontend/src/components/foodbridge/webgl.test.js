import { describe, it, expect, vi, afterEach } from 'vitest'
import { isWebGLAvailable, prefersReducedMotion, shouldUseFallback } from './webgl'

describe('webgl fallback triggers', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shouldUseFallback is true when WebGL is unavailable', () => {
    expect(shouldUseFallback({ webglAvailable: false, reducedMotion: false })).toBe(true)
  })

  it('shouldUseFallback is true on reduced motion even with WebGL', () => {
    expect(shouldUseFallback({ webglAvailable: true, reducedMotion: true })).toBe(true)
  })

  it('shouldUseFallback is false when WebGL works and no reduced motion', () => {
    expect(shouldUseFallback({ webglAvailable: true, reducedMotion: false })).toBe(false)
  })

  it('isWebGLAvailable returns false in jsdom (no GPU)', () => {
    // jsdom canvas has no getContext support for webgl
    expect(isWebGLAvailable()).toBe(false)
  })

  it('prefersReducedMotion follows matchMedia', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    expect(prefersReducedMotion()).toBe(true)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    expect(prefersReducedMotion()).toBe(false)
  })

  it('prefersReducedMotion is false when matchMedia is missing', () => {
    vi.stubGlobal('matchMedia', undefined)
    // window.matchMedia not a function -> safe false
    const orig = window.matchMedia
    // @ts-ignore
    window.matchMedia = undefined
    expect(prefersReducedMotion()).toBe(false)
    window.matchMedia = orig
  })
})
