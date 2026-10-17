// Light "UI" tiles: control panels, board placement, replay controls.
import { breath, clamp, linePath, mod, smooth } from './signal'

function Panel({ x, y, w, title, icon, children }: { x: number; y: number; w: number; title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div
      className="absolute rounded-[9px] border border-black/[0.04] bg-white px-[9px] pb-[9px] pt-[8px] shadow-[0_1px_3px_rgba(0,0,0,0.05)]"
      style={{ left: x, top: y, width: w }}
    >
      <div className="flex items-center gap-[4px] text-[8px] font-semibold text-[#1f1f22]">
        <span className="grid h-[9px] w-[9px] place-items-center">{icon}</span>
        {title}
        <span className="ml-auto grid h-[11px] w-[11px] place-items-center rounded-full bg-[#f1f1f1] text-[#8b8b8b]">
          <svg width="5" height="5" viewBox="0 0 5 5" stroke="currentColor" strokeWidth="0.8">
            <path d="M.5.5l4 4M4.5.5l-4 4" />
          </svg>
        </span>
      </div>
      <div className="mt-[8px] flex flex-col gap-[7px]">{children}</div>
    </div>
  )
}

const Label = ({ children, value }: { children: React.ReactNode; value?: React.ReactNode }) => (
  <div className="flex items-center justify-between text-[6.8px] text-[#707074]">
    <span>{children}</span>
    {value != null && <span className="font-medium tabular-nums text-[#1f1f22]">{value}</span>}
  </div>
)

function Slider({ value }: { value: number }) {
  return (
    <div className="relative mt-[-2px] h-[8px]">
      <div className="absolute left-0 right-0 top-[3.5px] h-[1px] rounded bg-[#e7e7e7]" />
      <div className="absolute left-0 top-[3px] h-[2px] rounded bg-[#2a2a2c]" style={{ width: `${value * 100}%` }} />
      <div className="absolute top-[1px] h-[6px] w-[9px] -translate-x-1/2 rounded-[3px] bg-[#3a3a3c]" style={{ left: `${value * 100}%` }} />
    </div>
  )
}

function Segmented({ items, active }: { items: React.ReactNode[]; active: number }) {
  return (
    <div className="flex rounded-[7px] bg-[#f3f3f3] p-[2px]">
      {items.map((item, i) => (
        <div
          key={i}
          className={`flex h-[14px] flex-1 items-center justify-center rounded-[5px] text-[6.3px] ${
            i === active ? 'bg-white font-medium text-[#1f1f22] shadow-[0_0.5px_1.5px_rgba(0,0,0,0.12)]' : 'text-[#9a9a9e]'
          }`}
        >
          {item}
        </div>
      ))}
    </div>
  )
}

function Toggle({ on }: { on: number }) {
  return (
    <div className="relative h-[11px] w-[19px] rounded-full" style={{ background: on > 0.5 ? '#2a2a2c' : '#dcdcdc' }}>
      <div className="absolute top-[1.5px] h-[8px] w-[8px] rounded-full bg-white shadow" style={{ left: 1.5 + on * 8 }} />
    </div>
  )
}

const Dark = ({ children, w = '100%', pressed = 0, red = false }: { children: React.ReactNode; w?: number | string; pressed?: number; red?: boolean }) => (
  <div
    className={`flex h-[17px] items-center justify-center gap-[4px] rounded-full text-[7px] font-medium text-white ${red ? 'bg-[#e5484d]' : 'bg-[#232325]'}`}
    style={{ width: w, transform: `scale(${1 - pressed * 0.05})` }}
  >
    {children}
  </div>
)

const Light = ({ children, flex = 1 }: { children: React.ReactNode; flex?: number }) => (
  <div className="flex h-[17px] items-center justify-center gap-[3px] rounded-full bg-[#f1f1f1] text-[7px] font-medium text-[#3a3a3c]" style={{ flex }}>
    {children}
  </div>
)

