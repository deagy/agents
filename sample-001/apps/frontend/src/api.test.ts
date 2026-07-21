import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, deleteDocument, downloadUrl, getDocument, getSession, logout, uploadDocument } from './api'

function response(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('fetch API client', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))

  it('parses authenticated and anonymous sessions', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: true, csrf_token: 'csrf', user: { display_name: 'Ada' } }))
    await expect(getSession()).resolves.toEqual({ authenticated: true, csrfToken: 'csrf', displayName: 'Ada' })
    expect(fetch).toHaveBeenCalledWith('/api/v1/session', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
    vi.mocked(fetch).mockResolvedValueOnce(response(undefined, 401))
    await expect(getSession()).resolves.toEqual({ authenticated: false })
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: false }))
    await expect(getSession()).resolves.toEqual({ authenticated: false })
  })

  it('rejects malformed session and unreadable responses', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: true }))
    await expect(getSession()).rejects.toMatchObject({ code: 'invalid_response' })
    vi.mocked(fetch).mockResolvedValueOnce(new Response('not json'))
    await expect(getSession()).rejects.toBeInstanceOf(ApiError)
    vi.mocked(fetch).mockResolvedValueOnce(response({ message: 'temporarily unavailable' }, 503))
    await expect(getSession()).rejects.toMatchObject({ status: 503, message: 'Unable to check your session.' })
  })

  it('validates document reads and handles mutations', async () => {
    const record = { id: 'doc/one', name: 'résumé.pdf', status: 'clean' }
    vi.mocked(fetch).mockResolvedValueOnce(response({ document: record }))
    await expect(getDocument('doc/one')).resolves.toEqual(record)
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/documents/doc%2Fone', expect.any(Object))

    vi.mocked(fetch).mockResolvedValueOnce(response(undefined, 204))
    await deleteDocument('doc', 'csrf')
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/documents/doc', expect.objectContaining({ method: 'DELETE', headers: { 'X-CSRF-Token': 'csrf' } }))

    vi.mocked(fetch).mockResolvedValueOnce(response(undefined, 204))
    await logout('csrf')
    expect(fetch).toHaveBeenLastCalledWith('/auth/logout', expect.objectContaining({ method: 'POST' }))
    expect(downloadUrl('a/b')).toBe('/api/v1/documents/a%2Fb/content')
  })

  it('fails closed for bad documents, expired sessions, and safe fallback errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ id: 'x', name: 'x', status: 'unknown' }))
    await expect(getDocument('x')).rejects.toMatchObject({ code: 'invalid_response' })
    vi.mocked(fetch).mockResolvedValueOnce(response(undefined, 401))
    await expect(getDocument('x')).rejects.toMatchObject({ code: 'session_expired' })
    vi.mocked(fetch).mockResolvedValueOnce(response({}, 500))
    await expect(getDocument('x')).rejects.toThrow('could not be completed')
  })
})

class FakeXHR {
  static last: FakeXHR
  status = 201
  response: unknown = { document: { id: 'doc', name: 'safe.pdf', status: 'pending_scan' } }
  responseType = ''
  withCredentials = false
  headers: Record<string, string> = {}
  listeners: Record<string, Array<(event: ProgressEvent) => void>> = {}
  upload = { addEventListener: (name: string, listener: (event: ProgressEvent) => void) => this.on(`upload:${name}`, listener) }
  constructor() { FakeXHR.last = this }
  open = vi.fn()
  setRequestHeader(name: string, value: string) { this.headers[name] = value }
  addEventListener(name: string, listener: (event: ProgressEvent) => void) { this.on(name, listener) }
  on(name: string, listener: (event: ProgressEvent) => void) { (this.listeners[name] ??= []).push(listener) }
  fire(name: string, event = {} as ProgressEvent) { this.listeners[name]?.forEach((listener) => listener(event)) }
  send = vi.fn()
  abort = vi.fn(() => this.fire('abort'))
}

describe('XHR upload client', () => {
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXHR))

  it('sends bound metadata, emits progress, parses response, and aborts', async () => {
    const progress = vi.fn()
    const operation = uploadDocument(new File(['safe'], 'résumé.pdf', { type: 'application/pdf' }), 'csrf', 'stable-key', progress)
    const xhr = FakeXHR.last
    expect(xhr.withCredentials).toBe(true)
    expect(xhr.headers).toEqual({ 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'stable-key' })
    expect(xhr.send).toHaveBeenCalledWith(expect.any(FormData))
    xhr.fire('upload:progress', { lengthComputable: true, loaded: 1, total: 2 } as ProgressEvent)
    expect(progress).toHaveBeenCalledWith(50)
    xhr.fire('load')
    await expect(operation.promise).resolves.toMatchObject({ id: 'doc', status: 'pending_scan' })

    const cancelled = uploadDocument(new File(['x'], 'x.txt', { type: 'text/plain' }), 'csrf', 'key', progress)
    cancelled.abort()
    await expect(cancelled.promise).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('returns safe errors for HTTP, network, expired, and malformed responses', async () => {
    let operation = uploadDocument(new File(['x'], 'x.txt', { type: 'text/plain' }), 'csrf', 'key', vi.fn())
    FakeXHR.last.status = 409
    FakeXHR.last.response = { message: 'Idempotency key conflict' }
    FakeXHR.last.fire('load')
    await expect(operation.promise).rejects.toMatchObject({ status: 409 })

    operation = uploadDocument(new File(['x'], 'x.txt', { type: 'text/plain' }), 'csrf', 'key', vi.fn())
    FakeXHR.last.status = 401
    FakeXHR.last.fire('load')
    await expect(operation.promise).rejects.toMatchObject({ code: 'session_expired' })

    operation = uploadDocument(new File(['x'], 'x.txt', { type: 'text/plain' }), 'csrf', 'key', vi.fn())
    FakeXHR.last.fire('error')
    await expect(operation.promise).rejects.toThrow('interrupted')

    operation = uploadDocument(new File(['x'], 'x.txt', { type: 'text/plain' }), 'csrf', 'key', vi.fn())
    FakeXHR.last.response = { document: { id: 'x' } }
    FakeXHR.last.fire('load')
    await expect(operation.promise).rejects.toMatchObject({ code: 'invalid_response' })
  })
})
