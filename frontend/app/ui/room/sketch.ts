// Hand-drawn line rendering for the 3D room: every object is white fill (for hidden lines)
// plus wobbly fat-line strokes, with view-dependent silhouettes for round shapes.
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js'

export type V = [number, number, number]
type Plane = 'xy' | 'xz' | 'yz'
type Axis = 'x' | 'y' | 'z'

export const INK = 'ink'
const PALETTE = {
  light: { ink: '#1f1f22', paper: '#ffffff' },
  dark: { ink: '#e9e9ec', paper: '#141416' },
}
export type Theme = keyof typeof PALETTE

export function paper(theme: Theme) {
  return PALETTE[theme].paper
}

function resolve(key: string, theme: Theme) {
  return key === INK ? PALETTE[theme].ink : key
}

export function mulberry32(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

type Round =
  | { kind: 'cyl'; m: THREE.Matrix4; r0: number; r1: number; h: number; key: string }
  | { kind: 'ball'; m: THREE.Matrix4; key: string }

type Label = { text: string; m: THREE.Matrix4; w: number; h: number; key: string; size: number; align: CanvasTextAlign }

export type Widths = { main: number; sketch: number; bold: number }

const BALL_N = 30
const v3 = new THREE.Vector3()
const v4 = new THREE.Vector3()
const inv = new THREE.Matrix4()

export class Piece {
  readonly group = new THREE.Group()
  readonly segs: number[] = []
  readonly keys: string[] = []
  readonly bold: number[] = []
  readonly boldKeys: string[] = []
  readonly rounds: Round[] = []
  readonly labels: Label[] = []
  readonly fills: THREE.BufferGeometry[] = []
  readonly box = new THREE.Box3()
  readonly center = new THREE.Vector3()
  radius = 1
  opacity = 1
  fill?: THREE.Mesh
  /** yaw of the object's front, for close-up views */
  front = 0
  private rand: () => number
  private mats: { mat: LineMaterial; alpha: number }[] = []
  private colored: { geo: LineSegmentsGeometry; keys: string[] }[] = []
  private sil?: { geo: LineSegmentsGeometry; arr: Float32Array; sketch: boolean }[]
  private labelMeshes: { mesh: THREE.Mesh; label: Label }[] = []
  private fillMat?: THREE.MeshBasicMaterial

  constructor(
    readonly id: string,
    readonly name: string,
    readonly zone: number,
    readonly color: string,
    seed: number,
  ) {
    this.rand = mulberry32(seed)
  }

  pen(key = this.color) {
    return new Pen(this, key)
  }

  build(widths: Widths, theme: Theme) {
    const r = this.rand
    const main: number[] = []
    const mainKeys: string[] = []
    const sketch: number[] = []
    const sketchKeys: string[] = []
    const thick: number[] = []
    const thickKeys: string[] = []
    const scale = Math.max(0.4, Math.min(2.5, this.sizeHint()))

    const add = (src: number[], srcKeys: string[], out: number[], outKeys: string[], doubled: boolean) => {
      for (let i = 0; i < src.length; i += 6) {
        const a: V = [src[i], src[i + 1], src[i + 2]]
        const b: V = [src[i + 3], src[i + 4], src[i + 5]]
        const n = wobble(a, b, r, 0.0035 * scale, out)
        for (let k = 0; k < n; k++) outKeys.push(srcKeys[i / 6])
        if (doubled && r() < 0.75) {
          offsetStroke(a, b, r, 0.0045 * scale, sketch)
          sketchKeys.push(srcKeys[i / 6])
        }
      }
    }
    add(this.segs, this.keys, main, mainKeys, true)
    add(this.bold, this.boldKeys, thick, thickKeys, false)

    const mainMat = this.material(widths.main, 1)
    const sketchMat = this.material(widths.sketch, 0.42)
    const boldMat = this.material(widths.bold, 1)
    this.addLines(main, mainKeys, mainMat)
    this.addLines(sketch, sketchKeys, sketchMat)
    this.addLines(thick, thickKeys, boldMat)

    if (this.rounds.length) {
      const keys: string[] = []
      for (const round of this.rounds) {
        const n = round.kind === 'cyl' ? 2 : BALL_N
        for (let k = 0; k < n; k++) keys.push(round.key)
      }
      this.sil = [false, true].map((isSketch) => {
        const arr = new Float32Array(keys.length * 6)
        const geo = new LineSegmentsGeometry()
        geo.setPositions(arr)
        const line = new LineSegments2(geo, isSketch ? sketchMat : mainMat)
        line.frustumCulled = false
        this.group.add(line)
        this.colored.push({ geo, keys })
        return { geo, arr, sketch: isSketch }
      })
    }

    if (this.fills.length) {
      const geo = mergeGeometries(this.fills.map((g) => (g.index ? g.toNonIndexed() : g)).map(stripToPosition))
      this.fillMat = new THREE.MeshBasicMaterial({
        color: paper(theme),
        polygonOffset: true,
        polygonOffsetFactor: 1.5,
        polygonOffsetUnits: 3,
      })
      this.fill = new THREE.Mesh(geo, this.fillMat)
      this.fill.userData.piece = this
      this.group.add(this.fill)
    }

    for (const label of this.labels) {
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(label.w, label.h),
        new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }),
      )
      mesh.matrixAutoUpdate = false
      mesh.matrix.copy(label.m)
      mesh.matrixWorldNeedsUpdate = true
      this.group.add(mesh)
      this.labelMeshes.push({ mesh, label })
    }
    this.drawLabels(theme)
    this.measure()
    this.setTheme(theme)
  }

  private sizeHint() {
    const b = new THREE.Box3()
    for (let i = 0; i < this.segs.length; i += 3) b.expandByPoint(v3.set(this.segs[i], this.segs[i + 1], this.segs[i + 2]))
    const s = b.getSize(v3)
    return Math.max(s.x, s.y, s.z) || 1
  }

  private material(linewidth: number, alpha: number) {
    const mat = new LineMaterial({ linewidth, vertexColors: true, transparent: true, depthWrite: false })
    this.mats.push({ mat, alpha })
    return mat
  }

  private addLines(pos: number[], keys: string[], mat: LineMaterial) {
    if (!pos.length) return
    const geo = new LineSegmentsGeometry()
    geo.setPositions(pos)
    geo.setColors(new Float32Array(keys.length * 6))
    this.colored.push({ geo, keys })
    this.group.add(new LineSegments2(geo, mat))
  }

  private measure() {
    this.group.updateMatrixWorld(true)
    this.box.makeEmpty()
    const m = this.group.matrixWorld
    for (const list of [this.segs, this.bold]) {
      for (let i = 0; i < list.length; i += 3) this.box.expandByPoint(v3.set(list[i], list[i + 1], list[i + 2]).applyMatrix4(m))
    }
    if (this.fill) {
      this.fill.geometry.computeBoundingBox()
      this.box.union(this.fill.geometry.boundingBox!.clone().applyMatrix4(m))
    }
    this.box.getCenter(this.center)
    this.radius = this.box.getSize(v3).length() / 2
  }

  /** Call after moving the group. */
  remeasure() {
    this.measure()
  }

  setTheme(theme: Theme) {
    const c = new THREE.Color()
    for (const { geo, keys } of this.colored) {
      const arr = new Float32Array(keys.length * 6)
      keys.forEach((key, i) => {
        c.set(resolve(key, theme))
        arr.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6)
      })
      geo.setColors(arr)
    }
    this.fillMat?.color.set(paper(theme))
    this.drawLabels(theme)
  }

  private drawLabels(theme: Theme) {
    const family = typeof window === 'undefined' ? 'sans-serif' : handFont()
    for (const { mesh, label } of this.labelMeshes) {
      const px = 64
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(8, Math.round((label.w / label.h) * px * 2))
      canvas.height = px * 2
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = resolve(label.key, theme)
      ctx.font = `${Math.round(px * 2 * label.size)}px ${family}`
      ctx.textAlign = label.align
      ctx.textBaseline = 'middle'
      const x = label.align === 'left' ? 4 : label.align === 'right' ? canvas.width - 4 : canvas.width / 2
      ctx.fillText(label.text, x, canvas.height / 2)
      const mat = mesh.material as THREE.MeshBasicMaterial
      mat.map?.dispose()
      mat.map = new THREE.CanvasTexture(canvas)
      mat.map.colorSpace = THREE.SRGBColorSpace
      mat.map.anisotropy = 4
      mat.needsUpdate = true
    }
  }

  setOpacity(o: number) {
    this.opacity = o
    for (const { mat, alpha } of this.mats) mat.opacity = o * alpha
    for (const { mesh } of this.labelMeshes) (mesh.material as THREE.MeshBasicMaterial).opacity = o
  }

  setResolution(w: number, h: number) {
    for (const { mat } of this.mats) mat.resolution.set(w, h)
  }

  /** Recompute silhouettes of round shapes for a camera at this world position. */
  updateSilhouettes(camWorld: THREE.Vector3) {
    if (!this.sil) return
    const local = this.group.worldToLocal(v4.copy(camWorld))
    for (const s of this.sil) {
      let o = 0
      const jitter = s.sketch ? 0.004 : 0
      for (const round of this.rounds) {
        inv.copy(round.m).invert()
        const c = v3.copy(local).applyMatrix4(inv)
        if (round.kind === 'cyl') {
          const d = Math.hypot(c.x, c.z) || 1
          const px = -c.z / d
          const pz = c.x / d
          for (const side of [1, -1]) {
            const a = new THREE.Vector3(px * round.r0 * side + jitter, 0, pz * round.r0 * side).applyMatrix4(round.m)
            const b = new THREE.Vector3(px * round.r1 * side, round.h + jitter, pz * round.r1 * side).applyMatrix4(round.m)
            s.arr.set([a.x, a.y, a.z, b.x, b.y, b.z], o)
            o += 6
          }
        } else {
          const D = Math.max(1.0001, c.length())
          const n = c.clone().normalize()
          const center = n.clone().multiplyScalar(1 / D)
          const rad = Math.sqrt(1 - 1 / (D * D)) * (1 + jitter * 2)
          const u = new THREE.Vector3(0, 1, 0).cross(n)
          if (u.lengthSq() < 1e-6) u.set(1, 0, 0)
          u.normalize()
          const w = n.clone().cross(u).normalize()
          let prev: THREE.Vector3 | null = null
          for (let k = 0; k <= BALL_N; k++) {
            const t = (k / BALL_N) * Math.PI * 2 + jitter * 40
            const p = center
              .clone()
              .addScaledVector(u, Math.cos(t) * rad)
              .addScaledVector(w, Math.sin(t) * rad)
              .applyMatrix4(round.m)
            if (prev) {
              s.arr.set([prev.x, prev.y, prev.z, p.x, p.y, p.z], o)
              o += 6
            }
            prev = p
          }
        }
      }
      const attr = s.geo.attributes.instanceStart as THREE.InterleavedBufferAttribute
      ;(attr.data.array as Float32Array).set(s.arr)
      attr.data.needsUpdate = true
    }
  }
}

