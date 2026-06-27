# HUD Laws Source Strategy

## Status
Accepted

## Date
2026-06-27

## Context
Sondra Keys needs a HUD-focused legal Q&A site with reliable citations. During discovery, HUD User confirmed free API access for Fair Market Rents and Income Limits datasets with token registration. Those APIs are useful data feeds, but they are not a complete legal-text source for statutory or regulatory Q&A.

Authoritative links used during discovery:
- HUD User Datasets API landing page: https://www.huduser.gov/portal/dataset/fmr-api.html
- HUD User API terms link from the same page: https://www.huduser.gov/portal/dataset/fmr-api.html#termsofservice
- HUD Fair Housing Act overview: https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview
- eCFR Title 24 Part 5: https://www.ecfr.gov/current/title-24/subtitle-A/part-5

## Decision
Use a hybrid source strategy with legal-text-first ingestion:
1. Primary source corpus: curated authoritative HUD/public legal and policy pages ingested into the existing chunk/index pipeline.
2. Supplemental source option: HUD User API datasets (FMR/Income Limits) can be added as structured context, but not treated as canonical legal text.
3. Deterministic identity and dedupe: each curated source maps to deterministic UUIDv5 document identity (`hud-source:<source_id>`), so sync is idempotent.
4. Safe refresh model: store source content hash and sync timestamp in a local state file, skip unchanged sources, allow explicit force refresh.

## Consequences
Positive:
- HUD Ask can return citation-backed answers tied to known authoritative source URLs.
- Sync is resilient (retry/backoff) and idempotent (content hash + deterministic IDs).
- Existing retrieval stack is reused with explicit source scope in frontend UX.

Trade-offs:
- Curated source set needs maintenance as HUD/public pages evolve.
- HTML extraction quality varies by site template.
- Dataset APIs still require separate modeling when numeric program data is needed.

## Operational Notes
- Backend endpoints:
  - `POST /api/hud/sync` for source synchronization.
  - `GET /api/hud/sources` for user-visible HUD corpus scope.
- Environment settings use `HUD_` prefix (sync toggles, fetch timeout/retry/backoff, optional token, state path).
- Frontend HUD site is available at `/hud-laws` through the portal registry.
