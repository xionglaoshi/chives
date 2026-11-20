/** Persisted record shapes shared by repositories and the HTTP layer. */

export type TaskStatus = 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted';
export type MessageRole = 'user' | 'bot' | 'system';
export type MessageKind =
  | 'text'
  | 'proactive'
  | 'delegation'
  | 'approval'
  | 'deliverable'
  | 'notice';
export type ToolEventStatus = 'running' | 'completed' | 'failed';

export type JsonRecord = Record<string, unknown>;

export interface BotOverride {
  id: string;
  displayName: string | null;
  avatarEmblem: string | null;
  avatarTone: string | null;
  updatedAt: string;
}

export interface BotOverrideUpdate {
  displayName?: string | null;
  avatarEmblem?: string | null;
  avatarTone?: string | null;
}

export interface TaskRecord {
  id: string;
  botId: string;
  title: string | null;
  status: TaskStatus;
  harnessSessionId: string | null;
  startedAt: string;
  endedAt: string | null;
  parentTaskId: string | null;
  /** 0 for a user task; +1 for each delegation hop. */
  depth: number;
  /** True when the task was created by another bot's `delegate` call. */
  delegated: boolean;
  /** The delegation brief; null for user tasks. */
  brief: string | null;
  /** End of the task segment (independent of the per-turn `status`). */
  closedAt?: string | null;
  /** Set by `POST /api/tasks/:id/reopen`; forces the next message to continue this task. */
  reopenedAt?: string | null;
  /** Why the segment decision picked continue/new/uncertain. */
  segmentReason?: string | null;
  /** Debug-only injection stats recorded on the first prompt of a new task. */
  contextMeta?: JsonRecord | null;
  lastContextUsed?: number | null;
  lastContextSize?: number | null;
  /** `routine`/`alert` for a proactive task; null for a user or delegated task. */
  origin?: string | null;
  /** Stable failure class of the last failed turn; null otherwise. */
  errorCode: string | null;
}

export interface NewTask {
  id: string;
  botId: string;
  title?: string | null;
  parentTaskId?: string | null;
  startedAt: string;
  depth?: number;
  delegated?: boolean;
  brief?: string | null;
  origin?: string | null;
}

export interface MessageRecord {
  id: string;
  botId: string;
  taskId: string | null;
  role: MessageRole;
  kind: MessageKind;
  content: string;
  meta: JsonRecord | null;
  createdAt: string;
  seq: number;
}

export interface NewMessage {
  id: string;
  botId: string;
  taskId: string | null;
  role: MessageRole;
  kind: MessageKind;
  content: string;
  meta?: JsonRecord | null;
  createdAt: string;
}

export interface MessagePage {
  /** Ascending by `seq`, at most `limit` rows. */
  messages: MessageRecord[];
  /** True when older messages exist before the first returned row. */
  hasMore: boolean;
  /** Pass as `beforeSeq` to fetch the previous page. */
  nextBeforeSeq: number | null;
}

export interface ToolEventRecord {
  id: string;
  taskId: string;
  messageId: string | null;
  toolCallId: string;
  title: string;
  kind: string;
  rawInput: unknown;
  status: ToolEventStatus;
  output: string | null;
  startedAt: string;
  endedAt: string | null;
}

export interface NewToolEvent {
  id: string;
  taskId: string;
  messageId?: string | null;
  toolCallId: string;
  title: string;
  kind: string;
  rawInput?: unknown;
  startedAt: string;
}

export interface UsageRecord {
  taskId: string;
  at: string;
  used: number;
  size: number;
}

export interface DeliverableRecord {
  id: string;
  taskId: string;
  botId: string;
  path: string;
  kind: string;
  size: number;
  createdAt: string;
}

export interface NewDeliverable {
  id: string;
  taskId: string;
  botId: string;
  path: string;
  kind: string;
  size: number;
  createdAt: string;
}

export interface ApprovalRecord {
  id: string;
  taskId: string;
  toolCallId: string;
  request: JsonRecord;
  decision: string | null;
  decidedAt: string | null;
  decidedBy: string | null;
}

export interface SummaryKeyNumber {
  label: string;
  value: string;
  source: string;
  asOf: string;
}

export interface SummarySymbol {
  code: string;
  name: string;
}

/** A symbol observed in one task segment; `firstSeenAt` is the earliest observation. */
export interface TaskSymbol {
  code: string;
  name: string | null;
  firstSeenAt: string;
}

export type SummarySource = 'model' | 'fallback';

