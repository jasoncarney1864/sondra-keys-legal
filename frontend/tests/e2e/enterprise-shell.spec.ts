import { expect, test, type Page, type Route } from '@playwright/test'

type SessionRecord = {
  session_id: string
  active_document_id: string | null
  active_document_file_name: string | null
  created_at: string
  last_accessed_at: string
  expires_at: string
}

type DocumentRecord = {
  document_id: string
  file_name: string
  file_size_bytes: number
  upload_timestamp: string
  page_count: number | null
  processing_status: string
  uploaded_by_user_id: string | null
}

type HudSourceRecord = {
  source_id: string
  document_id: string
  title: string
  source_url: string
  regulation_id: string
  effective_date: string | null
  processing_status: string
  operation: string
  last_synced_at: string
}

type MockState = {
  currentSessionId: string
  sessions: SessionRecord[]
  documents: DocumentRecord[]
  hudSources: HudSourceRecord[]
  uploadCalls: number
}

function utcNow(): string {
  return new Date().toISOString()
}

function fulfill(route: Route, payload: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

async function attachMockApi(page: Page, state: MockState) {
  await page.route('**/api/sessions/*', async (route) => {
    const request = route.request()
    if (request.method() !== 'DELETE') {
      return route.fallback()
    }

    const sessionId = request.url().split('/').pop()
    if (!sessionId) {
      return fulfill(route, { detail: 'Session not found.' }, 404)
    }

    const exists = state.sessions.some((session) => session.session_id === sessionId)
    if (!exists) {
      return fulfill(route, { detail: 'Session not found.' }, 404)
    }

    state.sessions = state.sessions.filter((session) => session.session_id !== sessionId)

    return route.fulfill({
      status: 204,
      body: '',
    })
  })

  await page.route('**/api/sessions/current', async (route) => {
    const active = state.sessions.find((session) => session.session_id === state.currentSessionId)
    if (!active) {
      return fulfill(route, { detail: 'Session not found.' }, 404)
    }

    return fulfill(route, {
      session_id: active.session_id,
      user_id: 'local-dev-user',
      active_document_id: active.active_document_id,
      created_at: active.created_at,
      expires_at: active.expires_at,
    })
  })

  await page.route('**/api/sessions', async (route) => {
    const request = route.request()
    const requestSessionId = request.headers()['x-session-id']

    if (requestSessionId && !state.sessions.some((session) => session.session_id === requestSessionId)) {
      return fulfill(route, { detail: 'Session not found.' }, 404)
    }

    if (request.method() === 'POST') {
      const index = state.sessions.length + 1
      const nextSession: SessionRecord = {
        session_id: `session-${index}`,
        active_document_id: null,
        active_document_file_name: null,
        created_at: utcNow(),
        last_accessed_at: utcNow(),
        expires_at: new Date(Date.now() + 86_400_000).toISOString(),
      }

      state.sessions.unshift(nextSession)
      state.currentSessionId = nextSession.session_id

      return fulfill(route, {
        session_id: nextSession.session_id,
        user_id: 'local-dev-user',
        active_document_id: null,
        created_at: nextSession.created_at,
        expires_at: nextSession.expires_at,
      }, 201)
    }

    return fulfill(route, {
      sessions: state.sessions,
      total_count: state.sessions.length,
    })
  })

  await page.route('**/api/documents?**', async (route) => {
    return fulfill(route, {
      documents: state.documents,
      total_count: state.documents.length,
      skip: 0,
      limit: 50,
    })
  })

  await page.route('**/api/documents/*', async (route) => {
    const request = route.request()
    if (request.method() !== 'DELETE') {
      return route.fallback()
    }

    const pathname = new URL(request.url()).pathname
    const segments = pathname.split('/').filter(Boolean)
    if (segments.length !== 3 || segments[0] !== 'api' || segments[1] !== 'documents') {
      return route.fallback()
    }

    const documentId = segments[2]
    const exists = state.documents.some((document) => document.document_id === documentId)
    if (!exists) {
      return route.fulfill({ status: 204, body: '' })
    }

    state.documents = state.documents.filter((document) => document.document_id !== documentId)
    state.sessions = state.sessions.map((session) =>
      session.active_document_id === documentId
        ? {
            ...session,
            active_document_id: null,
            active_document_file_name: null,
          }
        : session,
    )

    return route.fulfill({ status: 204, body: '' })
  })

  await page.route('**/api/documents/*/download', async (route) => {
    const segments = new URL(route.request().url()).pathname.split('/')
    const documentId = segments[segments.length - 2]
    const documentRecord = state.documents.find((document) => document.document_id === documentId)

    if (!documentRecord) {
      return fulfill(route, { detail: 'Document not found.' }, 404)
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      headers: {
        'content-disposition': `attachment; filename="${documentRecord.file_name}"`,
      },
      body: '%PDF-1.4\n%Mock\n',
    })
  })

  await page.route('**/api/documents/upload', async (route) => {
    state.uploadCalls += 1
    if (state.uploadCalls === 1) {
      return fulfill(route, {
        document_id: 'doc-uploaded',
        file_name: 'smoke-query.pdf',
        status: 'pending',
        message: 'Document queued for processing. Check status via GET /{document_id}.',
        chunks_created: 0,
      }, 202)
    }

    return fulfill(route, {
      document_id: 'doc-uploaded',
      file_name: 'smoke-query.pdf',
      status: 'completed',
      message: 'An identical document has already been processed.',
      chunks_created: 0,
    }, 202)
  })

  await page.route('**/api/hud/sources**', async (route) => {
    return fulfill(route, {
      sources: state.hudSources,
      total_count: state.hudSources.length,
    })
  })

  await page.route('**/api/hud/sync**', async (route) => {
    state.hudSources = state.hudSources.map((source) => ({
      ...source,
      operation: 'existing',
      last_synced_at: utcNow(),
    }))

    return fulfill(route, {
      ingested_count: 0,
      updated_count: 0,
      skipped_count: state.hudSources.length,
      failed_count: 0,
      sources: state.hudSources,
      strategy_note:
        'HUD User offers free dataset APIs (FMR/Income Limits) but not complete legal text. This endpoint ingests authoritative HUD/public legal-policy sources for grounded Q&A.',
    })
  })

  await page.route('**/api/query', async (route) => {
    const body = route.request().postDataJSON() as { question: string; document_ids?: string[] }
    const effectiveDocumentIds = body.document_ids?.length ? body.document_ids : []

    if (effectiveDocumentIds.length === 0) {
      return fulfill(
        route,
        {
          detail: 'Select at least one document in explicit document scope.',
        },
        400,
      )
    }

    return fulfill(route, {
      question: body.question,
      answer: 'Skyline requires vehicles to use designated parking spaces only.',
      citations: [
        {
          document_id: effectiveDocumentIds[0],
          file_name: 'Skyline-Mobile-Home-Park-Rules-Regs.pdf',
          chunk_index: 4,
          page_number: 2,
          section_title: 'Parking',
          snippet: 'Parking is restricted to assigned spaces and fire lanes must remain clear.',
        },
      ],
      model_used: 'gpt-4.1-mini',
      latency_ms: 42.5,
    })
  })
}

