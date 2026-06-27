export type PortalSiteStatus = 'active' | 'coming_soon'

export type PortalSite = {
  id: string
  title: string
  description: string
  route: string
  status: PortalSiteStatus
  visible: boolean
  icon?: string
}

export const PORTAL_ACCESS_STORAGE_KEY = 'sondra.portal.entry_site'
export const LEGAL_SITE_ID = 'sondra-keys-legal'
export const PDF_BUILDER_SITE_ID = 'sondra-keys-pdf-builder'
export const HUD_LAWS_SITE_ID = 'sondra-keys-hud-laws'

export const portalSites: PortalSite[] = [
  {
    id: LEGAL_SITE_ID,
    title: 'Sondra Keys Legal',
    description:
      'Session-based legal Q&A with document uploads, explicit document scope, and citation-backed answers.',
    route: '/legal/dashboard',
    status: 'active',
    visible: true,
    icon: 'Scale',
  },
  {
    id: PDF_BUILDER_SITE_ID,
    title: 'Sondra Keys PDF Builder',
    description:
      'Build a PDF from page images by uploading one-by-one or from a zip bundle, then selecting exactly what to include.',
    route: '/pdf-builder',
    status: 'active',
    visible: true,
    icon: 'Pages',
  },
  {
    id: HUD_LAWS_SITE_ID,
    title: 'Sondra Keys HUD Laws',
    description:
      'HUD-focused legal and policy Q&A with curated authoritative sources, explicit source scope, and citations.',
    route: '/hud-laws',
    status: 'active',
    visible: true,
    icon: 'Gov',
  },
]

export function getVisiblePortalSites(): PortalSite[] {
  return portalSites.filter((site) => site.visible)
}

export function resolveLegalRouteFromPortal(nextPath: string | null): string {
  if (!nextPath) {
    return '/legal/dashboard'
  }

  const legacyRouteMap: Record<string, string> = {
    '/dashboard': '/legal/dashboard',
    '/documents': '/legal/documents',
    '/ask': '/legal/ask',
    '/sessions': '/legal/sessions',
    '/help': '/legal/help',
  }

  if (legacyRouteMap[nextPath]) {
    return legacyRouteMap[nextPath]
  }

  if (nextPath.startsWith('/legal/')) {
    return nextPath
  }

  return '/legal/dashboard'
}
