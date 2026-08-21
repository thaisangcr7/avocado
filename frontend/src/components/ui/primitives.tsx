/** Small shared building blocks. Styling lives here so pages stay readable. */

import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-white shadow-[0_1px_2px_rgba(30,70,40,0.18)] hover:bg-accent-strong hover:shadow-[0_2px_8px_rgba(30,70,40,0.2)] disabled:bg-ink-muted/40 disabled:shadow-none',
  secondary:
    'bg-surface-raised text-ink border border-border-subtle shadow-[0_1px_2px_rgba(0,0,0,0.03)] hover:bg-surface-sunken',
  ghost: 'text-ink-muted hover:text-ink hover:bg-surface-sunken',
  danger: 'bg-danger-soft text-danger hover:bg-danger hover:text-white',
}

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', size = 'md', loading, disabled, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      // A loading button must also be disabled, or a double-click fires twice.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-xl font-medium',
        'transition-[color,background-color,box-shadow,transform] duration-150',
        'active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:active:scale-100',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
})

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          'h-10 w-full rounded-lg border border-border-subtle bg-surface-raised px-3',
          'text-sm text-ink placeholder:text-ink-muted/70',
          'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
          'disabled:bg-surface-sunken disabled:text-ink-muted',
          className,
        )}
        {...props}
      />
    )
  },
)

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn('animate-spin', className)}
      viewBox="0 0 24 24"
      fill="none"
      role="status"
      aria-label="Loading"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent'

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-sunken text-ink-muted',
  success: 'bg-accent-soft text-accent-strong',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  accent: 'bg-accent-soft text-accent-strong',
}

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-border-subtle/80 bg-surface-raised/90',
        'shadow-[0_1px_2px_rgba(30,50,30,0.04),0_8px_24px_rgba(30,50,30,0.05)]',
        'backdrop-blur-sm',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="animate-in-slow flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      {icon && (
        <div className="flex size-14 items-center justify-center rounded-2xl bg-accent-soft text-accent-strong">
          {icon}
        </div>
      )}
      <div>
        <p className="font-display text-xl font-semibold tracking-tight text-ink">{title}</p>
        {description && (
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-ink-muted text-balance">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  )
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-danger/20 bg-danger-soft px-3 py-2 text-sm text-danger"
    >
      {message}
    </div>
  )
}
