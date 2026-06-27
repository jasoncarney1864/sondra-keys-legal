import { describe, expect, it } from 'vitest'

import { nextSortState, sortScopeDocuments, type AskScopeDocument } from './scopeTable'

const DOCUMENTS: AskScopeDocument[] = [
  {
    document_id: 'doc-1',
    file_name: 'Skyline-Mobile-Home-Park-Rules-Regs.pdf',
    file_size_bytes: 240000,
    upload_timestamp: '2026-06-26T12:00:00.000Z',
    processing_status: 'completed',
  },
  {
    document_id: 'doc-2',
    file_name: 'Alpha-Lease-Agreement.pdf',
    file_size_bytes: 110000,
    upload_timestamp: '2026-06-20T12:00:00.000Z',
    processing_status: 'completed',
  },
  {
    document_id: 'doc-3',
    file_name: 'Tenant-Rights-Overview.pdf',
    file_size_bytes: 180000,
    upload_timestamp: '2026-06-24T12:00:00.000Z',
    processing_status: 'completed',
  },
]

describe('sortScopeDocuments', () => {
  it('sorts by name ascending', () => {
    const sorted = sortScopeDocuments(DOCUMENTS, { field: 'name', direction: 'asc' })
    expect(sorted.map((document) => document.file_name)).toEqual([
      'Alpha-Lease-Agreement.pdf',
      'Skyline-Mobile-Home-Park-Rules-Regs.pdf',
      'Tenant-Rights-Overview.pdf',
    ])
  })

  it('sorts by date descending', () => {
    const sorted = sortScopeDocuments(DOCUMENTS, { field: 'date', direction: 'desc' })
    expect(sorted.map((document) => document.document_id)).toEqual(['doc-1', 'doc-3', 'doc-2'])
  })
})

describe('nextSortState', () => {
  it('toggles direction when sorting the same field', () => {
    const first = { field: 'name', direction: 'asc' } as const
    const next = nextSortState(first, 'name')

    expect(next).toEqual({ field: 'name', direction: 'desc' })
  })

  it('uses default direction when switching fields', () => {
    const start = { field: 'name', direction: 'desc' } as const
    const next = nextSortState(start, 'date')

    expect(next).toEqual({ field: 'date', direction: 'desc' })
  })
})
