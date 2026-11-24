import type { BotSummary, NotificationDto } from '@chives/server/protocol';

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
      {entries.map(entry => {
        const sender = botNames.get(entry.botId) ?? entry.botId;
        const unread = entry.readAt === null;
        return <li key={entry.id}>
          <button className={'mb-bot-message' + (unread ? ' mb-bot-message--unread' : '')}
            title={sender + '：' + entry.title} onClick={() => onOpen(entry)}>
            {unread && <span className="sr-only">未读 </span>}
            <span>{sender}：</span>
            <span className="mb-bot-message-title">{entry.title}</span>
          </button>
        </li>;
      })}
    </ul>}
  </section>;
}
