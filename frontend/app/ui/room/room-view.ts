// Drives one canvas: the small card (one zone at a time, crossfading) or the full explorer
// (whole room, zones, and close-ups of a single object with a strip of its neighbours).
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { buildRoom, pickable, ZONES } from './models'
import { paper, type Piece, type Theme } from './sketch'

export type Mode = 'card' | 'room' | 'zone' | 'object'

export type Thumb = { id: string; name: string; x: number; y: number; w: number; h: number; active: boolean }

export type ViewState = {
  mode: Mode
  zone: number
  piece: { id: string; name: string } | null
  thumbs: Thumb[]
  hovering: boolean
}

type Shot = { pos: THREE.Vector3; target: THREE.Vector3 }

const FOV = 30
const FADED = 0.13
const ROOM_DIR = new THREE.Vector3(0.62, 0.86, 1).normalize()
const ZONE_DIR = new THREE.Vector3(0.5, 0.62, 1).normalize()
const CARD_DIR = new THREE.Vector3(0.62, 0.56, 1).normalize()
const OBJECT_DIR = new THREE.Vector3(0.42, 0.3, 1).normalize()

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

export class RoomView {
  readonly pieces: Piece[]
  private shell: Piece
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(FOV, 1, 0.05, 200)
  private thumbCam = new THREE.PerspectiveCamera(FOV, 1, 0.05, 200)
  private controls?: OrbitControls
  private raf = 0
  private clock = new THREE.Clock()
  private size = { w: 1, h: 1 }
  private tween: { from: Shot; to: Shot; t: number; dur: number } | null = null
  private targetOpacity = new Map<Piece, number>()
  private cardFade: { phase: 'out' | 'in'; next: number } | null = null
  private ray = new THREE.Raycaster()
  private pointer = new THREE.Vector2()
  private down: { x: number; y: number } | null = null
  private active = true
  private theme: Theme = 'light'
  state: ViewState

  constructor(
    private canvas: HTMLCanvasElement,
    private variant: 'card' | 'explorer',
    private onState: (s: ViewState) => void,
    zone = 0,
  ) {
    const card = variant === 'card'
    const room = buildRoom(card ? { main: 1.35, sketch: 1, bold: 2.1 } : { main: 1.6, sketch: 1.15, bold: 2.6 }, this.theme)
    this.pieces = room.pieces
    this.shell = room.shell
    for (const p of this.pieces) this.scene.add(p.group)
    this.scene.add(this.shell.group)

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setClearColor(paper(this.theme))

    this.state = { mode: card ? 'card' : 'room', zone, piece: null, thumbs: [], hovering: false }

    if (card) {
      this.shell.group.visible = false
      this.applyCardZone(zone)
    } else {
      this.controls = new OrbitControls(this.camera, canvas)
      this.controls.enableDamping = true
      this.controls.dampingFactor = 0.08
      this.controls.enablePan = false
      this.controls.rotateSpeed = 0.6
      this.controls.zoomSpeed = 0.8
      this.controls.maxPolarAngle = 1.38
      this.controls.minPolarAngle = 0.15
      const start = this.roomShot()
      start.pos.sub(start.target).multiplyScalar(1.35).add(start.target)
      start.pos.y += 4
      this.camera.position.copy(start.pos)
      this.controls.target.copy(start.target)
      this.setAllOpacity(1, true)
      canvas.addEventListener('pointerdown', this.onDown)
      canvas.addEventListener('pointerup', this.onUp)
      canvas.addEventListener('pointermove', this.onMove)
    }
    this.resize()
    this.loop()
  }

  // ---- shots ---------------------------------------------------------------

  private fit(center: THREE.Vector3, radius: number, dir: THREE.Vector3, aspect: number, margin = 1.1): Shot {
    const vfov = THREE.MathUtils.degToRad(FOV)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
    const dist = (radius * margin) / Math.sin(Math.min(vfov, hfov) / 2)
    return { pos: center.clone().addScaledVector(dir, dist), target: center.clone() }
  }

  private zoneBounds(zone: number) {
    const box = new THREE.Box3()
    for (const p of this.pieces) if (p.zone === zone) box.union(p.box)
    const sphere = box.getBoundingSphere(new THREE.Sphere())
    return sphere
  }

  private roomShot(): Shot {
    return this.fit(new THREE.Vector3(-0.2, 0.4, 0.2), 6.6, ROOM_DIR, this.size.w / this.size.h, 1.0)
  }

  private zoneShot(zone: number): Shot {
    const s = this.zoneBounds(zone)
    return this.fit(s.center, s.radius, ZONE_DIR, this.size.w / this.size.h, 0.95)
  }

