/** Sidebar glyphs for the Chives navigation rows. Stroke-only, `currentColor`. */
import type { ReactElement } from 'react'
import { ChivesMark } from './brand.tsx'

export interface SidebarIconProps {
  /** Requested square edge in px. */
  size: number
  /** Whether the panel is selected (owner-provided). */
  active?: boolean
}

/** "Mine" row: a wallet outline, distinct from the brand mark and the clock. */
export function MyPageIcon({ size }: SidebarIconProps): ReactElement {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <rect x="3" y="5.5" width="18" height="13" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3 9.5h18" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="16.6" cy="14.4" r="1.2" fill="currentColor" />
    </svg>
  )
}

/** Workbench row: the brand mark itself, so the first icon is the product. */
export function WorkbenchIcon({ size }: SidebarIconProps): ReactElement {
  return <ChivesMark size={size} />
}

/** Scheduled-task row: the clock shared by the built-in schedule panel. */
export function ScheduleIcon({ size }: SidebarIconProps): ReactElement {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 7.5 V12 L15.5 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Review row: a notebook page with a check line, distinct from the wallet and the clock. */
export function ReviewIcon({ size }: SidebarIconProps): ReactElement {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <rect x="5" y="3.5" width="14" height="17" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.6 9h6.8M8.6 12.5h6.8M8.6 16h3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
