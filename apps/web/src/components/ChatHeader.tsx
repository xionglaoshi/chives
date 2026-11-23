import { useState } from 'react';
import type { ReactElement } from 'react';

import type { BotSummary, NotificationDto } from '@chives/server/protocol';

import { formatTime } from '../utils/format';
import { toolbarPanels, type ToolbarPanelId } from './toolbarPanels';
import './ChatHeader.css';

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
  onSearch?: () => void;
  onOpenInbox: () => Promise<boolean>;
  inboxCount: number;
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
  onSearch,
  onOpenInbox,
  inboxCount,
  bots = [],
  notifications = [],
  unreadCount = 0,
  onMarkAllRead,
  onOpenNotification,
  openPanels = [],
  onTogglePanel
}: ChatHeaderProps): ReactElement {
  const watchCount = bots.reduce((sum, bot) => sum + (bot.watchCount ?? 0), 0);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [inboxStatus, setInboxStatus] = useState<'loading'|'empty'|'error'|null>(null);

  async function readInbox() {
    setNotificationsOpen(false);
    if (inboxStatus === 'loading') return;
    if (inboxCount === 0) { setInboxStatus('empty'); return; }
    setInboxStatus('loading');
    try { setInboxStatus(await onOpenInbox() ? null : 'empty'); }
    catch { setInboxStatus('error'); }
  }


  return (
    <header aria-label="全局工具条" className="chat-header">
      <div className="chat-header__dock">
        <button type="button" className="chat-header__pill" title="收件箱"
          aria-label={inboxCount > 0 ? `收件箱，${inboxCount} 条未读` : '收件箱'}
          onClick={() => void readInbox()}>
          <svg width="17" height="17" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
            <rect x="2" y="3.5" width="12" height="9" rx="1.5"/>
            <path d="m2.5 4.5 5.5 4 5.5-4" strokeLinejoin="round"/>
          </svg>
          <span className="chat-header__pill-name">收件箱</span>
          {inboxCount > 0 && <span className="chat-header__inbox-count" aria-hidden="true">{inboxCount}</span>}
        </button>

      <span className="chat-header__divider" aria-hidden="true" />

      <div className="chat-header__actions">
        <button
          type="button"
          className="chat-header__icon chat-header__bell"
          aria-label={unreadCount > 0 ? `通知，${unreadCount} 条未读` : '通知'}
          aria-expanded={notificationsOpen}
          onClick={() => { setInboxStatus(null); setNotificationsOpen(current => !current); }}
        >
          <BellIcon />
          {unreadCount > 0 ? <span className="chat-header__bell-dot">{unreadCount > 9 ? '9+' : unreadCount}</span> : null}
        </button>

        <button
          type="button"
          className="chat-header__icon chat-header__search"
          aria-label="全局搜索"
          title="全局搜索（/ 或 Ctrl/⌘ K）"
          onClick={() => { setInboxStatus(null); setNotificationsOpen(false); onSearch?.(); }}
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
              onClick={() => { setInboxStatus(null); setNotificationsOpen(false); onTogglePanel?.(panel); }}
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

      </div>

      {inboxStatus !== null && (
        <div className="chat-header__panel" role="dialog" aria-label="收件箱">
          <div className="chat-header__panel-head">
            <span>收件箱</span>
            <button type="button" className="chat-header__panel-close" onClick={() => setInboxStatus(null)}>关闭</button>
          </div>
          <div className="chat-header__panel-empty" role="status">
            {inboxStatus === 'loading' ? '正在打开未读通知…' : inboxStatus === 'error' ? '读取失败，请重新点击收件箱。' : '没有未读通知。'}
          </div>
        </div>
      )}

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
    </header>
  );
}
