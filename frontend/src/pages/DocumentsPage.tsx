import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  clearActiveDocument,
  listDocuments,
  setActiveDocument,
  uploadDocument,
} from '../lib/api/client'
import type { DocumentRecord } from '../lib/api/types'
import { formatDateTime, formatFileSize } from '../lib/format'

type DocumentsPageProps = {
  sessionId: string | null
  activeDocumentId: string | null
  onSessionChanged: () => Promise<void> | void
}

export function DocumentsPage({
  sessionId,
  activeDocumentId,
  onSessionChanged,
}: DocumentsPageProps) {
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const documentsQuery = useQuery({
    queryKey: ['documents'],
    queryFn: () => listDocuments(0, 50),
    refetchInterval: (query) => {
      const payload = query.state.data
      if (!payload) {
        return false
      }

      const hasInFlight = payload.documents.some((doc) =>
        ['pending', 'extracting', 'chunking', 'indexing'].includes(doc.processing_status),
      )

      return hasInFlight ? 3000 : false
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async (selected: File) => {
      if (!sessionId) {
        throw new Error('A session is required before uploading.')
      }
      return uploadDocument(sessionId, selected)
    },
    onSuccess: async (payload) => {
      setMessage(payload.message)
      setError(null)
      setFile(null)
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
      await onSessionChanged()
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message)
      setMessage(null)
    },
  })

  const setActiveMutation = useMutation({
    mutationFn: async (documentId: string) => {
      if (!sessionId) {
        throw new Error('A session is required before selecting an active document.')
      }
      return setActiveDocument(sessionId, documentId)
    },
    onSuccess: async () => {
      setError(null)
      setMessage('Active document updated for current session.')
      await onSessionChanged()
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message)
      setMessage(null)
    },
  })

  const clearActiveMutation = useMutation({
    mutationFn: async () => {
      if (!sessionId) {
        throw new Error('A session is required before clearing active document.')
      }
      return clearActiveDocument(sessionId)
    },
    onSuccess: async () => {
      setError(null)
      setMessage('Active document cleared.')
      await onSessionChanged()
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message)
      setMessage(null)
    },
  })

  const sortedDocuments = useMemo(() => {
    const source = documentsQuery.data?.documents ?? []
    return [...source].sort((a, b) => {
      return Date.parse(b.upload_timestamp) - Date.parse(a.upload_timestamp)
    })
  }, [documentsQuery.data?.documents])

  function onUploadSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) {
      setError('Select a PDF or DOCX file to upload.')
      setMessage(null)
      return
    }

    uploadMutation.mutate(file)
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Pipeline</p>
          <h2>Documents</h2>
          <p className="muted">
            Upload, monitor processing state, and control session-level active document.
          </p>
        </div>
      </header>

      <div className="card">
        <h3>Upload document</h3>
        <form className="inline-form" onSubmit={onUploadSubmit}>
          <input
            type="file"
            accept=".pdf,.doc,.docx,.txt"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
            }}
          />
          <button
            type="submit"
            disabled={!sessionId || uploadMutation.isPending}
            className="primary"
          >
            {uploadMutation.isPending ? 'Uploading...' : 'Upload'}
          </button>
          <button
            type="button"
            onClick={() => clearActiveMutation.mutate()}
            disabled={!sessionId || clearActiveMutation.isPending}
            className="ghost"
          >
            Clear active document
          </button>
        </form>

        {message ? <p className="notice success">{message}</p> : null}
        {error ? <p className="notice error">{error}</p> : null}
      </div>

      <div className="card">
        <div className="card-title-row">
          <h3>Known documents</h3>
          <button
            type="button"
            className="ghost"
            onClick={() => documentsQuery.refetch()}
            disabled={documentsQuery.isFetching}
          >
            Refresh
          </button>
        </div>

        {documentsQuery.isLoading ? <p className="muted">Loading documents...</p> : null}
        {documentsQuery.isError ? (
          <p className="notice error">{(documentsQuery.error as Error).message}</p>
        ) : null}

        {sortedDocuments.length === 0 ? (
          <p className="muted">No documents found yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Uploaded</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {sortedDocuments.map((document) => (
                  <DocumentRow
                    key={document.document_id}
                    document={document}
                    isActive={document.document_id === activeDocumentId}
                    onSetActive={(documentId) => setActiveMutation.mutate(documentId)}
                    isBusy={setActiveMutation.isPending}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

type DocumentRowProps = {
  document: DocumentRecord
  isActive: boolean
  isBusy: boolean
  onSetActive: (documentId: string) => void
}

function DocumentRow({ document, isActive, isBusy, onSetActive }: DocumentRowProps) {
  return (
    <tr>
      <td>
        <p className="cell-title">{document.file_name}</p>
      </td>
      <td>
        <span className={`status-pill ${document.processing_status.toLowerCase()}`}>
          {document.processing_status}
        </span>
      </td>
      <td>{formatFileSize(document.file_size_bytes)}</td>
      <td>{formatDateTime(document.upload_timestamp)}</td>
      <td>
        <button
          type="button"
          className={isActive ? 'primary' : 'ghost'}
          disabled={isBusy}
          onClick={() => onSetActive(document.document_id)}
        >
          {isActive ? 'Active' : 'Set active'}
        </button>
      </td>
    </tr>
  )
}
