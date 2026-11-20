/** Inline SVG/CSS charts: sparkline, sector treemap and drill-down trend line. */
import { useId, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import {
  DASH,
  UP_SYMBOL,
  DOWN_SYMBOL,
  HEAT_TIER_EDGES,
  divergingColor,
  heatFill,
  heatTier,
  tileFontScale,
  formatMoney,
  formatMove,
  type SectorRow,
  type SectorTrendPoint,
  type SparkPoint,
} from './market.ts'
import { miniPath } from './workbenchModel.ts'
import { MIN_TILE_SHARE, areaValue, treemapLayout, type AreaBasis } from './treemap.ts'

export interface SparklineProps {
  points: readonly SparkPoint[]
  width?: number
  height?: number
  label: string
  stale?: boolean
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** 2px line drawn left-to-right, with an end dot and a hover crosshair. */
export function Sparkline({ points, width = 132, height = 34, label, stale = false }: SparklineProps): ReactElement {
  const [hover, setHover] = useState<number | null>(null)
  const series = points.filter((point) => Number.isFinite(point.p))
  if (series.length < 2) {
    return <span className="chives-empty" aria-label={label}>{DASH}</span>
  }
  const values = series.map((point) => point.p)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pad = 4
  const usable = Math.max(1, height - pad * 2)
  const coords = series.map((point, index) => ({
    x: (index / (series.length - 1)) * width,
    y: pad + (1 - (point.p - min) / span) * usable,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
  const last = coords[coords.length - 1]!
  const active = hover === null ? null : coords[hover]

  const onMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (rect.width <= 0) return
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1)
    setHover(Math.round(ratio * (series.length - 1)))
  }

  return (
    <div
      className="chives-spark"
      style={{ width, height }}
      onPointerMove={onMove}
      onPointerLeave={() => setHover(null)}
      role="img"
      aria-label={label}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        <path className="chives-spark-path" d={path} pathLength={1} />
        {active ? (
          <>
            <line className="chives-spark-cross" x1={active.x} y1={0} x2={active.x} y2={height} />
            <circle className="chives-spark-cross" cx={active.x} cy={active.y} r={2.5} />
          </>
        ) : null}
        <circle className="chives-spark-dot" cx={last.x} cy={last.y} r={4} />
      </svg>
      {hover !== null && active ? (
        <span className="chives-spark-tip" style={{ left: `${(active.x / width) * 100}%` }}>
          {series[hover]!.p.toFixed(2)} {stale ? DASH : ''}
        </span>
      ) : null}
    </div>
  )
}

export interface IndexSparkProps {
  points: readonly SparkPoint[]
  kind: 'intraday' | 'daily' | null
  label: string
  dailyLabel: string
  /** Direction of the move; the line, area and end dot take its colour token. */
  side?: 'up' | 'down' | 'flat'
  width?: number
  height?: number
}

/**
 * Index-card sparkline: a 2px line over a gradient area that fades
 * out downwards, both in the move's direction colour, with a breathing end dot
 * and the contract's `spark_kind` caption. An empty series renders a dash.
 */
export function IndexSpark({ points, kind, label, dailyLabel, side = 'flat', width = 128, height = 32 }: IndexSparkProps): ReactElement {
  const gradientId = `chives-area-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const mini = miniPath(points, width, height, 3)
  if (!mini) return <span className="chives-wb-spark-empty" aria-label={label}>{DASH}</span>
  const area = `${mini.path} L${width} ${height} L0 ${height} Z`
  return (
    <span className={`chives-wb-spark is-${side}`} role="img" aria-label={`${label}${kind === 'daily' ? ` ${dailyLabel}` : ''}`}>
      {kind === 'daily' ? <span className="chives-wb-spark-kind">{dailyLabel}</span> : null}
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop className="chives-spark-stop-top" offset="0%" />
            <stop className="chives-spark-stop-bottom" offset="100%" />
          </linearGradient>
        </defs>
        <path className="chives-spark-area" d={area} fill={`url(#${gradientId})`} />
        <path className="chives-spark-path" d={mini.path} pathLength={1} />
        <circle className="chives-spark-dot" cx={mini.lastX} cy={mini.lastY} r={3.2} />
      </svg>
    </span>
  )
}

export interface SectorTreemapProps {
  rows: readonly SectorRow[]
  maxAbs: number
  selected: string | null
  smallLabel: string
  /** Area basis: `sqrt` (default, compressed turnover) or `equal`. */
  basis?: AreaBasis
  onSelect: (code: string) => void
}

/**
 * Area = sqrt(turnover) or equal, colour = signed change; refresh morphs tiles
 * in place. Every tile keeps its name (T100) and a minimum share so the
 * smallest sector still has room for it; the move/amount yield when they cannot
 * fit and remain in the hover tooltip.
 */
export function SectorTreemap({ rows, maxAbs, selected, smallLabel, basis = 'sqrt', onSelect }: SectorTreemapProps): ReactElement {
  const [hover, setHover] = useState<string | null>(null)
  const tiles = treemapLayout(
    rows.map((row) => ({ key: row.code, value: areaValue(row.amountYuan, basis) })),
    1000,
    600,
    2,
    { minShare: MIN_TILE_SHARE },
  )
  const byCode = new Map(rows.map((row) => [row.code, row]))
  const hovered = hover === null ? null : byCode.get(hover) ?? null
  const hoveredTile = hover === null ? null : tiles.find((tile) => tile.key === hover) ?? null
  return (
    <div className="chives-treemap" role="group" aria-label="\u7533\u4e07\u4e00\u7ea7\u677f\u5757\u70ed\u529b\u56fe">
      {tiles.map((tile) => {
        const row = byCode.get(tile.key)
        if (!row) return null
        const scale = tileFontScale(tile.w, tile.h)
        const style: CSSProperties & { viewTransitionName?: string } = {
          left: `${(tile.ix / 1000) * 100}%`,
          top: `${(tile.iy / 600) * 100}%`,
          width: `${(tile.iw / 1000) * 100}%`,
          height: `${(tile.ih / 600) * 100}%`,
          backgroundColor: divergingColor(row.changePct, maxAbs),
          viewTransitionName: `chives-sector-${row.code}`,
          ['--tile-fs' as string]: `${scale.cqw}cqw`,
        }
        return (
          <div
            key={row.code}
            className={`chives-tile${heatTier(row.changePct) >= 3 ? ' is-strong' : ''}${hover === row.code ? ' is-hover' : ''}${selected === row.code ? ' is-selected' : ''}${row.stale ? ' is-stale' : ''}`}
            style={style}
            title={row.asOf ?? undefined}
            onPointerEnter={() => setHover(row.code)}
            onPointerLeave={() => setHover(null)}
            onClick={() => onSelect(row.code)}
            onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect(row.code) }}
            role="button"
            tabIndex={0}
            aria-label={`${row.name} ${formatMove(row.changePct)}`}
          >
            <span className="chives-tile-name">{row.name}{row.small ? <span className="chives-tile-flag">{smallLabel}</span> : null}</span>
            {scale.showMove ? <span className="chives-tile-move">{formatMove(row.changePct)}</span> : null}
            {scale.showMove && scale.showAmount ? <span className="chives-tile-amount">{formatMoney(row.amountYuan)}</span> : null}
          </div>
        )
      })}
      {hovered && hoveredTile ? (
        <div
          className="chives-tooltip"
          style={{
            left: `${Math.min(72, ((hoveredTile.ix + hoveredTile.iw / 2) / 1000) * 100)}%`,
            top: `${Math.min(70, ((hoveredTile.iy + hoveredTile.ih) / 600) * 100)}%`,
          }}
        >
          <div className="chives-tooltip-title">{hovered.name} {formatMove(hovered.changePct)}</div>
          <div className="chives-tooltip-row"><span>{'\u6210\u4ea4\u989d'}</span><span>{formatMoney(hovered.amountYuan)}</span></div>
          {hovered.leaders.slice(0, 3).map((leader) => (
            <div className="chives-tooltip-row" key={leader.code}>
              <span>{leader.name || leader.code}</span>
              <span>{formatMove(leader.changePct)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export interface TrendLineProps {
  points: readonly SectorTrendPoint[]
  label: string
}

/** Intraday sector trend; the zero line is always drawn. */
export function TrendLine({ points, label }: TrendLineProps): ReactElement {
  const series = points.filter((point) => Number.isFinite(point.changePct))
  if (series.length < 2) {
    return <div className="chives-empty">{DASH}</div>
  }
  const values = series.map((point) => point.changePct)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const span = max - min || 1
  const coords = series.map((point, index) => ({
    x: (index / (series.length - 1)) * 100,
    y: 100 - ((point.changePct - min) / span) * 100,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
  const area = `${path} L100 100 L0 100 Z`
  const zeroY = 100 - ((0 - min) / span) * 100
  return (
    <svg className="chives-trend" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={label}>
      <line className="chives-spark-cross" x1={0} y1={zeroY} x2={100} y2={zeroY} />
      <path className="chives-trend-area" d={area} />
      <path className="chives-trend-path" d={path} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export const SPARK_GLYPHS = { up: UP_SYMBOL, down: DOWN_SYMBOL } as const

/** Heat legend: one swatch per tier, from the biggest fall to the biggest rise. */
export function HeatLegend({ label }: { label: string }): ReactElement {
  const edges = HEAT_TIER_EDGES
  const items: Array<{ tier: number; side: 'up' | 'down'; text: string }> = []
  for (let tier = edges.length; tier >= 1; tier -= 1) items.push({ tier, side: 'down', text: `\u2212${edges[tier - 1]}%` })
  items.push({ tier: 0, side: 'up', text: '0' })
  for (let tier = 1; tier <= edges.length; tier += 1) items.push({ tier, side: 'up', text: `+${edges[tier - 1]}%` })
  return (
    <div className="chives-heat-legend" role="img" aria-label={label}>
      {items.map((item) => (
        <span className="chives-heat-legend-item" key={`${item.side}-${item.tier}`}>
          <span className="chives-heat-swatch" style={{ backgroundColor: heatFill(item.tier, item.side) }} />
          <span className="chives-heat-legend-text">{item.text}</span>
        </span>
      ))}
    </div>
  )
}
