import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Preset, PresetList } from '@/api/types'
import { PresetsModal } from './PresetsModal'

function preset(overrides: Partial<Preset> = {}): Preset {
  return {
    id: 'p1',
    name: 'Sage',
    slug: 'sage',
    description: 'A patient reviewer.',
    system_prompt: 'Be careful.',
    model_hint: null,
    scope: 'private',
    is_native: false,
    version: 1,
    created_by_user_id: 'u1',
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    pinned: false,
    is_mine: true,
    can_edit: true,
    ...overrides,
  }
}

const LIST: PresetList = {
  presets: [
    preset(),
    preset({
      id: 'p2',
      name: 'House Style',
      slug: 'house-style',
      scope: 'published',
      is_native: true,
      is_mine: false,
      can_edit: false,
    }),
  ],
  total: 2,
}

const create = vi.fn()
const pin = vi.fn()

vi.mock('@/api/endpoints', () => ({
  presetApi: {
    list: () => Promise.resolve(LIST),
    create: (input: unknown) => {
      create(input)
      return Promise.resolve(preset())
    },
    update: () => Promise.resolve(preset()),
    remove: () => Promise.resolve(),
    pin: (id: string) => {
      pin(id)
      return Promise.resolve(preset({ pinned: true }))
    },
    unpin: () => Promise.resolve(preset()),
    publish: () => Promise.resolve(preset({ scope: 'published' })),
    share: () => Promise.resolve(preset()),
  },
}))

function renderModal(onApply?: (p: Preset) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PresetsModal onClose={() => {}} onApply={onApply} />
    </QueryClientProvider>,
  )
}

describe('PresetsModal', () => {
  beforeEach(() => {
    create.mockClear()
    pin.mockClear()
  })

  it('shows the slash command, because that is how a preset is invoked', async () => {
    renderModal()
    expect(await screen.findByText('/sage')).toBeInTheDocument()
  })

  it('shows who can see a preset', async () => {
    renderModal()
    await screen.findByText('Sage')

    // "Private" and "everyone in the organisation" look identical otherwise,
    // and the difference matters before someone writes a prompt into it.
    expect(screen.getByText('private')).toBeInTheDocument()
    expect(screen.getByText('published')).toBeInTheDocument()
  })

  it('marks a platform-authored preset as native', async () => {
    renderModal()
    await screen.findByText('House Style')

    expect(screen.getByText('native')).toBeInTheDocument()
  })

  it('offers no edit control on a preset that is not yours', async () => {
    renderModal()
    await screen.findByText('House Style')

    // One editable preset in the list, so exactly one Edit button.
    expect(screen.getAllByRole('button', { name: /^edit$/i })).toHaveLength(1)
  })

  it('pins a preset', async () => {
    renderModal()
    const toggle = await screen.findByRole('switch', { name: /pin sage/i })

    await userEvent.click(toggle)

    await waitFor(() => expect(pin).toHaveBeenCalledWith('p1'))
  })

  it('hands a chosen preset back to the composer', async () => {
    const onApply = vi.fn()
    renderModal(onApply)
    await screen.findByText('Sage')

    const [useButton] = screen.getAllByRole('button', { name: /^use$/i })
    await userEvent.click(useButton!)

    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ slug: 'sage' }))
  })

  it('will not save a preset with no instruction', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/create a preset/i))

    await userEvent.type(screen.getByPlaceholderText(/code review buddy/i), 'Nameless')

    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
    expect(create).not.toHaveBeenCalled()
  })

  it('creates a preset from the form', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/create a preset/i))

    await userEvent.type(screen.getByPlaceholderText(/code review buddy/i), 'Terse')
    await userEvent.type(screen.getByPlaceholderText(/careful reviewer/i), 'Be brief.')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Terse', system_prompt: 'Be brief.' }),
      ),
    )
  })

  it('says that sharing stops at the organisation', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/create a preset/i))

    expect(screen.getByText(/nothing here leaves your organisation/i)).toBeInTheDocument()
  })
})
