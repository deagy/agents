import { describe, expect, it } from 'vitest'
import { MAX_UPLOAD_BYTES, reducer, validateFile, type AppState, type DocumentRecord } from './model'

const idle: AppState = { phase: 'idle', csrfToken: 'csrf', displayName: 'Ada' }
const document: DocumentRecord = { id: 'doc-1', name: 'report.pdf', status: 'pending_scan' }

describe('reducer', () => {
  it('covers the session, validation, and upload lifecycle', () => {
    expect(reducer({ phase: 'loading-session' }, { type: 'SESSION', csrfToken: 'csrf', displayName: 'Ada' })).toEqual(idle)
    expect(reducer(idle, { type: 'INVALID', message: 'bad file' })).toMatchObject({ phase: 'idle', validation: 'bad file' })
    const file = new File(['ok'], 'report.pdf', { type: 'application/pdf' })
    const uploading = reducer(idle, { type: 'UPLOAD', file, idempotencyKey: 'stable' })
    expect(reducer(uploading, { type: 'PROGRESS', progress: 150 })).toMatchObject({ phase: 'uploading', progress: 100 })
    expect(reducer(uploading, { type: 'RETRY', message: 'network' })).toMatchObject({ phase: 'retry', idempotencyKey: 'stable' })
    expect(reducer(uploading, { type: 'DOCUMENT', document })).toMatchObject({ phase: 'processing' })
  })

  it('maps fail-closed states and deletion', () => {
    const clean = reducer(idle, { type: 'DOCUMENT', document: { ...document, status: 'clean' } })
    expect(clean.phase).toBe('clean')
    expect(reducer(idle, { type: 'DOCUMENT', document: { ...document, status: 'failed' } }).phase).toBe('rejected')
    const confirming = reducer(clean, { type: 'REQUEST_DELETE' })
    expect(confirming.phase).toBe('confirming-delete')
    expect(reducer(confirming, { type: 'DELETE_CONFIRMED' }).phase).toBe('deleting')
    expect(reducer(confirming, { type: 'CANCEL_DELETE' }).phase).toBe('clean')
    expect(reducer(clean, { type: 'RESET' })).toEqual(idle)
    expect(reducer(idle, { type: 'ERROR', message: 'safe' })).toMatchObject({ phase: 'error', message: 'safe' })
    expect(reducer(idle, { type: 'ANONYMOUS', expired: true })).toEqual({ phase: 'anonymous', expired: true })
  })

  it('ignores actions requiring a missing authenticated context', () => {
    const anonymous: AppState = { phase: 'anonymous', expired: false }
    const file = new File(['x'], 'x.txt', { type: 'text/plain' })
    expect(reducer(anonymous, { type: 'UPLOAD', file, idempotencyKey: 'x' })).toBe(anonymous)
    expect(reducer(anonymous, { type: 'DOCUMENT', document })).toBe(anonymous)
    expect(reducer(anonymous, { type: 'REQUEST_DELETE' })).toBe(anonymous)
  })
})

describe('file validation', () => {
  it.each([
    ['paper.pdf', 'application/pdf'],
    ['image.png', 'image/png'],
    ['photo.JPEG', 'image/jpeg'],
    ['notes.txt', 'text/plain'],
  ])('accepts matching %s', (name, type) => {
    expect(validateFile(new File(['safe'], name, { type }))).toBeUndefined()
  })

  it('rejects excessive size, unsupported types, and mismatched extensions', () => {
    const huge = new File(['x'], 'large.pdf', { type: 'application/pdf' })
    Object.defineProperty(huge, 'size', { value: MAX_UPLOAD_BYTES + 1 })
    expect(validateFile(huge)).toContain('25 MiB')
    expect(validateFile(new File(['x'], 'page.html', { type: 'text/html' }))).toContain('PDF')
    expect(validateFile(new File(['x'], 'image.txt', { type: 'image/png' }))).toContain('does not match')
  })
})
