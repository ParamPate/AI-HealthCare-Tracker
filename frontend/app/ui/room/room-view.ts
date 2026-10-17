// Drives the full-screen room: the whole room, one corner at a time, and close-ups of a single
// object with a strip of its neighbours. The seated person breathes; WiFi waves run between the boards.
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js'
import { ANTENNA_TOP, buildRoom, CHEST, LINK_Z, pickable, RX_AT, RX_COLOR, TX_AT, TX_COLOR, ZONE_FOCUS } from './models'
import { paper, type Piece, type Theme } from './sketch'

export type Mode = 'room' | 'zone' | 'object'

export type Thumb = { id: string; name: string; x: number; y: number; w: number; h: number; active: boolean }

export type ViewState = {
  mode: Mode
  zone: number
  piece: { id: string; name: string } | null
  thumbs: Thumb[]
  hovering: boolean
}

/** What the person's breathing should follow: a rate, and whether they are breathing at all. */
export type Breathing = { rate: number; breathing: boolean }

type Shot = { pos: THREE.Vector3; target: THREE.Vector3 }

const FOV = 30
const FADED = 0.13
const ROOM_DIR = new THREE.Vector3(0.62, 0.86, 1).normalize()
const ZONE_DIR = new THREE.Vector3(0.5, 0.62, 1).normalize()
// looking down at about 62 degrees, so the gap between the boards' line and the chest shows
const FOCUS_DIR = new THREE.Vector3(0.42, 1.95, 1).normalize()
const OBJECT_DIR = new THREE.Vector3(0.42, 0.3, 1).normalize()

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

/**
 * Wave paths from TX to RX. Each bows out away from the person by `bow` meters at its middle;
 * breathing out pushes it `give` meters further, breathing in lets it settle back.
 */
const WAVES = [
  { bow: 0.07, give: 0.045, strength: 1 },
  { bow: 0.14, give: 0.065, strength: 0.78 },
  { bow: 0.21, give: 0.085, strength: 0.58 },
]
const PATH_SEGS = 60
const FRONTS = 6 // wavefronts travelling along each path at once
const FRONT_SEGS = 8
const RIPPLES = 3
const RIPPLE_SEGS = 10
const UP = new THREE.Vector3(0, 1, 0)
const pa = new THREE.Vector3()
const pb = new THREE.Vector3()
const tangent = new THREE.Vector3()
const tint = new THREE.Color()

/** Fat-line segments rewritten every frame. */
class LiveLines {
  readonly line: LineSegments2

  constructor(count: number, mat: LineMaterial) {
    const geo = new LineSegmentsGeometry()
    geo.setPositions(new Float32Array(count * 6))
    geo.setColors(new Float32Array(count * 6))
    this.line = new LineSegments2(geo, mat)
    this.line.frustumCulled = false
  }

  private data(name: 'instanceStart' | 'instanceColorStart') {
    return (this.line.geometry.getAttribute(name) as THREE.InterleavedBufferAttribute).data
  }

  /** Segment i from a to b, colored c. */
  set(i: number, a: THREE.Vector3, b: THREE.Vector3, c: THREE.Color) {
    ;(this.data('instanceStart').array as Float32Array).set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6)
    ;(this.data('instanceColorStart').array as Float32Array).set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6)
  }

  flush() {
    this.data('instanceStart').needsUpdate = true
    this.data('instanceColorStart').needsUpdate = true
  }
}

/**
 * The radio between the boards. A faint dashed line is the straight path; WiFi waves leave TX
 * (orange), bow out away from the person, and arrive at RX (blue). Each breath out pushes them a little.
 */
