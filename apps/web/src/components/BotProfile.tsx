import { KernelSettings } from "./KernelSettings";
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type {
  BotMemoryItem,
  BotProfile as BotProfileDto,
  BotSummary,
  DeliverableDto,
  MemoryKind,
  RoutineDto,
  WatchDto,
  WatchHistoryDto,
  WorkspaceFileDto,
  WorkspaceFileList
} from '@chives/server/protocol';

import {
  cancelWatch,
  deleteMemory,
  deleteRoutine,
  fetchBotFiles,
  fetchBotProfile,
  fetchWatch,
  revealBotDirectory,
  runRoutine,
  updateBot,
  updateMemory,
  updateRoutine,
  type BotPatch
} from '../api/client';
import { BotAvatar } from '../brand/BotAvatar';
import { formatFileSize } from '../utils/deliverables';
import { formatShanghaiDate } from '../utils/format';
import {
  mcpInfo,
  shortenWorkspacePath,
  visibleMcp
} from '../utils/botProfile';
import { AvatarEditDialog } from './AvatarEditDialog';
import './BotProfile.css';

export interface BotProfileProps {
  bot: BotSummary;
  onOpenConversation: (botId: string) => void;
  onBotUpdated: (bot: BotSummary) => void;
  onOpenDeliverable: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
  onOpenWorkspaceMap?: (botId: string) => void;
  activeDeliverableId: string | null;
  /** Bumped when a `memory.updated` event arrives, so another tab's edit reloads. */
  memoryRevision?: number;
}

type WorkspaceGroupKey = 'reports' | 'charts' | 'data' | 'scripts' | 'scratch' | 'unarchived';

interface WorkspaceTopic {
  name: string;
  files: WorkspaceFileDto[];
}

interface WorkspaceGroup {
  key: WorkspaceGroupKey;
  label: string;
  files: WorkspaceFileDto[];
  topics: WorkspaceTopic[];
}

const WORKSPACE_GROUP_ORDER: WorkspaceGroupKey[] = [
  'reports',
  'charts',
  'data',
  'scripts',
  'scratch',
  'unarchived'
];

const WORKSPACE_GROUP_LABELS: Record<WorkspaceGroupKey, string> = {
  reports: '报告',
  charts: '图表',
  data: '数据',
  scripts: '脚本',
  scratch: '临时',
  unarchived: '未归档'
};

const WORKSPACE_GROUP_COLLAPSED: Record<WorkspaceGroupKey, boolean> = {
  reports: false,
  charts: false,
  data: false,
  scripts: false,
  scratch: true,
  unarchived: true
};

const CONVENTIONAL_GROUP_KEYS = new Set<WorkspaceGroupKey>([
  'reports',
  'charts',
  'data',
  'scripts',
  'scratch'
]);

function newestFirst(left: WorkspaceFileDto, right: WorkspaceFileDto): number {
  return right.modifiedAt.localeCompare(left.modifiedAt) || left.name.localeCompare(right.name);
}

function workspaceGroupsOf(files: readonly WorkspaceFileDto[]): WorkspaceGroup[] {
  const buckets = new Map<WorkspaceGroupKey, WorkspaceFileDto[]>();
  for (const key of WORKSPACE_GROUP_ORDER) buckets.set(key, []);
  for (const file of files) {
    const top = file.path.split('/')[0] ?? '';
    const key = CONVENTIONAL_GROUP_KEYS.has(top as WorkspaceGroupKey)
      ? (top as WorkspaceGroupKey)
      : 'unarchived';
    buckets.get(key)?.push(file);
  }
  return WORKSPACE_GROUP_ORDER.map((key) => {
    const grouped = [...(buckets.get(key) ?? [])].sort(newestFirst);
    const topics: WorkspaceTopic[] = [];
    if (key === 'reports') {
      const byTopic = new Map<string, WorkspaceFileDto[]>();
      for (const file of grouped) {
        const rest = file.path.slice('reports/'.length);
        const separator = rest.indexOf('/');
        const topic = separator < 0 ? '（未分主题）' : rest.slice(0, separator);
        const bucket = byTopic.get(topic);
        if (bucket === undefined) byTopic.set(topic, [file]);
        else bucket.push(file);
      }
      for (const [name, topicFiles] of [...byTopic.entries()].sort(([left], [right]) =>
        left.localeCompare(right, 'zh-CN')
      )) {
        topics.push({ name, files: topicFiles });
      }
    }
    return { key, label: WORKSPACE_GROUP_LABELS[key], files: grouped, topics };
  });
}

