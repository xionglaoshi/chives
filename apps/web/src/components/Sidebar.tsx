import { useEffect, useId, useRef, useState, type CSSProperties, type ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { workbenchTools, type WorkbenchTool } from '../utils/routes';
import { Logo } from '../brand/Logo';
import { BotList, BotRail } from './BotList';
import { desk, type Preferences } from './deskApi';
import './Sidebar.css';

type QuickTool = Exclude<WorkbenchTool, 'portrait' | 'strategies'>;

const toolIds: QuickTool[] = ['market', 'trends', 'holdings', 'watchlist'];

const widthKey = 'chives.sidebar.width';
const defaultWidth = 264;
const maxWidth = 420;

function minimumSidebarWidth(nav: HTMLElement): number {
  const style = getComputedStyle(nav);
  const pixels = (value: string) => Number.parseFloat(value) || 0;
  const borderAndPadding = pixels(style.borderInlineEndWidth) + pixels(style.borderInlineStartWidth);
  let minimum = 0;
  for (const button of nav.querySelectorAll('.desk-shortcuts button')) {
    const label = button.querySelector('span');
    const icon = button.querySelector('svg');
    if (!label || !icon) continue;
    const buttonStyle = getComputedStyle(button);
    minimum = Math.max(minimum, label.getBoundingClientRect().width + icon.getBoundingClientRect().width +
      pixels(buttonStyle.paddingInlineStart) + pixels(buttonStyle.paddingInlineEnd) + pixels(buttonStyle.columnGap));
  }
  // Compact mode removes the outer padding to center the icons.
  const padding = nav.classList.contains('sidebar--compact')
    ? 2 * pixels(style.getPropertyValue('--space-6'))
    : pixels(style.paddingInlineStart) + pixels(style.paddingInlineEnd);
  return Math.ceil(minimum + padding + borderAndPadding + 1);
}

const toolOrderKey = 'chives.sidebar.toolOrder';
function readToolOrder(): QuickTool[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(toolOrderKey) ?? 'null');
    if (Array.isArray(saved)) {
      const known = saved.filter((id): id is QuickTool => toolIds.includes(id));
      if (!known.includes('watchlist') && known.includes('holdings')) known.splice(known.indexOf('holdings')+1,0,'watchlist');
      return [...new Set<QuickTool>(['market', ...known, ...toolIds])];
    }
  } catch { /* Use the default order when storage is unavailable. */ }
  return toolIds;
}

export interface SidebarProps {
  bots: BotSummary[];
  selectedId: string | null;
  loading: boolean;
  /** Collapse the list to an avatar rail while a deliverable preview is open. */
  compact?: boolean;
  phone?: boolean;
  onHome?: () => void;
  /** True while the all-bots overview is the current route. */
  allBotsActive?: boolean;
  /** True while the settings page is the current route. */
  settingsActive?: boolean;
  onSelect: (botId: string) => void;
  activeTool: WorkbenchTool | null;
  onTool: (tool:WorkbenchTool)=>void;
  onMove: (source:string,target:string)=>void;
  onShowAll: () => void;
  onOpenSettings: () => void;
}

function SidebarSkeleton(): ReactElement {
  return (
    <div className="sidebar__skeleton" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <div className="sidebar__skeleton-row" key={index}>
          <span className="skeleton sidebar__skeleton-avatar" />
          <span className="skeleton sidebar__skeleton-line" />
        </div>
      ))}
    </div>
  );
}

