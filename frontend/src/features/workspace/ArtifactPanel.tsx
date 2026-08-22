/**
 * The right rail: artifacts the assistant produced, recent analysis runs, the
 * knowledge map, and projects — so the main pane can stay chat.
 *
 * The first section is the real artifacts store. What follows it used to be
 * called "analysis artifacts", which is why the rail was named this; those
 * are analysis *runs*, and keeping the two apart matters now that artifacts
 * are a first-class thing with versions of their own.
 */

import { useQueries } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { analysisApi } from '@/api/endpoints'
import type { AnalysisRun, DocumentKind, Project, Task, TaskStatus } from '@/api/types'
import { DOCUMENT_KIND_LABEL, TASK_STATUS_LABEL, TASK_STATUSES } from '@/api/types'
import { Badge, Button, EmptyState, Spinner } from '@/components/ui/primitives'
import { ArtifactsSection } from '@/features/artifacts/ArtifactsSection'
import {
  queryKeys,
  useCreateProject,
  useCreateTask,
  useDocuments,
  useKnowledgeMap,
  useProjects,
  useTasks,
  useUpdateTask,
} from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'

export function ArtifactPanel({
  workspaceId,
  onResumeTask,
  onOpenAnalysis,
}: {
  workspaceId: string
  onResumeTask: (taskId: string) => void
  onOpenAnalysis?: (documentId: string, run?: AnalysisRun) => void
}) {
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-2">
      <section className="rounded-xl border border-border-subtle/70 bg-surface-raised p-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
          Artifacts
        </h3>
        <p className="mt-0.5 text-xs text-ink-muted">
          Documents and programs the assistant produced here.
        </p>
        <div className="mt-2.5">
          <ArtifactsSection workspaceId={workspaceId} />
        </div>
      </section>

      <section className="rounded-xl border border-border-subtle/70 bg-surface-raised p-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
          Analysis runs
        </h3>
        <p className="mt-0.5 text-xs text-ink-muted">
          Computed results from spreadsheets — charts, tables, and code.
        </p>
        <div className="mt-2.5">
          <RecentAnalyses workspaceId={workspaceId} onOpenAnalysis={onOpenAnalysis} />
        </div>
      </section>

      <section className="rounded-xl border border-border-subtle/70 bg-surface-raised p-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
          Knowledge
        </h3>
        <p className="mt-0.5 text-xs text-ink-muted">
          Policies and processes classified from your documents.
        </p>
        <div className="mt-2.5">
          <KnowledgeSnippet workspaceId={workspaceId} />
        </div>
      </section>

      <section className="rounded-xl border border-border-subtle/70 bg-surface-raised p-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
          Projects
        </h3>
        <p className="mt-0.5 text-xs text-ink-muted">
          Tasks you can see — open one to pick up where you left off.
        </p>
        <div className="mt-2.5">
          <ProjectsSnippet workspaceId={workspaceId} onResumeTask={onResumeTask} />
        </div>
      </section>
    </div>
  )
}

function RecentAnalyses({
  workspaceId,
  onOpenAnalysis,
}: {
  workspaceId: string
  onOpenAnalysis?: (documentId: string, run?: AnalysisRun) => void
}) {
  const { data: documents, isLoading } = useDocuments(workspaceId)
  const sheets = useMemo(
    () =>
      (documents?.items ?? []).filter(
        (doc) =>
          doc.status === 'ready' && (doc.doc_type === 'csv' || doc.doc_type === 'xlsx'),
      ),
    [documents],
  )

  const runQueries = useQueries({
    queries: sheets.slice(0, 6).map((doc) => ({
      queryKey: queryKeys.analysisRuns(doc.id),
      queryFn: () => analysisApi.listForDocument(doc.id),
      staleTime: 30_000,
    })),
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner className="size-4 text-ink-muted" />
      </div>
    )
  }

  if (!sheets.length) {
    return (
      <EmptyState
        title="No spreadsheets yet"
        description="Upload a CSV or Excel file, then run Analyse to create artifacts."
      />
    )
  }

  const recent = sheets
    .flatMap((doc, index) => {
      const runs = runQueries[index]?.data ?? []
      return runs
        .filter((run) => run.status === 'succeeded')
        .map((run) => ({ doc, run }))
    })
    .sort((a, b) => b.run.created_at.localeCompare(a.run.created_at))
    .slice(0, 8)

  if (!recent.length) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-ink-muted">
          Spreadsheets are ready — open one and run an analysis to create an
          artifact.
        </p>
        <ul className="space-y-1.5">
          {sheets.slice(0, 4).map((doc) => (
            <li key={doc.id}>
              <button
                type="button"
                onClick={() => onOpenAnalysis?.(doc.id)}
                className="w-full rounded-xl border border-border-subtle/70 bg-surface-sunken/40 px-3 py-2 text-left text-sm font-medium text-ink hover:border-accent/40"
              >
                Analyse {doc.filename}
              </button>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <ul className="space-y-1.5">
      {recent.map(({ doc, run }) => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => onOpenAnalysis?.(doc.id, run)}
            className="w-full rounded-xl border border-border-subtle/70 bg-surface-sunken/40 px-3 py-2 text-left transition-colors hover:border-accent/40"
          >
            <p className="truncate text-sm font-medium text-ink">{run.question}</p>
            <p className="mt-0.5 truncate text-[11px] text-ink-muted">
              {doc.filename}
              {run.chart_url ? ' · chart' : ''}
              {' · '}
              {formatRelativeTime(run.created_at)}
            </p>
          </button>
        </li>
      ))}
    </ul>
  )
}

