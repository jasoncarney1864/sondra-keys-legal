import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { askQuestion, listDocuments } from '../lib/api/client'
import type { QueryResponse } from '../lib/api/types'

type AskPageProps = {
  sessionId: string | null
  activeDocumentId: string | null
  activeDocumentName: string | null
}

export function AskPage({ sessionId, activeDocumentId, activeDocumentName }: AskPageProps) {
  const [question, setQuestion] = useState('')
  const [explicitScope, setExplicitScope] = useState(false)
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [isScopeHelpOpen, setIsScopeHelpOpen] = useState(false)
  const scopeHelpRef = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    function onDocumentPointerDown(event: PointerEvent) {
      if (!scopeHelpRef.current) {
        return
      }

      if (!scopeHelpRef.current.contains(event.target as Node)) {
        setIsScopeHelpOpen(false)
      }
    }

    function onEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsScopeHelpOpen(false)
      }
    }

    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onEscape)

    return () => {
      document.removeEventListener('pointerdown', onDocumentPointerDown)
      document.removeEventListener('keydown', onEscape)
    }
  }, [])

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
        document_ids: explicitScope ? selectedDocumentIds : undefined,
      }

      return askQuestion(sessionId, payload)
    },
  })

  const selectableDocuments = useMemo(() => {
    return (documentsQuery.data?.documents ?? []).filter(
      (document) => document.processing_status.toLowerCase() === 'completed',
    )
  }, [documentsQuery.data?.documents])

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((current) => {
      if (current.includes(documentId)) {
        return current.filter((id) => id !== documentId)
      }
      return [...current, documentId]
    })
  }

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    queryMutation.mutate()
  }

  const canSubmit =
    Boolean(sessionId) &&
    question.trim().length >= 5 &&
    (!explicitScope || selectedDocumentIds.length > 0)

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Retrieval</p>
          <h2>Ask</h2>
          <p className="muted">
            Send grounded questions to the backend using either active document mode or explicit
            document scope.
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
            placeholder="What are the parking restrictions in Skyline?"
          />

          <label className="inline-checkbox toggle-row" htmlFor="explicit-scope">
            <input
              id="explicit-scope"
              type="checkbox"
              className="toggle-input"
              checked={explicitScope}
              onChange={(event) => setExplicitScope(event.target.checked)}
            />
            <span className="toggle-track" aria-hidden="true">
              <span className="toggle-thumb" />
            </span>
            <span className="scope-option-wrap">
              <span className="scope-option-text">
                Use explicit document scope instead of the session active document.
              </span>
              <span
                ref={scopeHelpRef}
                className={`scope-help ${isScopeHelpOpen ? 'is-open' : ''}`}
                tabIndex={0}
                aria-label="What explicit document scope means"
              >
                <button
                  type="button"
                  className="scope-help-icon"
                  aria-label="Explain explicit document scope"
                  aria-expanded={isScopeHelpOpen}
                  onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    setIsScopeHelpOpen((current) => !current)
                  }}
                >
                  ?
                </button>
                <span className="scope-help-tooltip">
                  Toggle on to choose specific documents for this question.
                  A document checklist appears below when enabled.
                  Toggle off to use your current session active document.
                </span>
              </span>
            </span>
          </label>
          <p className="muted scope-help-inline">
            Tip: keep this off for active-document mode, or toggle on to pick documents manually.
          </p>

          {explicitScope ? (
            <div className="document-picker">
              {selectableDocuments.length === 0 ? (
                <p className="muted">No completed documents are available to scope this query.</p>
              ) : (
                selectableDocuments.map((document) => (
                  <label key={document.document_id} className="inline-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedDocumentIds.includes(document.document_id)}
                      onChange={() => toggleDocument(document.document_id)}
                    />
                    {document.file_name}
                  </label>
                ))
              )}
            </div>
          ) : (
            <p className="muted">
              Current active document: <span className="mono">{activeDocumentName ?? (activeDocumentId ? 'Selected document' : 'None')}</span>
            </p>
          )}

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
