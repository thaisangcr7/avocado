/** One typed function per API route. Components call these, never `fetch`. */

import { http, tokenStore, BASE_URL } from './client'
import type {
  AnalysisRun,
  Invitation,
  InvitationCreated,
  InvitationPreview,
  Member,
  Organization,
  DocumentKind,
  KnowledgeMap,
  Project,
  ProjectDetail,
  ProjectStatus,
  ProjectVisibility,
  Role,
  SuggestionsResponse,
  Task,
  TaskResume,
  TaskStatus,
  Team,
  TeamDetail,
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

export const teamApi = {
  organization: () => http.get<Organization>('/organizations/current'),

  renameOrganization: (name: string) =>
    http.patch<Organization>('/organizations/current', { name }),

  orgMembers: () => http.get<Member[]>('/organizations/current/members'),

  list: () => http.get<Team[]>('/teams'),

  create: (payload: { name: string; description?: string }) =>
    http.post<TeamDetail>('/teams', payload),

  get: (teamId: string) => http.get<TeamDetail>(`/teams/${teamId}`),

  update: (teamId: string, payload: { name?: string; description?: string }) =>
    http.patch<TeamDetail>(`/teams/${teamId}`, payload),

  remove: (teamId: string) => http.delete<{ message: string }>(`/teams/${teamId}`),

  members: (teamId: string) => http.get<Member[]>(`/teams/${teamId}/members`),

  setMemberRole: (teamId: string, userId: string, role: Role) =>
    http.patch<Member>(`/teams/${teamId}/members/${userId}`, { role }),

  removeMember: (teamId: string, userId: string) =>
    http.delete<{ message: string }>(`/teams/${teamId}/members/${userId}`),
}

export const invitationApi = {
  list: (teamId: string) => http.get<Invitation[]>(`/teams/${teamId}/invitations`),

  create: (teamId: string, payload: { email: string; role: Role; expires_in_days?: number }) =>
    http.post<InvitationCreated>(`/teams/${teamId}/invitations`, payload),

  revoke: (invitationId: string) =>
    http.delete<{ message: string }>(`/invitations/${invitationId}`),

  // Anonymous: the recipient may have no account yet.
  preview: (token: string) =>
    http.get<InvitationPreview>(`/invitations/${token}`, { anonymous: true }),

  accept: (token: string, payload: { password?: string; full_name?: string }) =>
    http.post<TokenResponse>(`/invitations/${token}/accept`, payload),
}

export const projectApi = {
  list: (workspaceId: string, status?: ProjectStatus) => {
    const query = status ? `?status=${status}` : ''
    return http.get<Project[]>(`/workspaces/${workspaceId}/projects${query}`)
  },

  create: (
    workspaceId: string,
    payload: {
      name: string
      goal?: string
      visibility?: ProjectVisibility
      member_ids?: string[]
    },
  ) => http.post<ProjectDetail>(`/workspaces/${workspaceId}/projects`, payload),

  get: (workspaceId: string, projectId: string) =>
    http.get<ProjectDetail>(`/workspaces/${workspaceId}/projects/${projectId}`),

  update: (
    workspaceId: string,
    projectId: string,
    payload: { name?: string; goal?: string; status?: ProjectStatus; visibility?: ProjectVisibility },
  ) => http.patch<ProjectDetail>(`/workspaces/${workspaceId}/projects/${projectId}`, payload),

  remove: (workspaceId: string, projectId: string) =>
    http.delete<{ message: string }>(`/workspaces/${workspaceId}/projects/${projectId}`),

  addMember: (workspaceId: string, projectId: string, memberId: string) =>
    http.put<{ message: string }>(
      `/workspaces/${workspaceId}/projects/${projectId}/members/${memberId}`,
    ),

  removeMember: (workspaceId: string, projectId: string, memberId: string) =>
    http.delete<{ message: string }>(
      `/workspaces/${workspaceId}/projects/${projectId}/members/${memberId}`,
    ),
}

export const taskApi = {
  list: (
    workspaceId: string,
    filters: { project_id?: string; assignee_id?: string; status?: TaskStatus } = {},
  ) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value)
    }
    const query = params.toString()
    return http.get<Task[]>(`/workspaces/${workspaceId}/tasks${query ? `?${query}` : ''}`)
  },

  create: (
    workspaceId: string,
    projectId: string,
    payload: {
      title: string
      notes?: string
      assignee_id?: string | null
      status?: TaskStatus
      due_date?: string | null
    },
  ) => http.post<Task>(`/workspaces/${workspaceId}/projects/${projectId}/tasks`, payload),

  update: (
    workspaceId: string,
    taskId: string,
    payload: {
      title?: string
      notes?: string
      assignee_id?: string | null
      status?: TaskStatus
      due_date?: string | null
    },
  ) => http.patch<Task>(`/workspaces/${workspaceId}/tasks/${taskId}`, payload),

  remove: (workspaceId: string, taskId: string) =>
    http.delete<{ message: string }>(`/workspaces/${workspaceId}/tasks/${taskId}`),

  resume: (workspaceId: string, taskId: string) =>
    http.get<TaskResume>(`/workspaces/${workspaceId}/tasks/${taskId}/resume`),
}

export const suggestionApi = {
  get: (workspaceId: string, refresh = false) =>
    http.get<SuggestionsResponse>(
      `/workspaces/${workspaceId}/suggestions${refresh ? '?refresh=true' : ''}`,
    ),
}

export const knowledgeApi = {
  map: (workspaceId: string, filters: { kind?: DocumentKind; topic?: string } = {}) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value)
    }
    const query = params.toString()
    return http.get<KnowledgeMap>(
      `/workspaces/${workspaceId}/knowledge${query ? `?${query}` : ''}`,
    )
  },
}

export const modelApi = {
  catalog: () => http.get<ModelCatalog>('/models'),
}

export { tokenStore }
