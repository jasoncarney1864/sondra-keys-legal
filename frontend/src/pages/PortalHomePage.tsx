import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  LEGAL_SITE_ID,
  PORTAL_ACCESS_STORAGE_KEY,
  type PortalSite,
  getVisiblePortalSites,
  resolveLegalRouteFromPortal,
} from '../lib/portal/sites'

type PortalHomePageProps = {
  authIdentity: string | null
}

export function PortalHomePage({ authIdentity }: PortalHomePageProps) {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const requestedPath = searchParams.get('from')

  const legalTarget = useMemo(() => {
    return resolveLegalRouteFromPortal(requestedPath)
  }, [requestedPath])

  const visibleSites = useMemo(() => {
    return getVisiblePortalSites()
  }, [])

  function openSite(site: PortalSite, targetRoute: string) {
    window.sessionStorage.setItem(PORTAL_ACCESS_STORAGE_KEY, site.id)
    navigate(targetRoute)
  }

  return (
    <section className="portal-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Sondra Keys</p>
          <h2>{authIdentity ? `Welcome back, ${authIdentity}.` : 'Welcome to Sondra Keys.'}</h2>
          <p className="portal-lead muted">
            This is your launchpad for all Sondra Keys workspaces. Start here, then open the site you need.
          </p>
          {requestedPath ? (
            <p className="notice success">
              This route now opens through the Sondra Keys portal. Pick a site to continue.
            </p>
          ) : null}
        </div>
      </header>

      <div className="portal-grid">
        {visibleSites.map((site) => {
          const isActive = site.status === 'active'
          const targetRoute = site.id === LEGAL_SITE_ID ? legalTarget : site.route

          return (
            <article key={site.id} className="portal-card">
              <p className="eyebrow">{site.icon ?? 'Workspace'}</p>
              <h3>{site.title}</h3>
              <p>{site.description}</p>
              <p className={`status-pill ${isActive ? 'completed' : 'pending'}`}>
                {isActive ? 'Available' : 'Coming soon'}
              </p>
              <button
                type="button"
                className={isActive ? 'primary' : 'ghost'}
                disabled={!isActive}
                onClick={() => openSite(site, targetRoute)}
              >
                {isActive ? `Open ${site.title}` : `${site.title} (soon)`}
              </button>
            </article>
          )
        })}
      </div>

      <article className="card">
        <h3>Quick tip</h3>
        <p className="muted">
          To add a new child site later, register it in the portal site registry and it will appear here automatically.
        </p>
      </article>
    </section>
  )
}
