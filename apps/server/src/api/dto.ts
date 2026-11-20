/** Maps persisted rows and manifests to the wire shapes in `protocol.ts`. */

import type { BotManifest } from '../bots/index.js';
import type {
  BotOverride,
  DeliverableRecord,
  MessageRecord,
  TaskRecord,
  TaskSummaryRecord,
  ToolEventRecord,
  UsageRecord,
  RoutineRecord,
  AlertEventRecord,
  NotificationRecord,
  WatchRecord,
} from '../store/index.js';
import { describeSchedule } from '../routines/service.js';
import { scheduleToWire } from '../routines/types.js';
import type {
  BotStatus,
  BotSummary,
  DeliverableDto,
  DeliverableKind,
  MessageDto,
  TaskDto,
  TaskSummaryDto,
  ToolEventDto,
  UsageDto,
  RoutineDto,
  AlertEventDto,
  NotificationDto,
  WatchDto,
} from './protocol.js';
import { describeGiveUp, describeWatch } from '../watches/plan.js';

export function toTaskDto(task: TaskRecord, summary?: TaskSummaryRecord | null): TaskDto {
  return {
    id: task.id,
    botId: task.botId,
    title: task.title,
    status: task.status,
    harnessSessionId: task.harnessSessionId,
    startedAt: task.startedAt,
    endedAt: task.endedAt,
    parentTaskId: task.parentTaskId,
    depth: task.depth,
    delegated: task.delegated,
    brief: task.brief,
    closedAt: task.closedAt ?? null,
    summaryTitle: summary?.title ?? null,
    summaryConclusion: summary?.conclusion ?? null,
    contextMeta: task.contextMeta ?? null,
    lastContextUsed: task.lastContextUsed ?? null,
    lastContextSize: task.lastContextSize ?? null,
    errorCode: (task.errorCode as TaskDto['errorCode']) ?? null,
  };
}

export function toTaskSummaryDto(summary: TaskSummaryRecord): TaskSummaryDto {
  return {
    taskId: summary.taskId,
    title: summary.title,
    conclusion: summary.conclusion,
    keyNumbers: summary.keyNumbers.map((entry) => ({ ...entry })),
    deliverables: [...summary.deliverables],
    openQuestions: [...summary.openQuestions],
    symbols: summary.symbols.map((entry) => ({ ...entry })),
    createdAt: summary.createdAt,
    source: summary.source,
  };
}

export function toMessageDto(message: MessageRecord): MessageDto {
  return {
    id: message.id,
    botId: message.botId,
    taskId: message.taskId,
    role: message.role,
    kind: message.kind,
    content: message.content,
    meta: message.meta,
    createdAt: message.createdAt,
    seq: message.seq,
  };
}

export function toToolEventDto(tool: ToolEventRecord): ToolEventDto {
  return {
    id: tool.id,
    taskId: tool.taskId,
    messageId: tool.messageId,
    toolCallId: tool.toolCallId,
    title: tool.title,
    kind: tool.kind,
    rawInput: tool.rawInput,
    status: tool.status,
    output: tool.output,
    startedAt: tool.startedAt,
    endedAt: tool.endedAt,
  };
}

export function toUsageDto(usage: UsageRecord): UsageDto {
  return { taskId: usage.taskId, at: usage.at, used: usage.used, size: usage.size };
}

const DELIVERABLE_KINDS: readonly DeliverableKind[] = [
  'markdown',
  'image',
  'csv',
  'json',
  'html',
  'pdf',
  'code',
  'other',
];

function toDeliverableKind(value: string): DeliverableKind {
  return (DELIVERABLE_KINDS as readonly string[]).includes(value)
    ? (value as DeliverableKind)
    : 'other';
}

export function toDeliverableDto(record: DeliverableRecord): DeliverableDto {
  return {
    id: record.id,
    taskId: record.taskId,
    botId: record.botId,
    path: record.path,
    kind: toDeliverableKind(record.kind),
    size: record.size,
    createdAt: record.createdAt,
  };
}

