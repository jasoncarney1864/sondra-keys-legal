import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, createSession, deleteSession, listSessions, uploadDocument } from '../lib/api/client'
import { formatDateTime } from '../lib/format'

type SessionsPageProps = {
  currentSessionId: string | null
  onSessionSelected: (sessionId: string | null) => void
}

const ACCEPTED_FILE_TYPES = '.pdf, .docx, .doc, .txt'
const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 50)

export function SessionsPage({ currentSessionId, onSessionSelected }: SessionsPageProps) {
  const [newSessionFile, setNewSessionFile] = useState<File | null>(null)
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [uploadNotice, setUploadNotice] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const sessionsQuery = useQuery({
    queryKey: ['sessions', currentSessionId],
    queryFn: async () => {
      try {
        return await listSessions(currentSessionId ?? undefined)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404 && currentSessionId) {
          onSessionSelected(null)
          return listSessions()
        }
        throw error
      }
    },
  })

  const createSessionMutation = useMutation({
    mutationFn: async (file: File | null) => {
      const session = await createSession()
      if (file) {
        await uploadDocument(session.session_id, file)
      }
      return session
    },
    onSuccess: async (response, file) => {
      onSessionSelected(response.session_id)
      setUploadNotice(
        file
          ? `Session created and '${file.name}' uploaded.`
          : 'Session created.',
      )
      setIsCreateModalOpen(false)
      setNewSessionFile(null)
      await queryClient.invalidateQueries({ queryKey: ['sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['session-current'] })
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await deleteSession(sessionId)
      return sessionId
    },
    onSuccess: async (deletedSessionId) => {
      if (deletedSessionId === currentSessionId) {
        onSessionSelected(null)
      }
      queryClient.removeQueries({ queryKey: ['sessions', deletedSessionId], exact: true })
      await queryClient.invalidateQueries({ queryKey: ['sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['session-current'] })
    },
  })

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Identity</p>
          <h2>Sessions</h2>
          <p className="muted">
            Create and select sticky sessions to preserve conversation continuity.
          </p>
        </div>
        <div className="session-create-actions">
          <button
            type="button"
            className="primary"
            onClick={() => setIsCreateModalOpen(true)}
            disabled={createSessionMutation.isPending || isCreateModalOpen}
          >
            Create session
          </button>
        </div>
      </header>

      {isCreateModalOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => {
            if (createSessionMutation.isPending) {
              return
            }
            setIsCreateModalOpen(false)
            setNewSessionFile(null)
          }}
        >
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-session-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="create-session-title">Create session</h3>
            <p className="muted">
              Upload a document now if you want this new session ready for immediate questions.
            </p>
            <input
              type="file"
              accept={ACCEPTED_FILE_TYPES}
              onChange={(event) => setNewSessionFile(event.target.files?.[0] ?? null)}
            />
            <p className="muted">Allowed: {ACCEPTED_FILE_TYPES}. Max size: {MAX_UPLOAD_MB} MB.</p>
            <div className="row-actions">
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setIsCreateModalOpen(false)
                  setNewSessionFile(null)
                }}
                disabled={createSessionMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => createSessionMutation.mutate(newSessionFile)}
                disabled={createSessionMutation.isPending}
              >
                {createSessionMutation.isPending
                  ? 'Creating...'
                  : newSessionFile
                    ? 'Create + upload'
                    : 'Create now'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="card">
        {sessionsQuery.isLoading ? <p className="muted">Loading sessions...</p> : null}
        {sessionsQuery.isError ? (
          <p className="notice error">{(sessionsQuery.error as Error).message}</p>
        ) : null}
        {createSessionMutation.isError ? (
          <p className="notice error">{(createSessionMutation.error as Error).message}</p>
        ) : null}
        {deleteSessionMutation.isError ? (
          <p className="notice error">{(deleteSessionMutation.error as Error).message}</p>
        ) : null}
        {uploadNotice ? <p className="notice success">{uploadNotice}</p> : null}

        {(sessionsQuery.data?.sessions.length ?? 0) === 0 ? (
          <p className="muted">No sessions found.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Last accessed</th>
                  <th>Expires</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {sessionsQuery.data?.sessions.map((session) => {
                  const isCurrent = session.session_id === currentSessionId

                  return (
                    <tr key={session.session_id}>
                      <td className="mono">{session.session_id}</td>
                      <td>{formatDateTime(session.last_accessed_at)}</td>
                      <td>{formatDateTime(session.expires_at)}</td>
                      <td>
                        <div className="row-actions">
                          <button
                            type="button"
                            className={isCurrent ? 'primary' : 'ghost'}
                            onClick={() => onSessionSelected(session.session_id)}
                          >
                            {isCurrent ? 'Current' : 'Use session'}
                          </button>
                          <button
                            type="button"
                            className="ghost"
                            disabled={deleteSessionMutation.isPending}
                            onClick={() => {
                              const shouldDelete = window.confirm(
                                'Delete this session? This removes only session context. Documents remain available.',
                              )
                              if (shouldDelete) {
                                deleteSessionMutation.mutate(session.session_id)
                              }
                            }}
                            aria-label="Delete session"
                            title="Delete session"
                          >
                            <svg className="trash-icon" viewBox="0 0 24 24" role="img" focusable="false">
                              <path
                                d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v9h-2V9zm4 0h2v9h-2V9zM7 9h2v9H7V9z"
                                fill="currentColor"
                              />
                            </svg>
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
