/**
 * The primary navigation rail.
 *
 * Replaces a row of tabs in the header, which put the app's main destinations
 * in the same strip as account controls and left them competing for width with
 * an email address. A rail gives them a fixed home and room for a label.
 *
 * Every entry here drives something that already exists. A rail full of
 * destinations that do nothing looks more finished and is worth less.
 */

import type { ReactNode } from 'react'

import { useThemeStore, type ThemeChoice } from '@/stores/theme'
import { cn } from '@/lib/utils'

export type RailDestination = 'chat' | 'history' | 'presets' | 'spaces' | 'library'

const THEME_ICON: Record<ThemeChoice, string> = { system: '◐', light: '☀', dark: '☾' }
const NEXT_THEME: Record<ThemeChoice, ThemeChoice> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
}

export function NavRail({
  active,
  onNavigate,
  onNewChat,
}: {
  active: RailDestination | null
  onNavigate: (destination: RailDestination) => void
  onNewChat: () => void
}) {
  const choice = useThemeStore((state) => state.choice)
  const setChoice = useThemeStore((state) => state.setChoice)

  return (
    <nav
      aria-label="Sections"
      className="hidden w-14 shrink-0 flex-col items-center gap-1 border-r border-border-subtle/80 bg-surface-sunken/60 py-3 lg:flex"
    >
      <RailButton
        label="New chat"
        icon="✎"
        onClick={onNewChat}
        // Deliberately never the "current" destination: it is an action, and
        // showing it selected would imply a place you can be.
        active={false}
      />

      <div className="my-1 h-px w-6 bg-border-subtle/80" />

      <RailButton
        label="Chat"
        icon="◈"
        active={active === 'chat'}
        onClick={() => onNavigate('chat')}
      />
      <RailButton
        label="History"
        icon="↺"
        active={active === 'history'}
        onClick={() => onNavigate('history')}
      />
      <RailButton
        label="Presets"
        icon="/"
        active={active === 'presets'}
        onClick={() => onNavigate('presets')}
      />
      <RailButton
        label="Spaces"
        icon="⬚"
        active={active === 'spaces'}
        onClick={() => onNavigate('spaces')}
      />
      <RailButton
        label="Library"
        icon="▤"
        active={active === 'library'}
        onClick={() => onNavigate('library')}
      />

      <div className="flex-1" />

      <RailButton
        label={`Theme: ${choice}`}
        icon={THEME_ICON[choice]}
        active={false}
        onClick={() => setChoice(NEXT_THEME[choice])}
      />
    </nav>
  )
}

function RailButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string
  icon: ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex size-10 flex-col items-center justify-center rounded-xl text-base transition-colors',
        active
          ? 'bg-accent-soft text-accent-strong'
          : 'text-ink-muted hover:bg-surface-raised hover:text-ink',
      )}
    >
      <span aria-hidden="true">{icon}</span>
    </button>
  )
}