function stripToPosition(g: THREE.BufferGeometry) {
  const out = new THREE.BufferGeometry()
  out.setAttribute('position', g.getAttribute('position'))
  return out
}

let cachedHand = ''
export function handFont() {
  if (cachedHand) return cachedHand
  const v = getComputedStyle(document.documentElement).getPropertyValue('--font-hand').trim()
  cachedHand = v || 'cursive'
  return cachedHand
}

/** Split a stroke into a few pieces bent by a gentle random curve. Returns segment count. */
function wobble(a: V, b: V, r: () => number, amp: number, out: number[]) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2])
  const n = Math.max(1, Math.min(6, Math.round(len / 0.12)))
  const dir: V = [r() - 0.5, r() - 0.5, r() - 0.5]
  const bend = Math.min(amp, len * 0.03) * (r() < 0.5 ? -1 : 1) * (0.4 + r())
  const ext = Math.min(len * 0.04, amp * 1.5) * r()
  let prev: V = [a[0] - ((b[0] - a[0]) / len) * ext * 0.5, a[1] - ((b[1] - a[1]) / len) * ext * 0.5, a[2] - ((b[2] - a[2]) / len) * ext * 0.5]
  for (let i = 1; i <= n; i++) {
    const t = i / n
    const k = Math.sin(t * Math.PI) * bend
    const p: V = [
      a[0] + (b[0] - a[0]) * t + dir[0] * k,
      a[1] + (b[1] - a[1]) * t + dir[1] * k,
      a[2] + (b[2] - a[2]) * t + dir[2] * k,
    ]
    if (i === n && len > 0) {
      p[0] += ((b[0] - a[0]) / len) * ext * 0.5
      p[1] += ((b[1] - a[1]) / len) * ext * 0.5
      p[2] += ((b[2] - a[2]) / len) * ext * 0.5
    }
    out.push(...prev, ...p)
    prev = p
  }
  return n
}

