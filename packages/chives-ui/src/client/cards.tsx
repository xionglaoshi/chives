/** Six quick-start cards above the composer: fill the draft, never submit. */
import { useEffect, useRef } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import { CARD_STAGGER_MS, QUICK_CARDS } from './cards.ts'
import { ASK_EVENT, takePending } from './draftBridge.ts'
import { zh, type ChivesKey } from './locales.ts'

/** The part of `InputActions` used here (official API: replace the draft). */
export interface DraftActions {
  setDraft(text: string): void
}

/** Owner props actually consumed; the rest of the session snapshot is ignored. */
export interface QuickCardsProps {
  t?: (key: ChivesKey) => string
  inputActions?: DraftActions
  session?: { blank?: boolean } | undefined
}

interface HoverPoint {
  el: HTMLElement
  x: number
  y: number
}

/** Welcome-page cards; hidden as soon as the session stops being blank. */
export function QuickCards({ t, inputActions, session }: QuickCardsProps): ReactElement | null {
  const translate = t ?? ((key: ChivesKey): string => zh[key])
  const frame = useRef<number | null>(null)
  const point = useRef<HoverPoint | null>(null)

  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
  }, [])

  useEffect(() => {
    if (!inputActions) return
    const applyPending = (): void => {
      const text = takePending()
      if (text !== null) inputActions.setDraft(text)
    }
    applyPending()
    if (typeof window === 'undefined') return
    const listener = (): void => { window.setTimeout(applyPending, 0) }
    window.addEventListener(ASK_EVENT, listener)
    return () => window.removeEventListener(ASK_EVENT, listener)
  }, [inputActions])

  if (!session?.blank) return null

  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>): void => {
    const el = event.currentTarget
    const rect = el.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return
    point.current = {
      el,
      x: ((event.clientX - rect.left) / rect.width) * 100,
      y: ((event.clientY - rect.top) / rect.height) * 100,
    }
    if (frame.current !== null) return
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      const latest = point.current
      if (!latest || !latest.el.isConnected) return
      latest.el.style.setProperty('--chives-mx', `${latest.x}%`)
      latest.el.style.setProperty('--chives-my', `${latest.y}%`)
    })
  }

  return (
    <div className="chives-cards">
      <p className="chives-cards-title">{translate('cardsHeading')}</p>
      {QUICK_CARDS.map((card, index) => (
        <button
          key={card.id}
          type="button"
          className="chives-card"
          style={{ animationDelay: `${index * CARD_STAGGER_MS}ms` } as CSSProperties}
          onPointerMove={onPointerMove}
          onClick={() => { inputActions?.setDraft(translate(card.prompt)) }}
        >
          <span className="chives-card-text">{translate(card.prompt)}</span>
        </button>
      ))}
    </div>
  )
}
