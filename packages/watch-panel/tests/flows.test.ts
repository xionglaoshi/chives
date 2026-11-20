import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DEFAULT_FLOW_FILTERS,
  FLOW_DEFINITION,
  flowAmount,
  flowChange,
  flowColumns,
  flowGlyph,
  flowRows,
  flowSide,
  flowsPath,
  flowsProblem,
  flowsQuery,
  isFlowKind,
  northboundText,
  northboundVisible,
  normalizeFlows,
  normalizeFlowRow,
  normalizeNorthbound,
} from '../src/client/flows.ts'

test('normalizeFlows reads the v1.3 flow payload', () => {
  const payload = normalizeFlows({
    ok: true,
    as_of: '2026-11-03T15:00:00+08:00',
    kind: 'stock_in',
    definition: '东财主力口径',
    source: 'eastmoney',
    stale: true,
    state_note: '休市',
    rows: [{ rank: 1, code: '600000', name: '浦发银行', main_net_yuan: 1.5e8, main_net_pct: 1.1, change_pct: 3.2, amount_yuan: 1.2e9 }],
  })
  assert.equal(payload.kind, 'stock_in')
  assert.equal(payload.stale, true)
  assert.equal(payload.stateNote, '休市')
  assert.equal(payload.rows[0]!.mainNetYuan, 1.5e8)
  assert.equal(payload.definition, '东财主力口径')
})

test('normalizeFlows falls back to the given column and the vendor note', () => {
  const payload = normalizeFlows({ ok: false, error: { code: 'no_source' } }, 'sector_out')
  assert.equal(payload.kind, 'sector_out')
  assert.equal(payload.ok, false)
  assert.equal(payload.error, 'no_source')
  assert.equal(payload.definition, FLOW_DEFINITION)
  assert.deepEqual(payload.rows, [])
})

test('flow rows drop entries without a code and keep the rest', () => {
  const row = normalizeFlowRow({ code: '', name: 'x' })
  assert.equal(row.code, '')
  const payload = normalizeFlows({ rows: [{ code: '' }, { code: '600000' }] })
  assert.equal(payload.rows.length, 1)
})

test('flow queries clamp the limit into 5-20 and always emit the three flags', () => {
  assert.equal(flowsQuery('sector_in', DEFAULT_FLOW_FILTERS, 8), 'kind=sector_in&limit=8&include_st=0&include_new=0&include_bj=0')
  assert.equal(flowsQuery('stock_out', { includeSt: true, includeNew: false, includeBj: true }, 1), 'kind=stock_out&limit=5&include_st=1&include_new=0&include_bj=1')
  assert.equal(flowsQuery('stock_in', DEFAULT_FLOW_FILTERS, 99), 'kind=stock_in&limit=20&include_st=0&include_new=0&include_bj=0')
})

test('an unknown flow kind falls back to the sector inflow column', () => {
  assert.equal(flowsQuery('bogus' as never), 'kind=sector_in&limit=8&include_st=0&include_new=0&include_bj=0')
})

test('flowsPath points at the authenticated host route', () => {
  assert.match(flowsPath('sector_out'), /^\/api\/market\/flows\?kind=sector_out&limit=8/)
})

test('three columns by default and the stock-outflow column only with "更多"', () => {
  assert.deepEqual(flowColumns(false), ['sector_in', 'sector_out', 'stock_in'])
  assert.deepEqual(flowColumns(true), ['sector_in', 'sector_out', 'stock_in', 'stock_out'])
})

test('flow direction follows the sign and never relies on colour alone', () => {
  assert.equal(flowSide(1), 'up')
  assert.equal(flowSide(-1), 'down')
  assert.equal(flowSide(0), 'flat')
  assert.equal(flowSide(null), 'flat')
  assert.equal(flowGlyph(1.2e8), '▲')
  assert.equal(flowGlyph(-1.2e8), '▼')
  assert.equal(flowGlyph(0), '—')
})

test('amounts are always 亿元 with two decimals and an absolute value', () => {
  assert.equal(flowAmount(3.2e8), '3.20 亿元')
  assert.equal(flowAmount(-3.2e8), '3.20 亿元')
  assert.equal(flowAmount(1_500), '0.00 亿元')
  assert.equal(flowAmount(null), '—')
  assert.equal(flowChange(1.234), '▲ +1.23%')
})

test('northbound is shown only for an available finite source', () => {
  assert.equal(northboundVisible({ ok: true, available: true, reason: null, asOf: null, netYuan: 5.6e9 }), true)
  assert.equal(northboundVisible({ ok: true, available: false, reason: 'no source', asOf: null, netYuan: null }), false)
  assert.equal(northboundVisible({ ok: true, available: true, reason: null, asOf: null, netYuan: null }), false)
  assert.equal(northboundVisible({ ok: false, available: true, reason: null, asOf: null, netYuan: 1 }), false)
  assert.equal(northboundVisible(null), false)
})

test('northbound text carries a direction glyph and the amount', () => {
  assert.equal(northboundText({ ok: true, available: true, reason: null, asOf: null, netYuan: 5.6e9 }), '北向净流入 ▲ 56.00 亿元')
  assert.equal(northboundText({ ok: true, available: false, reason: null, asOf: null, netYuan: null }), null)
})

test('normalizeNorthbound keeps a reason when the source is unavailable', () => {
  const payload = normalizeNorthbound({ ok: true, available: false, reason: 'no free intraday source' })
  assert.equal(payload.available, false)
  assert.equal(payload.reason, 'no free intraday source')
  assert.equal(payload.netYuan, null)
})

test('flowsProblem reports failures, staleness and upstream reasons', () => {
  assert.equal(flowsProblem(null, true), '资金流向数据不可用')
  assert.equal(flowsProblem(null, false), null)
  assert.match(flowsProblem({ ok: true, error: null, asOf: null, kind: 'sector_in', rows: [], definition: '', source: null, stale: true, stateNote: null, reason: null }, false)!, /数据陈旧/)
  assert.equal(flowsProblem({ ok: true, error: null, asOf: null, kind: 'sector_in', rows: [], definition: '', source: null, stale: false, stateNote: null, reason: 'no source' }, false), 'no source')
})

test('flowRows caps a column at the configured limit', () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({ rank: index + 1, code: `60000${index}`, name: 'x', mainNetYuan: 1, mainNetPct: null, changePct: null, amountYuan: null }))
  const payload = { ok: true, error: null, asOf: null, kind: 'stock_in' as const, rows, definition: '', source: null, stale: false, stateNote: null, reason: null }
  assert.equal(flowRows(payload).length, 8)
  assert.equal(flowRows(payload, 20).length, 12)
  assert.equal(flowRows(null).length, 0)
})

test('isFlowKind accepts exactly the four contract kinds', () => {
  for (const kind of ['sector_in', 'sector_out', 'stock_in', 'stock_out']) assert.equal(isFlowKind(kind), true, kind)
  for (const kind of ['sector', 'stock', '', null]) assert.equal(isFlowKind(kind), false, String(kind))
})