/** A second, slightly displaced and overshooting stroke, the way a quick sketch doubles lines. */
function offsetStroke(a: V, b: V, r: () => number, amp: number, out: number[]) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) || 1
  const over = Math.min(len * 0.06, amp * 3) * r()
  const d: V = [(b[0] - a[0]) / len, (b[1] - a[1]) / len, (b[2] - a[2]) / len]
  const j = () => (r() - 0.5) * 2 * amp
  out.push(
    a[0] - d[0] * over + j(), a[1] - d[1] * over + j(), a[2] - d[2] * over + j(),
    b[0] + d[0] * over * r() + j(), b[1] + d[1] * over * r() + j(), b[2] + d[2] * over * r() + j(),
  )
}

type With = { at?: V; ry?: number; rx?: number; rz?: number; key?: string }

/** Authoring helper: draws into a Piece in local coordinates, with a transform stack. */
export class Pen {
  private stack: THREE.Matrix4[] = [new THREE.Matrix4()]
  constructor(
    private p: Piece,
    public key: string,
  ) {}

  private get m() {
    return this.stack[this.stack.length - 1]
  }

  with(o: With, fn: () => void) {
    const m = this.m.clone()
    if (o.at) m.multiply(new THREE.Matrix4().makeTranslation(...o.at))
    if (o.ry) m.multiply(new THREE.Matrix4().makeRotationY(o.ry))
    if (o.rx) m.multiply(new THREE.Matrix4().makeRotationX(o.rx))
    if (o.rz) m.multiply(new THREE.Matrix4().makeRotationZ(o.rz))
    const key = this.key
    if (o.key) this.key = o.key
    this.stack.push(m)
    fn()
    this.stack.pop()
    this.key = key
  }

