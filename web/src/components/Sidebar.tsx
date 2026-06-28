import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { api, type SessionSummary } from '../api'
import { useAuth } from '../auth'
import { agentMeta } from '../lib/agent'
import { STATIC_COLLECTIONS } from '../lib/collections'
import { useTheme } from '../theme'
import { FoundryMark } from './Logo'

function topTags(sessions: SessionSummary[], n = 6): string[] {
  const counts = new Map<string, number>()
  for (const s of sessions) for (const t of s.tags) counts.set(t, (counts.get(t) ?? 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, n).map(([t]) => t)
}

function groupByAgent(sessions: SessionSummary[]): [string, SessionSummary[]][] {
  const m = new Map<string, SessionSummary[]>()
  for (const s of sessions) {
    const arr = m.get(s.agent) ?? []
    arr.push(s)
    m.set(s.agent, arr)
  }
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

export function Sidebar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.list(),
    refetchInterval: 10_000,
  })
  const params = useParams({ strict: false }) as { sessionId?: string }
  const sessions = data?.sessions ?? []
  const groups = groupByAgent(sessions)
  const tags = topTags(sessions)
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const qc = useQueryClient()
  const { data: collections } = useQuery({ queryKey: ['collections'], queryFn: api.collections })
  const delCollection = useMutation({
    mutationFn: (id: string) => api.deleteCollection(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collections'] }),
  })

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between px-4 py-3">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <FoundryMark size={22} />
          Foundry
        </Link>
        <button
          onClick={onOpenSearch}
          className="rounded-md border border-border px-1.5 py-0.5 font-mono text-[11px] text-text-faint hover:text-text-dim"
          title="Search (⌘K)"
        >
          ⌘K
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {/* Collections — saved queries */}
        <div className="mb-3">
          <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-faint">
            Collections
          </div>
          {STATIC_COLLECTIONS.map((c) => (
            <Link
              key={c.id}
              to="/"
              search={c.search}
              className="block rounded-md px-2 py-1 text-sm text-text-dim hover:bg-surface-2 hover:text-text"
            >
              {c.label}
            </Link>
          ))}
          {/* user-saved collections (server) */}
          {collections?.map((c) => (
            <div key={c.id} className="group flex items-center">
              <Link
                to="/c/$collectionId"
                params={{ collectionId: c.id }}
                className="flex-1 truncate rounded-md px-2 py-1 text-sm text-text-dim hover:bg-surface-2 hover:text-text"
              >
                <span className="text-accent">◆</span> {c.name}
              </Link>
              <button
                onClick={() => delCollection.mutate(c.id)}
                title="Delete collection"
                className="hidden px-1.5 text-text-faint hover:text-red-400 group-hover:block"
              >
                ✕
              </button>
            </div>
          ))}
          {tags.map((t) => (
            <Link
              key={t}
              to="/"
              search={{ tag: t }}
              className="block truncate rounded-md px-2 py-1 text-sm text-text-dim hover:bg-surface-2 hover:text-text"
            >
              <span className="text-text-faint">#</span> {t}
            </Link>
          ))}
        </div>

        <div className="my-2 border-t border-border-soft" />
        <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-faint">
          Agents
        </div>

        {isLoading && <p className="px-2 py-1 text-xs text-text-faint">Loading…</p>}
        {error && (
          <p className="px-2 py-1 text-xs text-red-400">
            API offline — start the backend on :8000
          </p>
        )}
        {data && data.sessions.length === 0 && (
          <p className="px-2 py-2 text-xs text-text-faint">
            No sessions yet. Push one from an agent.
          </p>
        )}

        {groups.map(([agent, sessions]) => (
          <div key={agent} className="mb-3">
            <div className="flex items-center gap-2 px-2 py-1">
              <span className="size-2 rounded-full" style={{ background: agentMeta(agent).color }} />
              <span className="text-xs font-medium text-text-dim">{agentMeta(agent).label}</span>
              <span className="ml-auto text-[11px] text-text-faint">{sessions.length}</span>
            </div>
            {sessions.map((s) => {
              const active = s.id === params.sessionId
              return (
                <Link
                  key={s.id}
                  to="/s/$sessionId"
                  params={{ sessionId: s.id }}
                  className={`flex items-center gap-2 truncate rounded-md px-2 py-1 text-sm ${
                    active
                      ? 'bg-accent-soft text-text'
                      : 'text-text-dim hover:bg-surface-2 hover:text-text'
                  }`}
                >
                  <span className="truncate">{s.name}</span>
                  {s.favorite && <span className="text-[11px] text-amber-400">★</span>}
                </Link>
              )
            })}
          </div>
        ))}
      </nav>

      {/* user footer */}
      <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-xs">
        <span className="grid size-6 place-items-center rounded-full bg-accent-soft text-accent">
          {user?.username?.[0]?.toUpperCase() ?? '?'}
        </span>
        <span className="truncate text-text-dim">{user?.username}</span>
        {user?.role === 'admin' && <span className="text-[10px] text-text-faint">admin</span>}
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={toggle}
            className="rounded px-1.5 py-0.5 text-text-faint hover:text-text"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <Link to="/settings" className="rounded px-1.5 py-0.5 text-text-faint hover:text-text" title="Settings">
            ⚙
          </Link>
          <button onClick={logout} className="rounded px-1.5 py-0.5 text-text-faint hover:text-text" title="Log out">
            ⎋
          </button>
        </div>
      </div>
    </aside>
  )
}
