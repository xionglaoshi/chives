/** Bot-to-bot delegation: whitelist, depth, concurrency, execution and waiting. */

import { randomUUID } from 'node:crypto';

import type { BotRegistry } from '../bots/index.js';
import type { DelegationDto, DelegationStatus, ServerEvent } from '../api/protocol.js';
import { toMessageDto, toTaskDto } from '../api/dto.js';
import type { EventBus } from '../events/index.js';
import type { NotificationService } from '../notifications/index.js';
import type { Orchestrator } from '../orchestrator.js';
import type { JsonRecord, Store, TaskRecord, TaskStatus } from '../store/index.js';
import type { SessionIdentity } from './tokens.js';

export const DEFAULT_DELEGATION_CONCURRENCY = 3;
export const MAX_WAIT_SECONDS = 40;
/** Default upper bound for one delegated child (CHIVES_DELEGATION_TIMEOUT_MINUTES overrides). */
export const CHILD_TIMEOUT_MS = 20 * 60_000;
/** A follow-up waiting longer than this is given up and the user is notified. */
export const FOLLOWUP_MAX_MS = 30 * 60_000;
/** Per-child cap for the final reply embedded in a follow-up prompt. */
export const MAX_FOLLOWUP_RESULT_CHARS = 6_000;

export type DelegationMode = 'any' | 'all';

export interface DelegationStartInput {
  bot: string;
  brief: string;
  waitSeconds?: number;
  /** Defaults to true: the initiator ends its turn and is woken for a follow-up. */
  reportBack?: boolean;
  /** Per-delegation upper bound (1–60); falls back to the service default (20 min). */
  timeoutMinutes?: number;
}

export interface DelegationWaitInput {
  ids: readonly string[];
  mode?: DelegationMode;
  waitSeconds?: number;
}

export interface DelegationError {
  error: string;
  message: string;
}

export interface DelegationResult {
  /** Child task id; also the id accepted by `delegate_wait` and `GET /api/tasks/:id`. */
  id: string;
  bot: string | null;
  status: DelegationStatus;
  result?: string;
  error?: string;
  elapsed_s: number;
  /** Mirrors the request: true when a follow-up turn will run automatically. */
  report_back?: boolean;
}

export type DelegationWaitResult = DelegationResult[];

export interface DelegationServiceOptions {
  registry: BotRegistry;
  store: Store;
  bus: EventBus;
  orchestrator: Orchestrator;
  notifications: NotificationService;
  concurrency?: number;
  /** Injected so tests can shorten the 30-minute give-up window. */
  followupMaxMs?: number;
  /** A delegated child still running after this long is stopped and reported as timed out. */
  childTimeoutMs?: number;
  now?: () => Date;
}

interface DelegationRecord {
  messageId: string;
  parentBotId: string;
  dto: DelegationDto;
  reportBack: boolean;
  round: number;
  timer?: ReturnType<typeof setTimeout>;
  timedOut?: boolean;
  timeoutMs?: number;
}

interface Completion {
  promise: Promise<void>;
  resolve: () => void;
}

/** Children of one initiator turn; the follow-up waits for every member. */
interface RoundBatch {
  parentTaskId: string;
  parentBotId: string;
  round: number;
  childIds: Set<string>;
}

interface PendingFollowUp {
  parentTaskId: string;
  parentBotId: string;
  round: number;
  childIds: string[];
  since: number;
  timer: ReturnType<typeof setTimeout> | undefined;
}

interface ChildResult {
  id: string;
  botId: string;
  botName: string;
  brief: string;
  status: DelegationStatus;
  error: string | null;
  reply: string | null;
  deliverables: Array<{ path: string; size: number }>;
}

function clampWaitSeconds(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return MAX_WAIT_SECONDS;
  return Math.max(0, Math.min(Math.floor(value), MAX_WAIT_SECONDS));
}

function elapsedSeconds(startedAt: string, endedAt: string | null, now: Date): number {
  const start = Date.parse(startedAt);
  const end = endedAt === null ? now.getTime() : Date.parse(endedAt);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return Math.max(0, Math.round((end - start) / 100) / 10);
}

function metaString(meta: JsonRecord | null, key: string): string | undefined {
  const value = meta?.[key];
  return typeof value === 'string' ? value : undefined;
}