function createBaseState(): MockState {
  const initialSession: SessionRecord = {
    session_id: 'session-1',
    active_document_id: null,
    active_document_file_name: null,
    created_at: utcNow(),
    last_accessed_at: utcNow(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  }

  return {
    currentSessionId: initialSession.session_id,
    sessions: [initialSession],
    documents: [
      {
        document_id: 'doc-1',
        file_name: 'Skyline-Mobile-Home-Park-Rules-Regs.pdf',
        file_size_bytes: 240_000,
        upload_timestamp: '2026-06-26T12:00:00.000Z',
        page_count: 12,
        processing_status: 'completed',
        uploaded_by_user_id: 'local-dev-user',
      },
      {
        document_id: 'doc-2',
        file_name: 'Alpha-Lease-Agreement.pdf',
        file_size_bytes: 110_000,
        upload_timestamp: '2026-06-20T12:00:00.000Z',
        page_count: 8,
        processing_status: 'completed',
        uploaded_by_user_id: 'local-dev-user',
      },
      {
        document_id: 'doc-3',
        file_name: 'Tenant-Rights-Overview.pdf',
        file_size_bytes: 180_000,
        upload_timestamp: '2026-06-24T12:00:00.000Z',
        page_count: 10,
        processing_status: 'completed',
        uploaded_by_user_id: 'local-dev-user',
      },
    ],
    hudSources: [
      {
        source_id: 'fair-housing-act-overview',
        document_id: 'hud-doc-1',
        title: 'HUD Fair Housing Act Overview',
        source_url: 'https://www.hud.gov/program_offices/fair_housing_equal_opp/fair_housing_act_overview',
        regulation_id: '42 U.S.C. 3601-3619 (Fair Housing Act)',
        effective_date: '1968-04-11',
        processing_status: 'completed',
        operation: 'ingested',
        last_synced_at: utcNow(),
      },
      {
        source_id: 'cfr-title-24-part-5',
        document_id: 'hud-doc-2',
        title: '24 CFR Part 5: General HUD Program Requirements',
        source_url: 'https://www.ecfr.gov/current/title-24/subtitle-A/part-5',
        regulation_id: '24 CFR Part 5',
        effective_date: 'current',
        processing_status: 'completed',
        operation: 'ingested',
        last_synced_at: utcNow(),
      },
    ],
    uploadCalls: 0,
  }
}

async function enterLegalWorkspace(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Open Sondra Keys Legal' }).click()
  await expect(page.getByRole('heading', { level: 2, name: /Good to see you/i })).toBeVisible()
}

test('portal is default landing page and renders site registry cards', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')

  await expect(page.getByRole('heading', { level: 2, name: /Welcome to Sondra Keys/i })).toBeVisible()
  await expect(page.getByRole('heading', { level: 3, name: 'Sondra Keys Legal' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 3, name: 'Sondra Keys PDF Builder' })).toBeVisible()
})