const Note = ({ children }: { children: React.ReactNode }) => <p className="text-center text-[5.6px] leading-[7.5px] text-[#a0a0a4]">{children}</p>

const DOTS = ['#22c55e', '#14b8a6', '#0ea5e9', '#8b5cf6', '#d97706', '#ec4899', '#ef4444', '#f97316', '#eab308']

/** Panels for recording a session, marking moments, and the phone alarm. */
export function RecordPanels({ t }: { t: number }) {
  const s = mod(t, 10)
  const seconds = Math.round(60 + 10 * smooth(0.4, 1.6, s))
  const recording = s > 2.2 && s < 8.2
  const pressed = Math.max(0, 1 - Math.abs(s - 2.15) * 8)
  const elapsed = recording ? Math.floor(s - 2.2) : 0
  const mark = s > 5.2 && s < 9.6
  const toggle = smooth(3.2, 3.5, mod(t, 14)) - smooth(10.2, 10.5, mod(t, 14))

  return (
    <div className="absolute inset-0 font-body">
      <Panel
        x={98}
        y={42}
        w={152}
        title="Record session"
        icon={
          <svg width="8" height="8" viewBox="0 0 8 8" fill="#1f1f22">
            <rect x="0.5" y="1" width="1.6" height="6" rx="0.4" />
            <rect x="3.2" y="1" width="1.6" height="6" rx="0.4" />
            <rect x="5.9" y="1" width="1.6" height="6" rx="0.4" />
          </svg>
        }
      >
        <div>
          <Label value={seconds}>Seconds</Label>
          <Slider value={(seconds - 10) / 110} />
        </div>
        <div>
          <Label value={5}>Countdown</Label>
          <Slider value={0.28} />
        </div>
        <div className="flex flex-col gap-[4px]">
          <Label>Label</Label>
          <Segmented items={['breathing', 'hold', 'movement']} active={0} />
        </div>
        <div className="flex flex-col gap-[4px]">
          <Label>Source</Label>
          <Segmented
            items={[
              <span key="b" className="h-[5px] w-[9px] rounded-[1.5px] border border-current" />,
              <span key="r">replay</span>,
              <span key="f">fake</span>,
            ]}
            active={0}
          />
        </div>
        <div className="flex flex-col gap-[4px]">
          <Label>Raw log</Label>
          <Segmented
            items={[
              <span key="1" className="tracking-[-0.5px]">off</span>,
              <span key="2">lines</span>,
              <span key="3">jsonl</span>,
            ]}
            active={2}
          />
        </div>
        <div className="mt-[2px] flex gap-[4px]">
          <div className="flex-[1.15]">
            <Dark pressed={pressed} red={recording}>
              <span className={`h-[5px] w-[5px] ${recording ? 'rounded-[1px] bg-white' : 'rounded-full bg-[#ff5a5f]'}`} />
              {recording ? `Stop  0:0${elapsed}` : 'Record'}
            </Dark>
          </div>
          <Light>
            <svg width="7" height="7" viewBox="0 0 7 7" fill="none" stroke="currentColor" strokeWidth="0.8">
              <path d="M1 3.5a2.5 2.5 0 104.3-1.7M5.5 0.6v1.4H4.1" />
            </svg>
            Replay
          </Light>
        </div>
        <Note>
          Rows are written every 10 s.
          <br />A crash keeps what was recorded.
        </Note>
      </Panel>

      <Panel
        x={264}
        y={42}
        w={142}
        title="Mark moment"
        icon={
          <svg width="8" height="8" viewBox="0 0 8 8" fill="#1f1f22">
            <path d="M1.5 0.5v7M1.5 1h5l-1.2 1.6L6.5 4.2h-5" />
          </svg>
        }
      >
        <div className="flex flex-col gap-[4px]">
          <Label>Name</Label>
          <div className="flex h-[15px] items-center rounded-[6px] bg-[#f5f5f5] px-[6px] text-[6.5px] text-[#b4b4b8]">hold 2</div>
        </div>
        <div className="flex flex-col gap-[4px]">
          <Label>Color</Label>
          <div className="flex justify-between">
            {DOTS.map((c, i) => (
              <span
                key={c}
                className="h-[10px] w-[10px] rounded-full"
                style={{ background: c, boxShadow: i === 1 ? `0 0 0 1px white, 0 0 0 1.8px ${c}` : undefined }}
              />
            ))}
          </div>
        </div>
        <div className="flex h-[15px] items-center gap-[4px] rounded-[6px] bg-[#f5f5f5] px-[6px] text-[6.5px] font-medium text-[#2a2a2c]">
          <span className="h-[5px] w-[5px] rounded-full bg-[#14b8a6]" />
          hold 1
          <span className="ml-auto font-normal tabular-nums text-[#9a9a9e]">60.3 s</span>
        </div>
        {mark && (
          <div className="-mt-[3px] flex h-[15px] items-center gap-[4px] rounded-[6px] bg-[#f5f5f5] px-[6px] text-[6.5px] font-medium text-[#2a2a2c]" style={{ opacity: smooth(5.2, 5.5, s) }}>
            <span className="h-[5px] w-[5px] rounded-full bg-[#0ea5e9]" />
            hold 1 end
            <span className="ml-auto font-normal tabular-nums text-[#9a9a9e]">80.3 s</span>
          </div>
        )}
        <Dark>
          <svg width="7" height="7" viewBox="0 0 8 8" fill="white">
            <path d="M1.5 0.5v7M1.5 1h5l-1.2 1.6L6.5 4.2h-5" />
          </svg>
          Mark now
        </Dark>
        <Note>
          Press Enter while it runs
          <br />
          to mark the start and end of a hold.
        </Note>
      </Panel>

      <Panel
        x={264}
        y={mark ? 238 : 219}
        w={142}
        title="Phone alarm"
        icon={
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#1f1f22" strokeWidth="0.9">
            <path d="M2 6V3.5a2 2 0 014 0V6l.6.6H1.4zM3.3 7.2h1.4" />
          </svg>
        }
      >
        <div className="flex items-center justify-between text-[6.8px] text-[#707074]">
          Ring on pause
          <Toggle on={1 - clamp(toggle)} />
        </div>
        <div className="flex items-center justify-between text-[6.8px] text-[#707074]">
          Alert after
          <div className="flex gap-[2px] text-[6px]">
            {['5 s', '11 s', '20 s'].map((v) => (
              <span key={v} className={`rounded-[4px] px-[4px] py-[2px] ${v === '11 s' ? 'bg-[#f1f1f1] font-medium text-[#1f1f22]' : 'text-[#a0a0a4]'}`}>
                {v}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between text-[6.8px] text-[#707074]">
          Sound
          <div className="flex gap-[5px]">
            <span className="h-[10px] w-[10px] rounded-full border border-[#2a2a2c] bg-white" />
            <span className="h-[10px] w-[10px] rounded-full bg-[#1f1f22]" />
          </div>
        </div>
        <Dark>Test alarm</Dark>
        <div className="-mt-[3px] flex gap-[4px]">
          <Light flex={2}>Open /phone</Light>
          <Light>Copy</Light>
        </div>
      </Panel>
    </div>
  )
}

function Tape({ x, y, len, vertical = false }: { x: number; y: number; len: number; vertical?: boolean }) {
  const ticks: React.ReactNode[] = []
  for (let i = 2; i < len - 1; i += 2.5) {
    const big = Math.round(i / 2.5) % 4 === 0
    ticks.push(
      vertical ? (
        <line key={i} x1={x - 2.5} x2={x - 2.5 + (big ? 3 : 1.6)} y1={y + i} y2={y + i} />
      ) : (
        <line key={i} x1={x + i} x2={x + i} y1={y - 2.5} y2={y - 2.5 + (big ? 3 : 1.6)} />
      ),
    )
  }
  return (
    <g>
      {vertical ? <rect x={x - 2.5} y={y} width={5} height={len} fill="#f2d80c" /> : <rect x={x} y={y - 2.5} width={len} height={5} fill="#f2d80c" />}
      <g stroke="#6b5d00" strokeWidth={0.45} opacity={0.75}>
        {ticks}
      </g>
    </g>
  )
}

function Pill({ x, y, text, dark = false }: { x: number; y: number; text: string; dark?: boolean }) {
  const w = 8 + text.length * 5.2
  return (
    <g>
      <rect x={x - w / 2} y={y - 6} width={w} height={12} rx={6} fill={dark ? '#18181a' : '#2fb85a'} />
      <text x={x} y={y + 2.6} textAnchor="middle" fontSize={7.2} fontWeight={600} fill="white" className="tabular-nums">
        {text}
      </text>
    </g>
  )
}

/** Board placement around the chair, with measuring tapes like a design tool. */
export function Placement({ t }: { t: number }) {
  const shift = Math.sin(t * 0.55) * 22 + Math.sin(t * 1.3) * 3
  const chair = { x: 179 + shift, y: 155, w: 146, h: 107 }
  const tx = { x: -8, y: 98, w: 103, h: 124 }
  const rx = { x: 408, y: 98, w: 104, h: 124 }
  const tapeY = 208
  const left = chair.x - (tx.x + tx.w)
  const right = rx.x - (chair.x + chair.w)
  const cm = (px: number) => String(Math.round(px * 0.72))
  const cx = chair.x + chair.w / 2

  return (
    <svg viewBox="0 0 502 304" className="absolute inset-0 h-full w-full font-body">
      <rect width="502" height="304" fill="#f3f2ef" />
      <rect x={tx.x} y={tx.y} width={tx.w} height={tx.h} fill="#e64a21" />
      <rect x={rx.x} y={rx.y} width={rx.w} height={rx.h} fill="#2dcff5" />
      <text x={rx.x + 3} y={rx.y - 6} fontSize={7.5} fill="#8a8a8a">
        RX board
      </text>
      <text x={tx.x + 12} y={tx.y - 6} fontSize={7.5} fill="#8a8a8a">
        TX board
      </text>
      <Tape x={cx} y={0} len={chair.y} vertical />
      <Tape x={cx} y={chair.y + chair.h} len={304 - chair.y - chair.h} vertical />
      <Tape x={tx.x + tx.w + 2} y={tapeY} len={left - 2} />
      <Tape x={chair.x + chair.w} y={tapeY} len={right - 2} />
      <line x1={tx.x + tx.w + 1.5} x2={tx.x + tx.w + 1.5} y1={tapeY - 4} y2={tapeY + 4} stroke="#7a7a7a" strokeWidth={1} />
      <line x1={rx.x - 1.5} x2={rx.x - 1.5} y1={tapeY - 4} y2={tapeY + 4} stroke="#7a7a7a" strokeWidth={1} />
      <rect x={chair.x} y={chair.y} width={chair.w} height={chair.h} fill="#a54ef5" />
      <rect x={chair.x} y={chair.y - 15} width={37} height={11} fill="#a54ef5" />
      <text x={chair.x + 3.5} y={chair.y - 7} fontSize={7} fill="white">
        Chair 1
      </text>
      <Pill x={tx.x + tx.w + left / 2} y={tapeY} text={cm(left)} />
      <Pill x={chair.x + chair.w + right / 2} y={tapeY} text={cm(right)} />
      <Pill x={cx} y={72} text="75" dark />
      <g transform={`translate(${cx - 12} ${chair.y + 44})`}>
        <path d="M0 0l0 10.5 2.6-2.4 1.8 4 1.5-.7-1.8-3.9 3.6-.2z" fill="#1f1f22" stroke="white" strokeWidth={0.7} strokeLinejoin="round" />
      </g>
    </svg>
  )
}

/** Replaying a recording: timeline with the two breath holds and the speed controls. */
export function Replay({ t }: { t: number }) {
  const total = 150
  const pos = mod(t * 6, total)
  const pts: [number, number][] = []
  const x0 = 34
  const x1 = 468
  for (let i = 0; i <= 220; i++) {
    const sec = (i / 220) * total
    const held = (sec > 60.3 && sec < 80.3) || (sec > 110 && sec < 130.4)
    const v = held ? 0.05 * Math.sin(sec * 3) : breath(sec)
    pts.push([x0 + (i / 220) * (x1 - x0), 92 - v * 17])
  }
  const px = x0 + (pos / total) * (x1 - x0)
  const speed = Math.floor(mod(t / 4, 3))
  const fmt = (v: number) => `${Math.floor(v / 60)}:${String(Math.floor(v % 60)).padStart(2, '0')}.${Math.floor((v % 1) * 10)}`
  const loop = smooth(0.2, 0.45, mod(t, 9)) - smooth(5.2, 5.45, mod(t, 9))

  return (
    <div className="absolute inset-0 bg-black font-body">
      <svg viewBox="0 0 502 250" className="absolute inset-0 h-full w-full">
        <text x={x0} y={34} fontSize={8} fill="#6d6d72" className="font-mono">
          20261017-013311_hold.parquet
        </text>
        <text x={x1} y={34} fontSize={8} fill="#c8c8cc" textAnchor="end" className="font-mono tabular-nums">
          {fmt(pos)} <tspan fill="#5b5b60">/ 2:30.0</tspan>
        </text>
        {[
          [60.3, 80.3],
          [110, 130.4],
        ].map(([a, b]) => (
          <g key={a}>
            <rect x={x0 + (a / total) * (x1 - x0)} y={56} width={((b - a) / total) * (x1 - x0)} height={72} fill="#e5484d" opacity={0.13} rx={3} />
            <text x={x0 + (a / total) * (x1 - x0) + 4} y={66} fontSize={6.5} fill="#ff8a8d">
              hold
            </text>
          </g>
        ))}
        <path d={linePath(pts.filter((p) => p[0] <= px))} fill="none" stroke="#e8e8ea" strokeWidth={1.3} />
        <path d={linePath(pts.filter((p) => p[0] >= px - 2))} fill="none" stroke="#3a3a3e" strokeWidth={1.3} />
        <line x1={px} x2={px} y1={50} y2={136} stroke="white" strokeWidth={1} />
        <circle cx={px} cy={50} r={2.5} fill="white" />
        <line x1={x0} x2={x1} y1={146} y2={146} stroke="#222225" />
        {[0, 30, 60, 90, 120, 150].map((v) => (
          <text key={v} x={x0 + (v / total) * (x1 - x0)} y={158} fontSize={6.5} fill="#55555a" textAnchor="middle" className="font-mono">
            {v}s
          </text>
        ))}
      </svg>
      <div className="absolute bottom-[29px] left-1/2 flex -translate-x-1/2 items-center gap-[10px] rounded-[9px] border border-white/[0.06] bg-[#151517] px-[10px] py-[6px] text-[7.5px] text-[#d7d7db]">
        <span className="flex items-center gap-[6px]">
          Loop
          <span className="relative h-[11px] w-[19px] rounded-full" style={{ background: loop > 0.5 ? '#e8e8ea' : '#3a3a3e' }}>
            <span className="absolute top-[1.5px] h-[8px] w-[8px] rounded-full" style={{ left: 1.5 + loop * 8, background: loop > 0.5 ? '#111' : '#bbb' }} />
          </span>
        </span>
        <span className="h-[12px] w-px bg-white/10" />
        <span className="flex rounded-[6px] bg-[#232326] p-[2px]">
          {['1x', '2x', '4x'].map((v, i) => (
            <span key={v} className={`rounded-[4px] px-[7px] py-[2px] tabular-nums ${i === speed ? 'bg-[#3a3a3e] text-white' : 'text-[#77777c]'}`}>
              {v}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

