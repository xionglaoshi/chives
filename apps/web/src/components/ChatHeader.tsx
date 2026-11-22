import { useState } from 'react';
import type { ReactElement } from 'react';

import type { BotSummary, NotificationDto, TaskDto } from '@chives/server/protocol';

import { BotAvatar } from '../brand/BotAvatar';
import { useNow } from '../hooks/useNow';
import { formatDurationBetween, formatTime } from '../utils/format';
import { toolbarPanels, type ToolbarPanelId } from './toolbarPanels';
import './ChatHeader.css';

const STATUS_TEXT: Record<BotSummary['status'], string> = {
  idle: '空闲',
  starting: '启动中',
  working: '工作中',
  awaiting_approval: '待批准',
  error: '出错'
};

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

export interface ChatHeaderProps {
  operator: BotSummary | undefined;
  runningTask: TaskDto | null;
  /** Start of the current turn; defaults to the task start. */
  turnStartedAt?: string | null;
  onSearch?: () => void;
  onOpenOperator: () => void;
  bots?: readonly BotSummary[];
  notifications?: NotificationDto[];
  unreadCount?: number;
  onMarkAllRead?: () => Promise<void>;
  onOpenNotification?: (notification: NotificationDto) => void;
  /** Panels the user has opened. */
  openPanels?: readonly ToolbarPanelId[];
  onTogglePanel?: (panel: ToolbarPanelId) => void;
}

export function ChatHeader({
  operator,
  runningTask,
  turnStartedAt = null,
  onSearch,
  onOpenOperator,
  bots = [],
  notifications = [],
  unreadCount = 0,
  onMarkAllRead,
  onOpenNotification,
  openPanels = [],
  onTogglePanel
}: ChatHeaderProps): ReactElement {
  const status = operator?.status ?? 'idle';
  const active = status === 'working' || status === 'starting' || runningTask !== null;
  const now = useNow(active);
  const elapsed = runningTask === null ? null : formatDurationBetween(turnStartedAt ?? runningTask.startedAt, null, now);
  const watchCount = bots.reduce((sum, bot) => sum + (bot.watchCount ?? 0), 0);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const name = operator?.name ?? '总调度';

  return (
    <header aria-label="全局工具条" className={`chat-header chat-header--${status}`}>
      <div className="chat-header__dock">
        <button type="button" className="chat-header__pill" aria-label={`与${name}对话`}
          title={`与${name}对话 · ${STATUS_TEXT[status]}`}
          onClick={() => { setNotificationsOpen(false); onOpenOperator(); }}>
          <BotAvatar emblem={operator?.avatar.emblem ?? 'compass'} tone={operator?.avatar.tone ?? 'jade'} size={18} name={name}/>
          <span className="chat-header__pill-name">{name}</span>
          {active && <span className="chat-header__pill-dot" aria-hidden="true"/>}
          {elapsed !== null && <span className="chat-header__pill-time">{elapsed}</span>}
        </button>

      <span className="chat-header__divider" aria-hidden="true" />

      <div className="chat-header__actions">
        <button
          type="button"
          className="chat-header__icon chat-header__bell"
          aria-label={unreadCount > 0 ? `通知，${unreadCount} 条未读` : '通知'}
          aria-expanded={notificationsOpen}
          onClick={() => setNotificationsOpen((current) => !current)}
        >
          <BellIcon />
          {unreadCount > 0 ? <span className="chat-header__bell-dot">{unreadCount > 9 ? '9+' : unreadCount}</span> : null}
        </button>

        <button
          type="button"
          className="chat-header__icon chat-header__search"
          aria-label="全局搜索"
          title="全局搜索（/ 或 Ctrl/⌘ K）"
          onClick={() => { setNotificationsOpen(false); onSearch?.(); }}
        >
          <SearchIcon />
        </button>

      </div>
      <span className="chat-header__divider" aria-hidden="true" />
      <div className="chat-header__actions" role="group" aria-label="右侧面板快捷按钮">
        {toolbarPanels.map(({ id: panel, label, icon }) => {
          const open = openPanels.includes(panel);
          return (
            <button
              key={panel}
              type="button"
              className={`chat-header__icon chat-header__search${open ? ' chat-header__toggle--on' : ''}`}
              aria-label={label}
              aria-pressed={open}
              title={open ? `关闭${label}面板` : `打开${label}面板`}
              onClick={() => { setNotificationsOpen(false); onTogglePanel?.(panel); }}
            >
              <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">{icon}</svg>
              {panel === 'watches' && watchCount > 0 ? (
                <span className="chat-header__panel-badge" aria-hidden="true">
                  {watchCount > 9 ? '9+' : watchCount}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {notificationsOpen ? (
        <div className="chat-header__panel chat-header__panel--notifications" role="dialog" aria-label="通知">
          <div className="chat-header__panel-head">
            <span>通知</span>
            <span className="chat-header__panel-actions">
              <button type="button" className="chat-header__panel-close" onClick={() => void onMarkAllRead?.()}>
                全部已读
              </button>
              <button type="button" className="chat-header__panel-close" onClick={() => setNotificationsOpen(false)}>
                关闭
              </button>
            </span>
          </div>
          {notifications.length === 0 ? (
            <div className="chat-header__panel-empty">还没有通知。盯盘触发后，值得你知道的结论会出现在这里。</div>
          ) : (
            <ul className="chat-header__notification-list">
              {notifications.map((notification) => (
                <li key={notification.id} className={notification.readAt === null ? 'is-unread' : ''}>
                  <button
                    type="button"
                    onClick={() => {
                      onOpenNotification?.(notification);
                      setNotificationsOpen(false);
                    }}
                  >
                    <span className={`chat-header__notification-level chat-header__notification-level--${notification.level}`}>
                      {LEVEL_TEXT[notification.level]}
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
          )}
        </div>
      ) : null}
      </div>
    </header>
  );
}
