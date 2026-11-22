/**
 * Wire types for the Chives HTTP API and SSE stream. This module is type-only:
 * it has no runtime imports so the web app can `import type` from
 * `@chives/server/protocol` without pulling server code into its bundle.
 */

export type BotStatus = 'idle' | 'starting' | 'working' | 'awaiting_approval' | 'error';

/** Right-hand panels a bot may opt into, in display order. */
export type BotPanel = 'market' | 'portfolio' | 'watches' | `strategy:${string}`;

export type TaskStatus = 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted';

/** Stable failure classes written to `tasks.error_code` and notice `meta.code`. */
export type FailureCode =
  | 'harness_unavailable'
  | 'harness_crashed'
  | 'model_quota'
  | 'model_auth'
  | 'network'
  | 'engine_unavailable'
  | 'timeout'
  | 'unknown';

export type MessageRole = 'user' | 'bot' | 'system';

export type MessageKind =
  | 'text'
  | 'proactive'
  | 'delegation'
  | 'approval'
  | 'deliverable'
  | 'notice';

export type ToolStatus = 'running' | 'completed' | 'failed';

export interface BotAvatar {
  emblem: string;
  tone: string;
}

export interface BotSummary {
  /** Older workbenches have no employment preference. */
  hired?: boolean;
  permanent?: boolean;
  headline?: string;
  id: string;
  name: string;
  role: string;
  avatar: BotAvatar;
  skills: string[];
  mcp: string[];
  model: string;
  /** What the UI shows for `model`; `default` resolves to the server route's model. */
  modelDisplayName?: string;
  /** Absolute path of this bot's workspace. */
  workspacePath?: string;
  canDelegateTo: string[];
  background: boolean;
  status: BotStatus;
  runningTaskId: string | null;
  /** Pending approvals routed to this bot, including its delegated children. */
  pendingApprovals: number;
  /** Number of bot-level memories, shown on the overview card. */
  memoryCount?: number;
  /** File mtime of the most recently changed memory, ISO or null. */
  memoryUpdatedAt?: string | null;
  /** Enabled routines for this bot, shown on the overview card. */
  proactiveCount?: number;
  /** Active watches owned by this bot. */
  watchCount?: number;
  /** Unread notifications for this bot, shown as a dot in the bot list. */
  unreadNotifications?: number;
  /** Running report-back delegations initiated by this bot while it is idle. */
  waitingDelegations?: number;
  /** Right-hand panels this bot shows in the conversation view, in order. */
  panels: BotPanel[];
}

export interface StrategyPoolRow {
  code: string;
  name?: string | null;
  rank?: number | null;
  status?: string | null;
  priority?: string | null;
  priority_date?: string | null;
  score?: number | null;
  k?: number | null;
  vr?: number | null;
  hb?: number | null;
  t_star?: string | null;
  p_star?: number | null;
  s1_status?: string | null;
  s2_status?: string | null;
  support_score?: number | null;
  ma_score?: number | null;
  time_score?: number | null;
  volume_score?: number | null;
  basis?: number | null;
  hmax?: number | null;
  gain?: number | null;
  drawdown?: number | null;
  base_score?: number | null;
  deduction?: number | null;
  ma10_count?: number | null;
  ma10_obs_left?: number | null;
}

export interface StrategyPoolsDto {
  ok?: boolean;
  strategy: string;
  name: string;
  description?: string;
  date: string;
  latest_date: string | null;
  spec_version?: string | null;
  status: string;
  counts: { first: number; main: number };
  pools: { first: StrategyPoolRow[]; main: StrategyPoolRow[] };
}

export interface BotSkillInfo {
  name: string;
  /** First sentence of the skill's `description` frontmatter; empty when unavailable. */
  description: string;
}

export interface BotDelegateInfo {
  id: string;
  name: string;
}

export type MemoryKind = 'preference' | 'view' | 'fact' | 'note';
export type MemorySource = 'capture' | 'tool' | 'user';

