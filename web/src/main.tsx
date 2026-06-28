import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AuthProvider, useAuth } from './auth'
import { router } from './router'
import { Login } from './routes/Login'
import { applyThemeAttr, readTheme, ThemeProvider } from './theme'

applyThemeAttr(readTheme()) // set before first paint, no flash

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1 } },
})

function AppGate() {
  const { user, loading } = useAuth()
  if (loading)
    return <div className="flex h-screen items-center justify-center bg-bg text-text-faint">Loading…</div>
  if (!user) return <Login />
  return <RouterProvider router={router} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppGate />
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
