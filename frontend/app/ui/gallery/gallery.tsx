'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ComponentType } from 'react'
import { createPortal } from 'react-dom'
import { lockScroll } from '../lock-scroll'
import { setPaused, useTileTime } from './clock'
import { PipelineMap } from './tile-map'
import { Breathe, LiveWave, Packet, Waterfall } from './tiles-dark'
import { Dashboard, HoldTest, Phone, Recordings } from './tiles-scenes'
import { Placement, RecordPanels, Replay } from './tiles-ui'

type Def = { id: string; label: string; w: number; h: number; bg: string; dark: boolean; Comp: ComponentType<{ t: number }> }

// Authored at the reference's column width (502 px); every tile scales with its column.
const LEFT: Def[] = [
  { id: 'record', label: 'Recording controls', w: 502, h: 423, bg: '#f6f6f6', dark: false, Comp: RecordPanels },
  { id: 'breathe', label: 'Breathe', w: 502, h: 479, bg: '#000', dark: true, Comp: Breathe },
  { id: 'waterfall', label: 'Subcarrier amplitude over time', w: 502, h: 502, bg: '#050505', dark: true, Comp: Waterfall },
  { id: 'packet', label: 'What one CSI line carries', w: 502, h: 282, bg: '#1c1c1e', dark: true, Comp: Packet },
  { id: 'phone', label: 'Phone alarm', w: 502, h: 502, bg: '#000', dark: true, Comp: Phone },
]
const RIGHT: Def[] = [
  { id: 'replay', label: 'Replaying a recording', w: 502, h: 250, bg: '#000', dark: true, Comp: Replay },
  { id: 'placement', label: 'Board placement', w: 502, h: 304, bg: '#f3f2ef', dark: false, Comp: Placement },
  { id: 'live', label: 'Live breathing wave', w: 502, h: 502, bg: '#000', dark: true, Comp: LiveWave },
  { id: 'recordings', label: 'Recorded sessions', w: 502, h: 378, bg: '#e9d5dc', dark: false, Comp: Recordings },
  { id: 'dashboard', label: 'Front desk view', w: 502, h: 325, bg: '#e4e6e9', dark: false, Comp: Dashboard },
  { id: 'holds', label: 'Breath-hold test', w: 502, h: 408, bg: '#f6f6f6', dark: false, Comp: HoldTest },
]
const WIDE: Def = { id: 'map', label: 'How the data flows', w: 1025, h: 759, bg: '#fbfbfb', dark: false, Comp: PipelineMap }

const ORDER: Def[] = [...LEFT.flatMap((d, i) => (RIGHT[i] ? [d, RIGHT[i]] : [d])), ...RIGHT.slice(LEFT.length), WIDE]

const noop = () => () => {}
const useClient = () => useSyncExternalStore(noop, () => true, () => false)

