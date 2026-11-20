/** Typed repository bundle over one SQLite connection. */

import type { DatabaseSync } from 'node:sqlite';

import { AlertEventRepository } from './alerts.js';
import { BotOverrideRepository } from './bots.js';
import { RoutineRepository } from './routines.js';
import { openDatabase } from './db.js';
import { MessageRepository } from './messages.js';
import { ApprovalRepository, DeliverableRepository, SettingsRepository } from './misc.js';
import { NotificationRepository } from './notifications.js';
import { SearchRepository } from './search.js';
import { TaskSummaryRepository } from './summaries.js';
import { TaskSymbolRepository } from './task-symbols.js';
import { TaskRepository } from './tasks.js';
import { ToolEventRepository } from './tool-events.js';
import { UsageRepository } from './usage.js';
import { WatchRepository } from './watches.js';

export class Store {
  readonly bots: BotOverrideRepository;
  readonly tasks: TaskRepository;
  readonly messages: MessageRepository;
  readonly toolEvents: ToolEventRepository;
  readonly usage: UsageRepository;
  readonly deliverables: DeliverableRepository;
  readonly approvals: ApprovalRepository;
  readonly settings: SettingsRepository;
  readonly summaries: TaskSummaryRepository;
  readonly taskSymbols: TaskSymbolRepository;
  readonly search: SearchRepository;
  readonly routines: RoutineRepository;
  readonly alertEvents: AlertEventRepository;
  readonly watches: WatchRepository;
  readonly notifications: NotificationRepository;

  constructor(readonly db: DatabaseSync,dataDir?:string) {
    this.bots = new BotOverrideRepository(db);
    this.tasks = new TaskRepository(db);
    this.messages = new MessageRepository(db);
    this.toolEvents = new ToolEventRepository(db);
    this.usage = new UsageRepository(db);
    this.deliverables = new DeliverableRepository(db);
    this.approvals = new ApprovalRepository(db);
    this.settings = new SettingsRepository(db,dataDir);
    this.summaries = new TaskSummaryRepository(db);
    this.taskSymbols = new TaskSymbolRepository(db);
    this.search = new SearchRepository(db);
    this.routines = new RoutineRepository(db);
    this.alertEvents = new AlertEventRepository(db);
    this.watches = new WatchRepository(db);
    this.notifications = new NotificationRepository(db);
  }

  static open(dataDir: string): Store {
    return new Store(openDatabase(dataDir),dataDir);
  }

  close(): void {
    this.db.close();
  }
}

export { currentVersion, DATABASE_FILE, migrate, openDatabase } from './db.js';
export { isTerminalStatus } from './tasks.js';
export { resolveRootTask } from './search.js';
export type { SearchDocType, SearchDocumentRecord } from './search.js';
export type {
  AlertEventRecord,
  ApprovalRecord,
  BotOverride,
  BotOverrideUpdate,
  DeliverableRecord,
  JsonRecord,
  MessageKind,
  MessagePage,
  MessageRecord,
  MessageRole,
  NewDeliverable,
  NewMessage,
  NewTask,
  NewTaskSummary,
  NewAlertEvent,
  NewNotification,
  NewRoutine,
  NewWatch,
  NewWatchEvent,
  NotificationLevel,
  NotificationRecord,
  RoutineRecord,
  RoutineSchedule,
  RoutineSource,
  NewToolEvent,
  SummaryKeyNumber,
  SummarySource,
  SummarySymbol,
  TaskRecord,
  TaskStatus,
  TaskSummaryRecord,
  TaskSymbol,
  ToolEventRecord,
  ToolEventStatus,
  UsageRecord,
  WatchActor,
  WatchEventKind,
  WatchEventRecord,
  WatchRecord,
  WatchStatus,
} from './types.js';
