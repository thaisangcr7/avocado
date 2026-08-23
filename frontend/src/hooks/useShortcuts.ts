/**
 * Application keyboard shortcuts.
 *
 * The guard is the whole design. These are bare letters with Shift, so without
 * ignoring editable targets, typing a capital N into the composer would start
 * a new conversation and lose what was being written. A shortcut that fires
 * while someone is typing is worse than no shortcut.
 */

import { useEffect } from 'react'

type Handlers = {
  onNewChat: () => void
  onHistory: () => void
  onPresets: () => void
}

/** Whether the event came from somewhere the user is composing text. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export function useShortcuts({ onNewChat, onHistory, onPresets }: Handlers) {
  useEffect(() => {
    function handle(event: KeyboardEvent) {
      if (isTyping(event.target)) return
      // Leave the browser's own chords alone — ⌘⇧N is a private window.
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (!event.shiftKey) return

      const key = event.key.toLowerCase()
      const action =
        key === 'n' ? onNewChat : key === 'h' ? onHistory : key === 'p' ? onPresets : null
      if (!action) return

      event.preventDefault()
      action()
    }

    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [onNewChat, onHistory, onPresets])
}
