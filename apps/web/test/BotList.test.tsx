import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BotList } from '../src/components/BotList';
import { makeBot } from './testUtils';

const bots = [
  makeBot({ id: 'expert', name: '投资专家' }),
  makeBot({
    id: 'equity-analyst',
    name: '个股分析师',
    status: 'awaiting_approval',
    pendingApprovals: 2,
    avatar: { emblem: 'scale', tone: 'silver' }
  }),
  makeBot({ id: 'research', name: '研究员', avatar: { emblem: 'lens', tone: 'jade' } }),
  makeBot({
    id: 'data-prep',
    name: '数据员',
    background: true,
    avatar: { emblem: 'bars', tone: 'ink' }
  }),
  makeBot({
    id: 'report-builder',
    name: '报告员',
    background: true,
    avatar: { emblem: 'scroll', tone: 'bronze' }
  })
];

describe('BotList', () => {
  it('combines enabled bots and marks the selected one', () => {
    render(<BotList bots={bots} selectedId="expert" onSelect={() => {}} />);
    expect(screen.getByRole('heading', { name: '已在岗Bot' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '后台同事' })).toBeNull();
    expect(screen.getByRole('button', { name: /投资专家/ }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('button', { name: /数据员/ }).getAttribute('aria-current')).toBeNull();
  });

  it('shows the delegation wait label while the bot is idle', () => {
    const waiting = [
      makeBot({ id: 'expert', name: '投资专家', status: 'idle', waitingDelegations: 2 })
    ];
    render(<BotList bots={waiting} selectedId="expert" onSelect={() => {}} />);
    expect(screen.getAllByText('等待委派结果（2）').length).toBeGreaterThan(0);
  });

  it('shows the approval badge from the bot status', () => {
    const { container } = render(<BotList bots={bots} selectedId="expert" onSelect={() => {}} />);
    const badge = container.querySelector('.bot-row__badge');
    expect(badge?.textContent).toBe('2');
    expect(badge?.getAttribute('aria-label')).toBe('2 项待你批准');
  });

  it('moves selection with the arrow keys and keeps every row tabbable', () => {
    const onSelect = vi.fn();
    render(<BotList bots={bots} selectedId="expert" onSelect={onSelect} />);
    const first = screen.getByRole('button', { name: /投资专家/ });
    first.focus();
    expect(first.tabIndex).toBe(0);

    fireEvent.keyDown(first, { key: 'ArrowDown' });
    expect(onSelect).toHaveBeenCalledWith('equity-analyst');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /个股分析师/ }));

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowUp' });
    expect(onSelect).toHaveBeenLastCalledWith('expert');
  });
});
