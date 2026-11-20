/*! bundle id: "watch-panel" */
/** Client half: the watch page behind the authenticated Host proxy. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import { en, zh } from './locales.ts'
import { Workbench } from './workbench.tsx'
import { insertPanelStyles } from './styles.ts'

export const PANEL_ID = 'chives-workbench'
const NS = 'watchPanel'

export const inject = ['slots', 'locale']
export function apply(ctx: Context): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'watch-panel: dictionaries')
  ctx.effect(() => insertPanelStyles(), 'watch-panel: component styles')
  ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: PANEL_ID, locale: NS }, (props) => <Workbench t={props.t} />))
}
