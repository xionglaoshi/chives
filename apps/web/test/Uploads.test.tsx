import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BotProfile, MessageDto, TaskDto, TimelinePage } from '@chives/server/protocol';
import { App } from '../src/App';
import { Timeline } from '../src/components/Timeline';
import { emptyTimeline, jsonResponse, makeBot, MockEventSource, resetEventSources } from './testUtils';

const bot = makeBot();
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
const oldMessage: MessageDto = {
  id: 'm0',
  botId: 'expert',
  taskId: 't1',
  role: 'bot',
  kind: 'text',
  content: '旧回复',
  meta: null,
  createdAt: '2026-11-16T10:00:00.000Z',
  seq: 1
};

function profile(): BotProfile {
  return {
    bot,
    role: bot.role,
    personaSummary: '',
    skills: [],
    mcp: [],
    tools: { code: 'sandboxed', write: 'workspace-only' },
    canDelegateTo: [],
    routines: [],
    memoryPolicy: { user: 'read', bot: 'read-write' },
    tradingGuard: false,
    model: 'deepseek-v4.1-flash',
    workspace: { path: '/tmp/expert', fileCount: 0, totalBytes: 0 },
    recentDeliverables: [],
    memory: { count: 0, limit: 200, items: [], available: true, updatedAt: null },
    defaults: { name: bot.name, avatar: bot.avatar }
  };
}

function page(): TimelinePage {
  return { messages: [oldMessage], tasks: [task], toolEvents: [], hasMore: false, nextBeforeSeq: null };
}

