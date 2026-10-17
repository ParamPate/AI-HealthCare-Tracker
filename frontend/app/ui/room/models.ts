// A mini hospital floor, drawn in lines: the waiting room, reception, cafe, exam room, nurses' station and ward. Units are meters; y is up; each piece's front is local +z.
import { INK, Piece, type Pen, type V } from './sketch'

export const ZONES = ['Seats', 'Desk', 'Coffee', 'Exam', 'Monitors', 'Ward'] as const

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
  /** Page that clicking this piece opens, from its corner. */
  href?: string
  draw: (p: Pen) => void
  /** Extra parts and motion, after drawing. */
  setup?: (piece: Piece) => void
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

// The monitored chair. The README's recorded setup: a seated person with the two boards about
// 1 m apart at chest height, one each side. The chair sits back so the front of the chest
// rests about 30 cm behind the straight line between the boards' antennas.
const BOARD_GAP = 1.0
const CHEST_Y = 0.93
/** z of the straight line between the two boards */
export const LINK_Z = -3.7
const CHEST_GAP = 0.3
// the person's chest, relative to the chair: center (y, z) and front-to-back radius, at rest
const CHEST_REL = { y: 0.9, z: -0.08, depth: 0.125 }
export const CHAIR = { x: -0.45, z: LINK_Z - CHEST_GAP - (CHEST_REL.z + CHEST_REL.depth) }
/** The chest in room coordinates; it grows forward by up to INHALE_DEPTH of its depth on a breath. */
export const CHEST = { x: CHAIR.x, y: CHEST_REL.y, z: CHAIR.z + CHEST_REL.z, depth: CHEST_REL.depth }
export const INHALE_DEPTH = 0.14
export const TX_COLOR = ORANGE
export const RX_COLOR = BLUE
export const TX_AT: V = [CHAIR.x - BOARD_GAP / 2, CHEST_Y, LINK_Z]
export const RX_AT: V = [CHAIR.x + BOARD_GAP / 2, CHEST_Y, LINK_Z]
/** What a corner's camera frames, when it should not be the whole corner. */
export const ZONE_FOCUS: Record<number, string[]> = { 0: ['patient', 'tx', 'rx', 'tx-stand', 'rx-stand'] }

// ESP32 DevKitC, drawn from its real layout (mm), 2.5x life size so it reads in the room.
const MM = 0.0025
/** Antenna tip relative to the board's center, in meters. */
export const ANTENNA_TOP = 26.5 * MM

function esp32(p: Pen, tag: 'TX' | 'RX') {
  const m = (v: number) => v * MM
  const at = (x: number, y: number, z: number): V => [m(x), m(y), m(z)]
  // the board itself, components facing +z, antenna end up
  p.box([0, 0, 0], [m(28), m(55), m(1.6)])
  p.ink(INK, () => {
    // WROOM-32 module: its own small board, the shield can, and the printed antenna
    p.box(at(0, 15.75, 1.2), [m(18), m(25.5), m(0.8)])
    p.box(at(0, 12.4, 2.8), [m(16), m(17.6), m(2.4)])
    p.label('ESP32-WROOM-32', at(0, 14.5, 4.05), m(14), m(3), { size: 0.48 })
  })
  p.ink(GOLD, () => {
    const z = m(1.65)
    const pts: V[] = []
    for (let i = 0; i <= 7; i++) {
      const x = m(-7 + i * 2)
      pts.push(i % 2 ? [x, m(27.3), z] : [x, m(22.4), z], i % 2 ? [x, m(22.4), z] : [x, m(27.3), z])
    }
    p.poly(pts)
  })
  p.ink(INK, () => {
    // two rows of 19 header pins
    for (const x of [-12.7, 12.7]) {
      p.box(at(x, 0, -2.05), [m(2.54), m(48.3), m(2.5)])
      for (let i = 0; i < 19; i++) {
        const y = -22.86 + i * 2.54
        p.circle(at(x, y, 0.81), m(0.75), 'xy', 6)
        p.seg(at(x, y, -3.3), at(x, y, -8.5))
      }
    }
    // micro USB, EN and BOOT buttons, USB-serial chip, regulator
    p.box(at(0, -25.7, 2.2), [m(7.5), m(5.2), m(2.8)])
    for (const x of [-9.5, 9.5]) {
      p.box(at(x, -22.5, 1.3), [m(3.6), m(3.6), m(1)])
      p.circle(at(x, -22.5, 1.85), m(1), 'xy', 8)
    }
    p.box(at(1, -13.5, 1.25), [m(5), m(5), m(0.9)])
    p.circle(at(-0.6, -12, 1.75), m(0.4), 'xy', 5)
    p.box(at(-7.5, -5, 1.6), [m(6.5), m(3.5), m(1.6)])
    p.label(tag, at(4.5, -4.5, 0.82), m(9), m(5), { size: 0.95 })
  })
  p.ink(RED, () => p.box(at(8, -9, 1.1), [m(1.6), m(0.8), m(0.6)]))
}

