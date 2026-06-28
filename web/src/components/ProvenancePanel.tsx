import { useState } from 'react'
import type { SessionOut } from '../api'
import { AgentBadge } from './AgentBadge'
import { formatDateTime, relativeTime } from '../lib/agent'

// Turn a git remote (https or git@ SSH) into a browsable https URL, or null.
function repoWebUrl(repo: string | null): string | null {
  if (!repo) return null
  const u = repo.trim()
  const ssh = u.match(/^git@([^:]+):(.+?)(?:\.git)?$/)
  if (ssh) return `https://${ssh[1]}/${ssh[2]}`
  const https = u.replace(/\.git$/, '')
  return /^https?:\/\//.test(https) ? https : null
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-text-faint">{label}</span>
      <div className="text-sm text-text-dim">{children}</div>
    </div>
  )
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs text-text-dim">{children}</span>
}

function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(value).then(() => {
          setDone(true)
          setTimeout(() => setDone(false), 1200)
        })
      }}
      className="rounded px-1.5 py-0.5 text-[10px] text-text-faint hover:bg-surface-2 hover:text-text"
    >
      {done ? '✓ copied' : 'copy'}
    </button>
  )
}

export function ProvenancePanel({ s }: { s: SessionOut }) {
  const web = repoWebUrl(s.git.repository)
  const linkCls = 'text-accent hover:underline'

  return (
    <aside className="w-72 shrink-0 overflow-y-auto border-l border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-faint">Provenance</h2>
      </header>

      {s.description && (
        <Row label="Description">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-text">{s.description}</p>
        </Row>
      )}

      <div className="divide-y divide-border">
        <Row label="Agent">
          <AgentBadge agent={s.agent} />
        </Row>
        {s.model && <Row label="Model"><Mono>{s.model}</Mono></Row>}
        <Row label="Status">
          <span className="capitalize">{s.status}</span>
          <span className="text-text-faint"> · {s.visibility}</span>
        </Row>

        <Row label="Repository">
          {s.git.repository ? (
            web ? <a href={web} target="_blank" rel="noreferrer" className={linkCls}><Mono>{s.git.repository}</Mono></a>
                : <Mono>{s.git.repository}</Mono>
          ) : <span className="text-text-faint">—</span>}
        </Row>
        <Row label="Branch">
          {s.git.branch ? (
            web ? <a href={`${web}/tree/${s.git.branch}`} target="_blank" rel="noreferrer" className={linkCls}><Mono>{s.git.branch}</Mono></a>
                : <Mono>{s.git.branch}</Mono>
          ) : <span className="text-text-faint">—</span>}
        </Row>
        <Row label="Commit">
          {s.git.commit ? (
            web ? <a href={`${web}/commit/${s.git.commit}`} target="_blank" rel="noreferrer" className={linkCls}><Mono>{s.git.commit.slice(0, 12)}</Mono></a>
                : <Mono>{s.git.commit.slice(0, 12)}</Mono>
          ) : <span className="text-text-faint">—</span>}
        </Row>

        {s.tags.length > 0 && (
          <Row label="Tags">
            <div className="flex flex-wrap gap-1.5">
              {s.tags.map((t) => (
                <span key={t} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text-dim">#{t}</span>
              ))}
            </div>
          </Row>
        )}

        <Row label="Created">
          {formatDateTime(s.created_at)} <span className="text-text-faint">· {relativeTime(s.created_at)}</span>
        </Row>
        <Row label="Updated">
          {formatDateTime(s.updated_at)} <span className="text-text-faint">· {relativeTime(s.updated_at)}</span>
        </Row>

        <Row label="Session ID">
          <div className="flex items-center gap-1.5">
            <Mono>{s.id}</Mono>
            <CopyButton value={s.id} />
          </div>
        </Row>
      </div>
    </aside>
  )
}
