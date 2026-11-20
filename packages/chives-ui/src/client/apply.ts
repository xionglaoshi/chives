/**
 * Registration body shared by the shipped entry and the unit tests. Components
 * are injected by `index.tsx` so this module stays free of JSX and can run
 * under `node --test` type stripping.
 *
 * Slots and the theme service are reached through small structural ports: the
 * package intentionally keeps watch-panel's pinned dependency set, which does
 * not include `@deepseek-ai/dsh-client-ui-theme` or `dsh-client-ui-conversation`.
 */
import { installDocumentBrand } from './documentBrand.ts'
import type { Context } from '@deepseek-ai/cordis'
import type { ComponentType } from 'react'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import { installAskListener, requestDraft } from './draftBridge.ts'
import { en, zh, type ChivesKey } from './locales.ts'
import { MY_PAGE_PANEL, REVIEW_PANEL, WORKBENCH_PANEL, installPanelBridge } from './panels.ts'
import { insertChivesStyles } from './styles.ts'
import {
  OVERRIDE_SOURCE,
  THEME_DARK_ID,
  THEME_LIGHT_ID,
  aliasTokenPairs,
  aliasTokens,
  chivesTokenCss,
} from './tokens.ts'

/** Locale namespace and the dictionary file that owns it. */
export const LOCALE_NS = 'chives'
/**
 * Panel keys. Both `main` blocks are registered by `watch-panel` (it owns the
 * view models and polling); this package owns the sidebar rows and their icons,
 * so the ids must match exactly.
 */
export { MY_PAGE_PANEL, REVIEW_PANEL, WORKBENCH_PANEL }
/** Sidebar order: "mine" first, then the watch page, then scheduled tasks. */
export const NAV_ORDER = { myPage: 5, workbench: 10, review: 15, schedule: 90 } as const
/** Existing dsh rows whose sidebar cell Chives relabels (their main panels stay theirs). */
export const RELABELLED_PANELS = { schedule: 'schedules' } as const
/**
 * Rank for entries that shadow a shipped cell. A list cell admits one entry per
 * priority and the lowest rank renders, so relabelling `schedules` must register
 * below the shipped rank 0; the same rank would throw instead of replacing the row.
 */
export const SHADOW_PRIORITY = -10

export interface UiComponents {
  BrandMark: ComponentType<any>
  BrandName: ComponentType<any>
  HeroBrandMark: ComponentType<any>
  QuickCards: ComponentType<any>
  MyPage: ComponentType<any>
  MyPageIcon: ComponentType<any>
  /** Optional so older component sets (tests) still apply; the review row and page register only when present. */
  ReviewPage?: ComponentType<any>
  ReviewIcon?: ComponentType<any>
  WorkbenchIcon: ComponentType<any>
  ScheduleIcon: ComponentType<any>
}

type Disposer = () => void

interface SlotsPort {
  inject(key: string, run: () => Disposer | Generator<Disposer, void, unknown>): Disposer
  register(options: Record<string, unknown>, component: ComponentType<any>): Disposer
}

interface ThemePort {
  register(definition: { id: string; colorScheme: 'light' | 'dark'; tokens: Record<string, string> }): Disposer
  overrideTokens(source: string, tokens: Record<string, { light: string; dark: string }>): Disposer
}

