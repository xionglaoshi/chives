/** Task segmentation: decision, context injection, summaries, and idle closing. */

import type { BotManifest, BotRegistry } from '../bots/index.js';
import type { MemoryService } from '../memory/index.js';

import { toTaskDto, toTaskSummaryDto } from '../api/dto.js';
import type { ServerEvent } from '../api/protocol.js';
import type { EventBus } from '../events/index.js';
import type {
  HarnessDriver,
  HiddenPromptDriver,
  HarnessSink,
} from '../harness/types.js';
import type {
  MessageRecord,
  Store,
  TaskRecord,
  TaskSummaryRecord,
} from '../store/index.js';
import {
  DshTaskClassifier,
  isTemporaryPromptDriver,
  type ClassifierMessage,
  type TaskClassifier,
} from './classifier.js';
import {
  buildContextInjection,
  MAX_RECENT_MESSAGES,
  MAX_TASK_LINES,
  type ContextInjection,
} from './context.js';
import { decideSegment, TWO_HOURS_MS } from './decide.js';
import {
  buildSummaryPrompt,
  fallbackSummary,
  parseSummaryResponse,
  type ParsedMemoryCandidate,
} from './summary.js';
import { extractBotSymbols, extractUserSymbols, normalizeSymbolCode } from '../symbols.js';

export const DEFAULT_TASK_IDLE_CLOSE_MS = 30 * 60_000;
export const IDLE_SCAN_INTERVAL_MS = 60_000;
export const SUMMARY_TIMEOUT_MS = 60_000;

export type ClassifierMode = 'model' | 'rules';

export interface SegmentationDecision {
  kind: 'continue' | 'new';
  reason: string;
  detail?: string;
  /** The task the rules looked at; the caller continues or closes it. */
  previous: TaskRecord | undefined;
}

export interface SegmentationServiceOptions {
  registry: BotRegistry;
  store: Store;
  bus: EventBus;
  driver: HarnessDriver;
  now: () => Date;
  classifier?: TaskClassifier;
  mode?: ClassifierMode;
  idleCloseMs?: number;
  summaryTimeoutMs?: number;
  /** Cancels a running delegated child of the segment being closed. */
  onCancelDelegated?: (taskId: string) => void;
  /** T134: bot-level memory. Omitted in older unit tests, which then see none. */
  memory?: MemoryService;
}

function isHiddenPromptDriver(driver: HarnessDriver): driver is HarnessDriver & HiddenPromptDriver {
  return typeof (driver as Partial<HiddenPromptDriver>).hiddenPrompt === 'function';
}

export class SegmentationService {
  private readonly registry: BotRegistry;
  private readonly store: Store;
  private readonly bus: EventBus;
  private readonly driver: HarnessDriver;
  private readonly now: () => Date;
  private readonly mode: ClassifierMode;
  private readonly classifier: TaskClassifier | undefined;
  private readonly idleCloseMs: number;
  private readonly summaryTimeoutMs: number;
  private readonly onCancelDelegated: ((taskId: string) => void) | undefined;
  private readonly memory: MemoryService | undefined;
  private timer: ReturnType<typeof setInterval> | undefined;
  private readonly closing = new Map<string, Promise<TaskSummaryRecord | undefined>>();

  constructor(options: SegmentationServiceOptions) {
    this.registry = options.registry;
    this.store = options.store;
    this.bus = options.bus;
    this.driver = options.driver;
    this.now = options.now;
    this.mode = options.mode ?? 'model';
    this.idleCloseMs = options.idleCloseMs ?? DEFAULT_TASK_IDLE_CLOSE_MS;
    this.summaryTimeoutMs = options.summaryTimeoutMs ?? SUMMARY_TIMEOUT_MS;
    this.onCancelDelegated = options.onCancelDelegated;
    this.memory = options.memory;
    this.classifier =
      options.classifier ??
      (this.mode === 'model' && isTemporaryPromptDriver(this.driver)
        ? new DshTaskClassifier(this.driver)
        : undefined);
  }

