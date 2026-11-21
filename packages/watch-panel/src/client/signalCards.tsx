/**
 * Signal-card presentation for the watch panel.
 *
 * Pure props: the container owns fetching, filtering and the optimistic action
 * state. Colours are referenced only through `--chives-sig-*` / up/down tokens,
 * and every interactive control is a real button so keyboard use matches hover.
 */
import { useState } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import { DASH } from './market.ts'
import {
  conclusionText,
  directionMeta,
  mergedLabel,
  rankGeometry,
  rangeGeometry,
  signalTone,
  signalToneToken,
  signalKindLabel,
  signalTime,
  sparkGeometry,
  type Signal,
} from './signals.ts'
import type { SnoozeOption } from './signals.ts'
import type { WatchPanelKey } from './locales.ts'

type Translate = (key: WatchPanelKey, params?: Record<string, unknown>) => string

const KIND_ICON: Record<string, string> = {
  plan_proposal: '\u25ce',
  plan_entry: '\u25ce',
  plan_giveup: '\u2301',
  plan_other: '\u25ce',
  opportunity: '\u2726',
  risk: '\u25b3',
  sector: '\u25a6',
  info: '\u2022',
}

export function signalIcon(signal: Signal): string {
  return KIND_ICON[signal.kind] ?? '\u2022'
}

function cardStyle(signal: Signal): CSSProperties {
  return { ['--chives-sig-c' as string]: signalToneToken(signal.kind) }
}

function objectTag(t: Translate, signal: Signal): string | null {
  if (signal.object.type === 'stock') return t('wbFeedMine')
  if (signal.object.type === 'sector') return t('wbFeedSector')
  if (signal.object.type === 'market') return t('wbMarket')
  return null
}

function RangeWidget({ signal }: { signal: Signal }): ReactElement | null {
  if (signal.context?.type !== 'range') return null
  const geometry = rangeGeometry(signal.context)
  return (
    <div className="chives-sig-ctx" data-ctx="range">
      <div className="chives-sig-ctx-head"><span>{geometry.label}</span><span>{geometry.zoneText}</span></div>
      <div className="chives-sig-range">
        {geometry.zoneLeft !== null && geometry.zoneWidth !== null ? (
          <span className="chives-sig-zone" style={{ left: `${geometry.zoneLeft}%`, width: `${geometry.zoneWidth}%` }} />
        ) : null}
        {geometry.markerLeft !== null ? (
          <span className={`chives-sig-marker${geometry.giveup ? ' is-giveup' : ''}`} style={{ left: `${geometry.markerLeft}%` }}>
            <span>{geometry.markerText}</span>
          </span>
        ) : null}
        <span className="chives-sig-price" style={{ left: `${geometry.priceLeft}%` }}><span>{geometry.priceText}</span></span>
      </div>
    </div>
  )
}

function RankWidget({ signal }: { signal: Signal }): ReactElement | null {
  if (signal.context?.type !== 'rank') return null
  const geometry = rankGeometry(signal.context)
  return (
    <div className="chives-sig-ctx" data-ctx="rank">
      <div className="chives-sig-rank-row">
        <span>{'\u6392\u540d'}</span>
        <span className="chives-sig-rank-big">{geometry.from} <span className="chives-sig-arrow">{'\u2192'}</span> {geometry.to}</span>
        <span className="chives-sig-rank-share">{'\u6210\u4ea4\u989d\u5360\u6bd4'} {geometry.shareText}</span>
      </div>
      {geometry.spark ? (
        <svg className="chives-sig-spark" viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
          <path d={geometry.spark.path} fill="none" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
        </svg>
      ) : null}
    </div>
  )
}

function SparkWidget({ signal }: { signal: Signal }): ReactElement | null {
  if (signal.context?.type !== 'spark') return null
  const geometry = sparkGeometry(signal.context.points)
  if (!geometry) return null
  return (
    <div className="chives-sig-ctx" data-ctx="spark">
      <div className="chives-sig-ctx-head"><span>{signal.context.label || '\u8d70\u52bf'}</span><span /></div>
      <svg className="chives-sig-spark" viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
        <path d={geometry.path} fill="none" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
      </svg>
    </div>
  )
}

