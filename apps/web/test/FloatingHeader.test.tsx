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
  it('centers a name pill that opens the operator conversation and shows the running dot and timer', () => {
    const onOpenOperator = vi.fn();
    render(
      <ChatHeader
        operator={makeBot({ name: '总调度', status: 'working' })}
        runningTask={runningTask}
        turnStartedAt="2026-11-17T08:00:00.000Z"
        onOpenOperator={onOpenOperator}
      />
    );
    const pill = screen.getByRole('button', { name: '与总调度对话' });
    expect(pill.closest('header')?.className).toContain('chat-header');
    expect(pill.querySelector('.chat-header__pill-dot')).not.toBeNull();
    expect(pill.querySelector('.chat-header__pill-time')).not.toBeNull();
    fireEvent.click(pill);
    expect(onOpenOperator).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText('总调度').length).toBeGreaterThan(0);
  });

  it('keeps the bell, search and panel buttons in the floating action group', () => {
    const onSearch = vi.fn();
    const onTogglePanel = vi.fn();
    render(
      <ChatHeader
        operator={makeBot({ name: '总调度', panels: ['market', 'watches'], watchCount: 2 })}
        runningTask={null}
        onSearch={onSearch}
        onOpenOperator={() => undefined}
        onTogglePanel={onTogglePanel}
      />
    );
    const actions = screen.getByRole('group',{name:'右侧面板快捷按钮'});
    expect(actions?.querySelectorAll('button')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: '全局搜索' }));
    expect(onSearch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '盯盘' }));
    expect(onTogglePanel).toHaveBeenCalledWith('watches');
  });

  it('opens the operator conversation even while the roster is loading', () => {
    const open = vi.fn();
    render(<ChatHeader operator={undefined} runningTask={null} onOpenOperator={open}/>);
    fireEvent.click(screen.getByRole('button', {name:'与总调度对话'}));
    expect(open).toHaveBeenCalledOnce();
  });
});
