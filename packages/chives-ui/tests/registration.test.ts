import assert from 'node:assert/strict'
import test from 'node:test'
import type { Context } from '@deepseek-ai/cordis'
import { createApply, LOCALE_NS, MY_PAGE_PANEL, NAV_ORDER, RELABELLED_PANELS, SHADOW_PRIORITY, WORKBENCH_PANEL } from '../src/client/apply.ts'

interface BlockCall {
  name: string
  id?: string
  key?: string
  order?: number
  priority?: number
  locale?: string
  label?: () => string
}

interface ThemeCall {
  id: string
  colorScheme: string
  tokenCount: number
}

interface Harness {
  ctx: Context
  blocks: BlockCall[]
  themes: ThemeCall[]
  overrides: { source: string; tokens: Record<string, { light: string; dark: string }> }[]
  localeRegistrations: string[]
  panels: string[]
}

function harness(): Harness {
  const blocks: BlockCall[] = []
  const themes: ThemeCall[] = []
  const overrides: Harness['overrides'] = []
  const localeRegistrations: string[] = []
  const panels: string[] = []

  const fake = {
    effect(fn: () => unknown): () => void {
      const dispose = fn()
      return typeof dispose === 'function' ? dispose as () => void : () => {}
    },
    locale: {
      register(ns: string, dictionaries: unknown): () => void {
        assert.ok(dictionaries !== undefined)
        localeRegistrations.push(ns)
        return () => {}
      },
      bind(): (key: string) => string {
        return (key: string) => key
      },
    },
    layout: {
      selectPanel(id: string): void { panels.push(id) },
    },
    slots: {
      inject(_key: string, run: () => unknown): () => void {
        const result = run()
        if (typeof result === 'function') return result as () => void
        if (result && typeof (result as Generator).next === 'function') {
          const generator = result as Generator
          let step = generator.next()
          while (!step.done) step = generator.next()
        }
        return () => {}
      },
      register(options: BlockCall, _component: unknown): () => void {
        blocks.push(options)
        return () => {}
      },
    },
    theme: {
      register(definition: { id: string; colorScheme: string; tokens: Record<string, string> }): () => void {
        themes.push({ id: definition.id, colorScheme: definition.colorScheme, tokenCount: Object.keys(definition.tokens).length })
        return () => {}
      },
      overrideTokens(source: string, tokens: Record<string, { light: string; dark: string }>): () => void {
        overrides.push({ source, tokens })
        return () => {}
      },
    },
    document: undefined,
  }

  const ctx = fake as unknown as Context
  return { ctx, blocks, themes, overrides, localeRegistrations, panels }
}

const component = (): null => null
const ui = {
  BrandMark: component,
  BrandName: component,
  HeroBrandMark: component,
  QuickCards: component,
  MyPage: component,
  MyPageIcon: component,
  WorkbenchIcon: component,
  ScheduleIcon: component,
}

test('apply registers the locale namespace and both theme schemes', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  assert.deepEqual(h.localeRegistrations, [LOCALE_NS])
  assert.deepEqual(h.themes.map(theme => theme.id), ['chives', 'chives-light'])
  assert.deepEqual(h.themes.map(theme => theme.colorScheme), ['dark', 'light'])
  assert.ok(h.themes.every(theme => theme.tokenCount >= 15))
})

test('apply stacks exactly one alias override layer', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  assert.equal(h.overrides.length, 1)
  assert.equal(h.overrides[0]!.source, 'chives-ui')
  assert.ok(Object.keys(h.overrides[0]!.tokens).length >= 15)
})

test('brand slots are registered as the declaration-aware pair below the shipped rank', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  for (const name of ['sidebar.brand.mark', 'sidebar.brand.name', 'conversation.hero.brand.mark']) {
    const block = h.blocks.find(candidate => candidate.name === name)
    assert.ok(block, name)
    assert.equal(block!.priority, SHADOW_PRIORITY, name)
  }
  assert.ok(SHADOW_PRIORITY < 0)
})

test('welcome cards register into the input dock with the chives locale', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const cards = h.blocks.find(block => block.name === 'conversation.input.dock')
  assert.ok(cards)
  assert.equal(cards!.id, 'chives-quick-start')
  assert.equal(cards!.locale, LOCALE_NS)
})

