'use client'

import Wave, { LAG_S } from './wave'
import { useStream, type Level, type StreamFrame } from './use-stream'

const WARMUP_CALM_S = 30 // backend/live.py: MEASURING until this much calm data

type Tone = 'green' | 'red' | 'amber' | 'blue' | 'grey'

const PILL: Record<Tone, string> = {
  green: 'bg-green-950 text-green-300 ring-1 ring-green-800',
  red: 'bg-red-950 text-red-200 ring-1 ring-red-700',
  amber: 'bg-amber-950 text-amber-200 ring-1 ring-amber-700',
  blue: 'bg-sky-950 text-sky-200 ring-1 ring-sky-800',
  grey: 'bg-slate-800 text-slate-300 ring-1 ring-slate-700',
}

const LEVEL_TONE: Record<Level, Tone> = { normal: 'green', warning: 'amber', critical: 'red' }

type View = { label: string; tone: Tone; big: string; unit: string; note: string }

const NO_SIGNAL: Record<string, Omit<View, 'big' | 'unit'>> = {
  warming_up: { label: 'STARTING', tone: 'grey', note: 'Collecting data from the sensor' },
  unreliable_rhythm: { label: 'NO STEADY RHYTHM', tone: 'grey', note: 'Breathing is not clear yet' },
  waiting_for_packets: { label: 'WAITING FOR SENSOR', tone: 'grey', note: 'No data yet. Is the TX board powered?' },
  stale_input: { label: 'SENSOR DATA STOPPED', tone: 'amber', note: 'Check that both boards are powered' },
  disconnected: { label: 'SENSOR DISCONNECTED', tone: 'amber', note: 'Reconnect the RX board, then restart the server' },
  simulated_signal_loss: { label: 'NO SIGNAL', tone: 'grey', note: 'Simulated signal loss' },
}

function describe(frame: StreamFrame | null, connected: boolean, url: string): View {
  if (!connected) {
    return { label: 'OFFLINE', tone: 'grey', big: '--', unit: '', note: `Connecting to the server at ${url}...` }
  }
  if (!frame) return { label: 'CONNECTING', tone: 'grey', big: '--', unit: '', note: '' }
  if (frame.reason === 'panting') {
    return { label: 'PANTING', tone: 'red', big: frame.rate_bpm?.toFixed(0) ?? '--', unit: 'breaths/min',
      note: 'Rapid, shallow breathing detected' }
  }
  if (frame.source !== 'fake' && frame.ml_model_version) {
    if (frame.ml_label === 'checking') {
      return { label: 'CHECKING BREATHING', tone: 'amber', big: 'CHECK', unit: '',
        note: 'Reduced breathing movement; checking the next updates' }
    }
    if (frame.ml_label === 'breath_hold') {
      return { label: 'POSSIBLE BREATH HOLD', tone: 'red', big: 'HOLD', unit: '',
        note: 'Live model detects reduced breathing movement' }
    }
    if (frame.ml_label === 'breathing') {
      return { label: 'BREATHING', tone: 'green', big: frame.rate_bpm?.toFixed(1) ?? 'LIVE',
        unit: frame.rate_bpm != null ? 'breaths/min' : 'Breathing detected', note: '' }
    }
    return { label: 'MEASURING', tone: 'grey', big: '--', unit: '', note: 'Collecting a usable sensor window' }
  }
  switch (frame.status) {
    case 'breathing':
      return { label: 'BREATHING', tone: 'green', big: frame.rate_bpm?.toFixed(1) ?? '--', unit: 'breaths/min', note: '' }
    case 'pause':
      return {
        label: 'PAUSE', tone: 'red', big: `${Math.round(frame.pause_s ?? 0)} s`, unit: 'without a breath',
        note: 'No breathing movement detected while sitting still',
      }
    case 'motion':
      return { label: 'MOVEMENT', tone: 'blue', big: '--', unit: '', note: 'Measuring resumes when they sit still' }
  }
  if (frame.reason === 'measuring') {
    const calm = Math.min(WARMUP_CALM_S, Math.round(frame.calm_s ?? 0))
    return { label: 'MEASURING', tone: 'grey', big: '--', unit: '', note: `Calm data ${calm} of ${WARMUP_CALM_S} s` }
  }
  const known = NO_SIGNAL[frame.reason ?? '']
  return { big: '--', unit: '', ...(known ?? { label: 'PROCESSING', tone: 'grey', note: frame.reason ?? '' }) }
}

