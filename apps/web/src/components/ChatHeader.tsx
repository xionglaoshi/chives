import { useState } from 'react';
import type { ReactElement } from 'react';

import type { BotPanel, BotSummary, NotificationDto, TaskDto } from '@chives/server/protocol';

import { BotAvatar } from '../brand/BotAvatar';
import { useNow } from '../hooks/useNow';
import { formatDurationBetween, formatTime } from '../utils/format';
import { panelLabel } from '../utils/panels';
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

function PanelIcon({ panel }: { panel: BotPanel }): ReactElement {
  if (panel === 'market') {
    return (
      <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M2 12.5L6 8l3 2.5L14 4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M2 2v12h12" strokeLinecap="round" opacity="0.55" />
      </svg>
    );
  }
  if (panel === 'portfolio') {
    return (
      <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="4" width="12" height="9" rx="1.5" />
        <path d="M2 7h12" />
        <path d="M10.5 10.5h2" strokeLinecap="round" />
      </svg>
    );
  }
  if (panel.startsWith('strategy:')) {
    return (
      <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M2 13V9M6 13V5M10 13V7M14 13V3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="4.8" />
      <circle cx="8" cy="8" r="1.6" fill="currentColor" stroke="none" />
      <path d="M8 1.2v2M8 12.8v2M1.2 8h2M12.8 8h2" strokeLinecap="round" />
    </svg>
  );
}

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
  bot: BotSummary;
  runningTask: TaskDto | null;
  /** Start of the current turn; defaults to the task start. */
  turnStartedAt?: string | null;
  onSearch?: () => void;
  /** Opens the bot profile page from the floating name pill. */
  onOpenProfile?: () => void;
  bots?: readonly BotSummary[];
  notifications?: NotificationDto[];
  unreadCount?: number;
  onMarkAllRead?: () => Promise<void>;
  onOpenNotification?: (notification: NotificationDto) => void;
  /** The one open right-hand panel, if any. */
  openPanels?: readonly BotPanel[];
  onTogglePanel?: (panel: BotPanel) => void;
}

export function ChatHeader({
  bot,
  runningTask,
  turnStartedAt = null,
  onSearch,
  onOpenProfile,
  bots = [],
  notifications = [],
  unreadCount = 0,
  onMarkAllRead,
  onOpenNotification,
  openPanels = [],
  onTogglePanel
}: ChatHeaderProps): ReactElement {
  const active = runningTask !== null || bot.status === 'working' || bot.status === 'starting';
  const now = useNow(active);
  const elapsed =
    runningTask === null ? null : formatDurationBetween(turnStartedAt ?? runningTask.startedAt, null, now);
  const waiting = bot.waitingDelegations ?? 0;
  const waitingLabel = bot.status === 'idle' && waiting > 0 ? `等待委派结果（${waiting}）` : null;
  const statusText = waitingLabel ?? STATUS_TEXT[bot.status];
  const watchCount = bot.watchCount ?? 0;
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const shortName = [...bot.name].slice(0, 6).join('');

  const pillContent = (
    <>
      <BotAvatar emblem={bot.avatar.emblem} tone={bot.avatar.tone} size={18} name={bot.name} />
      <span className="chat-header__pill-name">{bot.name}</span>
      <span className="chat-header__pill-name chat-header__pill-name--short">{shortName}</span>
      {active ? <span className="chat-header__pill-dot" aria-hidden="true" /> : null}
      {elapsed === null ? null : <span className="chat-header__pill-time">{elapsed}</span>}
    </>
  );

  return (
    <header className={`chat-header chat-header--with-panels chat-header--${bot.status}`}>
      <div className="chat-header__dock">
      {onOpenProfile === undefined ? (
        <div className="chat-header__pill" title={`${bot.name} · ${statusText}`}>
          {pillContent}
        </div>
      ) : (
        <button
          type="button"
          className="chat-header__pill"
          aria-label={`打开 ${bot.name} 资料`}
          title={`${bot.name} · ${statusText}`}
          onClick={onOpenProfile}
        >
          {pillContent}
        </button>
      )}

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
          aria-label={`搜索与${bot.name}的时间线`}
          title="搜索时间线（/ 或 ⌘K）"
          onClick={onSearch}
        >
          <SearchIcon />
        </button>

        {bot.panels.length > 0 ? <span className="chat-header__divider" aria-hidden="true" /> : null}

        {bot.panels.map((panel) => {
          const open = openPanels.includes(panel);
          const label = panelLabel(panel);
          return (
            <button
              key={panel}
              type="button"
              className={`chat-header__icon chat-header__search${open ? ' chat-header__toggle--on' : ''}`}
              aria-label={label}
              aria-pressed={open}
              title={open ? `关闭${label}面板` : `打开${label}面板`}
              onClick={() => onTogglePanel?.(panel)}
            >
              <PanelIcon panel={panel} />
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
