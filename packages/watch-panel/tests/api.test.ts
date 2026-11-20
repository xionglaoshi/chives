import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MARKET_SECTOR_MEMBERS_PATH,
  MARKET_SECTOR_PATH,
  sectorDetailPath,
  sectorMembersPath,
} from '../src/client/api.ts'

test('sector detail and members use the fixed query routes', () => {
  assert.equal(MARKET_SECTOR_PATH, '/api/market/sector')
  assert.equal(MARKET_SECTOR_MEMBERS_PATH, '/api/market/sector-members')
  assert.equal(sectorDetailPath('BK0433'), '/api/market/sector?code=BK0433')
  assert.equal(sectorMembersPath('BK0433'), '/api/market/sector-members?code=BK0433')
})

test('sector paths carry the code as one encoded query value, never a path segment', () => {
  const detail = sectorDetailPath('BK0433/../x')
  assert.equal(detail, '/api/market/sector?code=BK0433%2F..%2Fx')
  assert.equal(detail.includes('/api/market/sectors/'), false)
  assert.equal(new URL(detail, 'http://localhost').searchParams.getAll('code').length, 1)
  assert.equal(sectorMembersPath('BK 0433'), '/api/market/sector-members?code=BK%200433')
})
