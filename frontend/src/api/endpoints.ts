/** One typed function per API route. Components call these, never `fetch`. */

import { http, tokenStore, BASE_URL } from './client'
import type {
  AnalysisRun,
  ChatTurn,
  Conversation,
  CurrentUser,
  Document,
  DocumentDetail,
  DocumentUploadResult,
  Message,
  ModelCatalog,
  Paginated,
  TokenResponse,
  Workspace,
  WorkspaceStats,
} from './types'

export const authApi = {
  register: (payload: {
    email: string
    password: string
    full_name?: string
    organization_name: string
  }) => http.post<TokenResponse>('/auth/register', payload, { anonymous: true }),

  login: (payload: { email: string; password: string }) =>
    http.post<TokenResponse>('/auth/login', payload, { anonymous: true }),

  me: () => http.get<CurrentUser>('/auth/me'),
}

export const workspaceApi = {
  list: () => http.get<Workspace[]>('/workspaces'),

  create: (payload: { name: string; description?: string; preferred_model?: string | null }) =>
    http.post<Workspace>('/workspaces', payload),

  get: (id: string) => http.get<Workspace>(`/workspaces/${id}`),

  update: (
    id: string,
    payload: { name?: string; description?: string; preferred_model?: string | null },
  ) => http.patch<Workspace>(`/workspaces/${id}`, payload),

  remove: (id: string) => http.delete<{ message: string }>(`/workspaces/${id}`),

  stats: (id: string) => http.get<WorkspaceStats>(`/workspaces/${id}/stats`),
}

export const documentApi = {
  list: (workspaceId: string, cursor?: string, limit = 25) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return http.get<Paginated<Document>>(
      `/workspaces/${workspaceId}/documents?${params}`,
    )
  },

  upload: (workspaceId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    // `raw` so the browser sets the multipart boundary itself; setting
    // Content-Type by hand omits it and the request fails to parse.
    return http.post<DocumentUploadResult>(
      `/workspaces/${workspaceId}/documents`,
      form,
      { raw: true },
    )
  },

  get: (documentId: string) => http.get<DocumentDetail>(`/documents/${documentId}`),

  remove: (documentId: string) =>
    http.delete<{ message: string }>(`/documents/${documentId}`),

  reprocess: (documentId: string) =>
    http.post<Document>(`/documents/${documentId}/reprocess`),
}

export const conversationApi = {
  list: (workspaceId: string) =>
    http.get<Conversation[]>(`/workspaces/${workspaceId}/conversations`),

  create: (workspaceId: string, payload: { title?: string } = {}) =>
    http.post<Conversation>(`/workspaces/${workspaceId}/conversations`, payload),

  rename: (workspaceId: string, conversationId: string, title: string) =>
    http.patch<Conversation>(
      `/workspaces/${workspaceId}/conversations/${conversationId}`,
      { title },
    ),

  remove: (workspaceId: string, conversationId: string) =>
    http.delete<{ message: string }>(
      `/workspaces/${workspaceId}/conversations/${conversationId}`,
    ),

  messages: (workspaceId: string, conversationId: string) =>
    http.get<Message[]>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
    ),

  send: (
    workspaceId: string,
    conversationId: string,
    payload: { content: string; document_ids?: string[] },
  ) =>
    http.post<ChatTurn>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
      payload,
    ),
}

export const analysisApi = {
  run: (documentId: string, payload: { question: string; table_id?: string }) =>
    http.post<AnalysisRun>(`/documents/${documentId}/analyze`, payload),

  get: (runId: string) => http.get<AnalysisRun>(`/analysis-runs/${runId}`),

  listForDocument: (documentId: string) =>
    http.get<AnalysisRun[]>(`/documents/${documentId}/analysis-runs`),

  /** Charts are served through the API so access stays behind the same check. */
  chartUrl: (runId: string) => `${BASE_URL}/analysis-runs/${runId}/chart`,

  fetchChart: (runId: string) => http.get<Blob>(`/analysis-runs/${runId}/chart`),
}

export const modelApi = {
  catalog: () => http.get<ModelCatalog>('/models'),
}

export { tokenStore }
