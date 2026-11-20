/**
 * Component stylesheet. Literal colours never appear here: everything reads a
 * `--chives-*` token from `tokens.ts`, so both schemes are defined in one place.
 *
 * Static client bundles have no `styles.insert` seat (that symbol exists only
 * inside the dynamic-plugin sandbox), so the same contract is implemented with
 * an owned `<style>` tag whose disposer runs from `ctx.effect`.
 */

/** Component CSS; prepended with the token sheet by {@link insertChivesStyles}. */
export const COMPONENT_CSS = `
.chives-brand-mark { display: inline-flex; align-items: center; justify-content: center; line-height: 0; }
.chives-brand-name { display: inline-flex; align-items: baseline; gap: 6px; min-width: 0; max-width: 100%; overflow: hidden; }
.chives-brand-word { font-family: var(--chives-font-serif); font-size: 16px; line-height: 22px; letter-spacing: 0.02em; color: var(--chives-text-primary); }
.chives-brand-sub { font-size: 10px; line-height: 22px; letter-spacing: 0.12em; color: var(--chives-text-tertiary); font-family: inherit; font-weight: 400; white-space: nowrap; }
.chives-hero-mark { display: inline-flex; align-items: center; gap: 12px; overflow: visible; line-height: 0; }
.chives-hero-copy { display: inline-flex; align-items: baseline; font-size: 26px; line-height: 32px; font-weight: 500; letter-spacing: 0.01em; color: var(--chives-text-primary); }
.chives-hero-title { white-space: nowrap; }
/* The hero title has no slot and "conversation" is a single-occupant locale
   namespace, so the mark seat renders mark + title and hides the shipped
   headline group (headline text and preview badge) it replaces. */
[class*="titleGroup"] { display: none !important; }
/* entry-customization's More launcher renders whenever that package has a
   sidebar.panellist.actions entry; hide the row even if the consumer row is
   still loaded (the patch disables it where the bundle order allows). */
nav[class*="panelList"] button[aria-haspopup="menu"] { display: none !important; }
.chives-mark-gold-face, .chives-mark-ripple { transform-box: fill-box; transform-origin: center; }
.chives-mark-ripple { opacity: 0; }
.chives-hero-mark.is-prologue .chives-mark-gold-face { animation: chives-touch-sweep 900ms var(--chives-ease) both; }
.chives-hero-mark.is-prologue .chives-mark-ripple { animation: chives-touch-ripple 1100ms var(--chives-ease) both; }
@keyframes chives-touch-sweep { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
@keyframes chives-touch-ripple {
  0% { opacity: 0.9; transform: scale(0.5); }
  70% { opacity: 0.25; transform: scale(1.5); }
  100% { opacity: 0; transform: scale(1.9); }
}
.chives-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 20px 0 24px; padding: 0 2px; }
.chives-cards-title { grid-column: 1 / -1; margin: 0; font-size: 11px; letter-spacing: 0.14em; color: var(--chives-text-tertiary); font-weight: 500; }
.chives-card {
  position: relative; overflow: hidden; isolation: isolate;
  display: block; width: 100%; text-align: left;
  padding: 12px 14px; border: 0; border-radius: var(--chives-radius-inner); box-shadow: var(--chives-shadow-card);
  background: var(--chives-surface-panel); color: var(--chives-text-primary);
  font: inherit; font-family: var(--chives-font-sans); font-size: 13px; font-weight: 500; line-height: 1.45; cursor: pointer;
  transition: border-color var(--chives-dur-fast) var(--chives-ease), transform var(--chives-dur-fast) var(--chives-ease);
  animation: chives-card-in 200ms var(--chives-ease) both;
}
.chives-card::after {
  content: ''; position: absolute; inset: 0; pointer-events: none; opacity: 0; z-index: 0;
  background: radial-gradient(140px circle at var(--chives-mx, 50%) var(--chives-my, 50%), var(--chives-gold-glow), transparent 68%);
  transition: opacity var(--chives-dur-fast) var(--chives-ease);
}
.chives-card-text { position: relative; z-index: 1; }
.chives-card:hover { transform: translateY(-1px); box-shadow: var(--chives-shadow-card), 0 0 0 1.5px var(--chives-gold-soft); }
.chives-card:hover::after { opacity: 1; }
.chives-card:active { transform: translateY(0); }
.chives-card:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
@keyframes chives-card-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.chives-home { display: flex; flex-direction: column; gap: 14px; height: 100%; overflow: auto; padding: 20px 24px 32px; background: var(--chives-surface-base); color: var(--chives-text-primary); font-size: 13px; line-height: 1.5; }
.chives-home-top { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 20px; padding-bottom: 10px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); }
.chives-home-brand { display: flex; align-items: center; gap: 10px; }
.chives-home-word { font-family: var(--chives-font-serif); font-size: 20px; letter-spacing: 0.02em; line-height: 1.1; }
.chives-home-sub { color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.18em; }
.chives-home-topmeta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; font-size: 12px; color: var(--chives-text-secondary); min-width: 0; }
.chives-home-trading { padding: 1px 9px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 10px; font-weight: 600; font-size: 11px; letter-spacing: 0.04em; }
.chives-home-trading.is-open { color: var(--chives-state-healthy); border-color: var(--chives-state-healthy); }
.chives-home-trading.is-pre_open, .chives-home-trading.is-lunch { color: var(--chives-state-warn); border-color: var(--chives-state-warn); }
.chives-home-trading.is-closed, .chives-home-trading.is-holiday, .chives-home-trading.is-unknown { color: var(--chives-state-idle); }
.chives-home-time { color: var(--chives-text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-home-note { color: var(--chives-state-idle); font-size: 11px; overflow-wrap: anywhere; min-width: 0; }
.chives-home-pulse { display: inline-flex; align-items: center; gap: 5px; }
.chives-home-reconnect { color: var(--chives-state-warn); font-size: 10px; }
.chives-home-banner { padding: 6px 10px; border: var(--chives-hairline) solid var(--chives-state-warn); border-radius: 6px; color: var(--chives-state-warn); font-size: 12px; background: var(--chives-surface-panel); }
.chives-home-banner.is-critical { border-color: var(--chives-state-critical); color: var(--chives-state-critical); }
.chives-home-indexbar { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 8px; padding: 2px 0 4px; min-width: 0; }
.chives-home-indices { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.chives-home-section-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 4px 12px; min-width: 0; }
.chives-index { min-width: 0; padding: 8px 10px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: var(--chives-surface-panel); }
.chives-index-name { color: var(--chives-text-secondary); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chives-index-price { font-size: 20px; font-weight: 500; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; line-height: 1.25; }
.chives-index-move { font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-index-amount { color: var(--chives-text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-home-spark-wrap { position: relative; display: block; }
.chives-home-spark { display: block; width: 100%; height: 30px; margin: 3px 0 1px; overflow: visible; }
.chives-home-spark-cross { stroke: var(--chives-text-tertiary); stroke-width: 1; stroke-dasharray: 2 2; }
.chives-home-spark-tip { position: absolute; z-index: 4; top: -16px; transform: translateX(-50%); padding: 1px 5px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 3px; background: var(--chives-surface-raised); color: var(--chives-text-primary); font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; pointer-events: none; }
.chives-home-spark-path { fill: none; stroke: var(--chives-gold-deep); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1; animation: chives-home-draw 700ms var(--chives-ease) both; }
.chives-home-spark-dot { fill: var(--chives-gold); animation: chives-home-breathe 2400ms ease-in-out infinite; }
.chives-home-spark-empty { display: block; width: 100%; height: 30px; margin: 3px 0 1px; }
.chives-home-toggle { appearance: none; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; background: var(--chives-surface-panel); color: var(--chives-text-secondary); padding: 3px 9px; font: inherit; font-size: 11px; cursor: pointer; white-space: nowrap; flex: 0 0 auto; }
.chives-home-toggle.is-active { border-color: var(--chives-gold); color: var(--chives-gold-deep); }
.chives-home-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: start; }
.chives-home-grid > * { min-width: 0; }
.chives-panel { display: flex; flex-direction: column; gap: 8px; padding: 11px 13px 13px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: var(--chives-surface-panel); min-width: 0; animation: chives-home-card-in 240ms var(--chives-ease) both; }
.chives-panel:nth-child(1) { animation-delay: 0ms; }
.chives-panel:nth-child(2) { animation-delay: 40ms; }
.chives-panel:nth-child(3) { animation-delay: 80ms; }
.chives-panel:nth-child(4) { animation-delay: 120ms; }
.chives-panel:nth-child(5) { animation-delay: 160ms; }
.chives-panel.is-placeholder { grid-column: 1 / -1; }
.chives-panel-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 10px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); padding-bottom: 5px; min-width: 0; }
.chives-panel-title { margin: 0; font-family: var(--chives-font-serif); font-size: 14px; font-weight: 500; letter-spacing: 0.01em; }
.chives-home-dash { color: var(--chives-text-tertiary); }
.chives-home-empty { color: var(--chives-text-tertiary); font-size: 12px; padding: 8px 0; }
.chives-breadth { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.chives-breadth-labels { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 10px; font-size: 11px; font-variant-numeric: tabular-nums; color: var(--chives-text-secondary); min-width: 0; }
.chives-breadth-track { display: flex; height: 8px; overflow: hidden; border-radius: 4px; background: var(--chives-surface-sunken); }
.chives-breadth-up { background: var(--chives-up); transition: width 320ms var(--chives-ease); }
.chives-breadth-flat { background: var(--chives-flat); opacity: 0.5; transition: width 320ms var(--chives-ease); }
.chives-breadth-down { background: var(--chives-down); transition: width 320ms var(--chives-ease); }
.chives-kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 4px 12px; font-size: 12px; }
.chives-kv > div { display: flex; justify-content: space-between; gap: 8px; border-bottom: var(--chives-hairline) dashed var(--chives-border-weak); padding: 2px 0; min-width: 0; }
.chives-kv span { color: var(--chives-text-tertiary); min-width: 0; overflow-wrap: anywhere; }
.chives-kv strong { font-weight: 600; font-variant-numeric: tabular-nums; }
.chives-regime.is-risk_on { color: var(--chives-up); }
.chives-regime.is-risk_off { color: var(--chives-down); }
.chives-regime.is-neutral, .chives-regime.is-unknown { color: var(--chives-text-secondary); }
.chives-reasons { margin: 0; padding-left: 16px; color: var(--chives-text-tertiary); font-size: 11px; overflow-wrap: anywhere; }
.chives-reasons li { margin: 1px 0; }
.chives-sector-lists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 16px; min-width: 0; }
.chives-rank-title { color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.1em; margin: 2px 0 3px; }
.chives-rank-row { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 4px 8px; align-items: baseline; padding: 3px 0; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); font-size: 12px; }
.chives-rank-no { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; font-size: 10px; }
.chives-rank-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-rank-pct { font-variant-numeric: tabular-nums; white-space: nowrap; }
.chives-rank-amount { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; font-size: 10px; text-align: right; }
.chives-rank-leader { grid-column: 2 / -1; color: var(--chives-text-tertiary); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-home-table { width: 100%; max-width: 100%; border-collapse: collapse; font-size: 12px; }
.chives-home-table th { text-align: left; padding: 4px 6px; color: var(--chives-text-tertiary); font-weight: 500; border-bottom: var(--chives-hairline) solid var(--chives-border-strong); white-space: nowrap; }
.chives-home-table td { padding: 4px 6px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); white-space: nowrap; }
.chives-home-code { color: var(--chives-text-tertiary); font-size: 10px; margin-left: 5px; font-variant-numeric: tabular-nums; }
.chives-num { font-variant-numeric: tabular-nums; text-align: right; }
.chives-up { color: var(--chives-up); }
.chives-down { color: var(--chives-down); }
.chives-flat { color: var(--chives-flat); }
.chives-stale { opacity: 0.55; }
.chives-tag { display: inline-block; padding: 0 5px; border-radius: 3px; border: var(--chives-hairline) solid var(--chives-border-strong); font-size: 9px; color: var(--chives-text-tertiary); margin-left: 4px; }
.chives-tag.is-small { border-color: var(--chives-state-warn); color: var(--chives-state-warn); }
.chives-feed { display: flex; flex-direction: column; gap: 4px; }
.chives-feed-item { position: relative; display: grid; grid-template-columns: 52px 1fr auto; gap: 2px 8px; padding: 5px 6px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); cursor: pointer; min-width: 0; }
.chives-feed-item:hover { background: var(--chives-surface-raised); }
.chives-feed-item.is-new { animation: chives-home-alert-in 420ms var(--chives-ease) both, chives-home-glow 30s linear 1; }
.chives-feed-item.is-analyzing::after { content: ''; position: absolute; inset: 0; pointer-events: none; background: linear-gradient(100deg, transparent 20%, var(--chives-gold-glow) 48%, transparent 76%); background-size: 220% 100%; animation: chives-home-flow 1800ms linear infinite; }
.chives-feed-time { color: var(--chives-text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-feed-body { min-width: 0; }
.chives-feed-title { display: flex; align-items: center; gap: 6px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-feed-status { font-size: 9px; font-weight: 500; padding: 0 4px; border-radius: 3px; border: var(--chives-hairline) solid var(--chives-border-strong); color: var(--chives-text-tertiary); }
.chives-feed-status.is-analyzed { color: var(--chives-state-healthy); border-color: var(--chives-state-healthy); }
.chives-feed-status.is-analyzing { color: var(--chives-gold-deep); border-color: var(--chives-gold-soft); }
.chives-feed-status.is-failed { color: var(--chives-state-critical); border-color: var(--chives-state-critical); }
.chives-feed-meta { display: block; color: var(--chives-text-tertiary); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-feed-sev { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; color: var(--chives-text-tertiary); }
.chives-feed-sev.is-l1 { color: var(--chives-state-warn); }
.chives-feed-sev.is-l2, .chives-feed-sev.is-l3 { color: var(--chives-state-critical); }
.chives-feed-detail { grid-column: 1 / -1; padding-top: 4px; border-top: var(--chives-hairline) dashed var(--chives-border-weak); }
.chives-home-mono { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; line-height: 1.55; white-space: pre-wrap; max-height: 340px; overflow: auto; }
.chives-home-building { padding: 12px 2px; }
.chives-home-building-title { font-family: var(--chives-font-serif); font-size: 20px; color: var(--chives-text-secondary); }
.chives-home-building p { margin: 4px 0 0; color: var(--chives-text-tertiary); font-size: 12px; }
.chives-pulse-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--chives-state-idle); }
.chives-pulse-dot.is-healthy { background: var(--chives-state-healthy); animation: chives-home-pulse 2200ms ease-out infinite; }
.chives-pulse-dot.is-warn { background: var(--chives-state-warn); animation: chives-home-pulse 3200ms ease-out infinite; }
.chives-pulse-dot.is-idle { background: var(--chives-state-idle); }
.chives-pulse-dot.is-unreachable { background: var(--chives-state-idle); animation: chives-home-pulse 4600ms ease-out infinite; }
.chives-digit { display: inline-block; animation: chives-home-digit-in 320ms var(--chives-ease) both; }
.chives-tick.is-up, .chives-index-price.is-up { animation: chives-home-tick-up 520ms var(--chives-ease) 1; }
.chives-tick.is-down, .chives-index-price.is-down { animation: chives-home-tick-down 520ms var(--chives-ease) 1; }
@keyframes chives-home-card-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes chives-home-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes chives-home-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
@keyframes chives-home-alert-in { from { opacity: 0; transform: translateX(14px); } to { opacity: 1; transform: none; } }
@keyframes chives-home-flow { from { background-position: 180% 0; } to { background-position: -80% 0; } }
@keyframes chives-home-glow { 0%, 92% { box-shadow: inset 0 0 0 1px var(--chives-gold-soft), 0 0 10px var(--chives-gold-glow); } 100% { box-shadow: none; } }
@keyframes chives-home-pulse { 0% { box-shadow: 0 0 0 0 var(--chives-gold-glow); } 70% { box-shadow: 0 0 0 7px var(--chives-gold-glow); } 100% { box-shadow: 0 0 0 0 var(--chives-gold-glow); } }
@keyframes chives-home-tick-up { 0% { color: var(--chives-up); transform: translateY(-2px); } 100% { color: inherit; transform: none; } }
@keyframes chives-home-tick-down { 0% { color: var(--chives-down); transform: translateY(2px); } 100% { color: inherit; transform: none; } }
@keyframes chives-home-digit-in { from { opacity: 0; transform: translateY(0.35em); } to { opacity: 1; transform: none; } }
@media (max-width: 980px) { .chives-home-grid { grid-template-columns: 1fr; } .chives-panel.is-placeholder { grid-column: auto; } }
@media (max-width: 767px) {
  .chives-home { padding: 14px 14px 24px; }
  .chives-home-indexbar { grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); }
  .chives-sector-lists { grid-template-columns: 1fr; }
  .chives-home-topmeta { gap: 4px 10px; }
  .chives-home-table { font-size: 11px; }
  .chives-home-table th, .chives-home-table td { padding: 3px 4px; }
  .chives-home-table td:first-child, .chives-home-table th:first-child { white-space: normal; }
  .chives-home-code { display: block; margin-left: 0; }
  .chives-rank-row { gap: 3px 6px; }
}
@media (max-width: 900px) { .chives-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) {
  .chives-cards { grid-template-columns: minmax(0, 1fr); margin: 24px 0; }
  .chives-hero-copy { font-size: 21px; line-height: 27px; }
  .chives-hero-title { white-space: normal; }
}
@media (hover: hover) { .chives-feed-item:hover { background: var(--chives-surface-raised); } }
@media (prefers-reduced-motion: reduce) {
  .chives-home *, .chives-home *::before, .chives-home *::after,
  .chives-cards *, .chives-hero-mark, .chives-hero-mark * {
    animation: none !important;
    transition: none !important;
    transform: none !important;
  }
  .chives-card::after { display: none; }
}
/* ---- T101 "mine" page: account overview, holdings, risk, curve, allocation, watchlist ---- */
.chives-my-scroll { height: 100%; overflow-y: auto; overflow-x: hidden; padding: 10px 14px 0; }
.chives-my { display: flex; flex-direction: column; gap: 14px; min-height: 100%; padding-bottom: 12px; color: var(--chives-text-primary); font-family: var(--chives-font-sans); -webkit-font-smoothing: antialiased; letter-spacing: -0.003em; }
.chives-my-top { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 10px 18px; min-width: 0; }
.chives-my-title-block { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.chives-my-title { margin: 0; font-family: var(--chives-font-serif); font-size: 26px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.15; }
.chives-my-topmeta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 14px; color: var(--chives-text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; min-width: 0; }
.chives-my-trading { padding: 1px 9px; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); font-size: 10px; font-weight: 600; letter-spacing: 0.04em; }
.chives-my-trading.is-open { color: var(--chives-gold-deep); background: color-mix(in oklab, var(--chives-gold) 16%, transparent); }
.chives-my-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.chives-my-eye { display: grid; place-items: center; width: 32px; height: 32px; border: 0; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); cursor: pointer; }
.chives-my-eye:hover { color: var(--chives-text-primary); background: var(--chives-surface-sunken); }
.chives-my-eye:focus-visible, .chives-my-button:focus-visible, .chives-my-link:focus-visible, .chives-my-seg:focus-visible, .chives-my-sort:focus-visible, .chives-my-ask-stock:focus-visible, .chives-my-alloc-seg:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-my-button { appearance: none; border: 0; border-radius: 999px; padding: 7px 14px; font: inherit; font-size: 12px; font-weight: 600; background: var(--chives-fill); color: var(--chives-text-primary); cursor: pointer; transition: background var(--chives-dur-fast) var(--chives-ease); }
.chives-my-button:hover { background: var(--chives-surface-sunken); }
.chives-my-button.is-primary { background: var(--chives-gold); color: var(--chives-on-color); }
.chives-my-button.is-primary:hover { background: var(--chives-gold-deep); }
.chives-my-overview { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px 18px; padding: 18px; border-radius: var(--chives-radius-card); background: var(--chives-surface-panel); box-shadow: var(--chives-shadow-card); animation: chives-my-in var(--chives-dur-base) var(--chives-ease) both; }
.chives-my-cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.chives-my-cell-label { color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chives-my-cell-value { font-size: 18px; font-weight: 600; letter-spacing: -0.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chives-my-cell-value.chives-my-big { font-size: 25px; font-weight: 500; }
.chives-my-pill { align-self: flex-start; display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.chives-my-pill.is-up { background: var(--chives-up); color: var(--chives-on-color); }
.chives-my-pill.is-down { background: var(--chives-down); color: var(--chives-on-color); }
.chives-my-track { display: block; height: 4px; width: 100%; max-width: 140px; border-radius: 2px; overflow: hidden; background: var(--chives-surface-sunken); }
.chives-my-track.is-thin { height: 3px; max-width: 100%; margin-top: 4px; }
.chives-my-track-fill { display: block; height: 100%; background: var(--chives-gold); transition: width var(--chives-dur-slow) var(--chives-ease); }
.chives-my-body { display: grid; grid-template-columns: 3fr 2fr; gap: 14px; align-items: start; min-width: 0; }
.chives-my-col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.chives-my-col .chives-my-section:nth-child(1) { animation-delay: 0ms; }
.chives-my-col .chives-my-section:nth-child(2) { animation-delay: 40ms; }
.chives-my-col .chives-my-section:nth-child(3) { animation-delay: 80ms; }
.chives-my-section { display: flex; flex-direction: column; gap: 10px; min-width: 0; padding: 16px; border-radius: var(--chives-radius-card); background: var(--chives-surface-panel); box-shadow: var(--chives-shadow-card); animation: chives-my-in var(--chives-dur-base) var(--chives-ease) both; }
.chives-my-section-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; min-width: 0; }
.chives-my-label { color: var(--chives-text-primary); font-size: 15px; font-weight: 600; letter-spacing: -0.012em; }
.chives-my-meta { color: var(--chives-text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-my-table-wrap { overflow-x: auto; }
.chives-my-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.chives-my-table th { padding: 0 6px 7px; text-align: right; white-space: nowrap; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); font-weight: 500; }
.chives-my-table th:first-child { text-align: left; }
.chives-my-table th:last-child { text-align: left; }
.chives-my-table td { padding: 9px 6px; text-align: right; white-space: nowrap; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-my-table td:first-child, .chives-my-table td.chives-my-flags { text-align: left; }
.chives-my-sort { appearance: none; border: 0; background: transparent; color: var(--chives-text-tertiary); font: inherit; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; padding: 0; cursor: pointer; white-space: nowrap; }
.chives-my-sort:hover, .chives-my-sort.is-active { color: var(--chives-text-primary); }
.chives-my-sort-glyph { margin-left: 3px; color: var(--chives-gold); font-size: 9px; }
.chives-my-row { cursor: pointer; }
.chives-my-row:hover { background: var(--chives-surface-raised); }
.chives-my-row.is-expanded { background: var(--chives-surface-raised); }
.chives-my-row.is-highlight { box-shadow: inset 2px 0 0 var(--chives-gold); }
.chives-my-row.is-missing { opacity: 0.6; }
.chives-my-name { display: block; font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.chives-my-code { display: block; color: var(--chives-text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-my-spark-col, .chives-my-spark-cell { width: 80px; text-align: center !important; padding-left: 2px; padding-right: 2px; }
.chives-my-spark { display: block; margin: 0 auto; overflow: visible; }
.chives-my-spark-line { fill: none; stroke: var(--chives-text-secondary); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.chives-my-spark-area { stroke: none; fill: var(--chives-text-secondary); opacity: 0.1; }
.chives-my-spark-base { stroke: var(--chives-hairline-color); stroke-width: 1; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
.chives-my-spark.is-up .chives-my-spark-line { stroke: var(--chives-up); }
.chives-my-spark.is-up .chives-my-spark-area { fill: var(--chives-up); }
.chives-my-spark.is-down .chives-my-spark-line { stroke: var(--chives-down); }
.chives-my-spark.is-down .chives-my-spark-area { fill: var(--chives-down); }
.chives-my-spark-empty { color: var(--chives-text-tertiary, var(--chives-text-secondary)); }
.chives-my-num { font-variant-numeric: tabular-nums; }
.chives-my-pct { display: block; color: var(--chives-text-tertiary); font-size: 10px; }
.chives-my-flags { white-space: normal; }
.chives-my-flag { display: inline-block; margin: 1px 4px 1px 0; padding: 0 6px; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); font-size: 9px; }
.chives-my-flag.is-t1 { color: var(--chives-state-idle); }
.chives-my-flag.is-limit_up { color: var(--chives-up); background: color-mix(in oklab, var(--chives-up) 12%, transparent); }
.chives-my-flag.is-limit_down { color: var(--chives-down); background: color-mix(in oklab, var(--chives-down) 12%, transparent); }
.chives-my-flag.is-missing { color: var(--chives-state-warn); background: color-mix(in oklab, var(--chives-state-warn) 14%, transparent); }
.chives-my-detail-row td { padding: 0 6px 10px; text-align: left; }
.chives-my-detail { animation: chives-my-in var(--chives-dur-fast) var(--chives-ease) both; }
.chives-my-detail { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; padding: 10px 12px; border-radius: var(--chives-radius-inner); background: var(--chives-surface-sunken); font-size: 11px; color: var(--chives-text-secondary); }
.chives-my-detail em { font-style: normal; color: var(--chives-text-tertiary); margin-right: 4px; }
.chives-my-ask-stock { appearance: none; margin-left: auto; border: 0; border-radius: 999px; padding: 5px 12px; background: var(--chives-gold); color: var(--chives-on-color); font: inherit; font-size: 11px; font-weight: 600; cursor: pointer; }
.chives-my-risk-list { margin: 0; display: flex; flex-direction: column; }
.chives-my-risk-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px; padding: 7px 0; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-my-risk-row:last-child { border-bottom: 0; }
.chives-my-risk-row dt { color: var(--chives-text-secondary); font-size: 12px; }
.chives-my-risk-row dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; font-size: 13px; }
.chives-my-risk-row p { grid-column: 1 / -1; margin: 0; color: var(--chives-text-tertiary); font-size: 10px; line-height: 1.5; }
.chives-my-risk-reason { display: block; margin-top: 4px; color: var(--chives-text-tertiary); font-size: 10px; }
.chives-my-chart { position: relative; width: 100%; min-height: 190px; }
.chives-my-chart svg { display: block; width: 100%; height: 190px; overflow: visible; }
.chives-my-line { fill: none; stroke: var(--chives-flat); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1; animation: chives-my-draw 700ms var(--chives-ease) both; }
.chives-my-area { opacity: 0.9; animation: chives-my-in 400ms var(--chives-ease) both; }
.chives-my-stop-top { stop-color: var(--chives-flat); stop-opacity: 0.28; }
.chives-my-stop-bottom { stop-color: var(--chives-flat); stop-opacity: 0; }
.chives-my-chart.is-up .chives-my-line { stroke: var(--chives-up); }
.chives-my-chart.is-down .chives-my-line { stroke: var(--chives-down); }
.chives-my-chart.is-up .chives-my-stop-top { stop-color: var(--chives-up); }
.chives-my-chart.is-down .chives-my-stop-top { stop-color: var(--chives-down); }
.chives-my-dot { fill: var(--chives-flat); animation: chives-my-breathe 2400ms ease-in-out infinite; }
.chives-my-chart.is-up .chives-my-dot { fill: var(--chives-up); }
.chives-my-chart.is-down .chives-my-dot { fill: var(--chives-down); }
.chives-my-cross { stroke: var(--chives-text-tertiary); stroke-width: 1; stroke-dasharray: 2 2; }
.chives-my-tip { position: absolute; top: 2px; transform: translateX(-50%); display: flex; flex-direction: column; gap: 1px; min-width: 150px; padding: 5px 8px; border-radius: 8px; background: var(--chives-surface-raised); box-shadow: var(--chives-shadow-card); color: var(--chives-text-secondary); font-size: 10px; font-variant-numeric: tabular-nums; pointer-events: none; z-index: 3; }
.chives-my-tip strong { color: var(--chives-text-primary); font-weight: 600; }
.chives-my-history-empty { padding: 24px 8px; text-align: center; line-height: 1.6; }
.chives-my-segmented { display: inline-flex; gap: 0; margin-left: auto; padding: 2px; border-radius: 9px; background: var(--chives-fill); }
.chives-my-seg { appearance: none; border: 0; border-radius: 7px; padding: 3px 10px; background: transparent; color: var(--chives-text-secondary); font: inherit; font-size: 11px; font-weight: 500; cursor: pointer; white-space: nowrap; }
.chives-my-seg.is-active { background: var(--chives-surface-panel); color: var(--chives-text-primary); font-weight: 600; box-shadow: var(--chives-shadow-card); }
.chives-my-alloc-bar { display: flex; gap: 2px; height: 18px; border-radius: 999px; overflow: hidden; background: var(--chives-surface-sunken); }
.chives-my-alloc-seg { appearance: none; border: 0; height: 100%; padding: 0; cursor: pointer; transition: width var(--chives-dur-slow) var(--chives-ease), filter var(--chives-dur-fast) var(--chives-ease); }
.chives-my-alloc-seg:hover { filter: brightness(1.08); }
.chives-my-alloc-seg.is-active { outline: 2px solid var(--chives-text-primary); outline-offset: -2px; }
.chives-my-alloc-legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 14px; }
.chives-my-alloc-legend li { display: inline-flex; align-items: center; gap: 5px; min-width: 0; font-size: 11px; color: var(--chives-text-secondary); }
.chives-my-alloc-dot { width: 8px; height: 8px; flex: none; border-radius: 50%; }
.chives-my-alloc-pct { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; }
.chives-my-watch-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.chives-my-watch-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 8px; align-items: center; padding: 8px 2px; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-my-watch-list li:last-child { border-bottom: 0; }
.chives-my-watch-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 500; }
.chives-my-watch-price { font-variant-numeric: tabular-nums; font-size: 12px; }
.chives-my-held { padding: 0 7px; border-radius: 999px; background: color-mix(in oklab, var(--chives-gold) 16%, transparent); color: var(--chives-gold-deep); font-size: 9px; font-weight: 600; }
.chives-my-link { appearance: none; margin-left: auto; border: 0; background: transparent; color: var(--chives-gold-deep); font: inherit; font-size: 11px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.chives-my-empty { color: var(--chives-text-tertiary); font-size: 12px; line-height: 1.6; padding: 8px 0; }
.chives-my-loading { padding: 40px 0; text-align: center; }
.chives-my-banner { padding: 7px 12px; border-radius: 10px; background: color-mix(in oklab, var(--chives-state-warn) 12%, transparent); color: var(--chives-state-warn); font-size: 11px; }
.chives-my-guide, .chives-my-hubdown { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 300px; padding: 34px 24px; border-radius: var(--chives-radius-card); background: var(--chives-surface-panel); box-shadow: var(--chives-shadow-card); text-align: center; }
.chives-my-hubdown { min-height: 52vh; }
.chives-my-guide h2, .chives-my-hubdown h2 { margin: 0; font-family: var(--chives-font-serif); font-size: 24px; font-weight: 500; }
.chives-my-guide p { margin: 0; max-width: 560px; color: var(--chives-text-secondary); font-size: 13px; line-height: 1.65; }
.chives-my-ask { position: sticky; bottom: 0; z-index: 15; display: flex; align-items: center; gap: 8px; margin-top: auto; padding: 8px 8px 8px 16px; border-radius: 999px; background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); }
.chives-my-ask:focus-within { box-shadow: var(--chives-shadow-card), 0 0 0 2px var(--chives-gold); }
.chives-my-ask-label { color: var(--chives-gold-deep); font-size: 10px; letter-spacing: 0.08em; white-space: nowrap; }
.chives-my-ask-input { flex: 1 1 auto; min-width: 0; appearance: none; border: 0; background: transparent; color: var(--chives-text-primary); font: inherit; font-size: 12px; padding: 2px 0; }
.chives-my-ask-input:focus { outline: none; }
.chives-my-ask-send { appearance: none; border: 0; border-radius: 999px; width: 26px; height: 24px; background: var(--chives-gold); color: var(--chives-on-color); font: inherit; cursor: pointer; }
.chives-my-ask-note { min-width: 10px; color: var(--chives-gold-deep); font-size: 10px; }
@keyframes chives-my-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes chives-my-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes chives-my-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
@media (max-width: 1279px) {
  .chives-my-body { grid-template-columns: minmax(0, 1fr); }
  .chives-my-overview { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 767px) {
  .chives-my-scroll { padding: 8px 9px 0; }
  .chives-my-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 14px; }
  .chives-my-cell-value { font-size: 16px; }
  .chives-my-cell-value.chives-my-big { font-size: 21px; }
  .chives-my-table { font-size: 11px; }
  .chives-my-spark-col, .chives-my-spark-cell { display: none; }
  .chives-my-table th, .chives-my-table td { padding: 7px 4px; }
  .chives-my-detail { gap: 4px 12px; }
  .chives-my-ask-stock { margin-left: 0; }
  .chives-my-watch-list li { grid-template-columns: minmax(0, 1fr) auto auto; }
  .chives-my-held { grid-column: 1; justify-self: start; }
  .chives-my-ask { position: static; }
}


@media (prefers-reduced-motion: reduce) {
  .chives-my *, .chives-my *::before, .chives-my *::after {
    animation: none !important;
    transition: none !important;
    transform: none !important;
    scroll-behavior: auto !important;
  }
}


/* ---- review page (复盘) ---- */
.chives-rv-wrap { display: block; min-height: 100%; }
.chives-rv-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.chives-rv .chives-my-banner.is-info { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: color-mix(in oklab, var(--chives-gold) 14%, transparent); color: var(--chives-gold-deep); }
.chives-rv button { appearance: none; border: 0; border-radius: 999px; padding: 4px 11px; background: var(--chives-fill); color: var(--chives-text-primary); font: inherit; font-size: 11px; font-weight: 500; cursor: pointer; transition: background var(--chives-dur-fast) var(--chives-ease), transform var(--chives-dur-fast) var(--chives-ease), opacity var(--chives-dur-fast) var(--chives-ease); }
.chives-rv button:hover:not(:disabled) { background: color-mix(in oklab, var(--chives-fill) 70%, var(--chives-text-primary) 8%); }
.chives-rv button:active:not(:disabled) { transform: scale(0.97); }
.chives-rv button:disabled { opacity: 0.45; cursor: default; }
.chives-rv button.is-primary { background: var(--chives-gold); color: var(--chives-on-color); font-weight: 600; }
.chives-rv button.is-ghost { background: transparent; color: var(--chives-text-secondary); }
.chives-rv input, .chives-rv select { appearance: none; border: var(--chives-hairline) solid var(--chives-hairline-color); border-radius: 8px; background: var(--chives-surface-base); color: var(--chives-text-primary); font: inherit; font-size: 11px; padding: 3px 8px; min-width: 0; }
.chives-rv input { width: 64px; text-align: right; font-variant-numeric: tabular-nums; }
.chives-rv input:focus, .chives-rv select:focus { outline: 2px solid var(--chives-gold); outline-offset: 0; }
.chives-rv em { font-style: normal; color: var(--chives-text-tertiary); margin-right: 4px; }
.chives-rv .is-up { color: var(--chives-up); }
.chives-rv .is-down { color: var(--chives-down); }
.chives-rv-empty, .chives-rv-empty-block { color: var(--chives-text-tertiary); font-size: 12px; line-height: 1.6; }
.chives-rv-empty-block { padding: 10px 2px; }
.chives-rv-env { display: inline-flex; align-items: center; padding: 1px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--chives-fill); }
.chives-rv-env.is-strong { background: color-mix(in oklab, var(--chives-up) 16%, transparent); color: var(--chives-up); }
.chives-rv-env.is-weak { background: color-mix(in oklab, var(--chives-down) 16%, transparent); color: var(--chives-down); }
.chives-rv-env.is-neutral { color: var(--chives-text-secondary); }
.chives-rv-state-strip { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chives-rv-state-chip { padding: 2px 9px; border-radius: 999px; font-size: 10px; background: var(--chives-fill); color: var(--chives-text-secondary); font-variant-numeric: tabular-nums; }
.chives-rv-state-chip.is-zero { opacity: 0.5; }
.chives-rv-state-chip.is-execute { background: color-mix(in oklab, var(--chives-sig-opp) 16%, transparent); color: var(--chives-sig-opp); }
.chives-rv-state-chip.is-await_confirm { background: color-mix(in oklab, var(--chives-sig-plan) 18%, transparent); color: var(--chives-gold-deep); }
.chives-rv-state-chip.is-abandon, .chives-rv-state-chip.is-exit { background: color-mix(in oklab, var(--chives-sig-risk) 16%, transparent); color: var(--chives-sig-risk); }
.chives-rv-cards { display: flex; flex-direction: column; gap: 8px; }
.chives-rv-card { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: var(--chives-radius-inner); background: var(--chives-surface-raised); border-left: 3px solid var(--chives-border-weak); animation: chives-home-card-in 360ms var(--chives-ease) both; }
.chives-rv-card.is-execute { border-left-color: var(--chives-sig-opp); }
.chives-rv-card.is-await_confirm { border-left-color: var(--chives-sig-plan); }
.chives-rv-card.is-abandon, .chives-rv-card.is-exit { border-left-color: var(--chives-sig-risk); }
.chives-rv-card.is-proposed { border-left-color: var(--chives-gold); background: color-mix(in oklab, var(--chives-gold) 7%, var(--chives-surface-raised)); }
.chives-rv-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; }
.chives-rv-card-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; min-width: 0; font-size: 13px; }
.chives-rv-tag { padding: 0 7px; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); font-size: 10px; }
.chives-rv-tag.is-warn { background: color-mix(in oklab, var(--chives-state-warn) 16%, transparent); color: var(--chives-state-warn); }
.chives-rv-state { padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--chives-fill); white-space: nowrap; }
.chives-rv-state.is-execute { background: var(--chives-sig-opp); color: var(--chives-on-color); }
.chives-rv-state.is-await_confirm { background: var(--chives-sig-plan); color: var(--chives-on-color); }
.chives-rv-state.is-abandon, .chives-rv-state.is-exit { background: var(--chives-sig-risk); color: var(--chives-on-color); }
.chives-rv-thesis, .chives-rv-judgement { margin: 0; font-size: 12px; line-height: 1.55; color: var(--chives-text-secondary); }
.chives-rv-judgement { color: var(--chives-text-primary); }
.chives-rv-judgement em { color: var(--chives-gold-deep); font-weight: 600; }
.chives-rv-card-line { display: flex; flex-wrap: wrap; gap: 3px 16px; font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-rv-card-body { display: flex; flex-direction: column; gap: 6px; padding-top: 4px; border-top: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-rv-conds { display: flex; flex-direction: column; gap: 2px; font-size: 11px; }
.chives-rv-conds-title { color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.04em; }
.chives-rv-conds ul, .chives-rv-history, .chives-rv-evidence, .chives-rv-candidates ul, .chives-rv-events ul, .chives-rv-pending ul { margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 2px; }
.chives-rv-conds li.has-light { list-style: none; margin-left: -14px; display: flex; align-items: center; gap: 6px; }
.chives-rv-light { width: 7px; height: 7px; border-radius: 50%; flex: none; background: var(--chives-fill); box-shadow: inset 0 0 0 1px var(--chives-border-weak); }
.chives-rv-conds li.is-met .chives-rv-light { background: var(--chives-sig-opp); box-shadow: 0 0 0 3px color-mix(in oklab, var(--chives-sig-opp) 22%, transparent); }
.chives-rv-conds li.is-unmet { color: var(--chives-text-secondary); }
.chives-rv-conds li.is-unknown { color: var(--chives-text-tertiary); }
.chives-rv-history { font-size: 10px; color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; list-style: none; padding-left: 0; }
.chives-rv-sizing-note { margin: 0; font-size: 10px; color: var(--chives-text-tertiary); }
.chives-rv-card-tools, .chives-rv-card-actions, .chives-rv-record-bar, .chives-rv-block-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.chives-rv-inline { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--chives-text-secondary); }
.chives-rv-pause { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px; border-radius: 10px; background: color-mix(in oklab, var(--chives-sig-risk) 14%, transparent); color: var(--chives-sig-risk); font-size: 12px; }
.chives-rv-metrics, .chives-rv-headroom { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 11px; font-variant-numeric: tabular-nums; align-items: center; }
.chives-rv-metrics button { margin-left: 4px; padding: 1px 8px; }
.chives-rv-mood { display: flex; flex-direction: column; gap: 4px; }
.chives-rv-mood-slot { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.chives-rv-mood-slot > span { width: 34px; color: var(--chives-text-tertiary); }
.chives-rv-mood-btn.is-on { background: var(--chives-gold); color: var(--chives-on-color); }
.chives-rv-settings { display: flex; flex-direction: column; gap: 10px; }
.chives-rv-setting-group h3 { margin: 0 0 4px; font-size: 11px; font-weight: 600; color: var(--chives-text-tertiary); letter-spacing: 0.04em; }
.chives-rv-setting-group ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; }
.chives-rv-setting { padding: 6px 0; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); display: flex; flex-direction: column; gap: 4px; }
.chives-rv-setting:last-child { border-bottom: 0; }
.chives-rv-setting-main { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 4px 8px; align-items: center; font-size: 12px; }
.chives-rv-setting-value { font-variant-numeric: tabular-nums; font-weight: 600; }
.chives-rv-source { padding: 0 7px; border-radius: 999px; font-size: 9px; background: var(--chives-fill); color: var(--chives-text-tertiary); }
.chives-rv-source.is-adopted, .chives-rv-source.is-user_set { background: color-mix(in oklab, var(--chives-sig-opp) 14%, transparent); color: var(--chives-sig-opp); }
.chives-rv-setting-edit { grid-column: 1 / -1; display: flex; align-items: center; gap: 6px; justify-content: flex-end; }
.chives-rv-suggest { display: flex; flex-direction: column; gap: 3px; padding: 7px 10px; border-radius: 10px; background: color-mix(in oklab, var(--chives-gold) 10%, transparent); font-size: 11px; }
.chives-rv-suggest-head { color: var(--chives-gold-deep); font-weight: 600; }
.chives-rv-suggest-basis { color: var(--chives-text-secondary); line-height: 1.5; }
.chives-rv-suggest-actions { display: flex; gap: 6px; }
.chives-rv-fineprint { color: var(--chives-text-tertiary); font-size: 10px; line-height: 1.5; }
.chives-rv-record { display: flex; flex-direction: column; gap: 6px; font-size: 12px; line-height: 1.6; }
.chives-rv-record p { margin: 0; }
.chives-rv-record-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.chives-rv-differs { color: var(--chives-state-warn); }
.chives-rv-checklist { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; }
.chives-rv-check.is-ok { color: var(--chives-sig-opp); }
.chives-rv-check.is-miss { color: var(--chives-text-tertiary); }
.chives-rv-pre { margin: 6px 0 0; padding: 10px 12px; border-radius: 10px; background: var(--chives-surface-sunken); font-family: var(--chives-font-sans); font-size: 11px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow: auto; }
.chives-rv-section.is-wide { grid-column: 1 / -1; }
.chives-rv-charts { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.chives-rv-chartcard { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: var(--chives-radius-inner); background: var(--chives-surface-raised); min-width: 0; }
.chives-rv-chartcard-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; font-size: 12px; font-weight: 600; }
.chives-rv-chartcard-head em { font-weight: 400; font-size: 10px; margin: 0; }
.chives-rv-chart { width: 100%; height: 64px; display: block; overflow: visible; }
.chives-rv-line { fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.chives-rv-line.is-a, .chives-rv-dot.is-a { stroke: var(--chives-up); background: var(--chives-up); }
.chives-rv-line.is-b, .chives-rv-dot.is-b { stroke: var(--chives-gold); background: var(--chives-gold); }
.chives-rv-line.is-c, .chives-rv-dot.is-c { stroke: var(--chives-down); background: var(--chives-down); }
.chives-rv-legend { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 10px; color: var(--chives-text-secondary); font-variant-numeric: tabular-nums; }
.chives-rv-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 4px; border: 0; }
.chives-rv-ladder, .chives-rv-themes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 11px; }
.chives-rv-ladder li { display: grid; grid-template-columns: 44px minmax(0, 1fr) 22px; gap: 4px 8px; align-items: center; }
.chives-rv-ladder-names { grid-column: 1 / -1; color: var(--chives-text-tertiary); font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chives-rv-bar { display: block; height: 6px; border-radius: 3px; background: var(--chives-fill); overflow: hidden; }
.chives-rv-bar i { display: block; height: 100%; border-radius: 3px; background: var(--chives-up); transition: width var(--chives-dur-slow) var(--chives-ease); }
.chives-rv-themes li { display: flex; justify-content: space-between; gap: 8px; font-variant-numeric: tabular-nums; }
.chives-rv-themes em { margin: 0; color: var(--chives-text-secondary); }
.chives-rv-themes em.is-up { color: var(--chives-up); }
.chives-rv-themes em.is-down { color: var(--chives-down); }
.chives-rv-kv { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; margin: 0; }
.chives-rv-kv dt { color: var(--chives-text-tertiary); font-size: 10px; }
.chives-rv-kv dd { margin: 0; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
@media (max-width: 1100px) { .chives-rv-grid { grid-template-columns: minmax(0, 1fr); } }
@media (prefers-reduced-motion: reduce) { .chives-rv-card, .chives-rv-bar i { animation: none !important; transition: none !important; } }
`

/** Insert the token + component sheets; returns a disposer that removes them. */
export function insertStyles(css: string): () => void {
  if (typeof document === 'undefined') return () => {}
  const tag = document.createElement('style')
  tag.dataset.chives = 'chives-ui'
  tag.textContent = css
  document.head.append(tag)
  return () => { tag.remove() }
}

/** Insert both Chives sheets as one owned tag. */
export function insertChivesStyles(tokenCss: string): () => void {
  return insertStyles(`${tokenCss}\n${COMPONENT_CSS}`)
}
