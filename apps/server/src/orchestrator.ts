import { botWorkspace } from './deliverables/files.js';
import { isSampleStyleReport, sampleReportSegment, styleReportAttachment } from './settings/style-report-turn.js';
/** One conversation turn: select a task, drive the harness, persist and publish events. */

import { randomUUID } from 'node:crypto';
import { join } from 'node:path';

import type {
  CrashedEvent,
  PermissionDecision,
  PermissionRequest,
} from '@chives/acp-client';

import type { BotManifest, BotRegistry } from './bots/index.js';
import { toDeliverableDto, toMessageDto, toTaskDto, toToolEventDto, toUsageDto } from './api/dto.js';
import type {
  ApprovalDecision,
  ApprovalDto,
  BotStatus,
  DeliverableDto,
  MessageAttachmentDto,
  ServerEvent,
  TaskDto,
} from './api/protocol.js';
import { DEFAULT_APPROVAL_TIMEOUT_MS } from './config.js';
import { classifyKind } from './deliverables/kinds.js';
import { cleanupScratch, isDeliverablePath } from './deliverables/layout.js';
import { writeWorkspaceMap } from './deliverables/map.js';
import { renderAttachmentPrompt } from './deliverables/uploads.js';
import {
  MAX_DELIVERABLES_PER_TASK,
  diffWorkspace,
  snapshotWorkspace,
  type WorkspaceSnapshot,
} from './deliverables/snapshot.js';
import { prepareWorkspace } from './deliverables/workspace.js';
import { AppError } from './errors.js';
import {
  classifyFailure,
  failureMeta,
  failureNotice,
  type ClassifiedFailure,
  type FailurePhase,
} from './failures.js';
import type { EventBus, EventInput } from './events/index.js';
import { MemoryService } from './memory/index.js';
import { DshDriver, type DshDriverOptions } from './harness/dsh-driver.js';
import type { HarnessDriver, HarnessEvent, HarnessSink } from './harness/types.js';
import { SessionTokenRegistry } from './delegations/tokens.js';
import { formatShanghaiTime } from './time.js';
import type { TaskClassifier } from './segmentation/classifier.js';
import { SegmentationService } from './segmentation/service.js';
import type {
  ApprovalRecord,
  DeliverableRecord,
  JsonRecord,
  MessageRecord,
  Store,
  TaskRecord,
  TaskStatus,
} from './store/index.js';

export const DEFAULT_CONTINUE_WITHIN_MS = 30 * 60_000;
export const CANCEL_FALLBACK_MS = 10_000;

export type ChooseTaskDecision =
  | { kind: 'continue'; task: TaskRecord }
  | { kind: 'new' };

/**
 * M1 task-selection rule: keep the previous task when it finished normally
 * less than `withinMs` ago. T132 replaces this function's callers, not the
 * timeline format.
 */
export function chooseTask(
  latest: TaskRecord | undefined,
  now: Date,
  withinMs: number = DEFAULT_CONTINUE_WITHIN_MS,
): ChooseTaskDecision {
  if (latest === undefined || latest.status !== 'done' || latest.endedAt === null) {
    return { kind: 'new' };
  }
  const endedAt = Date.parse(latest.endedAt);
  if (!Number.isFinite(endedAt)) return { kind: 'new' };
  return now.getTime() - endedAt < withinMs ? { kind: 'continue', task: latest } : { kind: 'new' };
}

interface ActiveTurn {
  taskId: string;
  botId: string;
  /** Timeline that receives this turn's SSE events (the initiator for a delegated child). */
  eventBotId: string;
  delegated: boolean;
  sessionId: string | null;
  cancelled: boolean;
  crashNoticed: boolean;
  /** Set once this turn's harness session is established; a crash before that is a startup failure. */
  sessionReady?: boolean;
  error: string | null;
  /** Stable classification of the failure that ended this turn. */
  errorCode: ClassifiedFailure['code'] | null;
  /** A tool result reported a missing watch engine; still a successful turn. */
  engineUnavailable: boolean;
  /** Last usage sample seen in this turn; null when the harness never reported one. */
  lastUsage: { used: number; size: number; at: string } | null;
  fallbackTimer: ReturnType<typeof setTimeout> | undefined;
}

export interface DelegationHooks {
  onChildFinished(task: TaskRecord, error: string | null): void;
  onParentFinished(task: TaskRecord, status: TaskStatus): void;
  /** Results of report-back children, merged into a user message on the same task. */
  consumeFollowup?(taskId: string): string | null;
}

/** One automatic follow-up turn after all report-back children finished. */
export interface FollowUpInput {
  /** Timeline separator text, e.g. 「委派结果已返回 · 个股分析师」. */
  content: string;
  prompt: string;
  meta?: JsonRecord;
}

interface PendingApproval {
  resolve: (decision: PermissionDecision) => void;
  timer: ReturnType<typeof setTimeout>;
  messageId: string;
  sourceTaskId: string;
  rootTaskId: string;
  rootBotId: string;
}

export interface OrchestratorOptions {
  styleReportTurn?: (botId: string, text: string, attachment: MessageAttachmentDto, messageId: string, sink: HarnessSink) => Promise<string>;
  profileCommand?: (botId:string,text:string)=>Promise<string|null>;
  profileNotice?: (botId:string,text:string) => Promise<string>;
  profileForTurn?: (botId:string,text:string) => string;
  executionFor?: (id: string) => Record<string,string>;
  registry: BotRegistry;
  store: Store;
  bus: EventBus;
  now?: () => Date;
  continueWithinMs?: number;
  /** Segmentation classifier; defaults to the model only when the driver supports it. */
  classifier?: TaskClassifier;
  classifierMode?: 'model' | 'rules';
  /** Close an inactive segment after this long (default 30 minutes). */
  idleCloseMs?: number;
  summaryTimeoutMs?: number;
  /** Server-side approval timeout; the ACP client timeout is set above this. */
  approvalTimeoutMs?: number;
  /** Injected in tests (FakeDriver). */
  driver?: HarnessDriver;
  /** Used to build the real DshDriver when `driver` is absent. */
  driverOptions?: Omit<DshDriverOptions, 'onNotice' | 'onPermission' | 'onCrash'>;
  /** Shared with the internal delegation API; one registry per server process. */
  sessions?: SessionTokenRegistry;
  /** Base URL handed to chives-mcp as `CHIVES_API`. */
  chivesApi?: string;
  /** Root of per-bot workspaces (`<dataDir>/bots/<id>/workspace`). */
  dataDir?: string;
  /** T134 bot-level memory; shared with the HTTP API. */
  memory?: MemoryService;
}

export interface SubmitResult {
  messageId: string;
  taskId: string;
}

export interface ProactiveTaskInput {
  /** Human title shown in the timeline separator and stored as the task title. */
  title: string;
  /** Timeline label prefix: 「主动消息」 or 「盯盘告警」. */
  label: string;
  /** Routine prompt or alert-analysis request appended after the T132 injection. */
  prompt: string;
  /** Daily-budget bucket. */
  origin: 'routine' | 'alert';
  /** Extra JSON stored on the proactive separator message. */
  meta?: JsonRecord;
}

/**
 * True only for a structured MCP error (`"code": "engine_unreachable"`, possibly
 * JSON-escaped). A bare mention of the word, e.g. in loaded skill text, must not
 * turn the turn into an "engine not started" notice.
 */
export function isEngineUnreachable(output: string): boolean {
  return /\\?"code\\?"\s*:\s*\\?"engine_unreachable\\?"/.test(output);
}

