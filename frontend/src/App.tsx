import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from './app/AppLayout'
import { getApiSettings, getCurrentSession, listDocuments } from './lib/api/client'
import {
  initializeOidcUser,
  loginWithOidcPopup,
  logoutOidcPopup,
} from './lib/auth/oidc'
import { AskPage } from './pages/AskPage'
import { DashboardPage } from './pages/DashboardPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { SessionsPage } from './pages/SessionsPage'

const SESSION_STORAGE_KEY = 'sondra.frontend.current_session_id'

function App() {
  const [sessionId, setSessionId] = useState<string | null>(() => {
    return window.localStorage.getItem(SESSION_STORAGE_KEY)
  })

  const apiSettings = getApiSettings()

  const oidcUserQuery = useQuery({
    queryKey: ['auth', 'oidc-user'],
    queryFn: initializeOidcUser,
    enabled: apiSettings.authMode === 'oidc',
    retry: false,
  })

  const signInMutation = useMutation({
    mutationFn: loginWithOidcPopup,
    onSuccess: async () => {
      await oidcUserQuery.refetch()
    },
  })

  const signOutMutation = useMutation({
    mutationFn: logoutOidcPopup,
    onSuccess: async () => {
      setSessionId(null)
      window.localStorage.removeItem(SESSION_STORAGE_KEY)
      await oidcUserQuery.refetch()
    },
  })

  const authReady =
    apiSettings.authMode === 'api_key'
      ? apiSettings.hasApiKey
      : Boolean(oidcUserQuery.data)

  const authIdentity =
    apiSettings.authMode === 'oidc' ? oidcUserQuery.data?.name ?? null : null

  const authError =
    (signInMutation.error as Error | null)?.message ??
    (signOutMutation.error as Error | null)?.message ??
    (oidcUserQuery.error as Error | null)?.message ??
    null

  const sessionQuery = useQuery({
    queryKey: ['session-current', sessionId],
    queryFn: async () => {
      const resolved = await getCurrentSession(sessionId ?? undefined)
      if (resolved.session_id !== sessionId) {
        setSessionId(resolved.session_id)
        window.localStorage.setItem(SESSION_STORAGE_KEY, resolved.session_id)
      }
      return resolved
    },
    enabled: authReady,
    retry: 1,
  })

  const activeDocumentId = sessionQuery.data?.active_document_id ?? null

  const documentsLookupQuery = useQuery({
    queryKey: ['documents', 'lookup'],
    queryFn: () => listDocuments(0, 200),
    enabled: authReady,
  })

  const activeDocumentName = activeDocumentId
    ? documentsLookupQuery.data?.documents.find(
        (document) => document.document_id === activeDocumentId,
      )?.file_name ?? null
    : null

  function selectSession(nextSessionId: string | null) {
    setSessionId(nextSessionId)
    if (nextSessionId) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId)
    } else {
      window.localStorage.removeItem(SESSION_STORAGE_KEY)
    }
  }

  async function refreshSession() {
    await sessionQuery.refetch()
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <AppLayout
              sessionId={sessionId}
              activeDocumentId={activeDocumentId}
              activeDocumentName={activeDocumentName}
              isSessionLoading={sessionQuery.isLoading}
              authMode={apiSettings.authMode}
              hasApiKey={apiSettings.hasApiKey}
              authReady={authReady}
              authIdentity={authIdentity}
              authError={authError}
              onSignIn={() => signInMutation.mutate()}
              onSignOut={() => signOutMutation.mutate()}
              authActionBusy={signInMutation.isPending || signOutMutation.isPending}
            />
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage authIdentity={authIdentity} />} />
          <Route
            path="documents"
            element={
              <DocumentsPage
                sessionId={sessionId}
                activeDocumentId={activeDocumentId}
                onSessionChanged={refreshSession}
              />
            }
          />
          <Route
            path="ask"
            element={
              <AskPage
                sessionId={sessionId}
                activeDocumentId={activeDocumentId}
                activeDocumentName={activeDocumentName}
              />
            }
          />
          <Route
            path="sessions"
            element={
              <SessionsPage
                currentSessionId={sessionId}
                currentActiveDocumentName={activeDocumentName}
                onSessionSelected={selectSession}
              />
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
