/**
 * WebGL + reduced-motion detection for FoodBridge fallback switching.
 * Pure helpers kept separate so unit tests don't need a real GPU.
 */

export function isWebGLAvailable() {
  try {
    if (typeof document === 'undefined') return false
    const canvas = document.createElement('canvas')
    const gl =
      canvas.getContext('webgl2') ||
      canvas.getContext('webgl') ||
      canvas.getContext('experimental-webgl')
    // jsdom returns null; real browsers return a context. Some headless
    // environments return a stub object — treat null/undefined as unavailable.
    return !!gl
  } catch {
    return false
  }
}

export function prefersReducedMotion() {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * Single decision point used by the FoodBridge page:
 * fall back to 2D cards when WebGL is unavailable OR the user prefers
 * reduced motion (camera/scene animation is skipped, real data still shown).
 */
export function shouldUseFallback({ webglAvailable, reducedMotion } = {}) {
  const hasGL = typeof webglAvailable === 'boolean' ? webglAvailable : isWebGLAvailable()
  const reduced = typeof reducedMotion === 'boolean' ? reducedMotion : prefersReducedMotion()
  return !hasGL || reduced
}
