// Scene tiles: the phone alarm, the recordings window, the nurse view, the breath-hold test.
import { breath, clamp, hash, linePath, mod, smooth, story, storyBreath } from './signal'

/** The phone page (/phone) ringing when a chair stops breathing. */
export function Phone({ t }: { t: number }) {
  const st = story(t)
  const alarm = st.pausing
  const ring = mod(t, 1.1) / 1.1
  const wave: [number, number][] = []
  for (let i = 0; i <= 60; i++) wave.push([30 + i * 2.4, 250 - storyBreath(t - 12 + i * 0.2) * 9])

  return (
    <div className="absolute inset-0 bg-black font-body">
      <div className="absolute left-[147px] top-[35px] h-[432px] w-[208px] rounded-[40px] bg-[#1a1a1c] p-[3px] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.12)]">
        <div className="absolute -left-[2px] top-[96px] h-[22px] w-[3px] rounded-l bg-[#2a2a2d]" />
        <div className="absolute -left-[2px] top-[130px] h-[38px] w-[3px] rounded-l bg-[#2a2a2d]" />
        <div className="absolute -right-[2px] top-[138px] h-[54px] w-[3px] rounded-r bg-[#2a2a2d]" />
        <div className="relative h-full w-full overflow-hidden rounded-[37px] bg-black p-[5px]">
          <div className="relative h-full w-full overflow-hidden rounded-[32px]">
            <div className="absolute inset-0" style={{ background: 'linear-gradient(180deg, #1d2b3c 0%, #0d1520 55%, #06090d 100%)' }} />
            <div
              className="absolute inset-0 transition-opacity duration-500"
              style={{ opacity: alarm ? 1 : 0, background: 'radial-gradient(90% 60% at 50% 48%, #8f1d26 0%, #3b0d12 55%, #12060a 100%)' }}
            />
            <div className="absolute left-0 right-0 top-[10px] flex items-center justify-between px-[22px] text-[9px] font-semibold text-white">
              <span>1:35</span>
              <span className="flex items-center gap-[3px]">
                <svg width="12" height="8" viewBox="0 0 12 8" fill="white">
                  <rect x="0" y="5" width="2" height="3" rx=".5" />
                  <rect x="3.3" y="3.5" width="2" height="4.5" rx=".5" />
                  <rect x="6.6" y="2" width="2" height="6" rx=".5" />
                  <rect x="9.9" y="0" width="2" height="8" rx=".5" opacity=".4" />
                </svg>
                <svg width="16" height="8" viewBox="0 0 16 8" fill="none">
                  <rect x=".5" y=".5" width="13" height="7" rx="2" stroke="white" opacity=".5" />
                  <rect x="2" y="2" width="9" height="4" rx="1" fill="white" />
                </svg>
              </span>
            </div>
            <div className="absolute left-1/2 top-[8px] h-[17px] w-[60px] -translate-x-1/2 rounded-full bg-black" />

            {alarm ? (
              <>
                <div className="absolute left-[10px] right-[10px] top-[46px] rounded-[14px] bg-white/[0.14] p-[8px] backdrop-blur" style={{ transform: `translateY(${(1 - smooth(13, 13.4, st.s)) * -30}px)` }}>
                  <div className="flex items-center gap-[6px]">
                    <span className="grid h-[16px] w-[16px] place-items-center rounded-[4px] bg-[#e5484d]">
                      <svg width="9" height="9" viewBox="0 0 8 8" fill="none" stroke="white" strokeWidth="0.9">
                        <path d="M2 6V3.5a2 2 0 014 0V6l.6.6H1.4zM3.3 7.2h1.4" />
                      </svg>
                    </span>
                    <span className="text-[7px] uppercase tracking-[0.04em] text-white/70">Waiting room</span>
                    <span className="ml-auto text-[7px] text-white/60">now</span>
                  </div>
                  <div className="mt-[5px] text-[8.5px] font-semibold text-white">Chair 1: no breath for {Math.floor(st.pauseS)} s</div>
                  <div className="text-[7.5px] text-white/70">Sitting still, no breathing movement.</div>
                </div>
                <div className="absolute left-1/2 top-[168px] grid h-[92px] w-[92px] -translate-x-1/2 place-items-center">
                  <span className="absolute inset-0 rounded-full border-2 border-[#ff6b70]" style={{ transform: `scale(${1 + ring * 0.45})`, opacity: 1 - ring }} />
                  <span className="absolute inset-[6px] rounded-full bg-[#e5484d]/25" />
                  <span className="relative text-[30px] font-semibold tracking-[-0.03em] text-white tabular-nums">{Math.floor(st.pauseS)}s</span>
                </div>
              </>
            ) : (
              <>
                <div className="absolute left-0 right-0 top-[92px] text-center">
                  <div className="text-[8px] uppercase tracking-[0.12em] text-white/50">Chair 1</div>
                  <div className="mt-[4px] text-[44px] font-semibold tracking-[-0.04em] text-white tabular-nums">{st.rate.toFixed(1)}</div>
                  <div className="text-[8.5px] text-white/60">breaths per minute</div>
                </div>
                <svg viewBox="0 0 202 422" className="absolute inset-0 h-full w-full">
                  <path d={linePath(wave)} fill="none" stroke="#3ddc84" strokeWidth={1.6} strokeLinecap="round" />
                </svg>
              </>
            )}

            <div className="absolute bottom-[26px] left-1/2 flex h-[25px] w-[158px] -translate-x-1/2 items-center justify-center rounded-full bg-white text-[8.5px] font-semibold text-black">
              {alarm ? 'Acknowledge' : 'Watching 4 chairs'}
              <span className="absolute right-[6px] h-[14px] w-[14px] rounded-full border-[1.5px] border-black/10" style={{ borderTopColor: alarm ? '#e5484d' : '#9a9a9e', transform: `rotate(${t * 300}deg)` }} />
            </div>
            <div className="absolute bottom-[7px] left-1/2 h-[3px] w-[64px] -translate-x-1/2 rounded-full bg-white/80" />
          </div>
        </div>
      </div>
    </div>
  )
}

