import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './api'
import type { DocumentRecord } from './model'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, getSession: vi.fn(), uploadDocument: vi.fn(), getDocument: vi.fn(), deleteDocument: vi.fn(), logout: vi.fn() }
})

describe('App', () => {
  beforeEach(() => {
    vi.mocked(api.getSession).mockResolvedValue({ authenticated: true, csrfToken: 'csrf', displayName: 'Ada' })
    vi.stubGlobal('crypto', { randomUUID: () => 'upload-key' })
  })

  it('renders anonymous and session-expired states without persisted authentication', async () => {
    vi.mocked(api.getSession).mockResolvedValueOnce({ authenticated: false })
    render(<App />)
    expect(await screen.findByRole('link', { name: 'Sign in securely' })).toHaveAttribute('href', '/auth/login')
    expect(document.body.textContent).not.toContain('csrf')
  })

  it('validates a file and keeps focusable controls accessible', async () => {
    const user = userEvent.setup()
    render(<App />)
    const input = await screen.findByLabelText(/Choose a PDF/)
    fireEvent.change(input, { target: { files: [new File(['unsafe'], 'unsafe.html', { type: 'text/html' })] } })
    await user.click(screen.getByRole('button', { name: 'Upload for scanning' }))
    expect(screen.getByText(/UTF-8 text file/)).toBeInTheDocument()
    expect(input).toHaveFocus()
  })

  it('uploads, reports progress, and offers cancellation', async () => {
    let resolve!: (document: DocumentRecord) => void
    let reject!: (error: Error) => void
    const promise = new Promise<DocumentRecord>((done, fail) => { resolve = done; reject = fail })
    const abort = vi.fn(() => reject(new DOMException('cancelled', 'AbortError')))
    vi.mocked(api.uploadDocument).mockImplementation((_file, _csrf, key, onProgress) => {
      expect(key).toBe('upload-key')
      onProgress(42)
      return { promise, abort }
    })
    const user = userEvent.setup()
    render(<App />)
    const input = await screen.findByLabelText(/Choose a PDF/)
    fireEvent.change(input, { target: { files: [new File(['safe'], 'report.pdf', { type: 'application/pdf' })] } })
    await user.click(screen.getByRole('button', { name: 'Upload for scanning' }))
    expect(await screen.findByRole('status')).toHaveTextContent('42%')
    await user.click(screen.getByRole('button', { name: 'Cancel upload' }))
    expect(abort).toHaveBeenCalled()
    await screen.findByRole('button', { name: 'Upload for scanning' })
    void resolve
  })

  it('reuses an idempotency key for retry and exposes clean-only download', async () => {
    const file = new File(['safe'], 'report.pdf', { type: 'application/pdf' })
    let reject!: (error: Error) => void
    const failed = new Promise<DocumentRecord>((_resolve, fail) => { reject = fail })
    vi.mocked(api.uploadDocument)
      .mockReturnValueOnce({ promise: failed, abort: vi.fn() })
      .mockReturnValueOnce({ promise: Promise.resolve({ id: 'doc', name: 'report.pdf', status: 'clean' }), abort: vi.fn() })
    const user = userEvent.setup()
    render(<App />)
    const input = await screen.findByLabelText(/Choose a PDF/)
    fireEvent.change(input, { target: { files: [file] } })
    await user.click(screen.getByRole('button', { name: 'Upload for scanning' }))
    reject(new api.ApiError('Try safely', 503))
    await user.click(await screen.findByRole('button', { name: 'Retry upload' }))
    const keys = vi.mocked(api.uploadDocument).mock.calls.map((call) => call[2])
    expect(keys).toEqual(['upload-key', 'upload-key'])
    expect(await screen.findByRole('link', { name: 'Download clean document' })).toHaveAttribute('href', '/api/v1/documents/doc/content')
  })

  it('polls processing documents then deletes without rendering a preview', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(api.uploadDocument).mockReturnValue({ promise: Promise.resolve({ id: 'doc', name: '<img src=x>', status: 'pending_scan' }), abort: vi.fn() })
    vi.mocked(api.getDocument).mockResolvedValue({ id: 'doc', name: '<img src=x>', status: 'clean' })
    vi.mocked(api.deleteDocument).mockResolvedValue()
    render(<App />)
    const input = await screen.findByLabelText(/Choose a PDF/)
    fireEvent.change(input, { target: { files: [new File(['safe'], 'report.pdf', { type: 'application/pdf' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload for scanning' }))
    await vi.advanceTimersByTimeAsync(1600)
    expect(await screen.findByText('<img src=x>')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Delete document' }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep document' }))
    expect(screen.getByRole('button', { name: 'Delete document' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete document' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith('doc', 'csrf'))
    vi.useRealTimers()
  })

  it('requires a selected file and clears the in-memory session on sign out', async () => {
    vi.mocked(api.logout).mockResolvedValue()
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Upload for scanning' }))
    expect(screen.getByText('Choose a file before uploading.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(api.logout).toHaveBeenCalledWith('csrf')
    expect(await screen.findByRole('link', { name: 'Sign in securely' })).toBeInTheDocument()
  })
})