beforeEach(() => {
  resetEventSources();
  vi.stubGlobal('EventSource', MockEventSource);
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('uploads in App', () => {
  it('offers the same upload-enabled composer on the first-run Welcome screen', async () => {
    const attachment = {
      path: 'uploads/20261117/note.md',
      name: 'note.md',
      size: 12,
      kind: 'markdown' as const
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/bots') return jsonResponse([bot]);
      if (url.startsWith('/api/bots/expert/timeline')) return jsonResponse(emptyTimeline());
      if (url === '/api/notifications?limit=50') return jsonResponse([]);
      if (url === '/api/settings/proactive') return jsonResponse({});
      if (url === '/api/bots/expert/uploads' && init?.method === 'POST') {
        return jsonResponse(attachment, 200);
      }
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByRole('heading', { name: '今天想盯哪只股票？' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '上传文件' })).toBeTruthy();

    const file = new File(['# note\n'], 'note.md', { type: 'text/markdown' });
    fireEvent.drop(document.querySelector('.conversation') as Element, {
      dataTransfer: { files: [file], types: ['Files'] }
    });
    expect(await screen.findByText('note.md')).toBeTruthy();
    expect(
      fetchMock.mock.calls.some(([url]) => String(url) === '/api/bots/expert/uploads')
    ).toBe(true);
  });

  it('uploads a dropped file, sends it with meta, and renders an attachment-only bubble', async () => {
    const attachment = {
      path: 'uploads/20261117/chart.png',
      name: 'chart.png',
      size: 3,
      kind: 'image' as const
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/bots') return jsonResponse([bot]);
      if (url.startsWith('/api/bots/expert/timeline')) return jsonResponse(page());
      if (url === '/api/bots/expert/profile') return jsonResponse(profile());
      if (url === '/api/notifications?limit=50') return jsonResponse([]);
      if (url === '/api/settings/proactive') return jsonResponse({});
      if (url === '/api/bots/expert/uploads' && init?.method === 'POST') {
        return jsonResponse(attachment, 200);
      }
      if (url === '/api/bots/expert/messages' && init?.method === 'POST') {
        return jsonResponse({ messageId: 'm1', taskId: 't1' }, 202);
      }
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByText('旧回复')).toBeTruthy();

    const conversation = document.querySelector('.conversation');
    expect(conversation).not.toBeNull();
    fireEvent.dragOver(conversation as Element, { dataTransfer: { types: ['Files'] } });
    expect(document.querySelector('.conversation__drop')).not.toBeNull();
    const file = new File(['png'], 'chart.png', { type: 'image/png' });
    fireEvent.drop(conversation as Element, { dataTransfer: { files: [file], types: ['Files'] } });

    await waitFor(() => expect(screen.getByText('chart.png')).toBeTruthy());
    const uploadCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/bots/expert/uploads');
    expect(uploadCall?.[1]?.headers).toMatchObject({
      'x-file-name': 'chart.png'
    });

    const send = screen.getByRole('button', { name: '发送' }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === '/api/bots/expert/messages' &&
          (init as RequestInit | undefined)?.method === 'POST'
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call?.[1] as RequestInit).body)) as {
        text: string;
        attachments: unknown[];
      };
      expect(body.text).toBe('');
      expect(body.attachments).toEqual([attachment]);
    });

    const source = MockEventSource.instances[0];
    act(() => {
      source?.emit('message.created', {
        type: 'message.created',
        id: 9,
        at: '2026-11-17T08:00:00.000Z',
        botId: 'expert',
        taskId: 't1',
        message: {
          id: 'm9',
          botId: 'expert',
          taskId: 't1',
          role: 'user',
          kind: 'text',
          content: '',
          meta: { attachments: [attachment] },
          createdAt: '2026-11-17T08:00:00.000Z',
          seq: 9
        }
      });
    });
    const card = await screen.findByTitle('chart.png');
    expect(card.querySelector('img')?.getAttribute('src')).toContain(
      '/api/bots/expert/files/content?path=uploads%2F20261117%2Fchart.png'
    );
    fireEvent.click(card);
    expect(await screen.findByLabelText('交付物预览')).toBeTruthy();
  });

  it('refuses a disallowed type before uploading and explains why', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/bots') return jsonResponse([bot]);
      if (url.startsWith('/api/bots/expert/timeline')) return jsonResponse(page());
      if (url === '/api/notifications?limit=50') return jsonResponse([]);
      if (url === '/api/settings/proactive') return jsonResponse({});
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByText('旧回复')).toBeTruthy();

    const file = new File(['bin'], 'evil.exe', { type: 'application/octet-stream' });
    fireEvent.drop(document.querySelector('.conversation') as Element, {
      dataTransfer: { files: [file], types: ['Files'] }
    });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('不支持的文件类型：evil.exe');
    expect(
      fetchMock.mock.calls.some(([url]) => String(url) === '/api/bots/expert/uploads')
    ).toBe(false);
  });
});

describe('Timeline attachments', () => {
  const userMessage: MessageDto = {
    id: 'm1',
    botId: 'expert',
    taskId: 't1',
    role: 'user',
    kind: 'text',
    content: '看这个',
    meta: {
      attachments: [
        { path: 'uploads/20261117/chart.png', name: 'chart.png', size: 2048, kind: 'image' },
        { path: 'uploads/20261117/note.md', name: 'note.md', size: 12, kind: 'markdown' }
      ]
    },
    createdAt: '2026-11-16T09:58:00.000Z',
    seq: 1
  };

  it('shows attachment cards under the user bubble and forwards clicks', () => {
    const onOpenAttachment = vi.fn();
    render(
      <Timeline
        botId="expert"
        messages={[userMessage]}
        tasks={{ t1: task }}
        toolEvents={{}}
        draft={null}
        pending={[]}
        hasMore={false}
        loadingOlder={false}
        onLoadOlder={() => {}}
        onRetryPending={() => {}}
        onOpenAttachment={onOpenAttachment}
      />
    );
    expect(screen.getByText('看这个')).toBeTruthy();
    expect(screen.getByText('chart.png')).toBeTruthy();
    expect(screen.getByText('note.md')).toBeTruthy();
    expect(screen.getByText('2.0 KB')).toBeTruthy();
    fireEvent.click(screen.getByTitle('note.md'));
    expect(onOpenAttachment).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'uploads/20261117/note.md' }),
      expect.any(HTMLElement)
    );
  });
});
