import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';

import type {
  BotSummary,
  DeliverableDto,
  MessageAttachmentDto,
  MessageDto,
  TaskDto,
  ToolEventDto
} from '@chives/server/protocol';

import { botFileContentUrl } from '../api/client';
import type { DraftState } from '../hooks/useTimeline';
import { ApprovalCard, approvalFromMessage } from './ApprovalCard';
import { RoutineCard, routineFromMessage } from './RoutineCard';
import { WatchCard, watchFromMessage } from './WatchCard';
import { DeliverableCards } from './DeliverableCard';
import { DelegationRow } from './DelegationRow';
import { deliverablesFromMessage, embeddedImagePaths, formatFileSize } from '../utils/deliverables';
import { formatDateLabel, formatTime, toDayKey } from '../utils/format';
import { Markdown } from './Markdown';
import { ReplyFooter } from './ReplyFooter';
import { TaskProgress } from './TaskProgress';
import './Timeline.css';

export interface PendingMessage {
  id: string;
  text: string;
  status: 'sending' | 'failed';
  attachments?: MessageAttachmentDto[];
}

export interface TimelineProps {
  botId: string;
  bots?: readonly BotSummary[];
  messages: MessageDto[];
  tasks: Record<string, TaskDto>;
  toolEvents: Record<string, ToolEventDto[]>;
  draft: DraftState | null;
  pending: PendingMessage[];
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  onRetryPending: (pending: PendingMessage) => void;
  /** Re-runs the last user message of a failed task. */
  onRetryTask?: (taskId: string) => Promise<void> | void;
  onDecideApproval?: (approvalId: string, decision: 'allow' | 'reject') => Promise<void>;
  onEnableRoutine?: (routineId: string) => Promise<void>;
  onDismissRoutine?: (routineId: string) => Promise<void>;
  onCancelWatch?: (watchId: string) => Promise<void>;
  activeDeliverableId?: string | null;
  onOpenDeliverable?: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
  onOpenAttachment?: (attachment: MessageAttachmentDto, trigger: HTMLElement) => void;
  /** Message to scroll to and briefly highlight after a timeline search. */
  highlightMessageId?: string | null;
}

type Item =
  | { kind: 'date'; key: string; label: string }
  | { kind: 'divider'; key: string; task: TaskDto }
  | { kind: 'message'; key: string; message: MessageDto }
  | { kind: 'task'; key: string; task: TaskDto; until?: string };

function buildItems(
  messages: MessageDto[],
  tasks: Record<string, TaskDto>
): Item[] {
  const items: Item[] = [];
  let currentDay = '';
  const seenTasks = new Set<string>();
  const seenDividers = new Set<string>();
  // A segment can contain several user turns. Bound historical progress to each turn.
  const usersByTask = new Set<string>();
  const nextUser = new Map<string, string>();
  const lastReply = new Map<string, string>();
  const turnWindows = new Map<string, {until?: string; end?: string}>();
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]!;
    const id = message.taskId;
    if (id === null) continue;
    if (message.role === 'bot' && message.kind === 'text' && !lastReply.has(id)) {
      lastReply.set(id, message.createdAt);
    } else if (message.role === 'user') {
      usersByTask.add(id);
      const until = nextUser.get(id);
      const end = lastReply.get(id);
      turnWindows.set(message.id, {...(until !== undefined ? {until} : {}), ...(end !== undefined ? {end} : {})});
      nextUser.set(id, message.createdAt);
      lastReply.delete(id);
    }
  }

  for (const message of messages) {
    const day = toDayKey(message.createdAt);
    if (day !== currentDay) {
      currentDay = day;
      items.push({ kind: 'date', key: `date-${day}`, label: formatDateLabel(message.createdAt) });
    }

    if (
      message.kind !== 'proactive' &&
      message.taskId !== null &&
      !seenDividers.has(message.taskId)
    ) {
      const task = tasks[message.taskId];
      if (task !== undefined) {
        seenDividers.add(message.taskId);
        items.push({ kind: 'divider', key: `divider-${task.id}`, task });
      }
    }

    if (message.role === 'user') {
      items.push({ kind: 'message', key: `message-${message.id}`, message });
      const task = message.taskId === null ? undefined : tasks[message.taskId];
      if (task) {
        const window = turnWindows.get(message.id);
        const startedAt = message.createdAt;
        const progress = window?.until
          ? {...task, startedAt, endedAt: window.end ?? startedAt, status: (window.end ? 'done' : 'interrupted') as TaskDto['status']}
          : {...task, startedAt};
        items.push({kind:'task', key:`task-${message.id}`, task:progress, ...(window?.until ? {until:window.until} : {})});
      }
      continue;
    }

    if (
      message.role === 'bot' &&
      message.taskId !== null &&
      !seenTasks.has(message.taskId) &&
      !usersByTask.has(message.taskId)
    ) {
      const task = tasks[message.taskId];
      if (task !== undefined) {
        seenTasks.add(message.taskId);
        items.push({ kind: 'task', key: `task-${task.id}`, task });
      }
    }

    items.push({ kind: 'message', key: `message-${message.id}`, message });
  }

  return items;
}

