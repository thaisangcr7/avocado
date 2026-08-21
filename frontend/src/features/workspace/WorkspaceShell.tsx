/**
 * The application shell: workspace switcher, conversation list, model picker,
 * chat in the center, and a right rail for Documents + Artifacts.
 */

import { useEffect, useState } from 'react'

import type { AnalysisRun, Document } from '@/api/types'
import { AnalysisView } from '@/features/analysis/AnalysisView'
import { ChatView } from '@/features/chat/ChatView'
import { DocumentPanel } from '@/features/documents/DocumentPanel'
import { TaskResumePanel } from '@/features/tasks/TaskResumePanel'
import { TeamSettings } from '@/features/teams/TeamSettings'
import { ArtifactPanel } from '@/features/workspace/ArtifactPanel'
import { Button, Spinner } from '@/components/ui/primitives'
import {
  useConversations,
  useCreateConversation,
  useCreateWorkspace,
  useDeleteConversation,
  useModels,
  useTeams,
  useUpdateWorkspace,
  useWorkspaces,
  useWorkspaceStats,
} from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'

type LibraryTab = 'documents' | 'artifacts'
type RightPanelView = LibraryTab | 'analysis' | 'task' | 'team'

export function WorkspaceShell() {
  const { data: workspaces, isLoading } = useWorkspaces()
  const { activeWorkspaceId, setActiveWorkspace } = useWorkspaceStore()
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [analysisDocumentId, setAnalysisDocumentId] = useState<string | null>(null)
  const [analysisRun, setAnalysisRun] = useState<AnalysisRun | null>(null)
  const [settingsTeamId, setSettingsTeamId] = useState<string | null>(null)
  const [resumeTaskId, setResumeTaskId] = useState<string | null>(null)
  const [threadsOpen, setThreadsOpen] = useState(
    () => window.matchMedia('(min-width: 1024px)').matches,
  )
  const [rightOpen, setRightOpen] = useState(
    () => window.matchMedia('(min-width: 1024px)').matches,
  )
  const [libraryTab, setLibraryTab] = useState<LibraryTab>('documents')
  const [rightView, setRightView] = useState<RightPanelView>('documents')
  // A question picked on the landing pane, held until the conversation it
  // will be asked in has been created.
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const startConversation = useCreateConversation(activeWorkspaceId ?? '')

  function openRight(view: RightPanelView) {
    setRightView(view)
    setRightOpen(true)
  }

  // Settle on a workspace once they load: the stored one if it still exists,
  // otherwise the first. A stale id from a deleted workspace must not stick.
  useEffect(() => {
    if (!workspaces?.length) return
    const stillExists = workspaces.some((w) => w.id === activeWorkspaceId)
    if (!stillExists) setActiveWorkspace(workspaces[0]!.id)
  }, [workspaces, activeWorkspaceId, setActiveWorkspace])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="size-6 text-ink-muted" />
      </div>
    )
  }

  const workspace = workspaces?.find((w) => w.id === activeWorkspaceId) ?? null

  return (
    <div className="bg-atmosphere flex h-screen flex-col">
      <TopBar
        threadsOpen={threadsOpen}
        rightOpen={rightOpen}
        onToggleThreads={() => setThreadsOpen((open) => !open)}
        onToggleRight={() => setRightOpen((open) => !open)}
        onOpenTeam={(teamId) => {
          setSettingsTeamId(teamId)
          openRight('team')
        }}
      />

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {(threadsOpen || rightOpen) && (
          <button
            type="button"
            aria-label="Close side panel"
            className="absolute inset-0 z-20 bg-ink/10 backdrop-blur-[1px] lg:hidden"
            onClick={() => {
              setThreadsOpen(false)
              setRightOpen(false)
            }}
          />
        )}

        <aside
          className={cn(
            'z-30 flex-col border-r border-border-subtle/80 bg-surface-raised/95 backdrop-blur-md',
            'fixed bottom-0 left-0 top-14 w-[min(20rem,86vw)] shadow-2xl lg:static lg:shadow-none',
            threadsOpen ? 'flex lg:w-72 lg:shrink-0' : 'hidden',
          )}
        >
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border-subtle/80 px-3 lg:hidden">
            <span className="text-sm font-semibold text-ink">Threads</span>
            <button
              type="button"
              onClick={() => setThreadsOpen(false)}
              aria-label="Close threads"
              className="flex size-8 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-sunken hover:text-ink"
            >
              ×
            </button>
          </div>
          <WorkspaceSwitcher />
          <ConversationList
            workspaceId={activeWorkspaceId}
            activeConversationId={activeConversationId}
            onSelect={(id) => {
              setActiveConversationId(id)
              if (window.innerWidth < 1024) setThreadsOpen(false)
            }}
          />
          <WorkspaceFooter workspaceId={activeWorkspaceId} />
        </aside>

        <main className="min-w-0 flex-1">
          {!workspace ? (
            <div className="flex h-full items-center justify-center text-sm text-ink-muted">
              Create a workspace to begin.
            </div>
          ) : (
            <ChatView
              workspaceId={workspace.id}
              conversationId={activeConversationId}
              onOpenTask={(taskId) => {
                setResumeTaskId(taskId)
                openRight('task')
              }}
              onOpenAnalysis={(documentId, run) => {
                setAnalysisDocumentId(documentId)
                setAnalysisRun(run)
                openRight('analysis')
              }}
              pendingQuestion={pendingQuestion}
              onPendingQuestionSent={() => setPendingQuestion(null)}
              onStartConversation={(question) =>
                startConversation.mutate(undefined, {
                  onSuccess: (conversation) => {
                    setActiveConversationId(conversation.id)
                    setPendingQuestion(question ?? null)
                  },
                })
              }
            />
          )}
        </main>

        <aside
          className={cn(
            'z-30 flex-col border-l border-border-subtle/80 bg-surface-raised/95 backdrop-blur-md',
            'fixed bottom-0 right-0 top-14 w-[min(46rem,94vw)] shadow-2xl lg:static lg:shadow-none',
            rightOpen ? 'flex lg:w-[min(42vw,44rem)] lg:shrink-0' : 'hidden',
          )}
        >
          {activeWorkspaceId && (
            <LibraryRail
              workspaceId={activeWorkspaceId}
              tab={libraryTab}
              view={rightView}
              onTabChange={(tab) => {
                setLibraryTab(tab)
                setRightView(tab)
              }}
              onClose={() => setRightOpen(false)}
              onSelectDocument={(document: Document) => {
                setAnalysisDocumentId(document.id)
                setAnalysisRun(null)
                openRight('analysis')
              }}
              onResumeTask={(taskId) => {
                setResumeTaskId(taskId)
                openRight('task')
              }}
              onOpenAnalysis={(documentId, run) => {
                setAnalysisDocumentId(documentId)
                setAnalysisRun(run ?? null)
                openRight('analysis')
              }}
              analysisDocumentId={analysisDocumentId}
              analysisRun={analysisRun}
              resumeTaskId={resumeTaskId}
              settingsTeamId={settingsTeamId}
              onOpenThread={(conversationId) => {
                setActiveConversationId(conversationId)
                setRightOpen(false)
              }}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

function LibraryRail({
  workspaceId,
  tab,
  view,
  onTabChange,
  onClose,
  onSelectDocument,
  onResumeTask,
  onOpenAnalysis,
  analysisDocumentId,
  analysisRun,
  resumeTaskId,
  settingsTeamId,
  onOpenThread,
}: {
  workspaceId: string
  tab: LibraryTab
  view: RightPanelView
  onTabChange: (tab: LibraryTab) => void
  onClose: () => void
  onSelectDocument: (document: Document) => void
  onResumeTask: (taskId: string) => void
  onOpenAnalysis: (documentId: string, run?: AnalysisRun) => void
  analysisDocumentId: string | null
  analysisRun: AnalysisRun | null
  resumeTaskId: string | null
  settingsTeamId: string | null
  onOpenThread: (conversationId: string) => void
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border-subtle/80 px-2">
        <nav
          className="flex min-w-0 flex-1 items-center gap-0.5 rounded-xl bg-surface-sunken/80 p-0.5"
          aria-label="Library"
        >
          {(
            [
              { id: 'documents', label: 'Documents' },
              { id: 'artifacts', label: 'Artifacts' },
            ] as const
          ).map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => onTabChange(candidate.id)}
              aria-current={tab === candidate.id ? 'page' : undefined}
              className={cn(
                'flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition-all',
                tab === candidate.id
                  ? 'bg-surface-raised text-ink shadow-[0_1px_3px_rgba(30,50,30,0.1)]'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              {candidate.label}
            </button>
          ))}
        </nav>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close library"
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-lg text-ink-muted hover:bg-surface-sunken hover:text-ink"
        >
          ×
        </button>
      </div>

      <div className="min-h-0 flex-1">
        {view === 'analysis' && analysisDocumentId ? (
          <AnalysisView
            documentId={analysisDocumentId}
            initialRun={analysisRun}
            onClose={() => onTabChange('artifacts')}
          />
        ) : view === 'task' && resumeTaskId ? (
          <TaskResumePanel
            workspaceId={workspaceId}
            taskId={resumeTaskId}
            onOpenThread={onOpenThread}
            onClose={() => onTabChange('artifacts')}
          />
        ) : view === 'team' && settingsTeamId ? (
          <TeamSettings
            teamId={settingsTeamId}
            onClose={() => onTabChange(tab)}
          />
        ) : view === 'documents' ? (
          <DocumentPanel
            workspaceId={workspaceId}
            onSelectDocument={onSelectDocument}
            compactUpload
          />
        ) : (
          <ArtifactPanel
            workspaceId={workspaceId}
            onResumeTask={onResumeTask}
            onOpenAnalysis={onOpenAnalysis}
          />
        )}
      </div>
    </div>
  )
}

function TopBar({
  threadsOpen,
  rightOpen,
  onToggleThreads,
  onToggleRight,
  onOpenTeam,
}: {
  threadsOpen: boolean
  rightOpen: boolean
  onToggleThreads: () => void
  onToggleRight: () => void
  onOpenTeam: (teamId: string) => void
}) {
  const user = useAuthStore((state) => state.user)
  const signOut = useAuthStore((state) => state.signOut)
  const { data: teams } = useTeams()

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border-subtle/80 bg-surface-raised/85 px-3 shadow-[0_1px_0_rgba(30,50,30,0.04)] backdrop-blur-md sm:px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <button
          type="button"
          onClick={onToggleThreads}
          aria-label={threadsOpen ? 'Collapse threads' : 'Open threads'}
          aria-pressed={threadsOpen}
          className={cn(
            'flex size-8 items-center justify-center rounded-lg transition-colors',
            threadsOpen
              ? 'bg-accent-soft text-accent-strong'
              : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
          )}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <span
          className="flex size-8 items-center justify-center rounded-xl bg-accent-soft text-lg"
          aria-hidden="true"
        >
          🥑
        </span>
        <span className="font-display text-lg font-semibold tracking-tight text-ink">
          Avocado
        </span>
        {user && (
          <span className="ml-1 hidden truncate rounded-full bg-surface-sunken px-2.5 py-0.5 text-xs font-medium text-ink-muted md:inline">
            {user.organization_name}
          </span>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        {teams && teams.length > 0 && (
          <label className="flex items-center gap-1.5">
            <span className="sr-only">Team settings</span>
            <select
              value=""
              onChange={(e) => e.target.value && onOpenTeam(e.target.value)}
              className="h-8 max-w-[8rem] truncate rounded-lg border border-border-subtle bg-surface px-2 text-sm text-ink sm:max-w-none"
            >
              <option value="">Team…</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <ModelPicker />
        <button
          type="button"
          onClick={onToggleRight}
          aria-label={rightOpen ? 'Close documents and artifacts' : 'Open documents and artifacts'}
          aria-pressed={rightOpen}
          className={cn(
            'flex h-8 items-center gap-1.5 rounded-lg px-2 text-sm font-medium transition-colors',
            rightOpen
              ? 'bg-accent-soft text-accent-strong'
              : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
          )}
        >
          <span aria-hidden="true">▤</span>
          <span className="hidden sm:inline">Library</span>
        </button>
        {user && (
          <span
            title={user.email}
            className="hidden max-w-[12rem] truncate text-sm text-ink-muted lg:inline"
          >
            {user.email}
          </span>
        )}
        <Button variant="ghost" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </div>
    </header>
  )
}

/**
 * The model picker.
 *
 * "Auto" is a real, user-facing choice, not internal plumbing: picking a model
 * pins every request in the workspace to it, and Auto lets the router choose
 * per task. Either way the answer carries the model that produced it.
 */
function ModelPicker() {
  const { data: catalog } = useModels()
  const activeWorkspaceId = useWorkspaceStore((state) => state.activeWorkspaceId)
  const { data: workspaces } = useWorkspaces()
  const updateWorkspace = useUpdateWorkspace()

  const workspace = workspaces?.find((w) => w.id === activeWorkspaceId)
  if (!catalog || !workspace) return null

  return (
    <label className="flex items-center gap-1.5">
      <span className="sr-only">Model</span>
      <select
        value={workspace.preferred_model ?? 'auto'}
        onChange={(e) => {
          const value = e.target.value
          updateWorkspace.mutate({
            id: workspace.id,
            preferred_model: value === 'auto' ? null : value,
          })
        }}
        className="h-8 max-w-[9rem] truncate rounded-lg border border-border-subtle bg-surface px-2 text-sm text-ink sm:max-w-none"
      >
        <option value="auto">
          Auto{catalog.auto_available ? '' : ' (no provider configured)'}
        </option>
        {catalog.models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.display_name}
          </option>
        ))}
      </select>
    </label>
  )
}

function WorkspaceSwitcher() {
  const { data: workspaces } = useWorkspaces()
  const { activeWorkspaceId, setActiveWorkspace } = useWorkspaceStore()
  const createWorkspace = useCreateWorkspace()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')

  return (
    <div className="border-b border-border-subtle p-3">
      <label className="block">
        <span className="sr-only">Workspace</span>
        <select
          value={activeWorkspaceId ?? ''}
          onChange={(e) => setActiveWorkspace(e.target.value)}
          className="h-9 w-full rounded-lg border border-border-subtle bg-surface px-2 text-sm font-medium text-ink"
        >
          {workspaces?.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>
              {workspace.name}
            </option>
          ))}
        </select>
      </label>

      {creating ? (
        <form
          className="mt-2 flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            createWorkspace.mutate(
              { name: name.trim() },
              {
                onSuccess: (workspace) => {
                  setActiveWorkspace(workspace.id)
                  setName('')
                  setCreating(false)
                },
              },
            )
          }}
        >
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workspace name"
            className="h-8 min-w-0 flex-1 rounded-lg border border-border-subtle bg-surface px-2 text-sm"
          />
          <Button type="submit" size="sm" loading={createWorkspace.isPending}>
            Add
          </Button>
        </form>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="mt-2 text-xs font-medium text-accent-strong hover:underline"
        >
          + New workspace
        </button>
      )}
    </div>
  )
}