  ink(key: string, fn: () => void) {
    this.with({ key }, fn)
  }

  private tp(v: V): V {
    v3.set(...v).applyMatrix4(this.m)
    return [v3.x, v3.y, v3.z]
  }

  seg(a: V, b: V, bold = false) {
    const list = bold ? this.p.bold : this.p.segs
    list.push(...this.tp(a), ...this.tp(b))
    ;(bold ? this.p.boldKeys : this.p.keys).push(this.key)
  }

  poly(pts: V[], closed = false, bold = false) {
    for (let i = 0; i < pts.length - 1; i++) this.seg(pts[i], pts[i + 1], bold)
    if (closed && pts.length > 2) this.seg(pts[pts.length - 1], pts[0], bold)
  }

  private addFill(g: THREE.BufferGeometry, local: THREE.Matrix4) {
    g.applyMatrix4(this.m.clone().multiply(local))
    this.p.fills.push(g)
  }

  /** Box by center and size. */
  box(c: V, s: V, o: { fill?: boolean; bold?: boolean; edges?: boolean } = {}) {
    const [x, y, z] = c
    const [hx, hy, hz] = [s[0] / 2, s[1] / 2, s[2] / 2]
    if (o.edges !== false) {
      const P = (i: number, j: number, k: number): V => [x + i * hx, y + j * hy, z + k * hz]
      for (const j of [-1, 1]) for (const k of [-1, 1]) this.seg(P(-1, j, k), P(1, j, k), o.bold)
      for (const i of [-1, 1]) for (const k of [-1, 1]) this.seg(P(i, -1, k), P(i, 1, k), o.bold)
      for (const i of [-1, 1]) for (const j of [-1, 1]) this.seg(P(i, j, -1), P(i, j, 1), o.bold)
    }
    if (o.fill !== false) this.addFill(new THREE.BoxGeometry(s[0], s[1], s[2]), new THREE.Matrix4().makeTranslation(x, y, z))
  }

  /** Rectangle outline centered at c in the given plane. */
  rect(c: V, w: number, h: number, plane: Plane = 'xy', bold = false) {
    const pts = rectPts(c, w, h, plane)
    this.poly(pts, true, bold)
  }

