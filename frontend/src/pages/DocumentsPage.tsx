import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteDocument,
  downloadDocument,
  getDocumentDownloadUrl,
  listHudSources,
  listDocuments,
  syncHudSources,
  uploadDocument,
} from '../lib/api/client'
import { formatDateTime, formatFileSize } from '../lib/format'

type DocumentsPageProps = {
  sessionId: string | null
  currentUserId: string | null
}

type DocumentSourceFilter = 'all' | 'uploads' | 'hud'

function isHudDocument(document: { uploaded_by_user_id: string | null; file_name: string }) {
  return document.uploaded_by_user_id === null && document.file_name.trim().startsWith('[HUD]')
}

export function DocumentsPage({ sessionId, currentUserId }: DocumentsPageProps) {
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<DocumentSourceFilter>('all')
  const [documentPendingDelete, setDocumentPendingDelete] = useState<{
    documentId: string
    fileName: string
  } | null>(null)
  const queryClient = useQueryClient()

  const hudSourcesQuery = useQuery({
    queryKey: ['hud', 'sources', 'documents-page'],
    queryFn: () => listHudSources(false),
  })

  const hudSyncMutation = useMutation({
    mutationFn: async (refresh: boolean) => syncHudSources(refresh),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['documents'] }),
        queryClient.invalidateQueries({ queryKey: ['hud', 'sources', 'documents-page'] }),
      ])
    },
  })

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
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message)
      setMessage(null)
    },
  })

  const downloadMutation = useMutation({
    mutationFn: async (documentId: string) => {
      try {
        const direct = await downloadDocument(documentId)
        return {
          mode: 'blob' as const,
          fileName: direct.fileName,
          blob: direct.blob,
        }
      } catch {
        const fallback = await getDocumentDownloadUrl(documentId)
        return {
          mode: 'url' as const,
          fileName: fallback.file_name,
          downloadUrl: fallback.download_url,
        }
      }
    },
    onSuccess: (payload) => {
      setError(null)

      if (payload.mode === 'blob') {
        setMessage(`Starting download for '${payload.fileName}'.`)

        const objectUrl = window.URL.createObjectURL(payload.blob)
        const anchor = window.document.createElement('a')
        anchor.href = objectUrl
        anchor.download = payload.fileName
        window.document.body.append(anchor)
        anchor.click()
        anchor.remove()

        // Delay revocation so browsers have enough time to begin download.
        window.setTimeout(() => {
          window.URL.revokeObjectURL(objectUrl)
        }, 2_000)
        return
      }

      setMessage(`Starting download for '${payload.fileName}' via signed URL.`)
      window.location.assign(payload.downloadUrl)
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message)
      setMessage(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (documentId: string) => deleteDocument(documentId),
    onSuccess: async (_, documentId) => {
      setError(null)
      setDocumentPendingDelete(null)
      setMessage(
        `Document deleted. Linked artifacts were removed and any active selection for document ${documentId.slice(0, 8)} was cleared.`,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['documents'] }),
        queryClient.invalidateQueries({ queryKey: ['documents', 'for-query'] }),
        queryClient.invalidateQueries({ queryKey: ['session-current'] }),
      ])
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

  const sourceCounts = useMemo(() => {
    let hud = 0
    let uploads = 0

    for (const document of sortedDocuments) {
      if (isHudDocument(document)) {
        hud += 1
      } else {
        uploads += 1
      }
    }

    return {
      all: sortedDocuments.length,
      uploads,
      hud,
    }
  }, [sortedDocuments])

  const filteredDocuments = useMemo(() => {
    if (sourceFilter === 'all') {
      return sortedDocuments
    }

    return sortedDocuments.filter((document) => {
      const hudDocument = isHudDocument(document)
      if (sourceFilter === 'hud') {
        return hudDocument
      }
      return !hudDocument
    })
  }, [sortedDocuments, sourceFilter])

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
            Upload files and monitor processing status for explicit document scope in Ask.
          </p>
        </div>
      </header>

      <div className="card">
        <div className="card-title-row">
          <h3>HUD source sync</h3>
          <p className="muted">Sources: {hudSourcesQuery.data?.total_count ?? 0}</p>
        </div>

        <p className="muted">
          Pull authoritative HUD/public legal-policy sources directly into this Documents list.
          Synced HUD records appear alongside uploaded files.
        </p>

        <div className="row-actions">
          <button
            type="button"
            className="ghost"
            onClick={() => hudSyncMutation.mutate(false)}
            disabled={hudSyncMutation.isPending}
          >
            {hudSyncMutation.isPending ? 'Syncing...' : 'Sync now'}
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => hudSyncMutation.mutate(true)}
            disabled={hudSyncMutation.isPending}
          >
            Force refresh
          </button>
        </div>

        {hudSyncMutation.data ? (
          <p className="notice success">
            Sync completed: +{hudSyncMutation.data.ingested_count} ingested, {hudSyncMutation.data.updated_count}{' '}
            updated, {hudSyncMutation.data.skipped_count} skipped, {hudSyncMutation.data.failed_count} failed.
          </p>
        ) : null}

        {hudSyncMutation.isError ? (
          <p className="notice error">{(hudSyncMutation.error as Error).message}</p>
        ) : null}

        {hudSourcesQuery.isError ? (
          <p className="notice error">{(hudSourcesQuery.error as Error).message}</p>
        ) : null}
      </div>

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
        </form>

        {message ? <p className="notice success">{message}</p> : null}
        {error ? <p className="notice error">{error}</p> : null}
      </div>

      <div className="card">
        <div className="card-title-row">
          <h3>Known documents</h3>
          <div className="row-actions">
            <button
              type="button"
              className={sourceFilter === 'all' ? 'primary' : 'ghost'}
              onClick={() => setSourceFilter('all')}
              aria-pressed={sourceFilter === 'all'}
            >
              All ({sourceCounts.all})
            </button>
            <button
              type="button"
              className={sourceFilter === 'uploads' ? 'primary' : 'ghost'}
              onClick={() => setSourceFilter('uploads')}
              aria-pressed={sourceFilter === 'uploads'}
            >
              User docs ({sourceCounts.uploads})
            </button>
            <button
              type="button"
              className={sourceFilter === 'hud' ? 'primary' : 'ghost'}
              onClick={() => setSourceFilter('hud')}
              aria-pressed={sourceFilter === 'hud'}
            >
              HUD sync ({sourceCounts.hud})
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => documentsQuery.refetch()}
              disabled={documentsQuery.isFetching}
            >
              Refresh
            </button>
          </div>
        </div>

        {documentsQuery.isLoading ? <p className="muted">Loading documents...</p> : null}
        {documentsQuery.isError ? (
          <p className="notice error">{(documentsQuery.error as Error).message}</p>
        ) : null}

        {filteredDocuments.length === 0 ? (
          <div className="stack-form">
            {sourceCounts.all === 0 ? (
              <>
                <p className="muted">No documents found in Known documents.</p>
                {sessionId ? (
                  <p className="muted">
                    Current user context: <span className="mono">{currentUserId ?? 'resolving-user'}</span>.
                    Upload a file in this session to create a user-linked record.
                  </p>
                ) : (
                  <p className="muted">Select or create a session first, then upload to populate this grid.</p>
                )}
              </>
            ) : (
              <p className="muted">
                No {sourceFilter === 'hud' ? 'HUD sync' : 'uploaded'} documents match this filter.
              </p>
            )}
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Uploaded</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.map((document) => (
                  <DocumentRow
                    key={document.document_id}
                    document={document}
                    onDownload={(documentId) => downloadMutation.mutate(documentId)}
                    isDownloading={downloadMutation.isPending}
                    onDelete={(documentId, fileName) => {
                      setDocumentPendingDelete({ documentId, fileName })
                    }}
                    isDeleting={deleteMutation.isPending}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {documentPendingDelete ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card" role="dialog" aria-modal="true" aria-label="Delete document">
            <h3>Delete document permanently?</h3>
            <p className="muted">
              This will remove the row and all linked artifacts (chunks, index entries, and stored files)
              for <strong>{documentPendingDelete.fileName}</strong>. This action cannot be undone.
            </p>
            <div className="row-actions">
              <button
                type="button"
                className="ghost"
                onClick={() => setDocumentPendingDelete(null)}
                disabled={deleteMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => deleteMutation.mutate(documentPendingDelete.documentId)}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete permanently'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}

type DocumentRowProps = {
  document: {
    document_id: string
    file_name: string
    file_size_bytes: number
    upload_timestamp: string
    processing_status: string
    uploaded_by_user_id: string | null
  }
  isDownloading: boolean
  isDeleting: boolean
  onDownload: (documentId: string) => void
  onDelete: (documentId: string, fileName: string) => void
}

function DocumentRow({ document, isDownloading, isDeleting, onDownload, onDelete }: DocumentRowProps) {
  const isHudSource = isHudDocument(document)

  return (
    <tr>
      <td>
        <p className="cell-title">{document.file_name}</p>
      </td>
      <td>
        <span className={`source-pill ${isHudSource ? 'hud' : 'uploaded'}`}>
          {isHudSource ? 'HUD sync' : 'Upload'}
        </span>
      </td>
      <td>
        <span className={`status-pill ${document.processing_status.toLowerCase()}`}>
          {document.processing_status}
        </span>
      </td>
      <td>{formatFileSize(document.file_size_bytes)}</td>
      <td>{formatDateTime(document.upload_timestamp)}</td>
      <td>
        <div className="row-actions">
          <button
            type="button"
            className="ghost"
            disabled={isDownloading}
            onClick={() => onDownload(document.document_id)}
          >
            Download
          </button>
          <button
            type="button"
            className="ghost"
            disabled={isDeleting}
            onClick={() => onDelete(document.document_id, document.file_name)}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}
