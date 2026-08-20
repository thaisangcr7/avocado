/**
 * Project board.
 *
 * Only tasks the caller may see arrive here at all — visibility is decided by
 * the server, so this component renders whatever it receives without filtering.
 * The visibility control is shown because "who can see this board" is a
 * deliberate choice a person makes, not a setting to bury.
 */

import { useState } from 'react'

import { ApiError } from '@/api/client'
import type { Project, Task, TaskStatus } from '@/api/types'
import { TASK_STATUS_LABEL, TASK_STATUSES } from '@/api/types'
import {
  Badge,
  Button,
  EmptyState,
  ErrorNotice,
  Input,
  Spinner,
} from '@/components/ui/primitives'
import {
  useCreateProject,
  useCreateTask,
  useDeleteTask,
  useProjects,
  useTasks,
  useUpdateProject,
  useUpdateTask,
} from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'

export function TaskBoard({
  workspaceId,
  onResumeTask,
  onClose,
}: {
  workspaceId: string
  onResumeTask: (taskId: string) => void
  onClose: () => void
}) {
  const { data: projects, isLoading } = useProjects(workspaceId)
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)

  const projectId = activeProjectId ?? projects?.[0]?.id ?? null
  const { data: tasks } = useTasks(workspaceId, projectId ? { project_id: projectId } : {})
  const project = projects?.find((p) => p.id === projectId) ?? null

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink">Projects</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            Tasks you can see: yours, your projects&apos;, and any open board.
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4">
        <ProjectPicker
          workspaceId={workspaceId}
          projects={projects ?? []}
          activeProjectId={projectId}
          onSelect={setActiveProjectId}
        />

        {project ? (
          <>
            <ProjectHeader workspaceId={workspaceId} project={project} />
            <Columns
              workspaceId={workspaceId}
              projectId={project.id}
              tasks={tasks ?? []}
              onResumeTask={onResumeTask}
            />
          </>
        ) : (
          <EmptyState
            title="No projects yet"
            description="Create one to start tracking work. Projects are private to their members unless you open them."
          />
        )}
      </div>
    </div>
  )
}

function ProjectPicker({
  workspaceId,
  projects,
  activeProjectId,
  onSelect,
}: {
  workspaceId: string
  projects: Project[]
  activeProjectId: string | null
  onSelect: (id: string) => void
}) {
  const createProject = useCreateProject(workspaceId)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {projects.map((project) => (
        <button
          key={project.id}
          onClick={() => onSelect(project.id)}
          className={cn(
            'rounded-full border px-3 py-1 text-sm transition-colors',
            project.id === activeProjectId
              ? 'border-accent bg-accent-soft text-accent-strong'
              : 'border-border-subtle text-ink-muted hover:text-ink',
          )}
        >
          {project.name}
        </button>
      ))}

      {creating ? (
        <form
          className="flex gap-1.5"
          onSubmit={async (event) => {
            event.preventDefault()
            setError(null)
            try {
              const created = await createProject.mutateAsync({ name: name.trim() })
              onSelect(created.id)
              setName('')
              setCreating(false)
            } catch (caught) {
              setError(caught instanceof ApiError ? caught.message : 'Could not create it.')
            }
          }}
        >
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Project name"
            className="h-8 w-40"
          />
          <Button type="submit" size="sm" loading={createProject.isPending}>
            Add
          </Button>
        </form>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="rounded-full border border-dashed border-border-subtle px-3 py-1 text-sm text-ink-muted hover:text-accent-strong"
        >
          + New project
        </button>
      )}

      {error && <ErrorNotice message={error} />}
    </div>
  )
}