/** Tripod stand holding a board by its USB end, with the cable. */
function stand(p: Pen, side: 'tx' | 'rx') {
  const top = CHEST_Y - 27.5 * MM - 0.012
  // label above the board, nudged away from the chair so the board doesn't hide it
  p.ink(side === 'tx' ? ORANGE : BLUE, () => p.label(`${side} board`, [side === 'tx' ? -0.24 : 0.24, CHEST_Y + 0.26, 0.05], 0.32, 0.07, { size: 0.85 }))
  p.seg([0, 0.3, 0], [0, top, 0], true)
  for (const a of [0.9, 3.0, 5.1]) p.seg([0, 0.3, 0], [Math.cos(a) * 0.17, 0.005, Math.sin(a) * 0.17])
  p.box([0, top - 0.004, 0], [0.03, 0.012, 0.075])
  // USB plug under the board's port, cable down the pole
  p.box([0, top + 0.004, 0], [0.012, 0.012, 0.02])
  // cables leave on the side away from the chair
  const d = side === 'tx' ? -1 : 1
  const cable: V[] = [[0, top - 0.004, 0.012], [d * 0.012, top - 0.06, 0.014], [d * 0.014, 0.5, 0.014], [d * 0.016, 0.3, 0.016], [d * 0.05, 0.12, 0.03], [d * 0.09, 0.012, 0.05]]
  if (side === 'tx') {
    // TX only needs power: a small battery pack on the floor
    p.poly([...cable, [-0.15, 0.012, 0.09]])
    p.box([-0.21, 0.012, 0.12], [0.075, 0.024, 0.14])
    p.circle([-0.21, 0.025, 0.07], 0.004, 'xz', 6)
  } else {
    // RX goes back to the computer that runs the backend
    p.poly([...cable, [0.14, 0.006, -0.1], [0.12, 0.006, -0.55], [0.3, 0.006, -0.74], [0.9, 0.006, -0.77]])
  }
}

/** A person sitting back in the chair. The chest and shoulders are separate parts so they can breathe. */
function person(piece: Piece) {
  const p = piece.pen(INK)
  p.ball([0, 0.585, -0.05], [0.165, 0.1, 0.13])
  for (const s of [-1, 1]) {
    p.limb([s * 0.09, 0.565, -0.02], [s * 0.1, 0.56, 0.36], 0.075, 0.06)
    p.ball([s * 0.1, 0.555, 0.37], [0.06, 0.06, 0.06])
    p.limb([s * 0.1, 0.54, 0.38], [s * 0.11, 0.1, 0.42], 0.052, 0.04)
    p.limb([s * 0.11, 0.045, 0.4], [s * 0.115, 0.04, 0.56], 0.045, 0.038)
    p.ball([s * 0.115, 0.04, 0.56], [0.038, 0.038, 0.038])
    p.ball([s * 0.27, 0.72, 0.02], [0.045, 0.045, 0.045])
    p.limb([s * 0.27, 0.72, 0.02], [s * 0.29, 0.72, 0.27], 0.04, 0.033)
    p.ball([s * 0.29, 0.715, 0.33], [0.035, 0.026, 0.06])
  }

  const chest = piece.part([0, CHEST_REL.y - 0.3, CHEST_REL.z])
  const c = chest.pen(INK)
  c.ball([0, 0.12, 0.04], [0.155, 0.13, 0.12])
  c.ball([0, 0.3, 0.0], [0.172, 0.17, CHEST_REL.depth])

  const upper = piece.part([0, 1.05, -0.09])
  const u = upper.pen(INK)
  u.limb([0, -0.05, 0], [0, 0.07, 0.01], 0.045)
  u.ball([0, 0.18, 0.02], [0.085, 0.108, 0.098])
  u.ball([0, 0.225, 0.0], [0.092, 0.075, 0.1])
  u.poly([[0, 0.19, 0.118], [0.004, 0.158, 0.134], [0, 0.15, 0.121]])
  for (const s of [-1, 1]) {
    u.ball([s * 0.19, -0.05, 0], [0.06, 0.06, 0.06])
    u.limb([s * 0.2, -0.06, 0], [s * 0.27, -0.33, 0.11], 0.052, 0.045)
  }

  piece.animate = (b) => {
    const i = (b + 1) / 2
    chest.group.scale.set(1 + 0.03 * i, 1 + 0.035 * i, 1 + INHALE_DEPTH * i)
    upper.group.position.set(0, 1.05 + 0.02 * i, -0.09 + 0.006 * i)
  }
}

