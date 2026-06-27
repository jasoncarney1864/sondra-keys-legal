import { useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppLayout } from './app/AppLayout'
import { getApiSettings, getCurrentSession } from './lib/api/client'
import { LEGAL_SITE_ID, PDF_BUILDER_SITE_ID, PORTAL_ACCESS_STORAGE_KEY } from './lib/portal/sites'
import {
  initializeOidcUser,
  loginWithOidcPopup,
  logoutOidcPopup,
} from './lib/auth/oidc'
import { AskPage } from './pages/AskPage'
import { DashboardPage } from './pages/DashboardPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { HelpPage } from './pages/HelpPage'
import { PdfBuilderPage } from './pages/PdfBuilderPage'
import { PortalHomePage } from './pages/PortalHomePage'
import { SessionsPage } from './pages/SessionsPage'

const SESSION_STORAGE_KEY = 'sondra.frontend.current_session_id'

function PortalSiteGate({ children, siteId }: { children: ReactNode; siteId: string }) {
  const location = useLocation()
  const hasPortalEntry =
    window.sessionStorage.getItem(PORTAL_ACCESS_STORAGE_KEY) === siteId

  if (!hasPortalEntry) {
    const from = `${location.pathname}${location.search}`
    return <Navigate to={`/?from=${encodeURIComponent(from)}`} replace />
  }

  return <>{children}</>
}

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
      window.sessionStorage.removeItem(PORTAL_ACCESS_STORAGE_KEY)
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

  const sessionDisplayLabel = sessionId
    ? `Session ${sessionId.length <= 12 ? sessionId : sessionId.slice(0, 8)}`
    : null

  const currentUserId = sessionQuery.data?.user_id ?? null

  function selectSession(nextSessionId: string | null) {
    setSessionId(nextSessionId)
    if (nextSessionId) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId)
    } else {
      window.localStorage.removeItem(SESSION_STORAGE_KEY)
    }
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<PortalHomePage authIdentity={authIdentity} />} />
        <Route
          path="/legal"
          element={
            <PortalSiteGate siteId={LEGAL_SITE_ID}>
              <AppLayout
                sessionId={sessionId}
                sessionDisplayLabel={sessionDisplayLabel}
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
            </PortalSiteGate>
          }
        >
          <Route index element={<Navigate to="/legal/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage authIdentity={authIdentity} />} />
          <Route path="help" element={<HelpPage />} />
          <Route
            path="documents"
            element={
              <DocumentsPage
                sessionId={sessionId}
                currentUserId={currentUserId}
              />
            }
          />
          <Route
            path="ask"
            element={
              <AskPage
                sessionId={sessionId}
              />
            }
          />
          <Route
            path="sessions"
            element={
              <SessionsPage
                currentSessionId={sessionId}
                onSessionSelected={selectSession}
              />
            }
          />
        </Route>
        <Route
          path="/pdf-builder"
          element={
            <PortalSiteGate siteId={PDF_BUILDER_SITE_ID}>
              <PdfBuilderPage />
            </PortalSiteGate>
          }
        />
        <Route path="/dashboard" element={<Navigate to="/?from=%2Fdashboard" replace />} />
        <Route path="/documents" element={<Navigate to="/?from=%2Fdocuments" replace />} />
        <Route path="/ask" element={<Navigate to="/?from=%2Fask" replace />} />
        <Route path="/sessions" element={<Navigate to="/?from=%2Fsessions" replace />} />
        <Route path="/help" element={<Navigate to="/?from=%2Fhelp" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
