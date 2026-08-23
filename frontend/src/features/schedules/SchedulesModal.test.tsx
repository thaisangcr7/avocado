import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Schedule } from '@/api/types'
import { SchedulesModal } from './SchedulesModal'

function schedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 's1',
    workspace_id: 'w',
    name: 'Morning brief',
    prompt: 'What changed overnight?',
    cron: '0 9 * * 1-5',
    preset_id: null,
    enabled: true,
    next_run_at: '2026-08-24T09:00:00Z',
    last_run_at: null,
    last_error: null,
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    ...overrides,
  }
}

const created = vi.fn()
const updated = vi.fn()
let LIST: Schedule[] = [schedule()]

vi.mock('@/api/endpoints', () => ({
  scheduleApi: {
    list: () => Promise.resolve(LIST),
    create: (_w: string, input: unknown) => {
      created(input)
      return Promise.resolve(schedule())
    },
    update: (_w: string, id: string, input: unknown) => {
      updated(id, input)
      return Promise.resolve(schedule({ enabled: false }))
    },
    remove: () => Promise.resolve(),
  },
}))

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SchedulesModal workspaceId="w" onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('SchedulesModal', () => {
  beforeEach(() => {
    created.mockClear()
    updated.mockClear()
    LIST = [schedule()]
  })

  it('shows when a schedule next runs', async () => {
    renderModal()
    await screen.findByText('Morning brief')

    // A mistyped recurrence is otherwise indistinguishable from a working one.
    expect(screen.getByText(/next /i)).toBeInTheDocument()
    expect(screen.getByText(/every weekday, 9am/i)).toBeInTheDocument()
  })

  it('surfaces a failing schedule rather than leaving it in a log', async () => {
    LIST = [schedule({ last_error: 'the model is on fire' })]
    renderModal()
    await screen.findByText('Morning brief')

    // Failing quietly for a week is the failure this feature designs against.
    expect(screen.getByText(/last run failed/i)).toBeInTheDocument()
    expect(screen.getByText(/the model is on fire/i)).toBeInTheDocument()
  })

  it('does not promise a next run for a paused schedule', async () => {
    LIST = [schedule({ enabled: false })]
    renderModal()
    await screen.findByText('Morning brief')

    expect(screen.getByText(/paused/i)).toBeInTheDocument()
    expect(screen.queryByText(/next /i)).not.toBeInTheDocument()
  })

  it('pauses a schedule without deleting it', async () => {
    renderModal()
    await screen.findByText('Morning brief')

    await userEvent.click(screen.getByRole('switch', { name: /pause morning brief/i }))

    await waitFor(() => expect(updated).toHaveBeenCalledWith('s1', { enabled: false }))
  })

  it('offers the common recurrences without requiring cron', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/new schedule/i))

    await userEvent.type(screen.getByPlaceholderText(/morning brief/i), 'Weekly')
    await userEvent.type(screen.getByPlaceholderText(/changed in our documents/i), 'Summarise')
    await userEvent.click(screen.getByRole('button', { name: /every monday, 9am/i }))
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() =>
      expect(created).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Weekly', cron: '0 9 * * 1' }),
      ),
    )
  })

  it('still allows a raw cron expression', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/new schedule/i))

    const field = screen.getByLabelText(/cron expression/i)
    await userEvent.clear(field)
    await userEvent.type(field, '15 3 * * 0')

    expect(field).toHaveValue('15 3 * * 0')
  })

  it('will not save a schedule with no question', async () => {
    renderModal()
    await userEvent.click(await screen.findByText(/new schedule/i))

    await userEvent.type(screen.getByPlaceholderText(/morning brief/i), 'Nameless')

    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
  })
})
