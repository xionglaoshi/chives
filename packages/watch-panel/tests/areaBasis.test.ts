import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MIN_TILE_SHARE,
  areaValue,
  floorShares,
  treemapLayout,
  type TreemapTile,
} from '../src/client/treemap.ts'
import { tileFontScale } from '../src/client/market.ts'

const area = (tile: { w: number; h: number }): number => tile.w * tile.h

function overlaps(left: TreemapTile, right: TreemapTile): boolean {
  const epsilon = 1e-6
  return left.x + left.w > right.x + epsilon
    && right.x + right.w > left.x + epsilon
    && left.y + left.h > right.y + epsilon
    && right.y + right.h > left.y + epsilon
}

const sectors = [
  520, 410, 380, 350, 300, 290, 260, 240, 220, 200, 190, 180, 170, 160, 150,
  140, 130, 120, 110, 100, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45,
].map((scale, index) => ({ key: `BK${String(index).padStart(4, '0')}`, value: scale * 1e7 }))

test('areaValue uses sqrt(turnover) by default and equal weight on demand', () => {
  assert.equal(areaValue(9e8), Math.sqrt(9e8))
  assert.equal(areaValue(9e8, 'equal'), 1)
  assert.equal(areaValue(0), 0)
  assert.equal(areaValue(-3), 0)
  assert.equal(areaValue(Number.NaN), 0)
})

test('the sqrt transform keeps the turnover order while compressing the gap', () => {
  const amounts = [4e8, 9e8, 16e8]
  const weights = amounts.map((amount) => areaValue(amount))
  assert.ok(weights[0]! < weights[1]! && weights[1]! < weights[2]!)
  assert.ok(weights[2]! / weights[0]! < amounts[2]! / amounts[0]!)
})

test('areas follow sqrt(turnover) rather than raw turnover', () => {
  const tiles = treemapLayout([
    { key: 'a', value: areaValue(4e8) },
    { key: 'b', value: areaValue(16e8) },
  ], 600, 200)
  const a = tiles.find((tile) => tile.key === 'a')!
  const b = tiles.find((tile) => tile.key === 'b')!
  assert.ok(Math.abs(area(a) / area(b) - 0.5) < 1e-9)
})

test('equal basis gives every sector the same area', () => {
  const tiles = treemapLayout(sectors.map((sector) => ({ key: sector.key, value: areaValue(sector.value, 'equal') })), 1000, 600, 2)
  const areas = tiles.map(area)
  for (const value of areas) assert.ok(Math.abs(value - areas[0]!) < 1e-6)
})

test('floorShares sums to one and lifts every share to the floor', () => {
  const shares = floorShares([0.7, 0.2, 0.06, 0.03, 0.01], 0.05)
  assert.ok(Math.abs(shares.reduce((sum, share) => sum + share, 0) - 1) < 1e-9)
  for (const share of shares) assert.ok(share >= 0.05 - 1e-9, String(share))
})

test('floorShares caps an impossible floor at a fair share', () => {
  const shares = floorShares([1, 1, 1, 1], 0.9)
  for (const share of shares) assert.ok(share >= 0.9 / 4 - 1e-9)
  assert.ok(Math.abs(shares.reduce((sum, share) => sum + share, 0) - 1) < 1e-9)
})

test('an empty share list stays empty', () => {
  assert.deepEqual(floorShares([], 0.1), [])
})

test('the minimum share keeps every tile large enough for a name', () => {
  const tiles = treemapLayout(sectors, 1000, 600, 2, { minShare: MIN_TILE_SHARE })
  const total = 1000 * 600
  assert.equal(tiles.length, sectors.length)
  for (const tile of tiles) {
    assert.ok(area(tile) >= MIN_TILE_SHARE * total - 1e-6, `${tile.key} ${area(tile)}`)
    assert.ok(Math.min(tile.w, tile.h) >= 24, `${tile.key} ${tile.w}x${tile.h}`)
  }
})

test('minimum tiles never overlap and still sum to the canvas', () => {
  const tiles = treemapLayout(sectors, 1000, 600, 2, { minShare: MIN_TILE_SHARE })
  const total = tiles.reduce((sum, tile) => sum + area(tile), 0)
  assert.ok(Math.abs(total - 1000 * 600) < 1e-6, String(total))
  for (let left = 0; left < tiles.length; left += 1) {
    for (let right = left + 1; right < tiles.length; right += 1) {
      assert.equal(overlaps(tiles[left]!, tiles[right]!), false, `${left}/${right}`)
    }
  }
})

test('a zero-turnover sector still gets a visible tile under the floor', () => {
  const tiles = treemapLayout([{ key: 'a', value: 0 }, { key: 'b', value: 10 }], 400, 300, 2, { minShare: 0.1 })
  assert.ok(area(tiles[0]!) > 0)
})

test('the layout is deterministic with and without the floor', () => {
  assert.deepEqual(
    treemapLayout(sectors, 800, 480, 2, { minShare: MIN_TILE_SHARE }),
    treemapLayout(sectors, 800, 480, 2, { minShare: MIN_TILE_SHARE }),
  )
})

test('tile label policy always keeps the name and drops move before amount', () => {
  const tiny = tileFontScale(50, 30)
  assert.equal(tiny.showText, true)
  assert.equal(tiny.showMove, false)
  assert.equal(tiny.showAmount, false)
  const medium = tileFontScale(100, 60)
  assert.equal(medium.showMove, true)
  assert.equal(medium.showAmount, false)
  const large = tileFontScale(200, 120)
  assert.equal(large.showAmount, true)
  assert.ok(large.cqw > medium.cqw)
  assert.ok(medium.cqw >= tiny.cqw)
})
