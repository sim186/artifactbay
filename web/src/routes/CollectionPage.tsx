import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { api } from '../api'
import { SessionCard } from '../components/SessionCard'

export function CollectionPage() {
  const { collectionId } = useParams({ from: '/c/$collectionId' })
  const qc = useQueryClient()

  const { data: collection } = useQuery({
    queryKey: ['collection', collectionId],
    queryFn: () => api.collection(collectionId),
  })
  const { data, isLoading } = useQuery({
    queryKey: ['collection-sessions', collectionId],
    queryFn: () => api.collectionSessions(collectionId),
  })
  const unpin = useMutation({
    mutationFn: (sid: string) => api.unpinSession(collectionId, sid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['collection', collectionId] })
      qc.invalidateQueries({ queryKey: ['collection-sessions', collectionId] })
      qc.invalidateQueries({ queryKey: ['collections'] })
    },
  })

  const sessions = data?.sessions ?? []
  const pinned = new Set(collection?.pinned ?? [])
  const q = collection?.query ?? {}
  const queryBits = [
    q.q && `“${q.q}”`,
    q.agent && `agent:${q.agent}`,
    q.tag && `#${q.tag}`,
    q.favorite && 'favorites',
  ].filter(Boolean)

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <header className="mb-8">
        <Link to="/" className="text-sm text-text-dim hover:text-text">← All sessions</Link>
        <h1 className="mt-2 flex items-center gap-2 text-xl font-semibold tracking-tight">
          <span className="text-accent">◆</span> {collection?.name ?? 'Collection'}
        </h1>
        <p className="mt-1 text-sm text-text-dim">
          {sessions.length} session{sessions.length === 1 ? '' : 's'}
          {queryBits.length > 0 && <> · query {queryBits.join(' ')}</>}
          {collection && collection.pinned.length > 0 && <> · {collection.pinned.length} pinned</>}
        </p>
      </header>

      {isLoading && <p className="text-sm text-text-faint">Loading…</p>}
      {data && sessions.length === 0 && (
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-sm text-text-dim">
          Empty collection. Pin sessions from their page, or give it a query.
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {sessions.map((s) => (
          <SessionCard
            key={s.id}
            s={s}
            corner={
              pinned.has(s.id) ? (
                <button
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    unpin.mutate(s.id)
                  }}
                  title="Unpin from collection"
                  className="shrink-0 rounded-md border border-border px-1.5 py-0.5 text-[11px] text-text-faint hover:text-red-400"
                >
                  📌 unpin
                </button>
              ) : undefined
            }
          />
        ))}
      </div>
    </div>
  )
}
