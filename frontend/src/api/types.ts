/**
 * The API contract, mirroring the backend's Pydantic schemas.
 *
 * Hand-written rather than generated so the shapes stay readable, but they
 * follow `backend/app/schemas/` exactly — when one changes, the other must.
 */

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'
export type DocumentType =
  | 'pdf'
  | 'docx'
  | 'xlsx'
  | 'csv'
  | 'image'
  | 'text'
  | 'markdown'
  | 'audio'
export type AnalysisStatus =
  | 'pending'
  | 'generating'
  | 'executing'
  | 'succeeded'
  | 'failed'
export type MessageRole = 'user' | 'assistant' | 'system'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface CurrentUser {
  id: string
  email: string
  full_name: string | null
  org_id: string
  is_active: boolean
  organization_name: string
  workspace_ids: string[]
}

export interface Workspace {
  id: string
  team_id: string
  name: string
  description: string | null
  /** null means Auto — the router picks per request. */
  preferred_model: string | null
  created_at: string
  updated_at: string
}

export interface WorkspaceStats {
  workspace_id: string
  document_count: number
  ready_document_count: number
  chunk_count: number
  conversation_count: number
  analysis_run_count: number
}

export interface DocumentColumn {
  name: string
  dtype: string
  null_count: number
  sample_values: (string | null)[]
}

export interface DocumentTable {
  id: string
  document_id: string
  name: string
  sheet_index: number
  row_count: number
  column_count: number
  columns: DocumentColumn[]
}

export interface Document {
  id: string
  workspace_id: string
  filename: string
  content_type: string
  doc_type: DocumentType
  size_bytes: number
  status: DocumentStatus
  error_message: string | null
  page_count: number | null
  chunk_count: number
  doc_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DocumentDetail extends Document {
  tables: DocumentTable[]
}

export interface DocumentUploadResult {
  document: Document
  deduplicated: boolean
}

export interface Citation {
  document_id: string
  document_name: string
  chunk_id: string
  snippet: string
  score: number
  page: number | null
  sheet: string | null
  section: string | null
}

export interface Conversation {
  id: string
  workspace_id: string
  user_id: string | null
  task_id: string | null
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: MessageRole
  content: string
  citations: Citation[]
  model_used: string | null
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  created_at: string
}

export interface ChatTurn {
  user_message: Message
  assistant_message: Message
}

export interface AnalysisTable {
  name: string
  columns: string[]
  rows: unknown[][]
  total_rows: number
  truncated: boolean
}

export interface AnalysisRun {
  id: string
  workspace_id: string
  document_id: string
  question: string
  status: AnalysisStatus
  generated_code: string | null
  code_explanation: string | null
  result_summary: string | null
  result_data: {
    stdout?: string
    tables?: AnalysisTable[]
    scalars?: Record<string, unknown>
  }
  chart_url: string | null
  error_message: string | null
  model_used: string | null
  execution_ms: number | null
  attempt_count: number
  created_at: string
}

export type Role = 'org_admin' | 'team_admin' | 'member' | 'viewer'
export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired'

/** Ordered weakest to strongest, mirroring the backend's rank. */
export const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  member: 1,
  team_admin: 2,
  org_admin: 3,
}

export const ROLE_LABEL: Record<Role, string> = {
  org_admin: 'Organization admin',
  team_admin: 'Team admin',
  member: 'Member',
  viewer: 'Viewer',
}

export function roleAtLeast(role: Role, minimum: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum]
}

export interface Organization {
  id: string
  name: string
  slug: string
  plan_tier: string
  created_at: string
}

export interface Team {
  id: string
  org_id: string
  name: string
  description: string | null
  created_at: string
}

export interface TeamDetail extends Team {
  member_count: number
  workspace_count: number
  /** The caller's own standing, so the client can render admin controls. */
  your_role: Role
}

export interface Member {
  user_id: string
  email: string
  full_name: string | null
  role: Role
  is_active: boolean
  joined_at: string
}

export interface Invitation {
  id: string
  team_id: string
  email: string
  role: Role
  status: InvitationStatus
  expires_at: string
  created_at: string
}

export interface InvitationCreated {
  invitation: Invitation
  accept_url: string
  /** Returned exactly once — only its hash is stored server-side. */
  token: string
}

export interface InvitationPreview {
  organization_name: string
  team_name: string
  email: string
  role: Role
  expires_at: string
  requires_account: boolean
}

export type TranscriptStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface VoiceRecording {
  id: string
  workspace_id: string
  /** Set once the transcript has become a retrievable document. */
  document_id: string | null
  duration_seconds: number | null
  transcript_status: TranscriptStatus
  transcript: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface VoiceUploadResult {
  recording: VoiceRecording
  message: string
}

export interface VoiceCapabilities {
  enabled: boolean
  provider: string | null
  live_transcription: boolean
  max_audio_mb: number
  max_stream_seconds: number
}

export interface ModelInfo {
  id: string
  provider: string
  display_name: string
  context_window: number
  max_output_tokens: number
  input_cost_per_mtok: number
  output_cost_per_mtok: number
  supports_vision: boolean
  tier: 'fast' | 'balanced' | 'frontier'
}

export interface ModelCatalog {
  models: ModelInfo[]
  default_provider: string
  auto_available: boolean
}

export interface Paginated<T> {
  items: T[]
  next_cursor: string | null
  has_more: boolean
}

/** RFC 9457 problem details — the only error shape the API returns. */
export interface ProblemDetail {
  type: string
  title: string
  status: number
  detail: string
  instance?: string
  errors?: { field: string; message: string }[]
  request_id?: string
}
