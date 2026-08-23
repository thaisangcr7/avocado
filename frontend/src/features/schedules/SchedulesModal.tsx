/**
 * Schedules — prompts that run without being asked.
 *
 * Two things are deliberately prominent. The next run time, because a schedule
 * whose recurrence someone mistyped is otherwise indistinguishable from one
 * that is working. And the last error, because a schedule failing quietly for
 * a week is the failure this feature has to be designed against.
 *
 * Cron is offered as presets plus a raw field. A five-field expression is a
 * power-user tool that most people get wrong; the common cases should not
 * require knowing it, and the field is still there when they do.
 */

import { useState } from 'react'

import type { Schedule, ScheduleInput } from '@/api/types'
import { Badge, Button, ErrorNotice, Spinner } from '@/components/ui/primitives'
import {
  useCreateSchedule,
  useDeleteSchedule,
  useSchedules,
  useUpdateSchedule,
} from '@/hooks/queries'
import { cn } from '@/lib/utils'

const COMMON: { label: string; cron: string }[] = [
  { label: 'Every weekday, 9am', cron: '0 9 * * 1-5' },
  { label: 'Every morning, 8am', cron: '0 8 * * *' },
  { label: 'Every Monday, 9am', cron: '0 9 * * 1' },
  { label: 'Every hour', cron: '0 * * * *' },
]

function describe(cron: string): string {
  return COMMON.find((option) => option.cron === cron)?.label ?? cron
}

export function SchedulesModal({
  workspaceId,
  onClose,
}: {
  workspaceId: string
  onClose: () => void
}) {
  const { data: schedules, isLoading, isError } = useSchedules(workspaceId)
  const update = useUpdateSchedule(workspaceId)
  const remove = useDeleteSchedule(workspaceId)
  const [creating, setCreating] = useState(false)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Schedules"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border-subtle bg-surface-raised shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">Schedules</h2>
            <p className="mt-0.5 text-xs text-ink-muted">
              A question asked on a timer. Each run lands in history like any other answer.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {isError && <ErrorNotice message="Schedules could not be loaded." />}
          {isLoading ? (
            <div className="flex justify-center py-10">
              <Spinner className="size-5 text-ink-muted" />
            </div>
          ) : creating ? (
            <ScheduleForm workspaceId={workspaceId} onDone={() => setCreating(false)} />
          ) : (
            <div className="space-y-2">
              <button
                onClick={() => setCreating(true)}
                className="w-full rounded-xl border border-dashed border-border-subtle p-3 text-left text-sm text-ink-muted transition-colors hover:border-accent hover:text-ink"
              >
                <span className="font-medium">New schedule</span>
                <span className="mt-0.5 block text-xs">
                  Ask something on a timer — an overnight brief, a weekly summary.
                </span>
              </button>

              {(schedules ?? []).map((schedule) => (
                <ScheduleRow
                  key={schedule.id}
                  schedule={schedule}
                  onToggle={() =>
                    update.mutate({
                      id: schedule.id,
                      input: { enabled: !schedule.enabled },
                    })
                  }
                  onDelete={() => remove.mutate(schedule.id)}
                />
              ))}

              {(schedules ?? []).length === 0 && (
                <p className="py-6 text-center text-sm text-ink-muted">
                  Nothing scheduled yet.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ScheduleRow({
  schedule,
  onToggle,
  onDelete,
}: {
  schedule: Schedule
  onToggle: () => void
  onDelete: () => void
}) {
  return (
    <div
      className={cn(
        'rounded-xl border border-border-subtle bg-surface p-3',
        !schedule.enabled && 'opacity-70',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-sm font-medium text-ink">{schedule.name}</p>
            {!schedule.enabled && <Badge tone="neutral">paused</Badge>}
            {/* A schedule failing quietly for a week is the whole reason this
                is on the row rather than in a log. */}
            {schedule.last_error && <Badge tone="danger">last run failed</Badge>}
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-muted">{schedule.prompt}</p>
          <p className="mt-1 text-[11px] text-ink-muted/80">
            {describe(schedule.cron)}
            {schedule.enabled && (
              <> · next {new Date(schedule.next_run_at).toLocaleString()}</>
            )}
          </p>
          {schedule.last_error && (
            <p className="mt-1 text-[11px] text-danger">{schedule.last_error}</p>
          )}
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={schedule.enabled}
          aria-label={`${schedule.enabled ? 'Pause' : 'Resume'} ${schedule.name}`}
          onClick={onToggle}
          className={cn(
            'mt-0.5 h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors',
            schedule.enabled ? 'bg-accent' : 'bg-border-subtle',
          )}
        >
          <span
            className={cn(
              'block size-4 rounded-full bg-white transition-transform',
              schedule.enabled && 'translate-x-4',
            )}
          />
        </button>
      </div>

      <div className="mt-2">
        <Button variant="ghost" size="sm" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </div>
  )
}

function ScheduleForm({
  workspaceId,
  onDone,
}: {
  workspaceId: string
  onDone: () => void
}) {
  const create = useCreateSchedule(workspaceId)
  const [form, setForm] = useState<ScheduleInput>({
    name: '',
    prompt: '',
    cron: COMMON[0]!.cron,
  })

  const valid = form.name.trim().length > 0 && form.prompt.trim().length > 0
  const rejected = create.isError

  return (
    <div className="space-y-3">
      {rejected && (
        <ErrorNotice message="That schedule was refused — check the recurrence." />
      )}

      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-muted">Name</span>
        <input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Morning brief"
          className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-muted">Question</span>
        <textarea
          value={form.prompt}
          onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          rows={3}
          placeholder="What changed in our documents overnight?"
          className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
        />
      </label>

      <div>
        <span className="mb-1 block text-xs font-medium text-ink-muted">When</span>
        <div className="flex flex-wrap gap-1">
          {COMMON.map((option) => (
            <button
              key={option.cron}
              onClick={() => setForm({ ...form, cron: option.cron })}
              className={cn(
                'rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
                form.cron === option.cron
                  ? 'bg-accent-soft text-accent-strong'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <input
          value={form.cron}
          aria-label="Cron expression"
          onChange={(e) => setForm({ ...form, cron: e.target.value })}
          className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 font-mono text-xs text-ink focus:border-accent focus:outline-none"
        />
        <p className="mt-1 text-[11px] text-ink-muted">
          Minute, hour, day of month, month, day of week.
        </p>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          size="sm"
          disabled={!valid || create.isPending}
          onClick={() => create.mutate(form, { onSuccess: onDone })}
        >
          {create.isPending ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}
