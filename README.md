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