/** Renders a fixed-size design scaled to the width of its box. */
function Stage({ w, h, children }: { w: number; h: number; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState<number | null>(null)
  useLayoutEffect(() => {
    const el = box.current!
    const ro = new ResizeObserver(([e]) => setScale(e.contentRect.width / w))
    ro.observe(el)
    return () => ro.disconnect()
  }, [w])
  return (
    <div ref={box} className="absolute inset-0">
      {scale !== null && (
        <div className="absolute left-0 top-0 origin-top-left" style={{ width: w, height: h, transform: `scale(${scale})` }}>
          {children}
        </div>
      )}
    </div>
  )
}

function TileBody({ def, paused, onPause, tRef }: { def: Def; paused: boolean; onPause: () => void; tRef: React.RefObject<HTMLElement | null> }) {
  const t = useTileTime(def.id, tRef, !paused)
  const Comp = def.Comp
  return (
    <>
      <Stage w={def.w} h={def.h}>
        <Comp t={t} />
      </Stage>
      <button
        type="button"
        aria-label={paused ? `Play ${def.label}` : `Pause ${def.label}`}
        onClick={(e) => {
          e.stopPropagation()
          onPause()
        }}
        className={`absolute bottom-[14px] right-[14px] grid h-[22px] w-[22px] place-items-center rounded-full opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 ${
          def.dark ? 'bg-white/[0.12] text-white' : 'bg-black/[0.06] text-[#1f1f22]'
        } ${paused ? 'opacity-100' : ''}`}
      >
        {paused ? (
          <svg width="9" height="10" viewBox="0 0 9 10" fill="currentColor">
            <path d="M1.5 1.2v7.6a.5.5 0 00.77.42l5.9-3.8a.5.5 0 000-.84L2.27.78a.5.5 0 00-.77.42z" />
          </svg>
        ) : (
          <svg width="9" height="10" viewBox="0 0 9 10" fill="currentColor">
            <rect x="1.2" y="1" width="2.3" height="8" rx=".6" />
            <rect x="5.5" y="1" width="2.3" height="8" rx=".6" />
          </svg>
        )}
      </button>
    </>
  )
}

function Tile({ def, paused, onPause, onOpen, hidden, register }: { def: Def; paused: boolean; onPause: () => void; onOpen: (el: HTMLElement) => void; hidden: boolean; register: (el: HTMLElement | null) => void }) {
  const el = useRef<HTMLDivElement>(null)
  const client = useClient()
  return (
    <div
      ref={(node) => {
        el.current = node
        register(node)
      }}
      role="button"
      tabIndex={0}
      aria-label={`Enlarge: ${def.label}`}
      onClick={() => onOpen(el.current!)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(el.current!)
        }
      }}
      className="group relative w-full cursor-zoom-in overflow-hidden rounded-[12px] outline-none focus-visible:ring-2 focus-visible:ring-[#1f1f22]/30"
      style={{ aspectRatio: `${def.w} / ${def.h}`, background: def.bg, opacity: hidden ? 0 : 1 }}
    >
      {client && <TileBody def={def} paused={paused} onPause={onPause} tRef={el} />}
    </div>
  )
}

type Open = { index: number; from: DOMRect }

export default function Gallery() {
  const [paused, setPausedState] = useState<Record<string, boolean>>({})
  const [open, setOpen] = useState<Open | null>(null)
  const els = useRef(new Map<string, HTMLElement>())
  const rectOf = useCallback((id: string) => els.current.get(id)?.getBoundingClientRect() ?? null, [])

  const togglePause = (id: string) => {
    const next = !paused[id]
    setPaused(id, next)
    setPausedState((p) => ({ ...p, [id]: next }))
  }

  const tile = (def: Def) => (
    <Tile
      key={def.id}
      def={def}
      paused={!!paused[def.id]}
      onPause={() => togglePause(def.id)}
      onOpen={(el) => setOpen({ index: ORDER.indexOf(def), from: el.getBoundingClientRect() })}
      hidden={open !== null && ORDER[open.index].id === def.id}
      register={(el) => {
        if (el) els.current.set(def.id, el)
        else els.current.delete(def.id)
      }}
    />
  )

  return (
    <>
      <div className="grid grid-cols-1 gap-[21px] md:grid-cols-2">
        <div className="flex flex-col gap-[21px]">{LEFT.map(tile)}</div>
        <div className="flex flex-col gap-[21px]">{RIGHT.map(tile)}</div>
        <div className="md:col-span-2">{tile(WIDE)}</div>
      </div>
      {open && (
        <Lightbox
          open={open}
          paused={paused}
          onPause={togglePause}
          rectOf={rectOf}
          onNav={(index) => setOpen({ index, from: els.current.get(ORDER[index].id)!.getBoundingClientRect() })}
          onClosed={() => setOpen(null)}
        />
      )}
    </>
  )
}

// Like the reference: about 1.17x the tile's size in the grid, at most 64% of the screen height.
function fitRect(def: Def, gridWidth: number) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const small = vw < 768
  const s = Math.min((gridWidth * (small ? 1 : 1.17)) / def.w, (vw * 0.92) / def.w, (vh * (small ? 0.72 : 0.64)) / def.h)
  const w = def.w * s
  const h = def.h * s
  return { x: (vw - w) / 2, y: (vh - h) / 2, w, h }
}

