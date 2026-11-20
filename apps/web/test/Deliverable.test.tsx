import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  BotSummary,
  DeliverableDto,
  MessageDto,
  TaskDto,
  TimelinePage
} from '@chives/server/protocol';
import { App } from '../src/App';
import { DeliverableCards } from '../src/components/DeliverableCard';
import { DeliverablePreview } from '../src/components/DeliverablePreview';
import { Timeline, embeddedImagesByTask } from '../src/components/Timeline';
import { parseCsv } from '../src/utils/csv';
import { emptyTimeline, jsonResponse, makeBot, MockEventSource, resetEventSources } from './testUtils';

const bots: BotSummary[] = [
  makeBot(),
  makeBot({
    id: 'data-prep',
    name: '数据员',
    background: true,
    avatar: { emblem: 'bars', tone: 'ink' }
  })
];

function makeDeliverable(overrides: Partial<DeliverableDto> = {}): DeliverableDto {
  return {
    id: 'd1',
    taskId: 't1',
    botId: 'expert',
    path: '报告.md',
    kind: 'markdown',
    size: 2048,
    createdAt: '2026-11-16T10:00:00.000Z',
    ...overrides
  };
}

const task: TaskDto = {
  id: 't1',
  botId: 'expert',
  title: '财报点评',
  status: 'done',
  harnessSessionId: null,
  startedAt: '2026-11-16T09:58:00.000Z',
  endedAt: '2026-11-16T10:00:00.000Z',
  parentTaskId: null,
  depth: 0,
  delegated: false,
  brief: null
};

function deliverableMessage(deliverables: DeliverableDto[], delegated = false): MessageDto {
  return {
    id: 'm-deliverable',
    botId: 'expert',
    taskId: 't1',
    role: 'bot',
    kind: 'deliverable',
    content: `本轮产出 ${deliverables.length} 个文件`,
    meta: {
      deliverableIds: deliverables.map((entry) => entry.id),
      deliverables,
      overflow: 0,
      delegated,
      sourceBotId: delegated ? 'data-prep' : 'expert',
      sourceBotName: delegated ? '数据员' : '投资专家'
    },
    createdAt: '2026-11-16T10:00:00.000Z',
    seq: 3
  };
}

function textResponse(body: string, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
    json: async () => JSON.parse(body) as unknown
  } as Response;
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

describe('CSV parsing', () => {
  it('handles quoted commas, escaped quotes, CRLF, and embedded newlines', () => {
    const rows = parseCsv('name,note\r\n"a, b","say ""hi"""\r\n"line\nbreak",2\r\n');
    expect(rows).toEqual([
      ['name', 'note'],
      ['a, b', 'say "hi"'],
      ['line\nbreak', '2']
    ]);
  });
});

describe('DeliverableCards', () => {
  it('shows file name, kind, bot, size, and the delegated attribution', () => {
    const deliverables = [
      makeDeliverable({ id: 'd1', path: 'reports/茅台.md', botId: 'data-prep' }),
      makeDeliverable({ id: 'd2', path: 'charts/pe.png', kind: 'image', size: 1024 * 1024 })
    ];
    render(
      <DeliverableCards
        message={deliverableMessage(deliverables, true)}
        bots={bots}
        activeId="d1"
        onOpen={() => {}}
      />
    );

    expect(screen.getByText('茅台.md')).toBeTruthy();
    expect(screen.getByText(/由 数据员 产出/)).toBeTruthy();
    expect(screen.getByText('1.0 MB')).toBeTruthy();
    expect(screen.getByText('正在预览')).toBeTruthy();
  });

  it('collects relative inline image paths per task', () => {
    const base = {
      botId: 'expert',
      role: 'bot' as const,
      kind: 'text' as const,
      meta: null,
      createdAt: '2026-11-16T10:00:00.000Z',
      seq: 1
    };
    const byTask = embeddedImagesByTask([
      {
        ...base,
        id: 'm1',
        taskId: 't1',
        content: '![a](charts/a.png) ![远端](https://example.com/b.png)'
      },
      { ...base, id: 'm2', taskId: 't2', content: '![c](charts/c.png)' }
    ]);
    expect([...(byTask.get('t1') ?? [])]).toEqual(['charts/a.png']);
    expect([...(byTask.get('t2') ?? [])]).toEqual(['charts/c.png']);
  });

  it('omits images already embedded in the turn Markdown and counts only shown files', () => {
    const deliverables = [
      makeDeliverable({ id: 'img', path: 'charts/embedded.png', kind: 'image' }),
      ...Array.from({ length: 5 }, (_, index) =>
        makeDeliverable({ id: `md${index}`, path: `reports/r${index}.md` })
      )
    ];
    render(
      <DeliverableCards
        message={deliverableMessage(deliverables)}
        bots={bots}
        activeId={null}
        onOpen={() => {}}
        embeddedImages={new Set(['charts/embedded.png'])}
      />
    );

    expect(screen.queryByText('embedded.png')).toBeNull();
    expect(screen.getByRole('button', { name: '+1 个文件' })).toBeTruthy();
  });

  it('collapses more than four files into +N and expands on click', () => {
    const deliverables = Array.from({ length: 6 }, (_, index) =>
      makeDeliverable({ id: `d${index}`, path: `file-${index}.md` })
    );
    render(
      <DeliverableCards
        message={deliverableMessage(deliverables)}
        bots={bots}
        activeId={null}
        onOpen={() => {}}
      />
    );
    expect(screen.getAllByRole('button', { name: /file-/ })).toHaveLength(4);
    fireEvent.click(screen.getByRole('button', { name: '+2 个文件' }));
    expect(screen.getAllByRole('button', { name: /file-/ })).toHaveLength(6);
    expect(screen.getByRole('button', { name: '收起' })).toBeTruthy();
  });

  it('opens a card through the timeline and returns the trigger element', () => {
    const onOpen = vi.fn();
    render(
      <Timeline
        botId="expert"
        bots={bots}
        messages={[deliverableMessage([makeDeliverable()])]}
        tasks={{ t1: task }}
        toolEvents={{}}
        draft={null}
        pending={[]}
        hasMore={false}
        loadingOlder={false}
        onLoadOlder={() => {}}
        onRetryPending={() => {}}
        onOpenDeliverable={onOpen}
      />
    );
    const card = screen.getByRole('button', { name: /报告.md/ });
    fireEvent.click(card);
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 'd1' }), card);
  });
});