class RadioLink {
  readonly group = new THREE.Group()
  private paper = new THREE.Color(paper('light'))
  private txColor = new THREE.Color(TX_COLOR)
  private rxColor = new THREE.Color(RX_COLOR)
  private from = new THREE.Vector3(TX_AT[0], TX_AT[1] + ANTENNA_TOP * 0.9, TX_AT[2])
  private to = new THREE.Vector3(RX_AT[0], RX_AT[1] + ANTENNA_TOP * 0.9, RX_AT[2])
  private dir = this.to.clone().sub(this.from).normalize()
  private directMat = new LineMaterial({ color: '#8a8a90', linewidth: 1.1, transparent: true, depthWrite: false, dashed: true, dashSize: 0.03, gapSize: 0.03 })
  private pathMat = new LineMaterial({ linewidth: 1.6, vertexColors: true, transparent: true, depthWrite: false })
  private frontMat = new LineMaterial({ linewidth: 2.4, vertexColors: true, transparent: true, depthWrite: false })
  private paths = new LiveLines(WAVES.length * PATH_SEGS, this.pathMat)
  private fronts = new LiveLines(WAVES.length * FRONTS * FRONT_SEGS + 2 * RIPPLES * RIPPLE_SEGS, this.frontMat)

  constructor() {
    const geo = new LineSegmentsGeometry()
    geo.setPositions([...this.from.toArray(), ...this.to.toArray()])
    const direct = new LineSegments2(geo, this.directMat)
    direct.computeLineDistances()
    this.group.add(direct, this.paths.line, this.fronts.line)
  }

  setTheme(color: string) {
    this.paper.set(color)
  }

  /** Point s (0 at TX, 1 at RX) along wave k: out of the straight line, away from the person, back in. */
  private path(k: number, s: number, push: number, out: THREE.Vector3) {
    const shape = (1 - (2 * s - 1) ** 2) ** 2
    const { bow, give } = WAVES[k]
    return out.set(this.from.x + (this.to.x - this.from.x) * s, this.from.y, LINK_Z + (bow + give * push) * shape)
  }

  /** Orange at TX to blue at RX, faded toward the background by (1 - strength). */
  private color(s: number, strength: number) {
    return tint.copy(this.txColor).lerp(this.rxColor, s).lerp(this.paper, 1 - Math.max(0, Math.min(1, strength)))
  }

  /** An arc ")" of radius r facing along `facing`, its front at p. */
  private arc(i: number, p: THREE.Vector3, facing: THREE.Vector3, r: number, spread: number, segs: number, c: THREE.Color) {
    const center = pa.copy(p).addScaledVector(facing, -r)
    const at = (a: number, out: THREE.Vector3) => out.copy(center).addScaledVector(facing, Math.cos(a) * r).addScaledVector(UP, Math.sin(a) * r)
    const q0 = new THREE.Vector3()
    const q1 = new THREE.Vector3()
    for (let n = 0; n < segs; n++) {
      this.fronts.set(i++, at(-spread + (2 * spread * n) / segs, q0), at(-spread + (2 * spread * (n + 1)) / segs, q1), c)
    }
    return i
  }

  update(t: number, opacity: number, inhale: number, w: number, h: number) {
    for (const m of [this.directMat, this.pathMat, this.frontMat]) m.resolution.set(w, h)
    this.directMat.opacity = 0.5 * opacity
    this.pathMat.opacity = opacity
    this.frontMat.opacity = opacity
    // breathing out pushes the waves a little further from the person; breathing in lets them settle
    const push = 1 - inhale
    const ends = (s: number) => Math.min(1, s * 6, (1 - s) * 6)

    let i = 0
    let f = 0
    WAVES.forEach((spec, k) => {
      for (let n = 0; n < PATH_SEGS; n++) {
        const s = (n + 0.5) / PATH_SEGS
        this.paths.set(i++, this.path(k, n / PATH_SEGS, push, pa), this.path(k, (n + 1) / PATH_SEGS, push, pb), this.color(s, 0.75 * spec.strength * ends(s)))
      }
      for (let j = 0; j < FRONTS; j++) {
        const s = (t * 0.32 + j / FRONTS + k * 0.11) % 1
        this.path(k, s, push, pb)
        this.path(k, Math.min(1, s + 0.005), push, tangent).sub(this.path(k, Math.max(0, s - 0.005), push, pa)).normalize()
        f = this.arc(f, pb.clone(), tangent.clone(), 0.06, 0.9, FRONT_SEGS, this.color(s, spec.strength * ends(s)))
      }
    })
    this.paths.flush()

    // ")))" leaving the TX antenna, "(((" closing in on the RX antenna
    for (let j = 0; j < RIPPLES; j++) {
      const g = (t * 0.9 + j / RIPPLES) % 1
      const fade = Math.min(1, g * 4, (1 - g) * 4)
      f = this.arc(f, this.from.clone().addScaledVector(this.dir, 0.02 + 0.09 * g), this.dir, 0.03 + 0.06 * g, 0.75, RIPPLE_SEGS, this.color(0, fade))
      f = this.arc(f, this.to.clone().addScaledVector(this.dir, -0.02 - 0.09 * (1 - g)), this.dir.clone().negate(), 0.03 + 0.06 * (1 - g), 0.75, RIPPLE_SEGS, this.color(1, fade))
    }
    this.fronts.flush()
  }
}

