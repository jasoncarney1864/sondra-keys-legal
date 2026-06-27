import { useMemo, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { askQuestion, listDocuments } from '../lib/api/client'
import type { QueryResponse } from '../lib/api/types'
import { formatDateTime, formatFileSize } from '../lib/format'
import {
  type AskScopeSortField,
  type AskScopeSortState,
  nextSortState,
  sortScopeDocuments,
} from '../lib/ask/scopeTable'

type AskPageProps = {
  sessionId: string | null
}

export function AskPage({ sessionId }: AskPageProps) {
  const [question, setQuestion] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [scopeValidationMessage, setScopeValidationMessage] = useState<string | null>(null)
  const [sortState, setSortState] = useState<AskScopeSortState>({
    field: 'date',
    direction: 'desc',
  })

  const documentsQuery = useQuery({
    queryKey: ['documents', 'for-query'],
    queryFn: () => listDocuments(0, 50),
  })

  const queryMutation = useMutation({
    mutationFn: async () => {
      if (!sessionId) {
        throw new Error('No session is available for this query.')
      }

      const payload = {
        question,
        top_k: 5,
        max_citations: 5,
        document_ids: selectedDocumentIdsInScope,
      }

      return askQuestion(sessionId, payload)
    },
  })

  const selectableDocuments = useMemo(() => {
    return (documentsQuery.data?.documents ?? []).filter(
      (document) => document.processing_status.toLowerCase() === 'completed',
    )
  }, [documentsQuery.data?.documents])

  const sortedSelectableDocuments = useMemo(() => {
    return sortScopeDocuments(selectableDocuments, sortState)
  }, [selectableDocuments, sortState])

  const selectableDocumentIds = useMemo(
    () => new Set(selectableDocuments.map((document) => document.document_id)),
    [selectableDocuments],
  )
  const selectedDocumentIdsInScope = selectedDocumentIds.filter((documentId) =>
    selectableDocumentIds.has(documentId),
  )
  const hasStaleSelection = selectedDocumentIds.length > selectedDocumentIdsInScope.length

  function toggleDocument(documentId: string) {
    setScopeValidationMessage(null)
    setSelectedDocumentIds((current) => {
      if (current.includes(documentId)) {
        return current.filter((id) => id !== documentId)
      }
      return [...current, documentId]
    })
  }

  function selectAllDocuments() {
    setScopeValidationMessage(null)
    setSelectedDocumentIds(sortedSelectableDocuments.map((document) => document.document_id))
  }

  function clearSelectedDocuments() {
    setScopeValidationMessage(null)
    setSelectedDocumentIds([])
  }

  function attemptSubmitQuestion() {
    if (!sessionId || question.trim().length < 5 || queryMutation.isPending) {
      return
    }

    if (selectedDocumentIdsInScope.length === 0) {
      setScopeValidationMessage('Select at least one document to ask this question.')
      return
    }

    setScopeValidationMessage(null)
    queryMutation.mutate()
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

  function onSort(field: AskScopeSortField) {
    setSortState((current) => nextSortState(current, field))
  }

  function sortIndicator(field: AskScopeSortField): string {
    if (sortState.field !== field) {
      return ''
    }
    return sortState.direction === 'asc' ? ' \u2191' : ' \u2193'
  }

  function sortAriaSuffix(field: AskScopeSortField): string {
    if (sortState.field !== field) {
      return ''
    }

    return sortState.direction === 'asc' ? ' ascending' : ' descending'
  }

  function getAriaSort(field: AskScopeSortField): 'none' | 'ascending' | 'descending' {
    if (sortState.field !== field) {
      return 'none'
    }
    return sortState.direction === 'asc' ? 'ascending' : 'descending'
  }

  const canSubmit =
    Boolean(sessionId) &&
    question.trim().length >= 5 &&
    selectableDocuments.length > 0

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Retrieval</p>
          <h2>Ask</h2>
          <p className="muted">
            Send grounded questions with explicit document scope. Choose the exact document set for
            each question.
          </p>
        </div>
      </header>

      <div className="card">
        <h3>Question</h3>
        <form onSubmit={submitQuestion} className="stack-form">
          <label htmlFor="question" className="label">
            Prompt
          </label>
          <textarea
            id="question"
            rows={5}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onQuestionKeyDown}
            placeholder="What are the parking restrictions in Skyline?"
          />

          <div>
            <div className="card-title-row">
              <label className="label">Explicit document scope</label>
              <p className="muted">
                Selected: {selectedDocumentIdsInScope.length} / {selectableDocuments.length}
              </p>
            </div>

            <div className="ask-scope-actions">
              <button
                type="button"
                className="ghost"
                onClick={selectAllDocuments}
                disabled={selectableDocuments.length === 0}
              >
                Select all
              </button>
              <button
                type="button"
                className="ghost"
                onClick={clearSelectedDocuments}
                disabled={selectedDocumentIdsInScope.length === 0}
              >
                Clear all
              </button>
            </div>

            <div className="table-wrap ask-scope-table-wrap">
              {sortedSelectableDocuments.length === 0 ? (
                <p className="muted">No completed documents are available for explicit scope yet.</p>
              ) : (
                <table className="ask-scope-table">
                  <thead>
                    <tr>
                      <th scope="col">Select</th>
                      <th scope="col" aria-sort={getAriaSort('name')}>
                        <button type="button" className="sort-header-button" onClick={() => onSort('name')}>
                          Name
                          <span className="sort-icon" aria-hidden="true">
                            {sortIndicator('name')}
                          </span>
                          <span className="sr-only">{sortAriaSuffix('name')}</span>
                        </button>
                      </th>
                      <th scope="col" aria-sort={getAriaSort('date')}>
                        <button type="button" className="sort-header-button" onClick={() => onSort('date')}>
                          Date created
                          <span className="sort-icon" aria-hidden="true">
                            {sortIndicator('date')}
                          </span>
                          <span className="sr-only">{sortAriaSuffix('date')}</span>
                        </button>
                      </th>
                      <th scope="col" aria-sort={getAriaSort('status')}>
                        <button type="button" className="sort-header-button" onClick={() => onSort('status')}>
                          Status
                          <span className="sort-icon" aria-hidden="true">
                            {sortIndicator('status')}
                          </span>
                          <span className="sr-only">{sortAriaSuffix('status')}</span>
                        </button>
                      </th>
                      <th scope="col" aria-sort={getAriaSort('size')}>
                        <button type="button" className="sort-header-button" onClick={() => onSort('size')}>
                          Size
                          <span className="sort-icon" aria-hidden="true">
                            {sortIndicator('size')}
                          </span>
                          <span className="sr-only">{sortAriaSuffix('size')}</span>
                        </button>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedSelectableDocuments.map((document) => (
                      <tr key={document.document_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Select ${document.file_name}`}
                            checked={selectedDocumentIdsInScope.includes(document.document_id)}
                            onChange={() => toggleDocument(document.document_id)}
                          />
                        </td>
                        <td>
                          <p className="cell-title">{document.file_name}</p>
                        </td>
                        <td>{formatDateTime(document.upload_timestamp)}</td>
                        <td>
                          <span className={`status-pill ${document.processing_status.toLowerCase()}`}>
                            {document.processing_status}
                          </span>
                        </td>
                        <td>{formatFileSize(document.file_size_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {scopeValidationMessage ? <p className="notice error">{scopeValidationMessage}</p> : null}
            {hasStaleSelection ? (
              <p className="notice success">
                One or more deleted documents were automatically excluded from explicit scope.
              </p>
            ) : null}
          </div>

          <button type="submit" className="primary" disabled={!canSubmit || queryMutation.isPending}>
            {queryMutation.isPending ? 'Running query...' : 'Ask question'}
          </button>
        </form>

        {queryMutation.isError ? (
          <p className="notice error">{(queryMutation.error as Error).message}</p>
        ) : null}
      </div>

      {queryMutation.data ? <AnswerPanel result={queryMutation.data} /> : null}
    </section>
  )
}

type AnswerPanelProps = {
  result: QueryResponse
}

function AnswerPanel({ result }: AnswerPanelProps) {
  return (
    <div className="card">
      <div className="card-title-row">
        <h3>Answer</h3>
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
              <p className="citation-snippet">{citation.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