function chair(p: Pen) {
  p.box([0, 0.45, 0.02], [0.52, 0.08, 0.5])
  p.with({ at: [0, 0.49, -0.21], rx: -0.13 }, () => p.box([0, 0.28, 0], [0.52, 0.54, 0.07]))
  for (const x of [-0.31, 0.31]) {
    p.box([x, 0.66, 0.0], [0.05, 0.035, 0.46])
    p.poly([[x, 0.645, 0.2], [x, 0.02, 0.22], [x, 0.02, -0.24], [x, 0.45, -0.2]], false, true)
  }
}

/** A desk monitor on a stand; `screen` draws the picture, centered on the glass. */
function monitor(p: Pen, screen: () => void) {
  p.box([0, 0.008, 0], [0.24, 0.016, 0.17])
  p.box([0, 0.14, -0.04], [0.04, 0.25, 0.025])
  p.box([0, 0.38, 0], [0.62, 0.38, 0.03])
  p.rect([0, 0.38, 0.016], 0.57, 0.33)
  p.with({ at: [0, 0.38, 0.017] }, screen)
}

/** Hospital bed, head end toward -z and raised; `patient` tucks someone in. */
function hospitalBed(p: Pen, patient: boolean) {
  p.ink(INK, () => {
    for (const x of [-0.36, 0.36]) for (const z of [-0.85, 0.85]) p.circle([x, 0.06, z], 0.05, 'yz', 10)
    p.box([0, 0.15, 0], [0.8, 0.05, 1.8])
    for (const z of [-0.55, 0.55]) p.seg([0, 0.18, z], [0, 0.42, z], true)
  })
  p.box([0, 0.48, 0.2], [0.9, 0.12, 1.4])
  p.with({ at: [0, 0.48, -0.5], rx: 0.5 }, () => {
    p.box([0, 0, -0.22], [0.9, 0.12, 0.44])
    p.ball([0, 0.11, -0.25], [0.28, 0.05, 0.13])
    if (patient) p.ink(INK, () => p.ball([0, 0.17, -0.1], [0.09, 0.1, 0.1]))
  })
  p.box([0, 0.62, -1.0], [0.94, 0.75, 0.05])
  p.box([0, 0.52, 1.0], [0.94, 0.5, 0.05])
  for (const x of [-0.47, 0.47]) p.box([x, 0.66, -0.25], [0.03, 0.14, 0.6])
  // blanket folded back
  p.seg([-0.45, 0.545, 0], [0.45, 0.545, 0])
  if (patient) p.ball([0, 0.56, 0.35], [0.26, 0.09, 0.6])
}