  /** Rounded rectangle outline. */
  rrect(c: V, w: number, h: number, r: number, plane: Plane = 'xy') {
    const pts: V[] = []
    const corners: [number, number, number][] = [
      [w / 2 - r, h / 2 - r, 0],
      [-w / 2 + r, h / 2 - r, Math.PI / 2],
      [-w / 2 + r, -h / 2 + r, Math.PI],
      [w / 2 - r, -h / 2 + r, (Math.PI * 3) / 2],
    ]
    for (const [cx, cy, a0] of corners) {
      for (let k = 0; k <= 4; k++) {
        const a = a0 + (k / 4) * (Math.PI / 2)
        pts.push(planar(c, cx + Math.cos(a) * r, cy + Math.sin(a) * r, plane))
      }
    }
    this.poly(pts, true)
  }

  circle(c: V, r: number, plane: Plane = 'xz', n = 28, from = 0, to = Math.PI * 2, bold = false) {
    const pts: V[] = []
    for (let k = 0; k <= n; k++) {
      const a = from + ((to - from) * k) / n
      pts.push(planar(c, Math.cos(a) * r, Math.sin(a) * r, plane))
    }
    this.poly(pts, false, bold)
  }

  /** Cylinder or cone standing on `base`, along `axis`. Rims are drawn; sides are view-dependent silhouettes. */
  cyl(base: V, r: number, h: number, o: { r1?: number; axis?: Axis; fill?: boolean; rims?: boolean; n?: number; bold?: boolean } = {}) {
    const r1 = o.r1 ?? r
    const local = new THREE.Matrix4().makeTranslation(...base)
    if (o.axis === 'x') local.multiply(new THREE.Matrix4().makeRotationZ(-Math.PI / 2))
    if (o.axis === 'z') local.multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2))
    const m = this.m.clone().multiply(local)
    if (o.rims !== false) {
      this.stack.push(m)
      if (r > 0.001) this.circle([0, 0, 0], r, 'xz', o.n ?? 28, 0, Math.PI * 2, o.bold)
      if (r1 > 0.001) this.circle([0, h, 0], r1, 'xz', o.n ?? 28, 0, Math.PI * 2, o.bold)
      this.stack.pop()
    }
    this.p.rounds.push({ kind: 'cyl', m, r0: r, r1, h, key: this.key })
    if (o.fill !== false) {
      const g = new THREE.CylinderGeometry(r1, r, h, 24)
      g.translate(0, h / 2, 0)
      g.applyMatrix4(m)
      this.p.fills.push(g)
    }
  }

  /** Ellipsoid with radii s, silhouette only. */
  ball(c: V, s: V, o: { fill?: boolean } = {}) {
    const local = new THREE.Matrix4().makeTranslation(...c).multiply(new THREE.Matrix4().makeScale(...s))
    const m = this.m.clone().multiply(local)
    this.p.rounds.push({ kind: 'ball', m, key: this.key })
    if (o.fill !== false) {
      const g = new THREE.SphereGeometry(1, 24, 16)
      g.applyMatrix4(m)
      this.p.fills.push(g)
    }
  }

  /** Fill without lines, to hide what is behind (screens, panels). */
  solid(c: V, s: V) {
    this.box(c, s, { edges: false })
  }

  /** Text on a plane facing local +z, centered at c. */
  label(text: string, c: V, w: number, h: number, o: { size?: number; align?: CanvasTextAlign; ry?: number } = {}) {
    const m = this.m.clone().multiply(new THREE.Matrix4().makeTranslation(...c))
    if (o.ry) m.multiply(new THREE.Matrix4().makeRotationY(o.ry))
    this.p.labels.push({ text, m, w, h, key: this.key, size: o.size ?? 0.8, align: o.align ?? 'center' })
  }
}

function planar(c: V, a: number, b: number, plane: Plane): V {
  if (plane === 'xy') return [c[0] + a, c[1] + b, c[2]]
  if (plane === 'xz') return [c[0] + a, c[1], c[2] + b]
  return [c[0], c[1] + b, c[2] + a]
}

function rectPts(c: V, w: number, h: number, plane: Plane): V[] {
  return [
    planar(c, -w / 2, -h / 2, plane),
    planar(c, w / 2, -h / 2, plane),
    planar(c, w / 2, h / 2, plane),
    planar(c, -w / 2, h / 2, plane),
  ]
}
