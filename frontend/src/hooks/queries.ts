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
  type UseQueryOptions,
} from '@tanstack/react-query'

import {
  analysisApi,
  authApi,
  conversationApi,
  documentApi,
  modelApi,
  workspaceApi,
} from '@/api/endpoints'
import type { Document, DocumentDetail } from '@/api/types'

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

export function useRunAnalysis(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { question: string; table_id?: string }) =>
      analysisApi.run(documentId, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.analysisRuns(documentId) }),
  })
}