export interface BotSummaryExtras {
  modelDisplayName?: string;
  workspacePath?: string;
  memoryCount?: number;
  memoryUpdatedAt?: string | null;
  proactiveCount?: number;
  watchCount?: number;
  unreadNotifications?: number;
  waitingDelegations?: number;
}

export function toBotSummary(
  bot: BotManifest,
  override: BotOverride | undefined,
  status: BotStatus,
  runningTaskId: string | null,
  pendingApprovals = 0,
  extras: BotSummaryExtras = {},
): BotSummary {
  return {
    id: bot.id,
    name: override?.displayName ?? bot.name,
    role: bot.role,
    ...(bot.headline === undefined ? {} : { headline: bot.headline }),
    avatar: {
      emblem: override?.avatarEmblem ?? bot.avatar.emblem,
      tone: override?.avatarTone ?? bot.avatar.tone,
    },
    skills: [...bot.skills],
    mcp: [...bot.mcp],
    model: bot.model,
    ...(extras.modelDisplayName === undefined
      ? {}
      : { modelDisplayName: extras.modelDisplayName }),
    ...(extras.workspacePath === undefined ? {} : { workspacePath: extras.workspacePath }),
    ...(extras.memoryCount === undefined ? {} : { memoryCount: extras.memoryCount }),
    ...(extras.memoryUpdatedAt === undefined ? {} : { memoryUpdatedAt: extras.memoryUpdatedAt }),
    ...(extras.proactiveCount === undefined ? {} : { proactiveCount: extras.proactiveCount }),
    ...(extras.watchCount === undefined ? {} : { watchCount: extras.watchCount }),
    ...(extras.unreadNotifications === undefined
      ? {}
      : { unreadNotifications: extras.unreadNotifications }),
    ...(extras.waitingDelegations === undefined
      ? {}
      : { waitingDelegations: extras.waitingDelegations }),
    panels: [...(bot.panels ?? [])],
    canDelegateTo: [...bot.can_delegate_to],
    background: bot.background,
    status,
    runningTaskId,
    pendingApprovals,
  };
}

export function toRoutineDto(record: RoutineRecord): RoutineDto {
  return {
    id: record.id,
    botId: record.botId,
    source: record.source,
    title: record.title,
    schedule: scheduleToWire(record.schedule),
    scheduleText: describeSchedule(record.schedule),
    prompt: record.prompt,
    promptSummary:
      record.prompt.length <= 120 ? record.prompt : `${record.prompt.slice(0, 120)}…`,
    tradingDaysOnly: record.tradingDaysOnly,
    enabled: record.enabled,
    createdAt: record.createdAt,
    lastRunAt: record.lastRunAt,
    nextRunAt: record.nextRunAt,
  };
}

export function toAlertEventDto(record: AlertEventRecord): AlertEventDto {
  return {
    id: record.id,
    source: record.source,
    alertId: record.alertId,
    alertTs: record.alertTs,
    code: record.code,
    name: record.name,
    ruleId: record.ruleId,
    status: record.status,
    reason: record.reason,
    taskId: record.taskId,
    createdAt: record.createdAt,
  };
}

export function toWatchDto(watch: WatchRecord): WatchDto {
  return {
    id: watch.id,
    botId: watch.botId,
    code: watch.code,
    name: watch.name,
    label: watch.label,
    note: watch.note,
    conditionText: describeWatch(watch),
    giveUpText: describeGiveUp(watch.plan),
    repeat: watch.repeat,
    status: watch.status,
    engineState: watch.engineState,
    lastPrice: watch.lastPrice,
    syncError: watch.syncError,
    createdTaskId: watch.createdTaskId,
    updatedTaskId: watch.updatedTaskId,
    createdAt: watch.createdAt,
    updatedAt: watch.updatedAt,
    expiresAt: watch.expiresAt,
    triggeredAt: watch.triggeredAt,
    triggerTaskId: watch.triggerTaskId,
    cancelledBy: watch.cancelledBy,
  };
}

export function toNotificationDto(record: NotificationRecord): NotificationDto {
  return {
    id: record.id,
    botId: record.botId,
    taskId: record.taskId,
    title: record.title,
    body: record.body,
    level: record.level,
    createdAt: record.createdAt,
    readAt: record.readAt,
  };
}
