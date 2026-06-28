import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { api, type ListParams, type SessionSummary } from '../api'
import { ImportSession } from '../components/ImportSession'
import { SessionCard } from '../components/SessionCard'
import { agentMeta } from '../lib/agent'

function Rail({ title, sessions }: { title: string; sessions: SessionSummary[] }) {
  if (sessions.length === 0) return null
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-faint">
        {title}
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {sessions.map((s) => (
          <SessionCard key={s.id} s={s} />
        ))}
      </div>
    </section>
  )
}

export function Dashboard() {
  const search = useSearch({ from: '/' })
  const filtered = !!(search.agent || search.favorite || search.tag || search.q)
  const qc = useQueryClient()
  const [importing, setImporting] = useState(false)
  const saveCollection = useMutation({
    mutationFn: (name: string) => api.createCollection(name, search as ListParams),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collections'] }),
  })

  // Server-side filters (agent/favorite/q); tag is applied client-side (exact membership).
  const params: ListParams = { agent: search.agent, favorite: search.favorite, q: search.q }
  const { data, isLoading, error } = useQuery({
    queryKey: ['sessions', params],
    queryFn: () => api.list(params),
    refetchInterval: 10_000,
  })

  let all = data?.sessions ?? []
  if (search.tag) all = all.filter((s) => s.tags.includes(search.tag!))

  const favorites = all.filter((s) => s.favorite)

  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfWeek = new Date(startOfToday)
  startOfWeek.setDate(startOfToday.getDate() - 7)

  const today    = all.filter((s) => new Date(s.updated_at) >= startOfToday)
  const thisWeek = all.filter((s) => { const d = new Date(s.updated_at); return d >= startOfWeek && d < startOfToday })
  const earlier  = all.filter((s) => new Date(s.updated_at) < startOfWeek)

  const title = search.tag
    ? `#${search.tag}`
    : search.favorite
      ? 'Favorites'
      : search.agent
        ? agentMeta(search.agent).label
        : search.q
          ? `Search: “${search.q}”`
          : 'Sessions'

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <header className="mb-8 flex items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-text-dim">
            {filtered
              ? `${all.length} session${all.length === 1 ? '' : 's'}`
              : 'AI-generated development sessions and their artifacts.'}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {filtered && (
            <>
              <button
                onClick={() => {
                  const name = window.prompt('Save this view as a collection named:')
                  if (name) saveCollection.mutate(name)
                }}
                className="rounded-md border border-border px-3 py-1.5 text-xs text-text-dim hover:bg-surface-2 hover:text-text"
              >
                ◆ Save as collection
              </button>
              <Link
                to="/"
                search={{}}
                className="rounded-md border border-border px-3 py-1.5 text-xs text-text-dim hover:bg-surface-2 hover:text-text"
              >
                Clear filter ✕
              </Link>
            </>
          )}
          <button
            onClick={() => setImporting(true)}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
          >
            + Import
          </button>
        </div>
      </header>

      {importing && <ImportSession onClose={() => setImporting(false)} />}

      {isLoading && <p className="text-sm text-text-faint">Loading…</p>}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300">
          Can't reach the API. Start the backend:{' '}
          <code className="font-mono">uv run uvicorn app.main:app --reload</code>
        </div>
      )}

      {data && all.length === 0 && (
        <div className="rounded-xl border border-border bg-surface p-8 text-center">
          <p className="text-sm text-text-dim">No sessions match.</p>
        </div>
      )}

      {data && all.length > 0 && (
        <>
          {filtered ? (
            <Rail title="Results" sessions={all} />
          ) : (
            <>
              <Rail title="Favorites" sessions={favorites} />
              <Rail title="Today" sessions={today} />
              <Rail title="This week" sessions={thisWeek} />
              <Rail title="Earlier" sessions={earlier} />
            </>
          )}
        </>
      )}
    </div>
  )
}