test('portal navigation opens Sondra Keys Legal workspace', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('button', { name: 'Open Sondra Keys Legal' }).click()

  await expect(page).toHaveURL(/\/legal\/dashboard$/)
  await expect(page.getByRole('navigation', { name: 'Primary' }).getByText('Sondra Keys Portal')).toBeVisible()
})

test('portal navigation opens PDF Builder workspace', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('button', { name: 'Open Sondra Keys PDF Builder' }).click()

  await expect(page).toHaveURL(/\/pdf-builder$/)
  await expect(page.getByRole('heading', { level: 2, name: /Build a PDF from your page images/i })).toBeVisible()
})

test('direct legacy route redirects to portal then resumes in legal workspace', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/dashboard')

  await expect(page).toHaveURL(/\/?\?from=%2Fdashboard$/)
  await expect(page.getByText(/route now opens through the Sondra Keys portal/i)).toBeVisible()

  await page.getByRole('button', { name: 'Open Sondra Keys Legal' }).click()
  await expect(page).toHaveURL(/\/legal\/dashboard$/)
})

test('session creation is reflected in the sessions view', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Sessions', exact: true }).click()

  await page.getByRole('button', { name: 'Create session' }).click()
  await page.getByRole('dialog', { name: 'Create session' }).getByRole('button', { name: 'Create now' }).click()

  await expect(page.getByRole('cell', { name: 'session-2' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Current', exact: true })).toBeVisible()
})

test('dashboard is the default landing page and top navigation item', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)

  await expect(page.getByRole('heading', { level: 2, name: /Good to see you/i })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Primary' }).locator('a').nth(1)).toHaveText('Dashboard')
  await expect(page.getByText(/^Session session-1$/)).toBeVisible()
})

test('explicit document scope requires selection and then succeeds', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Ask', exact: true }).click()

  await page.getByLabel('Prompt').fill('What are the Skyline parking rules?')
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page.getByText(/Select at least one document to ask this question/i)).toBeVisible()

  await expect(page.getByRole('columnheader', { name: 'Select' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Name/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Date created/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Status/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Size/ })).toBeVisible()

  const scopeTable = page.locator('.ask-scope-table')
  await page.getByRole('button', { name: /^Name/ }).click()
  await expect(scopeTable.locator('tbody tr').first().locator('td').nth(1)).toContainText('Alpha-Lease-Agreement.pdf')
  await page.getByRole('button', { name: /^Date created/ }).click()
  await expect(scopeTable.locator('tbody tr').first().locator('td').nth(1)).toContainText('Skyline-Mobile-Home-Park-Rules-Regs.pdf')

  await page.getByRole('checkbox', { name: /Skyline-Mobile-Home-Park-Rules-Regs.pdf/i }).check()
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page.getByText('Skyline requires vehicles to use designated parking spaces only.')).toBeVisible()
  await expect(page.getByText('Citations (1)')).toBeVisible()
})