export class RoomView {
  readonly pieces: Piece[]
  private shell: Piece
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(FOV, 1, 0.05, 200)
  private thumbCam = new THREE.PerspectiveCamera(FOV, 1, 0.05, 200)
  private controls: OrbitControls
  private link = new RadioLink()
  private raf = 0
  private clock = new THREE.Clock()
  private size = { w: 1, h: 1 }
  private tween: { from: Shot; to: Shot; t: number; dur: number } | null = null
  private targetOpacity = new Map<Piece, number>()
  private ray = new THREE.Raycaster()
  private pointer = new THREE.Vector2()
  private down: { x: number; y: number } | null = null
  private breath = { phase: 0, amp: 1, rate: 14, target: { rate: 14, breathing: true } as Breathing }
  /** 0 breathed out .. 1 breathed in */
  private inhale = 0.5
  state: ViewState
  /** Called when a click picks a corner or an object. */
  onPick?: () => void

  constructor(
    private canvas: HTMLCanvasElement,
    private onState: (s: ViewState) => void,
  ) {
    const room = buildRoom({ main: 1.7, sketch: 1.2, bold: 2.8 }, 'light')
    this.pieces = room.pieces
    this.shell = room.shell
    for (const p of this.pieces) this.scene.add(p.group)
    this.scene.add(this.shell.group, this.link.group)

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setClearColor(paper('light'))

    this.state = { mode: 'room', zone: 0, piece: null, thumbs: [], hovering: false }

    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.enablePan = false
    this.controls.rotateSpeed = 0.6
    this.controls.zoomSpeed = 0.8
    this.controls.minPolarAngle = 0.15
    this.setLimits()
    this.resize()
    const start = this.roomShot()
    start.pos.sub(start.target).multiplyScalar(1.35).add(start.target)
    start.pos.y += 4
    this.camera.position.copy(start.pos)
    this.controls.target.copy(start.target)
    this.setAllOpacity(1, true)
    canvas.addEventListener('pointerdown', this.onDown)
    canvas.addEventListener('pointerup', this.onUp)
    canvas.addEventListener('pointermove', this.onMove)
    this.loop()
  }

  // ---- shots ---------------------------------------------------------------

  private fit(center: THREE.Vector3, radius: number, dir: THREE.Vector3, aspect: number, margin = 1.1): Shot {
    const vfov = THREE.MathUtils.degToRad(FOV)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
    const dist = (radius * margin) / Math.sin(Math.min(vfov, hfov) / 2)
    return { pos: center.clone().addScaledVector(dir, dist), target: center.clone() }
  }

  private roomShot(): Shot {
    return this.fit(new THREE.Vector3(-0.2, 0.4, 0.2), 6.6, ROOM_DIR, this.size.w / this.size.h, 1.0)
  }

  private zoneShot(zone: number): Shot {
    const focus = ZONE_FOCUS[zone]
    const box = new THREE.Box3()
    for (const p of this.pieces) if (p.zone === zone && (!focus || focus.includes(p.id))) box.union(p.box)
    const s = box.getBoundingSphere(new THREE.Sphere())
    if (!focus) return this.fit(s.center, s.radius, ZONE_DIR, this.size.w / this.size.h, 1.22)
    // center between the chest and the waves bowing out in front of it
    const center = new THREE.Vector3(CHEST.x, 0.72, (CHEST.z + LINK_Z + WAVES[WAVES.length - 1].bow) / 2)
    return this.fit(center, 1.2, FOCUS_DIR, this.size.w / this.size.h, 1.0)
  }