function Lightbox({
  open,
  paused,
  onPause,
  rectOf,
  onNav,
  onClosed,
}: {
  open: Open
  paused: Record<string, boolean>
  onPause: (id: string) => void
  rectOf: (id: string) => DOMRect | null
  onNav: (index: number) => void
  onClosed: () => void
}) {
  const def = ORDER[open.index]
  const [target, setTarget] = useState(() => fitRect(def, open.from.width))
  const [phase, setPhase] = useState<'from' | 'open' | 'closing'>('from')
  const [from, setFrom] = useState(open.from)
  const card = useRef<HTMLDivElement>(null)
  const [navigated, setNavigated] = useState(false)
  const n = ORDER.length
  const prev = (open.index - 1 + n) % n
  const next = (open.index + 1) % n

  useEffect(() => {
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setPhase((p) => (p === 'from' ? 'open' : p))))
    const onResize = () => setTarget(fitRect(ORDER[open.index], (rectOf(ORDER[open.index].id) ?? open.from).width))
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
    }
  }, [open.index, open.from, rectOf])

  useEffect(() => lockScroll(), [])

  const close = () => {
    if (phase === 'closing') return
    setFrom(rectOf(def.id) ?? open.from)
    setPhase('closing')
    setTimeout(onClosed, 380)
  }

  const nav = (index: number) => {
    setNavigated(true)
    setTarget(fitRect(ORDER[index], (rectOf(ORDER[index].id) ?? open.from).width))
    onNav(index)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowLeft') nav(prev)
      if (e.key === 'ArrowRight') nav(next)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const atSource = phase !== 'open'
  const transform = atSource
    ? `translate(${from.left - target.x}px, ${from.top - target.y}px) scale(${from.width / target.w}, ${from.height / target.h})`
    : 'none'

  return createPortal(
    <div className="fixed inset-0 z-[90] font-body" role="dialog" aria-modal="true" aria-label={def.label}>
      <div
        className="absolute inset-0 bg-[#fafafa] transition-opacity duration-[380ms] ease-out"
        style={{ opacity: atSource ? 0 : 0.94 }}
        onClick={close}
      />
      <button
        type="button"
        onClick={() => nav(prev)}
        aria-label="Previous"
        className="absolute left-[22px] top-1/2 -translate-y-1/2 px-[8px] py-[6px] text-[15px] tabular-nums text-[#6d6d72] transition-[color,opacity] duration-300 hover:text-[#1f1f22]"
        style={{ opacity: atSource ? 0 : 1 }}
      >
        {prev + 1}
      </button>
      <button
        type="button"
        onClick={() => nav(next)}
        aria-label="Next"
        className="absolute right-[22px] top-1/2 -translate-y-1/2 px-[8px] py-[6px] text-[15px] tabular-nums text-[#6d6d72] transition-[color,opacity] duration-300 hover:text-[#1f1f22]"
        style={{ opacity: atSource ? 0 : 1 }}
      >
        {next + 1}
      </button>
      <button
        type="button"
        onClick={close}
        aria-label="Close"
        className="absolute right-[18px] top-[18px] grid h-[22px] w-[22px] place-items-center text-[#6d6d72] transition-[color,opacity] duration-300 hover:text-[#1f1f22]"
        style={{ opacity: atSource ? 0 : 1 }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <path d="M1.5 1.5l9 9M10.5 1.5l-9 9" />
        </svg>
      </button>
      <div
        ref={card}
        key={def.id}
        onClick={close}
        className="group absolute cursor-zoom-out overflow-hidden rounded-[12px]"
        style={{
          left: target.x,
          top: target.y,
          width: target.w,
          height: target.h,
          background: def.bg,
          transform,
          transformOrigin: '0 0',
          transition: phase === 'from' ? 'none' : 'transform 420ms cubic-bezier(0.2, 0.85, 0.25, 1)',
          boxShadow: atSource ? 'none' : '0 20px 60px rgba(0,0,0,0.08)',
          animation: navigated && phase === 'open' ? 'tile-in 260ms ease-out' : undefined,
        }}
      >
        <TileBody def={def} paused={!!paused[def.id]} onPause={() => onPause(def.id)} tRef={card} />
      </div>
    </div>,
    document.body,
  )
}
