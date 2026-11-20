/**
 * Chives design tokens — the single place where colour literals are allowed.
 *
 * Two layers are owned here:
 * 1. `--chives-*` component tokens, published twice (`:root` for the light
 *    surface, `body[data-ds-dark-theme]` for the dark one).
 * 2. `--dsw-alias-*` overrides that map dsh's semantic aliases onto the Chives
 *    palette, so shipped UI follows the brand in both schemes.
 *
 * Everything outside this file must reference a token, never a literal.
 */

export type ChivesMode = 'light' | 'dark'

/** Surface/text/brand/status/chart tokens consumed by Chives components. */
export type ChivesTokenName =
  | '--chives-surface-base'
  | '--chives-surface-panel'
  | '--chives-surface-raised'
  | '--chives-surface-sunken'
  | '--chives-text-primary'
  | '--chives-text-secondary'
  | '--chives-text-tertiary'
  | '--chives-gold'
  | '--chives-gold-deep'
  | '--chives-gold-soft'
  | '--chives-gold-glow'
  | '--chives-red'
  | '--chives-green'
  | '--chives-flat'
  | '--chives-up'
  | '--chives-down'
  | '--chives-state-healthy'
  | '--chives-state-warn'
  | '--chives-state-critical'
  | '--chives-state-idle'
  | '--chives-diverging-neg'
  | '--chives-diverging-mid'
  | '--chives-diverging-pos'
  | '--chives-cat-1'
  | '--chives-cat-2'
  | '--chives-cat-3'
  | '--chives-cat-4'
  | '--chives-cat-5'
  | '--chives-cat-6'
  | '--chives-cat-7'
  | '--chives-cat-8'
  | '--chives-hairline'
  | '--chives-hairline-color'
  | '--chives-border-strong'
  | '--chives-border-weak'
  | '--chives-ease'
  | '--chives-dur-fast'
  | '--chives-dur-base'
  | '--chives-dur-slow'
  | '--chives-mark-stone'
  | '--chives-mark-stone-deep'
  | '--chives-mark-gold'
  | '--chives-mark-gold-deep'
  | '--chives-mark-highlight'
  | '--chives-ripple'
  | '--chives-font-serif'
  | '--chives-font-sans'
  | '--chives-radius-card'
  | '--chives-radius-inner'
  | '--chives-radius-ctl'
  | '--chives-shadow-card'
  | '--chives-glass'
  | '--chives-glass-blur'
  | '--chives-fill'
  | '--chives-on-color'
  | '--chives-sig-plan'
  | '--chives-sig-opp'
  | '--chives-sig-risk'
  | '--chives-sig-sector'
  | '--chives-sig-info'

