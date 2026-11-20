import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type {
  BotSummary,
  MessageDto,
  TaskDetail,
  TaskDto,
  ToolEventDto
} from '@chives/server/protocol';
import { DelegationRow } from '../src/components/DelegationRow';
import { initialTimelineState, timelineReducer } from '../src/hooks/useTimeline';

const expertBot: BotSummary = {
  id: 'expert',
  name: '投资专家',
  role: '默认入口',
  avatar: { emblem: 'crown', tone: 'gold' },
  skills: [],
  mcp: [],
  model: 'default',
  canDelegateTo: ['data-prep'],
  background: false,
  status: 'idle',
  runningTaskId: null,
  pendingApprovals: 0,
  panels: []
};

const dataPrep: BotSummary = {
  id: 'data-prep',
  name: '数据员',
  role: '取数',
  avatar: { emblem: 'bars', tone: 'ink' },
  skills: [],
  mcp: [],
  model: 'default',
  canDelegateTo: [],
  background: true,
  status: 'idle',
  runningTaskId: null,
  pendingApprovals: 0,
  panels: []
};

function delegationMessage(
  meta: Record<string, unknown>,
  createdAt = '2026-11-16T10:00:00.000Z'
): MessageDto {
  return {
    id: 'm-delegation',
    botId: 'expert',
    taskId: 'parent-1',
    role: 'bot',
    kind: 'delegation',
    content: '委派给 数据员：取三表',
    meta: {
      delegationId: 'delegation-1',
      parentTaskId: 'parent-1',
      targetBotId: 'data-prep',
      targetBotName: '数据员',
      childTaskId: 'child-1',
      brief: '取三表、估值序列与一致预期',
      startedAt: '2026-11-16T10:00:00.000Z',
      endedAt: null,
      error: null,
      ...meta
    },
    createdAt,
    seq: 2
  };
}

const childTask: TaskDto = {
  id: 'child-1',
  botId: 'data-prep',
  title: '委派：取三表',
  status: 'done',
  harnessSessionId: null,
  startedAt: '2026-11-16T10:00:00.000Z',
  endedAt: '2026-11-16T10:00:38.000Z',
  parentTaskId: 'parent-1',
  depth: 1,
  delegated: true,
  brief: '取三表、估值序列与一致预期'
};

const tool: ToolEventDto = {
  id: 'tool-1',
  taskId: 'child-1',
  messageId: null,
  toolCallId: 'call-1',
  title: 'cn_get_financial_statements',
  kind: 'read',
  rawInput: { symbol: '600519.SH' },
  status: 'completed',
  output: 'ok',
  startedAt: '2026-11-16T10:00:01.000Z',
  endedAt: '2026-11-16T10:00:02.000Z'
};

const detail: TaskDetail = {
  task: childTask,
  toolEvents: [tool],
  usage: [],
  messages: [
    {
      id: 'child-msg',
      botId: 'data-prep',
      taskId: 'child-1',
      role: 'bot',
      kind: 'text',
      content: '**数据集已落盘**：data/600519.csv',
      meta: null,
      createdAt: '2026-11-16T10:00:38.000Z',
      seq: 3
    }
  ]
};

describe('DelegationRow', () => {
  it('shows a running row with the target bot and a live timer', () => {
    render(
      <DelegationRow
        message={delegationMessage({ status: 'running' })}
        bots={[expertBot, dataPrep]}
      />
    );
    const toggle = screen.getByRole('button', { name: /委派给 数据员/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.textContent).toContain('进行中');
    expect(toggle.textContent).toContain('结果返回后投资专家会自动合成');
    expect(toggle.textContent).toContain('数据员');
  });

  it('shows done with elapsed time and expands to tools plus the final message', async () => {
    const fetchDetail = vi.fn(async () => detail);
    render(
      <DelegationRow
        message={delegationMessage({ status: 'done', endedAt: '2026-11-16T10:00:38.000Z' })}
        bots={[dataPrep]}
        childTask={childTask}
        fetchDetail={fetchDetail}
      />
    );
    const toggle = screen.getByRole('button', { name: /委派给 数据员/ });
    expect(toggle.textContent).toContain('已完成 · 38 秒');

    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(await screen.findByText('cn_get_financial_statements')).toBeTruthy();
    expect(await screen.findByText('数据集已落盘')).toBeTruthy();
    expect(screen.getByText('取三表、估值序列与一致预期')).toBeTruthy();
    expect(fetchDetail).toHaveBeenCalledWith('child-1');
  });

  it('shows failed with the verbatim child error', () => {
    render(
      <DelegationRow
        message={delegationMessage({ status: 'failed', error: 'upstream 500' })}
        bots={[dataPrep]}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /委派给 数据员/ }));
    expect(screen.getByText('失败')).toBeTruthy();
    expect(screen.getByText('upstream 500')).toBeTruthy();
  });
});

describe('delegation.updated reducer', () => {
  it('merges the new status into the delegation message meta', () => {
    const message = delegationMessage({ status: 'running' });
    const state = { ...initialTimelineState, botId: 'expert', messages: [message] };
    const next = timelineReducer(state, {
      type: 'event',
      event: {
        id: 1,
        at: '2026-11-16T10:00:38.000Z',
        botId: 'expert',
        type: 'delegation.updated',
        taskId: 'parent-1',
        delegation: {
          delegationId: 'delegation-1',
          parentTaskId: 'parent-1',
          targetBotId: 'data-prep',
          targetBotName: '数据员',
          childTaskId: 'child-1',
          brief: '取三表、估值序列与一致预期',
          status: 'done',
          startedAt: '2026-11-16T10:00:00.000Z',
          endedAt: '2026-11-16T10:00:38.000Z',
          error: null
        },
        task: childTask
      }
    });
    expect(next.messages[0]?.meta?.status).toBe('done');
    expect(next.tasks['child-1']?.status).toBe('done');
  });
});