export class Orchestrator {
  private readonly registry: BotRegistry;
  private readonly store: Store;
  private readonly bus: EventBus;
  private readonly driver: HarnessDriver;
  private readonly now: () => Date;
  private readonly continueWithinMs: number;
  private readonly active = new Map<string, ActiveTurn>();
  private readonly delegatedActive = new Map<string, ActiveTurn>();
  private readonly statuses = new Map<string, BotStatus>();
  private readonly runningTaskIds = new Map<string, string | null>();
  /** Turn counter per task; a delegation batch belongs to the round it started in. */
  private readonly rounds = new Map<string, number>();
  /** Includes a message whose segmentation/classification is still in flight. */
  private readonly submitting = new Set<string>();
  private readonly pendingApprovals = new Map<string, PendingApproval>();
  private readonly approvalTimeoutMs: number;
  private readonly dataDir: string | undefined;
  readonly memory: MemoryService | undefined;
  readonly sessions: SessionTokenRegistry;
  readonly segmentation: SegmentationService;
  private hooks: DelegationHooks | undefined;
  /** Last UTC day a per-bot scratch cleanup ran in this process. */
  private readonly scratchCleanupDays = new Map<string, string>();

  private readonly styleReportTurn: OrchestratorOptions['styleReportTurn'];
  private readonly profileCommand: OrchestratorOptions['profileCommand'];
  private readonly profileNotice: OrchestratorOptions['profileNotice'];
  private readonly profileForTurn: OrchestratorOptions['profileForTurn'];
  private readonly executionFor: OrchestratorOptions['executionFor'];

  constructor(options: OrchestratorOptions) {
    this.styleReportTurn=options.styleReportTurn;
    this.profileCommand=options.profileCommand;
    this.profileNotice=options.profileNotice;
    this.profileForTurn=options.profileForTurn;
    this.executionFor = options.executionFor;
    this.registry = options.registry;
    this.store = options.store;
    this.bus = options.bus;
    this.now = options.now ?? (() => new Date());
    this.continueWithinMs = options.continueWithinMs ?? DEFAULT_CONTINUE_WITHIN_MS;
    this.approvalTimeoutMs = options.approvalTimeoutMs ?? DEFAULT_APPROVAL_TIMEOUT_MS;
    this.sessions = options.sessions ?? new SessionTokenRegistry();
    this.dataDir = options.dataDir ?? options.driverOptions?.dataDir;
    this.memory =
      options.memory ??
      (this.dataDir === undefined
        ? undefined
        : new MemoryService({ dataDir: this.dataDir, now: this.now, bus: this.bus }));

    if (options.driver !== undefined) {
      this.driver = options.driver;
    } else if (options.driverOptions !== undefined) {
      this.driver = new DshDriver({
        ...options.driverOptions,
        approvalTimeoutMs: this.approvalTimeoutMs,
        chivesApi: options.chivesApi ?? `http://127.0.0.1:8880`,
        sessionCredentialFor: (bot, task) =>
          this.sessions.issue({ botId: bot.id, taskId: task.id, depth: task.depth }),
        onNotice: (bot, task, text) => {
          this.appendSystem(bot.id, task.id, 'notice', text);
        },
        onPermission: (bot, request, task) => this.handlePermissionRequest(bot, request, task),
        onCrash: (bot, event) => {
          this.recordCrash(bot, event);
        },
      });
    } else {
      throw new Error('Orchestrator requires either a driver or driverOptions');
    }

    this.segmentation = new SegmentationService({
      registry: this.registry,
      store: this.store,
      bus: this.bus,
      driver: this.driver,
      now: this.now,
      ...(options.classifier === undefined ? {} : { classifier: options.classifier }),
      ...(options.classifierMode === undefined ? {} : { mode: options.classifierMode }),
      ...(options.idleCloseMs === undefined ? {} : { idleCloseMs: options.idleCloseMs }),
      ...(options.summaryTimeoutMs === undefined
        ? {}
        : { summaryTimeoutMs: options.summaryTimeoutMs }),
      ...(this.memory === undefined ? {} : { memory: this.memory }),
      onCancelDelegated: (taskId) => {
        this.cancelDelegated(taskId);
      },
    });
  }

  /** Marks tasks left running by a previous process as interrupted. */
  start(): void {
    const interrupted = this.store.tasks.interruptRunning(this.now().toISOString());
    for (const task of interrupted) {
      this.publish({
        type: 'task.updated',
        botId: task.botId,
        taskId: task.id,
        task: toTaskDto(task),
      });
      this.appendSystem(task.botId, task.id, 'notice', '服务重启，上一轮任务已中断。');
    }
    // No in-memory waiter survives a restart; keep the approvals table honest.
    for (const approval of this.store.approvals.listPending()) {
      try {
        this.settleApproval(approval.id, 'cancelled', 'system', false);
      } catch {
        // Startup must continue even if one stale approval row is malformed.
      }
    }
    for (const bot of this.registry.list()) {
      this.statuses.set(bot.id, 'idle');
      this.runningTaskIds.set(bot.id, null);
    }
    this.segmentation.start();
  }

  status(botId: string): BotStatus {
    return this.statuses.get(botId) ?? 'idle';
  }

  runningTaskId(botId: string): string | null {
    return this.active.get(botId)?.taskId ?? this.runningTaskIds.get(botId) ?? null;
  }

  /**
   * Segments the message, persists the user text, and schedules the turn. The
   * model classifier can take a moment, so callers await this method while the
   * HTTP layer still answers with 202.
   */
  async submitMessage(
    botId: string,
    text: string,
    attachments: readonly MessageAttachmentDto[] = [],
    messageId?: string,
  ): Promise<SubmitResult> {
    const bot = this.requireHired(botId);
    if (this.submitting.has(botId) || this.store.tasks.findRunning(botId) !== undefined) {
      throw new AppError(409, 'bot_busy', 'this bot already has a running task');
    }
    this.submitting.add(botId);
    try {
      return await this.submitLocked(bot, text, attachments, messageId);
    } finally {
      this.submitting.delete(botId);
    }
  }