/** Component token values per scheme; both maps must carry every name. */
export const CHIVES_TOKENS: Record<ChivesMode, Record<ChivesTokenName, string>> = {
  light: {
    '--chives-surface-base': '#F2F2F7',
    '--chives-surface-panel': '#FFFFFF',
    '--chives-surface-raised': '#EFEFF4',
    '--chives-surface-sunken': '#E8E8ED',
    '--chives-text-primary': '#1C1C1E',
    '--chives-text-secondary': '#5C5C61',
    '--chives-text-tertiary': '#8A8A8E',
    '--chives-gold': '#9A7B1F',
    '--chives-gold-deep': '#7A6118',
    '--chives-gold-soft': '#C9A94E',
    '--chives-gold-glow': 'rgba(154, 123, 31, 0.22)',
    '--chives-red': '#E5352C',
    '--chives-green': '#27A04A',
    '--chives-flat': '#8E8E93',
    '--chives-up': 'var(--chives-red)',
    '--chives-down': 'var(--chives-green)',
    '--chives-state-healthy': '#248A3D',
    '--chives-state-warn': '#B25000',
    '--chives-state-critical': '#D70015',
    '--chives-state-idle': '#8E8E93',
    '--chives-diverging-neg': '#E5352C',
    '--chives-diverging-mid': '#C7C7CC',
    '--chives-diverging-pos': '#27A04A',
    '--chives-cat-1': '#4C6EF5',
    '--chives-cat-2': '#12B886',
    '--chives-cat-3': '#E8590C',
    '--chives-cat-4': '#7048E8',
    '--chives-cat-5': '#1098AD',
    '--chives-cat-6': '#D6336C',
    '--chives-cat-7': '#74B816',
    '--chives-cat-8': '#F59F00',
    '--chives-hairline': '0.5px',
    '--chives-hairline-color': '#E3E3E8',
    '--chives-border-strong': '#D1D1D6',
    '--chives-border-weak': '#ECECF0',
    '--chives-ease': 'cubic-bezier(0.25, 1, 0.5, 1)',
    '--chives-dur-fast': '120ms',
    '--chives-dur-base': '240ms',
    '--chives-dur-slow': '380ms',
    '--chives-mark-stone': '#A8A296',
    '--chives-mark-stone-deep': '#7E786D',
    '--chives-mark-gold': '#9A7B1F',
    '--chives-mark-gold-deep': '#6F5714',
    '--chives-mark-highlight': '#F1E4BC',
    '--chives-ripple': 'rgba(154, 123, 31, 0.28)',
    '--chives-font-serif': 'Georgia, "Songti SC", "Noto Serif CJK SC", serif',
    '--chives-font-sans': '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", system-ui, sans-serif',
    '--chives-radius-card': '18px',
    '--chives-radius-inner': '12px',
    '--chives-radius-ctl': '10px',
    '--chives-shadow-card': '0 0 0 0.5px rgba(60, 60, 67, 0.10), 0 1px 2px rgba(0, 0, 0, 0.04), 0 8px 24px rgba(0, 0, 0, 0.06)',
    '--chives-glass': 'rgba(255, 255, 255, 0.72)',
    '--chives-glass-blur': 'saturate(180%) blur(22px)',
    '--chives-fill': 'rgba(120, 120, 128, 0.12)',
    '--chives-on-color': '#FFFFFF',
    '--chives-sig-plan': '#A67C00',
    '--chives-sig-opp': '#0071E3',
    '--chives-sig-risk': '#C93400',
    '--chives-sig-sector': '#8944AB',
    '--chives-sig-info': '#8A8A8E',
  },
  dark: {
    '--chives-surface-base': '#000000',
    '--chives-surface-panel': '#1C1C1E',
    '--chives-surface-raised': '#2C2C2E',
    '--chives-surface-sunken': '#0A0A0B',
    '--chives-text-primary': '#F5F5F7',
    '--chives-text-secondary': '#B4B4BA',
    '--chives-text-tertiary': '#8E8E93',
    '--chives-gold': '#D4AF37',
    '--chives-gold-deep': '#B8912B',
    '--chives-gold-soft': '#E8C766',
    '--chives-gold-glow': 'rgba(212, 175, 55, 0.20)',
    '--chives-red': '#FF453A',
    '--chives-green': '#30D158',
    '--chives-flat': '#8E8E93',
    '--chives-up': 'var(--chives-red)',
    '--chives-down': 'var(--chives-green)',
    '--chives-state-healthy': '#30D158',
    '--chives-state-warn': '#FFB340',
    '--chives-state-critical': '#FF453A',
    '--chives-state-idle': '#8E8E93',
    '--chives-diverging-neg': '#FF453A',
    '--chives-diverging-mid': '#48484A',
    '--chives-diverging-pos': '#30D158',
    '--chives-cat-1': '#748FFC',
    '--chives-cat-2': '#38D9A9',
    '--chives-cat-3': '#FF922B',
    '--chives-cat-4': '#9775FA',
    '--chives-cat-5': '#22B8CF',
    '--chives-cat-6': '#F06595',
    '--chives-cat-7': '#A9E34B',
    '--chives-cat-8': '#FFD43B',
    '--chives-hairline': '0.5px',
    '--chives-hairline-color': '#2C2C2E',
    '--chives-border-strong': '#3A3A3C',
    '--chives-border-weak': '#242426',
    '--chives-ease': 'cubic-bezier(0.25, 1, 0.5, 1)',
    '--chives-dur-fast': '120ms',
    '--chives-dur-base': '240ms',
    '--chives-dur-slow': '380ms',
    '--chives-mark-stone': '#6E7681',
    '--chives-mark-stone-deep': '#4A5058',
    '--chives-mark-gold': '#D4AF37',
    '--chives-mark-gold-deep': '#B8912B',
    '--chives-mark-highlight': '#FFF3C4',
    '--chives-ripple': 'rgba(212, 175, 55, 0.26)',
    '--chives-font-serif': 'Georgia, "Songti SC", "Noto Serif CJK SC", serif',
    '--chives-font-sans': '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", system-ui, sans-serif',
    '--chives-radius-card': '18px',
    '--chives-radius-inner': '12px',
    '--chives-radius-ctl': '10px',
    '--chives-shadow-card': '0 0 0 0.5px rgba(255, 255, 255, 0.07), 0 10px 30px rgba(0, 0, 0, 0.45)',
    '--chives-glass': 'rgba(28, 28, 30, 0.72)',
    '--chives-glass-blur': 'saturate(180%) blur(22px)',
    '--chives-fill': 'rgba(118, 118, 128, 0.24)',
    '--chives-on-color': '#FFFFFF',
    '--chives-sig-plan': '#E8B923',
    '--chives-sig-opp': '#0A84FF',
    '--chives-sig-risk': '#FF9F0A',
    '--chives-sig-sector': '#BF5AF2',
    '--chives-sig-info': '#8E8E93',
  },
}

