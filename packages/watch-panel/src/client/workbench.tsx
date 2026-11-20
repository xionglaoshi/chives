/**
 * Single-page workbench (T97): pulse band, engine summary, industry map,
 * movers, watchlist-by-stock focus, merged event feed, right-side drawer and a
 * fixed ask bar. The component is split into `WorkbenchView` (pure props, used
 * by the DOM tests) and `Workbench` (state + polling) so the layout can be
 * rendered from fake data without touching the network.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent, ReactElement, KeyboardEvent as ReactKeyboardEvent } from 'react'
import {
  ALERT_MAX_PAGES,
  ALERT_PAGE_LIMIT,
  ALERTS_PATH,
  ANALYSES_PATH,
  HEALTH_PATH,
  HUB_PLAN_ACTION_PATH,
  HUB_SIGNAL_ACTION_PATH,
  HUB_CARDS_PATH,
  REVIEW_LAYER_ENABLED,
  HUB_SIGNALS_PATH,
  sparkPath,
  HUB_SIGNAL_PATH,
  MARKET_ALERTS_PATH,
  MARKET_FLOWS_NORTHBOUND_PATH,
  MARKET_HEALTH_PATH,
  MARKET_MOVERS_PATH,
  MARKET_OVERVIEW_PATH,
  MARKET_RULES_PATH,
  MARKET_SECTORS_PATH,
  MARKET_SUMMARY_PATH,
  RULES_HISTORY_PATH,
  RULES_PATH,
  STATE_PATH,
  analysisPath,
  getJson,
  getMarketJson,
  postJson,
  sectorDetailPath,
  sectorMembersPath,
  signalDetailPath,
} from './api.ts'
import type { AlertsPayload, AnalysesPayload } from './api.ts'
import { HeatLegend, IndexSpark, SectorTreemap, TrendLine } from './charts.tsx'
import { FlowsBlock } from './flowsBlock.tsx'
import {
  DEFAULT_FLOW_FILTERS,
  FLOW_COLUMNS,
  flowsPath,
  normalizeFlows,
  normalizeNorthbound,
  type FlowKind,
  type FlowsPayload,
  type NorthboundPayload,
} from './flows.ts'
import type { WatchPanelKey } from './locales.ts'
import {
  DASH,
  buildTimeline,
  direction,
  distanceToLimit,
  formatMoney,
  formatMove,
  formatStamp,
  isSectorCode,
  marketPulse,
  marketRuleName,
  marketRuleParams,
  maxAbsChange,
  missingReason,
  normalizeMarketAlerts,
  normalizeMarketHealth,
  normalizeMarketRules,
  normalizeMembers,
  normalizeOverview,
  normalizeSectorDetail,
  normalizeSectors,
  rankArrow,
  avatarGlyph,
  avatarTone,
  type SparkPoint,
  type StockSparkSeries,
  normalizeStockSparks,
  normalizeCardChips,
  type CardChip,
} from './market.ts'
import type {
  MarketAlert,
  MarketHealth,
  MarketRule,
  Overview,
  SectorDetail,
  SectorMember,
  SectorRow,
  TimelineItem,
  TradingState,
} from './market.ts'
import { AnalysesTable } from './panel.tsx'
import { Poller } from './polling.ts'
import { DoneFold, RawAlerts, SignalCard, SignalRail, type RawAlertRow } from './signalCards.tsx'
import {
  performSignalAction,
  planActionBody,
  primaryIntent,
  toastFor,
  type ActionResult,
  type SignalAction,
  type ToastState,
} from './signalActions.ts'
import {
  conclusionText,
  doneRows,
  fillPrompt,
  filterSignals,
  normalizeSignals,
  normalizeSignalDetail,
  partitionSignals,
  recheckPrompt,
  signalObjectLabel,
  signalTone,
  type Signal,
  type SignalDetail,
  type SignalFilter,
} from './signals.ts'
import type { SnoozeOption } from './signals.ts'
import type { AreaBasis } from './treemap.ts'
import type {
  AlertPayload,
  AnalysisDetail,
  AnalysisRecord,
  HealthPayload,
  QuoteRow,
  RuleConfig,
  RulesPayload,
  StatePayload,
} from './viewModel.ts'
import {
  alertNameById,
  classifySession,
  continuesFrom,
  formatClock,
  formatPrice,
  mergeAlerts,
  mergeAnalyses,
  nextAfterId,
  quoteRows,
  ruleRows,
} from './viewModel.ts'
import {
  CLOSED_DRAWER,
  DEFAULT_MOVERS_FILTERS,
  MOVERS_PAGE_LIMIT,
  SINGLE_SECTION_ORDER,
  askContext,
  buildFocusRows,
  composeAsk,
  drawerFromRef,
  drawerReducer,
  focusEmphasis,
  indexColumns,
  moversPath,
  normalizeMovers,
  normalizeSummary,
  relativeTime,
  searchAsk,
  sparkKind,
  type DrawerAction,
  type DrawerState,
  type FocusRule,
  type FocusRow,
  type MoversFilters,
  type MoversKind,
  type MoversPayload,
  type SummaryPayload,
  type SummaryRef,
} from './workbenchModel.ts'

export type SectorView = 'heat' | 'table'

export interface RuleHistoryRow {
  ts?: string | null
  action?: string | null
  rule_id?: string | null
  actor?: string | null
}


export interface WorkbenchData {
  /** Battle-card chip per stock code (hub /cards, evaluated by the watch engine); optional. */
  cardChips?: Readonly<Record<string, CardChip>>
  /** Intraday sparklines by code (hub /spark); optional, missing codes render nothing. */
  sparks?: Readonly<Record<string, StockSparkSeries>>
  overview: Overview | null
  health: MarketHealth | null
  watchHealth: HealthPayload | null
  quotes: readonly QuoteRow[]
  rulesByCode: ReadonlyMap<string, readonly FocusRule[]>
  ruleIndex: ReadonlyMap<string, string>
  alertNames: Record<string, string>
  alertTsById: ReadonlyMap<number, string | null>
  ruleById: ReadonlyMap<string, RuleConfig>
  timeline: readonly TimelineItem[]
  analyses: readonly AnalysisRecord[]
  stockRules: ReturnType<typeof ruleRows>
  marketRules: readonly MarketRule[]
  sectors: readonly SectorRow[]
  sectorsAsOf: string | null
  sectorsNote: string | null
  summary: SummaryPayload | null
  movers: Partial<Record<MoversKind, MoversPayload>>
  sectorDetail: SectorDetail | null
  sectorMembers: readonly SectorMember[]
  analysis: AnalysisDetail | null
  history: readonly RuleHistoryRow[]
  signals: readonly Signal[]
  doneSignals: readonly Signal[]
  doneCount: number
  mergedToday: number
  signalDetail: SignalDetail | null
  flows: Partial<Record<FlowKind, FlowsPayload>>
  northbound: NorthboundPayload | null
}

export interface WorkbenchFailures {
  overview: boolean
  marketHealth: boolean
  watch: boolean
  sectors: boolean
  summary: boolean
  movers: boolean
  hub: boolean
  flows: boolean
}

type ChannelName =
  | 'watchHealth' | 'watchState' | 'watchAlerts' | 'watchRules' | 'analyses'
  | 'marketHealth' | 'overview' | 'sectors' | 'marketAlerts' | 'marketRules' | 'summary' | 'movers'
  | 'hubSignals' | 'hubDone' | 'flows' | 'northbound' | 'sparks' | 'cardChips'

type Failures = Record<ChannelName, boolean>

const NO_CHANNEL_FAILURES: Failures = {
  watchHealth: false, watchState: false, watchAlerts: false, watchRules: false, analyses: false,
  marketHealth: false, overview: false, sectors: false, marketAlerts: false, marketRules: false,
  summary: false, movers: false, hubSignals: false, hubDone: false, flows: false, northbound: false, sparks: false, cardChips: false,
}

/** One user gesture on a card; the container owns the fetch/optimistic update. */
export type SignalEvent =
  | { kind: 'primary' | 'recheck' | 'ignore' | 'reopen' | 'open'; signal: Signal }
  | { kind: 'snooze'; signal: Signal; until: SnoozeOption['value'] }

export interface WorkbenchViewProps {
  t: (key: WatchPanelKey, params?: Record<string, unknown>) => string
  now: number
  width: number
  collapsed: boolean
  data: WorkbenchData
  failures: WorkbenchFailures
  pulse: ReturnType<typeof marketPulse>
  summaryFailed: boolean
  sectorView: SectorView
  onSectorView: (view: SectorView) => void
  areaBasis: AreaBasis
  onAreaBasis: (basis: AreaBasis) => void
  moversFilters: MoversFilters
  onMoversFilters: (filters: MoversFilters) => void
  activeOpen: boolean
  onActiveOpen: (open: boolean) => void
  signalFilter: SignalFilter
  onSignalFilter: (filter: SignalFilter) => void
  doneOpen: boolean
  onDoneOpen: (open: boolean) => void
  flowsMore: boolean
  onFlowsMore: (more: boolean) => void
  onSignal: (event: SignalEvent) => void
  toast: ToastState | null
  onUndo: () => void
  pulsing: ReadonlySet<string>
  moverPulse: ReadonlySet<string>
  drawer: DrawerState
  onDrawer: (action: DrawerAction) => void
  signalLoading: boolean
  signalError: boolean
  analysisLoading: boolean
  analysisError: boolean
  sectorDetailError: boolean
  sectorMembersError: boolean
  historyError: boolean
  onHistory: () => void
  askText: string
  onAskText: (text: string) => void
  onAsk: (text: string) => void
  onSearch: (text: string) => void
  onAddWatch: (row: FocusRow | null) => void
  asked: boolean
}

const TRADING_KEY: Record<TradingState, WatchPanelKey> = {
  pre_open: 'sessionPreOpen',
  open: 'sessionOpen',
  lunch: 'sessionBreak',
  closed: 'sessionAfterHours',
  holiday: 'sessionNonTradingDay',
  unknown: 'sessionUnknown',
}

const REGIME_KEY: Record<Overview['regime']['label'], WatchPanelKey> = {
  risk_on: 'regimeRiskOn',
  neutral: 'regimeNeutral',
  risk_off: 'regimeRiskOff',
  unknown: 'regimeUnknown',
}

const PULSE_KEY: Record<ReturnType<typeof marketPulse>, WatchPanelKey> = {
  healthy: 'healthOk',
  warn: 'healthStale',
  idle: 'sessionNonTradingDay',
  unreachable: 'healthUnreachable',
}

const STATUS_KEY: Record<TimelineItem['status'], WatchPanelKey> = {
  analyzed: 'alertAnalyzed',
  analyzing: 'alertAnalyzing',
  skipped: 'alertSkipped',
  pending: 'alertPending',
  failed: 'alertFailed',
}

const KIND_KEY: Record<MoversKind, WatchPanelKey> = {
  gainers: 'wbGainers',
  losers: 'wbLosers',
  active: 'wbActive',
}

/** Direction for the sparkline colour: follows the move's sign, flat for zero or missing. */
function sparkSide(change: number | null | undefined): 'up' | 'down' | 'flat' {
  if (typeof change !== 'number' || !Number.isFinite(change) || change === 0) return 'flat'
  return change > 0 ? 'up' : 'down'
}

function changeClass(value: number | null | undefined): string {
  const side = direction(value)
  return side === 'up' ? 'chives-up' : side === 'down' ? 'chives-down' : 'chives-flat'
}

function tickClass(value: number | null | undefined): string {
  const side = direction(value)
  return side === 'up' ? 'is-up' : side === 'down' ? 'is-down' : ''
}

/** Per-character tick: only digits whose glyph changed remount and animate. */
export function Tick({ text }: { text: string }): ReactElement {
  return (
    <span className="chives-tick">
      {[...text].map((char, index) => <span className="chives-digit" key={`${index}:${char}`}>{char}</span>)}
    </span>
  )
}

