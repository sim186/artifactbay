import { useQuery } from '@tanstack/react-query'
import { marked } from 'marked'
import { useRef, useState } from 'react'
import type { ArtifactOut } from '../api'
import { api } from '../api'
import { useTheme } from '../theme'

// Media types where a backdrop colour matters (transparent SVG/PNG, PDF).
const MEDIA = new Set(['svg', 'png', 'pdf'])

// Which types have a rendered "preview" vs a raw "source" view.
const HAS_PREVIEW = new Set(['html', 'markdown', 'json', 'svg', 'png', 'pdf', 'conversation'])
const HAS_SOURCE = new Set(['html', 'markdown', 'json', 'svg', 'text', 'conversation'])
const TEXTUAL = new Set(['html', 'markdown', 'json', 'svg', 'text', 'conversation'])

interface ChatMessage {
  role?: string
  content?: string
  ts?: string | number
}

function Transcript({ text }: { text: string }) {
  let messages: ChatMessage[] = []
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) messages = parsed
  } catch {
    /* fall through to empty */
  }
  if (messages.length === 0) {
    return <pre className="h-full w-full overflow-auto p-4 font-mono text-xs text-text-dim">{text}</pre>
  }
  return (
    <div className="h-full w-full space-y-3 overflow-auto bg-bg p-5">
      {messages.map((m, i) => {
        const user = (m.role ?? '').toLowerCase() === 'user'
        return (
          <div key={i} className={`flex ${user ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${
                user ? 'bg-accent text-white' : 'bg-surface-2 text-text'
              }`}
            >
              <div className="mb-0.5 text-[10px] uppercase tracking-wide opacity-60">{m.role}</div>
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Readable document chrome for markdown rendered inside a sandboxed iframe.
// We render this HTML ourselves, so it follows the app theme (the raw markdown
// bytes stay untouched — only our presentation changes).
function mdDoc(html: string, theme: 'dark' | 'light'): string {
  const c = theme === 'dark'
    ? { bg: '#12151c', fg: '#e6e9ef', muted: '#9aa3b2', code: '#1d2230', border: '#232936', quote: '#9aa3b2' }
    : { bg: '#ffffff', fg: '#1a1a1a', muted: '#666', code: '#f3f3f3', border: '#e6e6e6', quote: '#666' }
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:system-ui,-apple-system,sans-serif;line-height:1.6;color:${c.fg};
      background:${c.bg};max-width:760px;margin:0 auto;padding:2rem 1.5rem}
    h1,h2,h3{line-height:1.25}h1{border-bottom:1px solid ${c.border};padding-bottom:.3em}
    code{background:${c.code};padding:.15em .4em;border-radius:4px;font-size:.9em}
    pre{background:${c.code};padding:1rem;border-radius:8px;overflow:auto}
    pre code{background:none;padding:0}
    blockquote{border-left:3px solid ${c.border};margin:0;padding-left:1rem;color:${c.quote}}
    table{border-collapse:collapse}td,th{border:1px solid ${c.border};padding:6px 12px}
    a{color:#818cf8}img{max-width:100%}
  </style></head><body>${html}</body></html>`
}

export function ArtifactViewer({ artifact, token }: { artifact: ArtifactOut; token?: string }) {
  const { type, id, allow_scripts } = artifact
  const hasPreview = HAS_PREVIEW.has(type)
  const hasSource = HAS_SOURCE.has(type)
  const [mode, setMode] = useState<'preview' | 'source'>(hasPreview ? 'preview' : 'source')
  const [backdrop, setBackdrop] = useState<'dark' | 'light'>('dark')
  const containerRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  const showBackdrop = MEDIA.has(type) && mode === 'preview'

  // Fetch raw text only for textual types (needed for source view + md/json/svg preview).
  const needText = TEXTUAL.has(type)
  const { data: text } = useQuery({
    queryKey: ['artifact-text', id, token],
    queryFn: () => fetch(api.artifactRaw(id, token)).then((r) => r.text()),
    enabled: needText,
  })

  function goFullscreen() {
    containerRef.current?.requestFullscreen?.().catch(() => {})
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border-soft px-3 py-1.5">
        <span className="truncate font-mono text-xs text-text-faint">{artifact.name}</span>
        {hasPreview && hasSource && (
          <div className="ml-2 flex overflow-hidden rounded-md border border-border text-xs">
            {(['preview', 'source'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2 py-0.5 ${
                  mode === m ? 'bg-accent text-white' : 'text-text-dim hover:bg-surface-2'
                }`}
              >
                {m === 'preview' ? 'Preview' : 'Source'}
              </button>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {showBackdrop && (
            <button
              onClick={() => setBackdrop((b) => (b === 'dark' ? 'light' : 'dark'))}
              title="Toggle backdrop (light/dark) behind the artifact"
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-surface-2"
            >
              ◐ Backdrop
            </button>
          )}
          <button
            onClick={goFullscreen}
            title="Fullscreen (Esc to exit)"
            className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-surface-2"
          >
            ⛶ Fullscreen
          </button>
          <a
            href={api.artifactRaw(id, token)}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-surface-2"
          >
            Open raw ↗
          </a>
        </div>
      </div>

      {/* Fullscreen target: the rendered artifact fills the whole screen here. */}
      <div ref={containerRef} className="relative min-h-0 flex-1 bg-bg">
        <Content
          artifact={artifact}
          mode={mode}
          text={text}
          allowScripts={allow_scripts}
          theme={theme}
          backdrop={backdrop}
          token={token}
        />
      </div>
    </div>
  )
}

function Content({
  artifact,
  mode,
  text,
  allowScripts,
  theme,
  backdrop,
  token,
}: {
  artifact: ArtifactOut
  mode: 'preview' | 'source'
  text: string | undefined
  allowScripts: boolean
  theme: 'dark' | 'light'
  backdrop: 'dark' | 'light'
  token?: string
}) {
  const { type, id, name } = artifact
  // Backdrop behind media is the user's choice; independent of the app theme.
  const mediaBg = backdrop === 'light' ? '#ffffff' : '#0d0f14'

  if (mode === 'source') {
    return (
      <pre className="h-full w-full overflow-auto bg-surface-2 p-4 font-mono text-xs leading-relaxed text-text-dim">
        {text ?? 'Loading…'}
      </pre>
    )
  }

  if (type === 'html') {
    return (
      <iframe
        title={name}
        src={api.artifactView(id, token)}
        sandbox={allowScripts ? 'allow-scripts' : ''}
        className="h-full w-full border-0 bg-white"
      />
    )
  }

  if (type === 'markdown') {
    const html = marked.parse(text ?? '', { async: false }) as string
    return (
      <iframe
        title={name}
        // Sandboxed, no allow-scripts → any HTML/script in the markdown is inert.
        srcDoc={mdDoc(html, theme)}
        sandbox=""
        className="h-full w-full border-0 bg-white"
      />
    )
  }

  if (type === 'conversation') {
    return <Transcript text={text ?? ''} />
  }

  if (type === 'json') {
    let pretty = text ?? ''
    try {
      pretty = JSON.stringify(JSON.parse(text ?? ''), null, 2)
    } catch {
      /* keep raw */
    }
    return (
      <pre className="h-full w-full overflow-auto bg-surface-2 p-4 font-mono text-xs text-text-dim">
        {pretty}
      </pre>
    )
  }

  if (type === 'svg' || type === 'png') {
    return (
      <div className="flex h-full w-full items-center justify-center p-4" style={{ background: mediaBg }}>
        <img src={api.artifactRaw(id, token)} alt={name} className="max-h-full max-w-full" />
      </div>
    )
  }

  if (type === 'pdf') {
    return (
      <div className="h-full w-full" style={{ background: mediaBg }}>
        <iframe title={name} src={api.artifactRaw(id, token)} className="h-full w-full border-0" />
      </div>
    )
  }

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-text-dim">
      <p className="text-sm">No inline preview for .{type}</p>
      <a
        href={api.artifactRaw(id, token)}
        target="_blank"
        rel="noreferrer"
        className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface-2"
      >
        Open raw ↗
      </a>
    </div>
  )
}
