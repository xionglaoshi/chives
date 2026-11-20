/**
 * "复盘" page: tonight's review record, the next-day battle cards, discipline and
 * position limits (agent suggests, the user adopts or edits), and the review
 * charts. `ReviewPageView` is a pure props component for DOM tests; `ReviewPage`
 * owns polling, actions and the ask bridge.
 *
 * Nothing here places orders: cards are condition reminders, and every write is
 * one of the three restricted Host routes (setting / discipline / card action).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import { ASK_EVENT } from './panels.ts'
import type { ChivesKey } from './locales.ts'
import { Poller } from './polling.ts'
import {
  CARD_STATES,
  DASH,
  ENV_ZH,
  HUB_CANDIDATE_STATS_PATH,
  HUB_CARD_ACTION_PATH,
  HUB_DISCIPLINE_ACTION_PATH,
  HUB_DISCIPLINE_PATH,
  HUB_REVIEWS_PATH,
  HUB_SETTINGS_PATH,
  HUB_SETTING_ACTION_PATH,
  MARKET_BREADTH_SERIES_PATH,
  MARKET_POOL_HISTORY_PATH,
  MARKET_POOL_INDUSTRY_PATH,
  MARKET_POOL_LADDER_PATH,
  MARKET_POOL_YESTERDAY_PATH,
  MARKET_THEMES_PATH,
  REVIEW_PROMPTS,
  cardActionBody,
  cardsPath,
  formatCny,
  groupSettings,
  lossStreakBody,
  moodBody,
  normalizeBreadthSeries,
  normalizeCandidateStats,
  normalizeCards,
  normalizeDiscipline,
  normalizeIndustryZt,
  normalizeLadder,
  normalizePoolHistory,
  normalizeReview,
  normalizeReviewList,
  normalizeSettings,
  normalizeThemes,
  normalizeYesterday,
  parseSettingInput,
  pendingSuggestionCount,
  reviewOverdue,
  reviewPath,
  seriesGeometry,
  settingBody,
  sizingText,
  sortCards,
} from './reviewModel.ts'
import type {
  BreadthSeries,
  CandidateStats,
  CardState,
  Discipline,
  EnvLabel,
  IndustryZt,
  MoodLevel,
  MoodSlot,
  PoolDay,
  ReviewCard,
  ReviewDetail,
  ReviewSummary,
  SettingRow,
  ThemeRow,
  YesterdayPerformance,
} from './reviewModel.ts'

type Translate = (key: ChivesKey, params?: Record<string, unknown>) => string

/* ------------------------------------------------------------------- helpers */

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: 'GET', signal, headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error('request failed')
  const payload = await response.json() as T & { ok?: boolean }
  if (payload && payload.ok === false) throw new Error('request was not ok')
  return payload
}

/** Restricted hub write (CSRF header + JSON); resolves to whether the hub accepted it. */
async function postHub(path: string, body: unknown): Promise<{ ok: boolean; error: string | null }> {
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { accept: 'application/json', 'content-type': 'application/json', 'x-chives-action': '1' },
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; error?: { code?: string } } | null
    if (response.ok && payload && payload.ok !== false) return { ok: true, error: null }
    return { ok: false, error: payload?.error?.code ?? 'failed' }
  } catch {
    return { ok: false, error: 'unreachable' }
  }
}

function pct(value: number | null, digits = 1): string {
  return value === null ? DASH : `${value.toFixed(digits)}%`
}