function metaStatus(meta: JsonRecord | null): DelegationStatus | undefined {
  const value = meta?.status;
  return value === 'running' || value === 'done' || value === 'failed' || value === 'cancelled' || value === 'interrupted'
    ? value
    : undefined;
}

/**
 * A delegated child task is invisible to the target bot's timeline. It is
 * announced only in the initiator's timeline through a `kind=delegation`
 * message whose `meta` mirrors {@link DelegationDto}.
 */
export class DelegationService {
  private readonly registry: BotRegistry;
  private readonly store: Store;
  private readonly bus: EventBus;
  private readonly orchestrator: Orchestrator;
  private readonly notifications: NotificationService;
  private readonly concurrency: number;
  private readonly followupMaxMs: number;
  private readonly childTimeoutMs: number;
  private readonly now: () => Date;
  private readonly records = new Map<string, DelegationRecord>();
  private readonly completions = new Map<string, Completion>();
  private readonly batches = new Map<string, RoundBatch>();
  private readonly pendingFollowups = new Map<string, PendingFollowUp>();
  private unsubscribe: (() => void) | undefined;

  constructor(options: DelegationServiceOptions) {
    this.registry = options.registry;
    this.store = options.store;
    this.bus = options.bus;
    this.orchestrator = options.orchestrator;
    this.notifications = options.notifications;
    this.concurrency = options.concurrency ?? DEFAULT_DELEGATION_CONCURRENCY;
    this.followupMaxMs = options.followupMaxMs ?? FOLLOWUP_MAX_MS;
    const envMinutes = Number(process.env['CHIVES_DELEGATION_TIMEOUT_MINUTES'] ?? '');
    this.childTimeoutMs =
      options.childTimeoutMs ??
      (Number.isFinite(envMinutes) && envMinutes > 0 ? envMinutes * 60_000 : CHILD_TIMEOUT_MS);
    this.now = options.now ?? (() => new Date());
    if (!Number.isInteger(this.concurrency) || this.concurrency < 1) {
      throw new Error('delegation concurrency must be a positive integer');
    }
  }

  /** Retries queued follow-ups whenever a bot's turn ends. */
  start(): void {
    if (this.unsubscribe !== undefined) return;
    this.unsubscribe = this.bus.subscribe((event) => {
      if (event.type !== 'task.updated' || event.task.status === 'running') return;
      const botId = event.task.botId;
      setTimeout(() => {
        void this.flushFollowups(botId).catch(() => undefined);
      }, 0).unref();
    });
  }

  close(): void {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    for (const entry of this.pendingFollowups.values()) {
      if (entry.timer !== undefined) clearTimeout(entry.timer);
    }
    this.pendingFollowups.clear();
    this.batches.clear();
  }

  get limit(): number {
    return this.concurrency;
  }

