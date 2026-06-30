import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
} from '@azure/msal-browser'

export type AuthMode = 'api_key' | 'oidc'
export type OidcProvider = 'msal' | 'google'

export type AuthSettings = {
  mode: AuthMode
  apiKey: string
  hasApiKey: boolean
  oidcConfigured: boolean
  oidcProvider: OidcProvider
  oidcScopes: string[]
}

const AUTH_MODE =
  ((import.meta.env.VITE_AUTH_MODE ?? 'api_key').trim().toLowerCase() as AuthMode) === 'oidc'
    ? 'oidc'
    : 'api_key'
const OIDC_PROVIDER: OidcProvider =
  (import.meta.env.VITE_OIDC_PROVIDER ?? 'msal').trim().toLowerCase() === 'google'
    ? 'google'
    : 'msal'

const API_KEY = (import.meta.env.VITE_API_KEY ?? '').trim()
const IS_LOCAL_HOST = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const USES_PROXY_API_AUTH = API_KEY.length === 0 && !IS_LOCAL_HOST
const OIDC_CLIENT_ID = (import.meta.env.VITE_OIDC_CLIENT_ID ?? '').trim()
const OIDC_TENANT_ID = (import.meta.env.VITE_OIDC_TENANT_ID ?? '').trim()
const OIDC_SCOPES = ((import.meta.env.VITE_OIDC_SCOPES ?? 'openid profile email') as string)
  .split(/[\s,]+/)
  .map((value) => value.trim())
  .filter(Boolean)
const OIDC_REDIRECT_URI = (import.meta.env.VITE_OIDC_REDIRECT_URI ?? window.location.origin).trim()
const GOOGLE_GSI_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
const GOOGLE_ID_TOKEN_STORAGE_KEY = 'sondra.auth.google.id_token'

let msalClient: PublicClientApplication | null = null
let googleScriptPromise: Promise<void> | null = null

export type OidcUser = {
  homeAccountId: string
  username: string
  name: string
}

type GoogleCredentialResponse = {
  credential?: string
}

type GooglePromptMomentNotification = {
  isNotDisplayed?: () => boolean
  isSkippedMoment?: () => boolean
  getNotDisplayedReason?: () => string
  getSkippedReason?: () => string
}

type GoogleIdClient = {
  initialize: (options: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
    ux_mode?: 'popup' | 'redirect'
    auto_select?: boolean
    context?: 'signin' | 'signup' | 'use'
    nonce?: string
  }) => void
  prompt: (listener?: (notification: GooglePromptMomentNotification) => void) => void
  disableAutoSelect: () => void
  revoke: (hint: string, done: () => void) => void
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: GoogleIdClient
      }
    }
  }
}

function isOidcConfigured(): boolean {
  if (OIDC_PROVIDER === 'google') {
    return OIDC_CLIENT_ID.length > 0
  }
  return OIDC_CLIENT_ID.length > 0 && OIDC_TENANT_ID.length > 0
}

export function getAuthSettings(): AuthSettings {
  return {
    mode: AUTH_MODE,
    apiKey: API_KEY,
    // In deployed container builds, API auth can be injected by nginx reverse proxy.
    hasApiKey: API_KEY.length > 0 || USES_PROXY_API_AUTH,
    oidcConfigured: isOidcConfigured(),
    oidcProvider: OIDC_PROVIDER,
    oidcScopes: OIDC_SCOPES,
  }
}

function toOidcUser(account: AccountInfo | null): OidcUser | null {
  if (!account) {
    return null
  }

  return {
    homeAccountId: account.homeAccountId,
    username: account.username,
    name: account.name ?? account.username,
  }
}

