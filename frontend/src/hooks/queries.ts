/**
 * React Query hooks — the single place server state is fetched and cached.
 *
 * Query keys are structured so an invalidation can target exactly what
 * changed: `['documents', workspaceId]` rather than a flat string.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'

import {
  analysisApi,
  artifactApi,
  enhanceApi,
  historyApi,
  notificationApi,
  presetApi,
  scheduleApi,
  toolApi,
  authApi,
  conversationApi,
  documentApi,
  invitationApi,
  knowledgeApi,
  modelApi,
  projectApi,
  suggestionApi,
  taskApi,
  teamApi,
  workspaceApi,
} from '@/api/endpoints'
import { voiceApi } from '@/api/voice'
import type {
  Document,
  DocumentDetail,
  DocumentKind,
  ProjectStatus,
  ProjectVisibility,
  Role,
  TaskStatus,
  PresetFilter,
  PresetInput,
  FeedbackRating,
  HistoryFilter,
  ScheduleInput,
} from '@/api/types'

export const queryKeys = {
  me: ['me'] as const,
  models: ['models'] as const,
  workspaces: ['workspaces'] as const,
  workspace: (id: string) => ['workspaces', id] as const,
  workspaceStats: (id: string) => ['workspaces', id, 'stats'] as const,
  documents: (workspaceId: string) => ['documents', workspaceId] as const,
  document: (id: string) => ['document', id] as const,
  conversations: (workspaceId: string) => ['conversations', workspaceId] as const,
  messages: (conversationId: string) => ['messages', conversationId] as const,
  analysisRuns: (documentId: string) => ['analysis-runs', documentId] as const,
  artifacts: (workspaceId: string, conversationId?: string) =>
    ['artifacts', workspaceId, conversationId ?? 'all'] as const,
  artifact: (id: string) => ['artifact', id] as const,
  tools: (conversationId: string) => ['tools', conversationId] as const,
  presets: (which: string, search: string) => ['presets', which, search] as const,
  schedules: (workspaceId: string) => ['schedules', workspaceId] as const,
  notifications: ['notifications'] as const,
  history: (workspaceId: string, which: string, search: string, offset: number) =>
    ['history', workspaceId, which, search, offset] as const,
  organization: ['organization'] as const,
  orgMembers: ['organization', 'members'] as const,
  teams: ['teams'] as const,
  team: (id: string) => ['teams', id] as const,
  teamMembers: (id: string) => ['teams', id, 'members'] as const,
  invitations: (teamId: string) => ['teams', teamId, 'invitations'] as const,
  projects: (workspaceId: string) => ['projects', workspaceId] as const,
  project: (workspaceId: string, id: string) => ['projects', workspaceId, id] as const,
  tasks: (workspaceId: string) => ['tasks', workspaceId] as const,
  taskResume: (workspaceId: string, id: string) => ['tasks', workspaceId, id, 'resume'] as const,
  suggestions: (workspaceId: string) => ['suggestions', workspaceId] as const,
  knowledge: (workspaceId: string) => ['knowledge', workspaceId] as const,
  voiceCapabilities: ['voice-capabilities'] as const,
  voiceRecordings: (workspaceId: string) => ['voice', workspaceId] as const,
}

/** How often to re-check a document that is still being ingested. */
const INGEST_POLL_MS = 2000

export function useCurrentUser(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: authApi.me,
    enabled,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: modelApi.catalog,
    // The catalogue only changes when the server is reconfigured.
    staleTime: 30 * 60 * 1000,
  })
}

export function useWorkspaces() {
  return useQuery({ queryKey: queryKeys.workspaces, queryFn: workspaceApi.list })
}

export function useWorkspaceStats(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.workspaceStats(workspaceId ?? ''),
    queryFn: () => workspaceApi.stats(workspaceId!),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: workspaceApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export function useUpdateWorkspace() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: { id: string; name?: string; preferred_model?: string | null }) =>
      workspaceApi.update(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.workspaces }),
  })
}

export function useDocuments(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.documents(workspaceId ?? ''),
    queryFn: () => documentApi.list(workspaceId!),
    enabled: Boolean(workspaceId),
    // Ingestion is asynchronous, so the list polls while anything is still
    // in flight and stops as soon as everything has settled.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const pending = items.some(
        (doc: Document) => doc.status === 'pending' || doc.status === 'processing',
      )
      return pending ? INGEST_POLL_MS : false
    },
  })
}

