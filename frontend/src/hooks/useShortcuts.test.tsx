import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useShortcuts } from './useShortcuts'

const onNewChat = vi.fn()
const onHistory = vi.fn()
const onPresets = vi.fn()

function Subject() {
  useShortcuts({ onNewChat, onHistory, onPresets })
  return (
    <div>
      <input aria-label="composer" />
      <button>elsewhere</button>
    </div>
  )
}

describe('useShortcuts', () => {
  beforeEach(() => {
    onNewChat.mockClear()
    onHistory.mockClear()
    onPresets.mockClear()
  })

  it('starts a new chat on shift+N', async () => {
    render(<Subject />)
    await userEvent.click(screen.getByRole('button'))

    await userEvent.keyboard('{Shift>}N{/Shift}')

    expect(onNewChat).toHaveBeenCalled()
  })

  it('opens history on shift+H and presets on shift+P', async () => {
    render(<Subject />)
    await userEvent.click(screen.getByRole('button'))

    await userEvent.keyboard('{Shift>}H{/Shift}')
    await userEvent.keyboard('{Shift>}P{/Shift}')

    expect(onHistory).toHaveBeenCalled()
    expect(onPresets).toHaveBeenCalled()
  })

  it('stays out of the way while someone is typing', async () => {
    render(<Subject />)
    await userEvent.click(screen.getByLabelText('composer'))

    await userEvent.keyboard('{Shift>}N{/Shift}')

    // Without this guard, typing a capital N into the composer would start a
    // new conversation and lose the question being written.
    expect(onNewChat).not.toHaveBeenCalled()
    expect(screen.getByLabelText('composer')).toHaveValue('N')
  })

  it('leaves the browser its own chords', async () => {
    render(<Subject />)
    await userEvent.click(screen.getByRole('button'))

    // ⌘⇧N is a private window; hijacking it would be hostile.
    await userEvent.keyboard('{Meta>}{Shift>}N{/Shift}{/Meta}')

    expect(onNewChat).not.toHaveBeenCalled()
  })

  it('ignores an unshifted letter', async () => {
    render(<Subject />)
    await userEvent.click(screen.getByRole('button'))

    await userEvent.keyboard('n')

    expect(onNewChat).not.toHaveBeenCalled()
  })
})
