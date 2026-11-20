/**
 * Design tokens shared by SVG, charts, and any code that cannot read CSS
 * custom properties. Names mirror `tokens.css`.
 */

export const colors = {
  bg: '#0C0B0A',
  nav: '#090807',
  panel: '#151311',
  card: '#131110',
  raised: '#1E1B18',
  bubble: '#24201C',
  line: '#2A2622',
  lineStrong: '#3A352F',
  text: '#EDE8DF',
  textSecondary: '#B5AEA2',
  textMuted: '#948D82',
  white: '#FFFFFF',
  gold: '#C8A96A',
  goldHighlight: '#E0C58C',
  up: '#E0685E',
  down: '#5DB28A',
  stone: '#5A544B',
  stoneDeep: '#4A453E',
  overlay: 'rgba(0, 0, 0, 0.4)'
} as const;

export const avatarTones = {
  gold: { label: '金', background: '#C8A96A', foreground: '#0C0B0A' },
  silver: { label: '银', background: '#B9BEC4', foreground: '#0C0B0A' },
  bronze: { label: '铜', background: '#B07A52', foreground: '#0C0B0A' },
  jade: { label: '玉', background: '#7FA693', foreground: '#0C0B0A' },
  ink: { label: '墨', background: '#3A352F', foreground: '#EDE8DF' }
} as const;

export type ToneName = keyof typeof avatarTones;

export const fontSize = {
  '2xs': 11,
  xs: 12,
  sm: 13,
  base: 14,
  md: 15,
  lg: 16,
  xl: 17,
  '2xl': 19,
  '3xl': 22,
  display: 28,
  hero: 36
} as const;

export const fontWeight = {
  light: 300,
  regular: 400,
  normal: 400,
  medium: 500,
  semibold: 500,
  bold: 600
} as const;

export const lineHeight = {
  tight: 1.35,
  snug: 1.5,
  normal: 1.65,
  relaxed: 1.8
} as const;

export const spacing = {
  1: 2,
  2: 4,
  3: 6,
  4: 8,
  5: 10,
  6: 12,
  7: 14,
  8: 16,
  9: 18,
  10: 20,
  11: 22,
  12: 24,
  14: 28,
  16: 32,
  20: 40
} as const;

export const radii = {
  xs: 4,
  sm: 8,
  md: 10,
  lg: 12,
  xl: 14,
  '2xl': 16,
  '3xl': 18,
  pill: 999
} as const;

export const shadows = {
  soft: '0 12px 32px rgba(0, 0, 0, 0.35)',
  pop: '0 8px 24px rgba(0, 0, 0, 0.45)',
  focus: '0 0 0 2px #0C0B0A, 0 0 0 4px #C8A96A'
} as const;

export const layout = {
  sidebar: 264,
  content: 820,
  touch: 44,
  avatarLarge: 36,
  avatarSmall: 28
} as const;

export const tokens = {
  colors,
  avatarTones,
  fontSize,
  fontWeight,
  lineHeight,
  spacing,
  radii,
  shadows,
  layout
} as const;
