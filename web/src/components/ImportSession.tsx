import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import { api, type ArtifactIn, type ArtifactType, type SessionIn } from '../api'
import { formatBytes } from '../lib/agent'

// Extension → artifact type. Mirrors integrations/artifactbay_cli.py EXT_TYPE.
const EXT_TYPE: Record<string, ArtifactType> = {
  html: 'html', htm: 'html', md: 'markdown', markdown: 'markdown',
  json: 'json', svg: 'svg', png: 'png', pdf: 'pdf', zip: 'zip', txt: 'text', log: 'text',
}
const BINARY = new Set<ArtifactType>(['png', 'pdf', 'zip'])
const TYPES: ArtifactType[] = ['html', 'markdown', 'json', 'svg', 'png', 'pdf', 'zip', 'text', 'conversation']

function typeForName(name: string): ArtifactType {
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
  return EXT_TYPE[ext] ?? 'text'
}

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(bin)
}

interface Staged {
  file: File
  name: string
  type: ArtifactType
  allow_scripts: boolean
}

async function toArtifact(s: Staged): Promise<ArtifactIn> {
  if (BINARY.has(s.type)) {
    return { name: s.name, type: s.type, encoding: 'base64', content: toBase64(await s.file.arrayBuffer()), allow_scripts: s.allow_scripts }
  }
  return { name: s.name, type: s.type, encoding: 'utf8', content: await s.file.text(), allow_scripts: s.allow_scripts }
}

export function ImportSession({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const [name, setName] = useState('')
  const [agent, setAgent] = useState('manual')
  const [model, setModel] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [visibility, setVisibility] = useState('private')
  const [files, setFiles] = useState<Staged[]>([])
  const [dragging, setDragging] = useState(false)

  function addFiles(list: FileList | null) {
    if (!list) return
    const next = Array.from(list).map<Staged>((file) => ({
      file, name: file.name, type: typeForName(file.name), allow_scripts: false,
    }))
    setFiles((prev) => [...prev, ...next])
  }

  const create = useMutation({
    mutationFn: async (): Promise<{ id: string }> => {
      const artifacts = await Promise.all(files.map(toArtifact))
      const payload: SessionIn = {
        name: name.trim(),
        agent: agent.trim() || 'manual',
        model: model.trim() || null,
        description: description.trim() || null,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        visibility,
        artifacts,
      }
      return api.createSession(payload)
    },
    onSuccess: ({ id }) => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      onClose()
      navigate({ to: '/s/$sessionId', params: { sessionId: id } })
    },
  })

  const canSubmit = name.trim().length > 0 && files.length > 0 && !create.isPending

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-3 border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Import session</h2>
          <button onClick={onClose} className="ml-auto text-text-faint hover:text-text">✕</button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <p className="text-xs leading-relaxed text-text-faint">
            Upload artifacts by hand — no agent integration or local paths needed. Files are stored
            in ArtifactBay; nothing is read from your disk afterwards.
          </p>

          <div className="space-y-3">
            <Field label="Name *">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="What is this session?"
                className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Agent">
                <input value={agent} onChange={(e) => setAgent(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none" />
              </Field>
              <Field label="Model">
                <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="optional"
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none" />
              </Field>
            </div>
            <Field label="Description">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="optional"
                className="w-full resize-none rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tags">
                <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="comma, separated"
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none" />
              </Field>
              <Field label="Visibility">
                <select value={visibility} onChange={(e) => setVisibility(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none">
                  <option value="private">Private</option>
                  <option value="public">Public</option>
                </select>
              </Field>
            </div>
          </div>

          {/* drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-lg border border-dashed px-4 py-6 text-center text-sm ${
              dragging ? 'border-accent bg-accent-soft text-text' : 'border-border text-text-faint hover:bg-surface-2'
            }`}
          >
            Drop files here, or click to browse
            <input ref={inputRef} type="file" multiple className="hidden" onChange={(e) => addFiles(e.target.files)} />
          </div>

          {files.length > 0 && (
            <div className="space-y-1.5">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-2 rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs">
                  <span className="min-w-0 flex-1 truncate">{f.name}</span>
                  <span className="text-text-faint">{formatBytes(f.file.size)}</span>
                  <select
                    value={f.type}
                    onChange={(e) => setFiles((prev) => prev.map((p, j) => j === i ? { ...p, type: e.target.value as ArtifactType } : p))}
                    className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[11px] text-text-dim focus:border-accent focus:outline-none"
                  >
                    {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                  {f.type === 'html' && (
                    <label className="flex items-center gap-1 text-[11px] text-text-faint" title="Allow scripts in the sandboxed iframe">
                      <input type="checkbox" checked={f.allow_scripts}
                        onChange={(e) => setFiles((prev) => prev.map((p, j) => j === i ? { ...p, allow_scripts: e.target.checked } : p))} />
                      js
                    </label>
                  )}
                  <button onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))} className="text-text-faint hover:text-red-400">✕</button>
                </div>
              ))}
            </div>
          )}

          {create.isError && (
            <p className="text-xs text-red-400">{(create.error as Error).message}</p>
          )}
        </div>

        <footer className="flex items-center gap-2 border-t border-border px-5 py-3">
          <span className="text-xs text-text-faint">{files.length} file{files.length === 1 ? '' : 's'}</span>
          <button onClick={onClose} className="ml-auto rounded-md border border-border px-3 py-1.5 text-xs text-text-dim hover:bg-surface-2 hover:text-text">Cancel</button>
          <button
            onClick={() => create.mutate()}
            disabled={!canSubmit}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {create.isPending ? 'Importing…' : 'Import'}
          </button>
        </footer>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-text-faint">{label}</span>
      {children}
    </label>
  )
}
