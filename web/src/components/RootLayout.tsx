import { Outlet } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'

export function RootLayout() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-text">
      {/* Integrated Sidebar */}
      <div
        className={`shrink-0 overflow-hidden transition-all duration-200 ease-in-out ${
          sidebarOpen ? 'w-64' : 'w-0'
        }`}
      >
        <Sidebar
          onOpenSearch={() => setPaletteOpen(true)}
          onClose={() => setSidebarOpen(false)}
        />
      </div>

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Top bar with sidebar toggle */}
        {!sidebarOpen && (
          <div className="flex shrink-0 items-center px-3 py-2">
            <button
              onClick={() => setSidebarOpen(true)}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-text hover:bg-surface-2 focus:outline-none cursor-pointer"
              title="Open Sidebar"
            >
              ☰
            </button>
          </div>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