  /** Starts (and optionally waits for) one delegation. */
  async delegate(identity: SessionIdentity, input: DelegationStartInput): Promise<DelegationResult | DelegationError> {
    const parent = this.store.tasks.get(identity.taskId);
    if (parent === undefined) return { error: 'unknown_task', message: '当前会话绑定的任务不存在' };
    if (parent.status !== 'running') {
      return { error: 'task_not_running', message: '当前任务已经结束，不能再委派' };
    }
    if (identity.depth >= 2) {
      return { error: 'depth_exceeded', message: '委派深度最多 2 层，被委派的任务不能再向下一层派发' };
    }

    const initiator = this.registry.get(identity.botId);
    if (initiator === undefined) return { error: 'unknown_bot', message: `未知的发起方 ${identity.botId}` };
    const target = this.registry.get(input.bot);
    if (target === undefined) return { error: 'unknown_bot', message: `未知的 bot「${input.bot}」` };
    if (target.id === identity.botId) {
      return { error: 'self_delegation', message: '不能把任务委派给自己' };
    }
    if (!initiator.can_delegate_to.includes(target.id)) {
      return {
        error: 'forbidden',
        message: `「${initiator.name}」的 can_delegate_to 不含「${target.name}」`,
      };
    }

    const running = this.store.tasks.listRunningDelegated(target.id).length;
    if (running >= this.concurrency) {
      return {
        error: 'busy',
        message: `「${target.name}」已有 ${running} 个进行中的委派任务（上限 ${this.concurrency}）`,
      };
    }

    const startedAt = this.now().toISOString();
    const reportBack = input.reportBack !== false;
    const round = this.orchestrator.currentRound(parent.id);
    const child = this.store.tasks.create({
      botId: target.id,
      title: `委派：${input.brief.trim().slice(0, 70)}`,
      startedAt,
      parentTaskId: parent.id,
      depth: identity.depth + 1,
      delegated: true,
      brief: input.brief,
    });
    const delegation: DelegationDto = {
      delegationId: randomUUID(),
      parentTaskId: parent.id,
      targetBotId: target.id,
      targetBotName: target.name,
      childTaskId: child.id,
      brief: input.brief,
      reportBack,
      status: 'running',
      startedAt,
      endedAt: null,
      error: null,
    };
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: parent.botId,
      taskId: parent.id,
      role: 'bot',
      kind: 'delegation',
      content: `委派给 ${target.name}：${input.brief}`,
      meta: this.dtoMeta(delegation, round),
      createdAt: startedAt,
    });
    this.records.set(child.id, {
      messageId: message.id,
      parentBotId: parent.botId,
      dto: delegation,
      reportBack,
      round,
    });
    if (reportBack) {
      const key = this.batchKey(parent.id, round);
      const batch = this.batches.get(key) ?? {
        parentTaskId: parent.id,
        parentBotId: parent.botId,
        round,
        childIds: new Set<string>(),
      };
      batch.childIds.add(child.id);
      this.batches.set(key, batch);
    }
    this.ensureCompletion(child.id);
    this.publish({
      type: 'message.created',
      botId: parent.botId,
      taskId: parent.id,
      message: toMessageDto(message),
    });

    void this.orchestrator.startDelegatedTask(child, input.brief);
    const timeoutMs =
      input.timeoutMinutes !== undefined ? input.timeoutMinutes * 60_000 : this.childTimeoutMs;
    if (timeoutMs > 0) {
      const record = this.records.get(child.id);
      if (record !== undefined) {
        record.timeoutMs = timeoutMs;
        record.timer = setTimeout(() => {
          if (this.store.tasks.get(child.id)?.status !== 'running') return;
          record.timedOut = true;
          this.orchestrator.cancelDelegated(child.id);
        }, timeoutMs);
        record.timer.unref?.();
      }
    }

    // report_back makes the initiator's own turn end immediately; the server
    // opens a follow-up turn once every child of this round is terminal.
    if (!reportBack) {
      const waitSeconds = clampWaitSeconds(input.waitSeconds);
      if (waitSeconds > 0) await this.waitForIds([child.id], 'all', waitSeconds);
    }
    return this.result(identity, child.id);
  }

  /** Waits for any/all of the given child task ids, capped at 40 seconds. */
  async wait(identity: SessionIdentity, input: DelegationWaitInput): Promise<DelegationResult[]> {
    const ids = [...new Set(input.ids)].filter((id) => id.length > 0);
    if (ids.length === 0) return [];
    const mode: DelegationMode = input.mode === 'any' ? 'any' : 'all';
    const waitSeconds = clampWaitSeconds(input.waitSeconds);

    const running = ids.filter((id) => this.result(identity, id).status === 'running');
    // `any` returns immediately when at least one requested id is already terminal.
    const mustWait = mode === 'all' || running.length === ids.length;
    if (running.length > 0 && mustWait && waitSeconds > 0) {
      await this.waitForIds(running, mode, waitSeconds);
    }
    return ids.map((id) => this.result(identity, id));
  }

  /**
   * Called once at startup, after the orchestrator has marked running tasks
   * interrupted: keeps delegation rows honest instead of leaving them on
   * "running" forever.
   */
  syncInterrupted(): void {
    const interrupted = new Map<
      string,
      { parentTaskId: string; parentBotId: string; round: number; childIds: string[] }
    >();
    for (const message of this.store.messages.listByKind('delegation')) {
      const meta = message.meta;
      const childTaskId = metaString(meta, 'childTaskId');
      if (childTaskId === undefined) continue;
      const child = this.store.tasks.get(childTaskId);
      const targetBotId = metaString(meta, 'targetBotId');
      const targetBotName = metaString(meta, 'targetBotName') ?? targetBotId ?? '';
      const brief = metaString(meta, 'brief') ?? '';
      const startedAt = metaString(meta, 'startedAt') ?? message.createdAt;
      const delegationId = metaString(meta, 'delegationId') ?? message.id;
      const parentTaskId = metaString(meta, 'parentTaskId') ?? message.taskId ?? '';
      const reportBack = meta?.['reportBack'] === true;
      const round = typeof meta?.['round'] === 'number' ? meta['round'] : 1;
      const endedAt = child?.endedAt ?? this.now().toISOString();
      const status: DelegationStatus =
        child === undefined ? 'failed' : (child.status as DelegationStatus);
      const stale = metaStatus(meta) === 'running' && status !== 'running';
      if (!stale && child !== undefined && status === 'running') continue;

      const dto: DelegationDto = {
        delegationId,
        parentTaskId,
        targetBotId: targetBotId ?? child?.botId ?? '',
        targetBotName,
        childTaskId,
        brief,
        reportBack,
        status,
        startedAt,
        endedAt: status === 'running' ? null : endedAt,
        error:
          status === 'failed'
            ? (child === undefined ? '子任务不存在' : this.failureDetail(child))
            : null,
      };
      this.store.messages.updateMeta(message.id, this.dtoMeta(dto, round));
      if (child !== undefined) {
        this.records.set(child.id, {
          messageId: message.id,
          parentBotId: message.botId,
          dto,
          reportBack,
          round,
        });
      }
      if (stale) {
        this.publish({
          type: 'delegation.updated',
          botId: message.botId,
          taskId: parentTaskId,
          delegation: dto,
          ...(child === undefined ? {} : { task: toTaskDto(child) }),
        });
        if (reportBack && status === 'interrupted' && parentTaskId !== '') {
          const key = this.batchKey(parentTaskId, round);
          const entry = interrupted.get(key) ?? {
            parentTaskId,
            parentBotId: message.botId,
            round,
            childIds: [],
          };
          entry.childIds.push(childTaskId);
          interrupted.set(key, entry);
        }
      }
    }
    for (const entry of interrupted.values()) {
      this.enqueueFollowup(entry.parentTaskId, entry.parentBotId, entry.round, entry.childIds);
    }
  }

  /** The stop-after limit applied to one delegated child (for tests and status). */
  timeoutMsFor(childId: string): number | undefined {
    return this.records.get(childId)?.timeoutMs;
  }

  /** Called by the orchestrator when a delegated child reaches a terminal state. */
  handleChildFinished(child: TaskRecord, error: string | null): void {
    const record = this.records.get(child.id);
    if (record === undefined) return;
    if (record.timer !== undefined) clearTimeout(record.timer);
    const minutes = (record.timeoutMs ?? this.childTimeoutMs) / 60_000;
    const timeoutText = `超过 ${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} 分钟没有完成，已停止`;
    const dto: DelegationDto = {
      ...record.dto,
      status: child.status,
      endedAt: child.endedAt,
      error: record.timedOut === true
        ? timeoutText
        : child.status === 'failed' ? (error ?? this.failureDetail(child)) : null,
    };
    record.dto = dto;
    this.store.messages.updateMeta(record.messageId, this.dtoMeta(dto, record.round));
    this.publish({
      type: 'delegation.updated',
      botId: record.parentBotId,
      taskId: dto.parentTaskId,
      delegation: dto,
      task: toTaskDto(child),
    });
    this.resolve(child.id);
    if (child.status === 'failed' || child.status === 'cancelled') {
      this.abandonParent(child.id);
    }
    this.maybeFollowUp(child.id);
  }

  /** Cancels every running child when its parent fails or is cancelled. */
  handleParentFinished(parent: TaskRecord, status: TaskStatus): void {
    if (status !== 'failed' && status !== 'cancelled') return;
    this.abandonParent(parent.id);
    for (const child of this.store.tasks.listByParent(parent.id)) {
      if (child.status !== 'running') continue;
      this.orchestrator.cancelDelegated(child.id);
    }
  }

  private abandonParent(parentTaskId: string): void {
    for (const [key, entry] of [...this.pendingFollowups]) {
      if (entry.parentTaskId === parentTaskId) this.dropPending(key);
    }
    for (const [key, batch] of [...this.batches]) {
      if (batch.parentTaskId === parentTaskId) this.batches.delete(key);
    }
  }

  private failureDetail(child: TaskRecord): string {
    const messages = this.store.messages.listByTask(child.id);
    const notice = [...messages].reverse().find((message) => message.kind === 'notice');
    if (notice !== undefined) return notice.content;
    return `子任务以 ${child.status} 结束`;
  }

  private result(identity: SessionIdentity, id: string): DelegationResult {
    const task = this.store.tasks.get(id);
    if (
      task === undefined ||
      !task.delegated ||
      task.parentTaskId !== identity.taskId
    ) {
      return { id, bot: null, status: 'failed', error: 'not_found', elapsed_s: 0 };
    }
    const status = task.status;
    const record = this.records.get(id);
    const result: DelegationResult = {
      id,
      bot: task.botId,
      status,
      elapsed_s: elapsedSeconds(task.startedAt, task.endedAt, this.now()),
      ...(record === undefined ? {} : { report_back: record.reportBack }),
    };
    if (status === 'done') {
      const final = [...this.store.messages.listByTask(id)].reverse().find((message) => message.role === 'bot');
      if (final !== undefined) result.result = final.content;
    }
    if (status === 'failed') {
      result.error = this.records.get(id)?.dto.error ?? this.failureDetail(task);
    }
    if (status === 'interrupted') {
      result.status = 'failed';
      result.error = '服务重启，委派已中断';
    }
    return result;
  }

  /** Running report-back children per initiating bot; drives the UI waiting badge. */
  pendingReportBackCounts(): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const [childId, record] of this.records) {
      if (!record.reportBack) continue;
      if (this.store.tasks.get(childId)?.status !== 'running') continue;
      counts[record.parentBotId] = (counts[record.parentBotId] ?? 0) + 1;
    }
    return counts;
  }

  /** Task ids whose follow-up is queued (for tests and status). */
  pendingFollowupTaskIds(): string[] {
    return [...new Set([...this.pendingFollowups.values()].map((entry) => entry.parentTaskId))];
  }

  /**
   * Merges queued follow-up results into the next user turn of the same task.
   * Called by the orchestrator right before a prompt is built.
   */
  consumeFollowup(taskId: string): string | null {
    const keys = [...this.pendingFollowups.entries()]
      .filter(([, entry]) => entry.parentTaskId === taskId)
      .map(([key]) => key);
    if (keys.length === 0) return null;
    const childIds: string[] = [];
    for (const key of keys) {
      const entry = this.pendingFollowups.get(key);
      if (entry === undefined) continue;
      for (const id of entry.childIds) if (!childIds.includes(id)) childIds.push(id);
      this.dropPending(key);
    }
    const children = this.childResults(childIds);
    if (children.length === 0) return null;
    return this.renderFollowup(
      children,
      '（你的跟进消息到达前，用户已经在原任务里发来新消息，子任务结果并入本轮。）',
    );
  }

  private batchKey(parentTaskId: string, round: number): string {
    return `${parentTaskId}\u0000${round}`;
  }

  /** Queues one batch when its last child reaches a terminal state. */
  private maybeFollowUp(childId: string): void {
    const record = this.records.get(childId);
    if (record === undefined || !record.reportBack) return;
    const key = this.batchKey(record.dto.parentTaskId, record.round);
    const batch = this.batches.get(key);
    if (batch === undefined) return;
    for (const id of batch.childIds) {
      if (this.store.tasks.get(id)?.status === 'running') return;
    }
    this.batches.delete(key);
    this.enqueueFollowup(batch.parentTaskId, batch.parentBotId, batch.round, [...batch.childIds]);
  }

  private enqueueFollowup(
    parentTaskId: string,
    parentBotId: string,
    round: number,
    childIds: string[],
  ): void {
    const parent = this.store.tasks.get(parentTaskId);
    if (parent === undefined || childIds.length === 0) return;
    if (parent.status === 'failed' || parent.status === 'cancelled') return;
    const key = this.batchKey(parentTaskId, round);
    if (this.pendingFollowups.has(key)) return;
    const entry: PendingFollowUp = {
      parentTaskId,
      parentBotId,
      round,
      childIds,
      since: this.now().getTime(),
      timer: undefined,
    };
    entry.timer = setTimeout(() => {
      void this.flushFollowups(parentBotId).catch(() => undefined);
    }, this.followupMaxMs);
    entry.timer.unref();
    this.pendingFollowups.set(key, entry);
    // The child can finish while its parent's finalize is still unwinding, so
    // never start the follow-up re-entrantly.
    setTimeout(() => {
      void this.flushFollowups(parentBotId).catch(() => undefined);
    }, 0).unref();
  }

  private dropPending(key: string): void {
    const entry = this.pendingFollowups.get(key);
    if (entry !== undefined && entry.timer !== undefined) clearTimeout(entry.timer);
    this.pendingFollowups.delete(key);
  }

  /**
   * Starts every queued follow-up whose bot is free. Too-old entries are given
   * up with a timeline notice plus an important notification instead.
   */
  async flushFollowups(botId?: string): Promise<void> {
    for (const [key, entry] of [...this.pendingFollowups]) {
      if (botId !== undefined && entry.parentBotId !== botId) continue;
      const parent = this.store.tasks.get(entry.parentTaskId);
      if (parent === undefined) {
        this.dropPending(key);
        continue;
      }
      if (parent.status === 'failed' || parent.status === 'cancelled') {
        this.dropPending(key);
        continue;
      }
      if (this.now().getTime() - entry.since >= this.followupMaxMs) {
        this.dropPending(key);
        this.giveUpFollowup(parent);
        continue;
      }
      if (parent.delegated) {
        if (parent.status === 'running') continue;
      } else if (this.store.tasks.findRunning(parent.botId) !== undefined) {
        continue;
      }
      const children = this.childResults(entry.childIds);
      if (children.length === 0) {
        this.dropPending(key);
        continue;
      }
      const names = [...new Set(children.map((child) => child.botName))];
      const started = this.orchestrator.startFollowUp(entry.parentTaskId, {
        content: `委派结果已返回 · ${names.join('、')}`,
        prompt: this.renderFollowup(children, ''),
        meta: {
          childTaskIds: entry.childIds,
          targetBotNames: names,
          delegationIds: children.flatMap((child) => {
            const id = this.records.get(child.id)?.dto.delegationId;
            return id === undefined ? [] : [id];
          }),
        },
      });
      if (started) this.dropPending(key);
    }
  }

  private giveUpFollowup(parent: TaskRecord): void {
    const root = this.rootTaskOf(parent);
    const bot = this.registry.get(root.botId);
    const botName = bot?.name ?? root.botId;
    const title = '委派结果已返回';
    const notification = this.notifications.notifyGuardrail(
      root.botId,
      root.id,
      title,
      `${botName}一直在忙，没有自动合成`,
    );
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: root.botId,
      taskId: root.id,
      role: 'system',
      kind: 'notice',
      content: `委派结果已返回，但${botName}一直在忙，没有自动合成`,
      meta: {
        code: 'delegation_followup_timeout',
        notification: true,
        notificationId: notification.id,
      },
      createdAt: this.now().toISOString(),
    });
    this.publish({
      type: 'message.created',
      botId: root.botId,
      taskId: root.id,
      message: toMessageDto(message),
    });
    this.notifications.publishCreated(notification);
  }

  private childResults(ids: readonly string[]): ChildResult[] {
    const results: ChildResult[] = [];
    for (const id of ids) {
      const task = this.store.tasks.get(id);
      if (task === undefined) continue;
      const bot = this.registry.get(task.botId);
      const record = this.records.get(id);
      const dto = record?.dto;
      let status: DelegationStatus = task.status;
      let error: string | null = null;
      if (status === 'failed') error = dto?.error ?? this.failureDetail(task);
      if (record?.timedOut === true) {
        // Stopped by the delegation timeout: report it as a failure with its reason.
        status = 'failed';
        error = dto?.error ?? '超时，已停止';
      }
      if (status === 'interrupted') {
        status = 'failed';
        error = '子任务因服务重启中断';
      }
      const final = [...this.store.messages.listByTask(id)]
        .reverse()
        .find((message) => message.role === 'bot');
      results.push({
        id,
        botId: task.botId,
        botName: bot?.name ?? task.botId,
        brief: task.brief ?? dto?.brief ?? '',
        status,
        error,
        reply: final?.content ?? null,
        deliverables: this.deliverablesOf(task),
      });
    }
    return results;
  }

  private deliverablesOf(task: TaskRecord): Array<{ path: string; size: number }> {
    const root = this.rootTaskOf(task);
    const from = Date.parse(task.startedAt);
    const to = task.endedAt === null ? Number.POSITIVE_INFINITY : Date.parse(task.endedAt);
    return this.store.deliverables
      .listByTask(root.id)
      .filter((record) => {
        if (record.botId !== task.botId) return false;
        const at = Date.parse(record.createdAt);
        if (Number.isFinite(from) && at < from) return false;
        return to === Number.POSITIVE_INFINITY || at <= to;
      })
      .map((record) => ({ path: record.path, size: record.size }));
  }

  private renderFollowup(children: ChildResult[], note: string): string {
    const labels: Record<DelegationStatus, string> = {
      running: '进行中',
      done: '已完成',
      failed: '失败',
      cancelled: '已取消',
      interrupted: '已中断',
    };
    const lines = [
      '## 委派结果已返回',
      '',
      '以下子任务由你发起，现已全部结束。请核对关键数字与数据时间，合成一份结论先行的回答，标明每个结论来自哪个 bot；失败或缺失的如实说明；不要为同一件事再次委派，不要重复取子任务已经取过的数据。',
    ];
    if (note !== '') lines.push('', note);
    children.forEach((child, index) => {
      lines.push('', `### ${index + 1}. ${child.botName}（${child.botId}）· ${labels[child.status]}`);
      lines.push(`任务：${child.brief.trim()}`);
      if (child.status === 'done') {
        const reply = child.reply ?? '（子任务没有留下最终回复）';
        const cut = reply.length > MAX_FOLLOWUP_RESULT_CHARS;
        lines.push('最终回复：', cut ? reply.slice(0, MAX_FOLLOWUP_RESULT_CHARS) : reply);
        if (cut) lines.push(`（已截断：原文共 ${reply.length} 字）`);
      } else if (child.error !== null) {
        lines.push(`失败原因：${child.error}`);
      }
      if (child.deliverables.length > 0) {
        lines.push('交付物（路径相对被委派方的工作空间）：');
        for (const deliverable of child.deliverables) {
          lines.push(`- ${deliverable.path}（${deliverable.size} 字节）`);
        }
      }
    });
    return lines.join('\n');
  }

  private rootTaskOf(task: TaskRecord): TaskRecord {
    let current = task;
    const seen = new Set<string>([current.id]);
    while (current.parentTaskId !== null) {
      const parent = this.store.tasks.get(current.parentTaskId);
      if (parent === undefined || seen.has(parent.id)) break;
      seen.add(parent.id);
      current = parent;
    }
    return current;
  }

  private async waitForIds(ids: readonly string[], mode: DelegationMode, seconds: number): Promise<void> {
    const waits = ids.map((id) => this.ensureCompletion(id).promise);
    if (waits.length === 0) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<void>((resolve) => {
      timer = setTimeout(resolve, seconds * 1000);
      timer.unref();
    });
    const done =
      mode === 'any' ? Promise.race([...waits, timeout]) : Promise.race([Promise.all(waits), timeout]);
    try {
      await done;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  private ensureCompletion(taskId: string): Completion {
    const existing = this.completions.get(taskId);
    if (existing !== undefined) return existing;
    let resolve: () => void = () => undefined;
    const promise = new Promise<void>((settle) => {
      resolve = settle;
    });
    const completion: Completion = { promise, resolve };
    this.completions.set(taskId, completion);
    return completion;
  }

  private resolve(taskId: string): void {
    const completion = this.completions.get(taskId);
    if (completion === undefined) return;
    completion.resolve();
    this.completions.delete(taskId);
  }

  private dtoMeta(dto: DelegationDto, round?: number): JsonRecord {
    return {
      delegationId: dto.delegationId,
      parentTaskId: dto.parentTaskId,
      targetBotId: dto.targetBotId,
      targetBotName: dto.targetBotName,
      childTaskId: dto.childTaskId,
      brief: dto.brief,
      reportBack: dto.reportBack,
      ...(round === undefined ? {} : { round }),
      status: dto.status,
      startedAt: dto.startedAt,
      endedAt: dto.endedAt,
      error: dto.error,
    };
  }

  private publish(input: Parameters<EventBus['publish']>[0]): ServerEvent {
    return this.bus.publish(input);
  }
}

