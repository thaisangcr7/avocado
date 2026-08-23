/**
 * The bell.
 *
 * There is exactly one source of notices right now — a schedule that ran while
 * nobody was watching — and that is the bar for adding more. A surface that
 * accepts everything becomes a second inbox nobody reads, which is worse than
 * not having one.
 *
 * Opening the panel does not mark everything read. Seeing that something
 * arrived is not the same as having read it, and clearing the count on a
 * glance is how people lose things.
 */

import { useState } from 'react'

import type { Notification } from '@/api/types'
import { Button } from '@/components/ui/primitives'
import { useMarkNotificationsRead, useNotifications } from '@/hooks/queries'
import { cn } from '@/lib/utils'

export function NotificationBell({
  onOpenConversation,
}: {
  onOpenConversation?: (conversationId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const { data } = useNotifications()
  const markRead = useMarkNotificationsRead()

  const unread = data?.unread ?? 0
  const notifications = data?.notifications ?? []

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-label={unread > 0 ? `Notifications (${unread} unread)` : 'Notifications'}
        className="relative flex size-10 items-center justify-center rounded-xl text-base text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
      >
        ✽
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="Close notifications"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute bottom-0 left-12 z-50 w-80 overflow-hidden rounded-xl border border-border-subtle bg-surface-raised shadow-xl">
            <header className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
              <span className="text-xs font-semibold text-ink">Notifications</span>
              {unread > 0 && (
                <Button variant="ghost" size="sm" onClick={() => markRead.mutate(undefined)}>
                  Mark all read
                </Button>
              )}
            </header>

            <div className="max-h-80 overflow-y-auto">
              {notifications.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-ink-muted">
                  Nothing yet. Scheduled runs will show up here.
                </p>
              ) : (
                <ul className="divide-y divide-border-subtle">
                  {notifications.map((notification) => (
                    <NotificationRow
                      key={notification.id}
                      notification={notification}
                      onOpen={() => {
                        markRead.mutate(notification.id)
                        if (notification.conversation_id) {
                          onOpenConversation?.(notification.conversation_id)
                          setOpen(false)
                        }
                      }}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function NotificationRow({
  notification,
  onOpen,
}: {
  notification: Notification
  onOpen: () => void
}) {
  const failed = notification.kind === 'schedule_failed'
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cn(
          'block w-full px-3 py-2 text-left transition-colors hover:bg-surface-sunken',
          !notification.read_at && 'bg-accent-soft/30',
        )}
      >
        <span
          className={cn(
            'block text-xs font-medium',
            failed ? 'text-danger' : 'text-ink',
          )}
        >
          {notification.title}
        </span>
        {notification.body && (
          <span className="mt-0.5 line-clamp-2 block text-[11px] text-ink-muted">
            {notification.body}
          </span>
        )}
        <span className="mt-0.5 block text-[10px] text-ink-muted/70">
          {new Date(notification.created_at).toLocaleString()}
        </span>
      </button>
    </li>
  )
}
