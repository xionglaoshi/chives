/**
 * Panel ids shared by the sidebar rows and the default landing logic. Both
 * `main` blocks are owned by watch-panel; this package only navigates to them.
 */
export const MY_PAGE_PANEL = 'chives-mypage'
export const WORKBENCH_PANEL = 'chives-workbench'
export const REVIEW_PANEL = 'chives-review'

/** Cross-panel navigation event emitted by the "mine" page. */
export const PANEL_EVENT = 'chives:panel'
export const ASK_EVENT = 'chives:ask'

export const PANEL_IDS: readonly string[] = [MY_PAGE_PANEL, WORKBENCH_PANEL, REVIEW_PANEL]

/** Accept only a known panel id from an untrusted event. */
export function panelFromEvent(event: unknown): string | null {
  const detail = (event as { detail?: unknown } | null)?.detail
  const panel = (detail as { panel?: unknown } | null)?.panel
  return typeof panel === 'string' && PANEL_IDS.includes(panel) ? panel : null
}

export interface PanelEventTarget {
  addEventListener(type: string, listener: (event: Event) => void): void
  removeEventListener(type: string, listener: (event: Event) => void): void
}

/**
 * Listen for `chives:panel` and forward a whitelisted panel id to the layout.
 * Returns a disposer; absent targets (tests / SSR) are a no-op.
 */
export function installPanelBridge(
  navigate: (panel: string) => void,
  target?: PanelEventTarget | null,
): () => void {
  const bus = target ?? (typeof window === 'undefined' ? null : window)
  if (bus === null) return () => {}
  const listener = (event: Event): void => {
    const panel = panelFromEvent(event)
    if (panel !== null) navigate(panel)
  }
  bus.addEventListener(PANEL_EVENT, listener)
  return () => bus.removeEventListener(PANEL_EVENT, listener)
}
