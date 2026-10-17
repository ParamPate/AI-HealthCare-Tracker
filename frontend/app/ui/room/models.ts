// The waiting room, drawn in lines. Units are meters; y is up; each piece's front is local +z.
import { INK, Piece, type Pen, type V } from './sketch'

export const ZONES = ['Seats', 'Desk', 'Coffee', 'Exam', 'Lab'] as const

const RED = '#d8344f'
const ORANGE = '#ee7a2c'
const BLUE = '#3a6be6'
const GOLD = '#e0a21f'
const GREEN = '#3b9a52'
const PURPLE = '#7a5cf0'
const PINK = '#e2559a'
const TEAL = '#1f9fb0'
const MINT = '#2bb39a'

export const ROOM = { x0: -6, x1: 6, z0: -4.5, z1: 4.5, h: 2.8 }

type Spec = {
  id: string
  name: string
  zone: number
  color: string
  at: V
  ry?: number
  pick?: boolean
  draw: (p: Pen) => void
}

function arc(c: V, r: number, from: number, to: number, n = 12, plane: 'xy' | 'yz' = 'xy'): V[] {
  const pts: V[] = []
  for (let k = 0; k <= n; k++) {
    const a = from + ((to - from) * k) / n
    pts.push(plane === 'xy' ? [c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r, c[2]] : [c[0], c[1] + Math.sin(a) * r, c[2] + Math.cos(a) * r])
  }
  return pts
}

function wave(x0: number, x1: number, y: number, z: number, amp: number, cycles: number, n = 40): V[] {
  const pts: V[] = []
  for (let k = 0; k <= n; k++) {
    const t = k / n
    pts.push([x0 + (x1 - x0) * t, y + Math.sin(t * cycles * Math.PI * 2) * amp, z])
  }
  return pts
}

function leaf(p: Pen, base: V, yaw: number, lean: number, len: number, w: number) {
  const dir: V = [Math.sin(yaw) * Math.sin(lean), Math.cos(lean), Math.cos(yaw) * Math.sin(lean)]
  const side: V = [Math.cos(yaw), 0, -Math.sin(yaw)]
  const pts: V[] = []
  const n = 7
  const droop = (t: number) => -t * t * len * 0.35
  for (let k = 0; k <= n; k++) {
    const t = k / n
    const half = Math.sin(t * Math.PI) * w
    pts.push([base[0] + dir[0] * len * t + side[0] * half, base[1] + dir[1] * len * t + droop(t), base[2] + dir[2] * len * t + side[2] * half])
  }
  for (let k = n - 1; k >= 1; k--) {
    const t = k / n
    const half = Math.sin(t * Math.PI) * w
    pts.push([base[0] + dir[0] * len * t - side[0] * half, base[1] + dir[1] * len * t + droop(t), base[2] + dir[2] * len * t - side[2] * half])
  }
  pts.push(base)
  p.poly(pts)
}

function star(p: Pen, y: number, r: number, legs = 5, bold = true) {
  for (let k = 0; k < legs; k++) {
    const a = (k / legs) * Math.PI * 2
    p.seg([0, y, 0], [Math.cos(a) * r, 0.03, Math.sin(a) * r], bold)
  }
}