  start(): void {
    if (this.timer !== undefined) return;
    this.timer = setInterval(() => {
      void this.scanIdle().catch(() => undefined);
    }, IDLE_SCAN_INTERVAL_MS);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer === undefined) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** Applies the ordered rules, then asks the model only for `uncertain`. */
  async decide(botId: string, text: string, now: Date): Promise<SegmentationDecision> {
    const latest = this.store.tasks.latestForBot(botId);
    if (latest !== undefined && (latest.reopenedAt ?? null) !== null) {
      // `POST /api/tasks/:id/reopen` explicitly picks this segment for the next
      // message, so the time/symbol/idle rules must not override it.
      return { kind: 'continue', reason: 'reopened', previous: latest };
    }
    const summary = latest === undefined ? undefined : this.store.summaries.get(latest.id);
    const previousSymbols = latest === undefined ? [] : this.store.taskSymbols.listForTask(latest.id);
    const lastMessageAt =
      latest === undefined
        ? null
        : (this.store.messages.lastMessageAt(latest.id) ?? latest.endedAt ?? latest.startedAt);
    const rules = decideSegment({
      previous:
        latest === undefined
          ? undefined
          : {
              id: latest.id,
              title: latest.title,
              closedAt: latest.closedAt ?? null,
              symbols: previousSymbols,
            },
      lastMessageAt,
      text,
      now,
      symbolNames: this.store.summaries.symbolNameMap(),
    });

    if (rules.kind !== 'uncertain') {
      return {
        kind: rules.kind,
        reason: rules.reason,
        ...(rules.detail === undefined ? {} : { detail: rules.detail }),
        previous: latest,
      };
    }

    if (this.mode === 'model' && this.classifier !== undefined) {
      const bot = this.registry.get(botId);
      if (bot !== undefined) {
        const recent: ClassifierMessage[] = this.store.messages
          .listRecentText(botId, 2, Number.MAX_SAFE_INTEGER)
          .map((message) => ({ role: message.role === 'bot' ? 'bot' : 'user', content: message.content }));
        try {
          const answer = await this.classifier.classify(bot, summary ?? null, recent, text);
          return {
            kind: answer,
            reason: `uncertain_model_${answer}`,
            previous: latest,
          };
        } catch {
          return { ...this.fallbackDecision(latest, lastMessageAt, now, 'uncertain_model_failed') };
        }
      }
    }

    return this.fallbackDecision(latest, lastMessageAt, now, 'uncertain_fallback');
  }

  /** Incrementally records symbols parsed from a user message into its task. */
  recordUserSymbols(taskId: string, text: string): void {
    const symbols = extractUserSymbols(text, this.store.summaries.symbolNameMap());
    this.store.taskSymbols.upsertAll(taskId, symbols, this.now().toISOString());
  }

  /** Committed bot replies teach `symbol_names` and belong to the same task. */
  recordBotSymbols(taskId: string, text: string): void {
    const symbols = extractBotSymbols(text);
    if (symbols.length === 0) return;
    const at = this.now().toISOString();
    this.store.summaries.upsertSymbolNames(symbols, at);
    this.store.taskSymbols.upsertAll(taskId, symbols, at);
  }

  private fallbackDecision(
    previous: TaskRecord | undefined,
    lastMessageAt: string | null,
    now: Date,
    reason: string,
  ): SegmentationDecision {
    const last = lastMessageAt === null ? Number.NaN : Date.parse(lastMessageAt);
    const gap = Number.isFinite(last) ? Math.max(0, now.getTime() - last) : Number.POSITIVE_INFINITY;
    const kind = gap < TWO_HOURS_MS ? 'continue' : 'new';
    return { kind, reason: `${reason}_${kind}`, previous };
  }