/** dsh semantic aliases driven by the Chives palette; values stay token references. */
export const ALIAS_TOKENS: Record<ChivesMode, Record<string, string>> = {
  light: {
    '--dsw-alias-bg-base': 'var(--chives-surface-base)',
    '--dsw-alias-bg-layer-1': 'var(--chives-surface-panel)',
    '--dsw-alias-bg-layer-2': 'var(--chives-surface-raised)',
    '--dsw-alias-bg-layer-3': 'var(--chives-surface-panel)',
    '--dsw-alias-label-primary': 'var(--chives-text-primary)',
    '--dsw-alias-label-secondary': 'var(--chives-text-secondary)',
    '--dsw-alias-label-tertiary': 'var(--chives-text-tertiary)',
    '--dsw-alias-label-caption': 'var(--chives-text-tertiary)',
    '--dsw-alias-border-l1': 'var(--chives-hairline-color)',
    '--dsw-alias-border-l2': 'var(--chives-border-strong)',
    '--dsw-alias-border-l3': 'var(--chives-border-strong)',
    '--dsw-alias-brand-primary': 'var(--chives-gold)',
    '--dsw-alias-brand-text': 'var(--chives-gold-deep)',
    '--dsw-alias-link': 'var(--chives-gold-deep)',
    '--dsw-alias-interactive-bg-hover': 'var(--chives-surface-raised)',
    '--dsw-alias-interactive-bg-active': 'var(--chives-surface-sunken)',
    '--dsw-alias-state-success-primary': 'var(--chives-state-healthy)',
    '--dsw-alias-state-warn-primary': 'var(--chives-state-warn)',
    '--dsw-alias-state-error-primary': 'var(--chives-state-critical)',
    '--dsw-alias-state-idle-primary': 'var(--chives-state-idle)',
  },
  dark: {
    '--dsw-alias-bg-base': 'var(--chives-surface-base)',
    '--dsw-alias-bg-layer-1': 'var(--chives-surface-panel)',
    '--dsw-alias-bg-layer-2': 'var(--chives-surface-raised)',
    '--dsw-alias-bg-layer-3': 'var(--chives-surface-panel)',
    '--dsw-alias-label-primary': 'var(--chives-text-primary)',
    '--dsw-alias-label-secondary': 'var(--chives-text-secondary)',
    '--dsw-alias-label-tertiary': 'var(--chives-text-tertiary)',
    '--dsw-alias-label-caption': 'var(--chives-text-tertiary)',
    '--dsw-alias-border-l1': 'var(--chives-hairline-color)',
    '--dsw-alias-border-l2': 'var(--chives-border-strong)',
    '--dsw-alias-border-l3': 'var(--chives-border-strong)',
    '--dsw-alias-brand-primary': 'var(--chives-gold)',
    '--dsw-alias-brand-text': 'var(--chives-gold-deep)',
    '--dsw-alias-link': 'var(--chives-gold-deep)',
    '--dsw-alias-interactive-bg-hover': 'var(--chives-surface-raised)',
    '--dsw-alias-interactive-bg-active': 'var(--chives-surface-sunken)',
    '--dsw-alias-state-success-primary': 'var(--chives-state-healthy)',
    '--dsw-alias-state-warn-primary': 'var(--chives-state-warn)',
    '--dsw-alias-state-error-primary': 'var(--chives-state-critical)',
    '--dsw-alias-state-idle-primary': 'var(--chives-state-idle)',
  },
}

