import type {
  ApiErrorEnvelope,
  DocumentDownloadResponse,
  DocumentListResponse,
  DocumentRecord,
  DocumentUploadResponse,
  HUDSourceListResponse,
  HUDSyncResponse,
  QueryRequest,
  QueryResponse,
  SessionCreateResponse,
  SessionListResponse,
} from './types'
import { getAuthSettings, getOidcAccessToken } from '../auth/oidc'

type ApiSettings = {
  baseUrl: string
  authMode: 'api_key' | 'oidc'
  hasApiKey: boolean
  oidcConfigured: boolean
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').trim()

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function buildUrl(path: string): string {
  if (!API_BASE_URL) {
    return path
  }

  const normalizedBase = API_BASE_URL.endsWith('/')
    ? API_BASE_URL.slice(0, -1)
    : API_BASE_URL
  const normalizedPath = path.startsWith('/') ? path : `/${path}`

  return `${normalizedBase}${normalizedPath}`
}

async function parseError(response: Response): Promise<string> {
  const rawBody = await response.text()

  if (rawBody) {
    try {
      const payload = JSON.parse(rawBody) as ApiErrorEnvelope
      if (payload?.detail) {
        return payload.detail
      }
    } catch {
      // Non-JSON response bodies (for example nginx error pages) are handled below.
    }

    // HTML error pages are noisy; prefer concise status-based messaging.
    if (!rawBody.trim().startsWith('<')) {
      return rawBody
    }
  }

  if (response.status === 413) {
    return 'File is too large. Maximum upload size is 50 MB.'
  }

  return response.statusText || `Request failed (HTTP ${response.status})`
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  sessionId?: string
  body?: BodyInit | null
  json?: unknown
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const authSettings = getAuthSettings()
  const headers = new Headers()
  if (authSettings.mode === 'api_key') {
    if (authSettings.apiKey) {
      headers.set('X-API-Key', authSettings.apiKey)
    }
  } else {
    const accessToken = await getOidcAccessToken()
    if (!accessToken) {
      throw new ApiError(401, 'No OIDC access token is available. Sign in first.')
    }
    headers.set('Authorization', `Bearer ${accessToken}`)
  }
  if (options.sessionId) {
    headers.set('X-Session-Id', options.sessionId)
  }

  let body = options.body ?? null
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  }

  const response = await fetch(buildUrl(path), {
    method: options.method ?? 'GET',
    headers,
    body,
  })

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function getApiSettings(): ApiSettings {
  const authSettings = getAuthSettings()
  return {
    baseUrl: API_BASE_URL,
    authMode: authSettings.mode,
    hasApiKey: authSettings.hasApiKey,
    oidcConfigured: authSettings.oidcConfigured,
  }
}

export function createSession() {
  return request<SessionCreateResponse>('/api/sessions', { method: 'POST' })
}

export function getCurrentSession(sessionId?: string) {
  return request<SessionCreateResponse>('/api/sessions/current', {
    sessionId,
  })
}

export function listSessions(sessionId?: string) {
  return request<SessionListResponse>('/api/sessions', { sessionId })
}

export function deleteSession(sessionId: string) {
  return request<void>(`/api/sessions/${sessionId}`, {
    method: 'DELETE',
    sessionId,
  })
}

export function listDocuments(skip = 0, limit = 40) {
  const query = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  })

  return request<DocumentListResponse>(`/api/documents?${query.toString()}`)
}

export function getDocument(documentId: string) {
  return request<DocumentRecord>(`/api/documents/${documentId}`)
}

export function deleteDocument(documentId: string) {
  return request<void>(`/api/documents/${documentId}`, {
    method: 'DELETE',
  })
}

export function getDocumentDownloadUrl(documentId: string) {
  return request<DocumentDownloadResponse>(`/api/documents/${documentId}/download-url`)
}

type DownloadedDocument = {
  blob: Blob
  fileName: string
}

function parseFileNameFromContentDisposition(headerValue: string | null, fallback: string): string {
  if (!headerValue) {
    return fallback
  }

  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const basicMatch = headerValue.match(/filename="?([^";]+)"?/i)
  if (basicMatch?.[1]) {
    return basicMatch[1]
  }

  return fallback
}

export async function downloadDocument(documentId: string): Promise<DownloadedDocument> {
  const authSettings = getAuthSettings()
  const headers = new Headers()

  if (authSettings.mode === 'api_key') {
    if (authSettings.apiKey) {
      headers.set('X-API-Key', authSettings.apiKey)
    }
  } else {
    const accessToken = await getOidcAccessToken()
    if (!accessToken) {
      throw new ApiError(401, 'No OIDC access token is available. Sign in first.')
    }
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const response = await fetch(buildUrl(`/api/documents/${documentId}/download`), {
    method: 'GET',
    headers,
  })

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response))
  }

  const blob = await response.blob()
  const fileName = parseFileNameFromContentDisposition(
    response.headers.get('content-disposition'),
    `document-${documentId}`,
  )

  return { blob, fileName }
}

export function uploadDocument(sessionId: string, file: File) {
  const body = new FormData()
  body.set('file', file)

  return request<DocumentUploadResponse>('/api/documents/upload', {
    method: 'POST',
    sessionId,
    body,
  })
}

export function askQuestion(sessionId: string, payload: QueryRequest) {
  return request<QueryResponse>('/api/query', {
    method: 'POST',
    sessionId,
    json: payload,
  })
}

export function listHudSources(ensureSynced = true) {
  const query = new URLSearchParams({
    ensure_synced: ensureSynced ? 'true' : 'false',
  })

  return request<HUDSourceListResponse>(`/api/hud/sources?${query.toString()}`)
}

export function syncHudSources(refresh = false) {
  const query = new URLSearchParams({
    refresh: refresh ? 'true' : 'false',
  })

  return request<HUDSyncResponse>(`/api/hud/sync?${query.toString()}`, {
    method: 'POST',
  })
}