export function Sidebar({
  bots,
  selectedId,
  loading,
  compact: previewOpen = false,
  phone = false, onHome,
  allBotsActive = false,
  settingsActive = false,
  activeTool, onTool, onMove,
  onSelect,
  onShowAll,
  onOpenSettings
}: SidebarProps): ReactElement {
  const accountMenu = useRef<HTMLDivElement>(null);
  const accountButton = useRef<HTMLButtonElement>(null);
  const accountMenuId = useId();
  const [profile, setProfile] = useState<Pick<Preferences, 'name' | 'avatar'> | null>(null);
  const [brokenAvatar, setBrokenAvatar] = useState('');
  useEffect(() => {
    let active = true;
    void desk<Preferences>('prefs').then(({ name, avatar }) => {
      if (active) setProfile({ name, avatar });
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  const displayName = profile?.name.trim() || '无名老韭菜';
  const avatar = profile?.avatar && profile.avatar !== brokenAvatar ? profile.avatar : '';
  function positionAccountMenu() {
    const panel = accountMenu.current;
    const anchor = accountButton.current?.getBoundingClientRect();
    if (!panel || !anchor) return;
    const width = Math.min(Math.max(anchor.width, 172), innerWidth - 16);
    panel.style.setProperty('--account-left', `${Math.max(8, Math.min(anchor.left, innerWidth - width - 8))}px`);
    panel.style.setProperty('--account-bottom', `${innerHeight - anchor.top + 6}px`);
    panel.style.setProperty('--account-width', `${width}px`);
  }
  function chooseAccountAction(action: () => void) {
    accountMenu.current?.hidePopover();
    action();
  }

  const navRef = useRef<HTMLElement>(null);
  const resize = useRef<{ x: number; width: number; minimum: number } | null>(null);
  const [width, setWidth] = useState(() => {
    try { return Math.max(72, Math.min(maxWidth, Number(localStorage.getItem(widthKey)) || defaultWidth)); }
    catch { return defaultWidth; }
  });
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('chives.sidebar.collapsed') === 'true'; } catch { return false; }
  });
  const [previewExpanded, setPreviewExpanded] = useState(false);
  useEffect(() => { if (!previewOpen) setPreviewExpanded(false); }, [previewOpen]);
  const compact = !phone && (previewOpen ? !previewExpanded : collapsed);
  const toggleLabel = compact ? '展开侧边栏' : '收起侧边栏';
  function toggleSidebar() {
    if (previewOpen) { setPreviewExpanded(!previewExpanded); return; }
    setCollapsed(!collapsed);
    try { localStorage.setItem('chives.sidebar.collapsed', String(!collapsed)); } catch { /* Session state remains usable. */ }
  }
  function resizeSidebar(requested: number, minimum: number) {
    const nextCollapsed = requested < minimum;
    if (previewOpen) setPreviewExpanded(!nextCollapsed);
    else {
      setCollapsed(nextCollapsed);
      try { localStorage.setItem('chives.sidebar.collapsed', String(nextCollapsed)); } catch { /* Optional persistence. */ }
    }
    if (!nextCollapsed) {
      const nextWidth = Math.max(minimum, Math.min(maxWidth, Math.floor(innerWidth * 0.45), Math.round(requested)));
      setWidth(nextWidth);
      try { localStorage.setItem(widthKey, String(nextWidth)); } catch { /* Optional persistence. */ }
    }
  }

  const [order, setOrder] = useState(readToolOrder);
  function moveTool(source: string, target: QuickTool) {
    const from = order.findIndex(id => id === source);
    if (source === 'market' || target === 'market' || from < 0 || source === target) return;
    const next = [...order];
    next.splice(from, 1);
    next.splice(order.indexOf(target), 0, order[from]!);
    setOrder(next);
    try { localStorage.setItem(toolOrderKey, JSON.stringify(next)); } catch { /* Keep the in-session order. */ }
  }
  return (
    <nav ref={navRef} className={`sidebar${compact ? ' sidebar--compact' : ''}${!compact && width < 175 ? ' sidebar--narrow' : ''}`}
      aria-label="Bot 列表" style={{ '--sidebar-width': `${width}px` } as CSSProperties}>
      <div className="sidebar__brand">
        <a className="sidebar__home" onClick={onHome} href="#/workspace/market" aria-label={`Chives，打开${workbenchTools.market}`} title={workbenchTools.market}>
          <Logo size={28} title="Chives" />
          <span className="sidebar__wordmark">Chives</span>
        </a>
        {!phone && <button type="button" className="sidebar__toggle" aria-expanded={!compact}
          aria-label={toggleLabel} title={toggleLabel} onClick={toggleSidebar}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="2.5" y="4" width="19" height="16" rx="3"/><path d="M8.5 4v16"/>
            <path d={compact ? 'm13 9 3 3-3 3' : 'm16 9-3 3 3 3'}/>
          </svg>
        </button>}
      </div>
      <section className="desk-shortcuts" aria-label="快速工具">
        <h2 className="bot-list__heading">快速工具</h2>
        {order.map((key,index)=><div className="sidebar-tool-row" key={key}
          onDragOver={event => { if (key !== 'market' && event.dataTransfer.types.includes('text/chives-tool')) event.preventDefault(); }}
          onDrop={event => {
            const source = event.dataTransfer.getData('text/chives-tool');
            if (source) { event.preventDefault(); moveTool(source,key); }
          }}>
          <button type="button" draggable={key !== 'market'} onDragStart={event => {
            event.dataTransfer.setData('text/chives-tool',key);
            event.dataTransfer.effectAllowed = 'move';
          }} onKeyDown={event => {
            if (key === 'market' || !event.altKey || !['ArrowUp','ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            const target = order[index + (event.key === 'ArrowUp' ? -1 : 1)];
            if (target) moveTool(key,target);
          }}
          title={workbenchTools[key] + (key === 'market' ? '' : ' · 拖动排序，或按 Alt 加上下方向键')} aria-label={workbenchTools[key]} aria-current={activeTool===key?'page':undefined}
          onClick={()=>onTool(key)}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d={{watchlist:'M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z',holdings:'M3 7h18v13H3z M8 7V4h8v3 M3 12c5 3 13 3 18 0 M11 13h2',market:'M3 4v16h18 M6 15l4-5 4 3 6-8',trends:'M13 3c1 5 6 6 6 12a7 7 0 0 1-14 0c0-3 2-6 4-8 0 4 1 5 2 5 2-2 3-5 2-9z'}[key]}/>
          </svg><span>{workbenchTools[key]}</span>
        </button></div>)}
      </section>
      {loading && bots.length === 0 ? (
        <SidebarSkeleton />
      ) : compact ? (
        <BotRail bots={bots} selectedId={selectedId} onSelect={onSelect} />
      ) : (
        <BotList onMove={onMove} bots={bots} selectedId={selectedId} onSelect={onSelect} />
      )}
      <div className="sidebar__footer">
        <button type="button" className="sidebar__account" ref={accountButton}
          aria-label={displayName} title={displayName} {...{ popovertarget: accountMenuId }}
          onClick={positionAccountMenu}>
          {avatar ? <img className="sidebar__account-avatar" src={avatar} alt=""
            onError={() => setBrokenAvatar(avatar)} /> :
            <svg className="sidebar__account-avatar sidebar__account-avatar--default" viewBox="0 0 32 32" aria-hidden="true">
              <circle cx="16" cy="16" r="16" fill="#ececef" />
              <circle cx="16" cy="12" r="4.5" fill="#151515" />
              <path d="M7.8 25a8.2 8.2 0 0 1 16.4 0Z" fill="#151515" />
            </svg>}
          <span className="sidebar__account-name">{displayName}</span>
        </button>
        <div className="sidebar__account-menu" id={accountMenuId} ref={accountMenu} {...{ popover: "auto" }}
          aria-label="用户菜单">
          <button
            type="button"
            className={`sidebar__all${allBotsActive ? ' sidebar__all--active' : ''}`}
            onClick={() => chooseAccountAction(onShowAll)}
            aria-current={allBotsActive ? 'page' : undefined}
            title="Bot市场" aria-label="Bot市场"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 6h7v7H4zM13 6h7v7h-7zM4 15h7v5H4zM13 15h7v5h-7z" />
            </svg>
            <span className="sidebar__all-label">Bot市场</span>
          </button>
          <button
            type="button"
            className={`sidebar__all${activeTool === 'strategies' ? ' sidebar__all--active' : ''}`}
            onClick={() => chooseAccountAction(() => onTool('strategies'))}
            aria-current={activeTool === 'strategies' ? 'page' : undefined}
            title={workbenchTools.strategies}
            aria-label={workbenchTools.strategies}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l2-5h14l2 5 M3 9h18 M5 9v11h14V9 M9 20v-6h6v6" />
            </svg>
            <span className="sidebar__all-label">{workbenchTools.strategies}</span>
          </button>
          <button
            type="button"
            className={`sidebar__all${activeTool === 'portrait' ? ' sidebar__all--active' : ''}`}
            onClick={() => chooseAccountAction(() => onTool('portrait'))}
            aria-current={activeTool === 'portrait' ? 'page' : undefined}
            title={workbenchTools.portrait}
            aria-label={workbenchTools.portrait}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 4h18v16H3z M10 10a2 2 0 1 0-4 0 2 2 0 0 0 4 0 M5 16c0-4 6-4 6 0 M14 9h4 M14 13h4" />
            </svg>
            <span className="sidebar__all-label">{workbenchTools.portrait}</span>
          </button>
          <button
            type="button"
            className={`sidebar__all${settingsActive ? ' sidebar__all--active' : ''}`}
            onClick={() => chooseAccountAction(onOpenSettings)}
            aria-current={settingsActive ? 'page' : undefined}
            title="设置"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 15.2a3.2 3.2 0 100-6.4 3.2 3.2 0 000 6.4z" />
              <path d="M19.4 15a1.7 1.7 0 00.34 1.88l.06.06a2 2 0 11-2.83 2.83l-.06-.06A1.7 1.7 0 0015 19.4a1.7 1.7 0 00-1 1.56V21a2 2 0 11-4 0v-.09A1.7 1.7 0 009 19.4a1.7 1.7 0 00-1.88.34l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.7 1.7 0 004.6 15a1.7 1.7 0 00-1.56-1H3a2 2 0 110-4h.09A1.7 1.7 0 004.6 9a1.7 1.7 0 00-.34-1.88l-.06-.06a2 2 0 112.83-2.83l.06.06A1.7 1.7 0 009 4.6a1.7 1.7 0 001-1.56V3a2 2 0 114 0v.09A1.7 1.7 0 0015 4.6a1.7 1.7 0 001.88-.34l.06-.06a2 2 0 112.83 2.83l-.06.06A1.7 1.7 0 0019.4 9a1.7 1.7 0 001.56 1H21a2 2 0 110 4h-.09a1.7 1.7 0 00-1.51 1z" />
            </svg>
            <span className="sidebar__all-label">设置</span>
          </button>
        </div>
      </div>
      {!phone && <div className="sidebar__resize" role="separator" tabIndex={0}
        aria-label="调整左侧栏宽度" aria-orientation="vertical"
        aria-valuemin={72} aria-valuemax={maxWidth} aria-valuenow={compact ? 72 : width}
        onPointerDown={event => {
          if (event.button !== 0 || !navRef.current) return;
          event.preventDefault();
          resize.current = { x: event.clientX, width: navRef.current.getBoundingClientRect().width,
            minimum: minimumSidebarWidth(navRef.current) };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={event => {
          const drag = resize.current;
          if (drag) resizeSidebar(drag.width + event.clientX - drag.x, drag.minimum);
        }}
        onLostPointerCapture={() => { resize.current = null; }}
        onKeyDown={event => {
          if (!navRef.current || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
          event.preventDefault();
          const minimum = minimumSidebarWidth(navRef.current);
          resizeSidebar(compact ? (event.key === 'ArrowRight' ? minimum : 72)
            : width + (event.key === 'ArrowRight' ? 16 : -16), minimum);
        }} />}
    </nav>
  );
}
