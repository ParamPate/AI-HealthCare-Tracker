'use client'

import { useEffect, useState, type RefObject } from 'react'

// One requestAnimationFrame loop shared by every animated tile.
const listeners = new Set<(now: number) => void>()
let raf = 0

function frame() {
  const now = performance.now() / 1000
  for (const l of listeners) l(now)
  raf = listeners.size ? requestAnimationFrame(frame) : 0
}

function subscribe(l: (now: number) => void) {
  listeners.add(l)
  if (!raf) raf = requestAnimationFrame(frame)
  return () => {
    listeners.delete(l)
  }
}

// Per-tile time, so a paused tile stays paused and its enlarged copy shows the same frame.
const pausedAt = new Map<string, number>()
const offset = new Map<string, number>()

export function tileTime(id: string, now = performance.now() / 1000) {
  return pausedAt.get(id) ?? now - (offset.get(id) ?? 0)
}

export function setPaused(id: string, paused: boolean) {
  const now = performance.now() / 1000
  if (paused && !pausedAt.has(id)) pausedAt.set(id, tileTime(id, now))
  if (!paused && pausedAt.has(id)) {
    offset.set(id, now - pausedAt.get(id)!)
    pausedAt.delete(id)
  }
}

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Seconds for tile `id`, ticking only while `el` is on screen and the tile is not paused. */
export function useTileTime(id: string, el: RefObject<HTMLElement | null>, running: boolean) {
  const [t, setT] = useState(() => (reducedMotion() ? 6 : tileTime(id)))

  useEffect(() => {
    if (reducedMotion()) return
    let visible = false
    let unsub: (() => void) | null = null
    const sync = () => {
      const want = visible && running
      if (want && !unsub) unsub = subscribe((now) => setT(tileTime(id, now)))
      if (!want && unsub) {
        unsub()
        unsub = null
      }
    }
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      sync()
    })
    if (el.current) io.observe(el.current)
    return () => {
      io.disconnect()
      unsub?.()
    }
  }, [id, el, running])

  return t
}
