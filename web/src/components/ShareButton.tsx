import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Owner-only control to mint / copy / revoke a session's capability link.
// `shareUrl` is the currently active link (null = not shared yet).
export function ShareButton({ sessionId, shareUrl }: { sessionId: string; shareUrl: string | null }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['session', sessionId] })
  const share = useMutation({ mutationFn: () => api.shareSession(sessionId), onSuccess: invalidate })
  const rotate = useMutation({ mutationFn: () => api.shareSession(sessionId, true), onSuccess: invalidate })
  const revoke = useMutation({
    mutationFn: () => api.revokeShare(sessionId),
    onSuccess: () => {
      setOpen(false)
      invalidate()
    },
  })

  // Close the popover on outside click.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  async function copy() {
    if (!shareUrl) return
    await navigator.clipboard.writeText(shareUrl).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`rounded-md border px-2.5 py-1 text-xs ${
          shareUrl
            ? 'border-accent/40 bg-accent-soft text-text'
            : 'border-border text-text-dim hover:bg-surface-2 hover:text-text'
        }`}
        title="Share a public link to this session"
      >
        🔗 {shareUrl ? 'Shared' : 'Share'}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-border bg-surface p-3 shadow-lg">
          {shareUrl ? (
            <>
              <p className="mb-2 text-[11px] text-text-faint">
                Anyone with this link can view this session — no login required.
              </p>
              <div className="flex items-center gap-1.5">
                <input
                  readOnly
                  value={shareUrl}
                  onFocus={(e) => e.currentTarget.select()}
                  className="min-w-0 flex-1 rounded-md border border-border bg-bg px-2 py-1 font-mono text-[11px] text-text-dim"
                />
                <button
                  onClick={copy}
                  className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-2"
                >
                  {copied ? '✓' : 'Copy'}
                </button>
              </div>
              <div className="mt-2 flex items-center justify-between">
                <button
                  onClick={() => rotate.mutate()}
                  disabled={rotate.isPending}
                  className="text-[11px] text-text-faint hover:text-text"
                  title="Generate a new link and invalidate the old one"
                >
                  Rotate link
                </button>
                <button
                  onClick={() => revoke.mutate()}
                  disabled={revoke.isPending}
                  className="text-[11px] text-red-400 hover:text-red-300"
                >
                  Revoke
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="mb-2 text-[11px] text-text-faint">
                Create a secret link so anyone can view this session without an account.
              </p>
              <button
                onClick={() => share.mutate()}
                disabled={share.isPending}
                className="w-full rounded-md border border-accent/40 bg-accent-soft px-2 py-1.5 text-xs text-text hover:bg-accent/20"
              >
                {share.isPending ? 'Creating…' : 'Create share link'}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
