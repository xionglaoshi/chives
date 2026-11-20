/** Inline Chives brand mark and wordmark. No image files, no external fonts. */
import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { CHIVES_FAVICON_SVG } from './tokens.ts'
import { zh } from './locales.ts'
import { markProloguePlayed, shouldPlayPrologue } from './prologue.ts'

const markUrl = 'data:image/svg+xml,' + encodeURIComponent(CHIVES_FAVICON_SVG)

export interface ChivesMarkProps {
  /** Square edge in CSS px. */
  size?: number
  /** Extra class from the owner (the hero passes the shell's geometry class). */
  className?: string
  /** Play the touch-ripple prologue (hero only). */
  animated?: boolean
}

/** One self-contained SVG mark; every paint reads a `--chives-*` token. */
export function ChivesMark({ size = 24, className, animated = false }: ChivesMarkProps): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={className === undefined ? 'chives-brand-mark' : `chives-brand-mark ${className}`}
      role="img"
      aria-label="Chives"
      focusable="false"
    >
      <image href={markUrl} width="48" height="48" />
      {animated ? <circle cx="24" cy="7" r="5" fill="none" stroke="var(--chives-ripple)" strokeWidth="0.9" className="chives-mark-ripple" /> : null}
    </svg>
  )
}

/** Sidebar brand mark seat (`sidebar.brand.mark`). */
export function SidebarBrandMark({ size }: { size: number }): ReactElement {
  return <ChivesMark size={size} />
}

/** Sidebar wordmark seat (`sidebar.brand.name`): serif "Chives" + tagline. */
export function SidebarBrandName(): ReactElement {
  return (
    <span className="chives-brand-name">
      <span className="chives-brand-word">老韭菜 · Chives</span>
      <span className="chives-brand-sub">{zh.brandTagline}</span>
    </span>
  )
}

/** Welcome-page mark with the once-a-week touch prologue. */
export function HeroBrandMark({ size, className }: { size: number; className?: string }): ReactElement {
  const [playing] = useState<boolean>(() => shouldPlayPrologue())
  useEffect(() => {
    if (playing) markProloguePlayed()
  }, [playing])
  const classes = ['chives-hero-mark', playing ? 'is-prologue' : ''].filter(Boolean).join(' ')
  // The hero title has no slot of its own and the `conversation` locale is a
  // single-occupant namespace, so the mark seat carries mark + title; styles.ts
  // hides the shipped headline group that would otherwise render twice.
  return (
    <span className={classes}>
      <ChivesMark size={size} className={className} animated={playing} />
      <span className="chives-hero-copy">
        <span className="chives-hero-title">{zh.heroTitle}</span>
      </span>
    </span>
  )
}
