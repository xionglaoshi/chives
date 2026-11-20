import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { MessageDto } from '@chives/server/protocol';
import {
  ApprovalCard,
  approvalFromMessage,
  humanToolName,
  type ApprovalCardData
} from '../src/components/ApprovalCard';
import { initialTimelineState, timelineReducer } from '../src/hooks/useTimeline';

function approval(overrides: Partial<ApprovalCardData> = {}): ApprovalCardData {
  return {
    id: 'approval-1',
    title: 'mcp__paper_broker__paper_place_order',
    rawInput: {
      symbol: '600519.SH',
      side: 'buy',
      qty: 100,
      price: null,
      order_type: 'market'
    },
    sourceBotName: '数据员',
    delegated: true,
    decision: null,
    decidedAt: null,
    decidedBy: null,
    ...overrides
  };
}

describe('ApprovalCard', () => {
  it('renders the human tool name, delegated source, and Chinese parameter labels', () => {
    const { container } = render(
      <ApprovalCard approval={approval()} onDecide={async () => undefined} />
    );
    expect(screen.getByText('需要你批准：模拟盘下单')).toBeTruthy();
    expect(screen.getByText(/来自 数据员（委派）/)).toBeTruthy();
    const labels = [...container.querySelectorAll('dt')].map((node) => node.textContent);
    expect(labels).toEqual(['标的', '方向', '数量', '价格', '委托类型']);
    const values = [...container.querySelectorAll('dd')].map((node) => node.textContent);
    expect(values).toEqual(['600519.SH', '买入', '100', '—', '市价']);
  });

  it('collapses arrays and objects into JSON text', () => {
    const { container } = render(
      <ApprovalCard
        approval={approval({ rawInput: { tags: ['a', 'b'], extra: { x: 1 } } })}
        onDecide={async () => undefined}
      />
    );
    const values = [...container.querySelectorAll('dd')].map((node) => node.textContent);
    expect(values).toContain('["a","b"]');
    expect(values).toContain('{"x":1}');
  });

  it('sends allow/reject decisions and disables both buttons while in flight', async () => {
    let resolve: () => void = () => undefined;
    const onDecide = vi.fn(
      () =>
        new Promise<void>((settle) => {
          resolve = settle;
        })
    );
    render(<ApprovalCard approval={approval()} onDecide={onDecide} />);
    const allow = screen.getByRole('button', { name: '允许这一次' });
    const reject = screen.getByRole('button', { name: '拒绝' });

    fireEvent.click(allow);
    expect(onDecide).toHaveBeenCalledWith('approval-1', 'allow');
    expect((allow as HTMLButtonElement).disabled).toBe(true);
    expect((reject as HTMLButtonElement).disabled).toBe(true);
    resolve();
    await waitFor(() => expect((allow as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(reject);
    expect(onDecide).toHaveBeenLastCalledWith('approval-1', 'reject');
  });

  it('becomes a read-only status row once decided', () => {
    render(
      <ApprovalCard
        approval={approval({ decision: 'allow', decidedAt: '2026-11-16T10:05:00.000Z', decidedBy: 'user' })}
        onDecide={async () => undefined}
      />
    );
    expect(screen.queryByRole('button', { name: '允许这一次' })).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('已允许');
    expect(screen.getByRole('status').textContent).toMatch(/\d{2}:\d{2}/);
  });

  it('labels a timeout rejection and a cancellation', () => {
    const { rerender } = render(
      <ApprovalCard
        approval={approval({ decision: 'reject', decidedAt: '2026-11-16T10:05:00.000Z', decidedBy: 'timeout' })}
        onDecide={async () => undefined}
      />
    );
    expect(screen.getByRole('status').textContent).toContain('超时已拒绝');
    rerender(
      <ApprovalCard
        approval={approval({ decision: 'cancelled', decidedAt: '2026-11-16T10:05:00.000Z', decidedBy: 'system' })}
        onDecide={async () => undefined}
      />
    );
    expect(screen.getByRole('status').textContent).toContain('已取消');
  });

  it('falls back to the raw tool name and parses message meta', () => {
    expect(humanToolName('mcp__paper_broker__paper_place_order')).toBe('模拟盘下单');
    expect(humanToolName('Bash')).toBe('Bash');
    const message: MessageDto = {
      id: 'm-approval',
      botId: 'expert',
      taskId: 't1',
      role: 'system',
      kind: 'approval',
      content: '需要你批准',
      meta: {
        approvalId: 'approval-2',
        title: 'paper_place_order',
        rawInput: { symbol: '600519.SH' },
        sourceBotName: '投资专家',
        delegated: false,
        decision: null,
        decidedAt: null,
        decidedBy: null
      },
      createdAt: '2026-11-16T10:00:00.000Z',
      seq: 1
    };
    expect(approvalFromMessage(message)).toMatchObject({
      id: 'approval-2',
      sourceBotName: '投资专家',
      delegated: false
    });
  });

  it('updates a timeline message when approval.decided arrives', () => {
    const state = {
      ...initialTimelineState,
      status: 'ready' as const,
      botId: 'expert',
      messages: [
        {
          id: 'm-approval',
          botId: 'expert',
          taskId: 't1',
          role: 'system' as const,
          kind: 'approval' as const,
          content: '需要你批准',
          meta: { approvalId: 'approval-1', decision: null },
          createdAt: '2026-11-16T10:00:00.000Z',
          seq: 1
        }
      ]
    };
    const next = timelineReducer(state, {
      type: 'event',
      event: {
        id: 1,
        at: '2026-11-16T10:01:00.000Z',
        type: 'approval.decided',
        botId: 'expert',
        taskId: 't1',
        approval: {
          id: 'approval-1',
          botId: 'expert',
          taskId: 't1',
          rootTaskId: 't1',
          sourceBotId: 'expert',
          sourceBotName: '投资专家',
          rootBotId: 'expert',
          delegated: false,
          toolCallId: 'tool-p',
          title: 'paper_place_order',
          rawInput: null,
          options: [],
          decision: 'reject',
          decidedAt: '2026-11-16T10:01:00.000Z',
          decidedBy: 'user'
        }
      }
    });
    expect(next.messages[0]?.meta).toMatchObject({ decision: 'reject', decidedBy: 'user' });
  });
});