function ProjectHeader({ workspaceId, project }: { workspaceId: string; project: Project }) {
  const updateProject = useUpdateProject(workspaceId)
  const [error, setError] = useState<string | null>(null)
  const isOpen = project.visibility === 'workspace'

  return (
    <div className="flex flex-wrap items-center gap-3">
      <h3 className="text-base font-semibold text-ink">{project.name}</h3>
      <Badge tone={isOpen ? 'accent' : 'neutral'}>
        {isOpen ? 'Visible to workspace' : 'Members only'}
      </Badge>

      <Button
        size="sm"
        variant="ghost"
        loading={updateProject.isPending}
        onClick={async () => {
          setError(null)
          try {
            await updateProject.mutateAsync({
              projectId: project.id,
              visibility: isOpen ? 'restricted' : 'workspace',
            })
          } catch (caught) {
            setError(caught instanceof ApiError ? caught.message : 'Could not change it.')
          }
        }}
      >
        {isOpen ? 'Restrict to members' : 'Open to workspace'}
      </Button>

      {error && <ErrorNotice message={error} />}
    </div>
  )
}

function Columns({
  workspaceId,
  projectId,
  tasks,
  onResumeTask,
}: {
  workspaceId: string
  projectId: string
  tasks: Task[]
  onResumeTask: (taskId: string) => void
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {TASK_STATUSES.map((status) => (
        <Column
          key={status}
          workspaceId={workspaceId}
          projectId={projectId}
          status={status}
          tasks={tasks.filter((task) => task.status === status)}
          onResumeTask={onResumeTask}
        />
      ))}
    </div>
  )
}

function Column({
  workspaceId,
  projectId,
  status,
  tasks,
  onResumeTask,
}: {
  workspaceId: string
  projectId: string
  status: TaskStatus
  tasks: Task[]
  onResumeTask: (taskId: string) => void
}) {
  const createTask = useCreateTask(workspaceId)
  const [title, setTitle] = useState('')

  return (
    <section className="rounded-xl bg-surface-sunken/60 p-2.5">
      <h4 className="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold text-ink-muted">
        {TASK_STATUS_LABEL[status]}
        <span className="rounded-full bg-surface-raised px-1.5 text-[11px]">
          {tasks.length}
        </span>
      </h4>

      <ul className="space-y-1.5">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            workspaceId={workspaceId}
            task={task}
            onResume={() => onResumeTask(task.id)}
          />
        ))}
      </ul>

      {status === 'todo' && (
        <form
          className="mt-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (!title.trim()) return
            createTask.mutate(
              { projectId, title: title.trim() },
              { onSuccess: () => setTitle('') },
            )
          }}
        >
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Add a task…"
            className="h-8 text-xs"
          />
        </form>
      )}
    </section>
  )
}

function TaskCard({
  workspaceId,
  task,
  onResume,
}: {
  workspaceId: string
  task: Task
  onResume: () => void
}) {
  const updateTask = useUpdateTask(workspaceId)
  const deleteTask = useDeleteTask(workspaceId)

  const overdue =
    task.due_date !== null &&
    task.status !== 'done' &&
    task.due_date < new Date().toISOString().slice(0, 10)

  return (
    <li className="group rounded-lg border border-border-subtle bg-surface-raised p-2.5">
      <p className="text-sm text-ink">{task.title}</p>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {task.due_date && (
          <Badge tone={overdue ? 'danger' : 'neutral'}>
            {overdue ? 'overdue' : 'due'} {task.due_date}
          </Badge>
        )}
        <span className="text-[11px] text-ink-muted/70">
          {formatRelativeTime(task.updated_at)}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <select
          value={task.status}
          onChange={(e) =>
            updateTask.mutate({ taskId: task.id, status: e.target.value as TaskStatus })
          }
          aria-label={`Status for ${task.title}`}
          className="h-6 rounded border border-border-subtle bg-surface px-1 text-[11px]"
        >
          {TASK_STATUSES.map((status) => (
            <option key={status} value={status}>
              {TASK_STATUS_LABEL[status]}
            </option>
          ))}
        </select>

        <Button size="sm" variant="ghost" onClick={onResume} className="h-6 px-1.5 text-[11px]">
          Resume
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => deleteTask.mutate(task.id)}
          className="h-6 px-1.5 text-[11px]"
        >
          Delete
        </Button>
      </div>
    </li>
  )
}
