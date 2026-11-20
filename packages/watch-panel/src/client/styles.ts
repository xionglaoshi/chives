/**
 * Watch-panel component stylesheet. Every colour is a `--chives-*` token; this
 * file never carries a palette value. The sheet is inserted once by the client
 * entry and removed with the plugin effect.
 */

export const PANEL_CSS = `
.chives-watch { display: flex; flex-direction: column; gap: 12px; height: 100%; overflow: auto; padding: 14px 18px 28px; color: var(--chives-text-primary); background: var(--chives-surface-base); font-size: 13px; line-height: 1.5; }
.chives-watch a { color: var(--chives-gold-deep); }
.chives-watch-status { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; padding: 8px 10px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: var(--chives-surface-panel); }
.chives-status-item { display: inline-flex; align-items: baseline; gap: 6px; white-space: nowrap; }
.chives-status-label { color: var(--chives-text-tertiary); font-size: 12px; }
.chives-badge { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 10px; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }
.chives-badge.is-healthy { color: var(--chives-state-healthy); border-color: var(--chives-state-healthy); }
.chives-badge.is-warn { color: var(--chives-state-warn); border-color: var(--chives-state-warn); }
.chives-badge.is-critical { color: var(--chives-state-critical); border-color: var(--chives-state-critical); }
.chives-badge.is-idle { color: var(--chives-state-idle); }
.chives-banner { padding: 7px 10px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; font-size: 12px; background: var(--chives-surface-panel); }
.chives-banner.is-warn { color: var(--chives-state-warn); border-color: var(--chives-state-warn); }
.chives-banner.is-critical { color: var(--chives-state-critical); border-color: var(--chives-state-critical); }
.chives-section { display: flex; flex-direction: column; gap: 8px; min-width: 0; animation: chives-section-in var(--chives-dur-base) var(--chives-ease) both; }
.chives-section-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; min-width: 0; }
.chives-section-title { margin: 0; font-family: var(--chives-font-serif); font-size: 16px; font-weight: 500; letter-spacing: 0.01em; }
.chives-section-meta { color: var(--chives-text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-actions { display: inline-flex; flex-wrap: wrap; gap: 6px; margin-left: auto; max-width: 100%; }
.chives-button { appearance: none; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; background: var(--chives-surface-panel); color: var(--chives-text-primary); padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; }
.chives-button:hover { border-color: var(--chives-gold-soft); }
.chives-button.is-active { border-color: var(--chives-gold); color: var(--chives-gold-deep); }
.chives-button:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-button:disabled { opacity: 0.5; cursor: default; }
.chives-empty { color: var(--chives-text-tertiary); padding: 10px 2px; }
.chives-scroll { overflow-x: auto; }
.chives-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.chives-table th { text-align: left; padding: 5px 7px; border-bottom: var(--chives-hairline) solid var(--chives-border-strong); color: var(--chives-text-tertiary); font-weight: 500; white-space: nowrap; }
.chives-table td { padding: 5px 7px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); white-space: nowrap; vertical-align: baseline; }
.chives-table tbody tr.is-clickable { cursor: pointer; }
.chives-table tbody tr.is-clickable:hover { background: var(--chives-surface-raised); }
.chives-table tbody tr.is-expanded { background: var(--chives-surface-raised); }
.chives-num { font-variant-numeric: tabular-nums; text-align: right; }
.chives-up { color: var(--chives-up); }
.chives-down { color: var(--chives-down); }
.chives-flat { color: var(--chives-flat); }
.chives-code { color: var(--chives-text-tertiary); font-size: 11px; margin-left: 6px; font-variant-numeric: tabular-nums; }
.chives-unit { color: var(--chives-text-tertiary); font-size: 10px; margin-left: 3px; }
.chives-reason { color: var(--chives-text-tertiary); font-size: 11px; margin-left: 5px; cursor: help; }
.chives-stale { opacity: 0.55; }
.chives-chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 6px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 4px; margin: 1px 3px 1px 0; font-size: 11px; color: var(--chives-text-secondary); }
.chives-chip.is-armed { border-color: var(--chives-gold-soft); color: var(--chives-gold-deep); }
.chives-tag { display: inline-block; padding: 0 5px; border-radius: 3px; border: var(--chives-hairline) solid var(--chives-border-strong); font-size: 10px; color: var(--chives-text-tertiary); }
.chives-tag.is-small { border-color: var(--chives-state-warn); color: var(--chives-state-warn); }
.chives-row-pulse { animation: chives-row-pulse 600ms var(--chives-ease) 1; }
.chives-row-pulse.chives-up { box-shadow: inset 0 0 0 1px var(--chives-up); }
.chives-row-pulse.chives-down { box-shadow: inset 0 0 0 1px var(--chives-down); }
.chives-detail { padding: 8px 10px; background: var(--chives-surface-sunken); border-left: 2px solid var(--chives-gold-soft); white-space: normal; }
.chives-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 4px 16px; }
.chives-detail-item { display: flex; justify-content: space-between; gap: 8px; border-bottom: var(--chives-hairline) dashed var(--chives-border-weak); padding: 2px 0; }
.chives-detail-label { color: var(--chives-text-tertiary); }
.chives-detail-value { font-variant-numeric: tabular-nums; text-align: right; }
.chives-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.55; white-space: pre-wrap; }
.chives-spark { position: relative; display: inline-block; vertical-align: middle; }
.chives-spark svg { display: block; overflow: visible; }
.chives-spark-path { fill: none; stroke: var(--chives-gold-deep); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1; stroke-dashoffset: 0; animation: chives-draw 700ms var(--chives-ease) both; }
.chives-spark-dot { fill: var(--chives-gold); animation: chives-breathe 2400ms ease-in-out infinite; }
.chives-spark-cross { stroke: var(--chives-text-tertiary); stroke-width: 1; stroke-dasharray: 2 2; }
.chives-spark-tip { position: absolute; z-index: 4; top: -30px; left: 0; transform: translateX(-50%); padding: 3px 6px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 4px; background: var(--chives-surface-raised); color: var(--chives-text-primary); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; pointer-events: none; }
.chives-treemap { position: relative; width: 100%; aspect-ratio: 16 / 9; min-height: 260px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; overflow: hidden; background: var(--chives-surface-sunken); }
.chives-tile { position: absolute; box-sizing: border-box; padding: 5px 6px; overflow: hidden; cursor: pointer; color: var(--chives-text-primary); transition: left 320ms var(--chives-ease), top 320ms var(--chives-ease), width 320ms var(--chives-ease), height 320ms var(--chives-ease), background-color 320ms var(--chives-ease), transform var(--chives-dur-fast) var(--chives-ease); }
.chives-tile.is-hover { transform: translateY(-2px); z-index: 3; outline: 1px solid var(--chives-gold); box-shadow: 0 2px 10px var(--chives-gold-glow); }
.chives-tile.is-selected { outline: 2px solid var(--chives-gold); z-index: 2; }
.chives-tile.is-stale { opacity: 0.55; }
.chives-tile-name { display: block; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-tile-flag { display: inline-block; margin-left: 4px; padding: 0 3px; border: var(--chives-hairline) solid var(--chives-state-warn); border-radius: 3px; color: var(--chives-state-warn); font-size: 8px; font-weight: 500; vertical-align: 1px; }
.chives-tile-move { display: block; font-size: 12px; font-variant-numeric: tabular-nums; }
.chives-tile-amount { display: block; color: var(--chives-text-secondary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-tooltip { position: absolute; z-index: 8; max-width: 240px; padding: 6px 8px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; background: var(--chives-surface-raised); box-shadow: 0 4px 18px var(--chives-gold-glow); font-size: 11px; pointer-events: none; }
.chives-tooltip-title { font-weight: 600; margin-bottom: 3px; }
.chives-tooltip-row { display: flex; justify-content: space-between; gap: 12px; color: var(--chives-text-secondary); }
.chives-timeline { display: flex; flex-direction: column; gap: 6px; }
.chives-alert { position: relative; display: grid; grid-template-columns: 62px 74px minmax(0, 1fr) auto; gap: 4px 10px; align-items: baseline; padding: 7px 10px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: var(--chives-surface-panel); overflow: hidden; min-width: 0; }
.chives-alert.is-new { animation: chives-alert-in 420ms var(--chives-ease) both, chives-alert-glow 30s linear 1; }
.chives-alert.is-analyzing::after { content: ''; position: absolute; inset: 0; pointer-events: none; background: linear-gradient(100deg, transparent 20%, var(--chives-gold-glow) 48%, transparent 76%); background-size: 220% 100%; animation: chives-flow 1800ms linear infinite; }
.chives-alert-summary { display: flex; flex-wrap: wrap; gap: 4px; }
.chives-alert-time { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; font-size: 11px; }
.chives-alert-sev { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; }
.chives-alert-sev.is-l1 { color: var(--chives-state-warn); }
.chives-alert-sev.is-l2 { color: var(--chives-state-critical); }
.chives-alert-sev.is-l3 { color: var(--chives-state-critical); font-weight: 800; }
.chives-alert-body { min-width: 0; }
.chives-alert-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-alert-meta { color: var(--chives-text-tertiary); font-size: 11px; }
.chives-alert-detail { grid-column: 1 / -1; padding-top: 4px; border-top: var(--chives-hairline) dashed var(--chives-border-weak); }
.chives-alert-status { justify-self: end; }
.chives-status-analyzed { color: var(--chives-state-healthy); }
.chives-status-analyzing { color: var(--chives-gold-deep); }
.chives-status-skipped { color: var(--chives-state-idle); }
.chives-status-pending { color: var(--chives-text-tertiary); }
.chives-status-failed { color: var(--chives-state-critical); }
.chives-filters { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chives-select { appearance: none; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; background: var(--chives-surface-panel); color: var(--chives-text-primary); padding: 4px 8px; font: inherit; font-size: 12px; }
.chives-rule-group { margin-top: 4px; }
.chives-rule-group-title { margin: 6px 0 4px; font-size: 12px; color: var(--chives-text-tertiary); letter-spacing: 0.08em; text-transform: uppercase; }
.chives-rule-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--chives-gold-deep); }
.chives-pulse-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--chives-state-idle); box-shadow: 0 0 0 0 var(--chives-gold-glow); }
.chives-pulse-dot.is-healthy { background: var(--chives-state-healthy); animation: chives-pulse 2200ms ease-out infinite; }
.chives-pulse-dot.is-warn { background: var(--chives-state-warn); animation: chives-pulse 3200ms ease-out infinite; }
.chives-pulse-dot.is-idle { background: var(--chives-state-idle); }
.chives-pulse-dot.is-unreachable { background: var(--chives-state-idle); animation: chives-pulse 4600ms ease-out infinite; }
.chives-tick { display: inline-block; font-variant-numeric: tabular-nums; }
.chives-digit { display: inline-block; animation: chives-digit-in 320ms var(--chives-ease) both; }
.chives-tick.is-up { animation: chives-tick-up 520ms var(--chives-ease) 1; }
.chives-tick.is-down { animation: chives-tick-down 520ms var(--chives-ease) 1; }
.chives-drill { animation: chives-drill-in 260ms var(--chives-ease) both; }
.chives-sector-detail-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 14px; }
.chives-sector-detail-title { margin: 0; font-family: var(--chives-font-serif); font-size: 20px; font-weight: 500; }
.chives-trend { width: 100%; height: 150px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: var(--chives-surface-panel); }
.chives-trend-path { fill: none; stroke: var(--chives-gold); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.chives-trend-area { fill: var(--chives-gold-glow); }
.chives-history { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--chives-text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.chives-members { max-height: 360px; overflow: auto; }
.chives-nowrap { white-space: nowrap; }
.chives-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@keyframes chives-section-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes chives-row-pulse { 0% { background-color: var(--chives-gold-glow); } 100% { background-color: var(--chives-surface-panel); } }
@keyframes chives-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes chives-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
@keyframes chives-alert-in { from { opacity: 0; transform: translateX(18px); } to { opacity: 1; transform: none; } }
@keyframes chives-alert-glow { 0%, 92% { box-shadow: inset 0 0 0 1px var(--chives-gold-soft), 0 0 12px var(--chives-gold-glow); } 100% { box-shadow: none; } }
@keyframes chives-flow { from { background-position: 180% 0; } to { background-position: -80% 0; } }
@keyframes chives-pulse { 0% { box-shadow: 0 0 0 0 var(--chives-gold-glow); } 70% { box-shadow: 0 0 0 7px var(--chives-gold-glow); } 100% { box-shadow: 0 0 0 0 var(--chives-gold-glow); } }
@keyframes chives-tick-up { 0% { color: var(--chives-up); transform: translateY(-2px); } 100% { color: inherit; transform: none; } }
@keyframes chives-tick-down { 0% { color: var(--chives-down); transform: translateY(2px); } 100% { color: inherit; transform: none; } }
@keyframes chives-digit-in { from { opacity: 0; transform: translateY(0.35em); } to { opacity: 1; transform: none; } }
@keyframes chives-drill-in { from { opacity: 0; transform: scale(0.985); } to { opacity: 1; transform: none; } }
@media (max-width: 767px) {
  .chives-watch { padding: 10px 12px 24px; }
  .chives-alert { grid-template-columns: 54px 1fr auto; }
  .chives-alert-sev { grid-column: 2; }
  .chives-treemap { aspect-ratio: 4 / 5; }
  .chives-watch-status { gap: 4px 10px; }
}
@media (hover: hover) {
  .chives-tile:hover { transform: translateY(-2px); outline: 1px solid var(--chives-gold); }
  .chives-alert:hover { border-color: var(--chives-gold-soft); }
}

/* ---- T97 single-page workbench ---- */
.chives-wb-scroll { height: 100%; overflow-y: auto; overflow-x: hidden; padding: 10px 14px 0; scroll-behavior: smooth; }
.chives-wb, .chives-wb-body, .chives-wb-col, .chives-wb-section { max-width: 100%; }
.chives-wb { display: flex; flex-direction: column; gap: 10px; min-height: 100%; padding-bottom: 12px; color: var(--chives-text-primary); }
.chives-wb-pulse { position: sticky; top: 0; z-index: 20; display: flex; flex-direction: column; gap: 6px; padding: 8px 10px 7px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 6px; background: color-mix(in oklab, var(--chives-surface-panel) 90%, transparent); backdrop-filter: blur(10px); box-shadow: 0 8px 24px -18px var(--chives-gold-glow); transition: padding var(--chives-dur-fast) var(--chives-ease); }
.chives-wb-pulse.is-collapsed { padding: 5px 10px; }
.chives-wb-pulse-row { display: flex; align-items: center; flex-wrap: wrap; gap: 5px 12px; min-width: 0; }
.chives-wb-title { font-family: var(--chives-font-serif); font-size: 15px; letter-spacing: 0.02em; }
.chives-wb-search { flex: 1 1 180px; min-width: 140px; max-width: 320px; appearance: none; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 4px; background: var(--chives-surface-sunken); color: var(--chives-text-primary); padding: 3px 8px; font: inherit; font-size: 11px; }
.chives-wb-search:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; border-color: var(--chives-gold-soft); }
.chives-wb-regime { color: var(--chives-text-tertiary); font-size: 11px; }
.chives-wb-regime-value.is-risk_on { color: var(--chives-up); }
.chives-wb-regime-value.is-risk_off { color: var(--chives-down); }
.chives-wb-regime-value.is-neutral, .chives-wb-regime-value.is-unknown { color: var(--chives-text-secondary); }
.chives-wb-trading { font-size: 10px; letter-spacing: 0.08em; padding: 1px 6px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 3px; color: var(--chives-text-secondary); }
.chives-wb-trading.is-open { color: var(--chives-gold-deep); border-color: var(--chives-gold-soft); }
.chives-wb-trading.is-closed, .chives-wb-trading.is-holiday { color: var(--chives-text-tertiary); }
.chives-wb-pulse-status { display: inline-flex; align-items: center; gap: 5px; color: var(--chives-text-secondary); font-size: 11px; }
.chives-wb-time { margin-left: auto; color: var(--chives-text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-wb-rules-button { appearance: none; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 4px; background: transparent; color: var(--chives-gold-deep); padding: 2px 7px; font: inherit; font-size: 10px; letter-spacing: 0.06em; cursor: pointer; }
.chives-wb-rules-button:hover { border-color: var(--chives-gold); }
.chives-wb-rules-button:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-wb-index-grid { display: grid; gap: 5px; }
.chives-wb-index { display: flex; flex-direction: column; gap: 2px; min-width: 0; padding: 5px 7px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 4px; background: var(--chives-surface-sunken); transition: border-color var(--chives-dur-fast) var(--chives-ease); }
.chives-wb-index:hover { border-color: var(--chives-gold-soft); }
.chives-wb-index-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; min-width: 0; }
.chives-wb-index-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--chives-text-secondary); }
.chives-wb-index-code { margin-left: 5px; color: var(--chives-text-tertiary); font-size: 9px; font-variant-numeric: tabular-nums; }
.chives-wb-index-move { font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.chives-wb-index-price { font-size: 19px; font-weight: 300; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; line-height: 1.15; }
.chives-wb-index-amount { color: var(--chives-text-tertiary); font-size: 9px; font-variant-numeric: tabular-nums; }
.chives-wb-spark { position: relative; display: block; min-height: 32px; }
.chives-wb-spark svg { display: block; overflow: visible; max-width: 100%; }
.chives-wb-spark-empty { display: block; min-height: 32px; color: var(--chives-text-tertiary); }
.chives-wb-spark-kind { position: absolute; top: 0; right: 0; color: var(--chives-text-tertiary); font-size: 8px; letter-spacing: 0.06em; }
.chives-wb-pulse-compact { display: flex; flex-wrap: wrap; gap: 2px 14px; align-items: baseline; }
.chives-wb-compact-index { display: inline-flex; gap: 5px; align-items: baseline; font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-wb-compact-name { color: var(--chives-text-secondary); }
.chives-wb-breadth { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chives-wb-breadth-counts, .chives-wb-breadth-stats { display: inline-flex; gap: 9px; align-items: baseline; font-size: 10px; font-variant-numeric: tabular-nums; color: var(--chives-text-secondary); white-space: nowrap; }
.chives-wb-breadth-counts .chives-flat { color: var(--chives-text-tertiary); }
.chives-wb-breadth-track { flex: 1 1 180px; display: flex; height: 5px; min-width: 120px; overflow: hidden; border-radius: 2px; background: var(--chives-surface-sunken); }
.chives-wb-breadth-up { height: 100%; background: var(--chives-up); }
.chives-wb-breadth-flat { height: 100%; background: var(--chives-surface-raised); }
.chives-wb-breadth-down { height: 100%; background: var(--chives-down); }
.chives-wb-primary { color: var(--chives-text-tertiary); }
.chives-wb-summary { display: flex; flex-direction: column; gap: 3px; }
.chives-wb-summary-head { display: flex; align-items: baseline; gap: 8px; }
.chives-wb-label { color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; }
.chives-wb-summary-age, .chives-wb-summary-note { color: var(--chives-text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-wb-summary-note { color: var(--chives-state-warn); }
.chives-wb-headlines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.chives-wb-headline { display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 4px; align-items: baseline; font-size: 12px; line-height: 1.45; }
.chives-wb-tone { font-size: 9px; text-align: center; }
.chives-wb-tone.is-up { color: var(--chives-up); }
.chives-wb-tone.is-down { color: var(--chives-down); }
.chives-wb-tone.is-warn { color: var(--chives-state-warn); font-weight: 700; }
.chives-wb-tone.is-neutral { color: var(--chives-text-tertiary); }
.chives-wb-headline-title { font-weight: 600; margin-right: 4px; }
.chives-wb-headline-body { color: var(--chives-text-secondary); }
.chives-wb-ref { appearance: none; border: 0; border-bottom: 1px dotted var(--chives-gold-soft); background: transparent; color: var(--chives-gold-deep); padding: 0; margin: 0 3px; font: inherit; font-size: 11px; cursor: pointer; }
.chives-wb-ref:hover { border-bottom-style: solid; }
.chives-wb-ref:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-wb-body { display: grid; grid-template-columns: 3fr 2fr; gap: 10px; align-items: start; }
.chives-wb-col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.chives-wb-section { display: flex; flex-direction: column; gap: 6px; min-width: 0; padding: 8px 10px 9px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 5px; background: var(--chives-surface-panel); animation: chives-section-in var(--chives-dur-base) var(--chives-ease) both; }
.chives-wb-focus.is-triggered, .chives-wb-focus-row.is-triggered { border-color: var(--chives-gold-soft); }
.chives-wb-section-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; min-width: 0; }
.chives-wb-meta { color: var(--chives-text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-wb-meta.is-stale { color: var(--chives-state-warn); }
.chives-wb-switch, .chives-wb-filters, .chives-wb-chips { display: inline-flex; flex-wrap: wrap; gap: 3px; margin-left: auto; }
.chives-wb-toggle, .chives-wb-filter, .chives-wb-chip, .chives-wb-add, .chives-wb-more, .chives-wb-drawer-close { appearance: none; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 4px; background: transparent; color: var(--chives-text-secondary); padding: 1px 7px; font: inherit; font-size: 10px; cursor: pointer; }
.chives-wb-toggle:hover, .chives-wb-filter:hover, .chives-wb-chip:hover, .chives-wb-add:hover, .chives-wb-more:hover { border-color: var(--chives-gold-soft); color: var(--chives-text-primary); }
.chives-wb-toggle.is-active, .chives-wb-filter.is-active, .chives-wb-chip.is-active { border-color: var(--chives-gold); color: var(--chives-gold-deep); }
.chives-wb-toggle:focus-visible, .chives-wb-filter:focus-visible, .chives-wb-chip:focus-visible, .chives-wb-add:focus-visible, .chives-wb-more:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-wb-chip-count { margin-left: 4px; color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; }
.chives-wb-add:disabled { opacity: 0.45; cursor: default; }
.chives-wb-empty { color: var(--chives-text-tertiary); padding: 8px 0; font-size: 11px; }
.chives-wb-banner { padding: 5px 8px; border: var(--chives-hairline) solid var(--chives-border-weak); border-radius: 4px; font-size: 11px; }
.chives-wb-banner.is-warn { color: var(--chives-state-warn); border-color: var(--chives-state-warn); }
.chives-wb-banner.is-critical { color: var(--chives-state-critical); border-color: var(--chives-state-critical); }
.chives-wb-mover-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; }
.chives-wb-mover-grid.has-active { grid-template-columns: 1fr 1fr 1fr; }
.chives-wb-mover-list { min-width: 0; }
.chives-wb-mover-head { display: flex; justify-content: space-between; align-items: baseline; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); padding-bottom: 2px; font-size: 11px; color: var(--chives-text-secondary); }
.chives-wb-mover-rows { list-style: none; margin: 0; padding: 0; }
.chives-wb-mover-row { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto auto auto; gap: 6px; align-items: baseline; width: 100%; appearance: none; border: 0; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); background: transparent; color: inherit; padding: 3px 0; font: inherit; font-size: 11px; text-align: left; cursor: pointer; }
.chives-wb-mover-row:hover { background: var(--chives-surface-raised); }
.chives-wb-mover-row:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: -2px; }
.chives-wb-mover-rank { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; text-align: right; }
.chives-wb-mover-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-wb-mover-price, .chives-wb-mover-change, .chives-wb-mover-amount { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.chives-wb-mover-amount { color: var(--chives-text-tertiary); }
.chives-wb-focus-rows { display: flex; flex-direction: column; }
.chives-wb-focus-row { display: flex; flex-direction: column; gap: 1px; padding: 5px 4px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); border-left: 2px solid transparent; cursor: pointer; }
.chives-wb-focus-row.is-triggered { border-left-color: var(--chives-gold); }
.chives-wb-focus-row:hover { background: var(--chives-surface-raised); }
.chives-wb-focus-row:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: -2px; }
.chives-wb-focus-main { display: grid; grid-template-columns: minmax(0, 1.4fr) auto auto auto minmax(0, 1fr) auto; gap: 3px 8px; align-items: baseline; }
.chives-wb-focus-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.chives-wb-focus-price, .chives-wb-focus-change, .chives-wb-focus-limit { font-size: 11px; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.chives-wb-focus-limit { color: var(--chives-text-tertiary); }
.chives-wb-focus-rules { display: inline-flex; flex-wrap: wrap; gap: 2px; min-width: 0; }
.chives-wb-focus-add { appearance: none; border: 0; background: transparent; color: var(--chives-gold-deep); font: inherit; font-size: 10px; cursor: pointer; padding: 0 2px; }
.chives-wb-focus-add:hover { text-decoration: underline; }
.chives-wb-focus-latest { display: flex; flex-wrap: wrap; gap: 2px 7px; align-items: baseline; font-size: 10px; color: var(--chives-text-tertiary); }
.chives-wb-focus-rule { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--chives-gold-deep); }
.chives-wb-focus-summary { flex: 1 1 120px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--chives-text-secondary); }
.chives-wb-focus-age { margin-left: auto; font-variant-numeric: tabular-nums; }
.chives-wb-portfolio { border-top: var(--chives-hairline) dashed var(--chives-border-weak); padding-top: 4px; }
.chives-wb-portfolio summary { cursor: pointer; color: var(--chives-text-tertiary); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; }
.chives-wb-portfolio-body { padding: 4px 0 2px; }
.chives-wb-portfolio-title { font-size: 12px; color: var(--chives-text-secondary); }
.chives-wb-portfolio-body p { margin: 2px 0 0; color: var(--chives-text-tertiary); font-size: 10px; line-height: 1.5; }
.chives-wb-feed-rows, .chives-wb-review, .chives-wb-drawer-alerts { display: flex; flex-direction: column; }
.chives-wb-review-head, .chives-wb-drawer-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.chives-wb-feed-row { display: grid; grid-template-columns: 52px 30px minmax(0, 1fr) auto; gap: 2px 7px; align-items: baseline; padding: 4px 3px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); border-left: 2px solid transparent; cursor: pointer; font-size: 11px; }
.chives-wb-feed-row:hover { background: var(--chives-surface-raised); }
.chives-wb-feed-row:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: -2px; }
.chives-wb-feed-row.is-new { border-left-color: var(--chives-gold); animation: chives-alert-in 420ms var(--chives-ease) both, chives-alert-glow 30s linear 1; }
.chives-wb-feed-row.is-analyzing::after { content: ''; position: absolute; inset: 0; pointer-events: none; background: linear-gradient(100deg, transparent 20%, var(--chives-gold-glow) 48%, transparent 76%); background-size: 220% 100%; animation: chives-flow 1800ms linear infinite; }
.chives-wb-feed-row { position: relative; overflow: hidden; }
.chives-wb-feed-time { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; font-size: 10px; }
.chives-wb-feed-sev { font-size: 9px; font-weight: 700; letter-spacing: 0.04em; color: var(--chives-text-tertiary); }
.chives-wb-feed-sev.is-l1 { color: var(--chives-state-warn); }
.chives-wb-feed-sev.is-l2, .chives-wb-feed-sev.is-l3 { color: var(--chives-state-critical); }
.chives-wb-feed-body { min-width: 0; }
.chives-wb-feed-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.chives-wb-feed-meta { display: flex; flex-wrap: wrap; gap: 2px 6px; align-items: baseline; color: var(--chives-text-tertiary); font-size: 10px; }
.chives-wb-rule-chip { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--chives-gold-deep); }
.chives-wb-rule-name { color: var(--chives-text-tertiary); }
.chives-wb-status { font-size: 10px; white-space: nowrap; }
.chives-wb-status.is-analyzed { color: var(--chives-state-healthy); }
.chives-wb-status.is-analyzing { color: var(--chives-gold-deep); }
.chives-wb-status.is-skipped, .chives-wb-status.is-pending { color: var(--chives-text-tertiary); }
.chives-wb-status.is-failed { color: var(--chives-state-critical); }
.chives-wb-more { margin: 4px 0 0; align-self: flex-start; }
.chives-wb-ask { position: sticky; bottom: 0; z-index: 15; display: flex; align-items: center; gap: 7px; margin-top: auto; padding: 7px 10px; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 6px; background: color-mix(in oklab, var(--chives-surface-panel) 84%, transparent); backdrop-filter: blur(9px); box-shadow: 0 -10px 26px -20px var(--chives-gold-glow); }
.chives-wb-ask:focus-within { border-color: var(--chives-gold); box-shadow: 0 0 0 2px var(--chives-gold-glow); }
.chives-wb-ask-label { color: var(--chives-gold-deep); font-size: 10px; letter-spacing: 0.08em; white-space: nowrap; }
.chives-wb-ask-input { flex: 1 1 auto; min-width: 0; appearance: none; border: 0; background: transparent; color: var(--chives-text-primary); font: inherit; font-size: 12px; padding: 2px 0; }
.chives-wb-ask-input:focus { outline: none; }
.chives-wb-ask-send { appearance: none; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 4px; background: var(--chives-surface-sunken); color: var(--chives-gold-deep); width: 24px; height: 22px; font: inherit; cursor: pointer; }
.chives-wb-ask-note { color: var(--chives-text-tertiary); font-size: 10px; white-space: nowrap; }
.chives-wb-overlay { position: fixed; inset: 0; z-index: 60; display: flex; justify-content: flex-end; background: color-mix(in oklab, var(--chives-surface-base) 55%, transparent); animation: chives-wb-fade 160ms var(--chives-ease) both; }
.chives-wb-drawer { width: min(560px, 94vw); height: 100%; display: flex; flex-direction: column; overflow: hidden; border-left: var(--chives-hairline) solid var(--chives-border-strong); background: var(--chives-surface-panel); box-shadow: -18px 0 40px -30px var(--chives-gold-glow); animation: chives-wb-slide 220ms var(--chives-ease) both; }
.chives-wb-drawer-head { padding: 10px 14px; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); align-items: center; }
.chives-wb-drawer-title { margin: 0; font-family: var(--chives-font-serif); font-size: 15px; font-weight: 500; }
.chives-wb-drawer-close { width: 24px; height: 24px; padding: 0; font-size: 15px; line-height: 1; }
.chives-wb-drawer-body { flex: 1 1 auto; overflow: auto; padding: 10px 14px 20px; display: flex; flex-direction: column; gap: 6px; }
.chives-wb-drawer-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; font-size: 12px; }
.chives-wb-drawer-meta .chives-num { font-size: 14px; }
.chives-wb-drawer-kv { display: flex; flex-wrap: wrap; gap: 3px 14px; color: var(--chives-text-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
.chives-wb-analysis { max-height: none; }
.chives-wb-drawer-alert { display: grid; grid-template-columns: 52px auto auto minmax(0, 1fr); gap: 4px 7px; align-items: baseline; appearance: none; border: 0; border-bottom: var(--chives-hairline) solid var(--chives-border-weak); background: transparent; color: inherit; font: inherit; font-size: 11px; text-align: left; padding: 3px 0; cursor: pointer; }
.chives-wb-drawer-alert:hover { background: var(--chives-surface-raised); }
.chives-wb-rank td { padding-top: 3px; padding-bottom: 3px; }
@keyframes chives-wb-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes chives-wb-slide { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: none; } }
@media (max-width: 1279px) {
  .chives-wb-body { grid-template-columns: minmax(0, 1fr); }
  .chives-wb-mover-grid { grid-template-columns: minmax(0, 1fr); }
  .chives-wb-body .chives-wb-col { display: contents; }
  .chives-wb-mover-grid.has-active { grid-template-columns: 1fr 1fr; }
  .chives-wb-mover-grid.has-active .chives-wb-mover-list:last-child { grid-column: 1 / -1; }
}
@media (max-width: 767px) {
  .chives-wb-scroll { padding: 8px 9px 0; }
  .chives-wb-focus-main { grid-template-columns: minmax(0, 1fr) auto auto; }
.chives-wb-focus-rules { grid-column: 1 / 3; grid-row: 3; }
.chives-wb-focus-add { grid-column: 3; grid-row: 3; }
  .chives-wb-focus-limit, .chives-wb-focus-rules { grid-column: 1 / -1; }
  .chives-wb-mover-grid, .chives-wb-mover-grid.has-active { grid-template-columns: 1fr; }
  .chives-wb-mover-grid.has-active .chives-wb-mover-list:last-child { grid-column: auto; }
  .chives-wb-feed-row { grid-template-columns: 46px 26px minmax(0, 1fr); }
  .chives-wb-feed-row > .chives-wb-status { grid-column: 2 / -1; justify-self: start; }
  .chives-wb-time { margin-left: 0; }
  .chives-wb-pulse { position: static; }
}
@media (hover: hover) {
  .chives-wb-index:hover .chives-wb-index-price { color: var(--chives-gold-deep); }
}

/* ---- style layer v2: heat tiers, area sparklines and status badges (all token-based) ---- */
.chives-wb-section, .chives-wb-pulse { box-shadow: inset 0 1px 0 var(--chives-hairline-color); }
.chives-wb-index { gap: 3px; padding: 8px 10px 7px; border-radius: 8px; background: var(--chives-surface-panel); border-color: var(--chives-border-weak); }
.chives-wb-index:hover { border-color: var(--chives-gold-soft); box-shadow: 0 6px 20px -14px var(--chives-gold-glow); }
.chives-wb-index-head { align-items: center; }
.chives-wb-index-name { font-size: 12px; color: var(--chives-text-secondary); font-weight: 500; }
.chives-wb-index-code { font-size: 9px; letter-spacing: 0.02em; }
.chives-wb-index-badge { display: inline-flex; align-items: center; gap: 3px; padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; background: color-mix(in oklab, currentColor 13%, transparent); }
.chives-wb-index-badge.chives-flat { background: var(--chives-surface-raised); }
.chives-wb-index-price { font-size: 22px; font-weight: 300; letter-spacing: -0.025em; }
.chives-wb-index-price.chives-tick.is-up, .chives-wb-index-price.chives-tick.is-down { font-weight: 400; }
.chives-wb-index-amount { font-size: 9px; letter-spacing: 0.02em; }
.chives-wb-spark { min-height: 34px; }
.chives-wb-spark svg { width: 100%; height: 34px; }
.chives-wb-spark .chives-spark-path { stroke: var(--chives-flat); stroke-width: 1.6; vector-effect: non-scaling-stroke; stroke-dasharray: none; animation: chives-section-in 700ms var(--chives-ease) both; }
.chives-wb-spark .chives-spark-dot { fill: var(--chives-flat); }
.chives-wb-spark.is-up .chives-spark-path { stroke: var(--chives-up); }
.chives-wb-spark.is-up .chives-spark-dot { fill: var(--chives-up); }
.chives-wb-spark.is-down .chives-spark-path { stroke: var(--chives-down); }
.chives-wb-spark.is-down .chives-spark-dot { fill: var(--chives-down); }
.chives-spark-stop-top { stop-color: var(--chives-flat); stop-opacity: 0.30; }
.chives-spark-stop-bottom { stop-color: var(--chives-flat); stop-opacity: 0; }
.chives-wb-spark.is-up .chives-spark-stop-top, .chives-wb-spark.is-up .chives-spark-stop-bottom { stop-color: var(--chives-up); }
.chives-wb-spark.is-down .chives-spark-stop-top, .chives-wb-spark.is-down .chives-spark-stop-bottom { stop-color: var(--chives-down); }
.chives-spark-area { animation: chives-section-in 700ms var(--chives-ease) both; }
.chives-wb-switch { gap: 0; margin-left: auto; border: var(--chives-hairline) solid var(--chives-border-strong); border-radius: 999px; overflow: hidden; background: var(--chives-surface-sunken); }
.chives-wb-switch .chives-wb-toggle { border: 0; border-radius: 0; padding: 2px 11px; font-size: 11px; background: transparent; color: var(--chives-text-tertiary); }
.chives-wb-switch .chives-wb-toggle.is-active { background: var(--chives-surface-panel); color: var(--chives-text-primary); font-weight: 600; box-shadow: inset 0 -2px 0 var(--chives-gold); }
.chives-wb-section-head .chives-wb-label { font-size: 11px; color: var(--chives-text-secondary); letter-spacing: 0.08em; }
.chives-treemap { container-type: inline-size; aspect-ratio: 2 / 1; max-height: 460px; border-radius: 8px; background: var(--chives-surface-base); border-color: var(--chives-border-weak); }
.chives-tile { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 2px 4px; border: 1px solid var(--chives-surface-base); border-radius: 2px; gap: 1px; }
.chives-tile-name { max-width: 100%; font-size: clamp(11px, var(--tile-fs, 1.4cqw), 26px); font-weight: 600; line-height: 1.15; }
.chives-tile-name { white-space: normal; word-break: break-all; overflow-wrap: anywhere; text-overflow: clip; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; }
.chives-tile-move { font-size: clamp(10px, calc(var(--tile-fs, 1.4cqw) * 0.88), 22px); font-weight: 500; line-height: 1.15; opacity: 0.92; }
.chives-tile-amount { font-size: clamp(9px, calc(var(--tile-fs, 1.4cqw) * 0.62), 13px); opacity: 0.7; }
.chives-tile.is-hover { transform: none; box-shadow: inset 0 0 0 2px var(--chives-gold); }
.chives-heat-legend { display: flex; align-items: center; justify-content: center; gap: 2px; margin-top: 2px; }
.chives-heat-legend-item { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 34px; }
.chives-heat-swatch { display: block; width: 100%; height: 6px; border-radius: 1px; }
.chives-heat-legend-text { color: var(--chives-text-tertiary); font-size: 9px; font-variant-numeric: tabular-nums; }
.chives-wb-mover-head { padding-bottom: 5px; }
.chives-wb-mover-row { padding: 6px 2px; font-size: 12px; border-radius: 4px; }
.chives-wb-mover-rank { font-size: 10px; }
.chives-wb-mover-change { font-weight: 600; }
.chives-wb-focus-row { padding: 8px 6px; border-radius: 6px; border-bottom-color: var(--chives-border-weak); }
.chives-wb-focus-name { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; }
.chives-wb-focus-name-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-wb-avatar { flex: none; display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; font-size: 11px; font-weight: 700; color: var(--chives-cat-1); background: color-mix(in oklab, var(--chives-cat-1) 18%, transparent); }
.chives-wb-avatar.is-tone-1 { color: var(--chives-cat-3); background: color-mix(in oklab, var(--chives-cat-3) 18%, transparent); }
.chives-wb-avatar.is-tone-2 { color: var(--chives-cat-4); background: color-mix(in oklab, var(--chives-cat-4) 18%, transparent); }
.chives-wb-avatar.is-tone-3 { color: var(--chives-cat-5); background: color-mix(in oklab, var(--chives-cat-5) 18%, transparent); }
.chives-wb-avatar.is-tone-4 { color: var(--chives-cat-6); background: color-mix(in oklab, var(--chives-cat-6) 18%, transparent); }
.chives-wb-avatar.is-tone-5 { color: var(--chives-cat-8); background: color-mix(in oklab, var(--chives-cat-8) 18%, transparent); }
.chives-wb-focus-price { font-size: 13px; font-weight: 500; }
.chives-wb-focus-change { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px; background: color-mix(in oklab, currentColor 13%, transparent); }
.chives-wb-label { font-size: 10px; }
.chives-wb-focus-main { grid-template-columns: minmax(0, 1fr) auto auto; }
.chives-wb-focus-rules { grid-column: 1 / 3; grid-row: 3; }
.chives-wb-focus-add { grid-column: 3; grid-row: 3; }
.chives-wb-focus-limit { grid-column: 1 / -1; grid-row: 2; text-align: left; font-size: 10px; }
.chives-wb-focus-rules { grid-column: 1 / 3; grid-row: 3; gap: 3px; }
.chives-wb-focus-add { grid-column: 3; grid-row: 3; justify-self: end; align-self: center; }
/* ---- style layer v3: Apple look (system font, large continuous radii, glass, solid pills, inset separators) ---- */
.chives-wb, .chives-watch { font-family: var(--chives-font-sans); -webkit-font-smoothing: antialiased; letter-spacing: -0.003em; gap: 14px; }
.chives-wb-section, .chives-wb-pulse { border: 0; border-radius: var(--chives-radius-card); box-shadow: var(--chives-shadow-card); }
.chives-wb-section { padding: 14px 16px 16px; gap: 10px; background: var(--chives-surface-panel); }
.chives-wb-pulse { padding: 12px 14px 12px; gap: 10px; background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); }
.chives-wb-section-head .chives-wb-label, .chives-wb-pulse .chives-wb-label { font-size: 15px; font-weight: 600; letter-spacing: -0.012em; text-transform: none; color: var(--chives-text-primary); }
.chives-wb-meta, .chives-wb-summary-age, .chives-wb-summary-note { font-size: 11px; }
.chives-wb-index { border: 0; border-radius: var(--chives-radius-inner); background: var(--chives-surface-raised); padding: 10px 12px 9px; gap: 4px; box-shadow: none; }
.chives-wb-index:hover { box-shadow: none; background: var(--chives-surface-sunken); }
.chives-wb-index-name { font-size: 12px; font-weight: 600; color: var(--chives-text-primary); }
.chives-wb-index-code { font-weight: 400; color: var(--chives-text-tertiary); }
.chives-wb-index-badge { padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; background: var(--chives-fill); color: var(--chives-text-secondary); }
.chives-wb-index-badge.chives-up { background: var(--chives-up); color: var(--chives-on-color); }
.chives-wb-index-badge.chives-down { background: var(--chives-down); color: var(--chives-on-color); }
.chives-wb-index-price { font-size: 24px; font-weight: 600; letter-spacing: -0.03em; }
.chives-wb-index-amount { font-size: 10px; }
.chives-wb-spark .chives-spark-path { stroke-width: 1.75; }
.chives-wb-switch { border: 0; border-radius: 9px; padding: 2px; background: var(--chives-fill); overflow: visible; gap: 0; }
.chives-wb-switch .chives-wb-toggle { border-radius: 7px; padding: 3px 12px; font-size: 12px; font-weight: 500; color: var(--chives-text-secondary); box-shadow: none; }
.chives-wb-switch .chives-wb-toggle.is-active { background: var(--chives-surface-panel); color: var(--chives-text-primary); font-weight: 600; box-shadow: var(--chives-shadow-card); }
.chives-wb-chip, .chives-wb-filter, .chives-wb-more, .chives-wb-add { border: 0; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); padding: 3px 11px; font-size: 11px; font-weight: 500; transition: background var(--chives-dur-fast) var(--chives-ease), color var(--chives-dur-fast) var(--chives-ease); }
.chives-wb-chip:hover, .chives-wb-filter:hover, .chives-wb-more:hover, .chives-wb-add:hover { background: var(--chives-surface-sunken); color: var(--chives-text-primary); }
.chives-wb-chip.is-active, .chives-wb-filter.is-active { background: var(--chives-text-primary); color: var(--chives-surface-panel); }
.chives-wb-headline { font-size: 13px; line-height: 1.5; }
.chives-wb-headline-title { font-weight: 600; }
.chives-wb-mover-head { border-bottom: 0; padding-bottom: 6px; font-size: 12px; font-weight: 600; }
.chives-wb-mover-row { padding: 8px 4px; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); border-radius: 0; font-size: 13px; }
.chives-wb-mover-row:last-child { border-bottom: 0; }
.chives-wb-mover-row:hover { background: var(--chives-surface-raised); border-radius: 8px; }
.chives-wb-mover-change { min-width: 62px; padding: 2px 7px; border-radius: 7px; font-size: 12px; font-weight: 600; text-align: center; background: var(--chives-fill); }
.chives-wb-mover-change.chives-up { background: var(--chives-up); color: var(--chives-on-color); }
.chives-wb-mover-change.chives-down { background: var(--chives-down); color: var(--chives-on-color); }
.chives-wb-focus-row { padding: 10px 8px; border-radius: 12px; border: 0; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-wb-focus-row:last-child { border-bottom: 0; }
.chives-wb-focus-row:hover { background: var(--chives-surface-raised); }
.chives-wb-focus-row.is-triggered { background: color-mix(in oklab, var(--chives-gold) 9%, transparent); box-shadow: inset 3px 0 0 var(--chives-gold); }
.chives-wb-focus-change { padding: 2px 8px; border-radius: 7px; font-size: 12px; font-weight: 600; background: var(--chives-fill); }
.chives-wb-focus-change.chives-up { background: var(--chives-up); color: var(--chives-on-color); }
.chives-wb-focus-change.chives-down { background: var(--chives-down); color: var(--chives-on-color); }
.chives-treemap { border: 0; border-radius: var(--chives-radius-inner); background: var(--chives-surface-panel); }
.chives-tile { border: 1.5px solid var(--chives-surface-panel); border-radius: 8px; font-family: var(--chives-font-sans); }
.chives-tile.is-strong { color: var(--chives-on-color); }
.chives-tile-name { font-weight: 600; letter-spacing: -0.01em; }
.chives-tile.is-hover { box-shadow: inset 0 0 0 2px var(--chives-text-primary); }
.chives-heat-swatch { border-radius: 3px; height: 5px; }
.chives-wb-ask { padding: 8px 8px 8px 16px; border: 0; border-radius: 999px; background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); }
.chives-wb-ask:focus-within { box-shadow: var(--chives-shadow-card), 0 0 0 2px var(--chives-gold); }
.chives-wb-ask-send { border-radius: 999px; background: var(--chives-gold); color: var(--chives-on-color); border: 0; }
.chives-wb-drawer { border-left: 0; border-radius: 22px 0 0 22px; background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); }
.chives-wb-drawer-close { border: 0; border-radius: 999px; background: var(--chives-fill); }
.chives-wb-banner { border: 0; border-radius: 10px; background: var(--chives-fill); }
.chives-wb-avatar { font-weight: 600; }
.chives-table th { font-weight: 500; color: var(--chives-text-tertiary); border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-table td { border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); }
.chives-badge, .chives-chip, .chives-tag { border-radius: 999px; border: 0; background: var(--chives-fill); color: var(--chives-text-secondary); }
.chives-chip.is-armed { background: color-mix(in oklab, var(--chives-gold) 16%, transparent); color: var(--chives-gold-deep); }

/* ---- T100 watch page: signal cards, fund flows, rules badge, area switch ---- */
.chives-wb-signalbar { grid-column: 1 / -1; display: flex; align-items: center; gap: 10px; justify-content: flex-end; padding: 0 2px; }
.chives-wb-signalbar .chives-wb-chips { margin-left: 0; }
.chives-wb-decide-wrap { grid-column: 1 / -1; }
.chives-wb-decide { background: var(--chives-surface-panel); }
.chives-sig-hero { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.chives-sig-rail { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.chives-sig-card { --chives-sig-c: var(--chives-sig-info); position: relative; display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 14px 15px 12px; border-radius: var(--chives-radius-card); background: var(--chives-surface-panel); box-shadow: var(--chives-shadow-card); animation: chives-sig-in var(--chives-dur-slow) var(--chives-ease) both; transition: transform var(--chives-dur-base) var(--chives-ease), box-shadow var(--chives-dur-base) var(--chives-ease), opacity var(--chives-dur-base) var(--chives-ease); }
.chives-sig-card::before { content: ''; position: absolute; inset: 0; pointer-events: none; border-radius: inherit; background: radial-gradient(120% 90% at 0% 0%, color-mix(in oklab, var(--chives-sig-c) 14%, transparent), transparent 60%); }
.chives-sig-card.is-hero { padding: 16px 17px 14px; box-shadow: var(--chives-shadow-card), 0 0 0 1px color-mix(in oklab, var(--chives-sig-c) 28%, transparent); }
.chives-sig-card:hover { transform: translateY(-2px); }
.chives-sig-card.is-leaving { opacity: 0; transform: scale(0.96); }
.chives-sig-top { position: relative; display: flex; align-items: center; gap: 8px; min-width: 0; }
.chives-sig-ico { width: 26px; height: 26px; flex: none; border-radius: 8px; display: grid; place-items: center; font-size: 13px; color: var(--chives-sig-c); background: color-mix(in oklab, var(--chives-sig-c) 16%, transparent); }
.chives-sig-type { font-size: 12px; font-weight: 600; color: var(--chives-sig-c); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-sig-time { margin-left: auto; font-size: 11px; color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; }
.chives-sig-new { width: 7px; height: 7px; flex: none; border-radius: 50%; background: var(--chives-sig-c); animation: chives-sig-pulse 2200ms ease-out infinite; }
.chives-sig-title { position: relative; font-size: 17px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.25; }
.chives-sig-card.is-hero .chives-sig-title { font-size: 19px; }
.chives-sig-chips { position: relative; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chives-sig-dir { display: inline-flex; align-items: center; gap: 3px; padding: 2px 9px; border-radius: 8px; font-size: 11.5px; font-weight: 600; color: var(--chives-on-color); }
.chives-sig-dir.is-bull { background: var(--chives-up); }
.chives-sig-dir.is-bear { background: var(--chives-down); }
.chives-sig-dir.is-flat { background: var(--chives-fill); color: var(--chives-text-secondary); }
.chives-sig-tag { padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 500; background: var(--chives-fill); color: var(--chives-text-secondary); }
.chives-sig-tag.is-code { font-variant-numeric: tabular-nums; }
.chives-sig-tag.is-merged { color: var(--chives-sig-info); }
.chives-sig-concl { position: relative; margin: 0; font-size: 13.5px; line-height: 1.5; color: var(--chives-text-primary); }
.chives-sig-brief { position: relative; margin: 0; font-size: 12.5px; color: var(--chives-text-secondary); line-height: 1.55; }
.chives-sig-ctx { position: relative; padding: 10px 12px; border-radius: var(--chives-radius-inner); background: var(--chives-surface-raised); }
.chives-sig-ctx-head { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--chives-text-tertiary); margin-bottom: 8px; }
.chives-sig-range { position: relative; height: 6px; border-radius: 3px; background: var(--chives-surface-sunken); margin: 14px 4px 20px; }
.chives-sig-zone { position: absolute; top: 0; bottom: 0; border-radius: 3px; background: color-mix(in oklab, var(--chives-sig-plan) 55%, transparent); }
.chives-sig-marker { position: absolute; top: -4px; width: 2px; height: 14px; border-radius: 1px; background: var(--chives-sig-risk); }
.chives-sig-marker.is-giveup { background: var(--chives-sig-risk); }
.chives-sig-marker span, .chives-sig-price span { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); font-size: 10px; white-space: nowrap; color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; }
.chives-sig-price { position: absolute; top: -5px; width: 16px; height: 16px; margin-left: -8px; border-radius: 50%; box-sizing: border-box; background: var(--chives-surface-panel); border: 3px solid var(--chives-text-primary); box-shadow: 0 0 0 4px color-mix(in oklab, var(--chives-text-primary) 12%, transparent); transition: left 600ms var(--chives-ease); }
.chives-sig-price span { top: -22px; color: var(--chives-text-primary); font-weight: 700; font-size: 11px; }
.chives-sig-rank-row { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--chives-text-secondary); }
.chives-sig-rank-big { font-size: 22px; font-weight: 700; color: var(--chives-text-primary); letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.chives-sig-arrow { color: var(--chives-sig-sector); font-weight: 700; }
.chives-sig-rank-share { margin-left: auto; font-variant-numeric: tabular-nums; }
.chives-sig-spark { display: block; width: 100%; height: 36px; }
.chives-sig-spark path { stroke: var(--chives-sig-sector); stroke-width: 2; }
.chives-sig-src { position: relative; font-size: 11px; color: var(--chives-text-tertiary); }
.chives-sig-acts { position: relative; display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
.chives-sig-btn { appearance: none; border: 0; font: inherit; font-size: 12px; font-weight: 600; padding: 5px 12px; border-radius: 999px; cursor: pointer; background: var(--chives-fill); color: var(--chives-text-primary); transition: background var(--chives-dur-fast) var(--chives-ease), transform var(--chives-dur-fast) var(--chives-ease); }
.chives-sig-btn:hover { background: var(--chives-surface-sunken); }
.chives-sig-btn:active { transform: scale(0.97); }
.chives-sig-btn:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-sig-btn.is-primary { background: var(--chives-sig-c); color: var(--chives-on-color); }
.chives-sig-btn.is-primary:hover { background: var(--chives-sig-c); filter: brightness(1.08); }
.chives-sig-btn.is-small { padding: 2px 9px; font-size: 11px; }
.chives-sig-snooze { position: relative; }
.chives-sig-menu { position: absolute; bottom: calc(100% + 6px); left: 0; z-index: 5; min-width: 150px; padding: 6px; border-radius: var(--chives-radius-inner); background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); display: none; }
.chives-sig-menu.is-open { display: block; }
.chives-sig-menu button { display: block; width: 100%; text-align: left; appearance: none; border: 0; background: transparent; color: var(--chives-text-primary); font: inherit; font-size: 12.5px; padding: 7px 10px; border-radius: 8px; cursor: pointer; }
.chives-sig-menu button:hover { background: var(--chives-fill); }
.chives-sig-done { display: flex; flex-direction: column; gap: 6px; }
.chives-sig-done-fold { display: flex; align-items: center; gap: 12px; width: 100%; appearance: none; border: 0; text-align: left; padding: 12px 14px; border-radius: var(--chives-radius-inner); background: var(--chives-surface-panel); box-shadow: var(--chives-shadow-card); font: inherit; font-size: 13px; color: var(--chives-text-secondary); cursor: pointer; }
.chives-sig-done-chevron { margin-left: auto; color: var(--chives-text-tertiary); }
.chives-sig-done-list { display: flex; flex-direction: column; gap: 2px; padding: 2px 4px; }
.chives-sig-done-row { display: grid; grid-template-columns: 56px auto minmax(0, 1fr) auto auto; gap: 6px 8px; align-items: baseline; padding: 5px 4px; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); opacity: 0.62; font-size: 11px; }
.chives-sig-done-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-sig-done-row .chives-sig-type.is-plan { color: var(--chives-sig-plan); }
.chives-sig-done-row .chives-sig-type.is-opp { color: var(--chives-sig-opp); }
.chives-sig-done-row .chives-sig-type.is-risk { color: var(--chives-sig-risk); }
.chives-sig-done-row .chives-sig-type.is-sector { color: var(--chives-sig-sector); }
.chives-sig-done-row .chives-sig-type.is-info { color: var(--chives-sig-info); }
.chives-sig-raw { border-top: var(--chives-hairline) dashed var(--chives-border-weak); padding-top: 6px; }
.chives-sig-raw summary { cursor: pointer; color: var(--chives-text-tertiary); font-size: 11px; }
.chives-sig-raw-list { display: flex; flex-direction: column; }
.chives-sig-raw-row { display: grid; grid-template-columns: 56px 90px minmax(0, 1fr) auto; gap: 4px 8px; align-items: baseline; padding: 3px 2px; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); font-size: 11px; }
.chives-sig-raw-object { color: var(--chives-text-secondary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-sig-raw-title { color: var(--chives-text-tertiary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-sig-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: var(--chives-sig-info); }
.chives-sig-dot.is-plan { background: var(--chives-sig-plan); }
.chives-sig-dot.is-opp { background: var(--chives-sig-opp); }
.chives-sig-dot.is-risk { background: var(--chives-sig-risk); }
.chives-sig-dot.is-sector { background: var(--chives-sig-sector); }
.chives-sig-dot.is-info { background: var(--chives-sig-info); }
.chives-sig-toast { position: sticky; bottom: 64px; z-index: 40; align-self: center; display: flex; align-items: center; gap: 12px; padding: 9px 15px; border-radius: 999px; background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); font-size: 13px; }
.chives-sig-toast button { appearance: none; border: 0; background: transparent; color: var(--chives-gold-deep); font: inherit; font-weight: 600; cursor: pointer; }
.chives-wb-focus-rules { position: relative; display: inline-flex; flex-wrap: wrap; align-items: center; gap: 3px; min-width: 0; }
.chives-wb-rules-badge { appearance: none; border: 0; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); padding: 1px 8px; font: inherit; font-size: 10px; cursor: pointer; }
.chives-wb-rules-badge:hover { color: var(--chives-text-primary); background: var(--chives-surface-sunken); }
.chives-wb-rules-badge:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: 1px; }
.chives-wb-rules-pop { display: none; position: absolute; right: 0; top: calc(100% + 4px); z-index: 9; min-width: 260px; max-width: 340px; padding: 7px; border-radius: var(--chives-radius-inner); background: var(--chives-glass); -webkit-backdrop-filter: var(--chives-glass-blur); backdrop-filter: var(--chives-glass-blur); box-shadow: var(--chives-shadow-card); }
.chives-wb-focus-rules:hover .chives-wb-rules-pop, .chives-wb-focus-rules:focus-within .chives-wb-rules-pop, .chives-wb-focus-rules.is-open .chives-wb-rules-pop { display: block; }
.chives-wb-rule-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 8px; align-items: baseline; padding: 3px 4px; font-size: 10px; }
.chives-wb-rule-desc { color: var(--chives-text-secondary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-wb-rule-state { color: var(--chives-text-tertiary); white-space: nowrap; }
.chives-wb-rule-state.is-armed { color: var(--chives-gold-deep); }
.chives-chip.is-triggered { border-color: transparent; background: color-mix(in oklab, var(--chives-sig-plan) 16%, transparent); color: var(--chives-sig-plan); font-weight: 600; }
.chives-wb-focus-signal { display: flex; align-items: baseline; gap: 5px; min-width: 0; padding-left: 2px; }
.chives-wb-focus-signal-button { display: flex; align-items: center; gap: 6px; min-width: 0; width: 100%; appearance: none; border: 0; background: transparent; color: var(--chives-text-secondary); font: inherit; font-size: 11px; text-align: left; padding: 1px 0; cursor: pointer; }
.chives-wb-focus-signal-button:hover .chives-wb-focus-signal-text { color: var(--chives-text-primary); }
.chives-wb-focus-signal-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-wb-focus-signal-time { margin-left: auto; color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; }
.chives-wb-signal-title { margin: 2px 0 0; font-size: 18px; line-height: 1.3; letter-spacing: -0.02em; }
.chives-wb-signal-sections { display: flex; flex-direction: column; gap: 8px; }
.chives-wb-signal-sections p { margin: 2px 0 0; font-size: 13px; line-height: 1.6; color: var(--chives-text-secondary); }
.chives-wb-signal-sections ul { margin: 2px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.6; color: var(--chives-text-secondary); }
.chives-flow-headline { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.chives-flow-def { color: var(--chives-text-tertiary); font-size: 10px; }
.chives-flow-north { margin-left: auto; color: var(--chives-text-secondary); font-size: 10px; font-variant-numeric: tabular-nums; }
.chives-flow-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; }
.chives-flow-grid.has-more { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.chives-flow-col { min-width: 0; }
.chives-flow-head { display: flex; justify-content: space-between; align-items: baseline; padding-bottom: 4px; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); font-size: 11px; font-weight: 600; color: var(--chives-text-secondary); }
.chives-flow-rows { list-style: none; margin: 0; padding: 0; }
.chives-flow-row { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 1px 5px; align-items: baseline; width: 100%; appearance: none; border: 0; border-bottom: var(--chives-hairline) solid var(--chives-hairline-color); background: transparent; color: inherit; font: inherit; font-size: 11px; text-align: left; padding: 4px 2px; cursor: pointer; }
.chives-flow-row:hover { background: var(--chives-surface-raised); border-radius: 6px; }
.chives-flow-row:focus-visible { outline: 2px solid var(--chives-gold); outline-offset: -2px; }
.chives-flow-row:disabled { cursor: default; }
.chives-flow-row.is-stale { opacity: 0.55; }
.chives-flow-rank { color: var(--chives-text-tertiary); font-variant-numeric: tabular-nums; text-align: right; }
.chives-flow-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chives-flow-net, .chives-flow-change { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.chives-flow-net.is-up { color: var(--chives-up); font-weight: 600; }
.chives-flow-net.is-down { color: var(--chives-down); font-weight: 600; }
.chives-flow-net.is-flat { color: var(--chives-flat); }
.chives-flow-change.is-up { color: var(--chives-up); }
.chives-flow-change.is-down { color: var(--chives-down); }
.chives-flow-change.is-flat { color: var(--chives-flat); }
@keyframes chives-sig-in { from { opacity: 0; transform: translateY(10px) scale(0.985); } to { opacity: 1; transform: none; } }
@keyframes chives-sig-pulse { 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@media (max-width: 1279px) {
  .chives-sig-hero { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .chives-flow-grid.has-more { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .chives-wb-signalbar { justify-content: flex-start; }
}
@media (max-width: 767px) {
  .chives-sig-hero, .chives-sig-rail { grid-template-columns: minmax(0, 1fr); }
  .chives-flow-grid, .chives-flow-grid.has-more { grid-template-columns: minmax(0, 1fr); }
  .chives-sig-done-row { grid-template-columns: 52px auto minmax(0, 1fr) auto; }
  .chives-sig-done-row .chives-sig-btn { grid-column: 4; grid-row: 1; }
  .chives-wb-rules-pop { right: auto; left: 0; min-width: 220px; }
}

@media (prefers-reduced-motion: reduce) { .chives-spark-area { animation: none; } }
@media (prefers-reduced-motion: reduce) {
  .chives-watch *, .chives-watch *::before, .chives-watch *::after,
  .chives-wb *, .chives-wb *::before, .chives-wb *::after {
    animation: none !important;
    transition: none !important;
    transform: none !important;
    scroll-behavior: auto !important;
  }
}

/* ---- per-stock intraday sparkline in the focus rows ---- */
.chives-wb-focus-main { grid-template-columns: minmax(0, 1fr) 64px auto auto; }
.chives-wb-focus-spark { display: block; width: 64px; min-height: 22px; align-self: center; }
.chives-wb-focus-spark .chives-wb-spark { min-height: 22px; }
.chives-wb-focus-limit { grid-column: 1 / -1; }
.chives-wb-focus-rules { grid-column: 1 / 4; }
.chives-wb-focus-add { grid-column: 4; }

/* ---- battle-card chip on focus rows ---- */
.chives-wb-cardchip { appearance: none; border: 0; padding: 1px 9px; border-radius: 999px; background: var(--chives-fill); color: var(--chives-text-secondary); font: inherit; font-size: 10px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.chives-wb-cardchip.is-proposed { background: color-mix(in oklab, var(--chives-gold) 20%, transparent); color: var(--chives-gold-deep); }
.chives-wb-cardchip.is-await_confirm { background: color-mix(in oklab, var(--chives-sig-plan) 20%, transparent); color: var(--chives-gold-deep); }
.chives-wb-cardchip.is-execute { background: var(--chives-sig-opp); color: var(--chives-on-color); }
.chives-wb-cardchip.is-abandon, .chives-wb-cardchip.is-exit { background: var(--chives-sig-risk); color: var(--chives-on-color); }
`

/** Insert the panel sheet; the returned disposer removes it. */
export function insertPanelStyles(): () => void {
  if (typeof document === 'undefined') return () => {}
  const tag = document.createElement('style')
  tag.dataset.chives = 'watch-panel'
  tag.textContent = PANEL_CSS
  document.head.append(tag)
  return () => { tag.remove() }
}
