/**
 * Deterministic squarified treemap used by the sector heat map. Input order is
 * preserved in the output, tile areas (before the surface gap) sum to the
 * canvas area, and tiles never overlap.
 */

export interface TreemapItem {
  readonly key: string
  readonly value: number
}

/** Area basis for the industry map: sqrt(amount) compresses size gaps, equal ignores them. */
export type AreaBasis = 'sqrt' | 'equal'

/** Smallest share of the canvas a sector tile may occupy (T100: names must fit). */
export const MIN_TILE_SHARE = 0.012

/** Weight fed to the layout: sqrt(amount) keeps order while compressing extremes. */
export function areaValue(amount: number | null | undefined, basis: AreaBasis = 'sqrt'): number {
  if (typeof amount !== 'number' || !Number.isFinite(amount) || amount <= 0) return 0
  return basis === 'equal' ? 1 : Math.sqrt(amount)
}

/**
 * Raise tiny shares to `floor` and take the difference proportionally from the
 * shares above it; the result always sums to 1. A floor above a fair share is
 * capped at 90% of 1/n so the water-filling cannot loop forever.
 */
export function floorShares(shares: readonly number[], floor: number): number[] {
  const count = shares.length
  if (count === 0) return []
  const usable = shares.map((share) => (Number.isFinite(share) && share > 0 ? share : 0))
  const sum = usable.reduce((total, share) => total + share, 0)
  let normalized = sum > 0 ? usable.map((share) => share / sum) : usable.map(() => 1 / count)
  const target = Math.min(Math.max(0, floor), 0.9 / count)
  if (target <= 0) return normalized
  for (let round = 0; round < 24; round += 1) {
    const low = normalized.map((share) => share < target)
    if (!low.some(Boolean)) break
    const deficit = normalized.reduce((total, share, index) => total + (low[index] ? target - share : 0), 0)
    const high = normalized.reduce((total, share, index) => total + (low[index] ? 0 : share), 0)
    if (high <= 0) {
      normalized = normalized.map(() => 1 / count)
      break
    }
    normalized = normalized.map((share, index) => (low[index] ? target : share - (deficit * share) / high))
  }
  const total = normalized.reduce((acc, share) => acc + share, 0)
  return total > 0 ? normalized.map((share) => share / total) : normalized.map(() => 1 / count)
}

export interface TreemapOptions {
  readonly minShare?: number
}

export interface TreemapTile {
  readonly key: string
  /** Full tile rectangle in canvas units (includes the gap that is removed for painting). */
  readonly x: number
  readonly y: number
  readonly w: number
  readonly h: number
  /** Painted rectangle: the full tile inset by half the gap on every side. */
  readonly ix: number
  readonly iy: number
  readonly iw: number
  readonly ih: number
}

interface Box {
  x: number
  y: number
  w: number
  h: number
}

interface RawTile {
  index: number
  x: number
  y: number
  w: number
  h: number
}

function worst(row: readonly number[], side: number): number {
  let sum = 0
  let max = 0
  let min = Number.POSITIVE_INFINITY
  for (const area of row) {
    sum += area
    if (area > max) max = area
    if (area < min) min = area
  }
  if (sum <= 0 || min <= 0 || side <= 0) return Number.POSITIVE_INFINITY
  return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min))
}

function layoutRow(row: readonly { index: number; area: number }[], box: Box, output: RawTile[]): Box {
  const rowArea = row.reduce((sum, item) => sum + item.area, 0)
  if (rowArea <= 0) return box
  if (box.w >= box.h) {
    const stripW = Math.min(box.w, rowArea / box.h)
    let y = box.y
    for (let index = 0; index < row.length; index += 1) {
      const item = row[index]!
      const height = index === row.length - 1 ? box.y + box.h - y : item.area / stripW
      output.push({ index: item.index, x: box.x, y, w: stripW, h: Math.max(0, height) })
      y += height
    }
    return { x: box.x + stripW, y: box.y, w: Math.max(0, box.w - stripW), h: box.h }
  }
  const stripH = Math.min(box.h, rowArea / box.w)
  let x = box.x
  for (let index = 0; index < row.length; index += 1) {
    const item = row[index]!
    const width = index === row.length - 1 ? box.x + box.w - x : item.area / stripH
    output.push({ index: item.index, x, y: box.y, w: Math.max(0, width), h: stripH })
    x += width
  }
  return { x: box.x, y: box.y + stripH, w: box.w, h: Math.max(0, box.h - stripH) }
}

/**
 * Lay items out over `width × height`. Non-positive values share the canvas
 * equally; an all-zero input falls back to equal areas so the view still shows
 * every sector.
 */
export function treemapLayout(
  items: readonly TreemapItem[],
  width: number,
  height: number,
  gap = 2,
  options: TreemapOptions = {},
): TreemapTile[] {
  if (items.length === 0 || width <= 0 || height <= 0) return []
  const total = width * height
  const values = items.map((item) => (Number.isFinite(item.value) && item.value > 0 ? item.value : 0))
  const sum = values.reduce((acc, value) => acc + value, 0)
  const minShare = options.minShare ?? 0
  const shares = sum > 0
    ? values.map((value) => value / sum)
    : values.map(() => 1 / values.length)
  const areas = (minShare > 0 ? floorShares(shares, minShare) : shares).map((share) => share * total)

  const positives = areas
    .map((area, index) => ({ area, index }))
    .filter((entry) => entry.area > 0)
  const raw: RawTile[] = []
  let box: Box = { x: 0, y: 0, w: width, h: height }
  let cursor = 0
  while (cursor < positives.length) {
    const side = Math.min(box.w, box.h)
    if (side <= 0) break
    const row: { index: number; area: number }[] = []
    let best = Number.POSITIVE_INFINITY
    while (cursor < positives.length) {
      const candidate = positives[cursor]!
      const next = [...row, candidate]
      const score = worst(next.map((entry) => entry.area), side)
      if (row.length > 0 && score > best) break
      row.push(candidate)
      best = score
      cursor += 1
    }
    box = layoutRow(row, box, raw)
  }

  const half = Math.max(0, gap) / 2
  const byIndex = new Map<number, RawTile>()
  for (const tile of raw) byIndex.set(tile.index, tile)
  return items.map((item, index) => {
    const tile = byIndex.get(index) ?? { index, x: 0, y: 0, w: 0, h: 0 }
    return {
      key: item.key,
      x: tile.x,
      y: tile.y,
      w: tile.w,
      h: tile.h,
      ix: tile.x + half,
      iy: tile.y + half,
      iw: Math.max(0, tile.w - gap),
      ih: Math.max(0, tile.h - gap),
    }
  })
}