const SPECS: Spec[] = [
  // Seats
  {
    id: 'chairs', name: 'waiting chairs', zone: 0, color: RED, at: [0, 0, -3.75],
    draw: (p) => {
      const pitch = 0.62
      p.box([0, 0.34, -0.06], [pitch * 3 - 0.1, 0.05, 0.07])
      for (const i of [-1, 0, 1]) {
        const x = i * pitch
        p.box([x, 0.45, 0.02], [0.52, 0.08, 0.5])
        p.with({ at: [x, 0.49, -0.21], rx: -0.13 }, () => p.box([0, 0.28, 0], [0.52, 0.54, 0.07]))
      }
      for (const k of [-1.5, -0.5, 0.5, 1.5]) {
        const x = k * pitch
        p.box([x, 0.66, 0.0], [0.05, 0.035, 0.46])
        p.seg([x, 0.49, 0.2], [x, 0.645, 0.2])
      }
      for (const x of [-0.82, 0.82]) {
        p.seg([x, 0.32, -0.06], [x, 0.02, -0.06], true)
        p.seg([x, 0.01, -0.32], [x, 0.01, 0.24], true)
      }
    },
  },
  {
    id: 'tx', name: 'tx board', zone: 0, color: ORANGE, at: [-1.45, 0, -3.45],
    draw: (p) => {
      for (const a of [0.4, 2.5, 4.6]) p.seg([0, 0.62, 0], [Math.cos(a) * 0.22, 0, Math.sin(a) * 0.22])
      p.seg([0, 0.62, 0], [0, 0.9, 0], true)
      p.with({ at: [0, 0.98, 0], ry: Math.PI / 2 }, () => {
        p.box([0, 0, 0], [0.2, 0.11, 0.025])
        p.ink(INK, () => p.rect([0.02, 0, 0.014], 0.07, 0.06, 'xy'))
        p.seg([-0.07, 0.055, 0], [-0.07, 0.26, 0], true)
        p.ball([-0.07, 0.27, 0], [0.014, 0.014, 0.014])
      })
      p.ink(GOLD, () => {
        for (const r of [0.12, 0.2, 0.28]) p.poly(arc([0, 1.25, 0], r, -0.6, 0.6, 8, 'yz'))
      })
    },
  },
  {
    id: 'rx', name: 'rx board', zone: 0, color: BLUE, at: [1.45, 0, -3.45],
    draw: (p) => {
      for (const a of [0.7, 2.8, 4.9]) p.seg([0, 0.62, 0], [Math.cos(a) * 0.22, 0, Math.sin(a) * 0.22])
      p.seg([0, 0.62, 0], [0, 0.9, 0], true)
      p.with({ at: [0, 0.98, 0], ry: -Math.PI / 2 }, () => {
        p.box([0, 0, 0], [0.2, 0.11, 0.025])
        p.ink(INK, () => p.rect([-0.02, 0, 0.014], 0.07, 0.06, 'xy'))
        p.seg([0.07, 0.055, 0], [0.07, 0.26, 0], true)
        p.ball([0.07, 0.27, 0], [0.014, 0.014, 0.014])
      })
      p.ink(INK, () =>
        p.poly([[0, 0.93, 0.02], [0.05, 0.7, 0.08], [0.04, 0.35, 0.12], [0.12, 0.02, 0.2], [0.5, 0.01, 0.3], [0.9, 0.01, 0.62]]),
      )
    },
  },
  {
    id: 'rug', name: 'rug', zone: 0, color: INK, at: [0.05, 0, -2.55], pick: false,
    draw: (p) => {
      p.rect([0, 0.005, 0], 2.7, 1.55, 'xz', true)
      p.rect([0, 0.006, 0], 2.5, 1.35, 'xz')
    },
  },
  {
    id: 'table', name: 'coffee table', zone: 0, color: INK, at: [0.15, 0, -2.5],
    draw: (p) => {
      p.cyl([0, 0.4, 0], 0.34, 0.04)
      for (const a of [0.5, 2.6, 4.7]) p.seg([Math.cos(a) * 0.2, 0.4, Math.sin(a) * 0.2], [Math.cos(a) * 0.27, 0.01, Math.sin(a) * 0.27], true)
      p.ink(PURPLE, () => {
        p.with({ at: [-0.08, 0.455, 0.02], ry: 0.4 }, () => p.box([0, 0, 0], [0.26, 0.015, 0.34]))
        p.with({ at: [-0.06, 0.472, 0.04], ry: 0.15 }, () => p.box([0, 0, 0], [0.24, 0.015, 0.32]))
      })
      p.ink(BLUE, () => p.cyl([0.17, 0.44, -0.08], 0.04, 0.1, { r1: 0.045 }))
    },
  },
  {
    id: 'lamp', name: 'floor lamp', zone: 0, color: GOLD, at: [-2.2, 0, -3.95],
    draw: (p) => {
      p.box([0, 0.03, 0], [0.32, 0.05, 0.32])
      const pts: V[] = [[0, 0.06, 0], [0, 1.55, 0]]
      for (let k = 1; k <= 10; k++) {
        const a = (k / 10) * Math.PI * 0.62
        pts.push([Math.sin(a) * 0.7, 1.55 + Math.sin(a * 1.2) * 0.28, Math.sin(a) * 0.55])
      }
      p.poly(pts, false, true)
      const tip = pts[pts.length - 1]
      p.cyl([tip[0], tip[1] - 0.22, tip[2]], 0.17, 0.2, { r1: 0.05 })
    },
  },
  {
    id: 'plant', name: 'plant', zone: 0, color: GREEN, at: [2.3, 0, -3.95],
    draw: (p) => {
      p.ink(INK, () => p.cyl([0, 0, 0], 0.15, 0.36, { r1: 0.19 }))
      const leaves: [number, number, number, number][] = [
        [0, 0.15, 0.95, 0.07], [1.3, 0.4, 0.8, 0.08], [2.5, 0.3, 0.9, 0.07], [3.6, 0.45, 0.75, 0.08],
        [4.6, 0.25, 0.85, 0.07], [5.6, 0.5, 0.7, 0.08], [0.7, 0.6, 0.6, 0.07], [3.1, 0.65, 0.55, 0.06],
      ]
      for (const [yaw, lean, len, w] of leaves) leaf(p, [0, 0.34, 0], yaw, lean, len, w)
    },
  },
  {
    id: 'art', name: 'wall art', zone: 0, color: INK, at: [-0.15, 0, -4.42],
    draw: (p) => {
      for (const [x, inner] of [[-0.42, 'sun'], [0.3, 'beat']] as const) {
        p.box([x, 1.72, 0], [0.5, 0.64, 0.03])
        p.rect([x, 1.72, 0.017], 0.38, 0.52)
        if (inner === 'sun') {
          p.ink(GOLD, () => p.circle([x, 1.8, 0.018], 0.08, 'xy', 20))
          p.ink(BLUE, () => p.poly(wave(x - 0.15, x + 0.15, 1.6, 0.018, 0.03, 1.5, 24)))
        } else {
          p.ink(RED, () => p.poly([[x - 0.16, 1.7, 0.018], [x - 0.05, 1.7, 0.018], [x - 0.02, 1.82, 0.018], [x + 0.02, 1.58, 0.018], [x + 0.05, 1.74, 0.018], [x + 0.16, 1.74, 0.018]]))
        }
      }
      p.cyl([1.15, 2.05, 0], 0.2, 0.03, { axis: 'z' })
      p.seg([1.15, 2.05, 0.035], [1.15, 2.17, 0.035])
      p.seg([1.15, 2.05, 0.035], [1.23, 2.02, 0.035])
    },
  },

  // Desk
  {
    id: 'desk', name: 'reception desk', zone: 1, color: MINT, at: [3.25, 0, 1.6], ry: -Math.PI / 2,
    draw: (p) => {
      p.box([0, 0.55, 0], [2.4, 1.1, 0.06])
      p.box([0, 1.12, 0.03], [2.46, 0.04, 0.3])
      p.box([0, 0.74, -0.4], [2.3, 0.04, 0.74])
      for (const x of [-1.15, 1.15]) p.box([x, 0.36, -0.4], [0.04, 0.72, 0.74])
      p.seg([-1.2, 0.35, 0.031], [1.2, 0.35, 0.031])
      p.seg([-1.2, 0.4, 0.031], [1.2, 0.4, 0.031])
    },
  },
  {
    id: 'monitor', name: 'monitor', zone: 1, color: BLUE, at: [3.75, 0.76, 1.35], ry: Math.PI / 2,
    draw: (p) => {
      p.box([0, 0.01, -0.05], [0.2, 0.02, 0.14])
      p.seg([0, 0.02, -0.06], [0, 0.17, -0.06], true)
      p.box([0, 0.32, -0.05], [0.6, 0.36, 0.03])
      p.rect([0, 0.32, -0.034], 0.54, 0.3)
      p.ink(GREEN, () => p.poly(wave(-0.24, 0.24, 0.36, -0.033, 0.03, 3, 36)))
      for (const [i, key] of [[0, GREEN], [1, GREEN], [2, RED]] as const) {
        p.ink(key, () => p.rect([-0.17 + i * 0.17, 0.24, -0.033], 0.12, 0.05))
      }
      p.box([0, 0.012, 0.16], [0.42, 0.02, 0.13])
    },
  },
  {
    id: 'bell', name: 'desk bell', zone: 1, color: GOLD, at: [3.22, 1.14, 2.35],
    draw: (p) => {
      p.cyl([0, 0, 0], 0.07, 0.015)
      p.ball([0, 0.015, 0], [0.06, 0.05, 0.06])
      p.cyl([0, 0.06, 0], 0.008, 0.025)
    },
  },
  {
    id: 'office-chair', name: 'office chair', zone: 1, color: INK, at: [4.5, 0, 1.3], ry: -Math.PI / 2,
    draw: (p) => {
      star(p, 0.1, 0.3)
      p.cyl([0, 0.1, 0], 0.025, 0.34)
      p.box([0, 0.48, 0], [0.48, 0.07, 0.46])
      p.with({ at: [0, 0.52, -0.22], rx: -0.1 }, () => p.box([0, 0.32, 0], [0.44, 0.5, 0.06]))
      for (const x of [-0.25, 0.25]) {
        p.seg([x, 0.5, -0.05], [x, 0.66, -0.05])
        p.box([x, 0.67, 0.02], [0.05, 0.03, 0.26])
      }
    },
  },
  {
    id: 'sign', name: 'check-in sign', zone: 1, color: PINK, at: [2.25, 0, 2.95], ry: 0.35,
    draw: (p) => {
      p.with({ at: [0, 0, 0.18], rx: -0.2 }, () => {
        p.box([0, 0.46, 0], [0.5, 0.88, 0.03])
        p.rect([0, 0.5, 0.016], 0.42, 0.68)
        p.ink(INK, () => {
          p.label('please', [0, 0.68, 0.018], 0.36, 0.1, { size: 0.7 })
          p.label('check in', [0, 0.55, 0.018], 0.4, 0.13, { size: 0.8 })
        })
        p.poly([[-0.1, 0.36, 0.018], [0.1, 0.36, 0.018], [0.05, 0.4, 0.018]])
        p.seg([0.1, 0.36, 0.018], [0.05, 0.32, 0.018])
      })
      p.with({ at: [0, 0, -0.18], rx: 0.2 }, () => p.box([0, 0.46, 0], [0.5, 0.88, 0.03]))
    },
  },

  // Coffee
  {
    id: 'counter', name: 'counter', zone: 2, color: INK, at: [3.95, 0, -4.15],
    draw: (p) => {
      p.box([0, 0.47, 0], [2.2, 0.86, 0.6])
      p.box([0, 0.92, 0.01], [2.28, 0.04, 0.64])
      for (const i of [-1, 0, 1]) {
        p.rect([i * 0.72, 0.5, 0.301], 0.66, 0.7)
        p.seg([i * 0.72 + 0.25, 0.7, 0.302], [i * 0.72 + 0.25, 0.55, 0.302])
      }
      p.seg([-1.1, 0.06, 0.29], [1.1, 0.06, 0.29])
    },
  },
  {
    id: 'coffee-machine', name: 'coffee machine', zone: 2, color: PINK, at: [3.35, 0.94, -4.2],
    draw: (p) => {
      p.box([0, 0.03, 0], [0.36, 0.06, 0.34])
      p.box([0, 0.3, -0.08], [0.36, 0.48, 0.18])
      p.box([0, 0.48, 0.05], [0.36, 0.12, 0.1])
      p.seg([-0.03, 0.42, 0.06], [-0.03, 0.36, 0.06])
      p.seg([0.03, 0.42, 0.06], [0.03, 0.36, 0.06])
      p.cyl([0, 0.06, 0.06], 0.045, 0.09, { r1: 0.05 })
      for (const x of [-0.1, 0, 0.1]) p.circle([x, 0.48, 0.101], 0.018, 'xy', 12)
      p.cyl([0, 0.54, -0.08], 0.07, 0.16, { r1: 0.11 })
    },
  },
  {
    id: 'kettle', name: 'kettle', zone: 2, color: PINK, at: [4.05, 0.94, -4.12],
    draw: (p) => {
      p.cyl([0, 0, 0], 0.11, 0.02)
      p.cyl([0, 0.02, 0], 0.1, 0.2, { r1: 0.075 })
      p.cyl([0, 0.22, 0], 0.03, 0.025)
      p.poly([[0.09, 0.08, 0], [0.17, 0.16, 0], [0.2, 0.22, 0]])
      p.poly(arc([-0.1, 0.13, 0], 0.08, Math.PI / 2, (Math.PI * 3) / 2, 10))
    },
  },
  {
    id: 'mugs', name: 'mug shelf', zone: 2, color: PINK, at: [4.2, 0, -4.38],
    draw: (p) => {
      p.ink(INK, () => {
        p.box([0, 1.6, 0.1], [1.1, 0.03, 0.2])
        for (const x of [-0.45, 0.45]) p.poly([[x, 1.58, 0.0], [x, 1.5, 0.0], [x, 1.58, 0.16]])
      })
      for (let i = 0; i < 4; i++) {
        const x = -0.36 + i * 0.2
        p.cyl([x, 1.615, 0.1], 0.045, 0.1)
        p.poly(arc([x + 0.05, 1.665, 0.1], 0.03, -Math.PI / 2, Math.PI / 2, 8))
      }
      p.ink(GOLD, () => p.cyl([0.46, 1.615, 0.1], 0.05, 0.16))
    },
  },
  {
    id: 'cooler', name: 'water cooler', zone: 2, color: TEAL, at: [5.5, 0, -4.05],
    draw: (p) => {
      p.box([0, 0.5, 0], [0.34, 1.0, 0.34])
      p.rect([0, 0.82, 0.171], 0.24, 0.16)
      p.ink(BLUE, () => p.box([-0.06, 0.8, 0.19], [0.03, 0.04, 0.04]))
      p.ink(RED, () => p.box([0.06, 0.8, 0.19], [0.03, 0.04, 0.04]))
      p.rect([0, 0.68, 0.171], 0.24, 0.02)
      p.cyl([0, 1.0, 0], 0.05, 0.06)
      p.cyl([0, 1.06, 0], 0.15, 0.4)
      for (const y of [1.18, 1.3]) p.circle([0, y, 0], 0.152, 'xz', 24)
    },
  },

  // Exam
  {
    id: 'bed', name: 'exam bed', zone: 3, color: GREEN, at: [-5.2, 0, -2.6], ry: Math.PI / 2,
    draw: (p) => {
      for (const x of [-0.85, 0.85]) for (const z of [-0.28, 0.28]) p.seg([x, 0, z], [x, 0.62, z], true)
      p.box([0, 0.66, 0], [1.9, 0.1, 0.7])
      p.box([-0.3, 0.75, 0], [1.3, 0.08, 0.66])
      p.with({ at: [0.38, 0.72, 0], rz: 0.42 }, () => p.box([0.3, 0.04, 0], [0.62, 0.08, 0.66]))
      p.box([0, 0.2, 0], [1.75, 0.03, 0.6])
      p.ink(INK, () => p.cyl([0.95, 0.88, -0.36], 0.06, 0.72, { axis: 'z' }))
      p.ink(INK, () => p.seg([0.95, 0.82, 0.0], [0.5, 0.79, 0.0]))
    },
  },
  {
    id: 'screen', name: 'privacy screen', zone: 3, color: TEAL, at: [-3.75, 0, -1.25], ry: 0.5,
    draw: (p) => {
      const panel = () => {
        p.rect([0, 0.95, 0], 0.55, 1.5, 'xy', true)
        for (const x of [-0.18, -0.06, 0.06, 0.18]) p.seg([x, 0.24, 0], [x, 1.66, 0])
        for (const x of [-0.27, 0.27]) p.seg([x, 0.2, 0], [x, 0.02, 0], true)
      }
      p.with({ at: [-0.52, 0, 0.12], ry: -0.5 }, panel)
      p.with({ at: [0, 0, 0] }, panel)
      p.with({ at: [0.52, 0, 0.12], ry: 0.5 }, panel)
    },
  },
  {
    id: 'bp', name: 'blood pressure monitor', zone: 3, color: PURPLE, at: [-4.25, 0, -3.95],
    draw: (p) => {
      star(p, 0.08, 0.25)
      p.seg([0, 0.08, 0], [0, 1.08, 0], true)
      p.box([0, 1.2, 0.02], [0.28, 0.22, 0.1])
      p.rect([-0.02, 1.2, 0.071], 0.17, 0.14)
      p.label('120/80', [-0.02, 1.2, 0.072], 0.16, 0.06, { size: 0.75 })
      p.circle([0.1, 1.24, 0.071], 0.015, 'xy', 10)
      p.circle([0.1, 1.17, 0.071], 0.015, 'xy', 10)
      p.box([0, 0.75, 0.08], [0.22, 0.12, 0.12])
      p.ink(INK, () => p.poly([[0.12, 1.12, 0.06], [0.2, 0.95, 0.12], [0.16, 0.82, 0.16], [0.08, 0.81, 0.14]]))
    },
  },
  {
    id: 'scale', name: 'scale', zone: 3, color: ORANGE, at: [-2.95, 0, -4.05],
    draw: (p) => {
      p.box([0, 0.04, 0.05], [0.38, 0.07, 0.44])
      p.box([0, 0.72, -0.15], [0.07, 1.3, 0.06])
      p.box([0, 1.4, -0.1], [0.42, 0.07, 0.06])
      p.seg([-0.18, 1.44, -0.07], [0.18, 1.44, -0.07])
      p.seg([0.02, 1.43, -0.06], [0.02, 1.37, -0.06])
      p.seg([0, 1.43, -0.15], [0, 1.95, -0.15], true)
      p.box([0, 1.96, -0.05], [0.04, 0.02, 0.22])
    },
  },
  {
    id: 'eye-chart', name: 'eye chart', zone: 3, color: RED, at: [-5.96, 0, -0.6], ry: Math.PI / 2,
    draw: (p) => {
      p.box([0, 1.55, 0], [0.56, 0.82, 0.02])
      p.rect([0, 1.55, 0.011], 0.48, 0.74)
      p.ink(INK, () => {
        const rows: [string, number, number][] = [['E', 1.82, 0.16], ['F P', 1.69, 0.1], ['T O Z', 1.58, 0.075], ['L P E D', 1.49, 0.06], ['P E C F D', 1.41, 0.05]]
        for (const [text, y, h] of rows) p.label(text, [0, y, 0.012], 0.44, h, { size: 0.9 })
      })
      p.seg([-0.2, 1.35, 0.012], [0.2, 1.35, 0.012])
    },
  },
  {
    id: 'stool', name: 'stool', zone: 3, color: INK, at: [-4.0, 0, -2.75],
    draw: (p) => {
      star(p, 0.08, 0.24)
      p.cyl([0, 0.08, 0], 0.025, 0.42)
      p.circle([0, 0.28, 0], 0.17, 'xz', 24)
      p.cyl([0, 0.5, 0], 0.19, 0.07)
    },
  },

  // Lab
  {
    id: 'bench', name: 'workbench', zone: 4, color: INK, at: [-3.4, 0, 2.45],
    draw: (p) => {
      p.box([0, 0.75, 0], [2.2, 0.05, 0.72])
      for (const x of [-1.05, 1.05]) for (const z of [-0.31, 0.31]) p.box([x, 0.36, z], [0.05, 0.72, 0.05])
      p.box([-0.35, 0.18, 0], [1.4, 0.03, 0.62])
      p.box([0.72, 0.55, 0], [0.56, 0.35, 0.66])
      for (const y of [0.63, 0.47]) {
        p.rect([0.72, y, 0.331], 0.5, 0.13)
        p.seg([0.66, y, 0.332], [0.78, y, 0.332])
      }
    },
  },
  {
    id: 'laptop', name: 'laptop', zone: 4, color: BLUE, at: [-3.75, 0.78, 2.4],
    draw: (p) => {
      p.box([0, 0.01, 0], [0.4, 0.02, 0.28])
      p.rect([0, 0.021, 0.02], 0.34, 0.14, 'xz')
      p.rect([0, 0.021, 0.11], 0.12, 0.05, 'xz')
      p.with({ at: [0, 0.02, -0.14], rx: -0.28 }, () => {
        p.box([0, 0.135, 0], [0.4, 0.27, 0.012])
        p.rect([0, 0.14, 0.007], 0.36, 0.23)
        p.ink(GREEN, () => p.poly(wave(-0.15, 0.15, 0.12, 0.008, 0.035, 2.5, 30)))
        p.ink(GREEN, () => p.label('14.2 /min', [-0.08, 0.215, 0.008], 0.16, 0.035, { size: 0.8, align: 'left' }))
      })
    },
  },
  {
    id: 'router', name: 'wifi router', zone: 4, color: INK, at: [-2.75, 0.78, 2.35],
    draw: (p) => {
      p.box([0, 0.03, 0], [0.32, 0.05, 0.2])
      for (const x of [-0.12, 0, 0.12]) p.seg([x, 0.055, -0.08], [x * 1.4, 0.3, -0.12], true)
      p.ink(GREEN, () => {
        for (const x of [-0.08, -0.04, 0]) p.circle([x, 0.03, 0.101], 0.006, 'xy', 6)
      })
      p.ink(GOLD, () => {
        for (const r of [0.08, 0.14, 0.2]) p.poly(arc([0, 0.38, -0.1], r, Math.PI * 0.25, Math.PI * 0.75, 8))
      })
    },
  },
  {
    id: 'phone', name: 'phone', zone: 4, color: RED, at: [-3.15, 0.78, 2.55], ry: -0.15,
    draw: (p) => {
      p.ink(INK, () => {
        p.box([0, 0.01, 0], [0.12, 0.02, 0.1])
        p.seg([0, 0.02, -0.03], [0, 0.07, -0.05])
      })
      p.with({ at: [0, 0.02, -0.02], rx: -0.3 }, () => {
        p.box([0, 0.09, 0], [0.085, 0.17, 0.01])
        p.rrect([0, 0.09, 0.0055], 0.075, 0.16, 0.01)
        p.rect([0, 0.13, 0.006], 0.06, 0.03)
        p.label('pause', [0, 0.13, 0.007], 0.06, 0.02, { size: 0.9 })
        p.label('12 s', [0, 0.08, 0.007], 0.06, 0.03, { size: 0.9 })
      })
    },
  },
  {
    id: 'whiteboard', name: 'whiteboard', zone: 4, color: INK, at: [-5.1, 0, 1.35], ry: 0.75,
    draw: (p) => {
      p.box([0, 1.35, 0], [1.3, 0.85, 0.03])
      p.rect([0, 1.35, 0.016], 1.2, 0.75)
      for (const x of [-0.6, 0.6]) {
        p.seg([x, 0.92, 0], [x, 0.05, 0], true)
        p.seg([x, 0.03, -0.25], [x, 0.03, 0.25], true)
      }
      p.ink(ORANGE, () => {
        p.rect([-0.42, 1.38, 0.017], 0.14, 0.1)
        p.label('tx', [-0.42, 1.22, 0.017], 0.12, 0.07, { size: 0.9 })
      })
      p.ink(BLUE, () => {
        p.rect([0.42, 1.38, 0.017], 0.14, 0.1)
        p.label('rx', [0.42, 1.22, 0.017], 0.12, 0.07, { size: 0.9 })
      })
      p.ink(GOLD, () => p.poly(wave(-0.33, 0.33, 1.42, 0.017, 0.03, 3, 30)))
      p.ink(RED, () => {
        p.circle([0, 1.62, 0.017], 0.05, 'xy', 14)
        p.poly([[0, 1.57, 0.017], [0, 1.45, 0.017], [0.08, 1.45, 0.017], [0.08, 1.38, 0.017]])
      })
      p.ink(GREEN, () => p.poly(wave(-0.45, 0.45, 1.06, 0.017, 0.025, 4, 36)))
    },
  },
  {
    id: 'toolbox', name: 'toolbox', zone: 4, color: ORANGE, at: [-2.25, 0, 3.05], ry: -0.4,
    draw: (p) => {
      p.box([0, 0.13, 0], [0.5, 0.24, 0.26])
      p.seg([-0.25, 0.2, 0.131], [0.25, 0.2, 0.131])
      p.box([0, 0.03, 0.135], [0.06, 0.04, 0.01])
      p.poly([[-0.14, 0.25, 0], [-0.12, 0.33, 0], [0.12, 0.33, 0], [0.14, 0.25, 0]], false, true)
    },
  },
]