const FILES = ['empty-chair', 'breathing', 'movement', 'hold', 'breathing', 'live']

/** Sessions landing in recordings/ while the status line counts packets. */
export function Recordings({ t }: { t: number }) {
  const cycle = 3.2
  const n = Math.floor(t / cycle)
  const s = mod(t, cycle) / cycle
  const fly = smooth(0.15, 0.7, s)
  const drop = smooth(0.62, 0.78, s)
  const name = FILES[n % FILES.length]
  const pps = 70 + Math.floor(hash(Math.floor(t * 2)) * 4)

  return (
    <div className="absolute inset-0 overflow-hidden font-body">
      <div className="absolute inset-0 bg-[#e9d5dc]" />
      <div className="absolute -inset-[30px] blur-[26px]">
        <div className="absolute left-[-40px] top-[-30px] h-[260px] w-[260px] rounded-full bg-[#ff4f87] opacity-80" />
        <div className="absolute right-[-60px] top-[40px] h-[240px] w-[240px] rounded-full bg-[#ff9a62] opacity-70" />
        <div className="absolute bottom-[-80px] left-[90px] h-[240px] w-[300px] rounded-full bg-[#9db7ff] opacity-70" />
        <div className="absolute left-[200px] top-[100px] h-[140px] w-[160px] rounded-full bg-white opacity-70" />
      </div>
      <div className="absolute left-[37px] top-[37px] h-[304px] w-[428px] overflow-hidden rounded-[10px] bg-[#1c1c1e] shadow-[0_10px_40px_rgba(0,0,0,0.35),inset_0_0_0_1px_rgba(255,255,255,0.08)]">
        <div className="flex items-center gap-[4px] px-[9px] pt-[9px]">
          <span className="h-[6px] w-[6px] rounded-full bg-[#ff5f57]" />
          <span className="h-[6px] w-[6px] rounded-full bg-[#febc2e]" />
          <span className="h-[6px] w-[6px] rounded-full bg-[#28c840]" />
        </div>
        <div className="flex items-center justify-between px-[16px] pt-[12px] text-[7px]">
          <span className="rounded-[4px] bg-white/[0.06] px-[7px] py-[3px] text-[#c8c8cc]">recordings/</span>
          <span className="flex items-center gap-[10px] text-[#8e8e93]">
            Close
            <span className="rounded-full bg-white px-[8px] py-[3px] font-medium text-black">New session</span>
          </span>
        </div>
        <svg viewBox="0 0 428 304" className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id="folder-back" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#3a8cf0" />
              <stop offset="1" stopColor="#2f6fe0" />
            </linearGradient>
            <linearGradient id="folder-front" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#6db0ff" />
              <stop offset="1" stopColor="#3f88f5" />
            </linearGradient>
          </defs>
          <path d="M150 104h38l9 9h81a8 8 0 018 8v76a8 8 0 01-8 8H150a8 8 0 01-8-8v-85a8 8 0 018-8z" fill="url(#folder-back)" />
          <g opacity={1 - drop} transform={`translate(${-120 + fly * 314} ${150 - Math.sin(fly * Math.PI) * 60 + drop * 20}) rotate(${(1 - fly) * -14})`}>
            <rect x="-26" y="-32" width="52" height="64" rx="5" fill="#f4f4f6" />
            <path d="M14 -32v12h12" fill="#d9d9de" />
            <rect x="-16" y="-8" width="32" height="3" rx="1.5" fill="#c9c9ce" />
            <rect x="-16" y="0" width="24" height="3" rx="1.5" fill="#c9c9ce" />
            <text x="0" y="22" fontSize="6" textAnchor="middle" fill="#6d6d72">
              .parquet
            </text>
          </g>
          <path d="M142 128a8 8 0 018-8h128a8 8 0 018 8v69a8 8 0 01-8 8H150a8 8 0 01-8-8z" fill="url(#folder-front)" />
          <path d="M142 128a8 8 0 018-8h128a8 8 0 018 8v2H142z" fill="white" opacity="0.25" />
          <text x="214" y="228" fontSize="8" fill="#e5e5ea" textAnchor="middle" className="font-mono">
            {`20261017-0133${String(10 + (n % 50)).padStart(2, '0')}_${name}.parquet`}
          </text>
          <text x="214" y="241" fontSize="6.5" fill="#6d6d72" textAnchor="middle">
            {12 + n} sessions
          </text>
        </svg>
        <div className="absolute bottom-[12px] left-1/2 flex -translate-x-1/2 items-center gap-[7px] text-[6.5px] text-[#8e8e93]">
          {[`${pps} packets/s`, `${(20 + hash(n) * 4).toFixed(0)}% dropped`, 'RSSI -52 dBm'].map((v) => (
            <span key={v} className="whitespace-nowrap rounded-[4px] bg-white/[0.06] px-[6px] py-[3px] tabular-nums">
              {v}
            </span>
          ))}
          <span className="mx-[2px] h-[10px] w-px bg-white/10" />
          {['#3ddc84', '#f5a524', '#e5484d', '#7fb2ff'].map((c) => (
            <span key={c} className="h-[7px] w-[7px] rounded-full" style={{ background: c }} />
          ))}
        </div>
      </div>
    </div>
  )
}

