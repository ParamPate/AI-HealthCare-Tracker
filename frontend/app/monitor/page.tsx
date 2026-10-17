import type { Metadata } from 'next'
import ChairMonitor from '../ui/chair-monitor'

export const metadata: Metadata = {
  title: 'Waiting room monitor',
}

export default function Page() {
  return <ChairMonitor />
}
