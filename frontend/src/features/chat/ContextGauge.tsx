/**
 * How much of the model's context window this conversation has left.
 *
 * The most confusing property of a long thread is that answer quality falls off
 * as the window fills, and it does so silently — the thread just gets vaguer.
 * This makes it visible before it bites.
 *
 * No new request and no new endpoint: every assistant message already records
 * what was actually sent to produce it, and the model catalogue already carries
 * each model's window. The estimate is arithmetic over data the page is holding.
 */

import { useMemo } from 'react'

import type { Message, ModelInfo } from '@/api/types'
import { cn } from '@/lib/utils'

/** Below this, the thread is close enough to the ceiling to say so. */
const WARN_BELOW = 0.25
const DANGER_BELOW = 0.1

export function estimateContext(
  messages: Message[] | undefined,
  models: ModelInfo[] | undefined,
): { usedTokens: number; windowTokens: number; fractionLeft: number } | null {
  if (!messages?.length || !models?.length) return null

  // The last assistant turn is the only honest measure of what a call to this
  // conversation costs: it is what the server actually sent, retrieved sources
  // and system prompt included, rather than a guess from message lengths.
  const last = [...messages]
    .reverse()
    .find((m) => m.role === 'assistant' && m.input_tokens != null && m.model_used)
  if (!last) return null

  const model = models.find((m) => m.id === last.model_used)
  if (!model?.context_window) return null

  // The next call carries this turn's input plus the reply it produced, so both
  // count against what is left.
  const usedTokens = (last.input_tokens ?? 0) + (last.output_tokens ?? 0)
  const fractionLeft = Math.max(0, Math.min(1, 1 - usedTokens / model.context_window))

  return { usedTokens, windowTokens: model.context_window, fractionLeft }
}

export function ContextGauge({
  messages,
  models,
}: {
  messages: Message[] | undefined
  models: ModelInfo[] | undefined
}) {
  const estimate = useMemo(() => estimateContext(messages, models), [messages, models])

  // Nothing has been sent yet, so there is nothing honest to report.
  if (!estimate) return null

  const percentLeft = Math.round(estimate.fractionLeft * 100)
  const tone =
    estimate.fractionLeft <= DANGER_BELOW
      ? 'text-danger'
      : estimate.fractionLeft <= WARN_BELOW
        ? 'text-warning'
        : 'text-ink-muted'

  return (
    <div
      className={cn('mb-2 flex items-center justify-end gap-1.5 text-xs', tone)}
      title={`${estimate.usedTokens.toLocaleString()} of ${estimate.windowTokens.toLocaleString()} tokens used`}
    >
      <Dial fraction={estimate.fractionLeft} />
      <span>
        Context: <span className="font-medium">{percentLeft}%</span> left
      </span>
    </div>
  )
}

function Dial({ fraction }: { fraction: number }) {
  const radius = 6
  const circumference = 2 * Math.PI * radius
  return (
    <svg viewBox="0 0 16 16" className="size-3.5 -rotate-90" aria-hidden="true">
      <circle cx="8" cy="8" r={radius} fill="none" stroke="currentColor" strokeOpacity={0.2} strokeWidth="2" />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - fraction)}
      />
    </svg>
  )
}
