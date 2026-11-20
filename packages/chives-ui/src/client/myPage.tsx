/**
 * "我的" page (T101): account overview, holdings table, risk, equity curve,
 * allocation and watchlist. `MyPageView` is a pure props component used by the
 * DOM tests; `MyPage` owns polling, visibility pause and the ask bridge.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { FormEvent, PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import { MY_PAGE_PANEL, PANEL_EVENT, WORKBENCH_PANEL, ASK_EVENT } from './panels.ts'
import type { ChivesKey } from './locales.ts'
import { Poller } from './polling.ts'
import {
  DASH,
  classifySession,
  formatStamp,
  quoteRows,
  type QuoteRow,
  type SessionLevel,
  type StatePayload,
} from './myPageFormat.ts'
import {
  DIAGNOSE_PROMPT,
  HISTORY_RANGE_DAYS,
  IMPORT_PROMPT,
  allocationSegments,
  askStockPrompt,
  buildWatchRows,
  normalizeHistory,
  normalizePortfolioOverview,
  normalizeSparks,
  sparkGeometry,
  sparkPath,
} from './myPageModel.ts'
import type {
  HistoryGeometry,
  HistoryPayload,
  HistoryPoint,
  HistoryRange,
  PortfolioOverview,
  PortfolioPosition,
  PositionSort,
  PositionSortKey,
  StockSpark,
} from './myPageModel.ts'
import {
  DEFAULT_SORT,
  browserStorage,
  historyDays,
  historyGeometry,
  historyPointAt,
  historyRangeSlice,
  historyReadiness,
  moneyText,
  moveText,
  pctText,
  positionFlags,
  priceText,
  quantityText,
  ratioText,
  readHidden,
  riskMetrics,
  riskState,
  sideOf,
  sortPositions,
  toggleSort,
  writeHidden,
} from './myPageModel.ts'

export { MY_PAGE_PANEL, WORKBENCH_PANEL, PANEL_EVENT, ASK_EVENT }

type Translate = (key: ChivesKey, params?: Record<string, unknown>) => string

const HUB_PORTFOLIO_OVERVIEW_PATH = '/api/hub/portfolio-overview'
const HUB_PORTFOLIO_HISTORY_PATH = '/api/hub/portfolio-history'
const STATE_PATH = '/api/watch/state'

/** Same-origin GET; hub business errors (`ok:false`) surface as throws. */
async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: 'GET', signal, headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error('request failed')
  return await response.json() as T
}

async function getHubJson<T extends { ok?: boolean }>(path: string, signal: AbortSignal): Promise<T> {
  const payload = await getJson<T>(path, signal)
  if (payload && payload.ok === false) throw new Error('hub request was not ok')
  return payload
}

function portfolioHistoryPath(days: number): string {
  return `${HUB_PORTFOLIO_HISTORY_PATH}?days=${encodeURIComponent(String(days))}`
}

/** Per-character tick copied from the watch page's Tick (same CSS contract). */
function Tick({ text }: { text: string }): ReactElement {
  return (
    <span className="chives-tick">
      {[...text].map((char, index) => <span className="chives-digit" key={`${index}:${char}`}>{char}</span>)}
    </span>
  )
}

const SESSION_KEY: Record<ReturnType<typeof classifySession>, ChivesKey> = {
  open: 'sessionOpen',
  pre_open: 'sessionPreOpen',
  break: 'sessionBreak',
  after_hours: 'sessionAfterHours',
  non_trading_day: 'sessionNonTradingDay',
  unknown: 'sessionUnknown',
}

const FLAG_KEY = {
  t1: 'myT1',
  limit_up: 'myLimitUp',
  limit_down: 'myLimitDown',
  missing: 'myMissing',
} as const

const RISK_LABEL: Record<string, ChivesKey> = {
  vol: 'myRiskVol',
  drawdown: 'myRiskDrawdown',
  beta: 'myRiskBeta',
  top1: 'myRiskTop1',
  effectiveN: 'myRiskEffectiveN',
}

const RISK_NOTE: Record<string, ChivesKey> = {
  vol: 'myRiskVolNote',
  drawdown: 'myRiskDrawdownNote',
  beta: 'myRiskBetaNote',
  top1: 'myRiskTop1Note',
  effectiveN: 'myRiskEffectiveNNote',
}