function KnowledgeSnippet({ workspaceId }: { workspaceId: string }) {
  const [kind, setKind] = useState<DocumentKind | undefined>(undefined)
  const { data, isLoading } = useKnowledgeMap(workspaceId, { kind })

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner className="size-4 text-ink-muted" />
      </div>
    )
  }

  const kinds = (Object.keys(data?.counts_by_kind ?? {}) as DocumentKind[]).filter(
    (candidate) => (data?.counts_by_kind[candidate] ?? 0) > 0,
  )
  const items = data?.documents ?? []

  if (!items.length && !kinds.length) {
    return (
      <EmptyState
        title="No classifications yet"
        description="Upload policies or process docs and they will appear here once classified."
      />
    )
  }

  return (
    <div className="space-y-3">
      {kinds.length > 0 && (
        <div className="flex flex-wrap gap-1">
          <FilterChip active={kind === undefined} onClick={() => setKind(undefined)}>
            All
          </FilterChip>
          {kinds.map((candidate) => (
            <FilterChip
              key={candidate}
              active={kind === candidate}
              onClick={() => setKind(kind === candidate ? undefined : candidate)}
            >
              {DOCUMENT_KIND_LABEL[candidate]} ({data!.counts_by_kind[candidate]})
            </FilterChip>
          ))}
        </div>
      )}

      <ul className="space-y-1.5">
        {items.slice(0, 8).map((doc) => (
          <li
            key={doc.document_id}
            className="rounded-xl border border-border-subtle/70 bg-surface-sunken/40 px-3 py-2"
          >
            <p className="truncate text-sm font-medium text-ink">{doc.filename}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge tone="accent">{DOCUMENT_KIND_LABEL[doc.kind]}</Badge>
              {doc.topics.slice(0, 2).map((topic) => (
                <span key={topic} className="text-[11px] text-ink-muted">
                  #{topic}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {items.length > 8 && (
        <p className="text-xs text-ink-muted">{items.length - 8} more in this filter</p>
      )}
    </div>
  )
}

function ProjectsSnippet({
  workspaceId,
  onResumeTask,
}: {
  workspaceId: string
  onResumeTask: (taskId: string) => void
}) {
  const { data: projects, isLoading } = useProjects(workspaceId)
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const projectId = activeProjectId ?? projects?.[0]?.id ?? null
  const { data: tasks } = useTasks(workspaceId, projectId ? { project_id: projectId } : {})
  const createProject = useCreateProject(workspaceId)
  const createTask = useCreateTask(workspaceId)
  const updateTask = useUpdateTask(workspaceId)
  const [newProjectName, setNewProjectName] = useState('')
  const [newTaskTitle, setNewTaskTitle] = useState('')

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner className="size-4 text-ink-muted" />
      </div>
    )
  }

  if (!projects?.length) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-ink-muted">No projects yet.</p>
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!newProjectName.trim()) return
            createProject.mutate(
              { name: newProjectName.trim() },
              { onSuccess: () => setNewProjectName('') },
            )
          }}
        >
          <input
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="New project"
            className="h-8 min-w-0 flex-1 rounded-lg border border-border-subtle bg-surface px-2 text-sm"
          />
          <Button type="submit" size="sm" loading={createProject.isPending}>
            Add
          </Button>
        </form>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {projects.map((project: Project) => (
          <FilterChip
            key={project.id}
            active={project.id === projectId}
            onClick={() => setActiveProjectId(project.id)}
          >
            {project.name}
          </FilterChip>
        ))}
      </div>

      {projectId && (
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!newTaskTitle.trim()) return
            createTask.mutate(
              { projectId, title: newTaskTitle.trim() },
              { onSuccess: () => setNewTaskTitle('') },
            )
          }}
        >
          <input
            value={newTaskTitle}
            onChange={(e) => setNewTaskTitle(e.target.value)}
            placeholder="Add a task"
            className="h-8 min-w-0 flex-1 rounded-lg border border-border-subtle bg-surface px-2 text-sm"
          />
          <Button type="submit" size="sm" loading={createTask.isPending}>
            Add
          </Button>
        </form>
      )}

      <ul className="space-y-1.5">
        {(tasks ?? []).map((task: Task) => (
          <li
            key={task.id}
            className="rounded-xl border border-border-subtle/70 bg-surface-sunken/40 px-3 py-2"
          >
            <button
              type="button"
              onClick={() => onResumeTask(task.id)}
              className="w-full text-left"
            >
              <p className="text-sm font-medium text-ink">{task.title}</p>
              <p className="mt-0.5 text-[11px] text-ink-muted">
                {TASK_STATUS_LABEL[task.status]}
                {task.due_date ? ` · due ${formatRelativeTime(task.due_date)}` : ''}
              </p>
            </button>
            <div className="mt-2 flex flex-wrap gap-1">
              {TASK_STATUSES.map((status: TaskStatus) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => updateTask.mutate({ taskId: task.id, status })}
                  className={cn(
                    'rounded-md px-1.5 py-0.5 text-[10px] font-medium',
                    task.status === status
                      ? 'bg-accent-soft text-accent-strong'
                      : 'text-ink-muted hover:bg-surface-sunken',
                  )}
                >
                  {TASK_STATUS_LABEL[status]}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>

      {(tasks ?? []).length === 0 && (
        <p className="text-xs text-ink-muted">No tasks in this project yet.</p>
      )}
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors',
        active
          ? 'bg-accent text-white'
          : 'bg-surface-sunken text-ink-muted hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}