/** Theme ids registered with `ctx.theme.register`, one per scheme. */
export const THEME_DARK_ID = 'chives'
export const THEME_LIGHT_ID = 'chives-light'

/** Override-layer source id; stacked so the palette applies without user settings writes. */
export const OVERRIDE_SOURCE = 'chives-ui'

function declarations(tokens: Record<string, string>): string {
  return Object.entries(tokens).map(([name, value]) => `${name}: ${value};`).join('')
}

/** Per-mode alias pairs for `ctx.theme.overrideTokens` (same token reference in both). */
export function aliasTokenPairs(): Record<string, { light: string; dark: string }> {
  const pairs: Record<string, { light: string; dark: string }> = {}
  for (const [name, value] of Object.entries(ALIAS_TOKENS.light)) {
    pairs[name] = { light: value, dark: ALIAS_TOKENS.dark[name] ?? value }
  }
  return pairs
}

/** Alias overrides for one concrete registered theme. */
export function aliasTokens(mode: ChivesMode): Record<string, string> {
  return { ...ALIAS_TOKENS[mode] }
}

/**
 * The `--chives-*` stylesheet: light on `:root`, dark under the body attribute
 * dsh's theme presenter writes, plus the red-up/green-up swap hook.
 */
export function chivesTokenCss(): string {
  const light = declarations(CHIVES_TOKENS.light)
  const dark = declarations(CHIVES_TOKENS.dark)
  return [
    `:root{${light}}`,
    `body[data-ds-dark-theme],html[data-ds-dark-theme]{${dark}}`,
    ':root[data-chives-updown="green-up"],body[data-chives-updown="green-up"]{--chives-up: var(--chives-green); --chives-down: var(--chives-red);}',
  ].join('\n')
}

/** Standalone copy of apps/web/public/chives.svg for the dsh plugin. */
const SVG_NAMESPACE = 'http:' + '//www.w3.org/2000/svg'
export const CHIVES_FAVICON_SVG =
  '<svg xmlns="' + SVG_NAMESPACE + '" viewBox="0 0 128 128" role="img" aria-label="老韭菜 03-market-bundle"><g transform="translate(128 0) scale(-1 1)"><path fill="#15483B" d="M18 24h92v80H18z"/><path d="M34 86h60" stroke="#9DE883" stroke-width="3" stroke-linecap="round"/><path fill="#9DE883" d="M43 82c-7-12-10-23-7-37 10 11 15 22 15 37Zm15 0c-2-20 2-35 12-48 3 19 0 35-5 48Zm16 0c3-13 10-23 22-31-2 15-8 25-15 31Z"/><path d="M32 45L49 56L61 52L77 65L96 73" fill="none" stroke="#15483B" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><path d="M32 45L49 56L61 52L77 65L96 73" fill="none" stroke="#F6FAE9" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g></svg>'