const SORT_LABEL: Record<PositionSortKey, ChivesKey> = {
  name: 'myColName',
  qty: 'myColQty',
  cost: 'myColCost',
  price: 'myColPrice',
  dayPnl: 'myColDayPnl',
  pnl: 'myColPnl',
  weight: 'myColWeight',
}

const RANGE_KEY: Record<HistoryRange, ChivesKey> = {
  '30': 'myHistory30',
  '90': 'myHistory90',
  all: 'myHistoryAll',
}

function sideClass(value: number | null): string {
  const side = sideOf(value)
  return side === 'up' ? 'chives-up' : side === 'down' ? 'chives-down' : 'chives-flat'
}

function riskValue(key: string, value: number | null): string {
  if (value === null) return '—'
  if (key === 'beta') return value.toFixed(2)
  if (key === 'effectiveN') return value.toFixed(1)
  return `${value.toFixed(2)}%`
}

function EyeIcon({ closed }: { closed: boolean }): ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <path d="M2.5 12s3.6-6 9.5-6 9.5 6 9.5 6-3.6 6-9.5 6-9.5-6-9.5-6Z" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="12" r="2.6" stroke="currentColor" strokeWidth="1.6" />
      {closed ? <path d="M4 20 20 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /> : null}
    </svg>
  )
}

function OverviewCard({ t, overview, hidden }: {
  t: Translate
  overview: PortfolioOverview
  hidden: boolean
}): ReactElement {
  const { totals } = overview
  const blank = overview.empty
  const money = (value: number | null): string => (blank ? '—' : moneyText(value, hidden))
  const totalText = overview.empty
    ? '—'
    : totals.totalAssetsCny !== null
      ? moneyText(totals.totalAssetsCny, hidden)
      : !totals.cashKnown
        ? t('myCashUnset')
        : '—'
  const cashText = overview.empty
    ? '—'
    : totals.cashCny !== null
      ? moneyText(totals.cashCny, hidden)
      : t('myCashUnset')
  return (
    <section className="chives-my-overview" data-my="overview" aria-label={t('myTitle')}>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myTotalAssets')}</span>
        <strong className="chives-my-cell-value chives-my-big"><Tick text={totalText} /></strong>
      </div>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myMarketValue')}</span>
        <strong className="chives-my-cell-value"><Tick text={money(totals.marketValueCny)} /></strong>
      </div>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myDayPnl')}</span>
        <strong className={`chives-my-cell-value ${sideClass(totals.dayPnlCny)}`}>
          <Tick text={money(totals.dayPnlCny)} />
        </strong>
        {blank ? null : <span className={`chives-my-pill is-${sideOf(totals.dayPnlCny)}`}>{moveText(totals.dayPnlPct)}</span>}
      </div>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myTotalPnl')}</span>
        <strong className={`chives-my-cell-value ${sideClass(totals.pnlCny)}`}>
          <Tick text={money(totals.pnlCny)} />
        </strong>
        {blank ? null : <span className={`chives-my-pill is-${sideOf(totals.pnlCny)}`}>{pctText(totals.pnlPct)}</span>}
      </div>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myPositionRatio')}</span>
        <strong className="chives-my-cell-value">{blank ? '—' : ratioText(totals.positionRatioPct)}</strong>
        <span className="chives-my-track" aria-hidden="true">
          <span className="chives-my-track-fill" style={{ width: `${blank ? 0 : Math.min(100, Math.max(0, totals.positionRatioPct ?? 0))}%` }} />
        </span>
      </div>
      <div className="chives-my-cell">
        <span className="chives-my-cell-label">{t('myCash')}</span>
        <strong className="chives-my-cell-value"><Tick text={cashText} /></strong>
      </div>
    </section>
  )
}

function SortHeader({ t, sortKey, sort, onSort }: {
  t: Translate
  sortKey: PositionSortKey
  sort: PositionSort
  onSort: (key: PositionSortKey) => void
}): ReactElement {
  const active = sort.key === sortKey
  const aria = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <th aria-sort={aria}>
      <button
        type="button"
        className={`chives-my-sort${active ? ' is-active' : ''}`}
        onClick={() => onSort(sortKey)}
      >
        {t(SORT_LABEL[sortKey])}
        <span className="chives-my-sort-glyph" aria-hidden="true">{active ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  )
}