function totalBytesOf(files: readonly WorkspaceFileDto[]): number {
  return files.reduce((sum, file) => sum + file.size, 0);
}

const MEMORY_KIND_LABELS: Record<MemoryKind, string> = {
  preference: '偏好',
  view: '观点',
  fact: '事实',
  note: '笔记'
};

interface MemoryDraft {
  title: string;
  body: string;
  kind: MemoryKind;
  expiresAt: string;
}

function toDraft(item: BotMemoryItem): MemoryDraft {
  return {
    title: item.title,
    body: item.body,
    kind: item.kind,
    expiresAt: item.expiresAt === null ? '' : formatShanghaiDate(item.expiresAt)
  };
}

interface PermissionRow {
  label: string;
  value: string;
}

function permissionsFor(profile: BotProfileDto): PermissionRow[] {
  const hasPaperBroker = profile.mcp.includes('paper_broker');
  const hasPortfolio = profile.mcp.includes('portfolio');
  return [
    {
      label: '可以委派',
      value:
        profile.canDelegateTo.length === 0
          ? '无'
          : profile.canDelegateTo.map((entry) => entry.name).join('、')
    },
    { label: '写入范围', value: '只能写自己的工作目录' },
    {
      label: '代码执行',
      value:
        profile.tools.code === 'sandboxed'
          ? '可以，仅用于计算与画图，限工作目录内'
          : '不能'
    },
    {
      label: '下单',
      value: hasPaperBroker ? '只有模拟盘，每次都要你批准' : '不能下单'
    },
    {
      label: '你的持仓',
      value: hasPortfolio ? '只在你问到时读取' : '读不到'
    },
    { label: '模型', value: `${profile.model} · 运行在 dsh 上` }
  ];
}

function deliverableForFile(
  file: WorkspaceFileDto,
  botId: string,
  recent: readonly DeliverableDto[]
): DeliverableDto | null {
  if (file.deliverableId === null) return null;
  const known = recent.find((entry) => entry.id === file.deliverableId);
  if (known !== undefined) return known;
  return {
    id: file.deliverableId,
    taskId: '',
    botId,
    path: file.path,
    kind: file.kind,
    size: file.size,
    createdAt: file.modifiedAt
  };
}

function formatRoutineTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
}

