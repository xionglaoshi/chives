import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  BotProfile,
  MessageDto,
  TaskDto,
  TimelinePage
} from '@chives/server/protocol';
import { App } from '../src/App';
import { emptyTimeline, jsonResponse, makeBot, MockEventSource, resetEventSources } from './testUtils';

const expertBot = makeBot();
const bots = [
  expertBot,
  makeBot({ id: 'research', name: '研究员', background: true, avatar: { emblem: 'bars', tone: 'ink' } })
];

function expertProfile(): BotProfile {
  return {
    bot: expertBot,
    role: expertBot.role,
    personaSummary: '你是面向 A 股的个人投资研究助手。',
    skills: [],
    mcp: [],
    tools: { code: 'sandboxed', write: 'workspace-only' },
    canDelegateTo: [],
    routines: [],
    memoryPolicy: { user: 'read', bot: 'read-write' },
    tradingGuard: false,
    model: 'deepseek-v4.1-flash',
    workspace: { path: '/Users/me/Chives/bots/expert/workspace', fileCount: 0, totalBytes: 0 },
    recentDeliverables: [],
    memory: { count: 0, limit: 200, items: [], available: true, updatedAt: null },
    defaults: { name: '投资专家', avatar: expertBot.avatar }
  };
}

function pageWithMessages(): TimelinePage {
  const task: TaskDto = {
    id: 't1',
    botId: 'expert',
    title: '已有任务',
    status: 'done',
    harnessSessionId: null,
    startedAt: '2026-11-16T09:58:00.000Z',
    endedAt: '2026-11-16T10:00:00.000Z',
    parentTaskId: null
  };
  const messages: MessageDto[] = [
    {
      id: 'm1',
      botId: 'expert',
      taskId: 't1',
      role: 'user',
      kind: 'text',
      content: '看下茅台',
      meta: null,
      createdAt: '2026-11-16T09:58:00.000Z',
      seq: 1
    },
    {
      id: 'm2',
      botId: 'expert',
      taskId: 't1',
      role: 'bot',
      kind: 'text',
      content: '已有的回复',
      meta: null,
      createdAt: '2026-11-16T10:00:00.000Z',
      seq: 2
    }
  ];
  return { messages, tasks: [task], toolEvents: [], hasMore: false, nextBeforeSeq: null };
}

function createFetch(timeline: TimelinePage = emptyTimeline()) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/bots') return jsonResponse(bots);
    if (url === '/api/bots/expert/profile') return jsonResponse(expertProfile());
    if (url.startsWith('/api/bots/expert/files')) {
      return jsonResponse({ dir: '', files: [] });
    }
    if (url.startsWith('/api/bots/research/timeline')) return jsonResponse(emptyTimeline());
    if (url.startsWith('/api/bots/expert/timeline')) return jsonResponse(timeline);
    if (url === '/api/bots/expert/messages' && init?.method === 'POST') {
      return jsonResponse({ messageId: 'm1', taskId: 't1' }, 202);
    }
    if (url === '/api/bots/expert/cancel' && init?.method === 'POST') {
      return jsonResponse({ taskId: 't1' }, 202);
    }
    return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
  });
}