  /** Recent text plus the closed-task directory, capped at 8000 characters. */
  buildInjection(botId: string, message: MessageRecord): ContextInjection {
    const recent = this.store.messages
      .listRecentText(botId, MAX_RECENT_MESSAGES, message.seq)
      .map((entry) => ({
        role: entry.role === 'bot' ? ('bot' as const) : ('user' as const),
        content: entry.content,
        createdAt: entry.createdAt,
        taskTitle:
          entry.taskId === null ? null : (this.store.tasks.get(entry.taskId)?.title ?? null),
      }));

    const tasks = this.store.tasks.listRecentClosed(botId, MAX_TASK_LINES).map((task) => {
      const summary = this.store.summaries.get(task.id);
      const closedAt = task.closedAt ?? task.endedAt ?? task.startedAt;
      return {
        taskId: task.id,
        date: closedAt.slice(0, 10),
        title: summary?.title ?? task.title ?? '未命名任务',
        conclusion: summary?.conclusion ?? '（小结生成中）',
      };
    });

    const memory = this.memory?.renderInjection(botId) ?? '';
    return buildContextInjection({
      userText: message.content,
      recentMessages: recent,
      tasks,
      memory,
      ...(this.memory === undefined ? {} : { memoryAuditCursor: this.memory.auditCursor() }),
    });
  }

  /**
   * Closes a segment once. The summary turn runs in the task's own harness
   * session; its events are swallowed and nothing is written to the timeline.
   */
  closeTask(taskId: string, reason = 'closed'): Promise<TaskSummaryRecord | undefined> {
    const inFlight = this.closing.get(taskId);
    if (inFlight !== undefined) return inFlight;
    const task = this.store.tasks.get(taskId);
    if (task === undefined) return Promise.resolve(undefined);
    if ((task.closedAt ?? null) !== null) {
      return Promise.resolve(this.store.summaries.get(taskId));
    }
    const promise = this.closeTaskOnce(task, reason);
    this.closing.set(taskId, promise);
    void promise
      .catch(() => undefined)
      .finally(() => {
        this.closing.delete(taskId);
      });
    return promise;
  }

  private async closeTaskOnce(task: TaskRecord, reason: string): Promise<TaskSummaryRecord | undefined> {
    if (!this.store.tasks.markClosed(task.id, this.now().toISOString())) {
      return this.store.summaries.get(task.id);
    }
    const closed = this.store.tasks.get(task.id) ?? task;
    void reason;
    this.cancelRunningChildren(task.id);
    const summary = await this.generateSummary(closed);
    const updated = this.store.tasks.get(task.id) ?? closed;
    this.publish({
      type: 'task.closed',
      botId: updated.botId,
      taskId: task.id,
      task: toTaskDto(updated, summary),
      summary: toTaskSummaryDto(summary),
    });
    return summary;
  }

  /** Closes every terminal segment whose last message is older than the idle window. */
  async scanIdle(): Promise<void> {
    const cutoff = new Date(this.now().getTime() - this.idleCloseMs).toISOString();
    const stale = this.store.tasks.listUnclosedBefore(cutoff);
    await Promise.all(stale.map((task) => this.closeTask(task.id, 'idle')));
  }

  private cancelRunningChildren(taskId: string): void {
    if (this.onCancelDelegated === undefined) return;
    for (const child of this.store.tasks.listByParent(taskId)) {
      if (child.status === 'running') this.onCancelDelegated(child.id);
    }
  }

  private async generateSummary(task: TaskRecord): Promise<TaskSummaryRecord> {
    const parsed = await this.requestSummary(task);
    if (parsed !== null) {
      try {
        this.captureMemories(task, parsed.memories);
      } catch {
        // A memory disk error must not swallow the task summary.
      }
    }
    // Stamp after the hidden turn: the summary (and the names it teaches) exist only from this point.
    const createdAt = this.now().toISOString();
    let record: TaskSummaryRecord;
    if (parsed === null) {
      const fallback = fallbackSummary(task, this.lastBotMessage(task.id), createdAt);
      record = {
        ...fallback,
        keyNumbers: [],
        deliverables: [],
        openQuestions: [],
        symbols: [],
        source: 'fallback',
      };
    } else {
      record = {
        taskId: task.id,
        title: parsed.title === '' ? (task.title ?? '未命名任务') : parsed.title,
        conclusion: parsed.conclusion,
        keyNumbers: parsed.keyNumbers,
        deliverables: parsed.deliverables,
        openQuestions: parsed.openQuestions,
        symbols: parsed.symbols,
        createdAt,
        source: 'model',
      };
    }
    const saved = this.store.summaries.upsert(record);
    this.store.tasks.setTitle(task.id, saved.title);
    const symbols = saved.symbols.map((symbol) => ({
      code: normalizeSymbolCode(symbol.code),
      name: symbol.name,
    }));
    this.store.summaries.upsertSymbolNames(symbols, createdAt);
    this.store.taskSymbols.upsertAll(task.id, symbols, createdAt);
    return saved;
  }

