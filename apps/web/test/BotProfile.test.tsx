import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  BotMemoryItem,
  BotProfile as BotProfileDto,
  BotSummary,
  WorkspaceFileList
} from '@chives/server/protocol';
import { BotProfile } from '../src/components/BotProfile';
import { jsonResponse, makeBot } from './testUtils';

const expert = makeBot({
  name: '投资专家',
  role: '默认入口，会把任务分给合适的同事',
  skills: ['idea-generation', 'morning-note'],
  mcp: ['cn_data', 'paper_broker', 'portfolio', 'chives'],
  canDelegateTo: ['equity-analyst'],
  workspacePath: '/Users/analyst/Chives/bots/expert/workspace'
});

function profileFor(
  bot: BotSummary,
  overrides: Partial<BotProfileDto> = {}
): BotProfileDto {
  return {
    bot,
    role: bot.role,
    personaSummary: '你是面向 A 股的个人投资研究助手。',
    skills: [
      { name: 'idea-generation', description: 'A 股选股漏斗：先把范围缩到可研究的候选。' },
      { name: 'morning-note', description: '' }
    ],
    mcp: [...bot.mcp],
    tools: { code: 'sandboxed', write: 'workspace-only' },
    canDelegateTo: [{ id: 'equity-analyst', name: '个股分析师' }],
    routines: [],
    memoryPolicy: { user: 'read', bot: 'read-write' },
    tradingGuard: true,
    model: 'deepseek-v4.1-flash',
    workspace: {
      path: '/Users/analyst/Chives/bots/expert/workspace',
      fileCount: 3,
      totalBytes: 2048
    },
    recentDeliverables: [
      {
        id: 'd1',
        taskId: 't1',
        botId: bot.id,
        path: 'reports/report.md',
        kind: 'markdown',
        size: 2048,
        createdAt: '2026-11-16T10:00:00.000Z'
      }
    ],
    memory: { count: 0, limit: 200, items: [], available: true, updatedAt: null },
    defaults: { name: '投资专家', avatar: { emblem: 'crown', tone: 'gold' } },
    ...overrides
  };
}

function filesFor(): WorkspaceFileList {
  return {
    dir: '',
    files: [
      {
        path: 'reports/report.md',
        name: 'report.md',
        size: 2048,
        modifiedAt: '2026-11-16T10:00:00.000Z',
        kind: 'markdown',
        deliverableId: 'd1'
      },
      {
        path: 'notes.txt',
        name: 'notes.txt',
        size: 12,
        modifiedAt: '2026-11-15T10:00:00.000Z',
        kind: 'code',
        deliverableId: null
      }
    ]
  };
}

