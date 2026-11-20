/**
 * Signal action state machine (T100).
 *
 * The card acts optimistically: the local list changes first, the POST decides
 * whether it sticks, and a failed write restores the exact previous list. The
 * module is pure (a `post` port plus a clock) so Node tests can drive every
 * branch without a browser or a hub.
 */
import type { Signal, SignalStatus } from './signals.ts'
import { isSnoozePreset } from './signals.ts'

export type SignalAction =
  | { type: 'ack'; id: number }
  | { type: 'ignore'; id: number }
  | { type: 'snooze'; id: number; until: '30m' | 'close' | 'next_open' }
  | { type: 'unsnooze'; id: number }
  | { type: 'reopen'; id: number }
  | { type: 'done'; id: number }

export interface ActionBody {
  id: number
  action: 'ack' | 'ignore' | 'snooze' | 'unsnooze' | 'done' | 'reopen'
  until?: '30m' | 'close' | 'next_open'
}

const ACTIONS = new Set(['ack', 'ignore', 'snooze', 'unsnooze', 'done', 'reopen'])

export function isSignalActionType(value: unknown): value is ActionBody['action'] {
  return typeof value === 'string' && ACTIONS.has(value)
}

/** Wire body for `POST /api/hub/signal-action`; null for an invalid action. */
export function signalActionBody(action: SignalAction): ActionBody | null {
  if (!Number.isInteger(action.id) || action.id <= 0) return null
  if (action.type === 'snooze') {
    if (!isSnoozePreset(action.until)) return null
    return { id: action.id, action: 'snooze', until: action.until }
  }
  if (!isSignalActionType(action.type)) return null
  return { id: action.id, action: action.type }
}

const NEXT_STATUS: Record<Exclude<SignalAction['type'], 'snooze'>, SignalStatus> = {
  ack: 'seen',
  ignore: 'done',
  unsnooze: 'new',
  reopen: 'new',
  done: 'done',
}

/**
 * Local state after an action, before the hub confirms it. Ignore moves the
 * card into "已处理"; ack only clears the unseen dot; reopen/unsnooze restore it.
 */
export function optimisticSignals(signals: readonly Signal[], action: SignalAction, nowMs = Date.now()): Signal[] {
  const status = action.type === 'snooze' ? 'snoozed' : NEXT_STATUS[action.type]
  return signals.map((signal) => {
    if (signal.id !== action.id) return signal
    if (action.type === 'snooze') {
      return { ...signal, status, snoozeUntil: presetIso(action.until, nowMs) }
    }
    return { ...signal, status, snoozeUntil: null }
  })
}

/** Last local update wins; the caller keeps the previous array for rollback. */
export interface ActionResult {
  ok: boolean
  code: string | null
}

export interface ActionPorts {
  post(body: ActionBody): Promise<ActionResult>
  now(): number
}

export interface ActionOutcome {
  signals: Signal[]
  ok: boolean
  error: string | null
}

/** Optimistic update, then keep it or roll back to the snapshot. */
export async function performSignalAction(
  signals: readonly Signal[],
  action: SignalAction,
  ports: ActionPorts,
): Promise<ActionOutcome> {
  const body = signalActionBody(action)
  if (body === null) return { signals: [...signals], ok: false, error: 'invalid_action' }
  const optimistic = optimisticSignals(signals, action, ports.now())
  let result: ActionResult
  try {
    result = await ports.post(body)
  } catch {
    return { signals: [...signals], ok: false, error: 'hub_unreachable' }
  }
  if (!result.ok) return { signals: [...signals], ok: false, error: result.code ?? 'hub_error' }
  return { signals: optimistic, ok: true, error: null }
}

export type PrimaryIntent =
  | { kind: 'open' }
  | { kind: 'plan'; planId: number | null }
  | { kind: 'signal'; action: SignalAction }
  | { kind: 'ask' }

/** Where the primary button leads; the component owns the resulting side effect. */
export function primaryIntent(signal: Signal): PrimaryIntent {
  switch (signal.primary.action) {
    case 'confirm_plan':
      return { kind: 'plan', planId: signal.source.planId }
    case 'ack':
      return { kind: 'signal', action: { type: 'ack', id: signal.id } }
    case 'remove_watch':
    case 'research':
      return { kind: 'ask' }
    default:
      return { kind: 'open' }
  }
}

export interface PlanActionBody {
  id: number
  action: 'confirm' | 'cancel' | 'extend'
  expires_at?: string
}

export function planActionBody(id: number, action: 'confirm' | 'cancel' | 'extend', expiresAt?: string | null): PlanActionBody | null {
  if (!Number.isInteger(id) || id <= 0 || id > 2 ** 31) return null
  if (action === 'extend') {
    if (typeof expiresAt !== 'string' || !Number.isFinite(Date.parse(expiresAt))) return null
    return { id, action, expires_at: expiresAt }
  }
  if (action === 'cancel') return { id, action }
  return { id, action }
}

export function snoozeLabel(until: '30m' | 'close' | 'next_open'): string {
  if (until === '30m') return '30 \u5206\u949f\u540e'
  if (until === 'close') return '\u6536\u76d8\u524d'
  return '\u660e\u5929\u5f00\u76d8'
}

/** Local ISO target for the snooze chip (the hub owns the authoritative time). */
export function presetIso(until: '30m' | 'close' | 'next_open', nowMs: number): string {
  const base = new Date(Number.isFinite(nowMs) ? nowMs : Date.now())
  if (until === '30m') return new Date(base.getTime() + 30 * 60_000).toISOString()
  const target = new Date(base.getTime())
  if (until === 'close') {
    target.setHours(14, 30, 0, 0)
    if (target.getTime() <= base.getTime()) target.setDate(target.getDate() + 1)
  } else {
    target.setDate(target.getDate() + 1)
    target.setHours(9, 30, 0, 0)
  }
  return target.toISOString()
}

export interface ToastState {
  text: string
  undo: SignalAction | null
  key: number
}

/** Toast copy and the inverse action offered by its "撤销" button. */
export function toastFor(action: SignalAction, key = Date.now()): ToastState | null {
  if (action.type === 'ignore') {
    return { text: '\u5df2\u5ffd\u7565\uff0c\u5df2\u8bb0\u5165\u300c\u5df2\u5904\u7406\u300d', undo: { type: 'reopen', id: action.id }, key }
  }
  if (action.type === 'snooze') {
    return { text: `\u5df2\u8bbe\u7f6e\u63d0\u9192\uff1a${snoozeLabel(action.until)}`, undo: { type: 'unsnooze', id: action.id }, key }
  }
  if (action.type === 'reopen' || action.type === 'unsnooze') {
    return { text: '\u5df2\u91cd\u65b0\u6253\u5f00', undo: null, key }
  }
  return null
}

/** Status used by the card dot/labels after a successful action. */
export function statusAfter(action: SignalAction): SignalStatus {
  return action.type === 'snooze' ? 'snoozed' : NEXT_STATUS[action.type]
}