function SourceBadge({ frame, connected }: { frame: StreamFrame | null; connected: boolean }) {
  if (!connected || !frame) return <span className="text-slate-500">not connected</span>
  if (frame.source === 'serial') {
    return (
      <span className="text-slate-300">
        <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-green-500" />
        LIVE sensor
      </span>
    )
  }
  return <span className="text-amber-300">{frame.source === 'replay' ? 'REPLAY of a recording' : 'SIMULATED data'}</span>
}

export default function ChairMonitor() {
  const { frame, receivedAt, connected, wave, url } = useStream()
  const view = describe(frame, connected, url)
  const modelPrimary = frame?.source !== 'fake' && !!frame?.ml_model_version
  const alarm = connected && (frame?.reason === 'panting' || (modelPrimary ? frame?.ml_label === 'breath_hold'
    : frame?.status === 'pause' || frame?.level === 'critical'))
  const pauseStart = !modelPrimary && frame?.status === 'pause' && frame.pause_s !== null ? receivedAt - frame.pause_s : null
  const delay = frame?.waveform_delay_s ?? 3

  return (
    <main
      className={`flex min-h-screen items-center justify-center p-4 transition-colors duration-500 sm:p-8 ${
        alarm ? 'bg-[#1a0b10]' : 'bg-[#0b1220]'
      }`}
    >
      <section
        className={`w-full max-w-4xl rounded-2xl p-6 transition-shadow sm:p-8 ${
          alarm ? 'ring-4 ring-red-500' : 'ring-1 ring-slate-800'
        }`}
      >
        <header className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <div>
            <span className="text-2xl font-bold text-slate-100">{frame?.chair ?? 'Chair 1'}</span>
            <span className="text-slate-400"> &middot; waiting room</span>
          </div>
          <SourceBadge frame={frame} connected={connected} />
        </header>

        <div className="mt-6 flex items-center gap-3">
          <span className={`rounded-full px-4 py-1.5 text-sm font-bold tracking-wide ${PILL[view.tone]}`}>
            {view.label}
          </span>
          {connected && !modelPrimary && frame?.level && (
            <span className={`ml-auto rounded-lg px-3 py-1.5 text-sm font-bold ${PILL[LEVEL_TONE[frame.level]]}`}>
              {frame.level.toUpperCase()}
            </span>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-baseline gap-x-4">
          <span className={`text-7xl font-bold tabular-nums sm:text-8xl ${alarm ? 'text-red-300' : 'text-slate-100'}`}>
            {view.big}
          </span>
          <span className="text-xl text-slate-400">{view.unit}</span>
        </div>
        <p className="mt-2 h-6 text-slate-400">{view.note}</p>

        {frame?.source !== 'fake' && (
          <div className="mt-3 text-sm text-slate-400" aria-live="polite" title={frame?.ml_model_version ?? undefined}>
            <span className="text-amber-300">Prototype model</span>
            {' · '}{!connected || !frame?.ml_label || frame.ml_label === 'no_signal' ? 'Unavailable'
              : frame.ml_label === 'motion' ? 'Movement'
              : frame.ml_label === 'checking' ? 'Checking for a hold'
              : frame.ml_label === 'breath_hold' ? 'Possible breath hold' : 'Breathing'}
            {connected && (frame?.ml_label === 'breathing' || frame?.ml_label === 'breath_hold')
              && frame.ml_hold_score != null && (
                <span> · Hold score {frame.ml_hold_score.toFixed(2)} (uncalibrated)</span>
              )}
            <p className="mt-1 text-xs">Seated-person demo; seat presence is not detected. Independent validation pending.</p>
          </div>
        )}

        <div className="mt-4">
          <p className="mb-2 text-xs text-slate-500">Filtered waveform · about {Math.round(delay + LAG_S)} s behind live</p>
          <Wave wave={wave} delay={delay} pauseStart={pauseStart} color="#22c55e" pauseColor="#f87171" />
          <div className="mt-1 flex justify-between text-xs text-slate-500">
            <span>{Math.round(30 + delay + LAG_S)} s ago</span>
            <span>{Math.round(delay + LAG_S)} s ago</span>
          </div>
        </div>

        <footer className="mt-6 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
          <span>
            {connected && frame?.rssi != null
              ? `Signal ${frame.rssi > -70 ? 'good' : 'weak'} · RSSI ${frame.rssi} dBm · ${Math.round(frame.packets_per_s ?? 0)} packets/s`
              : ' '}
          </span>
          <span>Screening signal only, not a diagnosis.</span>
        </footer>
      </section>
    </main>
  )
}
