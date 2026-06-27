import type {
  ActiveDocumentResponse,
  ApiErrorEnvelope,
  DocumentListResponse,
  DocumentRecord,
  DocumentUploadResponse,
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
  try {
    const payload = (await response.json()) as ApiErrorEnvelope
    if (payload?.detail) {
      return payload.detail
    }
  } catch {
    // Fall back to status text when body is not JSON.
  }

  return response.statusText || 'Request failed'
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

export function setActiveDocument(sessionId: string, documentId: string) {
  return request<ActiveDocumentResponse>('/api/sessions/current/active-document', {
    method: 'PUT',
    sessionId,
    json: {
      document_id: documentId,
    },
  })
}

export function clearActiveDocument(sessionId: string) {
  return request<ActiveDocumentResponse>('/api/sessions/current/active-document', {
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
