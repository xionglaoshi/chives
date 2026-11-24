import { useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react';
import type { BotSummary, NotificationDto } from '@chives/server/protocol';
import { formatTime } from '../utils/format';
import { WatchesPanel, type WatchesPanelProps } from './WatchesPanel';
import {type InitializationStep} from './DockInitialization';
import './Dock.css';

const LEVEL_TEXT: Record<NotificationDto['level'], string> = {
  info: '消息',
  important: '重要',
  urgent: '紧急'
};

function BellIcon(): ReactElement {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M3.5 7a4.5 4.5 0 019 0c0 3 1.5 4 1.5 4H2s1.5-1 1.5-4z" strokeLinejoin="round" />
      <path d="M6.5 13a1.5 1.5 0 003 0" strokeLinecap="round" />
    </svg>
  );
}

function SearchIcon(): ReactElement {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" strokeLinecap="round" />
    </svg>
  );
}

type DockProps = {
  initialization: readonly (readonly [InitializationStep,string])[];
  onInitialize: (step: InitializationStep) => void;
  searchOpen: boolean;
  onSearch: () => void;
  bots: readonly BotSummary[];
  notifications: NotificationDto[];
  unreadCount: number;
  onMarkAllRead: () => Promise<void>;
  onOpenNotification: (notification: NotificationDto) => void;
  watches: Omit<WatchesPanelProps, 'botId'>;
};

type DockTool = {
  id: string;
  label: string;
  title?: string;
  defaultPinned?: boolean;
  icon: ReactNode;
  count?: (props: DockProps) => number;
} & (
  | {openOverlay: (props: DockProps) => void}
  | {render: (props: DockProps, close: () => void) => ReactNode; actions?: (props: DockProps) => ReactNode}
);

function NotificationList({bots, notifications, onOpenNotification, close}: Pick<DockProps,
  'bots' | 'notifications' | 'onOpenNotification'> & {close: () => void}) {
  return (
    <>{notifications.length === 0 ? (
      <div className="chat-header__panel-empty">还没有通知。盯盘触发后，值得你知道的结论会出现在这里。</div>
    ) : (
      <ul className="chat-header__notification-list">
        {notifications.map((notification) => (
          <li key={notification.id} className={notification.readAt === null ? 'is-unread' : ''}>
            <button
              type="button"
              onClick={() => {
                onOpenNotification?.(notification);
                close();
              }}
            >
              <span className="chat-header__notification-labels">
                <span className={`chat-header__notification-level chat-header__notification-level--${notification.level}`}>
                  {LEVEL_TEXT[notification.level]}
                </span>
                {notification.readAt === null && <span className="chat-header__notification-unread">未读</span>}
              </span>
              <span className="chat-header__notification-title">
                {bots.find((entry) => entry.id === notification.botId)?.name ??
                  notification.botId}
                {' · '}
                {notification.title}
              </span>
              <span className="chat-header__notification-body">{notification.body}</span>
              <span className="chat-header__notification-time">{formatTime(notification.createdAt)}</span>
            </button>
          </li>
        ))}
      </ul>
    )}</>
  );
}

// Register each built-in once. Default tools stay fixed on the Dock.
const dockTools: readonly DockTool[] = [
  {
    id: 'search', label: '搜索', title: '全局搜索（/ 或 Ctrl/⌘ K）', defaultPinned: true,
    icon: <SearchIcon/>, openOverlay: props => props.onSearch(),
  },
  {
    id: 'notifications', label: '通知', defaultPinned: true,
    icon: <BellIcon/>, count: props => props.unreadCount,
    actions: props => <button type="button" className="chat-header__panel-close" onClick={() => void props.onMarkAllRead()}>全部已读</button>,
    render: (props, close) => <NotificationList {...props} close={close}/>,
  },
  {
    id: 'watches', label: '盯盘', defaultPinned: true,
    icon: <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="4.8"/><circle cx="8" cy="8" r="1.6" fill="currentColor" stroke="none"/>
      <path d="M8 1.2v2M8 12.8v2M1.2 8h2M12.8 8h2"/>
    </svg>,
    count: ({bots}) => bots.reduce((sum, bot) => sum + (bot.watchCount ?? 0), 0),
    render: ({watches}, close) => <WatchesPanel {...watches} botId={undefined}
      onEditWatch={(label, botId) => {close(); watches.onEditWatch(label, botId);}}
      onLocateTask={(taskId, botId) => {close(); watches.onLocateTask(taskId, botId);}} />,
  },
];

const addedToolsKey = 'chives.dock.addedTools';

function readAddedTools(): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(addedToolsKey) ?? '[]');
    return Array.isArray(saved) ? [...new Set(saved.filter((id): id is string => typeof id === 'string'))] : [];
  } catch {
    return [];
  }
}