test('shift+enter submits ask question while enter keeps newline behavior', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Ask', exact: true }).click()

  const prompt = page.getByLabel('Prompt')
  await prompt.fill('What are the Skyline parking rules?')
  await prompt.press('Shift+Enter')

  await expect(page.getByText(/Select at least one document to ask this question/i)).toBeVisible()

  await page.getByRole('checkbox', { name: /Skyline-Mobile-Home-Park-Rules-Regs.pdf/i }).check()
  await prompt.press('Enter')
  await expect(page.getByText('Skyline requires vehicles to use designated parking spaces only.')).toHaveCount(0)

  await prompt.press('Shift+Enter')
  await expect(page.getByText('Skyline requires vehicles to use designated parking spaces only.')).toBeVisible()
})

test('document upload displays queued then deduped reuse message', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Documents', exact: true }).click()

  await page.setInputFiles('input[type="file"]', {
    name: 'smoke-query.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%Mock\n'),
  })
  await page.getByRole('button', { name: 'Upload' }).click()
  await expect(page.getByText(/Document queued for processing/i)).toBeVisible()

  await page.setInputFiles('input[type="file"]', {
    name: 'smoke-query.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%Mock\n'),
  })
  await page.getByRole('button', { name: 'Upload' }).click()
  await expect(page.getByText(/identical document has already been processed/i)).toBeVisible()
})

test('documents page can request original file download', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Documents', exact: true }).click()

  await page.getByRole('button', { name: 'Download' }).first().click()
  await expect(page.getByText(/Starting download for/i)).toBeVisible()
})

test('documents page deletes failed and completed rows with hard-delete warning', async ({ page }) => {
  const state = createBaseState()
  state.documents = state.documents.map((document) =>
    document.document_id === 'doc-2'
      ? {
          ...document,
          processing_status: 'failed',
        }
      : document,
  )
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Documents', exact: true }).click()

  const failedRow = page.getByRole('row', { name: /Alpha-Lease-Agreement.pdf/i })
  await failedRow.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByRole('dialog', { name: 'Delete document' })).toBeVisible()
  await expect(page.getByText(/remove the row and all linked artifacts/i)).toBeVisible()
  await page.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(page.getByRole('row', { name: /Alpha-Lease-Agreement.pdf/i })).toHaveCount(0)

  const completedRow = page.getByRole('row', { name: /Skyline-Mobile-Home-Park-Rules-Regs.pdf/i })
  await completedRow.getByRole('button', { name: 'Delete' }).click()
  await page.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(page.getByRole('row', { name: /Skyline-Mobile-Home-Park-Rules-Regs.pdf/i })).toHaveCount(0)
})

test('deleting current session does not leave sticky Not Found error', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await enterLegalWorkspace(page)
  await page.getByRole('link', { name: 'Sessions', exact: true }).click()

  page.once('dialog', async (dialog) => {
    await dialog.accept()
  })

  await page.getByRole('button', { name: 'Delete session' }).first().click()

  await expect(page.getByText(/Not Found/i)).toHaveCount(0)
  await expect(page.getByText('No sessions found.')).toBeVisible()
})
