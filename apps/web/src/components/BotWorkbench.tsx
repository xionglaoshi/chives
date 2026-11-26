import { retiredRoutes } from '../utils/routes';
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import type { BotActivity, BotActivityPage, BotSummary, BotWorkbenchSection, ManagedTaskDto, TaskDto } from '@chives/server/protocol';
import { fetchBotActivity, fetchManagedTasks, markBotReplyRead } from '../api/client';
import { botPortraitUrl } from './BotPortraitPicker';
import './BotWorkbench.css';

const phoneQuery = '(max-width: 720px), (pointer: coarse) and (max-width: 960px) and (max-height: 520px)';
const minWidth = 250;
const maxWidth = 530;
const limitWidth = (value: number) => Math.min(maxWidth, Math.max(minWidth, value));

const defaultSections: readonly BotWorkbenchSection[] = [
  { kind: 'identity' }, { kind: 'tasks' }, { kind: 'activity' },
];

interface Props {
  bot: BotSummary;
  runningTask?: TaskDto | undefined;
  revision: string;
  watchRevision: number;
  previewOpen: boolean;
  onClosePreview: () => void;
  onLocateTask: (id: string) => void;
  onOpenActivity: (activity: BotActivity) => Promise<void> | void;
}

export function BotWorkbench({ previewOpen, onClosePreview, ...props }: Props) {
  const key = 'chives.bot-workbench.' + props.bot.id;
  const widthKey = key + '.width';
  const retiredId = Object.keys(retiredRoutes).find(id => retiredRoutes[id] === props.bot.id);
  const saved = (suffix: string) => localStorage.getItem(key + suffix) ??
    (retiredId ? localStorage.getItem('chives.bot-workbench.' + retiredId + suffix) : null);
  const collapsedKey = key + '.collapsed';
  const [phone, setPhone] = useState(() => window.matchMedia(phoneQuery).matches);
  const [width, setWidth] = useState(() => limitWidth(Number(saved('.width')) || 320));
  const [collapsed, setCollapsed] = useState(() => saved('.collapsed') === 'true');
  const [phoneOpen, setPhoneOpen] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const drag = useRef<{ startX: number; width: number } | null>(null);
  const folded = collapsed || previewOpen;
  useEffect(() => {
    const media = window.matchMedia(phoneQuery);
    const update = () => { setPhone(media.matches); setPhoneOpen(false); };
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);


  function saveWidth(value: number) {
    const next = limitWidth(value);
    setWidth(next);
    localStorage.setItem(widthKey, String(next));
  }

  function toggle() {
    if (phone) {
      if (previewOpen) onClosePreview();
      setPhoneOpen(value => !value);
      return;
    }
    if (previewOpen) onClosePreview();
    setCollapsed(!folded);
    localStorage.setItem(collapsedKey, String(!folded));
  }

  function resize(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    saveWidth(drag.current.width + drag.current.startX - event.clientX);
  }

  return <aside ref={panel} className={`bot-workbench${folded ? ' is-folded' : ''}${phoneOpen ? ' is-phone-open' : ''}`}
    aria-label={`${props.bot.name}工作台`} style={{ '--workbench-width': `${width}px` } as CSSProperties}
    onKeyDown={event => { if (event.key === 'Escape' && phoneOpen) setPhoneOpen(false); }}>
    {!folded && <div className="bot-workbench__grip" role="separator" tabIndex={0}
      aria-label="调整工作台宽度" aria-orientation="vertical" aria-valuemin={minWidth} aria-valuemax={maxWidth} aria-valuenow={width}
      onPointerDown={event => {
        if (event.button !== 0) return;
        drag.current = { startX: event.clientX, width: panel.current?.getBoundingClientRect().width ?? width };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={resize} onLostPointerCapture={() => { drag.current = null; }}
      onKeyDown={event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        saveWidth(width + (event.key === 'ArrowLeft' ? 20 : -20));
      }} />}
    <header className="bot-workbench__bar">
      <button type="button" className="bot-workbench__toggle" onClick={toggle}
        title="折叠或展开工作台" aria-label="折叠或展开工作台" aria-controls="bot-workbench-content" aria-expanded={phone ? phoneOpen : !folded}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M15 5v14" />
        </svg>
      </button>
      <strong>工作台</strong>
    </header>
    <div className="bot-workbench__content" id="bot-workbench-content">
      <BotWorkbenchContent {...props} onOpenActivity={entry => {
        setPhoneOpen(false);
        return props.onOpenActivity(entry);
      }} onLocateTask={id => {
        setPhoneOpen(false);
        props.onLocateTask(id);
      }} />
    </div>
  </aside>;
}

function BotWorkbenchContent({ bot, runningTask, revision, watchRevision, onLocateTask, onOpenActivity }:
  Omit<Props, 'previewOpen' | 'onClosePreview'>) {
  const sections = bot.workbench ?? defaultSections;
  const hasTasks = sections.some(section => section.kind === 'tasks');
  const hasActivity = sections.some(section => section.kind === 'activity');
  const [tasks, setTasks] = useState<ManagedTaskDto[] | null>(null);
  const [tasksError, setTasksError] = useState(false);
  const [activity, setActivity] = useState<BotActivityPage | null>(null);
  const [activityError, setActivityError] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  const moreRequest = useRef<AbortController | null>(null);
  const marked = useRef(new Map<string, string>());
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!hasTasks) return;
    const controller = new AbortController();
    const refresh = () => {
      void fetchManagedTasks(controller.signal).then(rows => {
        if (controller.signal.aborted) return;
        setTasks(rows.filter(task => task.botId === bot.id && task.enabled && task.canEnable &&
          (task.kind !== 'watch' || Date.parse(task.expiresAt) > Date.now())));
        setTasksError(false);
      }).catch(() => { if (!controller.signal.aborted) setTasksError(true); });
    };
    refresh();
    const timer = window.setInterval(refresh, 20_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [bot.id, hasTasks, watchRevision, retry]);

  useEffect(() => {
    if (!hasActivity) return;
    const controller = new AbortController();
    const refresh = () => {
      void fetchBotActivity(bot.id, null, controller.signal).then(page => {
        if (controller.signal.aborted) return;
        setActivity(current => {
          const entries = page.entries.map(entry => marked.current.has(entry.id)
            ? { ...entry, readAt: marked.current.get(entry.id)! } : entry);
          const boundary = entries.at(-1);
          if (!page.next || !boundary || !current || current.entries.length <= 30) return { ...page, entries };
          return { ...current, entries: entries.concat(current.entries.filter(entry =>
            entry.createdAt < boundary.createdAt || (entry.createdAt === boundary.createdAt && entry.id < boundary.id))) };
        });
        setActivityError('');
      }).catch(() => { if (!controller.signal.aborted) setActivityError('暂时无法读取动态。'); });
    };
    refresh();
    const timer = window.setInterval(refresh, 20_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [bot.id, hasActivity, revision, retry]);

  useEffect(() => () => moreRequest.current?.abort(), []);

  async function loadMore() {
    if (!activity?.next || moreRequest.current) return;
    const controller = new AbortController();
    moreRequest.current = controller;
    setLoadingMore(true);
    try {
      const page = await fetchBotActivity(bot.id, activity.next, controller.signal);
      if (controller.signal.aborted) return;
      setActivity(current => {
        const seen = new Set(current?.entries.map(entry => entry.id));
        return { ...page, entries: [...(current?.entries ?? []), ...page.entries.filter(entry => !seen.has(entry.id))] };
      });
      setActivityError('');
    } catch {
      if (!controller.signal.aborted) setActivityError('暂时无法读取更多动态。');
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
      moreRequest.current = null;
    }
  }

  async function open(entry: BotActivity) {
    if (!entry.readAt && marked.current.has(entry.id)) return;
    const readAt = new Date().toISOString();
    if (!entry.readAt) {
      marked.current.set(entry.id, readAt);
      setActivity(current => current && { ...current,
        entries: current.entries.map(row => row.id === entry.id ? { ...row, readAt } : row) });
    }
    try {
      await Promise.all([
        onOpenActivity(entry),
        !entry.readAt && entry.kind === 'reply' ? markBotReplyRead(bot.id, entry.id) : undefined,
      ]);
    } catch {
      marked.current.delete(entry.id);
      setActivity(current => current && { ...current,
        entries: current.entries.map(row => row.id === entry.id ? { ...row, readAt: entry.readAt } : row) });
      setActivityError('已读状态未保存，请重试。');
    }
  }

  function renderSection(section: BotWorkbenchSection) {
    if (section.kind === 'identity') return <section key={section.kind} className="bot-workbench__identity" aria-label={section.title ?? '岗位档案'}>
      <img src={botPortraitUrl(bot.portraitId ?? 'man-01')} alt="" width="64" height="80" />
      <div><h2>{bot.name}</h2><p>{bot.role}</p></div>
    </section>;

    if (section.kind === 'tasks') return <section key={section.kind} aria-labelledby="bot-workbench-tasks">
        <h3 id="bot-workbench-tasks">{section.title ?? '现有任务'}</h3>
        {!bot.runningTaskId && tasks?.length === 0 && !tasksError && <p>无任务</p>}
        {!tasks && !tasksError && <p>正在读取任务…</p>}
        {tasksError && <p role="alert">暂时无法读取任务。 <button type="button" onClick={() => setRetry(n => n + 1)}>重试</button></p>}
        <ul>
          {bot.runningTaskId && <li><button type="button" onClick={() => onLocateTask(bot.runningTaskId!)}>
            {runningTask?.title || '当前会话任务'}<span>执行中</span>
          </button></li>}
          {tasks?.map(task => <li key={`${task.kind}:${task.id}`}>
            <a href={`#/settings?tab=tasks&kind=${task.kind}&task=${encodeURIComponent(task.id)}`}>
              {task.title}<span>{task.kind === 'technical' || task.kind === 'archive' ? task.state : task.kind === 'watch' ? '监测中' : '待执行'}</span>
            </a>
          </li>)}
        </ul>
      </section>;

    return <section key={section.kind} aria-labelledby="bot-workbench-activity">
        <h3 id="bot-workbench-activity">{section.title ?? '动态'}</h3>
        {!activity && !activityError && <p>正在读取动态…</p>}
        {activity?.entries.length === 0 && !activityError && <p>暂无动态</p>}
        {activityError && <p role="alert">{activityError} <button type="button" onClick={() => setRetry(n => n + 1)}>重试</button></p>}
        <ul>{activity?.entries.map(entry => <li key={`${entry.kind}:${entry.id}`}>
          <button type="button" className={entry.readAt ? undefined : 'is-unread'}
            aria-label={entry.readAt ? entry.title : `未读：${entry.title}`}
            onClick={() => void open(entry)}>{entry.title}</button>
        </li>)}</ul>
        {activity?.next && <button type="button" disabled={loadingMore} onClick={() => void loadMore()}>
          {loadingMore ? '正在读取…' : '更多动态'}
        </button>}
      </section>;
  }

  const pinned = sections[0]?.kind === 'identity' ? sections[0] : undefined;
  return <>
    {pinned && renderSection(pinned)}
    <div className="bot-workbench__scroll">
      {(pinned ? sections.slice(1) : sections).map(renderSection)}
    </div>
  </>;
}
