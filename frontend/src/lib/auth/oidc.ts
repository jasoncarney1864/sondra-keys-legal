import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
} from '@azure/msal-browser'

export type AuthMode = 'api_key' | 'oidc'

export type AuthSettings = {
  mode: AuthMode
  apiKey: string
  hasApiKey: boolean
  oidcConfigured: boolean
  oidcScopes: string[]
}

const AUTH_MODE =
  ((import.meta.env.VITE_AUTH_MODE ?? 'api_key').trim().toLowerCase() as AuthMode) === 'oidc'
    ? 'oidc'
    : 'api_key'

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

let msalClient: PublicClientApplication | null = null

export type OidcUser = {
  homeAccountId: string
  username: string
  name: string
}

export function getAuthSettings(): AuthSettings {
  return {
    mode: AUTH_MODE,
    apiKey: API_KEY,
    // In deployed container builds, API auth can be injected by nginx reverse proxy.
    hasApiKey: API_KEY.length > 0 || USES_PROXY_API_AUTH,
    oidcConfigured: OIDC_CLIENT_ID.length > 0 && OIDC_TENANT_ID.length > 0,
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

  const client = await getMsalClient()
  return toOidcUser(getActiveAccount(client))
}

export async function loginWithOidcPopup(): Promise<OidcUser> {
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
