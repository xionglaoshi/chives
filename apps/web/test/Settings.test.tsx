import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  ActiveRoutineDto,
  AppearanceSettingsDto,
  ModelSettingsDto,
  ProactiveSettingsDto,
  RuntimeSettingsDto
} from '@chives/server/protocol';
import { Change } from '../src/components/Change';
import { Settings } from '../src/components/Settings';
import { Sidebar } from '../src/components/Sidebar';
import { jsonResponse } from './testUtils';

const proactive: ProactiveSettingsDto = { enabled: true, autoAnalysis: true, observeOnly: false };

const routines: ActiveRoutineDto[] = [
  {
    id: 'premarket-brief',
    botId: 'expert',
    source: 'manifest',
    title: '盘前简报',
    schedule: { cron: '30 8 * * 1-5', tz: 'Asia/Shanghai' },
    scheduleText: '工作日 08:30（北京时间）',
    prompt: '简报',
    promptSummary: '简报',
    tradingDaysOnly: true,
    enabled: true,
    createdAt: '2026-11-16T08:00:00.000Z',
    lastRunAt: null,
    nextRunAt: null,
    botName: '投资专家'
  }
];

function runtime(): RuntimeSettingsDto {
  return {
    harness: { name: 'DeepSeek Harness', version: null, connected: true },
    bots: [
      { id: 'expert', name: '投资专家', process: 'running' },
      { id: 'research', name: '研究员', process: 'not_started' }
    ],
    engines: [
      { port: 8865, healthy: true },
      { port: 8866, healthy: false },
      { port: 8867, healthy: true }
    ]
  };
}

function models(selected: string | null = 'm1'): ModelSettingsDto {
  return {
    selected,
    options: [
      { value: 'm1', name: 'Model One' },
      { value: 'm2', name: 'Model Two' }
    ]
  };
}

interface Options {
  assessmentError?: string;
  appearance?: AppearanceSettingsDto;
}

function createFetch(options: Options = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body =
      init?.body === undefined ? undefined : (JSON.parse(String(init.body)) as Record<string, unknown>);
    if (url === '/api/settings/desk/prefs') return jsonResponse({name:'',email:'',phone:'',avatar:'',locale:'zh-CN',timezone:'Asia/Shanghai',fontSize:'standard',density:'comfortable'});
    if (url === '/api/settings/desk/models') return jsonResponse([]);
    if (url === '/api/settings/desk/assessment') {
      return options.assessmentError ? new Response(JSON.stringify({error:{message:options.assessmentError}}),{status:503}) : jsonResponse({questions:[],result:null});
    }
    if (url === '/api/settings/proactive' && init?.method === 'PUT') {
      return jsonResponse({ ...proactive, ...(body ?? {}) });
    }
    if (url === '/api/settings/proactive') return jsonResponse(proactive);
    if (url === '/api/settings/routines?scope=all') return jsonResponse(routines);
    if (url === '/api/settings/runtime') return jsonResponse(runtime());
    if (url === '/api/settings/models' && init?.method === 'PUT') {
      return jsonResponse(models((body?.['value'] as string | null) ?? null));
    }
    if (url === '/api/settings/models') return jsonResponse(models());
    if (url === '/api/settings/appearance' && init?.method === 'PUT') {
      return jsonResponse({ ...(options.appearance ?? { theme: 'dark', changeColor: 'red-up' }), ...(body ?? {}) });
    }
    if (url === '/api/settings/appearance') {
      return jsonResponse(options.appearance ?? { theme: 'dark', changeColor: 'red-up' });
    }
    if (url === '/api/settings/data') return jsonResponse({ path: '/Users/me/Chives', bytes: 1234 });
    if (url === '/api/settings/data/reveal') return jsonResponse({ ok: true });
    return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
  });
}