  private async requestSummary(task: TaskRecord): Promise<ReturnType<typeof parseSummaryResponse>> {
    const bot = this.registry.get(task.botId);
    if (bot === undefined || task.harnessSessionId === null) return null;
    const prompt = buildSummaryPrompt(task.title, task.id);
    try {
      const raw = await this.runHiddenPrompt(bot, task, prompt);
      if (raw === null) return null;
      const parsed = parseSummaryResponse(raw);
      if (parsed === null) return null;
      const empty =
        parsed.title === '' &&
        parsed.conclusion === '' &&
        parsed.keyNumbers.length === 0 &&
        parsed.deliverables.length === 0 &&
        parsed.openQuestions.length === 0 &&
        parsed.symbols.length === 0 &&
        parsed.memories.length === 0;
      return empty ? null : parsed;
    } catch {
      return null;
    }
  }

  /** Every candidate still passes `policy.ts`; rejections only reach the audit log. */
  private captureMemories(task: TaskRecord, candidates: readonly ParsedMemoryCandidate[]): void {
    if (this.memory === undefined || candidates.length === 0) return;
    const userTexts = this.store.messages
      .listByTask(task.id)
      .filter((message) => message.role === 'user')
      .map((message) => message.content);
    for (const candidate of candidates.slice(0, 5)) {
      this.memory.write({
        botId: task.botId,
        taskId: task.id,
        actor: 'capture',
        candidate: {
          title: candidate.title,
          description: candidate.description,
          kind: candidate.kind,
          body: candidate.body,
          evidence: candidate.evidence,
          ...(candidate.expiresInDays === undefined
            ? {}
            : { expiresInDays: candidate.expiresInDays }),
        },
        userTexts,
        depth: task.depth,
      });
    }
  }

  private async runHiddenPrompt(
    bot: BotManifest,
    task: TaskRecord,
    prompt: string,
  ): Promise<string | null> {
    if (isHiddenPromptDriver(this.driver)) {
      return this.driver.hiddenPrompt(bot, task, prompt, this.summaryTimeoutMs);
    }
    let sessionId: string | undefined;
    try {
      sessionId = await this.driver.ensureSession(bot, task, { silent: true });
      let output = '';
      const sink: HarnessSink = (event) => {
        if (event.type === 'message') output += event.text;
      };
      const result = await this.withTimeout(
        this.driver.prompt(bot, sessionId, prompt, sink),
        this.summaryTimeoutMs,
      );
      if (result === null) {
        try {
          await this.driver.cancel(bot, sessionId);
        } catch {
          // The summary fallback below is enough when cancellation fails.
        }
        return null;
      }
      return output;
    } catch {
      return null;
    }
  }

  private withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T | null> {
    return new Promise((resolve) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        resolve(null);
      }, timeoutMs);
      timer.unref();
      promise.then(
        (value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(value);
        },
        () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(null);
        },
      );
    });
  }

  private lastBotMessage(taskId: string): string | null {
    const messages = this.store.messages.listByTask(taskId);
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message !== undefined && message.role === 'bot' && message.kind === 'text') {
        return message.content;
      }
    }
    return null;
  }

  private publish(input: Parameters<EventBus['publish']>[0]): ServerEvent {
    return this.bus.publish(input);
  }
}
