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

type MockState = {
  currentSessionId: string
  sessions: SessionRecord[]
  documents: DocumentRecord[]
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

  await page.route('**/api/sessions/current/active-document', async (route) => {
    const request = route.request()
    if (request.method() === 'PUT') {
      const body = request.postDataJSON() as { document_id: string }
      const activeDocument = state.documents.find((document) => document.document_id === body.document_id)
      state.sessions = state.sessions.map((session) =>
        session.session_id === state.currentSessionId
          ? {
              ...session,
              active_document_id: body.document_id,
              active_document_file_name: activeDocument?.file_name ?? null,
              last_accessed_at: utcNow(),
            }
          : session,
      )
      return fulfill(route, {
        session_id: state.currentSessionId,
        active_document_id: body.document_id,
        active_document_file_name: activeDocument?.file_name ?? null,
      })
    }

    state.sessions = state.sessions.map((session) =>
      session.session_id === state.currentSessionId
        ? {
            ...session,
            active_document_id: null,
            active_document_file_name: null,
            last_accessed_at: utcNow(),
          }
        : session,
    )
    return fulfill(route, {
      session_id: state.currentSessionId,
      active_document_id: null,
      active_document_file_name: null,
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

  await page.route('**/api/query', async (route) => {
    const body = route.request().postDataJSON() as { question: string; document_ids?: string[] }
    const currentSession = state.sessions.find((session) => session.session_id === state.currentSessionId)
    const effectiveDocumentIds = body.document_ids?.length
      ? body.document_ids
      : currentSession?.active_document_id
        ? [currentSession.active_document_id]
        : []

    if (effectiveDocumentIds.length === 0) {
      return fulfill(
        route,
        {
          detail:
            'No active document selected for this session. Select an active document first or pass document_ids explicitly.',
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
        upload_timestamp: utcNow(),
        page_count: 12,
        processing_status: 'completed',
        uploaded_by_user_id: 'local-dev-user',
      },
    ],
    uploadCalls: 0,
  }
}

test('session creation is reflected in the sessions view', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('link', { name: 'Sessions' }).click()

  await page.getByRole('button', { name: 'Create session' }).click()
  await page.getByRole('dialog', { name: 'Create session' }).getByRole('button', { name: 'Create now' }).click()

  await expect(page.getByRole('cell', { name: 'session-2' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Current', exact: true })).toBeVisible()
})

test('dashboard is the default landing page and top navigation item', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')

  await expect(page.getByRole('heading', { level: 2, name: /Good to see you/i })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Primary' }).locator('a').first()).toHaveText('Dashboard')
})

test('active-document enforcement fails then succeeds after selecting a document', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('link', { name: 'Ask' }).click()

  await page.getByLabel('Prompt').fill('What are the Skyline parking rules?')
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page.getByText(/No active document selected for this session/i)).toBeVisible()

  await page.getByRole('link', { name: 'Documents' }).click()
  await page.getByRole('button', { name: 'Set active' }).click()
  const skylineRow = page.getByRole('row', {
    name: /Skyline-Mobile-Home-Park-Rules-Regs.pdf/i,
  })
  await expect(skylineRow.getByRole('button', { name: 'Active', exact: true })).toBeVisible()

  await page.getByRole('link', { name: 'Ask' }).click()
  await page.getByLabel('Prompt').fill('What are the Skyline parking rules?')
  await page.getByRole('button', { name: 'Ask question' }).click()

  await expect(page.getByText('Skyline requires vehicles to use designated parking spaces only.')).toBeVisible()
  await expect(page.getByText('Citations (1)')).toBeVisible()
})

test('document upload displays queued then deduped reuse message', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('link', { name: 'Documents' }).click()

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

test('deleting current session does not leave sticky Not Found error', async ({ page }) => {
  const state = createBaseState()
  await attachMockApi(page, state)

  await page.goto('/')
  await page.getByRole('link', { name: 'Sessions' }).click()

  page.once('dialog', async (dialog) => {
    await dialog.accept()
  })

  await page.getByRole('button', { name: 'Delete session' }).first().click()

  await expect(page.getByText(/Not Found/i)).toHaveCount(0)
  await expect(page.getByText('No sessions found.')).toBeVisible()
})
