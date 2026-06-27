# Sondra Keys Legal Frontend

React + TypeScript client for session-scoped document operations and Q&A.

## Views

- Documents: upload files, monitor processing status, set/clear active document.
- Ask: submit grounded legal questions using active document mode or explicit document scope.
- Sessions: create and switch sticky sessions.

## Environment

Create `frontend/.env.local` from `.env.example`:

```bash
cp .env.example .env.local
```

Required:

- `VITE_AUTH_MODE`: `api_key` or `oidc`.
- If `VITE_AUTH_MODE=api_key`: `VITE_API_KEY` must match backend `SECURITY_API_KEY`.
- If `VITE_AUTH_MODE=oidc`: configure `VITE_OIDC_CLIENT_ID` and `VITE_OIDC_TENANT_ID`.

Optional:

- `VITE_API_BASE_URL`: leave empty for local Vite proxy.
- `VITE_OIDC_SCOPES`: defaults to `openid profile email`.
- `VITE_OIDC_REDIRECT_URI`: defaults to current origin.

## Local Development

```bash
npm install
npm run dev
```

The Vite config proxies `/api/*` and `/health` to `http://localhost:8000`.

## Build And Lint

```bash
npm run lint
npm run build
```

## End-To-End Tests (Playwright)

```bash
npm run test:e2e:install
npm run test:e2e
```

These tests mock `/api/*` responses and validate session creation, active-document enforcement, and upload dedupe behavior through the UI.

## Azure Static Web Apps

- `staticwebapp.config.json` defines SPA fallback and route handling.
- `swa-cli.config.json` sets local SWA CLI build settings.

Run SWA local preview after installing SWA CLI:

```bash
npm run swa:start
```

## azd Deployment (Repo Root)

From repo root:

```bash
azd auth login
azd init
azd up
```

The root `azure.yaml` uses Bicep in `deploy/infra-swa` to provision a Static Web App and deploy the frontend service.