export function BotProfile({
  bot,
  onOpenConversation,
  onBotUpdated,
  onOpenDeliverable,
  onOpenWorkspaceMap,
  activeDeliverableId,
  memoryRevision = 0
}: BotProfileProps): ReactElement {
  const [profile, setProfile] = useState<BotProfileDto | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [files, setFiles] = useState<WorkspaceFileDto[]>([]);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [revealNotice, setRevealNotice] = useState<string | null>(null);
  const [toggledGroups, setToggledGroups] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [showAllMemories, setShowAllMemories] = useState(false);
  const [editingMemorySlug, setEditingMemorySlug] = useState<string | null>(null);
  const [memoryDraft, setMemoryDraft] = useState<MemoryDraft | null>(null);
  const [deletingMemorySlug, setDeletingMemorySlug] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [routines, setRoutines] = useState<RoutineDto[]>([]);
  const [routineBusy, setRoutineBusy] = useState<string | null>(null);
  const [routineNotice, setRoutineNotice] = useState<string | null>(null);
  const [watchBusy, setWatchBusy] = useState<string | null>(null);
  const [watchNotice, setWatchNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setProfileError(null);
    setFilesError(null);
    setRevealNotice(null);
    setToggledGroups({});
    setEditing(false);
    setShowAllMemories(false);
    setEditingMemorySlug(null);
    setMemoryDraft(null);
    setDeletingMemorySlug(null);
    setMemoryNotice(null);
    setRoutineBusy(null);
    setRoutineNotice(null);
    setWatchBusy(null);
    setWatchNotice(null);
    void fetchBotProfile(bot.id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setProfile(result);
          setRoutines(result.routines);
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setProfileError(cause instanceof Error ? cause.message : '资料加载失败');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    void fetchBotFiles(bot.id, '', controller.signal, true)
      .then((result: WorkspaceFileList) => {
        if (!controller.signal.aborted) setFiles(result.files);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setFilesError(cause instanceof Error ? cause.message : '文件列表加载失败');
        }
      });
    return () => controller.abort();
  }, [bot.id, reloadToken, memoryRevision]);

  const handleReveal = useCallback((): void => {
    void revealBotDirectory(bot.id)
      .then(() => setRevealNotice('已在访达中打开'))
      .catch((cause: unknown) => {
        setRevealNotice(cause instanceof Error ? cause.message : '无法在访达中打开');
      });
  }, [bot.id]);

  const handleSave = useCallback(
    (patch: BotPatch): Promise<BotSummary> => updateBot(bot.id, patch),
    [bot.id]
  );

  const handleSaved = useCallback(
    (saved: BotSummary): void => {
      setEditing(false);
      onBotUpdated(saved);
      setProfile((current) => (current === null ? current : { ...current, bot: saved }));
    },
    [onBotUpdated]
  );

  const applyMemoryItems = useCallback((items: BotMemoryItem[], count: number): void => {
    setProfile((current) =>
      current === null
        ? current
        : {
            ...current,
            memory: {
              ...current.memory,
              items,
              count,
              updatedAt: new Date().toISOString()
            }
          }
    );
  }, []);

  const toggleRoutine = useCallback(
    (routine: RoutineDto): void => {
      setRoutineBusy(routine.id);
      setRoutineNotice(null);
      void updateRoutine(routine.id, { enabled: !routine.enabled })
        .then((saved) =>
          setRoutines((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)))
        )
        .catch((cause: unknown) =>
          setRoutineNotice(cause instanceof Error ? cause.message : '更新主动任务失败')
        )
        .finally(() => setRoutineBusy(null));
    },
    []
  );

  const runRoutineNow = useCallback((routine: RoutineDto): void => {
    setRoutineBusy(routine.id);
    setRoutineNotice(null);
    void runRoutine(routine.id)
      .then(() => setRoutineNotice(`已触发「${routine.title}」，结果会出现在时间线`))
      .catch((cause: unknown) =>
        setRoutineNotice(cause instanceof Error ? cause.message : '运行主动任务失败')
      )
      .finally(() => setRoutineBusy(null));
  }, []);

  const removeRoutine = useCallback((routine: RoutineDto): void => {
    setRoutineBusy(routine.id);
    setRoutineNotice(null);
    void deleteRoutine(routine.id)
      .then(() => setRoutines((current) => current.filter((entry) => entry.id !== routine.id)))
      .catch((cause: unknown) =>
        setRoutineNotice(cause instanceof Error ? cause.message : '删除主动任务失败')
      )
      .finally(() => setRoutineBusy(null));
  }, []);

  const handleMemoryEdit = useCallback((item: BotMemoryItem): void => {
    setEditingMemorySlug(item.slug);
    setDeletingMemorySlug(null);
    setMemoryDraft(toDraft(item));
    setMemoryNotice(null);
  }, []);

  const handleMemorySave = useCallback((): void => {
    if (profile === null || editingMemorySlug === null || memoryDraft === null) return;
    if (memoryDraft.title.trim() === '' || memoryDraft.body.trim() === '') {
      setMemoryNotice('标题和正文不能为空');
      return;
    }
    const expiresAt =
      memoryDraft.expiresAt === ''
        ? null
        : new Date(`${memoryDraft.expiresAt}T00:00:00.000Z`).toISOString();
    setMemoryBusy(true);
    setMemoryNotice(null);
    void updateMemory(bot.id, editingMemorySlug, {
      title: memoryDraft.title,
      body: memoryDraft.body,
      kind: memoryDraft.kind,
      expiresAt
    })
      .then((result) => {
        const items = profile.memory.items.map((item) =>
          item.slug === editingMemorySlug && result.memory !== null ? result.memory : item
        );
        applyMemoryItems(items, result.count);
        setEditingMemorySlug(null);
        setMemoryDraft(null);
        setMemoryNotice('已保存，下一轮对话生效');
      })
      .catch((cause: unknown) => {
        setMemoryNotice(cause instanceof Error ? cause.message : '保存失败');
      })
      .finally(() => setMemoryBusy(false));
  }, [applyMemoryItems, bot.id, editingMemorySlug, memoryDraft, profile]);

  const handleMemoryDelete = useCallback(
    (slug: string): void => {
      if (profile === null) return;
      setMemoryBusy(true);
      setMemoryNotice(null);
      void deleteMemory(bot.id, slug)
        .then((result) => {
          applyMemoryItems(
            profile.memory.items.filter((item) => item.slug !== slug),
            result.count
          );
          setDeletingMemorySlug(null);
          setMemoryNotice('已删除，下一轮对话生效');
        })
        .catch((cause: unknown) => {
          setMemoryNotice(cause instanceof Error ? cause.message : '删除失败');
        })
        .finally(() => setMemoryBusy(false));
    },
    [applyMemoryItems, bot.id, profile]
  );

  const renderWorkspaceFile = (file: WorkspaceFileDto): ReactElement => {
    const deliverable =
      profile === null ? null : deliverableForFile(file, bot.id, profile.recentDeliverables);
    const details = `${formatFileSize(file.size)} · ${new Date(file.modifiedAt).toLocaleDateString('zh-CN')}`;
    return (
      <li className="bot-profile__file" key={file.path}>
        {deliverable === null ? (
          <span className="bot-profile__file-static">
            <span className="bot-profile__file-name" title={file.path}>
              {file.name}
            </span>
            <span className="bot-profile__file-meta">{details}</span>
          </span>
        ) : (
          <button
            type="button"
            className={`bot-profile__file-button${
              activeDeliverableId === deliverable.id ? ' bot-profile__file-button--active' : ''
            }`}
            onClick={(event) => onOpenDeliverable(deliverable, event.currentTarget)}
            title={file.path}
          >
            <span className="bot-profile__file-name">{file.name}</span>
            <span className="bot-profile__file-meta">{details}</span>
          </button>
        )}
      </li>
    );
  };

  const headerName = bot.name;
  const skills = profile?.skills ?? [];
  const tools = profile === null ? [] : visibleMcp(profile.mcp);
  const profileWatches = [...(profile?.watches ?? [])].sort((left, right) => {
    const rank = (status: WatchDto['status']): number =>
      status === 'active' ? 0 : status === 'triggered' ? 1 : status === 'expired' ? 2 : 3;
    return rank(left.status) - rank(right.status) || right.updatedAt.localeCompare(left.updatedAt);
  });
  const memoryItems = profile?.memory.items ?? [];
  const memoryCount = profile?.memory.count ?? 0;
  const memoryLimit = profile?.memory.limit ?? 200;
  const visibleMemories = showAllMemories ? memoryItems : memoryItems.slice(0, 5);
  const workspaceGroups = useMemo(() => workspaceGroupsOf(files), [files]);
  const groupOpen = (key: WorkspaceGroupKey): boolean =>
    toggledGroups[key] ?? !WORKSPACE_GROUP_COLLAPSED[key];
  const toggleGroup = (key: WorkspaceGroupKey): void => {
    setToggledGroups((current) => ({ ...current, [key]: !(current[key] ?? !WORKSPACE_GROUP_COLLAPSED[key]) }));
  };

  return (
    <div className="bot-profile">
      <header className="bot-profile__header">
        <BotAvatar
          emblem={bot.avatar.emblem}
          tone={bot.avatar.tone}
          size={18}
          name={headerName}
        />
        <div className="bot-profile__identity">
          <h1 className="bot-profile__name">{headerName}</h1>
          <div className="bot-profile__role">{profile?.role ?? bot.role}</div>
          {profile?.personaSummary !== undefined ? (
            <p className="bot-profile__persona">{profile.personaSummary}</p>
          ) : null}
        </div>
        <div className="bot-profile__header-actions">
          <button
            type="button"
            className="bot-profile__button bot-profile__button--primary"
            onClick={() => onOpenConversation(bot.id)}
          >
            {bot.hired === false ? '查看历史对话' : '去对话'}
          </button>
          <button
            type="button"
            className="bot-profile__button"
            onClick={() => setEditing(true)}
            disabled={profile === null}
          >
            编辑头像与称呼
          </button>
        </div>
      </header>
      <KernelSettings key={bot.id} id={bot.id} onSave={() => setReloadToken(n => n + 1)} />

      {profileError !== null ? (
        <div className="bot-profile__error" role="alert">
          资料没有加载出来：{profileError}
          <button
            type="button"
            className="bot-profile__button"
            onClick={() => setReloadToken((value) => value + 1)}
          >
            重试
          </button>
        </div>
      ) : null}

      <div className="bot-profile__columns">
        <div className="bot-profile__column">
          <section className="bot-profile__section" aria-labelledby="profile-skills">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-skills">
                技能
              </h2>
              <span className="bot-profile__section-meta">
                {profile === null
                  ? loading
                    ? '正在读取…'
                    : '—'
                  : `${skills.length} 项 · 由 Chives 预置，不可修改`}
              </span>
            </div>
            {skills.map((skill) => (
              <div className="bot-profile__row" key={skill.name}>
                <span className="bot-profile__row-name">{skill.name}</span>
                <span className="bot-profile__row-body">
                  {skill.description === '' ? '暂无说明' : skill.description}
                </span>
              </div>
            ))}
            {profile !== null && skills.length === 0 ? (
              <div className="bot-profile__placeholder">这个 Bot 没有额外技能。</div>
            ) : null}
          </section>

          <section className="bot-profile__section" aria-labelledby="profile-tools">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-tools">
                数据与工具
              </h2>
              <span className="bot-profile__section-meta">
                {profile === null ? '正在读取…' : `${tools.length} 组 · 全部只读数据`}
              </span>
            </div>
            {tools.map((server) => {
              const info = mcpInfo(server);
              return (
                <div className="bot-profile__row" key={server}>
                  <span className="bot-profile__row-name">{info.name}</span>
                  <span className="bot-profile__row-body">{info.description}</span>
                </div>
              );
            })}
            {profile !== null && tools.length === 0 ? (
              <div className="bot-profile__placeholder">没有外接数据与工具。</div>
            ) : null}
          </section>

          <section className="bot-profile__section" aria-labelledby="profile-permissions">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-permissions">
                权限与边界
              </h2>
            </div>
            <dl className="bot-profile__permissions">
              {profile === null
                ? null
                : permissionsFor(profile).map((row) => (
                    <div className="bot-profile__permission" key={row.label}>
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
            </dl>
          </section>
        </div>

        <div className="bot-profile__column">
          <section className="bot-profile__section" aria-labelledby="profile-routines">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-routines">
                主动任务
              </h2>
              <span className="bot-profile__section-meta">
                {routines.filter((routine) => routine.enabled).length} 个已启用
              </span>
            </div>
            {routineNotice === null ? null : (
              <div className="bot-profile__notice" role="status">
                {routineNotice}
              </div>
            )}
            {routines.length === 0 ? (
              <div className="bot-profile__placeholder">
                这个 Bot 目前没有主动任务。可以在对话里说“每个交易日 8:30 给我盘前简报”，它会创建并在这里列出，你可以随时关掉。
              </div>
            ) : (
              <ul className="bot-profile__routines">
                {routines.map((routine) => (
                  <li className="bot-profile__routine" key={routine.id}>
                    <div className="bot-profile__routine-head">
                      <span className="bot-profile__routine-title">{routine.title}</span>
                      <span className="bot-profile__routine-source">
                        {routine.source === 'manifest' ? '内置' : '你创建的'}
                      </span>
                      <span
                        className={`bot-profile__routine-state${
                          routine.enabled ? ' bot-profile__routine-state--on' : ''
                        }`}
                      >
                        {routine.enabled ? '已启用' : '已暂停'}
                      </span>
                    </div>
                    <div className="bot-profile__routine-schedule">{routine.scheduleText}</div>
                    <div className="bot-profile__routine-meta">
                      上次运行 {routine.lastRunAt === null ? '—' : formatRoutineTime(routine.lastRunAt)}
                      {' · '}
                      下次运行 {routine.nextRunAt === null ? '—' : formatRoutineTime(routine.nextRunAt)}
                    </div>
                    <div className="bot-profile__routine-actions">
                      <label>
                        启用任务
                        <input type="checkbox" role="switch" checked={routine.enabled}
                          aria-label={`启用任务：${routine.title}`} disabled={routineBusy === routine.id}
                          onChange={() => toggleRoutine(routine)} />
                      </label>
                      <button
                        type="button"
                        className="bot-profile__button bot-profile__button--primary"
                        disabled={routineBusy === routine.id}
                        onClick={() => runRoutineNow(routine)}
                      >
                        立即运行
                      </button>
                      {routine.source === 'user' ? (
                        <button
                          type="button"
                          className="bot-profile__button bot-profile__button--danger"
                          disabled={routineBusy === routine.id}
                          onClick={() => removeRoutine(routine)}
                        >
                          删除
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="bot-profile__section" aria-labelledby="profile-watches">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-watches">
                盯盘任务
              </h2>
              <span className="bot-profile__section-meta">
                {(profile?.watches ?? []).filter((watch) => watch.status === 'active').length} 条生效中
              </span>
            </div>
            {watchNotice === null ? null : (
              <div className="bot-profile__notice" role="status">
                {watchNotice}
              </div>
            )}
            {profileWatches.length === 0 ? (
              <div className="bot-profile__placeholder">
                还没有盯盘。直接对 bot 说“跌破 X 叫我”“站上 Y 帮我看看”。
              </div>
            ) : (
              <ul className="bot-profile__watches">
                {profileWatches.map((watch) => (
                  <ProfileWatchItem
                    key={watch.id}
                    watch={watch}
                    busy={watchBusy === watch.id}
                    onCancel={async (id) => {
                      setWatchBusy(id);
                      setWatchNotice(null);
                      try {
                        await cancelWatch(id);
                        setWatchNotice('已删除这条盯盘');
                        setReloadToken((value) => value + 1);
                      } catch (cause) {
                        setWatchNotice(cause instanceof Error ? cause.message : '删除失败');
                      } finally {
                        setWatchBusy(null);
                      }
                    }}
                  />
                ))}
              </ul>
            )}
          </section>

          <section className="bot-profile__section" aria-labelledby="profile-memory">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-memory">
                它记住了什么
              </h2>
              <span className="bot-profile__section-meta">
                {memoryCount} 条 · 你可以改或删；带日期的观点到期会标出
              </span>
            </div>
            {memoryNotice === null ? null : (
              <div className="bot-profile__memory-notice" role="status">
                {memoryNotice}
              </div>
            )}
            {memoryItems.length === 0 ? (
              <div className="bot-profile__placeholder">
                还没有记忆。你明确要求它记住、或它从对话里提炼出长期偏好后，会出现在这里。
              </div>
            ) : (
              <>
                <ul className="bot-profile__memories">
                  {visibleMemories.map((item) => (
                    <li
                      className={`bot-profile__memory${item.expired ? ' bot-profile__memory--expired' : ''}`}
                      key={item.slug}
                    >
                      <div className="bot-profile__memory-head">
                        <span className="bot-profile__memory-kind">
                          {MEMORY_KIND_LABELS[item.kind]}
                        </span>
                        <span className="bot-profile__memory-title">{item.title}</span>
                      </div>
                      <div className="bot-profile__memory-meta">
                        写于 {item.writtenAt.slice(0, 10)}
                        {item.expiresAt === null
                          ? ' · 无到期'
                          : ` · 到期 ${formatShanghaiDate(item.expiresAt)}`}
                        {item.expired ? (
                          <span className="bot-profile__memory-expired"> · 已过期</span>
                        ) : null}
                      </div>
                      {editingMemorySlug === item.slug && memoryDraft !== null ? (
                        <form
                          className="bot-profile__memory-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            handleMemorySave();
                          }}
                        >
                          <label>
                            标题
                            <input
                              value={memoryDraft.title}
                              maxLength={80}
                              onChange={(event) =>
                                setMemoryDraft((current) =>
                                  current === null
                                    ? current
                                    : { ...current, title: event.target.value }
                                )
                              }
                            />
                          </label>
                          <label>
                            正文
                            <textarea
                              value={memoryDraft.body}
                              maxLength={800}
                              rows={3}
                              onChange={(event) =>
                                setMemoryDraft((current) =>
                                  current === null
                                    ? current
                                    : { ...current, body: event.target.value }
                                )
                              }
                            />
                          </label>
                          <label>
                            类型
                            <select
                              value={memoryDraft.kind}
                              onChange={(event) =>
                                setMemoryDraft((current) =>
                                  current === null
                                    ? current
                                    : { ...current, kind: event.target.value as MemoryKind }
                                )
                              }
                            >
                              <option value="preference">偏好</option>
                              <option value="view">观点</option>
                              <option value="fact">事实</option>
                              <option value="note">笔记</option>
                            </select>
                          </label>
                          <label>
                            到期日
                            <input
                              type="date"
                              value={memoryDraft.expiresAt}
                              onChange={(event) =>
                                setMemoryDraft((current) =>
                                  current === null
                                    ? current
                                    : { ...current, expiresAt: event.target.value }
                                )
                              }
                            />
                          </label>
                          <div className="bot-profile__memory-actions">
                            <button
                              type="submit"
                              className="bot-profile__button bot-profile__button--primary"
                              disabled={memoryBusy}
                            >
                              保存
                            </button>
                            <button
                              type="button"
                              className="bot-profile__button"
                              onClick={() => {
                                setEditingMemorySlug(null);
                                setMemoryDraft(null);
                              }}
                            >
                              取消
                            </button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <p className="bot-profile__memory-body">{item.body}</p>
                          {deletingMemorySlug === item.slug ? (
                            <div className="bot-profile__memory-actions">
                              <span>确定删除「{item.title}」？</span>
                              <button
                                type="button"
                                className="bot-profile__button bot-profile__button--danger"
                                disabled={memoryBusy}
                                onClick={() => handleMemoryDelete(item.slug)}
                              >
                                确认删除
                              </button>
                              <button
                                type="button"
                                className="bot-profile__button"
                                onClick={() => setDeletingMemorySlug(null)}
                              >
                                取消
                              </button>
                            </div>
                          ) : (
                            <div className="bot-profile__memory-actions">
                              <button
                                type="button"
                                className="bot-profile__button"
                                aria-label={`修改记忆 ${item.title}`}
                                onClick={() => handleMemoryEdit(item)}
                              >
                                改
                              </button>
                              <button
                                type="button"
                                className="bot-profile__button"
                                aria-label={`删除记忆 ${item.title}`}
                                onClick={() => {
                                  setEditingMemorySlug(null);
                                  setMemoryDraft(null);
                                  setDeletingMemorySlug(item.slug);
                                }}
                              >
                                删
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="bot-profile__memory-footer">
                  {memoryCount > visibleMemories.length || showAllMemories ? (
                    <button
                      type="button"
                      className="bot-profile__button"
                      onClick={() => setShowAllMemories((current) => !current)}
                    >
                      {showAllMemories ? '收起' : `查看全部 ${memoryCount} 条`}
                    </button>
                  ) : null}
                  <span className="bot-profile__section-meta">
                    共 {memoryCount}/{memoryLimit} 条
                  </span>
                </div>
              </>
            )}
          </section>

          <section className="bot-profile__section" aria-labelledby="profile-workspace">
            <div className="bot-profile__section-head">
              <h2 className="bot-profile__section-title" id="profile-workspace">
                工作目录
              </h2>
              <span
                className="bot-profile__path"
                title={profile?.workspace.path ?? ''}
              >
                {profile === null ? '—' : shortenWorkspacePath(profile.workspace.path)}
              </span>
            </div>
            <div className="bot-profile__workspace-actions">
              <button
                type="button"
                className="bot-profile__button"
                onClick={handleReveal}
              >
                在访达中打开
              </button>
              <button
                type="button"
                className="bot-profile__button"
                onClick={() => onOpenWorkspaceMap?.(bot.id)}
              >
                打开目录地图
              </button>
              <span className="bot-profile__section-meta">
                {profile === null
                  ? ''
                  : `共 ${profile.workspace.fileCount} 个文件 · ${formatFileSize(
                      profile.workspace.totalBytes
                    )}`}
              </span>
            </div>
            {revealNotice !== null ? (
              <div className="bot-profile__notice" role="status">
                {revealNotice}
              </div>
            ) : null}
            {filesError !== null ? (
              <div className="bot-profile__placeholder" role="status">
                {filesError}
              </div>
            ) : files.length === 0 ? (
              <div className="bot-profile__placeholder">
                {profile === null && loading ? '正在读取…' : '这个工作目录还没有文件。'}
              </div>
            ) : (
              <div className="bot-profile__workspace-groups">
                {workspaceGroups.map((group) => {
                  const open = groupOpen(group.key);
                  return (
                    <section className="bot-profile__workspace-group" key={group.key}>
                      <button
                        type="button"
                        className="bot-profile__workspace-group-head"
                        aria-expanded={open}
                        onClick={() => toggleGroup(group.key)}
                      >
                        <span className="bot-profile__workspace-caret" aria-hidden="true">
                          {open ? '▾' : '▸'}
                        </span>
                        <span className="bot-profile__workspace-group-name">{group.label}</span>
                        <span className="bot-profile__workspace-group-meta">
                          {group.files.length} 个文件 · {formatFileSize(totalBytesOf(group.files))}
                        </span>
                      </button>
                      {open ? (
                        group.key === 'reports' ? (
                          group.topics.map((topic) => (
                            <div className="bot-profile__workspace-topic" key={topic.name}>
                              <div className="bot-profile__workspace-topic-name">
                                <span>{topic.name}</span>
                                <span>{topic.files.length}</span>
                              </div>
                              <ul className="bot-profile__files">
                                {topic.files.map((file) => renderWorkspaceFile(file))}
                              </ul>
                            </div>
                          ))
                        ) : (
                          <ul className="bot-profile__files">
                            {group.files.map((file) => renderWorkspaceFile(file))}
                          </ul>
                        )
                      ) : null}
                    </section>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </div>

      {editing && profile !== null ? (
        <AvatarEditDialog
          bot={bot}
          defaults={profile.defaults}
          onClose={() => setEditing(false)}
          onSave={handleSave}
          onSaved={handleSaved}
        />
      ) : null}
    </div>
  );
}


const WATCH_STATUS_TEXT: Record<WatchDto['status'], string> = {
  active: '生效中',
  triggered: '已触发',
  expired: '已过期',
  cancelled: '已删除'
};

const WATCH_EVENT_TEXT: Record<string, string> = {
  created: '创建',
  updated: '修改',
  cancelled: '取消',
  triggered: '触发',
  expired: '到期',
  sync_error: '同步异常'
};

function ProfileWatchItem({
  watch,
  busy,
  onCancel
}: {
  watch: WatchDto;
  busy: boolean;
  onCancel: (id: string) => Promise<void>;
}): ReactElement {
  const [history, setHistory] = useState<WatchHistoryDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = (): void => {
    if (history !== null) return;
    void fetchWatch(watch.id)
      .then((detail) => setHistory(detail.history))
      .catch(() => setError('变更历史没有加载出来'));
  };

  return (
    <li className={`bot-profile__watch bot-profile__watch--${watch.status}`}>
      <details onToggle={(event) => {
        if ((event.currentTarget as HTMLDetailsElement).open) loadHistory();
      }}>
        <summary>
          <span className="bot-profile__watch-condition">{watch.conditionText}</span>
          <span className={`bot-profile__watch-state bot-profile__watch-state--${watch.status}`}>
            {WATCH_STATUS_TEXT[watch.status]}
          </span>
        </summary>
        <div className="bot-profile__watch-meta">
          <span>至 {formatShanghaiDate(watch.expiresAt)}</span>
          <span>最近价 {watch.lastPrice ?? '—'}</span>
          <span>引擎状态 {watch.engineState ?? '—'}</span>
          {watch.triggeredAt === null ? null : <span>最近触发 {formatRoutineTime(watch.triggeredAt)}</span>}
          {watch.triggerTaskId === null ? null : <span>触发任务 {watch.triggerTaskId.slice(0, 8)}</span>}
        </div>
        {watch.syncError === null ? null : (
          <div className="bot-profile__watch-sync">
            {watch.syncError === 'engine_unreachable'
              ? '盯盘引擎没有启动，启动后自动生效'
              : `同步异常：${watch.syncError}`}
          </div>
        )}
        {error === null ? null : <div className="bot-profile__watch-sync">{error}</div>}
        {history === null ? (
          <div className="bot-profile__watch-history-empty">展开后加载变更历史…</div>
        ) : (
          <ul className="bot-profile__watch-history">
            {history.map((event) => (
              <li key={event.id}>
                <span>{WATCH_EVENT_TEXT[event.kind] ?? event.kind}</span>
                <span>{formatRoutineTime(event.createdAt)}</span>
                {event.detail === null ? null : <span>{event.detail}</span>}
              </li>
            ))}
          </ul>
        )}
        {watch.status === 'active' ? (
          <button
            type="button"
            className="bot-profile__button bot-profile__button--danger"
            disabled={busy}
            onClick={() => void onCancel(watch.id)}
          >
            {busy ? '删除中…' : '删除盯盘'}
          </button>
        ) : null}
      </details>
    </li>
  );
}