  private objectDir(piece: Piece) {
    return OBJECT_DIR.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), piece.group.rotation.y)
  }

  private mainSize() {
    const { w, h } = this.size
    if (this.state.mode !== 'object') return { w, h }
    return { w: Math.round(w * (w > 760 ? 0.72 : 1)), h: w > 760 ? h : Math.round(h * 0.72) }
  }

  // ---- modes ---------------------------------------------------------------

  private zonePieces(zone: number) {
    return this.pieces.filter((p) => p.zone === zone && pickable(p))
  }

  private flyTo(to: Shot, dur = 1.1) {
    this.tween = { from: { pos: this.camera.position.clone(), target: this.controls.target.clone() }, to, t: 0, dur }
    this.controls.enabled = false
  }

  private setAllOpacity(o: number, now = false) {
    for (const p of this.pieces) {
      this.targetOpacity.set(p, o)
      if (now) p.setOpacity(o)
    }
  }

  showRoom() {
    this.leaveObject()
    this.state = { ...this.state, mode: 'room', piece: null, thumbs: [] }
    this.setAllOpacity(1)
    this.setLimits()
    this.flyTo(this.roomShot())
    this.emit({})
  }

  showZone(zone: number, dur = 1.1) {
    this.leaveObject()
    this.state = { ...this.state, mode: 'zone', zone, piece: null, thumbs: [] }
    for (const p of this.pieces) this.targetOpacity.set(p, p.zone === zone ? 1 : FADED)
    this.setLimits()
    this.flyTo(this.zoneShot(zone), dur)
    this.emit({})
  }

  focus(id: string) {
    const piece = this.pieces.find((p) => p.id === id)
    if (!piece) return
    this.state = { ...this.state, mode: 'object', zone: piece.zone, piece: { id: piece.id, name: piece.name } }
    this.shell.group.visible = false
    this.link.group.visible = false
    for (const p of this.pieces) {
      p.group.visible = p === piece
      p.setOpacity(p === piece ? 1 : 0)
      this.targetOpacity.set(p, p === piece ? 1 : 0)
    }
    const { w, h } = this.mainSize()
    const shot = this.fit(piece.center, piece.radius, this.objectDir(piece), w / h, 1.55)
    this.tween = null
    this.camera.position.copy(shot.pos)
    this.controls.target.copy(shot.target)
    this.controls.enabled = true
    this.controls.autoRotate = true
    this.controls.autoRotateSpeed = 0.7
    this.setLimits(piece)
    this.layoutThumbs()
    this.emit({})
  }

  /** In a close-up: show the previous or next object of the same corner. */
  step(delta: number) {
    if (this.state.mode !== 'object') return
    const list = this.zonePieces(this.state.zone)
    const i = list.findIndex((p) => p.id === this.state.piece?.id)
    this.focus(list[(i + delta + list.length) % list.length].id)
  }

  private leaveObject() {
    if (this.state.mode !== 'object') return
    this.shell.group.visible = true
    this.link.group.visible = true
    for (const p of this.pieces) {
      p.group.visible = true
      p.setOpacity(p.zone === this.state.zone ? 1 : 0)
    }
    this.controls.autoRotate = false
    const zone = this.zoneShot(this.state.zone)
    this.camera.position.copy(zone.pos).sub(zone.target).multiplyScalar(0.7).add(zone.target)
    this.controls.target.copy(zone.target)
  }

  private setLimits(piece?: Piece) {
    if (piece) {
      this.controls.minDistance = piece.radius * 1.4
      this.controls.maxDistance = piece.radius * 8
      this.controls.maxPolarAngle = Math.PI * 0.62
    } else {
      this.controls.minDistance = 1.2
      this.controls.maxDistance = 40
      this.controls.maxPolarAngle = 1.38
    }
  }

  /** Esc: object -> corner -> whole room. */
  back() {
    if (this.state.mode === 'object') this.showZone(this.state.zone, 0.9)
    else if (this.state.mode === 'zone') this.showRoom()
  }

  setTheme(theme: Theme) {
    this.renderer.setClearColor(paper(theme))
    this.link.setTheme(paper(theme))
    for (const p of [...this.pieces, this.shell]) p.setTheme(theme)
  }

  setBreathing(b: Breathing) {
    this.breath.target = b
  }

  private layoutThumbs() {
    if (this.state.mode !== 'object') return
    const list = this.zonePieces(this.state.zone)
    const { w, h } = this.size
    const main = this.mainSize()
    const side = w > 760
    const thumbs: Thumb[] = list.map((p, i) => {
      if (side) {
        const colW = w - main.w
        const area = h * 0.72
        const slot = area / list.length
        const size = Math.min(colW * 0.72, slot * 0.98, 210)
        return { id: p.id, name: p.name, x: main.w + colW / 2 - size / 2 + colW * -0.02, y: (h - area) / 2 + slot * i + (slot - size) / 2, w: size, h: size, active: p.id === this.state.piece?.id }
      }
      const area = w * 0.9
      const slot = area / list.length
      const size = Math.min(slot * 0.86, (h - main.h) * 0.6)
      return { id: p.id, name: p.name, x: (w - area) / 2 + slot * i + (slot - size) / 2, y: main.h + (h - main.h - size) / 2 - 20, w: size, h: size, active: p.id === this.state.piece?.id }
    })
    this.state = { ...this.state, thumbs }
  }

  // ---- input ---------------------------------------------------------------

  private onDown = (e: PointerEvent) => {
    this.down = { x: e.clientX, y: e.clientY }
  }

  private onUp = (e: PointerEvent) => {
    const d = this.down
    this.down = null
    if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5 || this.state.mode === 'object') return
    const hit = this.pick(e)
    if (!hit) return
    if (this.state.mode === 'zone' && hit.zone === this.state.zone) this.focus(hit.id)
    else this.showZone(hit.zone)
    this.onPick?.()
  }

  private onMove = (e: PointerEvent) => {
    if (this.down || this.state.mode === 'object') return
    const hovering = !!this.pick(e)
    if (hovering !== this.state.hovering) this.emit({ hovering })
  }

  private pick(e: PointerEvent): Piece | null {
    const rect = this.canvas.getBoundingClientRect()
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    this.ray.setFromCamera(this.pointer, this.camera)
    const meshes = this.pieces.filter((p) => pickable(p) && p.group.visible).flatMap((p) => p.pickMeshes())
    const hit = this.ray.intersectObjects(meshes, false)[0]
    return (hit?.object.userData.piece as Piece) ?? null
  }

  // ---- frame ---------------------------------------------------------------

  resize() {
    const parent = this.canvas.parentElement
    if (!parent) return
    const w = Math.max(1, parent.clientWidth)
    const h = Math.max(1, parent.clientHeight)
    if (w === this.size.w && h === this.size.h) return
    this.size = { w, h }
    this.renderer.setSize(w, h, false)
    if (this.state.mode === 'object') {
      this.layoutThumbs()
      this.emit({})
    }
  }

  private emit(patch: Partial<ViewState>) {
    this.state = { ...this.state, ...patch }
    this.onState(this.state)
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(0.05, this.clock.getDelta())
    this.resize()
    this.animateOpacity(dt)
    this.animateBreathing(dt)
    this.frame(dt)
  }

  private animateOpacity(dt: number) {
    const k = 1 - Math.exp(-dt * 9)
    for (const p of this.pieces) {
      const target = this.targetOpacity.get(p) ?? 1
      if (Math.abs(p.opacity - target) > 0.002) p.setOpacity(p.opacity + (target - p.opacity) * k)
      else if (p.opacity !== target) p.setOpacity(target)
    }
  }

  /** Advance the breathing phase at the current rate; during a pause the chest settles, breathed out. */
  private animateBreathing(dt: number) {
    const b = this.breath
    b.rate += (b.target.rate - b.rate) * (1 - Math.exp(-dt * 1.5))
    b.amp += ((b.target.breathing ? 1 : 0) - b.amp) * (1 - Math.exp(-dt * 2.5))
    b.phase += dt * Math.PI * 2 * (b.rate / 60)
    const value = b.amp * Math.sin(b.phase) - (1 - b.amp)
    this.inhale = (value + 1) / 2
    for (const p of this.pieces) {
      if (!p.animate) continue
      p.animate(value)
      p.group.updateMatrixWorld(true)
    }
  }

  private frame(dt: number) {
    const controls = this.controls
    if (this.tween) {
      const tw = this.tween
      tw.t = Math.min(1, tw.t + dt / tw.dur)
      const e = ease(tw.t)
      this.camera.position.lerpVectors(tw.from.pos, tw.to.pos, e)
      controls.target.lerpVectors(tw.from.target, tw.to.target, e)
      this.camera.lookAt(controls.target)
      if (tw.t >= 1) {
        this.tween = null
        controls.enabled = true
      }
    }
    if (!this.tween) controls.update(dt)

    const { w, h } = this.size
    const main = this.mainSize()
    this.camera.aspect = main.w / main.h
    this.camera.updateProjectionMatrix()

    const tx = this.pieces.find((p) => p.id === 'tx')
    this.link.update(this.clock.elapsedTime, tx?.opacity ?? 1, this.inhale, main.w, main.h)

    this.renderer.setScissorTest(true)
    this.renderer.setScissor(0, 0, w, h)
    this.renderer.setViewport(0, 0, w, h)
    this.renderer.clear()
    this.renderMain(main.w, main.h, h - main.h)

    if (this.state.mode === 'object') this.renderThumbs()
    this.renderer.setScissorTest(false)
  }

  private renderMain(w: number, h: number, y = 0) {
    this.renderer.setViewport(0, y, w, h)
    const visible = [...this.pieces, this.shell].filter((p) => p.group.visible)
    for (const p of visible) {
      p.setResolution(w, h)
      p.updateSilhouettes(this.camera.position)
    }
    this.renderer.render(this.scene, this.camera)
  }

  private renderThumbs() {
    const { h } = this.size
    const focused = this.state.piece?.id
    const saved = this.pieces.map((p) => [p, p.group.visible, p.opacity] as const)
    for (const t of this.state.thumbs) {
      const piece = this.pieces.find((p) => p.id === t.id)!
      for (const p of this.pieces) p.group.visible = p === piece
      piece.setOpacity(t.id === focused ? 1 : 0.32)
      const shot = this.fit(piece.center, piece.radius, this.objectDir(piece), 1, 1.0)
      this.thumbCam.position.copy(shot.pos)
      this.thumbCam.lookAt(shot.target)
      this.thumbCam.aspect = 1
      this.thumbCam.updateProjectionMatrix()
      const y = h - t.y - t.h
      this.renderer.setViewport(t.x, y, t.w, t.h)
      this.renderer.setScissor(t.x, y, t.w, t.h)
      piece.setResolution(t.w, t.h)
      piece.updateSilhouettes(this.thumbCam.position)
      this.renderer.render(this.scene, this.thumbCam)
    }
    for (const [p, vis, o] of saved) {
      p.group.visible = vis
      p.setOpacity(o)
    }
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    // The canvas (and its GL context) can be reused by the next view; don't leave label uploads' flags set.
    const gl = this.renderer.getContext()
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false)
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    this.canvas.removeEventListener('pointerdown', this.onDown)
    this.canvas.removeEventListener('pointerup', this.onUp)
    this.canvas.removeEventListener('pointermove', this.onMove)
    this.controls.dispose()
    this.scene.traverse((o) => {
      const mesh = o as THREE.Mesh
      mesh.geometry?.dispose()
      const mat = mesh.material as THREE.Material | undefined
      ;(mat as THREE.MeshBasicMaterial | undefined)?.map?.dispose()
      mat?.dispose()
    })
    this.renderer.dispose()
  }
}