/** Build the plugin `apply` around a concrete component set. */
export function createApply(ui: UiComponents): (ctx: Context) => void {
  return function apply(ctx: Context): void {
    const slots = (ctx as unknown as { slots: SlotsPort }).slots
    const theme = (ctx as unknown as { theme: ThemePort }).theme
    const t = ctx.locale.bind(LOCALE_NS) as (key: ChivesKey) => string

    ctx.effect(() => ctx.locale.register(LOCALE_NS, { zh, en }), 'chives-ui: dictionaries')
    // The watch panel has no input actions of its own; it emits `chives:ask` so
    // the shell can open the conversation and leave a pending draft.
    ctx.effect(() => installAskListener((text, persist) => {
      if (persist) requestDraft(text)
      else requestDraft(text, null)
      try {
        ctx.layout.selectPanel('conversation' as Parameters<typeof ctx.layout.selectPanel>[0])
      } catch {
        // The conversation panel may be unavailable in a trimmed profile.
      }
    }), 'chives-ui: ask bridge')
    // `chives:panel` lets the pages switch between the two `main` blocks without
    // depending on the layout service themselves.
    ctx.effect(() => installPanelBridge((panel) => {
      try {
        ctx.layout.selectPanel(panel as Parameters<typeof ctx.layout.selectPanel>[0])
      } catch {
        // The target panel may not be registered in a trimmed profile.
      }
    }), 'chives-ui: panel bridge')
    ctx.effect(() => insertChivesStyles(chivesTokenCss()), 'chives-ui: token + component styles')
    ctx.effect(() => installDocumentBrand(), 'chives-ui: tab title + icon')
    ctx.effect(() => theme.register({
      id: THEME_DARK_ID,
      colorScheme: 'dark',
      tokens: aliasTokens('dark'),
    }), 'chives-ui: dark theme')
    ctx.effect(() => theme.register({
      id: THEME_LIGHT_ID,
      colorScheme: 'light',
      tokens: aliasTokens('light'),
    }), 'chives-ui: light theme')
    // Apply the palette over whatever scheme the user picked, without writing
    // the user's theme preference (the Host half never touches settings).
    ctx.effect(() => theme.overrideTokens(OVERRIDE_SOURCE, aliasTokenPairs()), 'chives-ui: alias override layer')

    slots.inject('sidebar.brand.mark', () => slots.inject('sidebar.brand.name', function* () {
      // ui-brand-official holds both single cells at rank 0 on official builds;
      // a second rank-0 registration throws, while a lower rank shadows it.
      yield slots.register({ name: 'sidebar.brand.mark', priority: SHADOW_PRIORITY }, ui.BrandMark)
      yield slots.register({ name: 'sidebar.brand.name', priority: SHADOW_PRIORITY }, ui.BrandName)
    }))

    slots.inject('conversation.hero.brand.mark', () =>
      slots.register({ name: 'conversation.hero.brand.mark', priority: SHADOW_PRIORITY }, ui.HeroBrandMark))

    slots.inject('conversation.input.dock', () => slots.register({
      name: 'conversation.input.dock',
      id: 'chives-quick-start',
      order: 20,
      locale: LOCALE_NS,
    }, ui.QuickCards))

    // The "mine" row is the first panel row (after the built-in new-session
    // row); the watch row follows it. Both panel keys are owned by watch-panel,
    // so this package never registers a `main` block for them.
    slots.inject('sidebar.panellist', () => slots.register({
      name: 'sidebar.panellist',
      id: MY_PAGE_PANEL,
      order: NAV_ORDER.myPage,
      label: () => t('panelMyPage'),
      locale: LOCALE_NS,
    }, ui.MyPageIcon))

    slots.inject('sidebar.panellist', () => slots.register({
      name: 'sidebar.panellist',
      id: WORKBENCH_PANEL,
      order: NAV_ORDER.workbench,
      label: () => t('panelWorkbench'),
      locale: LOCALE_NS,
    }, ui.WorkbenchIcon))

    if (ui.ReviewIcon && ui.ReviewPage) {
      const ReviewIcon = ui.ReviewIcon
      const ReviewPage = ui.ReviewPage
      slots.inject('sidebar.panellist', () => slots.register({
        name: 'sidebar.panellist',
        id: REVIEW_PANEL,
        order: NAV_ORDER.review,
        label: () => t('panelReview'),
        locale: LOCALE_NS,
      }, ReviewIcon))
      slots.inject('main', () => slots.register({
        name: 'main',
        key: REVIEW_PANEL,
        locale: LOCALE_NS,
      }, ReviewPage))
    }

    slots.inject('sidebar.panellist', () => slots.register({
      name: 'sidebar.panellist',
      id: RELABELLED_PANELS.schedule,
      order: NAV_ORDER.schedule,
      priority: SHADOW_PRIORITY,
      label: () => t('panelSchedule'),
      locale: LOCALE_NS,
    }, ui.ScheduleIcon))

    // The "mine" page owns its market/account view model, but the shell package
    // registers the `main` block because watch-panel's client bundle is kept
    // below the legacy size budget (the Host proxy still lives in watch-panel).
    slots.inject('main', () => slots.register({
      name: 'main',
      key: MY_PAGE_PANEL,
      locale: LOCALE_NS,
    }, ui.MyPage))

    let landed = false
    const selectMyPage = (): boolean => {
      try {
        // Official layout navigation; the store starts at `null` (Conversation),
        // so this is the one non-invasive way to land on "mine" at startup.
        ctx.layout.selectPanel(MY_PAGE_PANEL as Parameters<typeof ctx.layout.selectPanel>[0])
        return true
      } catch {
        return false
      }
    }
    // watch-panel registers the `main` blocks. This side only lands the layout on
    // "mine"; the registry may not know the key yet, so retry briefly.
    slots.inject('main', () => {
      if (landed) return () => {}
      landed = true
      if (!selectMyPage() && typeof window !== 'undefined') {
        let tries = 0
        const retry = (): void => {
          tries += 1
          if (!selectMyPage() && tries < 20) window.setTimeout(retry, 100)
        }
        window.setTimeout(retry, 0)
      }
      return () => {}
    })
  }
}
