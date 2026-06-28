import { Outlet } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'

export function RootLayout() {
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
      if (e.key === 'Escape') setPaletteOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-text">
      <Sidebar onOpenSearch={() => setPaletteOpen(true)} />
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