  private async submitLocked(
    bot: BotManifest,
    text: string,
    attachments: readonly MessageAttachmentDto[],
    messageId?: string,
  ): Promise<SubmitResult> {
    const botId = bot.id;
    const now = this.now();
    const latest = this.store.tasks.latestForBot(botId);
    const report = this.styleReportTurn && styleReportAttachment(attachments);
    if (report && attachments.length !== 1) {
      throw new AppError(400, 'report_attachments', '风格报告解读每轮只接受当前章节附件。');
    }
    const decision = report
      ? {kind:'new' as const, reason:isSampleStyleReport(report) ? sampleReportSegment : 'style_report'}
      : latest?.segmentReason === sampleReportSegment
        ? {kind:'new' as const, reason:'after_style_report_sample'}
        : await this.segmentation.decide(botId, text, now);
    this.requireHired(botId);
    const continuing = decision.kind === 'continue' && decision.previous !== undefined;
    const fallbackTitle =
      attachments.length === 0 ? text : attachments.map((attachment) => attachment.name).join('、');
    let task: TaskRecord;
    if (decision.kind === 'continue' && decision.previous !== undefined) {
      task = this.store.tasks.restart(decision.previous.id);
    } else {
      task = this.store.tasks.create({
        botId,
        title: text.trim().slice(0, 80) || fallbackTitle.slice(0, 80),
        startedAt: now.toISOString(),
        depth: 0,
        delegated: false,
      });
    }
    task = this.store.tasks.setSegmentReason(task.id, decision.reason) ?? task;
    const round = continuing ? (this.rounds.get(task.id) ?? 1) + 1 : 1;
    this.rounds.set(task.id, round);

    // Closing the previous segment is asynchronous; `closed_at` is written
    // before the first await inside closeTask, so the new injection sees it.
    if (!continuing && decision.reason !== sampleReportSegment && latest !== undefined &&
        latest.segmentReason !== sampleReportSegment && latest.id !== task.id && (latest.closedAt ?? null) === null) {
      void this.segmentation.closeTask(latest.id, 'new_task').catch(() => undefined);
    }

    const message = this.store.messages.append({
      id: messageId ?? randomUUID(),
      botId,
      taskId: task.id,
      role: 'user',
      kind: 'text',
      content: text,
      meta: attachments.length === 0 ? null : { attachments: [...attachments] },
      createdAt: now.toISOString(),
    });
    if (!report) this.segmentation.recordUserSymbols(task.id, text);

    let promptText = text;
    let contextMeta: JsonRecord | null = task.contextMeta ?? null;
    if (!report && !continuing) {
      const injection = this.segmentation.buildInjection(botId, message);
      promptText = injection.text;
      contextMeta = { ...injection.meta };
    }
    if (!report && this.memory !== undefined) {
      const cursor = contextMeta?.['memoryAuditCursor'];
      const changes = this.memory.consumeChanges(
        botId,
        typeof cursor === 'number' ? cursor : null,
      );
      if (changes.text !== '') {
        promptText = `${changes.text}\n\n${promptText}`;
      }
      const nextCursor = changes.auditCursor;
      if (typeof cursor !== 'number' || nextCursor !== cursor) {
        contextMeta = { ...(contextMeta ?? {}), memoryAuditCursor: nextCursor };
      }
    }
    const watchNotices = report ? '' : this.consumeWatchNotices(botId);
    if (watchNotices !== '') promptText = `${watchNotices}\n\n${promptText}`;
    // A follow-up queued for this very task is folded into the user's turn
    // instead of running as a separate one.
    const followupContext = this.hooks?.consumeFollowup?.(task.id) ?? null;
    if (followupContext !== null) promptText = `${followupContext}\n\n${promptText}`;
    const attachmentPrompt = renderAttachmentPrompt(attachments);
    if (attachmentPrompt !== '') promptText = `${promptText}\n${attachmentPrompt}`;
    if (contextMeta !== null) {
      this.store.tasks.setContextMeta(task.id, contextMeta);
      task = this.store.tasks.get(task.id) ?? task;
    }

    const turn: ActiveTurn = {
      taskId: task.id,
      botId,
      eventBotId: botId,
      delegated: false,
      sessionId: task.harnessSessionId,
      cancelled: false,
      crashNoticed: false,
      error: null,
      errorCode: null,
      engineUnavailable: false,
      lastUsage: null,
      fallbackTimer: undefined,
    };
    this.active.set(botId, turn);
    this.runningTaskIds.set(botId, task.id);

    this.publish({
      type: 'message.created',
      botId,
      taskId: task.id,
      message: toMessageDto(message),
    });
    if (continuing) {
      this.publish({
        type: 'task.updated',
        botId,
        taskId: task.id,
        task: toTaskDto(task),
      });
    }
    this.publish({
      type: 'task.started',
      botId,
      taskId: task.id,
      task: toTaskDto(task),
    });
    this.setStatus(botId, 'starting');

    this.launchTurn(bot, task.id, promptText, turn,text, report ? {attachment:report,messageId:message.id} : undefined);
    return { messageId: message.id, taskId: task.id };
  }

  /** User cancellations queued by the watch service; consumed by the next prompt. */
  private consumeWatchNotices(botId: string): string {
    const key = `watch.notices.${botId}`;
    const queued = this.store.settings.get<string[]>(key);
    if (!Array.isArray(queued) || queued.length === 0) return '';
    this.store.settings.delete(key);
    return `近期盯盘变更（用户操作，供参考）：\n${queued.map((entry) => `- ${entry}`).join('\n')}`;
  }

  /**
   * Starts a proactive task: always a new segment, never a continuation. The
   * timeline gets a `kind=proactive` separator; the harness receives the T132
   * injection block followed by the caller's prompt.
   */
  async submitProactive(botId: string, input: ProactiveTaskInput): Promise<SubmitResult> {
    const bot = this.requireHired(botId);
    if (this.submitting.has(botId) || this.store.tasks.findRunning(botId) !== undefined) {
      throw new AppError(409, 'bot_busy', 'this bot already has a running task');
    }
    this.submitting.add(botId);
    try {
      return this.submitProactiveLocked(bot, input);
    } finally {
      this.submitting.delete(botId);
    }
  }

  private submitProactiveLocked(bot: BotManifest, input: ProactiveTaskInput): SubmitResult {
    const botId = bot.id;
    const now = this.now();
    const latest = this.store.tasks.latestForBot(botId);
    const task = this.store.tasks.create({
      botId,
      title: input.title,
      startedAt: now.toISOString(),
      depth: 0,
      delegated: false,
      origin: input.origin,
    });
    if (latest !== undefined && latest.id !== task.id && (latest.closedAt ?? null) === null) {
      void this.segmentation.closeTask(latest.id, 'proactive').catch(() => undefined);
    }

    const separatorText = `${input.label} · ${formatShanghaiTime(now)} · ${input.title}`;
    const message = this.store.messages.append({
      id: randomUUID(),
      botId,
      taskId: task.id,
      role: 'system',
      kind: 'proactive',
      content: separatorText,
      meta: { ...(input.meta ?? {}), origin: input.origin, title: input.title },
      createdAt: now.toISOString(),
    });

    const injection = this.segmentation.buildInjection(botId, message);
    let promptText = `${injection.text}\n\n${input.prompt}`;
    let contextMeta: JsonRecord | null = { ...injection.meta };
    if (this.memory !== undefined) {
      const cursor = contextMeta?.['memoryAuditCursor'];
      const changes = this.memory.consumeChanges(
        botId,
        typeof cursor === 'number' ? cursor : null,
      );
      if (changes.text !== '') promptText = `${changes.text}\n\n${promptText}`;
      const watchNotices = this.consumeWatchNotices(botId);
      if (watchNotices !== '') promptText = `${watchNotices}\n\n${promptText}`;
      const nextCursor = changes.auditCursor;
      if (typeof cursor !== 'number' || nextCursor !== cursor) {
        contextMeta = { ...(contextMeta ?? {}), memoryAuditCursor: nextCursor };
      }
    }
    this.store.tasks.setContextMeta(task.id, contextMeta);
    const stored = this.store.tasks.get(task.id) ?? task;
    this.rounds.set(stored.id, 1);

    const turn: ActiveTurn = {
      taskId: stored.id,
      botId,
      eventBotId: botId,
      delegated: false,
      sessionId: stored.harnessSessionId,
      cancelled: false,
      crashNoticed: false,
      error: null,
      errorCode: null,
      engineUnavailable: false,
      lastUsage: null,
      fallbackTimer: undefined,
    };
    this.active.set(botId, turn);
    this.runningTaskIds.set(botId, stored.id);

    this.publish({ type: 'message.created', botId, taskId: stored.id, message: toMessageDto(message) });
    this.publish({ type: 'task.started', botId, taskId: stored.id, task: toTaskDto(stored) });
    this.setStatus(botId, 'starting');
    this.launchTurn(bot, stored.id, promptText, turn);
    return { messageId: message.id, taskId: stored.id };
  }

  /** Cancels one specific running task, leaving any other bot task alone. */
  cancelTask(taskId: string): { taskId: string } {
    const direct = this.active.get(this.store.tasks.get(taskId)?.botId ?? '');
    const turn =
      direct !== undefined && direct.taskId === taskId
        ? direct
        : [...this.active.values()].find((entry) => entry.taskId === taskId);
    if (turn === undefined) {
      const running = this.store.tasks.get(taskId);
      if (running === undefined) throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
      if (running.status !== 'running') throw new AppError(409, 'no_running_task', 'this task is not running');
      const bot = this.requireBot(running.botId);
      this.finalize(bot, taskId, 'cancelled', null);
      return { taskId };
    }
    this.requestTurnCancel(turn);
    return { taskId };
  }