export function SignalContextView({ signal }: { signal: Signal }): ReactElement | null {
  if (signal.context === null) return null
  if (signal.context.type === 'range') return <RangeWidget signal={signal} />
  if (signal.context.type === 'rank') return <RankWidget signal={signal} />
  return <SparkWidget signal={signal} />
}

export interface SignalCardProps {
  t: Translate
  signal: Signal
  hero: boolean
  index: number
  onPrimary: (signal: Signal) => void
  onRecheck: (signal: Signal) => void
  onSnooze: (signal: Signal, until: SnoozeOption['value']) => void
  onIgnore: (signal: Signal) => void
}

/** One signal card: kind colour, direction pill, context widget, actions. */
export function SignalCard({ t, signal, hero, index, onPrimary, onRecheck, onSnooze, onIgnore }: SignalCardProps): ReactElement {
  const [menu, setMenu] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const tone = signalTone(signal.kind)
  const direction = directionMeta(signal.direction, signal.directionLabel)
  const merged = mergedLabel(signal)
  const tag = objectTag(t, signal)
  const source = signal.source.label
  return (
    <article
      className={`chives-sig-card is-${tone}${hero ? ' is-hero' : ''}${signal.status === 'new' ? ' is-new' : ''}${leaving ? ' is-leaving' : ''}`}
      style={{ ...cardStyle(signal), animationDelay: `${Math.min(400, index * 40)}ms` }}
      data-signal={signal.id}
      aria-label={signal.title}
    >
      <div className="chives-sig-top">
        <span className="chives-sig-ico" aria-hidden="true">{signalIcon(signal)}</span>
        <span className="chives-sig-type">{signalKindLabel(signal.kind, signal.kindLabel)}</span>
        {signal.status === 'new' ? <span className="chives-sig-new" title={t('wbSignalNew')} /> : null}
        <span className="chives-sig-time">{signalTime(signal)}</span>
      </div>
      <div className="chives-sig-title">{signal.title}</div>
      <div className="chives-sig-chips">
        <span className={`chives-sig-dir is-${direction.tone}`}>{direction.glyph} {direction.label}</span>
        {tag ? <span className="chives-sig-tag">{tag}</span> : null}
        {signal.object.code ? <span className="chives-sig-tag is-code">{signal.object.code}</span> : null}
        {merged ? <span className="chives-sig-tag is-merged">{t('wbSignalMerged', { count: signal.mergedCount })}</span> : null}
      </div>
      <p className="chives-sig-concl">{conclusionText(signal)}</p>
      {signal.brief ? <p className="chives-sig-brief">{signal.brief}</p> : null}
      <SignalContextView signal={signal} />
      {source ? <div className="chives-sig-src">{source}</div> : null}
      <div className="chives-sig-acts">
        <button type="button" className="chives-sig-btn is-primary" onClick={() => onPrimary(signal)}>{signal.primary.label}</button>
        <button type="button" className="chives-sig-btn" onClick={() => onRecheck(signal)}>{t('wbRecheck')}</button>
        <span className="chives-sig-snooze">
          <button
            type="button"
            className="chives-sig-btn"
            aria-haspopup="menu"
            aria-expanded={menu}
            onClick={() => setMenu((open) => !open)}
          >
            {t('wbSnooze')} {'\u25be'}
          </button>
          <div className={`chives-sig-menu${menu ? ' is-open' : ''}`} role="menu">
            <button type="button" role="menuitem" onClick={() => { setMenu(false); onSnooze(signal, '30m') }}>{'\u0033\u0030 \u5206\u949f\u540e'}</button>
            <button type="button" role="menuitem" onClick={() => { setMenu(false); onSnooze(signal, 'close') }}>{'\u6536\u76d8\u524d'}</button>
            <button type="button" role="menuitem" onClick={() => { setMenu(false); onSnooze(signal, 'next_open') }}>{'\u660e\u5929\u5f00\u76d8'}</button>
          </div>
        </span>
        <button
          type="button"
          className="chives-sig-btn"
          onClick={() => {
            if (leaving) return
            setLeaving(true)
            if (typeof window === 'undefined') onIgnore(signal)
            else window.setTimeout(() => onIgnore(signal), 240)
          }}
        >
          {t('wbIgnore')}
        </button>
      </div>
    </article>
  )
}

