import { useEffect, useState, type ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { workbenchTools, type WorkbenchTool } from '../utils/routes';
import { Logo } from '../brand/Logo';
import { BotList, BotRail } from './BotList';
import { HiddenMenu, Pin, useSidebarPins } from './SidebarPins';
import './Sidebar.css';

const initialTools = ['holdings', 'watchlist', 'market', 'trends', 'strategies', 'portrait'];
const initialBots = ['chives', 'expert', 'equity-analyst', 'research', 'zhushenglang', 'report-builder'];
const toolIds: WorkbenchTool[] = ['trends', ...(Object.keys(workbenchTools) as WorkbenchTool[]).filter(id => id !== 'trends')];

const toolOrderKey = 'chives.sidebar.toolOrder';
function readToolOrder(): WorkbenchTool[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(toolOrderKey) ?? 'null');
    if (Array.isArray(saved)) {
      const known = saved.filter((id): id is WorkbenchTool => toolIds.includes(id));
      if (!known.includes('watchlist') && known.includes('holdings')) known.splice(known.indexOf('holdings')+1,0,'watchlist');
      return [...new Set<WorkbenchTool>(['trends', ...known, ...toolIds])];
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
  const tools = useSidebarPins('tools', initialTools);
  const [order, setOrder] = useState(readToolOrder);
  const visibleTools = order.filter(id => tools.pins.includes(id));
  function moveTool(source: string, target: WorkbenchTool) {
    const from = order.findIndex(id => id === source);
    if (source === 'trends' || target === 'trends' || from < 0 || source === target || !tools.pins.includes(source)) return;
    const next = [...order];
    next.splice(from, 1);
    next.splice(order.indexOf(target), 0, order[from]!);
    setOrder(next);
    try { localStorage.setItem(toolOrderKey, JSON.stringify(next)); } catch { /* Keep the in-session order. */ }
  }
  const [legacyHidden] = useState(() => {
    try {
      const previous: unknown = JSON.parse(localStorage.getItem('chives.sidebar.pins.bots') ?? 'null');
      return Array.isArray(previous) ? initialBots.filter(id => !previous.includes(id)) : [];
    } catch { return []; }
  });
  const hiddenBots = useSidebarPins('hidden-bots.v1', legacyHidden);
  const visibleBots = bots.filter(bot => bot.permanent || !hiddenBots.pins.includes(bot.id));
  return (
    <nav className={`sidebar${compact ? ' sidebar--compact' : ''}`} aria-label="Bot 列表">
      <div className="sidebar__brand">
        <a className="sidebar__home" onClick={onHome} href="#/workspace/trends" aria-label="老韭菜 · Chives，打开热门榜单" title="热门榜单">
          <Logo size={40} title="Chives" />
          <span className="sidebar__wordmark">老韭菜 · Chives</span>
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
        {visibleTools.map((key,index)=><div className="sidebar-pin-row" key={key}
          onDragOver={event => { if (key !== 'trends' && event.dataTransfer.types.includes('text/chives-tool')) event.preventDefault(); }}
          onDrop={event => {
            const source = event.dataTransfer.getData('text/chives-tool');
            if (source) { event.preventDefault(); moveTool(source,key); }
          }}>
          <button type="button" draggable={key !== 'trends'} onDragStart={event => {
            event.dataTransfer.setData('text/chives-tool',key);
            event.dataTransfer.effectAllowed = 'move';
          }} onKeyDown={event => {
            if (!event.altKey || !['ArrowUp','ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            const target = visibleTools[index + (event.key === 'ArrowUp' ? -1 : 1)];
            if (target) moveTool(key,target);
          }}
          title={workbenchTools[key] + (key === 'trends' ? ' · 展示时置顶' : ' · 拖动排序，或按 Alt 加上下方向键')} aria-label={workbenchTools[key]} aria-current={activeTool===key?'page':undefined}
          onClick={()=>onTool(key)}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d={{watchlist:'M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z',holdings:'M3 7h18v13H3z M8 7V4h8v3 M3 12c5 3 13 3 18 0 M11 13h2',market:'M3 4v16h18 M6 15l4-5 4 3 6-8',trends:'M13 3c1 5 6 6 6 12a7 7 0 0 1-14 0c0-3 2-6 4-8 0 4 1 5 2 5 2-2 3-5 2-9z',portrait:'M3 4h18v16H3z M10 10a2 2 0 1 0-4 0 2 2 0 0 0 4 0 M5 16c0-4 6-4 6 0 M14 9h4 M14 13h4',strategies:'M3 9l2-5h14l2 5 M3 9h18 M5 9v11h14V9 M9 20v-6h6v6'}[key]}/>
          </svg><span>{workbenchTools[key]}</span>
        </button><Pin name={workbenchTools[key]} pinned onClick={() => tools.toggle(key)}/></div>)}
        <HiddenMenu label="更多工具" items={order.filter(key => !tools.pins.includes(key)).map(id => ({id,name:workbenchTools[id]}))}
          open={id => onTool(id as WorkbenchTool)} pin={tools.toggle}/>
      </section>
      {loading && bots.length === 0 ? (
        <SidebarSkeleton />
      ) : compact ? (
        <BotRail bots={visibleBots} selectedId={selectedId} onSelect={onSelect} />
      ) : (
        <BotList onPin={hiddenBots.toggle} onMove={onMove} bots={visibleBots} selectedId={selectedId} onSelect={onSelect} />
      )}
      {!loading || bots.length > 0 ? <HiddenMenu label="隐藏Bot" items={bots.filter(bot => !bot.permanent && hiddenBots.pins.includes(bot.id))}
        open={onSelect} pin={hiddenBots.toggle}/> : null}
      <div className="sidebar__footer">
        <button
          type="button"
          className={`sidebar__all${allBotsActive ? ' sidebar__all--active' : ''}`}
          onClick={onShowAll}
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
          className={`sidebar__all${settingsActive ? ' sidebar__all--active' : ''}`}
          onClick={onOpenSettings}
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
    </nav>
  );
}