function tradingStateOf(overview: Overview | null, health: MarketHealth | null): TradingState {
  return overview?.tradingState ?? health?.tradingState ?? 'unknown'
}

function toneGlyph(tone: SummaryPayload['headlines'][number]['tone']): string {
  if (tone === 'up') return '\u25b2'
  if (tone === 'down') return '\u25bc'
  if (tone === 'warn') return '!'
  return '\u2022'
}

function sectionStyle(index: number): CSSProperties {
  return { animationDelay: `${Math.min(400, index * 40)}ms` }
}

function ruleNameOf(ruleId: string, marketRules: readonly MarketRule[], ruleIndex: ReadonlyMap<string, string>): string {
  if (ruleId === '') return DASH
  const market = marketRules.find((rule) => rule.id === ruleId)
  if (market) return marketRuleName(market)
  return ruleIndex.get(ruleId) ?? ruleId
}

function Pulse(props: {
  t: WorkbenchViewProps['t']
  now: number
  width: number
  collapsed: boolean
  data: WorkbenchData
  pulse: WorkbenchViewProps['pulse']
  summaryFailed: boolean
  state: TradingState
  onDrawer: WorkbenchViewProps['onDrawer']
  onSearch: WorkbenchViewProps['onSearch']
}): ReactElement {
  const { t, now, width, collapsed, data, pulse, summaryFailed, state, onDrawer, onSearch } = props
  const [search, setSearch] = useState('')
  const overview = data.overview
  const indexes = overview?.indexes ?? []
  const breadth = overview?.breadth
  const segments = (() => {
    const up = Math.max(0, breadth?.up ?? 0)
    const down = Math.max(0, breadth?.down ?? 0)
    const flat = Math.max(0, breadth?.flat ?? 0)
    const total = up + down + flat
    if (total <= 0) return { up: 0, down: 0, flat: 100 }
    return { up: (up / total) * 100, down: (down / total) * 100, flat: (flat / total) * 100 }
  })()
  const summary = data.summary
  const relative = relativeTime(summary?.asOf ?? null, now)
  const summaryNote = summary?.stale
    ? t('wbSummaryStale')
    : summaryFailed
      ? t('marketUnreachable')
      : summary?.reason ?? (!summary ? t('loading') : null)
  const primary = indexes[0]
  const submitSearch = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    onSearch(search)
    setSearch('')
  }
  return (
    <header className={`chives-wb-pulse${collapsed ? ' is-collapsed' : ''}`} aria-label={t('wbPulse')}>
      <div className="chives-wb-pulse-row">
        <span className="chives-wb-title">{t('wbWorkbench')}</span>
        <input
          className="chives-wb-search"
          type="search"
          value={search}
          placeholder={t('wbSearchPlaceholder')}
          aria-label={t('wbSearchPlaceholder')}
          onChange={(event) => setSearch(event.currentTarget.value)}
          onKeyDown={submitSearch}
        />
        <span className="chives-wb-regime">{t('wbRegime')} <span className={`chives-wb-regime-value is-${overview?.regime.label ?? 'unknown'}`}>{t(REGIME_KEY[overview?.regime.label ?? 'unknown'])}</span></span>
        <span className={`chives-wb-trading is-${state}`}>{t(TRADING_KEY[state])}</span>
        <span className="chives-wb-pulse-status">
          <span className={`chives-pulse-dot is-${pulse === 'healthy' ? 'healthy' : pulse === 'warn' ? 'warn' : pulse === 'idle' ? 'idle' : 'unreachable'}`} aria-hidden="true" />
          {t(PULSE_KEY[pulse])}
        </span>
        <span className="chives-wb-time">{t('dataTime')} {formatStamp(overview?.asOf ?? data.health?.asOf ?? null)}</span>
        <button type="button" className="chives-wb-rules-button" onClick={() => onDrawer({ type: 'open', kind: 'rules' })}>
          {t('wbEngineRules')}
        </button>
      </div>

      {collapsed ? (
        <div className="chives-wb-pulse-compact">
          {indexes.map((index) => (
            <span className="chives-wb-compact-index" key={index.code}>
              <span className="chives-wb-compact-name">{index.name}</span>
              <span className={changeClass(index.changePct)}>{formatMove(index.changePct)}</span>
            </span>
          ))}
        </div>
      ) : (
        <>
          <div className="chives-wb-index-grid" style={{ gridTemplateColumns: `repeat(${indexColumns(width)}, minmax(0, 1fr))` }}>
            {indexes.map((index) => (
              <article className={`chives-wb-index${index.stale ? ' chives-stale' : ''}`} key={index.code} title={`${t('asOf')} ${formatStamp(index.asOf)}`}>
                <div className="chives-wb-index-head">
                  <span className="chives-wb-index-name">{index.name}<span className="chives-wb-index-code">{index.code}</span></span>
                  <span className={`chives-wb-index-badge ${changeClass(index.changePct)}`}>{formatMove(index.changePct)}</span>
                </div>
                <IndexSpark
                  points={index.spark}
                  kind={index.sparkKind}
                  label={`${index.name} ${t('sparkline')}`}
                  dailyLabel={t('wbSparkDaily')}
                  side={sparkSide(index.changePct)}
                />
                <div className={`chives-wb-index-price chives-tick ${tickClass(index.changePct)}`}><Tick text={formatPrice(index.price)} /></div>
                <div className="chives-wb-index-amount">{formatMoney(index.amountYuan)}</div>
              </article>
            ))}
          </div>
          {indexes.length === 0 ? <div className="chives-wb-empty">{data.overview === null ? t('loading') : t('marketUnreachable')}</div> : null}

          <div className="chives-wb-breadth" aria-label={t('wbBreadth')}>
            <div className="chives-wb-breadth-counts">
              <span className="chives-up">{'\u25b2'} {breadth?.up ?? DASH}</span>
              <span className="chives-flat">{'\u2014'} {breadth?.flat ?? DASH}</span>
              <span className="chives-down">{'\u25bc'} {breadth?.down ?? DASH}</span>
            </div>
            <div className="chives-wb-breadth-track" role="img" aria-label={`${'\u25b2'} ${breadth?.up ?? 0} / ${'\u25bc'} ${breadth?.down ?? 0}`}>
              <span className="chives-wb-breadth-up" style={{ width: `${segments.up}%` }} />
              <span className="chives-wb-breadth-flat" style={{ width: `${segments.flat}%` }} />
              <span className="chives-wb-breadth-down" style={{ width: `${segments.down}%` }} />
            </div>
            <div className="chives-wb-breadth-stats">
              <span>{t('wbLimitUp')} {breadth?.limitUp ?? DASH}</span>
              <span>{t('wbLimitDown')} {breadth?.limitDown ?? DASH}</span>
              <span>{t('wbBroken')} {breadth?.broken ?? DASH}</span>
              <span>{t('wbSeal')} {breadth?.sealRatio == null ? DASH : `${(breadth.sealRatio * 100).toFixed(0)}%`}</span>
              <span>{t('wbMaxStreak')} {breadth?.maxStreak ?? DASH}</span>
              <span>{t('amount')} {formatMoney(breadth?.amountYuan)}</span>
              <span className="chives-wb-primary">{primary ? `${primary.name} ${formatMove(primary.changePct)}` : ''}</span>
            </div>
          </div>

          <section className="chives-wb-summary" aria-label={t('wbSummary')}>
            <div className="chives-wb-summary-head">
              <span className="chives-wb-label">{t('wbSummary')}</span>
              {summary && relative !== DASH ? <span className="chives-wb-summary-age">{t('wbSummaryAge', { time: relative })}</span> : null}
              {summaryNote ? <span className="chives-wb-summary-note">{summaryNote}</span> : null}
            </div>
            {summary && summary.headlines.length > 0 ? (
              <ul className="chives-wb-headlines">
                {summary.headlines.slice(0, 4).map((headline) => (
                  <li className={`chives-wb-headline is-${headline.tone}`} key={headline.id}>
                    <span className={`chives-wb-tone is-${headline.tone}`} aria-hidden="true">{toneGlyph(headline.tone)}</span>
                    <span className="chives-wb-headline-text">
                      <span className="chives-wb-headline-title">{headline.title}</span>
                      <span className="chives-wb-headline-body">
                        {headline.body}
                        {headline.refs.map((ref) => (
                          <button
                            type="button"
                            className="chives-wb-ref"
                            key={`${headline.id}:${ref.type}:${ref.code}`}
                            onClick={() => {
                              const target = drawerFromRef(ref)
                              if (target.kind !== null) onDrawer({ type: 'open', kind: target.kind, code: target.code, id: target.id })
                            }}
                          >
                            {ref.name}
                          </button>
                        ))}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="chives-wb-empty">{summary && summary.ok ? t('wbSummaryEmpty') : t('wbSummaryEmpty')}</div>
            )}
          </section>
        </>
      )}
    </header>
  )
}

function MapBlock(props: {
  t: WorkbenchViewProps['t']
  data: WorkbenchData
  failures: WorkbenchFailures
  view: SectorView
  onView: (view: SectorView) => void
  basis: AreaBasis
  onBasis: (basis: AreaBasis) => void
  onDrawer: WorkbenchViewProps['onDrawer']
  index: number
}): ReactElement {
  const { t, data, failures, view, onView, basis, onBasis, onDrawer, index } = props
  const rows = data.sectors
  const maxAbs = maxAbsChange(rows)
  return (
    <section className="chives-wb-section chives-wb-map" style={sectionStyle(index)} aria-label={t('wbMap')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbMap')}</span>
        <span className="chives-wb-meta">
          {data.sectorsNote ? `${data.sectorsNote} \u00b7 ` : ''}{t('asOf')} {formatStamp(data.sectorsAsOf)}
        </span>
        <div className="chives-wb-switch">
          <button type="button" className={`chives-wb-toggle${view === 'heat' ? ' is-active' : ''}`} aria-pressed={view === 'heat'} onClick={() => onView('heat')}>{t('wbMapHeat')}</button>
          <button type="button" className={`chives-wb-toggle${view === 'table' ? ' is-active' : ''}`} aria-pressed={view === 'table'} onClick={() => onView('table')}>{t('wbMapRank')}</button>
        </div>
        <div className="chives-wb-switch chives-wb-basis" role="group" aria-label={t('wbMapArea')}>
          <button type="button" className={`chives-wb-toggle${basis === 'sqrt' ? ' is-active' : ''}`} aria-pressed={basis === 'sqrt'} onClick={() => onBasis('sqrt')}>{t('wbMapAreaAmount')}</button>
          <button type="button" className={`chives-wb-toggle${basis === 'equal' ? ' is-active' : ''}`} aria-pressed={basis === 'equal'} onClick={() => onBasis('equal')}>{t('wbMapAreaEqual')}</button>
        </div>
      </div>
      {failures.sectors && rows.length === 0 ? <div className="chives-wb-banner is-warn">{t('marketUnreachable')}</div> : null}
      {rows.length === 0 ? <div className="chives-wb-empty">{failures.sectors ? t('marketUnreachable') : t('noSectors')}</div> : view === 'heat' ? (
        <>
          <SectorTreemap
            rows={rows}
            maxAbs={maxAbs}
            selected={null}
            smallLabel={t('smallSample')}
            basis={basis}
            onSelect={(code) => { if (isSectorCode(code)) onDrawer({ type: 'open', kind: 'sector', code }) }}
          />
          <HeatLegend label={t('wbHeatLegend')} />
        </>
      ) : (
        <div className="chives-scroll">
          <table className="chives-table chives-wb-rank">
            <thead>
              <tr>
                <th className="chives-num">#</th>
                <th>{t('name')}</th>
                <th className="chives-num">{t('change')}</th>
                <th className="chives-num">{t('rel300')}</th>
                <th className="chives-num">{t('amountShare')}</th>
                <th className="chives-num">{t('limitUpCount')}</th>
                <th>{t('leaders')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.code} className={`is-clickable${row.stale ? ' chives-stale' : ''}`} onClick={() => { if (isSectorCode(row.code)) onDrawer({ type: 'open', kind: 'sector', code: row.code }) }}>
                  <td className="chives-num">{row.rank ?? DASH}</td>
                  <td>{row.name}{row.small ? <span className="chives-tag is-small">{t('smallSample')}</span> : null}</td>
                  <td className={`chives-num ${changeClass(row.changePct)}`}>{formatMove(row.changePct)}</td>
                  <td className={`chives-num ${changeClass(row.rel300Pct)}`}>{formatMove(row.rel300Pct)}</td>
                  <td className="chives-num">{row.amountShareRatio == null ? DASH : `${(row.amountShareRatio * 100).toFixed(1)}%`}</td>
                  <td className="chives-num">{row.limitUpCount ?? DASH}</td>
                  <td>{row.leaders[0] ? <>{row.leaders[0].name} <span className={changeClass(row.leaders[0].changePct)}>{formatMove(row.leaders[0].changePct)}</span></> : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function MoverList(props: {
  t: WorkbenchViewProps['t']
  kind: MoversKind
  payload: MoversPayload | undefined
  failed: boolean
  pulsing: ReadonlySet<string>
  onOpen: (code: string) => void
}): ReactElement {
  const { t, kind, payload, failed, pulsing, onOpen } = props
  const rows = payload?.rows ?? []
  return (
    <div className="chives-wb-mover-list" aria-label={t(KIND_KEY[kind])}>
      <div className="chives-wb-mover-head">
        <span>{t(KIND_KEY[kind])}</span>
        <span className="chives-wb-meta">{rows.length > 0 ? `${rows.length}` : ''}</span>
      </div>
      {rows.length === 0 ? (
        <div className="chives-wb-empty">{failed ? t('marketUnreachable') : payload?.reason ? missingReason(payload.reason) : t('noData')}</div>
      ) : (
        <ol className="chives-wb-mover-rows">
          {rows.slice(0, MOVERS_PAGE_LIMIT).map((row, position) => (
            <li key={`${kind}:${row.code}`}>
              <button type="button" className={`chives-wb-mover-row${pulsing.has(row.code) ? ` chives-row-pulse ${changeClass(row.changePct)}` : ''}`} onClick={() => onOpen(row.code)}>
                <span className="chives-wb-mover-rank">{row.rank ?? position + 1}</span>
                <span className="chives-wb-mover-name">{row.name}<span className="chives-code">{row.code}</span></span>
                <span className="chives-wb-mover-price chives-num">{formatPrice(row.price)}</span>
                <span className={`chives-wb-mover-change chives-num ${changeClass(row.changePct)}`}>{formatMove(row.changePct)}</span>
                <span className="chives-wb-mover-amount chives-num">{kind === 'active' && row.turnoverPct != null ? `${row.turnoverPct.toFixed(2)}%` : formatMoney(row.amountYuan)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function MoversBlock(props: {
  t: WorkbenchViewProps['t']
  data: WorkbenchData
  failures: WorkbenchFailures
  filters: MoversFilters
  onFilters: (filters: MoversFilters) => void
  activeOpen: boolean
  onActiveOpen: (open: boolean) => void
  pulsing: ReadonlySet<string>
  onDrawer: WorkbenchViewProps['onDrawer']
  index: number
}): ReactElement {
  const { t, data, failures, filters, onFilters, activeOpen, onActiveOpen, pulsing, onDrawer, index } = props
  const toggle = (key: keyof MoversFilters): void => {
    onFilters({ ...filters, [key]: !filters[key] })
  }
  return (
    <section className="chives-wb-section chives-wb-movers" data-wb="movers" style={sectionStyle(index)} aria-label={t('wbMovers')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbMovers')}</span>
        <span className={`chives-wb-meta${data.movers.gainers?.stale || data.movers.losers?.stale || (failures.movers && Object.keys(data.movers).length > 0) ? ' is-stale' : ''}`}>
          {t('asOf')} {formatStamp(data.movers.gainers?.asOf ?? data.movers.losers?.asOf ?? null)}
          {failures.movers && Object.keys(data.movers).length > 0 ? ` · ${t('marketStale')}` : ''}
        </span>
        <div className="chives-wb-filters">
          {(['includeSt', 'includeNew', 'includeBj'] as const).map((key) => (
            <button
              key={key}
              type="button"
              className={`chives-wb-filter${filters[key] ? ' is-active' : ''}`}
              aria-pressed={filters[key]}
              onClick={() => toggle(key)}
            >
              {t(key === 'includeSt' ? 'wbFilterSt' : key === 'includeNew' ? 'wbFilterNew' : 'wbFilterBj')}
            </button>
          ))}
          <button type="button" className={`chives-wb-filter${activeOpen ? ' is-active' : ''}`} aria-pressed={activeOpen} onClick={() => onActiveOpen(!activeOpen)}>
            {activeOpen ? t('wbActiveCollapse') : t('wbActive')}
          </button>
        </div>
      </div>
      <div className={`chives-wb-mover-grid${activeOpen ? ' has-active' : ''}`}>
        <MoverList t={t} kind="gainers" payload={data.movers.gainers} failed={failures.movers} pulsing={pulsing} onOpen={(code) => onDrawer({ type: 'open', kind: 'stock', code })} />
        <MoverList t={t} kind="losers" payload={data.movers.losers} failed={failures.movers} pulsing={pulsing} onOpen={(code) => onDrawer({ type: 'open', kind: 'stock', code })} />
        {activeOpen ? <MoverList t={t} kind="active" payload={data.movers.active} failed={failures.movers} pulsing={pulsing} onOpen={(code) => onDrawer({ type: 'open', kind: 'stock', code })} /> : null}
      </div>
    </section>
  )
}

function RuleBadge({ t, rules }: { t: WorkbenchViewProps['t']; rules: readonly FocusRule[] }): ReactElement {
  const [open, setOpen] = useState(false)
  if (rules.length === 0) return <span className="chives-wb-meta">{t('noActiveRules')}</span>
  const fired = rules.filter((rule) => rule.fired)
  return (
    <span className={`chives-wb-focus-rules${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="chives-wb-rules-badge"
        aria-expanded={open}
        onClick={(event) => { event.stopPropagation(); setOpen((value) => !value) }}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {t('wbRulesBadge', { count: rules.length })}
      </button>
      <span className="chives-wb-rules-pop" role="list">
        {rules.map((rule) => (
          <span className="chives-wb-rule-item" role="listitem" key={rule.ruleId}>
            <span className="chives-rule-code">{rule.ruleId}</span>
            <span className="chives-wb-rule-desc">{rule.description || DASH}</span>
            <span className={`chives-wb-rule-state${rule.armed ? ' is-armed' : ''}`}>
              {rule.armed ? t('armed') : t('unarmed')}{rule.fired ? ` \u00b7 ${t('wbRuleFired')}` : ''}
            </span>
          </span>
        ))}
      </span>
      {fired.map((rule) => (
        <span className="chives-chip is-triggered" key={`fired:${rule.ruleId}`} title={rule.description}>{rule.ruleId}</span>
      ))}
    </span>
  )
}

const CARD_CHIP_KEY: Record<CardChip['state'], 'wbCardProposed' | 'wbCardObserve' | 'wbCardAwait' | 'wbCardExecute' | 'wbCardAbandon' | 'wbCardExit'> = {
  proposed: 'wbCardProposed', observe: 'wbCardObserve', await_confirm: 'wbCardAwait', execute: 'wbCardExecute', abandon: 'wbCardAbandon', exit: 'wbCardExit',
}

function FocusBlock(props: {
  t: WorkbenchViewProps['t']
  data: WorkbenchData
  state: TradingState
  pulsing: ReadonlySet<string>
  now: number
  failed: boolean
  onDrawer: WorkbenchViewProps['onDrawer']
  onSignal: WorkbenchViewProps['onSignal']
  onAddWatch: (row: FocusRow | null) => void
  index: number
}): ReactElement {
  const { t, data, state, pulsing, now, failed, onDrawer, onSignal, onAddWatch, index } = props
  const rows = buildFocusRows(data.quotes, data.rulesByCode, data.timeline, focusEmphasis(state), data.signals)
  return (
    <section className="chives-wb-section chives-wb-focus" style={sectionStyle(index)} aria-label={t('wbFocus')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbFocus')}</span>
        <span className="chives-wb-meta">{t('readOnlyHint')}</span>
        <button type="button" className="chives-wb-add" onClick={() => onAddWatch(rows[0] ?? null)}>
          {t('wbAddWatch')}
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="chives-wb-empty">{failed ? t('bannerUnreachable') : t('wbFocusEmpty')}</div>
      ) : (
        <div className="chives-wb-focus-rows">
          {rows.map((row) => {
            const triggered = focusEmphasis(state) && (row.rules.some((rule) => rule.fired) || row.signal !== null)
            return (
              <article
                key={row.code}
                className={`chives-wb-focus-row${triggered ? ' is-triggered' : ''}${pulsing.has(row.code) ? ' chives-row-pulse' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => onDrawer({ type: 'open', kind: 'stock', code: row.code })}
                onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onDrawer({ type: 'open', kind: 'stock', code: row.code }) }}
              >
                <div className="chives-wb-focus-main">
                  <span className="chives-wb-focus-name">
                    <span className={`chives-wb-avatar is-tone-${avatarTone(row.code)}`} aria-hidden="true">{avatarGlyph(row.name)}</span>
                    <span className="chives-wb-focus-name-text">{row.name}<span className="chives-code">{row.code}</span></span>
                  </span>
                  <span className="chives-wb-focus-spark">
                    {data.sparks?.[row.code] ? (
                      <IndexSpark
                        points={data.sparks[row.code]!.points}
                        kind="intraday"
                        label={`${row.name} ${t('sparkline')}`}
                        dailyLabel={t('wbSparkDaily')}
                        side={sparkSide(row.changePct)}
                        width={64}
                        height={22}
                      />
                    ) : null}
                  </span>
                  <span className={`chives-wb-focus-price chives-num ${changeClass(row.changePct)}`}>{formatPrice(row.price)}</span>
                  <span className={`chives-wb-focus-change chives-num ${changeClass(row.changePct)}`}>{formatMove(row.changePct)}</span>
                  <span className="chives-wb-focus-limit chives-num">
                    {row.limit.pct === null ? DASH : `${row.limit.side === 'up' ? t('wbDistanceUp') : t('wbDistanceDown')} ${row.limit.pct.toFixed(2)}%`}
                  </span>
                  <RuleBadge t={t} rules={row.rules} />
                  {data.cardChips?.[row.code] ? (
                    <button
                      type="button"
                      className={`chives-wb-cardchip is-${data.cardChips[row.code]!.state}`}
                      title={t('wbCardChipTitle')}
                      onClick={(event) => {
                        event.stopPropagation()
                        window.dispatchEvent(new CustomEvent('chives:panel', { detail: { panel: 'chives-review' } }))
                      }}
                    >{t('wbCardChipTitle')}·{t(CARD_CHIP_KEY[data.cardChips[row.code]!.state])}</button>
                  ) : null}
                  <button
                    type="button"
                    className="chives-wb-focus-add"
                    onClick={(event) => { event.stopPropagation(); onAddWatch(row) }}
                  >
                    {t('wbAddWatch')}
                  </button>
                </div>
                <div className="chives-wb-focus-signal">
                  {row.signal ? (
                    <button
                      type="button"
                      className="chives-wb-focus-signal-button"
                      onClick={(event) => { event.stopPropagation(); onSignal({ kind: 'open', signal: row.signal! }) }}
                    >
                      <span className={`chives-sig-dot is-${signalTone(row.signal.kind)}`} aria-hidden="true" />
                      <span className="chives-wb-focus-signal-text">{conclusionText(row.signal)}</span>
                      <span className="chives-wb-focus-signal-time">{formatClock(row.signal.ts)}</span>
                    </button>
                  ) : <span className="chives-wb-meta">{t('wbFocusNoSignal')}</span>}
                </div>
                <div className="chives-wb-focus-latest">
                  {row.latest ? (
                    <>
                      <span className="chives-wb-focus-time">{formatClock(row.latest.ts)}</span>
                      <span className="chives-wb-focus-rule">{row.latest.ruleId || DASH}</span>
                      <span className={`chives-wb-status is-${row.latest.status}`}>{t(STATUS_KEY[row.latest.status])}</span>
                      {row.latest.reason ? <span className="chives-reason">{row.latest.reason}</span> : null}
                      <span className="chives-wb-focus-summary">{row.latest.summary}</span>
                    </>
                  ) : <span className="chives-wb-meta">{t('wbFocusNoLatest')}</span>}
                  <span className="chives-wb-focus-age">{relativeTime(row.latest?.ts ?? null, now)}</span>
                </div>
              </article>
            )
          })}
        </div>
      )}
      <details className="chives-wb-portfolio">
        <summary>{t('wbPortfolio')}</summary>
        <div className="chives-wb-portfolio-body">
          <div className="chives-wb-portfolio-title">{t('wbPortfolioBuilding')}</div>
          <p>{t('wbPortfolioHint')}</p>
        </div>
      </details>
    </section>
  )
}

const FILTER_KEY: Record<SignalFilter, WatchPanelKey> = {
  all: 'wbFeedAll',
  decide: 'wbDecide',
  stock: 'wbFeedMine',
  sector: 'wbFeedSector',
}

function signalHandlers(onSignal: WorkbenchViewProps['onSignal']) {
  return {
    onPrimary: (signal: Signal): void => onSignal({ kind: 'primary', signal }),
    onRecheck: (signal: Signal): void => onSignal({ kind: 'recheck', signal }),
    onSnooze: (signal: Signal, until: SnoozeOption['value']): void => onSignal({ kind: 'snooze', signal, until }),
    onIgnore: (signal: Signal): void => onSignal({ kind: 'ignore', signal }),
  }
}

function DecideBlock({ t, signals, failed, onSignal }: {
  t: WorkbenchViewProps['t']
  signals: readonly Signal[]
  failed: boolean
  onSignal: WorkbenchViewProps['onSignal']
}): ReactElement | null {
  if (signals.length === 0 && !failed) return null
  const handlers = signalHandlers(onSignal)
  return (
    <section className="chives-wb-section chives-wb-decide" aria-label={t('wbDecide')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbDecide')}</span>
        <span className="chives-wb-meta">{signals.length || DASH}</span>
      </div>
      {signals.length === 0 ? <div className="chives-wb-empty">{t('wbHubDown')}</div> : null}
      <div className="chives-sig-hero">
        {signals.map((signal, index) => (
          <SignalCard key={signal.id} t={t} signal={signal} hero index={index} {...handlers} />
        ))}
      </div>
    </section>
  )
}

function SignalBlock({ t, signals, failed, onSignal }: {
  t: WorkbenchViewProps['t']
  signals: readonly Signal[]
  failed: boolean
  onSignal: WorkbenchViewProps['onSignal']
}): ReactElement {
  const handlers = signalHandlers(onSignal)
  return (
    <section className="chives-wb-section chives-wb-signals" data-wb="signals" aria-label={t('wbSignals')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbSignals')}</span>
        <span className="chives-wb-meta">{failed ? DASH : signals.length}</span>
      </div>
      {failed ? (
        <div className="chives-wb-empty">{t('wbHubDown')}</div>
      ) : signals.length === 0 ? (
        <div className="chives-wb-empty">{t('wbSignalEmpty')}</div>
      ) : (
        <SignalRail t={t} signals={signals} {...handlers} />
      )}
    </section>
  )
}

function DoneBlock({ t, data, open, onOpen, failed, onSignal, count, merged }: {
  t: WorkbenchViewProps['t']
  data: WorkbenchData
  open: boolean
  onOpen: (open: boolean) => void
  failed: boolean
  onSignal: WorkbenchViewProps['onSignal']
  count: number
  merged: number
}): ReactElement {
  const rows: RawAlertRow[] = data.timeline.slice(0, 50).map((item) => ({
    key: item.key,
    time: formatClock(item.ts),
    object: item.objectName,
    title: item.title,
    status: t(STATUS_KEY[item.status]),
  }))
  return (
    <section className="chives-wb-section chives-wb-done-block" data-wb="done" aria-label={t('wbDone')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbDone')}</span>
        <span className="chives-wb-meta">{count || DASH}</span>
      </div>
      {data.doneSignals.length === 0 ? <div className="chives-wb-empty">{t('wbDoneEmpty')}</div> : (
        <DoneFold
          t={t}
          signals={doneRows(data.doneSignals)}
          count={count}
          merged={merged}
          open={open}
          onOpen={onOpen}
          onReopen={(signal) => onSignal({ kind: 'reopen', signal })}
        />
      )}
      {failed ? <RawAlerts t={t} rows={rows} failed={failed} /> : null}
    </section>
  )
}

function SignalBar({ t, data, filter, onFilter, failed }: {
  t: WorkbenchViewProps['t']
  data: WorkbenchData
  filter: SignalFilter
  onFilter: (filter: SignalFilter) => void
  failed: boolean
}): ReactElement | null {
  if (failed && data.signals.length === 0 && data.doneSignals.length === 0) return null
  const counts: Record<SignalFilter, number> = {
    all: data.signals.length,
    decide: data.signals.filter((signal) => signal.decide).length,
    stock: data.signals.filter((signal) => signal.object.type === 'stock').length,
    sector: data.signals.filter((signal) => signal.object.type === 'sector').length,
  }
  return (
    <div className="chives-wb-signalbar" role="group" aria-label={t('wbSignals')}>
      <div className="chives-wb-chips">
        {(['all', 'decide', 'stock', 'sector'] as const).map((id) => (
          <button
            key={id}
            type="button"
            className={`chives-wb-chip${filter === id ? ' is-active' : ''}`}
            aria-pressed={filter === id}
            onClick={() => onFilter(id)}
          >
            {t(FILTER_KEY[id])}
            <span className="chives-wb-chip-count">{counts[id]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function AskBar(props: {
  t: WorkbenchViewProps['t']
  value: string
  onChange: (text: string) => void
  onAsk: (text: string) => void
  asked: boolean
}): ReactElement {
  const { t, value, onChange, onAsk, asked } = props
  const submit = (event: FormEvent): void => {
    event.preventDefault()
    onAsk(value)
  }
  return (
    <form className="chives-wb-ask" onSubmit={submit} aria-label={t('wbAsk')}>
      <span className="chives-wb-ask-label">{t('wbAsk')}</span>
      <input
        className="chives-wb-ask-input"
        type="text"
        value={value}
        placeholder={t('wbAskPlaceholder')}
        aria-label={t('wbAskPlaceholder')}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <button type="submit" className="chives-wb-ask-send">{'\u21b5'}</button>
      {asked ? <span className="chives-wb-ask-note">{t('wbAskSent')}</span> : null}
    </form>
  )
}

function DrawerBody(props: {
  t: WorkbenchViewProps['t']
  drawer: DrawerState
  data: WorkbenchData
  now: number
  signalLoading: boolean
  signalError: boolean
  analysisLoading: boolean
  analysisError: boolean
  sectorDetailError: boolean
  sectorMembersError: boolean
  historyError: boolean
  onHistory: () => void
  onDrawer: WorkbenchViewProps['onDrawer']
  onToggleAnalysis: (record: AnalysisRecord) => void
}): ReactElement {
  const {
    t, drawer, data, now, signalLoading, signalError, analysisLoading, analysisError, sectorDetailError, sectorMembersError,
    historyError, onHistory, onDrawer, onToggleAnalysis,
  } = props

  if (drawer.kind === 'signal') {
    const detail = data.signalDetail && data.signalDetail.signal?.id === drawer.id ? data.signalDetail : null
    const signal = detail?.signal
      ?? data.signals.find((entry) => entry.id === drawer.id)
      ?? data.doneSignals.find((entry) => entry.id === drawer.id)
      ?? null
    const sections = detail?.sections
    return (
      <div className="chives-wb-drawer-body">
        <div className="chives-wb-drawer-meta">
          {signal ? <span className={`chives-sig-type is-${signalTone(signal.kind)}`}>{signal.kindLabel}</span> : null}
          <span>{signal ? signalObjectLabel(signal) : `#${drawer.id ?? DASH}`}</span>
          {signal ? <span className="chives-wb-meta">{t('wbSignalDataTime')} {formatStamp(signal.ts)}</span> : null}
          {signal?.source.label ? <span className="chives-wb-meta">{t('wbSignalSource')} {signal.source.label}</span> : null}
        </div>
        {signal ? <h3 className="chives-wb-signal-title">{signal.title}</h3> : null}
        {signalError ? <div className="chives-wb-banner is-warn">{t('wbSignalDetailFailed')}</div> : signalLoading && !detail ? (
          <div className="chives-wb-empty">{t('wbLoading')}</div>
        ) : null}
        {sections ? (
          <div className="chives-wb-signal-sections">
            {sections.conclusion ? <div><span className="chives-wb-label">{t('wbSignalConclusion')}</span><p>{sections.conclusion}</p></div> : null}
            {sections.direction ? <div><span className="chives-wb-label">{t('wbSignalDirection')}</span><p>{sections.direction}</p></div> : null}
            {sections.points.length > 0 ? (
              <div>
                <span className="chives-wb-label">{t('wbSignalPoints')}</span>
                <ul>{sections.points.map((point, index) => <li key={`${index}:${point}`}>{point}</li>)}</ul>
              </div>
            ) : null}
            {sections.detail ? <div><span className="chives-wb-label">{t('wbSignalDetailSection')}</span><p>{sections.detail}</p></div> : null}
          </div>
        ) : null}
        {detail?.markdown ? (
          <>
            <div className="chives-wb-label">{t('wbAnalysis')}</div>
            <pre className="chives-mono chives-wb-analysis">{detail.markdown}</pre>
            {detail.truncated ? <div className="chives-wb-empty">{t('analysisTruncated')}</div> : null}
          </>
        ) : null}
        {signal && !sections && !detail?.markdown && !signalLoading && !signalError ? (
          <div className="chives-wb-empty">{t('wbSignalNoAnalysis')}</div>
        ) : null}
      </div>
    )
  }

  if (drawer.kind === 'sector') {
    const detail = data.sectorDetail && data.sectorDetail.code === drawer.code ? data.sectorDetail : null
    const sector = data.sectors.find((row) => row.code === drawer.code)
    return (
      <div className="chives-wb-drawer-body">
        <div className="chives-wb-drawer-meta">
          <span>{detail?.name ?? sector?.name ?? drawer.code}</span>
          {detail ? <span className={`chives-num ${changeClass(detail.changePct)}`}>{formatMove(detail.changePct)}</span> : null}
          <span>{t('asOf')} {formatStamp(detail?.asOf ?? sector?.asOf ?? null)}</span>
          {detail?.stale ? <span className="chives-tag is-small">{t('stale')}</span> : null}
        </div>
        {sectorDetailError ? <div className="chives-wb-banner is-warn">{t('sectorLoadFailed')}</div> : null}
        {!detail && !sectorDetailError ? <div className="chives-wb-empty">{t('wbLoading')}</div> : null}
        {detail ? (
          <>
            <div className="chives-wb-label">{t('trend')}</div>
            <TrendLine points={detail.trend} label={`${detail.name} ${t('trend')}`} />
            <div className="chives-wb-drawer-kv">
              <span>{t('ret5')} {detail.history.ret5dPct === null ? DASH : formatMove(detail.history.ret5dPct)}</span>
              <span>{t('ret20')} {detail.history.ret20dPct === null ? DASH : formatMove(detail.history.ret20dPct)}</span>
              <span>{t('rank5d')} {detail.history.rank5d ?? DASH}</span>
              <span>{t('rank20d')} {detail.history.rank20d ?? DASH}</span>
              <span>{t('memberCount')} {detail.memberCount ?? DASH}</span>
            </div>
          </>
        ) : null}
        <div className="chives-wb-label">{t('members')}</div>
        {sectorMembersError ? <div className="chives-wb-banner is-warn">{t('sectorLoadFailed')}</div> : data.sectorMembers.length === 0 ? (
          <div className="chives-wb-empty">{t('noMembers')}</div>
        ) : (
          <div className="chives-scroll">
            <table className="chives-table">
              <thead><tr><th>{t('name')}</th><th className="chives-num">{t('price')}</th><th className="chives-num">{t('change')}</th><th className="chives-num">{t('amount')}</th><th className="chives-num">{t('weight')}</th></tr></thead>
              <tbody>
                {data.sectorMembers.map((member) => (
                  <tr key={member.code} className="is-clickable" onClick={() => onDrawer({ type: 'open', kind: 'stock', code: member.code })}>
                    <td>{member.name}<span className="chives-code">{member.code}</span></td>
                    <td className="chives-num">{formatPrice(member.price)}</td>
                    <td className={`chives-num ${changeClass(member.changePct)}`}>{formatMove(member.changePct)}</td>
                    <td className="chives-num">{formatMoney(member.amountYuan)}</td>
                    <td className="chives-num">{member.weightPct === null ? DASH : `${member.weightPct.toFixed(2)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  if (drawer.kind === 'stock') {
    const quote = data.quotes.find((row) => row.code === drawer.code) ?? null
    const mover = Object.values(data.movers).flatMap((payload) => payload?.rows ?? []).find((row) => row.code === drawer.code) ?? null
    const name = quote?.name || mover?.name || drawer.code
    const price = quote?.price ?? mover?.price ?? null
    const changePct = quote?.changePct ?? mover?.changePct ?? null
    const amount = quote?.amountYuan ?? mover?.amountYuan ?? null
    const rules = data.stockRules.filter((row) => row.code === drawer.code)
    const items = data.timeline.filter((item) => item.objectType === 'stock' && item.objectCode === drawer.code).slice(0, 5)
    const analyses = data.analyses.filter((record) => record.code === drawer.code)
    const moverAsOf = data.movers.gainers?.asOf ?? data.movers.losers?.asOf ?? null
    const limit = distanceToLimit(price, quote?.limitUp ?? null, quote?.limitDown ?? null)
    return (
      <div className="chives-wb-drawer-body">
        <div className="chives-wb-drawer-meta">
          <span>{name}</span>
          <span className="chives-num">{formatPrice(price)}</span>
          <span className={`chives-num ${changeClass(changePct)}`}>{formatMove(changePct)}</span>
          <span>{t('amount')} {formatMoney(amount)}</span>
        </div>
        {!quote ? <div className="chives-wb-empty">{t('wbStockNotWatched')}</div> : null}
        <div className="chives-wb-drawer-kv">
          <span>{t('distanceLimit')} {limit.pct === null ? DASH : `${limit.side === 'up' ? t('wbDistanceUp') : t('wbDistanceDown')} ${limit.pct.toFixed(2)}%`}</span>
          <span>{t('limitUpDown')} {quote ? `${formatPrice(quote.limitUp)} / ${formatPrice(quote.limitDown)}` : DASH}</span>
          <span>{t('updatedAt')} {formatClock(quote?.exchTime ?? null)}</span>
        </div>
        <div className="chives-wb-label">{t('rulesForStock')}</div>
        {rules.length === 0 ? <div className="chives-wb-empty">{t('noRules')}</div> : (
          <table className="chives-table">
            <thead><tr><th>{t('alertRule')}</th><th>{t('ruleDescription')}</th><th>{t('ruleState')}</th><th className="chives-num">{t('firedCount')}</th></tr></thead>
            <tbody>{rules.map((rule) => (
              <tr key={rule.ruleId}>
                <td><span className="chives-rule-code">{rule.ruleId}</span></td>
                <td>{rule.description}</td>
                <td>{rule.armed ? t('armed') : t('unarmed')}</td>
                <td className="chives-num">{rule.firedCount}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        <div className="chives-wb-label">{t('wbRecentAlerts')}</div>
        {items.length === 0 ? <div className="chives-wb-empty">{t('wbFocusNoLatest')}</div> : (
          <div className="chives-wb-drawer-alerts">
            {items.map((item) => (
              <button
                key={item.key}
                type="button"
                className="chives-wb-drawer-alert"
                onClick={() => { if (item.analysisId !== null) onDrawer({ type: 'open', kind: 'analysis', id: item.analysisId }) }}
              >
                <span className="chives-wb-focus-time">{formatClock(item.ts)}</span>
                <span className="chives-wb-rule-chip">{item.ruleId || DASH}</span>
                <span className={`chives-wb-status is-${item.status}`}>{t(STATUS_KEY[item.status])}</span>
                <span className="chives-wb-focus-summary">{item.detail || item.title}</span>
              </button>
            ))}
          </div>
        )}
        <div className="chives-wb-label">{t('wbRecentAnalyses')}</div>
        {analyses.length === 0 ? <div className="chives-wb-empty">{t('noAnalyses')}</div> : (
          <AnalysesTable
            t={t}
            records={analyses}
            alertNames={data.alertNames}
            alertTsById={data.alertTsById}
            ruleById={data.ruleById}
            details={{}}
            errors={{}}
            expanded={null}
            onToggle={onToggleAnalysis}
          />
        )}
        {moverAsOf ? <div className="chives-wb-meta">{t('wbDataStale', { time: relativeTime(moverAsOf, now) })}</div> : null}
      </div>
    )
  }

  if (drawer.kind === 'analysis') {
    return (
      <div className="chives-wb-drawer-body">
        <div className="chives-wb-drawer-meta"><span>{t('wbAnalysis')}</span><span>#{drawer.id ?? DASH}</span></div>
        {analysisError ? <div className="chives-wb-banner is-warn">{t('analysisUnavailable')}</div> : analysisLoading ? (
          <div className="chives-wb-empty">{t('analysisLoading')}</div>
        ) : data.analysis ? (
          <>
            <div className="chives-mono chives-wb-analysis">{data.analysis.markdown}</div>
            {data.analysis.truncated ? <div className="chives-wb-empty">{t('analysisTruncated')}</div> : null}
          </>
        ) : <div className="chives-wb-empty">{t('analysisNoAnalysis')}</div>}
      </div>
    )
  }

  if (drawer.kind === 'index') {
    const index = data.overview?.indexes.find((row) => row.code === drawer.code) ?? null
    return (
      <div className="chives-wb-drawer-body">
        <div className="chives-wb-drawer-meta">
          <span>{index?.name ?? drawer.code}</span>
          <span className="chives-code">{drawer.code}</span>
          {index ? <span className={`chives-num ${changeClass(index.changePct)}`}>{formatMove(index.changePct)}</span> : null}
        </div>
        {!index ? <div className="chives-wb-empty">{t('wbLoading')}</div> : (
          <>
            <div className={`chives-wb-index-price chives-tick ${tickClass(index.changePct)}`}><Tick text={formatPrice(index.price)} /></div>
            <div className="chives-wb-drawer-kv">
              <span>{t('amount')} {formatMoney(index.amountYuan)}</span>
              <span>{t('asOf')} {formatStamp(index.asOf)}</span>
              <span>{t('wbRegime')} {t(REGIME_KEY[data.overview?.regime.label ?? 'unknown'])}</span>
            </div>
            <IndexSpark points={index.spark} kind={index.sparkKind} label={`${index.name} ${t('sparkline')}`} dailyLabel={t('wbSparkDaily')} width={320} height={72} />
          </>
        )}
      </div>
    )
  }

  return (
    <div className="chives-wb-drawer-body">
      <div className="chives-wb-drawer-meta"><span>{t('wbRules')}</span><span className="chives-wb-meta">{t('wbRulesHint')}</span></div>
      <div className="chives-wb-label">{t('rulesStock')}</div>
      {data.stockRules.length === 0 ? <div className="chives-wb-empty">{t('noRules')}</div> : (
        <table className="chives-table">
          <thead><tr><th>{t('code')}</th><th>{t('alertRule')}</th><th>{t('ruleDescription')}</th><th>{t('ruleState')}</th></tr></thead>
          <tbody>{data.stockRules.map((row) => (
            <tr key={`${row.code}|${row.ruleId}`}>
              <td>{row.code}</td>
              <td><span className="chives-rule-code">{row.ruleId}</span></td>
              <td>{row.description}</td>
              <td>{row.armed ? t('armed') : t('unarmed')}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <div className="chives-wb-label">{t('rulesSector')}</div>
      {data.marketRules.length === 0 ? <div className="chives-wb-empty">{t('noRules')}</div> : (
        <table className="chives-table">
          <thead><tr><th>{t('alertRule')}</th><th>{t('name')}</th><th>{t('ruleParams')}</th><th>{t('ruleLevel')}</th></tr></thead>
          <tbody>{data.marketRules.map((rule) => (
            <tr key={rule.id}>
              <td><span className="chives-rule-code">{rule.id}</span></td>
              <td>{marketRuleName(rule)}</td>
              <td className="chives-code">{marketRuleParams(rule) || DASH}</td>
              <td>{rule.level ?? DASH}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <div className="chives-wb-drawer-head">
        <span className="chives-wb-label">{t('rulesHistory')}</span>
        <button type="button" className="chives-wb-toggle" onClick={onHistory}>{t('rulesHistory')}</button>
      </div>
      {historyError ? <div className="chives-wb-banner is-warn">{t('sectorLoadFailed')}</div> : data.history.length === 0 ? (
        <div className="chives-wb-empty">{t('rulesHistoryEmpty')}</div>
      ) : (
        <table className="chives-table">
          <thead><tr><th>{t('historyTime')}</th><th>{t('historyAction')}</th><th>{t('historyRule')}</th><th>{t('historyActor')}</th></tr></thead>
          <tbody>{data.history.map((row, index) => (
            <tr key={`${row.ts ?? ''}|${index}`}>
              <td>{formatStamp(row.ts)}</td>
              <td>{row.action ?? DASH}</td>
              <td><span className="chives-rule-code">{row.rule_id ?? DASH}</span></td>
              <td>{row.actor ?? DASH}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  )
}

const DRAWER_TITLE: Record<Exclude<DrawerState['kind'], null>, WatchPanelKey> = {
  sector: 'wbSectorDetail',
  stock: 'wbStockDetail',
  analysis: 'wbAnalysis',
  rules: 'wbRules',
  index: 'wbIndexDetail',
  signal: 'wbSignalDetail',
}

function Drawer(props: {
  t: WorkbenchViewProps['t']
  drawer: DrawerState
  onClose: () => void
  children: ReactElement
}): ReactElement | null {
  const { t, drawer, onClose, children } = props
  const closeRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    if (drawer.kind !== null) closeRef.current?.focus()
  }, [drawer.kind, drawer.code, drawer.id])
  if (drawer.kind === null) return null
  return (
    <div className="chives-wb-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <aside className="chives-wb-drawer" role="dialog" aria-modal="true" aria-label={t(DRAWER_TITLE[drawer.kind])}>
        <header className="chives-wb-drawer-head">
          <h2 className="chives-wb-drawer-title">{t(DRAWER_TITLE[drawer.kind])}</h2>
          <button ref={closeRef} type="button" className="chives-wb-drawer-close" onClick={onClose} aria-label={t('wbDrawerClose')}>{'\u00d7'}</button>
        </header>
        {children}
      </aside>
    </div>
  )
}

/** Pure page: every piece of state arrives through props, so DOM tests can fake it. */
export function WorkbenchView(props: WorkbenchViewProps): ReactElement {
  const {
    t, now, width, collapsed, data, failures, pulse, sectorView, onSectorView, areaBasis, onAreaBasis,
    moversFilters, onMoversFilters, activeOpen, onActiveOpen, signalFilter, onSignalFilter, doneOpen, onDoneOpen,
    flowsMore, onFlowsMore, onSignal, toast, onUndo, pulsing, moverPulse, drawer, onDrawer,
    signalLoading, signalError, analysisLoading, analysisError, sectorDetailError, sectorMembersError, historyError,
    onHistory, askText, onAskText, onAsk, onSearch, onAddWatch, asked,
  } = props
  const state = tradingStateOf(data.overview, data.health)
  const single = width < 1280
  const active = filterSignals(data.signals, signalFilter)
  const partition = partitionSignals(active)
  const done = filterSignals(data.doneSignals.filter((signal) => signal.status === 'done' || signal.status === 'ignored'), signalFilter)

  const toggleAnalysis = (record: AnalysisRecord): void => {
    onDrawer({ type: 'open', kind: 'analysis', id: record.alert_id })
  }

  return (
    <div className={`chives-wb is-${state}`} data-layout={single ? 'single' : 'two'}>
      <Pulse
        t={t}
        now={now}
        width={width}
        collapsed={collapsed}
        data={data}
        pulse={pulse}
        summaryFailed={failures.summary}
        state={state}
        onDrawer={onDrawer}
        onSearch={onSearch}
      />
      {failures.overview || failures.marketHealth ? (
        <div className={`chives-wb-banner${pulse === 'unreachable' ? ' is-critical' : ' is-warn'}`}>
          {pulse === 'unreachable' ? t('marketUnreachable') : t('marketStale')}
        </div>
      ) : null}
      <main className="chives-wb-body" data-columns="market,mine">
        <SignalBar t={t} data={data} filter={signalFilter} onFilter={onSignalFilter} failed={failures.hub} />
        {partition.decide.length > 0 || failures.hub ? (
          <div className="chives-wb-decide-wrap" style={{ order: single ? SINGLE_SECTION_ORDER.decide : 0 }}>
            <DecideBlock t={t} signals={partition.decide} failed={failures.hub} onSignal={onSignal} />
          </div>
        ) : null}
        <div className="chives-wb-col is-market" style={{ order: single ? SINGLE_SECTION_ORDER.map : 1 }}>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.map : 0 }}>
            <MapBlock t={t} data={data} failures={failures} view={sectorView} onView={onSectorView} basis={areaBasis} onBasis={onAreaBasis} onDrawer={onDrawer} index={3} />
          </div>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.movers : 1 }}>
            <MoversBlock
              t={t}
              data={data}
              failures={failures}
              filters={moversFilters}
              onFilters={onMoversFilters}
              activeOpen={activeOpen}
              onActiveOpen={onActiveOpen}
              pulsing={moverPulse}
              onDrawer={onDrawer}
              index={4}
            />
          </div>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.flows : 2 }}>
            <FlowsBlock
              t={t}
              flows={data.flows}
              northbound={data.northbound}
              failed={failures.flows}
              more={flowsMore}
              onMore={onFlowsMore}
              onSector={(code) => { if (isSectorCode(code)) onDrawer({ type: 'open', kind: 'sector', code }) }}
              onStock={(code) => { if (code !== '') onDrawer({ type: 'open', kind: 'stock', code }) }}
            />
          </div>
        </div>
        <div className="chives-wb-col is-mine" style={{ order: single ? SINGLE_SECTION_ORDER.focus : 2 }}>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.focus : 0 }}>
            <FocusBlock
              t={t}
              data={data}
              state={state}
              pulsing={pulsing}
              now={now}
              failed={failures.watch}
              onDrawer={onDrawer}
              onSignal={onSignal}
              onAddWatch={onAddWatch}
              index={1}
            />
          </div>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.signals : 1 }}>
            <SignalBlock t={t} signals={partition.rail} failed={failures.hub} onSignal={onSignal} />
          </div>
          <div style={{ order: single ? SINGLE_SECTION_ORDER.done : 2 }}>
            <DoneBlock
              t={t}
              data={{ ...data, doneSignals: done }}
              open={doneOpen}
              onOpen={onDoneOpen}
              failed={failures.hub}
              onSignal={onSignal}
              count={signalFilter === 'all' ? data.doneCount : done.length}
              merged={signalFilter === 'all' ? data.mergedToday : done.reduce((sum, signal) => sum + Math.max(0, signal.mergedCount - 1), 0)}
            />
          </div>
        </div>
      </main>
      {toast ? (
        <div className="chives-sig-toast" role="status">
          <span>{toast.text}</span>
          {toast.undo ? <button type="button" onClick={onUndo}>{t('wbUndo')}</button> : null}
        </div>
      ) : null}
      <AskBar t={t} value={askText} onChange={onAskText} onAsk={onAsk} asked={asked} />
      <Drawer t={t} drawer={drawer} onClose={() => onDrawer({ type: 'close' })}>
        <DrawerBody
          t={t}
          drawer={drawer}
          data={data}
          now={now}
          signalLoading={signalLoading}
          signalError={signalError}
          analysisLoading={analysisLoading}
          analysisError={analysisError}
          sectorDetailError={sectorDetailError}
          sectorMembersError={sectorMembersError}
          historyError={historyError}
          onHistory={onHistory}
          onDrawer={onDrawer}
          onToggleAnalysis={toggleAnalysis}
        />
      </Drawer>
    </div>
  )
}

const NO_FAILURES: WorkbenchFailures = {
  overview: false,
  marketHealth: false,
  watch: false,
  sectors: false,
  summary: false,
  movers: false,
  hub: false,
  flows: false,
}

function viewFailures(failures: Failures): WorkbenchFailures {
  return {
    overview: failures.overview || failures.marketHealth,
    marketHealth: failures.marketHealth,
    watch: failures.watchHealth || failures.watchState || failures.watchAlerts || failures.watchRules || failures.analyses,
    sectors: failures.sectors,
    summary: failures.summary,
    movers: failures.movers,
    hub: failures.hubSignals || failures.hubDone,
    flows: failures.flows,
  }
}

function emptyData(): WorkbenchData {
  return {
    overview: null,
    health: null,
    watchHealth: null,
    quotes: [],
    rulesByCode: new Map(),
    ruleIndex: new Map(),
    alertNames: {},
    alertTsById: new Map(),
    ruleById: new Map(),
    timeline: [],
    analyses: [],
    stockRules: [],
    marketRules: [],
    sectors: [],
    sectorsAsOf: null,
    sectorsNote: null,
    summary: null,
    movers: {},
    sectorDetail: null,
    sectorMembers: [],
    analysis: null,
    history: [],
    signals: [],
    doneSignals: [],
    doneCount: 0,
    mergedToday: 0,
    signalDetail: null,
    flows: {},
    northbound: null,
  }
}

export interface WorkbenchProps {
  t: (key: WatchPanelKey, params?: Record<string, unknown>) => string
}

/** Stateful page: layered polling, drawer fetching, visibility pause and the ask bridge. */
export function Workbench({ t }: WorkbenchProps): ReactElement {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [health, setHealth] = useState<MarketHealth | null>(null)
  const [watchHealth, setWatchHealth] = useState<HealthPayload | null>(null)
  const [state, setState] = useState<StatePayload | null>(null)
  const [rules, setRules] = useState<RulesPayload | null>(null)
  const [alerts, setAlerts] = useState<AlertPayload[]>([])
  const [analyses, setAnalyses] = useState<AnalysisRecord[]>([])
  const [marketAlerts, setMarketAlerts] = useState<MarketAlert[]>([])
  const [marketRules, setMarketRules] = useState<MarketRule[]>([])
  const [sectors, setSectors] = useState<{ rows: SectorRow[]; asOf: string | null; stateNote: string | null }>({ rows: [], asOf: null, stateNote: null })
  const [summary, setSummary] = useState<SummaryPayload | null>(null)
  const [sparks, setSparks] = useState<Record<string, StockSparkSeries>>({})
  const [cardChips, setCardChips] = useState<Record<string, CardChip>>({})
  const sparkCodesRef = useRef<string[]>([])
  const [movers, setMovers] = useState<Partial<Record<MoversKind, MoversPayload>>>({})
  const [failures, setFailures] = useState<Failures>(NO_CHANNEL_FAILURES)
  const [sectorView, setSectorView] = useState<SectorView>('heat')
  const [moversFilters, setMoversFilters] = useState<MoversFilters>(DEFAULT_MOVERS_FILTERS)
  const [activeOpen, setActiveOpen] = useState(false)
  const [areaBasis, setAreaBasis] = useState<AreaBasis>('sqrt')
  const [signals, setSignals] = useState<Signal[]>([])
  const [doneSignals, setDoneSignals] = useState<Signal[]>([])
  const [doneCount, setDoneCount] = useState(0)
  const [mergedToday, setMergedToday] = useState(0)
  const [signalFilter, setSignalFilter] = useState<SignalFilter>('all')
  const [doneOpen, setDoneOpen] = useState(false)
  const [signalDetail, setSignalDetail] = useState<SignalDetail | null>(null)
  const [signalLoading, setSignalLoading] = useState(false)
  const [signalError, setSignalError] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [flows, setFlows] = useState<Partial<Record<FlowKind, FlowsPayload>>>({})
  const [northbound, setNorthbound] = useState<NorthboundPayload | null>(null)
  const [flowsMore, setFlowsMore] = useState(false)
  const [drawer, setDrawer] = useState<DrawerState>(CLOSED_DRAWER)
  const [sectorDetail, setSectorDetail] = useState<SectorDetail | null>(null)
  const [sectorMembers, setSectorMembers] = useState<SectorMember[]>([])
  const [sectorDetailError, setSectorDetailError] = useState(false)
  const [sectorMembersError, setSectorMembersError] = useState(false)
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState(false)
  const [history, setHistory] = useState<RuleHistoryRow[]>([])
  const [historyError, setHistoryError] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [pulsing, setPulsing] = useState<Set<string>>(new Set())
  const [moverPulse, setMoverPulse] = useState<Set<string>>(new Set())
  const [now, setNow] = useState(() => Date.now())
  const [width, setWidth] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth))
  const [collapsed, setCollapsed] = useState(false)
  const [askText, setAskText] = useState('')
  const [asked, setAsked] = useState(false)

  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLElement | null>(null)
  const visibleRef = useRef(true)
  const moversVisibleRef = useRef(true)
  const flowsVisibleRef = useRef(true)
  const aliveRef = useRef(true)
  const pollerRef = useRef<Poller | null>(null)
  const filtersRef = useRef(moversFilters)
  const activeRef = useRef(activeOpen)
  const afterIdRef = useRef(0)
  const lastAlertRef = useRef<AlertPayload | null>(null)
  const alertsLoadedRef = useRef(false)
  const marketSinceRef = useRef(0)
  const prevPrices = useRef(new Map<string, number | null>())
  const prevMoverPrices = useRef(new Map<string, number | null>())
  const sectorRequest = useRef(0)
  const analysisRequest = useRef(0)
  const analysisCache = useRef(new Map<number, AnalysisDetail>())
  const toastTimer = useRef<number | null>(null)
  const signalCache = useRef(new Map<number, SignalDetail>())
  const signalRequest = useRef(0)
  const signalRef = useRef<{ active: Signal[]; done: Signal[] }>({ active: [], done: [] })
  const flowsMoreRef = useRef(false)
  filtersRef.current = moversFilters
  activeRef.current = activeOpen
  flowsMoreRef.current = flowsMore
  signalRef.current = { active: signals, done: doneSignals }

  useEffect(() => {
    aliveRef.current = true
    const inflight = new Set<AbortController>()
    let disposed = false

    const mark = (key: ChannelName, failed: boolean): void => {
      if (disposed) return
      setFailures((previous) => (previous[key] === failed ? previous : { ...previous, [key]: failed }))
    }
    const call = async <T,>(path: string, apply: (payload: T) => void, market = false): Promise<T> => {
      const controller = new AbortController()
      inflight.add(controller)
      try {
        const payload = market
          ? await getMarketJson<T & { ok?: boolean }>(path, controller.signal)
          : await getJson<T>(path, controller.signal)
        if (disposed) return payload as T
        apply(payload as T)
        return payload as T
      } finally {
        inflight.delete(controller)
      }
    }
    const channel = (name: ChannelName, intervalMs: number, load: () => Promise<unknown>) => ({
      name,
      intervalMs,
      load: async (): Promise<void> => {
        try {
          await load()
          mark(name, false)
        } catch (error) {
          mark(name, true)
          throw error
        }
      },
    })

    const loadAlerts = async (): Promise<void> => {
      {
        let pages = 0
        for (;;) {
          const known = lastAlertRef.current
          const from = known ? Math.max(0, afterIdRef.current - 1) : 0
          const payload = await call<AlertsPayload>(`${ALERTS_PATH}?after_id=${from}&limit=${ALERT_PAGE_LIMIT}`, () => {})
          if (disposed) return
          const rows = Array.isArray(payload.alerts) ? payload.alerts : []
          if (known && pages === 0 && !continuesFrom(known, rows)) {
            afterIdRef.current = 0
            lastAlertRef.current = null
            alertsLoadedRef.current = false
            setAlerts([])
            continue
          }
          if (rows.length > 0) {
            afterIdRef.current = Math.max(afterIdRef.current, nextAfterId(rows))
            for (const row of rows) if (!lastAlertRef.current || row.id > lastAlertRef.current.id) lastAlertRef.current = row
            setAlerts((previous) => mergeAlerts(previous, rows))
          }
          pages += 1
          if (alertsLoadedRef.current || rows.length < ALERT_PAGE_LIMIT || pages >= ALERT_MAX_PAGES) break
        }
        alertsLoadedRef.current = true
      }
    }
    const loadMarketAlerts = async (): Promise<void> => {
      {
        const payload = await call<Record<string, unknown>>(`${MARKET_ALERTS_PATH}?since_id=${marketSinceRef.current}&limit=50`, () => {}, true)
        if (disposed) return
        const parsed = normalizeMarketAlerts(payload)
        if (parsed.nextId !== null) marketSinceRef.current = Math.max(marketSinceRef.current, parsed.nextId)
        if (parsed.alerts.length > 0) {
          setMarketAlerts((previous) => {
            const map = new Map(previous.map((alert) => [alert.id, alert]))
            for (const alert of parsed.alerts) map.set(alert.id, alert)
            return [...map.values()].sort((left, right) => right.id - left.id).slice(0, 200)
          })
        }
      }
    }
    const loadFlows = async (): Promise<void> => {
      if (!flowsVisibleRef.current) return
      const kinds: FlowKind[] = flowsMoreRef.current ? [...FLOW_COLUMNS, 'stock_out'] : [...FLOW_COLUMNS]
      const results = await Promise.all(kinds.map((kind) => call<Record<string, unknown>>(flowsPath(kind), () => {}, true)))
      if (disposed) return
      const next: Partial<Record<FlowKind, FlowsPayload>> = {}
      kinds.forEach((kind, index) => { next[kind] = normalizeFlows(results[index], kind) })
      setFlows(next)
    }

    const loadMovers = async (): Promise<void> => {
      if (!moversVisibleRef.current) return
      const kinds: MoversKind[] = activeRef.current ? ['gainers', 'losers', 'active'] : ['gainers', 'losers']
      const results = await Promise.all(kinds.map((kind) => call<Record<string, unknown>>(moversPath(kind, filtersRef.current), () => {}, true)))
      if (disposed) return
      const next: Partial<Record<MoversKind, MoversPayload>> = {}
      kinds.forEach((kind, index) => { next[kind] = normalizeMovers(results[index]) })
      setMovers(next)
    }

    const poller = new Poller([
      channel('watchHealth', 5000, () => call<HealthPayload>(HEALTH_PATH, setWatchHealth)),
      channel('watchState', 5000, () => call<StatePayload>(STATE_PATH, setState)),
      channel('watchAlerts', 10000, loadAlerts),
      channel('watchRules', 60000, () => call<RulesPayload>(RULES_PATH, setRules)),
      channel('analyses', 10000, () => call<AnalysesPayload>(ANALYSES_PATH, (payload) => {
        const rows = Array.isArray(payload.records) ? payload.records : []
        setAnalyses((previous) => mergeAnalyses(previous, rows))
      })),
      channel('marketHealth', 5000, () => call<Record<string, unknown>>(MARKET_HEALTH_PATH, (payload) => setHealth(normalizeMarketHealth(payload)), true)),
      channel('overview', 5000, () => call<Record<string, unknown>>(MARKET_OVERVIEW_PATH, (payload) => setOverview(normalizeOverview(payload)), true)),
      channel('sectors', 15000, () => call<Record<string, unknown>>(`${MARKET_SECTORS_PATH}?level=sw1`, (payload) => {
        const parsed = normalizeSectors(payload)
        setSectors({ rows: parsed.rows, asOf: parsed.asOf, stateNote: parsed.stateNote })
      }, true)),
      // Sparklines are decoration: failures never mark the page degraded.
      {
        name: 'sparks' as ChannelName,
        intervalMs: 30000,
        load: async (): Promise<void> => {
          const path = sparkPath(sparkCodesRef.current)
          if (path === null) return
          try {
            await call<Record<string, unknown>>(path, (payload) => setSparks(normalizeStockSparks(payload)))
          } catch {
            // keep the previous lines
          }
        },
      },
      // Card chips are decoration on the focus rows: failures never mark the page degraded.
      // Review layer offline (2026-11-16): the cards route is not registered, so the channel is only added when enabled.
      ...(REVIEW_LAYER_ENABLED ? [{
        name: 'cardChips' as ChannelName,
        intervalMs: 5000,
        load: async (): Promise<void> => {
          try {
            await call<Record<string, unknown>>(`${HUB_CARDS_PATH}?status=all`, (payload) => setCardChips(normalizeCardChips(payload)))
          } catch {
            // keep the previous chips
          }
        },
      }] : []),
      channel('marketAlerts', 10000, loadMarketAlerts),
      channel('marketRules', 60000, () => call<Record<string, unknown>>(MARKET_RULES_PATH, (payload) => {
        const rows = Array.isArray((payload as { rules?: unknown }).rules) ? (payload as { rules: unknown[] }).rules : []
        setMarketRules(normalizeMarketRules(rows))
      }, true)),
      channel('summary', 60000, () => call<Record<string, unknown>>(MARKET_SUMMARY_PATH, (payload) => setSummary(normalizeSummary(payload)), true)),
      channel('movers', 30000, loadMovers),
      channel('flows', 30000, loadFlows),
      channel('northbound', 60000, () => call<Record<string, unknown>>(MARKET_FLOWS_NORTHBOUND_PATH, (payload) => setNorthbound(normalizeNorthbound(payload)), true)),
      channel('hubSignals', 10000, () => call<Record<string, unknown>>(`${HUB_SIGNALS_PATH}?status=active&limit=50`, (payload) => {
        setSignals(normalizeSignals(payload).signals)
      }, true)),
      channel('hubDone', 30000, () => call<Record<string, unknown>>(`${HUB_SIGNALS_PATH}?status=done&limit=20`, (payload) => {
        const parsed = normalizeSignals(payload)
        const mergedInList = parsed.signals.reduce((sum, signal) => sum + Math.max(0, signal.mergedCount - 1), 0)
        setDoneSignals(parsed.signals)
        setDoneCount(Math.max(parsed.counts.done, parsed.signals.length))
        setMergedToday(Math.max(parsed.mergedToday, mergedInList))
      }, true)),
    ], {
      setTimeout: (handler, ms) => window.setTimeout(handler, ms),
      clearTimeout: (id) => window.clearTimeout(id),
      isVisible: () => visibleRef.current,
    })
    pollerRef.current = poller

    let observer: IntersectionObserver | null = null
    let moversObserver: IntersectionObserver | null = null
    let flowsObserver: IntersectionObserver | null = null
    if (typeof IntersectionObserver !== 'undefined' && wrapRef.current) {
      observer = new IntersectionObserver((entries) => {
        visibleRef.current = entries[0]?.isIntersecting ?? true
        poller.visibleChanged(!document.hidden && visibleRef.current)
      }, { threshold: 0.01 })
      observer.observe(wrapRef.current)
    }
    const moversNode = wrapRef.current?.querySelector('[data-wb="movers"]')
    if (typeof IntersectionObserver !== 'undefined' && moversNode) {
      moversObserver = new IntersectionObserver((entries) => {
        moversVisibleRef.current = entries[0]?.isIntersecting ?? true
      }, { threshold: 0.01 })
      moversObserver.observe(moversNode)
    }
    const flowsNode = wrapRef.current?.querySelector('[data-wb="flows"]')
    if (typeof IntersectionObserver !== 'undefined' && flowsNode) {
      flowsObserver = new IntersectionObserver((entries) => {
        flowsVisibleRef.current = entries[0]?.isIntersecting ?? true
      }, { threshold: 0.01 })
      flowsObserver.observe(flowsNode)
    }
    const onVisibility = (): void => {
      poller.visibleChanged(!document.hidden && visibleRef.current)
    }
    const onResize = (): void => setWidth(window.innerWidth)
    const onScroll = (): void => setCollapsed(wrapRef.current ? (wrapRef.current.scrollTop > 48) : false)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('resize', onResize)
    wrapRef.current?.addEventListener('scroll', onScroll, { passive: true })
    const clock = window.setInterval(() => setNow(Date.now()), 30_000)
    poller.start()
    return () => {
      disposed = true
      aliveRef.current = false
      poller.stop()
      observer?.disconnect()
      moversObserver?.disconnect()
      flowsObserver?.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', onResize)
      wrapRef.current?.removeEventListener('scroll', onScroll)
      window.clearInterval(clock)
      for (const controller of inflight) controller.abort()
      inflight.clear()
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    }
  }, [])

  useEffect(() => {
    const quotes = quoteRows(state)
    const next = new Map<string, number | null>()
    const changed = new Set<string>()
    for (const row of quotes) {
      const before = prevPrices.current.get(row.code)
      if (before !== undefined && before !== null && row.price !== null && before !== row.price) changed.add(row.code)
      next.set(row.code, row.price)
    }
    prevPrices.current = next
    if (changed.size === 0) return
    setPulsing(changed)
    const timer = window.setTimeout(() => setPulsing(new Set()), 650)
    return () => window.clearTimeout(timer)
  }, [state])

  useEffect(() => {
    const next = new Map<string, number | null>()
    const changed = new Set<string>()
    for (const payload of Object.values(movers)) {
      for (const row of payload?.rows ?? []) {
        const before = prevMoverPrices.current.get(row.code)
        if (before !== undefined && before !== null && row.price !== null && before !== row.price) changed.add(row.code)
        next.set(row.code, row.price)
      }
    }
    prevMoverPrices.current = next
    if (changed.size === 0) return
    setMoverPulse(changed)
    const timer = window.setTimeout(() => setMoverPulse(new Set()), 650)
    return () => window.clearTimeout(timer)
  }, [movers])

  useEffect(() => {
    if (drawer.kind !== null) return
    const target = triggerRef.current
    triggerRef.current = null
    target?.focus?.()
  }, [drawer.kind])

  useEffect(() => {
    if (drawer.kind === null) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setDrawer(CLOSED_DRAWER)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawer.kind])

  useEffect(() => {
    if (drawer.kind !== 'sector' || !isSectorCode(drawer.code)) return
    const request = ++sectorRequest.current
    setSectorDetail(null)
    setSectorMembers([])
    setSectorDetailError(false)
    setSectorMembersError(false)
    void (async () => {
      try {
        const payload = await getMarketJson<Record<string, unknown>>(sectorDetailPath(drawer.code), new AbortController().signal)
        if (!aliveRef.current || request !== sectorRequest.current) return
        setSectorDetail(normalizeSectorDetail(payload))
      } catch {
        if (aliveRef.current && request === sectorRequest.current) setSectorDetailError(true)
      }
      try {
        const payload = await getMarketJson<Record<string, unknown>>(sectorMembersPath(drawer.code), new AbortController().signal)
        if (!aliveRef.current || request !== sectorRequest.current) return
        setSectorMembers(normalizeMembers((payload as { rows?: unknown }).rows))
      } catch {
        if (aliveRef.current && request === sectorRequest.current) setSectorMembersError(true)
      }
    })()
  }, [drawer.kind, drawer.code])

  useEffect(() => {
    if (drawer.kind !== 'analysis' || drawer.id === null) return
    const id = drawer.id
    const cached = analysisCache.current.get(id)
    if (cached) {
      setAnalysis(cached)
      setAnalysisError(false)
      setAnalysisLoading(false)
      return
    }
    const request = ++analysisRequest.current
    setAnalysis(null)
    setAnalysisError(false)
    setAnalysisLoading(true)
    getJson<AnalysisDetail>(analysisPath(id), new AbortController().signal)
      .then((payload) => {
        if (!aliveRef.current || request !== analysisRequest.current) return
        analysisCache.current.set(id, payload)
        setAnalysis(payload)
      })
      .catch(() => { if (aliveRef.current && request === analysisRequest.current) setAnalysisError(true) })
      .finally(() => { if (aliveRef.current && request === analysisRequest.current) setAnalysisLoading(false) })
  }, [drawer.kind, drawer.id])

  useEffect(() => {
    if (drawer.kind !== 'signal' || drawer.id === null) return
    const id = drawer.id
    const cached = signalCache.current.get(id)
    if (cached) {
      setSignalDetail(cached)
      setSignalError(false)
      setSignalLoading(false)
      return
    }
    const request = ++signalRequest.current
    setSignalDetail(null)
    setSignalError(false)
    setSignalLoading(true)
    getJson<Record<string, unknown>>(signalDetailPath(id), new AbortController().signal)
      .then((payload) => {
        if (!aliveRef.current || request !== signalRequest.current) return
        const fallback = signalRef.current.active.find((signal) => signal.id === id)
          ?? signalRef.current.done.find((signal) => signal.id === id)
          ?? null
        const detail = normalizeSignalDetail(payload, fallback)
        signalCache.current.set(id, detail)
        setSignalDetail(detail)
      })
      .catch(() => { if (aliveRef.current && request === signalRequest.current) setSignalError(true) })
      .finally(() => { if (aliveRef.current && request === signalRequest.current) setSignalLoading(false) })
  }, [drawer.kind, drawer.id])

  const loadHistory = (): void => {
    getJson<{ history?: RuleHistoryRow[] }>(`${RULES_HISTORY_PATH}?limit=50`, new AbortController().signal)
      .then((payload) => { setHistory(Array.isArray(payload.history) ? payload.history : []); setHistoryError(false); setHistoryLoaded(true) })
      .catch(() => setHistoryError(true))
  }

  useEffect(() => {
    if (drawer.kind === 'rules' && !historyLoaded) loadHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawer.kind])

  const timeline = useMemo(() => buildTimeline(alerts, marketAlerts, analyses), [alerts, marketAlerts, analyses])
  const quotes = useMemo(() => quoteRows(state), [state])
  sparkCodesRef.current = quotes.map((quote) => quote.code)
  const sparkCodeKey = sparkCodesRef.current.join(',')
  useEffect(() => {
    if (sparkCodeKey === '') return
    void pollerRef.current?.pollNow('sparks')
  }, [sparkCodeKey])
  const stockRules = useMemo(() => ruleRows(state, rules), [state, rules])
  const ruleIndex = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of stockRules) if (!map.has(row.ruleId)) map.set(row.ruleId, row.description)
    return map
  }, [stockRules])
  const rulesByCode = useMemo(() => {
    const map = new Map<string, FocusRule[]>()
    for (const row of stockRules) {
      const list = map.get(row.code) ?? []
      list.push({ ruleId: row.ruleId, description: row.description, armed: row.armed, fired: row.firedCount > 0 })
      map.set(row.code, list)
    }
    return map
  }, [stockRules])
  const alertNames = useMemo(() => alertNameById(alerts), [alerts])
  const alertTs = useMemo(() => new Map(analyses.map((record) => [record.alert_id, record.started_at ?? null])), [analyses])
  const ruleById = useMemo(() => {
    const map = new Map<string, RuleConfig>()
    for (const rule of rules?.rules ?? []) if (rule && typeof rule.id === 'string') map.set(rule.id, rule)
    return map
  }, [rules])

  const dispatchDrawer = (action: DrawerAction): void => {
    if (action.type === 'open' && drawer.kind === null && typeof document !== 'undefined') {
      triggerRef.current = document.activeElement as HTMLElement | null
    }
    setDrawer((previous) => drawerReducer(previous, action))
  }

  const openAnalysis = (id: number): void => { dispatchDrawer({ type: 'open', kind: 'analysis', id }) }

  const ask = (text: string, context: string): void => {
    const payload = composeAsk(text, context)
    if (payload === null) return
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent('chives:ask', { detail: { text: payload } }))
    setAsked(true)
    setAskText('')
    window.setTimeout(() => setAsked(false), 4000)
  }

  useEffect(() => {
    if (!toast) return
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => { toastTimer.current = null; setToast(null) }, 4200)
    return () => { if (toastTimer.current !== null) window.clearTimeout(toastTimer.current) }
  }, [toast])

  const postSignalAction = async (body: unknown): Promise<ActionResult> => {
    try {
      const payload = await postJson<{ ok?: boolean; error?: { code?: string } }>(
        HUB_SIGNAL_ACTION_PATH,
        body,
        AbortSignal.timeout(8000),
      )
      return { ok: payload.ok !== false, code: payload.error?.code ?? null }
    } catch {
      return { ok: false, code: 'hub_unreachable' }
    }
  }

  const applySignalAction = async (action: SignalAction): Promise<void> => {
    const combined = [...signalRef.current.active, ...signalRef.current.done]
    const outcome = await performSignalAction(combined, action, { post: postSignalAction, now: () => Date.now() })
    if (!outcome.ok) {
      setToast({ text: t('wbActionFailed'), undo: null, key: Date.now() })
      return
    }
    const nextActive = outcome.signals.filter((signal) => signal.status === 'new' || signal.status === 'seen')
    const nextDone = outcome.signals.filter((signal) => signal.status === 'done' || signal.status === 'ignored')
    signalRef.current = { active: nextActive, done: nextDone }
    setSignals(nextActive)
    setDoneSignals(nextDone)
    const notice = toastFor(action, Date.now())
    if (notice) setToast(notice)
  }

  const openSignal = (signal: Signal): void => {
    dispatchDrawer({ type: 'open', kind: 'signal', id: signal.id })
    if (signal.status === 'new') void applySignalAction({ type: 'ack', id: signal.id })
  }

  const confirmPlan = async (signal: Signal, planId: number | null): Promise<void> => {
    const body = planId === null ? null : planActionBody(planId, 'confirm')
    if (body === null) {
      setToast({ text: t('wbActionFailed'), undo: null, key: Date.now() })
      return
    }
    try {
      const payload = await postJson<{ ok?: boolean }>(HUB_PLAN_ACTION_PATH, body, AbortSignal.timeout(8000))
      if (payload.ok === false) throw new Error('plan action failed')
      setToast({ text: t('wbPlanConfirmed'), undo: null, key: Date.now() })
    } catch {
      setToast({ text: t('wbActionFailed'), undo: null, key: Date.now() })
    }
  }

  const fillAsk = (text: string): void => {
    setAskText(text)
    setAsked(true)
    window.setTimeout(() => setAsked(false), 4000)
  }

  const onSignal = (event: SignalEvent): void => {
    if (event.kind === 'primary') {
      const intent = primaryIntent(event.signal)
      if (intent.kind === 'open') openSignal(event.signal)
      else if (intent.kind === 'signal') void applySignalAction(intent.action)
      else if (intent.kind === 'plan') void confirmPlan(event.signal, intent.planId)
      else {
        const prompt = fillPrompt(event.signal)
        if (prompt !== null) fillAsk(prompt)
      }
      return
    }
    if (event.kind === 'open') { openSignal(event.signal); return }
    if (event.kind === 'recheck') { fillAsk(recheckPrompt(event.signal)); return }
    if (event.kind === 'reopen') { void applySignalAction({ type: 'reopen', id: event.signal.id }); return }
    if (event.kind === 'ignore') { void applySignalAction({ type: 'ignore', id: event.signal.id }); return }
    if (event.kind === 'snooze') void applySignalAction({ type: 'snooze', id: event.signal.id, until: event.until })
  }

  const undo = (): void => {
    const action = toast?.undo ?? null
    setToast(null)
    if (action !== null) void applySignalAction(action)
  }

  const stateNow = tradingStateOf(overview, health)
  const session = classifySession(watchHealth?.session)
  const pulse = health === null && !failures.marketHealth ? 'idle' : marketPulse(health, failures.marketHealth)
  const primary = overview?.indexes[0] ?? null
  const context = askContext({
    stateLabel: t(TRADING_KEY[stateNow]),
    indexName: primary?.name ?? null,
    indexChangePct: primary?.changePct ?? null,
    watchNames: quotes.map((quote) => quote.name || quote.code),
  })

  const data: WorkbenchData = {
    overview,
    health,
    watchHealth,
    quotes,
    rulesByCode,
    sparks,
    cardChips,
    ruleIndex,
    alertNames,
    alertTsById: alertTs,
    ruleById,
    timeline,
    analyses,
    stockRules,
    marketRules,
    sectors: sectors.rows,
    sectorsAsOf: sectors.asOf,
    sectorsNote: sectors.stateNote,
    summary,
    movers,
    sectorDetail,
    sectorMembers,
    analysis,
    history,
    signals,
    doneSignals,
    doneCount,
    mergedToday,
    signalDetail,
    flows,
    northbound,
  }

  return (
    <div className="chives-wb-scroll" ref={wrapRef} data-session={session}>
      <WorkbenchView
          t={t}
          now={now}
          width={width}
          collapsed={collapsed}
          data={data}
          failures={viewFailures(failures)}
          pulse={pulse}
          summaryFailed={failures.summary}
          sectorView={sectorView}
          onSectorView={setSectorView}
          areaBasis={areaBasis}
          onAreaBasis={setAreaBasis}
          moversFilters={moversFilters}
          onMoversFilters={(next) => { filtersRef.current = next; setMoversFilters(next); void pollerRef.current?.pollNow('movers') }}
          activeOpen={activeOpen}
          onActiveOpen={(open) => { activeRef.current = open; setActiveOpen(open); void pollerRef.current?.pollNow('movers') }}
          signalFilter={signalFilter}
          onSignalFilter={setSignalFilter}
          doneOpen={doneOpen}
          onDoneOpen={setDoneOpen}
          flowsMore={flowsMore}
          onFlowsMore={(more) => { flowsMoreRef.current = more; setFlowsMore(more); void pollerRef.current?.pollNow('flows') }}
          onSignal={onSignal}
          toast={toast}
          onUndo={undo}
          pulsing={pulsing}
          moverPulse={moverPulse}
          drawer={drawer}
          onDrawer={dispatchDrawer}
          signalLoading={signalLoading}
          signalError={signalError}
          analysisLoading={analysisLoading}
          analysisError={analysisError}
          sectorDetailError={sectorDetailError}
          sectorMembersError={sectorMembersError}
          historyError={historyError}
          onHistory={loadHistory}
          askText={askText}
          onAskText={setAskText}
          onAsk={(text) => ask(text, context)}
          onSearch={(text) => {
            const question = searchAsk(text)
            if (question !== null) ask(question, context)
          }}
          onAddWatch={(row) => ask(row ? t('wbAddWatchPrompt', { name: row.name, code: row.code }) : t('wbAddWatchGeneric'), context)}
          asked={asked}
        />
    </div>
  )
}