  private requestTurnCancel(turn: ActiveTurn): void {
    const bot = this.requireBot(turn.botId);
    turn.cancelled = true;
    if (turn.sessionId !== null) {
      try {
        const result = this.driver.cancel(bot, turn.sessionId);
        if (result instanceof Promise) void result.catch(() => undefined);
      } catch {
        // The fallback timer below still finalizes the turn.
      }
    }
    this.cancelPendingApprovals(turn.taskId);
    if (turn.fallbackTimer === undefined) {
      turn.fallbackTimer = setTimeout(() => {
        if (this.active.get(turn.botId) === turn) {
          this.finalize(bot, turn.taskId, 'cancelled', turn.lastUsage);
        }
      }, CANCEL_FALLBACK_MS);
      turn.fallbackTimer.unref();
    }
  }

  /**
   * Makes an old segment the next continuation target. Every other unclosed
   * segment of the same bot is closed through the same summary path T132 uses.
   */
  async reopenTask(taskId: string): Promise<TaskDto> {
    const task = this.store.tasks.get(taskId);
    if (task === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    if (task.delegated) {
      throw new AppError(400, 'validation_error', 'a delegated task cannot be reopened');
    }
    this.requireHired(task.botId);
    const running = this.store.tasks.findRunning(task.botId);
    if (running !== undefined && running.id !== taskId) {
      throw new AppError(409, 'bot_busy', 'this bot already has a running task');
    }
    const unclosed = this.store.tasks
      .listUnclosedForBot(task.botId)
      .filter((entry) => entry.id !== taskId);
    await Promise.all(
      unclosed.map((entry) =>
        this.segmentation.closeTask(entry.id, 'reopen').catch(() => undefined),
      ),
    );
    this.requireHired(task.botId);
    const reopened = this.store.tasks.reopen(taskId, this.now().toISOString());
    if (reopened === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    const dto = toTaskDto(reopened, this.store.summaries.get(taskId));
    this.publish({ type: 'task.updated', botId: task.botId, taskId, task: dto });
    return dto;
  }

  /** Undoes a pending reopen when the user dismisses the continuation hint. */
  cancelReopenTask(taskId: string): TaskDto {
    const task = this.store.tasks.get(taskId);
    if (task === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    if ((task.reopenedAt ?? null) === null) {
      return toTaskDto(task, this.store.summaries.get(taskId));
    }
    const updated = this.store.tasks.cancelReopen(taskId, this.now().toISOString());
    if (updated === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    const dto = toTaskDto(updated, this.store.summaries.get(taskId));
    this.publish({ type: 'task.updated', botId: task.botId, taskId, task: dto });
    return dto;
  }

  /** Asks the active turn to stop; marks the task cancelled if the driver stays silent. */
  cancel(botId: string): { taskId: string } {
    const bot = this.requireBot(botId);
    const turn = this.active.get(botId);
    if (turn === undefined) {
      const running = this.store.tasks.findRunning(botId);
      if (running === undefined) {
        throw new AppError(409, 'no_running_task', 'this bot has no running task');
      }
      this.finalize(bot, running.id, 'cancelled', null);
      return { taskId: running.id };
    }

    this.requestTurnCancel(turn);
    return { taskId: turn.taskId };
  }

  /**
   * Re-runs the last user message of a finished task without adding another
   * user bubble, so the timeline keeps one copy of the request.
   */
  async retryTask(taskId: string): Promise<SubmitResult> {
    const task = this.store.tasks.get(taskId);
    if (task === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    if (task.delegated) {
      throw new AppError(400, 'validation_error', 'a delegated task cannot be retried');
    }
    const bot = this.requireHired(task.botId);
    if (this.submitting.has(bot.id) || this.store.tasks.findRunning(bot.id) !== undefined) {
      throw new AppError(409, 'bot_busy', 'this bot already has a running task');
    }
    const lastUser = [...this.store.messages.listByTask(taskId)]
      .reverse()
      .find((message) => message.role === 'user');
    if (lastUser === undefined) {
      throw new AppError(400, 'nothing_to_retry', 'this task has no user message to retry');
    }
    this.submitting.add(bot.id);
    try {
      const restarted = this.store.tasks.restart(taskId);
      this.rounds.set(taskId, (this.rounds.get(taskId) ?? 1) + 1);
      const turn: ActiveTurn = {
        taskId,
        botId: bot.id,
        eventBotId: bot.id,
        delegated: false,
        sessionId: restarted.harnessSessionId,
        cancelled: false,
        crashNoticed: false,
        error: null,
        errorCode: null,
        engineUnavailable: false,
        lastUsage: null,
        fallbackTimer: undefined,
      };
      this.active.set(bot.id, turn);
      this.runningTaskIds.set(bot.id, taskId);
      this.publish({
        type: 'task.updated',
        botId: bot.id,
        taskId,
        task: toTaskDto(restarted),
      });
      this.publish({
        type: 'task.started',
        botId: bot.id,
        taskId,
        task: toTaskDto(restarted),
      });
      this.setStatus(bot.id, 'starting');
      const recorded = lastUser.meta?.['attachments'];
      const report = this.styleReportTurn && Array.isArray(recorded) && styleReportAttachment(recorded);
      this.launchTurn(bot, taskId, lastUser.content, turn, undefined,
        report ? {attachment:report,messageId:lastUser.id} : undefined);
      return { messageId: lastUser.id, taskId };
    } finally {
      this.submitting.delete(bot.id);
    }
  }

  private readonly unfinishedTurns=new Set<Promise<void>>();
  private launchTurn(...args:Parameters<Orchestrator['runTurn']>):void{
    const pending=this.runTurn(...args);
    this.unfinishedTurns.add(pending);
    void pending.then(()=>this.unfinishedTurns.delete(pending),()=>this.unfinishedTurns.delete(pending));
  }

  async close(): Promise<void> {
    this.segmentation.stop();
    for (const turn of this.active.values()) {
      if (turn.fallbackTimer !== undefined) clearTimeout(turn.fallbackTimer);
    }
    this.active.clear();
    this.delegatedActive.clear();
    this.rounds.clear();
    await this.driver.shutdown();
    await Promise.allSettled(this.unfinishedTurns);
  }

  /** Restarts harness processes (idle ones now, busy ones after their turn) to apply a new model config. */
  async reloadModel(botId?:string): Promise<void> {
    const driver = this.driver as HarnessDriver & { reloadModel?: (id?:string) => Promise<void> };
    await driver.reloadModel?.(botId);
  }

  /** Current turn number of a task; delegations started in the same turn share it. */
  currentRound(taskId: string): number {
    return this.rounds.get(taskId) ?? 1;
  }

  /**
   * Opens a follow-up turn inside an existing task (used after all report-back
   * children of one round finished). Returns false when the bot or task is busy,
   * so the caller can queue and retry.
   */
  startFollowUp(taskId: string, input: FollowUpInput): boolean {
    const task = this.store.tasks.get(taskId);
    if (task === undefined || task.status === 'running') return false;
    const bot = this.registry.get(task.botId);
    if (bot === undefined || !this.registry.isHired(bot.id)) return false;
    if (task.delegated) {
      if (this.delegatedActive.has(taskId)) return false;
    } else if (
      this.submitting.has(bot.id) ||
      this.active.has(bot.id) ||
      this.store.tasks.findRunning(bot.id) !== undefined
    ) {
      return false;
    }

    const now = this.now();
    const restarted = this.store.tasks.restart(taskId);
    this.rounds.set(taskId, (this.rounds.get(taskId) ?? 1) + 1);
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: task.delegated ? this.rootTaskOf(task).botId : bot.id,
      taskId,
      role: 'system',
      kind: 'proactive',
      content: input.content,
      meta: { followup: true, ...(input.meta ?? {}), round: this.currentRound(taskId) },
      createdAt: now.toISOString(),
    });
    const turn: ActiveTurn = {
      taskId,
      botId: bot.id,
      eventBotId: message.botId,
      delegated: task.delegated,
      sessionId: restarted.harnessSessionId,
      cancelled: false,
      crashNoticed: false,
      error: null,
      errorCode: null,
      engineUnavailable: false,
      lastUsage: null,
      fallbackTimer: undefined,
    };
    if (task.delegated) {
      this.delegatedActive.set(taskId, turn);
    } else {
      this.active.set(bot.id, turn);
      this.runningTaskIds.set(bot.id, taskId);
    }
    this.publish({ type: 'message.created', botId: message.botId, taskId, message: toMessageDto(message) });
    this.publish({ type: 'task.updated', botId: message.botId, taskId, task: toTaskDto(restarted) });
    this.publish({ type: 'task.started', botId: message.botId, taskId, task: toTaskDto(restarted) });
    if (!task.delegated) this.setStatus(bot.id, 'starting');
    this.launchTurn(bot, taskId, input.prompt, turn);
    return true;
  }

  setDelegationHooks(hooks: DelegationHooks): void {
    this.hooks = hooks;
  }

  /**
   * Runs a child task in the target bot's process/workspace. It neither
   * changes the target's user-facing status nor takes its user task slot.
   */
  startDelegatedTask(task: TaskRecord, brief: string): void {
    const bot = this.registry.get(task.botId);
    if (!bot || !this.registry.isHired(task.botId)) {
      const finished = this.store.tasks.finish(task.id, 'failed', this.now().toISOString());
      this.hooks?.onChildFinished(finished, bot ? '这位 Bot 尚未聘用' : `未知的 bot「${task.botId}」`);
      return;
    }
    const parent = task.parentTaskId === null ? undefined : this.store.tasks.get(task.parentTaskId);
    const turn: ActiveTurn = {
      taskId: task.id,
      botId: bot.id,
      eventBotId: parent?.botId ?? bot.id,
      delegated: true,
      sessionId: task.harnessSessionId,
      cancelled: false,
      crashNoticed: false,
      error: null,
      errorCode: null,
      engineUnavailable: false,
      lastUsage: null,
      fallbackTimer: undefined,
    };
    this.delegatedActive.set(task.id, turn);
    this.rounds.set(task.id, 1);
    this.launchTurn(bot, task.id, brief, turn);
  }

  cancelDelegated(taskId: string): void {
    const turn = this.delegatedActive.get(taskId);
    if (turn === undefined) {
      const running = this.store.tasks.get(taskId);
      if (running !== undefined && running.status === 'running') {
        this.finalizeDelegated(taskId, 'cancelled', null, null);
      }
      return;
    }
    turn.cancelled = true;
    const bot = this.registry.get(turn.botId);
    if (bot !== undefined && turn.sessionId !== null) {
      try {
        const result = this.driver.cancel(bot, turn.sessionId);
        if (result instanceof Promise) void result.catch(() => undefined);
      } catch {
        // Fallback below still finalizes the child.
      }
    }
    this.cancelPendingApprovals(taskId);
    if (turn.fallbackTimer === undefined) {
      turn.fallbackTimer = setTimeout(() => {
        if (this.delegatedActive.get(taskId) === turn) this.finalizeDelegated(taskId, 'cancelled', null, null);
      }, CANCEL_FALLBACK_MS);
      turn.fallbackTimer.unref();
    }
  }

  requireHired(botId: string): BotManifest {
    const bot = this.requireBot(botId);
    if (!this.registry.isHired(botId)) throw new AppError(409, 'bot_not_hired', '请先聘用这位 Bot，再开始新的工作。');
    return bot;
  }

  private requireBot(botId: string): BotManifest {
    const bot = this.registry.get(botId);
    if (bot === undefined) throw new AppError(404, 'bot_not_found', `unknown bot "${botId}"`);
    return bot;
  }

  private async runTurn(
    bot: BotManifest,
    taskId: string,
    text: string,
    turn: ActiveTurn,
    userText?:string,
    report?: {attachment: MessageAttachmentDto; messageId: string},
  ): Promise<void> {
    const workspace =
      this.dataDir === undefined ? null : botWorkspace(this.dataDir, bot.id);
    if (workspace !== null) {
      try {
        prepareWorkspace(workspace, { now: this.now() });
        this.cleanupScratchOncePerDay(bot.id, workspace);
      } catch {
        // A workspace that cannot be prepared must not block the turn.
      }
    }
    const before: WorkspaceSnapshot | null =
      workspace === null ? null : snapshotWorkspace(workspace);
    let captured = false;
    const capture = (): void => {
      if (captured || workspace === null || before === null) return;
      captured = true;
      try {
        this.captureDeliverables(bot, taskId, before, workspace);
      } catch {
        // A failed scan must not change the turn's outcome.
      }
      // The map reflects every change of the turn, including non-deliverables.
      try {
        writeWorkspaceMap(workspace, { now: this.now() });
      } catch {
        // writeWorkspaceMap already logs; the turn must still finish.
      }
    };
    const finish = (status: TaskStatus): void => {
      capture();
      this.finalizeTurn(bot, taskId, status, turn);
    };
    const committed: string[] = [];
    let flushed = false;
    const flush = (): void => {
      if (flushed) return;
      flushed = true;
      if (this.store.tasks.get(taskId)?.status !== 'running') return;
      for (const content of committed) {
        this.appendBotMessage(bot.id, taskId, turn.eventBotId, content);
      }
    };
    const sink: HarnessSink = (event) => {
      try {
        if (this.store.tasks.get(taskId)?.status !== 'running') return;
        this.handleHarnessEvent(bot, taskId, turn, event, committed);
      } catch {
        // Persistence failures on one event must not abort the turn.
      }
    };

    let phase: FailurePhase = 'session';
    try {
      if (!turn.delegated) this.setStatus(bot.id, 'starting');
      const task = this.store.tasks.get(taskId);
      if (task === undefined) throw new AppError(500, 'task_missing', `task "${taskId}" disappeared`);
      if (report && this.styleReportTurn) {
        phase = 'prompt';
        this.setStatus(bot.id, 'working');
        const answer = await this.styleReportTurn(bot.id, userText ?? text, report.attachment, report.messageId, sink);
        if (!turn.cancelled) this.appendBotMessage(bot.id, taskId, turn.eventBotId, answer);
        finish(turn.cancelled ? 'cancelled' : 'done');
        return;
      }
      if(userText!==undefined&&this.profileCommand){
        const receipt=await this.profileCommand(bot.id,userText);
        if(receipt!==null){
          if(!turn.cancelled)this.appendBotMessage(bot.id,taskId,turn.eventBotId,receipt);
          finish(turn.cancelled?'cancelled':'done');
          return;
        }
      }
      if(userText!==undefined&&this.profileNotice){
        const notice=await this.profileNotice(bot.id,userText);
        if(turn.cancelled){finish('cancelled');return;}
        if(notice){
          this.appendBotMessage(bot.id,taskId,turn.eventBotId,notice);
          text+='\n系统已向用户说明画像差异并给出澄清问题。继续处理本轮其他需求，勿重复提出更正。';
        }
      }
      const execution = this.executionFor?.(bot.id);
      let sessionTask = task;
      if (execution) {
        const key = 'execution/' + task.id;
        const prior = this.store.settings.get(key);
        if (task.harnessSessionId && JSON.stringify(prior) !== JSON.stringify(execution)) {
          sessionTask = {...task, harnessSessionId: null};
          const recent = this.store.messages.listByTask(task.id)
            .filter(message => message.role === 'user' || message.role === 'bot').slice(-10);
          text = '以下为此前对话记录：\n' + recent.map(message =>
            message.role + ': ' + message.content.slice(0, 1500)).join('\n') + '\n本轮任务：\n' + text;
        }
        this.store.tasks.setContextMeta(task.id, {...task.contextMeta, execution});
      }
      const sessionId = await this.driver.ensureSession(bot, sessionTask);
      if (execution) this.store.settings.set('execution/' + task.id, execution);
      turn.sessionReady = true;
      turn.sessionId = sessionId;
      if (task.harnessSessionId !== sessionId) {
        this.store.tasks.setHarnessSession(taskId, sessionId);
      }
      if (turn.cancelled || this.store.tasks.get(taskId)?.status !== 'running') {
        flush();
        finish('cancelled');
        return;
      }
      if (!turn.delegated) this.setStatus(bot.id, 'working');
      phase = 'prompt';
      const profile=this.profileForTurn?.(bot.id,text);
      const prompt=profile?profile+'\n\n本轮任务：\n'+text:text;
      const result = await this.driver.prompt(bot, sessionId, prompt, sink);
      flush();
      const status: TaskStatus =
        turn.cancelled || result.stopReason === 'cancelled' ? 'cancelled' : 'done';
      if (status === 'done' && turn.engineUnavailable) {
        const engineFailure: ClassifiedFailure = { code: 'engine_unavailable', detail: '' };
        this.appendSystem(
          bot.id,
          taskId,
          'notice',
          failureNotice(engineFailure),
          failureMeta(engineFailure),
        );
      }
      finish(status);
    } catch (error) {
      flush();
      const failure = classifyFailure(error, phase);
      turn.error = failure.detail;
      turn.errorCode = failure.code;
      if (turn.cancelled) {
        finish('cancelled');
        return;
      }
      const notice = failureNotice(failure);
      if (!turn.crashNoticed) {
        this.appendSystem(bot.id, taskId, 'notice', notice, failureMeta(failure));
      }
      this.publish({
        type: 'error',
        botId: turn.eventBotId,
        taskId,
        code: failure.code,
        message: notice,
      });
      finish('failed');
    } finally {
      const current = this.active.get(bot.id);
      if (current === turn) this.active.delete(bot.id);
      if (this.delegatedActive.get(taskId) === turn) this.delegatedActive.delete(taskId);
    }
  }

  /** Removes stale scratch files on a bot's first turn each UTC day. */
  private cleanupScratchOncePerDay(botId: string, workspace: string): void {
    const now = this.now();
    const day = now.toISOString().slice(0, 10);
    if (this.scratchCleanupDays.get(botId) === day) return;
    this.scratchCleanupDays.set(botId, day);
    try {
      cleanupScratch(workspace, { now });
    } catch {
      // Cleanup is best-effort and must never fail a task.
    }
  }

  /**
   * Records files added or modified during one turn. A delegated child's files
   * belong to the root task's timeline, while `bot_id` stays the producing bot.
   */
  private captureDeliverables(
    bot: BotManifest,
    taskId: string,
    before: WorkspaceSnapshot,
    workspace: string,
  ): void {
    const after = snapshotWorkspace(workspace);
    const changes = diffWorkspace(before, after).filter((change) => isDeliverablePath(change.path));
    if (changes.length === 0) return;
    const task = this.store.tasks.get(taskId);
    if (task === undefined) return;
    const root = this.rootTaskOf(task);
    const existing = this.store.deliverables.listByTask(root.id);
    const byKey = new Map(existing.map((record) => [`${record.botId}\0${record.path}`, record]));
    let total = existing.length;
    let overflow = 0;
    const recorded: DeliverableRecord[] = [];
    const createdAt = this.now().toISOString();

    for (const change of changes) {
      const found = byKey.get(`${bot.id}\0${change.path}`);
      if (found === undefined && total >= MAX_DELIVERABLES_PER_TASK) {
        overflow += 1;
        continue;
      }
      const record: DeliverableRecord = {
        id: found?.id ?? randomUUID(),
        taskId: root.id,
        botId: bot.id,
        path: change.path,
        kind: classifyKind(change.path),
        size: change.size,
        createdAt,
      };
      const stored = this.store.deliverables.upsert(record);
      if (found === undefined) {
        total += 1;
        byKey.set(`${bot.id}\0${change.path}`, stored);
      }
      recorded.push(stored);
    }

    if (recorded.length === 0 && overflow === 0) return;
    const deliverables: DeliverableDto[] = recorded.map(toDeliverableDto);
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: root.botId,
      taskId: root.id,
      role: 'bot',
      kind: 'deliverable',
      content:
        recorded.length === 0
          ? `本轮新增文件 ${overflow} 个，已达到单任务记录上限`
          : `本轮产出 ${recorded.length} 个文件${overflow > 0 ? `，另有 ${overflow} 个未记录` : ''}`,
      meta: {
        deliverableIds: deliverables.map((deliverable) => deliverable.id),
        deliverables,
        overflow,
        sourceBotId: bot.id,
        sourceBotName: bot.name,
        delegated: root.id !== taskId,
        rootTaskId: root.id,
      },
      createdAt,
    });
    for (const deliverable of deliverables) {
      this.publish({
        type: 'deliverable.created',
        botId: root.botId,
        taskId: root.id,
        deliverable,
      });
    }
    this.publish({
      type: 'message.created',
      botId: root.botId,
      taskId: root.id,
      message: toMessageDto(message),
    });
  }

  private handleHarnessEvent(
    bot: BotManifest,
    taskId: string,
    turn: ActiveTurn,
    event: HarnessEvent,
    committed: string[],
  ): void {
    switch (event.type) {
      case 'message':
        committed.push(event.text);
        return;
      case 'thought':
        return;
      case 'tool_start': {
        const tool = this.store.toolEvents.start({
          id: randomUUID(),
          taskId,
          toolCallId: event.toolCallId,
          title: event.title ?? event.toolCallId,
          kind: event.kind ?? 'other',
          rawInput: event.rawInput ?? null,
          startedAt: this.now().toISOString(),
        });
        this.publish({
          type: 'tool.started',
          botId: turn.eventBotId,
          taskId,
          tool: toToolEventDto(tool),
        });
        return;
      }
      case 'tool_end': {
        if (isEngineUnreachable(event.output)) {
          turn.engineUnavailable = true;
        }
        let tool = this.store.toolEvents.finish(
          taskId,
          event.toolCallId,
          event.status,
          event.output,
          this.now().toISOString(),
        );
        if (tool === undefined) {
          this.store.toolEvents.start({
            id: randomUUID(),
            taskId,
            toolCallId: event.toolCallId,
            title: event.title ?? event.toolCallId,
            kind: event.kind ?? 'other',
            startedAt: this.now().toISOString(),
          });
          tool = this.store.toolEvents.finish(
            taskId,
            event.toolCallId,
            event.status,
            event.output,
            this.now().toISOString(),
          );
        }
        if (tool !== undefined) {
          this.publish({
            type: 'tool.ended',
            botId: turn.eventBotId,
            taskId,
            tool: toToolEventDto(tool),
          });
        }
        return;
      }
      case 'usage': {
        turn.lastUsage = { used: event.used, size: event.size, at: this.now().toISOString() };
        const usage = this.store.usage.add(taskId, event.used, event.size, this.now());
        this.publish({
          type: 'usage',
          botId: turn.eventBotId,
          taskId,
          usage: toUsageDto(usage),
        });
        return;
      }
      case 'draft_reset': {
        if (turn.sessionId === null) return;
        this.publish({
          type: 'draft.reset',
          botId: turn.eventBotId,
          taskId,
          sessionId: turn.sessionId,
          ...(event.attemptId === undefined ? {} : { attemptId: event.attemptId }),
        });
        return;
      }
      case 'draft_delta': {
        if (turn.sessionId === null) return;
        this.publish({
          type: 'draft.delta',
          botId: turn.eventBotId,
          taskId,
          sessionId: turn.sessionId,
          kind: event.kind,
          text: event.text,
          ...(event.attemptId === undefined ? {} : { attemptId: event.attemptId }),
        });
        return;
      }
      case 'draft_commit': {
        if (turn.sessionId === null) return;
        this.publish({
          type: 'draft.commit',
          botId: turn.eventBotId,
          taskId,
          sessionId: turn.sessionId,
          text: event.text,
        });
        return;
      }
      default:
        return;
    }
  }

  private finalizeTurn(bot: BotManifest, taskId: string, status: TaskStatus, turn: ActiveTurn): void {
    if (turn.delegated) {
      this.finalizeDelegated(taskId, status, turn.error, turn.lastUsage);
      return;
    }
    this.finalize(bot, taskId, status, turn.lastUsage, turn.errorCode);
  }

  private finalize(
    bot: BotManifest,
    taskId: string,
    status: TaskStatus,
    lastUsage: { used: number; size: number; at: string } | null,
    failureCode: ClassifiedFailure['code'] | null = null,
  ): void {
    const current = this.store.tasks.get(taskId);
    if (current === undefined || current.status !== 'running') return;
    this.cancelPendingApprovals(taskId);
    this.recordLastContext(taskId, lastUsage);
    const errorCode = status === 'failed' ? failureCode : null;
    const finished = this.store.tasks.finish(
      taskId,
      status,
      this.now().toISOString(),
      errorCode,
    );
    this.publish({
      type: 'task.updated',
      botId: bot.id,
      taskId,
      task: toTaskDto(finished),
    });
    const turn = this.active.get(bot.id);
    if (turn !== undefined && turn.taskId === taskId) {
      if (turn.fallbackTimer !== undefined) clearTimeout(turn.fallbackTimer);
      turn.fallbackTimer = undefined;
      this.active.delete(bot.id);
    }
    this.runningTaskIds.set(bot.id, null);
    this.setStatus(
      bot.id,
      errorCode === 'harness_unavailable' ? 'error' : 'idle',
    );
    this.hooks?.onParentFinished(finished, finished.status);
  }

  private finalizeDelegated(
    taskId: string,
    status: TaskStatus,
    error: string | null | undefined,
    lastUsage: { used: number; size: number; at: string } | null,
  ): void {
    const current = this.store.tasks.get(taskId);
    if (current === undefined || current.status !== 'running') return;
    this.cancelPendingApprovals(taskId);
    this.recordLastContext(taskId, lastUsage);
    const finished = this.store.tasks.finish(taskId, status, this.now().toISOString());
    const turn = this.delegatedActive.get(taskId);
    if (turn !== undefined) {
      if (turn.fallbackTimer !== undefined) clearTimeout(turn.fallbackTimer);
      turn.fallbackTimer = undefined;
      this.delegatedActive.delete(taskId);
    }
    const eventBotId = turn?.eventBotId ?? current.botId;
    this.publish({
      type: 'task.updated',
      botId: eventBotId,
      taskId,
      task: toTaskDto(finished),
    });
    this.hooks?.onChildFinished(finished, error ?? turn?.error ?? null);
  }

  /** Persists the last usage sample of the turn that just ended, if it reported one. */
  private recordLastContext(
    taskId: string,
    usage: { used: number; size: number; at: string } | null,
  ): void {
    if (usage === null) return;
    this.store.tasks.setLastContext(taskId, usage.used, usage.size);
    this.store.usage.addRound(taskId, usage.used, usage.size, new Date(usage.at));
  }

  private appendBotMessage(
    botId: string,
    taskId: string,
    eventBotId: string,
    content: string,
  ): MessageRecord {
    const message = this.store.messages.append({
      id: randomUUID(),
      botId,
      taskId,
      role: 'bot',
      kind: 'text',
      content,
      createdAt: this.now().toISOString(),
    });
    this.segmentation.recordBotSymbols(taskId, content);
    // A delegated child's final answer belongs to `GET /api/tasks/:id`, not to
    // the initiator's timeline as a standalone bot message.
    if (eventBotId === botId) {
      this.publish({
        type: 'message.created',
        botId: eventBotId,
        taskId,
        message: toMessageDto(message),
      });
    }
    return message;
  }

  private appendSystem(
    botId: string,
    taskId: string | null,
    kind: 'notice' | 'approval',
    content: string,
    meta?: JsonRecord,
  ): MessageRecord {
    const message = this.store.messages.append({
      id: randomUUID(),
      botId,
      taskId,
      role: 'system',
      kind,
      content,
      ...(meta === undefined ? {} : { meta }),
      createdAt: this.now().toISOString(),
    });
    if (this.store.tasks.get(taskId ?? '')?.delegated !== true) {
      this.publish({
        type: 'message.created',
        botId,
        taskId,
        message: toMessageDto(message),
      });
    }
    return message;
  }

  /**
   * Entry point for a custom {@link HarnessDriver} permission callback. Blocks
   * until the user decides, the server timeout fires (reject), or the owning
   * task ends (cancelled).
   */
  handlePermissionRequest(
    bot: BotManifest,
    request: PermissionRequest,
    task: TaskRecord,
  ): Promise<PermissionDecision> {
    return this.requestApproval(bot, request, task);
  }

  private async requestApproval(
    bot: BotManifest,
    request: PermissionRequest,
    task: TaskRecord,
  ): Promise<PermissionDecision> {
    const sourceTask = this.store.tasks.get(task.id) ?? task;
    if (sourceTask.status !== 'running') return 'reject';
    const rootTask = this.rootTaskOf(sourceTask);
    const sourceBot = this.registry.get(sourceTask.botId) ?? bot;
    const rootBot = this.registry.get(rootTask.botId) ?? sourceBot;
    const approvalId = randomUUID();
    const options = request.options.map((option) => ({
      optionId: option.optionId,
      name: option.name,
      kind: option.kind,
    }));
    const record = this.store.approvals.add({
      id: approvalId,
      taskId: sourceTask.id,
      toolCallId: request.toolCallId,
      request: {
        toolCallId: request.toolCallId,
        title: request.title ?? null,
        rawInput: request.rawInput ?? null,
        options,
        botId: sourceBot.id,
        taskId: sourceTask.id,
      },
      decision: null,
      decidedAt: null,
      decidedBy: null,
    });
    const approval = this.approvalDto(record);
    const content = `需要你批准：${approval.title ?? approval.toolCallId}`;
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: rootBot.id,
      taskId: rootTask.id,
      role: 'system',
      kind: 'approval',
      content,
      meta: this.approvalMeta(approval),
      createdAt: this.now().toISOString(),
    });
    this.publish({
      type: 'message.created',
      botId: rootBot.id,
      taskId: rootTask.id,
      message: toMessageDto(message),
    });
    this.setStatus(rootBot.id, 'awaiting_approval');
    this.publish({
      type: 'approval.requested',
      botId: rootBot.id,
      taskId: rootTask.id,
      approvalId,
      toolCallId: request.toolCallId,
      title: approval.title,
      rawInput: approval.rawInput,
      options,
      approval,
    });

