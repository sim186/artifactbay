import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api'
import { ArtifactBayMark } from '../components/Logo'

export function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => api.login(username, password),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  })

  const err = mutation.error
  const msg = err instanceof ApiError && err.status === 401 ? 'Invalid credentials' : err ? 'Login failed' : null

  return (
    <div className="flex h-screen items-center justify-center bg-bg text-text">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
        className="w-80 rounded-xl border border-border bg-surface p-6"
      >
        <div className="mb-1 flex items-center gap-2.5">
          <ArtifactBayMark size={32} />
          <span className="text-lg font-semibold tracking-tight">ArtifactBay</span>
        </div>
        <p className="mb-5 text-xs text-text-faint">The persistent home for AI agent artifacts — store, search, showcase.</p>

        <label className="mb-1 block text-xs text-text-dim">Username</label>
        <input
          autoFocus
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="mb-3 w-full rounded-md border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <label className="mb-1 block text-xs text-text-dim">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded-md border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
        />

        {msg && <p className="mb-3 text-xs text-red-400">{msg}</p>}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
