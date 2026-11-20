import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { loadClientModule } from './tsx.ts'

type Component = (props: never) => ReactElement
const icons = await loadClientModule('icons.tsx')
const WorkbenchIcon = icons.WorkbenchIcon as Component
const ScheduleIcon = icons.ScheduleIcon as Component

const render = (component: Component): string => renderToStaticMarkup(
  createElement(component, { size: 18 } as never),
)

test('the workbench row keeps the Chives mark', () => {
  assert.match(render(WorkbenchIcon), /aria-label="Chives"/)
})

test('the watch glyph is gone with the removed watch row', () => {
  assert.equal(icons.WatchIcon, undefined)
  assert.equal(icons.HomeIcon, undefined)
})

test('the schedule row keeps the clock glyph', () => {
  assert.match(render(ScheduleIcon), /cx="12" cy="12" r="8.5"/)
})

test('the workbench and schedule rows do not share an icon', () => {
  assert.notEqual(render(WorkbenchIcon), render(ScheduleIcon))
})

const MyPageIcon = icons.MyPageIcon as Component

test('the mine row uses a wallet outline distinct from the brand mark and clock', () => {
  const mine = render(MyPageIcon)
  assert.match(mine, /<rect/)
  assert.notEqual(mine, render(WorkbenchIcon))
  assert.notEqual(mine, render(ScheduleIcon))
})
