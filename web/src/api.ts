// Typed client for the ArtifactBay v0 API. Mirrors backend/app/schemas.py.
// Dev: requests go to same-origin /v0 (Vite proxies to :8000).

export type ArtifactType =
  | 'html' | 'markdown' | 'json' | 'svg' | 'png' | 'pdf' | 'zip' | 'text' | 'conversation'

export interface GitInfo {
  repository: string | null
  branch: string | null
  commit: string | null
}

export interface ArtifactOut {
  id: string
  name: string
  type: ArtifactType
  size_bytes: number
  allow_scripts: boolean
  url: string
}

export interface SessionOut {
  id: string
  name: string
  description: string | null
  status: string
  agent: string
  model: string | null
  project_id: string | null
  git: GitInfo
  tags: string[]
  favorite: boolean
  visibility: string
  version: number
  requested_version: number
  created_at: string
  updated_at: string
  artifacts: ArtifactOut[]
}

export interface ArtifactIn {
  name: string
  type: ArtifactType
  encoding: 'utf8' | 'base64'
  content: string
  allow_scripts?: boolean
}

export interface SessionIn {
  name: string
  description?: string | null
  agent: string
  model?: string | null
  project?: string | null
  git?: GitInfo | null
  tags?: string[]
  visibility?: string
  favorite?: boolean
  artifacts: ArtifactIn[]
}

export interface CreateSessionOut {
  id: string
  version: number
  url: string
  artifacts: { id: string; name: string; url: string }[]
}

export interface ArtifactDetail extends ArtifactOut {
  content_hash: string
  session_id: string
  session_name: string
  version: number
}

export interface SessionSummary {
  id: string
  name: string
  agent: string
  model: string | null
  status: string
  version: number
  favorite: boolean
  tags: string[]
  git: GitInfo
  artifact_count: number
  updated_at: string
  url: string
  snippet?: string | null
}

export interface SessionList {
  sessions: SessionSummary[]
  total: number
}

export interface Meta {
  version: string
  max_artifact_bytes: number
  max_artifacts: number
  accepts: ArtifactType[]
  auth: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// All requests send the session cookie (credentials: 'include').
async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: body !== undefined
      ? { 'Content-Type': 'application/json', Accept: 'application/json' }
      : { Accept: 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError(res.status, `${res.status} ${res.statusText} — ${text}`)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const get = <T>(path: string) => req<T>('GET', path)

export interface ListParams {
  agent?: string
  favorite?: boolean
  q?: string
}

function qs(params: ListParams): string {
  const p = new URLSearchParams()
  if (params.agent) p.set('agent', params.agent)
  if (params.favorite != null) p.set('favorite', String(params.favorite))
  if (params.q) p.set('q', params.q)
  const s = p.toString()
  return s ? `?${s}` : ''
}

export interface User {
  id: string
  username: string
  role: string
}

export interface ApiKeyInfo {
  id: string
  prefix: string
  label: string
  scope: string
  revoked: boolean
  last_used_at: string | null
  created_at: string
}

export interface Collection {
  id: string
  name: string
  query: ListParams & { tag?: string }
  pinned: string[]
  created_at: string
}

export const api = {
  meta: () => get<Meta>('/v0/meta'),
  list: (params: ListParams = {}) => get<SessionList>(`/v0/sessions${qs(params)}`),
  setFavorite: (id: string, favorite: boolean) =>
    req<SessionSummary>('PATCH', `/v0/sessions/${id}`, { favorite }),
  session: (id: string, version?: number) =>
    get<SessionOut>(`/v0/sessions/${id}${version ? `?version=${version}` : ''}`),
  createSession: (payload: SessionIn) =>
    req<CreateSessionOut>('POST', '/v0/sessions', payload),
  artifactMeta: (id: string) => get<ArtifactDetail>(`/v0/artifacts/${id}/meta`),
  // Raw + sandboxed-view URLs are plain paths (used as <a>/<iframe> src).
  artifactRaw: (id: string) => `/v0/artifacts/${id}`,
  artifactView: (id: string) => `/v0/artifacts/${id}/view`,

  // auth
  me: () => get<User>('/v0/auth/me'),
  login: (username: string, password: string) =>
    req<User>('POST', '/v0/auth/login', { username, password }),
  logout: () => req<void>('POST', '/v0/auth/logout', {}),
  keys: () => get<ApiKeyInfo[]>('/v0/auth/keys'),
  createKey: (label: string, scope = 'write') =>
    req<ApiKeyInfo & { token: string }>('POST', '/v0/auth/keys', { label, scope }),
  revokeKey: (id: string) => req<void>('DELETE', `/v0/auth/keys/${id}`),

  // collections
  collections: () => get<Collection[]>('/v0/collections'),
  collection: (id: string) => get<Collection>(`/v0/collections/${id}`),
  collectionSessions: (id: string) => get<SessionList>(`/v0/collections/${id}/sessions`),
  createCollection: (name: string, query: ListParams) =>
    req<Collection>('POST', '/v0/collections', { name, query }),
  deleteCollection: (id: string) => req<void>('DELETE', `/v0/collections/${id}`),
  pinSession: (collectionId: string, sessionId: string) =>
    req<Collection>('PUT', `/v0/collections/${collectionId}/sessions/${sessionId}`),
  unpinSession: (collectionId: string, sessionId: string) =>
    req<Collection>('DELETE', `/v0/collections/${collectionId}/sessions/${sessionId}`),
}