export function useDocument(
  documentId: string | null,
  options?: Partial<UseQueryOptions<DocumentDetail>>,
) {
  return useQuery({
    queryKey: queryKeys.document(documentId ?? ''),
    queryFn: () => documentApi.get(documentId!),
    enabled: Boolean(documentId),
    ...options,
  })
}

export function useUploadDocument(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => documentApi.upload(workspaceId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents(workspaceId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaceStats(workspaceId) })
    },
  })
}

export function useDeleteDocument(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: documentApi.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents(workspaceId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaceStats(workspaceId) })
    },
  })
}

export function useReprocessDocument(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: documentApi.reprocess,
    onSuccess: (_data, documentId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents(workspaceId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) })
    },
  })
}

export function useConversations(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.conversations(workspaceId ?? ''),
    queryFn: () => conversationApi.list(workspaceId!),
    enabled: Boolean(workspaceId),
  })
}

export function useMessages(workspaceId: string | null, conversationId: string | null) {
  return useQuery({
    queryKey: queryKeys.messages(conversationId ?? ''),
    queryFn: () => conversationApi.messages(workspaceId!, conversationId!),
    enabled: Boolean(workspaceId && conversationId),
  })
}

export function useCreateConversation(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => conversationApi.create(workspaceId, { title }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations(workspaceId) }),
  })
}

export function useDeleteConversation(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (conversationId: string) =>
      conversationApi.remove(workspaceId, conversationId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations(workspaceId) }),
  })
}

export function useAnalysisRuns(documentId: string | null) {
  return useQuery({
    queryKey: queryKeys.analysisRuns(documentId ?? ''),
    queryFn: () => analysisApi.listForDocument(documentId!),
    enabled: Boolean(documentId),
  })
}

export function useArtifacts(workspaceId: string | null, conversationId?: string) {
  return useQuery({
    queryKey: queryKeys.artifacts(workspaceId ?? '', conversationId),
    queryFn: () => artifactApi.list(workspaceId!, conversationId),
    enabled: Boolean(workspaceId),
  })
}

export function useArtifact(workspaceId: string | null, artifactId: string | null) {
  return useQuery({
    queryKey: queryKeys.artifact(artifactId ?? ''),
    queryFn: () => artifactApi.get(workspaceId!, artifactId!),
    enabled: Boolean(workspaceId && artifactId),
  })
}

export function useReviseArtifact(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ artifactId, content, title }: {
      artifactId: string
      content: string
      title?: string
    }) => artifactApi.revise(workspaceId, artifactId, { content, title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      void queryClient.invalidateQueries({ queryKey: ['artifact'] })
    },
  })
}

export function useTools(workspaceId: string | null, conversationId: string | null) {
  return useQuery({
    queryKey: queryKeys.tools(conversationId ?? ''),
    queryFn: () => toolApi.list(workspaceId!, conversationId!),
    enabled: Boolean(workspaceId && conversationId),
  })
}

export function useSetTools(workspaceId: string, conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (slugs: string[]) => toolApi.setEnabled(workspaceId, conversationId, slugs),
    onSuccess: (selection) => {
      queryClient.setQueryData(queryKeys.tools(conversationId), selection)
    },
  })
}

export function usePresets(which: PresetFilter = 'all', search = '') {
  return useQuery({
    queryKey: queryKeys.presets(which, search),
    queryFn: () => presetApi.list(which, search || undefined),
  })
}

/** Every list is invalidated together: one edit can move a preset between tabs. */
function useInvalidatePresets() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['presets'] })
}

export function useCreatePreset() {
  const invalidate = useInvalidatePresets()
  return useMutation({
    mutationFn: (input: PresetInput) => presetApi.create(input),
    onSuccess: invalidate,
  })
}

export function useUpdatePreset() {
  const invalidate = useInvalidatePresets()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<PresetInput> }) =>
      presetApi.update(id, input),
    onSuccess: invalidate,
  })
}

export function useDeletePreset() {
  const invalidate = useInvalidatePresets()
  return useMutation({
    mutationFn: (id: string) => presetApi.remove(id),
    onSuccess: invalidate,
  })
}

export function useSetPresetPinned() {
  const invalidate = useInvalidatePresets()
  return useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      pinned ? presetApi.pin(id) : presetApi.unpin(id),
    onSuccess: invalidate,
  })
}

