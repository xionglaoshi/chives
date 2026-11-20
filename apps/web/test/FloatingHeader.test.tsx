import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskDto } from '@chives/server/protocol';
import { ChatHeader } from '../src/components/ChatHeader';
import { makeBot } from './testUtils';

const runningTask: TaskDto = {
  id: 't1',
  botId: 'expert',
  title: '分析',
  status: 'running',
  harnessSessionId: null,
  startedAt: '2026-11-17T08:00:00.000Z',
  endedAt: null,
  parentTaskId: null
};

describe('floating ChatHeader', () => {
  it('centers a name pill that opens the profile and shows the running dot and timer', () => {
    const onOpenProfile = vi.fn();
    render(
      <ChatHeader
        bot={makeBot({ name: '投资专家', status: 'working' })}
        runningTask={runningTask}
        turnStartedAt="2026-11-17T08:00:00.000Z"
        onOpenProfile={onOpenProfile}
      />
    );
    const pill = screen.getByRole('button', { name: '打开 投资专家 资料' });
    expect(pill.closest('header')?.className).toContain('chat-header');
    expect(pill.querySelector('.chat-header__pill-dot')).not.toBeNull();
    expect(pill.querySelector('.chat-header__pill-time')).not.toBeNull();
    fireEvent.click(pill);
    expect(onOpenProfile).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText('投资专家').length).toBeGreaterThan(0);
  });

  it('renders the first six characters for narrow screens', () => {
    render(
      <ChatHeader
        bot={makeBot({ name: '投资专家助手长名' })}
        runningTask={null}
        onOpenProfile={() => undefined}
      />
    );
    const short = document.querySelector('.chat-header__pill-name--short');
    expect(short?.textContent).toBe('投资专家助手');
  });

  it('keeps the bell, search and panel buttons in the floating action group', () => {
    const onSearch = vi.fn();
    const onTogglePanel = vi.fn();
    render(
      <ChatHeader
        bot={makeBot({ name: '投资专家', panels: ['market', 'watches'], watchCount: 2 })}
        runningTask={null}
        onSearch={onSearch}
        onTogglePanel={onTogglePanel}
      />
    );
    const actions = document.querySelector('.chat-header__actions');
    expect(actions?.querySelectorAll('button')).toHaveLength(4);
    fireEvent.click(screen.getByRole('button', { name: '搜索与投资专家的时间线' }));
    expect(onSearch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '盯盘' }));
    expect(onTogglePanel).toHaveBeenCalledWith('watches');
  });

  it('uses a non-interactive pill when no profile handler is given', () => {
    render(<ChatHeader bot={makeBot({ name: '投资专家' })} runningTask={null} />);
    expect(screen.queryByRole('button', { name: '打开 投资专家 资料' })).toBeNull();
    expect(document.querySelector('.chat-header__pill')?.tagName).toBe('DIV');
  });
});
