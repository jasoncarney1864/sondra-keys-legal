import { NavLink, Outlet } from 'react-router-dom'

type AppLayoutProps = {
  sessionId: string | null
  sessionDisplayLabel: string | null
  isSessionLoading: boolean
  authMode: 'api_key' | 'oidc'
  hasApiKey: boolean
  authReady: boolean
  authIdentity: string | null
  authError: string | null
  onSignIn: () => void
  onSignOut: () => void
  authActionBusy: boolean
}

export function AppLayout({
  sessionId,
  sessionDisplayLabel,
  isSessionLoading,
  authMode,
  hasApiKey,
  authReady,
  authIdentity,
  authError,
  onSignIn,
  onSignOut,
  authActionBusy,
}: AppLayoutProps) {
  const showAuthWarning = authMode === 'api_key' ? !hasApiKey : !authReady

  return (
    <div className="shell">
      <aside className="shell-sidebar">
        <p className="eyebrow">Sondra Keys Legal</p>
        <h1 className="brand-title">Enterprise QA Console</h1>
        <p className="brand-subtitle">Session continuity with explicit document scope on Ask</p>

        <nav className="nav-list" aria-label="Primary">
          <NavLink to="/" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Sondra Keys Portal
          </NavLink>
          <NavLink to="/legal/dashboard" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Dashboard
          </NavLink>
          <NavLink to="/legal/ask" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Ask
          </NavLink>
          <NavLink to="/legal/documents" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Documents
          </NavLink>
          <NavLink to="/legal/sessions" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Sessions
          </NavLink>
          <NavLink
            to="/legal/help"
            className={({ isActive }) => (isActive ? 'nav-link nav-link-help active' : 'nav-link nav-link-help')}
          >
            Help
          </NavLink>
        </nav>

        <div className="status-stack">
          <div className="status-card">
            <p className="status-label">Current session</p>
            <p className="status-value">{isSessionLoading ? 'Resolving...' : sessionDisplayLabel ?? 'Not set'}</p>
            {!isSessionLoading && sessionId ? <p className="status-value mono">{sessionId}</p> : null}
          </div>
          <div className="status-card">
            <p className="status-label">Auth</p>
            <p className={`status-value ${(authMode === 'api_key' ? hasApiKey : authReady) ? 'ok' : 'warn'}`}>
              {authMode === 'api_key'
                ? hasApiKey
                  ? 'API key configured'
                  : 'API key missing'
                : authReady
                  ? authIdentity ?? 'OIDC signed in'
                  : 'OIDC sign-in required'}
            </p>
            {authMode === 'oidc' ? (
              <div className="auth-actions">
                {authReady ? (
                  <button type="button" className="ghost" onClick={onSignOut} disabled={authActionBusy}>
                    Sign out
                  </button>
                ) : (
                  <button type="button" className="primary" onClick={onSignIn} disabled={authActionBusy}>
                    Sign in
                  </button>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </aside>

      <main className="shell-main">
        {showAuthWarning ? (
          <div className="alert warn" role="alert">
            {authMode === 'api_key'
              ? 'VITE_API_KEY is not set. Add it in frontend/.env.local to authenticate requests.'
              : 'Sign in with OIDC to run backend requests.'}
          </div>
        ) : null}
        {authError ? (
          <div className="notice error" role="alert">
            {authError}
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  )
}
