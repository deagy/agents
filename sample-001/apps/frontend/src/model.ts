export const ACCEPTED_TYPES = ['application/pdf', 'image/png', 'image/jpeg', 'text/plain'] as const
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

export type DocumentStatus = 'pending_scan' | 'scanning' | 'clean' | 'rejected' | 'failed' | 'delete_pending' | 'deleting'

export interface DocumentRecord {
  id: string
  name: string
  status: DocumentStatus
  message?: string
}

export type AppState =
  | { phase: 'loading-session' }
  | { phase: 'anonymous'; expired: boolean }
  | { phase: 'idle'; csrfToken: string; displayName: string; validation?: string }
  | { phase: 'uploading'; csrfToken: string; displayName: string; file: File; idempotencyKey: string; progress: number }
  | { phase: 'processing'; csrfToken: string; displayName: string; document: DocumentRecord }
  | { phase: 'clean'; csrfToken: string; displayName: string; document: DocumentRecord }
  | { phase: 'rejected'; csrfToken: string; displayName: string; document: DocumentRecord }
  | { phase: 'retry'; csrfToken: string; displayName: string; file: File; idempotencyKey: string; message: string }
  | { phase: 'confirming-delete'; csrfToken: string; displayName: string; document: DocumentRecord }
  | { phase: 'deleting'; csrfToken: string; displayName: string; document: DocumentRecord }
  | { phase: 'error'; csrfToken?: string; displayName?: string; message: string }

export type Action =
  | { type: 'SESSION'; csrfToken: string; displayName: string }
  | { type: 'ANONYMOUS'; expired?: boolean }
  | { type: 'INVALID'; message: string }
  | { type: 'UPLOAD'; file: File; idempotencyKey: string }
  | { type: 'PROGRESS'; progress: number }
  | { type: 'DOCUMENT'; document: DocumentRecord }
  | { type: 'RETRY'; message: string }
  | { type: 'REQUEST_DELETE' }
  | { type: 'CANCEL_DELETE' }
  | { type: 'DELETE_CONFIRMED' }
  | { type: 'RESET' }
  | { type: 'ERROR'; message: string }

function authenticated(state: AppState) {
  if ('csrfToken' in state && state.csrfToken && 'displayName' in state && state.displayName) {
    return { csrfToken: state.csrfToken, displayName: state.displayName }
  }
  return undefined
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SESSION':
      return { phase: 'idle', csrfToken: action.csrfToken, displayName: action.displayName }
    case 'ANONYMOUS':
      return { phase: 'anonymous', expired: action.expired ?? false }
    case 'INVALID': {
      const session = authenticated(state)
      return session ? { phase: 'idle', ...session, validation: action.message } : state
    }
    case 'UPLOAD': {
      const session = authenticated(state)
      return session ? { phase: 'uploading', ...session, file: action.file, idempotencyKey: action.idempotencyKey, progress: 0 } : state
    }
    case 'PROGRESS':
      return state.phase === 'uploading' ? { ...state, progress: Math.min(100, Math.max(0, action.progress)) } : state
    case 'DOCUMENT': {
      const session = authenticated(state)
      if (!session) return state
      if (action.document.status === 'clean') return { phase: 'clean', ...session, document: action.document }
      if (action.document.status === 'rejected' || action.document.status === 'failed') return { phase: 'rejected', ...session, document: action.document }
      if (action.document.status === 'delete_pending' || action.document.status === 'deleting') return { phase: 'deleting', ...session, document: action.document }
      return { phase: 'processing', ...session, document: action.document }
    }
    case 'RETRY':
      return state.phase === 'uploading' ? { phase: 'retry', csrfToken: state.csrfToken, displayName: state.displayName, file: state.file, idempotencyKey: state.idempotencyKey, message: action.message } : state
    case 'REQUEST_DELETE': {
      const session = authenticated(state)
      return session && 'document' in state ? { phase: 'confirming-delete', ...session, document: state.document } : state
    }
    case 'CANCEL_DELETE': {
      const session = authenticated(state)
      return session && state.phase === 'confirming-delete' ? reducer({ phase: 'idle', ...session }, { type: 'DOCUMENT', document: state.document }) : state
    }
    case 'DELETE_CONFIRMED': {
      const session = authenticated(state)
      return session && state.phase === 'confirming-delete' ? { phase: 'deleting', ...session, document: { ...state.document, status: 'delete_pending' } } : state
    }
    case 'RESET': {
      const session = authenticated(state)
      return session ? { phase: 'idle', ...session } : { phase: 'anonymous', expired: false }
    }
    case 'ERROR': {
      const session = authenticated(state)
      return session ? { phase: 'error', ...session, message: action.message } : { phase: 'error', message: action.message }
    }
  }
}

export function validateFile(file: File): string | undefined {
  if (file.size > MAX_UPLOAD_BYTES) return 'Choose a file no larger than 25 MiB.'
  if (!ACCEPTED_TYPES.includes(file.type as (typeof ACCEPTED_TYPES)[number])) return 'Choose a PDF, PNG, JPEG, or UTF-8 text file.'
  const extension = file.name.toLocaleLowerCase().split('.').pop()
  const allowed: Record<string, readonly string[]> = {
    'application/pdf': ['pdf'],
    'image/png': ['png'],
    'image/jpeg': ['jpg', 'jpeg'],
    'text/plain': ['txt'],
  }
  if (!extension || !allowed[file.type]?.includes(extension)) return 'The filename extension does not match the selected file type.'
  return undefined
}
