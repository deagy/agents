import type { DocumentRecord, DocumentStatus } from './model'

export type Session =
  | { authenticated: false }
  | { authenticated: true; csrfToken: string; displayName: string }

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = 'request_failed',
  ) {
    super(message)
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function safeMessage(value: unknown, fallback: string): string {
  if (!object(value) || typeof value.code !== 'string') return fallback
  const messages: Record<string, string> = {
    invalid_upload: 'Choose a supported file and try again.',
    upload_too_large: 'Choose a file no larger than 25 MiB.',
    unsupported_media_type: 'Choose a PDF, PNG, JPEG, or UTF-8 text file.',
    idempotency_conflict: 'This retry does not match the original upload.',
    session_expired: 'Your session expired. Sign in again.',
  }
  return messages[value.code] ?? fallback
}

function parseDocument(value: unknown): DocumentRecord {
  const candidate = object(value) && object(value.document) ? value.document : value
  const statuses: DocumentStatus[] = ['pending_scan', 'scanning', 'clean', 'rejected', 'failed', 'delete_pending', 'deleting']
  if (!object(candidate) || typeof candidate.id !== 'string' || typeof candidate.name !== 'string' || !statuses.includes(candidate.status as DocumentStatus)) {
    throw new ApiError('The server returned an invalid document response.', 502, 'invalid_response')
  }
  return {
    id: candidate.id,
    name: candidate.name,
    status: candidate.status as DocumentStatus,
    ...(typeof candidate.message === 'string' ? { message: candidate.message.slice(0, 300) } : {}),
  }
}

async function json(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new ApiError('The server returned an unreadable response.', 502, 'invalid_response')
  }
}

export async function getSession(signal?: AbortSignal): Promise<Session> {
  const response = await fetch('/api/v1/session', { credentials: 'same-origin', cache: 'no-store', ...(signal ? { signal } : {}) })
  if (response.status === 401) return { authenticated: false }
  const body = await json(response)
  if (!response.ok) throw new ApiError(safeMessage(body, 'Unable to check your session.'), response.status)
  if (!object(body) || typeof body.authenticated !== 'boolean') throw new ApiError('The server returned an invalid session response.', 502, 'invalid_response')
  if (!body.authenticated) return { authenticated: false }
  if (typeof body.csrf_token !== 'string' || !object(body.user) || typeof body.user.display_name !== 'string') {
    throw new ApiError('The server returned an invalid session response.', 502, 'invalid_response')
  }
  return { authenticated: true, csrfToken: body.csrf_token, displayName: body.user.display_name }
}

export interface UploadOperation {
  promise: Promise<DocumentRecord>
  abort: () => void
}

export function uploadDocument(file: File, csrfToken: string, idempotencyKey: string, onProgress: (progress: number) => void): UploadOperation {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<DocumentRecord>((resolve, reject) => {
    xhr.open('POST', '/api/v1/documents')
    xhr.responseType = 'json'
    xhr.withCredentials = true
    xhr.setRequestHeader('X-CSRF-Token', csrfToken)
    xhr.setRequestHeader('Idempotency-Key', idempotencyKey)
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    })
    xhr.addEventListener('load', () => {
      if (xhr.status === 401) return reject(new ApiError('Your session expired. Sign in again.', 401, 'session_expired'))
      if (xhr.status < 200 || xhr.status >= 300) return reject(new ApiError(safeMessage(xhr.response, 'The upload could not be completed.'), xhr.status))
      try { resolve(parseDocument(xhr.response)) } catch (error) { reject(error) }
    })
    xhr.addEventListener('error', () => reject(new ApiError('The upload was interrupted. Try again.', 0)))
    xhr.addEventListener('abort', () => reject(new DOMException('Upload cancelled', 'AbortError')))
    const form = new FormData()
    form.append('file', file, file.name)
    xhr.send(form)
  })
  return { promise, abort: () => xhr.abort() }
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...init })
  if (response.status === 401) throw new ApiError('Your session expired. Sign in again.', 401, 'session_expired')
  if (response.status === 202 || response.status === 204) return undefined
  const body = await json(response)
  if (!response.ok) throw new ApiError(safeMessage(body, 'The request could not be completed.'), response.status)
  return body
}

export async function getDocument(id: string, signal?: AbortSignal): Promise<DocumentRecord> {
  return parseDocument(await request(`/api/v1/documents/${encodeURIComponent(id)}`, signal ? { signal } : {}))
}

export async function deleteDocument(id: string, csrfToken: string): Promise<void> {
  await request(`/api/v1/documents/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrfToken } })
}

export async function logout(csrfToken: string): Promise<void> {
  await request('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken } })
}

export function downloadUrl(id: string): string {
  return `/api/v1/documents/${encodeURIComponent(id)}/content`
}
