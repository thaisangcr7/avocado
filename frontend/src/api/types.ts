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
  /** Which conversation the file arrived in; null means the workspace at large. */
  conversation_id: string | null
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
  /** True when this records a failed generation rather than an answer. */
  failed: boolean
  /** A whole-workspace executive report, when this message is one. */
  report_artifact?: ExecutiveReport | null
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

export type VisualizationFieldType =
  | 'nominal'
  | 'ordinal'
  | 'temporal'
  | 'quantitative'

export interface VisualizationEncoding {
  field: string
  type: VisualizationFieldType
  title: string | null
  format: string | null
}

export interface AnalysisVisualization {
  title: string
  description: string | null
  mark: 'bar' | 'line' | 'area' | 'point' | 'arc' | 'boxplot'
  table_index: number
  x: VisualizationEncoding
  y: VisualizationEncoding
  color: VisualizationEncoding | null
  interactive: boolean
}

export interface AnalysisMetric {
  label: string
  value: string
  context: string | null
  tone: 'neutral' | 'positive' | 'negative' | 'warning'
}

export interface AnalysisPresentation {
  summary: string
  metrics: AnalysisMetric[]
  visualizations: AnalysisVisualization[]
}

export type ToolCategory = 'analytics' | 'engineering' | 'knowledge' | 'admin' | 'data'
export type ToolKind = 'builtin' | 'mcp' | 'placeholder'

export interface Tool {
  slug: string
  name: string
  description: string
  category: ToolCategory
  kind: ToolKind
  /** What this tool's schema adds to every request while it is on. */
  context_cost_tokens: number
  enabled: boolean
  /** False for a tool that is declared but not wired to anything yet. */
  connected: boolean
}

export interface ToolSelection {
  tools: Tool[]
  enabled_count: number
  context_cost_tokens: number
}

export type ArtifactKind = 'html' | 'markdown' | 'code' | 'chart' | 'table'
export type ArtifactAuthor = 'ai' | 'user'

export interface ArtifactVersion {
  id: string
  version: number
  author: ArtifactAuthor
  model_used: string | null
  created_at: string
}

export interface Artifact {
  id: string
  workspace_id: string
  conversation_id: string | null
  /** Shared by every version of one artifact. */
  lineage_id: string
  version: number
  kind: ArtifactKind
  author: ArtifactAuthor
  title: string
  filename: string
  content: string | null
  model_used: string | null
  created_at: string
  updated_at: string
}

export interface ArtifactDetail extends Artifact {
  versions: ArtifactVersion[]
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
    presentation?: AnalysisPresentation
  }
  chart_url: string | null
  error_message: string | null
  model_used: string | null
  execution_ms: number | null
  attempt_count: number
  created_at: string
}

export type ReportStatus = 'on_course' | 'watch' | 'off_course' | 'neutral'

export interface ReportKpi {
  label: string
  value: string
  context: string | null
  tone: 'neutral' | 'positive' | 'negative' | 'warning'
}

export interface ReportSeries {
  key: string
  title: string
  columns: string[]
  rows: unknown[][]
}

export interface ReportChart {
  title: string
  description: string | null
  mark: 'bar' | 'line' | 'area' | 'point' | 'arc' | 'boxplot'
  series_key: string
  x: VisualizationEncoding
  y: VisualizationEncoding
  color: VisualizationEncoding | null
}

export interface ReportSection {
  title: string
  status: ReportStatus
  narrative: string
  charts: ReportChart[]
}

export interface ExecutiveReport {
  title: string
  thesis: string
  heading_status: ReportStatus
  kpis: ReportKpi[]
  sections: ReportSection[]
  series: ReportSeries[]
  limits: string[]
  model_used: string | null
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

export type ProjectStatus = 'active' | 'paused' | 'completed' | 'archived'
export type ProjectVisibility = 'restricted' | 'workspace'
export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done'
export type DocumentKind = 'policy' | 'process' | 'project' | 'reference' | 'other'
export type SuggestionKind =
  | 'task_due'
  | 'task_overdue'
  | 'task_blocked'
  | 'new_document'
  | 'unfinished_thread'
  | 'failed_document'

/** Board column order. */
export const TASK_STATUSES: TaskStatus[] = ['todo', 'in_progress', 'blocked', 'done']

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  blocked: 'Blocked',
  done: 'Done',
}

export const DOCUMENT_KIND_LABEL: Record<DocumentKind, string> = {
  policy: 'Policy',
  process: 'Process',
  project: 'Project',
  reference: 'Reference',
  other: 'Other',
}

export interface Project {
  id: string
  workspace_id: string
  name: string
  goal: string | null
  status: ProjectStatus
  /** `restricted` is the default: members and admins only. */
  visibility: ProjectVisibility
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ProjectDetail extends Project {
  member_ids: string[]
  task_counts: Record<string, number>
}

export interface Task {
  id: string
  project_id: string
  workspace_id: string
  assignee_id: string | null
  title: string
  notes: string | null
  status: TaskStatus
  due_date: string | null
  created_at: string
  updated_at: string
}

export interface TaskResume {
  task: Task
  conversation_id: string
  summary: string
  message_count: number
  last_activity_at: string | null
  /** False when the summary is deterministic rather than model-written. */
  synthesized: boolean
}

export interface Suggestion {
  id: string
  kind: SuggestionKind
  title: string
  detail: string | null
  task_id: string | null
  project_id: string | null
  document_id: string | null
  conversation_id: string | null
  priority: number
}

export interface SuggestionsResponse {
  items: Suggestion[]
  generated_at: string
  cached: boolean
  /** Null when the deterministic wording was used. */
  model_used: string | null
}

export interface ClassifiedDocument {
  document_id: string
  filename: string
  kind: DocumentKind
  title: string | null
  summary: string | null
  topics: string[]
  effective_date: string | null
  team_id: string | null
  created_at: string
}

export interface KnowledgeMap {
  counts_by_kind: Record<string, number>
  topics: string[]
  documents: ClassifiedDocument[]
  unclassified_count: number
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
