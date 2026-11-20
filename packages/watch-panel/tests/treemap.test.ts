import assert from 'node:assert/strict'
import { test } from 'node:test'
import { treemapLayout } from '../src/client/treemap.ts'

function area(tile: { w: number; h: number }): number {
  return tile.w * tile.h
}

function overlaps(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  const epsilon = 1e-6
  return a.x + a.w > b.x + epsilon && b.x + b.w > a.x + epsilon && a.y + a.h > b.y + epsilon && b.y + b.h > a.y + epsilon
}

test('treemapLayout returns nothing for empty input or empty canvas', () => {
  assert.deepEqual(treemapLayout([], 100, 100), [])
  assert.deepEqual(treemapLayout([{ key: 'a', value: 1 }], 0, 100), [])
  assert.deepEqual(treemapLayout([{ key: 'a', value: 1 }], 100, -1), [])
})

test('a single item fills the canvas', () => {
  const [tile] = treemapLayout([{ key: 'a', value: 3 }], 200, 100)
  assert.equal(tile!.x, 0)
  assert.equal(tile!.y, 0)
  assert.equal(tile!.w, 200)
  assert.equal(tile!.h, 100)
  assert.equal(area(tile!), 20000)
})

test('full tile areas sum to the canvas area', () => {
  const items = [
    { key: 'a', value: 10 }, { key: 'b', value: 20 }, { key: 'c', value: 30 },
    { key: 'd', value: 5 }, { key: 'e', value: 1 },
  ]
  const tiles = treemapLayout(items, 640, 360)
  const total = tiles.reduce((sum, tile) => sum + area(tile), 0)
  assert.ok(Math.abs(total - 640 * 360) < 1e-6, `area ${total}`)
})

test('tiles never overlap', () => {
  const items = Array.from({ length: 20 }, (_, index) => ({ key: `k${index}`, value: (index % 7) + 1 }))
  const tiles = treemapLayout(items, 500, 300)
  for (let left = 0; left < tiles.length; left += 1) {
    for (let right = left + 1; right < tiles.length; right += 1) {
      assert.equal(overlaps(tiles[left]!, tiles[right]!), false, `${left}/${right}`)
    }
  }
})

test('input order is preserved in the output', () => {
  const items = ['z', 'a', 'm', 'b'].map((key, index) => ({ key, value: index + 1 }))
  assert.deepEqual(treemapLayout(items, 300, 200).map((tile) => tile.key), ['z', 'a', 'm', 'b'])
})

test('areas are proportional to values', () => {
  const tiles = treemapLayout([{ key: 'a', value: 1 }, { key: 'b', value: 3 }], 400, 100)
  const a = tiles.find((tile) => tile.key === 'a')!
  const b = tiles.find((tile) => tile.key === 'b')!
  assert.ok(Math.abs(area(a) / area(b) - 1 / 3) < 1e-9)
})

test('a zero value gets a zero tile without disturbing the rest', () => {
  const tiles = treemapLayout([{ key: 'a', value: 0 }, { key: 'b', value: 10 }], 100, 100)
  assert.equal(tiles[0]!.w, 0)
  assert.equal(tiles[0]!.h, 0)
  assert.equal(tiles[1]!.w, 100)
  assert.equal(area(tiles[1]!), 10000)
})

test('all-zero values fall back to equal areas', () => {
  const tiles = treemapLayout([{ key: 'a', value: 0 }, { key: 'b', value: 0 }], 100, 100)
  assert.equal(tiles.length, 2)
  assert.ok(Math.abs(area(tiles[0]!) - 5000) < 1e-6)
  assert.ok(Math.abs(area(tiles[1]!) - 5000) < 1e-6)
})

test('negative and non-finite values are treated as zero', () => {
  const tiles = treemapLayout([{ key: 'a', value: -3 }, { key: 'b', value: Number.NaN }, { key: 'c', value: 5 }], 100, 100)
  assert.equal(tiles[0]!.w, 0)
  assert.equal(tiles[1]!.w, 0)
  assert.equal(area(tiles[2]!), 10000)
})

test('the painted rectangle is inset by half the gap on each side', () => {
  const [tile] = treemapLayout([{ key: 'a', value: 1 }], 100, 100, 4)
  assert.equal(tile!.ix, 2)
  assert.equal(tile!.iy, 2)
  assert.equal(tile!.iw, 96)
  assert.equal(tile!.ih, 96)
})

test('layout is deterministic', () => {
  const items = [{ key: 'a', value: 2 }, { key: 'b', value: 3 }, { key: 'c', value: 5 }]
  assert.deepEqual(treemapLayout(items, 320, 180), treemapLayout(items, 320, 180))
})
