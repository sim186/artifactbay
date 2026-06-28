import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

export function Settings() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [freshToken, setFreshToken] = useState<string | null>(null)

  const { data: keys } = useQuery({ queryKey: ['keys'], queryFn: api.keys })
  const create = useMutation({
    mutationFn: () => api.createKey(label || 'api key'),
    onSuccess: (k) => {
      setFreshToken(k.token)
      setLabel('')
      qc.invalidateQueries({ queryKey: ['keys'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeKey(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['keys'] }),
  })

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <Link to="/" className="text-sm text-text-dim hover:text-text">← Back</Link>
      <h1 className="mt-3 text-xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-text-dim">Signed in as {user?.username} ({user?.role}).</p>

      <section className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-faint">API keys</h2>
        <p className="mt-1 text-xs text-text-faint">
          Agents authenticate with these. The token is shown once at creation — store it safely.
        </p>

        <div className="mt-3 flex gap-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label (e.g. laptop, ci)"
            className="flex-1 rounded-md border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            Create key
          </button>
        </div>

        {freshToken && (
          <div className="mt-3 rounded-lg border border-accent/40 bg-accent-soft p-3">
            <p className="text-xs text-text-dim">New token — copy it now, it won't be shown again:</p>
            <code className="mt-1 block break-all font-mono text-sm text-text">{freshToken}</code>
            <button
              onClick={() => navigator.clipboard?.writeText(freshToken)}
              className="mt-2 rounded border border-border px-2 py-0.5 text-xs hover:bg-surface-2"
            >
              Copy
            </button>
          </div>
        )}

        <div className="mt-4 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-xs text-text-faint">
              <tr>
                <th className="px-3 py-2">Key</th>
                <th className="px-3 py-2">Label</th>
                <th className="px-3 py-2">Scope</th>
                <th className="px-3 py-2">Last used</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {keys?.map((k) => (
                <tr key={k.id} className="border-t border-border-soft">
                  <td className="px-3 py-2 font-mono text-xs text-text-dim">{k.prefix}…</td>
                  <td className="px-3 py-2 text-text-dim">{k.label || '—'}</td>
                  <td className="px-3 py-2 text-text-faint">{k.scope}</td>
                  <td className="px-3 py-2 text-text-faint">
                    {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {k.revoked ? (
                      <span className="text-xs text-text-faint">revoked</span>
                    ) : (
                      <button
                        onClick={() => revoke.mutate(k.id)}
                        className="text-xs text-text-faint hover:text-red-400"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {keys?.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-4 text-center text-xs text-text-faint">No keys yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
