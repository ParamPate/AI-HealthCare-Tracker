export const TAU = Math.PI * 2

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v))
export const mod = (a: number, n: number) => ((a % n) + n) % n
export const smooth = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}

/** Deterministic noise in [0, 1). */
export function hash(i: number) {
  const s = Math.sin(i * 127.1 + 311.7) * 43758.5453
  return s - Math.floor(s)
}

/** A breathing-like wave: a slow rise and fall with a little second harmonic. */
export function breath(t: number, rate = 14) {
  const f = rate / 60
  return Math.sin(TAU * f * t) + 0.18 * Math.sin(2 * TAU * f * t + 0.7) + 0.05 * Math.sin(TAU * 1.7 * t)
}

/**
 * The story every live tile tells, on a 24 s loop: steady breathing, a 7 s pause, then recovery.
 * pauseS starts at 3 because the monitor only calls a pause once a few breaths are missing.
 */
export const STORY = { period: 24, pauseFrom: 13, pauseTo: 20 }

export function story(t: number) {
  const s = mod(t, STORY.period)
  const pausing = s >= STORY.pauseFrom && s < STORY.pauseTo
  const amp = 1 - smooth(STORY.pauseFrom - 0.4, STORY.pauseFrom + 0.6, s) + smooth(STORY.pauseTo, STORY.pauseTo + 1.2, s)
  return {
    s,
    pausing,
    pauseS: pausing ? s - STORY.pauseFrom + 3 : 0,
    amp: clamp(amp),
    rate: 14.2 + Math.sin(t / 7) * 0.4,
  }
}

/** Breath value at time t following the story (flat during the pause). */
export function storyBreath(t: number) {
  const { amp } = story(t)
  return breath(t) * amp + (1 - amp) * 0.04 * Math.sin(TAU * 0.9 * t)
}

export function linePath(pts: [number, number][]) {
  let d = ''
  for (let i = 0; i < pts.length; i++) d += `${i ? 'L' : 'M'}${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)}`
  return d
}