export function usePublishPreset() {
  const invalidate = useInvalidatePresets()
  return useMutation({
    mutationFn: (id: string) => presetApi.publish(id),
    onSuccess: invalidate,
  })
}

export function useHistory(
  workspaceId: string,
  which: HistoryFilter,
  search: string,
  offset: number,
  limit = 20,
) {
  return useQuery({
    queryKey: queryKeys.history(workspaceId, which, search, offset),
    queryFn: () => historyApi.list(workspaceId, { which, search: search || undefined, limit, offset }),
    // A page of history should not blank out while the next one loads.
    placeholderData: (previous) => previous,
  })
}

export function useSetConversationFlags(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      conversationId,
      ...flags
    }: {
      conversationId: string
      pinned?: boolean
      archived?: boolean
    }) => historyApi.setFlags(workspaceId, conversationId, flags),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['history'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations(workspaceId) })
    },
  })
}

export function useRateMessage(workspaceId: string, conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ messageId, rating }: { messageId: string; rating: FeedbackRating | null }) =>
      historyApi.rate(workspaceId, conversationId, messageId, rating),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.messages(conversationId) })
    },
  })
}

export function useSchedules(workspaceId: string) {
  return useQuery({
    queryKey: queryKeys.schedules(workspaceId),
    queryFn: () => scheduleApi.list(workspaceId),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateSchedule(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ScheduleInput) => scheduleApi.create(workspaceId, input),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.schedules(workspaceId) }),
  })
}

export function useUpdateSchedule(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<ScheduleInput> }) =>
      scheduleApi.update(workspaceId, id, input),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.schedules(workspaceId) }),
  })
}

export function useDeleteSchedule(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => scheduleApi.remove(workspaceId, id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.schedules(workspaceId) }),
  })
}

export function useEnhanceDraft(workspaceId: string) {
  return useMutation({
    mutationFn: (draft: string) => enhanceApi.rewrite(workspaceId, draft),
  })
}

export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications,
    queryFn: () => notificationApi.list(),
    // A schedule can fire at any time, so the bell checks back on its own
    // rather than only on a reload.
    refetchInterval: 60_000,
  })
}

export function useMarkNotificationsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id?: string) =>
      id ? notificationApi.markRead(id) : notificationApi.markAllRead(),
    onSuccess: (list) => queryClient.setQueryData(queryKeys.notifications, list),
  })
}

export function useRenameConversation(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: string; title: string }) =>
      conversationApi.rename(workspaceId, conversationId, title),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations(workspaceId) })
    },
  })
}

export function useOrganization() {
  return useQuery({ queryKey: queryKeys.organization, queryFn: teamApi.organization })
}

export function useOrgMembers() {
  return useQuery({ queryKey: queryKeys.orgMembers, queryFn: teamApi.orgMembers })
}

export function useTeams() {
  return useQuery({ queryKey: queryKeys.teams, queryFn: teamApi.list })
}

export function useTeam(teamId: string | null) {
  return useQuery({
    queryKey: queryKeys.team(teamId ?? ''),
    queryFn: () => teamApi.get(teamId!),
    enabled: Boolean(teamId),
  })
}

export function useTeamMembers(teamId: string | null) {
  return useQuery({
    queryKey: queryKeys.teamMembers(teamId ?? ''),
    queryFn: () => teamApi.members(teamId!),
    enabled: Boolean(teamId),
  })
}

export function useCreateTeam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: teamApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.teams }),
  })
}

export function useSetMemberRole(teamId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      teamApi.setMemberRole(teamId, userId, role),
    onSuccess: () => {
      // The caller may have changed their own standing, so the team detail
      // (which carries `your_role`) has to be refetched alongside the list.
      queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(teamId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.team(teamId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.orgMembers })
    },
  })
}

export function useRemoveMember(teamId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => teamApi.removeMember(teamId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(teamId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.team(teamId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.teams })
    },
  })
}

export function useInvitations(teamId: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.invitations(teamId ?? ''),
    queryFn: () => invitationApi.list(teamId!),
    enabled: Boolean(teamId) && enabled,
  })
}

export function useCreateInvitation(teamId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { email: string; role: Role }) =>
      invitationApi.create(teamId, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.invitations(teamId) }),
  })
}

