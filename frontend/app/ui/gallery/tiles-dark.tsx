'use client'

// Dark tiles: the breathing word, the CSI heatmap, the packet layout, the live wave.
import { useEffect, useId, useRef } from 'react'
import { clamp, hash, linePath, mod, smooth, story, storyBreath, TAU } from './signal'

/** "breathe" written in light, then breathing. */
export function Breathe({ t }: { t: number }) {
  const id = useId().replace(/:/g, '')
  const s = mod(t, 9)
  const draw = smooth(0.3, 3.0, s)
  const fill = smooth(2.3, 3.4, s)
  const out = smooth(8.1, 8.9, s)
  const swell = 1 + 0.035 * smooth(3, 4, s) * Math.sin(TAU * (s - 3) / 4.2)
  const len = 900

  return (
    <svg viewBox="0 0 502 479" className="absolute inset-0 h-full w-full bg-black">
      <defs>
        <linearGradient id={`g${id}`} x1="0" x2="1" y1="0" y2="0.3">
          <stop offset="0" stopColor="#ff7ad9" />
          <stop offset="0.3" stopColor="#c58bff" />
          <stop offset="0.55" stopColor="#7fb2ff" />
          <stop offset="0.78" stopColor="#6ff0d0" />
          <stop offset="1" stopColor="#ffe178" />
        </linearGradient>
        <filter id={`b${id}`} x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="2.4" />
        </filter>
      </defs>
      <g transform={`translate(251 236) scale(${swell}) translate(-251 -236)`} opacity={1 - out} style={{ fontFamily: 'var(--font-script)' }}>
        <text x="251" y="252" textAnchor="middle" fontSize="54" fill="none" stroke={`url(#g${id})`} strokeWidth="4" strokeDasharray={len} strokeDashoffset={len * (1 - draw)} filter={`url(#b${id})`} opacity={0.55}>
          breathe
        </text>
        <text x="251" y="252" textAnchor="middle" fontSize="54" fill="none" stroke={`url(#g${id})`} strokeWidth="2.6" strokeLinejoin="round" strokeDasharray={len} strokeDashoffset={len * (1 - draw)}>
          breathe
        </text>
        <text x="251" y="252" textAnchor="middle" fontSize="54" fill="white" opacity={fill}>
          breathe
        </text>
      </g>
    </svg>
  )
}

// magma-like ramp for the heatmap
const RAMP = [
  [0, 0, 4],
  [40, 15, 95],
  [118, 36, 129],
  [196, 60, 117],
  [247, 112, 92],
  [254, 182, 123],
  [252, 253, 191],
]

