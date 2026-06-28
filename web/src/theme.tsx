import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'dark' | 'light'
const KEY = 'foundry.theme'

export function readTheme(): Theme {
  return (localStorage.getItem(KEY) as Theme) || 'dark'
}

// Apply before React renders to avoid a flash of the wrong theme.
export function applyThemeAttr(t: Theme) {
  document.documentElement.dataset.theme = t
}

interface ThemeState {
  theme: Theme
  toggle: () => void
}
const Ctx = createContext<ThemeState>({ theme: 'dark', toggle: () => {} })

export function useTheme() {
  return useContext(Ctx)
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readTheme)
  useEffect(() => {
    applyThemeAttr(theme)
    localStorage.setItem(KEY, theme)
  }, [theme])
  return (
    <Ctx.Provider value={{ theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }}>
      {children}
    </Ctx.Provider>
  )
}
