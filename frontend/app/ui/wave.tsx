'use client'

import { useEffect, useRef, type RefObject } from 'react'
import type { WavePoint } from './use-stream'

export const SPAN_S = 30 // seconds shown
export const LAG_S = 1.2 // new data arrives about once a second; draw just behind it so the wave scrolls smoothly
const RANGE = 2.5 // breath values have about unit spread; +-RANGE fills the height

type Props = {
  wave: RefObject<WavePoint[]>
  delay: number // seconds between now and the newest point the server sends
  pauseStart: number | null // Unix seconds; the wave is red from here on
  color: string
  pauseColor: string
}

// Redrawn every animation frame against the clock, so it scrolls instead of jumping once a second.
export default function Wave(props: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const latest = useRef(props)

  useEffect(() => {
    latest.current = props
  })

  useEffect(() => {
    const c = canvas.current
    const ctx = c?.getContext('2d')
    if (!c || !ctx) return
    let raf = 0

    const draw = () => {
      const { wave, delay, pauseStart, color, pauseColor } = latest.current
      const dpr = window.devicePixelRatio || 1
      const w = c.clientWidth
      const h = c.clientHeight
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
        c.width = Math.round(w * dpr)
        c.height = Math.round(h * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, h / 2)
      ctx.lineTo(w, h / 2)
      ctx.stroke()

      const right = Date.now() / 1000 - delay - LAG_S
      const left = right - SPAN_S
      const x = (t: number) => ((t - left) / SPAN_S) * w
      const y = (b: number) => h / 2 - Math.max(-1, Math.min(1, b / RANGE)) * (h / 2 - 3)

      ctx.lineWidth = 2.5
      ctx.lineJoin = 'round'
      let open = false
      let stroke = ''
      let prevT = -Infinity
      for (const p of wave.current) {
        if (p.breath === null || p.t < left - 1 || p.t > right + 1 || p.t - prevT > 1.5) {
          if (open) ctx.stroke()
          open = false
        }
        prevT = p.t
        if (p.breath === null || p.t < left - 1 || p.t > right + 1) continue
        const px = x(p.t)
        const py = y(p.breath)
        const want = pauseStart !== null && p.t >= pauseStart ? pauseColor : color
        if (open && want === stroke) {
          ctx.lineTo(px, py)
          continue
        }
        if (open) {
          ctx.lineTo(px, py)
          ctx.stroke()
        }
        ctx.beginPath()
        ctx.strokeStyle = stroke = want
        ctx.moveTo(px, py)
        open = true
      }
      if (open) ctx.stroke()
      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  return <canvas ref={canvas} className="h-36 w-full" aria-label="Breathing wave, last 30 seconds" />
}
