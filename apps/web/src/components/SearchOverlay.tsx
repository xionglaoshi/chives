import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactElement, ReactNode } from 'react';

import type {
  BotSummary,
  DeliverableDto,
  SearchResponse,
  SearchSnippet,
  SearchTaskGroup,
  TaskDetail
} from '@chives/server/protocol';

import { fetchTask, searchTimeline } from '../api/client';
import { fileName } from '../utils/deliverables';
import { formatDateLabel, formatTime } from '../utils/format';
import { Markdown } from './Markdown';
import { TaskProgress } from './TaskProgress';
import './SearchOverlay.css';

type SearchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; response: SearchResponse }
  | { status: 'error'; message: string };

type ProcessState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; details: TaskDetail[] }
  | { status: 'error'; message: string };

export interface SearchOverlayProps {
  bot: BotSummary;
  onClose: () => void;
  onReopen: (group: SearchTaskGroup) => Promise<void>;
  onLocate: (messageId: string) => void;
  onOpenDeliverable: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
}

function Highlighted({ snippet }: { snippet: SearchSnippet }): ReactElement {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const range of snippet.ranges) {
    const start = Math.max(cursor, Math.min(range.start, snippet.text.length));
    const end = Math.max(start, Math.min(range.end, snippet.text.length));
    if (start > cursor) parts.push(snippet.text.slice(cursor, start));
    if (end > start) parts.push(<mark key={`${start}-${end}`}>{snippet.text.slice(start, end)}</mark>);
    cursor = end;
  }
  if (cursor < snippet.text.length) parts.push(snippet.text.slice(cursor));
  return <>{parts}</>;
}

function groupTime(group: SearchTaskGroup): string {
  return `${formatDateLabel(group.lastActivityAt)} ${formatTime(group.lastActivityAt)}`;
}

