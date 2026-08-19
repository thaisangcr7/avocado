/**
 * The application shell: workspace switcher, conversation list, model picker,
 * and the main pane (chat, or analysis when a spreadsheet is opened).
 */

import { useEffect, useState } from 'react'

import type { Document } from '@/api/types'
import { AnalysisView } from '@/features/analysis/AnalysisView'
import { ChatView } from '@/features/chat/ChatView'
import { DocumentPanel } from '@/features/documents/DocumentPanel'
import { Badge, Button, Spinner } from '@/components/ui/primitives'
import {
  useConversations,
  useCreateConversation,
  useCreateWorkspace,
  useDeleteConversation,
  useModels,
  useUpdateWorkspace,
  useWorkspaces,
  useWorkspaceStats,
} from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'

/**
 * Which single pane is visible below `lg`. The three-column layout does not
 * fit a phone, so on small screens exactly one pane is shown at a time and a
 * tab bar switches between them.
 */
type MobilePane = 'menu' | 'main' | 'documents'

export function WorkspaceShell() {
  const { data: workspaces, isLoading } = useWorkspaces()
  const { activeWorkspaceId, setActiveWorkspace } = useWorkspaceStore()
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [analysisDocumentId, setAnalysisDocumentId] = useState<string | null>(null)
  const [mobilePane, setMobilePane] = useState<MobilePane>('main')

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
    <div className="flex h-screen flex-col bg-surface">
      <TopBar />

      <div className="flex min-h-0 flex-1">
        <aside
          className={cn(
            'flex-col border-r border-border-subtle bg-surface-raised',
            'lg:flex lg:w-64 lg:shrink-0',
            mobilePane === 'menu' ? 'flex w-full' : 'hidden',
          )}
        >
          <WorkspaceSwitcher />
          <ConversationList
            workspaceId={activeWorkspaceId}
            activeConversationId={activeConversationId}
            onSelect={(id) => {
              setActiveConversationId(id)
              setAnalysisDocumentId(null)
              // Choosing a thread on a phone should show it, not leave the
              // user staring at the list they just picked from.
              setMobilePane('main')
            }}
          />
          <WorkspaceFooter workspaceId={activeWorkspaceId} />
        </aside>

        <main
          className={cn(
            'min-w-0 flex-1 bg-surface',
            mobilePane === 'main' ? 'block' : 'hidden lg:block',
          )}
        >
          {!workspace ? (
            <div className="flex h-full items-center justify-center text-sm text-ink-muted">
              Create a workspace to begin.
            </div>
          ) : analysisDocumentId ? (
            <AnalysisView
              documentId={analysisDocumentId}
              onClose={() => setAnalysisDocumentId(null)}
            />
          ) : (
            <ChatView
              workspaceId={workspace.id}
              conversationId={activeConversationId}
            />
          )}
        </main>

        <aside
          className={cn(
            'border-l border-border-subtle bg-surface-raised',
            'lg:block lg:w-80 lg:shrink-0',
            mobilePane === 'documents' ? 'block w-full' : 'hidden',
          )}
        >
          {activeWorkspaceId && (
            <DocumentPanel
              workspaceId={activeWorkspaceId}
              onSelectDocument={(document: Document) => {
                setAnalysisDocumentId(document.id)
                setMobilePane('main')
              }}
            />
          )}
        </aside>
      </div>

      <MobileTabBar active={mobilePane} onChange={setMobilePane} />
    </div>
  )
}

function MobileTabBar({
  active,
  onChange,
}: {
  active: MobilePane
  onChange: (pane: MobilePane) => void
}) {
  const tabs: { id: MobilePane; label: string; icon: string }[] = [
    { id: 'menu', label: 'Threads', icon: '☰' },
    { id: 'main', label: 'Chat', icon: '💬' },
    { id: 'documents', label: 'Documents', icon: '📁' },
  ]

  return (
    <nav
      aria-label="Sections"
      className="flex shrink-0 border-t border-border-subtle bg-surface-raised lg:hidden"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          aria-current={active === tab.id ? 'page' : undefined}
          className={cn(
            'flex flex-1 flex-col items-center gap-0.5 py-2 text-xs font-medium transition-colors',
            active === tab.id
              ? 'text-accent-strong'
              : 'text-ink-muted hover:text-ink',
          )}
        >
          <span aria-hidden="true">{tab.icon}</span>
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

function TopBar() {
  const user = useAuthStore((state) => state.user)
  const signOut = useAuthStore((state) => state.signOut)

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border-subtle bg-surface-raised px-3 sm:px-4">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-xl" aria-hidden="true">
          🥑
        </span>
        <span className="font-semibold text-ink">Avocado</span>
        {user && (
          // Secondary identity: the first thing to go when space is tight.
          <span className="ml-2 hidden truncate text-sm text-ink-muted md:inline">
            {user.organization_name}
          </span>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <ModelPicker />
        {user && (
          <span className="hidden truncate text-sm text-ink-muted lg:inline">
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
      <div className="flex flex-wrap gap-1.5">
        <Badge tone="neutral">{stats.ready_document_count} ready</Badge>
        {stats.document_count > stats.ready_document_count && (
          <Badge tone="warning">
            {stats.document_count - stats.ready_document_count} processing
          </Badge>
        )}
        <Badge tone="neutral">{stats.chunk_count} chunks</Badge>
      </div>
    </div>
  )
}
