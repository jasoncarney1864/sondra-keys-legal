# sondra-keys-legal

Sondra Keys is a multi-site legal workspace portal:
- Sondra Keys Legal: upload documents and ask citation-backed questions.
- Sondra Keys PDF Builder: build PDFs from image pages.
- Sondra Keys HUD Laws: HUD-focused legal/policy Q&A over curated authoritative sources.

## Core loop
1. Open a site from the portal.
2. Sync or upload source documents.
3. Ask plain-language questions with explicit source scope.
4. Review grounded answers with citations.

## HUD Laws site
The HUD Laws site uses a curated source strategy documented in `docs/hud-laws-source-strategy.md`.

Backend endpoints:
- `POST /api/hud/sync` sync curated HUD/public legal sources into the retrieval corpus.
- `GET /api/hud/sources` list available HUD source documents for explicit Ask scope.

Environment variables (prefix `HUD_`):
- `HUD_SYNC_ENABLED`
- `HUD_SOURCE_STATE_PATH`
- `HUD_ENABLE_LIVE_FETCH`
- `HUD_FETCH_TIMEOUT_SECONDS`
- `HUD_FETCH_MAX_RETRIES`
- `HUD_FETCH_BACKOFF_SECONDS`
- `HUD_USER_API_TOKEN` (optional)

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
