export interface SessionCreateResponse {
  session_id: string
  user_id: string
  active_document_id: string | null
  created_at: string
  expires_at: string
}

export interface SessionSummary {
  session_id: string
  active_document_id: string | null
  active_document_file_name: string | null
  created_at: string
  last_accessed_at: string
  expires_at: string
}

export interface SessionListResponse {
  sessions: SessionSummary[]
  total_count: number
}

export interface ActiveDocumentResponse {
  session_id: string
  active_document_id: string | null
  active_document_file_name: string | null
}

export interface DocumentUploadResponse {
  document_id: string
  file_name: string
  status: string
  message: string
  chunks_created: number
}

export interface DocumentRecord {
  document_id: string
  file_name: string
  file_size_bytes: number
  upload_timestamp: string
  page_count: number | null
  processing_status: string
  uploaded_by_user_id: string | null
}

export interface DocumentListResponse {
  documents: DocumentRecord[]
  total_count: number
  skip: number
  limit: number
}

export interface Citation {
  document_id: string
  file_name: string
  chunk_index: number
  page_number: number | null
  section_title: string | null
  snippet: string
}

export interface QueryRequest {
  question: string
  document_ids?: string[]
  top_k?: number
  max_citations?: number
}

export interface QueryResponse {
  question: string
  answer: string
  citations: Citation[]
  model_used: string
  latency_ms: number
}

export interface ApiErrorEnvelope {
  detail?: string
}