describe('DeliverablePreview', () => {
  it('renders Markdown with a GFM table and disables export PDF', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse('# 标题\n\n| 指标 | 数值 |\n| --- | ---: |\n| EPS | 51.53 |\n'))
    );
    render(<DeliverablePreview deliverable={makeDeliverable()} bots={bots} onClose={() => {}} />);

    expect(await screen.findByRole('heading', { name: '标题' })).toBeTruthy();
    expect(screen.getByText('51.53')).toBeTruthy();
    const exportButton = screen.getByRole('button', { name: /导出 PDF/ }) as HTMLButtonElement;
    expect(exportButton.disabled).toBe(true);
    expect(exportButton.title).toBe('即将支持');
    expect(screen.getByRole('button', { name: '在访达中显示' })).toBeTruthy();
  });

  it('passes the bot id and report directory to Markdown image resolution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        return url.startsWith('/api/deliverables/')
          ? textResponse('![图](charts/pe.png)')
          : textResponse('');
      })
    );
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'reports/000528-柳工/20261117_估值.md' })}
        bots={bots}
        onClose={() => {}}
      />
    );

    const image = await screen.findByRole('img');
    const resolved = new URL(image.getAttribute('src') ?? '', 'http://localhost');
    expect(resolved.searchParams.get('path')).toBe('reports/000528-柳工/charts/pe.png');
  });

  it('reads MAP.md from the workspace and hides the deliverable reveal action', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/bots/expert/files/text?path=MAP.md') {
        return textResponse('# 工作目录地图\n\n- reports/');
      }
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ id: 'workspace-map-expert', path: 'MAP.md' })}
        bots={bots}
        workspaceFile={{ botId: 'expert', path: 'MAP.md' }}
        onClose={() => {}}
      />
    );

    expect(await screen.findByRole('heading', { name: '工作目录地图' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '在访达中显示' })).toBeNull();
  });

  it('renders CSV as a table with right-aligned numeric columns and escaped quotes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse('name,value\n"a, b","1,234"\n"say ""hi""",2\n'))
    );
    const { container } = render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'data.csv', kind: 'csv' })}
        bots={bots}
        onClose={() => {}}
      />
    );

    expect(await screen.findByText('a, b')).toBeTruthy();
    expect(screen.getByText('say "hi"')).toBeTruthy();
    const numeric = screen.getByText('1,234');
    expect(numeric.tagName).toBe('TD');
    expect(numeric.className).toContain('preview__num');
    expect(container.querySelector('.preview__table')).not.toBeNull();
  });

  it('caps CSV display at 500 rows and reports the total', async () => {
    const lines = ['id,value'];
    for (let index = 0; index < 501; index += 1) lines.push(`${index},${index * 2}`);
    vi.stubGlobal('fetch', vi.fn(async () => textResponse(lines.join('\n'))));
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'rows.csv', kind: 'csv' })}
        bots={bots}
        onClose={() => {}}
      />
    );

    expect(await screen.findByText('共 501 行，仅显示前 500 行')).toBeTruthy();
    expect(screen.getAllByRole('row')).toHaveLength(501);
  });

  it('formats JSON and shows unviewable files with a reveal action', async () => {
    const fetchMock = vi.fn(async () => textResponse('{"a":1,"b":[2,3]}'));
    vi.stubGlobal('fetch', fetchMock);
    const { rerender } = render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'data.json', kind: 'json' })}
        bots={bots}
        onClose={() => {}}
      />
    );
    expect(await screen.findByText(/"b": \[/)).toBeTruthy();

    rerender(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'archive.zip', kind: 'other' })}
        bots={bots}
        onClose={() => {}}
      />
    );
    expect(screen.getByText('无法预览')).toBeTruthy();
    expect(within(screen.getByLabelText('交付物预览')).getAllByRole('button', { name: '在访达中显示' }).length).toBeGreaterThan(0);
  });

  it('says the file no longer exists when the content route returns 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'deliverable_not_found', message: 'deliverable file does not exist' } },
          404
        )
      )
    );
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'gone.md', kind: 'markdown' })}
        bots={bots}
        onClose={() => {}}
      />
    );
    expect(await screen.findByText('文件已不存在')).toBeTruthy();
    expect(
      screen.getAllByRole('button', { name: '在访达中显示' }).length
    ).toBeGreaterThan(0);
  });

  it('shows an image preview error instead of a blank frame', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => textResponse('')));
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'charts/pe.png', kind: 'image' })}
        bots={bots}
        onClose={() => {}}
      />
    );
    const image = await screen.findByAltText('pe.png');
    fireEvent.error(image);
    expect(await screen.findByText('文件已不存在或无法加载')).toBeTruthy();
  });

  it('closes on Escape', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => textResponse('plain')));
    const onClose = vi.fn();
    render(
      <DeliverablePreview
        deliverable={makeDeliverable({ path: 'notes.txt', kind: 'code' })}
        bots={bots}
        onClose={onClose}
      />
    );
    expect(await screen.findByText('plain')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('App preview layout', () => {
  it('opens the panel, collapses the sidebar to avatars, and restores focus on Escape', async () => {
    const deliverables = [
      makeDeliverable({ id: 'd1', path: 'reports/茅台.md' }),
      makeDeliverable({ id: 'd2', path: 'charts/pe.png', kind: 'image' })
    ];
    const page: TimelinePage = {
      messages: [deliverableMessage(deliverables, true)],
      tasks: [task],
      toolEvents: [],
      hasMore: false,
      nextBeforeSeq: null
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/bots') return jsonResponse(bots);
      if (url.startsWith('/api/bots/expert/timeline')) return jsonResponse(page);
      if (url.startsWith('/api/bots/data-prep/timeline')) return jsonResponse(emptyTimeline());
      if (url.endsWith('/content')) return textResponse('# 茅台三季报\n\n结论');
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    const card = await screen.findByRole('button', { name: /茅台.md/ });
    fireEvent.click(card);
    expect(await screen.findByLabelText('交付物预览')).toBeTruthy();
    expect(await screen.findByRole('heading', { name: '茅台三季报' })).toBeTruthy();
    const sidebar = screen.getByRole('navigation', { name: 'Bot 列表' });
    expect(sidebar.className).toContain('sidebar--compact');
    expect(within(sidebar).getByRole('button', { name: /投资专家/ })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByLabelText('交付物预览')).toBeNull());
    expect(sidebar.className).not.toContain('sidebar--compact');
    await waitFor(() => expect(document.activeElement).toBe(card));
  });
});

describe('isShownDeliverablePath', () => {
  it('hides code, data, scratch and the workspace map from older records', async () => {
    const { isShownDeliverablePath } = await import('../src/utils/deliverables');
    expect(isShownDeliverablePath('lg_strategy_20261117/chart.py')).toBe(false);
    expect(isShownDeliverablePath('lg_strategy_20261117/metrics.json')).toBe(false);
    expect(isShownDeliverablePath('northbound_daily_20261117.csv')).toBe(false);
    expect(isShownDeliverablePath('data/000528-柳工/bars.parquet')).toBe(false);
    expect(isShownDeliverablePath('scratch/notes.md')).toBe(false);
    expect(isShownDeliverablePath('MAP.md')).toBe(false);
    expect(isShownDeliverablePath('lg_strategy_20261117/chart_liugong_20261117.png')).toBe(true);
    expect(isShownDeliverablePath('reports/000528-柳工/20261117_估值.md')).toBe(true);
  });
});