function shell(p: Pen) {
  const { x0, x1, z0, z1, h } = ROOM
  const t = 0.14
  p.box([(x0 + x1) / 2 - t / 2, -0.05, (z0 + z1) / 2], [x1 - x0 + t, 0.1, z1 - z0], { bold: true })
  p.box([(x0 + x1) / 2 - t / 2, h / 2, z0 - t / 2], [x1 - x0 + t, h, t], { bold: true })
  p.box([x0 - t / 2, h / 2, (z0 + z1) / 2], [t, h, z1 - z0], { bold: true })
  // window on the left wall, over the lab
  p.rect([x0 + 0.002, 1.55, 2.9], 1.5, 1.0, 'yz')
  p.rect([x0 + 0.003, 1.55, 2.9], 1.4, 0.9, 'yz')
  p.seg([x0 + 0.003, 1.1, 2.9], [x0 + 0.003, 2.0, 2.9])
  // door on the back wall, between the exam corner and the seats
  p.rect([-1.75, 1.05, z0 + 0.002], 0.9, 2.1, 'xy')
  p.circle([-1.43, 1.0, z0 + 0.01], 0.025, 'xy', 8)
}

export type Room = { pieces: Piece[]; shell: Piece }

export function buildRoom(widths: { main: number; sketch: number; bold: number }, theme: 'light' | 'dark'): Room {
  const pieces = SPECS.map((s, i) => {
    const piece = new Piece(s.id, s.name, s.zone, s.color, 1000 + i * 97)
    piece.group.position.set(...s.at)
    piece.group.rotation.y = s.ry ?? 0
    piece.front = s.ry ?? 0
    piece.group.userData.pick = s.pick !== false
    s.draw(piece.pen())
    piece.build(widths, theme)
    return piece
  })
  const shellPiece = new Piece('shell', 'room', -1, INK, 7)
  shell(shellPiece.pen())
  shellPiece.build(widths, theme)
  return { pieces, shell: shellPiece }
}

export function pickable(piece: Piece) {
  return piece.group.userData.pick !== false
}
