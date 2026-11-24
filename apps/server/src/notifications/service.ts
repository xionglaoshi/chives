/** `notify_user`: validation, rate limits, persistence, SSE and OS notifications. */

import { randomUUID } from 'node:crypto';

import type { EventBus } from '../events/index.js';
import { readProactiveSettings } from '../proactive-settings.js';
import { toMessageDto, toNotificationDto } from '../api/dto.js';
import type { NotificationLevel, NotificationRecord, Store } from '../store/index.js';
import { sendSystemNotification, type ExecFileFn } from './system.js';

export const MAX_NOTIFICATION_TITLE = 40;
export const MAX_NOTIFICATION_BODY = 300;
export const NOTIFICATIONS_PER_BOT_HOUR = 6;
export const NOTIFICATIONS_PER_TASK = 2;

const LEVELS: readonly NotificationLevel[] = ['info', 'important', 'urgent'];

export interface NotifyInput {
  botId: string;
  taskId: string;
  title: string;
  body: string;
  level: NotificationLevel;
  localOnly?: boolean;
}

export type NotifyResult =
  | { ok: true; notification: NotificationRecord }
  | { ok: false; code: string; message: string };

export interface NotificationServiceOptions {
  store: Store;
  bus: EventBus;
  now: () => Date;
  forward?: (title:string, body:string)=>void;
  platform?: NodeJS.Platform;
  /** Injected so tests can assert the exact osascript arguments. */
  execFile?: ExecFileFn;
  log?: (message: string, detail?: unknown) => void;
}

function isLevel(value: unknown): value is NotificationLevel {
  return typeof value === 'string' && (LEVELS as readonly string[]).includes(value);
}

export function normalizeLevel(value: unknown): NotificationLevel {
  return isLevel(value) ? value : 'important';
}

export class NotificationService {
  private readonly store: Store;
  private readonly bus: EventBus;
  private readonly now: () => Date;
  private readonly platform: NodeJS.Platform | undefined;
  private readonly execFile: ExecFileFn | undefined;
  private readonly log: (message: string, detail?: unknown) => void;

  private readonly forward: NotificationServiceOptions['forward'];
  constructor(options: NotificationServiceOptions) {
    this.forward=options.forward;
    this.store = options.store;
    this.bus = options.bus;
    this.now = options.now;
    this.platform = options.platform;
    this.execFile = options.execFile;
    this.log = options.log ?? ((message, detail) => console.log(message, detail ?? ''));
  }

  /** True for a user-initiated turn: the user is already looking at the timeline. */
  isForegroundTask(taskId: string): boolean {
    const task = this.store.tasks.get(taskId);
    if (task === undefined) return false;
    return task.origin === null && task.depth === 0 && !task.delegated;
  }

  notify(input: NotifyInput): NotifyResult {
    const title = input.title.trim();
    const body = input.body.trim();
    if (title === '' || [...title].length > MAX_NOTIFICATION_TITLE) {
      return {
        ok: false,
        code: 'invalid_arguments',
        message: `title 必须是 1-${MAX_NOTIFICATION_TITLE} 个字符`,
      };
    }
    if (body === '' || [...body].length > MAX_NOTIFICATION_BODY) {
      return {
        ok: false,
        code: 'invalid_arguments',
        message: `body 必须是 1-${MAX_NOTIFICATION_BODY} 个字符`,
      };
    }
    const hourAgo = new Date(this.now().getTime() - 3_600_000).toISOString();
    if (this.store.notifications.countForBotSince(input.botId, hourAgo) >= NOTIFICATIONS_PER_BOT_HOUR) {
      return {
        ok: false,
        code: 'rate_limited',
        message: `这个 bot 一小时内最多发 ${NOTIFICATIONS_PER_BOT_HOUR} 条通知`,
      };
    }
    if (this.store.notifications.countForTask(input.taskId) >= NOTIFICATIONS_PER_TASK) {
      return {
        ok: false,
        code: 'rate_limited',
        message: `同一个任务最多发 ${NOTIFICATIONS_PER_TASK} 条通知`,
      };
    }
    const createdAt = this.now().toISOString();
    const notification = this.store.notifications.add({
      id: randomUUID(),
      botId: input.botId,
      taskId: input.taskId,
      title,
      body,
      level: input.level,
      createdAt,
    });
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: input.botId,
      taskId: input.taskId,
      role: 'system',
      kind: 'notice',
      content: `${title} · ${body}`,
      meta: {
        notification: true,
        notificationId: notification.id,
        level: notification.level,
        title,
      },
      createdAt,
    });
    this.bus.publish({
      type: 'message.created',
      botId: input.botId,
      taskId: input.taskId,
      message: toMessageDto(message),
    });
    this.bus.publish({
      type: 'notification.created',
      botId: input.botId,
      notification: toNotificationDto(notification),
    });
    if (input.localOnly) return { ok: true, notification };
    const foreground = this.isForegroundTask(input.taskId);
    const settings = readProactiveSettings(this.store);
    if(!foreground && settings.enabled && (!settings.importantOnly || input.level!=='info'))this.forward?.(title,body);
    if (
      !foreground &&
      settings.systemNotify &&
      (!settings.importantOnly || input.level !== 'info')
    ) {
      sendSystemNotification(title, body, {
        ...(this.platform === undefined ? {} : { platform: this.platform }),
        ...(this.execFile === undefined ? {} : { execFile: this.execFile }),
        log: this.log,
      });
    }
    return { ok: true, notification };
  }

  /** Budget guardrail: bypasses `notify_user` validation but keeps persistence consistent. */
  notifyGuardrail(botId: string, taskId: string, title: string, body: string): NotificationRecord {
    const createdAt = this.now().toISOString();
    return this.store.notifications.add({
      id: randomUUID(),
      botId,
      taskId,
      title,
      body,
      level: 'important',
      createdAt,
    });
  }

  publishCreated(notification: NotificationRecord): void {
    this.bus.publish({
      type: 'notification.created',
      botId: notification.botId,
      notification: toNotificationDto(notification),
    });
  }

  list(options: { botId?: string; unreadOnly?: boolean; limit: number }): NotificationRecord[] {
    return this.store.notifications.list(options);
  }

  markRead(id: string, now = this.now()): NotificationRecord | undefined {
    return this.store.notifications.markRead(id, now.toISOString());
  }

  markAllRead(now = this.now()): number {
    return this.store.notifications.markAllRead(now.toISOString());
  }

  unreadCounts(): Record<string, number> {
    return this.store.notifications.countUnreadByBot();
  }
}