  private objectDir(piece: Piece) {
    return OBJECT_DIR.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), piece.group.rotation.y)
  }

  private mainSize() {
    const { w, h } = this.size
    if (this.state.mode !== 'object') return { w, h }
    return { w: Math.round(w * (w > 760 ? 0.72 : 1)), h: w > 760 ? h : Math.round(h * 0.72) }
  }

  // ---- card ----------------------------------------------------------------

  private applyCardZone(zone: number) {
    for (const p of this.pieces) {
      p.group.visible = p.zone === zone
      p.setOpacity(0)
      this.targetOpacity.set(p, p.zone === zone ? 1 : 0)
    }
    this.state = { ...this.state, zone }
    this.cardShot = null
  }

  private cardShot: Shot | null = null

  /** Card: step to the next or previous zone. */
  step(delta: number) {
    const next = (this.state.zone + delta + ZONES.length) % ZONES.length
    if (this.variant === 'card') {
      this.cardFade = { phase: 'out', next }
      for (const p of this.pieces) this.targetOpacity.set(p, 0)
      this.emit({ zone: next })
      return
    }
    if (this.state.mode === 'object') {
      const list = this.zonePieces(this.state.zone)
      const i = list.findIndex((p) => p.id === this.state.piece?.id)
      this.focus(list[(i + delta + list.length) % list.length].id)
    }
  }

  // ---- explorer ------------------------------------------------------------

  private zonePieces(zone: number) {
    return this.pieces.filter((p) => p.zone === zone && pickable(p))
  }

  private flyTo(to: Shot, dur = 1.1) {
    if (!this.controls) return
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
    if (!piece || !this.controls) return
    this.state = { ...this.state, mode: 'object', zone: piece.zone, piece: { id: piece.id, name: piece.name } }
    this.shell.group.visible = false
    for (const p of this.pieces) {
      p.group.visible = p === piece
      p.setOpacity(p === piece ? 1 : 0)
      this.targetOpacity.set(p, p === piece ? 1 : 0)
    }
    const { w, h } = this.mainSize()
    const shot = this.fit(piece.center, piece.radius, this.objectDir(piece), w / h, 1.25)
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

  private leaveObject() {
    if (this.state.mode !== 'object') return
    this.shell.group.visible = true
    for (const p of this.pieces) {
      p.group.visible = true
      p.setOpacity(p.zone === this.state.zone ? 1 : 0)
    }
    if (this.controls) this.controls.autoRotate = false
    const zone = this.zoneShot(this.state.zone)
    this.camera.position.copy(zone.pos).sub(zone.target).multiplyScalar(0.7).add(zone.target)
    this.controls?.target.copy(zone.target)
  }

  private setLimits(piece?: Piece) {
    if (!this.controls) return
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

  /** Esc: object -> zone -> room -> false (close). */
  back() {
    if (this.state.mode === 'object') this.showZone(this.state.zone, 0.9)
    else if (this.state.mode === 'zone') this.showRoom()
    else return false
    return true
  }

  setTheme(theme: Theme) {
    this.theme = theme
    this.renderer.setClearColor(paper(theme))
    for (const p of [...this.pieces, this.shell]) p.setTheme(theme)
  }

  setActive(active: boolean) {
    this.active = active
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
        const size = Math.min(colW * 0.62, slot * 0.86, 190)
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

  onPick?: () => void

  private onMove = (e: PointerEvent) => {
    if (this.down || this.state.mode === 'object') return
    const hovering = !!this.pick(e)
    if (hovering !== this.state.hovering) this.emit({ hovering })
  }

  private pick(e: PointerEvent): Piece | null {
    const rect = this.canvas.getBoundingClientRect()
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    this.ray.setFromCamera(this.pointer, this.camera)
    const fills = this.pieces.filter((p) => p.fill && pickable(p) && p.group.visible).map((p) => p.fill!)
    const hit = this.ray.intersectObjects(fills, false)[0]
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
    this.cardShot = null
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
    if (!this.active) return
    this.resize()
    this.animateOpacity(dt)
    if (this.variant === 'card') this.cardFrame()
    else this.explorerFrame(dt)
  }

  private animateOpacity(dt: number) {
    const k = 1 - Math.exp(-dt * 9)
    for (const p of this.pieces) {
      const target = this.targetOpacity.get(p) ?? 1
      if (Math.abs(p.opacity - target) > 0.002) p.setOpacity(p.opacity + (target - p.opacity) * k)
      else if (p.opacity !== target) p.setOpacity(target)
    }
  }

  private cardFrame() {
    const f = this.cardFade
    if (f?.phase === 'out' && this.pieces.every((p) => p.opacity < 0.03)) {
      this.applyCardZone(f.next)
      this.cardFade = { phase: 'in', next: f.next }
    } else if (f?.phase === 'in' && this.pieces.every((p) => Math.abs(p.opacity - (this.targetOpacity.get(p) ?? 0)) < 0.01)) {
      this.cardFade = null
    }
    if (!this.cardShot) {
      const s = this.zoneBounds(this.state.zone)
      this.cardShot = this.fit(s.center, s.radius, CARD_DIR, this.size.w / this.size.h, 0.92)
    }
    const shot = this.cardShot
    const sway = Math.sin(performance.now() / 2600) * 0.07
    const offset = shot.pos.clone().sub(shot.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), sway)
    this.camera.position.copy(shot.target).add(offset)
    this.camera.lookAt(shot.target)
    this.camera.aspect = this.size.w / this.size.h
    this.camera.updateProjectionMatrix()
    this.renderMain(this.size.w, this.size.h)
  }

  private explorerFrame(dt: number) {
    const controls = this.controls!
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

    this.renderer.setScissorTest(true)
    this.renderer.setViewport(0, h - main.h, main.w, main.h)
    this.renderer.setScissor(0, 0, w, h)
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
    this.canvas.removeEventListener('pointerdown', this.onDown)
    this.canvas.removeEventListener('pointerup', this.onUp)
    this.canvas.removeEventListener('pointermove', this.onMove)
    this.controls?.dispose()
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