export function Dock(props: DockProps): ReactElement {
  const {initialization} = props;
  const [addedTools, setAddedTools] = useState(readAddedTools);
  const [open, setOpen] = useState<string | null>(null);
  const root = useRef<HTMLElement>(null);
  const initializedPanel = open === 'initialize' && initialization.length > 0;
  const expanded = props.searchOpen || (open === 'initialize' && !initializedPanel) ? null : open;
  const pinned = dockTools.filter(tool => tool.defaultPinned || addedTools.includes(tool.id));
  const active = pinned.find(tool => tool.id === expanded);
  const close = () => setOpen(null);

  useEffect(() => {
    if (props.searchOpen) setOpen(null);
  }, [props.searchOpen]);

  useEffect(() => {
    if (expanded === null) return;
    function onPointerDown(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(null);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(null);
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [expanded]);

  function toggle(id: string) {
    setOpen(current => current === id ? null : id);
  }

  function setPinned(tool: DockTool, shouldPin: boolean) {
    if (tool.defaultPinned || addedTools.includes(tool.id) === shouldPin) return;
    const next = shouldPin ? [...addedTools, tool.id] : addedTools.filter(id => id !== tool.id);
    setAddedTools(next);
    try { localStorage.setItem(addedToolsKey, JSON.stringify(next)); } catch { /* Retain the session selection. */ }
  }

  return <header ref={root} aria-label="启动台" className="chat-header">
    <div className="chat-header__dock">
      {initialization.length > 0 && <button type="button" className="chat-header__icon dock-initialization"
        aria-expanded={expanded === 'initialize'} onClick={() => toggle('initialize')}>
        <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6"/><path d="M8 4v5m0 2v1"/>
        </svg><span>请先完成初始化</span>
      </button>}
      {pinned.map(tool => {
        const count = tool.count?.(props) ?? 0;
        const isOpen = 'openOverlay' in tool ? props.searchOpen : expanded === tool.id;
        return <button key={tool.id} type="button"
          className={'chat-header__icon' + (isOpen ? ' chat-header__toggle--on' : '')}
          aria-label={tool.label} aria-expanded={isOpen} title={tool.title ?? tool.label}
          aria-description={count > 0 ? (tool.id === 'notifications' ? count + ' 条未读' : count + ' 条盯盘') : undefined}
          onClick={() => {
            if ('openOverlay' in tool) {close(); tool.openOverlay(props);}
            else toggle(tool.id);
          }}>
          {tool.icon}<span>{tool.label}</span>
          {count > 0 && <span aria-hidden="true" className="chat-header__panel-badge">{count > 9 ? '9+' : count}</span>}
        </button>;
      })}
      <button type="button" className="chat-header__icon chat-header__icon--add" aria-label="添加工具" title="添加工具"
        aria-expanded={expanded === 'add'} onClick={() => toggle('add')}>
        <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M8 3v10M3 8h10" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
    {expanded === 'initialize' && <div className="chat-header__panel" role="dialog" aria-label="请先完成初始化">
      <ul className="dock-initialization-steps">
        {initialization.map(([id,label])=><li key={id}><button type="button" onClick={()=>{
          close();
          props.onInitialize(id);
        }}>{label}</button></li>)}
      </ul>
    </div>}
    {(expanded === 'add' || (active && 'render' in active)) && (
      <div className="chat-header__panel" role="dialog" aria-label={active?.label ?? '添加工具'}>
        <div className="chat-header__panel-head">
          <span>{active?.label ?? '添加工具'}</span>
          <span className="chat-header__panel-actions">
            {active && 'render' in active && active.actions?.(props)}
            <button type="button" className="chat-header__panel-close" onClick={close}>关闭</button>
          </span>
        </div>
        {active && 'render' in active ? active.render(props, close) : (
          <ul className="dock-tool-list">
            {dockTools.map(tool => {
              const isPinned = pinned.includes(tool);
              return <li key={tool.id}>
                <span className="dock-tool-name">{tool.icon}{tool.label}</span>
                {tool.defaultPinned ? <small>强制固定在Dock栏</small> : [true, false].map(shouldPin => {
                  const action = shouldPin ? '添加到Dock栏' : '从Dock栏删除';
                  const unavailable = shouldPin === isPinned;
                  return <button key={action} type="button" aria-disabled={unavailable}
                    aria-label={action + '：' + tool.label} title={action}
                    onClick={() => setPinned(tool, shouldPin)}>
                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none"
                      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                      <path d={shouldPin ? 'M3 8h10M8 3v10' : 'M3 8h10'}/>
                    </svg>
                  </button>;
                })}
              </li>;
            })}
          </ul>
        )}
      </div>
    )}
  </header>;
}