export interface TaskSummaryRecord {
  taskId: string;
  title: string;
  conclusion: string;
  keyNumbers: SummaryKeyNumber[];
  deliverables: string[];
  openQuestions: string[];
  symbols: SummarySymbol[];
  createdAt: string;
  source: SummarySource;
}

export type RoutineSource = 'manifest' | 'user';

export type RoutineSchedule =
  | { kind: 'cron'; expression: string; tz: 'Asia/Shanghai' | 'UTC' }
  | { kind: 'every'; minutes: number }
  | { kind: 'once'; at: string };

export interface RoutineRecord {
  id: string;
  botId: string;
  source: RoutineSource;
  title: string;
  schedule: RoutineSchedule;
  prompt: string;
  tradingDaysOnly: boolean;
  enabled: boolean;
  createdAt: string;
  lastRunAt: string | null;
  nextRunAt: string | null;
}

export interface NewRoutine {
  id: string;
  botId: string;
  source: RoutineSource;
  title: string;
  schedule: RoutineSchedule;
  prompt: string;
  tradingDaysOnly: boolean;
  enabled: boolean;
  createdAt: string;
  nextRunAt: string | null;
}

export type AlertEventStatus = 'started' | 'skipped';

export interface AlertEventRecord {
  id: number;
  source: string;
  alertId: number;
  alertTs: string | null;
  code: string | null;
  name: string | null;
  ruleId: string | null;
  status: AlertEventStatus;
  reason: string | null;
  taskId: string | null;
  createdAt: string;
}

export interface NewAlertEvent {
  source: string;
  alertId: number;
  alertTs: string | null;
  code: string | null;
  name: string | null;
  ruleId: string | null;
  status: AlertEventStatus;
  reason: string | null;
  taskId: string | null;
  createdAt: string;
}

export type WatchStatus = 'active' | 'triggered' | 'expired' | 'cancelled';
export type WatchActor = 'user' | 'bot' | 'system';

export interface WatchRecord {
  id: string;
  botId: string;
  code: string;
  name: string;
  label: string;
  note: string;
  /** The complete Plan JSON sent to cn-watch; `id` is always `chives-<id>`. */
  plan: JsonRecord;
  repeat: boolean;
  status: WatchStatus;
  engineState: string | null;
  lastPrice: number | null;
  syncError: string | null;
  createdTaskId: string | null;
  updatedTaskId: string | null;
  createdAt: string;
  updatedAt: string;
  expiresAt: string;
  triggeredAt: string | null;
  triggerTaskId: string | null;
  cancelledBy: WatchActor | null;
}

export interface NewWatch {
  id: string;
  botId: string;
  code: string;
  name: string;
  label: string;
  note: string;
  plan: JsonRecord;
  repeat: boolean;
  status: WatchStatus;
  engineState: string | null;
  lastPrice: number | null;
  syncError: string | null;
  createdTaskId: string | null;
  updatedTaskId: string | null;
  createdAt: string;
  updatedAt: string;
  expiresAt: string;
  cancelledBy: WatchActor | null;
}

export type WatchEventKind =
  | 'created'
  | 'updated'
  | 'cancelled'
  | 'triggered'
  | 'trigger_queued'
  | 'expired'
  | 'sync_error';

export interface WatchEventRecord {
  id: number;
  watchId: string;
  botId: string;
  kind: WatchEventKind;
  actor: WatchActor;
  taskId: string | null;
  before: JsonRecord | null;
  after: JsonRecord | null;
  detail: string | null;
  createdAt: string;
}

export interface NewWatchEvent {
  watchId: string;
  botId: string;
  kind: WatchEventKind;
  actor: WatchActor;
  taskId: string | null;
  before?: JsonRecord | null;
  after?: JsonRecord | null;
  detail?: string | null;
  createdAt: string;
}

export type NotificationLevel = 'info' | 'important' | 'urgent';

export interface NotificationRecord {
  id: string;
  botId: string;
  taskId: string;
  title: string;
  body: string;
  level: NotificationLevel;
  createdAt: string;
  readAt: string | null;
}

export interface NewNotification {
  id: string;
  botId: string;
  taskId: string;
  title: string;
  body: string;
  level: NotificationLevel;
  createdAt: string;
}

export interface NewTaskSummary {
  taskId: string;
  title: string;
  conclusion: string;
  keyNumbers?: SummaryKeyNumber[];
  deliverables?: string[];
  openQuestions?: string[];
  symbols?: SummarySymbol[];
  createdAt: string;
  source: SummarySource;
}
