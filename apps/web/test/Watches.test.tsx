import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MessageDto, NotificationDto } from '@chives/server/protocol';

import { BotList } from '../src/components/BotList';
import { ChatHeader } from '../src/components/ChatHeader';
import { WatchCard, watchFromMessage } from '../src/components/WatchCard';
import { makeBot } from './testUtils';

const notice: NotificationDto = {
  id: 'n1',
  botId: 'expert',
  taskId: 't1',
  title: '柳工放量',
  body: '现价 8.62，量比 2.1，10:31',
  level: 'important',
  createdAt: '2026-11-17T02:31:00.000Z',
  readAt: null
};

function watchMessage(): MessageDto {
  return {
    id: 'm-watch',
    botId: 'expert',
    taskId: 't1',
    role: 'system',
    kind: 'approval',
    content: '盯盘已创建',
    meta: {
      approvalKind: 'watch',
      watchAction: 'created',
      watchId: 'w1',
      code: '000528.SZ',
      label: '柳工回踩',
      conditionText: '柳工 000528.SZ：跌破 7.71 时唤醒投资专家，至 11-22',
      expiresAt: '2026-11-22T02:00:00.000Z',
      status: 'active',
      diff: '',
      repeat: false
    },
    createdAt: '2026-11-17T02:00:00.000Z',
    seq: 1
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('watch UI', () => {
  it('reads and renders a watch card without asking for confirmation', async () => {
    const card = watchFromMessage(watchMessage());
    expect(card?.watchId).toBe('w1');
    const onDelete = vi.fn(async () => undefined);
    render(<WatchCard card={card!} onDelete={onDelete} />);
    expect(screen.getByText(/已创建盯盘：柳工回踩/)).toBeTruthy();
    expect(screen.getByText(/跌破 7.71/)).toBeTruthy();
    expect(screen.getByText(/不会下单/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '启用' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('w1'));
    expect(await screen.findByText('已删除盯盘')).toBeTruthy();
  });

  it('shows "已修改" with the diff', () => {
    const message = watchMessage();
    message.meta = { ...message.meta, watchAction: 'updated', diff: '条件：跌破 7.71 → 站上 8.69' };
    const card = watchFromMessage(message);
    render(<WatchCard card={card!} />);
    expect(screen.getByText(/已修改盯盘/)).toBeTruthy();
    expect(screen.getByText(/站上 8.69/)).toBeTruthy();
  });

  it('marks bots with active watches and unread notifications', () => {
    const bot = makeBot({ id: 'expert', name: '投资专家', watchCount: 2, unreadNotifications: 1 });
    const { container } = render(<BotList bots={[bot]} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('盯盘 2')).toBeTruthy();
    expect(container.querySelector('.bot-row__unread')).not.toBeNull();
    expect(screen.getByRole('button', { name: /2 条盯盘/ })).toBeTruthy();
  });

  it('renders one button per global panel and drops the old watch label', () => {
    const onTogglePanel = vi.fn();
    render(
      <ChatHeader
        onOpenOperator={() => undefined}
        ceo={makeBot({
          id: 'expert',
          name: '投资专家',
          watchCount: 2,
          panels: ['market', 'portfolio', 'watches']
        })}
        runningTask={null}
        bots={[makeBot({watchCount:2})]}
        onTogglePanel={onTogglePanel}
      />
    );
    expect(screen.queryByText('盯盘 2')).toBeNull();
    expect(screen.queryByRole('button', { name: '盯盘 2 条' })).toBeNull();
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((button) => button.getAttribute('aria-label'))).toEqual([
      '与投资专家对话',
      '通知',
      '全局搜索',
      '盯盘',
      '持仓',
      '行情'
    ]);
    fireEvent.click(screen.getByRole('button', { name: '盯盘' }));
    expect(onTogglePanel).toHaveBeenCalledWith('watches');
  });

  it('hides the watch badge when the count is zero', () => {
    render(
      <ChatHeader
        onOpenOperator={() => undefined}
        ceo={makeBot({ id: 'expert', name: '投资专家', panels: ['watches'], watchCount: 0 })}
        runningTask={null}
      />
    );
    expect(screen.getByRole('button', { name: '盯盘' }).textContent).toBe('');
  });

  it('shows the unread bell and the notification list', () => {
    render(
      <ChatHeader
        onOpenOperator={() => undefined}
        ceo={makeBot({ id: 'expert', name: '投资专家' })}
        runningTask={null}
        notifications={[notice]}
        unreadCount={1}
      />
    );
    expect(screen.getByRole('button', { name: /1 条未读/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /1 条未读/ }));
    expect(screen.getByText(/柳工放量/)).toBeTruthy();
    expect(screen.getByText(/现价 8.62/)).toBeTruthy();
  });
});
