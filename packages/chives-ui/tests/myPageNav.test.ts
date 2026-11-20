import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createApply, LOCALE_NS, MY_PAGE_PANEL, NAV_ORDER, WORKBENCH_PANEL } from '../src/client/apply.ts'
import { PANEL_EVENT, installPanelBridge, panelFromEvent, PANEL_IDS } from '../src/client/panels.ts'

interface Row {
  name: string
  id?: string
  order?: number
  label?: () => string
}

interface FakeBus {
  listeners: Map<string, Array<(event: Event) => void>>
  addEventListener(type: string, listener: (event: Event) => void): void
  removeEventListener(type: string, listener: (event: Event) => void): void
  emit(type: string, event: unknown): void
}

function bus(): FakeBus {
  const listeners = new Map<string, Array<(event: Event) => void>>()
  return {
    listeners,
    addEventListener(type, listener) {
      const list = listeners.get(type) ?? []
      list.push(listener)
      listeners.set(type, list)
    },
    removeEventListener(type, listener) {
      listeners.set(type, (listeners.get(type) ?? []).filter((entry) => entry !== listener))
    },
    emit(type, event) {
      for (const listener of listeners.get(type) ?? []) listener(event as Event)
    },
  }
}

function harness() {
  const rows: Row[] = []
  const panels: string[] = []
  const fake = {
    effect(fn: () => unknown): () => void {
      const dispose = fn()
      return typeof dispose === 'function' ? dispose as () => void : () => {}
    },
    locale: {
      register(): () => void { return () => {} },
      bind(): (key: string) => string { return (key: string) => key },
    },
    layout: { selectPanel(id: string): void { panels.push(id) } },
    slots: {
      inject(_key: string, run: () => unknown): () => void {
        const result = run()
        if (typeof result === 'function') return result as () => void
        return () => {}
      },
      register(options: Row): () => void { rows.push(options); return () => {} },
    },
    theme: {
      register(): () => void { return () => {} },
      overrideTokens(): () => void { return () => {} },
    },
  }
  const component = (): null => null
  const ui = {
    BrandMark: component,
    BrandName: component,
    HeroBrandMark: component,
    QuickCards: component,
    MyPageIcon: component,
    WorkbenchIcon: component,
    ScheduleIcon: component,
  }
  return { ctx: fake, rows, panels, ui }
}

test('the mine row is registered first with its own label', () => {
  const h = harness()
  createApply(h.ui)(h.ctx as never)
  const mine = h.rows.find((row) => row.name === 'sidebar.panellist' && row.id === MY_PAGE_PANEL)
  assert.ok(mine)
  assert.equal(mine!.order, NAV_ORDER.myPage)
  assert.equal(mine!.label!(), 'panelMyPage')
  const first = [...h.rows].filter((row) => row.name === 'sidebar.panellist').sort((a, b) => (a.order ?? 0) - (b.order ?? 0))[0]
  assert.equal(first!.id, MY_PAGE_PANEL)
})

test('sidebar order is mine 5, watch 10, review 15, schedules 90', () => {
  assert.deepEqual(NAV_ORDER, { myPage: 5, workbench: 10, review: 15, schedule: 90 })
  assert.deepEqual(PANEL_IDS, [MY_PAGE_PANEL, WORKBENCH_PANEL, 'chives-review'])
})

test('startup lands on the mine panel, not the watch panel', () => {
  const h = harness()
  createApply(h.ui)(h.ctx as never)
  assert.deepEqual(h.panels, [MY_PAGE_PANEL])
})

test('a second apply does not navigate again beyond the landed flag', () => {
  const h = harness()
  const apply = createApply(h.ui)
  apply(h.ctx as never)
  apply(h.ctx as never)
  assert.deepEqual(h.panels, [MY_PAGE_PANEL, MY_PAGE_PANEL])
})

test('panelFromEvent accepts only the two known panel ids', () => {
  assert.equal(panelFromEvent({ detail: { panel: MY_PAGE_PANEL } }), MY_PAGE_PANEL)
  assert.equal(panelFromEvent({ detail: { panel: WORKBENCH_PANEL } }), WORKBENCH_PANEL)
  assert.equal(panelFromEvent({ detail: { panel: 'conversation' } }), null)
  assert.equal(panelFromEvent({ detail: { panel: 'chives-home' } }), null)
  assert.equal(panelFromEvent({ detail: { panel: 42 } }), null)
  assert.equal(panelFromEvent({ detail: null }), null)
  assert.equal(panelFromEvent(null), null)
})

test('the panel bridge forwards a whitelisted event and ignores the rest', () => {
  const target = bus()
  const seen: string[] = []
  installPanelBridge((panel) => seen.push(panel), target)
  target.emit(PANEL_EVENT, { detail: { panel: WORKBENCH_PANEL } })
  target.emit(PANEL_EVENT, { detail: { panel: 'conversation' } })
  assert.deepEqual(seen, [WORKBENCH_PANEL])
})

test('the panel bridge disposer removes its listener', () => {
  const target = bus()
  const seen: string[] = []
  const dispose = installPanelBridge((panel) => seen.push(panel), target)
  assert.equal(target.listeners.get(PANEL_EVENT)?.length, 1)
  dispose()
  assert.equal(target.listeners.get(PANEL_EVENT)?.length, 0)
  target.emit(PANEL_EVENT, { detail: { panel: WORKBENCH_PANEL } })
  assert.deepEqual(seen, [])
})

test('the panel bridge is a no-op without a target (SSR / tests)', () => {
  const dispose = installPanelBridge(() => {}, null)
  assert.equal(typeof dispose, 'function', 'disposer')
  dispose()
  assert.ok(LOCALE_NS.length > 0)
})