function ConversationList({
  workspaceId,
  activeConversationId,
  onSelect,
}: {
  workspaceId: string | null
  activeConversationId: string | null
  onSelect: (id: string) => void
}) {
  const { data: conversations } = useConversations(workspaceId)
  const createConversation = useCreateConversation(workspaceId ?? '')
  const deleteConversation = useDeleteConversation(workspaceId ?? '')

  if (!workspaceId) return <div className="flex-1" />

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-3 py-2">
        <Button
          size="sm"
          className="w-full"
          loading={createConversation.isPending}
          onClick={() =>
            createConversation.mutate(undefined, {
              onSuccess: (conversation) => onSelect(conversation.id),
            })
          }
        >
          New conversation
        </Button>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {conversations?.map((conversation) => (
          <li key={conversation.id} className="group">
            <div
              className={cn(
                'flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors',
                activeConversationId === conversation.id
                  ? 'bg-accent-soft'
                  : 'hover:bg-surface-sunken',
              )}
            >
              <button
                onClick={() => onSelect(conversation.id)}
                className="min-w-0 flex-1 text-left"
              >
                <p className="truncate text-sm text-ink">{conversation.title}</p>
                <p className="text-[11px] text-ink-muted">
                  {formatRelativeTime(conversation.updated_at)}
                </p>
              </button>
              <button
                onClick={() => deleteConversation.mutate(conversation.id)}
                aria-label={`Delete ${conversation.title}`}
                className="shrink-0 px-1 text-ink-muted opacity-0 transition-opacity hover:text-danger group-hover:opacity-100 focus:opacity-100"
              >
                ×
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function WorkspaceFooter({ workspaceId }: { workspaceId: string | null }) {
  const { data: stats } = useWorkspaceStats(workspaceId)
  if (!stats) return null

  return (
    <div className="border-t border-border-subtle px-3 py-2.5">
      {/* Named rather than bare counts: "28 chunks" reads as jargon to anyone
          who has not read the ingestion code. */}
      <p className="text-xs text-ink-muted">
        <span className="font-medium text-ink">{stats.ready_document_count}</span> document
        {stats.ready_document_count === 1 ? '' : 's'} searchable
        <span className="px-1 text-border-subtle">·</span>
        {stats.chunk_count} passage{stats.chunk_count === 1 ? '' : 's'} indexed
      </p>
      {stats.document_count > stats.ready_document_count && (
        <p className="mt-1 text-xs text-warning">
          {stats.document_count - stats.ready_document_count} still processing
        </p>
      )}
    </div>
  )
}