function wheelchair(p: Pen) {
  for (const s of [-1, 1]) {
    const x = s * 0.3
    p.circle([x, 0.3, -0.05], 0.3, 'yz', 24)
    p.circle([x, 0.3, -0.05], 0.03, 'yz', 8)
    p.circle([x * 0.8, 0.07, 0.42], 0.07, 'yz', 12)
    p.ink(INK, () => {
      // seat rail, back post and push handle; front post down to the caster; footrest
      p.poly([[x * 0.85, 0.48, 0.38], [x * 0.85, 0.48, -0.12], [x * 0.85, 0.98, -0.2], [x * 0.85, 1.0, -0.3]])
      p.seg([x * 0.85, 0.48, 0.38], [x * 0.8, 0.14, 0.42])
      p.seg([x * 0.8, 0.14, 0.42], [x * 0.6, 0.1, 0.56])
    })
  }
  p.box([0, 0.5, 0.13], [0.48, 0.04, 0.44])
  p.with({ at: [0, 0.5, -0.12], rx: -0.12 }, () => p.box([0, 0.24, 0], [0.48, 0.42, 0.03]))
  for (const s of [-1, 1]) p.box([s * 0.14, 0.1, 0.6], [0.16, 0.02, 0.12])
}

const SPECS: Spec[] = [
  // Seats
  { id: 'patient', name: 'chair 1', zone: 0, color: RED, at: [CHAIR.x, 0, CHAIR.z], draw: chair, setup: person },
  { id: 'tx', name: 'tx board', zone: 0, color: ORANGE, at: TX_AT, ry: Math.PI / 2, draw: (p) => esp32(p, 'TX') },
  { id: 'rx', name: 'rx board', zone: 0, color: BLUE, at: RX_AT, ry: -Math.PI / 2, draw: (p) => esp32(p, 'RX') },
  { id: 'tx-stand', name: 'stand', zone: 0, color: INK, at: [TX_AT[0], 0, TX_AT[2]], pick: false, draw: (p) => stand(p, 'tx') },
  { id: 'rx-stand', name: 'stand', zone: 0, color: INK, at: [RX_AT[0], 0, RX_AT[2]], pick: false, draw: (p) => stand(p, 'rx') },
  {
    id: 'chairs', name: 'waiting chairs', zone: 0, color: RED, at: [1.2, 0, -3.75],
    draw: (p) => {
      const pitch = 0.62
      p.box([0, 0.34, -0.06], [pitch * 2 - 0.1, 0.05, 0.07])
      for (const x of [-pitch / 2, pitch / 2]) {
        p.box([x, 0.45, 0.02], [0.52, 0.08, 0.5])
        p.with({ at: [x, 0.49, -0.21], rx: -0.13 }, () => p.box([0, 0.28, 0], [0.52, 0.54, 0.07]))
      }
      for (const x of [-pitch, 0, pitch]) {
        p.box([x, 0.66, 0.0], [0.05, 0.035, 0.46])
        p.seg([x, 0.49, 0.2], [x, 0.645, 0.2])
      }
      for (const x of [-0.5, 0.5]) {
        p.seg([x, 0.32, -0.06], [x, 0.02, -0.06], true)
        p.seg([x, 0.01, -0.32], [x, 0.01, 0.24], true)
      }
    },
  },
  {
    id: 'plant', name: 'plant', zone: 0, color: GREEN, at: [2.3, 0, -3.75],
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
    id: 'screen', name: 'privacy screen', zone: 3, color: TEAL, at: [-4.05, 0, -4.05], ry: -0.15,
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
    id: 'bp', name: 'blood pressure monitor', zone: 3, color: PURPLE, at: [-4.3, 0, -1.35],
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
    id: 'eye-chart', name: 'eye chart', zone: 3, color: RED, at: [-5.96, 0.1, -3.95], ry: Math.PI / 2,
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
    id: 'stool', name: 'stool', zone: 3, color: INK, at: [-4.05, 0, -2.55],
    draw: (p) => {
      star(p, 0.08, 0.24)
      p.cyl([0, 0.08, 0], 0.025, 0.42)
      p.circle([0, 0.28, 0], 0.17, 'xz', 24)
      p.cyl([0, 0.5, 0], 0.19, 0.07)
    },
  },

  // Monitors: the nurses' station. Any screen opens the live monitor page.
  {
    id: 'station', name: 'monitor desk', zone: 4, color: INK, at: [-3.6, 0, 2.4],
    draw: (p) => {
      p.box([0, 0.75, 0], [2.1, 0.05, 0.75])
      for (const x of [-1.02, 1.02]) p.box([x, 0.36, 0], [0.04, 0.72, 0.72])
      p.box([0, 0.42, -0.33], [2.0, 0.5, 0.02])
      // keyboard and mouse
      p.box([0, 0.785, 0.2], [0.46, 0.02, 0.15])
      for (const z of [0.16, 0.2, 0.24]) p.seg([-0.21, 0.796, z], [0.21, 0.796, z])
      p.ball([0.33, 0.79, 0.21], [0.03, 0.016, 0.045])
    },
  },
  {
    id: 'screen-live', name: 'chair 1, live', zone: 4, color: TEAL, at: [-3.6, 0.775, 2.22], href: '/monitor',
    draw: (p) =>
      monitor(p, () =>
        p.ink(GREEN, () => {
          p.label('chair 1', [-0.13, 0.11, 0], 0.26, 0.08, { size: 0.9, align: 'left' })
          p.label('14 /min', [0.13, 0.11, 0], 0.26, 0.08, { size: 0.9, align: 'right' })
          p.poly(wave(-0.25, 0.25, -0.05, 0, 0.06, 3, 48))
        }),
      ),
  },
  {
    id: 'screen-trend', name: 'breathing trend', zone: 4, color: TEAL, at: [-4.27, 0.775, 2.3], ry: 0.35, href: '/monitor',
    draw: (p) =>
      monitor(p, () => {
        p.ink(BLUE, () => {
          p.label('last hour', [-0.09, 0.11, 0], 0.34, 0.08, { size: 0.9, align: 'left' })
          const pts = [[-0.25, -0.05], [-0.18, -0.01], [-0.11, -0.06], [-0.04, 0], [0.03, -0.03], [0.1, 0.02], [0.17, -0.02], [0.25, 0.01]]
          p.poly(pts.map(([x, y]): V => [x, y, 0]))
        })
        p.ink(INK, () => p.seg([-0.25, -0.12, 0], [0.25, -0.12, 0]))
      }),
  },
  {
    id: 'screen-alerts', name: 'alerts', zone: 4, color: TEAL, at: [-2.93, 0.775, 2.3], ry: -0.35, href: '/monitor',
    draw: (p) =>
      monitor(p, () => {
        p.ink(INK, () => p.label('alerts', [-0.13, 0.11, 0], 0.26, 0.08, { size: 0.9, align: 'left' }))
        p.ink(GREEN, () => {
          p.circle([-0.22, -0.03, 0], 0.035, 'xy', 14)
          p.label('no pauses', [0.06, -0.03, 0], 0.44, 0.09, { size: 0.9, align: 'left' })
        })
      }),
  },
  {
    id: 'desk-chair', name: 'desk chair', zone: 4, color: INK, at: [-3.0, 0, 3.2], ry: -2.5,
    draw: (p) => {
      star(p, 0.08, 0.26)
      p.cyl([0, 0.08, 0], 0.025, 0.36)
      p.box([0, 0.47, 0], [0.48, 0.07, 0.46])
      p.with({ at: [0, 0.5, -0.21], rx: -0.12 }, () => p.box([0, 0.3, 0], [0.44, 0.5, 0.05]))
    },
  },

  // Reception, out in the lobby
  { id: 'wheelchair', name: 'wheelchair', zone: 1, color: PURPLE, at: [1.8, 0, 0.5], ry: 0.5, draw: wheelchair },

  // Ward
  { id: 'bed-1', name: 'ward bed', zone: 5, color: BLUE, at: [-1.55, 0, 2.5], draw: (p) => hospitalBed(p, true) },
  { id: 'bed-2', name: 'ward bed', zone: 5, color: BLUE, at: [-0.1, 0, 2.5], draw: (p) => hospitalBed(p, false) },
  {
    id: 'iv', name: 'iv drip', zone: 5, color: TEAL, at: [-2.1, 0, 2.0],
    draw: (p) => {
      star(p, 0.06, 0.22)
      p.seg([0, 0.06, 0], [0, 1.85, 0], true)
      p.seg([-0.12, 1.85, 0], [0.12, 1.85, 0])
      p.box([0.1, 1.66, 0], [0.12, 0.2, 0.04])
      p.poly([[0.1, 1.56, 0], [0.16, 1.1, 0.1], [0.3, 0.7, 0.3]])
    },
  },
  {
    id: 'cabinet', name: 'bedside cabinet', zone: 5, color: INK, at: [-0.82, 0, 1.75],
    draw: (p) => {
      p.box([0, 0.36, 0], [0.42, 0.72, 0.42])
      p.seg([-0.21, 0.52, 0.211], [0.21, 0.52, 0.211])
      p.seg([-0.04, 0.6, 0.212], [0.04, 0.6, 0.212])
      p.ink(BLUE, () => p.cyl([0.08, 0.72, 0], 0.035, 0.1))
    },
  },

  // Low cut-away walls between the rooms, room names on the floor, the sign on the roof.
  // Not a corner of its own, so it fades whenever one corner is in view.
  {
    id: 'walls', name: 'walls', zone: -1, color: INK, at: [0, 0, 0], pick: false,
    draw: (p) => {
      const h = 1.0
      const wall = (x0: number, z0: number, x1: number, z1: number) =>
        p.box([(x0 + x1) / 2, h / 2, (z0 + z1) / 2], [Math.abs(x1 - x0) || 0.1, h, Math.abs(z1 - z0) || 0.1])
      // exam room and nurses' station on the left, each with a door onto the lobby
      wall(-2.4, -4.5, -2.4, -1.4)
      wall(-2.4, -0.5, -2.4, 0.4)
      wall(-2.4, 1.3, -2.4, 4.5)
      wall(-6, 0, -2.4, 0)
      // the ward at the front, door in its back corner
      wall(-2.4, 1.4, 0.4, 1.4)
      wall(1.2, 1.4, 1.2, 4.5)
      // a stub wall setting the cafe apart
      wall(2.6, -4.5, 2.6, -3.0)

      const name = (text: string, x: number, z: number, w: number) =>
        p.with({ at: [x, 0.012, z], rx: -Math.PI / 2 }, () => p.label(text, [0, 0, 0], w, 0.32, { size: 0.85 }))
      name('exam room', -3.65, -1.8, 1.2)
      name("nurses' station", -4.4, 4.05, 2.0)
      name('ward', -0.6, 4.0, 0.9)
      name('waiting room', 0.6, -1.4, 1.8)
      name('cafe', 4.2, -3.2, 0.8)
      name('reception', 4.4, 3.6, 1.4)

      // hospital sign standing on the back wall
      p.box([0.5, 3.1, -4.57], [2.6, 0.6, 0.06])
      p.ink(RED, () => {
        const [a, b] = [0.18, 0.06]
        const plus: [number, number][] = [[-b, a], [b, a], [b, b], [a, b], [a, -b], [b, -b], [b, -a], [-b, -a], [-b, -b], [-a, -b], [-a, b], [-b, b]]
        p.poly(plus.map(([x, y]): V => [-0.45 + x, 3.1 + y, -4.535]), true)
      })
      p.label('hospital', [0.75, 3.1, -4.535], 1.8, 0.45, { size: 0.85 })
    },
  },
]

function shell(p: Pen) {
  const { x0, x1, z0, z1, h } = ROOM
  const t = 0.14
  p.box([(x0 + x1) / 2 - t / 2, -0.05, (z0 + z1) / 2], [x1 - x0 + t, 0.1, z1 - z0], { bold: true })
  p.box([(x0 + x1) / 2 - t / 2, h / 2, z0 - t / 2], [x1 - x0 + t, h, t], { bold: true })
  p.box([x0 - t / 2, h / 2, (z0 + z1) / 2], [t, h, z1 - z0], { bold: true })
  // window on the left wall, over the monitors
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
    piece.group.userData.href = s.href
    s.draw(piece.pen())
    s.setup?.(piece)
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

export function link(piece: Piece): string | undefined {
  return piece.group.userData.href
}
