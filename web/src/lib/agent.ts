// Agent visual identity. Each agent gets a stable color + short label.
const MAP: Record<string, { label: string; color: string }> = {
  'claude-code': { label: 'Claude Code', color: 'var(--color-agent-claude)' },
  codex: { label: 'Codex', color: 'var(--color-agent-codex)' },
  'codex-cli': { label: 'Codex CLI', color: 'var(--color-agent-codex)' },
  opencode: { label: 'OpenCode', color: 'var(--color-agent-opencode)' },
  cursor: { label: 'Cursor', color: 'var(--color-agent-cursor)' },
  aider: { label: 'Aider', color: 'var(--color-agent-aider)' },
  manual: { label: 'Manual', color: 'var(--color-text-dim)' },
}

export function agentMeta(agent: string): { label: string; color: string } {
  return MAP[agent] ?? { label: agent, color: 'var(--color-text-dim)' }
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const s = Math.round((Date.now() - then) / 1000)
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  return `${d}d ago`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