export interface BotMemoryItem {
  slug: string;
  title: string;
  description: string;
  kind: MemoryKind;
  writtenAt: string;
  expiresAt: string | null;
  expired: boolean;
  source: MemorySource;
  sourceTaskId: string | null;
  body: string;
}

export interface BotMemoryList {
  count: number;
  /** Per-bot hard cap, so the UI can say "3/200". */
  limit: number;
  items: BotMemoryItem[];
  available: boolean;
  updatedAt: string | null;
}

export interface BotWorkspaceInfo {
  /** Absolute path of `<dataDir>/bots/<botId>/workspace`. */
  path: string;
  fileCount: number;
  totalBytes: number;
}

export interface BotProfile {
  kernel?: 'dsh';
  bot: BotSummary;
  role: string;
  /** First paragraph of the bot's persona, without the shared rules. */
  personaSummary: string;
  skills: BotSkillInfo[];
  mcp: string[];
  tools: { code: 'sandboxed'; write: 'workspace-only' };
  canDelegateTo: BotDelegateInfo[];
  routines: RoutineDto[];
  /** Active first, then triggered/expired/cancelled. */
  watches?: WatchDto[];
  memoryPolicy: { user: 'read' | 'none'; bot: 'read-write' | 'read' | 'none' };
  tradingGuard: boolean;
  /** Display name: the manifest model, or the server's default route model. */
  model: string;
  workspace: BotWorkspaceInfo;
  recentDeliverables: DeliverableDto[];
  memory: BotMemoryList;
  /** Manifest values, used by "restore defaults" in the editor. */
  defaults: { name: string; avatar: BotAvatar };
}

export interface RoutineScheduleDto {
  cron?: string;
  tz?: string;
  every_minutes?: number;
  once_at?: string;
}

export type RoutineSource = 'manifest' | 'user';

export interface RoutineDto {
  id: string;
  botId: string;
  source: RoutineSource;
  title: string;
  schedule: RoutineScheduleDto;
  /** Human description such as「工作日 08:30（北京时间）」. */
  scheduleText: string;
  prompt: string;
  /** First 120 characters of the prompt. */
  promptSummary: string;
  tradingDaysOnly: boolean;
  enabled: boolean;
  createdAt: string;
  lastRunAt: string | null;
  nextRunAt: string | null;
}

export interface AlertEventDto {
  id: number;
  source: string;
  alertId: number;
  alertTs: string | null;
  code: string | null;
  name: string | null;
  ruleId: string | null;
  status: 'started' | 'skipped';
  reason: string | null;
  taskId: string | null;
  createdAt: string;
}

export interface ProactiveSettingsDto {
  enabled: boolean;
  autoAnalysis: boolean;
  observeOnly: boolean;
  browserNotify: boolean;
  systemNotify: boolean;
  importantOnly: boolean;
}

export type WatchStatus = 'active' | 'triggered' | 'expired' | 'cancelled';
export type WatchActor = 'user' | 'bot' | 'system';

