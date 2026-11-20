import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BotsOverview } from '../src/components/BotsOverview';
import { makeBot } from './testUtils';

const bots = [
  makeBot({
    id: 'expert',
    name: '投资专家',
    role: '默认入口',
    skills: ['idea-generation', 'morning-note', 'portfolio-diagnosis', 'watch-briefing'],
    mcp: ['cn_data', 'cn_extra', 'paper_broker'],
    canDelegateTo: ['data-prep', 'research'],
    status: 'working',
    pendingApprovals: 1,
    modelDisplayName: 'deepseek-v4.1-flash',
    workspacePath: '/Users/analyst/Chives/bots/expert/workspace',
    memoryCount: 8,
    memoryUpdatedAt: '2026-11-16T10:00:00.000Z'
  }),
  makeBot({
    id: 'data-prep',
    name: '数据员',
    role: '批量取数',
    background: true,
    avatar: { emblem: 'bars', tone: 'ink' },
    skills: [],
    mcp: ['cn_data'],
    status: 'idle',
    workspacePath: '/Users/analyst/Chives/bots/data-prep/workspace',
    memoryCount: 0
  })
];

describe('BotsOverview', () => {
  it('renders statistics and the required card fields', () => {
    render(
      <BotsOverview
        bots={bots}
        loading={false}
        error={null}
        onRetry={() => {}}
        onOpenConversation={() => {}}
        onOpenProfile={() => {}}
      />
    );

    const stats = screen.getByLabelText('Bot 概览统计');
    expect(stats.textContent).toContain('2');
    expect(stats.textContent).toContain('个 Bot');
    expect(stats.textContent).toContain('1');
    expect(stats.textContent).toContain('个工作中');
    expect(stats.textContent).toContain('项待批准');

    expect(screen.getByText('4 项 · idea-generation、morning-note、portfolio-diagnosis 等')).toBeTruthy();
    expect(screen.getByText('A 股行情与财务、分钟线与快照、模拟盘')).toBeTruthy();
    expect(screen.getByText('数据员、research')).toBeTruthy();
    expect(screen.getByText('8 条 · 最近更新 2026-11-16')).toBeTruthy();
    expect(screen.getByText('还没有记忆')).toBeTruthy();
    expect(screen.getByText('deepseek-v4.1-flash')).toBeTruthy();
    expect(screen.getByText('~/Chives/bots/expert/workspace')).toBeTruthy();
    expect(screen.getAllByText('暂无').length).toBeGreaterThanOrEqual(2);
  });

  it('calls the conversation and profile callbacks', () => {
    const onOpenConversation = vi.fn();
    const onOpenProfile = vi.fn();
    render(
      <BotsOverview
        bots={bots}
        loading={false}
        error={null}
        onRetry={() => {}}
        onOpenConversation={onOpenConversation}
        onOpenProfile={onOpenProfile}
      />
    );

    fireEvent.click(screen.getAllByRole('button', { name: '对话' })[0] as HTMLElement);
    expect(onOpenConversation).toHaveBeenCalledWith('expert');
    fireEvent.click(screen.getAllByRole('button', { name: '查看资料' })[0] as HTMLElement);
    expect(onOpenProfile).toHaveBeenCalledWith('expert');
  });

  it('weakens background bot cards', () => {
    const { container } = render(
      <BotsOverview
        bots={bots}
        loading={false}
        error={null}
        onRetry={() => {}}
        onOpenConversation={() => {}}
        onOpenProfile={() => {}}
      />
    );
    expect(container.querySelectorAll('.bots-overview__card--background')).toHaveLength(1);
  });
});
