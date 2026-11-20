import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  alertAnalysisMarker,
  alertNameById,
  analysisBadge,
  analysisByAlert,
  describeSkipReason,
  mergeAnalyses,
  ruleLabel,
  shouldFetchAnalysis,
  sortAnalyses,
} from '../src/client/viewModel.ts'
import { en, zh } from '../src/client/locales.ts'

test('analysisBadge accepts the four statuses and falls back to unknown', () => {
  for (const status of ['done', 'failed', 'timeout', 'skipped'] as const) {
    assert.equal(analysisBadge({ status }), status)
  }
  assert.equal(analysisBadge({ status: 'weird' }), 'unknown')
  assert.equal(analysisBadge({}), 'unknown')
  assert.equal(analysisBadge(null), 'unknown')
  assert.equal(analysisBadge(undefined), 'unknown')
})

test('describeSkipReason maps every reason and passes unknown strings through', () => {
  assert.equal(describeSkipReason('not_selected'), '未选中的规则')
  assert.equal(describeSkipReason('cooldown'), '冷却中')
  assert.equal(describeSkipReason('daily_limit'), '已达当日上限')
  assert.equal(describeSkipReason('stale_alert'), '告警已过期')
  assert.equal(describeSkipReason('queue_overflow'), '队列已满')
  assert.equal(describeSkipReason('kill_switch'), '熔断中')
  assert.equal(describeSkipReason('dry_run'), '干跑')
  assert.equal(describeSkipReason('something_new'), 'something_new')
  assert.equal(describeSkipReason(''), '')
  assert.equal(describeSkipReason(null), '')
  assert.equal(describeSkipReason(undefined), '')
})

test('sortAnalyses sorts descending without mutating the input', () => {
  const input = [{ alert_id: 2 }, { alert_id: 5 }, { alert_id: 3 }]
  assert.deepEqual(sortAnalyses(input).map((row) => row.alert_id), [5, 3, 2])
  assert.deepEqual(input.map((row) => row.alert_id), [2, 5, 3])
  assert.deepEqual(sortAnalyses(null), [])
})

test('mergeAnalyses dedupes by alert_id, incoming wins and the cap keeps the newest', () => {
  const merged = mergeAnalyses(
    [{ alert_id: 1, status: 'skipped' }, { alert_id: 2, status: 'done' }],
    [{ alert_id: 1, status: 'done' }, { alert_id: 3, status: 'failed' }],
    2,
  )
  assert.deepEqual(merged.map((row) => row.alert_id), [3, 2])
  assert.equal(merged[1]?.status, 'done')
  const replaced = mergeAnalyses([{ alert_id: 1, status: 'skipped' }], [{ alert_id: 1, status: 'done' }])
  assert.equal(replaced.length, 1)
  assert.equal(replaced[0]?.status, 'done')
  const big = mergeAnalyses([], Array.from({ length: 250 }, (_, index) => ({ alert_id: index + 1 })))
  assert.equal(big.length, 200)
  assert.equal(big[0]?.alert_id, 250)
  assert.equal(big[199]?.alert_id, 51)
})

test('alertAnalysisMarker marks only genuinely finished analyses', () => {
  assert.equal(alertAnalysisMarker({ status: 'done' }), 'analyzed')
  assert.equal(alertAnalysisMarker({ status: 'failed' }), 'failed')
  assert.equal(alertAnalysisMarker({ status: 'timeout' }), 'failed')
  assert.equal(alertAnalysisMarker({ status: 'skipped', reason: 'cooldown' }), null)
  assert.equal(alertAnalysisMarker({ status: 'skipped' }), null)
  assert.equal(alertAnalysisMarker({ status: 'weird' }), null)
  assert.equal(alertAnalysisMarker({}), null)
  assert.equal(alertAnalysisMarker(null), null)
  assert.equal(alertAnalysisMarker(undefined), null)
})