/** Medium-card rail: two columns on desktop, one on narrow screens. */
export function SignalRail({ t, signals, onPrimary, onRecheck, onSnooze, onIgnore }: {
  t: Translate
  signals: readonly Signal[]
  onPrimary: (signal: Signal) => void
  onRecheck: (signal: Signal) => void
  onSnooze: (signal: Signal, until: SnoozeOption['value']) => void
  onIgnore: (signal: Signal) => void
}): ReactElement | null {
  if (signals.length === 0) return null
  return (
    <div className="chives-sig-rail">
      {signals.map((signal, index) => (
        <SignalCard
          key={signal.id}
          t={t}
          signal={signal}
          hero={false}
          index={index}
          onPrimary={onPrimary}
          onRecheck={onRecheck}
          onSnooze={onSnooze}
          onIgnore={onIgnore}
        />
      ))}
    </div>
  )
}

/** Collapsed "已处理" row; expanding shows the newest 20 with a reopen action. */
export function DoneFold({ t, signals, count, merged, open, onOpen, onReopen }: {
  t: Translate
  signals: readonly Signal[]
  count?: number
  merged?: number
  open: boolean
  onOpen: (open: boolean) => void
  onReopen: (signal: Signal) => void
}): ReactElement | null {
  if (signals.length === 0) return null
  const total = count ?? signals.length
  const mergedTotal = merged ?? signals.reduce((sum, signal) => sum + Math.max(0, signal.mergedCount - 1), 0)
  return (
    <div className={`chives-sig-done${open ? ' is-open' : ''}`}>
      <button type="button" className="chives-sig-done-fold" aria-expanded={open} onClick={() => onOpen(!open)}>
        <span>{t('wbDoneFold', { count: total, merged: mergedTotal })}</span>
        <span className="chives-sig-done-chevron" aria-hidden="true">{open ? '\u25b4' : '\u25be'}</span>
      </button>
      {open ? (
        <div className="chives-sig-done-list">
          {signals.map((signal) => (
            <div className="chives-sig-done-row" key={signal.id} data-signal={signal.id}>
              <span className="chives-sig-time">{signalTime(signal)}</span>
              <span className={`chives-sig-type is-${signalTone(signal.kind)}`}>{signalKindLabel(signal.kind, signal.kindLabel)}</span>
              <span className="chives-sig-done-title">{signal.title}</span>
              <span className={`chives-sig-dir is-${directionMeta(signal.direction).tone}`}>
                {directionMeta(signal.direction).glyph} {directionMeta(signal.direction).label}
              </span>
              <button type="button" className="chives-sig-btn is-small" onClick={() => onReopen(signal)}>{t('wbReopen')}</button>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** Simplified merged timeline shown when the hub is not running. */
export interface RawAlertRow {
  key: string
  time: string
  object: string
  title: string
  status: string
}

export function RawAlerts({ t, rows, failed }: { t: Translate; rows: readonly RawAlertRow[]; failed: boolean }): ReactElement {
  return (
    <details className="chives-sig-raw">
      <summary>{t('wbRawAlerts')} <span className="chives-wb-meta">{rows.length}</span></summary>
      {rows.length === 0 ? <div className="chives-wb-empty">{failed ? t('wbRawAlertsFailed') : t('wbRawAlertsEmpty')}</div> : (
        <div className="chives-sig-raw-list">
          {rows.map((row) => (
            <div className="chives-sig-raw-row" key={row.key}>
              <span className="chives-sig-time">{row.time}</span>
              <span className="chives-sig-raw-object">{row.object || DASH}</span>
              <span className="chives-sig-raw-title">{row.title}</span>
              <span className="chives-wb-meta">{row.status}</span>
            </div>
          ))}
        </div>
      )}
    </details>
  )
}
