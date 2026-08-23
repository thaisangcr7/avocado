/**
 * The prompt library.
 *
 * A preset is a named system prompt — the instruction a conversation runs
 * under, saved so it can be reused and handed to a colleague. The card shows
 * the slash command because that is how it is actually invoked: from the
 * composer, by typing it, not from here.
 *
 * Scope is on the card for a reason. "Private" and "everyone in the
 * organisation" look identical otherwise, and the difference matters before
 * someone writes a prompt into it.
 */

import { useMemo, useState } from 'react'

import type { Preset, PresetFilter, PresetInput } from '@/api/types'
import { Badge, Button, ErrorNotice, Spinner } from '@/components/ui/primitives'
import {
  useCreatePreset,
  useDeletePreset,
  usePresets,
  usePublishPreset,
  useSetPresetPinned,
  useUpdatePreset,
} from '@/hooks/queries'
import { cn } from '@/lib/utils'

const TABS: { value: PresetFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pinned', label: 'Pinned' },
  { value: 'mine', label: 'My Presets' },
  { value: 'native', label: 'Native' },
  { value: 'community', label: 'Community' },
  { value: 'shared', label: 'Shared' },
]

const SCOPE_LABEL: Record<string, string> = {
  private: 'private',
  org: 'organisation',
  published: 'published',
}

export function PresetsModal({
  onClose,
  onApply,
}: {
  onClose: () => void
  /** Hand a slash command back to the composer, when opened from there. */
  onApply?: (preset: Preset) => void
}) {
  const [tab, setTab] = useState<PresetFilter>('all')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<Preset | 'new' | null>(null)

  const { data, isLoading, isError } = usePresets(tab, query)
  const setPinned = useSetPresetPinned()
  const publish = usePublishPreset()
  const remove = useDeletePreset()

  const presets = data?.presets ?? []

  if (editing) {
    return (
      <Shell title={editing === 'new' ? 'New preset' : 'Edit preset'} onClose={onClose}>
        <PresetForm
          preset={editing === 'new' ? null : editing}
          onDone={() => setEditing(null)}
        />
      </Shell>
    )
  }

  return (
    <Shell title="Presets" onClose={onClose}>
      <div className="space-y-3 border-b border-border-subtle px-5 py-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search presets…"
          className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        />
        <div className="flex flex-wrap gap-1">
          {TABS.map((option) => (
            <button
              key={option.value}
              onClick={() => setTab(option.value)}
              className={cn(
                'rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
                tab === option.value
                  ? 'bg-accent-soft text-accent-strong'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {isError && <ErrorNotice message="Presets could not be loaded." />}
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-5 text-ink-muted" />
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              onClick={() => setEditing('new')}
              className="rounded-xl border border-dashed border-border-subtle p-3 text-left text-sm text-ink-muted transition-colors hover:border-accent hover:text-ink"
            >
              <span className="font-medium">Create a preset</span>
              <span className="mt-0.5 block text-xs">
                Name an instruction once, then type its slash command.
              </span>
            </button>

            {presets.map((preset) => (
              <PresetCard
                key={preset.id}
                preset={preset}
                onApply={onApply}
                onEdit={() => setEditing(preset)}
                onPin={() => setPinned.mutate({ id: preset.id, pinned: !preset.pinned })}
                onPublish={() => publish.mutate(preset.id)}
                onDelete={() => remove.mutate(preset.id)}
              />
            ))}

            {presets.length === 0 && (
              <p className="col-span-full py-8 text-center text-sm text-ink-muted">
                Nothing here yet.
              </p>
            )}
          </div>
        )}
      </div>
    </Shell>
  )
}

function Shell({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border-subtle bg-surface-raised shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>
        {children}
      </div>
    </div>
  )
}

function PresetCard({
  preset,
  onApply,
  onEdit,
  onPin,
  onPublish,
  onDelete,
}: {
  preset: Preset
  onApply?: (preset: Preset) => void
  onEdit: () => void
  onPin: () => void
  onPublish: () => void
  onDelete: () => void
}) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-sm font-medium text-ink">{preset.name}</p>
            {preset.is_native && <Badge tone="accent">native</Badge>}
            <Badge tone="neutral">{SCOPE_LABEL[preset.scope] ?? preset.scope}</Badge>
          </div>
          {/* How it is actually invoked, so it is legible before it is needed. */}
          <code className="mt-0.5 block text-xs text-accent-strong">/{preset.slug}</code>
          {preset.description && (
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{preset.description}</p>
          )}
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={preset.pinned}
          aria-label={`${preset.pinned ? 'Unpin' : 'Pin'} ${preset.name}`}
          onClick={onPin}
          className={cn(
            'mt-0.5 h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors',
            preset.pinned ? 'bg-accent' : 'bg-border-subtle',
          )}
        >
          <span
            className={cn(
              'block size-4 rounded-full bg-white transition-transform',
              preset.pinned && 'translate-x-4',
            )}
          />
        </button>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {onApply && (
          <Button size="sm" onClick={() => onApply(preset)}>
            Use
          </Button>
        )}
        {preset.can_edit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            Edit
          </Button>
        )}
        {preset.can_edit && preset.scope !== 'published' && (
          <Button variant="ghost" size="sm" onClick={onPublish}>
            Publish
          </Button>
        )}
        {preset.can_edit && (
          <Button variant="ghost" size="sm" onClick={onDelete}>
            Delete
          </Button>
        )}
      </div>
    </div>
  )
}

function PresetForm({ preset, onDone }: { preset: Preset | null; onDone: () => void }) {
  const create = useCreatePreset()
  const update = useUpdatePreset()

  const [form, setForm] = useState<PresetInput>({
    name: preset?.name ?? '',
    description: preset?.description ?? '',
    system_prompt: preset?.system_prompt ?? '',
    scope: preset?.scope ?? 'private',
  })

  const pending = create.isPending || update.isPending
  const failed = create.isError || update.isError
  const valid = useMemo(
    () => form.name.trim().length > 0 && form.system_prompt.trim().length > 0,
    [form],
  )

  function submit() {
    if (!valid) return
    const done = { onSuccess: onDone }
    if (preset) update.mutate({ id: preset.id, input: form }, done)
    else create.mutate(form, done)
  }

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-5">
        {failed && <ErrorNotice message="That preset could not be saved." />}

        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Code review buddy"
            className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </Field>

        <Field label="Description">
          <input
            value={form.description ?? ''}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="What it is for"
            className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </Field>

        <Field label="Instruction">
          <textarea
            value={form.system_prompt}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
            rows={8}
            placeholder="You are a careful reviewer. Prefer specifics over praise."
            className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 font-mono text-xs text-ink focus:border-accent focus:outline-none"
          />
        </Field>

        <Field label="Who can see it">
          <select
            value={form.scope}
            onChange={(e) => setForm({ ...form, scope: e.target.value as PresetInput['scope'] })}
            className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          >
            <option value="private">Only me</option>
            <option value="org">Everyone in my organisation</option>
          </select>
          <p className="mt-1 text-[11px] text-ink-muted">
            Sharing beyond yourself needs a team admin. Nothing here leaves your
            organisation.
          </p>
        </Field>
      </div>

      <footer className="flex items-center justify-end gap-2 border-t border-border-subtle px-5 py-3">
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button size="sm" onClick={submit} disabled={!valid || pending}>
          {pending ? 'Saving…' : 'Save'}
        </Button>
      </footer>
    </>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-muted">{label}</span>
      {children}
    </label>
  )
}
