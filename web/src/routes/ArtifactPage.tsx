import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api'
import { ArtifactViewer } from '../components/ArtifactViewer'
import { formatBytes } from '../lib/agent'

// The hero. Near-fullscreen artifact with minimal floating chrome.
export function ArtifactPage() {
  const { artifactId } = useParams({ from: '/a/$artifactId' })
  const [showMeta, setShowMeta] = useState(false)
  const { data: a, isLoading, error } = useQuery({
    queryKey: ['artifact', artifactId],
    queryFn: () => api.artifactMeta(artifactId),
  })

  if (isLoading) return <p className="p-8 text-sm text-text-faint">Loading…</p>
  if (error || !a)
    return <p className="p-8 text-sm text-red-400">Artifact not found or API offline.</p>

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-2">
        <Link
          to="/s/$sessionId"
          params={{ sessionId: a.session_id }}
          className="text-sm text-text-dim hover:text-text"
        >
          ← {a.session_name}
        </Link>
        <span className="font-mono text-xs text-text-faint">/ {a.name}</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowMeta((v) => !v)}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
          >
            {showMeta ? 'Hide' : 'Metadata'}
          </button>
          <a
            href={api.artifactRaw(a.id)}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
          >
            Open raw ↗
          </a>
          <a
            href={api.artifactRaw(a.id)}
            download={a.name}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
          >
            Download
          </a>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <ArtifactViewer artifact={a} />
        </div>
        {showMeta && (
          <aside className="w-72 shrink-0 overflow-y-auto border-l border-border bg-surface p-4 text-sm">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-faint">
              Metadata
            </h2>
            <dl className="space-y-2">
              <Row k="Name" v={a.name} />
              <Row k="Type" v={a.type} />
              <Row k="Size" v={formatBytes(a.size_bytes)} />
              <Row k="Version" v={`v${a.version}`} />
              <Row k="Scripts" v={a.allow_scripts ? 'allowed (sandboxed)' : 'blocked'} />
              <Row k="SHA-256" v={a.content_hash} mono wrap />
            </dl>
          </aside>
        )}
      </div>
    </div>
  )
}

function Row({ k, v, mono, wrap }: { k: string; v: string; mono?: boolean; wrap?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-text-faint">{k}</dt>
      <dd className={`${mono ? 'font-mono text-xs' : ''} ${wrap ? 'break-all' : 'truncate'} text-text-dim`}>
        {v}
      </dd>
    </div>
  )
}
