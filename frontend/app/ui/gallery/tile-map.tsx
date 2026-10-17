// The project as a metro map: each line is a path the data can take.
import { mod } from './signal'

type Station = { x: number; y: number; name: string; at: 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'; hub?: boolean }

const YELLOW = '#e9cf2c'
const GREEN = '#5fd06b'
const RED = '#e2445c'
const TEAL = '#43d1c9'
const BLUE = '#2f97e6'

const S: Record<string, Station> = {
  tx: { x: 300, y: 412, name: 'TX\nboard', at: 'n' },
  wifi: { x: 404, y: 412, name: 'Wi-Fi\nchannel 6', at: 's' },
  rx: { x: 508, y: 412, name: 'RX\nboard', at: 'nw', hub: true },
  parse: { x: 612, y: 412, name: 'csi_format\nparse', at: 's' },
  live: { x: 742, y: 412, name: 'Live\nAnalyser', at: 'ne', hub: true },
  record: { x: 508, y: 204, name: 'record.py', at: 'nw', hub: true },
  recs: { x: 508, y: 308, name: 'recordings/', at: 'e' },
  replay: { x: 508, y: 516, name: 'replay', at: 'ne', hub: true },
  explore: { x: 508, y: 620, name: 'explore.py', at: 's' },
  view: { x: 378, y: 204, name: 'live_view\n.py', at: 'n' },
  label: { x: 638, y: 204, name: 'label.py', at: 'n' },
  holds: { x: 742, y: 204, name: 'hold\nmarks', at: 'n' },
  breathing: { x: 742, y: 308, name: 'breathing\n.py', at: 'e' },
  db: { x: 352, y: 516, name: 'healthcare\n.db', at: 's' },
  alerts: { x: 430, y: 516, name: 'alerts.py', at: 's' },
  classify: { x: 638, y: 516, name: 'classify()', at: 's' },
  ws: { x: 742, y: 516, name: 'WebSocket\n/ws', at: 's', hub: true },
  page: { x: 846, y: 516, name: 'Next.js\npage', at: 'n' },
  phone: { x: 950, y: 516, name: 'phone\nalarm', at: 's' },
}

const LINES: { color: string; path: string[]; tail?: [number, number] }[] = [
  { color: YELLOW, path: ['tx', 'wifi', 'rx', 'parse', 'live'] },
  { color: GREEN, path: ['live'], tail: [1025, 412] },
  { color: RED, path: ['record', 'recs', 'rx', 'replay', 'explore'] },
  { color: TEAL, path: ['view', 'record', 'label', 'holds', 'breathing', 'live'] },
  { color: BLUE, path: ['db', 'alerts', 'replay', 'classify', 'ws', 'page', 'phone'] },
]

function points(line: (typeof LINES)[number]) {
  const pts = line.path.map((k) => [S[k].x, S[k].y] as [number, number])
  if (line.tail) pts.push(line.tail)
  return pts
}

function along(pts: [number, number][], f: number): [number, number] {
  const lens = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]))
  let d = f * lens.reduce((a, b) => a + b, 0)
  for (let i = 0; i < lens.length; i++) {
    if (d <= lens[i]) {
      const k = d / lens[i]
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k]
    }
    d -= lens[i]
  }
  return pts[pts.length - 1]
}

function Label({ s }: { s: Station }) {
  const lines = s.name.split('\n')
  const off = s.hub ? 17 : 14
  const dx = s.at.includes('e') ? off : s.at.includes('w') ? -off : 0
  const dy = s.at.startsWith('n') ? -off - (lines.length - 1) * 13.5 - 2 : s.at.startsWith('s') ? off + 9 : 4
  const anchor = s.at.includes('e') ? 'start' : s.at.includes('w') ? 'end' : 'middle'
  return (
    <text x={s.x + dx} y={s.y + dy} textAnchor={anchor} fontSize={11.5} fontWeight={600} fill="#3d3d40">
      {lines.map((l, i) => (
        <tspan key={i} x={s.x + dx} dy={i ? 13.5 : 0}>
          {l}
        </tspan>
      ))}
    </text>
  )
}

export function PipelineMap({ t }: { t: number }) {
  const trains = [
    { line: 0, f: mod(t / 7, 1) },
    { line: 4, f: mod(t / 9 + 0.3, 1) },
    { line: 2, f: mod(t / 8 + 0.6, 1) },
  ]
  return (
    <svg viewBox="0 0 1025 759" className="absolute inset-0 h-full w-full bg-[#fbfbfb] font-body">
      <defs>
        <pattern id="map-dots" width="26" height="26" patternUnits="userSpaceOnUse" x="13" y="13">
          <circle cx="1" cy="1" r="1" fill="#e2e2e4" />
        </pattern>
      </defs>
      <rect width="1025" height="759" fill="url(#map-dots)" />
      {LINES.map((line, i) => (
        <polyline key={i} points={points(line).map((p) => p.join(',')).join(' ')} fill="none" stroke={line.color} strokeWidth={6} strokeLinejoin="round" />
      ))}
      {trains.map(({ line, f }, i) => {
        const pts = points(LINES[line])
        const [x, y] = along(pts, f)
        const [x2, y2] = along(pts, Math.min(1, f + 0.01))
        const angle = (Math.atan2(y2 - y, x2 - x) * 180) / Math.PI
        return <rect key={i} x={x - 9} y={y - 3.5} width={18} height={7} rx={3.5} fill="white" stroke={LINES[line].color} strokeWidth={1.6} opacity={0.95} transform={`rotate(${angle} ${x} ${y})`} />
      })}
      {Object.entries(S).map(([k, s]) => {
        const line = LINES.find((l) => l.path.includes(k))!
        const size = s.hub ? 22 : 15
        return (
          <g key={k}>
            <rect
              x={s.x - size / 2}
              y={s.y - size / 2}
              width={size}
              height={size}
              rx={s.hub ? 4 : 3}
              fill="white"
              stroke={s.hub ? '#1f1f22' : line.color}
              strokeWidth={s.hub ? 3.5 : 3}
            />
            <Label s={s} />
          </g>
        )
      })}
    </svg>
  )
}