export function useRevokeInvitation(teamId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: invitationApi.revoke,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.invitations(teamId) }),
  })
}

export function useProjects(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.projects(workspaceId ?? ''),
    queryFn: () => projectApi.list(workspaceId!),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateProject(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      name: string
      goal?: string
      visibility?: ProjectVisibility
    }) => projectApi.create(workspaceId, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(workspaceId) }),
  })
}

export function useUpdateProject(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      ...payload
    }: {
      projectId: string
      name?: string
      status?: ProjectStatus
      visibility?: ProjectVisibility
    }) => projectApi.update(workspaceId, projectId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(workspaceId) })
      // Changing visibility changes which tasks the caller can see.
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(workspaceId) })
    },
  })
}

export function useTasks(
  workspaceId: string | null,
  filters: { project_id?: string; assignee_id?: string } = {},
) {
  return useQuery({
    queryKey: [...queryKeys.tasks(workspaceId ?? ''), filters] as const,
    queryFn: () => taskApi.list(workspaceId!, filters),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateTask(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      ...payload
    }: {
      projectId: string
      title: string
      assignee_id?: string | null
      due_date?: string | null
    }) => taskApi.create(workspaceId, projectId, payload),
    onSuccess: () => invalidateTaskViews(queryClient, workspaceId),
  })
}

export function useUpdateTask(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      taskId,
      ...payload
    }: {
      taskId: string
      title?: string
      status?: TaskStatus
      assignee_id?: string | null
      due_date?: string | null
    }) => taskApi.update(workspaceId, taskId, payload),
    onSuccess: () => invalidateTaskViews(queryClient, workspaceId),
  })
}

export function useDeleteTask(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => taskApi.remove(workspaceId, taskId),
    onSuccess: () => invalidateTaskViews(queryClient, workspaceId),
  })
}

/** Completing a task also changes the suggestions, so both are refreshed. */
function invalidateTaskViews(queryClient: QueryClient, workspaceId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.tasks(workspaceId) })
  queryClient.invalidateQueries({ queryKey: queryKeys.projects(workspaceId) })
  queryClient.invalidateQueries({ queryKey: queryKeys.suggestions(workspaceId) })
}

export function useTaskResume(workspaceId: string | null, taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.taskResume(workspaceId ?? '', taskId ?? ''),
    queryFn: () => taskApi.resume(workspaceId!, taskId!),
    enabled: Boolean(workspaceId && taskId),
    // The summary costs a model call, so it is not re-fetched on every mount.
    staleTime: 5 * 60 * 1000,
  })
}

export function useSuggestions(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.suggestions(workspaceId ?? ''),
    queryFn: () => suggestionApi.get(workspaceId!),
    enabled: Boolean(workspaceId),
    // The server caches these; asking more often would only recompute them.
    staleTime: 5 * 60 * 1000,
  })
}

export function useKnowledgeMap(
  workspaceId: string | null,
  filters: { kind?: DocumentKind; topic?: string } = {},
) {
  return useQuery({
    queryKey: [...queryKeys.knowledge(workspaceId ?? ''), filters] as const,
    queryFn: () => knowledgeApi.map(workspaceId!, filters),
    enabled: Boolean(workspaceId),
  })
}

export function useVoiceCapabilities() {
  return useQuery({
    queryKey: queryKeys.voiceCapabilities,
    queryFn: voiceApi.capabilities,
    // Only changes when the server is reconfigured, and the answer decides
    // whether the microphone is shown at all.
    staleTime: 30 * 60 * 1000,
  })
}

export function useVoiceRecordings(workspaceId: string | null) {
  return useQuery({
    queryKey: queryKeys.voiceRecordings(workspaceId ?? ''),
    queryFn: () => voiceApi.list(workspaceId!),
    enabled: Boolean(workspaceId),
    // Transcription is asynchronous, so poll while anything is still in
    // flight and stop as soon as everything has settled.
    refetchInterval: (query) => {
      const pending = (query.state.data ?? []).some(
        (r) => r.transcript_status === 'pending' || r.transcript_status === 'processing',
      )
      return pending ? INGEST_POLL_MS : false
    },
  })
}

export function useRunAnalysis(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { question: string; table_id?: string }) =>
      analysisApi.run(documentId, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.analysisRuns(documentId) }),
  })
}