export interface WatchDto {
  id: string;
  botId: string;
  code: string;
  name: string;
  label: string;
  note: string;
  /** One human line including conditions and the expiry date. */
  conditionText: string;
  /** Empty when the plan has no give-up conditions. */
  giveUpText: string;
  repeat: boolean;
  status: WatchStatus;
  engineState: string | null;
  lastPrice: number | null;
  /** `engine_unreachable` while cn-watch is down; cleared after reconciliation. */
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

export interface WatchHistoryDto {
  id: number;
  kind: string;
  actor: WatchActor;
  taskId: string | null;
  detail: string | null;
  createdAt: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface WatchDetailDto {
  watch: WatchDto;
  history: WatchHistoryDto[];
}

export type NotificationLevelDto = 'info' | 'important' | 'urgent';

export interface NotificationDto {
  id: string;
  botId: string;
  taskId: string;
  title: string;
  body: string;
  level: NotificationLevelDto;
  createdAt: string;
  readAt: string | null;
}

export interface SettingsProfileDto {
  available: boolean;
  /** Profile fields exactly as returned by profile_get. */
  fields: Record<string, unknown>;
  timestamps: Record<string, string>;
  updatedAt: string | null;
  /** Why the profile service is unavailable; never contains credentials. */
  error: string | null;
}

export interface ModelChoiceDto {
  value: string;
  name: string;
  description?: string;
}

export interface ModelSettingsDto {
  selected: string | null;
  options: ModelChoiceDto[];
}

export type ModelApiDto = 'openai-completions' | 'openai-responses' | 'anthropic-messages' | 'openai-codex-subscription';

/** The settings-page model endpoint. The API key is write-only and never appears here. */
export interface ModelProviderDto {
  baseURL: string;
  api: ModelApiDto;
  model: string;
  displayName?: string;
  contextWindow?: number;
  maxTokens?: number;
  deepseekThinking: boolean;
  keyConfigured: boolean;
  /** Saved and keyed: new bot processes use it instead of the launcher's overlay. */
  active: boolean;
}

export interface ModelKeyDto {
  name: string;
  configured: boolean;
}

export type SettingsTheme = 'dark' | 'light' | 'system';
export type ChangeColorMode = 'red-up' | 'green-up';

export interface AppearanceSettingsDto {
  theme: SettingsTheme;
  changeColor: ChangeColorMode;
}

export interface RuntimeBotDto {
  id: string;
  name: string;
  process: 'running' | 'not_started' | 'error';
}

export interface EngineHealthDto {
  port: number;
  healthy: boolean;
}

export interface RuntimeSettingsDto {
  harness: {
    name: string;
    version: string | null;
    connected: boolean;
  };
  bots: RuntimeBotDto[];
  engines: EngineHealthDto[];
}

export interface StatusFailureDto {
  code: FailureCode;
  taskId: string;
  botId: string;
  /** User-facing notice text stored with the failure. */
  message: string;
  at: string;
}

/** Aggregated runtime status behind `GET /api/status`. */
export interface ChivesStatusDto {
  ok: true;
  updatedAt: string;
  harness: RuntimeSettingsDto['harness'] & { lastError: StatusFailureDto | null };
  engines: Array<EngineHealthDto & { name: string }>;
  network: { lastError: StatusFailureDto | null };
  /** Most recent `model_quota` / `model_auth` failure, across bots. */
  lastModelError: StatusFailureDto | null;
}

export interface DataLocationDto {
  path: string;
  bytes: number;
}

export interface ActiveRoutineDto extends RoutineDto {
  botAvatar?: BotAvatar;
  botName: string;
}

export interface WorkspaceFileDto {
  /** Path relative to the bot workspace, with `/` separators. */
  path: string;
  name: string;
  size: number;
  modifiedAt: string;
  kind: DeliverableKind;
  /** Set when this file is a recorded deliverable, so the UI can open its preview. */
  deliverableId: string | null;
}

export interface WorkspaceFileList {
  /** Relative directory that was listed; empty means the workspace root. */
  dir: string;
  files: WorkspaceFileDto[];
}

export interface TaskDto {
  id: string;
  botId: string;
  title: string | null;
  status: TaskStatus;
  harnessSessionId: string | null;
  startedAt: string;
  endedAt: string | null;
  parentTaskId: string | null;
  depth: number;
  delegated: boolean;
  brief: string | null;
  /** End of the task segment; null while the segment can still be continued. */
  closedAt?: string | null;
  /** Title/conclusion from `task_summaries`, when the segment is closed. */
  summaryTitle?: string | null;
  summaryConclusion?: string | null;
  /** Debug-only injection stats from the first prompt of a new segment. */
  contextMeta?: Record<string, unknown> | null;
  lastContextUsed?: number | null;
  lastContextSize?: number | null;
  /** Stable failure class of the last failed turn; null on success and while running. */
  errorCode?: FailureCode | null;
}

export interface TaskSummaryDto {
  taskId: string;
  title: string;
  conclusion: string;
  keyNumbers: Array<{ label: string; value: string; source: string; asOf: string }>;
  deliverables: string[];
  openQuestions: string[];
  symbols: Array<{ code: string; name: string }>;
  createdAt: string;
  source: 'model' | 'fallback';
}

export interface MessageDto {
  id: string;
  botId: string;
  taskId: string | null;
  role: MessageRole;
  kind: MessageKind;
  content: string;
  meta: Record<string, unknown> | null;
  createdAt: string;
  seq: number;
}

export interface ToolEventDto {
  id: string;
  taskId: string;
  messageId: string | null;
  toolCallId: string;
  title: string;
  kind: string;
  rawInput: unknown;
  status: ToolStatus;
  output: string | null;
  startedAt: string;
  endedAt: string | null;
}

export interface UsageDto {
  taskId: string;
  at: string;
  used: number;
  size: number;
}

export type DeliverableKind =
  | 'markdown'
  | 'image'
  | 'csv'
  | 'json'
  | 'html'
  | 'pdf'
  | 'code'
  | 'other';

export interface DeliverableDto {
  id: string;
  taskId: string;
  /** Bot whose workspace contains the file (a delegated child for child files). */
  botId: string;
  /** Path relative to `<dataDir>/bots/<botId>/workspace`. */
  path: string;
  kind: DeliverableKind;
  size: number;
  createdAt: string;
}

/** One uploaded file attached to a user message. */
export interface MessageAttachmentDto {
  /** Path relative to the bot workspace, under `uploads/`. */
  path: string;
  name: string;
  size: number;
  kind: DeliverableKind;
}

export interface TimelinePage {
  /** One page in ascending `seq` order. */
  messages: MessageDto[];
  /** Tasks referenced by this page, deduplicated. */
  tasks: TaskDto[];
  /** Tool steps belonging to those tasks, in start order. */
  toolEvents: ToolEventDto[];
  hasMore: boolean;
  nextBeforeSeq: number | null;
}

export interface SearchRange {
  /** Inclusive UTF-16 offset into `SearchSnippet.text`. */
  start: number;
  /** Exclusive UTF-16 offset into `SearchSnippet.text`. */
  end: number;
}

export interface SearchSnippet {
  docType: 'message' | 'summary' | 'deliverable';
  /** Message id, task summary task id, or deliverable id. */
  sourceId: string;
  /** Set when `docType` is `message`, so the UI can scroll to it. */
  messageId: string | null;
  /** Set when `docType` is `deliverable`, so the UI can open the preview. */
  deliverableId: string | null;
  text: string;
  ranges: SearchRange[];
  createdAt: string;
}

/** One task group in a bot-timeline search. Delegated child docs are folded into the root task. */
export interface SearchTaskGroup {
  taskId: string;
  botId: string;
  botName: string;
  title: string;
  lastActivityAt: string;
  startedAt: string;
  endedAt: string | null;
  /** Tool steps of the root task and its delegated descendants. */
  steps: number;
  summary: TaskSummaryDto | null;
  snippets: SearchSnippet[];
  /** All occurrences of every query term, not just the returned snippets. */
  hitCount: number;
  deliverables: DeliverableDto[];
  /** Root task plus its delegated descendants, used by "查看完整过程". */
  taskIds: string[];
  /** First message to scroll to for "在时间线里定位". */
  locateMessageId: string | null;
}

export interface SearchResponse {
  query: string;
  groups: SearchTaskGroup[];
  /** Groups before `limit` was applied. */
  totalGroups: number;
  totalHits: number;
}

export interface TaskDetail {
  task: TaskDto;
  toolEvents: ToolEventDto[];
  usage: UsageDto[];
  /** One entry per turn: that turn's last usage sample. */
  contextUsage: UsageDto[];
  /** Committed messages of this task, including a delegated child's final answer. */
  messages: MessageDto[];
  summary: TaskSummaryDto | null;
}

export type DelegationStatus = 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted';

/** One `kind=delegation` message's state, mirrored in `MessageDto.meta`. */
export interface DelegationDto {
  delegationId: string;
  parentTaskId: string;
  targetBotId: string;
  targetBotName: string;
  childTaskId: string;
  brief: string;
  /** false for a fire-and-forget delegation read through `delegate_wait`. */
  reportBack: boolean;
  status: DelegationStatus;
  startedAt: string;
  endedAt: string | null;
  /** Verbatim child failure detail; null unless `status` is `failed`. */
  error: string | null;
}

export interface MessageAccepted {
  messageId: string;
  taskId: string;
}

export type ApprovalDecision = 'allow' | 'reject' | 'cancelled';

/**
 * One approval request. `taskId` is the task whose harness asked (a delegated
 * child for delegation-sourced approvals); `rootTaskId`/`rootBotId` identify
 * the timeline that owns the card and the badge count.
 */
export interface ApprovalDto {
  id: string;
  /** Bot that triggered the tool call (the delegated child for a child approval). */
  botId: string;
  taskId: string;
  rootTaskId: string;
  sourceBotId: string;
  sourceBotName: string;
  rootBotId: string;
  delegated: boolean;
  toolCallId: string;
  title: string | null;
  rawInput: unknown;
  options: Array<{ optionId: string; name: string; kind: string }>;
  decision: ApprovalDecision | null;
  decidedAt: string | null;
  decidedBy: string | null;
}

export interface CancelAccepted {
  taskId: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

interface EventBase {
  /** Globally monotonic event id assigned by the server's EventBus. */
  id: number;
  at: string;
  botId: string;
}

export interface MessageCreatedEvent extends EventBase {
  type: 'message.created';
  taskId: string | null;
  message: MessageDto;
}

export interface TaskStartedEvent extends EventBase {
  type: 'task.started';
  taskId: string;
  task: TaskDto;
}

export interface TaskUpdatedEvent extends EventBase {
  type: 'task.updated';
  taskId: string;
  task: TaskDto;
}

export interface TaskClosedEvent extends EventBase {
  type: 'task.closed';
  taskId: string;
  /** Task after the summary title/closed_at were written. */
  task: TaskDto;
  summary: TaskSummaryDto;
}

export interface ToolStartedEvent extends EventBase {
  type: 'tool.started';
  taskId: string;
  tool: ToolEventDto;
}

export interface ToolEndedEvent extends EventBase {
  type: 'tool.ended';
  taskId: string;
  tool: ToolEventDto;
}

export interface DraftResetEvent extends EventBase {
  type: 'draft.reset';
  taskId: string;
  sessionId: string;
  attemptId?: string;
}

export interface DraftDeltaEvent extends EventBase {
  type: 'draft.delta';
  taskId: string;
  sessionId: string;
  kind: 'text' | 'reasoning';
  text: string;
  attemptId?: string;
}

export interface DraftCommitEvent extends EventBase {
  type: 'draft.commit';
  taskId: string;
  sessionId: string;
  text: string;
}

export interface UsageEvent extends EventBase {
  type: 'usage';
  taskId: string;
  usage: UsageDto;
}

export interface BotStatusEvent extends EventBase {
  type: 'bot.status';
  status: BotStatus;
  runningTaskId: string | null;
}

export interface BotUpdatedEvent extends EventBase {
  type: 'bot.updated';
  /** The merged summary after display-name/avatar overrides were applied. */
  bot: BotSummary;
}

export interface ApprovalRequestedEvent extends EventBase {
  type: 'approval.requested';
  /** The root task whose timeline shows the card. */
  taskId: string;
  approvalId: string;
  toolCallId: string;
  title: string | null;
  rawInput: unknown;
  options: Array<{ optionId: string; name: string; kind: string }>;
  approval: ApprovalDto;
}

export interface ApprovalDecidedEvent extends EventBase {
  type: 'approval.decided';
  /** The root task whose timeline shows the card. */
  taskId: string;
  approval: ApprovalDto;
}

export interface DelegationUpdatedEvent extends EventBase {
  type: 'delegation.updated';
  /** The initiating task whose timeline owns the delegation row. */
  taskId: string;
  delegation: DelegationDto;
  /** Child task state, so the row can show elapsed time without an extra fetch. */
  task?: TaskDto;
}

export interface DeliverableCreatedEvent extends EventBase {
  type: 'deliverable.created';
  /** The root task whose timeline shows the deliverable card. */
  taskId: string;
  deliverable: DeliverableDto;
}

export interface MemoryUpdatedEvent extends EventBase {
  type: 'memory.updated';
  action: 'created' | 'updated' | 'deleted';
  memory: BotMemoryItem | null;
  count: number;
}

export interface WatchCreatedEvent extends EventBase {
  type: 'watch.created';
  watch: WatchDto;
}

export interface WatchUpdatedEvent extends EventBase {
  type: 'watch.updated';
  watch: WatchDto;
}

export interface NotificationCreatedEvent extends EventBase {
  type: 'notification.created';
  notification: NotificationDto;
}

export interface ErrorEvent extends EventBase {
  type: 'error';
  taskId?: string;
  message: string;
  code?: string;
}

export type ServerEvent =
  | MessageCreatedEvent
  | TaskStartedEvent
  | TaskUpdatedEvent
  | TaskClosedEvent
  | ToolStartedEvent
  | ToolEndedEvent
  | DraftResetEvent
  | DraftDeltaEvent
  | DraftCommitEvent
  | UsageEvent
  | BotStatusEvent
  | (EventBase & {type:'roster.changed'})
  | BotUpdatedEvent
  | ApprovalRequestedEvent
  | ApprovalDecidedEvent
  | DelegationUpdatedEvent
  | DeliverableCreatedEvent
  | MemoryUpdatedEvent
  | WatchCreatedEvent
  | WatchUpdatedEvent
  | NotificationCreatedEvent
  | ErrorEvent;

/** `GET /api/dashboard/market`: the right-hand market panel. */
export type MarketSession = 'pre_open' | 'auction' | 'trading' | 'lunch_break' | 'closed' | 'holiday';

export interface MarketIndexDto {
  code: string;
  name: string;
  price: number | null;
  changePct: number | null;
  amountYuan: number | null;
  /** Close prices of today's 5-minute bars; empty when no series is available. */
  spark: number[];
}

export interface MarketDashboardDto {
  indexes: MarketIndexDto[];
  /** Combined turnover of the two exchanges, in yuan. */
  amountYuan: number | null;
  breadth: { up: number | null; down: number | null; upRatioPct: number | null };
  limit: { limitUp: number | null; limitDown: number | null };
  /** Gateway data time (ISO with offset). */
  asOf: string;
  session: MarketSession;
  stale: boolean;
}

export interface PortfolioPositionDto {
  code: string;
  name: string;
  qty: number | null;
  costPrice: number | null;
  price: number | null;
  prevClose: number | null;
  changePct: number | null;
  marketValue: number | null;
  pnl: number | null;
  pnlPct: number | null;
  /** (price - prevClose) * qty; null when either quote field is missing. */
  todayPnl: number | null;
  priceAvailable: boolean;
}

export interface PortfolioSummaryDto {
  positionCount: number;
  pricedCount: number;
  unpricedCount: number;
  totalMarketValue: number | null;
  totalPnl: number | null;
  totalPnlPct: number | null;
  todayPnl: number | null;
  todayPnlPct: number | null;
}

export interface PortfolioDashboardDto {
  asOf: string | null;
  /** null when the user never set cash. */
  cash: number | null;
  summary: PortfolioSummaryDto;
  positions: PortfolioPositionDto[];
  unpriced: Array<{ code: string; name: string; reason: string }>;
  /** True when the holdings book has no positions. */
  empty: boolean;
  warnings: Array<{ code: string; message: string }>;
}
