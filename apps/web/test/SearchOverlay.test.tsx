import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  SearchResponse,
  SearchTaskGroup,
  TaskDetail,
  TaskDto
} from '@chives/server/protocol';
import { SearchOverlay } from '../src/components/SearchOverlay';
import { jsonResponse, makeBot } from './testUtils';

const bot = makeBot();

function today(hour: number, minute: number): string {
  const date = new Date();
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

const task: TaskDto = {
  id: 't1',
  botId: 'expert',
  title: '贵州茅台三季报点评',
  status: 'done',
  harnessSessionId: null,
  startedAt: today(9, 30),
  endedAt: today(10, 0),
  parentTaskId: null,
  closedAt: today(10, 1)
};

const secondTask: TaskDto = {
  ...task,
  id: 't2',
  title: '宁德时代持仓体检',
  startedAt: today(8, 0),
  endedAt: today(8, 20),
  closedAt: today(8, 21)
};

function group(overrides: Partial<SearchTaskGroup> = {}): SearchTaskGroup {
  return {
    taskId: 't1',
    botId: 'expert',
    botName: '投资专家',
    title: '贵州茅台三季报点评',
    lastActivityAt: today(10, 1),
    startedAt: today(9, 30),
    endedAt: today(10, 0),
    steps: 14,
    summary: {
      taskId: 't1',
      title: '贵州茅台三季报点评',
      conclusion: '可以持有，加仓没有明显的赔率优势。',
      keyNumbers: [
        { label: '市盈率', value: '21.84 倍', source: '东方财富', asOf: '2026-11-13' }
      ],
      deliverables: [],
      openQuestions: ['四季度批价走势没有可靠数据'],
      symbols: [],
      createdAt: today(10, 1),
      source: 'model'
    },
    snippets: [
      {
        docType: 'message',
        sourceId: 'm1',
        messageId: 'm1',
        deliverableId: null,
        text: '看下贵州茅台三季报，茅台估值在中位。',
        ranges: [
          { start: 4, end: 6 },
          { start: 10, end: 12 }
        ],
        createdAt: today(9, 31)
      }
    ],
    hitCount: 3,
    deliverables: [
      {
        id: 'd1',
        taskId: 't1',
        botId: 'expert',
        path: '贵州茅台_点评.md',
        kind: 'markdown',
        size: 1024,
        createdAt: today(10, 2)
      }
    ],
    taskIds: ['t1'],
    locateMessageId: 'm1',
    ...overrides
  };
}

function response(groups: SearchTaskGroup[] = [group()]): SearchResponse {
  return {
    query: '茅台',
    groups,
    totalGroups: groups.length,
    totalHits: groups.reduce((sum, entry) => sum + entry.hitCount, 0)
  };
}

function detail(): TaskDetail {
  return {
    task,
    toolEvents: [
      {
        id: 'tool-1',
        taskId: 't1',
        messageId: null,
        toolCallId: 'call-1',
        title: 'cn_get_quote_snapshot',
        kind: 'read',
        rawInput: { symbol: '600519.SH' },
        status: 'completed',
        output: '{"price":1500}',
        startedAt: today(9, 31),
        endedAt: today(9, 32)
      }
    ],
    usage: [],
    contextUsage: [],
    messages: [
      {
        id: 'm1',
        botId: 'expert',
        taskId: 't1',
        role: 'user',
        kind: 'text',
        content: '看下贵州茅台三季报',
        meta: null,
        createdAt: today(9, 30),
        seq: 1
      }
    ],
    summary: group().summary
  };
}

function stubFetch(search: SearchResponse | Error, taskDetail: TaskDetail = detail()) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/bots/expert/search')) {
      if (search instanceof Error) throw search;
      return jsonResponse(search);
    }
    if (url === '/api/tasks/t1') return jsonResponse(taskDetail);
    if (url === '/api/tasks/t2') return jsonResponse({ ...taskDetail, task: secondTask });
    return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('SearchOverlay', () => {
  it('debounces the query, groups results, and highlights snippet ranges', async () => {
    const fetchMock = stubFetch(response());
    render(
      <SearchOverlay
        bot={bot}
        onClose={() => {}}
        onReopen={async () => {}}
        onLocate={() => {}}
        onOpenDeliverable={() => {}}
      />
    );
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '茅台' } });

    expect(screen.getByText('正在搜索…')).toBeTruthy();
    expect(await screen.findByText('可以持有，加仓没有明显的赔率优势。')).toBeTruthy();
    expect(screen.getByText('1 个任务 · 3 处提到')).toBeTruthy();

    const marks = screen.getAllByText('茅台', { selector: 'mark' });
    expect(marks.length).toBeGreaterThanOrEqual(2);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/bots/expert/search?q=%E8%8C%85%E5%8F%B0&limit=20',
      expect.any(Object)
    );
  });

  it('shows the summary panel and opens a deliverable', async () => {
    const onOpenDeliverable = vi.fn();
    const onClose = vi.fn();
    stubFetch(response());
    render(
      <SearchOverlay
        bot={bot}
        onClose={onClose}
        onReopen={async () => {}}
        onLocate={() => {}}
        onOpenDeliverable={onOpenDeliverable}
      />
    );
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '茅台' }
    });
    expect(await screen.findByText('任务小结')).toBeTruthy();
    expect(screen.getByText(/21.84 倍/)).toBeTruthy();
    expect(screen.getByText(/四季度批价走势没有可靠数据/)).toBeTruthy();
    expect(screen.getByText(/14 步/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '贵州茅台_点评.md' }));
    expect(onClose).toHaveBeenCalled();
    expect(onOpenDeliverable).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'd1' }),
      expect.any(HTMLElement)
    );
  });

  it('runs the three actions with the selected task', async () => {
    const onReopen = vi.fn(async () => {});
    const onLocate = vi.fn();
    stubFetch(response());
    render(
      <SearchOverlay
        bot={bot}
        onClose={() => {}}
        onReopen={onReopen}
        onLocate={onLocate}
        onOpenDeliverable={() => {}}
      />
    );
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '茅台' }
    });
    fireEvent.click(await screen.findByRole('button', { name: '接着这个任务聊' }));
    await waitFor(() => expect(onReopen).toHaveBeenCalledWith(expect.objectContaining({ taskId: 't1' })));

    fireEvent.click(screen.getByRole('button', { name: '在时间线里定位' }));
    expect(onLocate).toHaveBeenCalledWith('m1');

    fireEvent.click(screen.getByRole('button', { name: '查看完整过程' }));
    expect(await screen.findByText('完整过程')).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: /工作了/ }));
    expect(await screen.findByText('cn_get_quote_snapshot')).toBeTruthy();
    expect(screen.getByText('看下贵州茅台三季报')).toBeTruthy();
  });

  it('selects groups with the arrow keys and closes on Escape', async () => {
    const onClose = vi.fn();
    stubFetch(response([group(), group({ taskId: 't2', title: '宁德时代持仓体检', locateMessageId: 'm2' })]));
    render(
      <SearchOverlay
        bot={bot}
        onClose={onClose}
        onReopen={async () => {}}
        onLocate={() => {}}
        onOpenDeliverable={() => {}}
      />
    );
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '茅台' } });
    await screen.findByText('宁德时代持仓体检');
    const buttons = screen.getAllByRole('button', { pressed: false });
    expect(buttons.length).toBeGreaterThan(0);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    await waitFor(() => {
      const results = screen.getByLabelText('搜索结果');
      const active = within(results).getByText('宁德时代持仓体检').closest('button');
      expect(active?.getAttribute('aria-pressed')).toBe('true');
    });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('renders empty and error states', async () => {
    stubFetch(response([]));
    const { unmount } = render(
      <SearchOverlay
        bot={bot}
        onClose={() => {}}
        onReopen={async () => {}}
        onLocate={() => {}}
        onOpenDeliverable={() => {}}
      />
    );
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '不存在' }
    });
    expect(await screen.findByText(/没有找到/)).toBeTruthy();
    unmount();

    stubFetch(new Error('搜索失败'));
    render(
      <SearchOverlay
        bot={bot}
        onClose={() => {}}
        onReopen={async () => {}}
        onLocate={() => {}}
        onOpenDeliverable={() => {}}
      />
    );
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '茅台' }
    });
    expect(await screen.findByText('搜索失败')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
  });
});