async function getMsalClient(): Promise<PublicClientApplication> {
  if (OIDC_PROVIDER !== 'msal') {
    throw new Error('MSAL client requested while VITE_OIDC_PROVIDER is not msal.')
  }

  const settings = getAuthSettings()
  if (!settings.oidcConfigured) {
    throw new Error('OIDC is enabled but VITE_OIDC_CLIENT_ID or VITE_OIDC_TENANT_ID is missing.')
  }

  if (!msalClient) {
    msalClient = new PublicClientApplication({
      auth: {
        clientId: OIDC_CLIENT_ID,
        authority: `https://login.microsoftonline.com/${OIDC_TENANT_ID}`,
        redirectUri: OIDC_REDIRECT_URI,
      },
      cache: {
        cacheLocation: 'localStorage',
      },
    })
    await msalClient.initialize()
  }

  return msalClient
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split('.')
  if (parts.length < 2) {
    throw new Error('OIDC token has invalid JWT format.')
  }

  const payloadPart = parts[1]
  const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4 || 4)) % 4)
  const json = atob(padded)
  return JSON.parse(json) as Record<string, unknown>
}

function parseGoogleUserFromToken(token: string): OidcUser | null {
  try {
    const payload = decodeJwtPayload(token)
    const sub = String(payload.sub ?? '').trim()
    const email = String(payload.email ?? '').trim()
    const name = String(payload.name ?? '').trim()
    const username = email || sub
    const displayName = name || email || sub

    if (!sub || !username || !displayName) {
      return null
    }

    return {
      homeAccountId: sub,
      username,
      name: displayName,
    }
  } catch {
    return null
  }
}

function getStoredGoogleIdToken(): string | null {
  const token = window.localStorage.getItem(GOOGLE_ID_TOKEN_STORAGE_KEY)
  if (!token) {
    return null
  }

  try {
    const payload = decodeJwtPayload(token)
    const expRaw = payload.exp
    const exp = typeof expRaw === 'number' ? expRaw : Number(expRaw)
    if (Number.isFinite(exp) && Date.now() >= (exp * 1000) - 60000) {
      window.localStorage.removeItem(GOOGLE_ID_TOKEN_STORAGE_KEY)
      return null
    }
  } catch {
    window.localStorage.removeItem(GOOGLE_ID_TOKEN_STORAGE_KEY)
    return null
  }

  return token
}

function setStoredGoogleIdToken(token: string): void {
  window.localStorage.setItem(GOOGLE_ID_TOKEN_STORAGE_KEY, token)
}

async function ensureGoogleScriptLoaded(): Promise<void> {
  if (window.google?.accounts?.id) {
    return
  }

  if (!googleScriptPromise) {
    googleScriptPromise = new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>(`script[src="${GOOGLE_GSI_SCRIPT_SRC}"]`)
      if (existing) {
        existing.addEventListener('load', () => resolve())
        existing.addEventListener('error', () => reject(new Error('Failed to load Google Identity script.')))
        return
      }

      const script = document.createElement('script')
      script.src = GOOGLE_GSI_SCRIPT_SRC
      script.async = true
      script.defer = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Failed to load Google Identity script.'))
      document.head.appendChild(script)
    })
  }

  await googleScriptPromise

  if (!window.google?.accounts?.id) {
    throw new Error('Google Identity API did not initialize correctly.')
  }
}