function HoldingsTable({ t, positions, hidden, sort, onSort, expanded, onExpand, onAskStock, highlight, sparks }: {
  t: Translate
  positions: readonly PortfolioPosition[]
  hidden: boolean
  sort: PositionSort
  onSort: (key: PositionSortKey) => void
  expanded: string | null
  onExpand: (code: string | null) => void
  onAskStock: (position: PortfolioPosition) => void
  highlight: string | null
  sparks?: Readonly<Record<string, StockSpark>>
}): ReactElement {
  const rows = useMemo(() => sortPositions(positions, sort), [positions, sort])
  return (
    <section className="chives-my-section chives-my-holdings" data-my="positions" aria-label={t('myHoldings')}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{t('myHoldings')}</span>
        <span className="chives-my-meta">{positions.length}</span>
      </div>
      <div className="chives-my-table-wrap">
        <table className="chives-my-table">
          <thead>
            <tr>
              <SortHeader t={t} sortKey="name" sort={sort} onSort={onSort} />
              <th className="chives-my-spark-col">{t('myColTrend')}</th>
              <SortHeader t={t} sortKey="qty" sort={sort} onSort={onSort} />
              <SortHeader t={t} sortKey="cost" sort={sort} onSort={onSort} />
              <SortHeader t={t} sortKey="price" sort={sort} onSort={onSort} />
              <SortHeader t={t} sortKey="dayPnl" sort={sort} onSort={onSort} />
              <SortHeader t={t} sortKey="pnl" sort={sort} onSort={onSort} />
              <SortHeader t={t} sortKey="weight" sort={sort} onSort={onSort} />
              <th>{t('myColFlags')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((position) => {
              const open = expanded === position.code
              const flags = positionFlags(position)
              return (
                <RowGroup
                  key={position.code}
                  t={t}
                  position={position}
                  hidden={hidden}
                  open={open}
                  flags={flags}
                  highlight={highlight === position.code}
                  spark={sparks?.[position.code] ?? null}
                  onExpand={() => onExpand(open ? null : position.code)}
                  onAskStock={() => onAskStock(position)}
                />
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function RowSpark({ spark, label }: { spark: StockSpark | null; label: string }): ReactElement {
  const geometry = spark ? sparkGeometry(spark) : null
  if (!geometry) return <span className="chives-my-spark-empty" aria-hidden="true">{DASH}</span>
  return (
    <svg className={`chives-my-spark is-${geometry.side}`} viewBox="0 0 72 24" width="72" height="24" role="img" aria-label={label} preserveAspectRatio="none">
      {geometry.baseY !== null ? <line className="chives-my-spark-base" x1="0" x2="72" y1={geometry.baseY} y2={geometry.baseY} /> : null}
      <path className="chives-my-spark-area" d={geometry.area} />
      <path className="chives-my-spark-line" d={geometry.line} />
    </svg>
  )
}

function RowGroup({ t, position, hidden, open, flags, highlight, spark, onExpand, onAskStock }: {
  t: Translate
  position: PortfolioPosition
  hidden: boolean
  open: boolean
  flags: readonly string[]
  highlight: boolean
  spark: StockSpark | null
  onExpand: () => void
  onAskStock: () => void
}): ReactElement {
  const weight = position.weightPct ?? 0
  return (
    <>
      <tr
        className={`chives-my-row${open ? ' is-expanded' : ''}${highlight ? ' is-highlight' : ''}${position.priceUnavailable ? ' is-missing' : ''}`}
        onClick={onExpand}
      >
        <td>
          <span className="chives-my-name">{position.name}</span>
          <span className="chives-my-code">{position.code}</span>
        </td>
        <td className="chives-my-spark-cell"><RowSpark spark={spark} label={t('myColTrend')} /></td>
        <td className="chives-my-num">{quantityText(position.qty, hidden)}</td>
        <td className="chives-my-num">{priceText(position.costPriceCny, hidden)}</td>
        <td className="chives-my-num">{position.priceUnavailable ? t('myMissing') : priceText(position.priceCny, hidden)}</td>
        <td className={`chives-my-num ${sideClass(position.dayPnlCny)}`}>{moneyText(position.dayPnlCny, hidden)}</td>
        <td className={`chives-my-num ${sideClass(position.pnlCny)}`}>
          <span>{moneyText(position.pnlCny, hidden)}</span>
          <span className="chives-my-pct">{pctText(position.pnlPct)}</span>
        </td>
        <td className="chives-my-num">
          <span>{ratioText(position.weightPct)}</span>
          <span className="chives-my-track is-thin" aria-hidden="true">
            <span className="chives-my-track-fill" style={{ width: `${Math.min(100, Math.max(0, weight))}%` }} />
          </span>
        </td>
        <td className="chives-my-flags">
          {flags.map((flag) => (
            <span className={`chives-my-flag is-${flag}`} key={flag}>{t(FLAG_KEY[flag as keyof typeof FLAG_KEY])}</span>
          ))}
        </td>
      </tr>
      {open ? (
        <tr className="chives-my-detail-row">
          <td colSpan={9}>
            <div className="chives-my-detail">
              <span><em>{t('myDetailCost')}</em> {priceText(position.costPriceCny, hidden)}</span>
              <span><em>{t('mySellable')}</em> {position.sellableToday ? quantityText(position.qty, hidden) : '0'}</span>
              <span><em>{t('myWeightOfAssets')}</em> {ratioText(position.weightPct)}</span>
              <button type="button" className="chives-my-ask-stock" onClick={(event) => { event.stopPropagation(); onAskStock() }}>
                {t('myAskStock')}
              </button>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  )
}

function RiskCard({ t, overview }: { t: Translate; overview: PortfolioOverview }): ReactElement {
  const state = riskState(overview)
  return (
    <section className="chives-my-section chives-my-risk" data-my="risk" aria-label={t('myRisk')}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{t('myRisk')}</span>
      </div>
      {state === 'ready' && overview.risk !== null ? (
        <dl className="chives-my-risk-list">
          {riskMetrics(overview.risk).map((metric) => (
            <div className="chives-my-risk-row" key={metric.key}>
              <dt>{t(RISK_LABEL[metric.key]!)}</dt>
              <dd>{riskValue(metric.key, metric.value)}</dd>
              <p>{t(RISK_NOTE[metric.key]!)}</p>
            </div>
          ))}
        </dl>
      ) : (
        <div className="chives-my-empty">
          <span>{state === 'pending' ? t('myRiskPending') : t('myRiskUnavailable')}</span>
          {overview.riskReason !== null ? (
            <span className="chives-my-risk-reason">{t('myRiskReason')} · {overview.riskReason}</span>
          ) : null}
        </div>
      )}
    </section>
  )
}

function HistoryChart({ t, points, hidden }: {
  t: Translate
  points: readonly HistoryPoint[]
  hidden: boolean
}): ReactElement {
  const gradientId = `chives-my-area-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const [hover, setHover] = useState<number | null>(null)
  const geometry = useMemo(() => historyGeometry(points), [points])
  const readiness = historyReadiness(points)
  if (geometry === null) {
    return (
      <div className="chives-my-empty chives-my-history-empty">
        {t('myHistoryEmpty', { count: readiness.count })}
      </div>
    )
  }
  const active = hover === null ? null : geometry.coords[historyPointAt(geometry, hover) ?? 0] ?? null
  const onMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (rect.width <= 0) return
    setHover((event.clientX - rect.left) / rect.width)
  }
  return (
    <div
      className={`chives-my-chart is-${geometry.side}`}
      onPointerMove={onMove}
      onPointerLeave={() => setHover(null)}
      role="img"
      aria-label={t('myHistory')}
    >
      <svg viewBox="0 0 600 180" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop className="chives-my-stop-top" offset="0%" />
            <stop className="chives-my-stop-bottom" offset="100%" />
          </linearGradient>
        </defs>
        <path className="chives-my-area" d={geometry.area} fill={`url(#${gradientId})`} />
        <path className="chives-my-line" d={geometry.path} pathLength={1} />
        {active ? <line className="chives-my-cross" x1={active.x} y1={0} x2={active.x} y2={180} /> : null}
        <circle className="chives-my-dot" cx={geometry.coords[geometry.coords.length - 1]!.x} cy={geometry.coords[geometry.coords.length - 1]!.y} r={3.4} />
      </svg>
      {active ? (
        <div className="chives-my-tip" style={{ left: `${(active.x / geometry.width) * 100}%` }}>
          <strong>{active.date}</strong>
          <span>{t('myHistoryTotal')} {moneyText(active.value, hidden)}</span>
          <span>{t('myHistoryDayPnl')} {moneyText(dayPnlAt(points, active.date), hidden)}</span>
        </div>
      ) : null}
    </div>
  )
}

function dayPnlAt(points: readonly HistoryPoint[], date: string): number | null {
  return points.find((point) => point.date === date)?.dayPnlCny ?? null
}

function HistoryBlock({ t, points, range, onRange, hidden }: {
  t: Translate
  points: readonly HistoryPoint[]
  range: HistoryRange
  onRange: (range: HistoryRange) => void
  hidden: boolean
}): ReactElement {
  const visible = useMemo(() => historyRangeSlice(points, range), [points, range])
  return (
    <section className="chives-my-section chives-my-history" data-my="history" aria-label={t('myHistory')}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{t('myHistory')}</span>
        <div className="chives-my-segmented" role="group" aria-label={t('myHistory')}>
          {(Object.keys(HISTORY_RANGE_DAYS) as HistoryRange[]).map((value) => (
            <button
              key={value}
              type="button"
              className={`chives-my-seg${range === value ? ' is-active' : ''}`}
              aria-pressed={range === value}
              onClick={() => onRange(value)}
            >
              {t(RANGE_KEY[value])}
            </button>
          ))}
        </div>
      </div>
      <HistoryChart t={t} points={visible} hidden={hidden} />
    </section>
  )
}

function Allocation({ t, positions, highlight, onHighlight }: {
  t: Translate
  positions: readonly PortfolioPosition[]
  highlight: string | null
  onHighlight: (code: string | null) => void
}): ReactElement {
  const segments = useMemo(() => allocationSegments(positions), [positions])
  return (
    <section className="chives-my-section chives-my-alloc" data-my="allocation" aria-label={t('myAllocation')}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{t('myAllocation')}</span>
      </div>
      {segments.length === 0 ? <div className="chives-my-empty">{t('myHoldings')} —</div> : (
        <>
          <div className="chives-my-alloc-bar">
            {segments.map((segment) => (
              <button
                key={segment.key}
                type="button"
                className={`chives-my-alloc-seg${segment.code !== null && highlight === segment.code ? ' is-active' : ''}`}
                style={{ width: `${segment.pct}%`, backgroundColor: segment.color }}
                aria-label={`${segment.code === null ? t('myOther') : segment.name} ${segment.pct}%`}
                onClick={() => onHighlight(segment.code !== null && highlight === segment.code ? null : segment.code)}
              />
            ))}
          </div>
          <ul className="chives-my-alloc-legend">
            {segments.map((segment) => (
              <li key={segment.key}>
                <span className="chives-my-alloc-dot" style={{ backgroundColor: segment.color }} aria-hidden="true" />
                <span>{segment.code === null ? t('myOther') : segment.name}</span>
                <span className="chives-my-alloc-pct">{segment.pct.toFixed(1)}%</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function Watchlist({ t, rows, onOpenWatch }: {
  t: Translate
  rows: ReturnType<typeof buildWatchRows>
  onOpenWatch: () => void
}): ReactElement {
  return (
    <section className="chives-my-section chives-my-watch" data-my="watch" aria-label={t('myWatchlist')}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{t('myWatchlist')}</span>
        <button type="button" className="chives-my-link" onClick={onOpenWatch}>{t('myGoWatch')}</button>
      </div>
      {rows.length === 0 ? <div className="chives-my-empty">{t('myWatchEmpty')}</div> : (
        <ul className="chives-my-watch-list">
          {rows.map((row) => (
            <li key={row.code}>
              <span className="chives-my-watch-name">{row.name}<span className="chives-my-code">{row.code}</span></span>
              {row.held ? <span className="chives-my-held">{t('myWatchHeld')}</span> : null}
              <span className="chives-my-watch-price">{priceText(row.price, false)}</span>
              <span className={`chives-my-pill is-${sideOf(row.changePct)}`}>{moveText(row.changePct)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function AskBar({ t, value, onChange, onAsk, asked }: {
  t: Translate
  value: string
  onChange: (value: string) => void
  onAsk: (value: string) => void
  asked: boolean
}): ReactElement {
  const submit = (event: FormEvent): void => {
    event.preventDefault()
    onAsk(value)
  }
  return (
    <form className="chives-my-ask" onSubmit={submit} aria-label={t('myAsk')}>
      <span className="chives-my-ask-label">{t('myAsk')}</span>
      <input
        className="chives-my-ask-input"
        type="text"
        value={value}
        placeholder={t('myAskPlaceholder')}
        aria-label={t('myAskPlaceholder')}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <button type="submit" className="chives-my-ask-send" aria-label={t('myAsk')}>↵</button>
      <span className="chives-my-ask-note">{asked ? '✓' : ''}</span>
    </form>
  )
}

export interface MyPageFailures {
  overview: boolean
  history: boolean
  watch: boolean
}

export interface MyPageViewProps {
  t: Translate
  width: number
  session: SessionLevel
  overview: PortfolioOverview | null
  history: HistoryPayload | null
  quotes: readonly QuoteRow[]
  failures: MyPageFailures
  range: HistoryRange
  onRange: (range: HistoryRange) => void
  sort: PositionSort
  onSort: (key: PositionSortKey) => void
  expanded: string | null
  onExpand: (code: string | null) => void
  highlight: string | null
  onHighlight: (code: string | null) => void
  hidden: boolean
  onHidden: (hidden: boolean) => void
  askText: string
  onAskText: (text: string) => void
  onAsk: (text: string) => void
  onAskStock: (position: PortfolioPosition) => void
  onImport: () => void
  onDiagnose: () => void
  onOpenWatch: () => void
  onRetry: () => void
  asked: boolean
  /** Intraday sparklines by code (hub /spark); missing codes render a dash. */
  sparks?: Readonly<Record<string, StockSpark>>
}

export function MyPageView(props: MyPageViewProps): ReactElement {
  const {
    t, width, session, overview, history, quotes, failures, range, onRange, sort, onSort, expanded, onExpand,
    highlight, onHighlight, hidden, onHidden, askText, onAskText, onAsk, onAskStock,
    onImport, onDiagnose, onOpenWatch, onRetry, asked, sparks,
  } = props
  const single = width < 1280
  const watchRows = useMemo(() => buildWatchRows(quotes, overview?.positions ?? []), [quotes, overview])
  const stale = overview !== null && (failures.overview || failures.history)
  return (
    <div className={`chives-my is-${session}`} data-layout={single ? 'single' : 'two'} data-hidden={hidden ? 'true' : 'false'}>
      <header className="chives-my-top">
        <div className="chives-my-title-block">
          <h1 className="chives-my-title">{t('myTitle')}</h1>
          <span className="chives-my-topmeta">
            <span>{t('myDataTime')} {formatStamp(overview?.asOf ?? null)}</span>
            <span>{t('myQuoteTime')} {formatStamp(overview?.quoteTime ?? null)}</span>
            <span className={`chives-my-trading is-${session}`}>{t(SESSION_KEY[session])}</span>
          </span>
        </div>
        <div className="chives-my-actions">
          <button
            type="button"
            className={`chives-my-eye${hidden ? ' is-hidden' : ''}`}
            aria-pressed={hidden}
            title={hidden ? t('myShowAmounts') : t('myHideAmounts')}
            aria-label={hidden ? t('myShowAmounts') : t('myHideAmounts')}
            onClick={() => onHidden(!hidden)}
          >
            <EyeIcon closed={hidden} />
          </button>
          <button type="button" className="chives-my-button is-primary" onClick={onImport}>{t('myImport')}</button>
          <button type="button" className="chives-my-button" onClick={onDiagnose}>{t('myDiagnose')}</button>
        </div>
      </header>

      {overview === null ? (
        failures.overview ? (
          <section className="chives-my-hubdown" data-my="hubdown">
            <h2>{t('myHubDown')}</h2>
            <button type="button" className="chives-my-button is-primary" onClick={onRetry}>{t('myRetry')}</button>
          </section>
        ) : (
          <div className="chives-my-empty chives-my-loading">{t('myLoading')}</div>
        )
      ) : (
        <>
          {stale ? <div className="chives-my-banner">{t('myStale')}</div> : null}
          <OverviewCard t={t} overview={overview} hidden={hidden} />
          {overview.empty ? (
            <section className="chives-my-guide" data-my="empty">
              <h2>{t('myEmptyGuide')}</h2>
              <p>{t('myEmptyGuideBody')}</p>
              <button type="button" className="chives-my-button is-primary" onClick={onImport}>{t('myEmptyGuideAction')}</button>
            </section>
          ) : (
            <main className="chives-my-body">
              <div className="chives-my-col is-left">
                <HoldingsTable
                  t={t}
                  positions={overview.positions}
                  hidden={hidden}
                  sort={sort}
                  onSort={onSort}
                  expanded={expanded}
                  onExpand={onExpand}
                  onAskStock={onAskStock}
                  highlight={highlight}
                  sparks={sparks}
                />
                <RiskCard t={t} overview={overview} />
              </div>
              <div className="chives-my-col is-right">
                <HistoryBlock t={t} points={history?.points ?? []} range={range} onRange={onRange} hidden={hidden} />
                <Allocation t={t} positions={overview.positions} highlight={highlight} onHighlight={onHighlight} />
                <Watchlist t={t} rows={watchRows} onOpenWatch={onOpenWatch} />
              </div>
            </main>
          )}
          {overview.empty ? <Watchlist t={t} rows={watchRows} onOpenWatch={onOpenWatch} /> : null}
        </>
      )}
      <AskBar t={t} value={askText} onChange={onAskText} onAsk={onAsk} asked={asked} />
    </div>
  )
}

export interface MyPageProps {
  t: Translate
}

type MyChannel = 'portfolioOverview' | 'portfolioHistory' | 'watchState'

const SPARK_REFRESH_MS = 30_000

interface MyFailures {
  portfolioOverview: boolean
  portfolioHistory: boolean
  watchState: boolean
}

const NO_MY_FAILURES: MyFailures = {
  portfolioOverview: false,
  portfolioHistory: false,
  watchState: false,
}

/** Stateful page: visible-only polling, stale-on-error, guarded hidden-amount storage. */
export function MyPage({ t }: MyPageProps): ReactElement {
  const [overview, setOverview] = useState<PortfolioOverview | null>(null)
  const [history, setHistory] = useState<HistoryPayload | null>(null)
  const [state, setState] = useState<StatePayload | null>(null)
  const [failures, setFailures] = useState<MyFailures>(NO_MY_FAILURES)
  const [range, setRange] = useState<HistoryRange>('90')
  const [sort, setSort] = useState<PositionSort>(DEFAULT_SORT)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const [hidden, setHidden] = useState(() => readHidden(browserStorage()))
  const [width, setWidth] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth))
  const [askText, setAskText] = useState('')
  const [asked, setAsked] = useState(false)
  const [sparks, setSparks] = useState<Record<string, StockSpark>>({})

  const wrapRef = useRef<HTMLDivElement | null>(null)
  const visibleRef = useRef(true)
  const aliveRef = useRef(true)
  const pollerRef = useRef<Poller | null>(null)
  const rangeRef = useRef<HistoryRange>('90')
  const sparkCodesRef = useRef<string[]>([])
  const askedTimer = useRef<number | null>(null)

  rangeRef.current = range
  sparkCodesRef.current = (overview?.positions ?? []).map((position) => position.code)

  useEffect(() => {
    writeHidden(hidden, browserStorage())
  }, [hidden])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = (): void => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    aliveRef.current = true
    const inflight = new Set<AbortController>()
    let disposed = false

    const mark = (key: MyChannel, failed: boolean): void => {
      if (disposed) return
      setFailures((previous) => (previous[key] === failed ? previous : { ...previous, [key]: failed }))
    }
    const call = async <T,>(path: string, apply: (payload: T) => void, hub = true): Promise<T> => {
      const controller = new AbortController()
      inflight.add(controller)
      try {
        const payload = hub
          ? await getHubJson<T & { ok?: boolean }>(path, controller.signal)
          : await getJson<T>(path, controller.signal)
        if (!disposed) apply(payload as T)
        return payload as T
      } finally {
        inflight.delete(controller)
      }
    }
    const channel = (name: MyChannel, intervalMs: number, load: () => Promise<unknown>) => ({
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

    const poller = new Poller([
      channel('portfolioOverview', 10_000, () => call<Record<string, unknown>>(
        HUB_PORTFOLIO_OVERVIEW_PATH,
        (payload) => setOverview(normalizePortfolioOverview(payload)),
      )),
      channel('portfolioHistory', 5 * 60_000, () => call<Record<string, unknown>>(
        portfolioHistoryPath(historyDays(rangeRef.current)),
        (payload) => setHistory(normalizeHistory(payload)),
      )),
      // Sparklines are decoration: failures never mark the page stale.
      {
        name: 'sparks' as MyChannel,
        intervalMs: SPARK_REFRESH_MS,
        load: async (): Promise<void> => {
          const path = sparkPath(sparkCodesRef.current)
          if (path === null) return
          try {
            await call<Record<string, unknown>>(path, (payload) => setSparks(normalizeSparks(payload)))
          } catch {
            // keep the previous lines
          }
        },
      },
      channel('watchState', 10_000, () => call<StatePayload>(STATE_PATH, (payload) => setState(payload), false)),
    ], {
      setTimeout: (handler, ms) => window.setTimeout(handler, ms),
      clearTimeout: (id) => window.clearTimeout(id),
      isVisible: () => visibleRef.current,
    })
    pollerRef.current = poller

    let observer: IntersectionObserver | null = null
    if (typeof IntersectionObserver !== 'undefined' && wrapRef.current) {
      observer = new IntersectionObserver((entries) => {
        visibleRef.current = entries[0]?.isIntersecting ?? true
        poller.visibleChanged(!document.hidden && visibleRef.current)
      }, { threshold: 0.01 })
      observer.observe(wrapRef.current)
    }
    const onVisibility = (): void => poller.visibleChanged(!document.hidden && visibleRef.current)
    document.addEventListener('visibilitychange', onVisibility)
    poller.start()
    return () => {
      disposed = true
      aliveRef.current = false
      poller.stop()
      observer?.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      for (const controller of inflight) controller.abort()
      inflight.clear()
      if (askedTimer.current !== null) window.clearTimeout(askedTimer.current)
    }
  }, [])

  const sparkCodeKey = sparkCodesRef.current.join(',')
  useEffect(() => {
    if (sparkCodeKey === '') return
    void pollerRef.current?.pollNow('sparks')
  }, [sparkCodeKey])

  useEffect(() => {
    if (overview === null || overview.risk !== null || !overview.riskPending) return
    const timer = window.setTimeout(() => { void pollerRef.current?.pollNow('portfolioOverview') }, 20_000)
    return () => window.clearTimeout(timer)
  }, [overview?.riskPending, overview?.risk])

  const flashAsked = (): void => {
    setAsked(true)
    if (askedTimer.current !== null) window.clearTimeout(askedTimer.current)
    askedTimer.current = window.setTimeout(() => setAsked(false), 4000)
  }

  const ask = (text: string): void => {
    if (typeof window === 'undefined' || text.trim() === '') return
    window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text, persist: false } }))
    setAskText('')
    flashAsked()
  }

  const askImmediately = (text: string): void => {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text, persist: false } }))
    flashAsked()
  }

  const openWatch = (): void => {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent(PANEL_EVENT, { detail: { panel: WORKBENCH_PANEL } }))
  }

  const quotes = useMemo(() => quoteRows(state), [state])

  return (
    <div className="chives-my-scroll" ref={wrapRef}>
      <MyPageView
        sparks={sparks}
        t={t}
        width={width}
        session={classifySession(state?.session)}
        overview={overview}
        history={history}
        quotes={quotes}
        failures={{
          overview: failures.portfolioOverview,
          history: failures.portfolioHistory,
          watch: failures.watchState,
        }}
        range={range}
        onRange={(next) => {
          setRange(next)
          rangeRef.current = next
          void pollerRef.current?.pollNow('portfolioHistory')
        }}
        sort={sort}
        onSort={(key) => setSort((previous) => toggleSort(previous, key))}
        expanded={expanded}
        onExpand={setExpanded}
        highlight={highlight}
        onHighlight={setHighlight}
        hidden={hidden}
        onHidden={setHidden}
        askText={askText}
        onAskText={setAskText}
        onAsk={ask}
        onAskStock={(position) => { setAskText(askStockPrompt(position)) }}
        onImport={() => askImmediately(IMPORT_PROMPT)}
        onDiagnose={() => askImmediately(DIAGNOSE_PROMPT)}
        onOpenWatch={openWatch}
        onRetry={() => {
          void pollerRef.current?.pollNow('portfolioOverview')
          void pollerRef.current?.pollNow('portfolioHistory')
        }}
        asked={asked}
      />
    </div>
  )
}