function ramp(v: number) {
  const x = clamp(v) * (RAMP.length - 1)
  const i = Math.min(RAMP.length - 2, Math.floor(x))
  const f = x - i
  const a = RAMP[i]
  const b = RAMP[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

const COLS = 180
const ROWS = 52
const SPAN = 30

function moving(tau: number) {
  const m = mod(tau, 19)
  return m > 9 && m < 10.6
}

/** Per-subcarrier amplitude over the last 30 s, like backend/live_view.py. */
export function Waterfall({ t }: { t: number }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const step = SPAN / COLS
  const end = Math.floor(t / step)

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    const img = ctx.createImageData(COLS, ROWS)
    for (let c = 0; c < COLS; c++) {
      const n = end - (COLS - 1 - c)
      const tau = n * step
      const b = storyBreath(tau)
      const move = moving(tau)
      for (let k = 0; k < ROWS; k++) {
        const base = 0.42 + 0.2 * Math.sin(k * 0.23 + 1) + 0.12 * Math.sin(k * 0.071 + 2.2) - (k < 2 ? 0.4 : 0)
        const weight = Math.sin(k * 0.31 + 0.4) * (0.5 + 0.5 * Math.sin(k * 0.05))
        let v = base + 0.07 * weight * b + 0.03 * (hash(k * 913 + n) - 0.5)
        if (move) v += 0.42 * (hash(k * 37 + Math.floor(n / 2) * 7) - 0.4)
        const [r, g, bb] = ramp(v)
        const o = ((ROWS - 1 - k) * COLS + c) * 4
        img.data[o] = r
        img.data[o + 1] = g
        img.data[o + 2] = bb
        img.data[o + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, [end, step])

  const pts: [number, number][] = []
  const x0 = 40
  const x1 = 462
  const marks: number[] = []
  for (let i = 0; i <= 150; i++) {
    const tau = t - SPAN + (i / 150) * SPAN
    const v = moving(tau) ? 0.6 * (hash(Math.floor(tau * 6)) - 0.5) : storyBreath(tau)
    pts.push([x0 + (i / 150) * (x1 - x0), 404 - v * 22])
    if (moving(tau) && !moving(tau - SPAN / 150)) marks.push(x0 + (i / 150) * (x1 - x0))
  }

  return (
    <div className="absolute inset-0 bg-[#050505] font-mono">
      <div className="absolute left-[40px] top-[38px] text-[8px] text-[#8b8b90]">subcarrier amplitude</div>
      <div className="absolute right-[40px] top-[38px] text-[8px] text-[#55555a]">last 30 s</div>
      <canvas ref={canvas} width={COLS} height={ROWS} className="absolute left-[40px] top-[56px] h-[250px] w-[422px] rounded-[3px]" />
      <div className="absolute left-[24px] top-[52px] text-[6.5px] text-[#55555a]">52</div>
      <div className="absolute left-[29px] top-[298px] text-[6.5px] text-[#55555a]">0</div>
      <div className="absolute left-[40px] top-[340px] text-[8px] text-[#8b8b90]">smoothed preview</div>
      <svg viewBox="0 0 502 502" className="absolute inset-0 h-full w-full">
        <line x1={x0} x2={x1} y1={404} y2={404} stroke="#1c1c1f" />
        {marks.map((x) => (
          <g key={x}>
            <rect x={x} y={366} width={(1.6 / SPAN) * (x1 - x0)} height={76} fill="#f5a524" opacity={0.12} />
            <text x={x + 3} y={374} fontSize={6.5} fill="#f5a524">
              movement
            </text>
          </g>
        ))}
        <path d={linePath(pts)} fill="none" stroke="#3ddc84" strokeWidth={1.4} strokeLinejoin="round" />
        <text x={x0} y={462} fontSize={6.5} fill="#55555a">
          -30 s
        </text>
        <text x={x1} y={462} fontSize={6.5} fill="#55555a" textAnchor="end">
          now
        </text>
      </svg>
    </div>
  )
}

type Field = [label: string, w: number, value?: string]

/** What one CSI_DATA line from the receiver carries. */
export function Packet({ t }: { t: number }) {
  const seq = 4229 + Math.floor(t * 11)
  const rssi = -49 - Math.floor(hash(Math.floor(t * 2.5)) * 6)
  const rows: Field[][] = [
    [['CSI_DATA', 50], ['seq', 92, `sequence number · ${seq}`], ['mac', 62], ['rssi', 34, `${rssi}`], ['rate', 30], ['mode … sgi', 60], ['noise', 46]],
    [['ampdu', 40], ['channel', 44, '6'], ['2nd', 30], ['local timestamp', 150], ['ant', 28], ['sig_len', 50], ['rx_state', 32]],
    [['len', 40, '384'], ['first_word', 48], ['data  [im0, re0, im1, re1, …]', 286]],
  ]
  const x0 = 64
  const y0 = 92
  const rowH = 20
  const gap = 4
  const bars = Array.from({ length: 48 }, (_, i) => 0.3 + 0.6 * Math.abs(Math.sin(i * 0.29 + 1)) + 0.12 * (hash(i * 17 + Math.floor(t * 8)) - 0.5))

  return (
    <svg viewBox="0 0 502 282" className="absolute inset-0 h-full w-full bg-[#1c1c1e] font-body">
      <g stroke="#5b5b60" strokeWidth={0.6}>
        <line x1={x0} x2={x0 + 374} y1={70} y2={70} />
        {Array.from({ length: 26 }, (_, i) => (
          <line key={i} x1={x0 + (i / 25) * 374} x2={x0 + (i / 25) * 374} y1={i % 5 === 0 ? 65 : 67.5} y2={70} />
        ))}
      </g>
      {[0, 5, 10, 15, 20, 25].map((v) => (
        <text key={v} x={x0 + (v / 25) * 374} y={61} fontSize={6} fill="#6d6d72" textAnchor="middle">
          {v}
        </text>
      ))}
      {rows.map((row, r) => {
        let x = x0
        return row.map(([label, w, value]) => {
          const cx = x
          x += w
          const data = label.startsWith('data')
          return (
            <g key={label}>
              <rect x={cx} y={y0 + r * (rowH + gap)} width={w} height={rowH} fill="none" stroke="#8e8e93" strokeWidth={0.7} />
              {data && (
                <g>
                  {bars.map((b, i) => (
                    <rect key={i} x={cx + 128 + i * 3.2} y={y0 + r * (rowH + gap) + rowH - 3 - b * 12} width={1.8} height={b * 12} fill="#3a3a3f" />
                  ))}
                </g>
              )}
              <text
                x={cx + (data ? 6 : w / 2)}
                y={y0 + r * (rowH + gap) + 12.6}
                fontSize={value && !data ? 6.6 : 6.3}
                fill={value ? '#f2f2f4' : '#a1a1a6'}
                textAnchor={data ? 'start' : 'middle'}
                className="tabular-nums"
              >
                {value ?? label}
              </text>
            </g>
          )
        })
      })}
      <g stroke="#8e8e93" strokeWidth={0.6} fill="none">
        <path d={`M${x0 + 382} ${y0}h6v${3 * rowH + 2 * gap}h-6`} />
        <line x1={x0} x2={x0 + 374} y1={y0 + 3 * (rowH + gap) + 8} y2={y0 + 3 * (rowH + gap) + 8} />
        <line x1={x0} x2={x0} y1={y0 + 3 * (rowH + gap) + 4} y2={y0 + 3 * (rowH + gap) + 12} />
        <line x1={x0 + 374} x2={x0 + 374} y1={y0 + 3 * (rowH + gap) + 4} y2={y0 + 3 * (rowH + gap) + 12} />
      </g>
      <text x={x0 + 396} y={y0 + 38} fontSize={6} fill="#6d6d72">
        1 line
      </text>
      <text x={x0 + 187} y={y0 + 3 * (rowH + gap) + 20} fontSize={6} fill="#6d6d72" textAnchor="middle">
        25 columns
      </text>
      <text x={x0} y={y0 + 3 * (rowH + gap) + 40} fontSize={6.2} fill="#6d6d72">
        one line per packet, about 71 a second, 192 subcarriers each
      </text>
      <text x={72} y={246} fontSize={5.6} fill="#55555a">
        fig. CSI-1
      </text>
    </svg>
  )
}

/** The monitor's main view: status, rate or pause seconds, and the wave. */
export function LiveWave({ t }: { t: number }) {
  const st = story(t)
  const x0 = 40
  const x1 = 462
  const base = 330
  const segs: { d: string; red: boolean }[] = []
  let cur: [number, number][] = []
  let red = false
  for (let i = 0; i <= 160; i++) {
    const tau = t - 30 + (i / 160) * 30
    const p: [number, number] = [x0 + (i / 160) * (x1 - x0), base - storyBreath(tau) * 30]
    const r = story(tau).pausing
    if (i > 0 && r !== red) {
      cur.push(p)
      segs.push({ d: linePath(cur), red })
      cur = []
    }
    red = r
    cur.push(p)
  }
  segs.push({ d: linePath(cur), red })
  const alarm = st.pausing

  return (
    <div className="absolute inset-0 overflow-hidden bg-black font-body">
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{ opacity: alarm ? 1 : 0, background: 'radial-gradient(120% 80% at 50% 45%, rgba(229,72,77,0.22), rgba(229,72,77,0) 70%)' }}
      />
      <div className="absolute left-[40px] right-[40px] top-[40px] flex items-center justify-between text-[9px]">
        <span>
          <span className="text-[13px] font-semibold text-white">Chair 1</span>
          <span className="text-[#77777c]"> · waiting room</span>
        </span>
        <span className="flex items-center gap-[5px] text-[#b4b4b8]">
          <span className="h-[5px] w-[5px] animate-pulse rounded-full bg-[#3ddc84]" />
          LIVE sensor
        </span>
      </div>
      <div className="absolute left-[40px] top-[98px] flex items-center gap-[8px]">
        <span
          className={`rounded-full px-[9px] py-[3px] text-[8px] font-bold tracking-[0.06em] ring-1 ${
            alarm ? 'bg-[#3b0d12] text-[#ffb3b6] ring-[#8f1d26]' : 'bg-[#0b2a17] text-[#7ee2a4] ring-[#1d5a33]'
          }`}
        >
          {alarm ? 'PAUSE' : 'BREATHING'}
        </span>
        {alarm && <span className="rounded-[5px] bg-[#3b0d12] px-[7px] py-[3px] text-[8px] font-bold text-[#ffb3b6] ring-1 ring-[#8f1d26]">CRITICAL</span>}
      </div>
      <div className="absolute left-[38px] top-[118px] flex items-baseline gap-[10px]">
        <span className={`text-[64px] font-semibold tracking-[-0.03em] tabular-nums ${alarm ? 'text-[#ff9ea2]' : 'text-white'}`}>
          {alarm ? `${Math.floor(st.pauseS)} s` : st.rate.toFixed(1)}
        </span>
        <span className="text-[13px] text-[#77777c]">{alarm ? 'without a breath' : 'breaths/min'}</span>
      </div>
      <svg viewBox="0 0 502 502" className="absolute inset-0 h-full w-full">
        <line x1={x0} x2={x1} y1={base} y2={base} stroke="#1f1f23" />
        {segs.map((s, i) => (
          <path key={i} d={s.d} fill="none" stroke={s.red ? '#ff6b70' : '#3ddc84'} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        <text x={x0} y={392} fontSize={7} fill="#55555a">
          34 s ago
        </text>
        <text x={x1} y={392} fontSize={7} fill="#55555a" textAnchor="end">
          4 s ago
        </text>
      </svg>
      <div className="absolute bottom-[40px] left-[40px] right-[40px] flex justify-between text-[7.5px] text-[#55555a]">
        <span>Signal good · RSSI -52 dBm · 71 packets/s</span>
        <span>Screening signal only, not a diagnosis.</span>
      </div>
    </div>
  )
}
