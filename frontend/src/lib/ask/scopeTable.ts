export type AskScopeSortField = 'name' | 'date' | 'status' | 'size'

export type AskScopeSortDirection = 'asc' | 'desc'

export type AskScopeSortState = {
  field: AskScopeSortField
  direction: AskScopeSortDirection
}

export type AskScopeDocument = {
  document_id: string
  file_name: string
  file_size_bytes: number
  upload_timestamp: string
  processing_status: string
}

function defaultDirectionForField(field: AskScopeSortField): AskScopeSortDirection {
  if (field === 'date' || field === 'size') {
    return 'desc'
  }

  return 'asc'
}

export function nextSortState(current: AskScopeSortState, field: AskScopeSortField): AskScopeSortState {
  if (current.field === field) {
    return {
      field,
      direction: current.direction === 'asc' ? 'desc' : 'asc',
    }
  }

  return {
    field,
    direction: defaultDirectionForField(field),
  }
}

function compareByField(left: AskScopeDocument, right: AskScopeDocument, field: AskScopeSortField): number {
  if (field === 'name') {
    return left.file_name.localeCompare(right.file_name, undefined, { sensitivity: 'base' })
  }

  if (field === 'date') {
    return Date.parse(left.upload_timestamp) - Date.parse(right.upload_timestamp)
  }

  if (field === 'status') {
    return left.processing_status.localeCompare(right.processing_status, undefined, { sensitivity: 'base' })
  }

  return left.file_size_bytes - right.file_size_bytes
}

export function sortScopeDocuments(
  documents: AskScopeDocument[],
  sortState: AskScopeSortState,
): AskScopeDocument[] {
  const directionFactor = sortState.direction === 'asc' ? 1 : -1

  return documents
    .map((document, index) => ({ document, index }))
    .sort((left, right) => {
      const compared = compareByField(left.document, right.document, sortState.field)
      if (compared === 0) {
        return left.index - right.index
      }
      return compared * directionFactor
    })
    .map((item) => item.document)
}