test('en and zh locale key sets stay identical', () => {
  assert.deepEqual(Object.keys(en).sort(), Object.keys(zh).sort())
})

test('analysisByAlert keeps one plain-object entry per alert, later records win', () => {
  const index = analysisByAlert([
    { alert_id: 4, status: 'skipped' },
    { alert_id: 7, status: 'done' },
    { alert_id: 4, status: 'done' },
  ])
  assert.deepEqual(Object.keys(index).sort(), ['4', '7'])
  assert.equal(index[4]?.status, 'done')
  assert.equal(index[7]?.status, 'done')
  assert.deepEqual(analysisByAlert(undefined), {})
})

test('alertNameById maps alert ids to names and drops malformed entries', () => {
  const index = alertNameById([
    { id: 3, name: '南方精工' },
    { id: 4, name: '贵州茅台' },
    { id: 5, name: '旧名字' },
    { id: 5, name: '新名字' },
  ])
  assert.deepEqual(index, { 3: '南方精工', 4: '贵州茅台', 5: '新名字' })
  assert.equal(index[99], undefined)
  assert.deepEqual(alertNameById([
    { id: 1 },
    { id: 2, name: '' },
    { id: 3, name: 42 },
    { id: Number.NaN, name: '坏 id' },
    { id: Number.POSITIVE_INFINITY, name: '坏 id' },
    { name: '没有 id' },
  ]), {})
  assert.deepEqual(alertNameById(null), {})
  assert.deepEqual(alertNameById(undefined), {})
})

test('shouldFetchAnalysis never requests the analysis file for a skipped row', () => {
  assert.equal(shouldFetchAnalysis({ status: 'skipped', reason: 'dry_run' }), false)
  assert.equal(shouldFetchAnalysis({ status: 'skipped' }), false)
  assert.equal(shouldFetchAnalysis({ status: 'done' }), true)
  assert.equal(shouldFetchAnalysis({ status: 'failed' }), true)
  assert.equal(shouldFetchAnalysis({ status: 'timeout' }), true)
  assert.equal(shouldFetchAnalysis({ status: 'weird' }), true)
  assert.equal(shouldFetchAnalysis({}), true)
  assert.equal(shouldFetchAnalysis(null), true)
  assert.equal(shouldFetchAnalysis(undefined), true)
})

test('ruleLabel uses the same description as the alert list and falls back to the raw id', () => {
  const ruleById = new Map([
    ['surge_3x', { id: 'surge_3x', type: 'volume_surge', window_seconds: 60, multiple: 3 }],
    ['pct_up_3', { id: 'pct_up_3', type: 'pct_change', direction: 'up', threshold_pct: 3 }],
    ['unknown_type', { id: 'unknown_type' }],
  ])
  assert.equal(ruleLabel('surge_3x', ruleById), '60 秒放量 ≥ 3 倍')
  assert.equal(ruleLabel('pct_up_3', ruleById), '涨幅 ≥ 3%')
  assert.equal(ruleLabel('deleted_rule', ruleById), 'deleted_rule')
  assert.equal(ruleLabel('unknown_type', ruleById), 'unknown_type')
  assert.equal(ruleLabel('constructor', ruleById), 'constructor')
})

test('ruleLabel accepts a plain object index and handles missing ids', () => {
  const ruleById = { cross_16: { id: 'cross_16', type: 'price_cross', level: 16, direction: 'up' } }
  assert.equal(ruleLabel('cross_16', ruleById), '上穿 16.00')
  assert.equal(ruleLabel('toString', ruleById), 'toString')
  assert.equal(ruleLabel('cross_16', null), 'cross_16')
  assert.equal(ruleLabel('cross_16', undefined), 'cross_16')
  assert.equal(ruleLabel('', ruleById), '\u2014')
  assert.equal(ruleLabel(null, ruleById), '\u2014')
  assert.equal(ruleLabel(undefined, ruleById), '\u2014')
  assert.equal(ruleLabel(42, ruleById), '\u2014')
})
