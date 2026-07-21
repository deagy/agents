import { useEffect, useReducer, useRef, useState } from 'react'
import { ApiError, deleteDocument, downloadUrl, getDocument, getSession, logout, uploadDocument, type UploadOperation } from './api'
import { reducer, validateFile, type AppState } from './model'
import styles from './App.module.css'

const initialState: AppState = { phase: 'loading-session' }

function message(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong. Try again.'
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const upload = useRef<UploadOperation | undefined>(undefined)
  const fileInput = useRef<HTMLInputElement>(null)
  const pollAttempt = useRef(0)
  const [pollSignal, setPollSignal] = useState(0)
  const [manualPolling, setManualPolling] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void getSession(controller.signal)
      .then((session) => session.authenticated
        ? dispatch({ type: 'SESSION', csrfToken: session.csrfToken, displayName: session.displayName })
        : dispatch({ type: 'ANONYMOUS' }))
      .catch((error: unknown) => dispatch({ type: 'ERROR', message: message(error) }))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (state.phase === 'idle' && state.validation) fileInput.current?.focus()
  }, [state])

  useEffect(() => {
    if (state.phase !== 'processing' && state.phase !== 'deleting') {
      pollAttempt.current = 0
      setManualPolling(false)
      return
    }
    const controller = new AbortController()
    const poll = () => {
      void getDocument(state.document.id, controller.signal)
        .then((document) => {
          pollAttempt.current += 1
          dispatch({ type: 'DOCUMENT', document })
          setPollSignal((value) => value + 1)
        })
        .catch((error: unknown) => {
          if (state.phase === 'deleting' && error instanceof ApiError && error.status === 404) {
            dispatch({ type: 'RESET' })
          } else if (error instanceof ApiError && error.status === 401) dispatch({ type: 'ANONYMOUS', expired: true })
          else if (!(error instanceof DOMException && error.name === 'AbortError')) dispatch({ type: 'ERROR', message: message(error) })
        })
    }
    if (document.hidden) {
      const resume = () => { if (!document.hidden) setPollSignal((value) => value + 1) }
      document.addEventListener('visibilitychange', resume, { once: true })
      return () => { controller.abort(); document.removeEventListener('visibilitychange', resume) }
    }
    if (pollAttempt.current >= 5) {
      setManualPolling(true)
      return () => controller.abort()
    }
    const delays = [1000, 2000, 4000, 5000]
    const timer = window.setTimeout(poll, delays[Math.min(pollAttempt.current, delays.length - 1)])
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [state.phase, 'document' in state ? state.document.id : '', 'document' in state ? state.document.status : '', pollSignal])

  function beginUpload(file: File, idempotencyKey: string = crypto.randomUUID()) {
    const error = validateFile(file)
    if (error) {
      dispatch({ type: 'INVALID', message: error })
      fileInput.current?.focus()
      return
    }
    if (!('csrfToken' in state)) return
    dispatch({ type: 'UPLOAD', file, idempotencyKey })
    const operation = uploadDocument(file, state.csrfToken, idempotencyKey, (progress) => dispatch({ type: 'PROGRESS', progress }))
    upload.current = operation
    void operation.promise
      .then((document) => dispatch({ type: 'DOCUMENT', document }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') dispatch({ type: 'RESET' })
        else if (error instanceof ApiError && error.status === 401) dispatch({ type: 'ANONYMOUS', expired: true })
        else dispatch({ type: 'RETRY', message: message(error) })
      })
  }

  async function remove() {
    if (!('document' in state) || !('csrfToken' in state)) return
    dispatch({ type: 'DELETE_CONFIRMED' })
    try {
      await deleteDocument(state.document.id, state.csrfToken)
      pollAttempt.current = 0
      setPollSignal((value) => value + 1)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) dispatch({ type: 'ANONYMOUS', expired: true })
      else dispatch({ type: 'ERROR', message: message(error) })
    }
  }

  async function signOut() {
    if (!('csrfToken' in state)) return
    try { await logout(state.csrfToken) } finally { dispatch({ type: 'ANONYMOUS' }) }
  }

  const authenticated = 'displayName' in state && Boolean(state.displayName)
  const busy = state.phase === 'uploading' || state.phase === 'deleting'

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>SAMPLE-001 · local demonstration</p>
          <h1>Secure documents</h1>
        </div>
        {authenticated && <div className={styles.account}><span>Signed in as {state.displayName}</span><button className={styles.quiet} onClick={() => void signOut()}>Sign out</button></div>}
      </header>

      <section className={styles.card} aria-labelledby="workspace-heading" aria-busy={busy}>
        <h2 id="workspace-heading">Document workspace</h2>
        <div className={styles.status} role="status" aria-live="polite" aria-atomic="true">
          {state.phase === 'loading-session' && 'Checking your session…'}
          {state.phase === 'anonymous' && (state.expired ? 'Your session expired. Sign in again to continue.' : 'Sign in to upload and manage a document.')}
          {state.phase === 'uploading' && `Uploading ${state.file.name}: ${state.progress}%`}
          {state.phase === 'processing' && 'Upload complete. Security scanning is in progress.'}
          {state.phase === 'clean' && 'Security scan complete. Your document is ready to download.'}
          {state.phase === 'rejected' && (state.document.message ?? 'This document was rejected and cannot be downloaded.')}
          {state.phase === 'confirming-delete' && 'Confirm that you want to delete this document.'}
          {state.phase === 'retry' && state.message}
          {state.phase === 'deleting' && 'Deleting the document…'}
          {state.phase === 'error' && state.message}
        </div>

        {state.phase === 'anonymous' && <a className={styles.primary} href="/auth/login">Sign in securely</a>}

        {(state.phase === 'idle' || state.phase === 'error') && authenticated && (
          <form onSubmit={(event) => {
            event.preventDefault()
            const file = fileInput.current?.files?.[0]
            if (file) beginUpload(file)
            else dispatch({ type: 'INVALID', message: 'Choose a file before uploading.' })
          }}>
            <label htmlFor="document">Choose a PDF, PNG, JPEG, or text file</label>
            <input ref={fileInput} id="document" name="document" type="file" accept=".pdf,.png,.jpg,.jpeg,.txt,application/pdf,image/png,image/jpeg,text/plain" aria-describedby="file-help file-error" />
            <p id="file-help" className={styles.help}>Maximum size: 25 MiB. Files are never previewed in this application.</p>
            {'validation' in state && state.validation && <p id="file-error" className={styles.error}>{state.validation}</p>}
            <button className={styles.primary} type="submit">Upload for scanning</button>
          </form>
        )}

        {state.phase === 'uploading' && <div><progress max="100" value={state.progress}>{state.progress}%</progress><button className={styles.secondary} onClick={() => upload.current?.abort()}>Cancel upload</button></div>}

        {state.phase === 'retry' && <div className={styles.actions}><button className={styles.primary} onClick={() => beginUpload(state.file, state.idempotencyKey)}>Retry upload</button><button className={styles.secondary} onClick={() => dispatch({ type: 'RESET' })}>Choose another file</button></div>}

        {(state.phase === 'processing' || state.phase === 'clean' || state.phase === 'rejected' || state.phase === 'confirming-delete' || state.phase === 'deleting') && (
          <article className={styles.document}>
            <div><span className={styles.label}>Document</span><strong>{state.document.name}</strong></div>
            <div><span className={styles.label}>Status</span><strong>{state.document.status.replace('_', ' ')}</strong></div>
            <div className={styles.actions}>
              {state.phase === 'clean' && <a className={styles.primary} href={downloadUrl(state.document.id)} download>Download clean document</a>}
              {state.phase === 'confirming-delete' ? <><button className={styles.danger} onClick={() => void remove()}>Confirm deletion</button><button className={styles.secondary} onClick={() => dispatch({ type: 'CANCEL_DELETE' })}>Keep document</button></> : <button className={styles.danger} disabled={state.phase === 'deleting'} onClick={() => dispatch({ type: 'REQUEST_DELETE' })}>Delete document</button>}
            </div>
            {manualPolling && (state.phase === 'processing' || state.phase === 'deleting') && <div><p>This is taking longer than expected. You can check again safely.</p><button className={styles.secondary} onClick={() => { pollAttempt.current = 4; setManualPolling(false); setPollSignal((value) => value + 1) }}>Check status</button></div>}
          </article>
        )}

        {state.phase === 'error' && <button className={styles.secondary} onClick={() => window.location.reload()}>Try again</button>}
      </section>
      <p className={styles.notice}>Development demonstration only. Do not use production or regulated data.</p>
    </main>
  )
}