function signedPct(value: number | null): string {
  return value === null ? DASH : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function sideClass(value: number | null): string {
  if (value === null || value === 0) return 'is-flat'
  return value > 0 ? 'is-up' : 'is-down'
}

const STATE_KEY: Record<CardState, ChivesKey> = {
  observe: 'rvStateObserve',
  await_confirm: 'rvStateAwait',
  execute: 'rvStateExecute',
  abandon: 'rvStateAbandon',
  exit: 'rvStateExit',
}

const ENV_KEY: Record<EnvLabel, ChivesKey> = { strong: 'rvEnvStrong', neutral: 'rvEnvNeutral', weak: 'rvEnvWeak' }
const GROUP_KEY = { position: 'rvGroupPosition', risk: 'rvGroupRisk', pause: 'rvGroupPause', emergency: 'rvGroupEmergency' } as const
const MOOD_KEY: Record<MoodLevel, ChivesKey> = { calm: 'rvMoodCalm', volatile: 'rvMoodVolatile', unfit: 'rvMoodUnfit' }
const SLOT_KEY: Record<MoodSlot, ChivesKey> = { pre: 'rvSlotPre', mid: 'rvSlotMid', post: 'rvSlotPost' }
const CAP_KEY: Record<string, ChivesKey> = {
  risk_budget: 'rvCapRisk', single_stock_cap: 'rvCapSingle', total_cap: 'rvCapTotal', none: 'rvCapNone',
}

/* --------------------------------------------------------------------- charts */

const CHART_W = 220
const CHART_H = 64

function LineChart({ lines, label }: {
  lines: ReadonlyArray<{ values: ReadonlyArray<number | null>; tone: 'a' | 'b' | 'c' }>
  label: string
}): ReactElement {
  const geometry = useMemo(() => seriesGeometry(lines.map((line) => line.values), CHART_W, CHART_H, { floorZero: true }), [lines])
  if (!geometry) return <span className="chives-rv-empty">{DASH}</span>
  return (
    <svg className="chives-rv-chart" viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" role="img" aria-label={label}>
      {geometry.paths.map((path, index) => (
        <path key={index} className={`chives-rv-line is-${lines[index]!.tone}`} d={path} />
      ))}
    </svg>
  )
}

function Section({ title, meta, children, wide = false, id }: {
  title: string
  meta?: string
  children: ReactElement | ReactElement[] | null
  wide?: boolean
  id?: string
}): ReactElement {
  return (
    <section className={`chives-my-section chives-rv-section${wide ? ' is-wide' : ''}`} data-rv={id}>
      <div className="chives-my-section-head">
        <span className="chives-my-label">{title}</span>
        {meta ? <span className="chives-my-meta">{meta}</span> : null}
      </div>
      {children}
    </section>
  )
}

/* ---------------------------------------------------------------------- cards */

function ConditionList({ title, items }: { title: string; items: ReadonlyArray<{ text: string; ok?: boolean | null }> }): ReactElement | null {
  if (items.length === 0) return null
  return (
    <div className="chives-rv-conds">
      <span className="chives-rv-conds-title">{title}</span>
      <ul>
        {items.map((item, index) => (
          <li key={index} className={item.ok === undefined ? undefined : `has-light is-${item.ok === true ? 'met' : item.ok === false ? 'unmet' : 'unknown'}`}>
            {item.ok === undefined ? null : <i className="chives-rv-light" aria-hidden="true" />}
            {item.text}
          </li>
        ))}
      </ul>
    </div>
  )
}

function CardItem({ t, card, open, onToggle, onAction, busy }: {
  t: Translate
  card: ReviewCard
  open: boolean
  onToggle: () => void
  onAction: (body: ReturnType<typeof cardActionBody>) => void
  busy: boolean
}): ReactElement {
  const [stop, setStop] = useState('')
  const stopValue = /^\d+(\.\d+)?$/.test(stop.trim()) ? Number(stop.trim()) : null
  const proposed = card.status === 'proposed'
  const live = card.status === 'active'
  return (
    <article className={`chives-rv-card is-${card.state}${proposed ? ' is-proposed' : ''}`} data-card={card.id}>
      <header className="chives-rv-card-head" onClick={onToggle}>
        <span className="chives-rv-card-title">
          <strong>{card.name || card.code}</strong>
          <span className="chives-code">{card.code}</span>
          {card.tags.streak !== null ? <span className="chives-rv-tag">{t('rvStreak', { n: card.tags.streak })}</span> : null}
          {card.tags.theme ? <span className="chives-rv-tag">{card.tags.theme}</span> : null}
          {card.late ? <span className="chives-rv-tag is-warn">{t('rvLate')}</span> : null}
        </span>
        <span className={`chives-rv-state is-${card.state}`}>{proposed ? t('rvProposed') : t(STATE_KEY[card.state])}</span>
      </header>
      {card.thesis ? <p className="chives-rv-thesis">{card.thesis}</p> : null}
      {card.judgement ? (
        <p className="chives-rv-judgement">
          <em>{t('rvJudgement')}</em> {card.judgement.action ? `${card.judgement.action}｜` : ''}{card.judgement.reason}
          {card.judgement.nextCheck ? `｜${card.judgement.nextCheck}` : ''}
        </p>
      ) : null}
      <div className="chives-rv-card-line">
        <span><em>{t('rvLastPrice')}</em> {card.lastPrice === null ? DASH : card.lastPrice.toFixed(2)}</span>
        <span><em>{t('rvStop')}</em> {card.stopPrice === null ? DASH : card.stopPrice.toFixed(2)}</span>
        <span><em>{t('rvSizing')}</em> {sizingText(card.sizing)}</span>
      </div>
      {open ? (
        <div className="chives-rv-card-body">
          <ConditionList title={t('rvCondMarket')} items={card.market} />
          <ConditionList title={t('rvCondSector')} items={card.sector} />
          <ConditionList title={t('rvCondStock')} items={card.stock} />
          <ConditionList title={t('rvCondGiveup')} items={card.giveup} />
          {card.exitRules.length > 0 ? <ConditionList title={t('rvCondExit')} items={card.exitRules.map((text) => ({ text }))} /> : null}
          {card.sizing ? (
            <p className="chives-rv-sizing-note">
              {t('rvRiskBudget')} {formatCny(card.sizing.riskBudgetCny)}｜{t('rvStopDistance')} {pct(card.sizing.stopDistancePct)}｜{t(CAP_KEY[card.sizing.cappedBy] ?? 'rvCapNone')}
            </p>
          ) : null}
          {card.history.length > 0 ? (
            <ol className="chives-rv-history">
              {card.history.slice(-6).map((row, index) => (
                <li key={index}><time>{row.ts.slice(11, 19)}</time> {row.from} → {row.to}{row.reason ? `（${row.reason}）` : ''}</li>
              ))}
            </ol>
          ) : null}
          {live ? (
            <div className="chives-rv-card-tools">
              <label className="chives-rv-inline">
                <span>{t('rvTighten')}</span>
                <input value={stop} inputMode="decimal" placeholder={card.stopPrice === null ? '' : `> ${card.stopPrice}`} onChange={(event) => setStop(event.target.value)} />
              </label>
              <button
                type="button"
                disabled={busy || stopValue === null || (card.stopPrice !== null && stopValue <= card.stopPrice)}
                onClick={() => { if (stopValue !== null) onAction(cardActionBody(card.id, 'tighten_stop', stopValue)) }}
              >{t('rvApply')}</button>
              <button type="button" disabled={busy} onClick={() => onAction(cardActionBody(card.id, 'set_state', 'abandon'))}>{t('rvMarkAbandon')}</button>
            </div>
          ) : null}
        </div>
      ) : null}
      <footer className="chives-rv-card-actions">
        {proposed ? (
          <button type="button" className="is-primary" disabled={busy} onClick={() => onAction(cardActionBody(card.id, 'confirm'))}>{t('rvConfirmCard')}</button>
        ) : null}
        {(proposed || live) ? (
          <button type="button" disabled={busy} onClick={() => onAction(cardActionBody(card.id, 'cancel'))}>{t('rvCancelCard')}</button>
        ) : null}
        <button type="button" className="is-ghost" onClick={onToggle}>{open ? t('rvCollapse') : t('rvExpand')}</button>
      </footer>
    </article>
  )
}

function CardsBlock({ t, cards, openId, onToggle, onAction, busy }: {
  t: Translate
  cards: readonly ReviewCard[] | null
  openId: number | null
  onToggle: (id: number) => void
  onAction: (body: ReturnType<typeof cardActionBody>) => void
  busy: boolean
}): ReactElement {
  const visible = sortCards((cards ?? []).filter((card) => card.status === 'proposed' || card.status === 'active'))
  const counts = CARD_STATES.map((state) => [state, visible.filter((card) => card.status === 'active' && card.state === state).length] as const)
  return (
    <Section title={t('rvCards')} meta={t('rvCardsMeta', { n: visible.length })} id="cards">
      <>
        {visible.length > 0 ? (
          <div className="chives-rv-state-strip" aria-label={t('rvCards')}>
            {counts.map(([state, count]) => (
              <span key={state} className={`chives-rv-state-chip is-${state}${count === 0 ? ' is-zero' : ''}`}>{t(STATE_KEY[state])} {count}</span>
            ))}
          </div>
        ) : null}
        {visible.length === 0 ? <div className="chives-rv-empty-block">{cards === null ? t('rvLoading') : t('rvCardsEmpty')}</div> : (
          <div className="chives-rv-cards">
            {visible.map((card) => (
              <CardItem key={card.id} t={t} card={card} open={openId === card.id} onToggle={() => onToggle(card.id)} onAction={onAction} busy={busy} />
            ))}
          </div>
        )}
      </>
    </Section>
  )
}

/* ------------------------------------------------------- discipline + settings */

function SettingItem({ t, row, onAction, busy }: {
  t: Translate
  row: SettingRow
  onAction: (body: ReturnType<typeof settingBody>) => void
  busy: boolean
}): ReactElement {
  const [text, setText] = useState('')
  const parsed = parseSettingInput(row.key, text)
  const sourceKey: ChivesKey = row.source === 'adopted' ? 'rvSrcAdopted' : row.source === 'user_set' ? 'rvSrcUser' : 'rvSrcUnset'
  return (
    <li className={`chives-rv-setting is-${row.source}${row.suggestion ? ' has-suggestion' : ''}`} data-setting={row.key}>
      <div className="chives-rv-setting-main">
        <span className="chives-rv-setting-label">{row.label}</span>
        <span className="chives-rv-setting-value">{row.value === null ? DASH : `${row.value}${row.unit}`}</span>
        <span className={`chives-rv-source is-${row.source}`}>{t(sourceKey)}</span>
        <span className="chives-rv-setting-edit">
          <input value={text} inputMode="decimal" aria-label={row.label} placeholder={row.value === null ? '' : String(row.value)} onChange={(event) => setText(event.target.value)} />
          <button type="button" disabled={busy || parsed === null} onClick={() => { if (parsed !== null) { onAction(settingBody(row.key, 'set', parsed)); setText('') } }}>{t('rvSet')}</button>
          {row.source !== 'unset' ? <button type="button" className="is-ghost" disabled={busy} onClick={() => onAction(settingBody(row.key, 'clear'))}>{t('rvClear')}</button> : null}
        </span>
      </div>
      {row.suggestion ? (
        <div className="chives-rv-suggest">
          <span className="chives-rv-suggest-head">{t('rvSuggested', { value: `${row.suggestion.value}${row.unit}` })}{row.suggestion.backtested ? '' : `｜${t('rvNotBacktested')}`}</span>
          {row.suggestion.basis ? <span className="chives-rv-suggest-basis">{row.suggestion.basis}</span> : null}
          <span className="chives-rv-suggest-actions">
            <button type="button" className="is-primary" disabled={busy} onClick={() => onAction(settingBody(row.key, 'adopt'))}>{t('rvAdopt')}</button>
            <button type="button" className="is-ghost" disabled={busy} onClick={() => onAction(settingBody(row.key, 'dismiss'))}>{t('rvDismiss')}</button>
          </span>
        </div>
      ) : null}
    </li>
  )
}

function DisciplineBlock({ t, discipline, settings, onSetting, onDiscipline, onAsk, busy }: {
  t: Translate
  discipline: Discipline | null
  settings: readonly SettingRow[] | null
  onSetting: (body: ReturnType<typeof settingBody>) => void
  onDiscipline: (body: ReturnType<typeof lossStreakBody> | ReturnType<typeof moodBody>) => void
  onAsk: (text: string) => void
  busy: boolean
}): ReactElement {
  const rows = settings ?? []
  const groups = groupSettings(rows)
  const pending = pendingSuggestionCount(rows)
  const head = discipline?.headroom
  return (
    <Section title={t('rvDiscipline')} meta={pending > 0 ? t('rvPendingSuggestions', { n: pending }) : undefined} id="discipline">
      <>
        {discipline?.paused ? (
          <div className="chives-rv-pause" role="alert">
            <strong>{t('rvPaused')}</strong>
            <span>{discipline.reasons.map((reason) => reason.text).filter(Boolean).join('；') || t('rvPausedHint')}</span>
          </div>
        ) : null}
        {discipline ? (
          <div className="chives-rv-metrics">
            <span><em>{t('rvDayDrawdown')}</em> {pct(discipline.dayDrawdownPct)}</span>
            <span><em>{t('rvTotalLoss')}</em> {pct(discipline.totalLossPct)}</span>
            <span><em>{t('rvLossStreak')}</em> {discipline.lossStreak}
              <button type="button" disabled={busy} onClick={() => onDiscipline(lossStreakBody('add'))} aria-label={t('rvAddLoss')}>+1</button>
              <button type="button" className="is-ghost" disabled={busy || discipline.lossStreak === 0} onClick={() => onDiscipline(lossStreakBody('reset'))}>{t('rvResetLoss')}</button>
            </span>
          </div>
        ) : null}
        {head ? (
          <div className="chives-rv-headroom">
            <span><em>{t('rvHeadTotal')}</em> {head.totalCapPct === null ? t('rvNotSet') : `${pct(head.positionRatioPct)} / ${pct(head.totalCapPct, 0)}`}</span>
            <span><em>{t('rvHeadSingle')}</em> {head.singleCapPct === null ? t('rvNotSet') : `${pct(head.topWeightPct)} / ${pct(head.singleCapPct, 0)}`}</span>
            <span><em>{t('rvHeadTheme')}</em> {head.themeCapPct === null ? t('rvNotSet') : `${head.topTheme ? head.topTheme.name : DASH} ${pct(head.topTheme?.weightPct ?? null)} / ${pct(head.themeCapPct, 0)}`}</span>
          </div>
        ) : null}
        {discipline ? (
          <div className="chives-rv-mood">
            {(['pre', 'mid', 'post'] as const).map((slot) => (
              <div key={slot} className="chives-rv-mood-slot">
                <span>{t(SLOT_KEY[slot])}</span>
                {(['calm', 'volatile', 'unfit'] as const).map((level) => (
                  <button
                    key={level}
                    type="button"
                    className={`chives-rv-mood-btn${discipline.mood[slot] === level ? ' is-on' : ''}`}
                    aria-pressed={discipline.mood[slot] === level}
                    disabled={busy}
                    onClick={() => onDiscipline(moodBody(slot, level))}
                  >{t(MOOD_KEY[level])}</button>
                ))}
              </div>
            ))}
          </div>
        ) : null}
        <div className="chives-rv-settings">
          {groups.length === 0 ? <div className="chives-rv-empty-block">{settings === null ? t('rvLoading') : t('rvSettingsEmpty')}</div> : groups.map((group) => (
            <div key={group.id} className="chives-rv-setting-group">
              <h3>{t(GROUP_KEY[group.id as keyof typeof GROUP_KEY])}</h3>
              <ul>{group.rows.map((row) => <SettingItem key={row.key} t={t} row={row} onAction={onSetting} busy={busy} />)}</ul>
            </div>
          ))}
        </div>
        <div className="chives-rv-block-actions">
          <button type="button" onClick={() => onAsk(REVIEW_PROMPTS.suggestSettings)}>{t('rvAskSuggest')}</button>
          <span className="chives-rv-fineprint">{t('rvSettingsNote')}</span>
        </div>
      </>
    </Section>
  )
}

/* --------------------------------------------------------------- review record */

function ReviewBlock({ t, list, detail, selected, onSelect, onAsk }: {
  t: Translate
  list: readonly ReviewSummary[] | null
  detail: ReviewDetail | null
  selected: string | null
  onSelect: (key: string) => void
  onAsk: (text: string) => void
}): ReactElement {
  const [showBody, setShowBody] = useState(false)
  const items = list ?? []
  return (
    <Section title={t('rvRecord')} id="record" wide>
      <>
        <div className="chives-rv-record-bar">
          <select value={selected ?? ''} aria-label={t('rvRecord')} onChange={(event) => onSelect(event.target.value)}>
            {items.length === 0 ? <option value="">{DASH}</option> : null}
            {items.map((row) => (
              <option key={`${row.date}|${row.kind}`} value={`${row.date}|${row.kind}`}>{row.date} {row.kind === 'evening' ? t('rvKindEvening') : t('rvKindPremarket')}</option>
            ))}
          </select>
          <button type="button" onClick={() => onAsk(REVIEW_PROMPTS.runNow)}>{t('rvRunNow')}</button>
          <button type="button" onClick={() => onAsk(REVIEW_PROMPTS.premarket)}>{t('rvRunPremarket')}</button>
          <button type="button" className="is-ghost" onClick={() => onAsk(REVIEW_PROMPTS.enableSchedule)}>{t('rvEnableSchedule')}</button>
        </div>
        {detail === null ? <div className="chives-rv-empty-block">{list === null ? t('rvLoading') : t('rvNoReview')}</div> : (
          <div className="chives-rv-record">
            <div className="chives-rv-record-head">
              {detail.envLabel ? <span className={`chives-rv-env is-${detail.envLabel}`}>{t(ENV_KEY[detail.envLabel])}</span> : null}
              <span className="chives-my-meta">{t('rvCutoff')} {detail.dataCutoff || DASH}｜{t('rvSources')} {detail.sources.join('、') || DASH}｜v{detail.revision}</span>
            </div>
            {detail.evidence.length > 0 ? <ul className="chives-rv-evidence">{detail.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul> : null}
            {detail.differsFromRule ? <p className="chives-rv-differs">{t('rvDiffers')} {detail.differsNote}</p> : null}
            {detail.mainline ? <p><em>{t('rvMainline')}</em> {detail.mainline.name}：{detail.mainline.note}</p> : null}
            {detail.themes.length > 0 ? <p><em>{t('rvThemes')}</em> {detail.themes.map((item) => `${item.name}（${item.note}）`).join('；')}</p> : null}
            {detail.yesterdayFeedback ? <p><em>{t('rvYesterday')}</em> {detail.yesterdayFeedback}</p> : null}
            {detail.candidates.length > 0 ? (
              <div className="chives-rv-candidates">
                <em>{t('rvCandidates')}</em>
                <ul>{detail.candidates.map((item) => <li key={item.code}><strong>{item.code}</strong> {item.reason}</li>)}</ul>
              </div>
            ) : null}
            {detail.events.length > 0 ? (
              <div className="chives-rv-events">
                <em>{t('rvEvents')}</em>
                <ul>{detail.events.map((item, index) => (
                  <li key={index}>{item.date} {item.target} {item.type}{item.uncertain ? `（${t('rvUncertain')}）` : ''} {item.note}</li>
                ))}</ul>
              </div>
            ) : null}
            {detail.pending.length > 0 ? (
              <div className="chives-rv-pending">
                <em>{t('rvPending')}</em>
                <ul>{detail.pending.map((item, index) => <li key={index}>{item}</li>)}</ul>
              </div>
            ) : null}
            {detail.checklist.length > 0 ? (
              <div className="chives-rv-checklist">
                {detail.checklist.map((item, index) => (
                  <span key={index} className={`chives-rv-check${item.ok ? ' is-ok' : ' is-miss'}`} title={item.note}>{item.ok ? '✓' : '○'} {item.item}</span>
                ))}
              </div>
            ) : null}
            {detail.bodyMarkdown ? (
              <div className="chives-rv-body">
                <button type="button" className="is-ghost" aria-expanded={showBody} onClick={() => setShowBody(!showBody)}>{showBody ? t('rvHideBody') : t('rvShowBody')}</button>
                {showBody ? <pre className="chives-rv-pre">{detail.bodyMarkdown}</pre> : null}
              </div>
            ) : null}
          </div>
        )}
      </>
    </Section>
  )
}

/* ---------------------------------------------------------------- market block */

export interface ReviewMarketData {
  poolHistory: PoolDay[] | null
  ladder: { maxStreak: number; tiers: Array<{ streak: number; count: number; names: string[] }> } | null
  themes: ThemeRow[] | null
  industry: IndustryZt[] | null
  yesterday: YesterdayPerformance | null
  breadth: BreadthSeries | null
  stats: CandidateStats | null
}

function ChartCard({ title, note, children }: { title: string; note?: string; children: ReactElement | ReactElement[] }): ReactElement {
  return (
    <div className="chives-rv-chartcard">
      <div className="chives-rv-chartcard-head"><span>{title}</span>{note ? <em>{note}</em> : null}</div>
      {children}
    </div>
  )
}

function Legend({ items }: { items: ReadonlyArray<{ tone: 'a' | 'b' | 'c'; label: string; value?: string }> }): ReactElement {
  return (
    <div className="chives-rv-legend">
      {items.map((item) => (
        <span key={item.label}><i className={`chives-rv-dot is-${item.tone}`} />{item.label}{item.value ? ` ${item.value}` : ''}</span>
      ))}
    </div>
  )
}

function MarketBlock({ t, data }: { t: Translate; data: ReviewMarketData }): ReactElement {
  const days = (data.poolHistory ?? []).filter((day) => day.available)
  const last = days[days.length - 1]
  const missing = (data.poolHistory ?? []).filter((day) => !day.available).length
  const tiers = data.ladder?.tiers ?? []
  const maxCount = Math.max(1, ...tiers.map((tier) => tier.count))
  const breadthPts = data.breadth?.points ?? []
  const y = data.yesterday
  const stats = data.stats
  return (
    <Section title={t('rvCharts')} meta={missing > 0 ? t('rvMissingDays', { n: missing }) : undefined} wide id="charts">
      <div className="chives-rv-charts">
        <ChartCard title={t('rvChartPool')} note={t('rvDays', { n: days.length })}>
          <LineChart label={t('rvChartPool')} lines={[
            { values: days.map((day) => day.zt), tone: 'a' },
            { values: days.map((day) => day.zb), tone: 'b' },
            { values: days.map((day) => day.dt), tone: 'c' },
          ]} />
          <Legend items={[
            { tone: 'a', label: t('rvZt'), value: last?.zt?.toString() },
            { tone: 'b', label: t('rvZb'), value: last?.zb?.toString() },
            { tone: 'c', label: t('rvDt'), value: last?.dt?.toString() },
          ]} />
        </ChartCard>
        <ChartCard title={t('rvChartPromote')} note={t('rvDefinitionNote')}>
          <LineChart label={t('rvChartPromote')} lines={[
            { values: days.map((day) => day.sealRatioPct), tone: 'a' },
            { values: days.map((day) => day.promote12), tone: 'b' },
            { values: days.map((day) => day.promote23), tone: 'c' },
          ]} />
          <Legend items={[
            { tone: 'a', label: t('rvSealRatio'), value: pct(last?.sealRatioPct ?? null, 0) },
            { tone: 'b', label: t('rvPromote12'), value: pct(last?.promote12 ?? null, 0) },
            { tone: 'c', label: t('rvPromote23'), value: pct(last?.promote23 ?? null, 0) },
          ]} />
        </ChartCard>
        <ChartCard title={t('rvChartLadder')} note={data.ladder ? t('rvMaxStreak', { n: data.ladder.maxStreak }) : undefined}>
          {tiers.length === 0 ? <span className="chives-rv-empty">{DASH}</span> : (
            <ul className="chives-rv-ladder">
              {tiers.map((tier) => (
                <li key={tier.streak}>
                  <span className="chives-rv-ladder-n">{t('rvStreak', { n: tier.streak })}</span>
                  <span className="chives-rv-bar"><i style={{ width: `${(tier.count / maxCount) * 100}%` }} /></span>
                  <span className="chives-rv-ladder-c">{tier.count}</span>
                  <span className="chives-rv-ladder-names">{tier.names.slice(0, 3).join('、')}</span>
                </li>
              ))}
            </ul>
          )}
        </ChartCard>
        <ChartCard title={t('rvChartThemes')} note={t('rvConceptNote')}>
          {(data.themes ?? []).length === 0 ? <span className="chives-rv-empty">{DASH}</span> : (
            <ul className="chives-rv-themes">
              {(data.themes ?? []).slice(0, 8).map((row) => (
                <li key={row.code}><span>{row.name}</span><em className={sideClass(row.changePct)}>{signedPct(row.changePct)}</em></li>
              ))}
            </ul>
          )}
        </ChartCard>
        <ChartCard title={t('rvChartIndustry')} note={t('rvIndustryNote')}>
          {(data.industry ?? []).length === 0 ? <span className="chives-rv-empty">{DASH}</span> : (
            <ul className="chives-rv-themes">
              {(data.industry ?? []).slice(0, 8).map((row) => (
                <li key={row.industry}><span>{row.industry}</span><em>{t('rvZtCount', { n: row.zt })}{row.zb > 0 ? ` · ${t('rvZbCount', { n: row.zb })}` : ''}</em></li>
              ))}
            </ul>
          )}
        </ChartCard>
        <ChartCard title={t('rvChartYesterday')} note={y?.date ? `${y.prevDate} → ${y.date}` : undefined}>
          {y && y.count > 0 ? (
            <dl className="chives-rv-kv">
              <div><dt>{t('rvAvgOpen')}</dt><dd className={sideClass(y.avgOpenPct)}>{signedPct(y.avgOpenPct)}</dd></div>
              <div><dt>{t('rvAvgClose')}</dt><dd className={sideClass(y.avgClosePct)}>{signedPct(y.avgClosePct)}</dd></div>
              <div><dt>{t('rvWinRatio')}</dt><dd>{pct(y.winRatioPct, 0)}</dd></div>
              <div><dt>{t('rvSample')}</dt><dd>{y.count}</dd></div>
            </dl>
          ) : <span className="chives-rv-empty">{y?.reason || DASH}</span>}
        </ChartCard>
        <ChartCard title={t('rvChartBreadth')} note={data.breadth?.gaps ? t('rvHasGaps') : undefined}>
          <LineChart label={t('rvChartBreadth')} lines={[
            { values: breadthPts.map((row) => row.up), tone: 'a' },
            { values: breadthPts.map((row) => row.down), tone: 'c' },
          ]} />
          <Legend items={[
            { tone: 'a', label: t('rvUp'), value: breadthPts.length ? String(breadthPts[breadthPts.length - 1]!.up) : undefined },
            { tone: 'c', label: t('rvDown'), value: breadthPts.length ? String(breadthPts[breadthPts.length - 1]!.down) : undefined },
          ]} />
        </ChartCard>
        <ChartCard title={t('rvChartStats')} note={stats && stats.insufficient ? t('rvSampleInsufficient', { n: stats.n }) : undefined}>
          {stats && stats.n > 0 ? (
            <dl className="chives-rv-kv">
              <div><dt>{t('rvTriggerRate')}</dt><dd>{pct(stats.triggerRatePct, 0)}</dd></div>
              <div><dt>{t('rvAvgOpen')}</dt><dd className={sideClass(stats.avgOpenPct)}>{signedPct(stats.avgOpenPct)}</dd></div>
              <div><dt>{t('rvAvgClose')}</dt><dd className={sideClass(stats.avgClosePct)}>{signedPct(stats.avgClosePct)}</dd></div>
              <div><dt>{t('rvWinRatio')}</dt><dd>{pct(stats.winRatioPct, 0)}</dd></div>
            </dl>
          ) : <span className="chives-rv-empty">{t('rvStatsEmpty')}</span>}
        </ChartCard>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------- the view */

export interface ReviewPageViewProps {
  t: Translate
  now: Date
  cards: readonly ReviewCard[] | null
  discipline: Discipline | null
  settings: readonly SettingRow[] | null
  reviews: readonly ReviewSummary[] | null
  detail: ReviewDetail | null
  selected: string | null
  onSelect: (key: string) => void
  market: ReviewMarketData
  openCard: number | null
  onToggleCard: (id: number) => void
  onCardAction: (body: ReturnType<typeof cardActionBody>) => void
  onSetting: (body: ReturnType<typeof settingBody>) => void
  onDiscipline: (body: ReturnType<typeof lossStreakBody> | ReturnType<typeof moodBody>) => void
  onAsk: (text: string) => void
  busy: boolean
  failed: boolean
  notice: string | null
}

export function ReviewPageView(props: ReviewPageViewProps): ReactElement {
  const { t, now, cards, discipline, settings, reviews, detail, selected, market, onAsk, busy } = props
  const overdue = reviews !== null && reviewOverdue(now, reviews)
  const latestEnv = detail?.envLabel ?? null
  const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return (
    <div className="chives-my chives-rv" data-page="review">
      <header className="chives-my-top">
        <div className="chives-my-title-block">
          <h1 className="chives-my-title">{t('rvTitle')}</h1>
          <span className="chives-my-topmeta">
            <span>{stamp}</span>
            {latestEnv ? <span className={`chives-rv-env is-${latestEnv}`}>{t(ENV_KEY[latestEnv])}</span> : null}
            {discipline?.paused ? <span className="chives-rv-env is-weak">{t('rvPaused')}</span> : null}
          </span>
        </div>
      </header>
      {props.failed ? <div className="chives-my-banner">{t('rvFailed')}</div> : null}
      {props.notice ? <div className="chives-my-banner is-info" role="status">{props.notice}</div> : null}
      {overdue ? (
        <div className="chives-my-banner is-info" role="status">
          <span>{t('rvOverdue')}</span>
          <button type="button" className="is-primary" onClick={() => onAsk(REVIEW_PROMPTS.runNow)}>{t('rvRunNow')}</button>
        </div>
      ) : null}
      <div className="chives-rv-grid">
        <div className="chives-my-col is-left">
          <CardsBlock t={t} cards={cards} openId={props.openCard} onToggle={props.onToggleCard} onAction={props.onCardAction} busy={busy} />
          <ReviewBlock t={t} list={reviews} detail={detail} selected={selected} onSelect={props.onSelect} onAsk={onAsk} />
        </div>
        <div className="chives-my-col is-right">
          <DisciplineBlock t={t} discipline={discipline} settings={settings} onSetting={props.onSetting} onDiscipline={props.onDiscipline} onAsk={onAsk} busy={busy} />
        </div>
      </div>
      <MarketBlock t={t} data={market} />
    </div>
  )
}

/* ---------------------------------------------------------------- the container */

export interface ReviewPageProps {
  t: Translate
}

const NO_MARKET: ReviewMarketData = { poolHistory: null, ladder: null, themes: null, industry: null, yesterday: null, breadth: null, stats: null }

export function ReviewPage({ t }: ReviewPageProps): ReactElement {
  const [cards, setCards] = useState<ReviewCard[] | null>(null)
  const [discipline, setDiscipline] = useState<Discipline | null>(null)
  const [settings, setSettings] = useState<SettingRow[] | null>(null)
  const [reviews, setReviews] = useState<ReviewSummary[] | null>(null)
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [market, setMarket] = useState<ReviewMarketData>(NO_MARKET)
  const [openCard, setOpenCard] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [now, setNow] = useState(() => new Date())

  const wrapRef = useRef<HTMLDivElement | null>(null)
  const pollerRef = useRef<Poller | null>(null)
  const visibleRef = useRef(true)
  const selectedRef = useRef<string | null>(null)
  const noticeTimer = useRef<number | null>(null)
  selectedRef.current = selected

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    let disposed = false
    const inflight = new Set<AbortController>()
    const call = async <T,>(path: string, apply: (payload: T) => void): Promise<void> => {
      const controller = new AbortController()
      inflight.add(controller)
      try {
        const payload = await getJson<T>(path, controller.signal)
        if (!disposed) apply(payload)
      } finally {
        inflight.delete(controller)
      }
    }
    const patchMarket = (patch: Partial<ReviewMarketData>): void => setMarket((current) => ({ ...current, ...patch }))
    // Section data is decoration around the cards: a failing chart never blanks the page.
    const quiet = (name: string, intervalMs: number, load: () => Promise<void>) => ({
      name,
      intervalMs,
      load: async (): Promise<void> => {
        try { await load() } catch { /* keep the previous data */ }
      },
    })
    const critical = (name: string, intervalMs: number, load: () => Promise<void>) => ({
      name,
      intervalMs,
      load: async (): Promise<void> => {
        try { await load(); if (!disposed) setFailed(false) } catch (error) { if (!disposed) setFailed(true); throw error }
      },
    })
    const loadDetail = async (): Promise<void> => {
      const key = selectedRef.current
      if (key === null) return
      const [date, kind] = key.split('|')
      if (!date || (kind !== 'evening' && kind !== 'premarket')) return
      await call<Record<string, unknown>>(reviewPath(date, kind), (payload) => setDetail(normalizeReview(payload)))
    }
    const poller = new Poller([
      critical('cards', 5_000, () => call<Record<string, unknown>>(cardsPath('all'), (payload) => setCards(normalizeCards(payload)))),
      critical('discipline', 10_000, () => call<Record<string, unknown>>(HUB_DISCIPLINE_PATH, (payload) => setDiscipline(normalizeDiscipline(payload)))),
      critical('settings', 10_000, () => call<Record<string, unknown>>(HUB_SETTINGS_PATH, (payload) => setSettings(normalizeSettings(payload)))),
      critical('reviews', 30_000, async () => {
        await call<Record<string, unknown>>(`${HUB_REVIEWS_PATH}?limit=30`, (payload) => {
          const list = normalizeReviewList(payload)
          setReviews(list)
          if (selectedRef.current === null && list.length > 0) {
            const first = `${list[0]!.date}|${list[0]!.kind}`
            selectedRef.current = first
            setSelected(first)
          }
        })
        await loadDetail()
      }),
      quiet('poolHistory', 5 * 60_000, () => call<Record<string, unknown>>(`${MARKET_POOL_HISTORY_PATH}?days=20`, (payload) => patchMarket({ poolHistory: normalizePoolHistory(payload) }))),
      quiet('ladder', 60_000, () => call<Record<string, unknown>>(MARKET_POOL_LADDER_PATH, (payload) => patchMarket({ ladder: normalizeLadder(payload) }))),
      quiet('themes', 60_000, () => call<Record<string, unknown>>(`${MARKET_THEMES_PATH}?kind=concept&limit=10&sort=change`, (payload) => patchMarket({ themes: normalizeThemes(payload) }))),
      quiet('industry', 60_000, () => call<Record<string, unknown>>(MARKET_POOL_INDUSTRY_PATH, (payload) => patchMarket({ industry: normalizeIndustryZt(payload) }))),
      quiet('yesterday', 60_000, () => call<Record<string, unknown>>(MARKET_POOL_YESTERDAY_PATH, (payload) => patchMarket({ yesterday: normalizeYesterday(payload) }))),
      quiet('breadth', 60_000, () => call<Record<string, unknown>>(MARKET_BREADTH_SERIES_PATH, (payload) => patchMarket({ breadth: normalizeBreadthSeries(payload) }))),
      quiet('stats', 5 * 60_000, () => call<Record<string, unknown>>(`${HUB_CANDIDATE_STATS_PATH}?days=20`, (payload) => patchMarket({ stats: normalizeCandidateStats(payload) }))),
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
      poller.stop()
      observer?.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      for (const controller of inflight) controller.abort()
      inflight.clear()
      if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    }
  }, [])

  const flash = (message: string): void => {
    setNotice(message)
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000)
  }

  const write = async (path: string, body: unknown, refresh: string[]): Promise<void> => {
    setBusy(true)
    const result = await postHub(path, body)
    setBusy(false)
    if (!result.ok) flash(t('rvActionFailed', { code: result.error ?? 'failed' }))
    for (const name of refresh) void pollerRef.current?.pollNow(name)
  }

  const onAsk = (text: string): void => {
    window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text, persist: false } }))
    flash(t('rvAsked'))
  }

  const onSelect = (key: string): void => {
    selectedRef.current = key
    setSelected(key)
    setDetail(null)
    void pollerRef.current?.pollNow('reviews')
  }

  return (
    <div ref={wrapRef} className="chives-rv-wrap">
      <ReviewPageView
        t={t}
        now={now}
        cards={cards}
        discipline={discipline}
        settings={settings}
        reviews={reviews}
        detail={detail}
        selected={selected}
        onSelect={onSelect}
        market={market}
        openCard={openCard}
        onToggleCard={(id) => setOpenCard((current) => (current === id ? null : id))}
        onCardAction={(body) => { void write(HUB_CARD_ACTION_PATH, body, ['cards']) }}
        onSetting={(body) => { void write(HUB_SETTING_ACTION_PATH, body, ['settings', 'discipline']) }}
        onDiscipline={(body) => { void write(HUB_DISCIPLINE_ACTION_PATH, body, ['discipline']) }}
        onAsk={onAsk}
        busy={busy}
        failed={failed}
        notice={notice}
      />
    </div>
  )
}

export { ENV_ZH }
