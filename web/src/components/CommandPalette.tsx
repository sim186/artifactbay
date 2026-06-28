import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { AgentBadge } from './AgentBadge'
import { Snippet } from './Snippet'

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['search', q],
    queryFn: () => api.list(q ? { q } : {}),
    enabled: open,
  })

  useEffect(() => {
    if (!open) setQ('')
  }, [open])

  if (!open) return null
  const results = data?.sessions ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[12vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search sessions & artifact text…"
          className="w-full bg-transparent px-4 py-3 text-sm outline-none placeholder:text-text-faint"
        />
        <div className="max-h-80 overflow-y-auto border-t border-border-soft">
          {results.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-text-faint">No matches</p>
          )}
          {results.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                navigate({ to: '/s/$sessionId', params: { sessionId: s.id } })
                onClose()
              }}
              className="flex w-full items-start gap-3 px-4 py-2 text-left hover:bg-surface-2"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{s.name}</div>
                {s.snippet && (
                  <Snippet text={s.snippet} className="mt-0.5 block truncate text-xs text-text-faint" />
                )}
              </div>
              <AgentBadge agent={s.agent} dot />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
