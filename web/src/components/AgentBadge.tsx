import { agentMeta } from '../lib/agent'

export function AgentBadge({ agent, dot = false }: { agent: string; dot?: boolean }) {
  const { label, color } = agentMeta(agent)
  if (dot) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-text-dim">
        <span className="size-2 rounded-full" style={{ background: color }} />
        {label}
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium"
      style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}
    >
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
}
