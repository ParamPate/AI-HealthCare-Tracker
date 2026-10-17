import Link from 'next/link'
import Gallery from './ui/gallery/gallery'
import RoomCard from './ui/room/room-card'

const PHONE_URL = (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws').replace(/^ws/, 'http').replace(/\/ws$/, '/phone')

function A({ href, children, quiet = false }: { href: string; children: React.ReactNode; quiet?: boolean }) {
  const cls = `underline decoration-[#d9d9d9] decoration-1 underline-offset-[4px] transition-colors hover:decoration-current ${
    quiet ? 'text-[#666]' : 'text-[#0a0a0a]'
  }`
  if (href.startsWith('/')) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    )
  }
  return (
    <a href={href} className={cls} target="_blank" rel="noreferrer">
      {children}
    </a>
  )
}

function Bio() {
  return (
    <div className="max-w-[420px] text-[15px] leading-[22px] tracking-[-0.003em] text-[#5a5a5e]">
      <h1 className="mb-[2px] font-[560] text-[#0a0a0a]">Waiting Room Monitor</h1>
      <p>
        A contactless breathing monitor, built at <A href="https://hackthevalley.io">Hack the Valley</A>.
      </p>
      <p className="mt-[21px]">
        Two Wi-Fi boards sit beside a chair. Each breath bends the signal between them just enough to be counted.
      </p>
      <p className="mt-[21px]">
        Runs on two <A href="https://www.espressif.com/en/products/socs/esp32">ESP32</A> boards,
        <br className="hidden sm:inline" /> Espressif&apos;s <A href="https://github.com/espressif/esp-csi">esp-csi</A>,{' '}
        <A href="https://www.python.org">Python</A> and Next.js.
      </p>
      <p className="mt-[19px] flex gap-[13px]">
        <A href="/monitor" quiet>
          Live monitor
        </A>
        <A href={PHONE_URL} quiet>
          Phone alarm
        </A>
        <A href="https://github.com/ParamPate/AI-HealthCare-Tracker" quiet>
          GitHub
        </A>
      </p>
    </div>
  )
}

export default function Page() {
  return (
    <div className="w-full bg-white font-body text-[#5a5a5e]">
      <div className="mx-auto grid max-w-[1772px] grid-cols-1 gap-x-[21px] px-4 sm:px-6 lg:grid-cols-3 lg:px-[clamp(24px,6.32vw,112px)]">
        <aside className="flex flex-col gap-10 pt-[52px] lg:sticky lg:top-0 lg:h-screen lg:justify-between lg:pb-[55px]">
          <Bio />
          <RoomCard />
        </aside>
        <main className="pb-[55px] pt-10 lg:col-span-2 lg:pt-[52px]">
          <Gallery />
        </main>
      </div>
    </div>
  )
}