beforeEach(() => {
  resetEventSources();
  vi.stubGlobal('EventSource', MockEventSource);
  window.history.replaceState(null, '', '/#/bot/expert');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('App', () => {
  it('shows the first-run page for an empty timeline and sends a starter', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByRole('heading', { name: '今天想盯哪只股票？' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /看看我的持仓风险/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/bots/expert/messages',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '看看我的持仓风险' })
        })
      );
    });
    expect(await screen.findByText('看看我的持仓风险')).toBeTruthy();
  });

  it('renders an existing timeline instead of the first-run page', async () => {
    vi.stubGlobal('fetch', createFetch(pageWithMessages()));
    render(<App />);

    expect(await screen.findByText('已有的回复')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '今天想盯哪只股票？' })).toBeNull();
  });

  it('routes SSE events by bot id without reconnecting when switching bots', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByRole('heading', { name: '今天想盯哪只股票？' });

    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];
    expect(source).toBeDefined();

    act(() => {
      source?.emit('message.created', {
        type: 'message.created',
        id: 7,
        at: '2026-11-16T10:00:00.000Z',
        botId: 'expert',
        taskId: null,
        message: {
          id: 'm9',
          botId: 'expert',
          taskId: null,
          role: 'bot',
          kind: 'text',
          content: '来自 SSE 的回复',
          meta: null,
          createdAt: '2026-11-16T10:00:00.000Z',
          seq: 9
        }
      });
    });
    expect(await screen.findByText('来自 SSE 的回复')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^研究员，/ }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/bots/research/timeline'))).toBe(true);
    });
    expect(MockEventSource.instances).toHaveLength(1);
  });


  it('keeps the text and explains a 409 instead of adding a failed bubble', async () => {
    const base = createFetch();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/bots/expert/messages' && init?.method === 'POST') {
        return jsonResponse({ error: { code: 'bot_busy', message: 'bot is busy' } }, 409);
      }
      return base(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByRole('heading', { name: '今天想盯哪只股票？' });

    fireEvent.click(screen.getByRole('button', { name: /看看我的持仓风险/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('上一个任务还在进行');
    const input = screen.getByLabelText('给 Bot 发消息') as HTMLTextAreaElement;
    expect(input.value).toBe('看看我的持仓风险');
  });

  it('shows a retry action when posting a message fails', async () => {
    const base = createFetch();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/bots/expert/messages' && init?.method === 'POST') {
        throw new Error('offline');
      }
      return base(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByRole('heading', { name: '今天想盯哪只股票？' });
    fireEvent.click(screen.getByRole('button', { name: /看看我的持仓风险/ }));
    expect(await screen.findByText('发送失败')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
  });

  it('shows a retrying banner when the server is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    render(<App />);
    expect(await screen.findByText(/连不上 Chives 服务/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '立即重试' })).toBeTruthy();
  });

  it('routes #/bots, #/bot/:id/profile, and the conversation, with a sidebar overview entry', async () => {
    vi.stubGlobal('fetch', createFetch());
    window.history.replaceState(null, '', '#/bots');
    render(<App />);

    expect(await screen.findByRole('heading', { name: /人才市场/ })).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: '查看资料' })[0] as HTMLElement);
    await waitFor(() => expect(window.location.hash).toBe('#/bot/expert/profile'));
    expect(await screen.findByRole('heading', { name: '投资专家' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '去对话' }));
    await waitFor(() => expect(window.location.hash).toBe('#/bot/expert'));
    expect(await screen.findByRole('heading', { name: '今天想盯哪只股票？' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /人才市场/ }));
    await waitFor(() => expect(window.location.hash).toBe('#/bots'));
    expect(await screen.findByRole('heading', { name: /人才市场/ })).toBeTruthy();
  });


  it('opens the search layer with / and shows a continuation hint after reopen', async () => {
    const base = createFetch(pageWithMessages());
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/bots/expert/search')) {
        return jsonResponse({
          query: '茅台',
          totalGroups: 1,
          totalHits: 1,
          groups: [
            {
              taskId: 't1',
              botId: 'expert',
              botName: '投资专家',
              title: '已有任务',
              lastActivityAt: '2026-11-16T10:00:00.000Z',
              startedAt: '2026-11-16T09:58:00.000Z',
              endedAt: '2026-11-16T10:00:00.000Z',
              steps: 3,
              summary: null,
              snippets: [],
              hitCount: 1,
              deliverables: [],
              taskIds: ['t1'],
              locateMessageId: 'm1'
            }
          ]
        });
      }
      if (url === '/api/tasks/t1/reopen' && init?.method === 'POST') {
        return jsonResponse({
          id: 't1',
          botId: 'expert',
          title: '已有任务',
          status: 'done',
          harnessSessionId: null,
          startedAt: '2026-11-16T09:58:00.000Z',
          endedAt: '2026-11-16T10:00:00.000Z',
          parentTaskId: null,
          closedAt: null
        });
      }
      if (url === '/api/tasks/t1/reopen/cancel' && init?.method === 'POST') {
        return jsonResponse({
          id: 't1',
          botId: 'expert',
          title: '已有任务',
          status: 'done',
          harnessSessionId: null,
          startedAt: '2026-11-16T09:58:00.000Z',
          endedAt: '2026-11-16T10:00:00.000Z',
          parentTaskId: null,
          closedAt: '2026-11-16T10:01:00.000Z'
        });
      }
      return base(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByText('已有的回复');

    fireEvent.keyDown(window, { key: '/' });
    expect(
      await screen.findByRole('dialog', { name: /搜索与投资专家的时间线/ })
    ).toBeTruthy();
    fireEvent.change(within(screen.getByRole('dialog')).getByRole('textbox'), { target: { value: '茅台' } });
    fireEvent.click(await screen.findByRole('button', { name: '接着这个任务聊' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/tasks/t1/reopen',
        expect.objectContaining({ method: 'POST' })
      );
    });
    expect(await screen.findByText('接着：已有任务')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText('给 Bot 发消息'));

    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/tasks/t1/reopen/cancel',
        expect.objectContaining({ method: 'POST' })
      );
    });
    await waitFor(() => expect(screen.queryByText('接着：已有任务')).toBeNull());
  });

  it('applies bot.updated to the bot list without a reload', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByRole('heading', { name: '今天想盯哪只股票？' });
    const callsBefore = fetchMock.mock.calls.length;
    const source = MockEventSource.instances[0];

    act(() => {
      source?.emit('bot.updated', {
        type: 'bot.updated',
        id: 12,
        at: '2026-11-16T10:00:00.000Z',
        botId: 'expert',
        bot: { ...expertBot, name: '阿金', avatar: { emblem: 'lamp', tone: 'jade' } }
      });
    });

    expect(await screen.findByRole('button', { name: /阿金，空闲/ })).toBeTruthy();
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });
});
