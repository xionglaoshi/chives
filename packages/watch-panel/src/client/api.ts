/** Same-origin GET helpers. The browser only ever talks to the authenticated Host proxy. */
import type {
  AlertPayload,
  AnalysisDetail,
  AnalysisRecord,
  HealthPayload,
  RulesPayload,
  StatePayload,
} from './viewModel.ts'

export const HEALTH_PATH = '/api/watch/health'
export const STATE_PATH = '/api/watch/state'
export const RULES_PATH = '/api/watch/rules'
export const ALERTS_PATH = '/api/watch/alerts'
export const RULES_HISTORY_PATH = '/api/watch/rules/history'
export const ANALYSES_PATH = '/api/watch/analyses'
export const ANALYSIS_PATH = '/api/watch/analysis'
export const MARKET_HEALTH_PATH = '/api/market/health'
export const MARKET_OVERVIEW_PATH = '/api/market/overview'
export const MARKET_SECTORS_PATH = '/api/market/sectors'
export const MARKET_SECTOR_PATH = '/api/market/sector'
export const MARKET_SECTOR_MEMBERS_PATH = '/api/market/sector-members'
export const MARKET_ALERTS_PATH = '/api/market/alerts'
export const MARKET_RULES_PATH = '/api/market/rules'
export const MARKET_MOVERS_PATH = '/api/market/movers'
export const MARKET_SUMMARY_PATH = '/api/market/summary'
export const MARKET_FLOWS_PATH = '/api/market/flows'
export const MARKET_FLOWS_NORTHBOUND_PATH = '/api/market/flows-northbound'
export const HUB_SIGNALS_PATH = '/api/hub/signals'
export const HUB_SPARK_PATH = '/api/hub/spark'
export const HUB_CARDS_PATH = '/api/hub/cards'
/** Mirrors HUB_REVIEW_LAYER_ENABLED in ../hubProxy.ts: battle-card chips are off while the review feature is redesigned. */
export const REVIEW_LAYER_ENABLED = false
export const HUB_SIGNAL_PATH = '/api/hub/signal'
export const HUB_PLANS_PATH = '/api/hub/plans'
export const HUB_SIGNAL_ACTION_PATH = '/api/hub/signal-action'
export const HUB_PLAN_ACTION_PATH = '/api/hub/plan-action'
export const HUB_PORTFOLIO_OVERVIEW_PATH = '/api/hub/portfolio-overview'
export const HUB_PORTFOLIO_HISTORY_PATH = '/api/hub/portfolio-history'
export const ALERT_PAGE_LIMIT = 500
export const ALERT_MAX_PAGES = 10

export interface AlertsPayload {
  alerts?: AlertPayload[]
  count?: number
}

export interface AnalysesPayload {
  records?: AnalysisRecord[]
  count?: number
}

export async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: 'GET', signal, headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`watch request failed: ${response.status}`)
  return await response.json() as T
}

/** Market routes answer business errors with HTTP 200 + `ok:false`; surface them as throws. */
export async function getMarketJson<T extends { ok?: boolean }>(path: string, signal: AbortSignal): Promise<T> {
  const payload = await getJson<T>(path, signal)
  if (payload && payload.ok === false) throw new Error('market request was not ok')
  return payload
}

export function sectorDetailPath(code: string): string {
  return `${MARKET_SECTOR_PATH}?code=${encodeURIComponent(code)}`
}

export function sectorMembersPath(code: string): string {
  return `${MARKET_SECTOR_MEMBERS_PATH}?code=${encodeURIComponent(code)}`
}

export function analysisPath(id: number): string {
  return `${ANALYSIS_PATH}?id=${encodeURIComponent(String(id))}`
}

export function signalDetailPath(id: number): string {
  return `${HUB_SIGNAL_PATH}?id=${encodeURIComponent(String(id))}`
}

/** Portfolio history query; `days` is already clamped to the proxy's 7–365 range. */
export function portfolioHistoryPath(days: number): string {
  return `${HUB_PORTFOLIO_HISTORY_PATH}?days=${encodeURIComponent(String(days))}`
}

/** Hub private reads answer business errors with HTTP 200 + `ok:false`; surface them as throws. */
export async function getHubJson<T extends { ok?: boolean }>(path: string, signal: AbortSignal): Promise<T> {
  const payload = await getJson<T>(path, signal)
  if (payload && payload.ok === false) throw new Error('hub request was not ok')
  return payload
}

/** Restricted hub write: the action header is mandatory, the body is validated server-side. */
export async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'content-type': 'application/json',
      'x-chives-action': '1',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new Error(`hub write failed: ${response.status}`)
  return await response.json() as T
}

export type { AlertPayload, AnalysisDetail, AnalysisRecord, HealthPayload, RulesPayload, StatePayload }

const SPARK_CODE = /^\d{6}\.(SH|SZ)$/

/** Hub `/spark` query for stock codes: deduped, SH/SZ only, at most 30; null when no valid code remains. */
export function sparkPath(codes: readonly string[]): string | null {
  const unique = [...new Set(codes.filter((code) => SPARK_CODE.test(code)))].slice(0, 30)
  return unique.length === 0 ? null : `${HUB_SPARK_PATH}?codes=${unique.join(',')}`
}
