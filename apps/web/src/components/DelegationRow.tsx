import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';

import type {
  BotSummary,
  DelegationStatus,
  MessageDto,
  TaskDetail,
  TaskDto,
  ToolEventDto
} from '@chives/server/protocol';

import { fetchTask } from '../api/client';
import { BotAvatar } from '../brand/BotAvatar';
import { useNow } from '../hooks/useNow';
import { formatDurationBetween } from '../utils/format';
import { Markdown } from './Markdown';
import { ToolStepList } from './TaskProgress';
import './DelegationRow.css';

export interface DelegationRowProps {
  message: MessageDto;
  bots?: readonly BotSummary[];
  childTask?: TaskDto | undefined;
  tools?: ToolEventDto[] | undefined;
  /** Test seam; defaults to the real `GET /api/tasks/:id`. */
  fetchDetail?: (taskId: string) => Promise<TaskDetail>;
}

const STATUS_LABELS: Record<DelegationStatus, string> = {
  running: '进行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断'
};

function metaString(meta: Record<string, unknown> | null, key: string): string | undefined {
  const value = meta?.[key];
  return typeof value === 'string' ? value : undefined;
}

function metaStatus(meta: Record<string, unknown> | null, fallback: TaskDto | undefined): DelegationStatus {
  const value = meta?.status;
  if (
    value === 'running' ||
    value === 'done' ||
    value === 'failed' ||
    value === 'cancelled' ||
    value === 'interrupted'
  ) {
    return value;
  }
  return fallback?.status ?? 'running';
}

export function DelegationRow({
  message,
  bots = [],
  childTask,
  tools,
  fetchDetail
}: DelegationRowProps): ReactElement {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const targetBotId = metaString(message.meta, 'targetBotId') ?? childTask?.botId ?? '';
  const target = bots.find((bot) => bot.id === targetBotId);
  const initiatorName = bots.find((bot) => bot.id === message.botId)?.name ?? '发起方';
  const metaName = metaString(message.meta, 'targetBotName');
  const targetName =
    target?.name ?? (metaName !== undefined && metaName !== '' ? metaName : targetBotId !== '' ? targetBotId : '同事');
  const brief = metaString(message.meta, 'brief') ?? message.content;
  const childTaskId = metaString(message.meta, 'childTaskId') ?? childTask?.id;
  const status = metaStatus(message.meta, childTask);
  const running = status === 'running';
  const now = useNow(running);
  const startedAt = metaString(message.meta, 'startedAt') ?? childTask?.startedAt ?? message.createdAt;
  const endedAt = metaString(message.meta, 'endedAt') ?? childTask?.endedAt ?? null;
  const errorText = metaString(message.meta, 'error');
  const duration = formatDurationBetween(startedAt, running ? null : endedAt, now);

  useEffect(() => {
    if (!open || childTaskId === undefined) return undefined;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    const load = fetchDetail ?? fetchTask;
    void load(childTaskId)
      .then((value) => {
        if (!cancelled) setDetail(value);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoadError(cause instanceof Error ? cause.message : '子任务详情加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, childTaskId, status, fetchDetail]);

  const mergedTools = new Map<string, ToolEventDto>();
  for (const item of detail?.toolEvents ?? []) mergedTools.set(item.id, item);
  for (const item of tools ?? []) mergedTools.set(item.id, item);
  const shownTools = [...mergedTools.values()].sort((left, right) =>
    left.startedAt.localeCompare(right.startedAt)
  );
  const finalMessages = (detail?.messages ?? []).filter((item) => item.role === 'bot');
  const resultBotId = targetBotId !== '' ? targetBotId : message.botId;

  return (
    <section
      className={`delegation-row delegation-row--${status}`}
      aria-label={`委派给 ${targetName}`}
    >
      <button
        type="button"
        className="delegation-row__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="delegation-row__chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <BotAvatar
          emblem={target?.avatar.emblem ?? 'bars'}
          tone={target?.avatar.tone ?? 'ink'}
          size={18}
          name={targetName}
          className="delegation-row__avatar"
        />
        <span className="delegation-row__title">
          委派给 <strong>{targetName}</strong>：{brief}
        </span>
        <span className="delegation-row__status">
          {STATUS_LABELS[status]}
          {status === 'running'
            ? ` · 结果返回后${initiatorName}会自动合成 · ${duration}`
            : status === 'done'
              ? ` · ${duration}`
              : ''}
        </span>
      </button>

      {open ? (
        <div className="delegation-row__detail">
          <div className="delegation-row__label">任务说明</div>
          <div className="delegation-row__brief">{brief}</div>

          {loadError === null ? null : (
            <div className="delegation-row__error">{loadError}</div>
          )}
          {loading && detail === null ? (
            <div className="delegation-row__loading">正在读取子任务…</div>
          ) : null}

          <div className="delegation-row__label">工作步骤</div>
          <ToolStepList tools={shownTools} now={now} />

          {status === 'failed' && errorText !== null ? (
            <div className="delegation-row__error">{errorText}</div>
          ) : null}

          {finalMessages.length === 0 ? null : (
            <>
              <div className="delegation-row__label">子任务结果</div>
              {finalMessages.map((item) => (
                <div className="delegation-row__result" key={item.id}>
                  <Markdown botId={resultBotId}>{item.content}</Markdown>
                </div>
              ))}
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
