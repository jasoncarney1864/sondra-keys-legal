# sondra-keys-legal

Sondra Keys is a multi-site legal workspace portal:
- Sondra Keys Legal: upload documents and ask citation-backed questions.
- Sondra Keys PDF Builder: build PDFs from image pages.

## Core loop
1. Open a site from the portal.
2. Sync or upload source documents.
3. Ask plain-language questions with explicit source scope.
4. Review grounded answers with citations.

## HUD source sync in Legal workspace
HUD/public legal sources are synced into the Legal workspace retrieval corpus via:
- `POST /api/hud/sync`
- `GET /api/hud/sources`

## Google sign-in allowlist

To require login with specific Gmail accounts only, run in OIDC mode with Google token validation and allowlist checks.

Frontend environment (`frontend/.env.local`):

```env
VITE_AUTH_MODE=oidc
VITE_OIDC_PROVIDER=google
VITE_OIDC_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
VITE_OIDC_SCOPES=openid profile email
```

Backend environment (`backend/.env.local` or deployment env vars):

```env
SECURITY_AUTH_MODE=oidc
SECURITY_OIDC_ISSUER=https://accounts.google.com
SECURITY_OIDC_AUDIENCE=your-google-oauth-client-id.apps.googleusercontent.com
SECURITY_OIDC_JWKS_URL=https://www.googleapis.com/oauth2/v3/certs
SECURITY_OIDC_USER_ID_CLAIM=sub
SECURITY_OIDC_EMAIL_CLAIM=email
SECURITY_OIDC_ALLOWED_EMAILS=jasonbrookecarney@gmail.com,sandrakeys62@gmail.com,rloth101390@gmail.com
```

Behavior:
- Users must sign in with Google before they can call backend APIs.
- Only the listed email addresses are allowed.
- Allowed users share the same app permissions (admin-equivalent in current app model).

## Local startup helper

To avoid local API key mismatches between frontend and backend, use:

```powershell
pwsh -File backend/scripts/start_local_dev.ps1
```

What it does:
- Reads `VITE_API_KEY` from `frontend/.env.local`.
- Loads required backend Azure/OpenAI settings from process environment or `backend/.env.local` (`backend/.env` fallback).
- Starts the frontend Vite server in a separate PowerShell window.
- Starts the backend and sets `SECURITY_API_KEY` to match the frontend key.

If required backend Azure/OpenAI settings are missing, the script exits with a list of missing variable names.

## Kubernetes incident bundle (one command)

When a cluster issue happens, run:

```powershell
pwsh -File backend/scripts/collect_k8s_incident.ps1
```

Optional flags:

```powershell
pwsh -File backend/scripts/collect_k8s_incident.ps1 -Namespace default -MaxProblemPods 10 -LogTail 500
```

Collect and automatically open the generated summary:

```powershell
pwsh -File backend/scripts/collect_k8s_incident_and_open_summary.ps1
```

PowerShell profile aliases (short commands):

```powershell
# Add once to your PowerShell profile
# notepad $PROFILE

function k8s-incident {
	pwsh -File "c:/Users/jason/OneDrive/Documents/Work/sondra-keys-legal/backend/scripts/collect_k8s_incident.ps1" @args
}

function k8s-incident-open {
	pwsh -File "c:/Users/jason/OneDrive/Documents/Work/sondra-keys-legal/backend/scripts/collect_k8s_incident_and_open_summary.ps1" @args
}
```

After saving your profile, restart PowerShell (or run `. $PROFILE`) and use:
- `k8s-incident`
- `k8s-incident-open`

What it collects into `artifacts/k8s-incidents/<timestamp>/`:
- Cluster metadata (`kubectl version`, context, cluster info).
- Node and workload inventory (pods, deployments, statefulsets, daemonsets, services, ingress).
- Events and resource top output.
- Describe + logs (and previous logs) for problem pods.
- `SUMMARY.md` with quick triage findings and warnings.

It also creates a zip archive next to the folder for easy sharing.