const CHAIRS: [string, string, string][] = [
  ['Chair 1', 'breathing', '#3ddc84'],
  ['Chair 2', 'empty', '#55555a'],
  ['Chair 3', 'pause', '#e5484d'],
  ['Chair 4', 'measuring', '#8e8e93'],
]

/** A front-desk view that puts the paused chair first. */
export function Dashboard({ t }: { t: number }) {
  const s = mod(t, 12)
  const secs = 11 + Math.floor(Math.min(s, 9))
  const acked = s > 9.6
  return (
    <div className="absolute inset-0 overflow-hidden font-body">
      <div className="absolute inset-0" style={{ background: 'linear-gradient(180deg, #f1f1f2 0%, #e4e6e9 60%, #d9dce0 100%)' }} />
      <div className="absolute -inset-[20px] blur-[18px]">
        <div className="absolute left-[-30px] top-[60px] h-[160px] w-[200px] rounded-full bg-white/80" />
        <div className="absolute right-[-20px] top-[-40px] h-[180px] w-[220px] rounded-full bg-[#c9ced6]" />
      </div>
      <div className="absolute left-[24px] right-[24px] top-[34px] h-[320px] rounded-t-[7px] bg-[#0f1012] shadow-[0_8px_30px_rgba(0,0,0,0.25)]">
        <div className="flex items-center justify-center gap-[3px] pt-[8px] text-[5.5px] text-[#6d6d72]">
          <span className="h-[2px] w-[10px] rounded bg-[#c8c8cc]" />
          <span className="h-[2px] w-[5px] rounded bg-[#3a3a3e]" />
          <span className="h-[2px] w-[5px] rounded bg-[#3a3a3e]" />
          <span className="ml-[4px]">1 chair needs a look · 4 watched</span>
        </div>
        <div className="absolute left-[12px] top-[30px] w-[88px] text-[6px]">
          <div className="mb-[5px] text-[5.5px] uppercase tracking-[0.08em] text-[#55555a]">Chairs</div>
          {CHAIRS.map(([name, status, c]) => (
            <div key={name} className={`mb-[3px] flex items-start gap-[5px] rounded-[4px] px-[4px] py-[3px] ${status === 'pause' ? 'bg-white/[0.06]' : ''}`}>
              <span className="mt-[2px] h-[4px] w-[4px] rounded-full" style={{ background: c }} />
              <span>
                <span className="block text-[#e5e5ea]">{name}</span>
                <span className="block text-[5.2px] text-[#6d6d72]">{status}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="absolute right-[12px] top-[30px] w-[86px] text-[5.6px]">
          <div className="mb-[5px] text-[5.5px] uppercase tracking-[0.08em] text-[#55555a]">Recent</div>
          {[
            ['Chair 3 paused', 'phone rang'],
            ['Chair 1 moved', 'measuring again'],
          ].map(([a, b]) => (
            <div key={a} className="mb-[3px] flex items-start justify-between rounded-[4px] bg-white/[0.04] px-[4px] py-[3px]">
              <span>
                <span className="block text-[#c8c8cc]">{a}</span>
                <span className="block text-[5px] text-[#55555a]">{b}</span>
              </span>
              <span className="text-[#3ddc84]">Seen</span>
            </div>
          ))}
        </div>
        <div className="absolute left-[126px] top-[104px] w-[202px] rounded-[6px] bg-[#1a1b1e] p-[8px] shadow-[inset_0_0_0_0.5px_rgba(255,255,255,0.1)]">
          <div className="flex items-center justify-between text-[5.5px]">
            <span className={`flex items-center gap-[3px] rounded-[3px] px-[4px] py-[1.5px] ${acked ? 'bg-[#0b2a17] text-[#7ee2a4]' : 'bg-[#3b0d12] text-[#ffb3b6]'}`}>
              <span className={`h-[3px] w-[3px] rounded-full ${acked ? 'bg-[#3ddc84]' : 'bg-[#e5484d]'}`} />
              {acked ? 'Acknowledged' : 'Critical'}
            </span>
            <span className="text-[#55555a]">Chair 3 · now</span>
          </div>
          <div className="mt-[6px] text-[8.5px] font-semibold leading-[11px] text-white">Chair 3 has not breathed for {secs} s</div>
          <div className="mt-[3px] text-[5.6px] leading-[7.5px] text-[#8e8e93]">
            No breathing movement while sitting still. The phone rang at 11 s and keeps ringing until someone answers.
          </div>
          <div className="mt-[7px] grid grid-cols-3 gap-[4px] border-t border-white/[0.06] pt-[6px] text-[5.4px]">
            {[
              ['Rate', '0 /min', '#e5e5ea'],
              ['Last breath', `${secs} s ago`, '#ff9ea2'],
              ['Level', 'critical', '#e5e5ea'],
            ].map(([k, v, c]) => (
              <span key={k}>
                <span className="block text-[#55555a]">{k}</span>
                <span className="block font-medium tabular-nums" style={{ color: c }}>
                  {v}
                </span>
              </span>
            ))}
          </div>
          <div className="mt-[7px] flex items-center justify-end gap-[6px] text-[5.6px]">
            <span className="text-[#8e8e93]">Call the nurse</span>
            <span className="rounded-[3px] bg-white px-[6px] py-[2px] font-medium text-black">{acked ? 'Done' : 'Acknowledge'}</span>
          </div>
        </div>
        <div className="absolute left-[126px] top-[232px] flex w-[202px] justify-center gap-[9px] text-[5px] text-[#55555a]">
          {['Breathing', 'Movement', 'Pause', 'Empty'].map((v, i) => (
            <span key={v} className="flex items-center gap-[2.5px]">
              <span className="h-[3px] w-[3px] rounded-full" style={{ background: ['#3ddc84', '#7fb2ff', '#e5484d', '#55555a'][i] }} />
              {v}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

const HOLDS: [number, number][] = [
  [60.3, 80.3],
  [110.0, 130.4],
]

/** The shared breath-hold recording, with the marked holds and when the alarm fired. */
export function HoldTest({ t }: { t: number }) {
  const total = 150
  const head = mod(t * 10, total + 15)
  const at = Math.min(head, total)
  const x0 = 58
  const x1 = 446
  const X = (sec: number) => x0 + (sec / total) * (x1 - x0)
  const held = (sec: number) => HOLDS.some(([a, b]) => sec > a && sec < b)
  const pts: [number, number][] = []
  for (let i = 0; i <= 300; i++) {
    const sec = (i / 300) * total
    const amp = held(sec) ? 0.04 : 1
    pts.push([X(sec), 205 - (breath(sec) * amp + 0.06 * (hash(i) - 0.5)) * 36])
  }
  const alarms = HOLDS.map(([a, b]) => [a + 11, b + 5] as [number, number])
  const pausing = alarms.some(([a, b]) => at > a && at < b)

  return (
    <div className="absolute inset-0 bg-[#f6f6f6] font-body">
      <div className="absolute left-[31px] top-[38px] h-[332px] w-[440px] rounded-[10px] border border-black/[0.04] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
        <div className="flex items-start justify-between px-[16px] pt-[14px]">
          <div>
            <div className="text-[9.5px] font-semibold text-[#1f1f22]">Breath-hold test</div>
            <div className="mt-[2px] font-mono text-[6.5px] text-[#9a9a9e]">recordings/20261017-013311_hold.parquet</div>
          </div>
          <span
            className={`rounded-full px-[7px] py-[2.5px] text-[6.5px] font-bold tracking-[0.06em] ${
              pausing ? 'bg-[#fde8e8] text-[#c9252c]' : 'bg-[#e6f6ec] text-[#1d7a43]'
            }`}
          >
            {pausing ? 'PAUSE' : 'BREATHING'}
          </span>
        </div>
      </div>
      <svg viewBox="0 0 502 408" className="absolute inset-0 h-full w-full">
        {[0, 30, 60, 90, 120, 150].map((v) => (
          <g key={v}>
            <line x1={X(v)} x2={X(v)} y1={128} y2={282} stroke="#f0f0f0" />
            <text x={X(v)} y={296} fontSize={6.5} fill="#9a9a9e" textAnchor="middle">
              {v}s
            </text>
          </g>
        ))}
        {HOLDS.map(([a, b], i) => (
          <g key={a}>
            <rect x={X(a)} y={128} width={X(b) - X(a)} height={154} fill="#e5484d" opacity={0.07} />
            <text x={X(a) + 3} y={137} fontSize={6} fill="#c9252c">
              hold {i + 1}
            </text>
            <text x={X(a) + 3} y={145} fontSize={5.5} fill="#d97a7e">
              {a.toFixed(1)} to {b.toFixed(1)} s
            </text>
          </g>
        ))}
        <path d={linePath(pts.filter((p) => p[0] <= X(at)))} fill="none" stroke="#1f1f22" strokeWidth={1.2} strokeLinejoin="round" />
        <path d={linePath(pts.filter((p) => p[0] >= X(at) - 1))} fill="none" stroke="#d9d9dc" strokeWidth={1.2} strokeLinejoin="round" />
        <text x={x0} y={318} fontSize={6.5} fill="#9a9a9e">
          alarm
        </text>
        <line x1={x0 + 26} x2={x1} y1={315.5} y2={315.5} stroke="#f0f0f0" strokeWidth={5} strokeLinecap="round" />
        {alarms.map(([a, b]) => (
          <line key={a} x1={X(a)} x2={X(Math.min(b, Math.max(a, at)))} y1={315.5} y2={315.5} stroke="#e5484d" strokeWidth={5} strokeLinecap="round" opacity={at > a ? 1 : 0} />
        ))}
        <text x={x0} y={340} fontSize={6} fill="#b4b4b8">
          The alarm starts about 11 s into a hold and clears about 5 s after breathing returns.
        </text>
        <line x1={X(at)} x2={X(at)} y1={124} y2={322} stroke="#1f1f22" strokeWidth={0.8} opacity={clamp((total + 10 - head) / 4)} />
      </svg>
    </div>
  )
}
