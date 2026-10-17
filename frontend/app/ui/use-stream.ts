'use client'

import { useEffect, useRef, useState } from 'react'

// Mirrors StreamFrame in backend/main.py.
export type Status = 'no_signal' | 'motion' | 'breathing' | 'pause'
export type Level = 'normal' | 'warning' | 'critical'
export type WavePoint = { t: number; breath: number | null } // t: Unix seconds

export type StreamFrame = {
  t: number | null
  sent_at: number
  breath: number | null
  rate_bpm: number | null
  status: Status
  reason: string | null
  source: 'fake' | 'serial' | 'replay'
  seq: number
  waveform: WavePoint[]
  waveform_delay_s: number
  alert: { id: string; kind: string } | null
  chair: string
  level: Level | null
  pause_s: number | null
  calm_s: number | null
  rssi: number | null
  packets_per_s: number | null
  ml_label?: 'breathing' | 'breath_hold' | 'checking' | 'motion' | 'no_signal' | null
  ml_hold_score?: number | null
  ml_model_version?: string | null
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
const KEEP_S = 40 // wave history kept for drawing

// The server sends either a whole recent window (board, replay) or single points (fake).
// Either way: drop what the new points cover, append them, keep the last KEEP_S.
function merge(history: WavePoint[], incoming: WavePoint[]): WavePoint[] {
  if (incoming.length === 0) return history
  const first = incoming[0].t
  const last = incoming[incoming.length - 1].t
  return history.filter((p) => p.t < first && p.t >= last - KEEP_S).concat(incoming)
}

export function useStream() {
  const [latest, setLatest] = useState<{ frame: StreamFrame; receivedAt: number } | null>(null)
  const [connected, setConnected] = useState(false)
  const wave = useRef<WavePoint[]>([])

  useEffect(() => {
    let ws: WebSocket | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    let lastKey = ''

    const connect = () => {
      ws = new WebSocket(WS_URL)
      ws.onopen = () => {
        wave.current = [] // a new connection may be a different source; start the wave fresh
        setConnected(true)
      }
      ws.onmessage = (event) => {
        const frame: StreamFrame = JSON.parse(event.data)
        const key = `${frame.seq}|${frame.status}|${frame.reason}`
        if (key === lastKey) return // the server repeats its latest frame 15 times a second
        lastKey = key
        wave.current = merge(wave.current, frame.waveform)
        setLatest({ frame, receivedAt: Date.now() / 1000 })
      }
      ws.onclose = () => {
        setConnected(false)
        if (!stopped) retry = setTimeout(connect, 1000)
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return { frame: latest?.frame ?? null, receivedAt: latest?.receivedAt ?? 0, connected, wave, url: WS_URL }
}