test('the mine row is first, then the workbench row with the chives mark icon', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const rows = h.blocks.filter(block => block.name === 'sidebar.panellist')
  const mine = rows.find(row => row.id === MY_PAGE_PANEL)
  const workbench = rows.find(row => row.id === WORKBENCH_PANEL)
  assert.ok(mine)
  assert.ok(workbench)
  assert.equal(mine!.order, NAV_ORDER.myPage)
  assert.equal(mine!.label!(), 'panelMyPage')
  assert.equal(workbench!.order, NAV_ORDER.workbench)
  assert.equal(workbench!.label!(), 'panelWorkbench')
  assert.equal(workbench!.priority, undefined)
  const ordered = [...rows].sort((left, right) => (left.order ?? 0) - (right.order ?? 0))
  assert.deepEqual(ordered.map(row => row.id), [MY_PAGE_PANEL, WORKBENCH_PANEL, 'schedules'])
})

test('chives-ui registers only the mine main block; watch-panel owns the workbench main', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const mains = h.blocks.filter(block => block.name === 'main')
  assert.equal(mains.length, 1)
  assert.equal(mains[0]!.key, MY_PAGE_PANEL)
})

test('there is no legacy watch/home row; the sidebar carries mine, watch and schedules', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const ids = h.blocks.filter(block => block.name === 'sidebar.panellist').map(block => block.id)
  assert.ok(!ids.includes('watch-panel'))
  assert.ok(!ids.includes('chives-home'))
  assert.deepEqual(ids.sort(), [MY_PAGE_PANEL, WORKBENCH_PANEL, 'schedules'].sort())
})

test('the schedule row shadows the shipped cell with the documented order', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const schedule = h.blocks.find(block => block.name === 'sidebar.panellist' && block.id === RELABELLED_PANELS.schedule)
  assert.ok(schedule)
  assert.equal(schedule!.order, NAV_ORDER.schedule)
  assert.equal(schedule!.priority, SHADOW_PRIORITY)
  assert.equal(typeof schedule!.label, 'function')
})

test('registration set is exactly the planned slots (no extras)', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const plan = [
    `main:${MY_PAGE_PANEL}`,
    'sidebar.brand.mark:',
    'sidebar.brand.name:',
    'conversation.hero.brand.mark:',
    'conversation.input.dock:chives-quick-start',
    `sidebar.panellist:${MY_PAGE_PANEL}`,
    `sidebar.panellist:${WORKBENCH_PANEL}`,
    'sidebar.panellist:schedules',
  ]
  const actual = h.blocks.map(block => `${block.name}:${block.id ?? block.key ?? ''}`)
  assert.deepEqual(actual.sort(), plan.sort())
})

test('startup navigates to the mine page exactly once', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  assert.deepEqual(h.panels, [MY_PAGE_PANEL])
})

test('a second apply does not hijack navigation again', () => {
  const h = harness()
  const apply = createApply(ui)
  apply(h.ctx)
  apply(h.ctx)
  assert.deepEqual(h.panels, [MY_PAGE_PANEL, MY_PAGE_PANEL])
})

test('nav order is mine, workbench, review, schedules', () => {
  assert.deepEqual(NAV_ORDER, { myPage: 5, workbench: 10, review: 15, schedule: 90 })
  assert.ok(NAV_ORDER.myPage < NAV_ORDER.workbench)
  assert.ok(NAV_ORDER.workbench < NAV_ORDER.review)
  assert.ok(NAV_ORDER.review < NAV_ORDER.schedule)
})

test('the shipped schedules row is shadowed once, with no extra schedule entry', () => {
  const h = harness()
  createApply(ui)(h.ctx)
  const ids = h.blocks.filter(block => block.name === 'sidebar.panellist').map(block => block.id)
  assert.equal(ids.filter(id => id === 'schedules').length, 1)
  assert.ok(!ids.includes('schedule'))
})

test('the review row and page register together, only when both components are provided', () => {
  const full = harness()
  createApply({ ...ui, ReviewPage: () => null, ReviewIcon: () => null } as never)(full.ctx)
  assert.ok(full.blocks.some(block => block.name === 'sidebar.panellist' && block.id === 'chives-review'))
  assert.ok(full.blocks.some(block => block.name === 'main' && block.key === 'chives-review'))
  const bare = harness()
  createApply(ui)(bare.ctx)
  assert.ok(!bare.blocks.some(block => block.id === 'chives-review' || block.key === 'chives-review'))
})
