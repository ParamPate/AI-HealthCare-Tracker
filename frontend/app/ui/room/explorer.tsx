'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { lockScroll } from '../lock-scroll'
import { ZONES } from './models'
import { RoomView, type ViewState } from './room-view'
import type { Theme } from './sketch'

let audio: AudioContext | null = null

function tick() {
  audio ??= new AudioContext()
  const t = audio.currentTime
  const osc = audio.createOscillator()
  const gain = audio.createGain()
  osc.frequency.setValueAtTime(880, t)
  osc.frequency.exponentialRampToValueAtTime(520, t + 0.06)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(0.05, t + 0.005)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.09)
  osc.connect(gain).connect(audio.destination)
  osc.start(t)
  osc.stop(t + 0.1)
}

const HELP = ['drag to look around', 'click a corner to step in', 'click anything to pick it up', 'pinch to look closer', 'esc to step back']

export default function Explorer({ zone, onClose }: { zone: number; onClose: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const view = useRef<RoomView | null>(null)
  const [state, setState] = useState<ViewState | null>(null)
  const [shown, setShown] = useState(false)
  const [theme, setTheme] = useState<Theme>('light')
  const [help, setHelp] = useState(true)
  const [info, setInfo] = useState(false)
  const [sound, setSound] = useState(true)
  const [dragging, setDragging] = useState(false)
  const soundRef = useRef(sound)
  const closing = useRef(false)

  useEffect(() => {
    soundRef.current = sound
  }, [sound])

  const blip = () => {
    if (soundRef.current) tick()
  }

  const close = () => {
    if (closing.current) return
    closing.current = true
    setShown(false)
    setTimeout(onClose, 260)
  }

  useEffect(() => {
    const v = new RoomView(canvas.current!, 'explorer', setState)
    v.onPick = () => {
      if (soundRef.current) tick()
    }
    view.current = v
    const show = requestAnimationFrame(() => setShown(true))
    const fly = setTimeout(() => v.showZone(zone, 1.6), 250)
    const unlock = lockScroll()
    return () => {
      cancelAnimationFrame(show)
      clearTimeout(fly)
      unlock()
      v.dispose()
      view.current = null
    }
  }, [zone])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const v = view.current
      if (!v) return
      if (e.key === 'Escape') {
        if (!v.back()) close()
      } else if (v.state.mode === 'object' && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        v.step(e.key === 'ArrowLeft' ? -1 : 1)
        blip()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    view.current?.setTheme(theme)
  }, [theme])

  const dark = theme === 'dark'
  const mode = state?.mode ?? 'room'
  const object = mode === 'object'
  const fg = dark ? 'text-neutral-200' : 'text-neutral-800'
  const muted = dark ? 'text-neutral-400 hover:text-neutral-100' : 'text-neutral-500 hover:text-neutral-900'
  const pill = dark ? 'border-neutral-800 bg-neutral-900' : 'border-neutral-200/80 bg-[#fdfdfd]'

  return createPortal(
    <div
      className={`fixed inset-0 z-[100] transition-opacity duration-300 ${shown ? 'opacity-100' : 'opacity-0'} ${dark ? 'bg-[#141416]' : 'bg-white'}`}
      role="dialog"
      aria-modal="true"
      aria-label="Waiting room in 3D"
    >
      <div className="absolute inset-0">
        <canvas
          ref={canvas}
          className="block h-full w-full touch-none"
          style={{ cursor: dragging ? 'grabbing' : state?.hovering ? 'pointer' : 'grab' }}
          onPointerDown={() => setDragging(true)}
          onPointerUp={() => setDragging(false)}
          onPointerLeave={() => setDragging(false)}
        />
      </div>

      <div className="pointer-events-none absolute left-0 top-0 p-[16px] pl-[17px]">
        <div className="pointer-events-auto flex items-center gap-[15px]">
          <IconButton label={sound ? 'Mute sounds' : 'Unmute sounds'} onClick={() => setSound((s) => !s)} className={muted}>
            <SpeakerIcon on={sound} />
          </IconButton>
          <IconButton label={dark ? 'Light theme' : 'Dark theme'} onClick={() => setTheme(dark ? 'light' : 'dark')} className={muted}>
            <SunIcon />
          </IconButton>
          <IconButton label="How to explore" onClick={() => setHelp((h) => !h)} className={muted}>
            <CircleGlyph glyph="?" dark={dark} strong={help} />
          </IconButton>
          <IconButton label="About this room" onClick={() => setInfo((i) => !i)} className={muted}>
            <CircleGlyph glyph="i" dark={dark} strong={info} />
          </IconButton>
        </div>
        {!object && (help || info) && (
          <div className={`mt-[19px] font-hand text-[16.5px] leading-[19px] ${fg}`}>
            {help && (
              <ul>
                {HELP.map((line) => (
                  <li key={line}>- {line}</li>
                ))}
              </ul>
            )}
            {info && (
              <p className={`max-w-[270px] ${help ? 'mt-[14px]' : ''}`}>
                The waiting room this monitor was built for: two boards beside the chairs, a desk, coffee, an exam
                corner and the lab bench.
              </p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        aria-label="Close"
        onClick={close}
        className={`absolute right-[16px] top-[16px] grid h-[22px] w-[22px] place-items-center ${muted}`}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <path d="M1.5 1.5l9 9M10.5 1.5l-9 9" />
        </svg>
      </button>

      {object && state?.piece && (
        <>
          <div className={`pointer-events-none absolute left-0 top-[52px] w-full text-center font-hand text-[18px] min-[761px]:top-[19px] min-[761px]:w-[72%] ${fg}`}>
            {state.piece.name}
          </div>
          {state.thumbs.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-label={t.name}
              title={t.name}
              onClick={() => {
                view.current?.focus(t.id)
                blip()
              }}
              className="absolute rounded-xl"
              style={{ left: t.x, top: t.y, width: t.w, height: t.h }}
            />
          ))}
          <div className="absolute bottom-[19px] left-0 flex w-full justify-center min-[761px]:w-[72%]">
            <div className={`flex items-center rounded-full border p-[4px] shadow-[0_1px_2px_rgba(0,0,0,0.03)] ${pill}`}>
              <PillButton label="Previous" onClick={() => (view.current?.step(-1), blip())} className={muted}>
                <path d="M7.5 2.5L4 6l3.5 3.5" />
              </PillButton>
              <PillButton label="Back to the room" onClick={() => (view.current?.back(), blip())} className={muted}>
                <path d="M3 3l6 6M9 3L3 9" />
              </PillButton>
              <PillButton label="Next" onClick={() => (view.current?.step(1), blip())} className={muted}>
                <path d="M4.5 2.5L8 6 4.5 9.5" />
              </PillButton>
            </div>
          </div>
        </>
      )}

      {!object && (
        <div className="absolute bottom-[21px] left-1/2 -translate-x-1/2">
          <div className={`flex items-center gap-[2px] rounded-full border p-[4px] shadow-[0_1px_2px_rgba(0,0,0,0.03)] ${pill}`}>
            {ZONES.map((name, i) => {
              const on = mode === 'zone' && state?.zone === i
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => {
                    if (on) view.current?.showRoom()
                    else view.current?.showZone(i)
                    blip()
                  }}
                  className={`rounded-full px-[11px] py-[5px] text-[14px] transition-colors ${
                    on ? (dark ? 'bg-neutral-800 font-medium text-white' : 'bg-[#efefef] font-medium text-neutral-900') : muted
                  }`}
                >
                  {name}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}

function IconButton({ label, onClick, className, children }: { label: string; onClick: () => void; className: string; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={`grid h-[20px] w-[20px] place-items-center transition-colors ${className}`}>
      {children}
    </button>
  )
}

function PillButton({ label, onClick, className, children }: { label: string; onClick: () => void; className: string; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={`grid h-[28px] w-[30px] place-items-center rounded-full transition-colors ${className}`}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
    </button>
  )
}

function SpeakerIcon({ on }: { on: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <path d="M2.5 7h2.6L9 3.8v10.4L5.1 11H2.5z" fill="currentColor" />
      {on ? (
        <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <path d="M11.4 6.6a3.4 3.4 0 010 4.8" />
          <path d="M13.3 4.7a6 6 0 010 8.6" />
        </g>
      ) : (
        <path d="M11.5 7l4 4m0-4l-4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      )}
    </svg>
  )
}

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="3.6" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        {Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * Math.PI * 2
          return <path key={i} d={`M${9 + Math.cos(a) * 5.6} ${9 + Math.sin(a) * 5.6}L${9 + Math.cos(a) * 7.3} ${9 + Math.sin(a) * 7.3}`} />
        })}
      </g>
    </svg>
  )
}

function CircleGlyph({ glyph, dark, strong }: { glyph: string; dark: boolean; strong: boolean }) {
  const bg = strong ? (dark ? '#f2f2f2' : '#1f1f22') : dark ? '#8a8a8f' : '#77777c'
  const fg = dark && strong ? '#141416' : '#fff'
  return (
    <svg width="17" height="17" viewBox="0 0 17 17">
      <circle cx="8.5" cy="8.5" r="8.5" fill={bg} />
      <text x="8.5" y="12.4" textAnchor="middle" fontSize="11" fontWeight="700" fontFamily="var(--font-inter), system-ui" fill={fg}>
        {glyph}
      </text>
    </svg>
  )
}
