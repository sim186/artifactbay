import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'
import { api, ApiError, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  logout: () => Promise<void>
}

const Ctx = createContext<AuthState>({ user: null, loading: true, logout: async () => {} })

export function useAuth() {
  return useContext(Ctx)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 60_000,
  })

  async function logout() {
    await api.logout()
    qc.clear()
    window.location.reload()
  }

  return (
    <Ctx.Provider value={{ user: data ?? null, loading: isLoading, logout }}>
      {children}
    </Ctx.Provider>
  )
}