async function startGooglePromptSignIn(): Promise<OidcUser> {
  if (!OIDC_CLIENT_ID) {
    throw new Error('OIDC is enabled but VITE_OIDC_CLIENT_ID is missing.')
  }

  await ensureGoogleScriptLoaded()

  return new Promise<OidcUser>((resolve, reject) => {
    const idClient = window.google?.accounts?.id
    if (!idClient) {
      reject(new Error('Google Identity API is unavailable.'))
      return
    }

    let settled = false
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true
        reject(new Error('Google sign-in timed out. Try again.'))
      }
    }, 120000)

    idClient.initialize({
      client_id: OIDC_CLIENT_ID,
      ux_mode: 'popup',
      auto_select: false,
      context: 'signin',
      callback: (response: GoogleCredentialResponse) => {
        if (settled) {
          return
        }

        const credential = String(response.credential ?? '').trim()
        if (!credential) {
          settled = true
          window.clearTimeout(timer)
          reject(new Error('Google sign-in returned no ID token.'))
          return
        }

        setStoredGoogleIdToken(credential)
        const user = parseGoogleUserFromToken(credential)
        if (!user) {
          settled = true
          window.clearTimeout(timer)
          reject(new Error('Google sign-in token could not be parsed.'))
          return
        }

        settled = true
        window.clearTimeout(timer)
        resolve(user)
      },
    })

    idClient.prompt((notification: GooglePromptMomentNotification) => {
      if (settled) {
        return
      }

      const notDisplayed = notification.isNotDisplayed?.() === true
      const skipped = notification.isSkippedMoment?.() === true
      if (notDisplayed || skipped) {
        settled = true
        window.clearTimeout(timer)
        const reason = notification.getNotDisplayedReason?.() ?? notification.getSkippedReason?.() ?? 'unknown reason'
        reject(new Error(`Google sign-in prompt was not shown: ${reason}.`))
      }
    })
  })
}

function getActiveAccount(client: PublicClientApplication): AccountInfo | null {
  const active = client.getActiveAccount()
  if (active) {
    return active
  }

  const accounts = client.getAllAccounts()
  if (accounts.length === 0) {
    return null
  }

  client.setActiveAccount(accounts[0])
  return accounts[0]
}

export async function initializeOidcUser(): Promise<OidcUser | null> {
  const settings = getAuthSettings()
  if (settings.mode !== 'oidc') {
    return null
  }

  if (OIDC_PROVIDER === 'google') {
    const token = getStoredGoogleIdToken()
    if (!token) {
      return null
    }
    return parseGoogleUserFromToken(token)
  }

  const client = await getMsalClient()
  return toOidcUser(getActiveAccount(client))
}

export async function loginWithOidcPopup(): Promise<OidcUser> {
  if (OIDC_PROVIDER === 'google') {
    return startGooglePromptSignIn()
  }

  const client = await getMsalClient()
  const result = await client.loginPopup({
    scopes: OIDC_SCOPES,
    prompt: 'select_account',
  })

  client.setActiveAccount(result.account)
  const user = toOidcUser(result.account)
  if (!user) {
    throw new Error('OIDC sign-in succeeded but no account was returned.')
  }
  return user
}

export async function logoutOidcPopup(): Promise<void> {
  if (OIDC_PROVIDER === 'google') {
    const token = getStoredGoogleIdToken()
    const user = token ? parseGoogleUserFromToken(token) : null
    window.localStorage.removeItem(GOOGLE_ID_TOKEN_STORAGE_KEY)

    if (window.google?.accounts?.id) {
      window.google.accounts.id.disableAutoSelect()
      if (user?.username) {
        window.google.accounts.id.revoke(user.username, () => {
          // No-op callback; local state is already cleared.
        })
      }
    }
    return
  }

  const client = await getMsalClient()
  await client.logoutPopup()
}

async function acquireToken(client: PublicClientApplication, account: AccountInfo): Promise<AuthenticationResult> {
  try {
    return await client.acquireTokenSilent({
      account,
      scopes: OIDC_SCOPES,
    })
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      return client.acquireTokenPopup({
        scopes: OIDC_SCOPES,
      })
    }
    throw error
  }
}

export async function getOidcAccessToken(): Promise<string | null> {
  const settings = getAuthSettings()
  if (settings.mode !== 'oidc') {
    return null
  }

  if (OIDC_PROVIDER === 'google') {
    return getStoredGoogleIdToken()
  }

  const client = await getMsalClient()
  const account = getActiveAccount(client)
  if (!account) {
    return null
  }

  const result = await acquireToken(client, account)
  if (result.account) {
    client.setActiveAccount(result.account)
  }

  return result.accessToken || null
}