function childIdOf(message: MessageDto): string | undefined {
  const value = message.meta?.childTaskId;
  return typeof value === 'string' ? value : undefined;
}

/** Chronological separator after all report-back children of one round finished. */
function FollowUpDivider({
  message,
  bots,
  tasks,
  toolEvents,
  delegationMessages
}: {
  message: MessageDto;
  bots: readonly BotSummary[];
  tasks: Record<string, TaskDto>;
  toolEvents: Record<string, ToolEventDto[]>;
  delegationMessages: readonly MessageDto[];
}): ReactElement {
  const [open, setOpen] = useState(false);
  const raw = message.meta?.['childTaskIds'];
  const childIds = Array.isArray(raw)
    ? raw.filter((value): value is string => typeof value === 'string')
    : [];
  const rows = delegationMessages.filter((entry) => {
    const childId = childIdOf(entry);
    return childId !== undefined && childIds.includes(childId);
  });

  return (
    <div className="timeline__followup" role="group" aria-label={message.content}>
      <button
        type="button"
        className="timeline__followup-divider"
        aria-expanded={open}
        title={open ? '收起委派行' : '展开委派行'}
        onClick={() => setOpen((value) => !value)}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d="M2 4h10M2 7h7M2 10h4" strokeLinecap="round" />
        </svg>
        <span>{message.content}</span>
        <span className="timeline__followup-expand">
          {open ? '收起委派行' : `展开委派行（${rows.length}）`}
        </span>
        <span className="timeline__proactive-line" />
      </button>
      {open ? (
        <div className="timeline__followup-rows">
          {rows.map((row) => {
            const childId = childIdOf(row);
            return (
              <DelegationRow
                key={row.id}
                message={row}
                bots={bots}
                childTask={childId === undefined ? undefined : tasks[childId]}
                tools={childId === undefined ? undefined : (toolEvents[childId] ?? [])}
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

const EMPTY_IMAGE_PATHS: ReadonlySet<string> = new Set();

/** Relative images a task's own Markdown already shows inline. */
export function embeddedImagesByTask(
  messages: readonly MessageDto[]
): Map<string, Set<string>> {
  const byTask = new Map<string, Set<string>>();
  for (const message of messages) {
    if (message.role !== 'bot' || message.kind !== 'text' || message.taskId === null) continue;
    const paths = embeddedImagePaths(message.content);
    if (paths.length === 0) continue;
    const existing = byTask.get(message.taskId) ?? new Set<string>();
    for (const path of paths) existing.add(path);
    byTask.set(message.taskId, existing);
  }
  return byTask;
}

function isAttachment(value: unknown): value is MessageAttachmentDto {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry['path'] === 'string' &&
    typeof entry['name'] === 'string' &&
    typeof entry['size'] === 'number' &&
    typeof entry['kind'] === 'string'
  );
}

function attachmentsFromMessage(message: MessageDto): MessageAttachmentDto[] {
  const raw = message.meta?.['attachments'];
  return Array.isArray(raw) ? raw.filter(isAttachment) : [];
}

function AttachmentFileIcon(): ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M4 2h5l3 3v9H4z" strokeLinejoin="round" />
      <path d="M9 2v3h3" strokeLinejoin="round" />
    </svg>
  );
}

function AttachmentCards({
  attachments,
  botId,
  onOpen
}: {
  attachments: readonly MessageAttachmentDto[];
  botId: string;
  onOpen: ((attachment: MessageAttachmentDto, trigger: HTMLElement) => void) | undefined;
}): ReactElement | null {
  if (attachments.length === 0) return null;
  return (
    <ul className="timeline__attachments" aria-label="附件">
      {attachments.map((attachment) => (
        <li key={attachment.path}>
          <button
            type="button"
            className={`timeline__attachment${attachment.kind === 'image' ? ' timeline__attachment--image' : ''}`}
            title={attachment.name}
            onClick={(event) => onOpen?.(attachment, event.currentTarget)}
          >
            {attachment.kind === 'image' ? (
              <img
                className="timeline__attachment-thumb"
                src={botFileContentUrl(botId, attachment.path)}
                alt={attachment.name}
              />
            ) : (
              <span className="timeline__attachment-icon" aria-hidden="true">
                <AttachmentFileIcon />
              </span>
            )}
            <span className="timeline__attachment-text">
              <span className="timeline__attachment-name">{attachment.name}</span>
              <span className="timeline__attachment-size">{formatFileSize(attachment.size)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function MessageRow({
  message,
  bots,
  tasks,
  toolEvents,
  deliverables,
  embeddedImages,
  delegationMessages,
  onDecideApproval,
  onEnableRoutine,
  onDismissRoutine,
  onCancelWatch,
  onRetryTask,
  activeDeliverableId,
  onOpenDeliverable,
  onOpenAttachment
}: {
  message: MessageDto;
  bots: readonly BotSummary[];
  tasks: Record<string, TaskDto>;
  toolEvents: Record<string, ToolEventDto[]>;
  deliverables: readonly DeliverableDto[];
  embeddedImages: ReadonlySet<string>;
  delegationMessages: readonly MessageDto[];
  onDecideApproval: ((approvalId: string, decision: 'allow' | 'reject') => Promise<void>) | undefined;
  onEnableRoutine: ((routineId: string) => Promise<void>) | undefined;
  onDismissRoutine: ((routineId: string) => Promise<void>) | undefined;
  onCancelWatch: ((watchId: string) => Promise<void>) | undefined;
  onRetryTask: ((taskId: string) => Promise<void> | void) | undefined;
  activeDeliverableId: string | null;
  onOpenDeliverable:
    | ((deliverable: DeliverableDto, trigger: HTMLElement) => void)
    | undefined;
  onOpenAttachment:
    | ((attachment: MessageAttachmentDto, trigger: HTMLElement) => void)
    | undefined;
}): ReactElement {
  if (message.role === 'user') {
    const attachments = attachmentsFromMessage(message);
    return (
      <div className="timeline__user-row">
        {message.content === '' ? null : (
          <div className="timeline__user-bubble">{message.content}</div>
        )}
        <AttachmentCards
          attachments={attachments}
          botId={message.botId}
          onOpen={onOpenAttachment}
        />
        <div className="timeline__time">{formatTime(message.createdAt)}</div>
      </div>
    );
  }

  if (message.kind === 'delegation') {
    const childId = childIdOf(message);
    return (
      <DelegationRow
        message={message}
        bots={bots}
        childTask={childId === undefined ? undefined : tasks[childId]}
        tools={childId === undefined ? undefined : (toolEvents[childId] ?? [])}
      />
    );
  }

  if (message.kind === 'proactive' && message.meta?.['followup'] === true) {
    return (
      <FollowUpDivider
        message={message}
        bots={bots}
        tasks={tasks}
        toolEvents={toolEvents}
        delegationMessages={delegationMessages}
      />
    );
  }

  if (message.kind === 'approval') {
    const watch = watchFromMessage(message);
    if (watch !== null) {
      return (
        <WatchCard
          card={watch}
          {...(onCancelWatch === undefined ? {} : { onDelete: onCancelWatch })}
        />
      );
    }
    const routine = routineFromMessage(message);
    if (routine !== null) {
      return (
        <RoutineCard
          card={routine}
          onEnable={onEnableRoutine ?? (async () => undefined)}
          onDismiss={onDismissRoutine ?? (async () => undefined)}
        />
      );
    }
    const approval = approvalFromMessage(message);
    if (approval !== null) {
      return (
        <ApprovalCard
          approval={approval}
          onDecide={onDecideApproval ?? (async () => undefined)}
        />
      );
    }
  }

  if (message.kind === 'deliverable') {
    return (
      <DeliverableCards
        message={message}
        bots={bots}
        activeId={activeDeliverableId}
        onOpen={onOpenDeliverable ?? (() => undefined)}
        embeddedImages={embeddedImages}
      />
    );
  }

  if (message.kind === 'proactive') {
    return (
      <div className="timeline__proactive-divider" role="separator" aria-label={message.content}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="7" cy="7" r="5.5" />
          <path d="M7 4v3l2 1.5" strokeLinecap="round" />
        </svg>
        <span>{message.content}</span>
        <span className="timeline__proactive-line" />
      </div>
    );
  }

  if (message.role === 'system') {
    const code = typeof message.meta?.['code'] === 'string' ? message.meta['code'] : null;
    const retryable =
      code !== null &&
      code !== 'engine_unavailable' &&
      message.taskId !== null &&
      onRetryTask !== undefined;
    return (
      <div
        className={`timeline__system${message.kind === 'approval' ? ' timeline__system--approval' : ''}${
          message.meta?.['notification'] === true ? ' timeline__system--notification' : ''
        }${code === 'engine_unavailable' ? ' timeline__system--hint' : ''}`}
        role="note"
      >
        <span>{message.content}</span>
        {typeof message.meta?.handoffHref === 'string' && /^#\/(bots$|bot\/[a-z0-9_-]+\?task=[\w-]+$)/.test(message.meta.handoffHref) &&
          <a href={message.meta.handoffHref}>{message.meta.handoffHref==='#/bots'?'去聘用':'查看承接会话'}</a>}
        {typeof message.meta?.managedTaskHref==='string' && /^#\/settings\?tab=tasks&kind=(technical|watch)&task=[\w.-]+$/.test(message.meta.managedTaskHref) && <a href={message.meta.managedTaskHref}>查看盯盘任务</a>}
        {retryable ? (
          <button
            type="button"
            className="timeline__system-retry"
            onClick={() => {
              if (message.taskId !== null) void onRetryTask(message.taskId);
            }}
          >
            {code === 'harness_crashed' ? '重试这一轮' : '重试'}
          </button>
        ) : null}
      </div>
    );
  }

  return <BotReply message={message} deliverables={deliverables} onOpenDeliverable={onOpenDeliverable} />;
}

function BotReply({message, deliverables, onOpenDeliverable}: {
  message: MessageDto;
  deliverables: readonly DeliverableDto[];
  onOpenDeliverable?: ((deliverable: DeliverableDto, trigger: HTMLElement) => void) | undefined;
}) {
  const content = useRef<HTMLDivElement>(null);
  return (
    <section className="timeline__bot-message" aria-label="Bot 回复">
      <div ref={content}>
        <Markdown botId={message.botId} deliverables={deliverables} onOpenDeliverable={onOpenDeliverable}>
          {message.content}
        </Markdown>
      </div>
      <ReplyFooter message={message} content={content} />
    </section>
  );
}

export function Timeline({
  botId,
  bots = [],
  messages: history,
  tasks,
  toolEvents,
  draft,
  pending,
  hasMore,
  loadingOlder,
  onLoadOlder,
  onRetryPending,
  onDecideApproval,
  onEnableRoutine,
  onDismissRoutine,
  onCancelWatch,
  onRetryTask,
  activeDeliverableId = null,
  onOpenDeliverable,
  onOpenAttachment,
  highlightMessageId = null
}: TimelineProps): ReactElement {
  const messages = useMemo(() => history.filter(message => {
    if (message.role !== 'system' || message.kind !== 'notice') return true;
    const { kernel, model } = message.meta ?? {};
    return typeof kernel !== 'string' || typeof model !== 'string' || message.content !== `${kernel} · ${model}`;
  }), [history]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [showNew, setShowNew] = useState(false);
  const nearBottomRef = useRef(true);
  const previousBotRef = useRef(botId);
  const previousContentRef = useRef('');
  const prependRef = useRef<{ height: number; top: number } | null>(null);
  const firstMessageIdRef = useRef(messages[0]?.id ?? null);

  const contentKey = `${messages.at(-1)?.id ?? ''}:${draft?.text.length ?? 0}:${pending.map((item) => item.id).join(',')}`;

  const scrollToBottom = (smooth: boolean): void => {
    const element = scrollRef.current;
    if (element === null) return;
    if (typeof element.scrollTo === 'function') {
      element.scrollTo({ top: element.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    } else {
      element.scrollTop = element.scrollHeight;
    }
    nearBottomRef.current = true;
    setShowNew(false);
  };

  useEffect(() => {
    if (highlightMessageId === null) return;
    const container = scrollRef.current;
    const target = container?.querySelector(`[data-message-id="${highlightMessageId}"]`);
    if (target instanceof HTMLElement && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [highlightMessageId]);

  useLayoutEffect(() => {
    const firstId = messages[0]?.id ?? null;
    const anchored = prependRef.current;
    if (anchored !== null && firstMessageIdRef.current !== firstId) {
      const element = scrollRef.current;
      if (element !== null) {
        element.scrollTop = element.scrollHeight - anchored.height + anchored.top;
      }
      prependRef.current = null;
    }
    firstMessageIdRef.current = firstId;
  }, [messages]);

  useLayoutEffect(() => {
    if (previousBotRef.current !== botId) {      previousBotRef.current = botId;
      previousContentRef.current = contentKey;
      nearBottomRef.current = true;
      setShowNew(false);
      scrollToBottom(false);
      return;
    }
    if (previousContentRef.current === contentKey) return;
    previousContentRef.current = contentKey;
    if (nearBottomRef.current) scrollToBottom(false);
    else setShowNew(true);
  }, [botId, contentKey]);

  const handleScroll = (): void => {
    const element = scrollRef.current;
    if (element === null) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    nearBottomRef.current = distance < 120;
    if (nearBottomRef.current) setShowNew(false);
    if (element.scrollTop < 80 && hasMore && !loadingOlder) {
      prependRef.current = { height: element.scrollHeight, top: element.scrollTop };
      onLoadOlder();
    }
  };

  const items = buildItems(messages, tasks);
  const delegationMessages = messages.filter((message) => message.kind === 'delegation');
  const embeddedImages = embeddedImagesByTask(messages);
  const allDeliverables = messages.flatMap((message) =>
    message.kind === 'deliverable' ? deliverablesFromMessage(message) : []
  );
  const recentDeliverables = [...allDeliverables].sort((left, right) =>
    right.createdAt.localeCompare(left.createdAt)
  );
  const deliverablesFor = (taskId: string | null): DeliverableDto[] => {
    if (taskId === null) return recentDeliverables;
    const inTask = recentDeliverables.filter((entry) => entry.taskId === taskId);
    const ids = new Set(inTask.map((entry) => entry.id));
    return [...inTask, ...recentDeliverables.filter((entry) => !ids.has(entry.id))];
  };
  const lastDay = messages.length === 0 ? null : toDayKey(messages[messages.length - 1]?.createdAt ?? '');
  const todayKey = toDayKey(new Date().toISOString());
  const needsTodaySeparator =
    (pending.length > 0 || (draft !== null && draft.text !== '')) && lastDay !== todayKey;

  return (
    <div className="timeline">
      <div
        className="timeline__scroll"
        ref={scrollRef}
        onScroll={handleScroll}
        role="log"
        aria-label="时间线"
      >
        <div className="timeline__inner">
          {loadingOlder ? <div className="timeline__loading-older">正在加载更早的消息…</div> : null}
          {hasMore && !loadingOlder ? (
            <button type="button" className="timeline__load-older" onClick={onLoadOlder}>
              加载更早的消息
            </button>
          ) : null}

          {items.map((item) => {
            if (item.kind === 'date') {
              return (
                <div className="timeline__date" key={item.key}>
                  <span className="timeline__date-line" />
                  <span>{item.label}</span>
                  <span className="timeline__date-line" />
                </div>
              );
            }
            if (item.kind === 'divider') {
              return (
                <div
                  className="timeline__task-divider"
                  key={item.key}
                  role="separator"
                  aria-label="新任务"
                >
                  <span className="timeline__task-divider-line" />
                  <span className="timeline__task-divider-label">新任务</span>
                  <span className="timeline__task-divider-line" />
                </div>
              );
            }
            if (item.kind === 'task') {
              return (
                <div className="timeline__task" key={item.key}>
                  <TaskProgress task={item.task} tools={(toolEvents[item.task.id] ?? []).filter(tool =>
                    tool.startedAt >= item.task.startedAt && (item.until === undefined || tool.startedAt < item.until)
                  )} />
                </div>
              );
            }
            return (
              <div
                key={item.key}
                id={`timeline-message-${item.message.id}`}
                data-message-id={item.message.id}
                className={`timeline__anchor${
                  highlightMessageId === item.message.id ? ' timeline__anchor--highlight' : ''
                }`}
              >
                <MessageRow
                  message={item.message}
                  bots={bots}
                  tasks={tasks}
                  toolEvents={toolEvents}
                  deliverables={deliverablesFor(item.message.taskId)}
                  embeddedImages={
                    item.message.taskId === null
                      ? EMPTY_IMAGE_PATHS
                      : (embeddedImages.get(item.message.taskId) ?? EMPTY_IMAGE_PATHS)
                  }
                  delegationMessages={delegationMessages}
                  onDecideApproval={onDecideApproval}
                  onEnableRoutine={onEnableRoutine}
                  onDismissRoutine={onDismissRoutine}
                  onCancelWatch={onCancelWatch}
                  onRetryTask={onRetryTask}
                  activeDeliverableId={activeDeliverableId}
                  onOpenDeliverable={onOpenDeliverable}
                  onOpenAttachment={onOpenAttachment}
                />
              </div>
            );
          })}

          {needsTodaySeparator ? (
            <div className="timeline__date">
              <span className="timeline__date-line" />
              <span>今天</span>
              <span className="timeline__date-line" />
            </div>
          ) : null}

          {pending.map((item) => (
            <div className="timeline__user-row" key={item.id}>
              {item.text === '' ? null : (
                <div className="timeline__user-bubble">{item.text}</div>
              )}
              <AttachmentCards
                attachments={item.attachments ?? []}
                botId={botId}
                onOpen={onOpenAttachment}
              />
              {item.status === 'failed' ? (
                <div className="timeline__pending-error">
                  发送失败
                  <button type="button" className="timeline__retry" onClick={() => onRetryPending(item)}>
                    重试
                  </button>
                </div>
              ) : (
                <div className="timeline__pending">发送中…</div>
              )}
            </div>
          ))}

          {draft !== null && draft.text !== '' ? (
            <div className="timeline__draft" role="status" aria-label="正在生成的回复">
              <div className="timeline__draft-label">{draft.committed ? '正在提交…' : '正在撰写…'}</div>
              <div className="timeline__draft-text">
                {draft.text}
                {draft.committed ? null : <span className="timeline__cursor" aria-hidden="true" />}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {showNew ? (
        <button type="button" className="timeline__new" onClick={() => scrollToBottom(true)}>
          有新消息
        </button>
      ) : null}
    </div>
  );
}
