import { useMemo, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { askQuestion, listHudSources, syncHudSources } from '../lib/api/client'
import type { QueryResponse } from '../lib/api/types'
import { formatDateTime } from '../lib/format'

type HudLawsPageProps = {
  sessionId: string | null
}

export function HudLawsPage({ sessionId }: HudLawsPageProps) {
  const queryClient = useQueryClient()

  const [question, setQuestion] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [scopeValidationMessage, setScopeValidationMessage] = useState<string | null>(null)

  const sourcesQuery = useQuery({
    queryKey: ['hud', 'sources'],
    queryFn: () => listHudSources(true),
  })

  const syncMutation = useMutation({
    mutationFn: async (refresh: boolean) => syncHudSources(refresh),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['hud', 'sources'] })
    },
  })

  const askMutation = useMutation({
    mutationFn: async () => {
      if (!sessionId) {
        throw new Error('No session is available for HUD legal query.')
      }

      return askQuestion(sessionId, {
        question,
        document_ids: selectedDocumentIdsInScope,
        top_k: 8,
        max_citations: 6,
      })
    },
  })

  const sourceDocuments = useMemo(() => {
    return (sourcesQuery.data?.sources ?? []).filter(
      (source) => source.processing_status.toLowerCase() === 'completed',
    )
  }, [sourcesQuery.data?.sources])

  const selectableDocumentIds = useMemo(
    () => new Set(sourceDocuments.map((source) => source.document_id)),
    [sourceDocuments],
  )

  const selectedDocumentIdsInScope = selectedDocumentIds.filter((documentId) =>
    selectableDocumentIds.has(documentId),
  )

  const hasStaleSelection = selectedDocumentIds.length > selectedDocumentIdsInScope.length

  function toggleSourceDocument(documentId: string) {
    setScopeValidationMessage(null)
    setSelectedDocumentIds((current) => {
      if (current.includes(documentId)) {
        return current.filter((id) => id !== documentId)
      }
      return [...current, documentId]
    })
  }

  function selectAllSources() {
    setScopeValidationMessage(null)
    setSelectedDocumentIds(sourceDocuments.map((source) => source.document_id))
  }

  function clearSelectedSources() {
    setScopeValidationMessage(null)
    setSelectedDocumentIds([])
  }

  function attemptSubmitQuestion() {
    if (!sessionId || question.trim().length < 5 || askMutation.isPending) {
      return
    }

    if (selectedDocumentIdsInScope.length === 0) {
      setScopeValidationMessage('Select at least one HUD source document before asking.')
      return
    }

    setScopeValidationMessage(null)
    askMutation.mutate()
  }

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    attemptSubmitQuestion()
  }

  function onQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && event.shiftKey) {
      event.preventDefault()
      attemptSubmitQuestion()
    }
  }

  const canSubmit = Boolean(sessionId) && question.trim().length >= 5 && sourceDocuments.length > 0

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Sondra Keys HUD Laws</p>
          <h2>HUD Laws and Policy Ask</h2>
          <p className="muted">
            Ask HUD-focused legal and policy questions over curated authoritative sources with
            explicit source scope and citations.
          </p>
        </div>
        <Link to="/" className="help-card-link pdf-back-link">
          Back to portal
        </Link>
      </header>

      <div className="card">
        <div className="card-title-row">
          <h3>HUD source sync</h3>
          <p className="muted">Sources: {sourcesQuery.data?.total_count ?? 0}</p>
        </div>
        <p className="muted">
          Source strategy: authoritative HUD/public legal-policy pages are synced into the same
          retrieval stack used by Ask. HUD User dataset APIs are treated as supplemental context.
        </p>

        <div className="row-actions">
          <button
            type="button"
            className="ghost"
            onClick={() => syncMutation.mutate(false)}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Syncing...' : 'Sync now'}
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => syncMutation.mutate(true)}
            disabled={syncMutation.isPending}
          >
            Force refresh
          </button>
        </div>

        {syncMutation.data ? (
          <p className="notice success">
            Sync completed: +{syncMutation.data.ingested_count} ingested, {syncMutation.data.updated_count} updated,
            {` ${syncMutation.data.skipped_count}`} skipped, {syncMutation.data.failed_count} failed.
          </p>
        ) : null}

        {syncMutation.isError ? (
          <p className="notice error">{(syncMutation.error as Error).message}</p>
        ) : null}

        {sourcesQuery.isError ? (
          <p className="notice error">{(sourcesQuery.error as Error).message}</p>
        ) : null}
      </div>

      <div className="card">
        <h3>Ask HUD laws</h3>
        <form onSubmit={submitQuestion} className="stack-form">
          <label htmlFor="hud-question" className="label">
            Prompt
          </label>
          <textarea
            id="hud-question"
            rows={5}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onQuestionKeyDown}
            placeholder="What are the protected classes under the Fair Housing Act?"
          />

          <div>
            <div className="card-title-row">
              <label className="label">Explicit HUD source scope</label>
              <p className="muted">
                Selected: {selectedDocumentIdsInScope.length} / {sourceDocuments.length}
              </p>
            </div>

            <div className="ask-scope-actions">
              <button
                type="button"
                className="ghost"
                onClick={selectAllSources}
                disabled={sourceDocuments.length === 0}
              >
                Select all
              </button>
              <button
                type="button"
                className="ghost"
                onClick={clearSelectedSources}
                disabled={selectedDocumentIdsInScope.length === 0}
              >
                Clear all
              </button>
            </div>

            <div className="table-wrap ask-scope-table-wrap">
              {sourceDocuments.length === 0 ? (
                <p className="muted">No HUD sources are available yet. Run sync to ingest sources.</p>
              ) : (
                <table className="ask-scope-table">
                  <thead>
                    <tr>
                      <th scope="col">Select</th>
                      <th scope="col">Source</th>
                      <th scope="col">Regulation</th>
                      <th scope="col">Effective date</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sourceDocuments.map((source) => (
                      <tr key={source.document_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Select ${source.title}`}
                            checked={selectedDocumentIdsInScope.includes(source.document_id)}
                            onChange={() => toggleSourceDocument(source.document_id)}
                          />
                        </td>
                        <td>
                          <p className="cell-title">{source.title}</p>
                          <a href={source.source_url} target="_blank" rel="noreferrer" className="help-card-link">
                            Open source
                          </a>
                        </td>
                        <td>{source.regulation_id}</td>
                        <td>{source.effective_date ?? 'Unspecified'}</td>
                        <td>
                          <span className={`status-pill ${source.processing_status.toLowerCase()}`}>
                            {source.processing_status}
                          </span>
                          <p className="muted">Synced {formatDateTime(source.last_synced_at)}</p>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {scopeValidationMessage ? <p className="notice error">{scopeValidationMessage}</p> : null}
            {hasStaleSelection ? (
              <p className="notice success">
                One or more stale sources were automatically excluded from the current scope.
              </p>
            ) : null}
          </div>

          <button type="submit" className="primary" disabled={!canSubmit || askMutation.isPending}>
            {askMutation.isPending ? 'Running HUD query...' : 'Ask HUD laws'}
          </button>
        </form>

        {askMutation.isError ? <p className="notice error">{(askMutation.error as Error).message}</p> : null}
      </div>

      {askMutation.data ? <HudAnswerPanel result={askMutation.data} /> : null}
    </section>
  )
}

type HudAnswerPanelProps = {
  result: QueryResponse
}

function HudAnswerPanel({ result }: HudAnswerPanelProps) {
  return (
    <div className="card">
      <div className="card-title-row">
        <h3>HUD-grounded answer</h3>
        <p className="muted">{result.model_used}</p>
      </div>
      <p className="answer-text">{result.answer}</p>

      <h4>Citations ({result.citations.length})</h4>
      {result.citations.length === 0 ? (
        <p className="muted">No citations were returned for this response.</p>
      ) : (
        <ul className="citation-list">
          {result.citations.map((citation, index) => (
            <li key={`${citation.document_id}-${citation.chunk_index}-${index}`}>
              <p className="citation-meta">
                {citation.file_name}
                {citation.page_number ? ` | page ${citation.page_number}` : ''}
              </p>
              {citation.section_title ? <p className="muted">{citation.section_title}</p> : null}
              <p className="citation-snippet">{citation.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