function stubFetch(profile: BotProfileDto, files = filesFor()): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === `/api/bots/${profile.bot.id}/profile`) return jsonResponse(profile);
    if (url.startsWith(`/api/bots/${profile.bot.id}/files`)) return jsonResponse(files);
    if (url === `/api/bots/${profile.bot.id}/reveal` && init?.method === 'POST') {
      return jsonResponse({ ok: true });
    }
    if (url.startsWith('/api/routines/')) {
      const id = decodeURIComponent(url.slice('/api/routines/'.length));
      const routine = profile.routines.find((entry) => entry.id === id);
      if (routine !== undefined) {
        const body =
          typeof init?.body === 'string'
            ? (JSON.parse(init.body) as { enabled?: boolean })
            : {};
        return jsonResponse({ ...routine, enabled: body.enabled ?? routine.enabled });
      }
    }
    return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BotProfile', () => {
  it('renders skills, tools, permissions, workspace, memory, and routines', async () => {
    stubFetch(profileFor(expert));
    const onOpenDeliverable = vi.fn();
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={onOpenDeliverable}
        activeDeliverableId={null}
      />
    );

    expect(await screen.findByText(/A 股选股漏斗/)).toBeTruthy();
    expect(screen.getByText('idea-generation')).toBeTruthy();
    expect(screen.getByText('暂无说明')).toBeTruthy();
    expect(screen.getByText('A 股行情与财务')).toBeTruthy();
    expect(screen.queryByText('chives')).toBeNull();

    expect(screen.getByText('个股分析师')).toBeTruthy();
    expect(screen.getByText('只能写自己的工作目录')).toBeTruthy();
    expect(screen.getByText('只有模拟盘，每次都要你批准')).toBeTruthy();
    expect(screen.getByText('只在你问到时读取')).toBeTruthy();
    expect(screen.getByText('deepseek-v4.1-flash · 运行在 dsh 上')).toBeTruthy();

    expect(screen.getByText('~/Chives/bots/expert/workspace')).toBeTruthy();
    expect(screen.getByText('共 3 个文件 · 2.0 KB')).toBeTruthy();
    expect(screen.getByText('report.md')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /未归档/ }));
    expect(screen.getByText('notes.txt')).toBeTruthy();
    expect(screen.getByText(/还没有记忆/)).toBeTruthy();
    expect(screen.getByText(/这个 Bot 目前没有主动任务/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /report\.md/ }));
    expect(onOpenDeliverable).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'd1', path: 'reports/report.md' }),
      expect.any(HTMLElement)
    );
    expect(screen.queryByRole('button', { name: /notes\.txt/ })).toBeNull();
  });

  it('groups workspace files, collapses scratch and unarchived, and opens the map', async () => {
    const files: WorkspaceFileList = {
      dir: '',
      files: [
        {
          path: 'reports/000528-柳工/20261117_估值.md',
          name: '20261117_估值.md',
          size: 2048,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'markdown',
          deliverableId: 'd1'
        },
        {
          path: 'charts/000528-柳工/pe.png',
          name: 'pe.png',
          size: 1024,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'image',
          deliverableId: null
        },
        {
          path: 'data/000528-柳工/q.csv',
          name: 'q.csv',
          size: 32,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'csv',
          deliverableId: null
        },
        {
          path: 'scripts/calc.py',
          name: 'calc.py',
          size: 64,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'code',
          deliverableId: null
        },
        {
          path: 'scratch/tmp.json',
          name: 'tmp.json',
          size: 8,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'json',
          deliverableId: null
        },
        {
          path: 'old_dir/legacy.md',
          name: 'legacy.md',
          size: 16,
          modifiedAt: '2026-11-17T10:00:00.000Z',
          kind: 'markdown',
          deliverableId: null
        }
      ]
    };
    stubFetch(profileFor(expert), files);
    const onOpenWorkspaceMap = vi.fn();
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        onOpenWorkspaceMap={onOpenWorkspaceMap}
        activeDeliverableId={null}
      />
    );

    const reports = await screen.findByRole('button', { name: /报告/ });
    expect(reports.textContent).toContain('1 个文件 · 2.0 KB');
    expect(await screen.findByText('20261117_估值.md')).toBeTruthy();
    expect(screen.getAllByText('000528-柳工').length).toBeGreaterThan(0);
    expect(screen.getByText('pe.png')).toBeTruthy();
    expect(screen.queryByText('tmp.json')).toBeNull();
    expect(screen.queryByText('legacy.md')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /临时/ }));
    expect(screen.getByText('tmp.json')).toBeTruthy();
    expect(screen.getByRole('button', { name: /未归档/ }).textContent).toContain('1 个文件 · 16 B');
    fireEvent.click(screen.getByRole('button', { name: /未归档/ }));
    expect(screen.getByText('legacy.md')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '打开目录地图' }));
    expect(onOpenWorkspaceMap).toHaveBeenCalledWith('expert');
  });

  it('lists active routines and toggles their enabled state', async () => {
    const routine = {
      id: 'manifest:expert:premarket-brief',
      botId: 'expert',
      source: 'manifest' as const,
      title: '盘前简报',
      schedule: { cron: '30 8 * * 1-5', tz: 'Asia/Shanghai' },
      scheduleText: '工作日 08:30（北京时间）',
      prompt: '按 morning-note 技能出盘前简报',
      promptSummary: '按 morning-note 技能出盘前简报',
      tradingDaysOnly: true,
      enabled: true,
      createdAt: '2026-11-16T00:00:00.000Z',
      lastRunAt: null,
      nextRunAt: '2026-11-17T00:30:00.000Z'
    };
    const fetchMock = stubFetch(profileFor(expert, { routines: [routine] }));
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );

    expect(await screen.findByText('盘前简报')).toBeTruthy();
    expect(screen.getByText('工作日 08:30（北京时间）')).toBeTruthy();
    expect(screen.getByText('1 个已启用')).toBeTruthy();

    fireEvent.click(screen.getByRole('switch', { name: '启用任务：盘前简报', checked: true }));
    await waitFor(() => expect(screen.getByRole('switch', { name: '启用任务：盘前简报', checked: false })).toBeTruthy());
    const patch = fetchMock.mock.calls.find(([input]) => String(input).includes('/api/routines/'));
    expect(patch).toBeDefined();
    expect(patch?.[1]).toMatchObject({ method: 'PATCH' });
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ enabled: false });
  });

  it('generates the no-paper-broker and no-portfolio boundary rows', async () => {
    const dataPrep = makeBot({
      id: 'data-prep',
      name: '数据员',
      role: '批量取数',
      skills: [],
      mcp: ['cn_data'],
      canDelegateTo: [],
      background: true
    });
    stubFetch(
      profileFor(dataPrep, {
        role: '批量取数',
        skills: [],
        mcp: ['cn_data'],
        canDelegateTo: [],
        tools: { code: 'sandboxed', write: 'workspace-only' },
        tradingGuard: false,
        recentDeliverables: [],
        workspace: {
          path: '/Users/analyst/Chives/bots/data-prep/workspace',
          fileCount: 0,
          totalBytes: 0
        }
      }),
      { dir: '', files: [] }
    );
    render(
      <BotProfile
        bot={dataPrep}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );

    expect(await screen.findByText('这个 Bot 没有额外技能。')).toBeTruthy();
    expect(screen.getByText('不能下单')).toBeTruthy();
    expect(screen.getByText('读不到')).toBeTruthy();
    expect(screen.getByText('无')).toBeTruthy();
    expect(screen.getByText('这个工作目录还没有文件。')).toBeTruthy();
  });

  it('reveals the workspace directory and reports the result', async () => {
    stubFetch(profileFor(expert));
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );
    await screen.findByText('共 3 个文件 · 2.0 KB');
    fireEvent.click(screen.getByRole('button', { name: '在访达中打开' }));
    expect(await screen.findByText('已在访达中打开')).toBeTruthy();
  });

  it('shows a load error with retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ error: { code: 'boom', message: '服务错误' } }, 500))
    );
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );
    expect((await screen.findByRole('alert')).textContent).toContain('服务错误');
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
  });

  it('opens the editor and applies a saved bot summary', async () => {
    const saved = { ...expert, name: '阿金', avatar: { emblem: 'lamp', tone: 'gold' } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/bots/expert/profile') return jsonResponse(profileFor(expert));
      if (url.startsWith('/api/bots/expert/files')) return jsonResponse(filesFor());
      if (url === '/api/bots/expert' && init?.method === 'PATCH') return jsonResponse(saved);
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onBotUpdated = vi.fn();
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={onBotUpdated}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );
    await screen.findByText('共 3 个文件 · 2.0 KB');
    fireEvent.click(screen.getByRole('button', { name: '编辑头像与称呼' }));
    expect(await screen.findByRole('dialog', { name: '编辑头像与称呼' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('称呼'), { target: { value: '阿金' } });
    fireEvent.click(screen.getByRole('radio', { name: '明灯' }));
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/bots/expert',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({ displayName: '阿金', avatar: { emblem: 'lamp', tone: 'gold' } })
        })
      );
    });
    await waitFor(() => expect(onBotUpdated).toHaveBeenCalledWith(saved));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('BotProfile memory', () => {
  const memoryItems: BotMemoryItem[] = [
    {
      slug: 'm-pref',
      title: '长期偏好',
      description: '高股息',
      kind: 'preference',
      writtenAt: '2026-01-01T00:00:00.000Z',
      expiresAt: null,
      expired: false,
      source: 'capture',
      sourceTaskId: 't1',
      body: '偏好高股息'
    },
    {
      slug: 'm-view',
      title: '旧观点',
      description: '券商',
      kind: 'view',
      writtenAt: '2026-02-01T00:00:00.000Z',
      expiresAt: '2026-03-01T00:00:00.000Z',
      expired: true,
      source: 'user',
      sourceTaskId: null,
      body: '看好券商'
    }
  ];

  it('lists memories with dates and expired marks, then edits and deletes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/bots/expert/profile') {
        return jsonResponse(
          profileFor(expert, {
            memory: {
              count: 2,
              limit: 200,
              items: memoryItems,
              available: true,
              updatedAt: '2026-11-16T10:00:00.000Z'
            }
          })
        );
      }
      if (url.startsWith('/api/bots/expert/files')) return jsonResponse(filesFor());
      if (url === '/api/bots/expert/memories/m-view') {
        if (init?.method === 'DELETE') return jsonResponse({ ok: true, count: 1 });
      }
      if (url === '/api/bots/expert/memories/m-pref' && init?.method === 'PUT') {
        return jsonResponse({
          ok: true,
          count: 2,
          memory: {
            ...memoryItems[0],
            kind: 'view',
            body: '现在更看重成长',
            expiresAt: '2027-11-16T00:00:00.000Z'
          }
        });
      }
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );

    expect(await screen.findByText('长期偏好')).toBeTruthy();
    expect(screen.getByText('2 条 · 你可以改或删；带日期的观点到期会标出')).toBeTruthy();
    expect(screen.getByText('写于 2026-01-01 · 无到期')).toBeTruthy();
    expect(screen.getByText(/写于 2026-02-01 · 到期 2026-03-01/)).toBeTruthy();
    expect(screen.getByText(/已过期/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '修改记忆 长期偏好' }));
    fireEvent.change(screen.getByLabelText('正文'), { target: { value: '现在更看重成长' } });
    fireEvent.change(screen.getByLabelText('类型'), { target: { value: 'view' } });
    fireEvent.change(screen.getByLabelText('到期日'), { target: { value: '2027-11-16' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/bots/expert/memories/m-pref',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            title: '长期偏好',
            body: '现在更看重成长',
            kind: 'view',
            expiresAt: '2027-11-16T00:00:00.000Z'
          })
        })
      );
    });
    expect(await screen.findByText('现在更看重成长')).toBeTruthy();
    expect(await screen.findByText('已保存，下一轮对话生效')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '删除记忆 旧观点' }));
    expect(screen.getByText('确定删除「旧观点」？')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/bots/expert/memories/m-view',
        expect.objectContaining({ method: 'DELETE' })
      );
    });
    expect(screen.queryByText('旧观点')).toBeNull();
  });

  it('shows five memories and expands to all', async () => {
    const many: BotMemoryItem[] = Array.from({ length: 6 }, (_, index) => ({
      slug: `m-${index}`,
      title: `记忆 ${index}`,
      description: '',
      kind: 'note',
      writtenAt: '2026-01-01T00:00:00.000Z',
      expiresAt: null,
      expired: false,
      source: 'tool',
      sourceTaskId: 't1',
      body: `正文 ${index}`
    }));
    stubFetch(
      profileFor(expert, {
        memory: { count: 6, limit: 200, items: many, available: true, updatedAt: null }
      })
    );
    render(
      <BotProfile
        bot={expert}
        onOpenConversation={() => {}}
        onBotUpdated={() => {}}
        onOpenDeliverable={() => {}}
        activeDeliverableId={null}
      />
    );
    expect(await screen.findByText('记忆 4')).toBeTruthy();
    expect(screen.queryByText('记忆 5')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '查看全部 6 条' }));
    expect(screen.getByText('记忆 5')).toBeTruthy();
    expect(screen.getByRole('button', { name: '收起' })).toBeTruthy();
  });
});
