'use client'

import { useEffect, useRef, useState } from 'react'
import Explorer from './explorer'
import { RoomView } from './room-view'

export default function RoomCard() {
  const canvas = useRef<HTMLCanvasElement>(null)
  const view = useRef<RoomView | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const [zone, setZone] = useState(0)
  const [open, setOpen] = useState(false)
  const openRef = useRef(open)
  const onScreen = useRef(true)

  useEffect(() => {
    const v = new RoomView(canvas.current!, 'card', (s) => setZone(s.zone))
    view.current = v
    const io = new IntersectionObserver(([entry]) => {
      onScreen.current = entry.isIntersecting
      v.setActive(entry.isIntersecting && !openRef.current)
    })
    io.observe(box.current!)
    return () => {
      io.disconnect()
      v.dispose()
      view.current = null
    }
  }, [])

  useEffect(() => {
    openRef.current = open
    view.current?.setActive(onScreen.current && !open)
  }, [open])

  return (
    <div
      ref={box}
      className="relative aspect-[502/350] w-full overflow-hidden rounded-[12px] border border-[#f1f1f1] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.025)]"
    >
      <canvas ref={canvas} className="absolute inset-0 block h-full w-full" aria-label="Line drawing of the waiting room" />
      <div className="pointer-events-none absolute left-[10px] top-[8px] font-hand text-[15px] leading-[20px] text-[#2c2c2e]">
        our waiting room
      </div>
      <button
        type="button"
        aria-label="Explore the room in 3D"
        title="Explore in 3D"
        onClick={() => setOpen(true)}
        className="absolute right-[10px] top-[8px] grid h-[22px] w-[22px] place-items-center text-[#8d8d92] transition-colors hover:text-[#1f1f22]"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8.5 1.5h4v4M12.5 1.5L8 6M5.5 12.5h-4v-4M1.5 12.5L6 8" />
        </svg>
      </button>
      <Arrow side="left" onClick={() => view.current?.step(-1)} />
      <Arrow side="right" onClick={() => view.current?.step(1)} />
      {open && <Explorer zone={zone} onClose={() => setOpen(false)} />}
    </div>
  )
}

function Arrow({ side, onClick }: { side: 'left' | 'right'; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={side === 'left' ? 'Previous corner' : 'Next corner'}
      onClick={onClick}
      className={`absolute top-1/2 grid h-[30px] w-[24px] -translate-y-1/2 place-items-center text-[#9a9a9f] transition-colors hover:text-[#1f1f22] ${
        side === 'left' ? 'left-[8px]' : 'right-[8px]'
      }`}
    >
      <svg width="9" height="15" viewBox="0 0 9 15" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
        <path d={side === 'left' ? 'M7.5 1.5L1.5 7.5l6 6' : 'M1.5 1.5l6 6-6 6'} />
      </svg>
    </button>
  )
}
