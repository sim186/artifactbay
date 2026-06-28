import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'

// Dropdown: pin the given session into a collection (or create one and pin it).
export function AddToCollection({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const { data: collections } = useQuery({ queryKey: ['collections'], queryFn: api.collections })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['collections'] })
    qc.invalidateQueries({ queryKey: ['collection'] })
  }
  const pin = useMutation({
    mutationFn: (collectionId: string) => api.pinSession(collectionId, sessionId),
    onSuccess: invalidate,
  })
  const createAndPin = useMutation({
    mutationFn: async (name: string) => {
      const c = await api.createCollection(name, {})
      return api.pinSession(c.id, sessionId)
    },
    onSuccess: invalidate,
  })

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border border-border px-2 py-1 text-xs text-text-dim hover:bg-surface-2 hover:text-text"
      >
        ◆ Add to collection
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-surface shadow-xl">
            <div className="max-h-60 overflow-y-auto py-1">
              {collections?.length === 0 && (
                <p className="px-3 py-2 text-xs text-text-faint">No collections yet.</p>
              )}
              {collections?.map((c) => {
                const inIt = c.pinned.includes(sessionId)
                return (
                  <button
                    key={c.id}
                    onClick={() => {
                      pin.mutate(c.id)
                      setOpen(false)
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-2"
                  >
                    <span className="text-accent">◆</span>
                    <span className="flex-1 truncate">{c.name}</span>
                    {inIt && <span className="text-xs text-text-faint">✓</span>}
                  </button>
                )
              })}
            </div>
            <button
              onClick={() => {
                const name = window.prompt('New collection name:')
                if (name) createAndPin.mutate(name)
                setOpen(false)
              }}
              className="block w-full border-t border-border-soft px-3 py-2 text-left text-xs text-accent hover:bg-surface-2"
            >
              ＋ New collection…
            </button>
          </div>
        </>
      )}
    </div>
  )
}
