import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api'
import { AddToCollection } from '../components/AddToCollection'
import { AgentBadge } from '../components/AgentBadge'
import { ArtifactViewer } from '../components/ArtifactViewer'
import { FavoriteButton } from '../components/FavoriteButton'
import { ProvenancePanel } from '../components/ProvenancePanel'
import { formatBytes } from '../lib/agent'

export function SessionPage() {
  const { sessionId } = useParams({ from: '/s/$sessionId' })
  const [version, setVersion] = useState<number | undefined>(undefined)
  const [selected, setSelected] = useState(0)
  const [showInfo, setShowInfo] = useState(true)

  const { data: s, isLoading, error } = useQuery({
    queryKey: ['session', sessionId, version],
    queryFn: () => api.session(sessionId, version),
  })

  if (isLoading) return <p className="p-8 text-sm text-text-faint">Loading…</p>
  if (error || !s)
    return <p className="p-8 text-sm text-red-400">Session not found or API offline.</p>

  const artifact = s.artifacts[selected]
  const versions = Array.from({ length: s.version }, (_, i) => i + 1)

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <header className="flex items-center gap-3 border-b border-border px-6 py-3">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold">{s.name}</h1>
          <div className="mt-0.5 flex items-center gap-3 font-mono text-[11px] text-text-faint">
            {s.model && <span>{s.model}</span>}
            {s.git.commit && <span>{s.git.commit.slice(0, 7)}</span>}
            {s.git.branch && <span>{s.git.branch}</span>}
            <span>{s.status}</span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => setShowInfo((v) => !v)}
            className={`rounded-md border px-2.5 py-1 text-xs ${
              showInfo
                ? 'border-accent/40 bg-accent-soft text-text'
                : 'border-border text-text-dim hover:bg-surface-2 hover:text-text'
            }`}
            title="Toggle provenance panel"
          >
            ⓘ Details
          </button>
          <AddToCollection sessionId={s.id} />
          <FavoriteButton id={s.id} favorite={s.favorite} />
          <AgentBadge agent={s.agent} />
          {/* version timeline */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-faint">Version</span>
            <div className="relative flex items-center">
              <select
                value={s.requested_version}
                onChange={(e) => {
                  const val = Number(e.target.value)
                  setVersion(val)
                  setSelected(0)
                }}
                className="appearance-none rounded-md border border-border bg-surface pl-2.5 pr-7 py-1 font-mono text-xs text-text-dim hover:text-text hover:bg-surface-2 focus:border-accent focus:outline-none cursor-pointer"
              >
                {versions.map((v) => (
                  <option key={v} value={v}>
                    v{v} {v === s.version ? '(latest)' : ''}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[9px] text-text-faint">
                ▼
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* body: artifact list | preview */}
      <div className="flex min-h-0 flex-1">
        <div className="w-60 shrink-0 overflow-y-auto border-r border-border bg-surface p-2">
          {s.artifacts.length === 0 && (
            <p className="px-2 py-2 text-xs text-text-faint">No artifacts in this version.</p>
          )}
          {s.artifacts.map((a, i) => (
            <button
              key={a.id}
              onClick={() => setSelected(i)}
              className={`mb-1 flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left ${
                i === selected ? 'bg-accent-soft text-text' : 'text-text-dim hover:bg-surface-2'
              }`}
            >
              <span className="truncate text-sm">{a.name}</span>
              <span className="font-mono text-[10px] text-text-faint">
                {a.type} · {formatBytes(a.size_bytes)}
              </span>
            </button>
          ))}
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          {artifact ? (
            <ArtifactViewer key={artifact.id} artifact={artifact} />
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-text-faint">
              Select an artifact
            </div>
          )}
        </div>

        {showInfo && <ProvenancePanel s={s} />}
      </div>
    </div>
  )
}