function SummaryPanel({
  group,
  onReopen,
  onLocate,
  onOpenDeliverable,
  onShowProcess
}: {
  group: SearchTaskGroup;
  onReopen: (group: SearchTaskGroup) => void;
  onLocate: (messageId: string) => void;
  onOpenDeliverable: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
  onShowProcess: (group: SearchTaskGroup) => void;
}): ReactElement {
  const summary = group.summary;
  return (
    <>
      <div className="search-summary__heading">
        <span className="search-summary__chip">任务小结</span>
        <h2 className="search-summary__title">{group.title}</h2>
        <span className="search-summary__time">
          {groupTime(group)} · {group.steps} 步
        </span>
      </div>

      <div className="search-summary__section">
        <div className="search-summary__label">结论</div>
        <div>{summary?.conclusion ?? '这个任务还没有生成小结。'}</div>
      </div>

      <div className="search-summary__section">
        <div className="search-summary__label">关键数字（带来源和时间）</div>
        {summary === null || summary.keyNumbers.length === 0 ? (
          <div className="search-summary__muted">没有记录关键数字。</div>
        ) : (
          <ul className="search-summary__numbers">
            {summary.keyNumbers.map((entry, index) => (
              <li key={`${entry.label}-${index}`}>
                {entry.label === '' ? null : <span>{entry.label} </span>}
                <span>{entry.value}</span>
                {entry.source === '' && entry.asOf === '' ? null : (
                  <span className="search-summary__source">
                    {' '}· {[entry.source, entry.asOf].filter((part) => part !== '').join('，')}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="search-summary__section">
        <div className="search-summary__label">没解决的问题</div>
        {summary === null || summary.openQuestions.length === 0 ? (
          <div className="search-summary__muted">没有记录。</div>
        ) : (
          <ul className="search-summary__questions">
            {summary.openQuestions.map((question, index) => (
              <li key={`${question}-${index}`}>{question}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="search-summary__files">
        {group.deliverables.map((deliverable) => (
          <button
            key={deliverable.id}
            type="button"
            className="search-summary__file"
            title={deliverable.path}
            onClick={(event) => onOpenDeliverable(deliverable, event.currentTarget)}
          >
            {fileName(deliverable.path)}
          </button>
        ))}
      </div>

      <div className="search-summary__actions">
        <button type="button" className="search-summary__primary" onClick={() => onReopen(group)}>
          接着这个任务聊
        </button>
        <button
          type="button"
          className="search-summary__action"
          disabled={group.locateMessageId === null}
          onClick={() => {
            if (group.locateMessageId !== null) onLocate(group.locateMessageId);
          }}
        >
          在时间线里定位
        </button>
        <button type="button" className="search-summary__action" onClick={() => onShowProcess(group)}>
          查看完整过程
        </button>
      </div>
    </>
  );
}

function ProcessPanel({
  state,
  botId,
  onBack
}: {
  state: ProcessState;
  botId: string;
  onBack: () => void;
}): ReactElement {
  return (
    <>
      <div className="search-summary__heading">
        <span className="search-summary__chip">完整过程</span>
        <button type="button" className="search-summary__back" onClick={onBack}>
          返回小结
        </button>
      </div>
      {state.status === 'loading' ? <div className="search-state">正在加载完整过程…</div> : null}
      {state.status === 'error' ? (
        <div className="search-state search-state--error" role="alert">
          {state.message}
        </div>
      ) : null}
      {state.status === 'ready'
        ? state.details.map((detail) => (
            <div className="search-process__task" key={detail.task.id}>
              <div className="search-process__title">
                {detail.task.title ?? '未命名任务'}
                <span className="search-summary__time">{detail.task.status}</span>
              </div>
              <TaskProgress task={detail.task} tools={detail.toolEvents} />
              <div className="search-process__messages">
                {detail.messages.map((message) =>
                  message.role === 'user' ? (
                    <div className="search-process__user" key={message.id}>
                      {message.content}
                    </div>
                  ) : (
                    <div className="search-process__bot" key={message.id}>
                      <Markdown botId={botId}>{message.content}</Markdown>
                    </div>
                  )
                )}
              </div>
            </div>
          ))
        : null}
    </>
  );
}

export function SearchOverlay({
  bot,
  onClose,
  onReopen,
  onLocate,
  onOpenDeliverable
}: SearchOverlayProps): ReactElement {
  const [query, setQuery] = useState('');
  const [state, setState] = useState<SearchState>({ status: 'idle' });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [processState, setProcessState] = useState<ProcessState>({ status: 'idle' });
  const [showProcess, setShowProcess] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const requestIdRef = useRef(0);

  const groups = state.status === 'ready' ? state.response.groups : [];
  const selected = useMemo(
    () => groups.find((group) => group.taskId === selectedId) ?? groups[0] ?? null,
    [groups, selectedId]
  );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  useEffect(() => {
    setProcessState({ status: 'idle' });
    setShowProcess(false);
    setActionError(null);
  }, [selected?.taskId]);

  useEffect(() => {
    const text = query.trim();
    if (text === '') {
      setState({ status: 'idle' });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    const timer = window.setTimeout(() => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      void searchTimeline(bot.id, text, { limit: 20, signal: controller.signal })
        .then((response) => {
          if (controller.signal.aborted || requestId !== requestIdRef.current) return;
          setState({ status: 'ready', response });
          setSelectedId((current) =>
            current !== null && response.groups.some((group) => group.taskId === current)
              ? current
              : (response.groups[0]?.taskId ?? null)
          );
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          setState({
            status: 'error',
            message: cause instanceof Error ? cause.message : '搜索失败'
          });
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [bot.id, query, reloadToken]);

  const moveSelection = useCallback(
    (delta: number): void => {
      if (groups.length === 0) return;
      const current = Math.max(
        0,
        groups.findIndex((group) => group.taskId === selected?.taskId)
      );
      const next = (current + delta + groups.length) % groups.length;
      const target = groups[next];
      if (target !== undefined) setSelectedId(target.taskId);
    },
    [groups, selected?.taskId]
  );

  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveSelection(-1);
    }
  };

  const handleReopen = async (group: SearchTaskGroup): Promise<void> => {
    setBusy(true);
    setActionError(null);
    try {
      await onReopen(group);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : '无法接着这个任务聊');
    } finally {
      setBusy(false);
    }
  };

  const handleShowProcess = (group: SearchTaskGroup): void => {
    setShowProcess(true);
    setProcessState({ status: 'loading' });
    void Promise.all(group.taskIds.map((taskId) => fetchTask(taskId)))
      .then((details) => setProcessState({ status: 'ready', details }))
      .catch((cause: unknown) =>
        setProcessState({
          status: 'error',
          message: cause instanceof Error ? cause.message : '完整过程加载失败'
        })
      );
  };

  return (
    <div className="search-layer" role="dialog" aria-modal="true" aria-label={`搜索与${bot.name}的时间线`}>
      <button type="button" className="search-layer__backdrop" aria-label="关闭搜索" onClick={onClose} />
      <div className="search-layer__panel">
        <header className="search-layer__header">
          <span className="search-layer__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="7" cy="7" r="4.5" />
              <path d="M10.5 10.5L14 14" strokeLinecap="round" />
            </svg>
          </span>
          <label className="sr-only" htmlFor="chives-search">
            搜索与{bot.name}的时间线
          </label>
          <input
            id="chives-search"
            ref={inputRef}
            className="search-layer__input"
            value={query}
            placeholder={`搜索与${bot.name}的时间线`}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleInputKeyDown}
          />
          <span className="search-layer__count" aria-live="polite">
            {state.status === 'ready'
              ? `${state.response.totalGroups} 个任务 · ${state.response.totalHits} 处提到`
              : ''}
          </span>
          <button type="button" className="search-layer__close" onClick={onClose}>
            关闭搜索
          </button>
        </header>

        <div className="search-layer__body">
          <section className="search-results" aria-label="搜索结果">
            <div className="search-results__hint">按任务归组，最近的在前</div>
            {state.status === 'loading' ? <div className="search-state">正在搜索…</div> : null}
            {state.status === 'error' ? (
              <div className="search-state search-state--error" role="alert">
                <span>{state.message}</span>
                <button type="button" className="search-state__retry" onClick={() => setReloadToken((value) => value + 1)}>
                  重试
                </button>
              </div>
            ) : null}
            {state.status === 'ready' && state.response.groups.length === 0 ? (
              <div className="search-state">
                没有找到“{state.response.query}”。换个词，或者直接问 {bot.name}。
              </div>
            ) : null}
            {groups.map((group, index) => (
              <button
                key={group.taskId}
                type="button"
                className={`search-result${selected?.taskId === group.taskId ? ' search-result--active' : ''}`}
                aria-pressed={selected?.taskId === group.taskId}
                data-index={index}
                onClick={() => setSelectedId(group.taskId)}
              >
                <span className="search-result__top">
                  <span className="search-result__title">{group.title}</span>
                  <span className="search-result__time">{groupTime(group)}</span>
                </span>
                {group.summary === null || group.summary.conclusion === '' ? null : (
                  <span className="search-result__conclusion">结论：{group.summary.conclusion}</span>
                )}
                {group.snippets.slice(0, 2).map((snippet, snippetIndex) => (
                  <span className="search-result__snippet" key={`${snippet.sourceId}-${snippetIndex}`}>
                    <Highlighted snippet={snippet} />
                  </span>
                ))}
                <span className="search-result__meta">
                  {group.botName} · {group.hitCount} 处提到
                  {group.deliverables.length === 0 ? '' : ` · ${group.deliverables.length} 个文件`}
                </span>
              </button>
            ))}
            {groups.length > 0 ? (
              <div className="search-results__footer">
                也可以直接问：“上次{query.trim() === '' ? '' : `关于${query.trim()}的`}结论是什么？”{bot.name}会自己去翻这些记录。
              </div>
            ) : null}
          </section>

          <section className="search-summary" aria-label="任务小结">
            {selected === null ? (
              <div className="search-state">选中一个任务，查看它的小结。</div>
            ) : showProcess ? (
              <ProcessPanel state={processState} botId={bot.id} onBack={() => setShowProcess(false)} />
            ) : (
              <SummaryPanel
                group={selected}
                onReopen={(group) => void handleReopen(group)}
                onLocate={onLocate}
                onOpenDeliverable={(deliverable, trigger) => {
                  onClose();
                  onOpenDeliverable(deliverable, trigger);
                }}
                onShowProcess={handleShowProcess}
              />
            )}
            {actionError === null ? null : (
              <div className="search-state search-state--error" role="alert">
                {actionError}
              </div>
            )}
            {busy ? <div className="search-state">正在准备延续这个任务…</div> : null}
          </section>
        </div>
      </div>
    </div>
  );
}
