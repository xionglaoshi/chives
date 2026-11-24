import type { BotSummary, NotificationDto } from '@chives/server/protocol';

function category(title: string): string {
  return title.match(/盯盘|调研|分析/)?.[0] ?? '通知';
}

export function DashboardBotMessages({notifications, bots, expanded, loading, error, onLoadMore, onOpen}: {
  notifications: NotificationDto[];
  bots: BotSummary[];
  expanded: boolean;
  loading: boolean;
  error: boolean;
  onLoadMore: () => void;
  onOpen: (notification: NotificationDto) => void;
}) {
  const entries = notifications.filter((entry, index) => index < 20 || (expanded && entry.readAt === null));
  const botNames = new Map(bots.map(bot => [bot.id, bot.name]));
  return <section className="mb-panel mb-bot-messages">
    <header>
      <h2>Bot消息</h2>
      {!expanded && <button className="mb-ask" disabled={loading} onClick={onLoadMore}>{loading ? '正在载入…' : '载入更多'}</button>}
    </header>
    {error && <p role="status">未能载入全部未读消息，请重试。</p>}
    {entries.length === 0 ? <p>暂无 Bot 消息</p> : <ul>
      {entries.map(entry => <li key={entry.id}>
        <button className={'mb-bot-message' + (entry.readAt === null ? ' mb-bot-message--unread' : '')} onClick={() => onOpen(entry)}>
          <span className="mb-bot-message-title">
            {entry.readAt === null && <span className="sr-only">未读 </span>}
            【{category(entry.title)}】{entry.title}
          </span>
          {entry.body && <span>{entry.body}</span>}
          <small>{botNames.get(entry.botId) ?? entry.botId} · {new Date(entry.createdAt).toLocaleString('zh-CN', {hour12: false})}</small>
        </button>
      </li>)}
    </ul>}
  </section>;
}
