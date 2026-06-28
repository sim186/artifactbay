import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { SessionSummary } from '../api'
import { relativeTime } from '../lib/agent'
import { AgentBadge } from './AgentBadge'
import { FavoriteButton } from './FavoriteButton'

// `corner` replaces the favorite star in the top-right (e.g. an unpin button on
// collection pages) so the two controls never overlap.
export function SessionCard({ s, corner }: { s: SessionSummary; corner?: ReactNode }) {
  return (
    <Link
      to="/s/$sessionId"
      params={{ sessionId: s.id }}
      className="group flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 transition hover:border-accent/60 hover:bg-surface-2"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium leading-snug group-hover:text-text">{s.name}</h3>
        {corner ?? <FavoriteButton id={s.id} favorite={s.favorite} />}
      </div>
      <div className="flex items-center gap-2">
        <AgentBadge agent={s.agent} />
        {s.status !== 'active' && (
          <span className="rounded px-1.5 py-0.5 text-[11px] text-text-faint ring-1 ring-border">
            {s.status}
          </span>
        )}
      </div>
      <div className="mt-auto flex items-center gap-3 font-mono text-[11px] text-text-faint">
        <span>{s.artifact_count} artifact{s.artifact_count === 1 ? '' : 's'}</span>
        <span>v{s.version}</span>
        {s.git.commit && <span className="truncate">{s.git.commit.slice(0, 7)}</span>}
        <span className="ml-auto">{relativeTime(s.updated_at)}</span>
      </div>
    </Link>
  )
}