    return new Promise<PermissionDecision>((resolve) => {
      const timer = setTimeout(() => {
        try {
          this.settleApproval(approvalId, 'reject', 'timeout', false);
        } catch {
          // The task may have ended between the check and the timer.
        }
      }, this.approvalTimeoutMs);
      timer.unref();
      this.pendingApprovals.set(approvalId, {
        resolve,
        timer,
        messageId: message.id,
        sourceTaskId: sourceTask.id,
        rootTaskId: rootTask.id,
        rootBotId: rootBot.id,
      });
    });
  }

  /** Pending approvals, oldest first. `all` includes decided rows. */
  listApprovals(status: 'pending' | 'all' = 'pending'): ApprovalDto[] {
    const records = status === 'pending' ? this.store.approvals.listPending() : this.store.approvals.list();
    return records.map((record) => this.approvalDto(record));
  }

  /** Pending approval count per root bot, used by `GET /api/bots`. */
  pendingApprovalCounts(): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const record of this.store.approvals.listPending()) {
      const rootBotId = this.approvalDto(record).rootBotId;
      counts[rootBotId] = (counts[rootBotId] ?? 0) + 1;
    }
    return counts;
  }

  /** Applies a user decision. Duplicates are 409 and ended tasks are 410. */
  decideApproval(id: string, decision: 'allow' | 'reject'): ApprovalDto {
    const record = this.store.approvals.get(id);
    if (record === undefined) throw new AppError(404, 'approval_not_found', `unknown approval "${id}"`);
    const task = this.store.tasks.get(record.taskId);
    if (task === undefined || task.status !== 'running') {
      throw new AppError(410, 'task_ended', 'the task for this approval has already ended');
    }
    if (record.decision !== null) {
      throw new AppError(409, 'approval_decided', 'this approval has already been decided');
    }
    const settled = this.settleApproval(id, decision, 'user', true);
    if (settled === undefined) throw new AppError(404, 'approval_not_found', `unknown approval "${id}"`);
    return settled;
  }

  private settleApproval(
    id: string,
    decision: ApprovalDecision,
    decidedBy: string,
    requireRunning: boolean,
  ): ApprovalDto | undefined {
    const record = this.store.approvals.get(id);
    if (record === undefined) return undefined;
    if (record.decision !== null) return this.approvalDto(record);
    const task = this.store.tasks.get(record.taskId);
    if (requireRunning && (task === undefined || task.status !== 'running')) {
      throw new AppError(410, 'task_ended', 'the task for this approval has already ended');
    }
    const decidedAt = this.now().toISOString();
    const pending = this.pendingApprovals.get(id);
    const updated = this.store.approvals.decide(id, decision, decidedAt, decidedBy);
    if (updated === undefined) return undefined;
    const approval = this.approvalDto(updated);
    const message =
      pending === undefined
        ? this.findApprovalMessage(id)
        : this.store.messages.get(pending.messageId);
    if (message !== undefined) this.store.messages.updateMeta(message.id, this.approvalMeta(approval));
    this.publish({
      type: 'approval.decided',
      botId: approval.rootBotId,
      taskId: approval.rootTaskId,
      approval,
    });
    if (pending !== undefined) {
      clearTimeout(pending.timer);
      this.pendingApprovals.delete(id);
      pending.resolve(decision);
    }
    if (decision !== 'cancelled') this.refreshApprovalStatus(approval.rootBotId);
    return approval;
  }

  private cancelPendingApprovals(taskId: string): void {
    for (const [id, pending] of [...this.pendingApprovals]) {
      if (pending.sourceTaskId !== taskId && pending.rootTaskId !== taskId) continue;
      try {
        this.settleApproval(id, 'cancelled', 'system', false);
      } catch {
        // A pending approval must never block task finalization.
      }
    }
  }

  private refreshApprovalStatus(rootBotId: string): void {
    const stillPending = [...this.pendingApprovals.values()].some(
      (pending) => pending.rootBotId === rootBotId,
    );
    if (stillPending) {
      this.setStatus(rootBotId, 'awaiting_approval');
      return;
    }
    const running = this.store.tasks.findRunning(rootBotId);
    this.setStatus(rootBotId, running === undefined ? 'idle' : 'working');
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

  private approvalDto(record: ApprovalRecord): ApprovalDto {
    const request = record.request;
    const sourceTask = this.store.tasks.get(record.taskId);
    const requestBotId = typeof request.botId === 'string' ? request.botId : undefined;
    const sourceBotId = requestBotId ?? sourceTask?.botId ?? '';
    const sourceBot = this.registry.get(sourceBotId);
    const rootTask = sourceTask === undefined ? undefined : this.rootTaskOf(sourceTask);
    const rootBotId = rootTask?.botId ?? sourceBotId;
    const requestTaskId = typeof request.taskId === 'string' ? request.taskId : record.taskId;
    return {
      id: record.id,
      botId: sourceBotId,
      taskId: requestTaskId,
      rootTaskId: rootTask?.id ?? requestTaskId,
      sourceBotId,
      sourceBotName: sourceBot?.name ?? sourceBotId,
      rootBotId,
      delegated: sourceTask?.delegated ?? false,
      toolCallId: record.toolCallId,
      title: typeof request.title === 'string' ? request.title : null,
      rawInput: request.rawInput ?? null,
      options: Array.isArray(request.options)
        ? request.options.flatMap((option) => {
            if (typeof option !== 'object' || option === null || Array.isArray(option)) return [];
            const entry = option as Record<string, unknown>;
            if (typeof entry.optionId !== 'string' || typeof entry.name !== 'string') return [];
            return [{
              optionId: entry.optionId,
              name: entry.name,
              kind: typeof entry.kind === 'string' ? entry.kind : '',
            }];
          })
        : [],
      decision:
        record.decision === 'allow' || record.decision === 'reject' || record.decision === 'cancelled'
          ? record.decision
          : null,
      decidedAt: record.decidedAt,
      decidedBy: record.decidedBy,
    };
  }

  private approvalMeta(approval: ApprovalDto): JsonRecord {
    return {
      approvalId: approval.id,
      toolCallId: approval.toolCallId,
      title: approval.title,
      rawInput: approval.rawInput,
      options: approval.options,
      sourceTaskId: approval.taskId,
      sourceBotId: approval.sourceBotId,
      sourceBotName: approval.sourceBotName,
      rootTaskId: approval.rootTaskId,
      rootBotId: approval.rootBotId,
      delegated: approval.delegated,
      decision: approval.decision,
      decidedAt: approval.decidedAt,
      decidedBy: approval.decidedBy,
    };
  }

  private findApprovalMessage(approvalId: string): MessageRecord | undefined {
    return this.store.messages
      .listByKind('approval')
      .find((message) => message.meta?.['approvalId'] === approvalId);
  }

  private recordCrash(bot: BotManifest, event: CrashedEvent): void {
    const turn = this.active.get(bot.id);
    if (turn === undefined) return;
    turn.crashNoticed = true;
    const exit = `code=${event.code ?? 'null'}，signal=${event.signal ?? 'null'}`;
    // A process that exits before this turn has a session never started properly: report it as unavailable.
    const startup = turn.sessionReady !== true;
    const code = startup ? 'harness_unavailable' : 'harness_crashed';
    turn.errorCode = code;
    const failure: ClassifiedFailure = { code, detail: '' };
    this.appendSystem(
      bot.id,
      turn.taskId,
      'notice',
      startup
        ? `运行环境没有启动成功。检查 dsh 是否可用后重试。（harness 进程启动后退出 ${exit}）`
        : `这一轮中断了，已保留之前的内容。（harness 进程异常退出 ${exit}；下一条消息会自动重启进程）`,
      failureMeta(failure),
    );
  }

  private setStatus(botId: string, status: BotStatus): void {
    const runningTaskId = this.runningTaskIds.get(botId) ?? null;
    const previous = this.statuses.get(botId);
    this.statuses.set(botId, status);
    if (previous === status) return;
    this.publish({ type: 'bot.status', botId, status, runningTaskId });
  }

  private publish(input: EventInput): ServerEvent {
    return this.bus.publish(input);
  }
}