afterEach(() => {
  delete document.documentElement.dataset['theme'];
  delete document.documentElement.dataset['themePreference'];
  delete document.documentElement.dataset['changeColor'];
  document.documentElement.style.colorScheme = '';
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Settings', () => {
  it('shows assessment conclusions as read only and saves the automatic analysis permission', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<Settings onAskExpert={() => undefined} onOpenProfile={() => undefined} />);

    expect(await screen.findByRole('heading', { name: '用户资料' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'风格评估',exact:true}));
    await screen.findByText('完成问卷后，即可查看风险承受能力和风格偏好。');
    const open=vi.spyOn(window,'open').mockImplementation(()=>null);
    const begin=screen.getByRole('button',{name:'开始评测'});
    await waitFor(()=>expect(begin.hasAttribute('disabled')).toBe(false));
    fireEvent.click(begin);
    expect(open).toHaveBeenCalledWith(expect.stringContaining('interview=1'),'chives-style-interview');
    open.mockRestore();
    expect(screen.queryByRole('combobox')).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'补充资料更新评估'}));
    expect(screen.getByRole('button',{name:'去填问卷'})).toBeTruthy();

    fireEvent.click(screen.getByRole('button',{name:'消息权限',exact:true}));
    expect(screen.queryByText('高级')).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'任务管理',exact:true}));
    expect(await screen.findByRole('switch',{name:'投资专家 · 盘前简报'})).toBeTruthy();
    expect(screen.getByRole('switch',{name:'全部定时任务'})).toBeTruthy();
    expect(screen.getByText('高级')).toBeTruthy();
    expect(screen.queryByLabelText(/每天自动分析的上限/)).toBeNull();
    expect(screen.queryByRole('switch',{name:'允许Bot开启自动分析'})).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'权限设置',exact:true}));
    fireEvent.click(await screen.findByRole('switch',{name:'允许Bot开启自动分析'}));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/proactive',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ autoAnalysis: false })
        })
      );
    });
  });

  it('switches theme and price colours while Change keeps its class and arrow', async () => {
    vi.stubGlobal('fetch', createFetch());
    render(
      <>
        <Settings onAskExpert={() => undefined} onOpenProfile={() => undefined} />
        <Change value={1.23} />
      </>
    );

    fireEvent.click(screen.getByRole('button',{name:'外观设置',exact:true}));
    expect(await screen.findByLabelText('涨跌颜色')).toBeTruthy();
    const change = screen.getByText('▲ 1.23%');
    expect(change.className).toContain('change--up');

    fireEvent.click(screen.getByRole('button', { name: '绿涨红跌' }));
    await waitFor(() => {
      expect(document.documentElement.dataset['changeColor']).toBe('green-up');
    });
    expect(screen.getByText('▲ 1.23%').className).toContain('change--up');

    fireEvent.click(screen.getByRole('button', { name: '浅色' }));
    await waitFor(() => {
      expect(document.documentElement.dataset['theme']).toBe('light');
      expect(document.documentElement.style.colorScheme).toBe('light');
    });
    expect(screen.getByRole('button', { name: '浅色' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('▲ 1.23%').className).toContain('change--up');
  });

  it('shows the default model without requesting key status', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<Settings onAskExpert={() => undefined} onOpenProfile={() => undefined} />);
    fireEvent.click(screen.getByRole('button',{name:'模型设置',exact:true}));
    expect(await screen.findByRole('heading', {name:'各 Bot 的默认模型'})).toBeTruthy();
    expect(screen.queryByText('模型密钥')).toBeNull();
    expect(fetchMock.mock.calls.some(([url])=>String(url)==='/api/settings/keys')).toBe(false);
  });

  it('opens settings from the sidebar entry', () => {
    const onOpenSettings = vi.fn();
    render(
      <Sidebar
        bots={[]}
        selectedId={null}
        loading={false}
        settingsActive
        onSelect={() => undefined}
        onShowAll={() => undefined}
        onOpenSettings={onOpenSettings}
      />
    );
    const button = screen.getByRole('button', { name: '设置' });
    expect(button.getAttribute('aria-current')).toBe('page');
    fireEvent.click(button);
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it('shows the profile service reason without hiding other settings', async () => {
    vi.stubGlobal(
      'fetch',
      createFetch({assessmentError:'评测服务暂时不可用'})
    );
    render(<Settings onAskExpert={() => undefined} onOpenProfile={() => undefined} />);

    fireEvent.click(screen.getByRole('button',{name:'风格评估',exact:true}));
    expect(await screen.findByText('评测服务暂时不可用')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'备份及导入',exact:true}));
    expect(screen.getByText('/Users/me/Chives')).toBeTruthy();
  });
});
