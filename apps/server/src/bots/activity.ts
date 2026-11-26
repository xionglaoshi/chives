import type { BotActivity, BotActivityPage } from '../api/protocol.js';
import type { Store } from '../store/index.js';

const PAGE_SIZE = 30;
const readKey = (id: string) => 'activity.reply.read/' + id;

const replyCondition = `
  m.role = 'bot' AND m.kind = 'text' AND t.delegated = 0
  AND (t.origin IS NULL OR NOT EXISTS (
    SELECT 1 FROM notifications n WHERE n.bot_id = m.bot_id AND n.task_id = t.id
  ))
`;

export function listBotActivity(store: Store, botId: string, before: BotActivityPage['next']): BotActivityPage {
  const entries = store.db.prepare(`
    WITH activity AS (
      SELECT 'notification' AS kind, n.id, n.title, n.task_id AS taskId,
        (SELECT m.id FROM messages m
         WHERE m.bot_id = n.bot_id AND m.task_id = n.task_id AND m.kind = 'notice'
           AND json_valid(m.meta) AND json_extract(m.meta, '$.notificationId') = n.id
         ORDER BY m.seq DESC LIMIT 1) AS messageId,
        n.created_at AS createdAt, n.read_at AS readAt
      FROM notifications n WHERE n.bot_id = ? AND n.task_id NOT LIKE 'system:%'
      UNION ALL
      SELECT 'reply', m.id, COALESCE(NULLIF(TRIM(t.title), ''), '会话答复'),
        m.task_id, m.id, m.created_at, NULL
      FROM messages m JOIN tasks t ON t.id = m.task_id
      WHERE m.bot_id = ? AND ${replyCondition}
    )
    SELECT * FROM activity
    WHERE ? IS NULL OR (createdAt, id) < (?, ?)
    ORDER BY createdAt DESC, id DESC LIMIT ?
  `).all(botId, botId, before?.createdAt ?? null, before?.createdAt ?? null, before?.id ?? null, PAGE_SIZE + 1) as unknown as BotActivity[];
  const page = entries.slice(0, PAGE_SIZE).map(entry => entry.kind === 'reply'
    ? { ...entry, readAt: store.settings.get<string>(readKey(entry.id)) ?? null }
    : entry);
  const last = page.at(-1);
  return { entries: page, next: last && entries.length > PAGE_SIZE ? { createdAt: last.createdAt, id: last.id } : null };
}

export function markBotReplyRead(store: Store, botId: string, id: string, now: Date): string | null {
  const record = store.db.prepare(`
    SELECT m.id FROM messages m JOIN tasks t ON t.id = m.task_id
    WHERE m.id = ? AND m.bot_id = ? AND ${replyCondition}
  `).get(id, botId);
  if (!record) return null;
  const key = readKey(id);
  const readAt = store.settings.get<string>(key);
  if (readAt) return readAt;
  const timestamp = now.toISOString();
  store.settings.set(key, timestamp);
  return timestamp;
}
