/** Client entry: wires the shared registration body to concrete Chives components. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { createApply, type UiComponents } from './apply.ts'
import { HeroBrandMark, SidebarBrandMark, SidebarBrandName } from './brand.tsx'
import { QuickCards } from './cards.tsx'
import { MyPageIcon, ScheduleIcon, WorkbenchIcon } from './icons.tsx'
import { MyPage } from './myPage.tsx'

/** Services this half hard-depends on; `theme` is provided by ui-theme. */
export const inject = ['slots', 'locale', 'theme', 'layout']

const components: UiComponents = {
  BrandMark: SidebarBrandMark,
  BrandName: SidebarBrandName,
  HeroBrandMark,
  QuickCards,
  MyPage,
  // Review page offline (2026-11-16): reviewPage.tsx and ReviewIcon are kept but not registered while the feature
  // is redesigned; createApply() only adds the panel when both ReviewPage and ReviewIcon are passed.
  MyPageIcon,
  WorkbenchIcon,
  ScheduleIcon,
}

export const apply: (ctx: Context) => void = createApply(components)
